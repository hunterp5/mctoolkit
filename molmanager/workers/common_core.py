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

"""Background common-core search."""

from __future__ import annotations

import threading

from PyQt5.QtCore import QRunnable

from ..chem.common_core import COMMON_CORE_HEADERS, build_common_core_rows
from ..chem.molecule_conversion import mol_from_tool_input
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from .signals import WorkerSignals

_PROGRESS = "Common Core"


class CommonCoreWorker(QRunnable):
    """Find one MCS and write the core, atom map, and match flag."""

    def __init__(
        self,
        rows: list[tuple[int, object]],
        *,
        outliers: int,
        complete_rings: bool,
        timeout: int,
        signals: WorkerSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self._rows = list(rows)
        self._outliers = int(outliers)
        self._complete_rings = bool(complete_rings)
        self._timeout = int(timeout)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def _cancelled(self) -> bool:
        return self.cancel_event is not None and self.cancel_event.is_set()

    def run(self) -> None:
        total = max(1, len(self._rows))
        if self._cancelled():
            self.signals.common_core_failed.emit("Cancelled.")
            return
        report_tool_progress(
            message=_PROGRESS,
            done=0,
            total=total,
            progress_state=self.progress_state,
            signals=self.signals,
        )
        pairs = [(int(oid), mol_from_tool_input(payload)) for oid, payload in self._rows]
        try:
            result = build_common_core_rows(
                pairs,
                outliers=self._outliers,
                complete_rings=self._complete_rings,
                timeout=self._timeout,
            )
        except ValueError as exc:
            self.signals.common_core_failed.emit(str(exc) or "Common core search failed.")
            return
        if self._cancelled():
            self.signals.common_core_failed.emit("Cancelled.")
            return
        report_tool_progress(
            message=_PROGRESS,
            done=total,
            total=total,
            progress_state=self.progress_state,
            signals=self.signals,
        )
        self.signals.calculated.emit(result, list(COMMON_CORE_HEADERS))
