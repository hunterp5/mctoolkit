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
the page map: that combination has not been made.
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from typing import Sequence

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
    """One slice of the grid. Missing pairs are not in ``cells``."""

    label: str
    row_labels: tuple[str, ...]
    col_labels: tuple[str, ...]
    cells: dict[tuple[str, str], SarCell]

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
        pages.append(
            SarPage(
                label=page_label,
                row_labels=row_labels,
                col_labels=col_labels,
                cells=cells,
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
    """Rectangular text for one page. Unmade cells are blank."""
    header = [row_axis, *page.col_labels]
    body: list[list[str]] = []
    for row_label in page.row_labels:
        line = [row_label]
        for col_label in page.col_labels:
            cell = page.cells.get((row_label, col_label))
            line.append("" if cell is None else cell.grid_text())
        body.append(line)
    return [header, *body]


def sar_page_csv(page: SarPage, *, row_axis: str) -> str:
    """CSV of :func:`sar_page_rows`."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(sar_page_rows(page, row_axis=row_axis))
    return buffer.getvalue()
