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

"""Central configuration from environment."""

from __future__ import annotations


from molmanager.platform_support.config import clamp_substructure_async_rows, load_config


def test_clamp_substructure_async_rows_bounds():
    assert clamp_substructure_async_rows("") == 400
    assert clamp_substructure_async_rows("64") == 64
    assert clamp_substructure_async_rows("10") == 64
    assert clamp_substructure_async_rows("999999") == 500_000


def test_load_config_sql_caps_respect_monkeypatch(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_SQL_MAX_ROWS_HARD", "5000")
    monkeypatch.setenv("MOLMANAGER_SQL_PRECOUNT_WARN", "2000")
    cfg = load_config()
    assert cfg.sql_max_rows_hard == 5000
    assert cfg.sql_precount_warn == 2000


def test_protomer_process_workers_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_PROTOmer_PROCESSES", "3")
    assert load_config().protomer_process_workers == 3


def test_pka_process_workers_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_PKA_PROCESS_WORKERS", "2")
    assert load_config().pka_process_workers == 2


def test_disable_custom_calc_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DISABLE_CUSTOM_CALC", "1")
    assert load_config().disable_custom_calc is True


def test_legacy_custom_calc_eval_env_is_ignored(monkeypatch, caplog):
    monkeypatch.setenv("MOLMANAGER_CUSTOM_CALC_LEGACY_EVAL", "1")
    import logging

    with caplog.at_level(logging.WARNING, logger="molmanager.platform_support.config"):
        cfg = load_config()
    assert not hasattr(cfg, "custom_calc_legacy_eval")
    assert any("CUSTOM_CALC_LEGACY_EVAL" in r.message for r in caplog.records)


def test_chemmanager_env_alias_migrates_with_warning(monkeypatch, caplog):
    monkeypatch.delenv("MOLMANAGER_LOG_LEVEL", raising=False)
    monkeypatch.setenv("CHEMMANAGER_LOG_LEVEL", "DEBUG")
    import logging

    with caplog.at_level(logging.WARNING, logger="molmanager.platform_support.config"):
        cfg = load_config()
    assert cfg.log_level == "DEBUG"
    assert any("CHEMMANAGER_" in r.message for r in caplog.records)


def test_renamed_selection_env_vars_still_apply_with_warning(monkeypatch, caplog):
    import logging

    # delenv records the unset state, so the values the migration writes are removed afterwards.
    monkeypatch.delenv("MOLMANAGER_SELECTION_STATUS_MIN_ROWS", raising=False)
    monkeypatch.delenv("MOLMANAGER_TOOL_TABLE_CHUNK_ROWS", raising=False)
    monkeypatch.setenv("MOLMANAGER_TABLE_SELECTION_OID_OVERRIDE_MIN", "4000")
    monkeypatch.setenv("MOLMANAGER_TABLE_SELECTION_CHUNK_ROWS", "750")
    with caplog.at_level(logging.WARNING, logger="molmanager.platform_support.config"):
        cfg = load_config()
    assert cfg.selection_status_min_rows == 4000
    assert cfg.tool_table_chunk_rows == 750
    assert any("MOLMANAGER_TOOL_TABLE_CHUNK_ROWS" in r.message for r in caplog.records)


def test_new_selection_env_names_win_over_old_ones(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_TOOL_TABLE_CHUNK_ROWS", "900")
    monkeypatch.setenv("MOLMANAGER_TABLE_SELECTION_CHUNK_ROWS", "750")
    assert load_config().tool_table_chunk_rows == 900


def test_perf_and_sqlite_page_size_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_PERF_METRICS", "true")
    monkeypatch.setenv("MOLMANAGER_PERF_LOG_EVERY", "5")
    monkeypatch.setenv("MOLMANAGER_SQLITE_BACKEND_PAGE_SIZE", "6000")
    cfg = load_config()
    assert cfg.perf_metrics_enabled is True
    assert cfg.perf_log_every == 5
    assert cfg.sqlite_backend_page_size == 6000


def test_sqlite_backend_page_size_default():
    cfg = load_config()
    assert cfg.sqlite_backend_page_size == 5000


def test_structure_render_limits_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_AUTO_RENDER_2D_MAX_ROWS", "12000")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_RENDER_LAZY_MIN_ROWS", "6000")
    monkeypatch.setenv("MOLMANAGER_STRUCTURE_RENDER_PIXMAP_LRU", "128")
    cfg = load_config()
    assert cfg.auto_render_2d_max_rows == 12000
    assert cfg.structure_render_lazy_min_rows == 6000
    assert cfg.structure_render_pixmap_lru == 128


def test_tool_progress_poll_ms_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_TOOL_PROGRESS_POLL_MS", "350")
    assert load_config().tool_progress_poll_ms == 350


def test_descriptor_fp_process_pool_env(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "128")
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_PROCESS_POOL_BATCH_SIZE", "16")
    cfg = load_config()
    assert cfg.descriptor_fp_process_pool_min_rows == 128
    assert cfg.descriptor_process_pool_batch_size == 16
