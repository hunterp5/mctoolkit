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

"""Row-index helpers for table selection."""

from __future__ import annotations


def merge_sorted_row_indices(rows: list[int]) -> list[tuple[int, int]]:
    """Merge sorted unique row indices into inclusive ``(lo, hi)`` spans."""
    if not rows:
        return []
    uniq = sorted({int(r) for r in rows})
    spans: list[tuple[int, int]] = []
    lo = hi = uniq[0]
    for r in uniq[1:]:
        if r == hi + 1:
            hi = r
        else:
            spans.append((lo, hi))
            lo = hi = r
    spans.append((lo, hi))
    return spans
