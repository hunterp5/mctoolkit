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

"""Assemble a compact ``.cms`` session document from bulk cell + structure snapshots.

Qt-free: the GUI thread snapshots ``export_rows_for_sqlite`` and
``MolStore.iter_structure_payloads``; this module fills missing blobs/SMILES
(RDKit) and compact-encodes the document for gzip write.
"""

from __future__ import annotations

import os
import zipfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from .session_codec import (
    SESSION_ENSEMBLES_KEY,
    SESSION_ENSEMBLES_MEMBER,
    SESSION_FORMAT,
    SESSION_V3_CHUNK_ROWS,
    SESSION_V3_MANIFEST,
    _dumps_json_bytes,
    compact_session_document,
    encode_mol_blob_b64,
)
from ..chem.molecule_conversion import (
    mol_graph_binary,
    mol_to_canonical_smiles,
    parse_molecule_from_cell_text,
)

StructurePayload = tuple[bytes | None, str]


def _mol_from_blob(blob: bytes | None):
    if not blob:
        return None
    from rdkit import Chem

    try:
        mol = Chem.Mol(blob)
    except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
        return None
    return mol


def assemble_session_rows(
    headers: list[str],
    entries: list[tuple[int, dict[str, str]]],
    payloads: Mapping[int, StructurePayload],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Build v1-shaped rows plus parallel structure SMILES/blob lists.

    Prefer stored ``(blob, smiles)`` payloads. Only parse or re-serialize with
    RDKit when one of those is missing.
    """
    smiles_col = "SMILES" in headers
    rows_out: list[dict[str, Any]] = []
    structure_smiles: list[str] = []
    structure_mols: list[str] = []
    for oid, raw_cells in entries:
        cells = dict(raw_cells)
        blob, store_smi = payloads.get(int(oid), (None, ""))
        smi = str(store_smi or "").strip()
        if not smi and smiles_col:
            smi = str(cells.get("SMILES") or "").strip()
        if not blob and smi:
            mol = parse_molecule_from_cell_text(smi)
            blob = mol_graph_binary(mol)
        elif blob and not smi:
            mol = _mol_from_blob(blob)
            smi = mol_to_canonical_smiles(mol) if mol is not None else ""
        if smiles_col and smi and not str(cells.get("SMILES") or "").strip():
            cells["SMILES"] = smi
        rows_out.append({"id": int(oid), "cells": cells})
        structure_smiles.append(smi)
        structure_mols.append(encode_mol_blob_b64(blob))
    return rows_out, structure_smiles, structure_mols


def assemble_session_document(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Compact a session snapshot into the on-disk document shape (no file IO)."""
    headers = list(snapshot.get("headers") or [])
    entries = list(snapshot.get("entries") or [])
    payloads = snapshot.get("payloads") or {}
    if not isinstance(payloads, Mapping):
        payloads = {}
    metadata = snapshot.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    rows, structure_smiles, structure_mols = assemble_session_rows(headers, entries, payloads)
    doc = dict(metadata)
    doc["headers"] = headers
    doc["rows"] = rows
    doc["structure_smiles"] = structure_smiles
    doc["structure_mols"] = structure_mols
    out = compact_session_document(doc)
    ensembles = snapshot.get("ensembles")
    if isinstance(ensembles, (bytes, bytearray)) and ensembles:
        out[SESSION_ENSEMBLES_KEY] = bytes(ensembles)
    return out


def write_session_v3(
    path: str,
    snapshot: Mapping[str, Any],
    *,
    chunk_rows: int = SESSION_V3_CHUNK_ROWS,
    on_progress: Callable[[int, int], None] | None = None,
) -> None:
    """Write a version-3 zip. Each row chunk is built and dropped before the next.

    The manifest holds headers and workspace metadata. Row matrices are separate
    zip members so open can read one chunk at a time.
    """
    headers = list(snapshot.get("headers") or [])
    entries = list(snapshot.get("entries") or [])
    payloads = snapshot.get("payloads") or {}
    if not isinstance(payloads, Mapping):
        payloads = {}
    metadata = snapshot.get("metadata") or {}
    if not isinstance(metadata, Mapping):
        metadata = {}
    data_headers = [h for h in headers if h and h not in ("ID_HIDDEN", "Structure")]
    manifest_doc = dict(metadata)
    manifest_doc["format"] = metadata.get("format") or SESSION_FORMAT
    manifest_doc["headers"] = headers
    manifest_doc["rows"] = []
    manifest = compact_session_document(manifest_doc)
    manifest["version"] = 3
    manifest["data_headers"] = data_headers
    manifest["row_count"] = len(entries)
    manifest["chunk_rows"] = int(chunk_rows)
    for key in ("ids", "values", "structure_smiles", "structure_mols", "rows"):
        manifest.pop(key, None)

    dest = Path(path)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    size = max(1, int(chunk_rows))
    total = len(entries)
    replaced = False
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            written = 0
            for index, start in enumerate(range(0, total, size)):
                slice_entries = entries[start : start + size]
                rows, structure_smiles, structure_mols = assemble_session_rows(
                    headers, slice_entries, payloads
                )
                chunk = {
                    "ids": [int(row["id"]) for row in rows],
                    "values": [
                        [str(row["cells"].get(header, "") or "") for header in data_headers]
                        for row in rows
                    ],
                    "structure_smiles": structure_smiles,
                    "structure_mols": structure_mols,
                }
                zf.writestr(f"rows/{index:05d}.json", _dumps_json_bytes(chunk))
                written += len(slice_entries)
                if on_progress is not None:
                    on_progress(written, total)
            ensembles = snapshot.get("ensembles")
            if isinstance(ensembles, (bytes, bytearray)) and ensembles:
                zf.writestr(SESSION_ENSEMBLES_MEMBER, bytes(ensembles))
            zf.writestr(SESSION_V3_MANIFEST, _dumps_json_bytes(manifest))
        os.replace(tmp, dest)
        replaced = True
    finally:
        if not replaced:
            tmp.unlink(missing_ok=True)
