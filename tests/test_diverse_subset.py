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

"""Diverse subset (MaxMin) picking."""

from __future__ import annotations

import threading

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.chem.fingerprint_cache import clear as clear_fp_cache
from molmanager.chem.fingerprint_cache import get as cache_get
from molmanager.chem.fingerprint_cache import store_from_mol
from molmanager.workers.diverse_subset_worker import (
    DIVERSE_SUBSET_MODE_LABELS,
    DiverseSubsetPoolRow,
    DiverseSubsetRequest,
    DiverseSubsetWorker,
    build_diverse_subset_pool,
    materialize_pool_fingerprints,
    maxmin_diverse_pick_bulk,
    maxmin_diverse_pick_indices,
    maxmin_diverse_pick_lazy,
    prefilter_candidate_indices,
    resolve_diverse_mode,
    run_diverse_subset_pick,
    staged_maxmin_diverse_pick,
)
from molmanager.workers.signals import DiverseSubsetSignals


def _morgan_fps(smis: list[str]):
    mols = [Chem.MolFromSmiles(s) for s in smis]
    assert all(m is not None for m in mols)
    return [AllChem.GetMorganFingerprintAsBitVect(m, 2, 2048) for m in mols]


def test_maxmin_pick_size_and_spread():
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O", "CCC"]
    fps = _morgan_fps(smis)
    picks = maxmin_diverse_pick_indices(fps, 3, seed=42)
    assert len(picks) == 3
    assert len(set(picks)) == 3
    assert not ({2, 3} <= set(picks))


def test_maxmin_returns_all_when_k_ge_n():
    fps = _morgan_fps(["CCO", "CCC", "CCCC"])
    picks = maxmin_diverse_pick_indices(fps, 10)
    assert picks == [0, 1, 2]


def test_bulk_pick_matches_lazy_on_small_pool():
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O", "CCC"]
    fps = _morgan_fps(smis)
    bulk = maxmin_diverse_pick_bulk(fps, 3, seed=42)
    lazy = maxmin_diverse_pick_indices(fps, 3, seed=42)
    assert len(bulk) == len(lazy) == 3
    assert len(set(bulk)) == 3


def test_lazy_pick_uses_cached_fp_without_mol():
    smis = ["CCO", "c1ccccc1", "CC(=O)O", "CCC"]
    mols = [Chem.MolFromSmiles(s) for s in smis]
    fps = _morgan_fps(smis)
    pool = [
        DiverseSubsetPoolRow(oid=i, mol=mols[i] if i == 0 else None, fp=fps[i]) for i in range(4)
    ]
    picks = maxmin_diverse_pick_lazy(pool, "Morgan (r=2, n=2048)", 2, seed=1)
    assert len(picks) == 2


def test_build_pool_uses_onbits_column_filter():
    clear_fp_cache()
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    store_from_mol(1, "FP_Morgan_2_2048", mol)
    rows = [(1, mol), (2, mol)]
    pool_all, _ = build_diverse_subset_pool(rows, "Morgan (r=2, n=2048)")
    assert len(pool_all) == 2
    assert cache_get(1, "FP_Morgan_2_2048") is not None
    pool_filt, _ = build_diverse_subset_pool(
        rows,
        "Morgan (r=2, n=2048)",
        onbits_by_oid={1: "12", 2: "N/A"},
        require_onbits_column=True,
    )
    assert len(pool_filt) == 1
    assert pool_filt[0].fp is not None


def test_materialize_stores_fps_in_parent_cache():
    clear_fp_cache()
    smis = ["CCO", "c1ccccc1", "CC(=O)O"]
    pool = []
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        pool.append(DiverseSubsetPoolRow(oid=100 + i, mol=m, fp=None))
    fps, n_cached, n_computed = materialize_pool_fingerprints(
        pool, "Morgan (r=2, n=2048)", "FP_Morgan_2_2048", use_process_pool=False
    )
    assert n_cached == 0
    assert n_computed == 3
    assert len(fps) == 3
    assert cache_get(100, "FP_Morgan_2_2048") is not None
    assert cache_get(102, "FP_Morgan_2_2048") is not None


def test_staged_pick_size_and_uniqueness():
    # Build a larger synthetic pool so staging actually prefilters.
    smis = [
        "CCO",
        "CCCO",
        "CCCCO",
        "c1ccccc1",
        "Cc1ccccc1",
        "Clc1ccccc1",
        "CC(=O)O",
        "CCC(=O)O",
        "C=C",
        "C#N",
        "CCN",
        "c1ccncc1",
    ]
    fps = _morgan_fps(smis)
    picks = staged_maxmin_diverse_pick(fps, 4, candidate_cap=6, seed=7)
    assert len(picks) == 4
    assert len(set(picks)) == 4
    assert all(0 <= i < len(fps) for i in picks)


def test_prefilter_respects_cap():
    fps = _morgan_fps([f"{'C' * (i + 1)}O" for i in range(20)])
    idx = prefilter_candidate_indices(fps, 8, seed=1)
    assert len(idx) <= 8
    assert len(idx) == len(set(idx))


def test_resolve_diverse_mode_auto():
    assert resolve_diverse_mode("exact", 100_000) == "exact"
    assert resolve_diverse_mode("fast", 10) == "fast"
    assert resolve_diverse_mode("auto", 10, exact_max_rows=50) == "exact"
    assert resolve_diverse_mode("auto", 100, exact_max_rows=50) == "fast"


