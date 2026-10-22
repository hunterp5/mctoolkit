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

"""Ingest of 3D file structures: 2D Structure + packed confs for the viewer."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.conformers.conformer_column_codec import (
    mol_coordinates_fill_blank_confs,
    mol_from_packed_confs_cell,
    mol_has_3d_coordinates,
    rehydrate_v1_confs_cell,
    resolve_blocks_b64_for_viewer,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.mol_viewer_3d import prepare_mol_2d
from molmanager.workers.load_render import _mol_ingest_item


def _flat_ethanol():
    m = Chem.MolFromSmiles("CCO")
    AllChem.Compute2DCoords(m)
    return m


def _ethanol_3d():
    m = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMolecule(m, randomSeed=0xBEEF)
    return m


def test_mol_has_3d_coordinates_detects_z():
    assert not mol_has_3d_coordinates(_flat_ethanol())
    assert mol_has_3d_coordinates(_ethanol_3d())
    assert not mol_has_3d_coordinates(Chem.MolFromSmiles("CCO"))  # no conformer


def test_ingest_store_mol_demotes_3d_to_confs(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.table.setColumnHidden(0, True)

    # A flat structure does not add a confs column when the file has none.
    oid_flat = w.next_oid
    w.next_oid += 1
    cells_flat = w._ingest_store_mol(oid_flat, _flat_ethanol())
    assert not (cells_flat.get("confs") or "").strip()
    assert "confs" not in w.headers

    mol3d = _ethanol_3d()
    oid = w.next_oid
    w.next_oid += 1
    cells = w._ingest_store_mol(oid, mol3d)
    w._table_model.append_row(oid, cells)

    assert "confs" in w.headers
    assert "confs" in cells and cells["confs"]
    depict = w.mols[oid]
    assert depict is not None
    assert depict.GetNumConformers() == 1
    # Structure mol should be 2D (negligible Z), while packed confs keep 3D.
    assert not mol_has_3d_coordinates(depict)
    assert prepare_mol_2d(mol3d) is not None

    light = w._table_model.backing_value_for_row_header(0, "confs")
    sc = getattr(w, "_confs_blocks_sidecar", {})
    b64 = resolve_blocks_b64_for_viewer(light, "confs", oid, sc)
    assert b64 is not None
    packed = mol_from_packed_confs_cell(
        rehydrate_v1_confs_cell(light, "confs", oid, sc), min_conformers=1
    )
    assert packed is not None
    assert mol_has_3d_coordinates(packed)
    w.close()


def test_mol_coordinates_fill_blank_confs_only_for_empty_column():
    flat = _flat_ethanol()
    assert mol_coordinates_fill_blank_confs(flat, "")
    assert mol_coordinates_fill_blank_confs(flat, "   ")
    assert not mol_coordinates_fill_blank_confs(flat, None)
    assert not mol_coordinates_fill_blank_confs(flat, '{"v":2,"h":"confs","m":{"ok":true}}')
    assert not mol_coordinates_fill_blank_confs(_ethanol_3d(), "")
    assert not mol_coordinates_fill_blank_confs(Chem.MolFromSmiles("CCO"), "")


def test_blank_confs_load_stores_structure_coordinates(qapp):  # noqa: ARG001
    """An SDF structure with an empty confs field is that one conformation."""
    mol = _flat_ethanol()
    mol.SetProp("SMILES", "CCO")
    mol.SetProp("confs", "")
    blob, cells = _mol_ingest_item(mol, ["SMILES", "confs"])
    rebuilt = Chem.Mol(bytes(blob))
    assert rebuilt is not None and rebuilt.GetNumConformers() == 1
    assert not (cells.get("confs") or "").strip()

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
    w._table_model.set_headers(list(w.headers))
    oid = w.next_oid
    w.next_oid += 1
    stored = w._ingest_store_mol(oid, rebuilt, precomputed_cells=cells)
    w._table_model.append_row(oid, stored)

    assert (stored.get("confs") or "").strip()
    light = w._table_model.backing_value_for_row_header(0, "confs")
    sc = getattr(w, "_confs_blocks_sidecar", {})
    packed = mol_from_packed_confs_cell(
        rehydrate_v1_confs_cell(light, "confs", oid, sc), min_conformers=1
    )
    assert packed is not None
    assert packed.GetNumConformers() == 1
    assert packed.GetNumAtoms() == rebuilt.GetNumAtoms()

    # A confs payload already on the row is kept; depiction coords are not a second ensemble.
    payload = '{"v":2,"h":"confs","m":{"ok":true,"n_kept":2,"n_packed":2}}'
    kept = _flat_ethanol()
    kept.SetProp("SMILES", "CCO")
    kept.SetProp("confs", payload)
    kept_blob, kept_cells = _mol_ingest_item(kept, ["SMILES", "confs"])
    kept_mol = Chem.Mol(bytes(kept_blob))
    assert kept_mol.GetNumConformers() == 0
    assert kept_cells["confs"] == payload
    oid3 = w.next_oid
    w.next_oid += 1
    kept_stored = w._ingest_store_mol(oid3, kept_mol, precomputed_cells=kept_cells)
    assert kept_stored["confs"] == payload
    w.close()
