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

"""Fused templates, clipboard interchange, abbreviations, reaction text, and Rn."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from PyQt5.QtWidgets import QApplication
from rdkit import Chem

from molmanager.ui.sketcher.bonds import _bond_make, _bond_unpack
from molmanager.ui.sketcher.widget import SketchWidget


def _click(widget: SketchWidget, pos: QPoint) -> None:
    """Move, press, and release the left button at *pos* in widget coordinates."""
    move = QMouseEvent(QEvent.MouseMove, pos, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    press = QMouseEvent(QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    release = QMouseEvent(
        QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    widget.mouseMoveEvent(move)
    widget.mousePressEvent(press)
    widget.mouseReleaseEvent(release)


def _bond_midpoint_widget(widget: SketchWidget, bond_index: int) -> QPoint:
    a_id, b_id, _order, _stereo = _bond_unpack(widget.bonds[bond_index])
    na = next(node for node in widget.nodes if node["id"] == a_id)
    nb = next(node for node in widget.nodes if node["id"] == b_id)
    mid = QPoint(
        (na["pos"].x() + nb["pos"].x()) // 2,
        (na["pos"].y() + nb["pos"].y()) // 2,
    )
    return widget._model_point_to_widget(mid)


def test_ring_template_click_on_bond_fuses(qapp) -> None:  # noqa: ARG001
    """A highlighted bond click fuses the active ring instead of editing that bond."""
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.place_template("Cyclohexyl", center=QPoint(200, 200))
    _a, _b, order, stereo = _bond_unpack(widget.bonds[0])
    widget.active_template = "Benzene"
    widget.active_bond_order = 2
    mid = _bond_midpoint_widget(widget, 0)
    move = QMouseEvent(QEvent.MouseMove, mid, Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    widget.mouseMoveEvent(move)
    assert widget.hover == ("bond", 0)
    _click(widget, mid)
    assert len(widget.nodes) == 10
    assert _bond_unpack(widget.bonds[0])[2:] == (order, stereo)


def test_ring_template_click_on_atom_attaches(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.place_template("Cyclohexyl", center=QPoint(200, 200))
    before = len(widget.nodes)
    widget.active_template = "Cyclopropane"
    atom = widget._model_point_to_widget(widget.nodes[0]["pos"])
    _click(widget, atom)
    assert len(widget.nodes) == before + 2


def test_bond_click_without_template_sets_order(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.place_template("Cyclohexyl", center=QPoint(200, 200))
    widget.active_template = None
    widget.active_bond_order = 2
    mid = _bond_midpoint_widget(widget, 0)
    _click(widget, mid)
    assert len(widget.nodes) == 6
    assert _bond_unpack(widget.bonds[0])[2] == 2


def test_naphthalene_fuses_onto_a_bond(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.nodes = [
        {"id": 0, "pos": QPoint(100, 200), "element": "C"},
        {"id": 1, "pos": QPoint(160, 200), "element": "C"},
    ]
    widget.bonds = [_bond_make(0, 1, 1, 0)]
    widget.next_id = 2
    widget.place_template("Naphthalene", fuse_bond=0)
    assert len(widget.nodes) == 10
    assert any(n["element"] == "C" for n in widget.nodes)
    widget.undo()
    assert len(widget.nodes) == 2


def test_indole_drop_places_the_fragment(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.place_template("Indole", center=QPoint(200, 200))
    symbols = sorted(n["element"] for n in widget.nodes)
    assert symbols.count("N") == 1
    assert symbols.count("C") == 8


def test_paste_smiles_and_copy_molblock(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    QApplication.clipboard().setText("CCO")
    assert widget.paste_from_clipboard(QPoint(180, 180))
    assert len(widget.nodes) == 3
    assert widget.copy_molblock_to_clipboard()
    block = QApplication.clipboard().text()
    assert "V2000" in block or "V3000" in block
    assert widget.copy_depiction_png_to_clipboard()
    assert QApplication.clipboard().image().isNull() is False


def test_r3_exports_atom_map(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 300)
    widget.nodes = [{"id": 0, "pos": QPoint(40, 40), "element": "C"}]
    widget.next_id = 1
    widget.place_rgroup_on(0, "R3")
    smiles = widget.to_smiles() or ""
    assert "[*:3]" in smiles
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    widget.load_from_rdkit_mol(mol)
    assert any(n["element"] == "R3" for n in widget.nodes)


def test_reaction_text_is_annotation_not_smarts(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.reaction_arrow = (QPoint(40, 80), QPoint(180, 80))
    widget.set_reaction_text("Pd/C", "H2")
    assert widget.reaction_annotation() == "Pd/C | H2"
    widget.undo()
    assert widget.reaction_annotation() == ""
    widget.redo()
    assert widget.reaction_above == "Pd/C"
    assert widget.reaction_below == "H2"


def test_contracted_group_replaces_one_atom(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 300)
    widget.nodes = [{"id": 0, "pos": QPoint(80, 80), "element": "C"}]
    widget.next_id = 1
    assert widget.arm_contracted_label("CF3")
    assert widget.armed_abbrev == "CF3"
    widget._apply_armed_abbrev(QPoint(80, 80))
    assert len(widget.nodes) == 1
    assert widget.nodes[0]["abbrev"] == "CF3"
    assert widget.armed_abbrev is None
