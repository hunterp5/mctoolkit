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

"""Background pharmacophore screen of packed conformation ensembles."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from typing import Any

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..protein.pharmacophore import pharmacophore_from_dict
from ..protein.pharmacophore_screen import DEFAULT_SLACK_ANGSTROM, screen_mol
from ..storage import ensemble_mol_for
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import PharmacophoreScreenSignals

logger = logging.getLogger(__name__)

_PROGRESS_LABEL = "Pharmacophore screen"


def _hit_tuple(oid: int, hit) -> tuple[int, bool, float, float | None, int | None]:
    return (
        int(oid),
        bool(hit.matched),
        float(hit.score),
        None if hit.rmsd is None else float(hit.rmsd),
        None if hit.conf_id is None else int(hit.conf_id),
    )


def _screen_one(
    oid: int,
    mol: Chem.Mol,
    query: dict[str, Any],
    slack: float,
    min_matched: int | None,
) -> tuple[int, bool | None, float, float | None, int | None]:
    """``matched is None`` means the molecule had no usable 3D conformer."""
    try:
        if mol is None or mol.GetNumConformers() == 0:
            return (int(oid), None, 0.0, None, None)
        pharma = pharmacophore_from_dict(query)
        hit = screen_mol(mol, pharma, slack=slack, min_matched=min_matched)
        return _hit_tuple(oid, hit)
    except Exception:
        logger.debug("Pharmacophore screen failed for oid %s", oid, exc_info=True)
        return (int(oid), None, 0.0, None, None)


def _mp_screen_row(args: tuple) -> tuple[int, bool | None, float, float | None, int | None]:
    oid, mol_bytes, query, slack, min_matched, db_path, column = args
    mol = None
    if db_path and column:
        mol = ensemble_mol_for(db_path, int(oid), str(column), min_conformers=1)
    if mol is None:
        if not mol_bytes:
            return (int(oid), None, 0.0, None, None)
        try:
            mol = Chem.Mol(mol_bytes)
        except Exception:
            return (int(oid), None, 0.0, None, None)
    return _screen_one(int(oid), mol, query, float(slack), min_matched)


class PharmacophoreScreenWorker(QRunnable):
    """Screen packed ensembles against a MolManager pharmacophore JSON object."""

    def __init__(
        self,
        query: dict[str, Any],
        targets: list[tuple[int, Chem.Mol]],
        signals: PharmacophoreScreenSignals,
        *,
        slack: float = DEFAULT_SLACK_ANGSTROM,
        min_matched: int | None = None,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
        ensemble_db: str | None = None,
        ensemble_column: str | None = None,
    ) -> None:
        super().__init__()
        self.query = query
        self.targets = targets
        self.signals = signals
        self.slack = float(slack)
        self.min_matched = min_matched
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.ensemble_db = ensemble_db
        self.ensemble_column = ensemble_column

    def _report(self, done: int, total: int, *, force: bool = False) -> None:
        report_tool_progress(
            message=_PROGRESS_LABEL,
            done=done,
            total=total,
            progress_state=self.progress_state,
            force_signal=force,
        )

    def run(self) -> None:
        try:
            cancel_ev = self.cancel_event
            n = len(self.targets)
            total_steps = max(1, n)
            self._report(0, total_steps, force=True)
            if n <= 0:
                self.signals.finished.emit([])
                return
            raw: list[tuple[int, bool | None, float, float | None, int | None]] = []
            if n >= 2:
                tasks = [
                    (
                        oid,
                        b"" if mol is None else mol.ToBinary(),
                        self.query,
                        self.slack,
                        self.min_matched,
                        self.ensemble_db,
                        self.ensemble_column,
                    )
                    for oid, mol in self.targets
                ]
                from ..platform_support.worker_budget import rdkit_process_workers

                proc_workers = rdkit_process_workers()
                done_count = 0
                last_pulse = 0.0
                ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
                try:
                    pending = {ex.submit(_mp_screen_row, t) for t in tasks}
                    while pending:
                        if should_terminate_process_pool(cancel_ev):
                            for fut in list(pending):
                                if fut.done() and not fut.cancelled():
                                    try:
                                        raw.append(fut.result())
                                    except Exception:
                                        pass
                                else:
                                    fut.cancel()
                            break
                        completed, pending = wait(
                            pending, timeout=0.25, return_when=FIRST_COMPLETED
                        )
                        if not completed and pending:
                            now = time.monotonic()
                            if now - last_pulse >= 0.55:
                                last_pulse = now
                                self._report(done_count, total_steps, force=True)
                        for fut in completed:
                            if fut.cancelled():
                                continue
                            try:
                                raw.append(fut.result())
                            except Exception:
                                pass
                            done_count += 1
                            self._report(min(done_count, total_steps), total_steps)
                finally:
                    shutdown_process_pool_executor(
                        ex, kill_workers=should_terminate_process_pool(cancel_ev)
                    )
            else:
                done_count = 0
                for oid, mol in self.targets:
                    if cancel_ev is not None and cancel_ev.is_set():
                        break
                    if mol is None and self.ensemble_db and self.ensemble_column:
                        mol = ensemble_mol_for(
                            self.ensemble_db, oid, self.ensemble_column, min_conformers=1
                        )
                    raw.append(_screen_one(oid, mol, self.query, self.slack, self.min_matched))
                    done_count += 1
                    self._report(min(done_count, total_steps), total_steps)
            self._report(total_steps, total_steps, force=True)
            self.signals.finished.emit(raw)
        except Exception as exc:
            logger.exception("PharmacophoreScreenWorker failed")
            self.signals.failed.emit(str(exc))
