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

"""Central environment-driven settings (see README env table)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Default for controls that cap how many rows or pairs a plot draws.
DEFAULT_MAX_PLOTTED = 25_000


def _env_str(name: str, default: str) -> str:
    raw = (os.environ.get(name) or "").strip()
    return raw if raw else default


def _env_int(name: str, default: int, *, lo: int, hi: int | None = None) -> int:
    try:
        v = int((os.environ.get(name) or "").strip() or str(default))
    except ValueError:
        v = default
    v = max(lo, v)
    if hi is not None:
        v = min(v, hi)
    return v


def _env_optional_positive_int(name: str, *, lo: int, hi: int) -> int | None:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return None
    try:
        v = int(raw)
    except ValueError:
        return None
    return max(lo, min(v, hi))


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def _env_float(name: str, default: float, *, lo: float) -> float:
    try:
        v = float((os.environ.get(name) or "").strip() or str(default))
    except ValueError:
        v = default
    return max(lo, v)


def clamp_substructure_async_rows(raw: str | None) -> int:
    """Match ``FilterPanelMixin`` / worker threshold semantics."""
    default = 400
    try:
        thresh = int((raw or "").strip() or str(default))
    except ValueError:
        thresh = default
    return max(64, min(thresh, 500_000))


@dataclass(frozen=True)
class MolManagerConfig:
    log_level: str
    max_threadpool: int | None
    render_threadpool: int | None
    substructure_async_rows: int
    sql_max_rows_hard: int
    sql_precount_warn: int
    sqlite_timeout_s: float
    pg_connect_timeout: int
    conformer_threads: int | None
    descriptor_threads: int | None
    descriptor_process_pool_min_rows: int
    descriptor_fp_process_pool_min_rows: int
    descriptor_process_pool_batch_size: int
    fast_prepare_batch_size: int
    fast_prepare_process_pool_min_rows: int
    render2d_process_workers: int | None
    render2d_batch_size: int
    background_job_poll_ms: int
    bulk_update_defer_color_cache_rows: int
    protomer_process_workers: int | None
    pka_process_workers: int | None
    disable_custom_calc: bool
    filter_debounce_substructure_rows: int
    filter_debounce_substructure_ms: int
    filter_debounce_default_rows: int
    filter_debounce_default_ms: int
    filter_async_min_rows: int
    filter_chunk_rows: int
    bounds_async_min_rows: int
    bounds_chunk_rows: int
    ingest_gui_chunk_size: int
    ingest_gui_subslice_rows: int
    ingest_gui_time_budget_ms: int
    ingest_worker_batch_size: int
    ingest_csv_text_first: bool
    ingest_silent_model_append: bool
    ingest_sqlite_incremental: bool
    structure_render_lazy_after_ingest_min_rows: int
    perf_metrics_enabled: bool
    perf_log_every: int
    sqlite_backend_page_size: int
    auto_render_2d_max_rows: int
    structure_render_lazy_min_rows: int
    structure_render_pixmap_lru: int
    structure_layout_macrocycle_coordgen: bool
    structure_layout_flip_inward_substituents: bool
    structure_layout_rotate_to_cell: bool
    fingerprint_cache_max_entries: int
    tool_progress_poll_ms: int
    status_memory_enabled: bool
    status_memory_poll_ms: int
    selection_status_min_rows: int
    tool_table_chunk_rows: int
    plot_scattergl_min_points: int
    plot_selection_overlay_max_points: int
    table_delete_batch_min: int
    table_delete_chunk_rows: int
    table_undo_limit: int
    mol_cache_lru: int
    structure_render_png_max_entries: int
    memory_guard_conf_max_rows: int
    memory_guard_conf_max_row_confs: int
    memory_guard_cluster_max_rows: int
    memory_guard_diverse_max_rows: int
    memory_guard_diverse_max_kn: int
    diverse_subset_exact_max_rows: int
    diverse_subset_fast_candidate_cap: int
    memory_guard_fp_matrix_max_cells: int
    memory_guard_enum_max_products: int
    memory_guard_dimred_max_points: int
    recomp_constraint_candidate_multiplier: int
    recomp_constraint_min_candidates: int


#: Settings renamed when entry selection moved to ``SelectionStore`` (old name -> new name).
_RENAMED_ENV_VARS = {
    "MOLMANAGER_TABLE_SELECTION_OID_OVERRIDE_MIN": "MOLMANAGER_SELECTION_STATUS_MIN_ROWS",
    "MOLMANAGER_TABLE_SELECTION_CHUNK_ROWS": "MOLMANAGER_TOOL_TABLE_CHUNK_ROWS",
}


def _migrate_renamed_env_vars() -> None:
    """Honor renamed ``MOLMANAGER_*`` variables under their old names when the new one is unset."""
    migrated: list[str] = []
    for old_key, new_key in _RENAMED_ENV_VARS.items():
        value = os.environ.get(old_key)
        if value is None or new_key in os.environ:
            continue
        os.environ[new_key] = value
        migrated.append(f"{old_key}→{new_key}")
    if migrated:
        logger.warning(
            "Renamed MolManager environment variables were mapped to their new names (%s). "
            "Rename them; the old names will be removed in a future release.",
            ", ".join(migrated),
        )


def _migrate_chemmanager_env_aliases() -> None:
    """Map legacy ``CHEMMANAGER_*`` variables to ``MOLMANAGER_*`` when the new name is unset."""
    old_prefix = "CHEMMANAGER_"
    new_prefix = "MOLMANAGER_"
    migrated: list[str] = []
    for key, value in list(os.environ.items()):
        if not key.startswith(old_prefix):
            continue
        new_key = new_prefix + key[len(old_prefix) :]
        if new_key not in os.environ:
            os.environ[new_key] = value
            migrated.append(f"{key}→{new_key}")
    if migrated:
        logger.warning(
            "Deprecated CHEMMANAGER_* environment variables were mapped to MOLMANAGER_* "
            "(%s). Rename them; this alias will be removed in a future release.",
            ", ".join(migrated),
        )


def _warn_retired_custom_calc_legacy_eval() -> None:
    if _env_truthy("MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL"):
        logger.warning(
            "MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL is retired and ignored; "
            "custom calculator expressions always use the AST calculator_expressions path."
        )


def load_config() -> MolManagerConfig:
    """Read current settings from ``os.environ`` (no process-wide cache — tests can monkeypatch)."""
    _migrate_chemmanager_env_aliases()
    _migrate_renamed_env_vars()
    _warn_retired_custom_calc_legacy_eval()
    hard = _env_int("MOLMANAGER_SQL_MAX_ROWS_HARD", 2_000_000, lo=1000, hi=50_000_000)
    precowarn = _env_int("MOLMANAGER_SQL_PRECOUNT_WARN", 100_000, lo=1000, hi=hard)
    return MolManagerConfig(
        log_level=_env_str("MOLMANAGER_LOG_LEVEL", "INFO").upper(),
        max_threadpool=_env_optional_positive_int("MOLMANAGER_MAX_THREADPOOL", lo=1, hi=64),
        render_threadpool=_env_optional_positive_int("MOLMANAGER_RENDER_THREADPOOL", lo=1, hi=32),
        substructure_async_rows=clamp_substructure_async_rows(
            os.environ.get("MOLMANAGER_SUBSTRUCTURE_ASYNC_ROWS")
        ),
        sql_max_rows_hard=hard,
        sql_precount_warn=precowarn,
        sqlite_timeout_s=_env_float("MOLMANAGER_SQLITE_TIMEOUT_S", 30.0, lo=0.1),
        pg_connect_timeout=_env_int("MOLMANAGER_PG_CONNECT_TIMEOUT", 30, lo=1, hi=3600),
        conformer_threads=_env_optional_positive_int("MOLMANAGER_CONFORMER_THREADS", lo=1, hi=16),
        descriptor_threads=_env_optional_positive_int("MOLMANAGER_DESCRIPTOR_THREADS", lo=1, hi=32),
        descriptor_process_pool_min_rows=_env_int(
            "MOLMANAGER_DESCRIPTOR_PROCESS_POOL_MIN_ROWS", 1500, lo=0, hi=10_000_000
        ),
        descriptor_fp_process_pool_min_rows=_env_int(
            "MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", 64, lo=2, hi=10_000_000
        ),
        descriptor_process_pool_batch_size=_env_int(
            "MOLMANAGER_DESCRIPTOR_PROCESS_POOL_BATCH_SIZE", 32, lo=1, hi=512
        ),
        render2d_process_workers=_env_optional_positive_int(
            "MOLMANAGER_RENDER2D_PROCESS_WORKERS", lo=1, hi=32
        ),
        # Molecules per child-process render task. One-per-task made the parent process the
        # throughput ceiling, so extra workers bought nothing.
        render2d_batch_size=_env_int("MOLMANAGER_RENDER2D_BATCH_SIZE", 64, lo=1, hi=4096),
        fast_prepare_batch_size=_env_int("MOLMANAGER_FAST_PREPARE_BATCH_SIZE", 64, lo=1, hi=2048),
        # Below this row count, child-process startup costs more than the work it saves.
        fast_prepare_process_pool_min_rows=_env_int(
            "MOLMANAGER_FAST_PREPARE_PROCESS_POOL_MIN_ROWS", 250, lo=2, hi=10_000_000
        ),
        background_job_poll_ms=_env_int("MOLMANAGER_BACKGROUND_JOB_POLL_MS", 500, lo=100, hi=5000),
        bulk_update_defer_color_cache_rows=_env_int(
            "MOLMANAGER_BULK_UPDATE_DEFER_COLOR_CACHE_ROWS", 5000, lo=0, hi=10_000_000
        ),
        protomer_process_workers=_env_optional_positive_int(
            "MOLMANAGER_PROTOMER_PROCESSES", lo=1, hi=8
        ),
        # None = auto. <=0 scores in the caller. Any positive value still starts
        # one torch process; a value above 1 only caps the RDKit conformer pool.
        pka_process_workers=_env_optional_positive_int(
            "MOLMANAGER_PKA_PROCESS_WORKERS", lo=1, hi=8
        ),
        disable_custom_calc=_env_truthy("MOLMANAGER_DISABLE_CUSTOM_CALC"),
        filter_debounce_substructure_rows=_env_int(
            "MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_ROWS", 120, lo=1, hi=1_000_000
        ),
        filter_debounce_substructure_ms=_env_int(
            "MOLMANAGER_FILTER_DEBOUNCE_SUBSTRUCTURE_MS", 85, lo=0, hi=60_000
        ),
        filter_debounce_default_rows=_env_int(
            "MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_ROWS", 0, lo=0, hi=1_000_000
        ),
        filter_debounce_default_ms=_env_int(
            "MOLMANAGER_FILTER_DEBOUNCE_DEFAULT_MS", 80, lo=0, hi=60_000
        ),
        filter_async_min_rows=_env_int(
            "MOLMANAGER_FILTER_ASYNC_MIN_ROWS", 5000, lo=1, hi=10_000_000
        ),
        filter_chunk_rows=_env_int("MOLMANAGER_FILTER_CHUNK_ROWS", 2000, lo=64, hi=100_000),
        bounds_async_min_rows=_env_int(
            "MOLMANAGER_BOUNDS_ASYNC_MIN_ROWS", 5000, lo=1, hi=10_000_000
        ),
        bounds_chunk_rows=_env_int("MOLMANAGER_BOUNDS_CHUNK_ROWS", 2000, lo=64, hi=100_000),
        ingest_gui_chunk_size=_env_int("MOLMANAGER_INGEST_GUI_CHUNK", 512, lo=16, hi=10_000),
        ingest_gui_subslice_rows=_env_int("MOLMANAGER_INGEST_GUI_SUBSLICE", 128, lo=16, hi=10_000),
        ingest_gui_time_budget_ms=_env_int("MOLMANAGER_INGEST_GUI_TIME_MS", 30, lo=5, hi=200),
        ingest_worker_batch_size=_env_int("MOLMANAGER_INGEST_WORKER_BATCH", 2000, lo=64, hi=20_000),
        ingest_csv_text_first=_env_bool("MOLMANAGER_INGEST_CSV_TEXT_FIRST", True),
        ingest_silent_model_append=_env_bool("MOLMANAGER_INGEST_SILENT_MODEL_APPEND", True),
        ingest_sqlite_incremental=_env_bool("MOLMANAGER_INGEST_SQLITE_INCREMENTAL", True),
        structure_render_lazy_after_ingest_min_rows=_env_int(
            # 0 = structure-column renders always go to the PNG store (decoded LRU stays capped).
            "MOLMANAGER_STRUCTURE_RENDER_LAZY_AFTER_INGEST",
            0,
            lo=0,
            hi=10_000_000,
        ),
        perf_metrics_enabled=_env_truthy("MOLMANAGER_PERF_METRICS"),
        perf_log_every=_env_int("MOLMANAGER_PERF_LOG_EVERY", 25, lo=1, hi=10_000),
        sqlite_backend_page_size=_env_int(
            "MOLMANAGER_SQLITE_BACKEND_PAGE_SIZE", 5000, lo=100, hi=200_000
        ),
        auto_render_2d_max_rows=_env_int(
            "MOLMANAGER_AUTO_RENDER_2D_MAX_ROWS", 25_000, lo=0, hi=10_000_000
        ),
        structure_render_lazy_min_rows=_env_int(
            # 0 = same PNG store for Chemistry → Render 2D, not one decoded QPixmap per row.
            "MOLMANAGER_STRUCTURE_RENDER_LAZY_MIN_ROWS",
            0,
            lo=0,
            hi=10_000_000,
        ),
        structure_render_pixmap_lru=_env_int(
            "MOLMANAGER_STRUCTURE_RENDER_PIXMAP_LRU", 384, lo=32, hi=4096
        ),
        # Draw Structure cells from depiction scenes instead of RDKit PNGs.
        structure_layout_macrocycle_coordgen=_env_bool(
            "MOLMANAGER_STRUCTURE_LAYOUT_MACROCYCLE_COORDGEN", True
        ),
        structure_layout_flip_inward_substituents=_env_bool(
            "MOLMANAGER_STRUCTURE_LAYOUT_FLIP_INWARD_SUBSTITUENTS", True
        ),
        structure_layout_rotate_to_cell=_env_bool(
            "MOLMANAGER_STRUCTURE_LAYOUT_ROTATE_TO_CELL", True
        ),
        fingerprint_cache_max_entries=_env_int(
            "MOLMANAGER_FINGERPRINT_CACHE_MAX_ENTRIES", 50_000, lo=0, hi=5_000_000
        ),
        tool_progress_poll_ms=_env_int("MOLMANAGER_TOOL_PROGRESS_POLL_MS", 200, lo=50, hi=2000),
        status_memory_enabled=_env_bool("MOLMANAGER_STATUS_MEMORY", True),
        status_memory_poll_ms=_env_int("MOLMANAGER_STATUS_MEMORY_POLL_MS", 2000, lo=500, hi=60_000),
        # Show a "Selecting…" status before select-by-criteria row scans on tables this large.
        selection_status_min_rows=_env_int(
            "MOLMANAGER_SELECTION_STATUS_MIN_ROWS", 2500, lo=100, hi=10_000_000
        ),
        # Rows per GUI-thread chunk when tools read table snapshots or write results back.
        tool_table_chunk_rows=_env_int("MOLMANAGER_TOOL_TABLE_CHUNK_ROWS", 2000, lo=64, hi=100_000),
        # WebGL scatter above this count (pan/zoom/select stay responsive on large sets).
        plot_scattergl_min_points=_env_int(
            "MOLMANAGER_PLOT_SCATTERGL_MIN_POINTS", 2000, lo=0, hi=10_000_000
        ),
        # SVG overlay highlight is nicer for small lassos; above this use selectedpoints.
        plot_selection_overlay_max_points=_env_int(
            "MOLMANAGER_PLOT_SELECTION_OVERLAY_MAX", 400, lo=0, hi=100_000
        ),
        table_delete_batch_min=_env_int(
            "MOLMANAGER_TABLE_DELETE_BATCH_MIN", 50, lo=1, hi=10_000_000
        ),
        table_delete_chunk_rows=_env_int(
            "MOLMANAGER_TABLE_DELETE_CHUNK_ROWS", 2000, lo=64, hi=100_000
        ),
        table_undo_limit=_env_int("MOLMANAGER_TABLE_UNDO_LIMIT", 50, lo=1, hi=500),
        mol_cache_lru=_env_int("MOLMANAGER_MOL_CACHE_LRU", 256, lo=8, hi=4096),
        structure_render_png_max_entries=_env_int(
            # 0 = unlimited PNG bytes in the lazy structure store (decoded QPixmaps stay LRU-capped).
            # A positive cap was dropping Fast Prepare / Render 2D drawings beyond this limit.
            "MOLMANAGER_STRUCTURE_RENDER_PNG_MAX",
            0,
            lo=0,
            hi=10_000_000,
        ),
        memory_guard_conf_max_rows=_env_int(
            "MOLMANAGER_MEMORY_GUARD_CONF_MAX_ROWS", 5_000, lo=1, hi=10_000_000
        ),
        memory_guard_conf_max_row_confs=_env_int(
            "MOLMANAGER_MEMORY_GUARD_CONF_MAX_ROW_CONFS", 1_000_000, lo=100, hi=50_000_000
        ),
        memory_guard_cluster_max_rows=_env_int(
            "MOLMANAGER_MEMORY_GUARD_CLUSTER_MAX_ROWS", 25_000, lo=100, hi=10_000_000
        ),
        memory_guard_diverse_max_rows=_env_int(
            "MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_ROWS", 200_000, lo=100, hi=10_000_000
        ),
        memory_guard_diverse_max_kn=_env_int(
            "MOLMANAGER_MEMORY_GUARD_DIVERSE_MAX_KN",
            50_000_000,
            lo=1_000,
            hi=2_000_000_000,
        ),
        diverse_subset_exact_max_rows=_env_int(
            "MOLMANAGER_DIVERSE_SUBSET_EXACT_MAX_ROWS", 50_000, lo=100, hi=10_000_000
        ),
        diverse_subset_fast_candidate_cap=_env_int(
            "MOLMANAGER_DIVERSE_SUBSET_FAST_CANDIDATE_CAP", 10_000, lo=100, hi=500_000
        ),
        memory_guard_fp_matrix_max_cells=_env_int(
            "MOLMANAGER_MEMORY_GUARD_FP_MATRIX_MAX_CELLS",
            # 25k dimred rows × 2048-bit fingerprints (float64 working matrix).
            25_000 * 2048,
            lo=100_000,
            hi=2_000_000_000,
        ),
        memory_guard_enum_max_products=_env_int(
            "MOLMANAGER_MEMORY_GUARD_ENUM_MAX_PRODUCTS", 10_000, lo=10, hi=50_000
        ),
        memory_guard_dimred_max_points=_env_int(
            "MOLMANAGER_MEMORY_GUARD_DIMRED_MAX_POINTS",
            DEFAULT_MAX_PLOTTED,
            lo=100,
            hi=50_000,
        ),
        recomp_constraint_candidate_multiplier=_env_int(
            "MOLMANAGER_RECOMP_CONSTRAINT_CANDIDATE_MULT", 100, lo=10, hi=10_000
        ),
        recomp_constraint_min_candidates=_env_int(
            "MOLMANAGER_RECOMP_CONSTRAINT_MIN_CANDIDATES", 10_000, lo=1000, hi=10_000_000
        ),
    )
