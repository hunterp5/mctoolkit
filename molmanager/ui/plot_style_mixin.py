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

"""Color, size, hover, and curve-fit controls for :class:`PlotWidget`."""

from __future__ import annotations

import json

from plotly import graph_objects as go

from ..plotting.plot_statistics_fits import (
    FIT_NONE,
    FIT_TRUNCATED_GAUSSIAN,
    HISTOGRAM_ONLY_FITS,
    PLOT_FIT_CHOICES,
    PLOT_FIT_CHOICES_XY,
    fit_histogram_curve,
    fit_xy_curve,
)
from ..plotting.plot_axes import (
    PLOT_TYPE_BOX,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_RADAR,
    PLOT_TYPE_SCATTER,
    PLOT_TYPE_VIOLIN,
)
from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_OPACITY,
    DEFAULT_MARKER_SIZE_PX,
    DEFAULT_MARKER_SYMBOL,
    attach_marker_size_legend,
    color_values_are_numeric,
    normalize_color_column,
    normalize_size_column,
    resolve_marker_symbol,
    resolve_plot_colorscale,
    scatter_marker_from_column_values,
)
from ..plotting.plot_labels import add_fit_formula_annotation, apply_plotly_label_overrides
from .plot_hover import hover_cards_payload


class PlotStyleMixin:
    """Marker styling, hover cards, and analysis/fit UI for the plotter."""

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
            if self.parent_app is not None:
                for h in self.parent_app.headers:
                    if h and h != "ID_HIDDEN":
                        self.color_combo.addItem(h)
                        self.size_combo.addItem(h)
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
        """Populate On Hover column pickers from current table headers."""
        headers = list(getattr(self.parent_app, "headers", []) or []) if self.parent_app else []
        self._hover_controls.reload_columns(headers)

    def _selected_hover_columns(self) -> list[str]:
        return self._hover_controls.selected_columns()

    def _hover_card_json_for_point(self, point_index: int) -> str:
        if point_index < 0 or point_index >= len(self._plotted_oids):
            return ""
        oid = int(self._plotted_oids[point_index])
        show_struct = bool(
            getattr(self, "hover_structure_cb", None) and self.hover_structure_cb.isChecked()
        )
        payload = hover_cards_payload(
            self.parent_app,
            [oid],
            self._selected_hover_columns(),
            show_structure=show_struct,
        )
        return json.dumps(payload, separators=(",", ":"))

    def _hover_card_json_for_points(self, indices_json: str) -> str:
        try:
            raw = json.loads(indices_json or "[]")
            idxs = [int(x) for x in raw if isinstance(x, (int, float))]
        except Exception:
            idxs = []
        oids: list[int] = []
        n = len(self._plotted_oids)
        for i in idxs:
            if 0 <= i < n:
                oids.append(int(self._plotted_oids[i]))
        if not oids:
            return ""
        show_struct = bool(
            getattr(self, "hover_structure_cb", None) and self.hover_structure_cb.isChecked()
        )
        payload = hover_cards_payload(
            self.parent_app,
            oids,
            self._selected_hover_columns(),
            show_structure=show_struct,
        )
        return json.dumps(payload, separators=(",", ":"))

    def _on_hover_persist_changed(self, *_args) -> None:
        self._sync_hover_persist_visual()

    def _sync_hover_persist_visual(self) -> None:
        if not self._web_ready:
            return
        persist = bool(
            getattr(self, "hover_persist_cb", None) and self.hover_persist_cb.isChecked()
        )
        self.web.page().runJavaScript(
            f"window.molmanagerSetHoverPersist && molmanagerSetHoverPersist({json.dumps(persist)});"
        )
        if not persist:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        from .plot_hover import HOVER_MULTI_MAX_ITEMS

        n_sel = len(self._selected_point_indices)
        if n_sel == 0 or n_sel > HOVER_MULTI_MAX_ITEMS:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        idxs = sorted(self._selected_point_indices)
        js_idxs = json.dumps(idxs)
        self.web.page().runJavaScript(
            f"window.molmanagerPinHoverPoints && molmanagerPinHoverPoints({json.dumps(js_idxs)});"
        )

    def _attach_point_hover(self, trace_kwargs: dict, oids: list[int]) -> dict:
        """Disable native Plotly hover labels; custom overlay uses OIDs via the bridge."""
        out = dict(trace_kwargs)
        out["customdata"] = [[int(oid)] for oid in oids]
        out["hoverinfo"] = "none"
        return out

    def _current_color_column(self) -> str | None:
        text = self.color_combo.currentText()
        return None if not text or text == "(none)" else text

    def _current_size_column(self) -> str | None:
        text = self.size_combo.currentText()
        return None if not text or text == "(none)" else text

    def _column_values_for_oids(self, oids: list[int], column: str | None) -> list | None:
        if not column or self.parent_app is None:
            return None
        model = self.parent_app._table_model
        out: list = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row < 0:
                out.append(None)
                continue
            raw = model.value_for_header(row, column)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _color_values_for_oids(self, oids: list[int]) -> tuple[list | None, str | None]:
        color_col = self._current_color_column()
        if not color_col:
            return None, None
        return self._column_values_for_oids(oids, color_col), color_col

    def _size_values_for_oids(self, oids: list[int]) -> tuple[list | None, str | None]:
        size_col = self._current_size_column()
        if not size_col:
            return None, None
        return self._column_values_for_oids(oids, size_col), size_col

    def _marker_opacity(self) -> float:
        group = getattr(self, "_markers_group", None)
        if group is None:
            return DEFAULT_MARKER_OPACITY
        return float(group.marker_opacity())

    def _marker_symbol(self, *, scatter3d: bool = False) -> str:
        group = getattr(self, "_markers_group", None)
        raw = DEFAULT_MARKER_SYMBOL if group is None else group.marker_symbol()
        return resolve_marker_symbol(raw, scatter3d=scatter3d)

    def _marker_style_supported(self) -> bool:
        """True when the current plot type draws point markers."""
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_LINE_2D, PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
            return True
        if ptype == PLOT_TYPE_SCATTER:
            return self._effective_plot_mode() in ("2D", "3D")
        return False

    def _scatter_marker_for_oids(
        self,
        oids: list[int],
        *,
        point_size: float = DEFAULT_MARKER_SIZE_PX,
        scatter3d: bool = False,
    ) -> dict:
        color_vals, color_label = self._color_values_for_oids(oids)
        color_vals, color_label = normalize_color_column(color_vals, color_label)
        size_vals, size_label = self._size_values_for_oids(oids)
        size_vals, size_label = normalize_size_column(size_vals, size_label)
        color_min, color_max = self.color_range.parse_bounds()
        size_min_px, size_max_px = self.size_range.parse_bounds()
        return scatter_marker_from_column_values(
            color_vals,
            color_label=color_label,
            colorscale=self._current_colorscale(),
            color_min=color_min,
            color_max=color_max,
            size_values=size_vals,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
            point_size=point_size,
            opacity=self._marker_opacity(),
            symbol=self._marker_symbol(scatter3d=scatter3d),
            scatter3d=scatter3d,
        )

    def _attach_size_legend_for_oids(self, fig: go.Figure, oids: list[int]) -> None:
        size_vals, size_label = self._size_values_for_oids(oids)
        size_vals, size_label = normalize_size_column(size_vals, size_label)
        if not size_vals or not size_label:
            return
        size_min_px, size_max_px = self.size_range.parse_bounds()
        attach_marker_size_legend(
            fig,
            size_label=size_label,
            size_values=size_vals,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
        )

    def _on_color_column_changed(self, _index: int = 0) -> None:
        self._update_color_controls()
        self._schedule_plot()

    def _on_size_column_changed(self, _index: int = 0) -> None:
        self._update_size_controls()
        self._schedule_plot()

    def _current_fit_kind(self) -> str:
        key = self.fit_combo.currentData()
        return str(key) if key else FIT_NONE

    def _is_histogram_plot(self) -> bool:
        return self._current_plot_type() == PLOT_TYPE_HISTOGRAM

    def _analysis_supports_fit(self) -> bool:
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_HEATMAP, PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_LINE_2D:
            return True
        if ptype == PLOT_TYPE_HISTOGRAM:
            return True
        if ptype != PLOT_TYPE_SCATTER:
            return False
        return self._effective_plot_mode() == "2D"

    def _refresh_fit_combo_items(self) -> None:
        prev = self._current_fit_kind()
        choices = PLOT_FIT_CHOICES if self._is_histogram_plot() else PLOT_FIT_CHOICES_XY
        self.fit_combo.blockSignals(True)
        try:
            self.fit_combo.clear()
            for label, key in choices:
                self.fit_combo.addItem(label, key)
            idx = self.fit_combo.findData(prev)
            if idx < 0:
                idx = 0
            self.fit_combo.setCurrentIndex(idx)
        finally:
            self.fit_combo.blockSignals(False)

    def _on_fit_option_changed(self, *_args) -> None:
        self._update_analysis_controls()
        self._schedule_plot()

    def _truncation_bounds(self) -> tuple[float | None, float | None]:
        return (
            self._parse_edit_float(self.fit_trunc_lower),
            self._parse_edit_float(self.fit_trunc_upper),
        )

    def _uses_truncated_gaussian_fit(self) -> bool:
        return self._is_histogram_plot() and self._current_fit_kind() == FIT_TRUNCATED_GAUSSIAN

    def _present_analysis_panel(
        self,
        stats_lines: list[str] | None,
        fit_summary: str | None,
    ) -> None:
        parts: list[str] = []
        if stats_lines:
            parts.extend(stats_lines)
        if fit_summary:
            if parts:
                parts.append("")
            parts.append("Curve fit")
            parts.append(f"  {fit_summary}")
            parts.append("  (orange line on plot)")
        if not parts:
            self._stats_panel.set_lines(["No statistics for the current plot."])
            return
        self._stats_panel.set_lines(parts)

    def _present_analysis_dialog(
        self,
        stats_lines: list[str] | None,
        fit_summary: str | None,
    ) -> None:
        """Backward-compatible alias for :meth:`_present_analysis_panel`."""
        self._present_analysis_panel(stats_lines, fit_summary)

    def _fit_summary_from_name(self, name: str) -> str:
        return name.removeprefix("Fit: ").strip() if name.startswith("Fit:") else name

    def _add_fit_line_trace(self, fig: go.Figure, xs: list[float], ys: list[float]) -> None:
        fig.add_trace(
            go.Scatter(
                x=xs,
                y=ys,
                mode="lines",
                name="Fit",
                showlegend=False,
                line={"color": "#e76f51", "width": 2.5, "dash": "solid"},
            )
        )

    def _add_xy_fit_trace(self, fig: go.Figure, x: list[float], y: list[float]) -> str | None:
        if self._is_histogram_plot() or self._current_fit_kind() in HISTOGRAM_ONLY_FITS:
            return None
        if not self._analysis_supports_fit() or self._current_fit_kind() == FIT_NONE:
            return None
        fit = fit_xy_curve(x, y, self._current_fit_kind())
        if not fit:
            return None
        xs, ys, name = fit
        self._add_fit_line_trace(fig, xs, ys)
        summary = self._fit_summary_from_name(name)
        self._maybe_annotate_fit_formula(fig, summary)
        return summary

    def _add_histogram_fit_trace(
        self,
        fig: go.Figure,
        vals: list[float],
        edges: list[float],
        *,
        bin_width: float,
    ) -> str | None:
        if not self._is_histogram_plot() or self._current_fit_kind() == FIT_NONE:
            return None
        trunc_lo, trunc_hi = self._truncation_bounds()
        fit = fit_histogram_curve(
            vals,
            edges,
            self._current_fit_kind(),
            bin_width=bin_width,
            trunc_lower=trunc_lo,
            trunc_upper=trunc_hi,
        )
        if not fit:
            return None
        xs, ys, name = fit
        self._add_fit_line_trace(fig, xs, ys)
        summary = self._fit_summary_from_name(name)
        self._maybe_annotate_fit_formula(fig, summary)
        return summary

    def _maybe_annotate_fit_formula(self, fig: go.Figure, fit_summary: str | None) -> None:
        if not fit_summary:
            return
        cb = getattr(self, "show_fit_formula_cb", None)
        if cb is None or not cb.isChecked():
            return
        add_fit_formula_annotation(fig, fit_summary)

    def _apply_user_plot_labels(self, fig: go.Figure) -> None:
        apply_plotly_label_overrides(
            fig,
            title=self.plot_title_edit.text() if hasattr(self, "plot_title_edit") else "",
            x_title=self.xaxis_title_edit.text() if hasattr(self, "xaxis_title_edit") else "",
            y_title=self.yaxis_title_edit.text() if hasattr(self, "yaxis_title_edit") else "",
            z_title=self.zaxis_title_edit.text() if hasattr(self, "zaxis_title_edit") else "",
        )

    def _update_analysis_controls(self) -> None:
        self._refresh_fit_combo_items()
        fit_ok = self._analysis_supports_fit()
        self._fit_label.setEnabled(fit_ok)
        self.fit_combo.setEnabled(fit_ok)
        if hasattr(self, "show_fit_formula_cb"):
            self.show_fit_formula_cb.setEnabled(fit_ok)
        trunc_on = fit_ok and self._uses_truncated_gaussian_fit()
        for widget in (
            self._trunc_lower_label,
            self.fit_trunc_lower,
            self._trunc_upper_label,
            self.fit_trunc_upper,
        ):
            widget.setEnabled(trunc_on)
            widget.setVisible(self._is_histogram_plot())

    def _color_by_supported(self) -> bool:
        ptype = self._current_plot_type()
        if ptype in (PLOT_TYPE_HEATMAP, PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_LINE_2D:
            return True
        if ptype != PLOT_TYPE_SCATTER:
            return False
        return self._effective_plot_mode() in ("2D", "3D")

    def _probe_color_values(self) -> list | None:
        """Sample color-column values for numeric vs categorical detection."""
        color_col = self._current_color_column()
        if not color_col or self.parent_app is None:
            return None
        if self._plotted_oids:
            vals, _ = self._color_values_for_oids(self._plotted_oids)
            return vals
        model = self.parent_app._table_model
        out: list = []
        for r in range(min(model.rowCount(), 2000)):
            raw = model.value_for_header(r, color_col)
            out.append(raw if (raw or "").strip() else None)
        return out

    def _update_color_controls(self) -> None:
        heatmap = self._is_heatmap_plot()
        supported = self._color_by_supported()
        self.color_combo.setEnabled(supported)
        self._color_by_label.setEnabled(supported)
        spectrum_on = heatmap or (supported and self._current_color_column() is not None)
        self._spectrum_label.setEnabled(spectrum_on)
        self.colorscale_combo.setEnabled(spectrum_on)
        self.invert_spectrum_cb.setEnabled(spectrum_on)
        numeric = (
            not heatmap and spectrum_on and color_values_are_numeric(self._probe_color_values())
        )
        self.color_range.set_enabled(numeric)
        self._update_size_controls()
        markers = getattr(self, "_markers_group", None)
        if markers is not None:
            markers.set_style_enabled(self._marker_style_supported())
        self._update_analysis_controls()

    def _current_colorscale(self) -> str:
        return resolve_plot_colorscale(
            self.colorscale_combo.currentText(),
            invert=self.invert_spectrum_cb.isChecked(),
        )

    def _update_size_controls(self) -> None:
        supported = self._color_by_supported()
        self.size_combo.setEnabled(supported)
        self._size_by_label.setEnabled(supported)
        size_on = supported and self._current_size_column() is not None
        self.size_range.set_enabled(size_on)
