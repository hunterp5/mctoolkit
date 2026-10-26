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

"""Sketcher delete-key behavior."""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QKeyEvent, QKeySequence
from PyQt5.QtWidgets import QAction, QMenuBar, QWidget

from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.widget import SketchWidget


class _FakeParent(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._hotkey_actions = {
            "edit.delete_selection": QAction("Delete Selection"),
        }


def _add_two_atom_sketch(w: SketchWidget) -> tuple[int, int]:
    w.nodes = [
        {"id": 1, "pos": QPoint(100, 100), "element": "C"},
        {"id": 2, "pos": QPoint(160, 100), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 1, 0)]
    w.next_id = 3
    w.hover = 1
    return 1, 2


def test_delete_key_removes_hovered_atom_in_draw_mode(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.select_mode = False
    w.erase_mode = False
    _add_two_atom_sketch(w)
    w.hover = 1
    assert w._try_delete_hover_target(refresh_hover=False)
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 2


def test_handle_delete_key_prefers_hover_over_selection(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.select_mode = True
    _add_two_atom_sketch(w)
    w.selected_nodes = [2]
    w.hover = 1
    assert w._try_delete_hover_target(refresh_hover=False)
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 2


def test_handle_delete_key_deletes_selection_without_hover(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.select_mode = True
    _add_two_atom_sketch(w)
    w.selected_nodes = [2]
    w.hover = None
    assert w._handle_delete_key()
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 1


def test_delete_key_removes_hovered_bond(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w.nodes = [
        {"id": 1, "pos": QPoint(100, 100), "element": "C"},
        {"id": 2, "pos": QPoint(160, 100), "element": "C"},
        {"id": 3, "pos": QPoint(220, 100), "element": "C"},
    ]
    w.bonds = [_bond_make(1, 2, 1, 0), _bond_make(2, 3, 1, 0)]
    w.next_id = 4
    w.hover = ("bond", 0)
    assert w._try_delete_hover_target(refresh_hover=False)
    assert len(w.bonds) == 1
    assert w.bonds[0][:2] == (2, 3)


def test_sketcher_dialog_blocks_parent_delete_action(qapp) -> None:  # noqa: ARG001
    parent = _FakeParent()
    act = parent._hotkey_actions["edit.delete_selection"]
    act.setEnabled(True)
    dlg = SketcherDialog(parent)
    dlg.show()
    qapp.processEvents()
    assert act.isEnabled() is False
    dlg.hide()
    qapp.processEvents()
    assert act.isEnabled() is True


def test_sketcher_dialog_event_filter_deletes_hovered_atom(qapp) -> None:  # noqa: ARG001
    parent = _FakeParent()
    dlg = SketcherDialog(parent)
    dlg.show()
    qapp.processEvents()
    w = dlg.canvas
    _add_two_atom_sketch(w)
    w.hover = 1
    ev = QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier)
    assert dlg.eventFilter(w, ev) is True
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 2
    dlg.close()
    qapp.processEvents()


def test_sketcher_edit_menu_has_copy_paste_delete(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    assert dlg._act_edit_copy.text() == "&Copy"
    assert dlg._act_edit_paste.text() == "&Paste"
    assert dlg._act_edit_delete.text() == "Delete &Selection"
    assert dlg._act_edit_copy.shortcut() == QKeySequence.Copy
    assert dlg._act_edit_paste.shortcut() == QKeySequence.Paste
    assert dlg._act_edit_delete.shortcut() == QKeySequence.Delete
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    edit = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Edit")
    labels = [a.text().replace("&", "") for a in edit.actions() if not a.isSeparator()]
    assert labels[:5] == ["Undo", "Redo", "Copy", "Paste", "Delete Selection"]
    dlg.close()


def test_sketcher_edit_delete_action_removes_selection(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    w = dlg.canvas
    _add_two_atom_sketch(w)
    w.select_mode = True
    w.selected_nodes = [1]
    w.hover = None
    w._refresh_hover_from_cursor = lambda: None
    dlg._act_edit_delete.trigger()
    assert len(w.nodes) == 1
    assert w.nodes[0]["id"] == 2
    dlg.close()


def test_status_bar_reports_select_delete_copy_and_undo(qapp) -> None:
    dlg = SketcherDialog(QWidget())
    messages: list[str] = []
    dlg.canvas.statusMessage.connect(messages.append)
    w = dlg.canvas
    _add_two_atom_sketch(w)
    w.select_mode = True
    w.selected_nodes = [1, 2]
    w._sync_selected_bonds_from_nodes()
    w._announce_selection()
    assert messages[-1] == "Selected 2 atoms and 1 bond."
    w.hover = 1
    w._refresh_hover_from_cursor = lambda: None
    assert w._handle_delete_key()
    assert messages[-1] == "Deleted 1 atom."
    w.selected_nodes = [2]
    assert w.copy_selection_to_clipboard()
    assert messages[-1] == "Copied 1 atom."
    w.undo()
    assert messages[-1] == "Undone."
    assert any(node["id"] == 1 for node in w.nodes)
    dlg.close()
