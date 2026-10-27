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

"""MolManager ``.cms`` sessions, version 4: one SQLite database.

Tables:

- ``meta(key, value)``: format, version, the workspace manifest (zlib JSON), the row oids
  (little-endian int64), and the scene revision of stored depictions.
- ``columns``: one row per data column. Float columns are raw float64 values plus one
  bool per row; text columns are a JSON array of strings.
- ``sidecars(name, data)``: large workspace payloads (ionization cache, SOM maps,
  metabolite browser, docking results...) stored as zlib JSON next to the manifest
  instead of inside it.
- ``mols``, ``pngs`` and ``ensembles``: the same schemas as :class:`MolStore`,
  :class:`StructureRenderStore` and :class:`EnsembleStore`, so save and open copy rows
  with SQL instead of encoding them.

Saving and opening are Qt-free and run on worker threads. Store tables are copied in
short chunks so the GUI thread, which keeps writing to those stores, never waits long
on a SQLite lock.
"""

from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import tempfile
import zlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .column_store import ColumnBlob, ColumnStore

SESSION_FORMAT = "molmanager_session"
SESSION_VERSION = 4
SQLITE_HEADER = b"SQLite format 3\x00"

# Manifest keys whose payloads can be large; they live in ``sidecars`` instead.
SIDECAR_KEYS = frozenset(
    {
        "ionization_sidecar",
        "confs_sidecar",
        # Legacy site-of-metabolism payload. Old sessions still load; new saves omit it.
        "som_browse",
        "metabolite_browse",
        "depiction_2d",
        "dock_results",
        "mmp_ledger",
        "protein_viewer",
        "pose_column_contexts",
        "notepad",
        "row_lists",
    }
)

_COPY_CHUNK_ROWS = 2000
_JSON_ZLIB_LEVEL = 1
_LOCK_TIMEOUT_S = 30.0

_SCHEMA = (
    "CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB)",
    "CREATE TABLE columns (ordinal INTEGER PRIMARY KEY, name TEXT NOT NULL, kind TEXT NOT NULL, "
    "decimals INTEGER, blank_only INTEGER NOT NULL DEFAULT 0, data BLOB NOT NULL, valid BLOB)",
    "CREATE TABLE sidecars (name TEXT PRIMARY KEY, data BLOB NOT NULL)",
    "CREATE TABLE mols (oid INTEGER PRIMARY KEY, blob BLOB, smiles TEXT)",
    "CREATE TABLE pngs (oid INTEGER PRIMARY KEY, blob BLOB NOT NULL, seq INTEGER NOT NULL)",
    "CREATE INDEX pngs_seq ON pngs(seq)",
    "CREATE TABLE ensembles (oid INTEGER NOT NULL, col TEXT NOT NULL, kind TEXT NOT NULL, "
    "blob BLOB NOT NULL, PRIMARY KEY (oid, col))",
)

_STORE_TABLES = {
    "mols": ("CREATE TABLE IF NOT EXISTS mols (oid INTEGER PRIMARY KEY, blob BLOB, smiles TEXT)",),
    "pngs": (
        "CREATE TABLE IF NOT EXISTS pngs ("
        "oid INTEGER PRIMARY KEY, blob BLOB NOT NULL, seq INTEGER NOT NULL)",
        "CREATE INDEX IF NOT EXISTS pngs_seq ON pngs(seq)",
    ),
    "ensembles": (
        "CREATE TABLE IF NOT EXISTS ensembles (oid INTEGER NOT NULL, col TEXT NOT NULL, "
        "kind TEXT NOT NULL, blob BLOB NOT NULL, PRIMARY KEY (oid, col))",
    ),
}
_STORE_COLUMNS = {
    "mols": "oid, blob, smiles",
    "pngs": "oid, blob, seq",
    "ensembles": "oid, col, kind, blob",
}


