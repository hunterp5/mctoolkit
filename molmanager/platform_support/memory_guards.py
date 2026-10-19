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

"""Hard caps and preflight checks for large memory-heavy tools."""

from __future__ import annotations

from dataclasses import dataclass

from .config import load_config
from .memory_usage import available_physical_bytes, current_process_rss_bytes, format_memory_bytes
from .worker_budget import worker_memory_budget_bytes


@dataclass(frozen=True)
class MemoryGuardResult:
    """Outcome of a preflight check before starting a heavy job."""

    ok: bool
    message: str = ""
    estimated_extra_bytes: int | None = None


def _rss_hint() -> str:
    rss = current_process_rss_bytes()
    if rss is None:
        return ""
    return f" Current process memory: {format_memory_bytes(rss)}."


def _over_available_ram(estimated_extra_bytes: int) -> MemoryGuardResult | None:
    """Refuse a job whose estimate does not fit in free RAM after the reserve."""
    estimate = max(0, int(estimated_extra_bytes))
    if estimate <= 0:
        return None
    budget = worker_memory_budget_bytes()
    if budget is None or estimate <= budget:
        return None
    avail = available_physical_bytes()
    free = format_memory_bytes(avail) if avail else "unknown"
    return MemoryGuardResult(
        False,
        f"This needs about {format_memory_bytes(estimate)}, and about "
        f"{format_memory_bytes(budget)} can be used ({free} is free). "
        "Narrow the selection or close other programs." + _rss_hint(),
    )


def check_conformer_workload(n_rows: int, num_confs: int) -> MemoryGuardResult:
    """Guard conformer generation by row count and rows×confs product."""
    cfg = load_config()
    rows = max(0, int(n_rows))
    confs = max(1, int(num_confs))
    product = rows * confs
    if rows > cfg.memory_guard_conf_max_rows:
        return MemoryGuardResult(
            False,
            f"Conformer generation is limited to {cfg.memory_guard_conf_max_rows:,} rows "
            f"(requested {rows:,}). Narrow the scope or lower the row set." + _rss_hint(),
        )
    if product > cfg.memory_guard_conf_max_row_confs:
        return MemoryGuardResult(
            False,
            f"Conformer workload {rows:,} rows × {confs:,} confs = {product:,} exceeds the "
            f"cap of {cfg.memory_guard_conf_max_row_confs:,}. Reduce scope and/or conformer count."
            + _rss_hint(),
        )
    # Rough peak: ~0.5–2 MiB per multi-conf mol retained in worker results (conservative).
    est = product * 8_000
    blocked = _over_available_ram(est)
    if blocked is not None:
        return blocked
    return MemoryGuardResult(True, estimated_extra_bytes=est)


def check_cluster_workload(n_rows: int) -> MemoryGuardResult:
    cfg = load_config()
    rows = max(0, int(n_rows))
    if rows > cfg.memory_guard_cluster_max_rows:
        return MemoryGuardResult(
            False,
            f"Clustering is limited to {cfg.memory_guard_cluster_max_rows:,} structures "
            f"(requested {rows:,}). Select fewer rows or raise "
            f"MOLMANAGER_MEMORY_GUARD_CLUSTER_MAX_ROWS." + _rss_hint(),
        )
    # Upper bound only. Butina keeps neighbor indexes within the cutoff, not this
    # dense float32 matrix (and not the n×n float64 matrix RDKit's ClusterData builds).
    est = (rows * (rows - 1) // 2) * 4 if rows > 1 else 0
    blocked = _over_available_ram(est)
    if blocked is not None:
        return blocked
    return MemoryGuardResult(True, estimated_extra_bytes=est)


def check_diverse_subset_workload(
    n_rows: int,
    subset_size: int,
    *,
    mode: str = "auto",
) -> MemoryGuardResult:
    """
    Guard Diverse Subset by pool size and (for exact MaxMin) the k·N product.

    Fast / auto-on-large-N modes still enforce the hard row cap but skip the k·N
    product check (picking runs on a reduced candidate pool).
    """
    cfg = load_config()
    rows = max(0, int(n_rows))
    k = max(0, int(subset_size))
    if rows > cfg.memory_guard_diverse_max_rows:
        return MemoryGuardResult(
            False,
            f"Diverse Subset is limited to {cfg.memory_guard_diverse_max_rows:,} structures "
            f"(requested {rows:,}). Narrow the scope, use Selected Rows Only, or raise "
            f"MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_ROWS." + _rss_hint(),
        )
    resolved = (mode or "auto").strip().lower()
    if resolved == "auto":
        resolved = "exact" if rows <= int(cfg.diverse_subset_exact_max_rows) else "fast"
    if resolved == "exact":
        product = rows * max(1, k)
        if product > cfg.memory_guard_diverse_max_kn:
            return MemoryGuardResult(
                False,
                f"Exact MaxMin workload {rows:,} × subset {k:,} = {product:,} exceeds the "
                f"cap of {cfg.memory_guard_diverse_max_kn:,}. Lower subset size, switch to "
                f"Fast mode, or raise MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_KN." + _rss_hint(),
            )
    # Fingerprints + min-dist vector (order-of-magnitude hint).
    est = rows * 2_500
    blocked = _over_available_ram(est)
    if blocked is not None:
        return blocked
    return MemoryGuardResult(True, estimated_extra_bytes=est)


def check_fp_matrix_workload(n_rows: int, n_bits: int = 2048) -> MemoryGuardResult:
    cfg = load_config()
    rows = max(0, int(n_rows))
    bits = max(1, int(n_bits))
    cells = rows * bits
    if cells > cfg.memory_guard_fp_matrix_max_cells:
        max_rows = max(1, cfg.memory_guard_fp_matrix_max_cells // bits)
        return MemoryGuardResult(
            False,
            f"Fingerprint matrix {rows:,} × {bits:,} exceeds the cell cap "
            f"({cfg.memory_guard_fp_matrix_max_cells:,}). Use at most ~{max_rows:,} rows "
            f"for this fingerprint size, or adjust MOLMANAGER_MEMORY_GUARD_FP_MATRIX_MAX_CELLS."
            + _rss_hint(),
        )
    est = cells * 8  # float64 once a tool upcasts; stored bits are uint8
    blocked = _over_available_ram(est)
    if blocked is not None:
        return blocked
    return MemoryGuardResult(True, estimated_extra_bytes=est)


def check_product_enumeration(max_products: int) -> MemoryGuardResult:
    cfg = load_config()
    n = max(0, int(max_products))
    if n > cfg.memory_guard_enum_max_products:
        return MemoryGuardResult(
            False,
            f"Max products is capped at {cfg.memory_guard_enum_max_products:,} "
            f"(requested {n:,}). Lower Max products or raise "
            f"MOLMANAGER_MEMORY_GUARD_ENUM_MAX_PRODUCTS." + _rss_hint(),
        )
    est = n * 50_000
    blocked = _over_available_ram(est)
    if blocked is not None:
        return blocked
    return MemoryGuardResult(True, estimated_extra_bytes=est)


def clamp_max_products_ui(value: int) -> int:
    """Clamp a dialog Max products spinbox to the configured hard cap."""
    cfg = load_config()
    return max(1, min(int(value), int(cfg.memory_guard_enum_max_products)))


def clamp_dimred_max_points(value: int) -> int:
    cfg = load_config()
    return max(100, min(int(value), int(cfg.memory_guard_dimred_max_points)))
