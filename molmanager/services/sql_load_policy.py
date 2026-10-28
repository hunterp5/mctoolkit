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
"""SQL load safety helpers (no Qt).

SQLite opens with ``mode=ro``. Other engines get a read-only session where the
server has one, and every read-only engine refuses a statement that is not a
query. The keyword scan is the early message; the cursor guard is what stops a
statement the scan does not recognize.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Leading statement keywords that mutate schema/data or run server-side code.
_DESTRUCTIVE_HEAD = re.compile(
    r"^\s*(?:"
    r"INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE|"
    r"GRANT|REVOKE|EXEC(?:UTE)?|CALL|ATTACH|DETACH|VACUUM|REINDEX|"
    r"COPY\s+\S+\s+FROM"
    r")\b",
    re.IGNORECASE,
)

_MULTI_STMT = re.compile(r";\s*\S", re.DOTALL)

_MUTATING_AFTER_CTE = re.compile(
    r"\)\s*(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|MERGE)\b",
    re.IGNORECASE,
)

_SELECT_INTO = re.compile(r"\bSELECT\b[\s\S]*\bINTO\b", re.IGNORECASE)
_EXPLAIN = re.compile(
    r"^EXPLAIN\b(?:\s+QUERY\s+PLAN\b)?(?:\s+ANALYZE\b)?(?:\s+VERBOSE\b)?\s+",
    re.IGNORECASE,
)
_READ_HEAD = re.compile(r"^(?:SELECT|WITH|EXPLAIN|SHOW|VALUES|TABLE)\b", re.IGNORECASE)
_ROW_LOCK = re.compile(r"\bFOR\s+(?:UPDATE|SHARE|NO\s+KEY\s+UPDATE|KEY\s+SHARE)\b", re.IGNORECASE)

# Statements this process issues to make a session read-only. The cursor guard
# allows these and rejects every other non-query, including a later attempt to
# turn the session flag off.
_POSTGRES_SESSION = "SET default_transaction_read_only = on"
_POSTGRES_TRANSACTION = "SET TRANSACTION READ ONLY"
_MYSQL_SESSION = "SET SESSION TRANSACTION READ ONLY"
_SETUP_SQL = frozenset({_POSTGRES_SESSION, _POSTGRES_TRANSACTION, _MYSQL_SESSION})


class SqlWriteBlocked(RuntimeError):
    """A read-only SQL load refused a statement that is not a query."""


def _strip_sql_noise(sql: str) -> str:
    """Remove block comments and full-line ``--`` comments for heuristic checks."""
    text = re.sub(r"/\*.*?\*/", " ", sql, flags=re.DOTALL)
    lines: list[str] = []
    for line in text.splitlines():
        if line.lstrip().startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def sql_looks_destructive(sql: str | None) -> bool:
    """Heuristic: True when ``sql`` may modify the database or run non-SELECT work."""
    text = (sql or "").strip().rstrip(";")
    if not text:
        return False
    if _MULTI_STMT.search(text):
        return True
    cleaned = _strip_sql_noise(text)
    if not cleaned:
        return False
    if _DESTRUCTIVE_HEAD.match(cleaned):
        return True
    if _MUTATING_AFTER_CTE.search(cleaned):
        return True
    if _SELECT_INTO.search(cleaned):
        return True
    return False


def is_sqlite_sqlalchemy_url(url: str) -> bool:
    return (url or "").strip().lower().startswith("sqlite")


def sqlite_database_path_from_url(url: str) -> str | None:
    """
    Extract a filesystem path from a SQLAlchemy SQLite URL.

    Returns ``None`` for in-memory or unparseable URLs.
    """
    raw = (url or "").strip()
    low = raw.lower()
    if not low.startswith("sqlite"):
        return None
    # sqlite+pysqlite:///… or sqlite:///…
    if ":///" in raw:
        path = raw.split(":///", 1)[1]
    elif "://" in raw:
        path = raw.split("://", 1)[1]
    else:
        return None
    path_only, _, _query = path.partition("?")
    if path_only.lower().startswith("file:"):
        path_only = path_only[5:]
        # file:///C:/… → /C:/… on some parsers; strip leading slash before drive.
        if len(path_only) >= 3 and path_only[0] == "/" and path_only[2] == ":":
            path_only = path_only[1:]
    path_only = path_only.strip()
    if not path_only or path_only == ":memory:":
        return None
    return path_only


def make_sqlite_read_only_creator(
    path: str, *, timeout_s: float
) -> Callable[[], sqlite3.Connection]:
    """Return a SQLAlchemy ``creator`` that opens ``path`` with SQLite ``mode=ro``."""
    resolved = Path(path).expanduser().resolve()
    uri = resolved.as_uri() + "?mode=ro"
    t_s = max(1.0, min(float(timeout_s), 300.0))

    def _creator() -> sqlite3.Connection:
        return sqlite3.connect(uri, uri=True, timeout=t_s)

    return _creator


def engine_kwargs_for_sql_load(
    url: str,
    *,
    read_only: bool,
    sqlite_timeout_s: float,
    pg_connect_timeout: int,
) -> tuple[str, dict[str, Any]]:
    """Build ``(url, create_engine kwargs)`` including optional SQLite read-only mode."""
    connect_args: dict[str, Any] = {}
    out_url = url
    eng_kw: dict[str, Any] = {}
    lu = url.lower().strip()
    t_s = max(1.0, min(float(sqlite_timeout_s), 300.0))

    if read_only and is_sqlite_sqlalchemy_url(url):
        path = sqlite_database_path_from_url(url)
        if path:
            # Windows-safe: Path.as_uri() + sqlite3 uri=True (SQLAlchemy file: URLs are fragile).
            eng_kw["creator"] = make_sqlite_read_only_creator(path, timeout_s=t_s)
            return "sqlite://", eng_kw

    if lu.startswith("sqlite"):
        connect_args.setdefault("timeout", t_s)
    elif "postgresql" in lu or lu.startswith("postgres"):
        connect_args["connect_timeout"] = max(1, min(int(pg_connect_timeout), 120))
    if connect_args:
        eng_kw["connect_args"] = connect_args
    return out_url, eng_kw


def dialect_family(url: str) -> str:
    """Coarse engine name for read-only session setup."""
    lu = (url or "").lower().strip()
    scheme = lu.split(":", 1)[0]
    if scheme.startswith("sqlite"):
        return "sqlite"
    if "postgres" in scheme:
        return "postgresql"
    if scheme.startswith("mysql") or scheme.startswith("mariadb"):
        return "mysql"
    if scheme.startswith("mssql") or "sqlserver" in scheme:
        return "mssql"
    return "other"


def read_only_session_statements(url: str) -> tuple[str, ...]:
    """SQL run on connect so later transactions cannot write."""
    family = dialect_family(url)
    if family == "postgresql":
        return (_POSTGRES_SESSION,)
    if family == "mysql":
        return (_MYSQL_SESSION,)
    return ()


def read_only_transaction_statement(url: str) -> str | None:
    """First statement of a PostgreSQL transaction. Other engines have none."""
    if dialect_family(url) == "postgresql":
        return _POSTGRES_TRANSACTION
    return None


def assert_read_only_statement(statement: str) -> None:
    """Raise :class:`SqlWriteBlocked` unless *statement* is a single read query."""
    text = (statement or "").strip().rstrip(";").strip()
    if text in _SETUP_SQL:
        return
    if not text or _MULTI_STMT.search(text):
        raise SqlWriteBlocked("Read-only SQL load refused an empty or multi-statement query.")
    cleaned = _strip_sql_noise(text)
    if not cleaned:
        raise SqlWriteBlocked("Read-only SQL load refused an empty query.")
    examined = _EXPLAIN.sub("", cleaned, count=1).strip() if _EXPLAIN.match(cleaned) else cleaned
    if sql_looks_destructive(examined) or _ROW_LOCK.search(examined):
        raise SqlWriteBlocked(
            "Read-only SQL load refused a statement that may modify or lock the database."
        )
    if _READ_HEAD.match(examined) is None:
        raise SqlWriteBlocked(
            "Read-only SQL load only runs a query. This statement was not a SELECT, WITH, "
            "EXPLAIN, SHOW, VALUES, or TABLE."
        )


def install_read_only_guards(engine: Any, url: str) -> None:
    """Make *engine* reject writes for the rest of its lifetime.

    PostgreSQL sets ``default_transaction_read_only`` and starts each
    transaction ``READ ONLY``. MySQL sets the session transaction access mode.
    SQLite file loads already use ``mode=ro``. SQL Server has no session
    read-only mode. The cursor guard refuses a non-query on every engine.
    """
    from sqlalchemy import event

    session_sql = read_only_session_statements(url)
    begin_sql = read_only_transaction_statement(url)

    @event.listens_for(engine, "connect")
    def _read_only_connect(dbapi_conn: Any, _record: Any) -> None:
        if not session_sql:
            return
        cursor = dbapi_conn.cursor()
        try:
            for stmt in session_sql:
                cursor.execute(stmt)
        finally:
            cursor.close()

    if begin_sql is not None:

        @event.listens_for(engine, "begin")
        def _read_only_begin(conn: Any) -> None:
            conn.exec_driver_sql(begin_sql)

    @event.listens_for(engine, "before_cursor_execute")
    def _read_only_guard(
        _conn: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        assert_read_only_statement(statement)
