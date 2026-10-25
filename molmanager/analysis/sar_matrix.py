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

"""Pivot R-group columns into an R1 × R2 activity grid.

A third substituent becomes pages. A cell that no row occupies is absent from
the page map: that combination has not been made. When the additive model can
separate the substituents, that empty cell carries a Free-Wilson prediction.
"""

from __future__ import annotations

import csv
import io
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Sequence

import numpy as np

from .linear_fit import design_columns_with_intercept, fit_linear

_RGROUP_HEADER = re.compile(r"(?:^|_)R(\d+)$", re.IGNORECASE)
_BLANK = frozenset({"", "n/a", "na", "none", "null", "nan"})
MAX_SAR_AXIS_LABELS = 60


class SarMatrixLimit(ValueError):
    """The series cannot be drawn as a grid."""


@dataclass(frozen=True)
class SarObservation:
    """One table row placed on the grid."""

    oid: int
    row_label: str
    col_label: str
    page_label: str
    activity: float | None


@dataclass(frozen=True)
class SarCell:
    """Every compound that landed on one substituent pair."""

    oids: tuple[int, ...]
    activities: tuple[float | None, ...]

    def display_value(self) -> float | None:
        """Mean of the numeric activities, or ``None`` when none are numeric."""
        nums = [value for value in self.activities if value is not None]
        if not nums:
            return None
        return sum(nums) / len(nums)

    def grid_text(self) -> str:
        """Cell text. A count is appended when more than one compound shares the cell."""
        value = self.display_value()
        n = len(self.oids)
        if value is None:
            body = "—"
        else:
            body = f"{value:.4g}"
        if n > 1:
            return f"{body} ({n})"
        return body


@dataclass(frozen=True)
class SarPage:
    """One slice of the grid. Missing pairs are not in ``cells``.

    ``predictions`` holds Free-Wilson values for unmade pairs the additive model
    can separate. Pairs it cannot separate are absent from both maps.
    """

    label: str
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    cells: dict[tuple[str, str], SarCell]
    predictions: dict[tuple[str, str], float]

    def filled_count(self) -> int:
        return len(self.cells)

    def empty_count(self) -> int:
        return len(self.row_labels) * len(self.col_labels) - len(self.cells)


@dataclass(frozen=True)
class SarMatrix:
    """All pages of one pivot. Row and column labels are shared across pages."""

    row_axis: str
    col_axis: str
    page_axis: str
    activity_axis: str
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    pages: tuple[SarPage, ...]
    value_min: float | None
    value_max: float | None

    def page(self, index: int) -> SarPage:
        return self.pages[index]


def rgroup_index(name: str) -> int | None:
    """Attachment number when *name* ends in ``R1``, ``R2``, …, else ``None``."""
    match = _RGROUP_HEADER.search((name or "").strip())
    if match is None:
        return None
    return int(match.group(1))


def suggest_rgroup_axes(headers: Sequence[str]) -> tuple[str | None, str | None, str | None]:
    """Return ``(row, column, page)`` from headers named like ``RGD_R1``.

    The page axis is set only when a third R column exists.
    """
    ranked = sorted(
        (name for name in headers if rgroup_index(name) is not None),
        key=lambda name: (rgroup_index(name) or 0, name.casefold()),
    )
    row = ranked[0] if len(ranked) > 0 else None
    col = ranked[1] if len(ranked) > 1 else None
    page = ranked[2] if len(ranked) > 2 else None
    return row, col, page


def _is_blank(label: str) -> bool:
    return (label or "").strip().casefold() in _BLANK


def _label_key(label: str) -> str:
    return label.casefold()


