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

"""Terminal-group abbreviations for structure scenes.

The first set is CF3, OMe, Boc and Ph (IUPAC GR-2.3). When abbreviations are on,
the builder writes the short label on the group's attachment atom and leaves the
rest of the group out of the drawing. Atom indexes stay as they are, so highlights
still name the original atoms. The attachment atom is kept, and the covered atoms
are moved onto it so the cell fit and a highlight land on the label.

These are drawn at every cell size. A later detail level can turn the same groups
on only when the painted bond length is short.
"""

from __future__ import annotations

from dataclasses import dataclass

from rdkit import Chem

from molmanager.chem.depiction_scene import PieceKind

# Cache revisions pack layout options into the low 3 bits and this toggle into bit 3.
ABBREVIATION_REVISION_BIT = 3


@dataclass(frozen=True)
class Abbreviation:
    """One contracted group: *hidden* atoms are not drawn, *anchor* carries the label."""

    anchor: int
    hidden: frozenset[int]
    forward: tuple[tuple[str, PieceKind], ...]
    reverse: tuple[tuple[str, PieceKind], ...] | None
    attachment: str


def abbreviations_enabled() -> bool:
    """True when scenes should contract CF3, OMe, Boc and Ph."""
    from molmanager.platform_support.config import load_config

    return bool(load_config().structure_abbreviations)


