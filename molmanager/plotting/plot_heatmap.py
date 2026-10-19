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

"""2D binned count heatmaps for the Plotter."""

from __future__ import annotations

import numpy as np

from .plot_marker_color import colorbar_for_label, resolve_plot_colorscale
from .plotly_legend import finalize_plot_legend


def binned_count_matrix(
    x_vals: list[float],
    y_vals: list[float],
    x_edges: list[float],
    y_edges: list[float],
) -> tuple[list[list[float]], list[float], list[float]]:
    """
    Return (z, x_centers, y_centers) for Plotly ``Heatmap``.

    ``z[row][col]`` is the count for ``y_centers[row]`` and ``x_centers[col]``.
    """
    x_arr = np.asarray(x_vals, dtype=float)
    y_arr = np.asarray(y_vals, dtype=float)
    x_edge = np.asarray(x_edges, dtype=float)
    y_edge = np.asarray(y_edges, dtype=float)
    counts, _, _ = np.histogram2d(x_arr, y_arr, bins=[x_edge, y_edge])
    x_centers = ((x_edge[:-1] + x_edge[1:]) / 2.0).tolist()
    y_centers = ((y_edge[:-1] + y_edge[1:]) / 2.0).tolist()
    return counts.tolist(), x_centers, y_centers


def value_bin_index(edges: list[float], value: float) -> int | None:
    """Index of the half-open bin containing ``value`` (last bin inclusive on the right)."""
    if len(edges) < 2:
        return None
    vf = float(value)
    for i in range(len(edges) - 1):
        lo, hi = float(edges[i]), float(edges[i + 1])
        if i == len(edges) - 2:
            if lo <= vf <= hi:
                return i
        elif lo <= vf < hi:
            return i
    centers = [(float(edges[i]) + float(edges[i + 1])) / 2.0 for i in range(len(edges) - 1)]
    if not centers:
        return None
    return int(np.argmin([abs(vf - c) for c in centers]))


def oids_in_heatmap_cell(
    x_vals: list[float],
    y_vals: list[float],
    oids: list[int],
    x_edges: list[float],
    y_edges: list[float],
    x_value: float,
    y_value: float,
) -> list[int]:
    """OIDs whose (x, y) pair falls in the heatmap cell clicked at ``(x_value, y_value)``."""
    xi = value_bin_index(x_edges, x_value)
    yi = value_bin_index(y_edges, y_value)
    if xi is None or yi is None:
        return []
    x_lo, x_hi = float(x_edges[xi]), float(x_edges[xi + 1])
    y_lo, y_hi = float(y_edges[yi]), float(y_edges[yi + 1])
    x_last = xi == len(x_edges) - 2
    y_last = yi == len(y_edges) - 2
    selected: list[int] = []
    for xv, yv, oid in zip(x_vals, y_vals, oids):
        xf, yf = float(xv), float(yv)
        if x_last:
            x_ok = x_lo <= xf <= x_hi
        else:
            x_ok = x_lo <= xf < x_hi
        if y_last:
            y_ok = y_lo <= yf <= y_hi
        else:
            y_ok = y_lo <= yf < y_hi
        if x_ok and y_ok:
            selected.append(int(oid))
    return selected


def summarize_heatmap(
    x_vals: list[float],
    y_vals: list[float],
    *,
    x_label: str,
    y_label: str,
    x_edges: list[float],
    y_edges: list[float],
    counts: list[list[float]],
) -> list[str]:
    """Summary lines for a 2D count heatmap."""
    n = len(x_vals)
    if n == 0:
        return ["No data"]
    total = float(sum(sum(row) for row in counts))
    nx = max(len(x_edges) - 1, 0)
    ny = max(len(y_edges) - 1, 0)
    nonempty = sum(1 for row in counts for c in row if c > 0)
    lines = [
        f"n = {n:,} points",
        f"bins = {nx} × {ny} ({nonempty:,} nonempty cells)",
        f"total counts = {total:.0f}",
        f"{x_label}: [{x_edges[0]:.4g}, {x_edges[-1]:.4g}]",
        f"{y_label}: [{y_edges[0]:.4g}, {y_edges[-1]:.4g}]",
    ]
    return lines


def build_heatmap_figure(
    x_vals: list[float],
    y_vals: list[float],
    *,
    x_label: str,
    y_label: str,
    x_edges: list[float],
    y_edges: list[float],
    colorscale: str | None = None,
) -> tuple[object, list[list[float]]]:
    """Build a Plotly figure and return ``(fig, counts)``."""
    from plotly import graph_objects as go

    z, x_centers, y_centers = binned_count_matrix(x_vals, y_vals, x_edges, y_edges)
    fig = go.Figure(
        data=[
            go.Heatmap(
                x=x_centers,
                y=y_centers,
                z=z,
                colorscale=resolve_plot_colorscale(colorscale),
                showlegend=False,
                colorbar=colorbar_for_label("Count"),
                hovertemplate=(
                    f"{x_label}: %{{x}}<br>{y_label}: %{{y}}<br>Count: %{{z}}<extra></extra>"
                ),
            )
        ]
    )
    fig.update_layout(
        xaxis={"title": x_label},
        yaxis={"title": y_label},
        showlegend=False,
        margin={"l": 50, "r": 20, "t": 20, "b": 45},
    )
    return finalize_plot_legend(fig), z
