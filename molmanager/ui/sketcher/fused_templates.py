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

"""Fused-ring sketch templates: naphthalene, indole, and a few common heterocycles.

Each template is a Kekulé graph with one peripheral bond marked for fusion.
Dropping the template on a bond shares that edge. Dropping it on an atom shares
one atom of the fragment and grows the rest into the open side of that atom.
Dropping it on empty canvas places the whole fragment.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from rdkit import Chem
from rdkit.Chem import rdDepictor

from .iupac_rings import _largest_gap_bisector

FUSED_TEMPLATE_SMILES: dict[str, str] = {
    "Naphthalene": "c1ccc2ccccc2c1",
    "Indole": "c1ccc2[nH]ccc2c1",
    "Quinoline": "c1ccc2ncccc2c1",
    "Isoquinoline": "c1ccc2cnccc2c1",
    "Benzimidazole": "c1ccc2[nH]cnc2c1",
    "Purine": "c1ncc2nc[nH]c2n1",
}


@dataclass(frozen=True)
class FusedTemplate:
    """Heavy-atom graph in RDKit y-up coordinates. *fusion* is a peripheral bond."""

    elements: tuple[str, ...]
    bonds: tuple[tuple[int, int, int], ...]
    coords: tuple[tuple[float, float], ...]
    fusion: tuple[int, int]


def _median(values: list[float]) -> float:
    if not values:
        return 1.0
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def _peripheral_bond(mol: Chem.Mol) -> tuple[int, int]:
    """A ring bond that belongs to only one ring, stable across runs."""
    info = mol.GetRingInfo()
    counts: dict[int, int] = {}
    for ring in info.BondRings():
        for index in ring:
            counts[int(index)] = counts.get(int(index), 0) + 1
    candidates = []
    for index, count in counts.items():
        if count != 1:
            continue
        bond = mol.GetBondWithIdx(index)
        a = int(bond.GetBeginAtomIdx())
        b = int(bond.GetEndAtomIdx())
        candidates.append((min(a, b), max(a, b), a, b))
    if not candidates:
        bond = mol.GetBondWithIdx(0)
        return int(bond.GetBeginAtomIdx()), int(bond.GetEndAtomIdx())
    _lo, _hi, begin, end = min(candidates)
    return begin, end


@lru_cache(maxsize=None)
def fused_template(name: str) -> FusedTemplate | None:
    """Kekulé heavy-atom template, or ``None`` when *name* is not a fused system."""
    smiles = FUSED_TEMPLATE_SMILES.get(name)
    if not smiles:
        return None
    mol = Chem.MolFromSmiles(smiles)
    if mol is None:
        return None
    try:
        Chem.Kekulize(mol, clearAromaticFlags=True)
        rdDepictor.Compute2DCoords(mol)
    except (RuntimeError, ValueError):
        return None
    if mol.GetNumConformers() == 0:
        return None
    keep = [atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1]
    remap = {old: new for new, old in enumerate(keep)}
    conformer = mol.GetConformer()
    elements = tuple(mol.GetAtomWithIdx(old).GetSymbol() for old in keep)
    coords = tuple(
        (float(conformer.GetAtomPosition(old).x), float(conformer.GetAtomPosition(old).y))
        for old in keep
    )
    bonds: list[tuple[int, int, int]] = []
    for bond in mol.GetBonds():
        a = remap.get(bond.GetBeginAtomIdx())
        b = remap.get(bond.GetEndAtomIdx())
        if a is None or b is None:
            continue
        kind = bond.GetBondType()
        order = 2 if kind == Chem.BondType.DOUBLE else 3 if kind == Chem.BondType.TRIPLE else 1
        bonds.append((a, b, order))
    begin, end = _peripheral_bond(mol)
    fusion = (remap[begin], remap[end])
    return FusedTemplate(elements, tuple(bonds), coords, fusion)


def _screen_local(template: FusedTemplate) -> list[tuple[float, float]]:
    """Template coordinates in screen space (y down), fusion atom at the origin."""
    fx, fy = template.coords[template.fusion[0]]
    return [(x - fx, -(y - fy)) for x, y in template.coords]


def screen_points_centered(
    template: FusedTemplate, cx: float, cy: float, bond_px: float
) -> list[tuple[float, float]]:
    """Place *template* so its centroid is ``(cx, cy)`` and bonds match *bond_px*."""
    local = _screen_local(template)
    lengths = [
        math.hypot(local[j][0] - local[i][0], local[j][1] - local[i][1])
        for i, j, _order in template.bonds
    ]
    scale = float(bond_px) / max(_median(lengths), 1e-6)
    mx = sum(x for x, _y in local) / len(local)
    my = sum(y for _x, y in local) / len(local)
    return [((x - mx) * scale + cx, (y - my) * scale + cy) for x, y in local]


def _scale_about_origin(
    points: Sequence[tuple[float, float]],
    bond_px: float,
    bonds: Sequence[tuple[int, int, int]],
) -> list[tuple[float, float]]:
    lengths = [
        math.hypot(points[j][0] - points[i][0], points[j][1] - points[i][1])
        for i, j, _order in bonds
    ]
    scale = float(bond_px) / max(_median(lengths), 1e-6)
    return [(x * scale, y * scale) for x, y in points]


def _reflect_across(
    points: Sequence[tuple[float, float]], ux: float, uy: float
) -> list[tuple[float, float]]:
    reflected: list[tuple[float, float]] = []
    for x, y in points:
        along = x * ux + y * uy
        px, py = x - along * ux, y - along * uy
        reflected.append((along * ux - px, along * uy - py))
    return reflected


def screen_points_on_atom(
    template: FusedTemplate,
    ax: float,
    ay: float,
    neighbor_dirs: Sequence[tuple[float, float]],
    bond_px: float,
    obstacle_points: Sequence[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """Place the template's first fusion atom on ``(ax, ay)`` in screen space.

    The fragment grows into the largest gap between *neighbor_dirs* (also screen
    space, relative to the atom). The bonds that leave the shared atom are kept
    off those neighbors. *obstacle_points* are other atoms in the same frame;
    the mirror that stays farther from them is used.
    """
    local = _scale_about_origin(_screen_local(template), bond_px, template.bonds)
    anchor = template.fusion[0]
    neighbors = []
    for i, j, _order in template.bonds:
        if i == anchor:
            neighbors.append(local[j])
        elif j == anchor:
            neighbors.append(local[i])
    if not neighbors:
        return [(ax + x, ay + y) for x, y in local]
    gap = _largest_gap_bisector(
        [math.atan2(dy, dx) for dx, dy in neighbor_dirs if math.hypot(dx, dy) > 1e-6]
    )
    # Bisector of the template bonds that faces the rest of the fragment.
    angs = [math.atan2(y, x) for x, y in neighbors if math.hypot(x, y) > 1e-6]
    cx = sum(x for x, _y in local) / len(local)
    cy = sum(y for _x, y in local) / len(local)
    if len(angs) >= 2:
        # Largest gap at the anchor points out of a convex ring; flip toward the fragment.
        bisector = _largest_gap_bisector(angs)
        if math.hypot(cx, cy) > 1e-6 and math.cos(math.atan2(cy, cx) - bisector) < 0:
            bisector = (bisector + math.pi) % (2.0 * math.pi)
    elif math.hypot(cx, cy) > 1e-6:
        bisector = math.atan2(cy, cx)
    else:
        bisector = angs[0] if angs else 0.0
    cos_r, sin_r = math.cos(gap - bisector), math.sin(gap - bisector)
    rotated = [(x * cos_r - y * sin_r, x * sin_r + y * cos_r) for x, y in local]
    ux, uy = math.cos(gap), math.sin(gap)
    mirrored = _reflect_across(rotated, ux, uy)
    obstacles = list(obstacle_points or ())

    def _clearance(pts: list[tuple[float, float]]) -> float:
        nearest = min(
            (math.hypot(x, y) for i, (x, y) in enumerate(pts) if i != anchor),
            default=0.0,
        )
        for i, (x, y) in enumerate(pts):
            if i == anchor:
                continue
            for ox, oy in obstacles:
                nearest = min(nearest, math.hypot(x - ox, y - oy))
        return nearest

    chosen = rotated if _clearance(rotated) >= _clearance(mirrored) else mirrored
    return [(ax + x, ay + y) for x, y in chosen]


def screen_points_on_bond(
    template: FusedTemplate,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    *,
    prefer_side: float = 1.0,
) -> list[tuple[float, float]]:
    """Map the template's fusion bond onto the screen segment A→B.

    *prefer_side* picks which side of A→B the rest of the fragment occupies.
    """
    local = _screen_local(template)
    other = template.fusion[1]
    vx, vy = local[other]
    span = math.hypot(vx, vy) or 1.0
    target = math.hypot(bx - ax, by - ay) or 1.0
    scale = target / span
    scaled = [(x * scale, y * scale) for x, y in local]
    angle = math.atan2(by - ay, bx - ax) - math.atan2(scaled[other][1], scaled[other][0])
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rotated = [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in scaled]
    others = [point for index, point in enumerate(rotated) if index not in template.fusion]
    if others:
        cx = sum(point[0] for point in others) / len(others)
        cy = sum(point[1] for point in others) / len(others)
        cross = (bx - ax) * cy - (by - ay) * cx
        if cross * prefer_side < 0:
            ux, uy = (bx - ax) / target, (by - ay) / target
            reflected = []
            for x, y in rotated:
                along = x * ux + y * uy
                px, py = x - along * ux, y - along * uy
                reflected.append((along * ux - px, along * uy - py))
            rotated = reflected
    return [(ax + x, ay + y) for x, y in rotated]
