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

"""Choose the 2D coordinates a structure depiction is drawn from.

Coordinates the molecule already has win: stored orientations, SDF and molfile
drawings and sketcher output arrive as a flat conformer and are used unchanged.
Everything else gets a generated layout, made here rather than inside RDKit's
drawer so it does not depend on the process-wide ``SetPreferCoordGen`` switch
that the sketcher and superposition flip.

Generated layouts get three optional improvements, each behind its own toggle:

- Macrocycles (a ring of :data:`MACROCYCLE_RING_SIZE` or more atoms) are laid out
  with CoordGen, which draws them as ChemDraw-like rectangles instead of RDKit's
  circles. A CoordGen layout is only used when its double bonds show the
  molecule's E/Z configuration; otherwise the RDKit layout is kept.
- Macrocycle ring atoms whose substituents point into the ring are mirrored
  across the line between their ring neighbours, which puts the substituent
  outside without changing any stereo configuration.
- The layout is turned in 30° steps (so bonds stay on the hexagonal grid) when
  that lets it fill the default table cell noticeably better.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from rdkit import Chem
from rdkit.Chem import rdCoordGen, rdDepictor
from rdkit.Geometry import Point3D

# Width over height of the default Structure cell, which rotation aims to fill. The
# table module holds the cell size but reads Qt settings on import, so it stays out.
CELL_ASPECT = 210 / 170
MACROCYCLE_RING_SIZE = 12
# RDKit only assigns E/Z to ring double bonds in rings of this size or larger.
_STEREO_RING_SIZE = 8
ROTATION_STEP_DEGREES = 30
# A rotation must enlarge the cell fit by at least this factor to be used.
MIN_ROTATION_GAIN = 1.10
# Moved atoms must stay this far (in mean bond lengths) from every other atom.
MIN_FLIP_CLEARANCE = 0.5
# A conformer whose z range exceeds this is 3D, not a drawing.
_FLAT_Z_EPS = 1e-3
_MIN_XY_SPAN = 1e-4

Point = tuple[float, float]


@dataclass(frozen=True)
class LayoutOptions:
    """Which improvements apply to generated layouts."""

    macrocycle_coordgen: bool = True
    flip_inward_substituents: bool = True
    rotate_to_cell: bool = True

    @property
    def token(self) -> int:
        """Small integer identifying these options, for cache revisions."""
        return (
            int(self.macrocycle_coordgen)
            | int(self.flip_inward_substituents) << 1
            | int(self.rotate_to_cell) << 2
        )


def current_layout_options() -> LayoutOptions:
    """Layout options from the MolManager configuration."""
    from ..platform_support.config import load_config

    cfg = load_config()
    return LayoutOptions(
        macrocycle_coordgen=cfg.structure_layout_macrocycle_coordgen,
        flip_inward_substituents=cfg.structure_layout_flip_inward_substituents,
        rotate_to_cell=cfg.structure_layout_rotate_to_cell,
    )


def has_drawing_coordinates(mol) -> bool:
    """True when *mol*'s first conformer is a flat drawing with some spread."""
    if mol.GetNumAtoms() < 2 or mol.GetNumConformers() == 0:
        return False
    conformer = mol.GetConformer()
    positions = [conformer.GetAtomPosition(i) for i in range(mol.GetNumAtoms())]
    zs = [p.z for p in positions]
    if max(zs) - min(zs) > _FLAT_Z_EPS:
        return False
    xs = [p.x for p in positions]
    ys = [p.y for p in positions]
    return max(xs) - min(xs) >= _MIN_XY_SPAN or max(ys) - min(ys) >= _MIN_XY_SPAN


def layout_for_drawing(mol, options: LayoutOptions | None = None):
    """*mol*, or a copy with a generated 2D conformer, ready for ``PrepareMolForDrawing``.

    Atom and bond indices are unchanged, so highlights and stored scenes still line up.
    """
    if has_drawing_coordinates(mol):
        return mol
    opts = options if options is not None else current_layout_options()
    base = _with_stereo_hydrogens(mol)
    macrocycles = [ring for ring in _atom_rings(base) if len(ring) >= MACROCYCLE_RING_SIZE]
    layout = _rdkit_layout(base)
    if macrocycles:
        candidates = []
        if opts.macrocycle_coordgen:
            coordgen = _coordgen_layout(base)
            if coordgen is not None:
                candidates.append(coordgen)
        candidates.append(layout)
        layout = _first_with_true_double_bonds(base, candidates, opts, macrocycles)
    if opts.rotate_to_cell:
        _rotate_to_cell(layout)
    return layout


