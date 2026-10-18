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

"""Dock transition guard and batched splitter sizing."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QApplication, QSplitter, QWidget

from molmanager.ui.plot_dock_host import PlotDockHost, _SplitterSizeBatch


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _HostApp:
    status_label = None


def test_splitter_batch_applies_once(qapp):
    del qapp
    calls: list[list[int]] = []

    class _FakeSplitter:
        def setSizes(self, sizes):
            calls.append([int(s) for s in sizes])

    splitter = _FakeSplitter()
    batch = _SplitterSizeBatch()
    batch.set_sizes(splitter, [100, 300])
    batch.set_sizes(splitter, [120, 280])
    batch.apply()
    assert calls == [[120, 280]]
    batch.apply()
    assert calls == [[120, 280]]


def test_dock_transition_refuses_reentry(qapp):
    del qapp
    host = PlotDockHost(_HostApp())
    widget = QWidget()
    with host._dock_transition(widget) as batch1:
        assert batch1 is not None
        with host._dock_transition(widget) as batch2:
            assert batch2 is None


def test_dock_transition_restores_updates(qapp):
    del qapp
    host = PlotDockHost(_HostApp())
    widget = QWidget()
    widget.setUpdatesEnabled(True)
    with host._dock_transition(widget):
        assert widget.isEnabled()
    assert widget.updatesEnabled()
