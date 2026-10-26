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

"""One result per started command.

Tools still finish through a signal object that belongs to that job.
``dispatch_step`` turns the job callback into this handle so the recipe
runner, and later a recorder, wait on the job rather than on a single
attribute of the window.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, pyqtSignal


@dataclass(frozen=True)
class JobOutcome:
    """What a command left behind after its table write or filter pass."""

    ok: bool
    error: str | None
    cancelled: bool
    outputs: dict[str, str]


class JobHandle(QObject):
    """Completion for one ``dispatch_step`` call.

    ``finished`` is emitted once. A synchronous tool may finish before the
    caller connects, so ``outcome`` is also stored and can be read after
    ``dispatch_step`` returns.
    """

    finished = pyqtSignal(object)

    def __init__(self, command_id: str, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.command_id = command_id
        self._outcome: JobOutcome | None = None

    @property
    def outcome(self) -> JobOutcome | None:
        return self._outcome

    def succeed(self, outputs: dict[str, str] | None = None) -> None:
        """The step's columns or filters are in place."""
        self._settle(JobOutcome(True, None, False, dict(outputs or {})))

    def fail(self, error: str, *, cancelled: bool = False) -> None:
        """The step did not finish. *cancelled* is a user stop, not a bad recipe."""
        self._settle(JobOutcome(False, error or "The step failed.", cancelled, {}))

    def abandon(self) -> None:
        """Ignore any later completion. Does not emit ``finished``."""
        if self._outcome is None:
            self._outcome = JobOutcome(False, "Cancelled.", True, {})

    def _settle(self, outcome: JobOutcome) -> None:
        if self._outcome is not None:
            return
        self._outcome = outcome
        self.finished.emit(outcome)
