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

from molmanager.chem.ingest_records import ingest_record_from_mol
from molmanager.conformers.conformer_column_codec import (
    mol_coordinates_fill_blank_confs,
    mol_from_packed_confs_cell,
    mol_has_3d_coordinates,
    rehydrate_v1_confs_cell,
    resolve_blocks_b64_for_viewer,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.mol_viewer_3d import prepare_mol_2d


def _flat_ethanol():
    m = Chem.MolFromSmiles("CCO")
    AllChem.Compute2DCoords(m)
    return m


def _ethanol_3d():
    """Ethanol with a real z span. RDKit's heavy-atom embed can leave z at zero."""
    from rdkit.Geometry import Point3D

    m = Chem.MolFromSmiles("CCO")
    AllChem.EmbedMolecule(m, randomSeed=0xBEEF)
    conf = m.GetConformer()
    for i in range(m.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(float(pos.x), float(pos.y), float(i + 1)))
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
    assert w._depiction_coords.get("Structure", oid_flat)

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
    assert w._depiction_coords.get("Structure", oid) is None
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
    record = ingest_record_from_mol(mol, ["SMILES", "confs"])
    assert record.smiles == "CCO"
    assert Chem.Mol(record.structure).GetNumConformers() == 0
    assert record.ensemble and record.confs_cell
    assert not (record.cells.get("confs") or "").strip()

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
    w._table_model.set_headers(list(w.headers))
    rows: list = []
    w._ingest_append_batch_items([record], rows)
    oid, stored = rows[0]
    w._table_model.append_row(oid, stored)

    assert stored["confs"] == record.confs_cell
    light = w._table_model.backing_value_for_row_header(0, "confs")
    sc = getattr(w, "_confs_blocks_sidecar", {})
    packed = mol_from_packed_confs_cell(
        rehydrate_v1_confs_cell(light, "confs", oid, sc), min_conformers=1
    )
    assert packed is not None
    assert packed.GetNumConformers() == 1
    assert packed.GetNumAtoms() == mol.GetNumAtoms()

    # A confs payload already on the row is kept; depiction coords are not a second ensemble.
    payload = '{"v":2,"h":"confs","m":{"ok":true,"n_kept":2,"n_packed":2}}'
    kept = _flat_ethanol()
    kept.SetProp("SMILES", "CCO")
    kept.SetProp("confs", payload)
    kept_record = ingest_record_from_mol(kept, ["SMILES", "confs"])
    assert not kept_record.ensemble
    rows = []
    w._ingest_append_batch_items([kept_record], rows)
    assert rows[0][1]["confs"] == payload
    w.close()


def test_3d_file_record_packs_confs_without_a_gui_rebuild(qapp):  # noqa: ARG001
    record = ingest_record_from_mol(_ethanol_3d(), ["SMILES"])
    assert record.ensemble and record.depiction == b""
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    rows: list = []
    w._ingest_append_batch_items([record], rows)
    oid, cells = rows[0]
    assert "confs" in w.headers and cells["confs"] == record.confs_cell
    assert Chem.MolToSmiles(w.mols[oid]) == "CCO"
    assert w.mols[oid].GetNumConformers() == 0
    w.close()


def test_opened_molfile_keeps_its_2d_orientation(qapp):  # noqa: ARG001
    """An SDF or molfile's flat coordinates become the Structure orientation."""
    from rdkit.Geometry import Point3D

    from molmanager.chem.depiction_coords import apply_depiction_coords, unpack_xy

    mol = Chem.MolFromSmiles("c1ccccc1O")
    assert mol is not None
    AllChem.Compute2DCoords(mol)
    conf = mol.GetConformer()
    for i in range(mol.GetNumAtoms()):
        pos = conf.GetAtomPosition(i)
        conf.SetAtomPosition(i, Point3D(-float(pos.y), float(pos.x), 0.0))
    parsed = Chem.MolFromMolBlock(Chem.MolToMolBlock(mol))
    assert parsed is not None and parsed.GetNumConformers() == 1

    record = ingest_record_from_mol(parsed, [])
    stripped = Chem.Mol(record.structure)
    assert stripped is not None and stripped.GetNumConformers() == 0
    kept = unpack_xy(record.depiction)
    assert kept is not None and len(kept) == parsed.GetNumAtoms()
    src = parsed.GetConformer()
    for i, (x, y) in enumerate(kept):
        pos = src.GetAtomPosition(i)
        assert abs(x - float(pos.x)) < 1e-4
        assert abs(y - float(pos.y)) < 1e-4

    w = ChemistryWorkspaceWindow()
    rows: list = []
    w._ingest_append_batch_items([record], rows)
    oid = rows[0][0]
    stored = w.mols[oid]
    assert stored.GetNumConformers() == 0
    placed = apply_depiction_coords(stored, w._depiction_coords.get("Structure", oid))
    assert placed is not stored and placed.GetNumConformers() == 1
    drawn = placed.GetConformer()
    for i, (x, y) in enumerate(kept):
        pos = drawn.GetAtomPosition(i)
        assert abs(float(pos.x) - x) < 1e-4
        assert abs(float(pos.y) - y) < 1e-4

    assert ingest_record_from_mol(_ethanol_3d(), ["SMILES"]).depiction == b""
    w.close()
