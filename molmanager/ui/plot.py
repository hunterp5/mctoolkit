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

"""Plot dialog: Plotly scatter linked to the main table."""

from __future__ import annotations

__all__ = [
    "AXIS_NONE",
    "PLOT_TYPE_BOX",
    "PLOT_TYPE_SCATTER",
    "PLOT_TYPE_HISTOGRAM",
    "PLOT_TYPE_HEATMAP",
    "PLOT_TYPE_LINE_2D",
    "PLOT_TYPE_RADAR",
    "PLOT_TYPE_VIOLIN",
    "PLOT_TYPE_CHOICES",
    "PLOT_SESSION_KIND",
    "PlotDialog",
    "PlotWidget",
    "compute_histogram_bin_edges",
    "infer_plot_mode",
    "normalize_axis_name",
    "oids_at_histogram_point_indices",
    "oids_in_histogram_bin",
    "resolve_plot_mode",
]

import tempfile
from pathlib import Path

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..plotting.plot_axes import (
    AXIS_NONE,
    PLOT_SESSION_KIND,
    PLOT_TYPE_BOX,
    PLOT_TYPE_CHOICES,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_RADAR,
    PLOT_TYPE_SCATTER,
    PLOT_TYPE_VIOLIN,
    compute_histogram_bin_edges,
    infer_plot_mode,
    normalize_axis_name,
    oids_at_histogram_point_indices,
    oids_in_histogram_bin,
    resolve_plot_mode,
)
from .dockable_plot import (
    PLOT_BODY_MARGINS,
    PLOT_BODY_SPACING,
    apply_plot_chrome_glyphs,
    make_add_to_main_button,
    make_clear_selection_button,
    make_close_plot_button,
    make_plot_options_button,
    make_plot_options_dialog,
    make_send_window_button,
    request_close_plot_widget,
    show_plot_options_dialog,
    sync_footer_on_parent_change,
)
from ..plotting.plot_marker_color import PLOT_COLORSCALE_CHOICES
from ..plotting.plot_radar import (
    MAX_RADAR_DISPLAY_ENTRIES,
    MAX_RADAR_TRACES,
    MAX_RADAR_VARIABLES,
    MIN_RADAR_VARIABLES,
    SPOKE_NONE,
)
from .plot_axis_mixin import PlotAxisMixin
from .plot_bridge import PlotBridge
from .plot_collect_mixin import PlotCollectMixin
from .plot_color_range_controls import PlotColorRangeControls
from .plot_dialog import PlotDialog
from .plot_on_hover_controls import PlotOnHoverControls
from .plot_radar_mixin import PlotRadarMixin
from .plot_render_mixin import PlotRenderMixin
from .plot_session_mixin import PlotSessionMixin
from .plot_shell_mixin import PlotShellMixin
from .plot_size_controls import PlotSizeRangeControls
from .plot_statistics_panel import PlotStatisticsPanel
from .plot_style_mixin import PlotStyleMixin
from .plot_web_surface import build_plot_web_view, no_web_surface


