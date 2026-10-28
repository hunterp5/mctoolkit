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

"""Tests for pure chemistry column policy helpers."""

from __future__ import annotations

from molmanager.services.chemistry_columns import (
    canonical_smiles_header_for_updates,
    cell_texts_have_parseable_molecule,
    data_headers_confirmed_for_chemistry_tools,
    headers_with_depictable_structures,
    is_smiles_named_header,
    ordered_headers_for_molecule_lookup,
    is_legacy_som_map_header,
    skip_chemistry_tool_column_dropdown,
    should_skip_chemical_scan_column,
    text_is_depictable_structure,
)
from molmanager.chem.molecule_conversion import (
    canonical_structure_key_from_smiles,
    mol_from_binary_blob,
)


def test_skip_chemistry_tool_column_dropdown():
    assert skip_chemistry_tool_column_dropdown("Structure")
    assert skip_chemistry_tool_column_dropdown("pKa")
    assert skip_chemistry_tool_column_dropdown("pI")
    assert skip_chemistry_tool_column_dropdown("SOM Map")
    assert skip_chemistry_tool_column_dropdown("SOM Sites Phase 1")
    assert skip_chemistry_tool_column_dropdown("SOM Phase")
    assert skip_chemistry_tool_column_dropdown("Cluster (Morgan)")
    assert not skip_chemistry_tool_column_dropdown("SMILES")
    assert not skip_chemistry_tool_column_dropdown("Protonated")
    assert not skip_chemistry_tool_column_dropdown("Structure (Copy)")


def test_is_legacy_som_map_header():
    assert is_legacy_som_map_header("SOM Map")
    assert is_legacy_som_map_header("SOM Map 2")
    assert not is_legacy_som_map_header("SOM Sites")
    assert not is_legacy_som_map_header("Protonated")


def test_is_smiles_named_header():
    assert is_smiles_named_header("SMILES")
    assert is_smiles_named_header("canonical_smiles")
    assert not is_smiles_named_header("InChIKey")


def test_canonical_smiles_header_for_updates():
    headers = ["ID_HIDDEN", "Structure", "Name", "SMILES", "MW"]
    assert canonical_smiles_header_for_updates(headers) == "SMILES"
    headers2 = ["ID_HIDDEN", "Structure", "mol_smiles"]
    assert canonical_smiles_header_for_updates(headers2) == "mol_smiles"


def test_ordered_headers_prefer_smiles():
    headers = ["ID_HIDDEN", "Structure", "MW", "SMILES", "Name"]
    ordered = ordered_headers_for_molecule_lookup(headers)
    assert ordered[0] == "SMILES"


def test_ordered_headers_exclude_protonated_unless_override():
    headers = ["ID_HIDDEN", "Structure", "Protonated", "MW"]
    ordered = ordered_headers_for_molecule_lookup(headers)
    assert "Protonated" not in ordered
    overridden = ordered_headers_for_molecule_lookup(headers, structure_field_override="Protonated")
    assert overridden[0] == "Protonated"


def test_ordered_headers_exclude_structure_copy():
    headers = ["ID_HIDDEN", "Structure", "Structure (Copy)", "SMILES"]
    ordered = ordered_headers_for_molecule_lookup(headers)
    assert "Structure (Copy)" not in ordered
    assert "SMILES" in ordered


def test_should_skip_pixmap_via_callback():
    assert should_skip_chemical_scan_column(
        "Render2D",
        is_pixmap_column=lambda h: h == "Render2D",
    )


def test_data_headers_confirmed_structural():
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    out = data_headers_confirmed_for_chemistry_tools(headers)
    assert "SMILES" in out
    assert "MW" not in out


def test_data_headers_include_protonated_not_protomer_percent():
    headers = ["ID_HIDDEN", "Structure", "SMILES", "Protonated", "% Protomer (pH 7.4)"]
    out = data_headers_confirmed_for_chemistry_tools(headers)
    assert "Protonated" in out
    assert "SMILES" in out
    assert "% Protomer (pH 7.4)" not in out


def test_data_headers_include_structure_copy():
    headers = ["ID_HIDDEN", "Structure", "Structure (Copy)", "MW"]
    out = data_headers_confirmed_for_chemistry_tools(headers)
    assert "Structure (Copy)" in out
    assert "MW" not in out


def test_cell_texts_have_parseable_molecule():
    assert cell_texts_have_parseable_molecule(["CCO", "not-a-mol"])
    assert not cell_texts_have_parseable_molecule(["", "???"])
    assert not cell_texts_have_parseable_molecule(
        ["http://selleckchem.com/products/Carmofur.html", '{"v":2,"h":"confs"}']
    )


def test_text_is_depictable_structure_accepts_molecules_and_reactions():
    assert text_is_depictable_structure("c1ccccc1")
    assert text_is_depictable_structure("[16*]c1ccccc1")
    assert text_is_depictable_structure("CCO . [Na+]")
    assert text_is_depictable_structure("CCO>>CC")
    assert text_is_depictable_structure("[#6]-[#6]")
    assert not text_is_depictable_structure("N/A")
    assert not text_is_depictable_structure("1")
    assert not text_is_depictable_structure("7.40")
    assert not text_is_depictable_structure("CCO; CC")
    assert not text_is_depictable_structure("hello")


def test_headers_with_depictable_structures_skips_numbers_and_lists():
    rows = [
        (1, {"BRICS_1": "[16*]c1ccccc1", "BRICS_2": "N/A", "Count": "2", "Notes": "ring"}),
        (2, {"BRICS_1": "CCO . [Na+]", "BRICS_2": "*C", "Count": "1", "Notes": "salt"}),
        (3, {"Metabolites": "CCO; CC", "Product 1": "c1ccccc1"}),
    ]
    assert headers_with_depictable_structures(
        ["BRICS_1", "BRICS_2", "Count", "Notes", "Metabolites", "Product 1"],
        rows,
    ) == ["BRICS_1", "BRICS_2", "Product 1"]


def test_canonical_structure_key_from_smiles():
    key = canonical_structure_key_from_smiles("CCO")
    assert key
    assert canonical_structure_key_from_smiles("not-smiles") is None


def test_mol_from_binary_blob_roundtrip():
    from rdkit import Chem

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    rebuilt = mol_from_binary_blob(mol.ToBinary())
    assert rebuilt is not None
    assert Chem.MolToSmiles(rebuilt) == "CCO"
    assert mol_from_binary_blob(None) is None
