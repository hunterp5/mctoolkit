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

"""Scene builder geometry checked against RDKit's own SVG drawing.

For every plain bond (no wedge, hash, wavy or crossed style) the builder must draw the
same lines as RDKit: how many there are, and which side of the bond axis each sits on,
in steps of half the double-bond offset. Label size and trimming deliberately differ
from RDKit, so line ends are not compared.
"""

import csv
import itertools
import math
import re
from pathlib import Path

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from molmanager.chem.depiction_builder import DOUBLE_BOND_OFFSET, build_scene
from molmanager.table.table_file_formats import iter_sdf_mols

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "data" / "depiction_golden.tsv"
FDA = ROOT / "samples" / "fda_approved.sdf"
FDA_LIMIT = 500
FDA_MAX_MISMATCH_RATE = 0.002

_BOND_PATH = re.compile(r"<path class='bond-(\d+) atom-\d+ atom-\d+' d='([^']*)'")
_POINT = re.compile(r"(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")

Point = tuple[float, float]
Segment = tuple[Point, Point]


def _line_offsets(lines: list[Segment], p: Point, q: Point, bond_length: float) -> tuple:
    """Sorted perpendicular offsets of *lines* from ``p → q``, in half-offset steps."""
    ax, ay = q[0] - p[0], q[1] - p[1]
    size = math.hypot(ax, ay)
    nx, ny = -ay / size, ax / size
    step = DOUBLE_BOND_OFFSET / 2 * bond_length
    found = set()
    for (x1, y1), (x2, y2) in lines:
        mx, my = (x1 + x2) / 2 - p[0], (y1 + y2) / 2 - p[1]
        found.add(round((mx * nx + my * ny) / step))
    return tuple(sorted(found))


def _rdkit_lines(mol) -> tuple[Chem.Mol, list[Point], dict[int, list[Segment]], float]:
    """RDKit's prepared molecule, atom pixels (y up), straight bond lines, mean bond px."""
    prepared = rdMolDraw2D.PrepareMolForDrawing(mol)
    drawer = rdMolDraw2D.MolDraw2DSVG(800, 700)
    drawer.DrawMolecule(prepared)
    drawer.FinishDrawing()
    svg = drawer.GetDrawingText()
    atoms = []
    for index in range(prepared.GetNumAtoms()):
        point = drawer.GetDrawCoords(index)
        atoms.append((point.x, -point.y))
    lines: dict[int, list[Segment]] = {}
    for match in _BOND_PATH.finditer(svg):
        points = [(float(x), -float(y)) for x, y in _POINT.findall(match.group(2))]
        if len(points) == 2:
            lines.setdefault(int(match.group(1)), []).append((points[0], points[1]))
    lengths = [
        math.dist(atoms[b.GetBeginAtomIdx()], atoms[b.GetEndAtomIdx()]) for b in prepared.GetBonds()
    ]
    return prepared, atoms, lines, (sum(lengths) / len(lengths) if lengths else 1.0)


def _mismatches(mol) -> tuple[int, list[tuple]]:
    """``(bonds compared, [(bond, ours, rdkit), ...])`` for one molecule."""
    scene, _reason = build_scene(mol)
    if scene is None:
        return 0, []
    prepared, atoms, theirs, bond_px = _rdkit_lines(mol)
    ours: dict[int, list[Segment]] = {}
    for stroke in scene.strokes:
        ours.setdefault(stroke.bond, []).append(((stroke.x1, stroke.y1), (stroke.x2, stroke.y2)))
    compared = 0
    found = []
    for bond in prepared.GetBonds():
        if bond.GetBondDir() != Chem.BondDir.NONE:
            continue
        if bond.GetStereo() == Chem.BondStereo.STEREOANY:
            continue
        index = bond.GetIdx()
        if index not in ours or index not in theirs:
            continue
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        compared += 1
        mine = _line_offsets(ours[index], scene.atoms[a], scene.atoms[b], scene.mean_bond_length)
        rdkit = _line_offsets(theirs[index], atoms[a], atoms[b], bond_px)
        if mine != rdkit:
            found.append((index, mine, rdkit))
    return compared, found


def test_golden_set_bond_lines_match_rdkit():
    with GOLDEN.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    failures = {}
    for row in rows:
        _compared, found = _mismatches(Chem.MolFromSmiles(row["smiles"]))
        if found:
            failures[row["name"]] = found
    assert not failures


def test_fda_bond_lines_match_rdkit():
    compared = 0
    mismatched = 0
    for mol in itertools.islice(iter_sdf_mols(str(FDA)), FDA_LIMIT):
        count, found = _mismatches(mol)
        compared += count
        mismatched += len(found)
    assert compared > 10000
    assert mismatched / compared <= FDA_MAX_MISMATCH_RATE, (mismatched, compared)
