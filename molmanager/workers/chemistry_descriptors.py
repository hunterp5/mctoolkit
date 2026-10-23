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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.
"""Descriptor calculation workers (CalcWorker and helpers).

Fingerprint columns use RDKit implementations. The **2D pharmacophore (Gobbi)** column uses
``rdkit.Chem.Pharm2D`` with ``Gobbi_Pharm2D`` (Gobbi & Poppinger, *Perspect. Drug Discov. Des.* 1998).
Drug-likeness columns that invoke ``medchem_descriptors`` / Uni-pKa cite
``molmanager.reference.method_citations`` and the worker module docstrings there.
"""

import logging
import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass

from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit.Chem import Descriptors, QED, rdMolDescriptors

try:
    from rdkit.Chem.Pharm2D import Generate as Pharm2DGenerate
    from rdkit.Chem.Pharm2D import Gobbi_Pharm2D
except ImportError:  # pragma: no cover - very old RDKit builds
    Pharm2DGenerate = None  # type: ignore[misc, assignment]
else:

    def _pharm2d_gobbi_onbits(mol: Chem.Mol) -> int:
        fp = Pharm2DGenerate.Gen2DFingerprint(mol, Gobbi_Pharm2D.factory)
        if hasattr(fp, "GetNumOnBits"):
            return int(fp.GetNumOnBits())
        return int(sum(fp))


from ..platform_support.config import load_config
from ..descriptors.descriptors_3d import DESCRIPTOR_3D_FNS, int_fns_need_3d, mol_for_3d_descriptors
from ..descriptors.medchem_descriptors import (
    ab_mps_score,
    bbb_score,
    cns_mpo_score,
    esol_logS_intrinsic,
    lipinski_violations,
    logd74_value,
    logs74_value,
    mol_formula,
    mol_inchi_key,
    mol_net_formal_charge,
    ro5_pass,
)
from ..ionization.unipka_ensembles import int_fns_need_ionization, microstates_for_mol
from .ionization_parallel import build_microstates_cache_for_rows
from ..chem.molecule_conversion import (
    mol_from_tool_input,
    mol_to_canonical_smiles,
    parse_molecule_from_cell_text,
)
from ..chem.rdkit_fingerprints import (
    fingerprint_onbits_for_descriptor,
    fingerprint_onbits_for_internal_key,
    int_fns_include_fingerprints,
    spec_for_internal_key,
)
from .signals import emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)


def _descriptor_int_fns_include_pharm2d(int_fns) -> bool:
    """2D pharmacophore (Gobbi) is much slower than other descriptor columns — tune parallelism."""
    return any(isinstance(f, str) and f.startswith("FP_Pharm2D") for f in int_fns)


def _descriptor_process_pool_min_rows(cfg, int_fns) -> int:
    """Row-count threshold for child-process descriptor calculation."""
    if _descriptor_int_fns_include_pharm2d(int_fns):
        return 2
    if int_fns_include_fingerprints(int_fns):
        return int(cfg.descriptor_fp_process_pool_min_rows)
    return int(cfg.descriptor_process_pool_min_rows)


def _descriptor_output_headers(disp_headers: list, pka_cache_used: bool) -> list[str]:
    headers = list(disp_headers)
    if pka_cache_used and "pKa" not in headers:
        headers.append("pKa")
    return headers


def _mol_from_binary(blob) -> Chem.Mol | None:
    if not blob:
        return None
    try:
        return Chem.Mol(blob)
    except Exception:
        return None


def _unpack_mp_row_item(item) -> tuple[int, object, object, object]:
    """``(idx, mol_bytes, pka_states[, mol3_bytes])`` from a process-pool batch row."""
    idx = item[0]
    mol_bytes = item[1]
    pka_states = item[2]
    mol3_bytes = item[3] if len(item) > 3 else b""
    return int(idx), mol_bytes, pka_states, mol3_bytes


