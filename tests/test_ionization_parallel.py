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

"""Ionization process-pool planning and structure cache."""

from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest
from rdkit import Chem

import molmanager.workers.ionization_parallel as ionization_parallel
from molmanager.ionization.unipka_ensembles import PicklableMicrostate, microstates_to_picklable
from molmanager.ionization.microstate_cache import clear as cache_clear
from molmanager.workers.ionization_parallel import plan_ionization_process_workers


@pytest.fixture(autouse=True)
def _force_sequential_ionization_cache(monkeypatch) -> None:
    """Tests that mock ``microstates_for_mol`` must not spawn a real process pool."""
    monkeypatch.setenv("MOLMANAGER_PKA_PROCESS_WORKERS", "1")
    monkeypatch.setattr(
        ionization_parallel,
        "plan_ionization_process_workers",
        lambda _n, _c: (False, 1),
    )
    yield
    ionization_parallel.discard_ionization_process_pool()


def test_plan_ionization_auto_uses_mp_from_two_unique(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: False)
    monkeypatch.setattr(
        "molmanager.platform_support.memory_usage.available_physical_bytes",
        lambda: 32 * 1024**3,
    )
    use_mp, workers = plan_ionization_process_workers(3, None)
    assert use_mp is True
    assert workers == 1


def test_plan_ionization_stays_one_process_when_ram_is_plentiful(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: False)
    monkeypatch.setattr(
        "molmanager.platform_support.memory_usage.available_physical_bytes",
        lambda: 64 * 1024**3,
    )
    use_mp, workers = plan_ionization_process_workers(20, None)
    assert use_mp is True
    assert workers == 1
    use_mp, workers = plan_ionization_process_workers(20, 8)
    assert workers == 1


def test_plan_ionization_auto_is_one_worker_when_ram_is_tight(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: False)
    monkeypatch.setattr(
        "molmanager.platform_support.memory_usage.available_physical_bytes",
        lambda: 3 * 1024**3,
    )
    use_mp, workers = plan_ionization_process_workers(12, None)
    assert use_mp is True
    assert workers == 1


def test_plan_ionization_cuda_uses_one_worker_pool(monkeypatch) -> None:
    monkeypatch.setattr(ionization_parallel, "unipka_cuda_available", lambda: True)
    use_mp, workers = plan_ionization_process_workers(12, None)
    assert use_mp is True
    assert workers == 1
    use_mp, workers = plan_ionization_process_workers(12, 0)
    assert use_mp is False
    assert workers == 1


def test_chunk_structure_keys_spreads_across_workers() -> None:
    from molmanager.workers.ionization_parallel import chunk_structure_keys

    keys = [f"k{i}" for i in range(10)]
    chunks = chunk_structure_keys(keys, 2)
    assert len(chunks) >= 2
    assert sum(len(c) for c in chunks) == 10
    assert max(len(c) for c in chunks) <= 8
    assert chunk_structure_keys([], 4) == []


def test_chunk_structure_keys_single_worker_batches_and_splits() -> None:
    from molmanager.workers.ionization_parallel import (
        UNIPKA_STRUCTURE_CHUNK_SERIAL,
        chunk_structure_keys,
    )

    keys = [f"k{i}" for i in range(32)]
    chunks = chunk_structure_keys(keys, 1)
    assert sum(len(c) for c in chunks) == 32
    assert max(len(c) for c in chunks) == UNIPKA_STRUCTURE_CHUNK_SERIAL
    assert len(chunks) == 2


def test_structure_progress_flags_mark_prefix() -> None:
    from molmanager.workers.ionization_parallel import (
        flagged_unique_count,
        mark_structure_progress,
        structure_progress_flags,
    )

    flags = structure_progress_flags(4)
    assert flags is not None
    mark_structure_progress(flags, [1, 2, 3], 2)
    assert flagged_unique_count(flags, 4) == 2
    assert flags[1] == 1
    assert flags[2] == 1
    assert flags[0] == 0
    assert flags[3] == 0


def test_map_ionization_progress_protonate_moves_before_last_tick() -> None:
    from molmanager.workers.ionization_parallel import map_ionization_progress

    done, total = map_ionization_progress(1, 3, progress_total=3, reserve_final_tick=False)
    assert (done, total) == (1, 3)
    done, total = map_ionization_progress(3, 3, progress_total=3, reserve_final_tick=False)
    assert (done, total) == (3, 3)
    # Descriptor jobs still leave the last tick, but the first unique is not stuck at 0.
    done, total = map_ionization_progress(1, 3, progress_total=3, reserve_final_tick=True)
    assert total == 3
    assert done >= 1
    assert done < 3


def test_plan_ionization_respects_force_sequential() -> None:
    use_mp, workers = plan_ionization_process_workers(10, 1)
    assert workers == 1
    _ = use_mp


