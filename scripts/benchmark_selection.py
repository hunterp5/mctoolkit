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

"""Benchmark table <-> plot selection sync with real Qt WebEngine plots.

Needs a real platform plugin (not ``offscreen``): windows open on screen while it runs.

Usage:
    python scripts/benchmark_selection.py
    python scripts/benchmark_selection.py --rows 20000 --plots 1 3 --sizes 1 100 1000 5000
    python scripts/benchmark_selection.py samples/chembl_abl1.csv --plots 1 3

Without a table path, a synthetic CSV with ``--rows`` rows (SMILES plus numeric X/Y) is used.

Scenarios (each repeated ``--repeats`` times per selection size):
    table->plots   row-header click + Shift+click range select (table row-selection controller)
    tool->plots    programmatic ``select_table_rows`` with scattered rows (search / tools path)
    plot->table    lasso on the first plot (bridge ``pointsSelected``) with scattered points
    drag           ``--drag-steps`` growing range selections 16 ms apart (one drag-select)

Reported per scenario:
    call      synchronous main-thread time of the triggering call
    table     plot->table only: time until the table reports the expected selected count
    settled   time until every plot has finished painting the new selection
    js        per-plot Plotly selection work (``window.molmanagerSelectionPerfStats``):
              queue = wait from molmanagerSetSelection to paint start (rAF / busy coalescing)
              restyle = selectedpoints / overlay restyle, relayout = axis-restore relayout
    drag      paints during the drag (per plot) and lag from the last step to the final paint
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import json
import os
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

if (os.environ.get("QT_QPA_PLATFORM") or "").lower().startswith("offscreen"):
    raise SystemExit("benchmark_selection needs a real display; unset QT_QPA_PLATFORM=offscreen.")

os.environ["MOLMANAGER_LAYOUT_PERF"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from molmanager.platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

configure_qtwebengine_quiet_logs()
import PyQt5.QtWebEngineWidgets  # noqa: E402,F401 — must load before QApplication

from PyQt5.QtCore import Qt  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

from molmanager.ui.layout_perf import reset_spans, span_summary  # noqa: E402
from molmanager.ui.main_window import ChemistryWorkspaceWindow  # noqa: E402

#: p95 targets in milliseconds for "settled" (100 ms is the usual "feels instant" bound).
BUDGETS_MS = {
    "table->plots settled": 100.0,
    "tool->plots settled": 100.0,
    "plot->table settled": 100.0,
}
_SYNTHETIC_SMILES = (
    "CCO",
    "c1ccccc1",
    "CC(=O)O",
    "CCN(CC)CC",
    "c1ccncc1",
    "CC(C)Cc1ccc(cc1)C(C)C(=O)O",
    "O=C(O)c1ccccc1O",
    "CN1C=NC2=C1C(=O)N(C(=O)N2C)C",
)
_SETTLE_TIMEOUT_MS = 10_000.0
_JS_KEYS = ("queueMs", "restyleMs", "relayoutMs", "paintMs")


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
        time.sleep(0.001)
    return False


def _run_js(widget, script: str, timeout_ms: float = 2000.0):
    box: list[object] = []
    widget.web.page().runJavaScript(script, lambda r: box.append(r))
    _pump_until(lambda: bool(box), timeout_ms)
    return box[0] if box else None


def _js_selection_stats(widget) -> dict:
    raw = _run_js(
        widget, "window.molmanagerSelectionPerfStats ? molmanagerSelectionPerfStats() : '{}'"
    )
    try:
        return json.loads(str(raw)) if raw else {}
    except (TypeError, ValueError):
        return {}


def _reset_js_selection_stats(widgets: list) -> None:
    for widget in widgets:
        _run_js(
            widget,
            "window.molmanagerResetSelectionPerfStats && molmanagerResetSelectionPerfStats(); 1",
        )


class _PaintWatcher:
    """Poll each plot's selection-paint counter without blocking the Qt event loop."""

    def __init__(self, widgets: list) -> None:
        self._widgets = widgets
        self._counts = [0] * len(widgets)
        self._in_flight = [False] * len(widgets)

    def _poll(self, i: int) -> None:
        if self._in_flight[i]:
            return
        self._in_flight[i] = True

        def _done(raw, idx=i) -> None:
            self._in_flight[idx] = False
            with contextlib.suppress(TypeError, ValueError, AttributeError):
                self._counts[idx] = int(json.loads(str(raw)).get("count", 0))

        self._widgets[i].web.page().runJavaScript(
            "window.molmanagerSelectionPerfStats ? molmanagerSelectionPerfStats() : '{}'", _done
        )

    def counts(self) -> list[int]:
        return list(self._counts)

    def poll_all(self) -> None:
        for i in range(len(self._widgets)):
            self._poll(i)

    def wait_until(self, minimum: list[int], timeout_ms: float) -> bool:
        def _ready() -> bool:
            pending = [i for i, need in enumerate(minimum) if self._counts[i] < need]
            for i in pending:
                self._poll(i)
            return not pending

        return _pump_until(_ready, timeout_ms)


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
        text += f"  [{'PASS' if p95 <= budget else 'OVER'} target {budget:.0f}]"
    return text


