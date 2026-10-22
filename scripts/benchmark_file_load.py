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

"""Measure File > Open: time to a usable table, visible images, and GUI-thread stalls.

A high-frequency QTimer records the gap between successive fires. When the GUI
thread is blocked, the timer cannot fire, so a large gap is a direct measure of
a freeze exactly as the user perceives it.

Usage:
    python scripts/benchmark_file_load.py samples/fda_approved.sdf [--no-render] [--json out.json]
"""

from __future__ import annotations

import argparse
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QTimer  # noqa: E402

from bench_common import (  # noqa: E402
    TAIL_S,
    StallRecorder,
    emit_result,
    make_window,
    peak_rss_mb,
    responsive_s,
    table_revealed,
    visible_structures_drawn,
)


def _ingest_busy(win) -> bool:
    return bool(getattr(win, "_ingest_loading", False)) or bool(
        getattr(win, "_pending_batches", None)
    )


def _render_busy(win) -> bool:
    idle = getattr(win, "structure_render_idle", None)
    if callable(idle):
        return not idle()
    return bool(getattr(win, "_render2d_batch_active", False))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--no-render", action="store_true", help="skip auto 2D render")
    ap.add_argument("--stall-ms", type=float, default=50.0)
    ap.add_argument("--max-s", type=float, default=300.0)
    ap.add_argument("--json", default=None, help="write the result to this path")
    args = ap.parse_args()

    if args.no_render:
        os.environ["MOLMANAGER_AUTO_RENDER_2D_MAX_ROWS"] = "0"

    app, win = make_window(webengine=False)
    stalls = StallRecorder(threshold_ms=args.stall_ms)
    marks: dict[str, float] = {}
    state = {"render_seen": False, "done": False}

    def mark(name: str) -> None:
        if name not in marks:
            marks[name] = round(stalls.elapsed(), 3)

    def finish() -> None:
        state["done"] = True
        mark("done")
        QTimer.singleShot(int(TAIL_S * 1000), app.quit)

    def watchdog() -> None:
        if state["done"]:
            return
        if _render_busy(win):
            state["render_seen"] = True
        usable = table_revealed(win) and not _ingest_busy(win)
        if not usable:
            return
        mark("usable")
        if args.no_render:
            finish()
            return
        if visible_structures_drawn(win):
            mark("visible_drawn")
        if state["render_seen"] and not _render_busy(win):
            mark("all_drawn")
        if "visible_drawn" in marks and "all_drawn" in marks:
            finish()
        elif not state["render_seen"] and stalls.elapsed() - marks["usable"] > 5.0:
            # Nothing was rendered (for example above the auto-render row cap).
            finish()

    stalls.start()
    wd = QTimer()
    wd.setInterval(50)
    wd.timeout.connect(watchdog)
    wd.start()
    QTimer.singleShot(int(args.max_s * 1000), app.quit)
    QTimer.singleShot(0, lambda: win.load_file(args.path))
    app.exec_()

    result = {
        "benchmark": "file_open",
        "path": args.path,
        "rows": win._table_model.rowCount(),
        "render": not args.no_render,
        "completed": state["done"],
        "usable_s": marks.get("usable"),
        "visible_drawn_s": marks.get("visible_drawn"),
        "all_drawn_s": marks.get("all_drawn"),
        "responsive_s": responsive_s(marks.get("usable"), stalls),
        "wall_s": marks.get("done"),
        "peak_rss_mb": peak_rss_mb(),
        **stalls.summary(),
    }
    emit_result(result, args.json)


if __name__ == "__main__":
    main()
