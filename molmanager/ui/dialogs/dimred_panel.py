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

"""Shared PCA / t-SNE / UMAP / SOM plot panel."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pandas as pd
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from ...platform_support.session_log import record_ui_log
from ..dockable_plot import (
    hide_plot_options_dialog,
    make_plot_options_dialog,
    show_plot_options_dialog,
)
from ...analysis.dimensionality_reduction import (
    EMBEDDING_PCA_DIM,
    EMBEDDING_PCA_DIM_MAX,
    DimensionReductionResult,
    is_fingerprint_bitcount_column,
    normalize_target_dimensions,
    subset_dimension_reduction_result,
)
from ...workers import SIMILARITY_FP_TYPE_LABELS
from ...workers.dimensionality_reduction import DimensionReductionSignals, DimensionReductionWorker
from ..table_dataframe import scoped_table_column_names, table_to_dataframe
from ...plotting.plot_marker_color import (
    color_values_are_numeric,
    normalize_color_column,
    normalize_size_column,
)
from ..dimred_plot import build_dimension_reduction_figure, dimension_reduction_result_with_color
from ..plotly_interactive_view import PlotlyInteractiveView
from ..plot_table_sync import retained_snapshot_oids
from ..result_plot_panel import DockableResultPlotPanel
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except ImportError:
    _HAS_WEB = False

_FP_NONE_LABEL = "None"


class DimensionReductionPanel(DockableResultPlotPanel):
    """PCA / t-SNE / UMAP / SOM panel; owns Send/Close when docked so all actions share one footer."""

    DIMRED_SESSION_KIND = "dimension_reduction"
    owns_docked_plot_actions = True

    def __init__(self, parent: ChemistryWorkspaceWindow | None, *, window_title: str, method: str):
        from .dimensionality_reduction import DimensionReductionDialog

        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._method = method
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._job_running = False
        self._last_result: DimensionReductionResult | None = None
        super().__init__(
            parent,
            window_title=window_title,
            floating_dialog_cls=DimensionReductionDialog,
            parent=None,
            opts_title=window_title,
            opts_min_width=640,
            opts_min_height=480,
            opts_tooltip="Configure titles, Color by, Size by, and On Hover.",
            pair_encoding=False,
            defer_initial_reload=True,
        )
        self._build_dimred_ui(parent)
        self._wire_dimred_ui(parent)
        self._refresh_structure_sources()
        self._reload_columns()
        self._on_fp_selection_changed()
        self._update_spectrum_controls()
        self._update_size_controls()
        self._finish_layout()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _build_dimred_ui(self, parent: ChemistryWorkspaceWindow | None) -> None:
        n_sel = self._initial_selected_row_count
        if _HAS_WEB and parent is not None:
            self._plot_view = PlotlyInteractiveView(parent, self)
            self._plot_view.setMinimumHeight(420)
            self._root.addWidget(self._plot_view, 1)
            self._plot_placeholder = None
        else:
            self._plot_view = None
            self._plot_placeholder = QLabel(
                "Install PyQtWebEngine to show the interactive plot in this window."
            )
            self._plot_placeholder.setWordWrap(True)
            self._plot_placeholder.setAlignment(Qt.AlignCenter)
            self._root.addWidget(self._plot_placeholder, 1)

        extras = self._extra_opts_layout
        extras.addWidget(self._build_features_group())
        extras.addWidget(self._build_scope_group(n_sel))

        method_box = QGroupBox("Method")
        method_layout = QVBoxLayout(method_box)
        method_layout.setSpacing(6)
        self._build_method_options(method_layout)
        extras.addWidget(method_box)
        extras.addWidget(self._build_preprocess_group())

        run_row = QHBoxLayout()
        run_row.setContentsMargins(0, 10, 0, 6)
        run_row.addStretch()
        self.run_btn = QPushButton(self._run_button_label())
        self.run_btn.setMinimumWidth(160)
        self.run_btn.setStyleSheet("QPushButton { padding: 8px 28px; }")
        run_row.addWidget(self.run_btn)
        run_row.addStretch()
        extras.addLayout(run_row)
        self._install_appearance_dialog()

    def _wire_dimred_ui(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.fp_combo.currentIndexChanged.connect(self._on_fp_selection_changed)
        self.target_dimensions.currentIndexChanged.connect(self._sync_target_dimension_controls)
        self.only_selected_cb.stateChanged.connect(self._reload_columns)
        self._sync_target_dimension_controls()
        if self._pca_preprocess_cb is not None:
            self._pca_preprocess_cb.toggled.connect(self._sync_pca_preprocess_controls)
            self._sync_pca_preprocess_controls()
        self.run_btn.clicked.connect(self._on_run)
        host = parent if parent is not None else self
        self._signals = DimensionReductionSignals(host)
        self._signals.finished.connect(self._on_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)

    def _ui_parent(self) -> QWidget:
        """Parent for alerts: the open setup or plot-settings dialog, else the plot window."""
        for opts in (
            getattr(self, "_appearance_dialog", None),
            getattr(self, "_opts_dialog", None),
        ):
            try:
                if opts is not None and opts.isVisible():
                    return opts
            except RuntimeError:
                continue
        win = self.window()
        try:
            if win is not None and win.isVisible():
                return win
        except RuntimeError:
            pass
        return self.parent_app or self

    def _plot_window_is_visible(self) -> bool:
        if self._is_docked_in_main_window():
            return True
        win = self.window()
        try:
            return win is not None and win is not self and win.isVisible()
        except RuntimeError:
            return False

    def reveal_plot_window(self) -> None:
        """Show the floating plot host once an embedding is ready."""
        self._hide_dimred_dialogs()
        if self._is_docked_in_main_window():
            return
        win = self.window()
        if win is None or win is self:
            return
        try:
            win.show()
            win.raise_()
            win.activateWindow()
        except RuntimeError:
            return

    def present_initial_ui(self) -> None:
        """Open embedding setup until a figure exists; then show the plot window."""
        if self._last_result is not None or self._is_docked_in_main_window():
            self.reveal_plot_window()
            return
        self._open_setup_dialog()

    def _calculating_status_text(self) -> str:
        return f"{self._window_title}: calculating…"

    def _close_options_for_run(self) -> None:
        """Hide setup and plot settings so progress is the main-window status line."""
        self._hide_dimred_dialogs()
        if self._plot_window_is_visible() or self.parent_app is None:
            return
        try:
            self.parent_app.raise_()
            self.parent_app.activateWindow()
        except RuntimeError:
            return

    def _show_calculating_status(self) -> None:
        """Tell the main window a dimred plot is running, without a percent."""
        app = self.parent_app
        if app is None:
            return
        message = self._calculating_status_text()
        job_id = getattr(self, "_bg_job_id", None)
        begin = getattr(app, "_begin_tool_progress", None)
        if job_id and callable(begin):
            # Negative total is indeterminate: status text only, no 0/N (pct%).
            begin(message, -1, job_id=job_id)
            return
        label = getattr(app, "status_label", None)
        if label is not None:
            label.setText(message)

    def _log_dimred_summary(self, summary: str) -> None:
        text = (summary or "").strip()
        if not text:
            return
        record_ui_log(f"{self._window_title}\n{text}")

    def _log_dimred_failure(self, message: str) -> None:
        detail = (message or "Computation failed.").strip()
        record_ui_log(f"{self._window_title}: {detail}", level=logging.ERROR)

    def _clear_selection(self) -> None:
        """Clear table and plot point selection."""
        if self._plot_view is not None:
            self._plot_view.clear_table_selection(update_plot=True)
        elif self.parent_app is not None:
            self.parent_app.clear_table_selection()

    def create_floating_dialog(self, parent_app: ChemistryWorkspaceWindow) -> QDialog:
        """Re-open this panel in a floating window after undocking from the main table."""
        from .dimensionality_reduction import DIMRED_FLOATING_DIALOGS

        return DIMRED_FLOATING_DIALOGS[self._method](parent_app, panel=self)

    def _run_button_label(self) -> str:
        labels = {
            "pca": "Run PCA",
            "tsne": "Run t-SNE",
            "umap": "Run UMAP",
            "som": "Run SOM",
        }
        return labels.get(self._method, "Run")

    def _build_features_group(self) -> QGroupBox:
        """Numeric columns, optional fingerprint, and the structure column that feeds it."""
        src_grp = QGroupBox("Features")
        src_ly = QVBoxLayout(src_grp)
        self.column_list = QListWidget()
        self.column_list.setMinimumWidth(220)
        self.column_list.setMinimumHeight(100)
        self.column_list.setMaximumHeight(180)
        src_ly.addWidget(self.column_list)

        fp_row = QHBoxLayout()
        fp_row.addWidget(QLabel("Fingerprint:"))
        self.fp_combo = QComboBox()
        self.fp_combo.addItem(_FP_NONE_LABEL)
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        self.fp_combo.setToolTip(
            "None: numeric columns only. Otherwise concatenate a 2D fingerprint bit vector."
        )
        fp_row.addWidget(self.fp_combo, 1)
        src_ly.addLayout(fp_row)
        struct_row = QHBoxLayout()
        struct_row.addWidget(QLabel("Structure from:"))
        self.struct_src_combo = QComboBox()
        struct_row.addWidget(self.struct_src_combo, 1)
        src_ly.addLayout(struct_row)
        return src_grp

    def _build_scope_group(self, n_selected: int) -> QGroupBox:
        """Row scope and the number of embedding axes. Both apply on the next Run."""
        scope = QGroupBox("Scope")
        form = QFormLayout(scope)
        self.target_dimensions = QComboBox()
        self.target_dimensions.addItem("2D", 2)
        self.target_dimensions.addItem("3D", 3)
        self.target_dimensions.setToolTip(
            "Embed into two or three dimensions. 3D draws a rotatable scatter. "
            "Run again after changing this."
        )
        form.addRow("Target Dimensions:", self.target_dimensions)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({n_selected} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow(self.only_selected_cb)
        return scope

    def _build_preprocess_group(self) -> QGroupBox:
        """Standardize, and for non-PCA methods an optional PCA compression step."""
        box = QGroupBox("Preprocess")
        layout = QVBoxLayout(box)
        self.standardize_cb = QCheckBox("Standardize features (zero mean, unit variance)")
        self.standardize_cb.setChecked(True)
        layout.addWidget(self.standardize_cb)

        self._pca_preprocess_cb: QCheckBox | None = None
        self._pca_dim_spin: QSpinBox | None = None
        self._pca_var_spin: QDoubleSpinBox | None = None
        self._pca_whiten_cb: QCheckBox | None = None
        self._pca_detail_host: QWidget | None = None
        if self._method == "pca":
            return box

        self._pca_preprocess_cb = QCheckBox("PCA-compress before embedding")
        self._pca_preprocess_cb.setChecked(True)
        self._pca_preprocess_cb.setToolTip(
            "Project wide inputs (typical fingerprints) to principal components "
            "before t-SNE / UMAP / SOM. On by default: faster, and local neighborhoods "
            "are usually preserved. Turn off to embed the raw features."
        )
        layout.addWidget(self._pca_preprocess_cb)

        self._pca_dim_spin = QSpinBox()
        self._pca_dim_spin.setRange(2, EMBEDDING_PCA_DIM_MAX)
        self._pca_dim_spin.setValue(EMBEDDING_PCA_DIM)
        self._pca_dim_spin.setToolTip(
            "Maximum principal components to keep. Compression runs when the matrix "
            "is wider than this, or when a variance target is set."
        )
        self._pca_var_spin = QDoubleSpinBox()
        self._pca_var_spin.setRange(0.0, 99.0)
        self._pca_var_spin.setDecimals(0)
        self._pca_var_spin.setSuffix(" %")
        self._pca_var_spin.setSpecialValueText("off")
        self._pca_var_spin.setValue(0)
        self._pca_var_spin.setToolTip(
            "Keep the fewest PCs that reach this explained variance, up to PCA components. "
            "Off uses the component count only."
        )
        self._pca_whiten_cb = QCheckBox("Whiten PCA components")
        self._pca_whiten_cb.setChecked(False)
        self._pca_whiten_cb.setToolTip(
            "Scale each kept component to unit variance (sklearn whiten)."
        )

        detail = QWidget(box)
        detail_form = QFormLayout(detail)
        detail_form.setContentsMargins(0, 0, 0, 0)
        detail_form.addRow("PCA components:", self._pca_dim_spin)
        detail_form.addRow("PCA min. variance:", self._pca_var_spin)
        detail_form.addRow(self._pca_whiten_cb)
        self._pca_detail_host = detail
        layout.addWidget(detail)
        return box

    def _install_appearance_dialog(self) -> None:
        """Move titles, markers, and hover into the plot-settings dialog.

        The setup dialog keeps features, method, and Run. Plot settings redraws the
        current figure and does not show those controls.
        """
        opts = self._opts_panel.layout()
        opts.removeWidget(self._titles)
        opts.removeWidget(self._markers_group)
        opts.removeWidget(self._hover_controls)

        panel = QWidget()
        body = QVBoxLayout(panel)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(6)
        body.addWidget(self._titles)
        body.addWidget(self._markers_group)
        body.addWidget(self._hover_controls)
        body.addStretch(1)
        self._appearance_dialog = make_plot_options_dialog(
            self,
            panel,
            title=f"{self._window_title} — Plot Options",
            min_width=640,
            min_height=280,
        )

    def _hide_dimred_dialogs(self) -> None:
        hide_plot_options_dialog(getattr(self, "_opts_dialog", None))
        hide_plot_options_dialog(getattr(self, "_appearance_dialog", None))

    def _open_setup_dialog(self) -> None:
        """Features, scope, method, and Run."""
        show_plot_options_dialog(self._opts_dialog)

    def _open_plot_options(self) -> None:
        """Titles, color, size, and hover for the current embedding."""
        show_plot_options_dialog(self._appearance_dialog)

    def _build_method_options(self, layout: QVBoxLayout) -> None:
        raise NotImplementedError

    def _method_params(self) -> dict:
        raise NotImplementedError

    def _embedding_pca_params(self) -> dict:
        """PCA preprocess kwargs for t-SNE / UMAP / SOM (``pca_dim`` 0 disables)."""
        if self._pca_preprocess_cb is None:
            return {}
        dim = (
            int(self._pca_dim_spin.value()) if self._pca_dim_spin is not None else EMBEDDING_PCA_DIM
        )
        on = bool(self._pca_preprocess_cb.isChecked())
        var_pct = float(self._pca_var_spin.value()) if self._pca_var_spin is not None else 0.0
        whiten = bool(self._pca_whiten_cb.isChecked()) if self._pca_whiten_cb is not None else False
        return {
            "pca_dim": dim if on else 0,
            "pca_components": dim,
            "pca_min_variance": (var_pct / 100.0) if on else 0.0,
            "pca_whiten": whiten if on else False,
        }

    def _sync_pca_preprocess_controls(self) -> None:
        on = self._pca_preprocess_cb is not None and self._pca_preprocess_cb.isChecked()
        for widget in (self._pca_dim_spin, self._pca_var_spin, self._pca_whiten_cb):
            if widget is not None:
                widget.setEnabled(on)
        if self._pca_detail_host is not None:
            self._pca_detail_host.setVisible(on)

    def _target_n_components(self) -> int:
        return normalize_target_dimensions(self.target_dimensions.currentData())

    def _sync_target_dimension_controls(self) -> None:
        is_3d = self._target_n_components() == 3
        self._titles.set_z_visible(is_3d)
        self._on_target_dimensions_changed(is_3d)

    def _on_target_dimensions_changed(self, is_3d: bool) -> None:
        """Subclass hook for controls that only apply in 3D."""
        return None

    def _apply_target_dimensions(self, params: dict) -> None:
        if "target_dimensions" not in params:
            return
        n = normalize_target_dimensions(params.get("target_dimensions"))
        idx = self.target_dimensions.findData(n)
        if idx >= 0:
            self.target_dimensions.setCurrentIndex(idx)
        self._sync_target_dimension_controls()

    def _job_method_params(self) -> dict:
        params = dict(self._method_params())
        params.update(self._embedding_pca_params())
        params["target_dimensions"] = self._target_n_components()
        return params

    def _apply_method_params(self, params: dict | None) -> None:
        return None

    def _apply_pca_preprocess_param(self, params: dict) -> None:
        cb = self._pca_preprocess_cb
        if cb is None:
            return
        if "pca_dim" in params:
            try:
                dim = int(params.get("pca_dim"))
            except (TypeError, ValueError):
                dim = None
            else:
                cb.setChecked(dim > 0)
        spin_val = params.get("pca_components", params.get("pca_dim"))
        if self._pca_dim_spin is not None and spin_val is not None:
            try:
                n = int(spin_val)
            except (TypeError, ValueError):
                n = 0
            if n > 0:
                self._pca_dim_spin.setValue(max(2, min(EMBEDDING_PCA_DIM_MAX, n)))
        if self._pca_var_spin is not None and "pca_min_variance" in params:
            try:
                frac = float(params.get("pca_min_variance") or 0)
            except (TypeError, ValueError):
                frac = 0.0
            if frac > 1.0:
                frac = frac / 100.0
            self._pca_var_spin.setValue(max(0.0, min(99.0, frac * 100.0)))
        if self._pca_whiten_cb is not None and "pca_whiten" in params:
            self._pca_whiten_cb.setChecked(bool(params.get("pca_whiten")))
        self._sync_pca_preprocess_controls()

    def collect_session_state(self) -> dict:
        from ...analysis.dimensionality_reduction import result_to_dict

        state: dict = {
            "kind": self.DIMRED_SESSION_KIND,
            "method": self._method,
            "features": self._selected_feature_columns(),
            "use_fingerprints": self._use_fingerprints(),
            "fingerprint": self.fp_combo.currentText(),
            "struct_src": self.struct_src_combo.currentText(),
            "standardize": bool(self.standardize_cb.isChecked()),
            "only_selected": bool(self.only_selected_cb.isChecked()),
            "method_params": dict(self._job_method_params()),
            **self._collect_encoding_chrome_state(),
        }
        if self._last_result is not None:
            state["result"] = result_to_dict(self._last_result)
            state["summary"] = self._last_result.summary
        return state

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        self._reload_columns()
        features = set(state.get("features") or [])
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            item.setCheckState(Qt.Checked if item.text() in features else Qt.Unchecked)
        self.fp_combo.blockSignals(True)
        self.struct_src_combo.blockSignals(True)
        try:
            self._set_combo_text(self.fp_combo, state.get("fingerprint"))
            self._set_combo_text(self.struct_src_combo, state.get("struct_src"))
        finally:
            self.fp_combo.blockSignals(False)
            self.struct_src_combo.blockSignals(False)
        if "standardize" in state:
            self.standardize_cb.setChecked(bool(state.get("standardize")))
        if "only_selected" in state:
            self.only_selected_cb.setChecked(bool(state.get("only_selected")))
        self._apply_encoding_chrome_state(state)
        params = state.get("method_params")
        if isinstance(params, dict):
            self._apply_method_params(params)
            self._apply_pca_preprocess_param(params)
            self._apply_target_dimensions(params)
        self._on_fp_selection_changed()
        raw_result = state.get("result")
        if isinstance(raw_result, dict):
            self._last_result = DimensionReductionResult(**raw_result)
            QTimer.singleShot(0, self._refresh_plot_colors)

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "DimensionReductionPanel":
        from .dimensionality_reduction import dimension_reduction_panel_from_session

        return dimension_reduction_panel_from_session(parent_app, state)

    def _use_fingerprints(self) -> bool:
        return self.fp_combo.currentText() != _FP_NONE_LABEL

    def _on_fp_selection_changed(self, *_args) -> None:
        use_fp = self._use_fingerprints()
        self.struct_src_combo.setEnabled(use_fp)
        if use_fp and not self._selected_feature_columns():
            self.standardize_cb.setToolTip(
                "When combined with fingerprints, only numeric columns are scaled; "
                "fingerprint bits are left unchanged."
            )
        else:
            self.standardize_cb.setToolTip("")

    def _refresh_structure_sources(self) -> None:
        self.struct_src_combo.clear()
        if self.parent_app is None:
            return
        self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _reload_columns(self) -> None:
        prev_color = self.color_combo.currentText()
        prev_size = self.size_combo.currentText()
        self.column_list.clear()
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            self.color_combo.addItem("(none)")
            self.size_combo.clear()
            self.size_combo.addItem("(none)")
            if self.parent_app is None:
                return
            self._refresh_structure_sources()
            only_sel = selection_scope_checked(self)
            all_cols, numeric_cols = scoped_table_column_names(
                self.parent_app, visible_only=False, only_selected=only_sel
            )
            for col in numeric_cols:
                item = QListWidgetItem(col)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                self.column_list.addItem(item)
            for col in all_cols:
                if col != "ID_HIDDEN":
                    self.color_combo.addItem(col)
                    self.size_combo.addItem(col)
            idx = self.color_combo.findText(prev_color)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
            sidx = self.size_combo.findText(prev_size)
            if sidx >= 0:
                self.size_combo.setCurrentIndex(sidx)
        finally:
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        self._reload_hover_columns()

    def _color_values_for_oids(self, oids: list[int], color_col: str | None) -> list[Any] | None:
        return self._column_values_for_oids(oids, color_col)

    def _size_values_for_oids(self, oids: list[int], size_col: str | None) -> list[Any] | None:
        return self._column_values_for_oids(oids, size_col)

    def _update_spectrum_controls(self) -> None:
        enabled = self.color_combo.currentText() != "(none)"
        self._spectrum_label.setEnabled(enabled)
        self.colorscale_combo.setEnabled(enabled)
        self.invert_spectrum_cb.setEnabled(enabled)
        numeric = False
        if enabled and self._last_result is not None:
            color_col = self.color_combo.currentText()
            vals = self._color_values_for_oids(self._last_result.oids, color_col)
            numeric = color_values_are_numeric(vals)
        self.color_range.set_enabled(enabled and numeric)
        self._update_size_controls()

    def _rebuild_figure(self) -> None:
        self._refresh_plot_colors()

    def _size_encoding_for_oids(
        self, oids: list[int]
    ) -> tuple[list[Any] | None, str | None, float, float]:
        size_col = self.size_combo.currentText()
        if size_col == "(none)":
            size_col = None
        size_vals = self._size_values_for_oids(oids, size_col)
        size_vals, size_label = normalize_size_column(size_vals, size_col)
        size_min_px, size_max_px = self._current_size_bounds()
        return size_vals, size_label, size_min_px, size_max_px

    def _displayed_dimred_result(self) -> DimensionReductionResult | None:
        if self._last_result is None:
            return None
        return subset_dimension_reduction_result(
            self._last_result,
            retained_snapshot_oids(self.parent_app, self._last_result.oids),
        )

    def _refresh_plot_colors(self) -> None:
        result = self._displayed_dimred_result()
        if result is None or self._plot_view is None or self._job_running:
            return
        if not result.oids:
            from plotly import graph_objects as go

            self._plot_view.push_figure(go.Figure(), [])
            return
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None
        color_vals = self._color_values_for_oids(result.oids, color_col)
        color_vals, color_col = normalize_color_column(color_vals, color_col)
        updated = dimension_reduction_result_with_color(
            result,
            color_values=color_vals,
            color_label=color_col,
        )
        try:
            color_min, color_max = self._current_color_bounds()
            size_vals, size_label, size_min_px, size_max_px = self._size_encoding_for_oids(
                updated.oids
            )
            fig = build_dimension_reduction_figure(
                updated,
                colorscale=self._current_colorscale(),
                color_min=color_min,
                color_max=color_max,
                size_values=size_vals,
                size_label=size_label,
                size_min_px=size_min_px,
                size_max_px=size_max_px,
                marker_opacity=self._markers_group.marker_opacity(),
                marker_symbol=self._markers_group.marker_symbol(),
                **self._titles.title_overrides(),
            )
            self._plot_view.push_figure(fig, list(updated.oids))
        except Exception as exc:
            QMessageBox.warning(self._ui_parent(), self._window_title, f"Plot failed: {exc}")

    def _selected_feature_columns(self) -> list[str]:
        cols: list[str] = []
        for i in range(self.column_list.count()):
            item = self.column_list.item(i)
            if item.checkState() == Qt.Checked:
                cols.append(item.text())
        return cols

    def _collect_table_payloads(self, src: str, only_selected: bool):
        """Fingerprint payloads for Run: all table rows; table filters only hide points at draw time."""
        app = self.parent_app
        assert app is not None
        return app.collect_scoped_table_structure_payloads(
            src,
            only_selected=only_selected,
            only_visible=False,
        )

    def _scoped_dataframe_and_oids(self) -> tuple[pd.DataFrame, list[int]]:
        """Feature rows for Run: full table (Selected Rows Only still applies)."""
        app = self.parent_app
        assert app is not None
        only_sel = selection_scope_checked(self)
        df, source_rows = table_to_dataframe(app, visible_only=False, only_selected=only_sel)
        oids: list[int] = []
        for r in source_rows:
            t0 = app._table_model.cell_text(r, 0)
            oids.append(int(t0) if t0.isdigit() else int(r))
        return df, oids

    def _on_run(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        self._last_result = None
        use_fp = self._use_fingerprints()
        features = self._selected_feature_columns()
        only_sel = selection_scope_checked(self)
        if only_sel and not self.parent_app._selected_oids_set():
            QMessageBox.warning(
                self._ui_parent(),
                self._window_title,
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return
        if not features and not use_fp:
            QMessageBox.warning(
                self._ui_parent(),
                self._window_title,
                "Select at least one numeric column and/or choose a fingerprint type.",
            )
            return
        if (
            features
            and len(features) == 1
            and is_fingerprint_bitcount_column(features[0])
            and not use_fp
        ):
            QMessageBox.warning(
                self._ui_parent(),
                self._window_title,
                f"The column “{features[0]}” stores only the number of on-bits, not the full "
                "fingerprint vector.\n\n"
                "Choose a fingerprint type other than None, or select multiple numeric columns.",
            )
            return
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None

        self._close_options_for_run()
        self._job_running = True
        self.run_btn.setEnabled(False)
        self._show_calculating_status()

        prep = {
            "use_fp": use_fp,
            "features": features,
            "only_sel": only_sel,
            "color_col": color_col,
            "struct_src": self.struct_src_combo.currentText() if use_fp else None,
            "method_params": dict(self._job_method_params()),
            "standardize": self.standardize_cb.isChecked(),
            "fingerprint": self.fp_combo.currentText() if use_fp else None,
        }
        QTimer.singleShot(0, lambda p=prep: self._launch_dimred_job(p))

    def _launch_dimred_job(self, prep: dict) -> None:
        """Build inputs then start the background worker."""
        if self.parent_app is None or not self._job_running:
            return
        use_fp = bool(prep.get("use_fp"))
        features = list(prep.get("features") or [])
        only_sel = bool(prep.get("only_sel"))
        color_col = prep.get("color_col")
        try:
            df, oids = self._scoped_dataframe_and_oids()
        except Exception as exc:
            self._reset_dimred_job_ui()
            QMessageBox.warning(self._ui_parent(), self._window_title, str(exc))
            return
        if df.empty:
            self._reset_dimred_job_ui()
            QMessageBox.information(
                self._ui_parent(), self._window_title, "No rows in the current scope."
            )
            return
        mol_payloads = None
        if use_fp:
            src = str(prep.get("struct_src") or "")
            mol_payloads = self._collect_table_payloads(src, only_sel)
            if len(mol_payloads) < 2 and not features:
                self._reset_dimred_job_ui()
                QMessageBox.information(
                    self._ui_parent(),
                    self._window_title,
                    "Need at least two rows with valid structures when using fingerprints alone.",
                )
                return
        params = {
            "method": self._method,
            "dataframe": df,
            "oids": oids,
            "feature_columns": features,
            "use_fingerprints": use_fp,
            "mol_payloads": mol_payloads,
            "fingerprint": prep.get("fingerprint"),
            "standardize": bool(prep.get("standardize", True)),
            "color_column": color_col,
            **dict(prep.get("method_params") or {}),
        }
        import threading

        from ..background_jobs import register_background_job

        self._bg_cancel_event = threading.Event()
        self._bg_job_id = f"dimred-{id(self)}"
        register_background_job(
            self.parent_app,
            self._bg_job_id,
            f"{self._window_title}…",
            cancel=self._bg_cancel_event.set,
        )
        self._show_calculating_status()
        worker = DimensionReductionWorker(params, self._signals, cancel_event=self._bg_cancel_event)
        self.parent_app.threadpool.start(worker)

    def _reset_dimred_job_ui(self) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        if self.parent_app is not None:
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(
                    self._window_title,
                    status_message=f"{self._window_title}: ready.",
                    job_id=job_id,
                )
            else:
                self.parent_app.status_label.setText(f"{self._window_title}: ready.")
        if not self._plot_window_is_visible():
            self._open_setup_dialog()

    def _clear_dimred_background_job(self) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        if job_id and self.parent_app is not None:
            from ..background_jobs import unregister_background_job

            unregister_background_job(self.parent_app, job_id)
        self._bg_job_id = None

    def _on_finished(self, result) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        self._log_dimred_summary(getattr(result, "summary", ""))
        self._last_result = result
        if self._plot_view is None:
            if self.parent_app is not None:
                finish = getattr(self.parent_app, "_finish_tool_progress", None)
                msg = f"{self._window_title}: done."
                if callable(finish):
                    finish(self._window_title, status_message=msg, job_id=job_id)
                else:
                    self.parent_app.status_label.setText(msg)
            self.reveal_plot_window()
            return
        self._refresh_plot_colors()
        self._update_spectrum_controls()
        self.reveal_plot_window()
        if self.parent_app is not None:
            shown = self._displayed_dimred_result()
            n = len(shown.oids) if shown is not None else 0
            select_hint = (
                "Click a point to select its table row."
                if result.z
                else "Lasso or click to select table rows."
            )
            msg = f"{self._window_title}: rendered {n:,} point(s). {select_hint}"
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(self._window_title, status_message=msg, job_id=job_id)
            else:
                self.parent_app.status_label.setText(msg)

    def _on_failed(self, message: str) -> None:
        job_id = getattr(self, "_bg_job_id", None)
        self._clear_dimred_background_job()
        self._job_running = False
        self.run_btn.setEnabled(True)
        if message == "Cancelled.":
            if self.parent_app is not None:
                msg = f"{self._window_title}: cancelled."
                finish = getattr(self.parent_app, "_finish_tool_progress", None)
                if callable(finish):
                    finish(self._window_title, status_message=msg, job_id=job_id)
                else:
                    self.parent_app.status_label.setText(msg)
            if not self._plot_window_is_visible():
                self._open_setup_dialog()
            return
        self._log_dimred_failure(message)
        if self.parent_app is not None:
            msg = f"{self._window_title}: failed."
            finish = getattr(self.parent_app, "_finish_tool_progress", None)
            if callable(finish):
                finish(self._window_title, status_message=msg, job_id=job_id)
            else:
                self.parent_app.status_label.setText(msg)
        if not self._plot_window_is_visible():
            self._open_setup_dialog()
        QMessageBox.warning(self._ui_parent(), self._window_title, message or "Computation failed.")
