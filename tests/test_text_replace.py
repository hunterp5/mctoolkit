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

"""Cell find-and-replace, plus the table bar that writes those edits."""

from __future__ import annotations

from PyQt5.QtCore import QItemSelectionModel

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.text_replace import cell_matches, occurrence_count, replace_cell_text


def test_empty_find_is_a_no_op():
    assert occurrence_count("abc", "", case_sensitive=True, whole_cell=False) == 0
    assert replace_cell_text("abc", "", "x", case_sensitive=True, whole_cell=False) is None
    assert not cell_matches("abc", "", case_sensitive=False, whole_cell=True)


def test_substring_replaces_every_non_overlapping_hit():
    assert occurrence_count("ababa", "a", case_sensitive=True, whole_cell=False) == 3
    assert replace_cell_text("ababa", "a", "X", case_sensitive=True, whole_cell=False) == "XbXbX"
    assert replace_cell_text("aaa", "aa", "b", case_sensitive=True, whole_cell=False) == "ba"
    assert occurrence_count("aaa", "aa", case_sensitive=True, whole_cell=False) == 1


def test_empty_replacement_deletes_matches():
    assert replace_cell_text("ababa", "a", "", case_sensitive=True, whole_cell=False) == "bb"


def test_case_sensitive_and_insensitive():
    assert replace_cell_text("AbA", "a", "x", case_sensitive=True, whole_cell=False) is None
    assert occurrence_count("AbA", "a", case_sensitive=True, whole_cell=False) == 0
    assert replace_cell_text("AbA", "a", "x", case_sensitive=False, whole_cell=False) == "xbx"
    assert occurrence_count("AbA", "a", case_sensitive=False, whole_cell=False) == 2
    assert replace_cell_text("Foo", "foo", "foo", case_sensitive=False, whole_cell=False) == "foo"


def test_whole_cell_requires_the_entire_value():
    assert replace_cell_text("abc", "a", "z", case_sensitive=True, whole_cell=True) is None
    assert not cell_matches("abc", "a", case_sensitive=True, whole_cell=True)
    assert replace_cell_text("abc", "abc", "z", case_sensitive=True, whole_cell=True) == "z"
    assert replace_cell_text("Foo", "foo", "bar", case_sensitive=False, whole_cell=True) == "bar"
    assert replace_cell_text("foo", "foo", "foo", case_sensitive=True, whole_cell=True) is None
    assert occurrence_count("Foo", "foo", case_sensitive=False, whole_cell=True) == 1


def test_wildcards_replace_matching_spans():
    assert replace_cell_text(
        "an ethanol mix", "eth*l", "X", case_sensitive=True, whole_cell=False
    ) == ("an X mix")
    assert (
        replace_cell_text("an ethanol mix", "eth*", "X", case_sensitive=True, whole_cell=False)
        == "an X"
    )
    assert occurrence_count("abc adc", "a?c", case_sensitive=True, whole_cell=False) == 2
    assert replace_cell_text("abc adc", "a?c", "Z", case_sensitive=True, whole_cell=False) == "Z Z"
    assert replace_cell_text("abc", "*", "Z", case_sensitive=True, whole_cell=False) == "Z"
    assert occurrence_count("", "*", case_sensitive=True, whole_cell=False) == 0
    assert replace_cell_text("Ethanol", "eth*", "X", case_sensitive=False, whole_cell=False) == "X"
    assert replace_cell_text("ethanol", "eth*", "*", case_sensitive=True, whole_cell=False) == "*"
    assert (
        replace_cell_text("ethanol", "eth*", r"\1", case_sensitive=True, whole_cell=False) == r"\1"
    )
    assert (
        replace_cell_text("ethanol", "eth*", "ethanol", case_sensitive=True, whole_cell=False)
        is None
    )


def test_whole_cell_wildcards_use_the_entire_value():
    assert replace_cell_text("ethanol", "eth*", "X", case_sensitive=True, whole_cell=True) == "X"
    assert (
        replace_cell_text("an ethanol", "eth*", "X", case_sensitive=True, whole_cell=True) is None
    )
    assert replace_cell_text("Ethanol", "eth*", "X", case_sensitive=False, whole_cell=True) == "X"
    assert replace_cell_text("Ethanol", "eth*", "X", case_sensitive=True, whole_cell=True) is None
    assert occurrence_count("ab", "?", case_sensitive=True, whole_cell=True) == 0
    assert occurrence_count("a", "?", case_sensitive=True, whole_cell=True) == 1


