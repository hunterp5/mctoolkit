# This file is part of MolManager.
# Copyright (C) 2026 Hunter Picard
#
# MolManager is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# MolManager is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""QProcess host for Gnina dock: launch, logs, validation, and minimize phases."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from PyQt5.QtCore import QObject, QProcess, QProcessEnvironment, QTimer

from ..platform_support.bundled_paths import gnina_launch_env
from ..docking.pose_file_io import (
    is_sdf_path,
    mols_from_dock_output,
    stamp_pose_ff_energies,
    write_pose_mols_sdf,
)
from ..docking.redock_validation import (
    crystal_ref_label,
    existing_crystal_ligand_path,
    load_crystal_mol,
    prepare_crystal_ligand,
    stamp_crystal_ref,
    stamp_crystal_rmsd,
)
from ..docking import gnina_job
from ..docking.gnina_launch import gnina_exit_127_message, gnina_qprocess_spec, gnina_uses_wsl

logger = logging.getLogger(__name__)


def system_stamp(text: str) -> str:
    """Timestamped ``[system]`` line for the Protein Viewer log."""
    stamp = time.strftime("%H:%M:%S")
    return f"[{stamp}][system] {text}"


def start_gnina_qprocess(
    proc: QProcess,
    exe: str,
    launch: list[str],
    *,
    work_dir: str = "",
) -> None:
    """Start Gnina on *proc* (WSL login shell on Windows, native elsewhere)."""
    wd = (work_dir or "").strip()
    if gnina_uses_wsl():
        program, args = gnina_qprocess_spec(exe, launch, work_dir=wd)
        proc.start(program, args)
        return
    env = QProcessEnvironment.systemEnvironment()
    exe_dir = str(Path(exe).parent)
    path = env.value("PATH") or ""
    if exe_dir and exe_dir not in path.split(os.pathsep):
        env.insert("PATH", exe_dir + os.pathsep + path)
    for key, value in gnina_launch_env(exe).items():
        env.insert(key, value)
    proc.setProcessEnvironment(env)
    if wd:
        proc.setWorkingDirectory(str(Path(wd)))
    proc.start(exe, launch)