def _write_synthetic_table(rows: int, seed: int) -> Path:
    rng = random.Random(seed)
    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".csv", prefix="molmanager_selection_bench_", delete=False, newline=""
    )
    with handle:
        writer = csv.writer(handle)
        writer.writerow(["Name", "SMILES", "X", "Y"])
        for i in range(rows):
            writer.writerow(
                [
                    f"cmpd_{i}",
                    rng.choice(_SYNTHETIC_SMILES),
                    f"{rng.gauss(0.0, 1.0):.5f}",
                    f"{rng.gauss(0.0, 1.0):.5f}",
                ]
            )
    return Path(handle.name)


def _load_table(app: ChemistryWorkspaceWindow, path: Path) -> None:
    app.load_file(str(path))
    if not _pump_until(lambda: app._table_model.rowCount() > 0, 300_000):
        raise SystemExit(f"Table did not load from {path}")
    previous = -1
    while previous != app._table_model.rowCount():
        previous = app._table_model.rowCount()
        _pump(1000)
    _pump(1500)


def _open_plots(app: ChemistryWorkspaceWindow, count: int) -> list:
    """Open registered floating Plotters (``open_plot`` wires them into selection fan-out)."""
    widgets = []
    for _ in range(count):
        app.open_plot()
        widgets.append(app._plot_dialogs[-1]._plot_widget)
    _pump_until(lambda: all(getattr(w, "_web_ready", False) for w in widgets), 60_000)
    _pump_until(lambda: all(w._plotted_oids for w in widgets), 60_000)
    _pump(2500)
    for widget in widgets:
        if widget.web is None:
            raise SystemExit("Plot has no embedded web view; cannot benchmark selection paint.")
    return widgets


class _EchoCounter:
    """Count plot→Python selection events; during table-driven runs every one is an echo.

    Wraps each widget's bridge handlers (the bridge looks them up per call).
    """

    def __init__(self, widgets: list) -> None:
        self.count = 0
        for widget in widgets:
            for name in ("_on_plot_points_selected", "_on_plot_point_clicked"):
                original = getattr(widget, name)

                def _counted(*args, _original=original, **kwargs):
                    self.count += 1
                    return _original(*args, **kwargs)

                setattr(widget, name, _counted)


def _close_plots(widgets: list) -> None:
    for widget in widgets:
        win = widget.window()
        if win is not None and win is not widget and win.isWindow():
            win._force_close = True
            win.close()


def _clear_and_settle(app: ChemistryWorkspaceWindow, widgets: list) -> None:
    """Clear the selection and wait for the clear to paint so it cannot count as the next run."""
    _reset_js_selection_stats(widgets)
    app.clear_table_selection()
    # Plots that already showed no selection skip the paint; the timeout covers that case.
    _PaintWatcher(widgets).wait_until([1] * len(widgets), 2000.0)
    _pump(50)


def _user_select_range(app: ChemistryWorkspaceWindow, start: int, count: int) -> None:
    """Select view rows like a row-header click followed by a Shift+click."""
    controller = app.table.row_selection_controller()
    end = min(start + count, app.table.model().rowCount()) - 1
    if end < start:
        return
    controller.press_row(start, Qt.NoModifier)
    if end > start:
        controller.press_row(end, Qt.ShiftModifier)


def _collect_js(widgets: list, js: dict[str, list[float]]) -> None:
    for widget in widgets:
        stats = _js_selection_stats(widget)
        for key in _JS_KEYS:
            js[key].extend(float(v) for v in stats.get(key) or [])


