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

"""Undo/redo and extended bond types for the sketcher."""

from __future__ import annotations

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QWidget

from molmanager.ui.sketcher.bonds import (
    BOND_STEREO_DATIVE,
    BOND_STEREO_WAVY,
    _bond_make,
    _bond_unpack,
)
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.widget import SketchWidget


def test_clear_is_undoable(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(40, 40), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 1, 0)]
    w.next_id = 3
    w.clear()
    assert w.nodes == []
    assert w.bonds == []
    w.undo()
    assert len(w.nodes) == 2
    assert len(w.bonds) == 1
    w.redo()
    assert w.nodes == []


def test_undo_removes_newly_placed_atom_and_bond(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [{"id": 1, "pos": QPoint(40, 40), "element": "C"}]
    w.next_id = 2
    node = {"id": 2, "pos": QPoint(100, 40), "element": "C"}
    bond = _bond_make(1, 2, 1, 0)
    w.nodes.append(node)
    w.bonds.append(bond)
    w._push_undo("add_bonded_node", (node, bond))
    w.undo()
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 1
    assert w.bonds == []
    w.redo()
    assert len(w.nodes) == 2
    assert len(w.bonds) == 1


def test_undo_template_placement_is_atomic(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.place_template("Benzene", center=QPoint(200, 200))
    assert len(w.nodes) == 6
    assert len(w.bonds) == 6
    assert len(w._undo) == 1
    w.undo()
    assert w.nodes == []
    assert w.bonds == []
    w.redo()
    assert len(w.nodes) == 6
    assert len(w.bonds) == 6


def test_undo_fused_template_is_atomic(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.place_template("Cyclohexyl", center=QPoint(200, 200))
    n0, b0 = len(w.nodes), len(w.bonds)
    w.place_template("Benzene", fuse_bond=0)
    assert len(w.nodes) > n0
    assert len(w._undo) == 2
    w.undo()
    assert len(w.nodes) == n0
    assert len(w.bonds) == b0
    w.undo()
    assert w.nodes == []
    w.redo()
    assert len(w.nodes) == n0


def test_undo_attached_template_is_atomic(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [{"id": 1, "pos": QPoint(40, 40), "element": "C"}]
    w.next_id = 2
    w.place_template("Cyclopropane", attach_to=1)
    assert len(w.nodes) == 3
    assert len(w.bonds) == 3
    assert len(w._undo) == 1
    w.undo()
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 1
    assert w.bonds == []


def test_file_menu_undo_redo_actions(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QMenuBar

    dlg = SketcherDialog(QWidget())
    w = dlg.canvas
    w.nodes = [{"id": 1, "pos": QPoint(10, 10), "element": "C"}]
    w.next_id = 2
    w.clear()
    assert not w.nodes
    dlg._undo_sketch()
    assert len(w.nodes) == 1
    dlg._redo_sketch()
    assert not w.nodes
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    menus = [a.text().replace("&", "") for a in mb.actions()]
    assert "Edit" in menus
    assert "File" in menus
    assert "Tools" not in menus
    assert "Elements" not in menus
    dlg.close()


def test_wavy_and_dative_bond_tools(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    assert dlg.bond_wavy is not None
    assert dlg.bond_dative is not None
    assert dlg.bond_double is not None
    assert dlg.bond_triple is not None
    dlg._on_bond_tool(1, BOND_STEREO_WAVY)
    assert dlg.canvas.active_bond_stereo == BOND_STEREO_WAVY
    assert dlg.canvas.active_bond_order == 1
    dlg._on_bond_tool(2, 0)
    assert dlg.canvas.active_bond_order == 2
    assert dlg.canvas.active_bond_stereo == 0
    dlg.close()


def test_dative_roundtrip_rdkit(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(40, 40), "element": "N"},
        {"id": 2, "pos": QPoint(100, 40), "element": "B"},
    ]
    w.bonds = [_bond_make(1, 2, 1, BOND_STEREO_DATIVE)]
    w.next_id = 3
    mol = w._mol_from_node_ids({1, 2})
    assert mol is not None
    b = mol.GetBondWithIdx(0)
    from rdkit import Chem

    assert b.GetBondType() == Chem.BondType.DATIVE


def test_wavy_bond_dir_export(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(40, 40), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 1, BOND_STEREO_WAVY)]
    mol = w._mol_from_node_ids({1, 2})
    assert mol is not None
    from rdkit.Chem.rdchem import BondDir

    assert mol.GetBondWithIdx(0).GetBondDir() == BondDir.UNKNOWN
    assert _bond_unpack(w.bonds[0])[3] == BOND_STEREO_WAVY
