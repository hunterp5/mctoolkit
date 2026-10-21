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

"""Map table column values to Plotly scatter marker color settings."""

from __future__ import annotations

from typing import Any

import numpy as np

_CATEGORICAL_PALETTE = (
    "#636efa",
    "#ef553b",
    "#00cc96",
    "#ab63fa",
    "#ffa15a",
    "#19d3f3",
    "#ff6692",
    "#b6e880",
    "#ff97ff",
    "#fecb52",
)

_MISSING_TOKENS = frozenset({"", "N/A", "NA", "NAN", "NONE", "NULL"})

DEFAULT_PLOT_COLORSCALE = "Viridis"

DEFAULT_MARKER_SIZE_PX = 8.0
DEFAULT_MARKER_SIZE_3D_PX = 6.0
DEFAULT_SELECTED_MARKER_SIZE_PX = 11.0
DEFAULT_SELECTED_MARKER_SIZE_3D_PX = 9.0
DEFAULT_MARKER_SIZE_MIN_PX = 6.0
DEFAULT_MARKER_SIZE_MAX_PX = 18.0
DEFAULT_MARKER_OPACITY = 0.85
DEFAULT_UNSELECTED_MARKER_OPACITY = 0.35
DEFAULT_MARKER_SYMBOL = "circle"

# Labels shown in plot settings, and the Plotly ``marker.symbol`` each one sets.
# 3D scatter only draws the subset in ``_SCATTER3D_SYMBOLS``; other shapes fall back.
PLOT_MARKER_SHAPES: tuple[tuple[str, str], ...] = (
    ("Circle", "circle"),
    ("Circle (open)", "circle-open"),
    ("Square", "square"),
    ("Square (open)", "square-open"),
    ("Diamond", "diamond"),
    ("Diamond (open)", "diamond-open"),
    ("Triangle", "triangle-up"),
    ("Triangle (open)", "triangle-up-open"),
    ("Cross", "cross"),
    ("X", "x"),
    ("Star", "star"),
    ("Pentagon", "pentagon"),
    ("Hexagon", "hexagon"),
)

_MARKER_SYMBOLS = frozenset(symbol for _label, symbol in PLOT_MARKER_SHAPES)
_SCATTER3D_SYMBOLS = frozenset(
    {
        "circle",
        "circle-open",
        "square",
        "square-open",
        "diamond",
        "diamond-open",
        "cross",
        "x",
    }
)

# A title longer than the colorbar grows the figure. Keep it beside the bar.
COLORBAR_TITLE_MAX_CHARS = 32
COLORBAR_THICKNESS_PX = 14

# Plotly built-in continuous colorscales (numeric Color by).
PLOT_COLORSCALE_CHOICES: tuple[str, ...] = (
    "Viridis",
    "Plasma",
    "Inferno",
    "Magma",
    "Cividis",
    "Turbo",
    "Blues",
    "Greens",
    "Reds",
    "YlOrRd",
    "RdBu",
    "RdYlBu",
    "Portland",
    "Jet",
)


def colorscale_is_reversed(name: str | None) -> bool:
    """True when ``name`` is a reversed Plotly colorscale (``Viridis_r``)."""
    return bool(name) and str(name).strip().endswith("_r")


def resolve_plot_colorscale(name: str | None, *, invert: bool = False) -> str:
    """Return a valid Plotly colorscale name.

    ``invert`` reverses the scale (``Viridis`` becomes ``Viridis_r``). A name
    that already ends in ``_r`` stays reversed, so a resolved scale can be
    passed through again without flipping back.
    """
    raw = (name or "").strip()
    reversed_already = colorscale_is_reversed(raw)
    base = raw[:-2] if reversed_already else raw
    if base not in PLOT_COLORSCALE_CHOICES:
        base = DEFAULT_PLOT_COLORSCALE
        reversed_already = False
    if invert or reversed_already:
        return f"{base}_r"
    return base


def parse_color_range_bounds(
    min_text: str,
    max_text: str,
) -> tuple[float | None, float | None]:
    """Parse optional min/max edits; empty text means auto (data-driven) bounds."""
    from ..chem.molecule_conversion import safe_float

    lo = safe_float(min_text.strip()) if min_text.strip() else None
    hi = safe_float(max_text.strip()) if max_text.strip() else None
    return lo, hi


