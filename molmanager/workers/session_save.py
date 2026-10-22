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

"""Background write and read of version-4 ``.cms`` sessions."""

from __future__ import annotations

import logging

from PyQt5.QtCore import QRunnable

from ..platform_support.tool_progress import ToolProgressState, report_tool_progress
from ..table.session_v4 import SessionSaveSnapshot, read_session_v4, write_session_v4
from .signals import SessionOpenSignals, SessionSaveSignals

logger = logging.getLogger(__name__)


class SessionSaveWorker(QRunnable):
    """Write a session snapshot to disk off the UI thread."""

    def __init__(
        self,
        job_gen: int,
        path: str,
        snapshot: SessionSaveSnapshot,
        signals: SessionSaveSignals,
        *,
        scene_magic: bytes | None = None,
        progress_state: ToolProgressState | None = None,
    ) -> None:
        super().__init__()
        self.job_gen = int(job_gen)
        self.path = str(path)
        self.snapshot = snapshot
        self.scene_magic = scene_magic
        self.signals = signals
        self.progress_state = progress_state
        self._progress_throttle = [0, 0.0]

    def _emit_progress(self, done: int, total: int) -> None:
        report_tool_progress(
            message="Saving session…",
            done=int(done),
            total=max(1, int(total)),
            progress_state=self.progress_state,
            throttle=self._progress_throttle,
        )

    def run(self) -> None:
        n = max(1, int(self.snapshot.row_count))
        try:
            self._emit_progress(0, n)
            write_session_v4(
                self.path,
                self.snapshot,
                scene_magic=self.scene_magic,
                on_progress=self._emit_progress,
            )
            self._emit_progress(n, n)
            self.signals.finished.emit(self.job_gen, self.path)
        except Exception as exc:
            logger.exception("SessionSaveWorker failed: %s", self.path)
            self.signals.failed.emit(self.job_gen, str(exc))


class SessionOpenWorker(QRunnable):
    """Read a session into memory plus temp store files the GUI thread adopts."""

    def __init__(
        self,
        generation: int,
        path: str,
        signals: SessionOpenSignals,
        *,
        want_scene_revision: int | None,
    ) -> None:
        super().__init__()
        self.generation = int(generation)
        self.path = str(path)
        self.signals = signals
        self.want_scene_revision = want_scene_revision

    def run(self) -> None:
        try:
            result = read_session_v4(self.path, want_scene_revision=self.want_scene_revision)
        except Exception as exc:
            logger.exception("SessionOpenWorker failed: %s", self.path)
            self.signals.failed.emit(self.generation, str(exc) or "Could not read the session.")
            return
        self.signals.finished.emit(self.generation, result)
