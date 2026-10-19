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

"""Plotly figure for the MMP pair neighborhood network."""

from __future__ import annotations

from typing import Any

from plotly import graph_objects as go

from ..analysis.mmp_neighborhood_analysis import MmpNetworkGraph
from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_SIZE_MAX_PX,
    DEFAULT_MARKER_SIZE_MIN_PX,
    attach_marker_size_legend,
    colorbar_for_label,
    marker_sizes_from_column_values,
    resolve_plot_colorscale,
    scatter_marker_from_column_values,
)
from .dockable_plot import resolve_plot_title_text
from .plotly_html import finalize_plot_legend


def _equal_aspect_ranges(
    xs: list[float],
    ys: list[float],
    *,
    pad_frac: float = 0.08,
) -> tuple[list[float], list[float]]:
    """Square data window so pan/zoom need not use Plotly ``scaleanchor`` (expensive on SVG/GL)."""
    if not xs or not ys:
        return [-1.0, 1.0], [-1.0, 1.0]
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    cx = 0.5 * (xmin + xmax)
    cy = 0.5 * (ymin + ymax)
    half = 0.5 * max(xmax - xmin, ymax - ymin, 1e-9)
    half *= 1.0 + float(pad_frac)
    return [cx - half, cx + half], [cy - half, cy + half]


def build_mmp_neighborhood_figure(
    graph: MmpNetworkGraph,
    *,
    activity_column: str,
    color_values: list[Any] | None = None,
    color_label: str | None = None,
    colorscale: str | None = None,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_label: str | None = None,
    size_min_px: float = DEFAULT_MARKER_SIZE_MIN_PX,
    size_max_px: float = DEFAULT_MARKER_SIZE_MAX_PX,
    plot_title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
) -> go.Figure:
    """Node+edge scatter: edge color by signed Δ; nodes color/size by options or defaults.

    Uses ``scattergl`` for edges and nodes so pan/zoom/selection stay responsive on
    dense MMP networks (SVG path redraw was the main bottleneck).
    """
    traces: list[go.Scattergl] = []

    improve_x: list[float | None] = []
    improve_y: list[float | None] = []
    worsen_x: list[float | None] = []
    worsen_y: list[float | None] = []
    flat_x: list[float | None] = []
    flat_y: list[float | None] = []

    for edge in graph.edges:
        xa, ya = graph.positions.get(edge.oid_a, (0.0, 0.0))
        xb, yb = graph.positions.get(edge.oid_b, (0.0, 0.0))
        if edge.signed_delta > 1e-12:
            improve_x.extend([xa, xb, None])
            improve_y.extend([ya, yb, None])
        elif edge.signed_delta < -1e-12:
            worsen_x.extend([xa, xb, None])
            worsen_y.extend([ya, yb, None])
        else:
            flat_x.extend([xa, xb, None])
            flat_y.extend([ya, yb, None])

    def _edge_trace(xs, ys, *, name: str, color: str) -> go.Scattergl | None:
        if not xs:
            return None
        return go.Scattergl(
            x=xs,
            y=ys,
            mode="lines",
            name=name,
            line={"width": 1.5, "color": color},
            hoverinfo="skip",
            showlegend=True,
        )

    for tr in (
        _edge_trace(improve_x, improve_y, name="Δ > 0 (B−A)", color="#2a9d8f"),
        _edge_trace(worsen_x, worsen_y, name="Δ < 0 (B−A)", color="#e76f51"),
        _edge_trace(flat_x, flat_y, name="Δ ≈ 0", color="#9aa0a6"),
    ):
        if tr is not None:
            traces.append(tr)

    node_x: list[float] = []
    node_y: list[float] = []
    node_color: list[float] = []
    degree_sizes: list[float] = []
    custom: list[list[int]] = []
    for oid in graph.node_oids:
        x, y = graph.positions.get(oid, (0.0, 0.0))
        node_x.append(float(x))
        node_y.append(float(y))
        node_color.append(float(graph.activities.get(oid, 0.0)))
        deg = int(graph.degrees.get(oid, 1))
        degree_sizes.append(12.0 + min(18.0, 3.0 * deg))
        custom.append([int(oid)])

    if size_values is not None:
        sizes = marker_sizes_from_column_values(
            size_values,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
            default_size=14.0,
        )
    else:
        sizes = degree_sizes

    if color_values is not None:
        marker = scatter_marker_from_column_values(
            color_values,
            color_label=color_label,
            colorscale=colorscale,
            color_min=color_min,
            color_max=color_max,
            size_values=None,
            point_size=14,
            opacity=0.92,
        )
        marker["size"] = sizes
        if color_label:
            marker.setdefault("colorbar", colorbar_for_label(color_label))
            marker["showscale"] = True
    else:
        marker = {
            "size": sizes,
            "color": node_color,
            "colorscale": resolve_plot_colorscale(colorscale) if color_values else "Viridis",
            "colorbar": colorbar_for_label(activity_column),
            "line": {"width": 0.8, "color": "#333"},
            "opacity": 0.92,
        }
        if color_min is not None or color_max is not None:
            finite = [c for c in node_color if c == c]
            lo = float(color_min) if color_min is not None else (min(finite) if finite else 0.0)
            hi = float(color_max) if color_max is not None else (max(finite) if finite else 1.0)
            if lo > hi:
                lo, hi = hi, lo
            marker["cmin"] = lo
            marker["cmax"] = hi

    marker.setdefault("line", {"width": 0.8, "color": "#333"})

    node_trace_index = len(traces)
    traces.append(
        go.Scattergl(
            x=node_x,
            y=node_y,
            mode="markers",
            name="Molecules",
            customdata=custom,
            hoverinfo="none",
            marker=marker,
            showlegend=False,
            unselected={"marker": {"opacity": 0.3}},
            selected={"marker": {"opacity": 1.0}},
        )
    )

    x_range, y_range = _equal_aspect_ranges(node_x, node_y)

    fig = go.Figure(data=traces)
    fig.update_layout(
        title=resolve_plot_title_text(plot_title, ""),
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        uirevision="mmp-pair-network",
        xaxis={
            "visible": False,
            "range": x_range,
            "constrain": "domain",
            "title": resolve_plot_title_text(xaxis_title, ""),
        },
        yaxis={
            "visible": False,
            "range": y_range,
            "constrain": "domain",
            "title": resolve_plot_title_text(yaxis_title, ""),
        },
        margin=dict(l=24, r=24, t=24, b=24),
        legend={"orientation": "h", "yanchor": "bottom", "y": 1.02},
        meta={
            "molmanager_selection_traces": [node_trace_index],
            # selectedpoints on scattergl; SVG overlay is wrong/expensive with edge traces first.
            "molmanager_selection_overlay": False,
            "molmanager_hover_persist": False,
        },
    )
    if size_values is not None:
        attach_marker_size_legend(
            fig,
            size_label=size_label,
            size_values=size_values,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
        )
    finalize_plot_legend(fig)
    return fig