def _dumps(obj: Any) -> bytes:
    """Compact JSON, zlib level 1: manifest and sidecar JSON shrink ~10x for a few ms."""
    try:
        import orjson

        raw = orjson.dumps(obj, option=orjson.OPT_NON_STR_KEYS)
    except ImportError:
        raw = json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return zlib.compress(raw, _JSON_ZLIB_LEVEL)


def _loads(raw: bytes) -> Any:
    data = zlib.decompress(bytes(raw))
    try:
        import orjson

        return orjson.loads(data)
    except ImportError:
        return json.loads(data.decode("utf-8"))


def is_session_v4(path: str | os.PathLike[str]) -> bool:
    """True when *path* starts with the SQLite file header."""
    try:
        with open(path, "rb") as fh:
            return fh.read(len(SQLITE_HEADER)) == SQLITE_HEADER
    except OSError:
        return False


def is_legacy_session(path: str | os.PathLike[str]) -> bool:
    """True when *path* looks like a version 1-3 session (zip, gzip or JSON) or a session CSV."""
    if str(path).lower().endswith(".csv"):
        return True
    try:
        with open(path, "rb") as fh:
            head = fh.read(64).lstrip(b"\xef\xbb\xbf \t\r\n")
    except OSError:
        return False
    return head.startswith((b"PK", b"\x1f\x8b", b"{"))


@dataclass
class SessionSaveSnapshot:
    """Everything a v4 save needs, captured on the GUI thread.

    ``*_db`` paths name the live store files; the worker reads them with its own
    connection. ``keep_oids`` limits a save to selected rows. A sidecar value may be a
    zero-argument callable over an immutable copy; the writer calls it on its own thread,
    so slow serialization stays off the GUI thread.
    """

    manifest: dict[str, Any]
    oids: bytes
    columns: list[ColumnBlob]
    sidecars: dict[str, Any] = field(default_factory=dict)
    mol_db: Path | None = None
    render_db: Path | None = None
    ensembles_db: Path | None = None
    scene_revision: int = 0
    keep_oids: frozenset[int] | None = None
    row_count: int = 0


@dataclass
class SessionOpenResult:
    """A parsed v4 session; ``*_db`` files are new temp files the caller adopts or deletes."""

    manifest: dict[str, Any]
    rows: ColumnStore
    max_oid: int
    mol_db: Path | None = None
    render_db: Path | None = None
    ensembles_db: Path | None = None
    scene_revision: int = -1
    render_count: int = 0
    temp_files: list[Path] = field(default_factory=list)

    def discard_temp_files(self) -> None:
        for path in self.temp_files:
            remove_sqlite_file(path)
        self.temp_files.clear()


def remove_sqlite_file(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(path) + suffix).unlink(missing_ok=True)


