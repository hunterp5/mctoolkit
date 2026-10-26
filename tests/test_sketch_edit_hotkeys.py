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

"""Sketch edit keys win while the sketcher window is active, and the table keeps them otherwise."""

from __future__ import annotations

from PyQt5.QtCore import QPoint, Qt
from PyQt5.QtGui import QKeySequence
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QAction, QLineEdit, QVBoxLayout, QWidget

from molmanager.ui.sketcher.dialog import SketcherDialog


class _EditHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.undo_count = 0
        self.redo_count = 0
        undo = QAction("Undo", self)
        undo.setShortcut(QKeySequence("Ctrl+Z"))
        undo.setShortcutContext(Qt.ApplicationShortcut)
        undo.triggered.connect(self._count_undo)
        redo = QAction("Redo", self)
        redo.setShortcuts([QKeySequence("Ctrl+Y"), QKeySequence("Ctrl+Shift+Z")])
        redo.setShortcutContext(Qt.ApplicationShortcut)
        redo.triggered.connect(self._count_redo)
        delete = QAction("Delete Selection", self)
        delete.setShortcut(QKeySequence("Del"))
        delete.setShortcutContext(Qt.ApplicationShortcut)
        copy = QAction("Copy", self)
        copy.setShortcut(QKeySequence.Copy)
        copy.setShortcutContext(Qt.ApplicationShortcut)
        paste = QAction("Paste", self)
        paste.setShortcut(QKeySequence.Paste)
        paste.setShortcutContext(Qt.ApplicationShortcut)
        filter_panel = QAction("Toggle Filter Panel", self)
        filter_panel.setShortcut(QKeySequence("Ctrl+Shift+L"))
        filter_panel.setShortcutContext(Qt.ApplicationShortcut)
        for action in (undo, redo, delete, copy, paste, filter_panel):
            self.addAction(action)
        self._hotkey_actions = {
            "edit.undo": undo,
            "edit.redo": redo,
            "edit.copy": copy,
            "edit.paste": paste,
            "edit.delete_selection": delete,
            "tools.toggle_filter_panel": filter_panel,
        }
        self.undo = undo

    def _count_undo(self) -> None:
        self.undo_count += 1

    def _count_redo(self) -> None:
        self.redo_count += 1


def _activate(widget: QWidget, qapp) -> None:
    widget.show()
    widget.activateWindow()
    widget.raise_()
    qapp.processEvents()


def _push_carbon(dlg: SketcherDialog) -> None:
    node = {"id": dlg.canvas.next_id, "pos": QPoint(80, 80), "element": "C"}
    dlg.canvas.next_id += 1
    dlg.canvas.nodes.append(node)
    dlg.canvas._push_undo("add_node", node)


def test_active_sketcher_takes_edit_keys_and_releases_them(qapp) -> None:
    host = _EditHost()
    dlg = SketcherDialog(host)
    other = QWidget()
    _activate(other, qapp)
    _activate(dlg, qapp)
    assert dlg.isActiveWindow()
    for action in host._hotkey_actions.values():
        assert action.isEnabled() is False

    _activate(other, qapp)
    assert dlg.isActiveWindow() is False
    for action in host._hotkey_actions.values():
        assert action.isEnabled() is True

    _activate(dlg, qapp)
    assert host.undo.isEnabled() is False
    dlg.hide()
    qapp.processEvents()
    assert host.undo.isEnabled() is True
    other.close()
    dlg.close()
    qapp.processEvents()


def test_ctrl_z_and_ctrl_y_edit_the_sketch_not_the_table(qapp) -> None:
    host = _EditHost()
    dlg = SketcherDialog(host)
    _activate(dlg, qapp)
    dlg.canvas.setFocus()
    qapp.processEvents()
    _push_carbon(dlg)
    assert len(dlg.canvas.nodes) == 1

    QTest.keyClick(dlg.canvas, Qt.Key_Z, Qt.ControlModifier)
    qapp.processEvents()
    assert dlg.canvas.nodes == []
    assert host.undo_count == 0

    QTest.keyClick(dlg.canvas, Qt.Key_Y, Qt.ControlModifier)
    qapp.processEvents()
    assert len(dlg.canvas.nodes) == 1
    assert host.redo_count == 0

    QTest.keyClick(dlg.canvas, Qt.Key_Z, Qt.ControlModifier)
    qapp.processEvents()
    assert dlg.canvas.nodes == []
    QTest.keyClick(dlg.canvas, Qt.Key_Z, Qt.ControlModifier | Qt.ShiftModifier)
    qapp.processEvents()
    assert len(dlg.canvas.nodes) == 1
    assert host.undo_count == 0
    assert host.redo_count == 0
    dlg.close()
    qapp.processEvents()


def test_embedded_sketcher_owns_edit_keys_only_while_focused(qapp) -> None:
    host = _EditHost()
    dlg = SketcherDialog(host, app=host)
    dlg.set_embedded(True)
    other = QLineEdit(host)
    layout = QVBoxLayout(host)
    layout.addWidget(dlg)
    layout.addWidget(other)
    _activate(host, qapp)
    dlg.canvas.setFocus()
    qapp.processEvents()
    assert host.undo.isEnabled() is False

    other.setFocus()
    qapp.processEvents()
    assert host.undo.isEnabled() is True

    dlg.canvas.setFocus()
    qapp.processEvents()
    assert host.undo.isEnabled() is False
    host.close()
    qapp.processEvents()
