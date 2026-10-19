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

"""Background write of a chunked version-3 ``.cms`` session snapshot."""

from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import QRunnable

from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from ..table.session_document_build import write_session_v3
from .signals import SessionSaveSignals

logger = logging.getLogger(__name__)


class SessionSaveWorker(QRunnable):
    """Assemble, compact, and write a session file off the UI thread."""

    def __init__(
        self,
        job_gen: int,
        path: str,
        snapshot: dict[str, Any],
        signals: SessionSaveSignals,
        *,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self.job_gen = int(job_gen)
        self.path = str(path)
        self.snapshot = snapshot
        self.signals = signals
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _emit_progress(self, message: str, done: int, total: int) -> None:
        report_tool_progress(
            message=message,
            done=int(done),
            total=max(1, int(total)),
            progress_state=self.progress_state,
            throttle=self._progress_throttle,
        )

    def run(self) -> None:
        n = max(1, len(self.snapshot.get("entries") or []))
        try:
            self._emit_progress("Saving session…", 0, n)
            write_session_v3(
                self.path,
                self.snapshot,
                on_progress=lambda done, total: self._emit_progress("Saving session…", done, total),
            )
            self._emit_progress("Saving session…", n, n)
            self.signals.finished.emit(self.job_gen, self.path)
        except Exception as exc:
            logger.exception("SessionSaveWorker failed: %s", self.path)
            self.signals.failed.emit(self.job_gen, str(exc))
