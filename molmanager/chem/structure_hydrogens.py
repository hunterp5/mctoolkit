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

"""Add explicit hydrogen atoms to RDKit molecules."""

from __future__ import annotations

from contextlib import suppress

from rdkit import Chem


def add_explicit_hydrogens(mol: Chem.Mol) -> Chem.Mol | None:
    """
    Return a copy of *mol* with implicit hydrogens expanded to explicit H atoms.

    When a 3D conformer is present, hydrogen coordinates are computed from it.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
        Chem.SanitizeMol(m)
        if m.GetNumConformers() > 0:
            return Chem.AddHs(m, addCoords=True)
        return Chem.AddHs(m)
    except Exception:
        return None


def _bond_stereo_atom_ids(mol: Chem.Mol) -> set[int]:
    """Atom indices that define E/Z or cis/trans bond stereo."""
    ids: set[int] = set()
    for bond in mol.GetBonds():
        if bond.GetStereo() == Chem.BondStereo.STEREONONE:
            continue
        ids.update(int(atom_id) for atom_id in bond.GetStereoAtoms())
    return ids


def _nonstereo_hydrogen_indices(mol: Chem.Mol) -> list[int]:
    """Explicit hydrogens whose position is not part of the stereochemical drawing."""
    stereo_atoms = _bond_stereo_atom_ids(mol)
    drop: list[int] = []
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 1 or atom.GetIsotope() > 0 or atom.GetDegree() != 1:
            continue
        bond = atom.GetBonds()[0]
        if bond.GetBondDir() != Chem.BondDir.NONE:
            continue
        if atom.GetIdx() in stereo_atoms:
            continue
        neighbor = bond.GetOtherAtom(atom)
        if neighbor.GetAtomicNum() <= 1:
            continue
        if neighbor.GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
            continue
        drop.append(int(atom.GetIdx()))
    return drop


def keep_stereo_hydrogens(mol: Chem.Mol) -> Chem.Mol:
    """Drop explicit hydrogens that do not depict stereochemistry.

    Molblock wedging is restored first. A hydrogen stays when it carries a
    wedge, dash, or wavy bond, sits on a stereocenter, or defines double-bond
    stereo. Its coordinates stay with it. Other explicit hydrogens are removed.
    Isotopes, bridging hydrogens, and hydrogens not bonded to a heavy atom stay.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return mol
    work = Chem.Mol(mol)
    if work.GetNumConformers() > 0:
        with suppress(ValueError, RuntimeError):
            Chem.ReapplyMolBlockWedging(work)
    drop = _nonstereo_hydrogen_indices(work)
    if not drop:
        return work
    editable = Chem.RWMol(work)
    for idx in sorted(drop, reverse=True):
        editable.RemoveAtom(idx)
    out = editable.GetMol()
    try:
        Chem.SanitizeMol(out)
    except ValueError:
        try:
            return Chem.RemoveHs(work)
        except ValueError:
            return work
    if out.GetNumAtoms() == 0:
        return work
    return out


def remove_explicit_hydrogens(mol: Chem.Mol) -> Chem.Mol | None:
    """Return a copy of *mol* with explicit hydrogen atoms removed (RDKit RemoveHs)."""
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    try:
        m = Chem.Mol(mol)
        Chem.SanitizeMol(m)
        out = Chem.RemoveHs(m)
        if out is None or out.GetNumAtoms() == 0:
            return None
        return out
    except Exception:
        return None
