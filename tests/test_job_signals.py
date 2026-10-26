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

"""Two jobs of the same tool finish independently."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtCore import QObject, Qt

from molmanager.ui.job_signals import DescriptorJobSignals
from molmanager.ui.macro_filters import arm_filter_wait
from molmanager.workers.signals import WorkerSignals


class _Window(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.signals = WorkerSignals(self)


def test_descriptor_jobs_do_not_share_a_finish_slot(qapp):
    window = _Window()
    first = DescriptorJobSignals(window)
    second = DescriptorJobSignals(window)
    heard: list[str] = []
    first.calculated.connect(lambda _res, _headers: heard.append("first"), Qt.QueuedConnection)
    second.calculated.connect(lambda _res, _headers: heard.append("second"), Qt.QueuedConnection)
    first.calculated.emit([], ["MolWt"])
    qapp.processEvents()
    assert heard == ["first"]
    second.calculated.emit([], ["MolLogP"])
    qapp.processEvents()
    assert heard == ["first", "second"]


def test_a_new_filter_wait_cancels_the_previous_one():
    app = type("App", (), {})()
    heard: list[str | None] = []
    arm_filter_wait(app, heard.append)
    arm_filter_wait(app, heard.append)
    assert heard == ["Cancelled."]
    app._macro_filter_wait.succeed()
    assert heard == ["Cancelled.", None]
    app._macro_filter_wait.succeed()
    assert heard == ["Cancelled.", None]
