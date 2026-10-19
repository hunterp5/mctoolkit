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

"""Tests for Chemistry → Reaction → Extract."""

from __future__ import annotations

from types import SimpleNamespace

from rdkit import Chem

from molmanager.chem.reaction_extract import (
    extract_reaction_column_values,
    extract_reaction_sides,
    preferred_reaction_source_column,
    split_side_components,
)
from molmanager.chem.reaction_file_io import RXN_SMARTS_HEADER
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.strings import TOOL_REACTION_EXTRACT

_ETHANOL = "CCO.O>>CC=O"
_AMIDE = "[C:1](=[O:2])-[OH;D1].[N;H2,H1]>>[C:1](=[O:2])-[N]"


def test_split_side_components_ignores_dots_in_brackets() -> None:
    assert split_side_components("CCO.O") == ["CCO", "O"]
    assert split_side_components("[C:1].[N;H2,H1]") == ["[C:1]", "[N;H2,H1]"]
    assert split_side_components("") == []


def test_extract_reaction_sides_smiles() -> None:
    reactants, products = extract_reaction_sides(_ETHANOL)
    assert reactants == ["CCO", "O"]
    assert products == ["CC=O"]


def test_extract_reaction_sides_query_keeps_smarts() -> None:
    reactants, products = extract_reaction_sides(_AMIDE)
    assert len(reactants) == 2
    assert len(products) == 1
    assert "D1" in reactants[0] or "O" in reactants[0]
    assert reactants[1] in ("N", "[N;H2,H1]")
    assert products[0]


def test_extract_column_values_both_and_padding() -> None:
    headers, rows = extract_reaction_column_values(
        [_ETHANOL, "CCO>>CC=O", "not a reaction"],
        "both",
    )
    assert headers == ["Reactant 1", "Reactant 2", "Product 1"]
    assert rows[0]["Reactant 1"] == "CCO"
    assert rows[0]["Reactant 2"] == "O"
    assert rows[0]["Product 1"] == "CC=O"
    assert rows[1]["Reactant 1"] == "CCO"
    assert rows[1]["Reactant 2"] == ""
    assert rows[1]["Product 1"] == "CC=O"
    assert rows[2]["Reactant 1"] == ""
    assert rows[2]["Product 1"] == ""


def test_extract_column_values_reactants_or_products_only() -> None:
    r_headers, r_rows = extract_reaction_column_values([_ETHANOL], "reactants")
    assert r_headers == ["Reactant 1", "Reactant 2"]
    assert "Product 1" not in r_rows[0]
    p_headers, p_rows = extract_reaction_column_values([_ETHANOL], "products")
    assert p_headers == ["Product 1"]
    assert p_rows[0]["Product 1"] == "CC=O"


def test_preferred_reaction_source_column() -> None:
    assert preferred_reaction_source_column(["SMILES", RXN_SMARTS_HEADER]) == RXN_SMARTS_HEADER
    assert preferred_reaction_source_column(["SMILES", "MW"]) is None


def test_extract_writes_new_headers(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", RXN_SMARTS_HEADER]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {RXN_SMARTS_HEADER: _ETHANOL})
    w._table_model.append_row(1, {RXN_SMARTS_HEADER: "CCO>>CC=O"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCO")
    w.next_oid = 2

    accepted = SimpleNamespace(
        params=lambda: SimpleNamespace(
            source_column=RXN_SMARTS_HEADER,
            mode="both",
            reactant_prefix="Reactant",
            product_prefix="Product",
        ),
        only_selected_rows=lambda: False,
    )
    w._on_reaction_extract_dialog_accepted(accepted)
    assert "Reactant 1" in w.headers
    assert "Reactant 2" in w.headers
    assert "Product 1" in w.headers
    r1 = w.headers.index("Reactant 1")
    r2 = w.headers.index("Reactant 2")
    p1 = w.headers.index("Product 1")
    assert w._table_model.cell_text(0, r1) == "CCO"
    assert w._table_model.cell_text(0, r2) == "O"
    assert w._table_model.cell_text(0, p1) == "CC=O"
    assert w._table_model.cell_text(1, r1) == "CCO"
    assert (w._table_model.cell_text(1, r2) or "") == ""
    assert TOOL_REACTION_EXTRACT in (w.status_label.text() or "")
    w.close()


def test_extract_dialog_defaults_to_reaction_smarts(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.reaction_extract import ReactionExtractDialog

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", RXN_SMARTS_HEADER]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "", RXN_SMARTS_HEADER: _ETHANOL})
    w.next_oid = 1
    dlg = ReactionExtractDialog(["SMILES", RXN_SMARTS_HEADER], 0, w)
    try:
        assert dlg.col_combo.currentText() == RXN_SMARTS_HEADER
        assert dlg.params().mode == "both"
        assert "Reactant 1" in (dlg.preview_label.text() or "")
        assert "Product 1" in (dlg.preview_label.text() or "")
    finally:
        dlg.close()
        w.close()
