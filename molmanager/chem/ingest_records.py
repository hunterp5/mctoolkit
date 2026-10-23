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

"""Structure-file records ready for the stores, built off the GUI thread.

File open parses molecules on a load thread or in worker processes. Each molecule becomes
an :class:`IngestRecord` holding the exact bytes the stores keep, so the GUI thread only
inserts rows and never rebuilds, copies or re-serializes a molecule. Qt-free, so worker
processes can import it.
"""

from __future__ import annotations

import io
import mmap
from collections.abc import Iterator
from typing import NamedTuple

from rdkit import Chem

from .structure_hydrogens import keep_stereo_hydrogens

#: Records per worker-process task. Large enough to amortize pickling, small enough that the
#: first rows reach the table quickly.
RECORDS_PER_CHUNK = 500

_SDF_END = b"$$$$"
_MOL2_MARKER = b"@<TRIPOS>MOLECULE"


class IngestRecord(NamedTuple):
    """One parsed structure, in the form the stores keep it.

    ``structure`` is the connection table for the molecule store (no conformers) and
    ``cells`` the file's fields as read. ``depiction`` packs flat file coordinates as the
    Structure orientation (empty for 3D). ``ensemble`` is the packed ``confs`` ensemble for
    3D coordinates, or for a structure whose file has an empty ``confs`` field, and
    ``confs_cell`` is the table cell that points at it.
    """

    structure: bytes
    cells: dict[str, str]
    smiles: str
    depiction: bytes = b""
    ensemble: bytes = b""
    confs_cell: str = ""


def ingest_record_from_mol(mol: Chem.Mol, data_headers: list[str]) -> IngestRecord:
    """Build the store payloads and table cells for *mol*."""
    from ..conformers.conformer_column_codec import (
        make_sidecar_cell,
        mol_coordinates_fill_blank_confs,
        mol_has_3d_coordinates,
    )
    from ..conformers.ensemble_binary_codec import pack_ensemble_mol
    from .depiction_coords import depiction_blob_from_mol
    from .molecule_conversion import mol_graph_binary, row_cells_from_mol

    cells = row_cells_from_mol(mol, data_headers)
    try:
        smiles = Chem.MolToSmiles(mol)
    except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
        smiles = ""
    ensemble = b""
    confs_cell = ""
    file_confs = cells.get("confs") if "confs" in cells else None
    if mol_has_3d_coordinates(mol) or mol_coordinates_fill_blank_confs(mol, file_confs):
        ensemble = pack_ensemble_mol(mol) or b""
        if ensemble:
            n_conf = int(mol.GetNumConformers())
            meta = {"ok": True, "op": "ingest", "n_kept": n_conf, "n_packed": n_conf}
            confs_cell = make_sidecar_cell("confs", meta)
    return IngestRecord(
        structure=mol_graph_binary(mol) or b"",
        cells=cells,
        smiles=smiles,
        depiction=depiction_blob_from_mol(mol),
        ensemble=ensemble,
        confs_cell=confs_cell,
    )


def _record_ends(view: mmap.mmap, marker: bytes, *, at_start: bool) -> Iterator[int]:
    """Byte offsets where a record ends: after each ``$$$$`` line, or before each MOL2 marker."""
    pos = view.find(marker)
    while pos >= 0:
        if pos == 0 or view[pos - 1 : pos] == b"\n":
            if at_start:
                if pos:
                    yield pos
            else:
                newline = view.find(b"\n", pos)
                yield len(view) if newline < 0 else newline + 1
        pos = view.find(marker, pos + len(marker))


def structure_file_chunks(
    path: str, kind: str, *, records_per_chunk: int = RECORDS_PER_CHUNK
) -> list[tuple[int, int]]:
    """Split an uncompressed SDF (``kind="sdf"``) or MOL2 file into ``(start, end)`` byte ranges.

    Each range holds up to *records_per_chunk* whole records. Splitting scans for record
    markers at line starts, so no molecule is parsed here.
    """
    with open(path, "rb") as fh:
        try:
            view = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ)
        except ValueError:
            return []
        try:
            size = len(view)
            if kind == "sdf":
                ends = _record_ends(view, _SDF_END, at_start=False)
            else:
                ends = _record_ends(view, _MOL2_MARKER, at_start=True)
            chunks: list[tuple[int, int]] = []
            start = 0
            count = 0
            for end in ends:
                count += 1
                if count >= records_per_chunk:
                    chunks.append((start, end))
                    start, count = end, 0
            if start < size and view[start:size].strip():
                chunks.append((start, size))
            return chunks
        finally:
            view.close()


def iter_chunk_mols(data: bytes, kind: str) -> Iterator[Chem.Mol]:
    """Molecules in one SDF or MOL2 byte range, read the same way as a whole file."""
    if kind == "sdf":
        for mol in Chem.ForwardSDMolSupplier(io.BytesIO(data), removeHs=False):
            if mol is not None:
                yield keep_stereo_hydrogens(mol)
        return
    text = data.decode("utf-8", errors="replace")
    marker = _MOL2_MARKER.decode("ascii")
    for block in text.split(marker):
        if not block.strip():
            continue
        mol = Chem.MolFromMol2Block(marker + block)
        if mol is not None:
            yield mol


def parse_structure_chunk(task: tuple[str, str, int, int, list[str]]) -> list[IngestRecord]:
    """Worker-process entry: parse one ``(path, kind, start, end, data_headers)`` byte range."""
    from rdkit import RDLogger

    RDLogger.DisableLog("rdApp.*")
    path, kind, start, end, data_headers = task
    with open(path, "rb") as fh:
        fh.seek(start)
        data = fh.read(end - start)
    return [ingest_record_from_mol(mol, data_headers) for mol in iter_chunk_mols(data, kind)]