def _calc_descriptor_row_values(
    idx: int,
    mol: Chem.Mol | None,
    disp_headers: list,
    int_fns: tuple,
    smarts_cache: dict,
    *,
    pka_states,
    pka_cache_used: bool,
    mol_3d: Chem.Mol | None = None,
    packed_confs: str | None = None,
) -> tuple[int, dict[str, str]]:
    row_ctx: dict = {"oid": int(idx)}
    if mol_3d is None and int_fns_need_3d(int_fns):
        mol_3d = mol_for_3d_descriptors(mol, packed_cell=packed_confs)
    row_ctx["mol_3d"] = mol_3d
    if mol is not None and int_fns_need_ionization(int_fns):
        if pka_cache_used:
            row_ctx["ionization_states"] = pka_states
        else:
            row_ctx["ionization_states"] = microstates_for_mol(mol)
    callables = [descriptor_callable_for_int_fn(i_f, smarts_cache, row_ctx) for i_f in int_fns]
    row_data: dict[str, str] = {}
    if mol is None and mol_3d is None:
        for d_n in disp_headers:
            row_data[d_n] = "N/A"
    else:
        for d_n, fn in zip(disp_headers, callables):
            try:
                v = fn(mol)
                row_data[d_n] = f"{v:.3f}" if isinstance(v, float) else str(v)
            except Exception:
                row_data[d_n] = "N/A"
    if pka_cache_used:
        from molmanager.ionization.unipka_ensembles import format_pka_values, pka_values_from_states

        row_data["pKa"] = format_pka_values(pka_values_from_states(pka_states))
    return int(idx), row_data


def descriptor_callable_for_int_fn(i_f, smarts_cache, row_ctx=None):
    """Return ``callable(mol)`` for one internal descriptor id (shared by thread and process workers)."""
    ctx = row_ctx if row_ctx is not None else {}
    row_oid = ctx.get("oid")
    if isinstance(i_f, str) and i_f.startswith("ALERT:"):
        from ..chem.structural_alerts import callable_for_alert_key

        return callable_for_alert_key(i_f, ctx)
    if isinstance(i_f, str) and i_f.startswith("MURCKO_"):
        from ..chem.murcko import murcko_callable_for_key

        return murcko_callable_for_key(i_f)
    if i_f == "SMILES":
        return lambda m: mol_to_canonical_smiles(m) if m is not None else ""
    if i_f == "INCHIKEY":
        return lambda m: mol_inchi_key(m) if m is not None else ""
    if i_f == "MOLFORMULA":
        return lambda m: mol_formula(m) if m is not None else ""
    if i_f == "RO5_VIOLATIONS":
        return lambda m: lipinski_violations(m) if m is not None else 0
    if i_f == "RO5_PASS":
        return lambda m: ro5_pass(m) if m is not None else "No"
    if i_f == "LOGD74":
        return lambda m: logd74_value(m, ctx.get("ionization_states"))
    if i_f == "LOGS_ESOL":
        return lambda m: esol_logS_intrinsic(m) if m is not None else 0.0
    if i_f == "LOGS74":
        return lambda m: logs74_value(m, ctx.get("ionization_states"))
    if i_f == "AB_MPS":
        return lambda m: ab_mps_score(m, ctx.get("ionization_states")) if m is not None else 0.0
    if i_f == "BBB_SCORE":
        return lambda m: bbb_score(m, ctx.get("ionization_states")) if m is not None else 0.0
    if i_f == "CNS_MPO":
        return lambda m: cns_mpo_score(m, ctx.get("ionization_states")) if m is not None else 0.0
    if i_f == "QED":
        return lambda m: QED.qed(m)
    if i_f in DESCRIPTOR_3D_FNS:
        fn3 = DESCRIPTOR_3D_FNS[i_f]

        def _calc_3d(_m, f=fn3, c=ctx):
            work = c.get("mol_3d")
            if work is None:
                raise ValueError("no 3d coordinates")
            return f(work)

        return _calc_3d
    if i_f == "NET_FORMAL_CHARGE":
        return lambda m: mol_net_formal_charge(m) if m is not None else 0
    if i_f.startswith("Count_"):
        atom = i_f.split("_", 1)[1]
        s = Chem.MolFromSmarts(f"[{atom}]")
        smarts_cache[i_f] = s
        return lambda m, s=s: len(m.GetSubstructMatches(s))
    func = getattr(Descriptors, i_f, None)
    if func:
        return lambda m, f=func: f(m)
    func = getattr(rdMolDescriptors, i_f, None)
    if func:
        return lambda m, f=func: f(m)
    func = getattr(Chem, i_f, None)
    if func:
        return lambda m, f=func: f(m)
    if isinstance(i_f, str) and i_f.startswith("FP_"):
        if spec_for_internal_key(i_f) is not None:
            if row_oid is not None:
                return fingerprint_onbits_for_descriptor(i_f, int(row_oid))
            return fingerprint_onbits_for_internal_key(i_f)
    return lambda m: "N/A"


