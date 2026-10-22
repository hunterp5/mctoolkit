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

import csv
import math
import subprocess
import sys
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point3D

from molmanager.chem.depiction_builder import build_scene, scene_fallback_reason
from molmanager.chem.depiction_scene import LabelOrientation, StrokeStyle, pack_scene, unpack_scene

ROOT = Path(__file__).resolve().parent.parent
GOLDEN = ROOT / "tests" / "data" / "depiction_golden.tsv"
# Golden molecules the builder deliberately hands back to RDKit, with the reason.
EXPECTED_FALLBACKS = {"methyl_radical": "radical"}


def _golden() -> dict[str, Chem.Mol]:
    with GOLDEN.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    return {row["name"]: Chem.MolFromSmiles(row["smiles"]) for row in rows}


def _scene(smiles: str):
    scene, reason = build_scene(Chem.MolFromSmiles(smiles))
    assert scene is not None, reason
    return scene


def _with_coords(smiles: str, points: list[tuple[float, float]]) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    conf = Chem.Conformer(mol.GetNumAtoms())
    for index, (x, y) in enumerate(points):
        conf.SetAtomPosition(index, Point3D(x, y, 0.0))
    mol.AddConformer(conf, assignId=True)
    return mol


def _label_text(label) -> str:
    return "".join(piece.text for piece in label.pieces)


def _inside(point: tuple[float, float], box, eps: float = 1e-4) -> bool:
    return box[0] + eps < point[0] < box[2] - eps and box[1] + eps < point[1] < box[3] - eps


def test_golden_set_builds_or_falls_back_as_expected():
    for name, mol in _golden().items():
        scene, reason = build_scene(mol)
        if name in EXPECTED_FALLBACKS:
            assert scene is None and reason == EXPECTED_FALLBACKS[name], name
            continue
        assert scene is not None, f"{name}: {reason}"
        assert unpack_scene(pack_scene(scene)) is not None, name


def test_no_stroke_ends_inside_a_label():
    for name, mol in _golden().items():
        scene, _reason = build_scene(mol)
        if scene is None:
            continue
        for stroke in scene.strokes:
            for label in scene.labels:
                for point in ((stroke.x1, stroke.y1), (stroke.x2, stroke.y2)):
                    assert not _inside(point, label.box), f"{name}: {_label_text(label)}"


def test_benzene_inner_lines_sit_inside_the_ring():
    scene = _scene("c1ccccc1")
    assert len(scene.strokes) == 9
    cx = sum(x for x, _ in scene.atoms) / 6
    cy = sum(y for _, y in scene.atoms) / 6
    ring_radius = math.dist(scene.atoms[0], (cx, cy))
    by_bond: dict[int, list] = {}
    for stroke in scene.strokes:
        by_bond.setdefault(stroke.bond, []).append(stroke)
    doubles = [strokes for strokes in by_bond.values() if len(strokes) == 2]
    assert len(doubles) == 3
    for outer, inner in doubles:
        for stroke in (outer, inner):
            mid = ((stroke.x1 + stroke.x2) / 2, (stroke.y1 + stroke.y2) / 2)
            distance = math.dist(mid, (cx, cy))
            assert distance < ring_radius + 1e-6
        lengths = [math.dist((s.x1, s.y1), (s.x2, s.y2)) for s in (outer, inner)]
        assert min(lengths) < max(lengths)


def test_terminal_carbonyl_is_centred_on_the_bond():
    mol = _with_coords("CC(=O)C", [(-1.3, -0.75), (0.0, 0.0), (0.0, 1.5), (1.3, -0.75)])
    scene, _reason = build_scene(mol)
    # Two lines, each split into a carbon half and an oxygen half.
    carbonyl = [s for s in scene.strokes if s.bond == 1]
    assert len(carbonyl) == 4
    xs = sorted({round((s.x1 + s.x2) / 2, 6) for s in carbonyl})
    assert len(xs) == 2
    assert xs[0] == pytest.approx(-xs[1], abs=1e-6)


@pytest.mark.parametrize(
    ("o_x", "expected", "orientation"),
    [(1.5, "OH", LabelOrientation.EAST), (-1.5, "HO", LabelOrientation.WEST)],
)
def test_hydroxyl_label_reverses_when_bonded_from_the_right(o_x, expected, orientation):
    scene, _reason = build_scene(_with_coords("CO", [(0.0, 0.0), (o_x, 0.0)]))
    (label,) = scene.labels
    assert _label_text(label) == expected
    assert label.orientation == orientation


def test_ring_nh_stacks_its_hydrogen():
    scene = _scene("c1ccc2[nH]ccc2c1")
    (label,) = scene.labels
    assert label.orientation in (LabelOrientation.NORTH, LabelOrientation.SOUTH)
    nitrogen = next(p for p in label.pieces if p.text == "N")
    hydrogen = next(p for p in label.pieces if p.text == "H")
    assert hydrogen.x == pytest.approx(nitrogen.x, abs=0.2)
    assert abs(hydrogen.y - nitrogen.y) > 0.3


