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

"""Background CONFORGE job: table ligands → packed conformer ensembles."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..chem.molecule_conversion import mol_from_tool_input
from ..conformers.conforge_generation import (
    ConforgeParams,
    ensure_conforge_ready,
    run_conforge_generation,
)
from .chemistry_worker_common import emit_tool_progress_throttled
from .process_pool_utils import should_terminate_process_pool
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)

PROGRESS_LABEL = "CONFORGE conformations"


class ConforgeConformerWorker(QRunnable):
    """Run :func:`run_conforge_generation` off the UI thread (one ligand at a time)."""

    def __init__(
        self,
        data: list[tuple[int, Chem.Mol | None]],
        params: ConforgeParams,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = list(data)
        self.params = params
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        tot = max(len(self.data), 1)
        results: list = []
        cancelled = False
        prog_state = [0, 0.0]
        missing = ensure_conforge_ready(self.params.confgen_path)
        if missing:
            for oid, _mol in self.data:
                results.append(_error_row(oid, self.params, "conforge_unavailable"))
            self._emit(results, cancelled=False, tot=tot)
            return
        try:
            emit_tool_progress_throttled(
                self.signals,
                PROGRESS_LABEL,
                0,
                tot,
                prog_state,
                progress_state=self.progress_state,
            )
        except Exception:
            pass
        for i, (oid, item) in enumerate(self.data):
            if should_terminate_process_pool(self.cancel_event):
                cancelled = True
                break
            mol = mol_from_tool_input(item)
            results.append(_row_result(int(oid), mol, self.params, self.cancel_event))
            if should_terminate_process_pool(self.cancel_event):
                cancelled = True
                break
            emit_tool_progress_throttled(
                self.signals,
                PROGRESS_LABEL,
                i + 1,
                tot,
                prog_state,
                progress_state=self.progress_state,
                force=(i + 1) >= tot,
            )
        self._emit(results, cancelled=cancelled, tot=tot)

    def _emit(self, results: list, *, cancelled: bool, tot: int) -> None:
        final_done = tot if not cancelled else min(len(results), tot)
        emit_tool_progress_throttled(
            self.signals,
            PROGRESS_LABEL,
            final_done,
            tot,
            [0, 0.0],
            progress_state=self.progress_state,
            force=True,
        )
        emit_partial_results_if_cancelled(
            self.signals, PROGRESS_LABEL, len(results), tot, cancelled
        )
        try:
            self.signals.conformers_finished.emit(results)
        except Exception:
            logger.warning("conformers_finished emit failed", exc_info=True)


def _error_row(oid: int, params: ConforgeParams, err: str) -> tuple[int, None, dict]:
    meta = {
        "ok": False,
        "err": err[:200],
        "n_requested": int(params.num_confs),
        "ff": "MMFF94",
        "op": "conforge",
    }
    return int(oid), None, meta


def _row_result(
    oid: int,
    mol: Chem.Mol | None,
    params: ConforgeParams,
    cancel_event: threading.Event | None,
) -> tuple[int, Chem.Mol | None, dict]:
    try:
        if mol is None:
            return _error_row(oid, params, "missing_mol")
        new_m, meta = run_conforge_generation(mol, params, cancel_event=cancel_event)
        return oid, new_m, dict(meta)
    except Exception as e:
        logger.exception("ConforgeConformerWorker failed for oid=%s", oid)
        return _error_row(oid, params, str(e))
