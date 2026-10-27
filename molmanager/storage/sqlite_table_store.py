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

"""SQLite-backed row store with paged reads and simple filter/sort pushdown."""

from __future__ import annotations

import sqlite3
from pathlib import Path


def _quoted_ident(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def unlink_sqlite_files(path: str | Path) -> None:
    """Delete a SQLite file and its WAL sidecars. Missing files are ignored."""
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            pass


class SqliteTableStore:
    """Materialize row dicts in SQLite and query them in pages."""

    def __init__(self, db_path: str | Path | None = None, *, delete_on_close: bool = False) -> None:
        if db_path is None:
            from ..platform_support.session_runtime import current_runtime

            self._path = current_runtime().allocate_sqlite("table-cache-")
            self._delete_on_close = True
        else:
            self._path = Path(db_path)
            self._delete_on_close = delete_on_close
        self._conn = sqlite3.connect(str(self._path))
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA temp_store=MEMORY")
        except sqlite3.Error:
            pass
        self._headers: list[str] = []
        self._bulk_loading = False
        self._load_headers_from_schema()

    @property
    def bulk_loading(self) -> bool:
        return self._bulk_loading

    @property
    def headers(self) -> list[str]:
        return list(self._headers)

    @property
    def db_path(self) -> Path:
        return self._path

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
        if self._delete_on_close:
            unlink_sqlite_files(self._path)

    def _data_columns(self, headers: list[str]) -> list[str]:
        return [h for h in headers if h not in ("ID_HIDDEN", "Structure")]

    def _load_headers_from_schema(self) -> None:
        """Populate ``_headers`` from an existing ``table_rows`` schema, if any."""
        try:
            rows = self._conn.execute("PRAGMA table_info(table_rows)").fetchall()
        except sqlite3.Error:
            return
        cols: list[str] = []
        for rec in rows:
            name = str(rec["name"] if "name" in rec.keys() else rec[1] or "")
            if name and name != "oid":
                cols.append(name)
        if cols:
            self._headers = cols

    def _create_table_rows_schema(self, cols: list[str]) -> None:
        cur = self._conn.cursor()
        cur.execute("DROP TABLE IF EXISTS table_rows")
        col_sql = ", ".join(f"{_quoted_ident(h)} TEXT" for h in cols)
        if col_sql:
            cur.execute(f"CREATE TABLE table_rows (oid INTEGER PRIMARY KEY, {col_sql})")
        else:
            cur.execute("CREATE TABLE table_rows (oid INTEGER PRIMARY KEY)")

    def _insert_rows_payload(
        self,
        cols: list[str],
        rows: list[tuple[int, dict[str, str]]],
    ) -> None:
        if not rows:
            return
        names = ["oid"] + cols
        placeholders = ", ".join(["?"] * len(names))
        insert_sql = f"INSERT INTO table_rows ({', '.join(_quoted_ident(n) for n in names)}) VALUES ({placeholders})"
        payload = []
        for oid, cells in rows:
            vals = [int(oid)] + [str(cells.get(h, "") or "") for h in cols]
            payload.append(vals)
        self._conn.cursor().executemany(insert_sql, payload)

    def begin_bulk_load(self, headers: list[str]) -> None:
        """Start an incremental ingest: create schema and defer the oid index until finalize."""
        cols = self._data_columns(headers)
        self._headers = list(cols)
        self._bulk_loading = True
        self._create_table_rows_schema(cols)
        self._conn.execute("BEGIN IMMEDIATE")

    def append_bulk_rows(self, rows: list[tuple[int, dict[str, str]]]) -> None:
        """Append rows during :meth:`begin_bulk_load` / :meth:`finalize_bulk_load`."""
        if not rows:
            return
        self._insert_rows_payload(self._headers, rows)

    def abort_bulk_load(self) -> None:
        """Roll back an incremental ingest that did not finish."""
        if not self._bulk_loading:
            return
        try:
            self._conn.rollback()
        except Exception:
            pass
        self._bulk_loading = False

    def finalize_bulk_load(self) -> None:
        """Finish incremental ingest: create index and commit the bulk transaction."""
        if not self._bulk_loading:
            return
        try:
            self._conn.cursor().execute(
                "CREATE INDEX IF NOT EXISTS idx_table_rows_oid ON table_rows(oid)"
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
            raise
        finally:
            self._bulk_loading = False

    def rebuild(
        self,
        headers: list[str],
        rows: list[tuple[int, dict[str, str]]],
    ) -> None:
        if self._bulk_loading:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._bulk_loading = False
        cols = self._data_columns(headers)
        self._headers = list(cols)
        self._create_table_rows_schema(cols)
        self._insert_rows_payload(cols, rows)
        self._conn.cursor().execute(
            "CREATE INDEX IF NOT EXISTS idx_table_rows_oid ON table_rows(oid)"
        )
        self._conn.commit()

    def start_stream_rebuild(self, headers: list[str]) -> None:
        """Begin a disk-backed rebuild (no full in-RAM entries list)."""
        if self._bulk_loading:
            try:
                self._conn.rollback()
            except Exception:
                pass
            self._bulk_loading = False
        cols = self._data_columns(headers)
        self._headers = list(cols)
        self._create_table_rows_schema(cols)
        self._conn.commit()

    def append_stream_rows(self, rows: list[tuple[int, dict[str, str]]]) -> None:
        """Append a chunk during :meth:`start_stream_rebuild`."""
        if not rows:
            return
        self._insert_rows_payload(self._headers, rows)
        self._conn.commit()

    def finish_stream_rebuild(self) -> None:
        """Create the oid index after streaming row inserts."""
        self._conn.cursor().execute(
            "CREATE INDEX IF NOT EXISTS idx_table_rows_oid ON table_rows(oid)"
        )
        self._conn.commit()

    def count(self, where_sql: str = "", args: tuple | list | None = None) -> int:
        cur = self._conn.cursor()
        args = tuple(args or ())
        sql = "SELECT COUNT(*) AS c FROM table_rows"
        if where_sql:
            sql += f" WHERE {where_sql}"
        row = cur.execute(sql, args).fetchone()
        return int(row["c"]) if row is not None else 0

    def distinct_values(self, column: str, *, limit: int = 2001) -> list[str]:
        """Distinct non-null text values for a column (for category filter UI)."""
        if column not in self._headers:
            return []
        lim = max(1, int(limit))
        qp = _quoted_ident(column)
        sql = (
            f"SELECT DISTINCT {qp} AS v FROM table_rows ORDER BY LOWER({qp}) ASC, {qp} ASC LIMIT ?"
        )
        rows = self._conn.execute(sql, (lim,)).fetchall()
        return [str(rec["v"] or "") for rec in rows]

    def fetch_oids(
        self,
        *,
        where_sql: str = "",
        args: tuple | list | None = None,
        after_oid: int | None = None,
        limit: int = 5000,
    ) -> list[int]:
        """Keyset page of OIDs (``oid > after_oid``) so search/filter skip OFFSET scans."""
        lim = max(1, int(limit))
        bind: list[object] = list(tuple(args or ()))
        clauses: list[str] = []
        if where_sql:
            clauses.append(f"({where_sql})")
        if after_oid is not None:
            clauses.append("oid > ?")
            bind.append(int(after_oid))
        sql = "SELECT oid FROM table_rows"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY oid ASC LIMIT ?"
        bind.append(lim)
        rows = self._conn.execute(sql, tuple(bind)).fetchall()
        return [int(rec["oid"]) for rec in rows]

    def fetch_page(
        self,
        *,
        limit: int,
        offset: int = 0,
        where_sql: str = "",
        args: tuple | list | None = None,
        sort_by: str = "oid",
        ascending: bool = True,
        after_oid: int | None = None,
    ) -> list[tuple[int, dict[str, str]]]:
        lim = max(1, int(limit))
        args = tuple(args or ())
        col = sort_by if sort_by in self._headers else "oid"
        order = "ASC" if ascending else "DESC"
        sql = "SELECT * FROM table_rows"
        bind: list[object] = list(args)
        clauses: list[str] = []
        if where_sql:
            clauses.append(f"({where_sql})")
        use_keyset = after_oid is not None and col == "oid"
        if use_keyset:
            clauses.append("oid > ?" if order == "ASC" else "oid < ?")
            bind.append(int(after_oid))
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += f" ORDER BY {_quoted_ident(col)} {order}, oid {order} LIMIT ?"
        bind.append(lim)
        if not use_keyset:
            sql += " OFFSET ?"
            bind.append(max(0, int(offset)))
        rows = self._conn.execute(sql, tuple(bind)).fetchall()
        out: list[tuple[int, dict[str, str]]] = []
        for rec in rows:
            oid = int(rec["oid"])
            out.append((oid, {h: str(rec[h] or "") for h in self._headers}))
        return out
