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

"""Lazy PNG cache for structure-column 2D renders on very large tables."""

from __future__ import annotations

import os
from collections import OrderedDict
from pathlib import Path

from PyQt5.QtGui import QPixmap

from ..table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ..table.structure_image import pixmap_from_structure_image
from .temp_sqlite import close_owned_sqlite, open_owned_sqlite


class StructureRenderStore:
    """
    Holds rendered structure image bytes (PNG or depiction scene) on disk and decodes
    them to QPixmap on demand.

    Only a bounded number of QPixmaps are kept in memory (LRU). PNG bytes live in
    a temp SQLite file (optional entry cap, oldest seq evicted).
    """

    def __init__(
        self,
        *,
        max_decoded_pixmaps: int = 384,
        max_png_entries: int = 0,
        db_path: str | Path | None = None,
    ) -> None:
        self._owns_path = db_path is None
        if db_path is None:
            self._path, self._conn = open_owned_sqlite("molmanager_png_")
        else:
            import sqlite3

            self._path = Path(db_path)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS pngs ("
            "oid INTEGER PRIMARY KEY, blob BLOB NOT NULL, seq INTEGER NOT NULL)"
        )
        self._conn.execute("CREATE INDEX IF NOT EXISTS pngs_seq ON pngs(seq)")
        self._conn.commit()
        self._lru: OrderedDict[int, QPixmap] = OrderedDict()
        self._max_decoded = max(32, int(max_decoded_pixmaps))
        # 0 = unlimited PNG entry count
        self._max_png_entries = max(0, int(max_png_entries))
        self._seq = self._next_seq()
        self._count = self._count_rows()
        self._closed = False

    def _next_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) FROM pngs").fetchone()
        return int(row[0] or 0)

    def _count_rows(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM pngs").fetchone()
        return int(row[0] if row else 0)

    @property
    def db_path(self) -> Path:
        return self._path

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._lru.clear()
        close_owned_sqlite(self._path, self._conn, owns_path=self._owns_path)
        self._count = 0

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def clear(self) -> None:
        self._conn.execute("DELETE FROM pngs")
        self._conn.commit()
        self._lru.clear()
        self._count = 0
        self._seq = 0

    def __len__(self) -> int:
        return int(self._count)

    def has_png(self, oid: int) -> bool:
        oid_i = int(oid)
        if oid_i in self._lru:
            return True
        row = self._conn.execute("SELECT 1 FROM pngs WHERE oid = ? LIMIT 1", (oid_i,)).fetchone()
        return row is not None

    def png_bytes(self, oid: int) -> bytes | None:
        row = self._conn.execute("SELECT blob FROM pngs WHERE oid = ?", (int(oid),)).fetchone()
        if row is None or not row[0]:
            return None
        return bytes(row[0])

    def png_oids(self) -> list[int]:
        """OIDs in insertion/eviction order (oldest first)."""
        return [int(oid) for (oid,) in self._conn.execute("SELECT oid FROM pngs ORDER BY seq")]

    @property
    def _png(self) -> dict[int, bytes]:
        """Insertion-ordered oid→bytes for tests; do not use on large tables."""
        return {oid: (self.png_bytes(oid) or b"") for oid in self.png_oids()}

    def remove_oid(self, oid: int) -> None:
        oid_i = int(oid)
        cur = self._conn.execute("DELETE FROM pngs WHERE oid = ?", (oid_i,))
        self._conn.commit()
        self._lru.pop(oid_i, None)
        if cur.rowcount > 0:
            self._count = max(0, self._count - 1)

    def ingest_png(self, oid: int, png_bytes: bytes) -> None:
        self._upsert(int(oid), bytes(png_bytes))
        self._conn.commit()
        self._trim_png_entries()

    def ingest_batch(self, items: list[tuple[int, bytes]]) -> None:
        if not items:
            return
        if self._max_png_entries > 0:
            self._max_png_entries = max(self._max_png_entries, self._count + len(items))
        for oid, png_bytes in items:
            self._upsert(int(oid), bytes(png_bytes))
        self._conn.commit()
        self._trim_png_entries()

    def export_sqlite_bytes(self) -> bytes:
        """Return a snapshot of the PNG SQLite file for sidecar caching."""
        self._conn.commit()
        # Ensure pending pages are on disk before reading the file bytes.
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception:
            pass
        path = Path(self._path)
        return path.read_bytes()

    def import_sqlite_bytes(self, raw: bytes) -> int:
        """Replace store contents from a sidecar PNG SQLite blob. Returns imported OID count.

        The snapshot is copied with SQLite's backup API so the PNG bytes are not also held as a
        Python list.
        """
        if not raw:
            return 0
        import sqlite3
        import tempfile

        fd, tmp_name = tempfile.mkstemp(prefix="molmanager_png_import_", suffix=".sqlite")
        os.close(fd)
        tmp_path = Path(tmp_name)
        try:
            tmp_path.write_bytes(bytes(raw))
            src = sqlite3.connect(str(tmp_path), check_same_thread=False)
            try:
                self._conn.commit()
                src.backup(self._conn)
            finally:
                src.close()
            self._lru.clear()
            self._seq = self._next_seq()
            self._count = self._count_rows()
            return self._count
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass

    def expand_png_capacity(self, needed: int) -> None:
        """Raise the PNG entry cap so at least *needed* entries can be retained (0 = unlimited)."""
        need = max(0, int(needed))
        if need <= 0:
            return
        if self._max_png_entries <= 0:
            return
        self._max_png_entries = max(self._max_png_entries, need)

    def pixmap(self, oid: int) -> QPixmap | None:
        oid_i = int(oid)
        cached = self._lru.get(oid_i)
        if cached is not None and not cached.isNull():
            self._lru.move_to_end(oid_i)
            return cached
        raw = self.png_bytes(oid_i)
        if not raw:
            return None
        pm = pixmap_from_structure_image(
            raw, int(structure_depict_width()), int(structure_depict_height())
        )
        if pm.isNull():
            return None
        self._lru[oid_i] = pm
        self._lru.move_to_end(oid_i)
        while len(self._lru) > self._max_decoded:
            self._lru.popitem(last=False)
        return pm

    def trim_decoded_cache(self, *, keep_oids: set[int] | None = None) -> None:
        """Drop decoded pixmaps not in *keep_oids* (PNG bytes are retained)."""
        if keep_oids is None:
            self._lru.clear()
            return
        keep = {int(x) for x in keep_oids}
        for oid in list(self._lru):
            if oid not in keep:
                del self._lru[oid]

    def _upsert(self, oid: int, raw: bytes) -> None:
        existed = self._conn.execute("SELECT 1 FROM pngs WHERE oid = ? LIMIT 1", (oid,)).fetchone()
        self._seq += 1
        self._conn.execute(
            "INSERT OR REPLACE INTO pngs (oid, blob, seq) VALUES (?, ?, ?)",
            (oid, raw, self._seq),
        )
        self._lru.pop(oid, None)
        if existed is None:
            self._count += 1

    def _trim_png_entries(self) -> None:
        limit = self._max_png_entries
        if limit <= 0 or self._count <= limit:
            return
        drop_n = self._count - limit
        rows = self._conn.execute(
            "SELECT oid FROM pngs ORDER BY seq ASC LIMIT ?", (drop_n,)
        ).fetchall()
        oids = [int(r[0]) for r in rows]
        if not oids:
            return
        self._conn.executemany("DELETE FROM pngs WHERE oid = ?", [(oid,) for oid in oids])
        self._conn.commit()
        for oid in oids:
            self._lru.pop(oid, None)
        self._count = max(0, self._count - len(oids))
