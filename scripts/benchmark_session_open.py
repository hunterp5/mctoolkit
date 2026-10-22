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

"""Measure File > Open Session: time to a usable table, visible images, and GUI stalls.

A high-frequency QTimer records the gap between successive fires. When the GUI
thread is blocked, the timer cannot fire, so a large gap is a direct measure of
a freeze exactly as the user perceives it.

Usage:
    python scripts/benchmark_session_open.py samples/fda_approved.cms [--json out.json]
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


def session_busy(win) -> bool:
    """True while any phase of a session open is still running."""
    for name in (
        "_session_parse_busy",
        "_session_awaiting_ready",
    ):
        if getattr(win, name, False):
            return True
    for name in ("_session_restore_ctx", "_session_finalize_ctx"):
        if getattr(win, name, None) is not None:
            return True
    return False


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument(
        "--no-webengine",
        action="store_true",
        help="skip the QtWebEngine preload (Chromium can crash under offscreen Qt)",
    )
    ap.add_argument("--stall-ms", type=float, default=50.0)
    ap.add_argument("--max-s", type=float, default=300.0)
    ap.add_argument("--json", default=None, help="write the result to this path")
    args = ap.parse_args()

    app, win = make_window(webengine=not args.no_webengine)
    stalls = StallRecorder(threshold_ms=args.stall_ms)
    marks: dict[str, float] = {}
    state = {"done": False}

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
        if not table_revealed(win) or session_busy(win):
            return
        mark("usable")
        if visible_structures_drawn(win):
            mark("visible_drawn")
            finish()
        elif stalls.elapsed() - marks["usable"] > 30.0:
            finish()

    stalls.start()
    wd = QTimer()
    wd.setInterval(50)
    wd.timeout.connect(watchdog)
    wd.start()
    QTimer.singleShot(int(args.max_s * 1000), app.quit)
    QTimer.singleShot(0, lambda: win.apply_saved_session_from_file(args.path))
    app.exec_()

    result = {
        "benchmark": "session_open",
        "path": args.path,
        "rows": win._table_model.rowCount(),
        "completed": state["done"],
        "usable_s": marks.get("usable"),
        "visible_drawn_s": marks.get("visible_drawn"),
        "responsive_s": responsive_s(marks.get("usable"), stalls),
        "wall_s": marks.get("done"),
        "peak_rss_mb": peak_rss_mb(),
        **stalls.summary(),
    }
    emit_result(result, args.json)


if __name__ == "__main__":
    main()
