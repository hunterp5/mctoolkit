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

"""Place a reaction's reactants and products on the sketch canvas."""

from __future__ import annotations

import math

from PyQt5.QtCore import QPoint
from rdkit import Chem
from rdkit.Chem import rdDepictor

from .constants import SKETCH_MEDIAN_BOND_PX

_REACTION_STACK_PAD = 48
_REACTION_ARROW_GAP = 120


def reaction_from_pattern(text: str):
    """Parse a reaction SMILES or SMARTS. ``None`` when it has no product."""
    raw = text.strip()
    if ">>" not in raw and ">" not in raw:
        return None
    parser = Chem.rdChemReactions.ReactionFromSmarts
    for use_smiles in (True, False):
        try:
            reaction = parser(raw, useSmiles=use_smiles)
        except (ValueError, RuntimeError):
            reaction = None
        if reaction is not None and reaction.GetNumProductTemplates():
            return reaction
    return None


def prepared_reaction_mols(mols) -> list[Chem.Mol]:
    """Copies with atom maps removed and a 2D conformer, when RDKit can draw them."""
    prepared: list[Chem.Mol] = []
    for mol in mols:
        if mol is None or mol.GetNumAtoms() == 0:
            continue
        try:
            copy = Chem.Mol(mol)
        except (ValueError, RuntimeError):
            continue
        for atom in copy.GetAtoms():
            atom.SetAtomMapNum(0)
        try:
            Chem.SanitizeMol(copy)
        except (ValueError, RuntimeError):
            try:
                copy.UpdatePropertyCache(strict=False)
            except (ValueError, RuntimeError):
                continue
        if copy.GetNumConformers() == 0:
            try:
                rdDepictor.Compute2DCoords(copy)
            except (ValueError, RuntimeError):
                continue
        if copy.GetNumConformers() == 0:
            continue
        prepared.append(copy)
    return prepared


def _reaction_pixel_size(mol: Chem.Mol) -> tuple[int, int]:
    """Width and height of *mol* in sketch pixels, matching the 2D load scale."""
    conformer = mol.GetConformer()
    lengths: list[float] = []
    for bond in mol.GetBonds():
        begin = conformer.GetAtomPosition(bond.GetBeginAtomIdx())
        end = conformer.GetAtomPosition(bond.GetEndAtomIdx())
        lengths.append(math.hypot(begin.x - end.x, begin.y - end.y))
    median = sorted(lengths)[len(lengths) // 2] if lengths else 1.5
    scale = float(SKETCH_MEDIAN_BOND_PX) / max(median, 0.01)
    xs = [conformer.GetAtomPosition(i).x for i in range(mol.GetNumAtoms())]
    ys = [conformer.GetAtomPosition(i).y for i in range(mol.GetNumAtoms())]
    width = int(round((max(xs) - min(xs)) * scale)) + _REACTION_STACK_PAD
    height = int(round((max(ys) - min(ys)) * scale)) + _REACTION_STACK_PAD
    return max(width, _REACTION_STACK_PAD), max(height, _REACTION_STACK_PAD)


def _stacked_centers(sizes: list[tuple[int, int]], x: int, mid_y: int) -> list[QPoint]:
    total = sum(height for _width, height in sizes) + _REACTION_STACK_PAD * (len(sizes) - 1)
    top = mid_y - total / 2
    centers: list[QPoint] = []
    cursor = top
    for _width, height in sizes:
        centers.append(QPoint(int(x), int(round(cursor + height / 2))))
        cursor += height + _REACTION_STACK_PAD
    return centers


def reaction_centers(
    reactants: list[Chem.Mol], products: list[Chem.Mol]
) -> tuple[list[QPoint], list[QPoint], tuple[QPoint, QPoint]] | None:
    """Centers for each side and the arrow that sits in the gap between them."""
    left_sizes = [_reaction_pixel_size(mol) for mol in reactants]
    right_sizes = [_reaction_pixel_size(mol) for mol in products]
    if not left_sizes or not right_sizes:
        return None
    left_w = max(width for width, _height in left_sizes)
    right_w = max(width for width, _height in right_sizes)
    left_h = sum(height for _width, height in left_sizes) + _REACTION_STACK_PAD * (
        len(left_sizes) - 1
    )
    right_h = sum(height for _width, height in right_sizes) + _REACTION_STACK_PAD * (
        len(right_sizes) - 1
    )
    mid_y = 80 + max(left_h, right_h) // 2
    left_x = 40 + left_w // 2
    right_x = left_x + left_w // 2 + _REACTION_ARROW_GAP + right_w // 2
    tail = QPoint(int(left_x + left_w // 2 + 16), mid_y)
    head = QPoint(int(right_x - right_w // 2 - 16), mid_y)
    return (
        _stacked_centers(left_sizes, left_x, mid_y),
        _stacked_centers(right_sizes, right_x, mid_y),
        (tail, head),
    )
