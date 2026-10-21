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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Pytest fixtures for molmanager (Qt offscreen for headless CI)."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(autouse=True)
def _reset_worker_global_state() -> None:
    """Avoid cross-test pollution of process-pool shutdown (pKa / Uni-pKa workers)."""
    from molmanager.workers import process_pool_utils as ppu

    ppu._SHUTDOWN.clear()
    yield
    ppu._SHUTDOWN.clear()


@pytest.fixture(autouse=True)
def _destroy_leftover_widgets() -> None:
    """Destroy the widgets a test leaves behind, while no Qt code is on the stack.

    A window graph is cyclic — collaborators hold the window, signal connections hold bound
    methods — so closing a window frees nothing and the cycle collector ends up owning a live Qt
    tree. It then frees that tree at whatever allocation trips its threshold, which has meant
    inside another widget's constructor. Leaked windows are also not passive: ``setFont`` and
    friends walk every live widget, so one half-destroyed leftover corrupts an unrelated test.
    """
    yield
    from PyQt5 import sip
    from PyQt5.QtCore import QEvent
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    # Drain first. Callbacks already queued with ``QTimer.singleShot(0, ...)`` capture the window
    # and assume it outlives them, so deleting before they run turns them into use-after-free.
    for _ in range(3):
        app.processEvents()
    for widget in list(app.topLevelWidgets()):
        if not sip.isdeleted(widget):
            widget.deleteLater()
    QApplication.sendPostedEvents(None, QEvent.DeferredDelete)


@pytest.fixture(autouse=True)
def _isolate_recent_paths(tmp_path, monkeypatch) -> None:
    """Keep File → Open Recent off the developer QSettings profile."""
    from PyQt5.QtCore import QSettings

    ini = str(tmp_path / "recent_paths.ini")
    monkeypatch.setattr(
        "molmanager.ui.recent_paths.QSettings",
        lambda *_a, **_k: QSettings(ini, QSettings.IniFormat),
    )


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the test session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
