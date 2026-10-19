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

"""Plotly figure for the Structure–Activity Landscape (SALI) map."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from plotly import graph_objects as go

from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_SIZE_MAX_PX,
    DEFAULT_MARKER_SIZE_MIN_PX,
    attach_marker_size_legend,
    colorbar_for_label,
    marker_sizes_from_column_values,
    scatter_marker_from_column_values,
)
from ..analysis.sali_analysis import SaliPoint
from .dockable_plot import resolve_plot_title_text
from .plotly_html import finalize_plot_legend


def build_sali_figure(
    points: Sequence[SaliPoint],
    *,
    activity_column: str,
    similarity_label: str = "Similarity",
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
    """Scatter of fingerprint similarity vs ``|Δactivity|``, colored by SALI by default."""
    xs = [float(p.similarity) for p in points]
    ys = [float(p.abs_delta) for p in points]
    custom = [[int(p.oid_a), int(p.oid_b), int(p.pair_index)] for p in points]

    if color_values is not None:
        marker = scatter_marker_from_column_values(
            color_values,
            color_label=color_label,
            colorscale=colorscale,
            color_min=color_min,
            color_max=color_max,
            size_values=size_values,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
            point_size=11,
            opacity=0.85,
        )
        if color_label:
            marker.setdefault("colorbar", colorbar_for_label(color_label))
            marker["showscale"] = True
    else:
        sizes = marker_sizes_from_column_values(
            size_values,
            size_min_px=size_min_px,
            size_max_px=size_max_px,
            default_size=11.0,
        )
        colors = [float(p.sali) for p in points]
        marker = {
            "size": sizes,
            "color": colors,
            "colorscale": "Viridis",
            "colorbar": colorbar_for_label("SALI"),
            "line": {"width": 0.5, "color": "#333"},
            "opacity": 0.85,
        }

    marker.setdefault("line", {"width": 0.5, "color": "#333"})

    fig = go.Figure(
        data=[
            go.Scatter(
                x=xs,
                y=ys,
                mode="markers",
                customdata=custom,
                hoverinfo="none",
                marker=marker,
                showlegend=False,
                unselected={"marker": {"opacity": 0.25}},
                selected={"marker": {"opacity": 1.0}},
            )
        ]
    )
    fig.update_layout(
        title=resolve_plot_title_text(plot_title, ""),
        xaxis_title=resolve_plot_title_text(xaxis_title, ""),
        yaxis_title=resolve_plot_title_text(yaxis_title, ""),
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        showlegend=False,
        margin=dict(l=48, r=24, t=24, b=40),
        meta={
            "molmanager_selection_traces": [0],
            "molmanager_hover_persist": False,
        },
    )
    attach_marker_size_legend(
        fig,
        size_label=size_label,
        size_values=size_values,
        size_min_px=size_min_px,
        size_max_px=size_max_px,
    )
    finalize_plot_legend(fig)
    return fig
