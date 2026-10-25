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

"""Plotly figures for BOILED-Egg, golden-triangle, and LipE medicinal chemistry plots."""

from __future__ import annotations

from typing import Any

from plotly import graph_objects as go

from ..analysis.medchem_space import (
    MedChemSpaceDataset,
    bbb_polygon,
    gia_polygon,
    golden_triangle_polygon,
)
from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_SIZE_PX,
    DEFAULT_PLOT_COLORSCALE,
    DEFAULT_SELECTED_MARKER_SIZE_PX,
    attach_marker_size_legend,
)
from ..ui.plotly_html import finalize_plot_legend
from .dockable_plot import resolve_plot_title_text

# Solid markers up to the old 5,000-point sample; larger clouds fade with sqrt(n).
_MARKER_OPACITY = 0.88
_OPACITY_REFERENCE_POINTS = 5_000
_OPACITY_FLOOR = 0.08
_UNSELECTED_OPACITY_RATIO = 0.35 / _MARKER_OPACITY


def marker_opacity_for_point_count(n_points: int, *, base: float | None = None) -> float:
    """Fade markers as the cloud grows so overlap shows density instead of a solid fill.

    ``base`` is the opacity used up to 5,000 points. Larger clouds fade from that value.
    """
    from ..plotting.plot_marker_color import clamp_marker_opacity

    solid = _MARKER_OPACITY if base is None else clamp_marker_opacity(base)
    count = max(0, int(n_points))
    if count <= _OPACITY_REFERENCE_POINTS:
        return solid
    scaled = solid * (_OPACITY_REFERENCE_POINTS / count) ** 0.5
    floor = min(_OPACITY_FLOOR, solid)
    return max(floor, min(solid, scaled))


def _unselected_marker_opacity(rest_opacity: float) -> float:
    """Dim the unselected cloud by the same ratio the solid markers used."""
    return max(0.04, float(rest_opacity) * _UNSELECTED_OPACITY_RATIO)


def _path_shape(
    polygon: list[tuple[float, float]],
    *,
    fillcolor: str,
    line_color: str,
) -> dict:
    xs = [p[0] for p in polygon]
    ys = [p[1] for p in polygon]
    path = "M " + " L ".join(f"{x},{y}" for x, y in zip(xs, ys, strict=True)) + " Z"
    return dict(
        type="path",
        path=path,
        fillcolor=fillcolor,
        line=dict(color=line_color, width=1.5),
        xref="x",
        yref="y",
        layer="below",
    )


def _scatter_marker(
    color_values: list[Any] | None,
    color_label: str | None,
    *,
    colorscale: str = DEFAULT_PLOT_COLORSCALE,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_min_px: float | None = None,
    size_max_px: float | None = None,
    n_points: int = 0,
    marker_opacity: float | None = None,
    marker_symbol: str | None = None,
) -> dict:
    from ..plotting.plot_marker_color import scatter_marker_from_column_values

    kwargs: dict[str, Any] = {
        "color_label": color_label,
        "colorscale": colorscale,
        "color_min": color_min,
        "color_max": color_max,
        "size_values": size_values,
        "point_size": DEFAULT_MARKER_SIZE_PX,
        "opacity": marker_opacity_for_point_count(n_points, base=marker_opacity),
        "symbol": marker_symbol,
    }
    if size_min_px is not None:
        kwargs["size_min_px"] = size_min_px
    if size_max_px is not None:
        kwargs["size_max_px"] = size_max_px
    return scatter_marker_from_column_values(color_values, **kwargs)


def _compound_scatter(
    xs: list[float],
    ys: list[float],
    oids: list[int],
    marker: dict,
) -> go.Scatter:
    rest = float(marker.get("opacity") or _MARKER_OPACITY)
    return go.Scatter(
        x=xs,
        y=ys,
        mode="markers",
        customdata=[[int(oid)] for oid in oids],
        hoverinfo="none",
        marker=marker,
        name="Compounds",
        showlegend=False,
        unselected={"marker": {"opacity": _unselected_marker_opacity(rest)}},
        selected={
            "marker": {"size": DEFAULT_SELECTED_MARKER_SIZE_PX, "color": "#d62828", "opacity": 1.0}
        },
    )


