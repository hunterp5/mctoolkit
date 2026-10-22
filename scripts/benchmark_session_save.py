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

"""Measure File > Save Session: GUI-thread cost, total time, and file size.

The input (a structure file or a ``.cms``) is opened first and allowed to finish
rendering, so the save includes every structure image the user would have.

Usage:
    python scripts/benchmark_session_save.py samples/fda_approved.cms --out bench/out.cms
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PyQt5.QtCore import QTimer  # noqa: E402

from bench_common import StallRecorder, emit_result, make_window, table_revealed  # noqa: E402
from benchmark_session_open import session_busy  # noqa: E402


def _input_busy(win) -> bool:
    if session_busy(win):
        return True
    if getattr(win, "_ingest_loading", False) or getattr(win, "_pending_batches", None):
        return True
    idle = getattr(win, "structure_render_idle", None)
    if callable(idle):
        return not idle()
    return bool(getattr(win, "_render2d_batch_active", False))


def _save_pending(win) -> bool:
    return bool(getattr(win, "_session_save_pending", None))


def _saved_size(path: str) -> int:
    saved = Path(path)
    return saved.stat().st_size if saved.is_file() else 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("path", help="structure file or .cms to open before saving")
    ap.add_argument("--out", default=None, help="where to write the session")
    ap.add_argument("--stall-ms", type=float, default=50.0)
    ap.add_argument("--max-s", type=float, default=600.0)
    ap.add_argument("--json", default=None, help="write the result to this path")
    args = ap.parse_args()

    out = args.out or os.path.join(tempfile.mkdtemp(prefix="bench_save_"), "out.cms")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    Path(out).unlink(missing_ok=True)
    app, win = make_window(webengine=False)
    stalls = StallRecorder(threshold_ms=args.stall_ms)
    state = {"phase": "opening", "settle": 0, "gui_s": 0.0, "t0": 0.0, "total_s": None}

    def watchdog() -> None:
        if state["phase"] == "opening":
            ready = table_revealed(win) and not _input_busy(win)
            state["settle"] = state["settle"] + 1 if ready else 0
            if state["settle"] < 4:
                return
            state["phase"] = "saving"
            stalls.reset()
            state["t0"] = time.perf_counter()
            win.save_session_to_path(out)
            state["gui_s"] = time.perf_counter() - state["t0"]
            return
        if state["phase"] == "saving" and not _save_pending(win):
            state["total_s"] = time.perf_counter() - state["t0"]
            state["phase"] = "done"
            QTimer.singleShot(200, app.quit)

    stalls.start()
    wd = QTimer()
    wd.setInterval(20)
    wd.timeout.connect(watchdog)
    wd.start()
    QTimer.singleShot(int(args.max_s * 1000), app.quit)
    opener = win.apply_saved_session_from_file if args.path.endswith(".cms") else win.load_file
    QTimer.singleShot(0, lambda: opener(args.path))
    app.exec_()

    result = {
        "benchmark": "session_save",
        "input": args.path,
        "out": out,
        "rows": win._table_model.rowCount(),
        "completed": state["phase"] == "done" and bool(getattr(win, "_session_save_last_ok", 0)),
        "gui_call_s": round(state["gui_s"], 3),
        "total_s": None if state["total_s"] is None else round(state["total_s"], 3),
        "bytes": _saved_size(out),
        **stalls.summary(),
    }
    emit_result(result, args.json)


if __name__ == "__main__":
    main()
