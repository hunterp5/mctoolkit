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

"""Shared measurement helpers for the file-operation benchmarks.

Every measurement reads state the user can see (table revealed, loading finished,
visible structure images drawn) rather than private method names, so a baseline
recorded before a refactor stays comparable with a run after it.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field


@dataclass
class StallRecorder:
    """Record gaps between fires of a fast QTimer; a long gap is a GUI freeze."""

    threshold_ms: float = 50.0
    stalls: list[tuple[float, float]] = field(default_factory=list)
    t_start: float = field(default_factory=time.perf_counter)
    _last: float = field(default_factory=time.perf_counter)
    _timer: object = None

    def start(self) -> None:
        from PyQt5.QtCore import QTimer

        self.t_start = time.perf_counter()
        self._last = self.t_start
        self._timer = QTimer()
        self._timer.setInterval(8)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    def reset(self) -> None:
        self.stalls.clear()
        self.t_start = time.perf_counter()
        self._last = self.t_start

    def _tick(self) -> None:
        now = time.perf_counter()
        gap_ms = (now - self._last) * 1000.0
        self._last = now
        if gap_ms >= self.threshold_ms:
            self.stalls.append((now - self.t_start, gap_ms))

    def elapsed(self) -> float:
        return time.perf_counter() - self.t_start

    def summary(self) -> dict:
        gaps = [gap for _t, gap in self.stalls]
        return {
            "stall_count": len(gaps),
            "worst_stall_ms": round(max(gaps, default=0.0), 1),
            "total_stall_s": round(sum(gaps) / 1000.0, 3),
            "last_stall_end_s": round(max((t for t, _gap in self.stalls), default=0.0), 3),
        }


#: Seconds to keep watching for freezes after an operation reports completion.
TAIL_S = 2.0


def responsive_s(usable_s: float | None, stalls: StallRecorder) -> float | None:
    """When the table was usable *and* the GUI had stopped freezing."""
    if usable_s is None:
        return None
    big_ends = [t for t, gap in stalls.stalls if gap >= 100.0]
    return round(max([usable_s, *big_ends]), 3)


def visible_structure_oids(win) -> list[int]:
    """Oids of rows on screen that have a structure to draw."""
    table = win.table
    proxy = table.model()
    if proxy is None or proxy.rowCount() == 0:
        return []
    top = table.rowAt(0)
    if top < 0:
        return []
    bottom = table.rowAt(max(0, table.viewport().height() - 1))
    if bottom < 0:
        bottom = proxy.rowCount() - 1
    model = win._table_model
    oids: list[int] = []
    for view_row in range(top, bottom + 1):
        source = proxy.mapToSource(proxy.index(view_row, 0))
        if not source.isValid():
            continue
        oid = int(model.row_oid(source.row()))
        if model.structure_text_for_oid(oid):
            oids.append(oid)
    return oids


def visible_structures_drawn(win) -> bool:
    """True once every on-screen row with a structure has a 2D image."""
    oids = visible_structure_oids(win)
    if not oids:
        return False
    model = win._table_model
    return all(model.structure_pixmap_for_oid(oid) is not None for oid in oids)


def table_revealed(win) -> bool:
    return win._table_stack.currentIndex() == 1


def peak_rss_mb() -> float:
    """Peak resident memory of this process, in MiB (0 when psutil is missing)."""
    try:
        import psutil
    except ImportError:
        return 0.0
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or info.rss
    return round(peak / (1024 * 1024), 1)


def make_window(*, show: bool = True, webengine: bool = True):
    """Build the main window the way ``molmanager.app`` does, sized like a real desktop."""
    import contextlib
    import sys

    from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

    if webengine:
        configure_qtwebengine_quiet_logs()
        with contextlib.suppress(ImportError):
            import PyQt5.QtWebEngineWidgets  # noqa: F401

    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.main_window.chemistry_workspace_window import ChemistryWorkspaceWindow
    from molmanager.workers.process_pool_utils import signal_application_shutdown

    app = QApplication.instance() or QApplication(sys.argv[:1])
    # Benchmarks quit without closing the window, which is where the app signals shutdown.
    app.aboutToQuit.connect(signal_application_shutdown)
    win = ChemistryWorkspaceWindow()
    win._suppress_exit_session_prompt = True
    if show:
        win.resize(1500, 900)
        win.show()
    return app, win


def emit_result(result: dict, json_path: str | None) -> None:
    """Print *result* and optionally write it as JSON for the runner."""
    print(json.dumps(result, indent=2))
    if json_path:
        os.makedirs(os.path.dirname(os.path.abspath(json_path)), exist_ok=True)
        with open(json_path, "w", encoding="utf-8") as fh:
            json.dump(result, fh, indent=2)
