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

"""Radar (spider) charts — up to six numeric spokes."""

from __future__ import annotations

from typing import Any

import numpy as np
from plotly import graph_objects as go

from molmanager.plotting.plotly_legend import finalize_plot_legend

SPOKE_NONE = "(none)"
ENTRY_NONE = "(none)"

MAX_RADAR_VARIABLES = 6
MIN_RADAR_VARIABLES = 2
MAX_RADAR_DISPLAY_ENTRIES = 6
MAX_RADAR_TRACES = 50

_TRACE_PALETTE = (
    "#2a74d6",
    "#e76f51",
    "#2a9d8f",
    "#9b5de5",
    "#f4a261",
    "#e63946",
    "#457b9d",
    "#a7c957",
    "#ff6b6b",
    "#4ecdc4",
)


def collect_radar_rows(
    model: Any,
    headers: list[str],
    columns: list[str],
    *,
    allowed_oids: set[int] | None,
    row_indices: list[int] | None = None,
) -> tuple[list[int], list[list[float | None]]]:
    """Return (oids, values) with one value list per row aligned to ``columns``."""
    col_idx = [headers.index(c) for c in columns]
    oids: list[int] = []
    rows: list[list[float | None]] = []
    indices = list(row_indices) if row_indices is not None else range(model.rowCount())
    for r in indices:
        oid = int(model.row_oid(r))
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        vals: list[float | None] = []
        skip = False
        for ci in col_idx:
            raw = model.cell_text(r, ci)
            v = _parse_cell_float(raw)
            if v is None:
                skip = True
                break
            vals.append(v)
        if skip:
            continue
        oids.append(oid)
        rows.append(vals)
    return oids, rows


def filter_radar_rows_by_oids(
    oids: list[int],
    rows: list[list[float]],
    display_oids: list[int],
) -> tuple[list[int], list[list[float]]]:
    """Keep only rows whose OID is in ``display_oids`` (order follows ``display_oids``)."""
    if not display_oids:
        return oids, rows
    by_oid = {int(oid): row for oid, row in zip(oids, rows)}
    out_oids: list[int] = []
    out_rows: list[list[float]] = []
    for oid in display_oids:
        key = int(oid)
        if key in by_oid:
            out_oids.append(key)
            out_rows.append(by_oid[key])
    return out_oids, out_rows


def _parse_cell_float(raw: str) -> float | None:
    from ..chem.molecule_conversion import safe_float

    if not (raw or "").strip():
        return None
    v = safe_float(raw)
    if v is None:
        return None
    return float(v)


def compute_radar_normalization_bounds(
    rows: list[list[float]],
) -> tuple[list[float], list[float]]:
    """Per-spoke min/max used to scale values to [0, 1] before plotting."""
    if not rows:
        return [], []
    arr = np.asarray(rows, dtype=float)
    mins = arr.min(axis=0)
    maxs = arr.max(axis=0)
    return mins.tolist(), maxs.tolist()


def apply_radar_normalization(
    rows: list[list[float]],
    mins: list[float],
    maxs: list[float],
) -> list[list[float]]:
    """Scale ``rows`` to [0, 1] using the given per-spoke bounds."""
    if not rows:
        return []
    arr = np.asarray(rows, dtype=float)
    mins_a = np.asarray(mins, dtype=float)
    maxs_a = np.asarray(maxs, dtype=float)
    span = maxs_a - mins_a
    span[span < 1e-12] = 1.0
    norm = (arr - mins_a) / span
    return norm.tolist()


def normalize_radar_rows(
    rows: list[list[float]],
) -> tuple[list[list[float]], list[float], list[float]]:
    """Scale each spoke to [0, 1] using min/max across ``rows``."""
    mins, maxs = compute_radar_normalization_bounds(rows)
    if not mins:
        return [], [], []
    return apply_radar_normalization(rows, mins, maxs), mins, maxs


def resolve_entry_row_oid(
    text: str,
    *,
    model: Any,
    row_for_oid: Any,
) -> int | None:
    """Resolve typed row ID to a table OID (OID or 1-based row number)."""
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        n = int(raw)
    except ValueError:
        return None
    if int(row_for_oid(n)) >= 0:
        return n
    row_idx = n - 1
    if 0 <= row_idx < model.rowCount():
        return int(model.row_oid(row_idx))
    return None


def summarize_radar(
    columns: list[str],
    rows: list[list[float]],
    *,
    oids: list[int],
) -> list[str]:
    """Statistics lines for the radar variable panel."""
    if not columns or not rows:
        return ["No data"]
    lines = [
        f"Variables: {', '.join(columns)}",
        f"Rows plotted: {len(rows):,}",
    ]
    arr = np.asarray(rows, dtype=float)
    for i, col in enumerate(columns):
        col_vals = arr[:, i]
        lines.append(
            f"  {col}: min {_fmt(col_vals.min())}  max {_fmt(col_vals.max())}  "
            f"mean {_fmt(col_vals.mean())}"
        )
    lines.append("Spoke values are min–max normalized across plotted rows.")
    return lines


def build_radar_figure(
    columns: list[str],
    oids: list[int],
    rows: list[list[float]],
    *,
    norm_mins: list[float] | None = None,
    norm_maxs: list[float] | None = None,
) -> go.Figure:
    """One closed polygon per row; radial axis 0–1 after min–max normalization."""
    if norm_mins is not None and norm_maxs is not None:
        norm_rows = apply_radar_normalization(rows, norm_mins, norm_maxs)
    else:
        norm_rows, _, _ = normalize_radar_rows(rows)
    theta = list(columns) + [columns[0]]
    fig = go.Figure()
    for i, (oid, rvals) in enumerate(zip(oids, norm_rows)):
        r_closed = list(rvals) + [rvals[0]]
        color = _TRACE_PALETTE[i % len(_TRACE_PALETTE)]
        hover_lines = [
            f"{col}: {_fmt(raw)} (norm {nv:.3f})" for col, raw, nv in zip(columns, rows[i], rvals)
        ]
        fig.add_trace(
            go.Scatterpolar(
                r=r_closed,
                theta=theta,
                name=f"OID {oid}",
                line={"color": color, "width": 1.5},
                fill="toself",
                fillcolor=_hex_to_rgba(color, 0.15),
                opacity=0.85,
                hovertext="<br>".join(hover_lines),
                hoverinfo="text",
            )
        )
    fig.update_layout(
        polar={
            "radialaxis": {
                "visible": True,
                "range": [0, 1],
                "tickformat": ".0%",
            },
            "angularaxis": {"direction": "clockwise"},
        },
        showlegend=len(oids) <= 12,
        margin={"l": 40, "r": 40, "t": 30, "b": 30},
        legend={
            "title": {"text": "Rows (OID)"},
            "font": {"size": 10},
        },
    )
    return finalize_plot_legend(fig)


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return f"rgba(42,116,214,{alpha})"
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def _fmt(value: float) -> str:
    av = abs(float(value))
    if av >= 1000 or (av > 0 and av < 0.001):
        return f"{value:.4g}"
    if av >= 100:
        return f"{value:.2f}"
    return f"{value:.4f}"