class GninaDockWorker(QObject):
    """Owns the Gnina ``QProcess`` and dock → validate → minimize sequencing.

    Widget state stays on the dialog (*host*). This object starts the binary,
    streams logs, and runs pose I/O after each phase.
    """

    def __init__(self, host) -> None:
        super().__init__(host)
        self._host = host
        self._stop_requested = False
        self._discard_finish = False
        self.proc = QProcess(self)
        self.proc.finished.connect(self.on_proc_finished)
        self.proc.readyReadStandardOutput.connect(self.append_stdout)
        self.proc.readyReadStandardError.connect(self.append_stderr)
        self.proc.started.connect(self.on_proc_started)
        self.proc.errorOccurred.connect(self.on_proc_error)

    def is_running(self) -> bool:
        return self.proc.state() != QProcess.NotRunning

    def start_process(self, launch: list[str]) -> None:
        self._stop_requested = False
        self._discard_finish = False
        h = self._host
        h._dismiss_for_run()
        exe = h._resolved_exe or h._gnina_executable()
        start_gnina_qprocess(self.proc, exe, launch, work_dir=h.edit_wd.text())

    def stop(self) -> None:
        h = self._host
        self._stop_requested = True
        h._batch_cancelled = True
        if not self.is_running():
            self._finish_stopped()
            return
        h.log.append(system_stamp("Stopping…"))
        # Windows console and WSL launchers ignore WM_CLOSE, so terminate() never exits.
        if sys.platform == "win32":
            self._kill_process_tree()
        else:
            try:
                self.proc.terminate()
            except Exception:
                pass
        QTimer.singleShot(2500, self.kill_if_running)

    def kill_if_running(self) -> None:
        if not self._stop_requested:
            return
        if self.is_running():
            self._kill_process_tree()
            QTimer.singleShot(1500, self._abandon_if_still_running)
            return
        self._finish_stopped()

    def _abandon_if_still_running(self) -> None:
        """Release the dock UI if Gnina still has not exited after a force kill."""
        if not self._stop_requested:
            return
        if not self.is_running():
            self._finish_stopped()
            return
        h = self._host
        h.log.append(system_stamp("Gnina did not exit; the dock was stopped anyway."))
        self._discard_finish = True
        self._stop_requested = False
        h._clear_batch()
        h._set_running_ui(False)
        h._notify_activity()

    def _kill_process_tree(self) -> None:
        """Force-stop Gnina, including a copy left running inside WSL."""
        pid = 0
        try:
            pid = int(self.proc.processId() or 0)
        except (TypeError, ValueError):
            pid = 0
        if sys.platform == "win32" and pid > 0:
            try:
                subprocess.Popen(
                    ["taskkill", "/F", "/T", "/PID", str(pid)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                logger.debug("taskkill gnina failed", exc_info=True)
            if gnina_uses_wsl():
                try:
                    from ..platform_support.wsl_launcher import wsl_argv

                    subprocess.Popen(
                        wsl_argv(["bash", "-lc", "pkill -x gnina || true"]),
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    logger.debug("could not ask WSL to stop gnina", exc_info=True)
        try:
            if self.is_running():
                self.proc.kill()
        except Exception:
            logger.debug("QProcess.kill failed", exc_info=True)

    def _finish_stopped(self) -> None:
        """Clear the running UI after Stop, including when Gnina has already exited."""
        if not self._stop_requested:
            return
        self._stop_requested = False
        h = self._host
        if h._minimize_ins:
            self.finish_minimize_keep_placement()
        else:
            h._clear_batch()
        h._set_running_ui(False)
        h._notify_activity()
        h.log.append(system_stamp("Stopped."))

    def on_proc_started(self) -> None:
        h = self._host
        h._set_running_ui(True)
        if not h._minimize_ins:
            h._stdout_buf = ""
            h._stderr_buf = ""
        pid = self.proc.processId()
        n_min = h._minimize_n_poses or len(h._minimize_ins)
        n_lig = len(h._batch_ligands)
        if h._validation_phase:
            h.log.append(
                system_stamp(f"Gnina started (PID {pid}) internal validation (crystal redock).")
            )
        elif n_min:
            h.log.append(system_stamp(f"Gnina started (PID {pid}) minimizing {n_min} pose(s)."))
        elif n_lig > 1:
            h.log.append(system_stamp(f"Gnina started (PID {pid}) docking {n_lig} ligands."))
        else:
            h.log.append(system_stamp(f"Gnina started (PID {pid})."))
        if (not h._minimize_ins) and h._flex_mode() != "off":
            h.log.append(
                system_stamp(
                    "Flexible side chains on (backbone rigid). "
                    f"Writing {gnina_job.flex_out_path(h._effective_out_path())}."
                )
            )
        h._notify_activity()

    def on_proc_error(self, error: QProcess.ProcessError) -> None:
        if error != QProcess.FailedToStart:
            return
        h = self._host
        detail = (self.proc.errorString() or "").strip() or "Gnina failed to start."
        h.log.append(system_stamp(detail))
        h._reveal_dock_dialog()
        if h._minimize_ins:
            self.finish_minimize_keep_placement()
        else:
            h._validation_phase = False
            h._pending_user_ligand = None
            h._clear_batch()
        h._set_running_ui(False)
        h._notify_activity()

    def append_stdout(self) -> None:
        h = self._host
        text = bytes(self.proc.readAllStandardOutput()).decode("utf-8", errors="replace")
        h._stdout_buf += text
        if text:
            h.log.append(text.rstrip("\n"))

    def append_stderr(self) -> None:
        h = self._host
        text = bytes(self.proc.readAllStandardError()).decode("utf-8", errors="replace")
        h._stderr_buf += text
        if text:
            h.log.append(text.rstrip("\n"))

    def write_sidecar_sdf(self, pdbqt_out: str) -> None:
        h = self._host
        _path, msg = gnina_job.write_sidecar_sdf(pdbqt_out, h._ligand_template_mol())
        if msg:
            h.log.append(system_stamp(msg))

    def write_final_sdf(self, pdbqt_out: str) -> None:
        if self._host.save_sdf_cb.isChecked():
            self.write_sidecar_sdf(pdbqt_out)

    def restore_sdf_bonds(self, sdf_path: str) -> None:
        h = self._host
        msg = gnina_job.restore_sdf_bonds(sdf_path, h._ligand_template_mols())
        if msg:
            h.log.append(system_stamp(msg))

    def present_dock_results(self, out_path: str) -> None:
        """Load finished poses (all Gnina fields) into the pose browser."""
        h = self._host
        path = str(h._resolve_path(out_path))
        templates = h._ligand_template_mols()
        template = templates[0] if templates else None
        if h._stamp_crystal_on_poses and h._crystal_ref_mol is not None:
            template = h._crystal_ref_mol
        log = f"{h._stdout_buf or ''}\n{h._stderr_buf or ''}"
        try:
            mols = mols_from_dock_output(path, template=template, log_text=log)
        except Exception as exc:
            h.log.append(system_stamp(f"Could not load dock results: {exc}"))
            return
        if h._stamp_crystal_on_poses and h._crystal_ref_mol is not None:
            top = stamp_crystal_rmsd(mols, h._crystal_ref_mol)
            if top is not None:
                h._crystal_rmsd = top
                h.log.append(
                    system_stamp(f"Internal validation: top pose crystal RMSD = {top:.3f} Å.")
                )
        if h._stamp_crystal_on_poses:
            ref_path = (h._validation_ligand_path or "").strip()
            if h._crystal_ref_mol is not None or ref_path:
                stamp_crystal_ref(mols, crystal_ref_label(h._crystal_ref_mol, ref_path))
        stamp_pose_ff_energies(mols)
        mols = h._apply_pharmacophore_filter(mols)
        if is_sdf_path(path) and mols:
            try:
                write_pose_mols_sdf(mols, path)
            except Exception:
                pass
        extra = [m for m in (h._validation_pose_mols or []) if m is not None]
        if extra and not h._stamp_crystal_on_poses:
            extra = h._apply_pharmacophore_filter(extra, log=False)
            mols = extra + list(mols)
        opener = getattr(h._main_window, "open_dock_results_window", None)
        if not callable(opener) or not mols:
            return
        rec = h._receptor_for_gnina() or (h.edit_receptor.text() or "").strip()
        writer = getattr(h._main_window, "write_dock_poses_to_table", None)
        if callable(writer):
            try:
                col = writer(mols)
            except Exception:
                col = None
            if col:
                h.log.append(system_stamp(f"Wrote packed poses to “{col}”."))
        title = f"Pose browser — {Path(path).name}"
        if h._crystal_rmsd is not None:
            title += f"  (crystal RMSD {h._crystal_rmsd:.3f} Å)"
        crystal = existing_crystal_ligand_path(
            h._crystal_ligand_path
        ) or existing_crystal_ligand_path(h._validation_ligand_path)
        opener(mols, title=title, receptor_path=rec or None, crystal_path=crystal or None)
        h.log.append(system_stamp(f"Opened {len(mols)} pose(s) in the pose browser."))

    def after_successful_dock(self, placement_path: str) -> None:
        h = self._host
        self.restore_sdf_bonds(placement_path)
        self.log_flex_output(placement_path)
        if h.minimize_poses_cb.isChecked() and self.start_minimize_phase(placement_path):
            return
        self.write_final_sdf(placement_path)
        self.present_dock_results(placement_path)
        h._clear_batch()
        h._set_running_ui(False)
        h._notify_activity()

    def log_flex_output(self, pose_path: str) -> None:
        h = self._host
        if h._flex_mode() == "off":
            return
        dest = Path(gnina_job.flex_out_path(str(h._resolve_path(pose_path))))
        if dest.is_file():
            h.log.append(system_stamp(f"Flexible residues: {dest}."))
        else:
            h.log.append(system_stamp(f"Flexible-residue output was not written ({dest})."))

    def start_minimize_phase(self, placement_path: str) -> bool:
        h = self._host
        tmp = h._ensure_batch_tmp("gnina_min_")
        ins, min_out, n_poses = gnina_job.prepare_minimize_inputs(placement_path, tmp)
        if n_poses < 1:
            return False
        h._placement_out = placement_path
        h._minimize_ins = ins
        h._minimize_out = min_out
        h._minimize_n_poses = n_poses
        if is_sdf_path(placement_path):
            h.log.append(
                system_stamp(f"Minimizing {n_poses} docked pose(s) from SDF in one Gnina process.")
            )
        else:
            h.log.append(system_stamp(f"Minimizing {n_poses} docked pose(s) in one Gnina process."))
        self.start_minimize_job()
        return True

    def start_minimize_job(self) -> None:
        h = self._host
        min_out = h._minimize_out
        if min_out is None:
            return
        argv = h._build_minimize_argv([str(p) for p in h._minimize_ins], str(min_out))
        n = h._minimize_n_poses or len(h._minimize_ins)
        launch = h._launch_argv(argv)
        h.log.append(system_stamp(f"Minimize ({n} pose(s)): {h._resolved_exe} {' '.join(launch)}"))
        h._notify_activity()
        self.start_process(launch)

    def finish_minimize_keep_placement(self) -> None:
        h = self._host
        dest = (h._placement_out or (h.edit_out.text() or "").strip()).strip()
        h.log.append(system_stamp("Pose minimization stopped; keeping placement poses."))
        if dest:
            self.write_final_sdf(dest)
            self.present_dock_results(dest)
        h._clear_batch()

    def write_combined_minimize(self) -> None:
        h = self._host
        dest = (h._placement_out or "").strip()
        min_path = h._minimize_out
        if not dest or min_path is None:
            return
        logs = gnina_job.write_combined_minimize_results(dest, min_path, h._ligand_template_mols())
        for msg in logs:
            h.log.append(system_stamp(msg))
        if not is_sdf_path(dest):
            self.write_final_sdf(dest)

    def on_validation_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        h = self._host
        h._validation_phase = False
        failed = code != 0 or status == QProcess.CrashExit or h._batch_cancelled
        h.log.append(system_stamp(f"Gnina finished internal validation (exit code {code})."))
        if h._batch_cancelled:
            h._clear_batch()
            h._set_running_ui(False)
            h._notify_activity()
            return
        if failed:
            h.log.append(system_stamp("Internal validation failed; continuing with docking."))
        else:
            self.record_crystal_validation_rmsd()
        pending = h._pending_user_ligand
        pending_out = (h._pending_user_out or "").strip()
        h._pending_user_ligand = None
        h._pending_user_out = ""
        if pending is None:
            out = (h._validation_out or h._effective_out_path() or "").strip()
            if not failed and out:
                h._stamp_crystal_on_poses = True
                self.after_successful_dock(out)
                return
            h._clear_batch()
            h._set_running_ui(False)
            h._notify_activity()
            return
        try:
            argv = h._build_argv(ligand=pending, out=pending_out)
        except Exception as exc:
            h.log.append(system_stamp(f"Could not start docking after validation: {exc}"))
            h._clear_batch()
            h._set_running_ui(False)
            h._notify_activity()
            return
        launch = h._launch_argv(argv)
        h.log.append(system_stamp(f"Launch: {h._resolved_exe} {' '.join(launch)}"))
        h._notify_activity()
        self.start_process(launch)

    def record_crystal_validation_rmsd(self) -> None:
        h = self._host
        path = (h._validation_out or "").strip()
        crystal = h._crystal_ref_mol
        if not path or crystal is None:
            return
        try:
            mols = mols_from_dock_output(path, template=crystal)
        except Exception as exc:
            h.log.append(system_stamp(f"Could not read validation poses: {exc}"))
            return
        top = stamp_crystal_rmsd(mols, crystal)
        stamp_crystal_ref(mols, crystal_ref_label(crystal, h._validation_ligand_path or path))
        stamp_pose_ff_energies(mols)
        h._validation_pose_mols = [m for m in mols if m is not None]
        if top is None:
            h.log.append(
                system_stamp("Internal validation finished; could not compute crystal RMSD.")
            )
            return
        h._crystal_rmsd = top
        h.log.append(system_stamp(f"Internal validation: top pose crystal RMSD = {top:.3f} Å."))

    def on_proc_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        try:
            self._on_proc_finished(code, status)
        except Exception:
            logger.exception("Gnina finish handler failed")
            h = self._host
            h.log.append(system_stamp("Gnina finished, but the results could not be read."))
            self._stop_requested = False
            h._clear_batch()
            h._set_running_ui(False)
            h._notify_activity()

    def _on_proc_finished(self, code: int, status: QProcess.ExitStatus) -> None:
        h = self._host
        if self._discard_finish:
            self._discard_finish = False
            self._stop_requested = False
            return
        if self._stop_requested or h._batch_cancelled:
            self._finish_stopped()
            return
        if h._validation_phase:
            self.on_validation_finished(code, status)
            return
        if h._minimize_ins:
            n = h._minimize_n_poses or len(h._minimize_ins)
            h.log.append(
                system_stamp(f"Gnina finished minimize of {n} pose(s) (exit code {code}).")
            )
            if h._batch_cancelled:
                self.finish_minimize_keep_placement()
                h._set_running_ui(False)
                h._notify_activity()
                return
            if code != 0 or status == QProcess.CrashExit:
                h.log.append(system_stamp("Minimize failed; keeping the placement poses."))
                self.finish_minimize_keep_placement()
                h._set_running_ui(False)
                h._notify_activity()
                return
            try:
                self.write_combined_minimize()
            except Exception as exc:
                h.log.append(system_stamp(f"Could not combine minimized poses: {exc}"))
                self.finish_minimize_keep_placement()
            else:
                dest = (h._placement_out or h._effective_out_path() or "").strip()
                if dest:
                    self.present_dock_results(dest)
                h._clear_batch()
            h._set_running_ui(False)
            h._notify_activity()
            return

        h.log.append(system_stamp(f"Gnina finished (exit code {code})."))
        if int(code) == 127:
            h.log.append(system_stamp(gnina_exit_127_message(h._resolved_exe, h._stderr_buf)))
        failed = code != 0 or status == QProcess.CrashExit or h._batch_cancelled
        out = h._effective_out_path()
        if not failed and out:
            self.after_successful_dock(out)
            return
        h._clear_batch()
        h._set_running_ui(False)
        h._notify_activity()

    def setup_crystal_validation(
        self,
        rec: str,
        *,
        durable_dir: Path | None = None,
        validate: bool = True,
    ) -> None:
        h = self._host
        dest = h._ensure_validation_tmp()
        rec_path = str(h._resolve_path(rec)) if rec else rec
        sidecar = (
            gnina_job.sidecar_for_receptor(
                rec,
                sidecar=h._crystal_ligand_path,
                prepare_receptor=h._prepare_receptor_path,
                work_dir=h.edit_wd.text(),
            )
            if validate
            else ""
        )
        prep = prepare_crystal_ligand(rec_path, dest, crystal_ligand_path=sidecar)
        h._validation_ligand_path = ""
        if prep is None:
            return
        h._apo_receptor_path = prep.apo_receptor_path
        if prep.stripped_from_receptor and durable_dir is not None:
            h._apo_receptor_path = gnina_job.durable_apo_receptor(
                prep.apo_receptor_path, durable_dir
            )
        if not validate:
            if prep.stripped_from_receptor:
                h.log.append(system_stamp("Receptor ligand stripped for apo docking."))
            return
        h._validation_ligand_path = prep.crystal_ligand_path
        h._crystal_ref_mol = load_crystal_mol(prep.crystal_ligand_path)
        if prep.stripped_from_receptor:
            h.log.append(
                system_stamp(
                    "Internal validation: ligand found in the receptor; docking into an apo copy."
                )
            )
        else:
            h.log.append(
                system_stamp(
                    "Internal validation: redocking crystal ligand "
                    f"{Path(prep.crystal_ligand_path).name}."
                )
            )

    def prepare_file_ligands(self, ligand: str) -> list[Path]:
        h = self._host
        if not (ligand or "").strip():
            raise ValueError("Choose a ligand file (PDBQT or SDF).")
        from ..docking.pose_file_io import ligand_is_openbabel_format

        lig_path = h._resolve_path(ligand)
        if ligand_is_openbabel_format(lig_path):
            return [lig_path]
        h._clear_batch()
        tmp = h._ensure_batch_tmp("gnina_ligands_")
        paths, batch = gnina_job.prepare_file_ligands(lig_path, tmp)
        h._batch_cancelled = False
        h._batch_ligands = list(batch)
        return paths