def split_manifest(doc: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Split a workspace document into ``(manifest, sidecars)``; empty sidecars are dropped."""
    manifest: dict[str, Any] = {}
    sidecars: dict[str, Any] = {}
    for key, value in doc.items():
        if key in SIDECAR_KEYS:
            if value not in (None, "", [], {}):
                sidecars[key] = value
            continue
        manifest[key] = value
    return manifest, sidecars


def _copy_store_table(
    conn: sqlite3.Connection,
    table: str,
    source: Path,
    *,
    keep_table: str | None,
    where: str = "",
    params: tuple = (),
    on_chunk: Callable[[int], None] | None = None,
) -> int:
    """Copy *table* from *source* into ``main`` in oid-ordered chunks. Returns rows copied.

    Each chunk is one statement, so the read lock on the live store file is held only
    for that chunk.
    """
    conn.execute("ATTACH DATABASE ? AS src", (str(source),))
    try:
        exists = conn.execute(
            "SELECT 1 FROM src.sqlite_master WHERE type = 'table' AND name = ?", (table,)
        ).fetchone()
        if exists is None:
            return 0
        cols = _STORE_COLUMNS[table]
        if table == "ensembles":
            # Several rows share one oid, so oid-keyed chunks would split them.
            keep = f" WHERE oid IN (SELECT oid FROM {keep_table})" if keep_table else ""
            cur = conn.execute(
                f"INSERT OR REPLACE INTO main.{table} ({cols}) SELECT {cols} FROM src.{table}{keep}"
            )
            return max(0, int(cur.rowcount))
        marks = ",".join("?" * len(cols.split(",")))
        copied = 0
        last_oid: int | None = None
        while True:
            clauses: list[str] = []
            args: list[Any] = []
            if last_oid is not None:
                clauses.append("oid > ?")
                args.append(last_oid)
            if keep_table:
                clauses.append(f"oid IN (SELECT oid FROM {keep_table})")
            if where:
                clauses.append(where)
                args.extend(params)
            sql_where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT {cols} FROM src.{table}{sql_where} ORDER BY oid LIMIT {_COPY_CHUNK_ROWS}",
                args,
            ).fetchall()
            if not rows:
                break
            conn.executemany(f"INSERT OR REPLACE INTO main.{table} ({cols}) VALUES ({marks})", rows)
            copied += len(rows)
            last_oid = int(rows[-1][0])
            if on_chunk is not None:
                on_chunk(copied)
            if len(rows) < _COPY_CHUNK_ROWS:
                break
        return copied
    finally:
        conn.commit()
        conn.execute("DETACH DATABASE src")


def write_session_v4(
    path: str | os.PathLike[str],
    snapshot: SessionSaveSnapshot,
    *,
    scene_magic: bytes | None = None,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Write *snapshot* to ``path.tmp`` and atomically replace *path*.

    *scene_magic*, when given, keeps only ``pngs`` rows whose bytes start with it.
    """
    dest = Path(path)
    tmp = dest.with_name(dest.name + ".tmp")
    remove_sqlite_file(tmp)
    total = max(1, int(snapshot.row_count))
    replaced = False
    conn = sqlite3.connect(str(tmp), timeout=_LOCK_TIMEOUT_S)
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        for stmt in _SCHEMA:
            conn.execute(stmt)
        meta = {
            "format": SESSION_FORMAT.encode(),
            "version": str(SESSION_VERSION).encode(),
            "manifest": _dumps(snapshot.manifest),
            "oids": snapshot.oids,
            "scene_revision": str(int(snapshot.scene_revision)).encode(),
        }
        conn.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", list(meta.items()))
        conn.executemany(
            "INSERT INTO columns (ordinal, name, kind, decimals, blank_only, data, valid) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (i, c.name, c.kind, c.decimals, int(c.blank_only), c.data, c.valid or None)
                for i, c in enumerate(snapshot.columns)
            ],
        )
        conn.executemany(
            "INSERT INTO sidecars (name, data) VALUES (?, ?)",
            [
                (name, _dumps(value() if callable(value) else value))
                for name, value in snapshot.sidecars.items()
            ],
        )
        keep_table = None
        if snapshot.keep_oids is not None:
            conn.execute("CREATE TEMP TABLE keep_oids (oid INTEGER PRIMARY KEY)")
            conn.executemany(
                "INSERT INTO keep_oids (oid) VALUES (?)", [(int(o),) for o in snapshot.keep_oids]
            )
            keep_table = "temp.keep_oids"
        conn.commit()

        def _progress(done: int) -> None:
            if on_progress is not None:
                on_progress(min(done, total), total)

        if snapshot.mol_db is not None:
            _copy_store_table(
                conn, "mols", snapshot.mol_db, keep_table=keep_table, on_chunk=_progress
            )
        if snapshot.render_db is not None:
            where, params = "", ()
            if scene_magic:
                where, params = "substr(blob, 1, ?) = ?", (len(scene_magic), scene_magic)
            _copy_store_table(
                conn, "pngs", snapshot.render_db, keep_table=keep_table, where=where, params=params
            )
        if snapshot.ensembles_db is not None:
            _copy_store_table(conn, "ensembles", snapshot.ensembles_db, keep_table=keep_table)
        conn.commit()
        conn.close()
        conn = None
        os.replace(tmp, dest)
        replaced = True
    finally:
        if conn is not None:
            conn.close()
        if not replaced:
            remove_sqlite_file(tmp)


