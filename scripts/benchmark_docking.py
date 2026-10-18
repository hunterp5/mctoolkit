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

"""Benchmark plot dock/undock and splitter resize with real Qt WebEngine views.

Needs a real platform plugin (not ``offscreen``): windows open on screen while it runs.

Usage:
    python scripts/benchmark_docking.py
    python scripts/benchmark_docking.py samples/chembl_abl1.csv --plots 1 3 10 --cycles 5

Reported per scenario:
    call      synchronous main-thread time of the dock/undock call
    settled   call plus the time until the moved plot's renderer answers a JS round trip
    resize    main-thread time per splitter step while sweeping the plot pane width
    js        Plotly resize cost inside the page (``window.molmanagerPerfStats``)
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from pathlib import Path

if (os.environ.get("QT_QPA_PLATFORM") or "").lower().startswith("offscreen"):
    raise SystemExit("benchmark_docking needs a real display; unset QT_QPA_PLATFORM=offscreen.")

os.environ["MOLMANAGER_LAYOUT_PERF"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

configure_qtwebengine_quiet_logs()
import PyQt5.QtWebEngineWidgets  # noqa: E402,F401 — must load before QApplication

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from molmanager.ui.layout_perf import reset_spans, span_summary  # noqa: E402
from molmanager.ui.main_window import ChemistryWorkspaceWindow  # noqa: E402
from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE  # noqa: E402

#: p95 budgets in milliseconds (settled transition; main-thread time per resize step).
BUDGETS_MS = {
    "dock settled": 150.0,
    "undock settled": 150.0,
    "resize step": 33.0,
}


def _pump(ms: float) -> None:
    qapp = QApplication.instance()
    deadline = time.perf_counter() + ms / 1000.0
    while time.perf_counter() < deadline:
        qapp.processEvents()
        time.sleep(0.002)


def _pump_until(predicate, timeout_ms: float) -> bool:
    qapp = QApplication.instance()
    deadline = time.perf_counter() + timeout_ms / 1000.0
    while time.perf_counter() < deadline:
        qapp.processEvents()
        if predicate():
            return True
        time.sleep(0.002)
    return False


def _renderer_round_trip_ms(plot_widget, timeout_ms: float = 3000.0) -> float:
    """Milliseconds until the plot page answers a trivial script (renderer caught up)."""
    web = getattr(plot_widget, "web", None)
    if web is None:
        return 0.0
    done: list[bool] = []
    start = time.perf_counter()
    web.page().runJavaScript("1", lambda _r: done.append(True))
    _pump_until(lambda: bool(done), timeout_ms)
    return (time.perf_counter() - start) * 1000.0


def _js_perf_stats(plot_widget) -> dict:
    web = getattr(plot_widget, "web", None)
    if web is None:
        return {}
    box: list[object] = []
    web.page().runJavaScript(
        "window.molmanagerPerfStats ? window.molmanagerPerfStats() : '{}'",
        lambda r: box.append(r),
    )
    _pump_until(lambda: bool(box), 2000.0)
    try:
        return json.loads(str(box[0])) if box else {}
    except (TypeError, ValueError):
        return {}


def _reset_js_perf_stats(plot_widget) -> None:
    web = getattr(plot_widget, "web", None)
    if web is not None:
        web.page().runJavaScript("window.molmanagerResetPerfStats && molmanagerResetPerfStats();")


def _p95(ordered: list[float]) -> float:
    return ordered[min(len(ordered) - 1, round(0.95 * (len(ordered) - 1)))]


def _fmt(values: list[float], label: str = "") -> str:
    if not values:
        return "n/a"
    ordered = sorted(values)
    p95 = _p95(ordered)
    text = (
        f"p50={statistics.median(ordered):7.1f}  p95={p95:7.1f}  max={ordered[-1]:7.1f} ms"
        f"  (n={len(ordered)})"
    )
    budget = BUDGETS_MS.get(label)
    if budget is not None:
        text += f"  [{'PASS' if p95 <= budget else 'OVER'} budget {budget:.0f}]"
    return text


def _load_table(app: ChemistryWorkspaceWindow, path: Path) -> None:
    app.load_file(str(path))
    if not _pump_until(lambda: app._table_model.rowCount() > 0, 120_000):
        raise SystemExit(f"Table did not load from {path}")
    _pump(1500)


def _open_floating_plots(app: ChemistryWorkspaceWindow, count: int) -> list:
    widgets = []
    for _ in range(count):
        dlg = app._create_plot_dialog()
        dlg.show()
        widgets.append(dlg._plot_widget)
    _pump_until(lambda: all(getattr(w, "_web_ready", False) for w in widgets), 60_000)
    _pump(2500)
    return widgets


def _bench_dock_cycles(widgets: list, cycles: int) -> dict[str, list[float]]:
    results: dict[str, list[float]] = {
        "dock call": [],
        "dock settled": [],
        "undock call": [],
        "undock settled": [],
    }
    for _ in range(cycles):
        for widget in widgets:
            t0 = time.perf_counter()
            widget._add_to_main_window()
            call_ms = (time.perf_counter() - t0) * 1000.0
            results["dock call"].append(call_ms)
            results["dock settled"].append(call_ms + _renderer_round_trip_ms(widget))
            _pump(150)
        for widget in widgets:
            t0 = time.perf_counter()
            widget._send_to_new_window()
            call_ms = (time.perf_counter() - t0) * 1000.0
            results["undock call"].append(call_ms)
            results["undock settled"].append(call_ms + _renderer_round_trip_ms(widget))
            _pump(150)
    return results


def _bench_splitter_sweep(app: ChemistryWorkspaceWindow, widgets: list, steps: int) -> tuple:
    for widget in widgets:
        widget._add_to_main_window()
        _pump(100)
    _pump(800)
    mgr = app._workspace_layout
    splitter = mgr._splitters[0]
    total = sum(splitter.sizes())
    current = widgets[-1]
    _reset_js_perf_stats(current)
    _pump(50)
    step_ms: list[float] = []
    qapp = QApplication.instance()
    for i in range(steps):
        frac = 0.35 + 0.30 * (i % 30) / 29.0
        plot_w = int(total * frac)
        t0 = time.perf_counter()
        splitter.setSizes([total - plot_w, plot_w])
        qapp.processEvents()
        step_ms.append((time.perf_counter() - t0) * 1000.0)
        time.sleep(1 / 60)
    _pump(600)
    return step_ms, _js_perf_stats(current)


def _close_floating(widgets: list) -> None:
    for widget in widgets:
        win = widget.window()
        if win is not None and win is not widget and win.isWindow():
            win._force_close = True
            win.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark plot docking and resizing.")
    parser.add_argument("table", nargs="?", default="samples/chembl_abl1.csv")
    parser.add_argument("--plots", type=int, nargs="+", default=[1, 3, 10])
    parser.add_argument("--cycles", type=int, default=3)
    parser.add_argument("--steps", type=int, default=90)
    args = parser.parse_args()
    table_path = Path(args.table).expanduser()
    if not table_path.is_file():
        raise SystemExit(f"Table file not found: {table_path}")

    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    app = ChemistryWorkspaceWindow()
    app.resize(1600, 1000)
    app.show()
    _pump(500)
    _load_table(app, table_path)
    print(f"Table: {table_path}  rows={app._table_model.rowCount()}", flush=True)

    for count in args.plots:
        reset_spans()
        app.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
        _pump(300)
        widgets = _open_floating_plots(app, count)
        print(f"\n{count} plot(s), {args.cycles} dock/undock cycle(s)", flush=True)
        for label, values in _bench_dock_cycles(widgets, args.cycles).items():
            print(f"  {label:16s} {_fmt(values, label)}", flush=True)
        step_ms, js_stats = _bench_splitter_sweep(app, widgets, args.steps)
        print(f"  {'resize step':16s} {_fmt(step_ms, 'resize step')}", flush=True)
        recent = [float(v) for v in js_stats.get("recentMs") or []]
        print(f"  {'js resize':16s} {_fmt(recent)}", flush=True)
        for name, row in sorted(span_summary().items()):
            print(
                f"  span {name:28s} p50={row['p50']:7.1f}  p95={row['p95']:7.1f}"
                f"  max={row['max']:7.1f} ms  (n={int(row['count'])})",
                flush=True,
            )
        for widget in widgets:
            app.close_docked_plot(widget, confirm=False)
        _close_floating(widgets)
        _pump(500)

    app.setAttribute(Qt.WA_DeleteOnClose, False)
    app.hide()
    qapp.processEvents()
    # Skip interpreter teardown: destroying live Chromium views at exit is slow and noisy.
    os._exit(0)


if __name__ == "__main__":
    main()
