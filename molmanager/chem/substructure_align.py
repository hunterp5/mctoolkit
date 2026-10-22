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

"""Orient a molecule's 2D depiction to a substructure drawn in a chosen pose.

The query molecule carries both the substructure pattern and the coordinate
frame. Rows that do not contain it are left unchanged.
"""

from __future__ import annotations

from .depiction_coords import pack_xy
from .molecule_conversion import looks_like_mol_block

_MIN_QUERY_ATOMS = 2

# RDKit raises ValueError (sanitize, depiction mismatch), RuntimeError (invariant
# violations), and Boost ArgumentError, a TypeError subclass, on bad inputs.
_RDKIT_ERRORS = (ValueError, RuntimeError, TypeError)


def partition_alignment_scope(
    oids: list[int],
    already: set[int],
    *,
    skip_existing: bool,
) -> tuple[list[int], int]:
    """Oids still to align, and how many were left alone because they already had a pose."""
    ordered = [int(oid) for oid in oids]
    if not skip_existing or not already:
        return ordered, 0
    keep = [oid for oid in ordered if oid not in already]
    return keep, len(ordered) - len(keep)


def conformer_xy(mol) -> tuple[list[float], list[float]]:
    """X and Y of the first conformer. Empty when *mol* has no coordinates."""
    if mol is None or mol.GetNumConformers() < 1:
        return [], []
    conf = mol.GetConformer()
    xs: list[float] = []
    ys: list[float] = []
    for i in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        xs.append(float(pos.x))
        ys.append(float(pos.y))
    return xs, ys


def set_conformer_xy(mol, xs: list[float], ys: list[float]):
    """Return a copy of *mol* whose conformer uses *xs* and *ys*."""
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    out = Chem.Mol(mol)
    n = out.GetNumAtoms()
    if len(xs) != n or len(ys) != n:
        raise ValueError("Coordinate length does not match the atom count.")
    out.RemoveAllConformers()
    conf = Chem.Conformer(n)
    for i in range(n):
        conf.SetAtomPosition(i, Point3D(float(xs[i]), float(ys[i]), 0.0))
    out.AddConformer(conf, assignId=True)
    return out


def _layout_2d(mol) -> bool:
    """RDKit's default depictor, not CoordGen, matching table pictures."""
    from rdkit.Chem import rdDepictor

    rdDepictor.SetPreferCoordGen(False)
    try:
        rdDepictor.Compute2DCoords(mol)
    except _RDKIT_ERRORS:
        return False
    return mol.GetNumConformers() > 0


def _zero_z(mol) -> None:
    """Keep x,y and drop z so a molfile pose stays a 2D orientation."""
    if mol is None or mol.GetNumConformers() < 1:
        return
    from rdkit.Geometry import Point3D

    conf = mol.GetConformer()
    for i in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        if abs(float(pos.z)) > 1e-8:
            conf.SetAtomPosition(i, Point3D(float(pos.x), float(pos.y), 0.0))


def _aromatize_keeping_coords(mol):
    """Sanitize when that preserves atoms and coordinates, so benzene matches table mols."""
    from rdkit import Chem

    copy = Chem.Mol(mol)
    try:
        Chem.SanitizeMol(copy)
    except _RDKIT_ERRORS:
        return mol
    if copy.GetNumAtoms() != mol.GetNumAtoms():
        return mol
    if mol.GetNumConformers() > 0 and copy.GetNumConformers() < 1:
        return mol
    return copy


def _single_fragment(mol) -> bool:
    from rdkit import Chem

    return len(Chem.GetMolFrags(mol)) == 1


def _mol_from_molblock(text: str):
    from rdkit import Chem

    for candidate in (text, "\n" + text):
        mol = Chem.MolFromMolBlock(candidate, sanitize=True, removeHs=False)
        if mol is not None:
            return mol
    return None


