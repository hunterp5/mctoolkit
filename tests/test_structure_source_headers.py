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

"""Tests for import structure-source header detection."""

from molmanager.chem.structure_source_headers import (
    header_looks_like_structure_text,
    is_duplicated_structure_header,
    is_tool_generated_structure_header,
    needs_structure_source_picker,
    structure_source_picker_candidates,
)


def test_inchi_key_not_a_structure_source_candidate():
    headers = ["ID_HIDDEN", "Structure", "Ligand InChI", "Ligand InChI Key", "Target Name"]
    cols = structure_source_picker_candidates(headers)
    assert cols == ["Ligand InChI"]
    assert not needs_structure_source_picker(headers)


def test_needs_picker_when_two_real_structure_columns():
    headers = ["ID_HIDDEN", "Structure", "SMILES", "Ligand InChI"]
    assert needs_structure_source_picker(headers)


def test_tool_generated_structure_headers():
    assert header_looks_like_structure_text("Protonated")
    assert header_looks_like_structure_text("Protonated (1)")
    assert header_looks_like_structure_text("Largest Fragment")
    assert header_looks_like_structure_text("Largest Fragment (1)")
    assert not header_looks_like_structure_text("% Protomer (pH 7.4)")
    assert not header_looks_like_structure_text("Protomer %")
    assert not header_looks_like_structure_text("Fragments")
    assert is_tool_generated_structure_header("Protonated")
    assert is_tool_generated_structure_header("Protonated (1)")
    assert is_tool_generated_structure_header("Largest Fragment")
    assert header_looks_like_structure_text("Murcko scaffold")
    assert header_looks_like_structure_text("Murcko scaffold (1)")
    assert header_looks_like_structure_text("Murcko framework")
    assert header_looks_like_structure_text("Murcko ring systems (2)")
    assert not header_looks_like_structure_text("Scaffold count")
    assert header_looks_like_structure_text("Common core")
    assert header_looks_like_structure_text("Common core (1)")
    assert not header_looks_like_structure_text("Core atom map")
    assert not header_looks_like_structure_text("Core match")
    assert is_tool_generated_structure_header("Common core")
    assert is_tool_generated_structure_header("Murcko scaffold")
    assert is_tool_generated_structure_header("Murcko framework (1)")
    assert not is_tool_generated_structure_header("Scaffold count")
    assert not is_tool_generated_structure_header("SMILES")
    assert header_looks_like_structure_text("Reaction SMARTS")
    assert header_looks_like_structure_text("SMIRKS")
    assert header_looks_like_structure_text("Structure (Copy)")
    assert header_looks_like_structure_text("Structure (Copy 2)")
    assert is_tool_generated_structure_header("Structure (Copy)")
    assert is_tool_generated_structure_header("Structure (Copy 2)")
    assert not is_tool_generated_structure_header("Structure")
    assert is_duplicated_structure_header("Structure (Copy)")
    assert not is_duplicated_structure_header("Structure")
