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

"""OID / row selection helpers used by the main table (no Qt)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence


def oids_for_source_rows(
    source_rows: Sequence[int],
    *,
    row_oid: Callable[[int], int],
) -> frozenset[int]:
    """Map source-model row indices to compound OIDs."""
    oids: set[int] = set()
    for r in source_rows:
        try:
            oids.add(int(row_oid(int(r))))
        except (IndexError, ValueError, TypeError):
            continue
    return frozenset(oids)


def oids_from_id_hidden_cells(
    rows: Sequence[int],
    *,
    cell_text_col0: Callable[[int], str],
) -> frozenset[int]:
    """Read OIDs from column-0 text (``ID_HIDDEN``) for the given rows."""
    oids: set[int] = set()
    for r in rows:
        try:
            t0 = cell_text_col0(int(r))
        except (IndexError, TypeError, ValueError):
            continue
        if str(t0).isdigit():
            oids.add(int(t0))
    return frozenset(oids)


def logical_rows_for_oids(
    oids: Iterable[int],
    *,
    logical_row_for_oid: Callable[[int], int],
) -> list[int]:
    """Sorted unique logical rows for the given OIDs (skips missing)."""
    rows: list[int] = []
    for oid in oids:
        try:
            r = int(logical_row_for_oid(int(oid)))
        except (TypeError, ValueError):
            continue
        if r >= 0:
            rows.append(r)
    return sorted(set(rows))


def first_rows_for_distinct_keys(
    row_indices: Iterable[int],
    *,
    key_for_row: Callable[[int], str],
) -> list[int]:
    """Keep the first row for each non-empty key (stable order)."""
    seen: set[str] = set()
    out: list[int] = []
    for r in row_indices:
        key = (key_for_row(int(r)) or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(int(r))
    return out


def rows_where(
    row_indices: Iterable[int],
    *,
    predicate: Callable[[int], bool],
) -> list[int]:
    """Return rows for which *predicate* is true."""
    return [int(r) for r in row_indices if predicate(int(r))]


def cached_string_key(
    value: str,
    cache: dict[str, str] | None,
    *,
    key_fn: Callable[[str], str | None],
    fallback_to_value: bool = True,
) -> str:
    """Memoize a string→key transform (e.g. canonical SMILES)."""
    s = (value or "").strip()
    if not s:
        return ""
    if cache is not None and s in cache:
        return cache[s]
    key = key_fn(s)
    if not key:
        key = s if fallback_to_value else ""
    else:
        key = str(key)
    if cache is not None:
        cache[s] = key
    return key


def collect_canonical_keys_from_column(
    row_count: int,
    *,
    cell_text: Callable[[int], str],
    key_fn: Callable[[str], str | None],
) -> set[str]:
    """Build the set of canonical keys present in one text column."""
    keys: set[str] = set()
    for r in range(int(row_count)):
        raw = (cell_text(r) or "").strip()
        if not raw:
            continue
        k = key_fn(raw)
        if k:
            keys.add(k)
    return keys
