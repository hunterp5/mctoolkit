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

"""Measure app startup through the real ``molmanager.app.main`` entry point.

Phases are timed from the first line of this script: importing ``molmanager.app``,
constructing ``QApplication``, and the first paint of the main window. The script
quits as soon as the window has painted. Run it in a fresh process each time; the
runner (``benchmark_file_ops.py``) also measures from process launch.

Usage:
    python scripts/benchmark_startup.py [--json out.json]
"""

import time

T_SCRIPT = time.perf_counter()
T_SCRIPT_WALL_NS = time.time_ns()

import argparse  # noqa: E402
import os  # noqa: E402
import sys  # noqa: E402

# The real platform plugin: offscreen Qt cannot host the WebEngine prewarm view, and
# startup should be measured the way the user sees it.
os.environ.setdefault("QT_QPA_PLATFORM", "windows" if sys.platform == "win32" else "xcb")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_HEAVY_MODULES = (
    "rdkit",
    "rdkit.Chem",
    "numpy",
    "scipy",
    "pandas",
    "sklearn",
    "torch",
    "plotly",
    "PyQt5.QtWebEngineWidgets",
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=None, help="write the result to this path")
    args = ap.parse_args()

    marks: dict[str, float] = {}

    def mark(name: str) -> None:
        marks.setdefault(name, round(time.perf_counter() - T_SCRIPT, 4))

    def report_and_exit() -> None:
        from bench_common import emit_result

        result = {
            "benchmark": "startup",
            "import_app_s": marks.get("import_app"),
            "qapplication_s": marks.get("qapplication"),
            "first_paint_s": marks.get("first_paint"),
            "window_build_s": (
                None
                if "first_paint" not in marks or "qapplication" not in marks
                else round(marks["first_paint"] - marks["qapplication"], 4)
            ),
            "script_start_wall_ns": T_SCRIPT_WALL_NS,
            "first_paint_wall_ns": marks.get("first_paint_wall_ns"),
            "heavy_modules_at_first_paint": [m for m in _HEAVY_MODULES if m in sys.modules],
        }
        emit_result(result, args.json)
        sys.stdout.flush()
        # Chromium may still be starting from the WebEngine prewarm; a normal Qt teardown
        # that early can crash, and nothing after first paint is being measured.
        os._exit(0)

    import molmanager.app as app_module

    mark("import_app")
    from PyQt5.QtCore import QEvent, QObject, QTimer
    from PyQt5.QtWidgets import QApplication, QMainWindow

    class _FirstPaintFilter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
            if event.type() == QEvent.Paint and "first_paint" not in marks:
                window = obj.window() if hasattr(obj, "window") else None
                if isinstance(window, QMainWindow):
                    mark("first_paint")
                    marks["first_paint_wall_ns"] = time.time_ns()
                    report_and_exit()
            return False

    class _TimedApplication(QApplication):
        def __init__(self, argv):
            super().__init__(argv)
            mark("qapplication")
            self._first_paint_filter = _FirstPaintFilter()
            self.installEventFilter(self._first_paint_filter)
            QTimer.singleShot(60_000, report_and_exit)

    app_module.QApplication = _TimedApplication
    app_module.main([sys.argv[0]])
    report_and_exit()


if __name__ == "__main__":
    main()
