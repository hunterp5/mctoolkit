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

"""Compound-table file suffixes, Qt filters, and readers for Open / Import / Save."""

from __future__ import annotations

import gzip
import logging
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, TextIO

from rdkit import Chem

from ..chem.structure_hydrogens import keep_stereo_hydrogens

logger = logging.getLogger(__name__)

SDF_EXTS = frozenset({".sdf", ".sd", ".mol"})
MOL2_EXTS = frozenset({".mol2", ".ml2"})
SMI_LINE_EXTS = frozenset({".smi", ".smiles"})
TABULAR_EXTS = frozenset({".csv", ".tsv", ".txt", ".xlsx"})
TDT_EXTS = frozenset({".tdt"})
PDB_EXTS = frozenset({".pdb"})
PDBQT_EXTS = frozenset({".pdbqt"})
RXN_EXTS = frozenset({".rxn", ".rdf"})
STRUCTURE_MOL_EXTS = SDF_EXTS | MOL2_EXTS | TDT_EXTS | PDB_EXTS | PDBQT_EXTS

_MOL2_MARKER = "@<TRIPOS>MOLECULE"

TABLE_OPEN_FILTER = (
    "All Supported (*.sdf *.sd *.mol *.mol2 *.ml2 *.csv *.tsv *.xlsx *.smi *.smiles "
    "*.txt *.tdt *.pdb *.pdbqt *.rxn *.rdf *.gz);;"
    "SDF/Mol (*.sdf *.sd *.mol *.sdf.gz *.sd.gz *.mol.gz);;"
    "MOL2 (*.mol2 *.ml2 *.mol2.gz);;"
    "SMILES (*.smi *.smiles *.smi.gz *.smiles.gz);;"
    "CSV/TSV (*.csv *.tsv *.txt *.csv.gz *.tsv.gz);;"
    "Excel (*.xlsx);;"
    "TDT (*.tdt);;"
    "PDB (*.pdb);;"
    "PDBQT (*.pdbqt *.pdbqt.gz);;"
    "Reactions (*.rxn *.rdf);;"
    "Gzip (*.gz)"
)

TABLE_SAVE_FILTER = (
    "SDF (*.sdf);;Molfile (*.mol);;MOL2 (*.mol2);;SMILES (*.smi);;"
    "CSV (*.csv);;TSV (*.tsv);;Excel (*.xlsx);;TDT (*.tdt);;PDB (*.pdb);;PDBQT (*.pdbqt)"
)


def table_path_parts(path: str | Path) -> tuple[str, bool]:
    """Return ``(logical_suffix, gzipped)`` for a table file path (``.sdf.gz`` → ``.sdf``)."""
    suffixes = [s.lower() for s in Path(path).suffixes]
    gzipped = bool(suffixes) and suffixes[-1] == ".gz"
    if gzipped:
        suffixes = suffixes[:-1]
    ext = suffixes[-1] if suffixes else ""
    return ext, gzipped


def logical_suffix(path: str | Path) -> str:
    """File type suffix with a trailing ``.gz`` stripped (``.csv.gz`` → ``.csv``)."""
    return table_path_parts(path)[0]


def default_table_delimiter(ext: str) -> str:
    """Default delimiter for tabular text (CSV vs TSV/SMILES/TXT)."""
    return "," if ext == ".csv" else "\t"


@contextmanager
def open_text_maybe_gzip(path: str | Path) -> Iterator[TextIO]:
    """Open *path* as UTF-8 text, transparently decompressing ``.gz``."""
    _ext, gzipped = table_path_parts(path)
    if gzipped:
        with gzip.open(path, "rt", encoding="utf-8-sig", errors="replace") as fh:
            yield fh
    else:
        with open(path, encoding="utf-8-sig", errors="replace") as fh:
            yield fh


@contextmanager
def open_binary_maybe_gzip(path: str | Path) -> Iterator[IO[bytes]]:
    """Open *path* as binary, transparently decompressing ``.gz``."""
    _ext, gzipped = table_path_parts(path)
    if gzipped:
        with gzip.open(path, "rb") as fh:
            yield fh
    else:
        with open(path, "rb") as fh:
            yield fh


@contextmanager
def uncompressed_path_if_gzip(path: str | Path) -> Iterator[str]:
    """Yield a real filesystem path; gzip inputs are written to a temporary file."""
    ext, gzipped = table_path_parts(path)
    if not gzipped:
        yield str(path)
        return
    suffix = ext or ".dat"
    tmp_path = ""
    try:
        with gzip.open(path, "rb") as src:
            data = src.read()
        fd, tmp_path = tempfile.mkstemp(suffix=suffix)
        with os.fdopen(fd, "wb") as dst:
            dst.write(data)
        yield tmp_path
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def iter_sdf_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield molecules from SDF / SD / molfile, including gzipped files.

    Always uses ``ForwardSDMolSupplier`` so uncompressed files are not indexed.
    Hydrogens are read with the record so molblock wedges and their coordinates
    exist, then hydrogens that do not depict stereochemistry are removed.
    """
    with open_binary_maybe_gzip(path) as fh:
        suppl = Chem.ForwardSDMolSupplier(fh, removeHs=False)
        for mol in suppl:
            if mol is not None:
                yield keep_stereo_hydrogens(mol)


def _iter_mol2_blocks(fh: TextIO) -> Iterator[str]:
    """Yield one MOL2 record at a time without holding later records in memory."""
    buf = ""
    while True:
        chunk = fh.read(1 << 20)
        if not chunk:
            break
        buf += chunk
        starts: list[int] = []
        idx = buf.find(_MOL2_MARKER)
        while idx >= 0:
            starts.append(idx)
            idx = buf.find(_MOL2_MARKER, idx + 1)
        if len(starts) >= 2:
            for a, b in zip(starts, starts[1:]):
                yield buf[a:b]
            buf = buf[starts[-1] :]
    if buf:
        yield buf


def iter_mol2_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield molecules from Tripos MOL2 (multi-record files split on ``@<TRIPOS>MOLECULE``)."""
    with open_text_maybe_gzip(path) as fh:
        for block in _iter_mol2_blocks(fh):
            text = block if _MOL2_MARKER in block else (_MOL2_MARKER + "\n" + block)
            mol = Chem.MolFromMol2Block(text)
            if mol is not None:
                yield mol


