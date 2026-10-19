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

"""SQLite blob store for packed conformer / pose ensembles."""

from __future__ import annotations

import sqlite3
import tempfile
import threading
from collections import OrderedDict
from collections.abc import Iterable, Iterator, MutableMapping
from pathlib import Path

from rdkit import Chem

from ..conformers.ensemble_binary_codec import (
    blocks_b64_to_ensemble_blob,
    ensemble_blob_to_blocks_b64,
    pack_ensemble_mol,
    unpack_ensemble_mol,
)
from .temp_sqlite import close_owned_sqlite, open_owned_sqlite

KIND_COMPACT = "compact"
KIND_LEGACY = "legacy"
_DEFAULT_LRU = 48
_AUTOCOMMIT_EVERY = 64
_thread_stores = threading.local()


def _parse_key(key: object) -> tuple[int, str] | None:
    if not isinstance(key, tuple) or len(key) != 2:
        return None
    try:
        return int(key[0]), str(key[1])
    except (TypeError, ValueError):
        return None


class EnsembleStore(MutableMapping[tuple[int, str], str]):
    """Disk-backed mapping ``(oid, column) -> viewer blocks_b64``."""

    def __init__(self, db_path: str | Path | None = None, *, lru_max: int = _DEFAULT_LRU) -> None:
        self._owns_path = db_path is None
        if db_path is None:
            self._path, self._conn = open_owned_sqlite("molmanager_ens_")
        else:
            self._path = Path(db_path)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            try:
                self._conn.execute("PRAGMA synchronous=NORMAL")
                self._conn.execute("PRAGMA temp_store=MEMORY")
            except sqlite3.Error:
                pass
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS ensembles ("
            "oid INTEGER NOT NULL, col TEXT NOT NULL, kind TEXT NOT NULL, "
            "blob BLOB NOT NULL, PRIMARY KEY (oid, col))"
        )
        self._conn.commit()
        self._lru: OrderedDict[tuple[int, str], str] = OrderedDict()
        self._lru_max = max(4, int(lru_max))
        self._pending = 0

    @property
    def db_path(self) -> Path:
        self._flush()
        return self._path

    def flush(self) -> None:
        """Commit pending writes so other connections can read them."""
        self._flush()

    def _flush(self) -> None:
        if self._pending <= 0:
            return
        self._conn.commit()
        self._pending = 0

    def _write_row(self, oid: int, col: str, kind: str, data: bytes) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO ensembles (oid, col, kind, blob) VALUES (?, ?, ?, ?)",
            (int(oid), str(col), str(kind), data),
        )
        self._pending += 1
        if self._pending >= _AUTOCOMMIT_EVERY:
            self._flush()

    def close(self) -> None:
        self._flush()
        self._lru.clear()
        close_owned_sqlite(self._path, self._conn, owns_path=self._owns_path)

    def clear(self) -> None:
        self._flush()
        self._conn.execute("DELETE FROM ensembles")
        self._conn.commit()
        self._pending = 0
        self._lru.clear()

    def __bool__(self) -> bool:
        return len(self) > 0

    def __len__(self) -> int:
        self._flush()
        row = self._conn.execute("SELECT COUNT(*) FROM ensembles").fetchone()
        return int(row[0]) if row else 0

    def __iter__(self) -> Iterator[tuple[int, str]]:
        self._flush()
        for oid, col in self._conn.execute("SELECT oid, col FROM ensembles"):
            yield (int(oid), str(col))

    def __contains__(self, key: object) -> bool:
        parsed = _parse_key(key)
        if parsed is None:
            return False
        oid, col = parsed
        if (oid, col) in self._lru:
            return True
        self._flush()
        row = self._conn.execute(
            "SELECT 1 FROM ensembles WHERE oid = ? AND col = ? LIMIT 1", (oid, col)
        ).fetchone()
        return row is not None

    def get(self, key, default=None):  # type: ignore[override]
        try:
            return self[key]
        except KeyError:
            return default

    def _remember(self, key: tuple[int, str], text: str) -> None:
        self._lru[key] = text
        self._lru.move_to_end(key)
        while len(self._lru) > self._lru_max:
            self._lru.popitem(last=False)

    def __getitem__(self, key: tuple[int, str]) -> str:
        parsed = _parse_key(key)
        if parsed is None:
            raise KeyError(key)
        oid, col = parsed
        cached = self._lru.get((oid, col))
        if cached is not None:
            self._lru.move_to_end((oid, col))
            return cached
        self._flush()
        row = self._conn.execute(
            "SELECT kind, blob FROM ensembles WHERE oid = ? AND col = ?",
            (oid, col),
        ).fetchone()
        if row is None:
            raise KeyError(key)
        kind, blob = str(row[0]), bytes(row[1] or b"")
        if kind == KIND_COMPACT:
            text = ensemble_blob_to_blocks_b64(blob)
        else:
            text = blob.decode("ascii", errors="ignore")
        if not text:
            raise KeyError(key)
        self._remember((oid, col), text)
        return text

    def __setitem__(self, key: tuple[int, str], value: str) -> None:
        parsed = _parse_key(key)
        if parsed is None:
            raise TypeError("EnsembleStore keys are (oid, column)")
        oid, col = parsed
        text = str(value or "")
        blob = blocks_b64_to_ensemble_blob(text)
        if blob:
            kind, data = KIND_COMPACT, blob
        else:
            kind, data = KIND_LEGACY, text.encode("ascii", errors="ignore")
        self._write_row(oid, col, kind, data)
        if blob:
            self._lru.pop((oid, col), None)
        else:
            self._remember((oid, col), text)

    def __delitem__(self, key: tuple[int, str]) -> None:
        parsed = _parse_key(key)
        if parsed is None:
            raise KeyError(key)
        oid, col = parsed
        self._flush()
        cur = self._conn.execute("DELETE FROM ensembles WHERE oid = ? AND col = ?", (oid, col))
        self._conn.commit()
        self._pending = 0
        self._lru.pop((oid, col), None)
        if cur.rowcount <= 0:
            raise KeyError(key)

    def update(self, other=(), /, **kwargs):  # type: ignore[override]
        if kwargs:
            raise TypeError("EnsembleStore.update does not take keyword keys")
        items = list(other.items()) if hasattr(other, "items") else list(other)
        rows: list[tuple[int, str, str, bytes]] = []
        for key, value in items:
            parsed = _parse_key(key)
            if parsed is None:
                raise TypeError("EnsembleStore keys are (oid, column)")
            oid, col = parsed
            text = str(value or "")
            blob = blocks_b64_to_ensemble_blob(text)
            if blob:
                kind, data = KIND_COMPACT, blob
                self._lru.pop((oid, col), None)
            else:
                kind, data = KIND_LEGACY, text.encode("ascii", errors="ignore")
                self._remember((oid, col), text)
            rows.append((oid, col, kind, data))
        if not rows:
            return
        self._flush()
        self._conn.executemany(
            "INSERT OR REPLACE INTO ensembles (oid, col, kind, blob) VALUES (?, ?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def store_mol(self, oid: int, column: str, mol: Chem.Mol | None) -> bool:
        """Write a compact blob from *mol*. Returns False when packing fails."""
        packed = pack_ensemble_mol(mol)
        if not packed:
            return False
        key = (int(oid), str(column))
        self._write_row(key[0], key[1], KIND_COMPACT, packed)
        self._lru.pop(key, None)
        return True

    def mol_for(self, oid: int, column: str) -> Chem.Mol | None:
        """Decode a stored ensemble without building nested base64."""
        self._flush()
        row = self._conn.execute(
            "SELECT kind, blob FROM ensembles WHERE oid = ? AND col = ?",
            (int(oid), str(column)),
        ).fetchone()
        if row is None:
            return None
        kind, blob = str(row[0]), bytes(row[1] or b"")
        if kind == KIND_COMPACT:
            return unpack_ensemble_mol(blob)
        compact = blocks_b64_to_ensemble_blob(blob.decode("ascii", errors="ignore"))
        return unpack_ensemble_mol(compact) if compact else None

    def discard_oids(self, oids: Iterable[int]) -> None:
        dead = [int(o) for o in oids]
        if not dead:
            return
        self._flush()
        qmarks = ",".join("?" * len(dead))
        self._conn.execute(f"DELETE FROM ensembles WHERE oid IN ({qmarks})", dead)
        self._conn.commit()
        self._pending = 0
        gone = set(dead)
        for key in list(self._lru):
            if key[0] in gone:
                self._lru.pop(key, None)

    def copy_oid(self, src_oid: int, dst_oid: int, columns: Iterable[str]) -> None:
        src, dst = int(src_oid), int(dst_oid)
        self._flush()
        for col in columns:
            row = self._conn.execute(
                "SELECT kind, blob FROM ensembles WHERE oid = ? AND col = ?",
                (src, str(col)),
            ).fetchone()
            if row is None:
                continue
            self._conn.execute(
                "INSERT OR REPLACE INTO ensembles (oid, col, kind, blob) VALUES (?, ?, ?, ?)",
                (dst, str(col), str(row[0]), bytes(row[1] or b"")),
            )
            self._lru.pop((dst, str(col)), None)
        self._conn.commit()
        self._pending = 0

    def export_sqlite_bytes(self, oids: set[int] | None = None) -> bytes:
        """Snapshot the ensemble DB (optionally one OID subset) as SQLite bytes."""
        self._flush()
        handle = tempfile.NamedTemporaryFile(
            prefix="molmanager_ens_exp_", suffix=".sqlite3", delete=False
        )
        handle.close()
        dest = Path(handle.name)
        dest_conn: sqlite3.Connection | None = sqlite3.connect(str(dest))
        try:
            if oids is None:
                self._conn.backup(dest_conn)
                dest_conn.close()
                dest_conn = None
            else:
                dest_conn.execute(
                    "CREATE TABLE IF NOT EXISTS ensembles ("
                    "oid INTEGER NOT NULL, col TEXT NOT NULL, kind TEXT NOT NULL, "
                    "blob BLOB NOT NULL, PRIMARY KEY (oid, col))"
                )
                dest_conn.commit()
                dest_conn.close()
                dest_conn = None
                want = sorted({int(o) for o in oids})
                if want:
                    self._conn.execute("ATTACH DATABASE ? AS snapshot", (str(dest),))
                    try:
                        placeholders = ",".join("?" * len(want))
                        self._conn.execute(
                            "INSERT INTO snapshot.ensembles (oid, col, kind, blob) "
                            "SELECT oid, col, kind, blob FROM ensembles "
                            f"WHERE oid IN ({placeholders})",
                            want,
                        )
                        self._conn.commit()
                    finally:
                        self._conn.execute("DETACH DATABASE snapshot")
            return dest.read_bytes()
        finally:
            if dest_conn is not None:
                try:
                    dest_conn.close()
                except sqlite3.Error:
                    pass
            try:
                dest.unlink(missing_ok=True)
            except OSError:
                pass

    def import_sqlite_bytes(self, data: bytes, *, replace: bool = True) -> None:
        """Load ensembles from a SQLite snapshot produced by :meth:`export_sqlite_bytes`."""
        if not data:
            return
        handle = tempfile.NamedTemporaryFile(
            prefix="molmanager_ens_imp_", suffix=".sqlite3", delete=False
        )
        handle.write(data)
        handle.close()
        src_path = Path(handle.name)
        src: sqlite3.Connection | None = sqlite3.connect(str(src_path))
        try:
            self._flush()
            if replace:
                src.backup(self._conn)
            else:
                # Close before ATTACH. Windows locks a file another connection still has open.
                src.close()
                src = None
                self._conn.execute("ATTACH DATABASE ? AS incoming", (str(src_path),))
                try:
                    self._conn.execute(
                        "INSERT OR REPLACE INTO ensembles (oid, col, kind, blob) "
                        "SELECT oid, col, kind, blob FROM incoming.ensembles"
                    )
                    self._conn.commit()
                finally:
                    self._conn.execute("DETACH DATABASE incoming")
            self._lru.clear()
        except sqlite3.Error:
            return
        finally:
            if src is not None:
                src.close()
            try:
                src_path.unlink(missing_ok=True)
            except OSError:
                pass


def ensure_confs_sidecar(holder: object) -> EnsembleStore:
    """Return *holder._confs_blocks_sidecar*, upgrading a dict to :class:`EnsembleStore`."""
    sc = getattr(holder, "_confs_blocks_sidecar", None)
    if isinstance(sc, EnsembleStore):
        return sc
    store = EnsembleStore()
    if isinstance(sc, dict) and sc:
        store.update(sc)
    setattr(holder, "_confs_blocks_sidecar", store)
    return store


def reset_confs_sidecar(holder: object) -> EnsembleStore:
    """Empty the ensemble store on *holder*, replacing a dict sidecar when needed."""
    sc = getattr(holder, "_confs_blocks_sidecar", None)
    if isinstance(sc, EnsembleStore):
        sc.clear()
        return sc
    store = EnsembleStore()
    setattr(holder, "_confs_blocks_sidecar", store)
    return store


def ensemble_db_path(holder: object) -> Path | None:
    """SQLite path for *holder._confs_blocks_sidecar* when it is an :class:`EnsembleStore`."""
    sc = getattr(holder, "_confs_blocks_sidecar", None)
    if isinstance(sc, EnsembleStore):
        return sc.db_path
    return None


def _store_for_path(db_path: str | Path) -> EnsembleStore:
    path = Path(db_path)
    cache = getattr(_thread_stores, "by_path", None)
    if cache is None:
        cache = {}
        _thread_stores.by_path = cache
    key = str(path)
    store = cache.get(key)
    if store is None:
        store = EnsembleStore(path, lru_max=8)
        cache[key] = store
    return store


def ensemble_mol_for(
    source: EnsembleStore | str | Path | None,
    oid: int,
    column: str,
    *,
    min_conformers: int = 1,
) -> Chem.Mol | None:
    """Decode one stored ensemble. *source* is a store or a SQLite path (worker-safe)."""
    if source is None:
        return None
    if isinstance(source, EnsembleStore):
        mol = source.mol_for(int(oid), str(column))
    else:
        try:
            mol = _store_for_path(source).mol_for(int(oid), str(column))
        except Exception:
            return None
    if mol is None:
        return None
    try:
        n = int(mol.GetNumConformers())
    except Exception:
        return None
    if n < max(1, int(min_conformers)):
        return None
    return mol
