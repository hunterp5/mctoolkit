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

"""PNG-backed extra table-column images with a decoded QPixmap LRU."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
from PyQt5.QtGui import QImage, QPixmap

from .temp_sqlite import close_owned_sqlite, open_owned_sqlite


def pixmap_to_png_bytes(pixmap: QPixmap | None) -> bytes | None:
    """Encode *pixmap* as PNG bytes, or ``None`` when the image is empty."""
    if pixmap is None or pixmap.isNull():
        return None
    ba = QByteArray()
    buf = QBuffer(ba)
    if not buf.open(QIODevice.WriteOnly):
        return None
    ok = pixmap.save(buf, "PNG")
    buf.close()
    if not ok:
        return None
    raw = bytes(ba)
    return raw or None


class ExtraPixmapStore:
    """Holds extra-column images as PNG bytes on disk; only a bounded LRU is decoded.

    The set of stored ``(oid, header)`` keys is mirrored in memory so lookups for cells
    without an image (the common case on every table repaint) never touch SQLite.
    """

    def __init__(
        self,
        *,
        max_decoded_pixmaps: int = 384,
        db_path: str | Path | None = None,
    ) -> None:
        self._owns_path = db_path is None
        if db_path is None:
            self._path, self._conn = open_owned_sqlite("molmanager_xpix_")
        else:
            import sqlite3

            self._path = Path(db_path)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS images ("
            "oid INTEGER NOT NULL, header TEXT NOT NULL, blob BLOB NOT NULL, "
            "PRIMARY KEY (oid, header))"
        )
        self._conn.commit()
        self._lru: OrderedDict[tuple[int, str], QPixmap] = OrderedDict()
        self._max_decoded = max(32, int(max_decoded_pixmaps))
        self._keys: set[tuple[int, str]] = self._load_keys()
        self._closed = False

    def _load_keys(self) -> set[tuple[int, str]]:
        return {
            (int(oid), str(header))
            for oid, header in self._conn.execute("SELECT oid, header FROM images")
        }

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._lru.clear()
        self._keys.clear()
        close_owned_sqlite(self._path, self._conn, owns_path=self._owns_path)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def clear(self) -> None:
        self._conn.execute("DELETE FROM images")
        self._conn.commit()
        self._lru.clear()
        self._keys.clear()

    def __len__(self) -> int:
        return len(self._keys)

    def __contains__(self, key: object) -> bool:
        parsed = self._parse_key(key)
        return parsed is not None and parsed in self._keys

    @staticmethod
    def _parse_key(key: object) -> tuple[int, str] | None:
        if not isinstance(key, tuple) or len(key) != 2:
            return None
        try:
            return int(key[0]), str(key[1])
        except (TypeError, ValueError):
            return None

    def _raw(self, oid: int, header: str) -> bytes | None:
        if (oid, header) not in self._keys:
            return None
        row = self._conn.execute(
            "SELECT blob FROM images WHERE oid = ? AND header = ?",
            (oid, header),
        ).fetchone()
        if row is None or not row[0]:
            return None
        return bytes(row[0])

    def pixmap(self, oid: int, header_name: str) -> QPixmap | None:
        key = (int(oid), str(header_name))
        cached = self._lru.get(key)
        if cached is not None and not cached.isNull():
            self._lru.move_to_end(key)
            return cached
        raw = self._raw(*key)
        if not raw:
            return None
        pm = QPixmap.fromImage(QImage.fromData(raw))
        if pm.isNull():
            return None
        self._lru[key] = pm
        self._lru.move_to_end(key)
        while len(self._lru) > self._max_decoded:
            self._lru.popitem(last=False)
        return pm

    def get(self, key: tuple[int, str], default=None):
        oid, header = key
        pm = self.pixmap(int(oid), str(header))
        return default if pm is None else pm

    def __setitem__(self, key: tuple[int, str], pixmap: QPixmap | None) -> None:
        self.set_pixmap(int(key[0]), str(key[1]), pixmap)

    def pop(self, key: tuple[int, str], default=None):
        oid_i, header = int(key[0]), str(key[1])
        kk = (oid_i, header)
        self._lru.pop(kk, None)
        raw = self._raw(oid_i, header)
        if kk in self._keys:
            self._conn.execute("DELETE FROM images WHERE oid = ? AND header = ?", kk)
            self._conn.commit()
            self._keys.discard(kk)
        if raw is None:
            return default
        pm = QPixmap.fromImage(QImage.fromData(raw))
        return pm if pm is not None and not pm.isNull() else default

    def pixmaps_for_oid(self, oid: int) -> dict[str, QPixmap]:
        oid_i = int(oid)
        out: dict[str, QPixmap] = {}
        for (header,) in self._conn.execute("SELECT header FROM images WHERE oid = ?", (oid_i,)):
            pm = self.pixmap(oid_i, str(header))
            if pm is not None and not pm.isNull():
                out[str(header)] = QPixmap(pm)
        return out

    def pixmaps_for_header(self, header_name: str) -> dict[int, QPixmap]:
        header = str(header_name)
        out: dict[int, QPixmap] = {}
        for (oid,) in self._conn.execute("SELECT oid FROM images WHERE header = ?", (header,)):
            pm = self.pixmap(int(oid), header)
            if pm is not None and not pm.isNull():
                out[int(oid)] = QPixmap(pm)
        return out

    def keys(self):
        return [
            (int(oid), str(header))
            for oid, header in self._conn.execute("SELECT oid, header FROM images")
        ]

    def items(self):
        for key in self.keys():
            pm = self.pixmap(key[0], key[1])
            if pm is not None:
                yield key, pm

    def set_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        key = (int(oid), str(header_name))
        self._store_png(key, pixmap_to_png_bytes(pixmap))

    def copy_png(self, src: tuple[int, str], dest: tuple[int, str]) -> None:
        raw = self._raw(int(src[0]), str(src[1]))
        self._store_png((int(dest[0]), str(dest[1])), raw)

    def _store_png(self, key: tuple[int, str], raw: bytes | None) -> None:
        """Write *raw* PNG bytes under *key*, or delete the entry when *raw* is empty."""
        self._lru.pop(key, None)
        if not raw:
            if key in self._keys:
                self._conn.execute("DELETE FROM images WHERE oid = ? AND header = ?", key)
                self._conn.commit()
                self._keys.discard(key)
            return
        self._conn.execute(
            "INSERT OR REPLACE INTO images (oid, header, blob) VALUES (?, ?, ?)",
            (key[0], key[1], raw),
        )
        self._conn.commit()
        self._keys.add(key)

    def remove_oid(self, oid: int) -> None:
        oid_i = int(oid)
        dropped = {k for k in self._keys if k[0] == oid_i}
        if not dropped:
            return
        self._conn.execute("DELETE FROM images WHERE oid = ?", (oid_i,))
        self._conn.commit()
        self._keys -= dropped
        for key in dropped:
            self._lru.pop(key, None)

    def remove_header(self, header_name: str) -> None:
        header = str(header_name)
        dropped = {k for k in self._keys if k[1] == header}
        if not dropped:
            return
        self._conn.execute("DELETE FROM images WHERE header = ?", (header,))
        self._conn.commit()
        self._keys -= dropped
        for key in dropped:
            self._lru.pop(key, None)

    def keep_headers(self, headers: set[str]) -> None:
        keep = set(headers)
        current = {header for _oid, header in self._keys}
        for header in current - keep:
            self.remove_header(header)

    def rename_header(self, old: str, new: str) -> None:
        old_h, new_h = str(old), str(new)
        rows = self._conn.execute(
            "SELECT oid, blob FROM images WHERE header = ?", (old_h,)
        ).fetchall()
        if not rows:
            return
        self._conn.execute("DELETE FROM images WHERE header = ?", (old_h,))
        self._conn.executemany(
            "INSERT OR REPLACE INTO images (oid, header, blob) VALUES (?, ?, ?)",
            [(int(oid), new_h, blob) for oid, blob in rows],
        )
        self._conn.commit()
        for oid, _blob in rows:
            self._lru.pop((int(oid), old_h), None)
            self._lru.pop((int(oid), new_h), None)
        self._keys = self._load_keys()