def build_boiled_egg_figure(
    dataset: MedChemSpaceDataset,
    *,
    color_values: list[Any] | None = None,
    color_label: str | None = None,
    colorscale: str = DEFAULT_PLOT_COLORSCALE,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_label: str | None = None,
    size_min_px: float | None = None,
    size_max_px: float | None = None,
    plot_title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    marker_opacity: float | None = None,
    marker_symbol: str | None = None,
) -> go.Figure:
    """TPSA vs LogP with GIA (white) and BBB (yellow) regions."""
    pts = dataset.points
    marker = _scatter_marker(
        color_values,
        color_label,
        colorscale=colorscale,
        color_min=color_min,
        color_max=color_max,
        size_values=size_values,
        size_min_px=size_min_px,
        size_max_px=size_max_px,
        n_points=len(pts),
        marker_opacity=marker_opacity,
        marker_symbol=marker_symbol,
    )
    fig = go.Figure(
        data=[
            _compound_scatter(
                [p.tpsa for p in pts],
                [p.wlogp for p in pts],
                [p.oid for p in pts],
                marker,
            )
        ]
    )
    fig.update_layout(
        title=resolve_plot_title_text(plot_title, "") or None,
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        showlegend=False,
        margin=dict(l=56, r=24, t=48 if (plot_title or "").strip() else 24, b=48),
        meta={
            "molmanager_selection_traces": [0],
            "molmanager_hover_persist": False,
        },
        shapes=[
            dict(
                type="rect",
                xref="x",
                yref="y",
                x0=-20,
                x1=220,
                y0=-3,
                y1=8,
                fillcolor="rgba(235,235,235,0.55)",
                line=dict(width=0),
                layer="below",
            ),
            _path_shape(
                gia_polygon(),
                fillcolor="rgba(255,255,255,0.92)",
                line_color="rgba(40,40,40,0.9)",
            ),
            _path_shape(
                bbb_polygon(),
                fillcolor="rgba(255,220,40,0.75)",
                line_color="rgba(180,140,0,0.9)",
            ),
        ],
    )
    fig.update_xaxes(title_text=resolve_plot_title_text(xaxis_title, "TPSA (Ų)"), range=[-20, 220])
    fig.update_yaxes(title_text=resolve_plot_title_text(yaxis_title, "LogP"), range=[-3, 8])
    attach_marker_size_legend(
        fig,
        size_label=size_label,
        size_values=size_values,
        size_min_px=float(size_min_px) if size_min_px is not None else 4.0,
        size_max_px=float(size_max_px) if size_max_px is not None else 16.0,
    )
    return finalize_plot_legend(fig)


def build_golden_triangle_figure(
    dataset: MedChemSpaceDataset,
    *,
    color_values: list[Any] | None = None,
    color_label: str | None = None,
    colorscale: str = DEFAULT_PLOT_COLORSCALE,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_label: str | None = None,
    size_min_px: float | None = None,
    size_max_px: float | None = None,
    plot_title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    marker_opacity: float | None = None,
    marker_symbol: str | None = None,
) -> go.Figure:
    """MW vs LogP with the golden-triangle drug-likeness region."""
    pts = dataset.points
    marker = _scatter_marker(
        color_values,
        color_label,
        colorscale=colorscale,
        color_min=color_min,
        color_max=color_max,
        size_values=size_values,
        size_min_px=size_min_px,
        size_max_px=size_max_px,
        n_points=len(pts),
        marker_opacity=marker_opacity,
        marker_symbol=marker_symbol,
    )
    fig = go.Figure(
        data=[
            _compound_scatter(
                [p.logp for p in pts],
                [p.mw for p in pts],
                [p.oid for p in pts],
                marker,
            )
        ]
    )
    fig.update_layout(
        title=resolve_plot_title_text(plot_title, "") or None,
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        showlegend=False,
        margin=dict(l=56, r=24, t=48 if (plot_title or "").strip() else 24, b=48),
        meta={
            "molmanager_selection_traces": [0],
            "molmanager_hover_persist": False,
        },
        shapes=[
            _path_shape(
                golden_triangle_polygon(),
                fillcolor="rgba(218,165,32,0.35)",
                line_color="rgba(160,120,20,0.95)",
            ),
        ],
    )
    fig.update_xaxes(title_text=resolve_plot_title_text(xaxis_title, "LogP"), range=[-3, 6])
    fig.update_yaxes(
        title_text=resolve_plot_title_text(yaxis_title, "Molecular weight (Da)"),
        range=[150, 520],
    )
    attach_marker_size_legend(
        fig,
        size_label=size_label,
        size_values=size_values,
        size_min_px=float(size_min_px) if size_min_px is not None else 4.0,
        size_max_px=float(size_max_px) if size_max_px is not None else 16.0,
    )
    return finalize_plot_legend(fig)


# Integer LipE contours. 5 is drawn solid; the others are guides.
_LIPE_GUIDE_LEVELS = (2, 4, 5, 6, 8)


