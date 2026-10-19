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

"""Tests for plot hover card helpers."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.plot_hover import (
    hover_card_payload,
    hover_cards_payload,
    hover_column_choices,
    hover_lines_for_oid,
    resolve_default_hover_columns,
    structure_png_data_url_for_oid,
)


def test_hover_column_choices_skips_id_and_structure():
    assert hover_column_choices(["ID_HIDDEN", "Structure", "SMILES", "MW"]) == ["SMILES", "MW"]


def test_resolve_default_hover_columns():
    cols = resolve_default_hover_columns(["ID_HIDDEN", "Structure", "SMILES", "Name", "MW", "LogP"])
    assert cols == []
    assert resolve_default_hover_columns([]) == []


def test_hover_controls_default_to_structure_only(qapp):  # noqa: ARG001
    from molmanager.ui.plot_on_hover_controls import PlotOnHoverControls

    controls = PlotOnHoverControls()
    controls.reload_columns(["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"])
    assert controls.show_structure() is True
    assert controls.selected_columns() == []
    assert all(combo.currentText() == "—" for combo in controls._hover_combos)

    controls._hover_combos[0].setCurrentText("SMILES")
    controls.reload_columns(["ID_HIDDEN", "Structure", "SMILES", "Name", "MW", "LogP"])
    assert controls.selected_columns() == ["SMILES"]
    assert controls.apply_all_btn.text() == "Apply to All Plots"


def test_apply_hover_to_all_plots(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.plot_on_hover_controls import PlotOnHoverControls

    headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"]

    class _Host(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self._hover_controls = PlotOnHoverControls(self)
            self._plot_view = None
            self._hover_controls.reload_columns(headers)

    class _App:
        def __init__(self, hosts: list[_Host]) -> None:
            self._hosts = hosts

        def _iter_active_plot_hosts(self) -> list[_Host]:
            return list(self._hosts)

    source = _Host()
    other = _Host()
    untouched = PlotOnHoverControls()
    untouched.reload_columns(headers)
    app = _App([source, other])
    source.parent_app = app

    source._hover_controls.hover_structure_cb.setChecked(False)
    source._hover_controls.hover_persist_cb.setChecked(True)
    source._hover_controls._hover_combos[0].setCurrentText("Name")
    source._hover_controls._hover_combos[1].setCurrentText("MW")
    source._hover_controls.apply_all_btn.click()

    assert other._hover_controls.show_structure() is False
    assert other._hover_controls.persist_on_select() is True
    assert other._hover_controls.selected_columns() == ["Name", "MW"]
    assert untouched.show_structure() is True
    assert untouched.selected_columns() == []


def test_hover_lines_and_structure_png(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1

    lines = hover_lines_for_oid(w, 0, ["SMILES", "Name"])
    assert lines == ["SMILES: CCO", "Name: ethanol"]
    assert not any(line.startswith("OID") for line in lines)

    url = structure_png_data_url_for_oid(w, 0)
    assert url.startswith("data:image/png;base64,")
    assert len(url) > 40

    payload = hover_card_payload(w, 0, ["MW"], show_structure=True)
    assert payload["oid"] == 0
    assert any("MW:" in s for s in payload["lines"])
    assert payload["img"].startswith("data:image/png;base64,")

    payload2 = hover_card_payload(w, 0, ["MW"], show_structure=False)
    assert payload2["img"] == ""


def test_hover_cards_payload_multi(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "Name": "ethanol"})
    w._table_model.append_row(1, {"SMILES": "C", "Name": "methane"})
    w._table_model.append_row(2, {"SMILES": "CC", "Name": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.mols[2] = Chem.MolFromSmiles("CC")
    w.next_oid = 3

    single = hover_cards_payload(w, [0], ["Name"], show_structure=False)
    assert single["count"] == 1
    assert len(single["items"]) == 1
    assert single["title"] == ""
    assert single["oid"] == 0

    multi = hover_cards_payload(w, [0, 1, 2], ["Name"], show_structure=True)
    assert multi["count"] == 3
    assert multi["title"].startswith("3 selected")
    assert len(multi["items"]) == 3
    assert all(it["img"].startswith("data:image/png;base64,") for it in multi["items"])

    many_oids = list(range(12))
    for i in range(3, 12):
        w._table_model.append_row(i, {"SMILES": "C", "Name": f"n{i}"})
        w.mols[i] = Chem.MolFromSmiles("C")
    w.next_oid = 12
    many = hover_cards_payload(w, many_oids, ["Name"], show_structure=False)
    assert many["count"] == 12
    assert len(many["items"]) == 10
    assert many["overflow"] == 2
