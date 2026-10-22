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

"""End-to-end offscreen UI workflow benchmark for large tables."""

from __future__ import annotations

import argparse
import csv
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PyQt5.QtWidgets import QApplication

from molmanager.ui.filters.cards import SubstructureFilterCard, TextFilterCard
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.workers.export_worker import ExportWorker


class _NoopEmitter:
    def emit(self, *_args, **_kwargs) -> None:
        return


class _NoopSignals:
    export_finished = _NoopEmitter()
    tool_progress = _NoopEmitter()


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, int(round((len(vals) - 1) * p))))
    return float(vals[idx])


def _write_table_csv(path: Path, n_rows: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["SMILES", "MW", "Note"])
        writer.writeheader()
        for i in range(n_rows):
            smi = "CCO" if i % 2 == 0 else "CCN"
            writer.writerow(
                {
                    "SMILES": smi,
                    "MW": f"{100.0 + ((i * 7) % 450):.3f}",
                    "Note": f"group_{i % 25}",
                }
            )


def _wait_until(done, *, timeout_s: float = 600.0) -> None:
    """Process Qt events until ``done()`` is true."""
    qapp = QApplication.instance()
    deadline = time.monotonic() + timeout_s
    while not done():
        if time.monotonic() > deadline:
            raise RuntimeError("timed out waiting for the workspace")
        qapp.processEvents()
        time.sleep(0.001)


def _ingest_idle(app: ChemistryWorkspaceWindow) -> bool:
    return not app._ingest_loading and not getattr(app, "_pending_batches", None)


def _open_session(app: ChemistryWorkspaceWindow, path: Path) -> None:
    if not app.apply_saved_session_from_file(str(path)):
        raise RuntimeError(f"could not open {path}")
    app._drain_pending_session_load(timeout_s=600.0)
    _wait_until(lambda: _ingest_idle(app))


def _build_export_snapshot(app: ChemistryWorkspaceWindow) -> dict[int, dict[str, str]]:
    cols = [h for h in app.headers if h not in ("ID_HIDDEN", "Structure")]
    h_map = {h: i for i, h in enumerate(app.headers)}
    out: dict[int, dict[str, str]] = {}
    for r in range(app._table_model.rowCount()):
        oid = app._table_model.row_oid(r)
        out[oid] = {h: app._export_cell_text(r, h_map[h]) for h in cols}
    return out


def _bench_one(scale: int) -> dict[str, float]:
    app = ChemistryWorkspaceWindow()
    # Measure load/filter/export; skip auto Render 2D so drain does not wait on paint.
    app._try_auto_render_all_structures_after_ingest = lambda: False
    tmp_dir = Path(tempfile.mkdtemp(prefix="MOLMANAGER_ui_bench_"))
    csv_path = tmp_dir / f"table_{scale}.csv"
    cms_path = tmp_dir / f"session_{scale}.cms"
    out_csv = tmp_dir / f"export_{scale}.csv"
    _write_table_csv(csv_path, scale)

    tracemalloc.start()
    t0 = time.perf_counter()
    app.load_file(str(csv_path))
    _wait_until(lambda: _ingest_idle(app) and app._table_model.rowCount() == scale)
    load_ms = (time.perf_counter() - t0) * 1000.0
    _cur_b, peak_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # .cms restore into the same window (avoids dual QMainWindow teardown crashes on Windows).
    if not app.save_session_to_path(str(cms_path)):
        raise RuntimeError(f"could not save {cms_path}")
    _wait_until(lambda: not getattr(app, "_session_save_pending", None))
    t0 = time.perf_counter()
    _open_session(app, cms_path)
    cms_load_ms = (time.perf_counter() - t0) * 1000.0
    if app._table_model.rowCount() != scale:
        raise RuntimeError(
            f".cms restore row count mismatch: got {app._table_model.rowCount()}, expected {scale}"
        )

    app.delete_all_filters_from_panel()
    text_card = TextFilterCard(["SMILES", "MW", "Note"], app)
    text_card.set_column("Note")
    text_card.text_edit.setText("group_7")
    app.filters = [text_card]
    t0 = time.perf_counter()
    app._apply_filters_impl_sync(None)
    text_filter_ms = (time.perf_counter() - t0) * 1000.0

    app.delete_all_filters_from_panel()
    ss_card = SubstructureFilterCard()
    ss_card.set_smarts("CO")
    app.filters = [ss_card]
    t0 = time.perf_counter()
    app._apply_filters_impl_sync(None)
    substructure_ms = (time.perf_counter() - t0) * 1000.0

    # Plot-like full-table numeric collect (avoids Plotly/WebEngine in offscreen CI).
    app.calculate_global_bounds()
    xi = app.headers.index("MW") if "MW" in app.headers else None
    t0 = time.perf_counter()
    fx: list[float] = []
    foids: list[int] = []
    model = app._table_model
    if xi is not None:
        for r in range(model.rowCount()):
            oid = int(model.row_oid(r))
            raw = (model.cell_text(r, xi) or "").strip()
            try:
                fx.append(float(raw))
                foids.append(oid)
            except ValueError:
                continue
    plot_collect_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    app._replot_active_plots()
    plot_replot_ms = (time.perf_counter() - t0) * 1000.0
    _ = (fx, foids)

    app.delete_all_filters_from_panel()
    app._search_panel.setVisible(True)
    app._populate_table_search_columns_combo()
    note_col = app.headers.index("Note")
    for j in range(app._search_col_combo.count()):
        if app._search_col_combo.itemData(j) == note_col:
            app._search_col_combo.setCurrentIndex(j)
            break
    app._search_partial_cb.setChecked(True)
    app._search_query_edit.setText('"group_11"')
    t0 = time.perf_counter()
    app._run_table_search()
    search_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    snap = _build_export_snapshot(app)
    export_snapshot_ms = (time.perf_counter() - t0) * 1000.0

    t0 = time.perf_counter()
    worker = ExportWorker(
        path=str(out_csv),
        ext=".csv",
        mols_dict=app.mols,
        headers_to_export=list(app.headers),
        table_data=snap,
        signals=_NoopSignals(),
        oids=list(app._table_model.all_oids_in_order()),
    )
    worker.run()
    export_write_ms = (time.perf_counter() - t0) * 1000.0

    qapp = QApplication.instance()
    if qapp is not None:
        qapp.processEvents()
    # Avoid hard-close after heavy session/filter churn (Qt teardown AV on Windows).
    try:
        app.hide()
    except Exception:
        pass

    return {
        "load_ms": load_ms,
        "cms_load_ms": cms_load_ms,
        "text_filter_ms": text_filter_ms,
        "substructure_ms": substructure_ms,
        "plot_collect_ms": plot_collect_ms,
        "plot_replot_ms": plot_replot_ms,
        "search_ms": search_ms,
        "export_snapshot_ms": export_snapshot_ms,
        "export_write_ms": export_write_ms,
        "peak_mem_mb": peak_b / (1024.0 * 1024.0),
    }


