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

"""Background alignment of structure depictions to one oriented substructure."""

from __future__ import annotations

import threading

from PyQt5.QtCore import QRunnable

from ..chem.molecule_conversion import mol_from_binary_blob
from ..chem.substructure_align import align_structure_rows
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import WorkerSignals, emit_partial_results_if_cancelled

_PROGRESS = "Align to substructure"


class SubstructureAlignWorker(QRunnable):
    """Pin matching rows to *template_blob*'s 2D coordinates.

    Emits ``substructure_aligned`` with column, aligned ``(oid, coord_bytes)``
    rows, how many rows were considered, and how many were skipped before the
    job because they already had an orientation.
    """

    def __init__(
        self,
        rows: list[tuple],
        template_blob: bytes,
        *,
        column: str,
        skipped_existing: int = 0,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self._rows = list(rows)
        self._template_blob = bytes(template_blob)
        self._column = str(column)
        self._skipped_existing = int(skipped_existing)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self._throttle = [0, 0.0]

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def _progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message=_PROGRESS,
            done=int(done),
            total=int(total),
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=self._throttle,
        )

    def run(self) -> None:
        template = mol_from_binary_blob(self._template_blob)
        aligned: list[tuple[int, bytes]] = []
        considered = len(self._rows)
        cancelled = False
        if template is None:
            self.signals.substructure_aligned.emit(self._payload(aligned, cancelled=False))
            return
        aligned, _skipped, cancelled = align_structure_rows(
            self._rows,
            template,
            cancelled=self._cancelled,
            on_progress=self._progress,
        )
        emit_partial_results_if_cancelled(
            self.signals, "Align to Substructure", len(aligned), max(considered, 1), cancelled
        )
        self.signals.substructure_aligned.emit(self._payload(aligned, cancelled=cancelled))

    def _payload(self, aligned: list[tuple[int, bytes]], *, cancelled: bool) -> dict:
        return {
            "column": self._column,
            "aligned": aligned,
            "considered": len(self._rows),
            "skipped_existing": self._skipped_existing,
            "cancelled": bool(cancelled),
        }
