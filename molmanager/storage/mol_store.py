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

"""SQLite-backed molecule store with a small in-memory LRU."""

from __future__ import annotations

import sqlite3
from collections import OrderedDict
from collections.abc import Iterable, Iterator, Mapping, MutableMapping
from pathlib import Path

from rdkit import Chem

from .temp_sqlite import close_owned_sqlite, open_owned_sqlite

_DEFAULT_LRU = 256
_AUTOCOMMIT_EVERY = 64
# SQLite's default bound-parameter limit is 999 on older builds.
_SQLITE_IN_CHUNK = 900


def _as_oid(key: object) -> int:
    return int(key)


def _mol_blob(mol: Chem.Mol) -> bytes | None:
    from ..chem.molecule_conversion import mol_graph_binary

    blob = mol_graph_binary(mol)
    if blob:
        return blob
    try:
        raw = mol.ToBinary()
    except Exception:
        return None
    return bytes(raw) if raw else None


def _mol_from_blob(blob: bytes | None) -> Chem.Mol | None:
    if not blob:
        return None
    try:
        mol = Chem.Mol(bytes(blob))
    except Exception:
        return None
    return mol


def _mol_from_text(text: str | None) -> Chem.Mol | None:
    from ..chem.molecule_conversion import parse_molecule_from_cell_text

    return parse_molecule_from_cell_text(text or "")


def _canonical_text(mol: Chem.Mol | None) -> str | None:
    if mol is None:
        return None
    try:
        return Chem.MolToSmiles(mol) or None
    except Exception:
        return None