def _print_stats(label: str, samples: list[dict[str, float]], keys: tuple[str, ...]) -> None:
    print(f"\n{label}")
    for key in keys:
        vals = [float(s[key]) for s in samples]
        avg = statistics.fmean(vals)
        p50 = _percentile(vals, 0.50)
        p95 = _percentile(vals, 0.95)
        unit = "MB" if key.endswith("_mb") else "ms"
        print(f"  {key:18s} avg={avg:9.1f}{unit}  p50={p50:9.1f}{unit}  p95={p95:9.1f}{unit}")


def _bench_cms_file(cms_path: Path) -> dict[str, float]:
    """Time Open Session on an existing .cms (worker read, install and finalize)."""
    app = ChemistryWorkspaceWindow()
    app._try_auto_render_all_structures_after_ingest = lambda: False

    tracemalloc.start()
    t0 = time.perf_counter()
    _open_session(app, cms_path)
    open_ms = (time.perf_counter() - t0) * 1000.0
    _cur_b, peak_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    rows = int(app._table_model.rowCount())
    mols_n = len(getattr(app, "mols", {}) or {})
    qapp = QApplication.instance()
    if qapp is not None:
        qapp.processEvents()
    try:
        app.hide()
    except Exception:
        pass
    return {
        "cms_load_ms": open_ms,
        "peak_mem_mb": peak_b / (1024.0 * 1024.0),
        "rows": float(rows),
        "mols": float(mols_n),
        "file_mb": cms_path.stat().st_size / (1024.0 * 1024.0),
    }


def run_cms_benchmark(cms_path: Path, runs: int) -> None:
    _app = QApplication.instance() or QApplication([])
    samples = [_bench_cms_file(cms_path) for _ in range(runs)]
    first = samples[0]
    print(
        f"\nCMS: {cms_path}  "
        f"file={first['file_mb']:.1f}MB  rows={int(first['rows']):,}  mols={int(first['mols']):,}"
    )
    _print_stats(
        f"Runs: {runs}",
        samples,
        ("cms_load_ms", "peak_mem_mb"),
    )


def run_benchmark(scales: list[int], runs: int) -> None:
    _app = QApplication.instance() or QApplication([])
    for scale in scales:
        samples = [_bench_one(scale) for _ in range(runs)]
        _print_stats(
            f"Rows: {scale:,}",
            samples,
            (
                "load_ms",
                "cms_load_ms",
                "text_filter_ms",
                "substructure_ms",
                "plot_collect_ms",
                "plot_replot_ms",
                "search_ms",
                "export_snapshot_ms",
                "export_write_ms",
                "peak_mem_mb",
            ),
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="End-to-end UI workflow benchmark.")
    parser.add_argument("--runs", type=int, default=1, help="Runs per scale (default: 1)")
    parser.add_argument(
        "--cms",
        type=str,
        default="",
        help="Existing .cms to time (Open Session read + restore). Skips synthetic scales.",
    )
    parser.add_argument(
        "--scales",
        type=str,
        default="10000,50000,100000",
        help="Comma-separated row counts (default: 10000,50000,100000)",
    )
    args = parser.parse_args()
    if (args.cms or "").strip():
        cms_path = Path(args.cms).expanduser()
        if not cms_path.is_file():
            raise SystemExit(f"Session file not found: {cms_path}")
        run_cms_benchmark(cms_path, max(1, int(args.runs)))
        return
    scales = [max(100, int(x.strip())) for x in (args.scales or "").split(",") if x.strip()]
    run_benchmark(scales, max(1, int(args.runs)))


if __name__ == "__main__":
    main()