def _bench_trigger(
    app: ChemistryWorkspaceWindow,
    widgets: list,
    trigger,
    *,
    expected_table_count: int | None = None,
) -> tuple[float, float | None, float | None]:
    """Run ``trigger`` once; return (call ms, table ms, settled ms)."""
    _reset_js_selection_stats(widgets)
    watcher = _PaintWatcher(widgets)
    t0 = time.perf_counter()
    trigger()
    call_ms = (time.perf_counter() - t0) * 1000.0
    table_ms: list[float] = []

    def _table_ready() -> bool:
        if expected_table_count is None or table_ms:
            return True
        if app._selected_row_count_fast() == expected_table_count:
            table_ms.append((time.perf_counter() - t0) * 1000.0)
            return True
        return False

    def _all_ready() -> bool:
        table_done = _table_ready()
        watcher.poll_all()
        return table_done and all(c >= 1 for c in watcher.counts())

    ok = _pump_until(_all_ready, _SETTLE_TIMEOUT_MS)
    settled = (time.perf_counter() - t0) * 1000.0 if ok else None
    return call_ms, (table_ms[0] if table_ms else None), settled


def _bench_size(
    app: ChemistryWorkspaceWindow,
    widgets: list,
    size: int,
    repeats: int,
    rng: random.Random,
) -> None:
    n_rows = app._table_model.rowCount()
    n_points = len(widgets[0]._plotted_oids)
    scenarios: dict[str, dict[str, list[float]]] = {}
    js: dict[str, dict[str, list[float]]] = {}
    timeouts: dict[str, int] = {}
    echoes: dict[str, int] = {}
    echo_counter = _EchoCounter(widgets)

    def _record(name: str, result: tuple[float, float | None, float | None]) -> None:
        if name != "plot->table":
            # Let any late echo from this run's paint arrive before counting.
            _pump(100)
            echoes[name] = echoes.get(name, 0) + echo_counter.count
        echo_counter.count = 0
        call_ms, table_ms, settled_ms = result
        bucket = scenarios.setdefault(name, {"call": [], "table": [], "settled": []})
        bucket["call"].append(call_ms)
        if table_ms is not None:
            bucket["table"].append(table_ms)
        if settled_ms is None:
            timeouts[name] = timeouts.get(name, 0) + 1
        else:
            bucket["settled"].append(settled_ms)
        _collect_js(widgets, js.setdefault(name, {k: [] for k in _JS_KEYS}))

    for _ in range(repeats):
        _clear_and_settle(app, widgets)
        echo_counter.count = 0
        start = rng.randrange(0, max(1, n_rows - size + 1))
        _record(
            "table->plots",
            _bench_trigger(app, widgets, lambda: _user_select_range(app, start, size)),
        )

        _clear_and_settle(app, widgets)
        echo_counter.count = 0
        rows = sorted(rng.sample(range(n_rows), min(size, n_rows)))
        _record("tool->plots", _bench_trigger(app, widgets, lambda: app.select_table_rows(rows)))

        _clear_and_settle(app, widgets)
        points = sorted(rng.sample(range(n_points), min(size, n_points)))
        expected = len({int(widgets[0]._plotted_oids[i]) for i in points})
        _record(
            "plot->table",
            _bench_trigger(
                app,
                widgets,
                lambda: widgets[0]._bridge.pointsSelected(json.dumps(points), False),
                expected_table_count=expected,
            ),
        )

    print(f"\n  selection size {size:,}", flush=True)
    for name, bucket in scenarios.items():
        print(f"    {name}", flush=True)
        print(f"      {'call':10s} {_fmt(bucket['call'])}", flush=True)
        if bucket["table"]:
            print(f"      {'table':10s} {_fmt(bucket['table'])}", flush=True)
        print(f"      {'settled':10s} {_fmt(bucket['settled'], f'{name} settled')}", flush=True)
        if timeouts.get(name):
            print(
                f"      ({timeouts[name]} run(s) did not settle within {_SETTLE_TIMEOUT_MS:.0f} ms)"
            )
        if name in echoes:
            print(f"      {'echoes':10s} {echoes[name]} plot event(s) sent back", flush=True)
        stats = js.get(name) or {}
        for key, label in (
            ("queueMs", "js queue"),
            ("restyleMs", "js restyle"),
            ("relayoutMs", "js relayout"),
            ("paintMs", "js total"),
        ):
            print(f"      {label:10s} {_fmt(stats.get(key) or [])}", flush=True)


