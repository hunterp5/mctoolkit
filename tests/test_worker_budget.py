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

"""Shared process-pool sizing from free RAM and per-worker cost."""

from __future__ import annotations

from molmanager.platform_support.memory_guards import check_fp_matrix_workload
from molmanager.platform_support.worker_budget import (
    RDKIT_PROCESS_BYTES,
    UNIPKA_PROCESS_BYTES,
    plan_process_workers,
    rdkit_process_workers,
)


def _pin_available(monkeypatch, nbytes: int) -> None:
    monkeypatch.setattr(
        "molmanager.platform_support.memory_usage.available_physical_bytes",
        lambda: nbytes,
    )


def test_unipka_auto_fits_one_worker_in_a_small_budget(monkeypatch) -> None:
    _pin_available(monkeypatch, 5 * 1024**3)
    workers = plan_process_workers(
        per_worker_bytes=UNIPKA_PROCESS_BYTES,
        cpu_cap=8,
        n_tasks=20,
        min_workers=1,
    )
    assert workers == 1


def test_unipka_auto_uses_the_cpu_cap_when_ram_is_plentiful(monkeypatch) -> None:
    _pin_available(monkeypatch, 64 * 1024**3)
    workers = plan_process_workers(
        per_worker_bytes=UNIPKA_PROCESS_BYTES,
        cpu_cap=8,
        n_tasks=20,
        min_workers=1,
    )
    assert workers == 8


def test_configured_worker_count_ignores_free_ram(monkeypatch) -> None:
    _pin_available(monkeypatch, 3 * 1024**3)
    workers = plan_process_workers(
        per_worker_bytes=UNIPKA_PROCESS_BYTES,
        cpu_cap=8,
        n_tasks=20,
        configured=4,
        configured_cap=8,
    )
    assert workers == 4


def test_rdkit_pool_shrinks_when_the_budget_is_small(monkeypatch) -> None:
    # Reserve is 2 GiB, so 2.2 GiB free leaves about 0.2 GiB: a few RDKit children.
    _pin_available(monkeypatch, int(2.2 * 1024**3))
    workers = rdkit_process_workers(32)
    affordable = int(0.2 * 1024**3) // RDKIT_PROCESS_BYTES
    assert workers == max(2, affordable)


def test_fp_matrix_guard_rejects_when_the_estimate_exceeds_free_ram(monkeypatch) -> None:
    _pin_available(monkeypatch, 2 * 1024**3)
    result = check_fp_matrix_workload(25_000, n_bits=2048)
    assert not result.ok
    assert "free" in result.message
