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

"""Fingerprint similarity batch worker."""

from __future__ import annotations

import logging
import os
import pickle
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from typing import TYPE_CHECKING

from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit import DataStructs

from ..chem.rdkit_fingerprints import (
    fingerprint_bitvect_for_row,
    fingerprint_bitvect_for_ui_choice,
    fingerprint_is_gil_heavy,
)
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from ..chem.molecule_conversion import mol_to_canonical_smiles
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import FPSimilaritySignals

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

SIMILARITY_METRIC_LABELS: list[str] = ["Tanimoto", "Dice", "Cosine"]

_PROGRESS_LABEL = "Fingerprint similarity"


def pairwise_fingerprint_similarity(qfp, fp, metric: str) -> float:
    """Pairwise similarity for bit-vector fingerprints (RDKit DataStructs)."""
    if metric == "Dice":
        return float(DataStructs.DiceSimilarity(qfp, fp))
    if metric == "Cosine":
        return float(DataStructs.CosineSimilarity(qfp, fp))
    return float(DataStructs.TanimotoSimilarity(qfp, fp))


def _fp_similarity_one(
    oid: int,
    mol: Chem.Mol,
    qfp,
    fp_choice: str,
    metric: str,
) -> tuple[int, float, str] | None:
    try:
        fp = fingerprint_bitvect_for_row(int(oid), mol, fp_choice)
        if fp is None:
            fp = fingerprint_bitvect_for_ui_choice(mol, fp_choice)
        if fp is None:
            return None
        sim = pairwise_fingerprint_similarity(qfp, fp, metric)
        return (oid, sim, mol_to_canonical_smiles(mol))
    except Exception:
        return None


def _mp_fp_similarity_row(args: tuple) -> tuple[int, float, str] | None:
    """One row in a child process (Gobbi Pharm2D releases GIL only across processes)."""
    oid, mol_bytes, fp_choice, metric, qfp_bytes = args
    if not mol_bytes:
        return None
    try:
        mol = Chem.Mol(mol_bytes)
        qfp = pickle.loads(qfp_bytes)
    except Exception:
        return None
    return _fp_similarity_one(int(oid), mol, qfp, str(fp_choice), str(metric))


class FPSimilarityWorker(QRunnable):
    """Compute fingerprint similarity vs a query structure off the UI thread."""

    def __init__(
        self,
        qmol: Chem.Mol,
        targets: list[tuple[int, Chem.Mol]],
        fp_choice: str,
        signals: FPSimilaritySignals,
        *,
        metric: str = "Tanimoto",
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.qmol = qmol
        self.targets = targets
        self.fp_choice = fp_choice
        self.metric = metric if metric in SIMILARITY_METRIC_LABELS else "Tanimoto"
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def _report(self, done: int, total: int, *, force: bool = False) -> None:
        report_tool_progress(
            message=_PROGRESS_LABEL,
            done=done,
            total=total,
            progress_state=self.progress_state,
            force_signal=force,
        )

    def run(self):
        try:
            cancel_ev = self.cancel_event
            n = len(self.targets)
            total_steps = max(1, n + 1)
            self._report(0, total_steps, force=True)

            qfp = fingerprint_bitvect_for_ui_choice(self.qmol, self.fp_choice)
            if qfp is None:
                self.signals.failed.emit("Could not compute query fingerprint.")
                return
            self._report(1, total_steps, force=True)

            if n <= 0:
                self.signals.finished.emit([])
                return

            metric = self.metric
            use_mp = fingerprint_is_gil_heavy(self.fp_choice) and n >= 2
            raw: list[tuple[int, float, str] | None] = []

            if use_mp:
                qfp_bytes = pickle.dumps(qfp)
                mp_tasks = [
                    (oid, mol.ToBinary(), self.fp_choice, metric, qfp_bytes)
                    for oid, mol in self.targets
                ]
                from ..platform_support.worker_budget import rdkit_process_workers

                proc_workers = rdkit_process_workers()
                done_count = 1
                last_pulse = 0.0
                ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
                try:
                    pending = {ex.submit(_mp_fp_similarity_row, t) for t in mp_tasks}
                    while pending:
                        if should_terminate_process_pool(cancel_ev):
                            for f in list(pending):
                                if f.done() and not f.cancelled():
                                    try:
                                        raw.append(f.result())
                                    except Exception:
                                        pass
                                else:
                                    f.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.25, return_when=FIRST_COMPLETED
                        )
                        if not completed and pending:
                            now = time.monotonic()
                            if now - last_pulse >= 0.55:
                                last_pulse = now
                                self._report(done_count, total_steps, force=True)
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                raw.append(f.result())
                            except Exception:
                                pass
                            done_count += 1
                            self._report(min(done_count, total_steps), total_steps)
                finally:
                    shutdown_process_pool_executor(
                        ex, kill_workers=should_terminate_process_pool(cancel_ev)
                    )
            elif n < 64:
                done_count = 1
                for oid, mol in self.targets:
                    if cancel_ev is not None and cancel_ev.is_set():
                        break
                    raw.append(_fp_similarity_one(oid, mol, qfp, self.fp_choice, metric))
                    done_count += 1
                    self._report(min(done_count, total_steps), total_steps)
            else:
                max_workers = min(8, max(1, (os.cpu_count() or 4)))
                tasks = [(oid, mol, qfp, self.fp_choice, metric) for oid, mol in self.targets]
                done_count = 1
                with ThreadPoolExecutor(max_workers=max_workers) as ex:
                    pending = {ex.submit(_fp_similarity_one, *t) for t in tasks}
                    while pending:
                        if cancel_ev is not None and cancel_ev.is_set():
                            for f in pending:
                                f.cancel()
                            for f in list(pending):
                                if f.done():
                                    try:
                                        raw.append(f.result())
                                    except Exception:
                                        pass
                                    pending.discard(f)
                            break
                        completed, pending = wait(
                            pending, timeout=0.08, return_when=FIRST_COMPLETED
                        )
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                raw.append(f.result())
                            except Exception:
                                pass
                            done_count += 1
                            self._report(min(done_count, total_steps), total_steps)

            rows = [x for x in raw if x is not None]
            rows.sort(key=lambda x: x[1], reverse=True)
            self._report(total_steps, total_steps, force=True)
            self.signals.finished.emit(rows)
        except Exception as e:
            logger.exception("FPSimilarityWorker failed")
            self.signals.failed.emit(str(e))
