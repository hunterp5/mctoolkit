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
import sys

import pytest

# Worker caps for the test process. The app sizes its pools to the machine (up to 12 Render 2D
# children, pKa and protomer pools, CPU-wide thread pools), and each child loads RDKit or
# PyTorch. Many tests start real pools, so uncapped a full run can saturate every core and
# exhaust RAM. These must be set before ``molmanager`` reads its config; an explicit value in
# the environment still wins.
_TEST_WORKER_CAPS = {
    "MOLMANAGER_MAX_THREADPOOL": "2",
    "MOLMANAGER_RENDER_THREADPOOL": "1",
    "MOLMANAGER_RENDER2D_PROCESS_WORKERS": "1",
    "MOLMANAGER_PKA_PROCESS_WORKERS": "1",
    "MOLMANAGER_PROTOMER_PROCESSES": "1",
    "MOLMANAGER_DESCRIPTOR_THREADS": "1",
    "MOLMANAGER_CONFORMER_THREADS": "1",
    "MOLMANAGER_UNIPKA_MMFF_THREADS": "1",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}
for _name, _value in _TEST_WORKER_CAPS.items():
    os.environ.setdefault(_name, _value)


def pytest_addoption(parser) -> None:
    parser.addoption(
        "--run-slow",
        action="store_true",
        default=False,
        help="Also run tests marked slow (live model inference, full protein preparation).",
    )


def pytest_collection_modifyitems(config, items) -> None:
    if config.getoption("--run-slow"):
        return
    skip_slow = pytest.mark.skip(reason="slow test; pass --run-slow to include it")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(autouse=True, scope="module")
def _release_worker_pools() -> None:
    """Kill process pools a test module started so idle children do not pile up across modules.

    Only modules a test already imported are touched, so a light test module never pays for
    importing the pool code.
    """
    yield
    render_pool = sys.modules.get("molmanager.workers.render2d_pool")
    if render_pool is not None:
        render_pool.release_render2d_process_pool(kill_workers=True)
    pools = sys.modules.get("molmanager.workers.process_pool_utils")
    if pools is not None:
        pools.shutdown_all_process_pools(kill_workers=True)
    score_host = sys.modules.get("molmanager.ionization.unipka_score_host")
    if score_host is not None:
        score_host.shutdown_unipka_score_host()


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


@pytest.fixture(autouse=True)
def _isolate_tool_paths(tmp_path, monkeypatch) -> None:
    """Keep Settings → Configure paths off the developer QSettings profile."""
    from PyQt5.QtCore import QSettings

    store = QSettings(str(tmp_path / "tool_paths.ini"), QSettings.IniFormat)
    monkeypatch.setattr("molmanager.platform_support.tool_paths._qsettings", lambda: store)


@pytest.fixture(scope="session")
def qapp():
    """Single QApplication for the test session."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt5.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app