def _mp_calc_descriptor_row(args: tuple):
    """One row in a child process — avoids GIL contention with the Qt GUI thread."""
    idx, mol_bytes, disp_headers, int_fns, pka_states, pka_cache_used = args[:6]
    mol3_bytes = args[6] if len(args) > 6 else b""
    return _calc_descriptor_row_values(
        idx,
        _mol_from_binary(mol_bytes),
        list(disp_headers),
        tuple(int_fns),
        {},
        pka_states=pka_states,
        pka_cache_used=bool(pka_cache_used),
        mol_3d=_mol_from_binary(mol3_bytes),
    )


def _mp_calc_descriptor_batch(args: tuple) -> list[tuple[int, dict[str, str]]]:
    """Several rows per child process — less IPC overhead on large fingerprint jobs."""
    items, disp_headers, int_fns, pka_cache_used = args
    smarts_cache: dict = {}
    out: list[tuple[int, dict[str, str]]] = []
    headers = list(disp_headers)
    fns = tuple(int_fns)
    for item in items:
        idx, mol_bytes, pka_states, mol3_bytes = _unpack_mp_row_item(item)
        out.append(
            _calc_descriptor_row_values(
                idx,
                _mol_from_binary(mol_bytes),
                headers,
                fns,
                smarts_cache,
                pka_states=pka_states,
                pka_cache_used=bool(pka_cache_used),
                mol_3d=_mol_from_binary(mol3_bytes),
            )
        )
    return out