def test_comparisons_replace_the_whole_cell():
    assert replace_cell_text("100", "10", "X", case_sensitive=True, whole_cell=False) == "X0"
    assert replace_cell_text("12", ">10", "high", case_sensitive=True, whole_cell=False) == "high"
    assert replace_cell_text("10", ">10", "high", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("10", ">=10", "high", case_sensitive=True, whole_cell=False) == "high"
    assert replace_cell_text(" 10 ", "=10", "high", case_sensitive=True, whole_cell=False) == "high"
    assert replace_cell_text("10.0", "=10", "high", case_sensitive=True, whole_cell=False) == "high"
    assert replace_cell_text("100", "=10", "high", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("11", "<>10", "high", case_sensitive=True, whole_cell=False) == "high"
    assert replace_cell_text("10.0", "!=10", "high", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("-1", "<0", "low", case_sensitive=True, whole_cell=False) == "low"
    assert replace_cell_text("-3", ">= -2", "low", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("12", ">10", "high", case_sensitive=True, whole_cell=True) == "high"
    assert replace_cell_text("15", ">10", "15", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("abc", ">abc", "Z", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text("2", ">1*", "Z", case_sensitive=True, whole_cell=False) is None
    assert replace_cell_text(">", ">", "Z", case_sensitive=True, whole_cell=False) == "Z"


def test_equality_and_empty_keywords():
    assert (
        replace_cell_text(" ethanol ", "=ethanol", "X", case_sensitive=True, whole_cell=False)
        == "X"
    )
    assert (
        replace_cell_text("Ethanol", "=ethanol", "X", case_sensitive=True, whole_cell=False) is None
    )
    assert (
        replace_cell_text("Ethanol", "=ethanol", "X", case_sensitive=False, whole_cell=False) == "X"
    )
    assert replace_cell_text("foo", "!=ethanol", "X", case_sensitive=False, whole_cell=False) == "X"
    assert (
        replace_cell_text("Ethanol", "!=ethanol", "X", case_sensitive=False, whole_cell=False)
        is None
    )
    assert cell_matches("", "empty", case_sensitive=True, whole_cell=False)
    assert cell_matches("  ", "blank", case_sensitive=True, whole_cell=False)
    assert not cell_matches("0", "is:empty", case_sensitive=True, whole_cell=False)
    assert cell_matches("0", "not empty", case_sensitive=True, whole_cell=False)
    assert not cell_matches("  ", "!empty", case_sensitive=True, whole_cell=False)
    assert replace_cell_text("empty", "=empty", "X", case_sensitive=True, whole_cell=False) == "X"
    assert replace_cell_text("empty", "*empty*", "X", case_sensitive=True, whole_cell=False) == "X"
    assert replace_cell_text("", "empty", "X", case_sensitive=True, whole_cell=False) == "X"
    assert replace_cell_text("note", "notempty", "X", case_sensitive=False, whole_cell=False) == "X"


def test_unchanged_text_is_skipped_and_regex_metacharacters_stay_literal():
    assert cell_matches("cat", "a", case_sensitive=True, whole_cell=False)
    assert replace_cell_text("cat", "a", "a", case_sensitive=True, whole_cell=False) is None
    assert (
        replace_cell_text("a.b-aXb", "a.b", "Z", case_sensitive=True, whole_cell=False) == "Z-aXb"
    )
    assert replace_cell_text("a", "a", r"\1", case_sensitive=True, whole_cell=False) == r"\1"


def _load_notes(window: ChemistryWorkspaceWindow) -> int:
    window.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "CC", "Note": "alpha"})
    window._table_model.append_row(1, {"SMILES": "C", "Note": "beta"})
    window.next_oid = 2
    return window.headers.index("Note")


def _select_source_cell(window: ChemistryWorkspaceWindow, row: int, col: int) -> None:
    source = window._table_model.index(row, col)
    proxy = window._filter_proxy_model
    index = proxy.mapFromSource(source) if window.table.model() is proxy else source
    selection = window.table.selectionModel()
    assert selection is not None and index.isValid()
    selection.setCurrentIndex(index, QItemSelectionModel.ClearAndSelect)


def test_find_next_walks_and_wraps(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window.open_find_replace_with_column(note)
    window._find_replace_bar.find_edit.setText("a")

    window.find_replace_find_next()
    assert window._source_cell_from_view_index(window.table.currentIndex()) == (0, note)
    assert "Match in Note" in window.status_label.text()

    window.find_replace_find_next()
    assert window._source_cell_from_view_index(window.table.currentIndex()) == (1, note)

    window.find_replace_find_next()
    assert window._source_cell_from_view_index(window.table.currentIndex()) == (0, note)
    assert "Wrapped" in window.status_label.text()


def test_replace_all_undo_and_selection_scope(qapp, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window.open_find_replace_with_column(note)
    bar = window._find_replace_bar
    bar.find_edit.setText("a")
    bar.replace_edit.setText("Z")
    monkeypatch.setattr(window, "_confirm_replace_all", lambda *_args: False)
    window.find_replace_replace_all()
    assert window._table_model.cell_text(0, note) == "alpha"
    assert "cancelled" in window.status_label.text()

    monkeypatch.setattr(window, "_confirm_replace_all", lambda *_args: True)
    window.find_replace_replace_all()
    assert window._table_model.cell_text(0, note) == "ZlphZ"
    assert window._table_model.cell_text(1, note) == "betZ"
    assert window._table_model.cell_text(0, window.headers.index("SMILES")) == "CC"

    window._undo_stack.undo()
    assert window._table_model.cell_text(0, note) == "alpha"
    assert window._table_model.cell_text(1, note) == "beta"
    assert "restored" in window.status_label.text()

    window._undo_stack.redo()
    assert window._table_model.cell_text(0, note) == "ZlphZ"
    window._undo_stack.undo()

    scope = bar.scope_combo.findData("selection")
    assert scope >= 0
    bar.scope_combo.setCurrentIndex(scope)
    _select_source_cell(window, 0, note)
    window.find_replace_replace_all()
    assert window._table_model.cell_text(0, note) == "ZlphZ"
    assert window._table_model.cell_text(1, note) == "beta"
    window._undo_stack.undo()
    assert window._table_model.cell_text(0, note) == "alpha"


def test_replace_current_cell_then_moves(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window.open_find_replace_with_column(note)
    bar = window._find_replace_bar
    bar.find_edit.setText("a")
    bar.replace_edit.setText("Z")
    _select_source_cell(window, 0, note)
    window.find_replace_replace()
    assert window._table_model.cell_text(0, note) == "ZlphZ"
    assert window._table_model.cell_text(1, note) == "beta"
    assert window._source_cell_from_view_index(window.table.currentIndex()) == (1, note)


def test_structure_column_is_not_editable_and_header_menu_offers_replace(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window.open_find_replace_with_column(1)
    assert not window._find_replace_panel.isHidden()
    assert "cannot be edited" in window.status_label.text()
    labels = [
        window._find_replace_bar.column_combo.itemText(i)
        for i in range(window._find_replace_bar.column_combo.count())
    ]
    assert "Structure" not in labels
    assert "Note" in labels
    assert window._find_replace_bar.column_combo.currentData() == "all"

    window.open_find_replace_with_column(note)
    assert window._find_replace_bar.column_combo.currentData() == note
    menu = window._create_header_context_menu(note)
    assert menu is not None
    assert any(action.objectName() == "header_find_replace" for action in menu.actions())


def test_replace_all_comparison_and_wildcard(qapp, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window._table_model.set_cell_text_at(0, note, "12")
    window._table_model.set_cell_text_at(1, note, "ethanol")
    window.open_find_replace_with_column(note)
    bar = window._find_replace_bar
    bar.find_edit.setText(">5")
    bar.replace_edit.setText("high")
    monkeypatch.setattr(window, "_confirm_replace_all", lambda *_args: True)
    window.find_replace_replace_all()
    assert window._table_model.cell_text(0, note) == "high"
    assert window._table_model.cell_text(1, note) == "ethanol"

    window._undo_stack.undo()
    bar.find_edit.setText("eth*")
    bar.replace_edit.setText("X")
    window.find_replace_replace_all()
    assert window._table_model.cell_text(0, note) == "12"
    assert window._table_model.cell_text(1, note) == "X"


def test_empty_find_and_no_match_status(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    note = _load_notes(window)
    window.toggle_find_replace_panel()
    window.find_replace_find_next()
    assert "enter text to find" in window.status_label.text()
    window._find_replace_bar.find_edit.setText("zzz")
    window._find_replace_bar.column_combo.setCurrentIndex(
        window._find_replace_bar.column_combo.findData(note)
    )
    window.find_replace_find_next()
    assert "no matches" in window.status_label.text()
