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

"""Matched molecular pair analysis worker (Data → MMP)."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..analysis.mmp_analysis import (
    CoreSideKey,
    MmpPair,
    filter_fragment_keys_by_core_query,
    fragment_keys_for_mol,
    mol_contains_core_query,
    pairs_from_fragment_records,
    parse_mmp_core_query,
)
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import WorkerSignals
from .structure_grouping import group_rows_by_structure


def _mp_fragment_mol(task: tuple[str, bytes, int, int]) -> tuple[str, list[tuple[str, list[str]]]]:
    """Process-pool helper: fragment one unique structure (keeps RDKit off the GUI GIL)."""
    key, mol_bytes, max_cuts, max_cut_bonds = task
    if not mol_bytes:
        return key, []
    try:
        mol = Chem.Mol(mol_bytes)
    except Exception:
        return key, []
    if mol is None:
        return key, []
    try:
        keys = fragment_keys_for_mol(mol, max_cuts=max_cuts, max_cut_bonds=max_cut_bonds)
        # Convert tuples → lists for a compact pickle payload.
        return key, [(core, list(sides)) for core, sides in keys]
    except Exception:
        return key, []


class MmpAnalysisWorker(QRunnable):
    """Find matched molecular pairs and emit results for the MMP browser."""

    def __init__(
        self,
        records: list[tuple[int, Chem.Mol, float]],
        *,
        activity_column: str,
        max_cuts: int = 1,
        max_cut_bonds: int = 20,
        max_variable_heavy_atoms: int | None = 13,
        min_activity_difference: float = 0.0,
        max_activity_difference: float = 0.0,
        core_smarts: str = "",
        purpose: str = "mmp",
        x_mode: str = "heavy_atoms",
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.records = records
        self.activity_column = activity_column
        self.max_cuts = max_cuts
        self.max_cut_bonds = max_cut_bonds
        self.max_variable_heavy_atoms = max_variable_heavy_atoms
        self.min_activity_difference = float(min_activity_difference)
        self.max_activity_difference = float(max_activity_difference)
        self.core_smarts = (core_smarts or "").strip()
        self.purpose = (purpose or "mmp").strip().lower()
        self.x_mode = x_mode or "heavy_atoms"
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            return

        from ..platform_support.tool_progress import report_tool_progress

        tot = max(len(self.records), 1)
        throttle = [0, 0.0]
        progress_label = {
            "activity_cliff": "Activity Cliffs",
            "mmp_neighborhood": "Pair Network",
        }.get(self.purpose, "MMP")
        report_tool_progress(
            message=progress_label,
            done=0,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )

        try:
            core_query = parse_mmp_core_query(self.core_smarts)
            if self.core_smarts and core_query is None:
                self._emit_failed("Core / MCS pattern could not be parsed as SMARTS or SMILES.")
                return

            activity_by_oid = {int(oid): float(act) for oid, _mol, act in self.records}
            mol_rows = [
                (int(oid), mol)
                for oid, mol, _act in self.records
                if mol is not None and mol_contains_core_query(mol, core_query)
            ]
            order, rep, oids_map = group_rows_by_structure(mol_rows)
            if not order:
                self._emit_finished([])
                return

            frag_by_key: dict[str, list[CoreSideKey]] = {}
            n_unique = len(order)
            use_mp = (os.cpu_count() or 1) > 1 and n_unique >= 2
            done_cum = 0
            last_pulse = 0.0
            max_cuts = int(self.max_cuts)
            max_cut_bonds = int(self.max_cut_bonds)

            if use_mp:
                tasks = [
                    (
                        k,
                        rep[k].ToBinary() if rep.get(k) is not None else b"",
                        max_cuts,
                        max_cut_bonds,
                    )
                    for k in order
                ]
                from ..platform_support.worker_budget import rdkit_process_workers

                proc_workers = rdkit_process_workers(n_unique)
                ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
                try:
                    pending = {ex.submit(_mp_fragment_mol, t) for t in tasks}
                    while pending:
                        if should_terminate_process_pool(ev):
                            for f in pending:
                                f.cancel()
                            break
                        # Short waits release the worker thread so the GUI stays responsive.
                        completed, pending = wait(
                            pending, timeout=0.25, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                key, raw_keys = f.result()
                                frag_by_key[str(key)] = [
                                    (core, tuple(sides)) for core, sides in (raw_keys or [])
                                ]
                                done_cum += len(oids_map.get(str(key), ()))
                            except Exception:
                                pass
                        now = time.monotonic()
                        if (now - last_pulse) >= 0.12:
                            last_pulse = now
                            report_tool_progress(
                                message=progress_label,
                                done=min(done_cum, tot),
                                total=tot,
                                progress_state=self.progress_state,
                                signals=self.signals,
                                throttle=throttle,
                            )
                finally:
                    shutdown_process_pool_executor(
                        ex, kill_workers=should_terminate_process_pool(ev)
                    )
            else:
                for key in order:
                    if ev is not None and ev.is_set():
                        break
                    mol = rep.get(key)
                    try:
                        frag_by_key[key] = (
                            fragment_keys_for_mol(
                                mol, max_cuts=max_cuts, max_cut_bonds=max_cut_bonds
                            )
                            if mol is not None
                            else []
                        )
                    except Exception:
                        frag_by_key[key] = []
                    done_cum += len(oids_map.get(key, ()))
                    report_tool_progress(
                        message=progress_label,
                        done=min(done_cum, tot),
                        total=tot,
                        progress_state=self.progress_state,
                        signals=self.signals,
                        throttle=throttle,
                    )
                    # Brief yield so the GUI thread can run between RDKit calls.
                    time.sleep(0)

            if ev is not None and ev.is_set():
                return

            if core_query is not None:
                for key, keys in list(frag_by_key.items()):
                    frag_by_key[key] = filter_fragment_keys_by_core_query(keys, core_query)

            frag_records: list[tuple[int, str, float, list[CoreSideKey]]] = []
            for key in order:
                keys = frag_by_key.get(key, [])
                smiles = key if not key.startswith("__uid_") else ""
                mol = rep.get(key)
                if mol is not None:
                    try:
                        smiles = Chem.MolToSmiles(mol, isomericSmiles=True) or smiles
                    except Exception:
                        pass
                for oid in oids_map.get(key, ()):
                    if oid is None:
                        continue
                    oid_i = int(oid)
                    act = activity_by_oid.get(oid_i)
                    if act is None:
                        continue
                    frag_records.append((oid_i, smiles, float(act), keys))

            def _cancelled() -> bool:
                return ev is not None and ev.is_set()

            pairs: list[MmpPair] = pairs_from_fragment_records(
                frag_records,
                max_variable_heavy_atoms=self.max_variable_heavy_atoms,
                min_activity_difference=self.min_activity_difference,
                max_activity_difference=self.max_activity_difference,
                cancel_check=_cancelled,
            )

            report_tool_progress(
                message=progress_label,
                done=tot,
                total=tot,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
                force_signal=True,
            )
            if ev is not None and ev.is_set():
                return
            self._emit_finished(pairs)
        except Exception as exc:
            self._emit_failed(str(exc) or f"{progress_label} analysis failed.")

    def _emit_finished(self, pairs: list[MmpPair]) -> None:
        if self.purpose == "activity_cliff":
            self.signals.activity_cliff_finished.emit(pairs, self.activity_column, self.x_mode)
        elif self.purpose == "mmp_neighborhood":
            self.signals.mmp_neighborhood_finished.emit(pairs, self.activity_column)
        else:
            self.signals.mmp_finished.emit(pairs, self.activity_column)

    def _emit_failed(self, message: str) -> None:
        if self.purpose == "activity_cliff":
            self.signals.activity_cliff_failed.emit(message)
        elif self.purpose == "mmp_neighborhood":
            self.signals.mmp_neighborhood_failed.emit(message)
        else:
            self.signals.mmp_failed.emit(message)