def color_values_are_numeric(raw_values: list[Any] | None) -> bool:
    """True when every non-missing value parses as a number (continuous color column)."""
    if not raw_values or not column_values_have_color_data(raw_values):
        return False
    for value in raw_values:
        if _is_missing(value):
            continue
        if _try_float(value) is None:
            return False
    return True


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, float) and np.isnan(value):
        return True
    if isinstance(value, str):
        return value.strip().upper() in _MISSING_TOKENS
    try:
        if np.isnan(float(value)):
            return True
    except (TypeError, ValueError):
        pass
    return False


def column_values_have_color_data(raw_values: list[Any] | None) -> bool:
    """True if at least one value can be used for coloring."""
    if not raw_values:
        return False
    return any(not _is_missing(v) for v in raw_values)


def normalize_color_column(
    color_values: list[Any] | None,
    color_label: str | None,
) -> tuple[list[Any] | None, str | None]:
    """Return ``(None, None)`` when the column has no usable values."""
    if not color_label or color_label == "(none)":
        return None, None
    if not column_values_have_color_data(color_values):
        return None, None
    return color_values, color_label


def normalize_size_column(
    size_values: list[Any] | None,
    size_label: str | None,
) -> tuple[list[Any] | None, str | None]:
    """Return ``(None, None)`` when Size by has no usable values."""
    return normalize_color_column(size_values, size_label)


def clamp_marker_opacity(opacity: float) -> float:
    """Clamp a marker opacity into the Plotly range ``[0, 1]``."""
    try:
        value = float(opacity)
    except (TypeError, ValueError):
        return DEFAULT_MARKER_OPACITY
    if value != value:  # NaN
        return DEFAULT_MARKER_OPACITY
    return max(0.0, min(1.0, value))


def resolve_marker_symbol(symbol: str | None, *, scatter3d: bool = False) -> str:
    """Return a Plotly marker symbol, falling back to a circle when needed.

    Scatter3d only draws circle, square, diamond, cross, and x (filled or open).
    """
    raw = str(symbol or "").strip()
    if raw not in _MARKER_SYMBOLS:
        raw = DEFAULT_MARKER_SYMBOL
    if scatter3d and raw not in _SCATTER3D_SYMBOLS:
        return "circle-open" if raw.endswith("-open") else "circle"
    return raw


def unselected_marker_opacity(
    opacity: float,
    *,
    rest: float = DEFAULT_MARKER_OPACITY,
    dim: float = DEFAULT_UNSELECTED_MARKER_OPACITY,
) -> float:
    """Dim unselected points in proportion to the chosen marker opacity.

    At ``opacity == rest`` the result is ``dim``, so the historical look is kept
    when the user has not changed the control.
    """
    chosen = clamp_marker_opacity(opacity)
    rest_v = clamp_marker_opacity(rest)
    dim_v = clamp_marker_opacity(dim)
    if rest_v <= 1e-9:
        return min(chosen, dim_v)
    scaled = chosen * (dim_v / rest_v)
    return max(0.02, min(chosen, scaled))


def apply_marker_appearance(
    marker: dict,
    *,
    opacity: float | None = None,
    symbol: str | None = None,
    scatter3d: bool = False,
) -> dict:
    """Set opacity and symbol on an existing Plotly marker dict."""
    if opacity is not None:
        marker["opacity"] = clamp_marker_opacity(opacity)
    if symbol is not None:
        marker["symbol"] = resolve_marker_symbol(symbol, scatter3d=scatter3d)
    return marker


def marker_selection_opacities(fig: Any) -> tuple[float | None, float | None]:
    """Return ``(rest, unselected)`` opacity from the first marker trace.

    The plot shell uses these when a selection restyles unselected points, so a
    custom opacity is not replaced by the historical 0.85 / 0.35 pair.
    """
    for trace in getattr(fig, "data", None) or []:
        mode = str(getattr(trace, "mode", "") or "")
        if "markers" not in mode:
            continue
        marker = getattr(trace, "marker", None)
        if marker is None:
            continue
        opacity = getattr(marker, "opacity", None)
        if not isinstance(opacity, (int, float)):
            continue
        dim: float | None = None
        unselected = getattr(trace, "unselected", None)
        umarker = getattr(unselected, "marker", None) if unselected is not None else None
        raw_dim = getattr(umarker, "opacity", None) if umarker is not None else None
        if isinstance(raw_dim, (int, float)):
            dim = float(raw_dim)
        return float(opacity), dim
    return None, None


