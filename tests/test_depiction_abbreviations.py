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

"""Terminal CF3, CN, N3, CO2H, SO3H, PO3H2, OMe, Boc and Ph abbreviations in depiction scenes."""

from __future__ import annotations

import pytest
from rdkit import Chem
from rdkit.Geometry import Point3D

from molmanager.chem.depiction_builder import build_scene, scene_revision
from molmanager.chem.depiction_layout import LayoutOptions

_FIXED = LayoutOptions(
    macrocycle_coordgen=False, flip_inward_substituents=False, rotate_to_cell=False
)


def _scene(smiles: str, *, layout: LayoutOptions | None = None):
    mol = Chem.MolFromSmiles(smiles)
    if layout is not None:
        conf = Chem.Conformer(mol.GetNumAtoms())
        mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, layout)
    assert scene is not None, reason
    return scene


def _label_text(label) -> str:
    return "".join(piece.text for piece in label.pieces)


def _texts(scene) -> list[str]:
    return [_label_text(label) for label in scene.labels]


def test_benzene_stays_a_ring(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    scene = _scene("c1ccccc1")
    assert "Ph" not in _texts(scene)
    assert len(scene.strokes) == 9


def test_trifluoromethyl_and_phenyl_contract(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("FC(F)(F)c1ccccc1")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("FC(F)(F)c1ccccc1")
    texts = set(_texts(short))
    assert texts == {"CF3", "Ph"} or texts == {"F3C", "Ph"}
    cf3 = next(label for label in short.labels if _label_text(label) in {"CF3", "F3C"})
    phenyl = next(label for label in short.labels if _label_text(label) == "Ph")
    assert cf3.role == 9
    assert phenyl.role == 6
    assert len(short.strokes) < len(full.strokes)
    # Covered fluorines sit on the CF3 carbon, so a highlight lands on the label.
    assert short.atoms[0] == pytest.approx(short.atoms[1])
    assert short.atoms[2] == pytest.approx(short.atoms[1])
    assert short.atoms[3] == pytest.approx(short.atoms[1])


def test_methoxy_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("COc1ccccc1")
    conf = Chem.Conformer(mol.GetNumAtoms())
    points = [
        (-1.5, 0.0),
        (0.0, 0.0),
        (1.5, 0.0),
        (2.25, 1.3),
        (3.75, 1.3),
        (4.5, 0.0),
        (3.75, -1.3),
        (2.25, -1.3),
    ]
    for index, (x, y) in enumerate(points):
        conf.SetAtomPosition(index, Point3D(x, y, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    oxygen = next(label for label in scene.labels if label.atom == 1)
    assert "".join(piece.text for piece in oxygen.pieces) == "MeO"
    assert scene.atoms[2][0] > scene.atoms[1][0]
    assert scene.atoms[0] == pytest.approx(scene.atoms[1])


def test_boc_on_nitrogen_contracts_with_phenyl(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("CC(C)(C)OC(=O)Nc1ccccc1")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("CC(C)(C)OC(=O)Nc1ccccc1")
    texts = set(_texts(short))
    assert "Boc" in texts
    assert "Ph" in texts
    assert "NH" in texts or "HN" in texts
    assert len(short.strokes) < len(full.strokes) // 2


def test_tert_butyl_ester_is_not_boc(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    assert "Boc" not in _texts(_scene("CC(=O)OC(C)(C)C"))


def test_disubstituted_ring_stays_drawn(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    scene = _scene("CC(=O)Oc1ccccc1C(=O)O")
    assert "Ph" not in _texts(scene)
    assert len(scene.strokes) > 6


def test_nitrile_contracts_in_nitrogen_blue(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("c1ccccc1C#N")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("c1ccccc1C#N")
    texts = set(_texts(short))
    assert texts == {"Ph", "CN"} or texts == {"Ph", "NC"}
    nitrile = next(label for label in short.labels if _label_text(label) in {"CN", "NC"})
    assert nitrile.role == 7
    assert len(short.strokes) < len(full.strokes)
    # SMILES c1ccccc1C#N: the nitrile nitrogen is the last atom and sits on its carbon.
    nitrogen = short.atoms[-1]
    assert nitrogen == pytest.approx(short.atoms[nitrile.atom])


def test_nitrile_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("CC#N")
    conf = Chem.Conformer(mol.GetNumAtoms())
    # Methyl on the right of the nitrile carbon, so the label reads NC.
    for index, (x, y) in enumerate(((1.5, 0.0), (0.0, 0.0), (-1.5, 0.0))):
        conf.SetAtomPosition(index, Point3D(x, y, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    nitrile = next(label for label in scene.labels if label.atom == 1)
    assert _label_text(nitrile) == "NC"
    assert nitrile.role == 7


def test_azide_contracts_in_nitrogen_blue(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("CN=[N+]=[N-]")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("CN=[N+]=[N-]")
    texts = set(_texts(short))
    assert texts == {"N3"} or texts == {"3N"}
    azide = short.labels[0]
    assert azide.role == 7
    assert len(short.strokes) < len(full.strokes)
    assert short.atoms[2] == pytest.approx(short.atoms[1])
    assert short.atoms[3] == pytest.approx(short.atoms[1])


def test_azide_resonance_form_contracts(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    scene = _scene("C[N-]-[N+]#N")
    assert set(_texts(scene)) == {"N3"} or set(_texts(scene)) == {"3N"}
    assert scene.labels[0].role == 7
    assert scene.atoms[2] == pytest.approx(scene.atoms[1])
    assert scene.atoms[3] == pytest.approx(scene.atoms[1])


def test_azide_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("CN=[N+]=[N-]")
    conf = Chem.Conformer(mol.GetNumAtoms())
    for index, (x, y) in enumerate(((1.5, 0.0), (0.0, 0.0), (-1.2, 0.0), (-2.4, 0.0))):
        conf.SetAtomPosition(index, Point3D(x, y, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    azide = next(label for label in scene.labels if label.atom == 1)
    assert _label_text(azide) == "3N"
    assert azide.role == 7


def test_carboxylic_acid_contracts_in_oxygen_red(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("CC(=O)O")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("CC(=O)O")
    texts = set(_texts(short))
    assert texts == {"CO2H"} or texts == {"HO2C"}
    acid = short.labels[0]
    assert acid.role == 8
    assert len(short.strokes) < len(full.strokes)
    assert short.atoms[2] == pytest.approx(short.atoms[1])
    assert short.atoms[3] == pytest.approx(short.atoms[1])


def test_carboxylic_acid_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("CC(=O)O")
    conf = Chem.Conformer(mol.GetNumAtoms())
    for index, (x, y) in enumerate(((1.5, 0.0), (0.0, 0.0), (-1.2, 0.8), (-1.2, -0.8))):
        conf.SetAtomPosition(index, Point3D(x, y, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    acid = next(label for label in scene.labels if label.atom == 1)
    assert _label_text(acid) == "HO2C"
    assert acid.role == 8


def test_ester_carboxylate_and_formic_acid_stay_drawn(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    for smiles in ("CC(=O)OC", "CC(=O)[O-]", "C(=O)O"):
        texts = _texts(_scene(smiles))
        assert "CO2H" not in texts
        assert "HO2C" not in texts


def test_phenyl_azide_and_benzoic_acid_contract_both_groups(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    azide = set(_texts(_scene("c1ccccc1N=[N+]=[N-]")))
    assert "Ph" in azide
    assert "N3" in azide or "3N" in azide
    acid = set(_texts(_scene("c1ccccc1C(=O)O")))
    assert "Ph" in acid
    assert "CO2H" in acid or "HO2C" in acid


def test_isocyanide_is_not_a_nitrile_abbreviation(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    assert "CN" not in _texts(_scene("C[N+]#[C-]"))
    assert "NC" not in _texts(_scene("C[N+]#[C-]"))


def test_abbreviations_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    texts = _texts(_scene("FC(F)(F)C"))
    assert texts.count("F") == 3
    assert "CF3" not in texts and "F3C" not in texts


def test_sulfonic_acid_contracts_in_sulfur_yellow(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("CS(=O)(=O)O")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("CS(=O)(=O)O")
    texts = set(_texts(short))
    assert texts == {"SO3H"} or texts == {"HO3S"}
    acid = short.labels[0]
    assert acid.role == 16
    assert len(short.strokes) < len(full.strokes)
    sulfur = acid.atom
    oxygens = [
        atom.GetIdx()
        for atom in Chem.MolFromSmiles("CS(=O)(=O)O").GetAtoms()
        if atom.GetAtomicNum() == 8
    ]
    for atom in oxygens:
        assert short.atoms[atom] == pytest.approx(short.atoms[sulfur])


def test_sulfonic_acid_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("CS(=O)(=O)O")
    sulfur = next(atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() == 16)
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(sulfur, Point3D(0.0, 0.0, 0.0))
    left = 0
    for atom in mol.GetAtoms():
        if atom.GetIdx() == sulfur:
            continue
        if atom.GetAtomicNum() == 6:
            conf.SetAtomPosition(atom.GetIdx(), Point3D(1.6, 0.0, 0.0))
        else:
            left += 1
            conf.SetAtomPosition(atom.GetIdx(), Point3D(-1.2, (left - 2) * 0.8, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    label = next(item for item in scene.labels if item.atom == sulfur)
    assert _label_text(label) == "HO3S"
    assert label.role == 16


def test_sulfonate_and_sulfonate_ester_stay_drawn(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    for smiles in ("CS(=O)(=O)[O-]", "CS(=O)(=O)OC", "CS(=O)(=O)N"):
        texts = _texts(_scene(smiles))
        assert "SO3H" not in texts
        assert "HO3S" not in texts


def test_phosphonic_acid_contracts_in_phosphorus_orange(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    full = _scene("CP(=O)(O)O")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    short = _scene("CP(=O)(O)O")
    texts = set(_texts(short))
    assert texts == {"PO3H2"} or texts == {"H2O3P"}
    acid = short.labels[0]
    assert acid.role == 15
    assert len(short.strokes) < len(full.strokes)
    phosphorus = acid.atom
    oxygens = [
        atom.GetIdx()
        for atom in Chem.MolFromSmiles("CP(=O)(O)O").GetAtoms()
        if atom.GetAtomicNum() == 8
    ]
    for atom in oxygens:
        assert short.atoms[atom] == pytest.approx(short.atoms[phosphorus])


def test_phosphonic_acid_reverses_when_the_bond_comes_from_the_right(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    mol = Chem.MolFromSmiles("CP(=O)(O)O")
    phosphorus = next(atom.GetIdx() for atom in mol.GetAtoms() if atom.GetAtomicNum() == 15)
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(phosphorus, Point3D(0.0, 0.0, 0.0))
    left = 0
    for atom in mol.GetAtoms():
        if atom.GetIdx() == phosphorus:
            continue
        if atom.GetAtomicNum() == 6:
            conf.SetAtomPosition(atom.GetIdx(), Point3D(1.6, 0.0, 0.0))
        else:
            left += 1
            conf.SetAtomPosition(atom.GetIdx(), Point3D(-1.2, (left - 2) * 0.8, 0.0))
    mol.AddConformer(conf, assignId=True)
    scene, reason = build_scene(mol, _FIXED)
    assert scene is not None, reason
    label = next(item for item in scene.labels if item.atom == phosphorus)
    assert _label_text(label) == "H2O3P"
    assert label.role == 15


def test_phosphonate_ester_and_phosphoric_acid_stay_drawn(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    for smiles in ("CP(=O)(OC)OC", "O=P(O)(O)O", "CP(O)(=O)C"):
        texts = _texts(_scene(smiles))
        assert "PO3H2" not in texts
        assert "H2O3P" not in texts


def test_phenyl_sulfonic_and_phosphonic_acids_contract_both_groups(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    sulfonic = set(_texts(_scene("c1ccccc1S(=O)(=O)O")))
    assert "Ph" in sulfonic
    assert "SO3H" in sulfonic or "HO3S" in sulfonic
    phosphonic = set(_texts(_scene("c1ccccc1P(=O)(O)O")))
    assert "Ph" in phosphonic
    assert "PO3H2" in phosphonic or "H2O3P" in phosphonic


def test_abbreviated_scenes_paint(qapp, monkeypatch) -> None:
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QImage, QPainter

    from molmanager.table.depiction_painter import light_palette, paint_scene

    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    for smiles in (
        "FC(F)(F)c1ccccc1",
        "COc1ccccc1",
        "CC(C)(C)OC(=O)Nc1ccccc1",
        "c1ccccc1",
        "CC(=O)Oc1ccccc1C(=O)O",
        "CC#N",
        "CC(F)(F)F",
        "CN=[N+]=[N-]",
        "C[N-]-[N+]#N",
        "CC(=O)O",
        "c1ccccc1C(=O)O",
        "CS(=O)(=O)O",
        "CP(=O)(O)O",
    ):
        image = QImage(210, 170, QImage.Format_ARGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        try:
            fit = paint_scene(painter, _scene(smiles), QRectF(0, 0, 210, 170), light_palette())
        finally:
            painter.end()
        assert fit.scale > 0
        inked = sum(
            image.pixelColor(x, y) != QColor(255, 255, 255)
            for x in range(0, 210, 4)
            for y in range(0, 170, 4)
        )
        assert inked > 15


def test_abbreviation_colours(qapp, monkeypatch) -> None:
    from PyQt5.QtCore import QRectF
    from PyQt5.QtGui import QColor, QImage, QPainter

    from molmanager.table.depiction_painter import light_palette, paint_scene

    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")

    def coloured(smiles: str, match) -> int:
        image = QImage(210, 170, QImage.Format_ARGB32)
        image.fill(QColor(255, 255, 255))
        painter = QPainter(image)
        try:
            paint_scene(painter, _scene(smiles), QRectF(0, 0, 210, 170), light_palette())
        finally:
            painter.end()
        return sum(
            match(image.pixelColor(x, y)) for x in range(0, 210, 2) for y in range(0, 170, 2)
        )

    blue = coloured("CC#N", lambda c: c.blue() > 200 and c.red() < 40 and c.green() < 40)
    fluorine = coloured("CC(F)(F)F", lambda c: c.green() > 150 and c.blue() > 150 and c.red() < 100)
    azide = coloured("CN=[N+]=[N-]", lambda c: c.blue() > 200 and c.red() < 40 and c.green() < 40)
    acid = coloured("CC(=O)O", lambda c: c.red() > 200 and c.green() < 40 and c.blue() < 40)
    sulfur = coloured("CS(=O)(=O)O", lambda c: c.red() > 150 and c.green() > 150 and c.blue() < 40)
    phosphorus = coloured(
        "CP(=O)(O)O", lambda c: c.red() > 200 and 80 < c.green() < 180 and c.blue() < 40
    )
    assert blue > 15
    assert fluorine > 15
    assert azide > 15
    assert acid > 15
    assert sulfur > 15
    assert phosphorus > 15


def test_abbreviation_toggle_changes_the_scene_revision(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    off = scene_revision()
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    on = scene_revision()
    assert on != off
    assert on - off == 8