def test_bonded_carbon_labels_omit_hydrogens():
    scene = _scene("C[13CH2]O")
    texts = {_label_text(label) for label in scene.labels}
    assert "13C" in texts


def test_cumulated_carbon_is_labelled():
    texts = [_label_text(label) for label in _scene("CC=C=CC").labels]
    assert texts == ["C"]


def test_charges_and_isotopes_are_scripts():
    scene = _scene("[NH4+]")
    (label,) = scene.labels
    assert [(p.text, p.kind.name) for p in label.pieces] == [
        ("N", "NORMAL"),
        ("H", "NORMAL"),
        ("4", "SUBSCRIPT"),
        ("+", "SUPERSCRIPT"),
    ]


def _fda_molecules(names: set[str]) -> dict[str, Chem.Mol]:
    """FDA sample molecules whose ``_Name`` starts with one of *names*, keeping SDF coordinates."""
    from molmanager.chem.molecule_conversion import safe_mol_prop_string

    found = {}
    for mol in Chem.SDMolSupplier(str(ROOT / "samples" / "fda_approved.sdf")):
        if mol is None:
            continue
        words = safe_mol_prop_string(mol, "_Name").split(".")[0].split()
        name = words[-1] if words else ""
        if name in names:
            found[name] = mol
    return found


def _boxes_overlap(a, b) -> bool:
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_added_stereo_hydrogens_stay_clear_of_other_labels_and_bonds():
    from molmanager.chem.depiction_builder import _box_interval

    mols = _fda_molecules({"Exemestane", "Dutasteride", "Artemisinin", "Gelsemine"})
    assert len(mols) == 4
    for name, mol in mols.items():
        scene, _reason = build_scene(mol)
        prepared = rdMolDraw2D.PrepareMolForDrawing(mol)
        added = [lab for lab in scene.labels if lab.atom >= mol.GetNumAtoms()]
        assert added, name
        for lab in added:
            parent_bond = prepared.GetAtomWithIdx(lab.atom).GetBonds()[0].GetIdx()
            for other in scene.labels:
                assert other is lab or not _boxes_overlap(lab.box, other.box), name
            for s in scene.strokes:
                if s.bond == parent_bond:
                    continue
                span = _box_interval((s.x1, s.y1), (s.x2, s.y2), lab.box)
                assert span is None or span[1] - span[0] < 1e-3, name


def test_moving_added_hydrogens_keeps_the_drawn_stereo():
    from rdkit.Chem.Draw import rdMolDraw2D as draw

    from molmanager.chem.depiction_builder import _SceneBuilder

    def perceived(prepared, positions) -> str:
        copy = Chem.Mol(prepared)
        conf = copy.GetConformer()
        for i, (x, y) in enumerate(positions):
            conf.SetAtomPosition(i, Point3D(x, y, 0.0))
        for atom in copy.GetAtoms():
            atom.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
        Chem.AssignChiralTypesFromBondDirs(copy, conf.GetId())
        Chem.AssignStereochemistry(copy, cleanIt=True, force=True)
        return Chem.MolToSmiles(Chem.RemoveHs(copy))

    checked = 0
    for index, mol in enumerate(Chem.SDMolSupplier(str(ROOT / "samples" / "fda_approved.sdf"))):
        if index >= 600:
            break
        if mol is None or scene_fallback_reason(mol):
            continue
        prepared = draw.PrepareMolForDrawing(mol)
        if prepared.GetNumAtoms() == mol.GetNumAtoms():
            continue
        conf = prepared.GetConformer()
        original = [
            (conf.GetAtomPosition(i).x, conf.GetAtomPosition(i).y)
            for i in range(len(conf.GetPositions()))
        ]
        moved = _SceneBuilder(prepared, first_added_atom=mol.GetNumAtoms()).pos
        assert perceived(prepared, moved) == perceived(prepared, original), index
        checked += 1
    assert checked > 50


def test_salt_fragments_are_slid_clear_of_each_other():
    for smiles in ("[NH4+].[Cl-]", "[Na+].[Na+].[O-]S(=O)(=O)[O-]", "CC(=O)[O-].[K+]"):
        scene = _scene(smiles)
        fragments = Chem.GetMolFrags(Chem.MolFromSmiles(smiles))
        fragment_of = {atom: k for k, atoms in enumerate(fragments) for atom in atoms}
        for i, first in enumerate(scene.labels):
            for second in scene.labels[i + 1 :]:
                if fragment_of[first.atom] == fragment_of[second.atom]:
                    continue
                a, b = first.box, second.box
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], smiles


def test_single_fragment_keeps_rdkit_coordinates():
    mol = Chem.MolFromSmiles("CCO")
    prepared = rdMolDraw2D.PrepareMolForDrawing(mol)
    expected = [tuple(prepared.GetConformer().GetAtomPosition(i))[:2] for i in range(3)]
    assert list(_scene("CCO").atoms) == pytest.approx(expected)


