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

"""Figure builders and plot-type click handlers — file-split of ``PlotWidget``."""

from __future__ import annotations

import json

from plotly import graph_objects as go

from ..plotting.plot_axes import (
    PLOT_TYPE_BOX,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_RADAR,
    PLOT_TYPE_SCATTER,
    PLOT_TYPE_VIOLIN,
    compute_histogram_bin_edges,
    oids_at_histogram_point_indices,
    oids_in_histogram_bin,
)
from ..plotting.plot_statistics_fits import summarize_univariate, summarize_xy
from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_SIZE_3D_PX,
    DEFAULT_MARKER_SIZE_PX,
    DEFAULT_SELECTED_MARKER_SIZE_3D_PX,
    DEFAULT_SELECTED_MARKER_SIZE_PX,
    unselected_marker_opacity,
)
from ..plotting.plot_heatmap import build_heatmap_figure, oids_in_heatmap_cell, summarize_heatmap
from ..plotting.plot_radar import (
    MAX_RADAR_TRACES,
    MAX_RADAR_VARIABLES,
    MIN_RADAR_VARIABLES,
    build_radar_figure,
    collect_radar_rows,
    compute_radar_normalization_bounds,
    filter_radar_rows_by_oids,
    summarize_radar,
)
from .plot_table_sync import apply_table_selection_for_source_rows, selected_oids_for_plot


