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

"""Clustering leaves the GUI process when fingerprint or fit work would hold the GIL."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.chem.fingerprint_cache import clear as clear_fp_cache
from molmanager.workers.cluster_worker import (
    ClusterWorker,
    _explore_trials_off_gil,
    _fit_labels_off_gil,
    _use_fit_process_pool,
    _use_fp_process_pool,
    cluster_butina,
)
from molmanager.workers.signals import WorkerSignals


def test_fp_process_pool_for_gil_heavy_and_large_tables(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "64")
    assert _use_fp_process_pool(3, "2D pharmacophore (Gobbi)")
    assert not _use_fp_process_pool(3, "Morgan (r=2, n=1024)")
    assert _use_fp_process_pool(64, "Morgan (r=2, n=1024)")


def test_fit_process_pool_stays_on_when_fp_threshold_is_raised(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "5000")
    assert _use_fit_process_pool(64)
    assert not _use_fit_process_pool(63)


def test_fit_process_pool_follows_a_lower_fp_threshold(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "10")
    assert _use_fit_process_pool(10)
    assert not _use_fit_process_pool(9)


def _morgan_fps() -> list:
    smiles = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1"]
    fps = []
    for smi in smiles:
        mol = Chem.MolFromSmiles(smi)
        assert mol is not None
        fps.append(AllChem.GetMorganFingerprintAsBitVect(mol, 2, 1024))
    return fps


def test_fit_off_gil_matches_in_process_butina(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "2")
    fps = _morgan_fps()
    direct = cluster_butina(fps, 0.4)
    off = _fit_labels_off_gil(
        "butina",
        {"cutoff": 0.4, "reordering": False},
        fps,
        None,
    )
    assert direct is not None
    assert off is not None
    assert [int(v) for v in off] == [int(v) for v in direct]


def test_explore_off_gil_returns_butina_summary(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "2")
    clear_fp_cache()
    results, cancelled = _explore_trials_off_gil(
        _morgan_fps(),
        [("butina", {"cutoff": 0.4, "reordering": False})],
        cancel_event=None,
        on_trial=None,
    )
    assert cancelled is False
    assert len(results) == 1
    assert results[0]["method"] == "butina"
    assert results[0]["notes"] == ""
    assert results[0]["n_clusters"] is not None


def test_cluster_worker_process_pool_emits_labels(monkeypatch, qapp):
    del qapp
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "2")
    clear_fp_cache()
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))
    sigs.cluster_failed.connect(lambda msg: out.update({"failed": msg}))
    smiles = ["CCO", "CCN", "CCC", "c1ccccc1"]
    rows = []
    for oid, smi in enumerate(smiles, start=1):
        mol = Chem.MolFromSmiles(smi)
        assert mol is not None
        rows.append((oid, mol))
    worker = ClusterWorker(
        rows=rows,
        fp_choice="Morgan (r=2, n=1024)",
        method="butina",
        params={"cutoff": 0.35, "reordering": False},
        column_name="Cluster",
        signals=sigs,
    )
    worker.run()
    assert "failed" not in out
    got = out.get("rows")
    assert isinstance(got, list)
    assert len(got) == 4
    assert out.get("headers") == ["Cluster"]
    assert all(str(cols["Cluster"]) for _oid, cols in got)
