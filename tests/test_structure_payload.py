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

"""StructurePayload hydrate helpers (no Qt)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.molecule_conversion import mol_graph_binary
from molmanager.chem.structure_payload import (
    StructurePayload,
    mol_from_payload,
    mol_rows_from_job_params,
    mols_from_payloads,
    oid_mol_rows_from_payloads,
    smiles_rows_from_payloads,
    smiles_text_for_payload,
)


def test_mol_from_payload_prefers_blob():
    mol = Chem.MolFromSmiles("CCO")
    blob = mol_graph_binary(mol)
    got = mol_from_payload(StructurePayload(1, blob, "CC"))
    assert Chem.MolToSmiles(got) == "CCO"


def test_mol_from_payload_falls_back_to_smiles():
    got = mol_from_payload(StructurePayload(2, None, "CC"))
    assert Chem.MolToSmiles(got) == "CC"


def test_mols_from_payloads_drops_unparseable():
    rows = mols_from_payloads(
        [
            StructurePayload(1, None, "CCO"),
            StructurePayload(2, None, "not-a-molecule"),
            StructurePayload(None, None, "CC"),
        ]
    )
    assert [oid for oid, _mol in rows] == [1, None]


def test_oid_mol_rows_from_payloads_drops_none_oid():
    rows = oid_mol_rows_from_payloads(
        [StructurePayload(None, None, "CC"), StructurePayload(3, None, "CCO")]
    )
    assert [oid for oid, _mol in rows] == [3]


def test_smiles_text_for_payload_blob_without_smiles():
    mol = Chem.MolFromSmiles("c1ccccc1O")
    blob = mol_graph_binary(mol)
    got = smiles_text_for_payload(StructurePayload(1, blob, ""))
    assert got == Chem.MolToSmiles(mol, canonical=True)


def test_smiles_text_for_payload_molblock_text():
    mol = Chem.MolFromSmiles("CCO")
    block = Chem.MolToMolBlock(mol)
    got = smiles_text_for_payload(StructurePayload(2, None, block))
    assert got == "CCO"


def test_smiles_rows_from_payloads_keeps_blob_only_and_drops_invalid():
    mol = Chem.MolFromSmiles("CC")
    rows = smiles_rows_from_payloads(
        [
            StructurePayload(4, mol_graph_binary(mol), ""),
            StructurePayload(5, None, "not-a-molecule"),
            StructurePayload(None, None, "CCO"),
        ]
    )
    assert rows == [(4, "CC")]


def test_mol_rows_from_job_params_prefers_payloads():
    params = {
        "mol_payloads": [StructurePayload(1, None, "CC")],
        "mol_rows": [(9, object())],
    }
    rows = mol_rows_from_job_params(params)
    assert rows is not None
    assert rows[0][0] == 1
