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

"""Sketcher Add to Table and Update Table Entry."""

from __future__ import annotations

from PyQt5.QtWidgets import QMenu, QMenuBar, QMessageBox, QWidget
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.sketcher import SketcherDialog


def _file_labels(dialog: SketcherDialog) -> list[str]:
    bar = dialog.findChild(QMenuBar)
    file_menu = next(action.menu() for action in bar.actions() if action.text() == "File")
    file_menu.aboutToShow.emit()
    return [action.text() for action in file_menu.actions() if action.isVisible() and action.text()]


def test_file_menu_update_entry_follows_the_source_row(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    blank = SketcherDialog(QWidget())
    opened = SketcherDialog(QWidget(), source_oid=3)
    try:
        assert _file_labels(blank) == ["Save Sketch…", "Add to Table"]
        assert "Update Table Entry" not in _file_labels(blank)
        assert _file_labels(opened) == ["Save Sketch…", "Add to Table", "Update Table Entry"]
        opened.set_source_entry(None)
        assert "Update Table Entry" not in _file_labels(opened)
    finally:
        blank.close()
        opened.close()


def _accept_close(monkeypatch) -> None:
    monkeypatch.setattr(
        SketcherDialog,
        "_ask_close",
        lambda _self: QMessageBox.Yes,
    )


def _accept_table_write(monkeypatch, asked: list[tuple[str, str]] | None = None) -> None:
    def confirm(_self, title: str, message: str) -> bool:
        if asked is not None:
            asked.append((title, message))
        return True

    monkeypatch.setattr(SketcherDialog, "_confirm_table_write", confirm)


def _row_window() -> ChemistryWorkspaceWindow:
    w = ChemistryWorkspaceWindow()
    w.start_render_worker = lambda *_a, **_k: None
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.mols[0] = Chem.MolFromSmiles("CCN")
    w._table_model.append_row(0, {"SMILES": "CCN"})
    w.next_oid = 1
    return w


def _sketch(window: ChemistryWorkspaceWindow, smiles: str, *, source_oid: int | None = 0):
    dlg = SketcherDialog(window, source_oid=source_oid)
    assert dlg.load_structure_from_mol(Chem.MolFromSmiles(smiles), confirm_if_nonempty=False)
    return dlg


def test_update_table_entry_replaces_the_source_row(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    asked: list[tuple[str, str]] = []
    _accept_table_write(monkeypatch, asked)
    w = _row_window()
    dlg = _sketch(w, "OCC")
    try:
        dlg._update_table_entry()
        assert asked == [("Update Table Entry", "Update this table entry with the sketch?")]
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        assert w._table_model.value_for_header(0, "SMILES") == "CCO"
        assert 1 not in w.mols
    finally:
        dlg.close()
        w.close()


def test_add_to_table_appends_a_row(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    asked: list[tuple[str, str]] = []
    _accept_table_write(monkeypatch, asked)
    w = _row_window()
    dlg = _sketch(w, "OCC")
    try:
        dlg._add_to_table()
        assert asked == [("Add to Table", "Add this sketch to the table as new rows?")]
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        assert Chem.MolToSmiles(w.mols[1]) == "CCO"
    finally:
        dlg.close()
        w.close()


def test_closing_sketcher_asks_and_leaves_the_row(qapp, monkeypatch):  # noqa: ARG001
    w = _row_window()
    dlg = _sketch(w, "c1ccccc1")
    dlg.show()
    qapp.processEvents()
    asked: list[str] = []

    def refuse_close(_self) -> int:
        asked.append("close")
        return QMessageBox.No

    monkeypatch.setattr(SketcherDialog, "_ask_close", refuse_close)
    try:
        assert dlg.close() is False
        assert dlg.isVisible()
        assert asked == ["close"]
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        monkeypatch.setattr(SketcherDialog, "_ask_close", lambda _self: QMessageBox.Yes)
        assert dlg.close() is True
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
    finally:
        w.close()


def test_declining_table_write_leaves_the_rows(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    monkeypatch.setattr(SketcherDialog, "_confirm_table_write", lambda *_args, **_kwargs: False)
    w = _row_window()
    dlg = _sketch(w, "OCC")
    try:
        dlg._add_to_table()
        dlg._update_table_entry()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        assert 1 not in w.mols
    finally:
        dlg.close()
        w.close()


def test_updating_an_unchanged_sketch_does_not_record_undo(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    _accept_table_write(monkeypatch)
    w = _row_window()
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w._table_model.set_cell_text(0, "SMILES", "CCO")
    dlg = _sketch(w, "CCO")
    try:
        before = w._undo_stack.count()
        dlg._update_table_entry()
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        assert w._undo_stack.count() == before
        assert w.status_label.text() == "That table row already has this structure."
    finally:
        dlg.close()
        w.close()


def test_export_without_a_source_row_adds_a_row(qapp, monkeypatch):  # noqa: ARG001
    _accept_close(monkeypatch)
    _accept_table_write(monkeypatch)
    w = _row_window()
    dlg = _sketch(w, "OCC", source_oid=None)
    try:
        dlg._add_to_table()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        assert Chem.MolToSmiles(w.mols[1]) == "CCO"
    finally:
        dlg.close()
        w.close()


def test_structure_menu_groups_open_copy_and_browser(qapp, monkeypatch):  # noqa: ARG001
    w = _row_window()
    opened: dict = {}

    def fake_exec(menu, *_args, **_kwargs):
        opened["texts"] = [act.text() for act in menu.actions() if act.text()]
        return next(act for act in menu.actions() if act.text() == "Open in Sketcher")

    def capture_open(mol=None, **kwargs):
        opened["mol"] = mol
        opened["kwargs"] = kwargs

    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    w.open_sketcher = capture_open
    try:
        w.show()
        qapp.processEvents()
        proxy = w.table.model()
        src = w._table_model.index(0, 1)
        rect = w.table.visualRect(proxy.mapFromSource(src))
        w.show_table_menu(rect.center())
        assert opened["texts"] == [
            "Open in Sketcher",
            "Open in Design Studio",
            "Copy",
            "Paste",
            "Browser…",
        ]
        assert opened["kwargs"] == {"source_oid": 0}
        assert opened["mol"] is not None
    finally:
        w.close()