def test_build_microstates_cache_reports_progress_during_sequential(monkeypatch) -> None:
    cache_clear()
    monkeypatch.setattr(
        ionization_parallel,
        "plan_ionization_process_workers",
        lambda _n, _c: (False, 1),
    )
    monkeypatch.setattr(
        "molmanager.ionization.unipka_ensembles.microstates_for_mol",
        lambda _mol: [{"pka": 7.0}],
    )
    seen: list[tuple[int, int]] = []

    def _capture(**kwargs):
        seen.append((int(kwargs["done"]), int(kwargs["total"])))

    monkeypatch.setattr("molmanager.platform_support.tool_progress.report_tool_progress", _capture)
    mols = [Chem.MolFromSmiles(s) for s in ("CCO", "CCN", "CCC")]
    assert all(m is not None for m in mols)
    ionization_parallel.build_microstates_cache_by_key(
        mols,
        progress_message="Protonate",
        progress_total=3,
        reserve_final_tick=False,
    )
    assert seen
    assert any(done > 0 and done < 3 for done, _total in seen)
    assert seen[-1][0] == 3


def test_build_microstates_cache_dedupes(monkeypatch) -> None:
    cache_clear()
    calls: list[str] = []

    def _fake_microstates(mol):
        from molmanager.workers.structure_grouping import structure_key

        calls.append(structure_key(mol))
        return [{"pka": 7.0}]

    monkeypatch.setattr(
        "molmanager.ionization.unipka_ensembles.microstates_for_mol",
        _fake_microstates,
    )

    m = Chem.MolFromSmiles("CCO")
    assert m is not None
    cache = ionization_parallel.build_microstates_cache_by_key(
        [Chem.Mol(m), Chem.Mol(m), Chem.MolFromSmiles("CCN")]
    )
    assert len(calls) == 2
    assert len(cache) == 2


def test_microstates_to_picklable_roundtrip() -> None:
    pm = Chem.MolFromSmiles("CCO")
    dm = Chem.MolFromSmiles("CC[O-]")
    assert pm is not None and dm is not None
    raw = [SimpleNamespace(pka=15.9, protonated_mol=pm, deprotonated_mol=dm, ph7_mol=pm)]
    snap = microstates_to_picklable(raw)
    assert snap[0].pka == 15.9
    assert isinstance(snap[0], PicklableMicrostate)
    assert snap[0].protonated_mol is not None


class _FakeIonizationPool:
    def __init__(self, max_workers=1):
        self.max_workers = max_workers
        self._broken = False
        self._shutdown_thread = False
        self._processes = {}

    def shutdown(self, **_kwargs) -> None:
        self._shutdown_thread = True


def _patch_fake_ionization_pool(monkeypatch, created: list[_FakeIonizationPool]) -> None:
    def _fake_pool(*args, max_workers=1, **_kwargs):
        if args:
            max_workers = args[0]
        pool = _FakeIonizationPool(max_workers=max_workers)
        created.append(pool)
        return pool

    monkeypatch.setattr(ionization_parallel, "ProcessPoolExecutor", _fake_pool)
    monkeypatch.setattr(ionization_parallel, "register_process_pool", lambda ex: ex)
    ionization_parallel.discard_ionization_process_pool()


def test_ionization_process_pool_reuses_one_worker(monkeypatch) -> None:
    created: list[_FakeIonizationPool] = []
    _patch_fake_ionization_pool(monkeypatch, created)
    with ionization_parallel.ionization_process_pool(1) as first:
        pass
    with ionization_parallel.ionization_process_pool(1) as second:
        assert second is first
    assert len(created) == 1
    assert created[0]._shutdown_thread is False
    ionization_parallel.discard_ionization_process_pool()
    assert created[0]._shutdown_thread is True


def test_ionization_process_pool_kills_one_worker_on_cancel(monkeypatch) -> None:
    created: list[_FakeIonizationPool] = []
    _patch_fake_ionization_pool(monkeypatch, created)
    cancel = threading.Event()
    cancel.set()
    with ionization_parallel.ionization_process_pool(1, cancel_event=cancel):
        pass
    assert len(created) == 1
    assert created[0]._shutdown_thread is True
    with ionization_parallel.ionization_process_pool(1) as nxt:
        assert nxt is not created[0]
    assert len(created) == 2


def test_ionization_process_pool_multi_worker_is_ephemeral(monkeypatch) -> None:
    created: list[_FakeIonizationPool] = []
    _patch_fake_ionization_pool(monkeypatch, created)
    with ionization_parallel.ionization_process_pool(2) as first:
        assert first.max_workers == 2
    with ionization_parallel.ionization_process_pool(2) as second:
        assert second is not first
    assert len(created) == 2
    assert all(pool._shutdown_thread for pool in created)