def _with_stereo_hydrogens(mol):
    """Copy of *mol* without conformers, with the explicit stereo H RDKit's drawer adds.

    ``PrepareMolForDrawing`` gives every stereocentre shared by two or more rings an
    explicit H before it lays a molecule out, so the layout leaves room for it; adding
    it after the layout can leave a bridgehead H where no wedge shows its
    configuration. The hydrogens are appended, so heavy-atom indices are unchanged,
    and ``PrepareMolForDrawing`` then adds no more.
    """
    base = Chem.Mol(mol)
    base.RemoveAllConformers()
    rings = base.GetRingInfo()
    centres = [
        atom.GetIdx()
        for atom in base.GetAtoms()
        if atom.GetChiralTag()
        in (Chem.ChiralType.CHI_TETRAHEDRAL_CW, Chem.ChiralType.CHI_TETRAHEDRAL_CCW)
        and rings.NumAtomRings(atom.GetIdx()) > 1
    ]
    return Chem.AddHs(base, onlyOnAtoms=centres) if centres else base


def _atom_rings(mol) -> list[tuple[int, ...]]:
    try:
        return list(mol.GetRingInfo().AtomRings())
    except RuntimeError:
        Chem.FastFindRings(mol)
        return list(mol.GetRingInfo().AtomRings())


def _rdkit_layout(base):
    layout = Chem.Mol(base)
    rdDepictor.Compute2DCoords(layout, forceRDKit=True)
    return layout


def _coordgen_layout(base):
    layout = Chem.Mol(base)
    try:
        rdCoordGen.AddCoords(layout)
    except (RuntimeError, ValueError):
        return None
    return layout if layout.GetNumConformers() else None


def _first_with_true_double_bonds(base, candidates, options: LayoutOptions, macrocycles):
    """First candidate (after flips) that draws every E/Z double bond as configured.

    Falls back to the last candidate, the plain RDKit layout, so a molecule always
    gets a picture.
    """
    expected = _double_bond_configuration(base)
    for layout in candidates:
        if options.flip_inward_substituents:
            flipped = Chem.Mol(layout)
            _flip_inward_substituents(flipped, macrocycles)
            if _drawn_double_bond_configuration(flipped, expected):
                return flipped
        if _drawn_double_bond_configuration(layout, expected):
            return layout
    return candidates[-1]


def _double_bond_configuration(mol) -> dict[int, Chem.BondStereo]:
    """E/Z label of every double bond whose configuration *mol* specifies."""
    copy = Chem.Mol(mol)
    Chem.AssignStereochemistry(copy, cleanIt=True, force=True)
    return {
        bond.GetIdx(): bond.GetStereo()
        for bond in copy.GetBonds()
        if bond.GetStereo() in (Chem.BondStereo.STEREOE, Chem.BondStereo.STEREOZ)
    }


def _drawn_double_bond_configuration(layout, expected: dict[int, Chem.BondStereo]) -> bool:
    """True when the coordinates of *layout* show every double bond in *expected* correctly."""
    if not expected:
        return True
    drawn = Chem.Mol(layout)
    for bond in drawn.GetBonds():
        if bond.GetBondType() == Chem.BondType.DOUBLE:
            bond.SetStereo(Chem.BondStereo.STEREONONE)
        elif bond.GetBondDir() in (Chem.BondDir.ENDUPRIGHT, Chem.BondDir.ENDDOWNRIGHT):
            bond.SetBondDir(Chem.BondDir.NONE)
    Chem.DetectBondStereochemistry(drawn, drawn.GetConformer().GetId())
    Chem.AssignStereochemistry(drawn, cleanIt=True, force=True)
    return all(
        drawn.GetBondWithIdx(index).GetStereo() == label for index, label in expected.items()
    )


def _positions(mol) -> list[Point]:
    conformer = mol.GetConformer()
    return [
        (conformer.GetAtomPosition(i).x, conformer.GetAtomPosition(i).y)
        for i in range(mol.GetNumAtoms())
    ]


def _set_positions(mol, positions: list[Point]) -> None:
    conformer = mol.GetConformer()
    for index, (x, y) in enumerate(positions):
        conformer.SetAtomPosition(index, Point3D(x, y, 0.0))


def _mean_bond_length(mol, positions: list[Point]) -> float:
    lengths = [
        math.dist(positions[bond.GetBeginAtomIdx()], positions[bond.GetEndAtomIdx()])
        for bond in mol.GetBonds()
    ]
    return sum(lengths) / len(lengths) if lengths else 1.0