class PlotRenderMixin:
    """Build Plotly figures and handle radar / heatmap / histogram selection."""

    def _empty_plot_hint(self) -> str:
        ptype = self._current_plot_type()
        if ptype == PLOT_TYPE_SCATTER:
            return "Choose X and Y for 2D scatter; set Z as well for 3D."
        if ptype == PLOT_TYPE_HISTOGRAM:
            return "Choose a numeric column for the X axis."
        if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
            return "Choose a numeric column for the X axis."
        if ptype == PLOT_TYPE_LINE_2D:
            return "Choose X and Y columns for the line chart."
        if ptype == PLOT_TYPE_HEATMAP:
            return "Choose X and Y columns for the heatmap."
        if ptype == PLOT_TYPE_RADAR:
            return (
                f"Choose {MIN_RADAR_VARIABLES}–{MAX_RADAR_VARIABLES} numeric spokes "
                "in Plot Options."
            )
        return "Choose axes for the current plot type."

    def plot(self):
        app = self.parent_app
        if app is not None and getattr(app, "status_label", None) is not None:
            try:
                app.status_label.setText("Plot: collecting…")
            except RuntimeError:
                pass
        job_id = f"plot-{id(self)}"
        if app is not None:
            try:
                from .background_jobs import register_background_job, unregister_background_job

                register_background_job(app, job_id, "Updating plot")
            except Exception:
                job_id = ""
        try:
            ptype = self._current_plot_type()
            if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN):
                self._plot_distribution(ptype)
            elif ptype == PLOT_TYPE_LINE_2D:
                self._plot_line_2d()
            elif ptype == PLOT_TYPE_HEATMAP:
                self._plot_heatmap()
            elif ptype == PLOT_TYPE_RADAR:
                self._plot_radar()
            elif ptype == PLOT_TYPE_HISTOGRAM:
                if self._effective_plot_mode() == "Histogram":
                    self._plot_histogram()
                else:
                    self._render_empty_plot(self._empty_plot_hint())
            else:
                mode = self._effective_plot_mode()
                if mode is None:
                    self._render_empty_plot(self._empty_plot_hint())
                else:
                    self._plot_scatter(mode)
            self._update_color_controls()
        finally:
            if app is not None and job_id:
                try:
                    from .background_jobs import unregister_background_job

                    unregister_background_job(app, job_id)
                except Exception:
                    pass
            restore_idle = getattr(app, "_restore_idle_status", None) if app is not None else None
            if callable(restore_idle):
                restore_idle()

    def _plot_scatter(self, mode: str) -> None:
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        self._clear_heatmap_state()
        fx, fy, fz, foids, xname, yname, zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        is3d = mode == "3D"
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        zmin = self._parse_edit_float(self.zmin) if is3d else None
        zmax = self._parse_edit_float(self.zmax) if is3d else None

        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            if is3d:
                fig.update_layout(
                    scene={
                        "xaxis": {"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                        "yaxis": {"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                        "zaxis": {"title": zname or "Z", **self._plotly_axis_range(zmin, zmax, [])},
                    },
                    margin={"l": 20, "r": 20, "t": 20, "b": 20},
                )
            else:
                fig.update_layout(
                    xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                    yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                    margin={"l": 50, "r": 20, "t": 20, "b": 45},
                )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText("Plot: no points for current axis/range/scope.")
            return

        self._plotted_oids = list(foids)
        self._selected_point_indices = {
            i for i in self._selected_point_indices if 0 <= i < len(self._plotted_oids)
        }
        selected_points = (
            sorted(self._selected_point_indices) if self._selected_point_indices else []
        )
        from ..platform_support.config import load_config

        overlay_max = int(load_config().plot_selection_overlay_max_points)
        # Large selections are applied after react via molmanagerSetSelection (avoids fat payloads).
        bake_selection = bool(selected_points) and len(selected_points) <= overlay_max
        marker = self._scatter_marker_for_oids(
            foids,
            point_size=DEFAULT_MARKER_SIZE_3D_PX if is3d else DEFAULT_MARKER_SIZE_PX,
            scatter3d=is3d,
        )
        selected_marker_2d = {
            "size": DEFAULT_SELECTED_MARKER_SIZE_PX,
            "color": "#d62828",
            "opacity": 1.0,
        }
        unselected_marker = {
            "marker": {"opacity": unselected_marker_opacity(marker.get("opacity", 0.85))}
        }

        fig = go.Figure()
        if is3d:
            fig.add_trace(
                go.Scatter3d(
                    **self._attach_point_hover(
                        {
                            "x": fx,
                            "y": fy,
                            "z": fz,
                            "mode": "markers",
                            "marker": marker,
                            "name": "Points",
                            "showlegend": False,
                        },
                        foids,
                    )
                )
            )
            if bake_selection:
                sx = [fx[i] for i in selected_points]
                sy = [fy[i] for i in selected_points]
                sz = [fz[i] for i in selected_points]
                fig.add_trace(
                    go.Scatter3d(
                        x=sx,
                        y=sy,
                        z=sz,
                        mode="markers",
                        marker={
                            "size": DEFAULT_SELECTED_MARKER_SIZE_3D_PX,
                            "opacity": 1.0,
                            "color": "#d62828",
                            "symbol": marker.get("symbol", "circle"),
                        },
                        name="Selected",
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )
            fig.update_layout(
                scene={
                    "xaxis": {"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
                    "yaxis": {"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
                    "zaxis": {"title": zname or "Z", **self._plotly_axis_range(zmin, zmax, fz)},
                },
                margin={"l": 20, "r": 20, "t": 20, "b": 20},
            )
            stats_lines = (
                summarize_univariate(fx, label=xname)
                + summarize_univariate(fy, label=yname)
                + summarize_univariate(fz, label=zname or "Z")
            )
            self._present_analysis_dialog(stats_lines, None)
        else:
            fig.add_trace(
                go.Scatter(
                    **self._attach_point_hover(
                        {
                            "x": fx,
                            "y": fy,
                            "mode": "markers",
                            "marker": marker,
                            "showlegend": False,
                            "selectedpoints": selected_points if bake_selection else None,
                            "selected": {"marker": selected_marker_2d},
                            "unselected": unselected_marker,
                        },
                        foids,
                    )
                )
            )
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
                dragmode="lasso",
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            fit_summary = self._add_xy_fit_trace(fig, fx, fy)
            self._present_analysis_dialog(
                summarize_xy(fx, fy, x_label=xname, y_label=yname),
                fit_summary,
            )

        self._attach_size_legend_for_oids(fig, foids)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Plot: rendered {len(fx):,} point(s).")

    def _plot_line_2d(self) -> None:
        self._clear_heatmap_state()
        fx, fy, _fz, foids, xname, yname, _zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                "Line plot: no points for current axis/range/scope."
            )
            return
        ordered = sorted(zip(fx, fy, foids), key=lambda t: t[0])
        fx, fy, foids = [list(c) for c in zip(*ordered)]
        self._plotted_oids = list(foids)
        self._selected_point_indices = {
            i for i in self._selected_point_indices if 0 <= i < len(self._plotted_oids)
        }
        selected_points = (
            sorted(self._selected_point_indices) if self._selected_point_indices else []
        )
        marker = self._scatter_marker_for_oids(foids, point_size=DEFAULT_MARKER_SIZE_PX)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                **self._attach_point_hover(
                    {
                        "x": fx,
                        "y": fy,
                        "mode": "lines+markers",
                        "line": {"color": "#2a74d6", "width": 1.5},
                        "marker": marker,
                        "showlegend": False,
                        "selectedpoints": selected_points if selected_points else None,
                        "selected": {
                            "marker": {
                                "size": DEFAULT_SELECTED_MARKER_SIZE_PX,
                                "color": "#d62828",
                                "opacity": 1.0,
                            }
                        },
                        "unselected": {
                            "marker": {
                                "opacity": unselected_marker_opacity(marker.get("opacity", 0.85))
                            }
                        },
                    },
                    foids,
                )
            )
        )
        fig.update_layout(
            xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, fx)},
            yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, fy)},
            dragmode="lasso",
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        fit_summary = self._add_xy_fit_trace(fig, fx, fy)
        self._present_analysis_dialog(
            summarize_xy(fx, fy, x_label=xname, y_label=yname),
            fit_summary,
        )
        self._attach_size_legend_for_oids(fig, foids)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Line plot: {len(fx):,} point(s).")

    def _plot_distribution(self, kind: str) -> None:
        self._clear_heatmap_state()
        vals, oids, xname = self._collect_histogram()
        if not xname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        label = "Box plot" if kind == PLOT_TYPE_BOX else "Violin"
        if not vals:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                yaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                f"{label}: no values for current column/range/scope."
            )
            return
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        trace_kwargs: dict = {
            "y": vals,
            "name": xname,
            "marker": {
                "color": "#2a74d6",
                "size": DEFAULT_MARKER_SIZE_PX,
                "opacity": self._marker_opacity(),
                "symbol": self._marker_symbol(),
                "line": {"color": "#1d3557", "width": 1},
            },
        }
        if kind == PLOT_TYPE_BOX:
            trace_kwargs["boxmean"] = "sd"
            trace = go.Box(**trace_kwargs)
        else:
            trace = go.Violin(**trace_kwargs)
        fig = go.Figure(data=[trace])
        fig.update_layout(
            yaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, vals)},
            showlegend=False,
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        self._present_analysis_dialog(summarize_univariate(vals, label=xname), None)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"{label}: {len(vals):,} value(s) in {xname!r}.")

    def _plot_histogram(self) -> None:
        self._clear_heatmap_state()
        vals, oids, xname = self._collect_histogram()
        if not xname:
            self._render_empty_plot("Choose a column for the histogram.")
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        bin_width = self._parse_edit_float(self.hist_bin_width)
        if not vals:
            self._hist_edges = []
            self._hist_vals = []
            self._hist_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": "Count"},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText(
                "Histogram: no values for current column/range/scope."
            )
            return
        self._hist_vals = list(vals)
        self._hist_oids = list(oids)
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        edges, width = compute_histogram_bin_edges(vals, bin_width=bin_width, xmin=xmin, xmax=xmax)
        self._hist_edges = edges
        hist_kwargs: dict = {
            "x": vals,
            "xbins": {"start": edges[0], "end": edges[-1], "size": width},
        }
        fig = go.Figure(
            data=[
                go.Histogram(
                    **hist_kwargs,
                    marker={"color": "#2a74d6", "line": {"color": "white", "width": 0.5}},
                    showlegend=False,
                )
            ]
        )
        fig.update_layout(
            xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, vals)},
            yaxis={"title": "Count"},
            bargap=0.02,
            margin={"l": 50, "r": 20, "t": 20, "b": 45},
        )
        fit_summary = self._add_histogram_fit_trace(fig, vals, edges, bin_width=width)
        self._present_analysis_dialog(summarize_univariate(vals, label=xname), fit_summary)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(f"Histogram: {len(vals):,} value(s) in {xname!r}.")

    def _radar_scope_allowed_oids(self) -> set[int] | None:
        if self.parent_app is None:
            return None
        n_sel = len(self.parent_app._selected_logical_rows())
        if n_sel > 0 and self.only_selected_cb.isChecked():
            return self.parent_app._selected_oids_set()
        return None

    def _plot_radar(self) -> None:
        self._clear_heatmap_state()
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        columns = self._selected_radar_spoke_columns()
        if len(columns) < MIN_RADAR_VARIABLES:
            self._radar_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            self._render_empty_plot(self._empty_plot_hint())
            return
        if self.parent_app is None:
            return

        row_indices = list(self._plot_source_row_indices())
        oids, raw_rows = collect_radar_rows(
            self.parent_app._table_model,
            list(self.parent_app.headers),
            columns,
            allowed_oids=self._radar_scope_allowed_oids(),
            row_indices=row_indices,
        )
        rows = [[float(v) for v in row] for row in raw_rows]
        if not rows:
            self._radar_oids = []
            self._plotted_oids = []
            self._selected_point_indices = set()
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._render_empty_plot("No rows with numeric values in all selected spokes.")
            self.parent_app.status_label.setText(
                "Radar Plot: no rows with numeric values in all selected spokes."
            )
            return

        norm_mins, norm_maxs = compute_radar_normalization_bounds(rows)
        display_oids, invalid_ids = self._selected_radar_entry_oids()
        if invalid_ids:
            self.parent_app.status_label.setText(
                "Radar Plot: unknown row ID(s): " + ", ".join(invalid_ids)
            )
        total_in_scope = len(oids)
        if display_oids is not None:
            oids, rows = filter_radar_rows_by_oids(oids, rows, display_oids)
            if not rows:
                self._radar_oids = []
                self._plotted_oids = []
                self._selected_point_indices = set()
                self._stats_panel.set_lines(["No statistics for the current plot."])
                self._render_empty_plot("Entered row IDs have no data for the current spokes.")
                if not invalid_ids:
                    self.parent_app.status_label.setText(
                        "Radar Plot: entered row IDs have no data for the current spokes."
                    )
                return
        elif total_in_scope > MAX_RADAR_TRACES:
            oids = oids[:MAX_RADAR_TRACES]
            rows = rows[:MAX_RADAR_TRACES]

        self._radar_oids = list(oids)
        self._plotted_oids = list(oids)
        self._selected_point_indices = set()
        fig = build_radar_figure(
            columns,
            oids,
            rows,
            norm_mins=norm_mins,
            norm_maxs=norm_maxs,
        )
        self._present_analysis_panel(summarize_radar(columns, rows, oids=oids), None)
        self._push_plotly_figure(fig)
        msg = f"Radar Plot: {len(rows):,} row(s), {len(columns)} spoke(s) (normalized)."
        if display_oids is None and total_in_scope > len(rows):
            msg = (
                f"Radar Plot: showing first {MAX_RADAR_TRACES:,} of "
                f"{total_in_scope:,} rows (normalized)."
            )
        if not invalid_ids:
            self.parent_app.status_label.setText(msg)

    def _on_radar_trace_clicked(self, trace_index: int) -> None:
        if trace_index < 0 or trace_index >= len(self._radar_oids):
            return
        if self.parent_app is None:
            return
        oid = int(self._radar_oids[trace_index])
        row = self.parent_app.logical_row_for_oid(oid)
        if row < 0:
            return
        apply_table_selection_for_source_rows(self.parent_app, [row], origin=self)
        self.parent_app.status_label.setText(f"Radar Plot: selected row {row + 1:,} (OID {oid}).")

    def _clear_heatmap_state(self) -> None:
        self._heat_x = []
        self._heat_y = []
        self._heat_oids = []
        self._heat_x_edges = []
        self._heat_y_edges = []

    def _plot_heatmap(self) -> None:
        self._hist_edges = []
        self._hist_vals = []
        self._hist_oids = []
        self._clear_heatmap_state()
        fx, fy, _fz, foids, xname, yname, _zname = self._collect_points()
        if not xname or not yname:
            self._render_empty_plot(self._empty_plot_hint())
            return
        xmin = self._parse_edit_float(self.xmin)
        xmax = self._parse_edit_float(self.xmax)
        ymin = self._parse_edit_float(self.ymin)
        ymax = self._parse_edit_float(self.ymax)
        x_bin_width = self._parse_edit_float(self.hist_bin_width)
        y_bin_width = self._parse_edit_float(self.heatmap_y_bin_width)

        if not fx:
            self._plotted_oids = []
            self._selected_point_indices = set()
            fig = go.Figure()
            fig.update_layout(
                xaxis={"title": xname, **self._plotly_axis_range(xmin, xmax, [])},
                yaxis={"title": yname, **self._plotly_axis_range(ymin, ymax, [])},
                margin={"l": 50, "r": 20, "t": 20, "b": 45},
            )
            self._stats_panel.set_lines(["No statistics for the current plot."])
            self._push_plotly_figure(fig)
            self.parent_app.status_label.setText("Heatmap: no points for current axis/range/scope.")
            return

        x_edges, x_width = compute_histogram_bin_edges(
            fx, bin_width=x_bin_width, xmin=xmin, xmax=xmax
        )
        y_edges, y_width = compute_histogram_bin_edges(
            fy, bin_width=y_bin_width, xmin=ymin, xmax=ymax
        )
        colorscale = self._current_colorscale()
        fig, counts = build_heatmap_figure(
            fx,
            fy,
            x_label=xname,
            y_label=yname,
            x_edges=x_edges,
            y_edges=y_edges,
            colorscale=colorscale,
        )
        self._heat_x = list(fx)
        self._heat_y = list(fy)
        self._heat_oids = list(foids)
        self._heat_x_edges = list(x_edges)
        self._heat_y_edges = list(y_edges)
        self._plotted_oids = list(foids)
        self._selected_point_indices = set()
        stats = summarize_heatmap(
            fx,
            fy,
            x_label=xname,
            y_label=yname,
            x_edges=x_edges,
            y_edges=y_edges,
            counts=counts,
        )
        self._present_analysis_dialog(stats, None)
        self._push_plotly_figure(fig)
        self.parent_app.status_label.setText(
            f"Heatmap: {len(fx):,} point(s), {len(x_edges) - 1}×{len(y_edges) - 1} bins."
        )

    def _on_heatmap_cell_clicked(self, x_value: float, y_value: float) -> None:
        oids = oids_in_heatmap_cell(
            self._heat_x,
            self._heat_y,
            self._heat_oids,
            self._heat_x_edges,
            self._heat_y_edges,
            x_value,
            y_value,
        )
        if not oids:
            return
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Heatmap: selected {len(oids):,} row(s) in the clicked cell."
        )

    def _on_histogram_points_selected(self, indices_json: str, *, additive: bool = False) -> None:
        try:
            raw = json.loads(indices_json)
        except json.JSONDecodeError:
            return
        if not isinstance(raw, list):
            return
        indices = [int(x) for x in raw if isinstance(x, (int, float)) and not isinstance(x, bool)]
        oids = oids_at_histogram_point_indices(self._hist_oids, indices)
        if not oids:
            return
        if additive:
            oids = sorted({int(x) for x in oids} | selected_oids_for_plot(self.parent_app))
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Histogram: selected {len(oids):,} row(s) in the clicked bar."
        )

    def _on_histogram_bin_clicked(self, bin_index: int) -> None:
        oids = oids_in_histogram_bin(self._hist_vals, self._hist_oids, self._hist_edges, bin_index)
        if not oids:
            return
        self._select_rows_for_oids(oids)
        self.parent_app.status_label.setText(
            f"Histogram: selected {len(oids):,} row(s) in bin {bin_index + 1}."
        )