def clamp_marker_size_bounds(
    size_min_px: float,
    size_max_px: float,
    *,
    floor: float = 1.0,
    ceiling: float = 64.0,
) -> tuple[float, float]:
    """Clamp and order marker pixel size bounds."""
    lo = max(floor, min(ceiling, float(size_min_px)))
    hi = max(floor, min(ceiling, float(size_max_px)))
    if lo > hi:
        lo, hi = hi, lo
    return lo, hi


def _format_size_legend_tick(value: float) -> str:
    """Compact tick label for the size scale."""
    if value != value:  # NaN
        return "—"
    text = f"{value:.4g}"
    return text


def size_legend_levels(
    raw_values: list[Any] | None,
    *,
    size_min_px: float = DEFAULT_MARKER_SIZE_MIN_PX,
    size_max_px: float = DEFAULT_MARKER_SIZE_MAX_PX,
    max_categorical: int = 6,
    n_numeric: int = 5,
) -> list[tuple[str, float]] | None:
    """
    Return ``(label, marker_px)`` levels for a right-side size legend.

    Numeric columns: ``n_numeric`` evenly spaced ticks (high → low).
    Categorical: up to ``max_categorical`` classes.
    """
    if not raw_values or not column_values_have_color_data(raw_values):
        return None
    lo_px, hi_px = clamp_marker_size_bounds(size_min_px, size_max_px)

    numeric: list[float] = []
    for value in raw_values:
        parsed = _try_float(value)
        if parsed is None:
            numeric.clear()
            break
        numeric.append(parsed)

    if numeric:
        finite = [v for v in numeric if v == v]
        if not finite:
            return None
        data_lo, data_hi = min(finite), max(finite)
        n = max(2, int(n_numeric))
        if abs(data_hi - data_lo) < 1e-12:
            mid_px = (lo_px + hi_px) * 0.5
            return [(_format_size_legend_tick(data_lo), mid_px)]
        levels: list[tuple[str, float]] = []
        for i in range(n):
            # High → low (colorbar-style: top is largest).
            t = i / (n - 1)
            val = data_hi - t * (data_hi - data_lo)
            px = hi_px - t * (hi_px - lo_px)
            levels.append((_format_size_legend_tick(val), float(px)))
        return levels

    categories: list[str] = []
    for value in raw_values:
        if _is_missing(value):
            categories.append("(missing)")
        else:
            text = str(value).strip()
            categories.append(text if text else "(missing)")
    uniq = sorted(set(categories), key=lambda x: (x == "(missing)", x.lower()))
    if not uniq:
        return None
    if len(uniq) == 1:
        px = lo_px if uniq[0] == "(missing)" else (lo_px + hi_px) * 0.5
        return [(uniq[0], px)]
    shown = uniq[: max(1, int(max_categorical))]
    span = len(uniq) - 1
    levels = []
    for cat in shown:
        i = uniq.index(cat)
        px = lo_px + (i / span) * (hi_px - lo_px)
        levels.append((cat, float(px)))
    # High → low in the legend (match colorbar top=high).
    levels.sort(key=lambda t: -t[1])
    return levels


def shorten_colorbar_title(label: str) -> str:
    """Keep a colorbar title short enough to sit beside the scale."""
    text = str(label).strip()
    if len(text) <= COLORBAR_TITLE_MAX_CHARS:
        return text
    return text[: COLORBAR_TITLE_MAX_CHARS - 1].rstrip() + "…"


def colorbar_for_label(label: str) -> dict[str, Any]:
    """Colorbar whose title runs down the bar, first character at the top.

    Plotly places ``side="right"`` beside the scale, then rotates it so the
    name reads upward. The plot view flips that rotation after each draw.
    """
    return {
        "title": {"text": shorten_colorbar_title(label), "side": "right"},
        "thickness": COLORBAR_THICKNESS_PX,
    }


def _colorbar_as_dict(colorbar: Any) -> dict[str, Any]:
    """Convert a Plotly ColorBar / mapping to a plain dict for updates."""
    if colorbar is None:
        return {}
    if isinstance(colorbar, dict):
        return dict(colorbar)
    to_json = getattr(colorbar, "to_plotly_json", None)
    if callable(to_json):
        try:
            raw = to_json()
            if isinstance(raw, dict):
                return dict(raw)
        except Exception:
            pass
    try:
        return {k: getattr(colorbar, k) for k in colorbar}
    except Exception:
        return {}