def _inside(point: Point, polygon: list[Point]) -> bool:
    """Even-odd point-in-polygon test."""
    x, y = point
    inside = False
    for (x1, y1), (x2, y2) in zip(polygon, polygon[-1:] + polygon[:-1]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def _reflect(point: Point, p: Point, q: Point) -> Point:
    """*point* mirrored across the line through *p* and *q*."""
    dx, dy = q[0] - p[0], q[1] - p[1]
    length_sq = dx * dx + dy * dy
    t = ((point[0] - p[0]) * dx + (point[1] - p[1]) * dy) / length_sq
    foot = (p[0] + t * dx, p[1] + t * dy)
    return (2 * foot[0] - point[0], 2 * foot[1] - point[1])


def _branch(mol, root: int, ring: set[int]) -> set[int] | None:
    """*root* plus every atom reached from it without entering *ring*.

    ``None`` when the branch connects back to *ring* through another atom, since
    mirroring it would then stretch the connecting bonds.
    """
    seen = {root}
    stack = [n.GetIdx() for n in mol.GetAtomWithIdx(root).GetNeighbors() if n.GetIdx() not in ring]
    while stack:
        index = stack.pop()
        if index in seen:
            continue
        seen.add(index)
        for neighbour in mol.GetAtomWithIdx(index).GetNeighbors():
            other = neighbour.GetIdx()
            if other in ring and other != root:
                return None
            if other not in seen and other not in ring:
                stack.append(other)
    return seen


def _has_stereo_capable_double_bond(atom) -> bool:
    """True when *atom* is in a double bond whose two ends both have other neighbours.

    Moving a neighbour of such a bond could change its drawn E/Z shape.
    """
    for bond in atom.GetBonds():
        if bond.GetBondType() != Chem.BondType.DOUBLE:
            continue
        if bond.GetBeginAtom().GetDegree() > 1 and bond.GetEndAtom().GetDegree() > 1:
            return True
    return False


def _flip_inward_substituents(mol, macrocycles: list[tuple[int, ...]]) -> int:
    """Mirror ring atoms whose substituents point into a macrocycle. Returns the flip count.

    A ring atom *r* between ring neighbours *a* and *b* is mirrored, with its whole
    branch, across the line *a*–*b*. Only *r* and its branch move and *a*, *b* lie on
    the mirror, so bond lengths and every stereo configuration in the branch are kept.
    Atoms in two rings, branches that reconnect to the ring, double bonds that could
    change their E/Z shape, and flips that crowd other atoms are skipped.
    """
    positions = _positions(mol)
    clearance = MIN_FLIP_CLEARANCE * _mean_bond_length(mol, positions)
    ring_count = mol.GetRingInfo().NumAtomRings
    flips = 0
    for ring in macrocycles:
        members = set(ring)
        for k, root in enumerate(ring):
            atom = mol.GetAtomWithIdx(root)
            substituents = [n.GetIdx() for n in atom.GetNeighbors() if n.GetIdx() not in members]
            polygon = [positions[i] for i in ring]
            if not substituents or ring_count(root) > 1:
                continue
            if not any(_inside(positions[s], polygon) for s in substituents):
                continue
            a, b = ring[k - 1], ring[(k + 1) % len(ring)]
            if any(_has_stereo_capable_double_bond(mol.GetAtomWithIdx(i)) for i in (root, a, b)):
                continue
            branch = _branch(mol, root, members)
            if branch is None:
                continue
            moved = {i: _reflect(positions[i], positions[a], positions[b]) for i in branch}
            trial = [moved.get(i, p) for i, p in enumerate(positions)]
            trial_polygon = [trial[i] for i in ring]
            if any(_inside(trial[s], trial_polygon) for s in substituents):
                continue
            if any(
                math.dist(trial[i], trial[j]) < clearance
                for i in branch
                for j in range(len(trial))
                if j not in branch and mol.GetBondBetweenAtoms(i, j) is None
            ):
                continue
            positions = trial
            flips += 1
    if flips:
        _set_positions(mol, positions)
    return flips


def _cell_fit(positions: list[Point], angle: float, margin: float) -> float:
    """Scale at which *positions* turned by *angle* fit a cell of :data:`CELL_ASPECT`, height 1."""
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    xs = [x * cos_a - y * sin_a for x, y in positions]
    ys = [x * sin_a + y * cos_a for x, y in positions]
    width = max(xs) - min(xs) + margin
    height = max(ys) - min(ys) + margin
    return min(CELL_ASPECT / width, 1.0 / height)


def _rotate_to_cell(mol) -> None:
    """Turn *mol*'s layout by a multiple of 30° when it then fills the cell much better.

    The margin of one bond length stands in for the labels at the edges.
    """
    positions = _positions(mol)
    if len(positions) < 3:
        return
    margin = _mean_bond_length(mol, positions)
    current = _cell_fit(positions, 0.0, margin)
    best_angle, best_fit = 0.0, current
    for step in range(1, 180 // ROTATION_STEP_DEGREES):
        angle = math.radians(step * ROTATION_STEP_DEGREES)
        fit = _cell_fit(positions, angle, margin)
        if fit > best_fit:
            best_angle, best_fit = angle, fit
    if best_fit < current * MIN_ROTATION_GAIN:
        return
    cos_a, sin_a = math.cos(best_angle), math.sin(best_angle)
    _set_positions(mol, [(x * cos_a - y * sin_a, x * sin_a + y * cos_a) for x, y in positions])