def _descriptor_progress_emit_step(total: int) -> int:
    """Fewer cross-thread progress signals on very large tables."""
    tot = max(1, int(total))
    if tot >= 100_000:
        return max(1, tot // 200)
    if tot >= 10_000:
        return max(1, tot // 80)
    return max(1, tot // 40)


def _run_descriptor_process_pool(
    prepared: list,
    *,
    disp_headers: list,
    int_fns: tuple,
    pka_by_idx: dict,
    pka_cache_used: bool,
    max_workers: int,
    batch_size: int,
    cancel_event: threading.Event | None,
    emit_progress,
    mol3_by_idx: dict | None = None,
) -> tuple[list, bool]:
    """
    Run descriptor rows in child processes (keeps the Qt GUI thread off the GIL).

    Returns ``(results, cancelled)``.
    """
    mol3_map = mol3_by_idx or {}
    row_items: list[tuple] = []
    for i, mol in prepared:
        blob = mol.ToBinary() if mol is not None else b""
        pka = pka_by_idx.get(i) if pka_cache_used else None
        mol3 = mol3_map.get(int(i))
        blob3 = mol3.ToBinary() if mol3 is not None else b""
        row_items.append((i, blob, pka, blob3))
    batch_size = max(1, int(batch_size))
    batch_args: list[tuple] = []
    for start in range(0, len(row_items), batch_size):
        chunk = row_items[start : start + batch_size]
        batch_args.append((chunk, tuple(disp_headers), tuple(int_fns), bool(pka_cache_used)))
    from ..platform_support.worker_budget import RDKIT_PROCESS_BYTES, plan_process_workers

    requested = max(1, int(max_workers))
    cpu_cap = min(8, requested, max(2, (os.cpu_count() or 4) - 1))
    proc_workers = plan_process_workers(
        per_worker_bytes=RDKIT_PROCESS_BYTES,
        cpu_cap=max(1, cpu_cap),
        min_workers=1 if requested <= 1 else min(2, max(1, cpu_cap)),
    )
    emit_progress(0, force=True)
    mp_results_dict: dict = {}
    done_count = 0
    cancelled = False
    last_pulse = 0.0
    ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
    try:
        pending = {ex.submit(_mp_calc_descriptor_batch, args) for args in batch_args}
        while pending:
            if should_terminate_process_pool(cancel_event):
                cancelled = True
                for f in list(pending):
                    if f.done() and not f.cancelled():
                        try:
                            for idx, row_d in f.result():
                                mp_results_dict[int(idx)] = row_d
                                done_count += 1
                        except Exception:
                            logger.exception("Process-pool descriptor batch failed")
                    else:
                        f.cancel()
                break
            completed, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            if not completed and pending:
                now = time.monotonic()
                if now - last_pulse >= 0.55:
                    last_pulse = now
                    emit_progress(done_count, force=True)
            for f in completed:
                if f.cancelled():
                    continue
                try:
                    for idx, row_d in f.result():
                        mp_results_dict[int(idx)] = row_d
                        done_count += 1
                    emit_progress(done_count)
                except Exception:
                    logger.exception("Process-pool descriptor batch failed")
    finally:
        shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(cancel_event))
    emit_progress(done_count, force=True)
    results = [(oid, mp_results_dict[oid]) for oid, _ in prepared if oid in mp_results_dict]
    return results, cancelled


def _calc_descriptor_row_task(args):
    """One row for :class:`CalcWorker` parallel path (thread worker)."""
    idx, mol, disp_headers, int_fns, smarts_cache, pka_states, pka_cache_used = args[:7]
    mol_3d = args[7] if len(args) > 7 else None
    if mol is not None:
        try:
            mol = Chem.Mol(mol)
        except Exception:
            mol = None
    if mol_3d is not None:
        try:
            mol_3d = Chem.Mol(mol_3d)
        except Exception:
            mol_3d = None
    return _calc_descriptor_row_values(
        idx,
        mol,
        list(disp_headers),
        tuple(int_fns),
        smarts_cache,
        pka_states=pka_states,
        pka_cache_used=bool(pka_cache_used),
        mol_3d=mol_3d,
    )


@dataclass(frozen=True)
class CalcDescriptorsRequest:
    """Row payloads and selected descriptors for :class:`CalcWorker`."""

    data: list
    disp_headers: list
    int_fns: list
    is_smiles: bool = False
    confs_by_idx: dict | None = None
    confs_col_by_idx: dict | None = None
    ensemble_db: str | None = None
    progress_label: str = "Calculate descriptors"


class CalcWorker(QRunnable):
    def __init__(
        self,
        request: CalcDescriptorsRequest,
        signals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = request.data
        self.disp_headers = request.disp_headers
        self.int_fns = request.int_fns
        self.is_smiles = request.is_smiles
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.confs_by_idx = request.confs_by_idx or {}
        self.confs_col_by_idx = request.confs_col_by_idx or {}
        self.ensemble_db = request.ensemble_db
        self.progress_label = request.progress_label or "Calculate descriptors"

    def _prep_progress_message(self) -> str:
        if self.progress_label == "Calculate descriptors":
            return "Preparing descriptors…"
        return f"Preparing {self.progress_label.lower()}…"

    def run(self):
        smarts_cache = {}
        nrows = len(self.data)
        tot = max(nrows, 1)
        prepared = []
        prep_emit_step = max(1, nrows // 80)
        prep_last_emit = 0.0

        def _emit_prep_progress(done_count: int, *, force: bool = False) -> None:
            nonlocal prep_last_emit
            from ..platform_support.tool_progress import report_tool_progress

            now = time.monotonic()
            if force or done_count >= nrows or (now - prep_last_emit) >= 0.2:
                prep_last_emit = now
                report_tool_progress(
                    message=self._prep_progress_message(),
                    done=done_count,
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.signals,
                    force_signal=force,
                )

        need_3d = int_fns_need_3d(self.int_fns)
        mol3_by_idx: dict[int, Chem.Mol | None] = {}
        from ..storage import ensemble_mol_for

        for idx, (i, item) in enumerate(self.data):
            packed = self.confs_by_idx.get(int(i))
            if self.is_smiles:
                smi = item.strip() if isinstance(item, str) else ""
                mol = parse_molecule_from_cell_text(smi) if smi else None
                if packed is None and smi:
                    packed = smi
            else:
                mol = mol_from_tool_input(item)
            prepared.append((i, mol))
            if need_3d:
                col = self.confs_col_by_idx.get(int(i))
                ens = (
                    ensemble_mol_for(self.ensemble_db, int(i), str(col), min_conformers=1)
                    if self.ensemble_db and col
                    else None
                )
                mol3_by_idx[int(i)] = mol_for_3d_descriptors(ens or mol, packed_cell=packed)
            if idx == 0 or idx + 1 >= nrows or (idx + 1) % prep_emit_step == 0:
                _emit_prep_progress(idx + 1)
        _emit_prep_progress(len(prepared), force=True)

        cfg = load_config()
        if cfg.descriptor_threads is not None:
            max_workers = cfg.descriptor_threads
        else:
            max_workers = min(8, max(1, (os.cpu_count() or 4)))

        cancel_ev = self.cancel_event
        cancelled = False

        prog_last_emit = 0.0
        prog_last_done = -1

        def _emit_progress(done_count: int, *, force: bool = False) -> None:
            """Update shared progress state every row; throttle cross-thread signal emissions."""
            nonlocal prog_last_emit, prog_last_done
            from ..platform_support.tool_progress import report_tool_progress

            now = time.monotonic()
            step = _descriptor_progress_emit_step(tot)
            throttle_signal = (
                force
                or done_count >= tot
                or done_count <= 1
                or (done_count - prog_last_done) >= step
                or (now - prog_last_emit) >= 0.15
            )
            if throttle_signal:
                prog_last_emit = now
                prog_last_done = done_count
            report_tool_progress(
                message=self.progress_label,
                done=done_count,
                total=tot,
                progress_state=self.progress_state,
                signals=self.signals if throttle_signal else None,
                force_signal=force,
            )

        pka_by_idx: dict[int, list | None] = {}
        pka_cache_used = False
        if int_fns_need_ionization(self.int_fns) and nrows > 0:
            pka_by_idx = build_microstates_cache_for_rows(
                prepared,
                cancel_event=self.cancel_event,
                progress_state=self.progress_state,
                signals=self.signals,
                progress_message=self.progress_label,
                progress_total=tot,
            )
            pka_cache_used = True
            from ..platform_support.tool_progress import report_tool_progress

            report_tool_progress(
                message=self.progress_label,
                done=0,
                total=tot,
                progress_state=self.progress_state,
                signals=self.signals,
                force_signal=True,
            )

            # If the user cancelled while Uni-pKa was still computing ensembles, we can still
            # return partial descriptor results for the structures whose ensembles we already
            # have. This prevents "blank columns" after cancellation for LogD/LogS and similar
            # ionization-dependent descriptors.
            if cancel_ev is not None and cancel_ev.is_set():
                cancelled = True
                results = []
                done_count = 0
                _emit_progress(0, force=True)
                for i, mol in prepared:
                    if pka_by_idx.get(i) is None:
                        continue
                    try:
                        results.append(
                            _calc_descriptor_row_task(
                                (
                                    i,
                                    mol,
                                    self.disp_headers,
                                    tuple(self.int_fns),
                                    smarts_cache,
                                    pka_by_idx.get(i),
                                    True,
                                    mol3_by_idx.get(int(i)),
                                )
                            )
                        )
                        done_count += 1
                    except Exception:
                        logger.exception("Descriptor row task failed (partial-cancel path)")
                    _emit_progress(min(done_count, tot))
                _emit_progress(min(done_count, tot), force=True)
                self._emit_descriptor_results(
                    results,
                    prepared=prepared,
                    cancelled=cancelled,
                    pka_cache_used=pka_cache_used,
                    tot=tot,
                )
                return
        # ThreadPoolExecutor row tasks so RDKit never runs on the Qt GUI thread and small jobs
        # still use a worker thread instead of the process-queue thread doing every row inline.
        # RDKit descriptor / fingerprint work holds the GIL; child processes keep Qt responsive.
        mp_min = _descriptor_process_pool_min_rows(cfg, self.int_fns)
        use_process_pool = bool(self.int_fns) and nrows >= mp_min and nrows >= 2 and max_workers > 1
        mp_used = False
        if use_process_pool:
            try:
                results, pool_cancelled = _run_descriptor_process_pool(
                    prepared,
                    disp_headers=self.disp_headers,
                    int_fns=tuple(self.int_fns),
                    pka_by_idx=pka_by_idx,
                    pka_cache_used=pka_cache_used,
                    max_workers=max_workers,
                    batch_size=int(cfg.descriptor_process_pool_batch_size),
                    cancel_event=cancel_ev,
                    emit_progress=_emit_progress,
                    mol3_by_idx=mol3_by_idx,
                )
                cancelled = cancelled or pool_cancelled
                mp_used = True
            except Exception:
                logger.exception("Process-pool descriptors failed; falling back to in-process pool")
                mp_used = False

        if mp_used:
            pass
        elif nrows == 0:
            results = []
        elif not self.int_fns:
            results = [(i, {}) for i, _mol in prepared]
        else:
            _emit_progress(0, force=True)
            tasks = [
                (
                    i,
                    mol,
                    self.disp_headers,
                    tuple(self.int_fns),
                    smarts_cache,
                    pka_by_idx.get(i) if pka_cache_used else None,
                    pka_cache_used,
                    mol3_by_idx.get(int(i)),
                )
                for i, mol in prepared
            ]
            results = []
            with ThreadPoolExecutor(max_workers=max_workers) as ex:
                pending = {ex.submit(_calc_descriptor_row_task, t) for t in tasks}
                done_count = 0
                last_pulse = 0.0
                while pending:
                    if cancel_ev is not None and cancel_ev.is_set():
                        cancelled = True
                        for f in pending:
                            f.cancel()
                        for f in list(pending):
                            if f.done():
                                try:
                                    results.append(f.result())
                                    done_count += 1
                                except Exception:
                                    pass
                                pending.discard(f)
                        break
                    completed, pending = wait(pending, timeout=0.12, return_when=FIRST_COMPLETED)
                    if not completed and pending:
                        now = time.monotonic()
                        if now - last_pulse >= 0.55:
                            last_pulse = now
                            _emit_progress(done_count, force=True)
                    for f in completed:
                        if f.cancelled():
                            continue
                        try:
                            results.append(f.result())
                            done_count += 1
                        except Exception:
                            logger.exception("Descriptor row task failed")
                        _emit_progress(done_count)
            _emit_progress(min(done_count, tot), force=True)

        self._emit_descriptor_results(
            results,
            prepared=prepared,
            cancelled=cancelled,
            pka_cache_used=pka_cache_used,
            tot=tot,
        )

    def _emit_descriptor_results(
        self,
        results,
        *,
        prepared,
        cancelled,
        pka_cache_used,
        tot,
    ) -> None:
        from ..chem.murcko import apply_murcko_scaffold_counts

        results = apply_murcko_scaffold_counts(results, prepared, self.disp_headers, self.int_fns)
        emit_partial_results_if_cancelled(
            self.signals, self.progress_label, len(results), tot, cancelled
        )
        self.signals.calculated.emit(
            results, _descriptor_output_headers(self.disp_headers, pka_cache_used)
        )
