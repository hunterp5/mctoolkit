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

"""Sketcher writes a structure back to the table row it was opened from."""

from __future__ import annotations

from PyQt5.QtWidgets import QAction, QMenu, QMessageBox, QWidget
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.sketcher import SketcherDialog


def test_file_menu_has_no_update_table_entry(qapp):  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    try:
        names = [a.text() for a in dlg.findChildren(QAction)]
        assert "Update Table Entry" not in names
        assert "Export to Table" in names
    finally:
        dlg.close()


def _answer_close_prompt(monkeypatch, choice: QMessageBox.StandardButton) -> list[int]:
    asked: list[int] = []

    def question(*_args, **_kwargs):
        asked.append(choice)
        return choice

    monkeypatch.setattr(QMessageBox, "question", question)
    return asked


def _row_window() -> ChemistryWorkspaceWindow:
    w = ChemistryWorkspaceWindow()
    w.start_render_worker = lambda *_a, **_k: None
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.mols[0] = Chem.MolFromSmiles("CCN")
    w._table_model.append_row(0, {"SMILES": "CCN"})
    w.next_oid = 1
    return w


def test_closing_edit_sketcher_updates_the_row_after_yes(qapp, monkeypatch):  # noqa: ARG001
    asked = _answer_close_prompt(monkeypatch, QMessageBox.Yes)
    w = _row_window()
    dlg = SketcherDialog(w, source_oid=0, update_on_close=True)
    try:
        assert dlg.load_structure_from_mol(Chem.MolFromSmiles("OCC"), confirm_if_nonempty=False)
        dlg.close()
        assert asked == [QMessageBox.Yes]
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        assert w._table_model.value_for_header(0, "SMILES") == "CCO"
    finally:
        w.close()


def test_closing_edit_sketcher_can_keep_the_row_or_stay_open(qapp, monkeypatch):  # noqa: ARG001
    choice = {"value": QMessageBox.No}
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: choice["value"])
    w = _row_window()
    dlg = SketcherDialog(w, source_oid=0, update_on_close=True)
    try:
        assert dlg.load_structure_from_mol(Chem.MolFromSmiles("OCC"), confirm_if_nonempty=False)
        dlg.close()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        choice["value"] = QMessageBox.Cancel
        dlg = SketcherDialog(w, source_oid=0, update_on_close=True)
        assert dlg.load_structure_from_mol(Chem.MolFromSmiles("OCC"), confirm_if_nonempty=False)
        dlg.close()
        assert dlg._update_on_close
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        dlg._update_on_close = False
    finally:
        dlg.close()
        w.close()


def test_closing_sketcher_without_edit_flag_leaves_the_row(qapp):  # noqa: ARG001
    w = _row_window()
    dlg = SketcherDialog(w, source_oid=0)
    try:
        assert dlg.load_structure_from_mol(
            Chem.MolFromSmiles("c1ccccc1"), confirm_if_nonempty=False
        )
        dlg.close()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
    finally:
        w.close()


def test_closing_an_unchanged_sketch_does_not_record_undo(qapp):  # noqa: ARG001
    w = _row_window()
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w._table_model.set_cell_text(0, "SMILES", "CCO")
    dlg = SketcherDialog(w, source_oid=0, update_on_close=True)
    try:
        assert dlg.load_structure_from_mol(Chem.MolFromSmiles("CCO"), confirm_if_nonempty=False)
        before = w._undo_stack.count()
        dlg.close()
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        assert w._undo_stack.count() == before
    finally:
        w.close()


def test_structure_menu_edits_in_sketcher_under_paste(qapp, monkeypatch):  # noqa: ARG001
    w = _row_window()
    opened: dict = {}

    def fake_exec(menu, *_args, **_kwargs):
        opened["texts"] = [act.text() for act in menu.actions() if act.text()]
        return next(act for act in menu.actions() if act.text() == "Edit in Sketcher")

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
        texts = opened["texts"]
        assert texts[texts.index("Paste") + 1] == "Edit in Sketcher"
        assert opened["kwargs"] == {"source_oid": 0, "update_on_close": True}
        assert opened["mol"] is not None
    finally:
        w.close()