def _lipe_levels_for_points(lipes: list[float]) -> list[int]:
    """Guide lines near the data, including LipE 5 when it is still close."""
    lo, hi = min(lipes), max(lipes)
    levels = [level for level in _LIPE_GUIDE_LEVELS if lo - 1.0 <= level <= hi + 1.0]
    if 5 not in levels and lo - 3.0 <= 5.0 <= hi + 3.0:
        levels.append(5)
    return sorted(levels)


def _lipe_guide_layout(
    dataset: MedChemSpaceDataset,
) -> tuple[list[dict], list[dict], list[float] | None, list[float] | None]:
    pairs = [(p.logp, p.activity) for p in dataset.points if p.activity is not None]
    if not pairs:
        return [], [], None, None
    logps = [logp for logp, _activity in pairs]
    activities = [activity for _logp, activity in pairs]
    pad = 0.4
    x0, x1 = min(logps) - pad, max(logps) + pad
    y0, y1 = min(activities) - pad, max(activities) + pad
    if x1 <= x0:
        x1 = x0 + 1.0
    if y1 <= y0:
        y1 = y0 + 1.0
    lipes = [activity - logp for logp, activity in pairs]
    shapes: list[dict] = []
    annotations: list[dict] = []
    for level in _lipe_levels_for_points(lipes):
        ya = x0 + float(level)
        yb = x1 + float(level)
        y0 = min(y0, ya, yb)
        y1 = max(y1, ya, yb)
        emphasize = level == 5
        shapes.append(
            dict(
                type="line",
                x0=x0,
                y0=ya,
                x1=x1,
                y1=yb,
                xref="x",
                yref="y",
                layer="below",
                line=dict(
                    color="rgba(36,90,140,0.9)" if emphasize else "rgba(120,120,120,0.55)",
                    width=1.8 if emphasize else 1.0,
                    dash="solid" if emphasize else "dot",
                ),
            )
        )
        annotations.append(
            dict(
                x=x1,
                y=yb,
                text=f"{level:g}",
                showarrow=False,
                xanchor="left",
                yanchor="middle",
                font=dict(size=11, color="#245a8c" if emphasize else "#666666"),
            )
        )
    return shapes, annotations, [x0, x1], [y0, y1]


def build_lipe_figure(
    dataset: MedChemSpaceDataset,
    *,
    color_values: list[Any] | None = None,
    color_label: str | None = None,
    colorscale: str = DEFAULT_PLOT_COLORSCALE,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_label: str | None = None,
    size_min_px: float | None = None,
    size_max_px: float | None = None,
    plot_title: str = "",
    xaxis_title: str = "",
    yaxis_title: str = "",
    marker_opacity: float | None = None,
    marker_symbol: str | None = None,
) -> go.Figure:
    """pActivity vs LogP with lines of constant lipophilic efficiency."""
    pts = dataset.points
    marker = _scatter_marker(
        color_values,
        color_label,
        colorscale=colorscale,
        color_min=color_min,
        color_max=color_max,
        size_values=size_values,
        size_min_px=size_min_px,
        size_max_px=size_max_px,
        n_points=len(pts),
        marker_opacity=marker_opacity,
        marker_symbol=marker_symbol,
    )
    fig = go.Figure(
        data=[
            _compound_scatter(
                [p.logp for p in pts],
                [float(p.activity or 0.0) for p in pts],
                [p.oid for p in pts],
                marker,
            )
        ]
    )
    shapes, annotations, x_range, y_range = _lipe_guide_layout(dataset)
    fig.update_layout(
        title=resolve_plot_title_text(plot_title, "") or None,
        template="plotly_white",
        dragmode="lasso",
        clickmode="event+select",
        showlegend=False,
        margin=dict(l=56, r=36, t=48 if (plot_title or "").strip() else 24, b=48),
        meta={
            "molmanager_selection_traces": [0],
            "molmanager_hover_persist": False,
        },
        shapes=shapes,
        annotations=annotations,
    )
    fig.update_xaxes(title_text=resolve_plot_title_text(xaxis_title, "LogP"), range=x_range)
    fig.update_yaxes(
        title_text=resolve_plot_title_text(yaxis_title, "pActivity"),
        range=y_range,
    )
    attach_marker_size_legend(
        fig,
        size_label=size_label,
        size_values=size_values,
        size_min_px=float(size_min_px) if size_min_px is not None else 4.0,
        size_max_px=float(size_max_px) if size_max_px is not None else 16.0,
    )
    return finalize_plot_legend(fig)
