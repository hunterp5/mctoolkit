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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Compact ensemble codec and disk-backed EnsembleStore."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Geometry import Point3D

from molmanager.conformers.conformer_column_codec import (
    demote_v1_cell_to_sidecar,
    mol_from_packed_confs_cell,
    pack_confs_cell,
    rehydrate_v1_confs_cell,
)
from molmanager.conformers.ensemble_binary_codec import pack_ensemble_mol, unpack_ensemble_mol
from molmanager.storage import EnsembleStore, ensure_confs_sidecar


def _ethanol_ensemble(n: int = 3) -> Chem.Mol:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    for i in range(n):
        conf = Chem.Conformer(mol.GetNumAtoms())
        conf.SetAtomPosition(0, Point3D(float(i), 0.0, 0.0))
        conf.SetAtomPosition(1, Point3D(float(i) + 1.4, 0.0, 0.0))
        conf.SetAtomPosition(2, Point3D(float(i) + 2.0, 1.1, 0.0))
        mol.AddConformer(conf, assignId=True)
    return mol


def test_pack_unpack_ensemble_mol_roundtrip():
    mol = _ethanol_ensemble(4)
    blob = pack_ensemble_mol(mol)
    assert blob
    back = unpack_ensemble_mol(blob)
    assert back is not None
    assert back.GetNumAtoms() == mol.GetNumAtoms()
    assert back.GetNumConformers() == 4
    orig = mol.GetConformer(2).GetAtomPosition(0)
    got = back.GetConformer(2).GetAtomPosition(0)
    assert abs(float(orig.x) - float(got.x)) < 1e-4


def test_ensemble_store_set_get_and_export_import():
    mol = _ethanol_ensemble(3)
    packed = pack_confs_cell({"ok": True, "n_kept": 3, "n_packed": 3}, mol)
    _light, b64 = demote_v1_cell_to_sidecar(packed, "confs")
    assert b64
    store = EnsembleStore()
    other = EnsembleStore()
    try:
        assert store.store_mol(7, "confs", mol)
        got = store.mol_for(7, "confs")
        assert got is not None
        assert got.GetNumConformers() == 3
        store[(8, "poses")] = b64
        assert (8, "poses") in store
        viewer = store[(8, "poses")]
        full = rehydrate_v1_confs_cell(
            '{"v":2,"h":"poses","m":{}}', "poses", 8, {(8, "poses"): viewer}
        )
        rebuilt = mol_from_packed_confs_cell(full, min_conformers=3)
        assert rebuilt is not None
        blob = store.export_sqlite_bytes({7})
        other.import_sqlite_bytes(blob, replace=True)
        assert (7, "confs") in other
        assert (8, "poses") not in other
        store.copy_oid(7, 9, ["confs"])
        assert (9, "confs") in store
        store.discard_oids([7])
        assert (7, "confs") not in store
    finally:
        store.close()
        other.close()


def test_ensemble_import_merges_without_materializing_rows():
    store = EnsembleStore()
    other = EnsembleStore()
    try:
        assert store.store_mol(1, "confs", _ethanol_ensemble(2))
        assert other.store_mol(2, "confs", _ethanol_ensemble(2))
        other.import_sqlite_bytes(store.export_sqlite_bytes(), replace=False)
        assert (1, "confs") in other
        assert (2, "confs") in other
        assert other.mol_for(1, "confs").GetNumConformers() == 2
    finally:
        store.close()
        other.close()


def test_ensure_confs_sidecar_upgrades_dict():
    class Holder:
        _confs_blocks_sidecar = {(1, "confs"): "YWFh"}

    holder = Holder()
    store = ensure_confs_sidecar(holder)
    try:
        assert isinstance(store, EnsembleStore)
        assert holder._confs_blocks_sidecar is store
        assert store[(1, "confs")] == "YWFh"
    finally:
        store.close()


def test_ensemble_mol_for_reads_sqlite_path():
    from molmanager.storage import ensemble_mol_for

    mol = _ethanol_ensemble(3)
    store = EnsembleStore()
    try:
        assert store.store_mol(4, "confs", mol)
        got = ensemble_mol_for(store.db_path, 4, "confs", min_conformers=3)
        assert got is not None
        assert got.GetNumConformers() == 3
        assert ensemble_mol_for(store.db_path, 4, "confs", min_conformers=9) is None
        assert ensemble_mol_for(store.db_path, 99, "confs") is None
    finally:
        store.close()


def test_write_ensemble_worker_results_stores_mol(qapp):  # noqa: ARG001
    from molmanager.conformers.conformer_column_codec import unpack_confs_blocks_json_b64
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.main_window.conformer_writeback import write_ensemble_worker_results

    mol = _ethanol_ensemble(2)
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "confs": ""})
    try:
        write_ensemble_worker_results(
            w, "confs", [(0, mol, {"ok": True, "n_kept": 2, "n_packed": 2})]
        )
        cell = w._table_model.value_for_header(0, "confs")
        assert unpack_confs_blocks_json_b64(cell) is None
        got = w._confs_blocks_sidecar.mol_for(0, "confs")
        assert got is not None
        assert got.GetNumConformers() == 2
    finally:
        w.close()


def test_superpose_row_task_fetches_by_oid():
    from molmanager.workers.superpose import SuperposeParams, _superpose_row_task

    mol = _ethanol_ensemble(3)
    store = EnsembleStore()
    try:
        assert store.store_mol(1, "confs", mol)
        oid, out, meta = _superpose_row_task(
            (1, "confs", SuperposeParams(reference_conformer_index=0), None, str(store.db_path))
        )
        assert oid == 1
        assert out is not None
        assert isinstance(meta, dict)
        assert meta.get("ok") is True
        assert out.GetNumConformers() == 3
    finally:
        store.close()


def test_ensemble_store_batches_commits_and_still_reads():
    mol = _ethanol_ensemble(2)
    store = EnsembleStore()
    try:
        for oid in range(80):
            assert store.store_mol(oid, "confs", mol)
        assert store._pending < 64
        got = store.mol_for(79, "confs")
        assert got is not None
        assert got.GetNumConformers() == 2
        assert (0, "confs") in store
        path = store.db_path
        from molmanager.storage import ensemble_mol_for

        other = ensemble_mol_for(path, 40, "confs", min_conformers=2)
        assert other is not None
    finally:
        store.close()
