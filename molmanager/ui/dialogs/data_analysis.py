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

"""Table statistics dialog for the main window."""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import pandas as pd
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QMessageBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...analysis.table_statistics import (
    CURVE_MODELS,
    HYPOTHESIS_TESTS,
    OUTLIER_METHODS,
    TEST_ONE_SAMPLE_T,
    analyze_outlier_column,
    fit_xy_curve,
    format_numeric_summary,
    format_outlier_column_report,
    parse_percentiles,
    run_hypothesis_test,
)
from ..qt_widget_utils import make_window_minimizable
from ..table_dataframe import (
    numeric_subset,
    selected_table_column_headers,
    table_to_dataframe,
)
from .data_analysis_tabs import (
    CorrelationTab,
    CurveFitTab,
    OutliersTab,
    PercentilesTab,
    StatsTestsTab,
    SummaryTab,
)

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


class DataAnalysisDialog(QDialog):
    """Summarize, correlate, detect outliers, fit curves, and run tests on numeric columns."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_analysis_state(parent)
        self._build_analysis_ui()
        self._wire_analysis_ui()
        self._reload()
        self._sync_selected_columns_only_scope()
        self._wire_table_updates()
        make_window_minimizable(self)

    def _init_analysis_state(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.setWindowTitle("Statistics")
        self.resize(920, 680)
        self._df_raw = pd.DataFrame()
        self._df_num = pd.DataFrame()
        self._scoped_source_rows: list[int] = []
        self._last_outlier_table_rows: list[int] = []
        self._suppress_analysis_reload = False
        self._table_updates_wired = False
        self._reload_debounce = QTimer(self)
        self._reload_debounce.setSingleShot(True)
        self._reload_debounce.setInterval(80)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel

    def _build_analysis_ui(self) -> None:
        root = QVBoxLayout(self)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.chk_visible = QCheckBox("Visible Rows Only")
        self.chk_visible.setChecked(True)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        n_sel = self._initial_selected_row_count
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)

        self.chk_selected_columns = QCheckBox("Selected Columns Only")
        self._selected_columns_scope_prefix = "Selected Columns Only"
        self.chk_selected_columns.setToolTip(
            "Correlations and Percentiles use only numeric columns selected in the main table "
            "(click a column header to select a column; Ctrl+click to toggle; "
            "Shift+click for a range)."
        )
        self.chk_selected_columns.setEnabled(False)

        self._tab_summary = SummaryTab()
        self._tab_corr = CorrelationTab()
        self._tab_percentiles = PercentilesTab()
        self._tab_outliers = OutliersTab()
        self._tab_curve = CurveFitTab()
        self._tab_stats = StatsTestsTab()
        self.summary_text = self._tab_summary.summary_text
        self.corr_method = self._tab_corr.corr_method
        self.btn_corr = self._tab_corr.btn_corr
        self.corr_table = self._tab_corr.corr_table
        self.percentile_input = self._tab_percentiles.percentile_input
        self.btn_percentiles = self._tab_percentiles.btn_percentiles
        self.percentile_text = self._tab_percentiles.percentile_text
        self.outlier_method = self._tab_outliers.outlier_method
        self.outlier_col = self._tab_outliers.outlier_col
        self.outlier_iqr_k = self._tab_outliers.outlier_iqr_k
        self.outlier_z_abs = self._tab_outliers.outlier_z_abs
        self.outlier_mz_thr = self._tab_outliers.outlier_mz_thr
        self.btn_outliers = self._tab_outliers.btn_outliers
        self.btn_select_outliers = self._tab_outliers.btn_select_outliers
        self.outlier_text = self._tab_outliers.outlier_text
        self.fit_x = self._tab_curve.fit_x
        self.fit_y = self._tab_curve.fit_y
        self.fit_model = self._tab_curve.fit_model
        self.fit_poly_deg = self._tab_curve.fit_poly_deg
        self.btn_curve_fit = self._tab_curve.btn_curve_fit
        self.curve_text = self._tab_curve.curve_text
        self.stats_hint = self._tab_stats.stats_hint
        self.stats_test = self._tab_stats.stats_test
        self.stats_a = self._tab_stats.stats_a
        self.stats_b = self._tab_stats.stats_b
        self.stats_mean = self._tab_stats.stats_mean
        self.btn_stats = self._tab_stats.btn_stats
        self.stats_text = self._tab_stats.stats_text

        self.tabs.addTab(self._tab_summary, "Summary")
        self.tabs.addTab(self._tab_corr, "Correlations")
        self.tabs.addTab(self._tab_percentiles, "Percentiles")
        self.tabs.addTab(self._tab_outliers, "Outliers")
        self.tabs.addTab(self._tab_curve, "Curve Fit")
        self.tabs.addTab(self._tab_stats, "Statistical tests")

        bottom = QHBoxLayout()
        bottom.addWidget(self.chk_visible)
        bottom.addWidget(self.only_selected_cb)
        bottom.addWidget(self.chk_selected_columns)
        bottom.addStretch()
        root.addLayout(bottom)

    def _wire_analysis_ui(self) -> None:
        self._reload_debounce.timeout.connect(self._reload)
        self.chk_visible.stateChanged.connect(self._reload)
        self.only_selected_cb.stateChanged.connect(self._reload)
        self._tab_summary.copy_button.clicked.connect(self._copy_summary)
        self.btn_corr.clicked.connect(self._run_correlation)
        self.btn_percentiles.clicked.connect(self._run_percentiles)
        self.btn_outliers.clicked.connect(self._run_outliers)
        self.btn_select_outliers.clicked.connect(self._select_last_outliers_in_main_table)
        self.btn_curve_fit.clicked.connect(self._run_curve_fit)
        self.btn_stats.clicked.connect(self._run_stats_tests)

    def _wire_table_updates(self) -> None:
        """Keep scoped table data in sync when the main table, filters, or selection change."""
        if self._table_updates_wired or self.parent_app is None:
            return
        app = self.parent_app
        model = getattr(app, "_table_model", None)
        if model is None:
            return

        def _schedule_reload() -> None:
            if self._suppress_analysis_reload:
                return
            self._reload_debounce.start()

        model.dataChanged.connect(_schedule_reload)
        model.rowsInserted.connect(_schedule_reload)
        model.rowsRemoved.connect(_schedule_reload)
        model.modelReset.connect(_schedule_reload)
        model.layoutChanged.connect(_schedule_reload)
        model.headerDataChanged.connect(_schedule_reload)
        proxy = getattr(app, "_filter_proxy_model", None)
        if proxy is not None:
            proxy.layoutChanged.connect(_schedule_reload)
            proxy.modelReset.connect(_schedule_reload)
        sm = app.table.selectionModel()
        if sm is not None:
            sm.selectionChanged.connect(self._sync_selected_columns_only_scope)
        # Do not reload on selection changes — selecting outlier rows in the main table
        # must not clear the outlier log or cached row indices from the last Find run.
        self._table_updates_wired = True

    def _selected_table_column_headers(self) -> list[str]:
        app = self.parent_app
        if app is None:
            return []
        return selected_table_column_headers(app)

    def _sync_selected_columns_only_scope(self) -> None:
        """Enable Selected Columns Only when the main table has column(s) selected."""
        prefix = self._selected_columns_scope_prefix
        headers = self._selected_table_column_headers()
        n = len(headers)
        if n > 0:
            self.chk_selected_columns.setEnabled(True)
            self.chk_selected_columns.setText(f"{prefix} ({n} column(s))")
        else:
            self.chk_selected_columns.setEnabled(False)
            self.chk_selected_columns.setChecked(False)
            self.chk_selected_columns.setText(prefix)

    def _numeric_for_correlation_percentiles(self) -> pd.DataFrame | None:
        """
        Numeric columns for Correlations / Percentiles.

        Returns ``None`` when Selected Columns Only is checked but no usable columns remain.
        """
        df = self._df_num
        if not self.chk_selected_columns.isChecked():
            return df
        chosen = self._selected_table_column_headers()
        if not chosen:
            return None
        keep = [c for c in chosen if c in df.columns]
        if not keep:
            return None
        return df[keep]

    def refresh_table_data(self) -> None:
        """Reload the scoped DataFrame from the main table (immediate, not debounced)."""
        self._reload_debounce.stop()
        self._reload()

    def _reload(self) -> None:
        if self.parent_app is None:
            return
        vis = self.chk_visible.isChecked()
        only_sel = self.only_selected_cb.isChecked() and self.only_selected_cb.isEnabled()
        self._df_raw, self._scoped_source_rows = table_to_dataframe(
            self.parent_app, visible_only=vis, only_selected=only_sel
        )
        self._df_num = numeric_subset(self._df_raw, exclude_id=True)
        self._populate_fit_combos()
        self._run_summary()
        self._sync_selected_columns_only_scope()
        self.curve_text.clear()
        self.stats_text.clear()
        self.corr_table.setRowCount(0)
        self.corr_table.setColumnCount(0)
        self.percentile_text.clear()

    def _populate_fit_combos(self, *, refresh_outlier_col: bool = True) -> None:
        cols = list(self._df_num.columns)
        prev_outlier_col = self.outlier_col.currentText()
        for combo in (self.fit_x, self.fit_y, self.stats_a, self.stats_b):
            combo.clear()
            combo.addItems(cols)
        if refresh_outlier_col:
            self._repopulate_outlier_col_combo(cols, prev_outlier_col)
        if len(cols) >= 2:
            self.fit_y.setCurrentIndex(1)
            self.stats_b.setCurrentIndex(min(1, len(cols) - 1))

    def _run_summary(self) -> None:
        only_sel = self.only_selected_cb.isChecked() and self.only_selected_cb.isEnabled()
        empty_note = None
        if only_sel and self.parent_app is not None and not self.parent_app._selected_oids_set():
            empty_note = "Selected Rows Only is checked, but no rows are selected."
        self.summary_text.setPlainText(
            format_numeric_summary(self._df_raw, self._df_num, empty_selection_note=empty_note)
        )

    def _copy_summary(self) -> None:
        from PyQt5.QtWidgets import QApplication

        QApplication.clipboard().setText(self.summary_text.toPlainText())

    def _run_correlation(self) -> None:
        self.refresh_table_data()
        num = self._numeric_for_correlation_percentiles()
        if num is None:
            QMessageBox.information(
                self,
                "Correlations",
                "Selected Columns Only is checked, but no table columns are selected "
                "(click a column header in the main table; Ctrl+click to toggle; "
                "Shift+click for a range).",
            )
            self.corr_table.setRowCount(0)
            self.corr_table.setColumnCount(0)
            return
        if num.shape[1] < 2:
            QMessageBox.information(
                self,
                "Correlations",
                "Need at least two numeric columns with data. Try Calculate Descriptors or Calculator first.",
            )
            self.corr_table.setRowCount(0)
            self.corr_table.setColumnCount(0)
            return
        method = self.corr_method.currentText()
        try:
            corr = num.corr(method=method, numeric_only=True)
        except (TypeError, ValueError) as e:
            QMessageBox.warning(self, "Correlations", str(e))
            return
        self._fill_matrix_table(self.corr_table, corr)

    def _fill_matrix_table(self, table: QTableWidget, mat: pd.DataFrame) -> None:
        table.clear()
        labels = [str(x) for x in mat.columns]
        n = len(labels)
        table.setRowCount(n)
        table.setColumnCount(n)
        table.setHorizontalHeaderLabels(labels)
        table.setVerticalHeaderLabels(labels)
        for i in range(n):
            for j in range(n):
                v = mat.iloc[i, j]
                item = QTableWidgetItem("" if pd.isna(v) else f"{float(v):.6g}")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                table.setItem(i, j, item)

    def _run_percentiles(self) -> None:
        self.refresh_table_data()
        num = self._numeric_for_correlation_percentiles()
        if num is None:
            self.percentile_text.setPlainText(
                "Selected Columns Only is checked, but no table columns are selected "
                "(click a column header in the main table; Ctrl+click to toggle; "
                "Shift+click for a range)."
            )
            return
        if num.empty:
            self.percentile_text.setPlainText("No numeric columns.")
            return
        try:
            qs = parse_percentiles(self.percentile_input.text())
        except ValueError as e:
            QMessageBox.warning(self, "Percentiles", str(e))
            return
        try:
            res = num.quantile(q=qs, interpolation="linear")
        except (TypeError, ValueError) as e:
            QMessageBox.warning(self, "Percentiles", str(e))
            return
        buf = io.StringIO()
        res.to_csv(buf)
        self.percentile_text.setPlainText(buf.getvalue())

    def _repopulate_outlier_col_combo(self, cols: list[str], prev_choice: str) -> None:
        self.outlier_col.blockSignals(True)
        self.outlier_col.clear()
        self.outlier_col.addItem("All numeric columns")
        self.outlier_col.addItems(cols)
        if prev_choice == "All numeric columns" or prev_choice in cols:
            idx = self.outlier_col.findText(prev_choice)
            if idx >= 0:
                self.outlier_col.setCurrentIndex(idx)
        self.outlier_col.blockSignals(False)

    def _select_last_outliers_in_main_table(self) -> None:
        app = self.parent_app
        if app is None:
            return
        if not self._last_outlier_table_rows:
            QMessageBox.information(
                self,
                "Outliers",
                "Run Find outliers first, or no outliers were flagged in the last run.",
            )
            return
        self._suppress_analysis_reload = True
        try:
            app.select_table_rows(self._last_outlier_table_rows)
        finally:
            QTimer.singleShot(300, self._end_suppress_analysis_reload)

    def _end_suppress_analysis_reload(self) -> None:
        self._suppress_analysis_reload = False

    def _outlier_row_label(self, i: int) -> str:
        if 0 <= i < len(self._df_raw) and "ID_HIDDEN" in self._df_raw.columns:
            raw = self._df_raw.iloc[i]["ID_HIDDEN"]
            s = str(raw).strip()
            if s and s.lower() != "nan":
                return f"ID_HIDDEN={s}"
        return f"row_index={i + 1}"

    def _run_outliers(self) -> None:
        self.refresh_table_data()
        self._last_outlier_table_rows = []
        if self._df_num.empty:
            self.outlier_text.setPlainText("No numeric columns in the current scope.")
            return
        choice = self.outlier_col.currentText()
        all_cols = choice == "All numeric columns"
        cols = list(self._df_num.columns) if all_cols else [choice]
        if not all_cols and (not choice or choice not in self._df_num.columns):
            self.outlier_text.setPlainText("Pick a numeric column.")
            return
        if not cols:
            self.outlier_text.setPlainText("No numeric columns in the current scope.")
            return

        method = OUTLIER_METHODS[self.outlier_method.currentIndex()]
        k = float(self.outlier_iqr_k.value())
        z = float(self.outlier_z_abs.value())
        threshold = float(self.outlier_mz_thr.value())
        blocks: list[str] = []
        union_rows: set[int] = set()
        for col in cols:
            series = pd.to_numeric(self._df_num[col], errors="coerce").to_numpy(dtype=float)
            result = analyze_outlier_column(
                series, column=col, method=method, k=k, z=z, threshold=threshold
            )
            for irow in result.indices:
                if 0 <= irow < len(self._scoped_source_rows):
                    union_rows.add(self._scoped_source_rows[irow])
            blocks.append(
                format_outlier_column_report(
                    result, row_label=self._outlier_row_label, values=series
                )
            )
        self._last_outlier_table_rows = sorted(union_rows)
        self.outlier_text.setPlainText("\n\n".join(blocks).strip())

    def _run_curve_fit(self) -> None:
        self.refresh_table_data()
        xn = self.fit_x.currentText()
        yn = self.fit_y.currentText()
        if not xn or not yn or xn == yn:
            self.curve_text.setPlainText("Pick two different numeric columns.")
            return
        x = pd.to_numeric(self._df_num[xn], errors="coerce").to_numpy(dtype=float)
        y = pd.to_numeric(self._df_num[yn], errors="coerce").to_numpy(dtype=float)
        model = CURVE_MODELS[self.fit_model.currentIndex()]
        result = fit_xy_curve(
            x,
            y,
            model=model,
            x_name=xn,
            y_name=yn,
            degree=int(self.fit_poly_deg.value()),
        )
        self.curve_text.setPlainText(result.text)

    def _run_stats_tests(self) -> None:
        self.refresh_table_data()
        idx = self.stats_test.currentIndex()
        test = HYPOTHESIS_TESTS[idx]
        an = self.stats_a.currentText()
        bn = self.stats_b.currentText()

        def col(name: str):
            if name not in self._df_num.columns:
                return pd.Series(dtype=float).to_numpy(dtype=float)
            return pd.to_numeric(self._df_num[name], errors="coerce").to_numpy(dtype=float)

        hypothesized: float | None = None
        if test == TEST_ONE_SAMPLE_T:
            try:
                hypothesized = float((self.stats_mean.text() or "0").strip())
            except ValueError:
                self.stats_text.setPlainText("Enter a numeric hypothesized mean.")
                return
        result = run_hypothesis_test(
            col(an),
            col(bn) if bn else None,
            test=test,
            a_name=an,
            b_name=bn,
            hypothesized_mean=hypothesized,
        )
        self.stats_text.setPlainText("\n".join(result.lines))