def build_sar_matrix(
    observations: Sequence[SarObservation],
    *,
    row_axis: str,
    col_axis: str,
    page_axis: str = "",
    activity_axis: str,
    max_labels: int = MAX_SAR_AXIS_LABELS,
) -> SarMatrix:
    """Group observations into pages of an R1 × R2 grid.

    Labels are the union across pages, so switching pages does not move a
    substituent. Rows with a blank substituent, or a blank page when a page
    axis is set, are left out.
    """
    kept: list[SarObservation] = []
    for obs in observations:
        row_label = (obs.row_label or "").strip()
        col_label = (obs.col_label or "").strip()
        page_label = (obs.page_label or "").strip()
        if _is_blank(row_label) or _is_blank(col_label):
            continue
        if page_axis and _is_blank(page_label):
            continue
        if not page_axis:
            page_label = ""
        kept.append(
            SarObservation(
                oid=int(obs.oid),
                row_label=row_label,
                col_label=col_label,
                page_label=page_label,
                activity=obs.activity,
            )
        )
    if not kept:
        raise SarMatrixLimit("No rows have both substituent columns filled.")

    row_labels = tuple(sorted({obs.row_label for obs in kept}, key=_label_key))
    col_labels = tuple(sorted({obs.col_label for obs in kept}, key=_label_key))
    if len(row_labels) > max_labels:
        raise SarMatrixLimit(
            f"{row_axis} has {len(row_labels)} substituents. "
            f"Filter the series to {max_labels} or fewer."
        )
    if len(col_labels) > max_labels:
        raise SarMatrixLimit(
            f"{col_axis} has {len(col_labels)} substituents. "
            f"Filter the series to {max_labels} or fewer."
        )

    page_labels = tuple(sorted({obs.page_label for obs in kept}, key=_label_key))
    grouped: dict[tuple[str, str, str], list[SarObservation]] = {}
    for obs in kept:
        grouped.setdefault((obs.page_label, obs.row_label, obs.col_label), []).append(obs)

    finite = [obs for obs in kept if _finite_activity(obs.activity)]
    predicted = _predict_missing(
        finite,
        row_labels=row_labels,
        col_labels=col_labels,
        page_labels=page_labels,
        use_page=bool(page_axis),
    )
    pages: list[SarPage] = []
    display_values: list[float] = []
    for page_label in page_labels:
        cells: dict[tuple[str, str], SarCell] = {}
        for (page, row_label, col_label), members in grouped.items():
            if page != page_label:
                continue
            paired = sorted(
                ((int(member.oid), member.activity) for member in members),
                key=lambda item: item[0],
            )
            cell = SarCell(
                oids=tuple(oid for oid, _activity in paired),
                activities=tuple(activity for _oid, activity in paired),
            )
            cells[(row_label, col_label)] = cell
            value = cell.display_value()
            if value is not None:
                display_values.append(value)
        page_predictions = {
            (row_label, col_label): value
            for (page, row_label, col_label), value in predicted.items()
            if page == page_label and (row_label, col_label) not in cells
        }
        display_values.extend(page_predictions.values())
        pages.append(
            SarPage(
                label=page_label,
                row_labels=row_labels,
                col_labels=col_labels,
                cells=cells,
                predictions=page_predictions,
            )
        )

    return SarMatrix(
        row_axis=row_axis,
        col_axis=col_axis,
        page_axis=page_axis,
        activity_axis=activity_axis,
        row_labels=row_labels,
        col_labels=col_labels,
        pages=tuple(pages),
        value_min=min(display_values) if display_values else None,
        value_max=max(display_values) if display_values else None,
    )


def sar_page_rows(page: SarPage, *, row_axis: str) -> list[list[str]]:
    """Rectangular text for one page.

    Measured cells use their grid text. A Free-Wilson prediction is prefixed
    with ``≈``. A pair the model cannot separate stays blank.
    """
    header = [row_axis, *page.col_labels]
    body: list[list[str]] = []
    for row_label in page.row_labels:
        line = [row_label]
        for col_label in page.col_labels:
            cell = page.cells.get((row_label, col_label))
            if cell is not None:
                line.append(cell.grid_text())
            else:
                predicted = page.predictions.get((row_label, col_label))
                line.append("" if predicted is None else f"≈{predicted:.4g}")
        body.append(line)
    return [header, *body]