def test_run_diverse_subset_pick_fast_mode():
    clear_fp_cache()
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O", "CCC", "C=C", "CCN"]
    pool = []
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        pool.append(DiverseSubsetPoolRow(oid=i, mol=m, fp=None))
    picks, _nc, _ncomp = run_diverse_subset_pick(
        pool,
        "Morgan (r=2, n=2048)",
        3,
        "FP_Morgan_2_2048",
        mode="fast",
        candidate_cap=5,
        use_process_pool=False,
    )
    assert len(picks) == 3
    assert len(set(picks)) == 3


def test_diverse_subset_worker_cancel():
    smis = ["CCO", "CCCO", "c1ccccc1", "CC(=O)O", "CCC", "C=C"]
    rows = []
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        rows.append((i, m))
    sig = _CaptureSignals()
    ev = threading.Event()
    ev.set()
    worker = DiverseSubsetWorker(
        DiverseSubsetRequest(rows=rows, fp_choice="Morgan (r=2, n=2048)", subset_size=4),
        sig,
        cancel_event=ev,
    )
    worker.run()
    assert sig.err == "Cancelled."
    assert sig.picked == []


class _CaptureSignals(DiverseSubsetSignals):
    def __init__(self) -> None:
        super().__init__(None)
        self.picked: list[int] = []
        self.rows: list = []
        self.n_cached = 0
        self.n_computed = 0
        self.err: str | None = None
        self.finished.connect(self._on_done)
        self.failed.connect(self._on_fail)

    def _on_done(self, picked, rows, n_cached, n_computed) -> None:
        self.picked = list(picked)
        self.rows = list(rows)
        self.n_cached = int(n_cached)
        self.n_computed = int(n_computed)

    def _on_fail(self, msg: str) -> None:
        self.err = msg


def test_diverse_subset_worker_picks_k():
    smis = ["CCO", "CCCO", "c1ccccc1", "CC(=O)O", "CCC", "C=C"]
    rows = []
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        rows.append((i, m))
    sig = _CaptureSignals()
    worker = DiverseSubsetWorker(
        DiverseSubsetRequest(
            rows=rows, fp_choice="Morgan (r=2, n=2048)", subset_size=4, mode="exact"
        ),
        sig,
    )
    worker.run()
    assert sig.err is None
    assert len(sig.picked) == 4
    assert len(sig.rows) == 4
    ranks = {oid: rank for oid, rank in sig.rows}
    assert set(ranks.values()) == {"1", "2", "3", "4"}


def test_prefilter_skips_leader_on_large_pools(monkeypatch):
    """BindingDB-scale pools must not run LeaderPicker (would freeze)."""
    calls = {"n": 0}

    def _boom(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("Leader should not run on large pools")

    monkeypatch.setattr(
        "molmanager.workers.diverse_subset_worker._leader_candidate_indices",
        _boom,
    )
    fps = list(range(30_000))  # opaque stand-ins; Leader is never called
    idx = prefilter_candidate_indices(fps, 100, seed=3, leader_max_rows=25_000)
    assert calls["n"] == 0
    assert len(idx) == 100
    assert len(set(idx)) == 100


def test_diverse_subset_worker_resolves_oids_via_app():
    class _App:
        def __init__(self, mols: dict[int, Chem.Mol]):
            self.mols = mols

    smis = ["CCO", "c1ccccc1", "CC(=O)O", "CCC"]
    mols = {}
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        mols[i] = m
    sig = _CaptureSignals()
    worker = DiverseSubsetWorker(
        DiverseSubsetRequest(
            fp_choice="Morgan (r=2, n=2048)",
            subset_size=2,
            oids=list(mols.keys()),
            structure_source="Structure",
            mode="exact",
        ),
        sig,
        app=_App(mols),
    )
    worker.run()
    assert sig.err is None
    assert len(sig.picked) == 2


def test_diverse_subset_worker_resolves_mols_by_oid_snapshot():
    smis = ["CCO", "c1ccccc1", "CC(=O)O", "CCC"]
    mols = {}
    for i, s in enumerate(smis):
        m = Chem.MolFromSmiles(s)
        assert m is not None
        mols[i] = m
    sig = _CaptureSignals()
    worker = DiverseSubsetWorker(
        DiverseSubsetRequest(
            fp_choice="Morgan (r=2, n=2048)",
            subset_size=2,
            oids=list(mols.keys()),
            mols_by_oid=mols,
            mode="exact",
        ),
        sig,
    )
    worker.run()
    assert sig.err is None
    assert len(sig.picked) == 2


def test_diverse_subset_worker_resolves_structure_texts():
    smis = ["CCO", "c1ccccc1", "CC(=O)O", "CCC"]
    texts = [(i, s) for i, s in enumerate(smis)]
    sig = _CaptureSignals()
    worker = DiverseSubsetWorker(
        DiverseSubsetRequest(
            fp_choice="Morgan (r=2, n=2048)",
            subset_size=2,
            oids=[i for i, _ in texts],
            structure_texts=texts,
            mode="exact",
        ),
        sig,
    )
    worker.run()
    assert sig.err is None
    assert len(sig.picked) == 2


def test_diverse_subset_dialog_mode_uses_item_data(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.diverse_subset import DiverseSubsetDialog

    dlg = DiverseSubsetDialog(None)
    try:
        assert dlg.fp_combo.currentText() == "Morgan (r=2, n=2048)"
        keys = [dlg.mode_combo.itemData(i) for i in range(dlg.mode_combo.count())]
        assert keys == [k for k, _ in DIVERSE_SUBSET_MODE_LABELS]
        dlg.mode_combo.setCurrentIndex(keys.index("fast"))
        assert dlg._selected_mode_key() == "fast"
    finally:
        dlg.close()