def iter_pdbqt_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield ligands / poses from PDBQT (MODEL records or concatenated ROOT/TORSDOF)."""
    from ..docking.pose_file_io import (
        mol_from_pdbqt_block,
        split_ligand_pdbqt_records,
        split_pdbqt_models,
    )

    with open_text_maybe_gzip(path) as fh:
        text = fh.read()
    blocks = split_pdbqt_models(text)
    if len(blocks) <= 1:
        recs = split_ligand_pdbqt_records(text)
        if recs:
            blocks = recs
    for block in blocks:
        mol = mol_from_pdbqt_block(block)
        if mol is not None:
            yield mol


def iter_pdb_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield molecules from PDB (gzip uses a temporary uncompressed file)."""
    with uncompressed_path_if_gzip(path) as local:
        suppl = Chem.PDBMolSupplier(local)
        for mol in suppl:
            if mol is not None:
                yield mol


def iter_tdt_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield molecules from Daylight TDT."""
    with uncompressed_path_if_gzip(path) as local:
        suppl = Chem.TDTMolSupplier(local)
        for mol in suppl:
            if mol is not None:
                yield mol


def iter_structure_mols(path: str | Path) -> Iterator[Chem.Mol]:
    """Yield RDKit molecules from SDF, MOL2, TDT, PDB, or PDBQT."""
    ext = logical_suffix(path)
    if ext in SDF_EXTS:
        yield from iter_sdf_mols(path)
    elif ext in MOL2_EXTS:
        yield from iter_mol2_mols(path)
    elif ext in PDBQT_EXTS:
        yield from iter_pdbqt_mols(path)
    elif ext in PDB_EXTS:
        yield from iter_pdb_mols(path)
    elif ext in TDT_EXTS:
        yield from iter_tdt_mols(path)


def load_xlsx_table(path: str | Path) -> tuple[list[str], list[dict[str, str]]]:
    """Read the first Excel sheet as string columns (requires ``openpyxl``)."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Excel (.xlsx) requires pandas.") from exc
    try:
        frame = pd.read_excel(path, dtype=str, keep_default_na=False)
    except ImportError as exc:
        raise RuntimeError(
            "Excel (.xlsx) requires openpyxl. Install with: pip install openpyxl"
        ) from exc
    fieldnames = [str(col) for col in frame.columns]
    rows: list[dict[str, str]] = []
    for rec in frame.to_dict(orient="records"):
        rows.append({name: str(rec.get(name, "") or "") for name in fieldnames})
    return fieldnames, rows


def mol_to_openbabel_format(mol: Chem.Mol, out_fmt: str) -> str:
    """Convert one RDKit molecule to MOL2 or PDBQT via Open Babel."""
    from ..platform_support.bundled_paths import apply_openbabel_runtime_env

    apply_openbabel_runtime_env()
    try:
        from openbabel import openbabel as ob
    except ImportError:
        try:
            import openbabel as ob  # type: ignore[no-redef]
        except ImportError as exc:
            raise RuntimeError(
                "Open Babel is required to write MOL2/PDBQT. Install with: pip install openbabel"
            ) from exc
    sdf = Chem.MolToMolBlock(mol) or ""
    if not sdf.strip():
        return ""
    conv = ob.OBConversion()
    if not conv.SetInAndOutFormats("mol", out_fmt):
        raise RuntimeError(f"Open Babel cannot write {out_fmt}.")
    obmol = ob.OBMol()
    if not conv.ReadString(obmol, sdf):
        return ""
    return str(conv.WriteString(obmol) or "")


def write_openbabel_mols(path: str | Path, mols: list[Chem.Mol], out_fmt: str) -> int:
    """Write *mols* as concatenated MOL2 or PDBQT records. Returns the count written."""
    written = 0
    with open(path, "w", encoding="utf-8") as fh:
        for mol in mols:
            if mol is None:
                continue
            try:
                block = mol_to_openbabel_format(mol, out_fmt)
            except RuntimeError:
                raise
            except Exception:
                logger.debug("Open Babel conversion failed for one molecule", exc_info=True)
                continue
            if not block.strip():
                continue
            fh.write(block if block.endswith("\n") else block + "\n")
            written += 1
    return written


def write_xlsx_table(path: str | Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    """Write *rows* to an ``.xlsx`` workbook (requires ``openpyxl``)."""
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError("Excel (.xlsx) requires pandas.") from exc
    frame = pd.DataFrame(rows, columns=fieldnames)
    try:
        frame.to_excel(path, index=False)
    except ImportError as exc:
        raise RuntimeError(
            "Excel (.xlsx) requires openpyxl. Install with: pip install openpyxl"
        ) from exc