class MolStore(MutableMapping[int, Chem.Mol]):
    """Disk-backed ``oid -> RDKit mol``. Only a bounded LRU stays hydrated.

    Each row is the table's one molecule for that ``oid``: an RDKit connection-table blob
    and its structure text. The text is canonical SMILES once RDKit has seen the molecule.
    A file read as text stores the source cell (SMILES, InChI, or a mol block) with no blob,
    and the blob is filled in the first time the molecule is needed.
    """

    def __init__(self, db_path: str | Path | None = None, *, lru_max: int = _DEFAULT_LRU) -> None:
        self._owns_path = db_path is None
        if db_path is None:
            self._path, self._conn = open_owned_sqlite("molmanager_mols_")
        else:
            self._path = Path(db_path)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS mols (oid INTEGER PRIMARY KEY, blob BLOB, smiles TEXT)"
        )
        self._conn.commit()
        self._lru: OrderedDict[int, Chem.Mol] = OrderedDict()
        self._lru_max = max(8, int(lru_max))
        self._pending = 0
        self._closed = False

    @property
    def db_path(self) -> Path:
        return self._path

    def close(self) -> None:
        if getattr(self, "_closed", False):
            return
        self._closed = True
        self._flush()
        self._lru.clear()
        close_owned_sqlite(self._path, self._conn, owns_path=self._owns_path)

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass

    def clear(self) -> None:
        self._conn.execute("DELETE FROM mols")
        self._conn.commit()
        self._pending = 0
        self._lru.clear()

    def __bool__(self) -> bool:
        return len(self) > 0

    def __len__(self) -> int:
        self._flush()
        row = self._conn.execute("SELECT COUNT(*) FROM mols").fetchone()
        return int(row[0]) if row else 0

    def __iter__(self) -> Iterator[int]:
        self._flush()
        for (oid,) in self._conn.execute("SELECT oid FROM mols ORDER BY oid"):
            yield int(oid)

    def __contains__(self, key: object) -> bool:
        try:
            oid = _as_oid(key)
        except (TypeError, ValueError):
            return False
        if oid in self._lru:
            return True
        self._flush()
        row = self._conn.execute("SELECT 1 FROM mols WHERE oid = ? LIMIT 1", (oid,)).fetchone()
        return row is not None

    def get(self, key, default=None):  # type: ignore[override]
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key, default=None):  # type: ignore[override]
        try:
            oid = _as_oid(key)
        except (TypeError, ValueError):
            return default
        cached = self._lru.pop(oid, None)
        self._flush()
        cur = self._conn.execute("DELETE FROM mols WHERE oid = ?", (oid,))
        self._conn.commit()
        self._pending = 0
        if cur.rowcount <= 0 and cached is None:
            return default
        return cached if cached is not None else default

    def _remember(self, oid: int, mol: Chem.Mol) -> None:
        self._lru[oid] = mol
        self._lru.move_to_end(oid)
        while len(self._lru) > self._lru_max:
            self._lru.popitem(last=False)

    def _flush(self) -> None:
        if self._pending <= 0:
            return
        self._conn.commit()
        self._pending = 0

    def _write_row(self, oid: int, blob: bytes | None, smiles: str | None) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO mols (oid, blob, smiles) VALUES (?, ?, ?)",
            (int(oid), blob, smiles),
        )
        self._pending += 1
        if self._pending >= _AUTOCOMMIT_EVERY:
            self._flush()

    def structure_text_for(self, oid: int) -> str:
        """Structure text for one row, or ``""`` when the row has no structure.

        A row stored as a blob only gets canonical SMILES computed and saved the first
        time it is asked for, so later reads are one indexed lookup.
        """
        row = self._conn.execute(
            "SELECT blob, smiles FROM mols WHERE oid = ?", (int(oid),)
        ).fetchone()
        if row is None:
            return ""
        blob, text = row
        text = (text or "").strip()
        if text or not blob:
            return text
        computed = _canonical_text(_mol_from_blob(blob))
        if not computed:
            return ""
        self._write_row(int(oid), bytes(blob), computed)
        return computed

    def blob_for(self, oid: int) -> bytes | None:
        """Return the stored RDKit pickle without hydrating a live mol."""
        self._flush()
        row = self._conn.execute("SELECT blob FROM mols WHERE oid = ?", (int(oid),)).fetchone()
        if row is None or not row[0]:
            return None
        return bytes(row[0])

    def iter_structure_payloads(self) -> Iterator[tuple[int, bytes | None, str]]:
        """Yield ``(oid, blob, smiles)`` for every stored row in a single scan.

        Batch 2D rendering re-serializes each structure for its subprocesses anyway, so
        hydrating molecules through :meth:`__getitem__` would pay RDKit twice per row and
        thrash the LRU on top of one SQLite query per oid.
        """
        self._flush()
        cursor = self._conn.execute("SELECT oid, blob, smiles FROM mols ORDER BY oid")
        for oid, blob, smiles in cursor:
            yield int(oid), (bytes(blob) if blob else None), (smiles or "")

    def structure_payloads_for(
        self, oids: Iterable[int]
    ) -> Iterator[tuple[int, bytes | None, str]]:
        """Yield ``(oid, blob, smiles)`` for just *oids*, in chunked ``IN`` queries.

        Scoped tools (selected rows, one clicked row) would otherwise scan every stored row.
        """
        wanted = sorted({int(oid) for oid in oids})
        if not wanted:
            return
        self._flush()
        for start in range(0, len(wanted), _SQLITE_IN_CHUNK):
            chunk = wanted[start : start + _SQLITE_IN_CHUNK]
            marks = ",".join("?" * len(chunk))
            cursor = self._conn.execute(
                f"SELECT oid, blob, smiles FROM mols WHERE oid IN ({marks})", chunk
            )
            for oid, blob, smiles in cursor:
                yield int(oid), (bytes(blob) if blob else None), (smiles or "")

    def ingest_jobs(self, jobs: Iterable[tuple[int, bytes | None, str]]) -> None:
        """Persist (oid, blob, smiles) rows without constructing molecules.

        Replaced oids are dropped from the LRU so a later read cannot return the old structure.
        """
        rows: list[tuple[int, bytes | None, str | None]] = []
        for oid, blob, smiles in jobs:
            blob_b = bytes(blob) if blob else None
            smi = (smiles or "").strip() or None
            if not blob_b and not smi:
                continue
            rows.append((int(oid), blob_b, smi))
        if not rows:
            return
        self._flush()
        self._conn.executemany(
            "INSERT OR REPLACE INTO mols (oid, blob, smiles) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()
        if self._lru:
            for oid, _blob, _smiles in rows:
                self._lru.pop(oid, None)

    def ingest_structures(
        self, rows: Iterable[tuple[int, Chem.Mol | None, bytes | None, str]]
    ) -> None:
        """Write many ``(oid, mol, blob, smiles)`` structures in one statement.

        File ingest already holds the load worker's pickle and the row's SMILES cell, so the
        per-row :meth:`__setitem__` path would re-serialize and re-canonicalize every molecule
        on the GUI thread to recreate values it was handed.
        """
        jobs: list[tuple[int, bytes | None, str]] = []
        for oid, mol, blob, smiles in rows:
            payload = bytes(blob) if blob else (_mol_blob(mol) if mol is not None else None)
            jobs.append((int(oid), payload, smiles))
        self.ingest_jobs(jobs)

    def ingest_blobs(self, blobs: Mapping[int, bytes]) -> None:
        jobs = ((int(oid), blob, "") for oid, blob in blobs.items() if blob)
        self.ingest_jobs(jobs)

    def ingest_smiles(self, smiles: Mapping[int, str]) -> None:
        jobs = ((int(oid), None, str(smi)) for oid, smi in smiles.items() if str(smi).strip())
        self.ingest_jobs(jobs)

    def ingest_mols(self, mols: Mapping[int, Chem.Mol | None], *, cache: bool = False) -> None:
        """Pickle molecules to disk. Live objects stay in the LRU only when *cache* is true."""
        rows: list[tuple[int, bytes | None, str | None]] = []
        for oid, mol in mols.items():
            if mol is None:
                continue
            blob = _mol_blob(mol)
            smi = _canonical_text(mol)
            if not blob and not smi:
                continue
            oid_i = int(oid)
            rows.append((oid_i, blob, smi))
            if cache:
                self._remember(oid_i, mol)
        if not rows:
            return
        self._flush()
        self._conn.executemany(
            "INSERT OR REPLACE INTO mols (oid, blob, smiles) VALUES (?, ?, ?)",
            rows,
        )
        self._conn.commit()

    def __getitem__(self, key: int) -> Chem.Mol:
        oid = _as_oid(key)
        cached = self._lru.get(oid)
        if cached is not None:
            self._lru.move_to_end(oid)
            return cached
        self._flush()
        row = self._conn.execute("SELECT blob, smiles FROM mols WHERE oid = ?", (oid,)).fetchone()
        if row is None:
            raise KeyError(key)
        mol = _mol_from_blob(row[0])
        if mol is None:
            mol = _mol_from_text(row[1])
        if mol is None:
            raise KeyError(key)
        if not row[0]:
            blob = _mol_blob(mol)
            if blob:
                self._write_row(oid, blob, row[1])
        self._remember(oid, mol)
        return mol

    def __setitem__(self, key: int, mol: Chem.Mol | None) -> None:
        oid = _as_oid(key)
        if mol is None:
            self.pop(oid, None)
            return
        self._write_row(oid, _mol_blob(mol), _canonical_text(mol))
        self._remember(oid, mol)

    def __delitem__(self, key: int) -> None:
        oid = _as_oid(key)
        if oid not in self:
            raise KeyError(key)
        self.pop(oid, None)


def ensure_mol_store(holder: object, *, lru_max: int | None = None) -> MolStore:
    """Return *holder.mols* as a :class:`MolStore`, wrapping a dict when needed."""
    mols = getattr(holder, "mols", None)
    if isinstance(mols, MolStore):
        return mols
    from ..platform_support.config import load_config

    cap = int(lru_max) if lru_max is not None else int(load_config().mol_cache_lru)
    store = MolStore(lru_max=cap)
    if isinstance(mols, dict) and mols:
        store.ingest_mols(mols)
    setattr(holder, "mols", store)
    return store


def reset_mol_store(holder: object, *, lru_max: int | None = None) -> MolStore:
    """Empty the molecule store on *holder* without replacing it with a dict."""
    mols = getattr(holder, "mols", None)
    if isinstance(mols, MolStore):
        mols.clear()
        return mols
    return ensure_mol_store(holder, lru_max=lru_max)


def load_mols_from_parse_result(
    holder: object, result: object, *, replace: bool = True
) -> MolStore:
    """Ingest worker blobs/jobs into *holder.mols* without hydrating every molecule."""
    store = reset_mol_store(holder) if replace else ensure_mol_store(holder)
    jobs = getattr(result, "mol_jobs", None)
    if jobs:
        store.ingest_jobs(jobs)
        return store
    blobs = getattr(result, "mol_blobs", None)
    if blobs:
        store.ingest_blobs(blobs)
        return store
    mols = getattr(result, "mols", None)
    if mols:
        store.ingest_mols(mols)
    return store