def find_abbreviations(mol) -> dict[int, Abbreviation]:
    """Terminal CF3, OMe, Boc and Ph groups, keyed by the atom that keeps the label.

    Longer groups win when two would cover the same atom. A group is skipped when
    one of its atoms is charged, isotopically labelled, mapped, radical or chiral,
    or when an internal bond is wedged or hashed.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return {}
    _ensure_rings(mol)
    candidates = (*_boc_groups(mol), *_phenyl_groups(mol), *_methoxy_groups(mol), *_cf3_groups(mol))
    used: set[int] = set()
    found: dict[int, Abbreviation] = {}
    for group in candidates:
        covered = {group.anchor, *group.hidden}
        if covered & used or _has_drawn_stereo(mol, covered):
            continue
        used |= covered
        found[group.anchor] = group
    return found


def _ensure_rings(mol) -> None:
    try:
        mol.GetRingInfo().AtomRings()
    except RuntimeError:
        Chem.FastFindRings(mol)


def _plain(atom) -> bool:
    return not (
        atom.GetFormalCharge()
        or atom.GetIsotope()
        or atom.GetAtomMapNum()
        or atom.GetNumRadicalElectrons()
    )


def _heavy_neighbors(atom) -> list:
    return [other for other in atom.GetNeighbors() if other.GetAtomicNum() != 1]


def _is_methyl(atom) -> bool:
    return (
        atom.GetAtomicNum() == 6
        and _plain(atom)
        and not atom.IsInRing()
        and len(_heavy_neighbors(atom)) == 1
        and atom.GetTotalNumHs() == 3
    )


def _has_drawn_stereo(mol, atom_ids: set[int]) -> bool:
    for index in atom_ids:
        if mol.GetAtomWithIdx(index).GetChiralTag() != Chem.ChiralType.CHI_UNSPECIFIED:
            return True
    for bond in mol.GetBonds():
        begin, end = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        if begin in atom_ids and end in atom_ids and bond.GetBondDir() != Chem.BondDir.NONE:
            return True
    return False


def _with_hydrogens(mol, hidden: set[int]) -> frozenset[int]:
    """Hydrogens on covered atoms are part of the abbreviation, including added stereo H."""
    extra: set[int] = set()
    for index in hidden:
        for other in mol.GetAtomWithIdx(index).GetNeighbors():
            if other.GetAtomicNum() == 1 and other.GetDegree() == 1:
                extra.add(other.GetIdx())
    return frozenset(hidden | extra)


def _group(
    anchor: int,
    hidden: frozenset[int],
    forward: tuple[tuple[str, PieceKind], ...],
    reverse: tuple[tuple[str, PieceKind], ...] | None,
    attachment: str,
) -> Abbreviation:
    return Abbreviation(anchor, hidden, forward, reverse, attachment)


def _cf3_groups(mol) -> list[Abbreviation]:
    found = []
    forward = (
        ("C", PieceKind.NORMAL),
        ("F", PieceKind.NORMAL),
        ("3", PieceKind.SUBSCRIPT),
    )
    reverse = (
        ("F", PieceKind.NORMAL),
        ("3", PieceKind.SUBSCRIPT),
        ("C", PieceKind.NORMAL),
    )
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 6 or not _plain(atom) or len(_heavy_neighbors(atom)) != 4:
            continue
        fluorines = []
        outside = []
        for other in _heavy_neighbors(atom):
            if other.GetAtomicNum() == 9 and len(_heavy_neighbors(other)) == 1 and _plain(other):
                fluorines.append(other.GetIdx())
            else:
                outside.append(other.GetIdx())
        if len(fluorines) != 3 or len(outside) != 1:
            continue
        found.append(
            _group(atom.GetIdx(), _with_hydrogens(mol, set(fluorines)), forward, reverse, "C")
        )
    return found


def _methoxy_groups(mol) -> list[Abbreviation]:
    found = []
    forward = (("O", PieceKind.NORMAL), ("Me", PieceKind.NORMAL))
    reverse = (("Me", PieceKind.NORMAL), ("O", PieceKind.NORMAL))
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 8 or not _plain(atom) or len(_heavy_neighbors(atom)) != 2:
            continue
        methyl = None
        parent = None
        for other in _heavy_neighbors(atom):
            if _is_methyl(other):
                if methyl is not None:
                    methyl = None
                    break
                methyl = other
            else:
                parent = other
        if methyl is None or parent is None:
            continue
        found.append(
            _group(atom.GetIdx(), _with_hydrogens(mol, {methyl.GetIdx()}), forward, reverse, "O")
        )
    return found


def _phenyl_groups(mol) -> list[Abbreviation]:
    found = []
    label = (("Ph", PieceKind.NORMAL),)
    info = mol.GetRingInfo()
    for ring in info.AtomRings():
        if len(ring) != 6 or any(info.NumAtomRings(index) != 1 for index in ring):
            continue
        atoms = [mol.GetAtomWithIdx(index) for index in ring]
        if any(atom.GetAtomicNum() != 6 or not _plain(atom) for atom in atoms):
            continue
        ipso = [atom for atom in atoms if len(_heavy_neighbors(atom)) == 3]
        unsubstituted = [atom for atom in atoms if len(_heavy_neighbors(atom)) == 2]
        if len(ipso) != 1 or len(unsubstituted) != 5:
            continue
        if any(atom.GetTotalNumHs() != 1 for atom in unsubstituted):
            continue
        anchor = ipso[0]
        outside = [other for other in _heavy_neighbors(anchor) if other.GetIdx() not in ring]
        if len(outside) != 1:
            continue
        hidden = {atom.GetIdx() for atom in unsubstituted}
        found.append(_group(anchor.GetIdx(), _with_hydrogens(mol, hidden), label, None, "Ph"))
    return found


def _boc_groups(mol) -> list[Abbreviation]:
    """Boc on nitrogen or oxygen: the carbonyl carbon carries the label."""
    found = []
    label = (("Boc", PieceKind.NORMAL),)
    for carbon in mol.GetAtoms():
        if carbon.GetAtomicNum() != 6 or not _plain(carbon) or len(_heavy_neighbors(carbon)) != 3:
            continue
        carbonyl_oxygen = None
        alkoxy = None
        for bond in carbon.GetBonds():
            other = bond.GetOtherAtom(carbon)
            if other.GetAtomicNum() == 1:
                continue
            if (
                bond.GetBondType() == Chem.BondType.DOUBLE
                and other.GetAtomicNum() == 8
                and len(_heavy_neighbors(other)) == 1
                and _plain(other)
            ):
                carbonyl_oxygen = other
            elif (
                bond.GetBondType() == Chem.BondType.SINGLE
                and other.GetAtomicNum() == 8
                and len(_heavy_neighbors(other)) == 2
                and _plain(other)
            ):
                alkoxy = other
        if carbonyl_oxygen is None or alkoxy is None:
            continue
        parent = [
            other
            for other in _heavy_neighbors(carbon)
            if other.GetIdx() not in (carbonyl_oxygen.GetIdx(), alkoxy.GetIdx())
        ]
        if len(parent) != 1 or parent[0].GetAtomicNum() not in (7, 8):
            continue
        parent_bond = mol.GetBondBetweenAtoms(carbon.GetIdx(), parent[0].GetIdx())
        if parent_bond is None or parent_bond.GetBondType() != Chem.BondType.SINGLE:
            continue
        tert_butyl = [
            other for other in _heavy_neighbors(alkoxy) if other.GetIdx() != carbon.GetIdx()
        ]
        if len(tert_butyl) != 1:
            continue
        tert = tert_butyl[0]
        if tert.GetAtomicNum() != 6 or not _plain(tert) or len(_heavy_neighbors(tert)) != 4:
            continue
        methyls = [
            other.GetIdx()
            for other in _heavy_neighbors(tert)
            if other.GetIdx() != alkoxy.GetIdx() and _is_methyl(other)
        ]
        if len(methyls) != 3:
            continue
        hidden = {carbonyl_oxygen.GetIdx(), alkoxy.GetIdx(), tert.GetIdx(), *methyls}
        found.append(_group(carbon.GetIdx(), _with_hydrogens(mol, hidden), label, None, "Boc"))
    return found
