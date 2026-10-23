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

"""Owned temporary SQLite files for blob sidecars."""

from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path


def open_owned_sqlite(prefix: str) -> tuple[Path, sqlite3.Connection]:
    """Create a temp SQLite file and connection owned by the caller."""
    handle = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".sqlite3", delete=False)
    handle.close()
    path = Path(handle.name)
    return path, connect_owned_sqlite(path)


def connect_owned_sqlite(path: str | Path) -> sqlite3.Connection:
    """Connect to a workspace temp file that is discarded when the session closes.

    Nothing survives a crash in these files, so commits skip the disk sync; with it,
    each commit cost about 3 ms and large loads spent seconds of GUI time in them.
    """
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def close_owned_sqlite(path: Path, conn: sqlite3.Connection, *, owns_path: bool) -> None:
    """Close *conn* and delete the temp file (and WAL leftovers) when we created it."""
    try:
        conn.close()
    except Exception:
        pass
    if not owns_path:
        return
    for suffix in ("", "-wal", "-shm"):
        try:
            Path(str(path) + suffix).unlink(missing_ok=True)
        except OSError:
            pass
