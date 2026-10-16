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

"""Shared dock chrome and Color/Size Plot Options for analysis result maps."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent
from PyQt5.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..plotting.plot_marker_color import (
    PLOT_COLORSCALE_CHOICES,
    color_values_are_numeric,
    normalize_color_column,
    normalize_size_column,
    resolve_plot_colorscale,
)
from .dockable_plot import (
    PLOT_BODY_MARGINS,
    PLOT_BODY_SPACING,
    PlotTitlesControls,
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
from .plot_color_range_controls import PlotColorRangeControls
from .plot_on_hover_controls import PlotOnHoverControls
from .plot_size_controls import PlotSizeRangeControls


class DockableResultPlotPanel(QWidget):
    """
    Base for analysis result plots that dock beside the compound table.

    Subclasses build content above the footer and implement ``_rebuild_figure``.
    """

    dockable_in_workspace = True

    def __init__(
        self,
        parent_app: Any,
        *,
        window_title: str,
        floating_dialog_cls: type,
        default_color_hint: str = "",
        parent: QWidget | None = None,
        opts_title: str | None = None,
        opts_min_width: int = 520,
        opts_min_height: int = 360,
        opts_tooltip: str | None = None,
        pair_encoding: bool = True,
        defer_initial_reload: bool = False,
    ):
        super().__init__(parent)
        self.parent_app = parent_app
        self._window_title = window_title
        self._floating_dialog_cls = floating_dialog_cls
        self._default_color_hint = default_color_hint or ""
        self._pair_encoding = bool(pair_encoding)

        self._opts_panel = QWidget(self)
        opts = QVBoxLayout(self._opts_panel)
        opts.setContentsMargins(0, 0, 0, 0)
        opts.setSpacing(6)

        self._titles = PlotTitlesControls(self._opts_panel)
        self._titles.changed.connect(self._on_titles_changed)
        opts.addWidget(self._titles)

        color_row = QHBoxLayout()
        color_row.setSpacing(6)
        self._color_by_label = QLabel("Color by:")
        color_row.addWidget(self._color_by_label)
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(120)
        pair_note = (
            ". For pair points, numeric columns use the mean of both molecules."
            if self._pair_encoding
            else ""
        )
        self.color_combo.setToolTip(
            "Color markers by a table column. Leave as (none) for the plot’s default coloring"
            + (f" ({self._default_color_hint})" if self._default_color_hint else "")
            + pair_note
        )
        self.color_combo.currentIndexChanged.connect(self._on_color_column_changed)
        color_row.addWidget(self.color_combo, 1)
        self._spectrum_label = QLabel("Spectrum:")
        color_row.addWidget(self._spectrum_label)
        self.colorscale_combo = QComboBox()
        self.colorscale_combo.setMinimumWidth(100)
        self.colorscale_combo.addItems(PLOT_COLORSCALE_CHOICES)
        self.colorscale_combo.setToolTip("Continuous colorscale for numeric Color by columns.")
        self.colorscale_combo.currentIndexChanged.connect(self._on_color_column_changed)
        color_row.addWidget(self.colorscale_combo)
        self.color_range = PlotColorRangeControls()
        self.color_range.connect_changed(self._on_color_column_changed)
        color_row.addWidget(self.color_range)
        opts.addLayout(color_row)

        size_row = QHBoxLayout()
        size_row.setSpacing(6)
        self._size_by_label = QLabel("Size by:")
        size_row.addWidget(self._size_by_label)
        self.size_combo = QComboBox()
        self.size_combo.setMinimumWidth(120)
        size_note = (
            " For pair points, numeric columns use the mean of both molecules."
            if self._pair_encoding
            else ""
        )
        self.size_combo.setToolTip(
            "Size markers by a table column (numeric or categorical)." + size_note
        )
        self.size_combo.currentIndexChanged.connect(self._on_size_column_changed)
        size_row.addWidget(self.size_combo, 1)
        self.size_range = PlotSizeRangeControls()
        self.size_range.connect_changed(self._on_size_column_changed)
        size_row.addWidget(self.size_range)
        opts.addLayout(size_row)

        self._hover_controls = PlotOnHoverControls(self._opts_panel)
        self._hover_controls.changed.connect(self._on_hover_options_changed)
        self._hover_controls.persist_changed.connect(self._on_hover_persist_changed)
        opts.addWidget(self._hover_controls)

        self._trailing_opts_host = QWidget(self._opts_panel)
        self._trailing_opts_layout = QVBoxLayout(self._trailing_opts_host)
        self._trailing_opts_layout.setContentsMargins(0, 0, 0, 0)
        self._trailing_opts_layout.setSpacing(6)
        opts.addWidget(self._trailing_opts_host)
        opts.addStretch(1)

        self._opts_dialog = make_plot_options_dialog(
            self,
            self._opts_panel,
            title=opts_title or "Plot Options",
            min_width=opts_min_width,
            min_height=opts_min_height,
        )

        self._extra_opts_host = QWidget(self._opts_panel)
        self._extra_opts_layout = QVBoxLayout(self._extra_opts_host)
        self._extra_opts_layout.setContentsMargins(0, 0, 0, 0)
        self._extra_opts_layout.setSpacing(6)
        # Keep Titles first; subclass extras sit just below.
        opts.insertWidget(1, self._extra_opts_host)

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(*PLOT_BODY_MARGINS)
        self._root.setSpacing(PLOT_BODY_SPACING)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        self._opts_btn = make_plot_options_button(
            self,
            tooltip=opts_tooltip
            or "Configure Color by, Size by, On Hover, and other plot options.",
        )
        self._opts_btn.clicked.connect(self._open_plot_options)
        foot.addWidget(self._opts_btn)
        self._clear_sel_btn = make_clear_selection_button(self)
        self._clear_sel_btn.clicked.connect(self._clear_selection)
        foot.addWidget(self._clear_sel_btn)
        foot.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this plot beside the compound table.",
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

        if not defer_initial_reload:
            self._reload_color_columns()
            self._reload_hover_columns()
            self._update_spectrum_controls()
            self._update_size_controls()
            self._sync_footer_chrome()
            self.setMinimumWidth(self.embedded_minimum_width())

    def _finish_layout(self) -> None:
        """Call after subclass adds content widgets to ``self._root``."""
        if self._extra_opts_layout.count() == 0:
            self._extra_opts_host.hide()
        if self._trailing_opts_layout.count() == 0:
            self._trailing_opts_host.hide()
        # Floating chrome sits as a header; docked panes hide this bar.
        self._root.insertWidget(0, self._footer_bar)
        self._sync_hover_options_to_plot_view()
        self._sync_footer_chrome()

    def embedded_minimum_width(self) -> int:
        return 420

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), 640)

    def create_floating_dialog(self, parent_app: Any):
        return self._floating_dialog_cls(parent_app, panel=self)

    def _open_plot_options(self) -> None:
        show_plot_options_dialog(self._opts_dialog)

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        teardown = getattr(dlg, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if not dock(self):
            return
        if isinstance(dlg, self._floating_dialog_cls):
            dlg._panel = None
            dlg._force_close = True
            dlg.close()

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

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
        from .dockable_plot import sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), self._floating_dialog_cls)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_plot_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def event(self, event):  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def _reload_color_columns(self) -> None:
        prev = self.color_combo.currentText()
        prev_size = self.size_combo.currentText()
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self.color_combo.clear()
            self.color_combo.addItem("(none)")
            self.size_combo.clear()
            self.size_combo.addItem("(none)")
            app = self.parent_app
            if app is None:
                return
            model = getattr(app, "_table_model", None)
            if model is None:
                return
            headers = list(getattr(model, "_sorted_bounds_data_headers", lambda: [])())
            if not headers:
                headers = [h for h in getattr(app, "headers", []) if h and h != "ID"]
            for col in headers:
                self.color_combo.addItem(col)
                self.size_combo.addItem(col)
            idx = self.color_combo.findText(prev)
            if idx >= 0:
                self.color_combo.setCurrentIndex(idx)
            sidx = self.size_combo.findText(prev_size)
            if sidx >= 0:
                self.size_combo.setCurrentIndex(sidx)
        finally:
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        self._reload_hover_columns()

    def _reload_hover_columns(self) -> None:
        headers = list(getattr(self.parent_app, "headers", []) or []) if self.parent_app else []
        self._hover_controls.reload_columns(headers)
        self._sync_hover_options_to_plot_view()

    def _sync_hover_options_to_plot_view(self) -> None:
        self._hover_controls.apply_to_plot_view(getattr(self, "_plot_view", None))

    def _on_hover_options_changed(self) -> None:
        self._sync_hover_options_to_plot_view()

    def _on_hover_persist_changed(self) -> None:
        self._sync_hover_options_to_plot_view()

    def _update_spectrum_controls(self) -> None:
        enabled = self.color_combo.currentText() != "(none)"
        self._spectrum_label.setEnabled(enabled)
        self.colorscale_combo.setEnabled(enabled)
        numeric = False
        if enabled:
            # Probe with empty list → disable range until figure has points.
            sample = self._encoding_sample_values()
            numeric = color_values_are_numeric(sample) if sample else True
        self.color_range.set_enabled(enabled and numeric)
        self._update_size_controls()

    def _update_size_controls(self) -> None:
        self.size_range.set_enabled(self.size_combo.currentText() != "(none)")

    def _encoding_sample_values(self) -> list[Any] | None:
        """Optional subclass hook: sample Color-by values for numeric detection."""
        return None

    def _current_color_bounds(self) -> tuple[float | None, float | None]:
        return self.color_range.parse_bounds()

    def _current_size_bounds(self) -> tuple[float, float]:
        return self.size_range.parse_bounds()

    def _current_colorscale(self) -> str:
        return resolve_plot_colorscale(self.colorscale_combo.currentText())

    def _on_color_column_changed(self, _index: int = 0) -> None:
        self._update_spectrum_controls()
        self._rebuild_figure()

    def _on_size_column_changed(self, _index: int = 0) -> None:
        self._update_size_controls()
        self._rebuild_figure()

    def _column_values_for_oids(self, oids: list[int], color_col: str | None) -> list[Any] | None:
        if not color_col or color_col == "(none)" or self.parent_app is None:
            return None
        model = self.parent_app._table_model
        out: list[Any] = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row < 0:
                out.append(None)
                continue
            raw = model.value_for_header(row, color_col)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _column_values_for_oid_pairs(
        self,
        pairs: list[tuple[int, int]],
        color_col: str | None,
    ) -> list[Any] | None:
        """Per-pair values: mean of numeric partners, else left (oid_a) cell text."""
        if not color_col or color_col == "(none)" or self.parent_app is None:
            return None
        singles = self._column_values_for_oids(
            [oid for ab in pairs for oid in ab],
            color_col,
        )
        if singles is None:
            return None
        out: list[Any] = []
        for i, (oid_a, oid_b) in enumerate(pairs):
            va = singles[2 * i]
            vb = singles[2 * i + 1]
            fa = _try_float_cell(va)
            fb = _try_float_cell(vb)
            if fa is not None and fb is not None:
                out.append(0.5 * (fa + fb))
            elif fa is not None:
                out.append(fa)
            elif fb is not None:
                out.append(fb)
            else:
                out.append(va if va is not None else vb)
            _ = oid_a, oid_b
        return out

    def _resolved_encoding(
        self,
        *,
        oids: list[int] | None = None,
        oid_pairs: list[tuple[int, int]] | None = None,
    ) -> dict[str, Any]:
        """Build kwargs for figure builders from Color by / Size by controls."""
        color_col = self.color_combo.currentText()
        if color_col == "(none)":
            color_col = None
        size_col = self.size_combo.currentText()
        if size_col == "(none)":
            size_col = None

        if oid_pairs is not None:
            color_vals = self._column_values_for_oid_pairs(oid_pairs, color_col)
            size_vals = self._column_values_for_oid_pairs(oid_pairs, size_col)
        else:
            color_vals = self._column_values_for_oids(list(oids or []), color_col)
            size_vals = self._column_values_for_oids(list(oids or []), size_col)

        color_vals, color_col = normalize_color_column(color_vals, color_col)
        size_vals, size_col = normalize_size_column(size_vals, size_col)
        size_min_px, size_max_px = self._current_size_bounds()
        color_min, color_max = self._current_color_bounds()
        return {
            "color_values": color_vals,
            "color_label": color_col,
            "colorscale": self._current_colorscale(),
            "color_min": color_min,
            "color_max": color_max,
            "size_values": size_vals,
            "size_label": size_col,
            "size_min_px": size_min_px,
            "size_max_px": size_max_px,
            **self._titles.title_overrides(),
        }

    def _on_titles_changed(self) -> None:
        if getattr(self, "_plot_view", None) is not None:
            self._rebuild_figure()

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str | None) -> None:
        if not text:
            return
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _collect_encoding_chrome_state(self) -> dict[str, Any]:
        return {
            "color": self.color_combo.currentText(),
            "colorscale": self.colorscale_combo.currentText(),
            "color_min": self.color_range.color_min.text(),
            "color_max": self.color_range.color_max.text(),
            "size": self.size_combo.currentText(),
            "size_min": float(self.size_range.size_min.value()),
            "size_max": float(self.size_range.size_max.value()),
            **self._titles.title_overrides(),
            **self._hover_controls.collect_state(),
        }

    def _apply_encoding_chrome_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        self.color_combo.blockSignals(True)
        self.size_combo.blockSignals(True)
        try:
            self._set_combo_text(self.color_combo, state.get("color"))
            self._set_combo_text(self.colorscale_combo, state.get("colorscale"))
            self._set_combo_text(self.size_combo, state.get("size"))
        finally:
            self.color_combo.blockSignals(False)
            self.size_combo.blockSignals(False)
        cmin, cmax = state.get("color_min"), state.get("color_max")
        if isinstance(cmin, str):
            self.color_range.color_min.setText(cmin)
        if isinstance(cmax, str):
            self.color_range.color_max.setText(cmax)
        try:
            if state.get("size_min") is not None:
                self.size_range.size_min.setValue(float(state["size_min"]))
            if state.get("size_max") is not None:
                self.size_range.size_max.setValue(float(state["size_max"]))
        except (TypeError, ValueError):
            pass
        for edit, key in (
            (self._titles.plot_title_edit, "plot_title"),
            (self._titles.xaxis_title_edit, "xaxis_title"),
            (self._titles.yaxis_title_edit, "yaxis_title"),
            (self._titles.zaxis_title_edit, "zaxis_title"),
        ):
            val = state.get(key)
            if isinstance(val, str):
                edit.setText(val)
        self._hover_controls.apply_state(state)
        self._sync_hover_options_to_plot_view()
        self._update_spectrum_controls()
        self._update_size_controls()

    def _rebuild_figure(self) -> None:
        raise NotImplementedError

    def _schedule_plot(self) -> None:
        """Rebuild when table filters or cell values change."""
        self._rebuild_figure()

    def _clear_selection(self) -> None:
        raise NotImplementedError


def _try_float_cell(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v == v else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        v = float(text)
    except ValueError:
        return None
    return v if v == v else None
