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

"""Numeric min/max scan helpers for filter slider bounds (Qt-free)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ..conformers.conformer_column_codec import is_packed_ensemble_header
from ..chem.molecule_conversion import safe_float

# Packed multi-conformer / alignment / dock-pose payloads — not numeric filter columns.
NON_NUMERIC_BLOB_COLUMNS = frozenset({"confs", "superpose", "poses"})


def is_non_numeric_blob_header(header: str) -> bool:
    """True when *header* is a packed ensemble column (including ``confs (1)``, ``poses_2``)."""
    name = str(header or "").strip()
    return name in NON_NUMERIC_BLOB_COLUMNS or is_packed_ensemble_header(name)


def merge_numeric_bounds_rows(
    rows: Sequence[Any],
    header: str,
    start_row: int,
    end_row: int,
    acc: dict | None,
) -> dict | None:
    """Merge numeric min/max for ``rows[start_row:end_row]`` into *acc*.

    Each row must expose a ``.values`` mapping of header → cell text.
    """
    lo = acc.get("min") if acc else None
    hi = acc.get("max") if acc else None
    int_ok = bool(acc.get("is_int", True)) if acc else True
    start = max(0, int(start_row))
    end = min(len(rows), int(end_row))
    for row in rows[start:end]:
        f = safe_float(row.values.get(header, ""))
        if f is None:
            continue
        fv = float(f)
        if lo is None:
            lo = hi = fv
            int_ok = f.is_integer()
        else:
            if fv < lo:
                lo = fv
            if fv > hi:
                hi = fv
            if not f.is_integer():
                int_ok = False
    if lo is None:
        return None
    return {"min": lo, "max": hi, "is_int": int_ok}


def merge_numeric_range(acc: dict | None, lo: float, hi: float, is_int: bool) -> dict:
    """Fold one ``(min, max, all_integers)`` range into the bounds accumulator *acc*."""
    if not acc:
        return {"min": lo, "max": hi, "is_int": is_int}
    return {
        "min": min(acc["min"], lo),
        "max": max(acc["max"], hi),
        "is_int": bool(acc.get("is_int", True)) and is_int,
    }


def scan_numeric_column(rows: Sequence[Any], header: str) -> dict | None:
    """Full-column numeric bounds scan."""
    return merge_numeric_bounds_rows(rows, header, 0, len(rows), None)
