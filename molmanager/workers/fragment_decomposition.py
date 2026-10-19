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

"""BRICS / RECAP fragment decomposition workers (Tools menu)."""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..chem.fragment_decomposition import (
    DecompositionMethod,
    assemble_fragment_table_rows,
    decompose_fragments,
)
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import WorkerSignals
from .structure_grouping import group_rows_by_structure


def _mp_decompose_fragments(task: tuple[str, bytes, str]) -> tuple[str, list[str]]:
    key, mol_bytes, method = task
    if not mol_bytes:
        return key, []
    try:
        mol = Chem.Mol(mol_bytes)
    except Exception:
        mol = None
    if mol is None:
        return key, []
    try:
        frags = decompose_fragments(mol, method)  # type: ignore[arg-type]
        return key, list(frags or [])
    except Exception:
        return key, []


class FragmentDecompositionWorker(QRunnable):
    """Decompose each structure into fragments and emit new table columns."""

    def __init__(
        self,
        data: list[tuple[int, Chem.Mol]],
        method: DecompositionMethod,
        column_prefix: str,
        tool_title: str,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = data
        self.method = method
        self.column_prefix = (column_prefix or "").strip()
        self.tool_title = tool_title
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            return

        from ..platform_support.tool_progress import report_tool_progress

        order, rep, oids_map = group_rows_by_structure(self.data)
        tot = max(sum(len(oids_map[k]) for k in order), 1)
        label = self.tool_title
        throttle = [0, 0.0]
        report_tool_progress(
            message=label,
            done=0,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )

        # Compute fragments once per unique structure (dedupe), optionally in a process pool.
        method = self.method
        n_unique = len(order)
        use_mp = (os.cpu_count() or 1) > 1 and n_unique >= 2
        done_cum = 0
        last_pulse = 0.0

        results_by_key: dict[str, list[str]] = {}

        if use_mp:
            tasks = [
                (k, rep[k].ToBinary() if rep.get(k) is not None else b"", method) for k in order
            ]
            from ..platform_support.worker_budget import rdkit_process_workers

            proc_workers = rdkit_process_workers(n_unique)
            ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
            try:
                pending = {ex.submit(_mp_decompose_fragments, t) for t in tasks}
                while pending:
                    if should_terminate_process_pool(ev):
                        for f in pending:
                            f.cancel()
                        break
                    completed, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                    for f in completed:
                        if f.cancelled():
                            continue
                        try:
                            key, frags = f.result()
                            results_by_key[str(key)] = list(frags or [])
                            done_cum += len(oids_map.get(str(key), ()))
                        except Exception:
                            # Keep going; failed rows become empty fragments.
                            pass
                    now = time.monotonic()
                    if (now - last_pulse) >= 0.12:
                        last_pulse = now
                        report_tool_progress(
                            message=label,
                            done=min(done_cum, tot),
                            total=tot,
                            progress_state=self.progress_state,
                            signals=self.signals,
                            throttle=throttle,
                        )
            finally:
                shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(ev))
        else:
            for key in order:
                if ev is not None and ev.is_set():
                    break
                m = rep.get(key)
                try:
                    results_by_key[key] = decompose_fragments(m, method) if m is not None else []
                except Exception:
                    results_by_key[key] = []
                done_cum += len(oids_map.get(key, ()))
                report_tool_progress(
                    message=label,
                    done=min(done_cum, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.signals,
                    throttle=throttle,
                )

        # Expand unique results back to per-row order.
        oids: list[int] = []
        per_row: list[list[str]] = []
        for key in order:
            frags = results_by_key.get(key, [])
            for oid in oids_map.get(key, ()):
                oids.append(int(oid))
                per_row.append(list(frags))

        table_rows, headers = assemble_fragment_table_rows(oids, per_row, self.column_prefix)
        if not headers:
            try:
                self.signals.fragment_decomp_failed.emit(
                    "No fragments were produced for any row in scope.",
                    self.tool_title,
                )
            except Exception:
                pass
            return

        report_tool_progress(
            message=label,
            done=min(done_cum, tot),
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        try:
            self.signals.fragment_decomp_finished.emit(table_rows, headers, self.tool_title)
        except Exception:
            pass
