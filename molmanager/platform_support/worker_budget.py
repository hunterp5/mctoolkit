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

"""How many child processes a tool may start.

Each pool used to write its own ``min(8, cpu - 1)``. That ignores what a child
actually holds, so a heavy tool could launch several ~1.9 GB processes on a laptop.
Callers ask here instead. An explicit env override is not reduced to fit free RAM.
Uni-pKa scoring itself stays one process and does not ask for a worker count.
"""

from __future__ import annotations

import os

# Private bytes for one child after imports and a real job (Windows, Oct 2026).
# One full Uni-pKa process peaked near 1.9 GB before scoring was limited to one.
# Render 2D settled near 30 MB.
# Other RDKit children are the interpreter plus a batch of molecules.
UNIPKA_PROCESS_BYTES = 1_900 * 1024 * 1024
RENDER2D_PROCESS_BYTES = 32 * 1024 * 1024
RDKIT_PROCESS_BYTES = 48 * 1024 * 1024


def ram_reserve_bytes(available: int) -> int:
    """RAM left for the OS, the GUI, and the open table.

    At least 2 GiB, or a quarter of what is still free, whichever is larger.
    """
    avail = max(0, int(available))
    return max(2 * 1024**3, avail // 4)


def worker_memory_budget_bytes() -> int | None:
    """Bytes a new job may use without eating the reserve, or None if unknown."""
    from .memory_usage import available_physical_bytes

    avail = available_physical_bytes()
    if avail is None:
        return None
    return max(0, int(avail) - ram_reserve_bytes(int(avail)))


def plan_process_workers(
    *,
    per_worker_bytes: int,
    cpu_cap: int,
    n_tasks: int | None = None,
    configured: int | None = None,
    min_workers: int = 1,
    configured_cap: int | None = None,
) -> int:
    """How many child processes to start.

    *configured* is an env override and is not shrunk to fit free RAM. It is still
    limited by *n_tasks* and *configured_cap*. The automatic count is the minimum
    of the CPU cap, the task count, and ``(available RAM - reserve) / per-worker cost``.
    *min_workers* is kept even when the budget is tight, so a cheap pool does not
    drop below the size it was written for.
    """
    if configured is not None:
        count = max(1, int(configured))
        if configured_cap is not None:
            count = min(count, max(1, int(configured_cap)))
        if n_tasks is not None:
            count = min(count, max(1, int(n_tasks)))
        return count

    cpu_n = max(1, int(cpu_cap))
    floor = max(1, min(int(min_workers), cpu_n))
    cost = max(0, int(per_worker_bytes))
    budget = worker_memory_budget_bytes()
    if budget is None or cost <= 0:
        count = cpu_n
    else:
        affordable = max(0, int(budget) // cost)
        count = min(cpu_n, max(affordable, floor))
    if n_tasks is not None:
        count = min(count, max(1, int(n_tasks)))
    return max(1, count)


def rdkit_process_workers(
    n_tasks: int | None = None,
    *,
    hard_cap: int = 8,
    min_workers: int = 2,
) -> int:
    """Automatic worker count for an RDKit child process pool."""
    floor = max(1, int(min_workers))
    cpu_cap = min(int(hard_cap), max(floor, (os.cpu_count() or 4) - 1))
    return plan_process_workers(
        per_worker_bytes=RDKIT_PROCESS_BYTES,
        cpu_cap=cpu_cap,
        n_tasks=n_tasks,
        min_workers=floor,
    )
