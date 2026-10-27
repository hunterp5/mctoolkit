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

"""Run a simulation document off the GUI thread."""

from __future__ import annotations

import json
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from ..platform_support.sleep_guard import SleepGuard
from ..platform_support.tool_progress import report_tool_progress
from ..sim.document import document_from_json, validate_document
from ..sim.fep import FepUnavailable, execute_star
from ..sim.protocol import SimulationRunError, run_document
from ..sim.selection import atoms_from_structure_text
from ..sim.system_build import SystemBuildError, build_system
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)


class SimulationSignals(QObject):
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)
    scalar = pyqtSignal(str)


def mp_run_simulation(payload: dict) -> tuple[bool, object]:
    """Child-process entry. OpenMM stays out of the GUI process."""
    live = Path(payload.get("live") or "")
    try:
        with SleepGuard():
            document = document_from_json(payload["document"])
            issues = validate_document(document)
            if issues:
                return False, "\n".join(issues)
            if document.run.kind == "alchemical":
                rows = execute_star(
                    document.run,
                    receptor_path=payload.get("structure_path") or "",
                    ligand_paths=payload.get("ligand_paths") or {},
                    reference_id=payload.get("reference_id") or "",
                    charges=payload.get("charges") or {},
                    output_dir=payload["output_dir"],
                )
                return True, {"kind": "alchemical", "rows": rows}
            work = Path(payload["output_dir"]) / "work"
            work.mkdir(parents=True, exist_ok=True)
            structure_path, ligand_mols, ligand_keys = _prepare_structure(payload, document, work)
            built = build_system(
                document,
                structure_path=structure_path,
                work_dir=work,
                ligand_mols=ligand_mols,
                ligand_keys=ligand_keys,
            )
            text = Path(structure_path).read_text(encoding="utf-8", errors="replace")
            atoms = atoms_from_structure_text(text, payload.get("fmt") or "pdb")

            def _on_scalar(row: dict) -> None:
                if not live:
                    return
                with live.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(row) + "\n")

            pause_file = Path(payload.get("pause_file") or "")
            manifest = run_document(
                document,
                topology=built.topology,
                system=built.system,
                positions=built.positions,
                box=built.box,
                output_dir=payload["output_dir"],
                atoms=atoms,
                platform=document.run.platform,
                precision=document.run.precision,
                device_index=document.run.device_index,
                seed=int(payload.get("seed") or document.run.seeds[0]),
                resume_state=payload.get("resume_state") or "",
                resume_checkpoint=payload.get("resume_checkpoint") or "",
                completed=set(payload.get("completed") or []),
                solute_atoms=built.solute_atoms,
                on_scalar=_on_scalar,
                should_pause=lambda: pause_file.is_file(),
            )
            return True, manifest.to_dict()
    except (
        SimulationRunError,
        SystemBuildError,
        FepUnavailable,
        OSError,
        ValueError,
        RuntimeError,
    ) as exc:
        return False, str(exc)


def _prepare_structure(payload: dict, document, work: Path) -> tuple[str, list | None, set | None]:
    """Bond-order the ligand when the document asks for GAFF or OpenFF."""
    path = str(payload["structure_path"])
    fmt = payload.get("fmt") or "pdb"
    ligand_ff = document.system.ligand_ff
    if ligand_ff not in {"gaff", "gaff2", "openff"}:
        return path, None, None
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    from ..workers.protein_prepare_io import residue_kind_map

    keys = {key for key, kind in residue_kind_map(text, fmt).items() if kind == "ligand"}
    if not keys:
        return path, None, None
    if ligand_ff == "openff":
        from rdkit import Chem

        smiles = document.system.ligand_smiles.strip()
        mol = Chem.MolFromSmiles(smiles) if smiles else None
        if mol is None:
            raise ValueError("OpenFF needs a ligand SMILES template on the system.")
        return path, [mol], keys
    from ..workers.protein_prepare_ligand import prepare_ligands_for_gaff

    mols, prepared = prepare_ligands_for_gaff(
        text,
        keys,
        smiles=document.system.ligand_smiles,
        fmt=fmt,
    )
    prepared_path = work / f"prepared.{fmt if fmt != 'cif' else 'cif'}"
    prepared_path.write_text(prepared, encoding="utf-8", newline="\n")
    return str(prepared_path), mols, keys


class SimulationWorker(QRunnable):
    """One simulation in a process pool. Scalars are tailed from *live_path*."""

    def __init__(
        self,
        payload: dict,
        *,
        signals: SimulationSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        n_stages: int = 1,
    ) -> None:
        super().__init__()
        self.payload = payload
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.n_stages = max(1, n_stages)
        self._seen_lines = 0

    def run(self) -> None:
        cancel_ev = self.cancel_event
        try:
            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return
            ex = register_process_pool(ProcessPoolExecutor(max_workers=1))
            try:
                future = ex.submit(mp_run_simulation, self.payload)
                pending = {future}
                while pending:
                    self._drain_live()
                    if should_terminate_process_pool(cancel_ev):
                        future.cancel()
                        self.signals.failed.emit("Cancelled.")
                        return
                    _done, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                if future.cancelled():
                    self.signals.failed.emit("Cancelled.")
                    return
                ok, result = future.result()
            finally:
                shutdown_process_pool_executor(
                    ex, kill_workers=should_terminate_process_pool(cancel_ev)
                )
            self._drain_live()
            if ok:
                self.signals.finished.emit(result)
            else:
                self.signals.failed.emit(str(result))
        except BrokenExecutor:
            self.signals.failed.emit(
                "Simulation subprocess crashed. On Windows this is often OpenMM 8.3+. "
                "Install openmm>=8.2,<8.3."
            )
        except (OSError, RuntimeError, ValueError) as exc:
            self.signals.failed.emit(str(exc) or "Simulation failed.")

    def _drain_live(self) -> None:
        path = Path(self.payload.get("live") or "")
        if not path.is_file():
            return
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        fresh = lines[self._seen_lines :]
        self._seen_lines = len(lines)
        for line in fresh:
            self.signals.scalar.emit(line)
        if fresh:
            report_tool_progress(
                message=fresh[-1][:180],
                done=min(self._seen_lines, self.n_stages),
                total=self.n_stages,
                progress_state=self.progress_state,
            )