def sar_recommendation(matrix: SarMatrix, *, higher_is_better: bool) -> str:
    """Name the best unmade pair when its prediction beats every measured cell.

    Otherwise name the best measured pair. An empty string means the grid has
    no numeric activity to compare.
    """
    measured: list[tuple[float, str, str, str]] = []
    predicted: list[tuple[float, str, str, str]] = []
    for page in matrix.pages:
        for (row_label, col_label), cell in page.cells.items():
            value = cell.display_value()
            if value is not None:
                measured.append((value, row_label, col_label, page.label))
        for (row_label, col_label), value in page.predictions.items():
            predicted.append((value, row_label, col_label, page.label))
    if not measured:
        return ""
    best_made = _best_entry(measured, higher_is_better=higher_is_better)
    made_name = _combination_name(matrix, best_made)
    if not predicted:
        return f"Best pair is already made ({made_name}, {_format_activity(best_made[0])})."
    best_open = _best_entry(predicted, higher_is_better=higher_is_better)
    if _is_better(best_open[0], best_made[0], higher_is_better=higher_is_better):
        relation = "above" if higher_is_better else "below"
        return (
            f"Best unmade: {_combination_name(matrix, best_open)}, "
            f"predicted {_format_activity(best_open[0])}, {relation} "
            f"{made_name} ({_format_activity(best_made[0])})."
        )
    return f"Best pair is already made ({made_name}, {_format_activity(best_made[0])})."


def _finite_activity(value: float | None) -> bool:
    return value is not None and math.isfinite(value)


def _axis_label(obs: SarObservation, axis: str) -> str:
    if axis == "row":
        return obs.row_label
    if axis == "col":
        return obs.col_label
    return obs.page_label


def _reference_label(counts: Counter[str]) -> str:
    if "H" in counts:
        return "H"
    return min(counts, key=lambda key: (-counts[key], key))


def _predict_missing(
    observations: Sequence[SarObservation],
    *,
    row_labels: tuple[str, ...],
    col_labels: tuple[str, ...],
    page_labels: tuple[str, ...],
    use_page: bool,
) -> dict[tuple[str, str, str], float]:
    """Fujita-Ban prediction for unmade combinations the design can separate.

    A substituent that is an exact copy of another is left out, and so is a
    column that is not estimable beside the intercept. A missing pair is filled
    only when its substituents sit in one connected piece of the observed grid,
    so two disjoint series do not invent a cross-term.
    """
    usable = [obs for obs in observations if _finite_activity(obs.activity)]
    if len(usable) < 2:
        return {}
    axes = ["row", "col"]
    if use_page:
        axes.append("page")
    counts = {axis: Counter(_axis_label(obs, axis) for obs in usable) for axis in axes}
    reference = {axis: _reference_label(counts[axis]) for axis in axes if counts[axis]}
    columns: list[tuple[str, str]] = []
    for axis in axes:
        if axis not in reference:
            continue
        others = [label for label in counts[axis] if label != reference[axis]]
        for label in sorted(others, key=_label_key):
            columns.append((axis, label))
    design = np.zeros((len(usable), len(columns)), dtype=float)
    for row_index, obs in enumerate(usable):
        present = {axis: _axis_label(obs, axis) for axis in axes}
        for column_index, (axis, label) in enumerate(columns):
            if present.get(axis) == label:
                design[row_index, column_index] = 1.0
    kept_columns = _estimable_columns(design)
    if columns and not kept_columns:
        return {}
    reduced = design[:, kept_columns] if kept_columns else np.zeros((len(usable), 0))
    fit = fit_linear(
        np.array([float(obs.activity) for obs in usable], dtype=float),
        reduced,
    )
    coefficient = {
        columns[index]: fit.coefficients[offset] for offset, index in enumerate(kept_columns)
    }
    components = _component_roots(usable, use_page=use_page)
    predictions: dict[tuple[str, str, str]] = {}
    for page_label in page_labels:
        for row_label in row_labels:
            for col_label in col_labels:
                chosen = {"row": row_label, "col": col_label}
                if use_page:
                    chosen["page"] = page_label
                if not _connected(components, chosen):
                    continue
                total, ok = _combination_value(chosen, reference, coefficient, fit.intercept)
                if ok:
                    predictions[(page_label, row_label, col_label)] = total
    return predictions


