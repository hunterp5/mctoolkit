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

"""Terminal CF3, OMe, Boc and Ph abbreviations in depiction scenes."""

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


def _texts(scene) -> list[str]:
    return ["".join(piece.text for piece in label.pieces) for label in scene.labels]


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
    assert all(label.role != 9 for label in short.labels)
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


def test_abbreviations_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    texts = _texts(_scene("FC(F)(F)C"))
    assert texts.count("F") == 3
    assert "CF3" not in texts and "F3C" not in texts


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


def test_abbreviation_toggle_changes_the_scene_revision(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "0")
    off = scene_revision()
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_ABBREVIATIONS", "1")
    on = scene_revision()
    assert on != off
    assert on - off == 8
