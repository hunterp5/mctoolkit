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

"""Prepare molecule edits, each on its own and in combination."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.molecule_conversion import mol_to_canonical_smiles
from molmanager.chem.structure_prepare import (
    StructurePrepareOptions,
    apply_structure_prepare,
    options_from_prepare_params,
)


def _smiles(mol) -> str:
    return mol_to_canonical_smiles(mol)


def test_each_prepare_edit_can_run_alone() -> None:
    salt = Chem.MolFromSmiles("CC(=O)[O-].[Na+]")
    parent, rest = apply_structure_prepare(
        salt, StructurePrepareOptions(largest_fragment=True), "CC(=O)[O-].[Na+]"
    )
    assert _smiles(parent) == "CC(=O)[O-]"
    assert rest == "[Na+]"

    metal = Chem.MolFromSmiles("CC(=O)O[Na]")
    standardized, _rest = apply_structure_prepare(metal, StructurePrepareOptions(standardize=True))
    assert _smiles(standardized) == "CC(=O)[O-].[Na+]"

    sulfoxide = Chem.MolFromSmiles("CS(=O)C")
    normalized, _rest = apply_structure_prepare(
        sulfoxide, StructurePrepareOptions(standardize=True)
    )
    assert _smiles(normalized) == "C[S+](C)[O-]"

    enol = Chem.MolFromSmiles("OC=CC")
    tautomer, _rest = apply_structure_prepare(
        enol, StructurePrepareOptions(canonical_tautomer=True)
    )
    assert _smiles(tautomer) == "CCC=O"

    glycine = Chem.MolFromSmiles("NCC(=O)[O-]")
    neutral, _rest = apply_structure_prepare(glycine, StructurePrepareOptions(neutralize=True))
    assert _smiles(neutral) == "NCC(=O)O"
    assert Chem.GetFormalCharge(neutral) == 0

    labeled = Chem.MolFromSmiles("[2H]C")
    cleared, _rest = apply_structure_prepare(labeled, StructurePrepareOptions(remove_isotopes=True))
    assert all(atom.GetIsotope() == 0 for atom in cleared.GetAtoms())


def test_canonical_tautomer_search_is_bounded() -> None:
    from molmanager.chem import structure_prepare as prepare

    enol = Chem.MolFromSmiles("OC=CC")
    tautomer, _rest = apply_structure_prepare(
        enol, StructurePrepareOptions(canonical_tautomer=True)
    )
    assert _smiles(tautomer) == "CCC=O"
    enumerator = prepare._tautomer_enumerator()
    assert enumerator.GetMaxTautomers() == prepare._MAX_TAUTOMERS == 100
    assert enumerator.GetMaxTransforms() == prepare._MAX_TRANSFORMS == 100


def test_explicit_hydrogens_do_not_change_charge() -> None:
    amine = Chem.MolFromSmiles("CCN")
    charge = Chem.GetFormalCharge(amine)
    shown, _rest = apply_structure_prepare(amine, StructurePrepareOptions(explicit_hydrogens="add"))
    assert shown.GetNumAtoms() > amine.GetNumAtoms()
    assert Chem.GetFormalCharge(shown) == charge
    hidden, _rest = apply_structure_prepare(
        shown, StructurePrepareOptions(explicit_hydrogens="remove")
    )
    assert hidden.GetNumAtoms() == amine.GetNumAtoms()
    assert Chem.GetFormalCharge(hidden) == charge


def test_checked_edits_run_together() -> None:
    mol = Chem.MolFromSmiles("CC(=O)O[Na]")
    prepared, rest = apply_structure_prepare(
        mol,
        StructurePrepareOptions(standardize=True, largest_fragment=True, neutralize=True),
    )
    assert _smiles(prepared) == "CC(=O)O"
    assert "[Na+]" in rest


def test_protomer_output_file_writes_sdf_and_csv(tmp_path) -> None:
    from molmanager.ui.dialogs.protomer import write_protomer_file

    rows = [(7, "CCO", 80.0, "15.9"), (7, "CC[OH2+]", 20.0, "15.9")]
    sdf = tmp_path / "protomers.sdf"
    csv_path = tmp_path / "protomers.csv"
    write_protomer_file(str(sdf), rows)
    write_protomer_file(str(csv_path), rows)
    text = sdf.read_text(encoding="utf-8")
    assert "CCO" in text
    assert "15.9" in text
    assert "Source OID,SMILES,Protomer %,pKa" in csv_path.read_text(encoding="utf-8")


def test_legacy_fast_prepare_params_do_not_gain_tautomers() -> None:
    assert options_from_prepare_params({"neutralize": True}) is None
    options = options_from_prepare_params(
        {
            "standardize": False,
            "largest_fragment": True,
            "canonical_tautomer": False,
            "neutralize": True,
        }
    )
    assert options is not None
    assert options.largest_fragment is True
    assert options.canonical_tautomer is False
    assert options.neutralize is True