def prepare_query_mol(mol) -> tuple[object | None, str]:
    """One fragment, at least two atoms, with a planar conformer.

    Sanitizes when that keeps the coordinates, so a Kekulé drawing matches
    aromatic table structures. Query atoms that cannot be sanitized are kept.
    """
    if mol is None or mol.GetNumAtoms() < 1:
        return None, "Draw or paste a substructure."
    if mol.GetNumAtoms() < _MIN_QUERY_ATOMS:
        return None, "The query needs at least two atoms to set an orientation."
    if not _single_fragment(mol):
        return None, "The query must be a single fragment."
    prepared = _aromatize_keeping_coords(mol)
    if prepared.GetNumConformers() < 1:
        if not _layout_2d(prepared):
            return None, "Open the sketcher to give this query an orientation."
    else:
        _zero_z(prepared)
    if prepared.GetNumConformers() < 1:
        return None, "Open the sketcher to give this query an orientation."
    return prepared, ""


def query_mol_from_text(text: str) -> tuple[object | None, str]:
    """Parse SMILES, SMARTS, or a molfile into an oriented query.

    A molfile keeps its embedded coordinates. SMILES and SMARTS receive an
    initial RDKit 2D layout the user can rotate in the dialog.
    """
    raw = (text or "").strip()
    if not raw:
        return None, "Enter a substructure."
    from rdkit import Chem

    if looks_like_mol_block(raw):
        mol = _mol_from_molblock(raw)
        if mol is None:
            return None, "Could not read that molfile."
        if mol.GetNumConformers() < 1 and not _layout_2d(mol):
            return None, "The molfile has no 2D coordinates."
        return prepare_query_mol(mol)

    mol = Chem.MolFromSmiles(raw)
    if mol is None:
        mol = Chem.MolFromSmarts(raw)
        if mol is None:
            return None, "Could not parse that SMILES or SMARTS."
        if not _layout_2d(mol):
            return None, "Open the sketcher to give this SMARTS an orientation."
        return prepare_query_mol(mol)
    if not _layout_2d(mol):
        return None, "Could not lay out that substructure."
    return prepare_query_mol(mol)


def align_mol_to_template(mol, template) -> bytes | None:
    """Packed 2D coordinates of *mol* with *template* pinned, or ``None`` on a miss.

    The first substructure match is used. Stereochemistry on *mol* is kept;
    only the depiction coordinates change.
    """
    if mol is None or template is None:
        return None
    if template.GetNumConformers() < 1 or template.GetNumAtoms() < _MIN_QUERY_ATOMS:
        return None
    match = mol.GetSubstructMatch(template)
    if not match or len(match) < _MIN_QUERY_ATOMS:
        return None
    from rdkit import Chem
    from rdkit.Chem import rdDepictor

    out = Chem.Mol(mol)
    out.RemoveAllConformers()
    rdkit_map = [(int(ref_i), int(match[ref_i])) for ref_i in range(len(match))]
    rdDepictor.SetPreferCoordGen(False)
    try:
        rdDepictor.GenerateDepictionMatching2DStructure(out, template, rdkit_map)
    except _RDKIT_ERRORS:
        return None
    if out.GetNumConformers() < 1:
        return None
    conf = out.GetConformer()
    points = []
    for i in range(out.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        points.append((float(pos.x), float(pos.y)))
    return pack_xy(points)


def align_structure_rows(
    rows: list[tuple[int, object]],
    template,
    *,
    cancelled=None,
    on_progress=None,
) -> tuple[list[tuple[int, bytes]], int, bool]:
    """Align each ``(oid, mol_or_blob_or_text)`` row.

    Returns ``(aligned, skipped, was_cancelled)``. Skipped rows include parse
    failures and substructure misses. Already-oriented rows are filtered by
    the caller before this runs.
    """
    from .molecule_conversion import mol_from_tool_input

    items = list(rows)
    total = max(len(items), 1)
    aligned: list[tuple[int, bytes]] = []
    skipped = 0
    was_cancelled = False
    for done, row in enumerate(items, start=1):
        if cancelled is not None and cancelled():
            was_cancelled = True
            skipped += len(items) - done + 1
            break
        oid = int(row[0])
        mol = mol_from_tool_input(row[1])
        blob = align_mol_to_template(mol, template) if mol is not None else None
        if blob:
            aligned.append((oid, blob))
        else:
            skipped += 1
        if on_progress is not None:
            on_progress(done, total)
    return aligned, skipped, was_cancelled