def _new_store_file(prefix: str, table: str, source: str, where: str = "") -> tuple[Path, int]:
    """Copy one table of the session at *source* into a new temp SQLite file."""
    handle = tempfile.NamedTemporaryFile(prefix=prefix, suffix=".sqlite3", delete=False)
    handle.close()
    out = Path(handle.name)
    conn = sqlite3.connect(str(out))
    try:
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        for stmt in _STORE_TABLES[table]:
            conn.execute(stmt)
        conn.execute("ATTACH DATABASE ? AS s", (source,))
        cols = _STORE_COLUMNS[table]
        cur = conn.execute(
            f"INSERT INTO main.{table} ({cols}) SELECT {cols} FROM s.{table}"
            + (f" WHERE {where}" if where else "")
        )
        count = max(0, int(cur.rowcount))
        conn.commit()
        conn.execute("DETACH DATABASE s")
        conn.execute("PRAGMA journal_mode=DELETE")
    except BaseException:
        conn.close()
        remove_sqlite_file(out)
        raise
    conn.close()
    return out, count


def read_session_v4(
    path: str | os.PathLike[str],
    *,
    want_scene_revision: int | None = None,
    load_images: bool = True,
) -> SessionOpenResult:
    """Read a v4 session into memory plus temp store files.

    Depictions are copied only when the file's scene revision equals
    *want_scene_revision* (``None`` accepts any revision).
    """
    src = str(Path(path))
    uri = Path(src).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    try:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        if bytes(meta.get("format") or b"").decode() != SESSION_FORMAT:
            raise ValueError("Not a MolManager session.")
        version = int(bytes(meta.get("version") or b"0").decode() or 0)
        if version != SESSION_VERSION:
            raise ValueError(f"Unsupported session version: {version}")
        manifest = _loads(meta.get("manifest") or b"{}")
        if not isinstance(manifest, dict):
            raise ValueError("Session manifest must be a JSON object.")
        for name, data in conn.execute("SELECT name, data FROM sidecars"):
            manifest[str(name)] = _loads(data)
        blobs = [
            ColumnBlob(
                name=str(name),
                kind=str(kind),
                data=bytes(data or b""),
                valid=bytes(valid or b""),
                decimals=None if decimals is None else int(decimals),
                blank_only=bool(blank_only),
            )
            for name, kind, decimals, blank_only, data, valid in conn.execute(
                "SELECT name, kind, decimals, blank_only, data, valid FROM columns ORDER BY ordinal"
            )
        ]
        rows = ColumnStore.from_blobs(bytes(meta.get("oids") or b""), blobs)
        scene_rev = int(bytes(meta.get("scene_revision") or b"-1").decode() or -1)
        counts = {
            table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("mols", "pngs", "ensembles")
        }
    finally:
        conn.close()
    n = rows.n
    result = SessionOpenResult(
        manifest=manifest,
        rows=rows,
        max_oid=int(rows.oids[:n].max()) if n else -1,
        scene_revision=scene_rev,
    )
    try:
        if counts["mols"]:
            result.mol_db, _ = _new_store_file("molmanager_mols_", "mols", src)
            result.temp_files.append(result.mol_db)
        images_ok = want_scene_revision is None or scene_rev == int(want_scene_revision)
        if load_images and images_ok and counts["pngs"]:
            result.render_db, result.render_count = _new_store_file("molmanager_png_", "pngs", src)
            result.temp_files.append(result.render_db)
        if counts["ensembles"]:
            result.ensembles_db, _ = _new_store_file("molmanager_ens_", "ensembles", src)
            result.temp_files.append(result.ensembles_db)
    except BaseException:
        result.discard_temp_files()
        raise
    return result


def keep_mask(oids: np.ndarray, keep: Iterable[int] | None) -> np.ndarray | None:
    """Per-row bool mask for *keep*, or ``None`` for every row."""
    if keep is None:
        return None
    wanted = np.fromiter((int(o) for o in keep), dtype=np.int64)
    return np.isin(oids, wanted)
