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

"""Filter OID computation helpers (no Qt)."""

from __future__ import annotations

import math
import sqlite3
from collections.abc import Callable
from pathlib import Path

from ..chem.molecule_conversion import safe_float
from ..services.sqlite_text_match import sqlite_text_match_clause


def _nonempty_text_sql(quoted_column: str) -> str:
    """True when a text cell has a non-blank value."""
    return f"TRIM(COALESCE(\"{quoted_column}\", '')) <> ''"


def _mm_numeric_match(value: object, lo: float, hi: float, inverted: int) -> int:
    """1 when *value* is a finite number inside (or, if inverted, outside) the range.

    Blank and non-numeric cells never match. SQLite ``CAST(x AS REAL)`` turns those
    into 0, which would otherwise pass a range that includes 0.
    """
    number = safe_float(value)
    if number is None or not math.isfinite(number):
        return 0
    inside = float(lo) <= float(number) <= float(hi)
    if inverted:
        return 0 if inside else 1
    return 1 if inside else 0


def _connect_readonly(db_path: str | Path) -> sqlite3.Connection:
    uri = f"file:{Path(db_path).resolve()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.create_function("mm_numeric_match", 4, _mm_numeric_match, deterministic=True)
    return conn


def build_sqlite_where(
    filter_specs: list[dict],
    *,
    headers: list[str],
) -> tuple[str, tuple] | None:
    """Build SQL WHERE clause for simple enabled filters; None when unsupported."""
    header_set = set(headers)
    where_parts: list[str] = []
    args: list[object] = []
    for spec in filter_specs:
        kind = str(spec.get("kind") or "")
        if kind == "substructure":
            if spec.get("enabled", True):
                return None
            continue
        if not spec.get("enabled", True):
            continue
        if kind == "category":
            prop = str(spec.get("column") or "")
            if not prop or prop not in header_set:
                continue
            checked = [str(v) for v in (spec.get("values") or []) if str(v).strip()]
            qp = prop.replace('"', '""')
            nonempty = _nonempty_text_sql(qp)
            if spec.get("inverted", False):
                if not checked:
                    where_parts.append(f"({nonempty})")
                else:
                    placeholders = ", ".join(["?"] * len(checked))
                    where_parts.append(f'({nonempty} AND "{qp}" NOT IN ({placeholders}))')
                    args.extend(sorted(checked))
            elif not checked:
                where_parts.append("0")
            else:
                placeholders = ", ".join(["?"] * len(checked))
                where_parts.append(f'"{qp}" IN ({placeholders})')
                args.extend(sorted(checked))
            continue
        if kind == "numeric":
            prop = str(spec.get("column") or "")
            if not prop or prop not in header_set:
                continue
            qp = prop.replace('"', '""')
            lo = float(spec.get("min", 0.0))
            hi = float(spec.get("max", 0.0))
            where_parts.append(f'(mm_numeric_match("{qp}", ?, ?, ?))')
            args.extend([lo, hi, 1 if spec.get("inverted", False) else 0])
            continue
        if kind == "text":
            prop = str(spec.get("column") or "")
            needle = str(spec.get("text", "") or "").strip()
            if not prop or not needle:
                continue
            qp = prop.replace('"', '""')
            expr, match_args = sqlite_text_match_clause(
                qp,
                needle,
                partial=bool(spec.get("partial_match", True)),
                case_sensitive=bool(spec.get("case_sensitive", False)),
            )
            if spec.get("inverted", False):
                where_parts.append(f"({_nonempty_text_sql(qp)} AND NOT ({expr}))")
            else:
                where_parts.append(f"({expr})")
            args.extend(match_args)
            continue
        return None
    if not where_parts:
        return None
    return " AND ".join(where_parts), tuple(args)


def sqlite_count_matching(db_path: str | Path, where_sql: str, args: tuple) -> int:
    conn = _connect_readonly(db_path)
    try:
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM table_rows WHERE {where_sql}",
            args,
        ).fetchone()
        return int(row[0]) if row is not None else 0
    finally:
        conn.close()


def fetch_matching_oids(
    db_path: str | Path,
    where_sql: str,
    args: tuple,
    *,
    page_size: int = 5000,
    progress_cb: Callable[[int, int], None] | None = None,
) -> frozenset[int]:
    """Fetch all OIDs matching ``where_sql`` using a read-only SQLite connection."""
    conn = _connect_readonly(db_path)
    try:
        page = max(1, int(page_size))
        out: set[int] = set()
        last_oid: int | None = None
        where = f"({where_sql})" if where_sql else "1"
        while True:
            bind: list[object] = list(args)
            extra = ""
            if last_oid is not None:
                extra = " AND oid > ?"
                bind.append(int(last_oid))
            bind.append(page)
            rows = conn.execute(
                f"SELECT oid FROM table_rows WHERE {where}{extra} ORDER BY oid ASC LIMIT ?",
                tuple(bind),
            ).fetchall()
            if not rows:
                break
            for rec in rows:
                out.add(int(rec[0]))
            last_oid = int(rows[-1][0])
            if progress_cb is not None:
                n = len(out)
                progress_cb(n, max(n, 1))
            if len(rows) < page:
                break
        if progress_cb is not None and not out:
            progress_cb(0, 1)
        return frozenset(out)
    finally:
        conn.close()
