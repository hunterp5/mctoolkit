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

"""Tests for shared PlotlyInteractiveView hover helpers (no WebEngine)."""

from __future__ import annotations

import json

from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.plotly_interactive_view import PlotlyInteractiveView


def test_interactive_view_hover_card_json(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Name", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "Name": "ethanol", "MW": "46.07"})
    w._table_model.append_row(1, {"SMILES": "C", "Name": "methane", "MW": "16.04"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2

    view = PlotlyInteractiveView.__new__(PlotlyInteractiveView)
    view.parent_app = w
    view.plotted_oids = [0, 1]
    view._hover_show_structure = True
    view._hover_persist = True
    view._hover_columns = None

    one = json.loads(view._hover_card_json_for_point(0))
    assert one["count"] == 1
    assert one["oid"] == 0
    assert one["lines"] == []
    assert one["img"].startswith("data:image/png;base64,")

    multi = json.loads(view._hover_card_json_for_points("[0,1]"))
    assert multi["count"] == 2
    assert len(multi["items"]) == 2
