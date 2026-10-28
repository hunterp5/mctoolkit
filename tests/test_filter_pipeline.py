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

"""Filter pipeline: numeric range, text, substructure (sync + async), and invalid SMARTS."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.widgets import (
    CategoryFilterCard,
    FilterCard,
    SubstructureFilterCard,
    TextFilterCard,
)


def _setup_two_row_mw_table(w: ChemistryWorkspaceWindow) -> FilterCard:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "50"})
    w.mols[0] = Chem.MolFromSmiles("C")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 5.0, 25.0)
    w.filters = [card]
    return card


def _src_row_visible(w: ChemistryWorkspaceWindow, source_row: int) -> bool:
    """Proxy-aware visibility check for tests."""
    return w._is_source_row_visible(source_row)


def test_numeric_range_filter_hides_rows_with_no_value(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "0"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "5"})
    w._table_model.append_row(2, {"SMILES": "CCC", "MW": ""})
    w._table_model.append_row(3, {"SMILES": "CCCC", "MW": "n/a"})
    for i, smi in enumerate(("C", "CC", "CCC", "CCCC")):
        w.mols[i] = Chem.MolFromSmiles(smi)
    w.next_oid = 4
    w.calculate_global_bounds()
    w._rebuild_sqlite_store_from_model()
    w._sqlite_store_dirty = False
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 0.0, 5.0)
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is True
    assert _src_row_visible(w, 2) is False
    assert _src_row_visible(w, 3) is False


def test_numeric_range_filter_hides_row_outside_bounds(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False


def test_text_filter_partial_substring(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane lot"})
    w._table_model.append_row(1, {"SMILES": "C", "Note": "argon cylinder"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = TextFilterCard(["SMILES", "Note"], w)
    card.set_column("Note")
    # Partial match on "eth" — present in row 0 only (avoid "methane" which contains "eth" / "ethan").
    card.text_edit.setText("eth")
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False


def test_inverted_text_filter_hides_blank_cells(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane lot"})
    w._table_model.append_row(1, {"SMILES": "C", "Note": ""})
    w._table_model.append_row(2, {"SMILES": "CCC", "Note": "argon cylinder"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.mols[2] = Chem.MolFromSmiles("CCC")
    w.next_oid = 3
    w.calculate_global_bounds()
    card = TextFilterCard(["SMILES", "Note"], w)
    card.set_column("Note")
    card.text_edit.setText("eth")
    card.restore_filter_flags(True, True)
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is False
    assert _src_row_visible(w, 1) is False
    assert _src_row_visible(w, 2) is True


def test_text_filter_enable_btn_highlighted_when_on(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.calculate_global_bounds()
    card = TextFilterCard(["SMILES"], w)
    assert card.filter_enabled() is True
    assert card.enable_btn.property("fcActive") is True


def test_category_filter_enable_btn_highlighted_when_on(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    w._table_model.set_headers(list(w.headers))
    w.calculate_global_bounds()
    card = CategoryFilterCard(["SMILES", "Phase"], w)
    assert card.filter_enabled() is True
    assert card.enable_btn.property("fcActive") is True


def test_category_filter_defaults_to_all_selected(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Phase": "prep"})
    w._table_model.append_row(1, {"SMILES": "C", "Phase": "ship"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = CategoryFilterCard(["SMILES", "Phase"], w)
    card.set_column("Phase")
    assert card.checked_values() == frozenset({"prep", "ship"})
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is True


def test_category_filter_all_button_selects_every_value(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Phase": "prep"})
    w._table_model.append_row(1, {"SMILES": "C", "Phase": "ship"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = CategoryFilterCard(["SMILES", "Phase"], w)
    card.set_column("Phase")
    card._select_all_categories()
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is True


def test_category_filter_hides_rows_with_no_value(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Phase": "prep"})
    w._table_model.append_row(1, {"SMILES": "C", "Phase": ""})
    w._table_model.append_row(2, {"SMILES": "CCC", "Phase": "ship"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.mols[2] = Chem.MolFromSmiles("CCC")
    w.next_oid = 3
    w.calculate_global_bounds()
    card = CategoryFilterCard(["SMILES", "Phase"], w)
    card.set_column("Phase")
    assert "" not in card.checked_values()
    labels = {card.list_widget.item(i).text() for i in range(card.list_widget.count())}
    assert "(blank)" not in labels
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False
    assert _src_row_visible(w, 2) is True
    card.restore_filter_flags(True, True)
    card.restore_from_session("Phase", ["prep"])
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is False
    assert _src_row_visible(w, 1) is False
    assert _src_row_visible(w, 2) is True


def test_category_filter_only_checked_values_visible(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Phase": "prep"})
    w._table_model.append_row(1, {"SMILES": "C", "Phase": "ship"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = CategoryFilterCard(["SMILES", "Phase"], w)
    card.restore_from_session("Phase", ["prep"])
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False


def test_substructure_sync_benzene_smarts_hides_non_aromatic(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "c1ccccc1"})
    w._table_model.append_row(1, {"SMILES": "CC"})
    w.mols[0] = Chem.MolFromSmiles("c1ccccc1")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = SubstructureFilterCard()
    card.set_smarts("c1ccccc1")
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False


def test_inverted_substructure_filter_hides_rows_with_no_structure(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "c1ccccc1"})
    w._table_model.append_row(1, {"SMILES": ""})
    w._table_model.append_row(2, {"SMILES": "CC"})
    w.mols[0] = Chem.MolFromSmiles("c1ccccc1")
    w.mols[2] = Chem.MolFromSmiles("CC")
    w.next_oid = 3
    w.calculate_global_bounds()
    card = SubstructureFilterCard()
    card.set_smarts("c1ccccc1")
    card.restore_filter_flags(True, True)
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert _src_row_visible(w, 0) is False
    assert _src_row_visible(w, 1) is False
    assert _src_row_visible(w, 2) is True


def test_substructure_invalid_smarts_sets_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.calculate_global_bounds()
    card = SubstructureFilterCard()
    card.set_smarts("not_valid_smarts_{{{")
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert "invalid" in w.status_label.text().lower()


def test_async_sqlite_filter_apply_hides_rows(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    monkeypatch.setenv("MOLMANAGER_FILTER_ASYNC_MIN_ROWS", "2")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    for i, mw in enumerate(("10", "50", "30")):
        w._table_model.append_row(i, {"SMILES": "C" * (i + 1), "MW": mw})
        w.mols[i] = Chem.MolFromSmiles("C" * (i + 1))
    w.next_oid = 3
    w.calculate_global_bounds()
    w._rebuild_sqlite_store_from_model()
    w._sqlite_store_dirty = False
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 5.0, 25.0)
    w.filters = [card]
    w._apply_filters_impl()
    assert w.threadpool.waitForDone(120_000)
    qapp.processEvents()
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False
    assert _src_row_visible(w, 2) is False


def test_substructure_async_handoff_hides_rows(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setenv("MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS", "64")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    for i in range(70):
        smi = "c1ccccc1" if i == 0 else "CC"
        w._table_model.append_row(i, {"SMILES": smi})
        w.mols[i] = Chem.MolFromSmiles(smi)
    w.next_oid = 70
    w.calculate_global_bounds()
    card = SubstructureFilterCard()
    card.set_smarts("c1ccccc1")
    w.filters = [card]
    w.apply_filters()
    assert w.threadpool.waitForDone(120_000)
    qapp.processEvents()
    assert _src_row_visible(w, 0) is True
    for r in range(1, 70):
        assert _src_row_visible(w, r) is False


def test_substructure_async_without_smiles_column_uses_mols(qapp, monkeypatch):  # noqa: ARG001
    """Async path must match via in-memory mols when no SMILES column exists (e.g. SDF)."""
    monkeypatch.setenv("MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS", "64")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "Name"]
    w._table_model.set_headers(list(w.headers))
    for i in range(70):
        smi = "c1ccccc1" if i == 0 else "CC"
        w._table_model.append_row(i, {"Name": f"mol{i}"})
        w.mols[i] = Chem.MolFromSmiles(smi)
    w.next_oid = 70
    w.calculate_global_bounds()
    targets = w._substructure_filter_targets()
    assert len(targets) == 70
    assert isinstance(targets[0][1], bytes)
    card = SubstructureFilterCard()
    card.set_smarts("c1ccccc1")
    w.filters = [card]
    w.apply_filters()
    assert w.threadpool.waitForDone(120_000)
    qapp.processEvents()
    assert _src_row_visible(w, 0) is True
    for r in range(1, 70):
        assert _src_row_visible(w, r) is False


def test_substructure_async_multi_card_handoff(qapp, monkeypatch):  # noqa: ARG001
    """Two SMARTS cards at async scale must finish off-thread without GUI match_mol."""
    monkeypatch.setenv("MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS", "64")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    for i in range(70):
        if i == 0:
            smi = "c1ccccc1O"  # phenol — matches benzene and oxygen
        elif i == 1:
            smi = "CCO"  # alcohol only
        else:
            smi = "CCCC"
        w._table_model.append_row(i, {"SMILES": smi})
        w.mols[i] = Chem.MolFromSmiles(smi)
    w.next_oid = 70
    w.calculate_global_bounds()
    a = SubstructureFilterCard()
    a.set_smarts("c1ccccc1")
    b = SubstructureFilterCard()
    b.set_smarts("O")
    w.filters = [a, b]
    w._apply_filters_impl()
    assert w.threadpool.waitForDone(120_000)
    qapp.processEvents()
    assert _src_row_visible(w, 0) is True
    assert _src_row_visible(w, 1) is False
    for r in range(2, 70):
        assert _src_row_visible(w, r) is False


def test_reorder_filter_card_updates_list_and_layout(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QVBoxLayout

    from molmanager.ui.filters.cards import FilterCardsHost, filter_card_drop_index

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w.calculate_global_bounds()
    host = FilterCardsHost(on_reorder=w.reorder_filter_card)
    layout = QVBoxLayout(host)
    w._filter_cards_host = host
    w.f_container = layout
    a = FilterCard(["MW"], w, initial_property="MW")
    b = TextFilterCard(["SMILES"], w)
    c = SubstructureFilterCard()
    for card in (a, b, c):
        layout.addWidget(card)
    w.filters = [a, b, c]

    w.reorder_filter_card(a, 2)
    assert w.filters == [b, c, a]
    assert layout.itemAt(0).widget() is b
    assert layout.itemAt(1).widget() is c
    assert layout.itemAt(2).widget() is a

    # Drop index: y above first other card mid -> 0
    b.setGeometry(0, 0, 100, 40)
    c.setGeometry(0, 50, 100, 40)
    a.setGeometry(0, 100, 100, 40)
    assert filter_card_drop_index(host, 10, a) == 0
    assert filter_card_drop_index(host, 55, a) == 1
    assert filter_card_drop_index(host, 200, a) == 2


def test_filter_card_default_titles_and_rename(qapp):  # noqa: ARG001
    from molmanager.ui.filters.cards import next_default_filter_title

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w.calculate_global_bounds()

    assert next_default_filter_title([], TextFilterCard) == "Text"
    assert next_default_filter_title([TextFilterCard(["SMILES"], w)], TextFilterCard) == "Text 2"

    a = TextFilterCard(["SMILES"], w)
    a.set_filter_title(next_default_filter_title([], TextFilterCard))
    b = TextFilterCard(["SMILES"], w)
    b.set_filter_title(next_default_filter_title([a], TextFilterCard))
    assert a.filter_title() == "Text"
    assert b.filter_title() == "Text 2"
    a.set_filter_title("My text filter")
    assert a.filter_title() == "My text filter"

    s = FilterCard(["MW"], w, initial_property="MW")
    s.set_filter_title(next_default_filter_title([], FilterCard))
    assert s.filter_title() == "Slider"
