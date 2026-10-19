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

"""Tools → Browser shows the current table row in a compact table."""

from __future__ import annotations

from PyQt5.QtWidgets import QSizePolicy
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.selection_browser import SelectionBrowserWidget


def _seed_row(app: ChemistryWorkspaceWindow) -> None:
    app.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"]
    app._table_model.set_headers(list(app.headers))
    app._table_model.append_row(0, {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"})
    app.mols[0] = Chem.MolFromSmiles("CCO")
    app.next_oid = 1


def test_selection_browser_shows_current_row_table(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    assert getattr(panel, "_prop_panel", None) is None
    assert not hasattr(panel, "_spin_field_count")
    table = panel._row_table
    assert table.rowCount() == 1
    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert headers == ["SMILES", "Name", "MW"]
    assert table.item(0, 0).text() == "CCO"
    assert table.item(0, 1).text() == "ethanol"
    assert table.item(0, 2).text() == "46.07"
    assert panel._btn_toggle_select.text() == ""
    assert not panel._btn_toggle_select.icon().isNull()
    assert panel._btn_toggle_select.isCheckable()
    assert panel._btn_toggle_select.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    panel.deleteLater()
    w.close()


def test_selection_browser_row_table_follows_navigation(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(1, {"SMILES": "CCC", "Name": "propane", "MW": "44.10"})
    w.mols[1] = Chem.MolFromSmiles("CCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    assert panel._row_table.item(0, 1).text() == "ethanol"
    assert panel._index_edit.value() == 1
    assert panel._index_scope_label.text() == "Row"
    panel._step(1)
    assert panel._index_edit.value() == 2
    assert panel._row_table.item(0, 0).text() == "CCC"
    assert panel._row_table.item(0, 1).text() == "propane"
    panel.deleteLater()
    w.close()


def test_selection_browser_row_table_keeps_size_while_navigating(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(
        1,
        {
            "SMILES": "CCCCCCCCCCCCCCCCCCCC",
            "Name": "a much longer compound name than ethanol",
            "MW": "1234.5678",
        },
    )
    w.mols[1] = Chem.MolFromSmiles("CCCCCCCCCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    table = panel._row_table
    height = table.height()
    col_w = table.columnWidth(0)
    panel._step(1)
    assert table.height() == height
    assert table.columnWidth(0) == col_w
    panel.deleteLater()
    w.close()


def test_selection_browser_index_left_of_nav(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(1, {"SMILES": "CCC", "Name": "propane", "MW": "44.10"})
    w.mols[1] = Chem.MolFromSmiles("CCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    assert panel.layout().indexOf(panel._footer_bar) == 0
    assert panel._opts_btn.parent() is panel._header_left
    assert panel._add_to_main_btn.parent() is panel._header_right
    assert not panel._meta.isVisibleTo(panel)
    nav = panel._nav_bar.layout()
    assert nav.indexOf(panel._index_host) < nav.indexOf(panel._btn_first)
    assert panel._index_scope_label.text() == "Row"
    assert panel._index_edit.value() == 1
    assert panel._index_count_label.text() == "/ 2"
    panel._index_edit.lineEdit().setText("2")
    panel._index_edit.interpretText()
    assert panel._idx == 1
    assert panel._row_table.item(0, 1).text() == "propane"
    assert panel._index_edit.value() == 2
    panel._cb_only_selected.setChecked(True)
    assert panel._index_scope_label.text() == "Selected"
    panel.deleteLater()
    w.close()


def test_selection_browser_preview_mode_uses_item_data(qapp):  # noqa: ARG001
    from molmanager.ui.browsers.selection_browser import (
        BROWSER_PREVIEW_MODE_3DMOL_2D,
        BROWSER_PREVIEW_MODE_3DMOL_3D,
        BROWSER_PREVIEW_MODE_LABELS,
        BROWSER_PREVIEW_MODE_RDKIT_2D,
        DEFAULT_BROWSER_PREVIEW_MODE,
    )

    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    keys = [panel._preview_mode_combo.itemData(i) for i in range(panel._preview_mode_combo.count())]
    assert keys == [k for k, _ in BROWSER_PREVIEW_MODE_LABELS]
    assert panel._preview_mode_key() == DEFAULT_BROWSER_PREVIEW_MODE
    assert panel._preview_mode_key() == BROWSER_PREVIEW_MODE_RDKIT_2D
    assert not panel._uses_3dmol_preview()
    panel.set_preview_mode(BROWSER_PREVIEW_MODE_3DMOL_2D)
    assert panel._preview_mode_key() == BROWSER_PREVIEW_MODE_3DMOL_2D
    assert panel._uses_3dmol_preview()
    panel.set_preview_mode(BROWSER_PREVIEW_MODE_3DMOL_3D)
    assert panel._preview_mode_key() == BROWSER_PREVIEW_MODE_3DMOL_3D
    panel.deleteLater()
    w.close()


def test_selection_browser_ignores_selection_when_browsing_all_rows(qapp, monkeypatch):  # noqa: ARG001
    """With "Browse Selected" off, a selection change only restates the toggle button."""
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    refreshes: list[dict] = []
    monkeypatch.setattr(panel, "refresh_from_app", lambda **k: refreshes.append(k))

    w.select_table_oids({0})

    assert not panel._selection_refresh_timer.isActive()
    assert not panel._auto_refresh_timer.isActive()
    assert panel._btn_toggle_select.isChecked()
    assert refreshes == []
    panel.deleteLater()
    w.close()


def test_selection_browser_rescope_keeps_previews(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(True)
    panel._preview_pix_cache["sentinel"] = object()

    w.select_table_oids({0})
    assert panel._selection_refresh_timer.isActive()
    panel._selection_refresh_timer.timeout.emit()

    assert "sentinel" in panel._preview_pix_cache
    assert panel._rows == [0]
    panel.deleteLater()
    w.close()


def test_selection_browser_focus_oid_walks_to_row(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_row(w)
    w._table_model.append_row(1, {"SMILES": "CCC", "Name": "propane", "MW": "44.10"})
    w.mols[1] = Chem.MolFromSmiles("CCC")
    w.next_oid = 2
    panel = SelectionBrowserWidget(w)
    panel._cb_only_selected.setChecked(False)
    panel.refresh_from_app()
    panel.focus_oid(1)
    assert panel._rows[panel._idx] == 1
    assert panel._row_table.item(0, 1).text() == "propane"
    panel.deleteLater()
    w.close()