def attach_marker_size_legend(
    fig: Any,
    *,
    size_label: str | None,
    size_values: list[Any] | None,
    size_min_px: float = DEFAULT_MARKER_SIZE_MIN_PX,
    size_max_px: float = DEFAULT_MARKER_SIZE_MAX_PX,
) -> None:
    """Add a vertical size scale on the right of the plot (analogous to Color by's colorbar)."""
    from plotly import graph_objects as go

    label = (size_label or "").strip()
    if not label or label == "(none)":
        return
    levels = size_legend_levels(size_values, size_min_px=size_min_px, size_max_px=size_max_px)
    if not levels:
        return

    has_cbar = False
    for tr in fig.data:
        marker = getattr(tr, "marker", None)
        if marker is not None and bool(getattr(marker, "showscale", False)):
            has_cbar = True
            cbar = _colorbar_as_dict(getattr(marker, "colorbar", None))
            # Leave room below the colorbar for the size legend.
            cbar.setdefault("x", 1.02)
            cbar.setdefault("xanchor", "left")
            cbar["len"] = min(float(cbar.get("len") or 1.0), 0.48)
            cbar["y"] = 1.0
            cbar["yanchor"] = "top"
            try:
                tr.marker.colorbar = cbar
            except Exception:
                pass

    for tick_label, px in levels:
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                mode="markers",
                marker={
                    "size": float(px),
                    "color": "#4a4a4a",
                    "line": {"width": 0.5, "color": "#222"},
                    "opacity": 1.0,
                },
                name=str(tick_label),
                legendgroup="molmanager_size",
                showlegend=True,
                hoverinfo="skip",
            )
        )

    margin = {}
    try:
        raw_margin = fig.layout.margin
        if raw_margin is not None:
            margin = dict(raw_margin.to_plotly_json())
    except Exception:
        margin = {}
    margin["r"] = max(int(margin.get("r") or 0), 118 if has_cbar else 96)

    legend: dict[str, Any] = {
        "title": {"text": label},
        "itemsizing": "trace",
        "tracegroupgap": 10,
        "bgcolor": "rgba(255,255,255,0.92)",
        "bordercolor": "rgba(0,0,0,0.18)",
        "borderwidth": 1,
        "x": 1.02,
        "xanchor": "left",
        "orientation": "v",
        "font": {"size": 11},
    }
    if has_cbar:
        legend["y"] = 0.0
        legend["yanchor"] = "bottom"
    else:
        legend["y"] = 0.5
        legend["yanchor"] = "middle"

    fig.update_layout(showlegend=True, legend=legend, margin=margin)


def marker_sizes_from_column_values(
    raw_values: list[Any] | None,
    *,
    size_min_px: float = DEFAULT_MARKER_SIZE_MIN_PX,
    size_max_px: float = DEFAULT_MARKER_SIZE_MAX_PX,
    default_size: float = DEFAULT_MARKER_SIZE_PX,
) -> float | list[float]:
    """
    Map per-point column values to Plotly marker sizes (pixels).

    Numeric columns scale linearly between ``size_min_px`` and ``size_max_px``.
    Categorical columns get evenly spaced sizes across that range.
    Missing values use ``size_min_px``. Returns ``default_size`` when unused.
    """
    if not raw_values or not column_values_have_color_data(raw_values):
        return float(default_size)

    lo_px, hi_px = clamp_marker_size_bounds(size_min_px, size_max_px)
    if abs(hi_px - lo_px) < 1e-12:
        return lo_px

    numeric: list[float] = []
    for value in raw_values:
        parsed = _try_float(value)
        if parsed is None:
            numeric.clear()
            break
        numeric.append(parsed)

    if numeric:
        finite = [v for v in numeric if v == v]
        if not finite:
            return float(default_size)
        data_lo, data_hi = min(finite), max(finite)
        if abs(data_hi - data_lo) < 1e-12:
            return [(lo_px + hi_px) * 0.5] * len(numeric)
        span = data_hi - data_lo
        out: list[float] = []
        for v in numeric:
            if v != v:
                out.append(lo_px)
            else:
                t = (v - data_lo) / span
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                out.append(lo_px + t * (hi_px - lo_px))
        return out

    categories: list[str] = []
    for value in raw_values:
        if _is_missing(value):
            categories.append("(missing)")
        else:
            text = str(value).strip()
            categories.append(text if text else "(missing)")
    uniq = sorted(set(categories), key=lambda x: (x == "(missing)", x.lower()))
    if len(uniq) == 1:
        return [lo_px if uniq[0] == "(missing)" else (lo_px + hi_px) * 0.5] * len(categories)
    size_map = {cat: lo_px + (i / (len(uniq) - 1)) * (hi_px - lo_px) for i, cat in enumerate(uniq)}
    return [float(size_map[c]) for c in categories]