def _estimable_columns(design: np.ndarray) -> list[int]:
    """Column indices that stay independent beside the intercept.

    Exact copies are removed as a group. Keeping one copy would assign the
    shared effect to a single substituent.
    """
    width = int(design.shape[1])
    if width == 0:
        return []
    copied: set[int] = set()
    for left in range(width):
        for right in range(left + 1, width):
            if np.allclose(design[:, left], design[:, right]):
                copied.add(left)
                copied.add(right)
    remaining = [index for index in range(width) if index not in copied]
    if not remaining:
        return []
    kept = design_columns_with_intercept(design[:, remaining])
    return [remaining[index] for index in kept]


def _combination_value(
    chosen: dict[str, str],
    reference: dict[str, str],
    coefficient: dict[tuple[str, str], float],
    intercept: float,
) -> tuple[float, bool]:
    total = float(intercept)
    for axis, label in chosen.items():
        if reference.get(axis) == label:
            continue
        value = coefficient.get((axis, label))
        if value is None:
            return 0.0, False
        total += float(value)
    return total, True


def _component_roots(
    observations: Sequence[SarObservation],
    *,
    use_page: bool,
) -> dict[tuple[str, str], tuple[str, str]]:
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(node: tuple[str, str]) -> tuple[str, str]:
        parent.setdefault(node, node)
        while parent[node] != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    def union(left: tuple[str, str], right: tuple[str, str]) -> None:
        left_root = find(left)
        right_root = find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    for obs in observations:
        nodes = [("row", obs.row_label), ("col", obs.col_label)]
        if use_page:
            nodes.append(("page", obs.page_label))
        for node in nodes:
            find(node)
        for other in nodes[1:]:
            union(nodes[0], other)
    return {node: find(node) for node in parent}


def _connected(roots: dict[tuple[str, str], tuple[str, str]], chosen: dict[str, str]) -> bool:
    found: list[tuple[str, str]] = []
    for axis, label in chosen.items():
        root = roots.get((axis, label))
        if root is None:
            return False
        found.append(root)
    return len(set(found)) == 1


def _best_entry(
    entries: list[tuple[float, str, str, str]],
    *,
    higher_is_better: bool,
) -> tuple[float, str, str, str]:
    def sort_key(entry: tuple[float, str, str, str]) -> tuple[float, str, str, str]:
        value, row_label, col_label, page_label = entry
        rank = -value if higher_is_better else value
        return (rank, row_label.casefold(), col_label.casefold(), page_label.casefold())

    return min(entries, key=sort_key)


def _is_better(candidate: float, incumbent: float, *, higher_is_better: bool) -> bool:
    if higher_is_better:
        return candidate > incumbent
    return candidate < incumbent


def _combination_name(matrix: SarMatrix, entry: tuple[float, str, str, str]) -> str:
    _value, row_label, col_label, page_label = entry
    parts = [f"{matrix.row_axis}={row_label}", f"{matrix.col_axis}={col_label}"]
    if matrix.page_axis and page_label:
        parts.append(f"{matrix.page_axis}={page_label}")
    return ", ".join(parts)


def _format_activity(value: float) -> str:
    return f"{value:.4g}"


def sar_page_csv(page: SarPage, *, row_axis: str) -> str:
    """CSV of :func:`sar_page_rows`."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(sar_page_rows(page, row_axis=row_axis))
    return buffer.getvalue()
