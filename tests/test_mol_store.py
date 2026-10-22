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

from __future__ import annotations

from rdkit import Chem

from molmanager.storage.mol_store import MolStore


def test_mol_store_persists_and_lru_evicts():
    store = MolStore(lru_max=8)
    try:
        mol = Chem.MolFromSmiles("CCO")
        store[3] = mol
        assert 3 in store
        assert Chem.MolToSmiles(store[3]) == "CCO"
        blob = store.blob_for(3)
        assert blob
        store._lru.clear()
        again = store.get(3)
        assert again is not None
        assert Chem.MolToSmiles(again) == "CCO"
        store.pop(3)
        assert 3 not in store
        assert store.get(3) is None
    finally:
        store.close()


def test_mol_store_ingest_jobs_does_not_hydrate():
    store = MolStore(lru_max=8)
    try:
        parent = Chem.MolFromSmiles("CCN")
        blob = parent.ToBinary()
        store.ingest_jobs([(1, blob, "not-a-smiles"), (2, None, "CCO")])
        assert len(store) == 2
        assert len(store._lru) == 0
        assert Chem.MolToSmiles(store[1]) == "CCN"
        assert Chem.MolToSmiles(store[2]) == "CCO"
        assert 1 in store._lru
    finally:
        store.close()


def test_mol_store_ingest_jobs_replaces_cached_mol():
    store = MolStore(lru_max=8)
    try:
        store[1] = Chem.MolFromSmiles("CC[NH3+]")
        assert 1 in store._lru
        store.ingest_jobs([(1, Chem.MolFromSmiles("CCN").ToBinary(), "CCN")])
        assert Chem.MolToSmiles(store[1]) == "CCN"
    finally:
        store.close()


def test_mol_store_structure_text_for():
    store = MolStore(lru_max=8)
    try:
        inchi = Chem.MolToInchi(Chem.MolFromSmiles("CCO"))
        store.ingest_jobs(
            [
                (1, Chem.MolFromSmiles("OCC").ToBinary(), ""),
                (2, None, "c1ccccc1"),
                (3, None, inchi),
            ]
        )
        assert store.structure_text_for(1) == "CCO"
        assert list(store.structure_payloads_for([1]))[0][2] == "CCO"
        assert store.structure_text_for(2) == "c1ccccc1"
        assert store.structure_text_for(3) == inchi
        assert Chem.MolToSmiles(store[3]) == "CCO"
        assert store.structure_text_for(99) == ""
    finally:
        store.close()


def test_mol_store_structure_payloads_for_returns_only_requested():
    store = MolStore(lru_max=8)
    try:
        store.ingest_jobs([(oid, None, "C" * (oid + 1)) for oid in range(2000)])
        got = {oid: smi for oid, _blob, smi in store.structure_payloads_for([5, 1500, 9999])}
        assert got == {5: "C" * 6, 1500: "C" * 1501}
        assert list(store.structure_payloads_for([])) == []
    finally:
        store.close()