def _bench_drag(app: ChemistryWorkspaceWindow, widgets: list, steps: int, step_rows: int) -> None:
    """Simulate one drag-select: the selection grows every frame; count live plot updates."""
    _clear_and_settle(app, widgets)
    _reset_js_selection_stats(widgets)
    fanouts: list[float] = []
    original_fanout = app._sync_active_plots_from_table_selection

    def _counted_fanout() -> None:
        fanouts.append(time.perf_counter())
        original_fanout()

    app._sync_active_plots_from_table_selection = _counted_fanout
    watcher = _PaintWatcher(widgets)
    try:
        for i in range(1, steps + 1):
            _user_select_range(app, 0, i * step_rows)
            _pump(16)
            watcher.poll_all()
        t_last = time.perf_counter()
        during_fanouts = len(fanouts)
        _pump(5)
        during = watcher.counts()
        ok = watcher.wait_until([c + 1 for c in during], _SETTLE_TIMEOUT_MS)
        lag_ms = (time.perf_counter() - t_last) * 1000.0
    finally:
        del app._sync_active_plots_from_table_selection
    _pump(500)
    totals = [int(_js_selection_stats(w).get("count", 0)) for w in widgets]
    lag_text = f"{lag_ms:7.1f} ms" if ok else f"did not settle within {_SETTLE_TIMEOUT_MS:.0f} ms"
    print(
        f"\n  drag ({steps} steps x {step_rows} rows, 16 ms apart)\n"
        f"    python fan-outs during drag:  {during_fanouts}"
        f" (+{len(fanouts) - during_fanouts} after)\n"
        f"    paints seen during drag:      {during}\n"
        f"    paints in total per plot:     {totals}\n"
        f"    last step -> final paint:     {lag_text}",
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark table <-> plot selection sync.")
    parser.add_argument(
        "table", nargs="?", default=None, help="CSV/SDF to load (default: synthetic)"
    )
    parser.add_argument("--rows", type=int, default=10_000, help="synthetic table rows")
    parser.add_argument("--plots", type=int, nargs="+", default=[1, 3])
    parser.add_argument("--sizes", type=int, nargs="+", default=[1, 100, 1000, 5000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--drag-steps", type=int, default=30)
    parser.add_argument("--drag-step-rows", type=int, default=5)
    parser.add_argument("--seed", type=int, default=1234)
    args = parser.parse_args()

    synthetic: Path | None = None
    if args.table:
        table_path = Path(args.table).expanduser()
        if not table_path.is_file():
            raise SystemExit(f"Table file not found: {table_path}")
    else:
        synthetic = _write_synthetic_table(args.rows, args.seed)
        table_path = synthetic

    rng = random.Random(args.seed)
    qapp = QApplication.instance() or QApplication(sys.argv[:1])
    app = ChemistryWorkspaceWindow()
    app.resize(1600, 1000)
    app.show()
    _pump(500)
    _load_table(app, table_path)
    n_rows = app._table_model.rowCount()
    print(f"Table: {table_path}  rows={n_rows:,}", flush=True)

    for count in args.plots:
        widgets = _open_plots(app, count)
        n_points = len(widgets[0]._plotted_oids)
        print(f"\n{count} plot(s), {n_points:,} points each, {args.repeats} repeat(s)", flush=True)
        reset_spans()
        for size in args.sizes:
            if size > min(n_rows, n_points):
                print(f"\n  selection size {size:,}: skipped (table/plot too small)", flush=True)
                continue
            _bench_size(app, widgets, size, args.repeats, rng)
        _bench_drag(app, widgets, args.drag_steps, args.drag_step_rows)
        print("\n  python spans", flush=True)
        for name, row in sorted(span_summary().items()):
            if not name.startswith("selection."):
                continue
            print(
                f"    {name:32s} p50={row['p50']:7.1f}  p95={row['p95']:7.1f}"
                f"  max={row['max']:7.1f} ms  (n={int(row['count'])})",
                flush=True,
            )
        _clear_and_settle(app, widgets)
        _close_plots(widgets)
        _pump(500)

    if synthetic is not None:
        with contextlib.suppress(OSError):
            synthetic.unlink()
    app.setAttribute(Qt.WA_DeleteOnClose, False)
    app.hide()
    qapp.processEvents()
    # Skip interpreter teardown: destroying live Chromium views at exit is slow and noisy.
    os._exit(0)


if __name__ == "__main__":
    main()
