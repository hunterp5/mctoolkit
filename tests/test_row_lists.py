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

"""Named row lists: store, dialogs, menu, and session round-trip."""

from __future__ import annotations

import pytest
from PyQt5.QtWidgets import QDialog, QMessageBox
from rdkit import Chem

from molmanager.ui.dialogs.row_lists import AddSelectedToListDialog, ManageListsDialog
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.row_lists import RowListStore


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def test_row_list_store_unions_and_serializes():
    store = RowListStore()
    created, n_new = store.add("  Actives  ", [2, 0, 2])
    assert created is True
    assert n_new == 2
    assert store.oids("Actives") == [0, 2]

    created, n_new = store.add("Actives", [2, 1])
    assert created is False
    assert n_new == 1
    assert store.oids("Actives") == [0, 1, 2]
    assert store.to_session() == [{"name": "Actives", "oids": [0, 1, 2]}]
    assert store.to_session(keep_oids={0}) == [{"name": "Actives", "oids": [0]}]
    assert store.to_session(keep_oids={9}) == []

    assert store.retain(["missing"]) == ["Actives"]
    assert store.names() == []


def test_row_list_store_loads_session_payload():
    store = RowListStore()
    store.load_session(
        [
            {"name": "A", "oids": [1, "2", 1, "nope"]},
            {"name": "A", "oids": [9]},
            "skip",
            {"name": "  ", "oids": [1]},
            {"name": "B", "oids": []},
        ]
    )
    assert store.names() == ["A", "B"]
    assert store.oids("A") == [1, 2]
    assert store.oids("B") == []


def test_add_selected_dialog_requires_a_name(qapp):  # noqa: ARG001
    dlg = AddSelectedToListDialog(None, existing_names=["Actives"])
    assert not dlg._ok_btn.isEnabled()
    dlg.name_combo.setCurrentText("   ")
    assert not dlg._ok_btn.isEnabled()
    dlg._accept_name()
    assert dlg.result() != QDialog.Accepted

    dlg.name_combo.setCurrentText("  Leads  ")
    assert dlg._ok_btn.isEnabled()
    dlg._accept_name()
    assert dlg.result() == QDialog.Accepted
    assert dlg.list_name() == "Leads"


def test_manage_lists_dialog_delete_keeps_the_rest(qapp):  # noqa: ARG001
    dlg = ManageListsDialog(None, entries=[("Actives", 2), ("Leads", 1)])
    dlg._list.setCurrentRow(0)
    dlg._delete_selected()
    assert dlg.remaining_names() == ["Leads"]
    assert not dlg._delete_btn.isEnabled()


def _seed_rows(window: ChemistryWorkspaceWindow) -> None:
    window.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "C"})
    window._table_model.append_row(1, {"SMILES": "CC"})
    window._table_model.append_row(2, {"SMILES": "CCO"})
    window.mols[0] = Chem.MolFromSmiles("C")
    window.mols[1] = Chem.MolFromSmiles("CC")
    window.mols[2] = Chem.MolFromSmiles("CCO")
    window.next_oid = 3


def _menu_labels(window: ChemistryWorkspaceWindow) -> list[str]:
    labels: list[str] = []
    for act in window._lists_menu.actions():
        if act.isSeparator():
            labels.append("")
            continue
        data = act.data()
        labels.append(data if isinstance(data, str) and data else act.text().replace("&", ""))
    return labels


def test_lists_menu_is_under_data_below_table(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    labels = [act.text().replace("&", "") for act in window.menuBar().actions() if act.text()]
    assert "Lists" not in labels
    assert labels[labels.index("Data") + 1] == "Settings"
    lists = window._lists_menu
    data = lists.parent()
    assert data.title().replace("&", "") == "Data"
    data_labels = [act.text().replace("&", "") for act in data.actions() if act.text()]
    assert data_labels.index("Lists") == data_labels.index("Table") + 1
    assert _menu_labels(window) == ["Add Selected to List…", "", "Manage Lists…"]
    window.close()


def test_add_selected_without_rows_does_not_create_a_list(qapp, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    _seed_rows(window)
    seen: dict[str, str] = {}

    def _info(*args, **kwargs):  # noqa: ARG001
        seen["title"] = str(args[1]) if len(args) > 1 else ""
        return QMessageBox.Ok

    monkeypatch.setattr(
        "molmanager.ui.main_window.row_lists_mixin.QMessageBox.information",
        _info,
    )
    window.add_selected_to_list()
    assert seen["title"] == "Add Selected to List"
    assert window._row_list_store().names() == []
    window.close()


def test_named_list_selects_rows_and_can_be_deleted(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    _seed_rows(window)
    window.select_table_oids({0, 2})
    qapp.processEvents()

    assert window.commit_named_row_list("Actives", window._selected_oids_set()) is True
    assert _menu_labels(window) == [
        "Add Selected to List…",
        "Actives",
        "",
        "Manage Lists…",
    ]

    window.select_table_oids({1})
    qapp.processEvents()
    assert window.commit_named_row_list("Actives", {1}) is True
    assert window._row_list_store().oids("Actives") == [0, 1, 2]

    act = next(a for a in window._lists_menu.actions() if a.data() == "Actives")
    act.trigger()
    qapp.processEvents()
    assert window._selected_oids_set() == {0, 1, 2}

    window._row_list_store().retain([])
    window._rebuild_lists_menu()
    assert _menu_labels(window) == ["Add Selected to List…", "", "Manage Lists…"]
    window.close()


def test_manage_row_lists_deletes_on_accept(qapp, monkeypatch):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    _seed_rows(window)
    window.commit_named_row_list("Actives", {0})
    window.commit_named_row_list("Leads", {1, 2})

    class _Dlg:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec_(self):
            return QDialog.Accepted

        def remaining_names(self):
            return ["Leads"]

    monkeypatch.setattr("molmanager.ui.dialogs.row_lists.ManageListsDialog", _Dlg)
    window.manage_row_lists()
    assert window._row_list_store().names() == ["Leads"]
    assert _menu_labels(window)[1] == "Leads"
    window.close()


def test_session_roundtrip_restores_lists(qapp):  # noqa: ARG001
    window = ChemistryWorkspaceWindow()
    _seed_rows(window)
    window.commit_named_row_list("Actives", {0, 2})
    window.commit_named_row_list("Leads", {1})
    window._session_dirty = False

    doc = window._build_session_document()
    assert doc["row_lists"] == [
        {"name": "Actives", "oids": [0, 2]},
        {"name": "Leads", "oids": [1]},
    ]
    selected = window._build_session_document(oids={1})
    assert selected["row_lists"] == [{"name": "Leads", "oids": [1]}]
    assert "row_lists" not in window._build_session_document(oids={9})

    restored = ChemistryWorkspaceWindow()
    restored._apply_session_document(doc)
    assert restored._row_list_store().names() == ["Actives", "Leads"]
    assert restored._row_list_store().oids("Actives") == [0, 2]
    assert _menu_labels(restored)[1:3] == ["Actives", "Leads"]
    restored.apply_row_list("Actives")
    qapp.processEvents()
    assert restored._selected_oids_set() == {0, 2}

    restored.clear_all()
    assert restored._row_list_store().names() == []
    assert _menu_labels(restored) == ["Add Selected to List…", "", "Manage Lists…"]
    window.close()
    restored.close()