class PlotWidget(
    PlotRenderMixin,
    PlotShellMixin,
    PlotStyleMixin,
    PlotAxisMixin,
    PlotRadarMixin,
    PlotCollectMixin,
    PlotSessionMixin,
    QWidget,
):
    """Interactive Plotly plotter for numeric table columns (dialog or main-window panel).

    Mixin bases are a file-split of this widget; extract helpers, not new mixin bases.
    """

    # Color-by + Spectrum + Min/Max need ~640px; Statistics sits beside axes.
    _AXES_CONTROLS_MIN_WIDTH = 640
    _STATS_PANEL_MIN_WIDTH = 240
    owns_docked_plot_actions = True

    def __init__(self, parent_app=None):
        super().__init__(None)
        self.parent_app = parent_app
        self._init_plot_state()
        self._build_plot_ui()

    def _init_plot_state(self) -> None:
        self._plot_shell_path = (
            Path(tempfile.gettempdir()) / f"MOLMANAGER_plot_shell_{id(self)}.html"
        )
        self._last_browser_opened_path: str | None = None
        self._plotted_oids: list[int] = []
        self._oid_point_index: dict[int, list[int]] = {}
        self._selected_point_indices: set[int] = set()
        self._last_pushed_selection_key: tuple[int, int] | None = None
        self._web_ready = False
        self._pending_table_selection_sync = False
        self._pending_payload_json: str | None = None
        self._prev_range_axis: dict[str, str] = {"x": "", "y": "", "z": ""}
        self._ignore_plot_clear_until: float = 0.0
        self._hist_edges: list[float] = []
        self._hist_vals: list[float] = []
        self._hist_oids: list[int] = []
        self._heat_x: list[float] = []
        self._heat_y: list[float] = []
        self._heat_oids: list[int] = []
        self._heat_x_edges: list[float] = []
        self._heat_y_edges: list[float] = []
        self._radar_oids: list[int] = []

    def _build_plot_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(*PLOT_BODY_MARGINS)
        root.setSpacing(PLOT_BODY_SPACING)

        self._opts_panel = QWidget()
        opts_root = QVBoxLayout(self._opts_panel)
        opts_root.setContentsMargins(0, 0, 0, 0)
        opts_root.setSpacing(6)

        self._type_row_host = QWidget()
        type_row = QHBoxLayout(self._type_row_host)
        type_row.setContentsMargins(0, 0, 0, 0)
        type_row.setSpacing(6)
        type_row.addWidget(QLabel("Plot type:"))
        self.plot_type_combo = QComboBox()
        for label, key in PLOT_TYPE_CHOICES:
            self.plot_type_combo.addItem(label, key)
        self.plot_type_combo.setToolTip(
            "Scatter: 2D or 3D from X/Y/Z. Histogram: single-column distribution. "
            "Radar: compare 2–6 numeric spokes. Other types use a fixed chart style."
        )
        type_row.addWidget(self.plot_type_combo, 1)
        opts_root.addWidget(self._type_row_host)

        self.web = build_plot_web_view(self, minimum_height=420)
        plot_surface = self.web if self.web is not None else no_web_surface(self)

        ctrl_wrap = QWidget(self)
        ctrl_root = QVBoxLayout(ctrl_wrap)
        ctrl_root.setContentsMargins(0, 0, 0, 0)
        ctrl_root.setSpacing(4)

        range_edit_w = 76
        self.x_combo = QComboBox()
        self.y_combo = QComboBox()
        self.z_combo = QComboBox()
        self.xmin = QLineEdit()
        self.xmin.setFixedWidth(range_edit_w)
        self.xmax = QLineEdit()
        self.xmax.setFixedWidth(range_edit_w)
        self.ymin = QLineEdit()
        self.ymin.setFixedWidth(range_edit_w)
        self.ymax = QLineEdit()
        self.ymax.setFixedWidth(range_edit_w)
        self.zmin = QLineEdit()
        self.zmin.setFixedWidth(range_edit_w)
        self.zmax = QLineEdit()
        self.zmax.setFixedWidth(range_edit_w)
        self.hist_bin_width = QLineEdit()
        self.hist_bin_width.setFixedWidth(range_edit_w)
        self.hist_bin_width.setToolTip(
            "X-axis bin width for histogram or heatmap (empty = automatic)."
        )
        self.hist_bin_width.editingFinished.connect(self._schedule_plot)
        self.heatmap_y_bin_width_label = QLabel("Y bin width:")
        self.heatmap_y_bin_width = QLineEdit()
        self.heatmap_y_bin_width.setFixedWidth(range_edit_w)
        self.heatmap_y_bin_width.setToolTip("Y-axis bin width for heatmap (empty = automatic).")
        self.heatmap_y_bin_width.editingFinished.connect(self._schedule_plot)

        gb_axes = QGroupBox("Axes")
        axes_l = QVBoxLayout(gb_axes)
        axes_l.setSpacing(4)

        self.hist_bin_width_label = QLabel("Bin width:")
        self._x_axis_row = self._build_axis_row(
            "X",
            self.x_combo,
            self.xmin,
            self.xmax,
            extra_after_range=(self.hist_bin_width_label, self.hist_bin_width),
        )
        self._y_axis_row = self._build_axis_row(
            "Y",
            self.y_combo,
            self.ymin,
            self.ymax,
            extra_after_range=(self.heatmap_y_bin_width_label, self.heatmap_y_bin_width),
        )
        self._z_axis_row = self._build_axis_row("Z", self.z_combo, self.zmin, self.zmax)
        axes_l.addWidget(self._x_axis_row)
        axes_l.addWidget(self._y_axis_row)
        axes_l.addWidget(self._z_axis_row)

        cols = self._numeric_column_names()
        self.x_combo.addItems(cols)
        # Scatter needs X+Y; default Y to the second numeric column when available.
        y_default = cols[1] if len(cols) > 1 else AXIS_NONE
        self._set_axis_combo_items(self.y_combo, cols, previous=y_default, allow_none=True)
        self._populate_optional_axis_combo(self.z_combo, cols, AXIS_NONE)

        n_sel = len(self.parent_app._selected_logical_rows()) if self.parent_app is not None else 0
        self._plot_scope_has_selection = n_sel > 0
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._plot_scope_has_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)

        self.only_selected_cb.stateChanged.connect(self._schedule_plot)
        gb_options = QGroupBox("Options")
        options_l = QVBoxLayout(gb_options)
        options_l.setSpacing(4)
        options_l.addWidget(self.only_selected_cb)
        ctrl_root.addWidget(gb_options)

        self._hover_controls = PlotOnHoverControls()
        self.hover_structure_cb = self._hover_controls.hover_structure_cb
        self.hover_persist_cb = self._hover_controls.hover_persist_cb
        self._hover_combos = self._hover_controls._hover_combos
        self._hover_controls.changed.connect(self._schedule_plot)
        self._hover_controls.persist_changed.connect(self._on_hover_persist_changed)
        ctrl_root.addWidget(self._hover_controls)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_by_label = QLabel("Color by:")
        color_row.addWidget(self._color_by_label)
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(100)
        self.color_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.color_combo.setToolTip(
            "Color scatter and line points by a table column (numeric or categorical)."
        )
        self.color_combo.currentIndexChanged.connect(self._on_color_column_changed)
        color_row.addWidget(self.color_combo, 1)
        self._spectrum_label = QLabel("Spectrum:")
        color_row.addWidget(self._spectrum_label)
        self.colorscale_combo = QComboBox()
        self.colorscale_combo.setMinimumWidth(90)
        self.colorscale_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.colorscale_combo.addItems(PLOT_COLORSCALE_CHOICES)
        self.colorscale_combo.setToolTip("Continuous colorscale for numeric Color by columns.")
        self.colorscale_combo.currentIndexChanged.connect(self._schedule_plot)
        color_row.addWidget(self.colorscale_combo)
        self.color_range = PlotColorRangeControls()
        self.color_range.connect_changed(self._schedule_plot)
        color_row.addWidget(self.color_range, 0)
        axes_l.addLayout(color_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self._size_by_label = QLabel("Size by:")
        size_row.addWidget(self._size_by_label)
        self.size_combo = QComboBox()
        self.size_combo.setMinimumWidth(100)
        self.size_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.size_combo.setToolTip(
            "Size scatter and line points by a table column (numeric or categorical)."
        )
        self.size_combo.currentIndexChanged.connect(self._on_size_column_changed)
        size_row.addWidget(self.size_combo, 1)
        self.size_range = PlotSizeRangeControls()
        self.size_range.connect_changed(self._schedule_plot)
        size_row.addWidget(self.size_range, 0)
        axes_l.addLayout(size_row)

        analysis_row = QHBoxLayout()
        analysis_row.setSpacing(6)
        self._fit_label = QLabel("Fit:")
        analysis_row.addWidget(self._fit_label)
        self.fit_combo = QComboBox()
        self.fit_combo.setMinimumWidth(120)
        self.fit_combo.setToolTip(
            "Overlay a fit on 2D/line plots, or on histograms (Gaussian, log-normal, truncated Gaussian, or bin trends)."
        )
        self._refresh_fit_combo_items()
        self.fit_combo.currentIndexChanged.connect(self._on_fit_option_changed)
        analysis_row.addWidget(self.fit_combo)
        self.show_fit_formula_cb = QCheckBox("Show formula on plot")
        self.show_fit_formula_cb.setChecked(False)
        self.show_fit_formula_cb.setToolTip(
            "Draw the fit equation on the graph (also shown in the statistics panel)."
        )
        self.show_fit_formula_cb.stateChanged.connect(self._schedule_plot)
        analysis_row.addWidget(self.show_fit_formula_cb)
        trunc_bound_w = 64
        self._trunc_lower_label = QLabel("Trunc lower:")
        self._trunc_lower_label.setToolTip("Lower truncation bound (empty = no lower bound).")
        analysis_row.addWidget(self._trunc_lower_label)
        self.fit_trunc_lower = QLineEdit()
        self.fit_trunc_lower.setFixedWidth(trunc_bound_w)
        self.fit_trunc_lower.setPlaceholderText("—")
        self.fit_trunc_lower.setToolTip(self._trunc_lower_label.toolTip())
        self.fit_trunc_lower.editingFinished.connect(self._schedule_plot)
        analysis_row.addWidget(self.fit_trunc_lower)
        self._trunc_upper_label = QLabel("Trunc upper:")
        self._trunc_upper_label.setToolTip("Upper truncation bound (empty = no upper bound).")
        analysis_row.addWidget(self._trunc_upper_label)
        self.fit_trunc_upper = QLineEdit()
        self.fit_trunc_upper.setFixedWidth(trunc_bound_w)
        self.fit_trunc_upper.setPlaceholderText("—")
        self.fit_trunc_upper.setToolTip(self._trunc_upper_label.toolTip())
        self.fit_trunc_upper.editingFinished.connect(self._schedule_plot)
        analysis_row.addWidget(self.fit_trunc_upper)
        analysis_row.addStretch()
        axes_l.addLayout(analysis_row)

        self._axes_group = gb_axes
        ctrl_root.addWidget(gb_axes)

        gb_labels = QGroupBox("Titles")
        labels_l = QVBoxLayout(gb_labels)
        labels_l.setSpacing(4)
        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title_row.addWidget(QLabel("Plot title:"))
        self.plot_title_edit = QLineEdit()
        self.plot_title_edit.setPlaceholderText("Optional (empty = no title)")
        self.plot_title_edit.setToolTip("Overall figure title. Leave blank for no title.")
        self.plot_title_edit.editingFinished.connect(self._schedule_plot)
        title_row.addWidget(self.plot_title_edit, 1)
        labels_l.addLayout(title_row)
        axis_title_row = QHBoxLayout()
        axis_title_row.setSpacing(6)
        axis_title_row.addWidget(QLabel("X title:"))
        self.xaxis_title_edit = QLineEdit()
        self.xaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.xaxis_title_edit.setToolTip("Override the X-axis title. Empty keeps the column name.")
        self.xaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.xaxis_title_edit, 1)
        axis_title_row.addWidget(QLabel("Y title:"))
        self.yaxis_title_edit = QLineEdit()
        self.yaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.yaxis_title_edit.setToolTip("Override the Y-axis title. Empty keeps the column name.")
        self.yaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.yaxis_title_edit, 1)
        self._z_title_label = QLabel("Z title:")
        axis_title_row.addWidget(self._z_title_label)
        self.zaxis_title_edit = QLineEdit()
        self.zaxis_title_edit.setPlaceholderText("Auto (column name)")
        self.zaxis_title_edit.setToolTip(
            "Override the Z-axis title (3D scatter). Empty keeps the column name."
        )
        self.zaxis_title_edit.editingFinished.connect(self._schedule_plot)
        axis_title_row.addWidget(self.zaxis_title_edit, 1)
        labels_l.addLayout(axis_title_row)
        self._labels_group = gb_labels
        ctrl_root.addWidget(gb_labels)

        self._radar_host = QWidget()
        radar_ly = QVBoxLayout(self._radar_host)
        radar_ly.setContentsMargins(0, 0, 0, 0)
        radar_ly.setSpacing(6)
        spokes_gb = QGroupBox("Spokes (numeric columns)")
        spokes_ly = QVBoxLayout(spokes_gb)
        spoke_row = QHBoxLayout()
        spoke_row.setSpacing(6)
        self.spoke_combos: list[QComboBox] = []
        for i in range(MAX_RADAR_VARIABLES):
            spoke_row.addWidget(QLabel(f"{i + 1}:"))
            combo = QComboBox()
            combo.setToolTip(f"Spoke {i + 1}: choose a numeric column, or {SPOKE_NONE}.")
            combo.currentIndexChanged.connect(lambda _idx, n=i: self._on_radar_spoke_changed(n))
            self.spoke_combos.append(combo)
            spoke_row.addWidget(combo, 1)
        spokes_ly.addLayout(spoke_row)
        self.entry_edits: list[QLineEdit] = []
        for row_start in (0, 3):
            entries_row = QHBoxLayout()
            entries_row.setSpacing(6)
            for i in range(row_start, min(row_start + 3, MAX_RADAR_DISPLAY_ENTRIES)):
                entries_row.addWidget(QLabel(f"Entry {i + 1}:"))
                edit = QLineEdit()
                edit.setPlaceholderText("Row ID")
                edit.setToolTip(
                    "OID or 1-based table row number. Leave empty to plot all rows in scope."
                )
                edit.textChanged.connect(self._schedule_plot)
                self.entry_edits.append(edit)
                entries_row.addWidget(edit, 1)
            spokes_ly.addLayout(entries_row)
        hint = QLabel(
            f"Choose {MIN_RADAR_VARIABLES}–{MAX_RADAR_VARIABLES} different spoke columns. "
            f"Type up to {MAX_RADAR_DISPLAY_ENTRIES} row IDs to plot only those entries; "
            f"leave entry fields empty to plot every row in scope (up to {MAX_RADAR_TRACES:,}). "
            "Spoke values are min–max normalized across all rows in scope before plotting. "
            "Click a trace to select that row in the table."
        )
        hint.setWordWrap(True)
        spokes_ly.addWidget(hint)
        radar_ly.addWidget(spokes_gb)
        self._radar_host.hide()
        ctrl_root.addWidget(self._radar_host)

        self._controls_bottom = QSplitter(Qt.Horizontal)
        self._controls_bottom.setChildrenCollapsible(False)
        ctrl_wrap.setMinimumWidth(PlotWidget._AXES_CONTROLS_MIN_WIDTH)
        self._controls_bottom.addWidget(ctrl_wrap)
        self._stats_panel = PlotStatisticsPanel(self)
        self._stats_panel.setMinimumWidth(PlotWidget._STATS_PANEL_MIN_WIDTH)
        self._controls_bottom.addWidget(self._stats_panel)
        self._controls_bottom.setStretchFactor(0, 1)
        self._controls_bottom.setStretchFactor(1, 1)
        self._controls_bottom.setSizes(
            [PlotWidget._AXES_CONTROLS_MIN_WIDTH, PlotWidget._STATS_PANEL_MIN_WIDTH + 40]
        )
        opts_root.addWidget(self._controls_bottom, 1)

        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            min_width=720,
            min_height=420,
        )

        root.addWidget(plot_surface, 1)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip="Configure plot type, axes, titles, color, fit, and statistics.",
        )
        self._opts_btn.clicked.connect(self._open_plot_options)
        foot.addWidget(self._opts_btn)
        self._clear_sel_btn = make_clear_selection_button(self)
        self._clear_sel_btn.clicked.connect(self._on_clear_selection_clicked)
        foot.addWidget(self._clear_sel_btn)
        foot.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this plot beside the table in the main window (like the filter panel).",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked plot in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        self._close_plot_btn = make_close_plot_button(self)
        self._close_plot_btn.clicked.connect(self._close_docked_plot)
        foot.addWidget(self._close_plot_btn)
        root.insertWidget(0, self._footer_bar)
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

        self._bridge = PlotBridge(self)
        self._web_channel = None
        if self.web is not None:
            self._web_channel = QWebChannel(self.web.page())
            self._web_channel.registerObject("chemBridge", self._bridge)
            self.web.page().setWebChannel(self._web_channel)
            self.web.loadFinished.connect(self._on_web_load_finished)

        self._plot_debounce = QTimer(self)
        self._plot_debounce.setSingleShot(True)
        self._plot_debounce.timeout.connect(self.plot)

        self.plot_type_combo.currentIndexChanged.connect(self._on_plot_type_change)
        self.x_combo.currentIndexChanged.connect(self._on_axis_change)
        self.y_combo.currentIndexChanged.connect(self._on_axis_change)
        self.z_combo.currentIndexChanged.connect(self._on_axis_change)
        self.xmin.editingFinished.connect(self._schedule_plot)
        self.xmax.editingFinished.connect(self._schedule_plot)
        self.ymin.editingFinished.connect(self._schedule_plot)
        self.ymax.editingFinished.connect(self._schedule_plot)
        self.zmin.editingFinished.connect(self._schedule_plot)
        self.zmax.editingFinished.connect(self._schedule_plot)

        QTimer.singleShot(0, self._load_plot_shell)
        self._reload_color_columns()
        self._refresh_radar_spoke_columns()
        self._on_axis_change()
        parent_app = self.parent_app
        if parent_app is not None:
            model = parent_app._table_model
            model.rowsRemoved.connect(self._on_table_rows_changed)
            model.rowsInserted.connect(self._on_table_rows_changed)
            model.dataChanged.connect(self._on_table_data_changed)
            model.modelReset.connect(self._on_table_model_reset)
            model.columnsInserted.connect(self._on_table_columns_changed)
            model.columnsRemoved.connect(self._on_table_columns_changed)
            model.headerDataChanged.connect(self._on_table_header_data_changed)

    def _open_plot_options(self) -> None:
        """Open the plot configuration dialog (axes, titles, color, fit, statistics)."""
        show_plot_options_dialog(self._opts_dialog)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not self.parent_app.dock_plot_widget(self):
            return
        if isinstance(dlg, PlotDialog):
            dlg._plot_widget = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            self.parent_app.undock_plot_to_window(self)

    def _close_docked_plot(self) -> None:
        request_close_plot_widget(self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return getattr(app, "_docked_plot_widget", None) is self

    def _sync_footer_chrome(self) -> None:
        """Floating: opts + clear + Add. Docked: opts + clear + Send + Close Plot."""
        from .dockable_plot import sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), PlotDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_plot_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def _on_clear_selection_clicked(self) -> None:
        """Clear table and plot point selection from the footer button."""
        if self.parent_app is None:
            return
        self._clear_plot_table_selection(update_plot=True)
        if hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText("Plot: selection cleared.")

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def create_floating_dialog(self, parent_app) -> PlotDialog:
        """Re-open this plotter in a floating window after undocking from the main table."""
        return PlotDialog(parent_app, plot_widget=self)

    def embedded_minimum_width(self) -> int:
        """Minimum dock width for the figure (options open in a separate dialog)."""
        return 420

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 640)

    def _on_table_rows_changed(self, *_args) -> None:
        """Refresh plot when rows are added or removed."""
        if self._selected_point_indices:
            self._clear_plot_table_selection(update_plot=False)
        self._schedule_plot()

    def _on_table_data_changed(self, top_left=None, bottom_right=None, roles=()) -> None:
        """Refresh plot when cell values change (filters, descriptors, edits)."""
        from .compound_table_model import CompoundTableModel

        if CompoundTableModel.is_structure_paint_data_change(top_left, bottom_right, roles):
            return
        self._schedule_plot()

    def _on_table_model_reset(self, *_args) -> None:
        """Rows and columns may both change after a model reset."""
        self._on_table_columns_changed()

    def _on_table_columns_changed(self, *_args) -> None:
        """Repopulate axis combos when columns are inserted or removed."""
        self.refresh_axis_columns()

    def _on_table_header_data_changed(self, orientation, first: int, last: int) -> None:
        if int(orientation) == Qt.Horizontal:
            self.refresh_axis_columns()

    def refresh_axis_columns(self) -> None:
        """Sync X/Y/Z and radar spoke column lists with the table."""
        if self.parent_app is None:
            return
        cols = self._numeric_column_names()
        x_prev = self.x_combo.currentText()
        y_prev = self.y_combo.currentText()
        z_prev = self.z_combo.currentText()
        self._set_axis_combo_items(self.x_combo, cols, previous=x_prev, allow_none=False)
        self._set_axis_combo_items(self.y_combo, cols, previous=y_prev, allow_none=True)
        self._set_axis_combo_items(self.z_combo, cols, previous=z_prev, allow_none=True)
        self._prev_range_axis = {"x": "", "y": "", "z": ""}
        self._reload_color_columns()
        self._refresh_radar_spoke_columns()
        self._on_axis_change()

    def _schedule_plot(self) -> None:
        timer = getattr(self, "_plot_debounce", None)
        if timer is None:
            return
        timer.start(70)
