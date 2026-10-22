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

"""The Structure column shows and resolves the molecule store's one molecule per row."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QKeyEvent, QPixmap
from PyQt5.QtWidgets import QLineEdit, QPlainTextEdit
from rdkit import Chem

from molmanager.ui.compound_table_model import STRUCTURE_COLUMN_PENDING_HINT, CompoundTableModel
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.workers.load_render import _mol_ingest_item
from molmanager.workers.session_rows_parse import parse_session_rows

MOL_BLOCK = Chem.MolToMolBlock(Chem.MolFromSmiles("CCO"))


def _structure_cell(model: CompoundTableModel, row: int, role: int):
    return model.data(model.index(row, CompoundTableModel.STRUCTURE_COL), role)


def test_undrawn_structure_cell_shows_store_text(qapp):  # noqa: ARG001
    model = CompoundTableModel([])
    model.set_headers(["ID_HIDDEN", "Structure", "Name"])
    for oid in range(3):
        model.append_row(oid, {"Name": str(oid)})
    texts = {0: "CCO", 1: MOL_BLOCK, 2: ""}
    model.set_structure_text_source(texts.get)

    assert _structure_cell(model, 0, Qt.DisplayRole) == "CCO"
    assert _structure_cell(model, 0, Qt.ToolTipRole) == "CCO"
    assert model.cell_text(0, CompoundTableModel.STRUCTURE_COL) == "CCO"
    assert _structure_cell(model, 1, Qt.DisplayRole) == STRUCTURE_COLUMN_PENDING_HINT
    assert _structure_cell(model, 1, Qt.ToolTipRole) == MOL_BLOCK.strip()
    assert _structure_cell(model, 2, Qt.DisplayRole) == STRUCTURE_COLUMN_PENDING_HINT


def _window(headers: list[str]) -> ChemistryWorkspaceWindow:
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", *headers]
    w._table_model.set_headers(list(w.headers))
    return w


def _ingest(w: ChemistryWorkspaceWindow, items: list) -> list[tuple[int, dict[str, str]]]:
    new_rows: list[tuple[int, dict[str, str]]] = []
    w._ingest_append_batch_items(items, new_rows)
    w._table_model.append_rows_batch(new_rows)
    return new_rows


def test_text_first_ingest_fills_store(qapp):  # noqa: ARG001
    w = _window(["SMILES", "Name"])
    try:
        rows = _ingest(w, [{"SMILES": "OCC", "Name": "ethanol"}])
        oid = rows[0][0]
        assert w._structure_text_for_oid(oid) == "OCC"
        assert Chem.MolToSmiles(w.mols[oid]) == "CCO"
        assert _structure_cell(w._table_model, 0, Qt.DisplayRole) == "OCC"
        assert w._mol_for_structure_row(0) is not None
    finally:
        w.close()


def test_chosen_structure_column_writes_store_and_keeps_cells(qapp):  # noqa: ARG001
    w = _window(["SMILES", "Alt"])
    w._ingest_structure_field = "Alt"
    try:
        cells = [{"SMILES": "CCO", "Alt": "c1ccccc1"}, {"SMILES": "CCN", "Alt": ""}]
        rows = _ingest(w, [dict(c) for c in cells])
        assert [r[1] for r in rows] == cells
        assert w._structure_text_for_oid(rows[0][0]) == "c1ccccc1"
        assert w._structure_text_for_oid(rows[1][0]) == "CCN"
    finally:
        w.close()


def test_chosen_structure_column_keeps_structure_file_fields(qapp):  # noqa: ARG001
    mol = Chem.MolFromSmiles("CCO")
    mol.SetProp("Alt", "c1ccccc1")
    mol.SetProp("Name", "ethanol")
    w = _window(["Alt", "Name"])
    w._ingest_structure_field = "Alt"
    try:
        rows = _ingest(w, [_mol_ingest_item(mol, ["Alt", "Name"])])
        oid, cells = rows[0]
        assert cells == {"Alt": "c1ccccc1", "Name": "ethanol"}
        assert w._structure_text_for_oid(oid) == "c1ccccc1"
    finally:
        w.close()


def test_structure_file_ingest_stores_canonical_smiles(qapp):  # noqa: ARG001
    mol = Chem.MolFromSmiles("OCC")
    mol.SetProp("SMILES", "not the structure")
    w = _window(["SMILES"])
    try:
        rows = _ingest(w, [_mol_ingest_item(mol, ["SMILES"])])
        assert w._structure_text_for_oid(rows[0][0]) == "CCO"
        assert rows[0][1]["SMILES"] == "not the structure"
    finally:
        w.close()


def test_legacy_session_override_migrates_into_store():
    rows = [
        {"id": 0, "cells": {"SMILES": "CCO", "Alt": "c1ccccc1"}},
        {"id": 1, "cells": {"SMILES": "CCN", "Alt": ""}},
    ]
    result = parse_session_rows(rows, ["SMILES", "Alt"], ["CCO", "CCN"], [], "Alt")
    assert result.mol_jobs == [(0, None, "c1ccccc1"), (1, None, "CCN")]


def test_structure_editor_reads_smiles_behind_a_picture(qapp):  # noqa: ARG001
    model = CompoundTableModel([])
    model.set_headers(["ID_HIDDEN", "Structure"])
    model.append_row(0, {})
    model.set_structure_text_source(lambda _oid: "CCO")
    picture = QPixmap(8, 8)
    picture.fill()
    model.set_structure_pixmap(0, picture)
    assert _structure_cell(model, 0, Qt.DisplayRole) == ""
    assert _structure_cell(model, 0, Qt.EditRole) == "CCO"
    assert model.flags(model.index(0, 1)) & Qt.ItemIsEditable
    model.set_structure_text_source(lambda _oid: MOL_BLOCK)
    assert _structure_cell(model, 0, Qt.EditRole) == ""


def test_typed_structure_text_replaces_the_row_and_undoes(qapp):  # noqa: ARG001
    w = _window(["SMILES"])
    w.start_render_worker = lambda *_a, **_k: None
    try:
        w.mols[0] = Chem.MolFromSmiles("CCN")
        w._table_model.append_row(0, {"SMILES": "CCN"})
        w.next_oid = 1
        assert w.commit_structure_text_edit(0, "OCC")
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        assert w._table_model.value_for_header(0, "SMILES") == "CCO"
        assert w._undo_stack.undoText() == "Edit structure"
        w._undo_stack.undo()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
        before = w._undo_stack.count()
        assert w.commit_structure_text_edit(0, "CCN")
        assert w._undo_stack.count() == before
        assert not w.commit_structure_text_edit(0, "")
        assert not w.commit_structure_text_edit(0, "not-a-structure")
        assert "Could not read" in w.status_label.text()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
    finally:
        w.close()


def test_edit_structure_button_opens_a_dialog(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.ui.main_window import table_edit_mixin

    w = _window(["SMILES"])
    w.start_render_worker = lambda *_a, **_k: None
    w.mols[0] = Chem.MolFromSmiles("CCN")
    w._table_model.append_row(0, {"SMILES": "CCN"})
    w.next_oid = 1
    seen: dict[str, str] = {}

    def fake_dialog(_parent, text: str):
        seen["text"] = text
        return "OCC", True

    monkeypatch.setattr(table_edit_mixin, "ask_edit_structure_text", fake_dialog)
    try:
        w.edit_structure_cell(0)
        assert seen["text"] == "CCN"
        assert Chem.MolToSmiles(w.mols[0]) == "CCO"
        w._undo_stack.undo()
        assert Chem.MolToSmiles(w.mols[0]) == "CCN"
    finally:
        w.close()


def test_edit_structure_dialog_stays_compact(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.edit_structure import EditStructureDialog

    smiles = EditStructureDialog(None, "CCN")
    block = EditStructureDialog(None, "CCO\n  RDKit\n\n  2  1  0  0  0  0  0  0  0  0999 V2000\n")
    try:
        smiles.show()
        block.show()
        qapp.processEvents()
        assert isinstance(smiles._editor, QLineEdit)
        assert smiles.width() <= 380
        assert smiles.height() <= 140
        assert isinstance(block._editor, QPlainTextEdit)
        assert block.width() == smiles.width()
        assert block.height() <= 220
        assert block.height() > smiles.height()
    finally:
        smiles.close()
        block.close()


def test_typing_opens_the_structure_editor_and_delete_does_not(qapp):  # noqa: ARG001
    w = _window(["SMILES"])
    try:
        w.mols[0] = Chem.MolFromSmiles("CCO")
        w._table_model.append_row(0, {"SMILES": "CCO"})
        w.show()
        qapp.processEvents()
        view = w.table.model().mapFromSource(w._table_model.index(0, 1))
        w.table.setCurrentIndex(view)
        w.table.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Delete, Qt.NoModifier))
        assert w.table.findChild(QLineEdit) is None
        w.table.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_C, Qt.NoModifier, "c"))
        qapp.processEvents()
        editor = w.table.findChild(QLineEdit)
        assert editor is not None
        assert editor.placeholderText() == "SMILES or InChI"
    finally:
        w.close()
