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

"""Per-job Qt signals so two runs of one tool cannot finish each other.

The window's shared ``WorkerSignals`` stays for dialogs and tools that are
not part of a macro. A macro job gets its own signal object. Progress and
cancel notices are forwarded to the window. The finish signal is connected
only to that job.
"""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QObject, Qt, pyqtSignal


def retain_job_signals(owner: Any, signals: QObject) -> None:
    """Keep *signals* alive until :func:`release_job_signals`."""
    held = getattr(owner, "_job_signal_holders", None)
    if held is None:
        held = []
        owner._job_signal_holders = held
    held.append(signals)


def release_job_signals(owner: Any, signals: QObject) -> None:
    """Drop *signals* once. A finish and a failure may both try."""
    held = getattr(owner, "_job_signal_holders", None)
    if not held or signals not in held:
        return
    held.remove(signals)
    signals.deleteLater()


class DescriptorJobSignals(QObject):
    """``calculated`` for one descriptor job. Cancel notices still reach the window."""

    calculated = pyqtSignal(list, list)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        window_signals = window.signals
        self.partial_results.connect(window_signals.partial_results, Qt.QueuedConnection)


class CalculatorJobSignals(QObject):
    """``custom_calc`` for one calculator job."""

    custom_calc = pyqtSignal(list)
    tool_progress = pyqtSignal(str, int, int)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        window_signals = window.signals
        self.tool_progress.connect(window_signals.tool_progress, Qt.QueuedConnection)
        self.partial_results.connect(window_signals.partial_results, Qt.QueuedConnection)


class ProtonateJobSignals(QObject):
    """``finished`` / ``failed`` for one protonate job."""

    finished = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)


class StructureEditJobSignals(QObject):
    """Finish signals for one neutralize or explicit-hydrogen job."""

    neutralized = pyqtSignal(list)
    explicit_hydrogens_added = pyqtSignal(list)
    explicit_hydrogens_removed = pyqtSignal(list)
    tool_progress = pyqtSignal(str, int, int)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        window_signals = window.signals
        self.tool_progress.connect(window_signals.tool_progress, Qt.QueuedConnection)
        self.partial_results.connect(window_signals.partial_results, Qt.QueuedConnection)


class RGroupJobSignals(QObject):
    """R-group enumeration signals for one job."""

    rgroup_enum_finished = pyqtSignal(object)
    rgroup_enum_failed = pyqtSignal(str, str)
    tool_progress = pyqtSignal(str, int, int)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        window_signals = window.signals
        self.tool_progress.connect(window_signals.tool_progress, Qt.QueuedConnection)
        self.partial_results.connect(window_signals.partial_results, Qt.QueuedConnection)


class FastPrepareJobSignals(QObject):
    """Batch and finish signals for one Fast Prepare job."""

    fast_prepared = pyqtSignal(list)
    fast_prepared_batch = pyqtSignal(list, bool)
    tool_progress = pyqtSignal(str, int, int)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        window_signals = window.signals
        self.tool_progress.connect(window_signals.tool_progress, Qt.QueuedConnection)
        self.partial_results.connect(window_signals.partial_results, Qt.QueuedConnection)


class ReactionJobSignals(QObject):
    """Reaction enumeration signals for one job."""

    reaction_enum_finished = pyqtSignal(object)
    reaction_enum_failed = pyqtSignal(str, str)
    partial_results = pyqtSignal(str, int, int)

    def __init__(self, window: QObject) -> None:
        super().__init__(window)
        self.partial_results.connect(window.signals.partial_results, Qt.QueuedConnection)