def _try_float(value: Any) -> float | None:
    if _is_missing(value):
        return float("nan")
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if hasattr(value, "item"):
        try:
            return float(value.item())
        except (TypeError, ValueError):
            pass
    text = str(value).strip().replace(",", "")
    if not text or text.upper() in _MISSING_TOKENS:
        return float("nan")
    try:
        return float(text)
    except ValueError:
        return None


def scatter_marker_from_column_values(
    raw_values: list[Any] | None,
    *,
    color_label: str | None = None,
    colorscale: str | None = None,
    color_min: float | None = None,
    color_max: float | None = None,
    size_values: list[Any] | None = None,
    size_min_px: float = DEFAULT_MARKER_SIZE_MIN_PX,
    size_max_px: float = DEFAULT_MARKER_SIZE_MAX_PX,
    default_color: str = "#2a74d6",
    point_size: float = DEFAULT_MARKER_SIZE_PX,
    opacity: float = DEFAULT_MARKER_OPACITY,
    symbol: str | None = None,
    scatter3d: bool = False,
) -> dict:
    """
    Build a Plotly ``marker`` dict for scatter traces from per-point column values.

    Numeric columns (including numeric strings from the table) use a continuous colorscale.
    Text/category columns use a fixed discrete palette.
    Optional ``size_values`` map a second column onto marker size between
    ``size_min_px`` and ``size_max_px``.
    ``symbol`` is a Plotly marker symbol (see ``PLOT_MARKER_SHAPES``).
    """
    size = marker_sizes_from_column_values(
        size_values,
        size_min_px=size_min_px,
        size_max_px=size_max_px,
        default_size=point_size,
    )
    opacity = clamp_marker_opacity(opacity)
    resolved_symbol = resolve_marker_symbol(symbol, scatter3d=scatter3d)

    def _done(marker: dict) -> dict:
        marker["symbol"] = resolved_symbol
        return marker

    if not raw_values or not column_values_have_color_data(raw_values):
        return _done({"size": size, "opacity": opacity, "color": default_color})

    numeric: list[float] = []
    for value in raw_values:
        parsed = _try_float(value)
        if parsed is None:
            numeric.clear()
            break
        numeric.append(parsed)

    if numeric:
        plot_colors = [float(v) if v == v else float("nan") for v in numeric]
        finite = [v for v in plot_colors if v == v]
        if not finite:
            return _done({"size": size, "opacity": opacity, "color": default_color})
        lo, hi = min(finite), max(finite)
        if color_min is not None:
            lo = float(color_min)
        if color_max is not None:
            hi = float(color_max)
        if lo > hi:
            lo, hi = hi, lo
        if abs(hi - lo) < 1e-12:
            lo -= 0.5
            hi += 0.5
        marker: dict = {
            "size": size,
            "opacity": opacity,
            "color": plot_colors,
            "colorscale": resolve_plot_colorscale(colorscale),
            "showscale": True,
            "cmin": lo,
            "cmax": hi,
        }
        if color_label:
            marker["colorbar"] = colorbar_for_label(color_label)
        return _done(marker)

    categories: list[str] = []
    for value in raw_values:
        if _is_missing(value):
            categories.append("(missing)")
        else:
            text = str(value).strip()
            categories.append(text if text else "(missing)")
    uniq = sorted(set(categories), key=lambda x: (x == "(missing)", x.lower()))
    color_map = {
        cat: _CATEGORICAL_PALETTE[i % len(_CATEGORICAL_PALETTE)] for i, cat in enumerate(uniq)
    }
    point_colors = [color_map[c] for c in categories]
    return _done(
        {
            "size": size,
            "opacity": opacity,
            "color": point_colors,
        }
    )
