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

"""Assign numeric table cells to bins and label them (Data → Similarity → Binning)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from ..chem.molecule_conversion import safe_float

BinMethod = Literal["equal_width", "equal_count", "custom"]

MAX_BINS = 256

BIN_METHODS: tuple[tuple[str, BinMethod], ...] = (
    ("Equal width", "equal_width"),
    ("Equal count", "equal_count"),
    ("Custom edges", "custom"),
)
# Low bin → high bin. Other counts use "Class 1", "Class 2", …
_CLASS_PRESETS: dict[int, tuple[str, ...]] = {
    2: ("Inactive", "Active"),
    3: ("Low", "Medium", "High"),
    4: ("Low", "Medium", "High", "Very high"),
}


@dataclass(frozen=True)
class BinInterval:
    """One bin. ``lo``/``hi`` may be infinite for open-ended custom bins."""

    lo: float
    hi: float
    left_closed: bool
    right_closed: bool


@dataclass(frozen=True)
class BinningParams:
    """Settings for writing a range column and a classification column."""

    source_column: str
    range_column: str
    class_column: str
    method: BinMethod
    bin_count: int = 5
    bin_width: float | None = None
    minimum: float | None = None
    maximum: float | None = None
    edges: tuple[float, ...] = ()
    open_ends: bool = True


@dataclass(frozen=True)
class BinnedColumn:
    """Range and class labels aligned with the input cells."""

    ranges: tuple[str, ...]
    classes: tuple[str, ...]
    range_names: tuple[str, ...]
    class_names: tuple[str, ...]
    numeric_count: int


def default_bin_column_name(source: str) -> str:
    """Default range-column header for *source*."""
    base = (source or "").strip() or "Value"
    return f"{base}_bin"


def default_class_column_name(source: str) -> str:
    """Default classification-column header for *source*."""
    base = (source or "").strip() or "Value"
    return f"{base}_class"


def parse_numeric_cell(text: object) -> float | None:
    """Finite float for a table cell, or None when the cell is not a plain number."""
    value = safe_float(text)
    if value is None or not math.isfinite(value):
        return None
    return float(value)


def parse_edges_text(text: str) -> tuple[float, ...]:
    """Parse strictly increasing edges from commas, semicolons, or whitespace."""
    parts = (text or "").replace(";", " ").replace(",", " ").split()
    if not parts:
        raise ValueError("Enter bin edges, for example 5, 6, 7.")
    edges: list[float] = []
    for part in parts:
        value = safe_float(part)
        if value is None or not math.isfinite(value):
            raise ValueError(f"Could not read edge {part!r}.")
        edges.append(float(value))
    for left, right in zip(edges, edges[1:]):
        if not right > left:
            raise ValueError("Edges must be strictly increasing.")
    if len(edges) > MAX_BINS + 1:
        raise ValueError(f"Use at most {MAX_BINS} bins.")
    return tuple(edges)


def classification_labels(n_bins: int) -> tuple[str, ...]:
    """Default class names from the low bin to the high bin."""
    if n_bins < 1:
        return ()
    preset = _CLASS_PRESETS.get(n_bins)
    if preset is not None:
        return preset
    return tuple(f"Class {i + 1}" for i in range(n_bins))


def bin_column_texts(texts: list[str], params: BinningParams) -> BinnedColumn:
    """Label each cell. Non-numeric cells are blank. Raises ``ValueError`` on bad settings."""
    numeric = [parse_numeric_cell(text) for text in texts]
    finite = [value for value in numeric if value is not None]
    if not finite:
        raise ValueError("No numeric values in the current scope.")
    intervals = _intervals_for(finite, params)
    range_names = tuple(_interval_label(interval) for interval in intervals)
    class_names = classification_labels(len(intervals))
    ranges: list[str] = []
    classes: list[str] = []
    for value in numeric:
        if value is None or not _value_in_requested_span(value, params):
            ranges.append("")
            classes.append("")
            continue
        range_label = ""
        class_label = ""
        for interval, range_name, class_name in zip(intervals, range_names, class_names):
            if _contains(interval, value):
                range_label = range_name
                class_label = class_name
                break
        ranges.append(range_label)
        classes.append(class_label)
    if not any(ranges):
        raise ValueError("No values fell into a bin. Check the edges and range.")
    return BinnedColumn(
        tuple(ranges),
        tuple(classes),
        range_names,
        class_names,
        len(finite),
    )


def _value_in_requested_span(value: float, params: BinningParams) -> bool:
    """Equal-width Min/Max exclude values outside that span. Other methods do not."""
    if params.method != "equal_width":
        return True
    if params.minimum is not None and value < params.minimum:
        return False
    if params.maximum is not None and value > params.maximum:
        return False
    return True


def _intervals_for(values: list[float], params: BinningParams) -> tuple[BinInterval, ...]:
    if params.method == "custom":
        intervals = _custom_intervals(list(params.edges), open_ends=params.open_ends)
    elif params.method == "equal_count":
        intervals = _equal_count_intervals(values, params.bin_count)
    elif params.method == "equal_width":
        intervals = _equal_width_intervals(values, params)
    else:
        raise ValueError("Choose a binning method.")
    if not intervals:
        raise ValueError("No bins were produced.")
    if len(intervals) > MAX_BINS:
        raise ValueError(f"Too many bins ({len(intervals)}). Use at most {MAX_BINS}.")
    return tuple(intervals)


def _custom_intervals(cuts: list[float], *, open_ends: bool) -> list[BinInterval]:
    if not cuts:
        raise ValueError("Enter bin edges, for example 5, 6, 7.")
    for left, right in zip(cuts, cuts[1:]):
        if not right > left:
            raise ValueError("Edges must be strictly increasing.")
    if open_ends:
        intervals = [BinInterval(float("-inf"), cuts[0], False, False)]
        for lo, hi in zip(cuts, cuts[1:]):
            intervals.append(BinInterval(lo, hi, True, False))
        intervals.append(BinInterval(cuts[-1], float("inf"), True, False))
        return intervals
    if len(cuts) < 2:
        raise ValueError("Enter at least two edges, or turn on Open ends.")
    return _closed_intervals(cuts)


def _equal_width_intervals(values: list[float], params: BinningParams) -> list[BinInterval]:
    data_lo = min(values)
    data_hi = max(values)
    lo = data_lo if params.minimum is None else float(params.minimum)
    hi = data_hi if params.maximum is None else float(params.maximum)
    if lo > hi and not math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        raise ValueError("No numeric values fall inside the minimum and maximum.")
    if params.bin_width is not None:
        if params.minimum is None and params.maximum is None:
            edges = _aligned_width_edges(data_lo, data_hi, float(params.bin_width))
        else:
            edges = _bounded_width_edges(lo, hi, float(params.bin_width))
    elif math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        edges = [lo, hi]
    else:
        edges = _count_edges(lo, hi, params.bin_count)
    return _closed_intervals(edges)


def _count_edges(lo: float, hi: float, n_bins: int) -> list[float]:
    _require_bin_count(n_bins)
    edges = [lo + i * (hi - lo) / n_bins for i in range(n_bins)]
    edges.append(hi)
    return edges


def _aligned_width_edges(lo: float, hi: float, width: float) -> list[float]:
    """Width-aligned edges, matching histogram bins when the span is not a single point."""
    if not width > 0:
        raise ValueError("Bin width must be greater than zero.")
    if math.isclose(lo, hi, rel_tol=0.0, abs_tol=1e-12):
        start = math.floor(lo / width) * width
        return [start, start + width]
    start = math.floor(lo / width) * width
    end = math.ceil(hi / width) * width
    if math.isclose(start, end, rel_tol=0.0, abs_tol=1e-12):
        end = start + width
    edges: list[float] = []
    x = start
    guard = 0
    limit = MAX_BINS + 2
    while x <= end + abs(end) * 1e-9 and guard < limit:
        edges.append(x)
        x += width
        guard += 1
    if guard >= limit or len(edges) - 1 > MAX_BINS:
        raise ValueError(f"Bin width produces more than {MAX_BINS} bins. Use a wider bin.")
    if len(edges) < 2:
        return [lo, lo + width]
    return edges


def _bounded_width_edges(lo: float, hi: float, width: float) -> list[float]:
    """Step *width* from *lo* and stop at *hi* (the user's Min/Max span)."""
    if not width > 0:
        raise ValueError("Bin width must be greater than zero.")
    if not hi > lo:
        return [lo, hi]
    edges = [lo]
    x = lo
    guard = 0
    while guard < MAX_BINS:
        nxt = x + width
        if nxt >= hi or math.isclose(nxt, hi, rel_tol=0.0, abs_tol=1e-9 * max(1.0, abs(hi))):
            break
        edges.append(nxt)
        x = nxt
        guard += 1
    else:
        raise ValueError(f"Bin width produces more than {MAX_BINS} bins. Use a wider bin.")
    edges.append(hi)
    return edges


def _equal_count_intervals(values: list[float], n_bins: int) -> list[BinInterval]:
    """
    Split *values* into up to *n_bins* groups of nearly equal size.

    Identical values stay in one bin, so heavy ties can yield fewer bins than requested.
    A boundary value belongs to the higher bin.
    """
    _require_bin_count(n_bins)
    ordered = sorted(values)
    n = len(ordered)
    assignment = [min(n_bins - 1, i * n_bins // n) for i in range(n)]
    for i in range(1, n):
        if ordered[i] == ordered[i - 1]:
            assignment[i] = assignment[i - 1]
    groups: list[list[float]] = []
    current = [ordered[0]]
    current_id = assignment[0]
    for i in range(1, n):
        if assignment[i] != current_id:
            groups.append(current)
            current = [ordered[i]]
            current_id = assignment[i]
        else:
            current.append(ordered[i])
    groups.append(current)
    intervals: list[BinInterval] = []
    for i, group in enumerate(groups):
        lo = group[0]
        if i < len(groups) - 1:
            intervals.append(BinInterval(lo, groups[i + 1][0], True, False))
        else:
            intervals.append(BinInterval(lo, group[-1], True, True))
    return intervals


def _closed_intervals(edges: list[float]) -> list[BinInterval]:
    if len(edges) < 2:
        raise ValueError("At least one bin is required.")
    n = len(edges) - 1
    intervals: list[BinInterval] = []
    for i in range(n):
        lo, hi = edges[i], edges[i + 1]
        last = i == n - 1
        intervals.append(BinInterval(lo, hi, True, last or lo == hi))
    return intervals


def _require_bin_count(n_bins: int) -> None:
    if n_bins < 2:
        raise ValueError("Enter at least 2 bins.")
    if n_bins > MAX_BINS:
        raise ValueError(f"Use at most {MAX_BINS} bins.")


def _format_edge(value: float) -> str:
    if math.isinf(value):
        return "inf" if value > 0 else "-inf"
    text = f"{float(value):.12g}"
    if text in ("-0", "-0.0"):
        return "0"
    return text


def _interval_label(interval: BinInterval) -> str:
    if math.isinf(interval.lo) and not math.isinf(interval.hi):
        return f"< {_format_edge(interval.hi)}"
    if math.isinf(interval.hi) and not math.isinf(interval.lo):
        return f"≥ {_format_edge(interval.lo)}"
    if interval.lo == interval.hi:
        return _format_edge(interval.lo)
    if interval.right_closed:
        return f"[{_format_edge(interval.lo)}, {_format_edge(interval.hi)}]"
    return f"[{_format_edge(interval.lo)}, {_format_edge(interval.hi)})"


def _contains(interval: BinInterval, value: float) -> bool:
    if interval.left_closed:
        if value < interval.lo:
            return False
    elif value <= interval.lo:
        return False
    if interval.right_closed:
        if value > interval.hi:
            return False
    elif value >= interval.hi:
        return False
    return True
