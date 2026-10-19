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

"""Background SMILES parsing for session document and legacy CSV restore."""

from __future__ import annotations

import csv
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..table.open_messages import message_for_session_read_failure
from ..table.session_codec import decode_mol_blob_b64, row_structure_smiles

logger = logging.getLogger(__name__)

_SERIAL_MOL_DECODE_MAX = 32
_MAX_MOL_DECODE_WORKERS = 8


def mol_from_session_blob(blob: bytes | None, smiles: str = "") -> Chem.Mol | None:
    """Rebuild a structure from an RDKit pickle blob, then SMILES if needed."""
    if blob:
        try:
            mol = Chem.Mol(blob)
            if mol is not None:
                return mol
        except Exception:
            pass
    smi = (smiles or "").strip()
    if not smi:
        return None
    try:
        return Chem.MolFromSmiles(smi)
    except Exception:
        return None


def decode_session_mols(jobs: list[tuple[int, bytes | None, str]]) -> dict[int, Any]:
    """Decode session structure blobs. Threads are opt-in; RDKit pickle is usually GIL-bound."""
    mols: dict[int, Any] = {}
    if not jobs:
        return mols
    n = len(jobs)
    workers = _session_mol_decode_workers(n)
    if n <= _SERIAL_MOL_DECODE_MAX or workers <= 1:
        for oid, blob, smi in jobs:
            mol = mol_from_session_blob(blob, smi)
            if mol is not None:
                mols[oid] = mol
        return mols
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(mol_from_session_blob, blob, smi) for _oid, blob, smi in jobs]
        for (oid, _blob, _smi), fut in zip(jobs, futures, strict=True):
            mol = fut.result()
            if mol is not None:
                mols[oid] = mol
    return mols


def _session_mol_decode_workers(n: int) -> int:
    raw = (os.environ.get("MOLMANAGER_SESSION_MOL_WORKERS") or "").strip()
    if not raw:
        return 1
    try:
        requested = int(raw)
    except ValueError:
        return 1
    if requested <= 1:
        return 1
    cpu = os.cpu_count() or 1
    return max(1, min(_MAX_MOL_DECODE_WORKERS, cpu, n, requested))


def _safe_emit(obj: QObject | None, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


@dataclass
class SessionRowsParseResult:
    """Prepared table rows and parsed molecules for chunked UI apply."""

    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mol_jobs: list[tuple[int, bytes | None, str]] = field(default_factory=list)
    max_id: int = -1

    @property
    def mols(self) -> dict[int, Any]:
        return decode_session_mols(self.mol_jobs)


@dataclass
class CsvSessionParseResult:
    """Prepared rows from a legacy session CSV (SMILES + property columns)."""

    columns: list[str] = field(default_factory=list)
    prepared_rows: list[tuple[int, dict[str, str]]] = field(default_factory=list)
    mol_blobs: dict[int, bytes] = field(default_factory=dict)
    next_oid: int = 0

    @property
    def mols(self) -> dict[int, Any]:
        out: dict[int, Any] = {}
        for oid, blob in self.mol_blobs.items():
            try:
                mol = Chem.Mol(blob)
            except Exception:
                continue
            if mol is not None:
                out[int(oid)] = mol
        return out


class SessionRowsParseSignals(QObject):
    """Signals for session row parse workers (owned on the GUI thread)."""

    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class SessionRowsParseWorker(QRunnable):
    """Load session structures off the GUI thread (mol binary first, SMILES fallback)."""

    def __init__(
        self,
        rows: list[dict],
        *,
        data_headers: list[str],
        signals: SessionRowsParseSignals,
        generation: int,
        structure_smiles: list[str] | None = None,
        structure_mols: list[str] | None = None,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self.rows = rows
        self.data_headers = list(data_headers)
        self.structure_smiles = list(structure_smiles or [])
        self.structure_mols = list(structure_mols or [])
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            prepared: list[tuple[int, dict[str, str]]] = []
            jobs: list[tuple[int, bytes | None, str]] = []
            max_id = -1
            headers = self.data_headers
            for i, entry in enumerate(self.rows):
                if not isinstance(entry, dict):
                    continue
                try:
                    oid = int(entry["id"])
                except (KeyError, TypeError, ValueError):
                    continue
                max_id = max(max_id, oid)
                cells = entry.get("cells") or {}
                if not isinstance(cells, dict):
                    cells = {}
                saved_smi = ""
                if i < len(self.structure_smiles):
                    saved_smi = str(self.structure_smiles[i] or "")
                smi = row_structure_smiles(cells, saved_smi)
                row_cells = {cname: str(cells.get(cname, "") or "") for cname in headers}
                prepared.append((oid, row_cells))
                blob = None
                if i < len(self.structure_mols):
                    blob = decode_mol_blob_b64(self.structure_mols[i])
                jobs.append((oid, blob, smi))
            _safe_emit(
                self.signals,
                "finished",
                SessionRowsParseResult(
                    prepared_rows=prepared,
                    mol_jobs=jobs,
                    max_id=max_id,
                ),
            )
        except Exception as exc:
            _safe_emit(self.signals, "failed", str(exc) or "Session row parse failed.")


class CsvSessionParseWorker(QRunnable):
    """Read a legacy session CSV and parse SMILES off the GUI thread."""

    def __init__(self, path: str, signals: SessionRowsParseSignals, generation: int):
        super().__init__()
        self.setAutoDelete(True)
        self.path = str(path)
        self.signals = signals
        self.generation = int(generation)

    def run(self) -> None:
        try:
            with open(self.path, "r", encoding="utf-8", errors="replace", newline="") as handle:
                reader = csv.DictReader(handle)
                cols = list(reader.fieldnames or [])
                if "SMILES" not in cols:
                    cols = ["SMILES"] + cols
                prepared: list[tuple[int, dict[str, str]]] = []
                mol_blobs: dict[int, bytes] = {}
                oid = 0
                for row in reader:
                    smi = (row.get("SMILES", "") or "").strip()
                    row_cells = {c: str(row.get(c, "") or "") for c in cols}
                    prepared.append((oid, row_cells))
                    if smi:
                        mol = Chem.MolFromSmiles(smi)
                        if mol is not None:
                            try:
                                blob = mol.ToBinary()
                            except Exception:
                                blob = None
                            if blob:
                                mol_blobs[oid] = bytes(blob)
                    oid += 1
            _safe_emit(
                self.signals,
                "finished",
                CsvSessionParseResult(
                    columns=cols,
                    prepared_rows=prepared,
                    mol_blobs=mol_blobs,
                    next_oid=oid,
                ),
            )
        except Exception as exc:
            logger.exception("Session CSV parse failed: %s", self.path)
            _safe_emit(
                self.signals,
                "failed",
                message_for_session_read_failure(self.path, exc),
            )
