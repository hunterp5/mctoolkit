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

"""Most central ring decomposition (Chemistry → Structure Decomposition → Most Central Ring)."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..chem.central_ring_decomposition import decompose_central_ring
from .rgroup_decomposition import _assemble_table_rows, _collect_rg_columns
from .signals import WorkerSignals
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)

_RDKIT_ERRORS = (ValueError, RuntimeError)
_NO_RINGS = "No rings were found in the selected structures."


class CentralRingDecompositionWorker(QRunnable):
    """Write ``PREFIX_Core`` / ``PREFIX_R1`` / … for each row's most central ring system."""

    def __init__(
        self,
        data: list[tuple[int, Chem.Mol]],
        column_prefix: str,
        tool_title: str,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.data = data
        self.column_prefix = (column_prefix or "MCR").strip() or "MCR"
        self.tool_title = tool_title or "Most Central Ring Decomposition"
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        ev = self.cancel_event
        if ev is not None and ev.is_set():
            self._emit_finished([], [])
            return

        order, representatives, oids_by_key = group_rows_by_structure(self.data)
        total = sum(len(oids_by_key[key]) for key in order)
        if total <= 0:
            self._emit_failed(_NO_RINGS)
            return

        throttle = [0, 0.0]
        report_tool_progress(
            message=self.tool_title,
            done=0,
            total=total,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )

        results: dict[str, dict[str, str] | None] = {}
        processed: list[str] = []
        done = 0
        for key in order:
            if ev is not None and ev.is_set():
                break
            mol = representatives.get(key)
            try:
                results[key] = decompose_central_ring(mol) if mol is not None else None
            except _RDKIT_ERRORS as exc:
                logger.warning("Most central ring decomposition failed for one structure: %s", exc)
                results[key] = None
            processed.append(key)
            done += len(oids_by_key.get(key, ()))
            report_tool_progress(
                message=self.tool_title,
                done=min(done, total),
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )

        oids: list[int] = []
        matched_rows: list[dict[str, str]] = []
        unmatched: list[int] = []
        for key in processed:
            result = results.get(key)
            for oid in oids_by_key.get(key, ()):
                if oid is None:
                    continue
                index = len(oids)
                oids.append(int(oid))
                if result is None:
                    unmatched.append(index)
                else:
                    matched_rows.append(result)

        cancelled = ev is not None and ev.is_set()
        if not matched_rows:
            if cancelled:
                self._emit_finished([], [])
            else:
                self._emit_failed(_NO_RINGS)
            return

        columns = _collect_rg_columns(matched_rows)
        table_rows = _assemble_table_rows(
            oids, matched_rows, unmatched, columns, self.column_prefix
        )
        headers = [f"{self.column_prefix}_{key}" for key in columns]
        report_tool_progress(
            message=self.tool_title,
            done=total if not cancelled else min(done, total),
            total=total,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self._emit_finished(table_rows, headers)

    def _emit_finished(self, rows: list, headers: list) -> None:
        try:
            self.signals.fragment_decomp_finished.emit(rows, headers, self.tool_title)
        except _RDKIT_ERRORS:
            logger.warning(
                "Most central ring decomposition result could not be delivered", exc_info=True
            )

    def _emit_failed(self, message: str) -> None:
        try:
            self.signals.fragment_decomp_failed.emit(message, self.tool_title)
        except _RDKIT_ERRORS:
            logger.warning(
                "Most central ring decomposition failure could not be delivered", exc_info=True
            )