def test_stereo_bonds_become_wedges_or_hashes():
    scene = _scene("C[C@@H](C(=O)O)N")
    hashes = [s for s in scene.strokes if s.style == StrokeStyle.HASH]
    assert scene.fills or len(hashes) >= 4


def test_wedge_wide_end_meets_the_neighbouring_bond():
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles("OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O")
    scene, _reason = build_scene(mol)
    prepared = rdMolDraw2D.PrepareMolForDrawing(mol)
    met = 0
    for fill in scene.fills:
        bond = prepared.GetBondWithIdx(fill.bond)
        wide = bond.GetEndAtomIdx()
        here = scene.atoms[wide]
        for other in bond.GetEndAtom().GetNeighbors():
            if other.GetIdx() == bond.GetBeginAtomIdx():
                continue
            there = scene.atoms[other.GetIdx()]
            axis = (there[0] - here[0], there[1] - here[1])
            for x, y in fill.points:
                cross = axis[0] * (y - here[1]) - axis[1] * (x - here[0])
                met += abs(cross) < 1e-3
    assert met >= 1


def _lines_cross(first, second) -> bool:
    def side(s, x, y) -> float:
        return (s.x2 - s.x1) * (y - s.y1) - (s.y2 - s.y1) * (x - s.x1)

    return (
        side(first, second.x1, second.y1) * side(first, second.x2, second.y2) < 0
        and side(second, first.x1, first.y1) * side(second, first.x2, first.y2) < 0
    )


def _either_bond_lines(smiles: str, bond_index: int):
    mol = Chem.MolFromSmiles(smiles)
    mol.GetBondWithIdx(bond_index).SetStereo(Chem.BondStereo.STEREOANY)
    scene, _reason = build_scene(mol)
    return [s for s in scene.strokes if s.bond == bond_index]


def test_either_double_bond_is_crossed():
    lines = _either_bond_lines("CC=CC", 1)
    assert len(lines) == 2 and _lines_cross(*lines)


def test_either_flag_is_ignored_where_e_and_z_are_the_same():
    mol = Chem.MolFromSmiles("CC(C)OC(=O)C(C(=O)OC(C)C)=C1SC=CS1")
    ylidene = next(
        b.GetIdx()
        for b in mol.GetBonds()
        if b.GetBondType() == Chem.BondType.DOUBLE
        and b.GetBeginAtom().GetSymbol() == "C"
        and b.GetEndAtom().GetSymbol() == "C"
        and not b.IsInRing()
    )
    lines = _either_bond_lines("CC(C)OC(=O)C(C(=O)OC(C)C)=C1SC=CS1", ylidene)
    assert len(lines) == 2 and not _lines_cross(*lines)


@pytest.mark.parametrize(
    ("smiles", "reason"),
    [("[CH3]", "radical"), ("", "empty")],
)
def test_fallback_reasons(smiles, reason):
    mol = Chem.MolFromSmiles(smiles)
    assert scene_fallback_reason(mol) == reason
    assert build_scene(mol) == (None, reason)


def test_dative_bond_falls_back():
    mol = Chem.MolFromSmiles("N->[Pt]")
    assert scene_fallback_reason(mol) == "bond_dative"


def test_molfile_r_atom_is_drawn_as_its_label():
    block = """
  RDKit          2D

  2  1  0  0  0  0  0  0  0  0999 V2000
    0.0000    0.0000    0.0000 C   0  0  0  0  0  0  0  0  0  0  0  0
    1.5000    0.0000    0.0000 R   0  0  0  0  0  0  0  0  0  0  0  0
  1  2  1  0
M  END
"""
    mol = Chem.MolFromMolBlock(block)
    scene, reason = build_scene(mol)
    assert scene is not None, reason
    assert [_label_text(label) for label in scene.labels] == ["R"]


def test_builder_does_not_import_qt():
    code = (
        "import sys; import molmanager.chem.depiction_builder; "
        "sys.exit(any(m.startswith('PyQt5') for m in sys.modules))"
    )
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, check=False)
    assert result.returncode == 0


def test_painter_draws_a_scene(qapp):
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QImage, QPainter

    from molmanager.table.depiction_painter import light_palette, paint_scene

    image = QImage(210, 170, QImage.Format_ARGB32)
    image.fill(QColor(255, 255, 255))
    painter = QPainter(image)
    try:
        fit = paint_scene(
            painter, _scene("OC(=O)c1ccccc1"), QRectF(0, 0, 210, 170), light_palette()
        )
    finally:
        painter.end()
    assert fit.scale > 0
    inked = sum(
        image.pixelColor(x, y) != QColor(255, 255, 255)
        for x in range(0, 210, 3)
        for y in range(0, 170, 3)
    )
    red = sum(
        image.pixelColor(x, y).red() > 200 and image.pixelColor(x, y).green() < 80
        for x in range(210)
        for y in range(170)
    )
    assert inked > 50
    assert red > 10
