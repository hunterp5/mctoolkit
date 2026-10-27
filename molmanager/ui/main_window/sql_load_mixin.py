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

"""External SQL load into the main table."""

from __future__ import annotations

import logging
import re
import sys
import threading
import time
from contextlib import nullcontext

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QApplication, QMessageBox


from ...platform_support.config import load_config
from ...storage import load_mols_from_parse_result
from ...services.sql_load_policy import engine_kwargs_for_sql_load, sql_looks_destructive
from ...chem.molecule_conversion import redact_sqlalchemy_url
from ...workers.sql_load_worker import SqlLoadParseResult, SqlLoadSignals, SqlLoadWorker
from ..background_jobs import register_background_job, unregister_background_job
from ..strings import (
    loaded_sql_status,
)
from ..threadpool_access import start_runnable_on_app_pool

logger = logging.getLogger(__name__)


class SqlLoadMixin:
    def load_from_sql(
        self,
        *,
        url: str,
        query: str | None = None,
        table: str | None = None,
        limit: int = 50000,
        apply_limit: bool = True,
        clear_first: bool = True,
        read_only: bool = True,
    ) -> None:
        """Load a SQL query/table into the main table.

        Fetch + SMILES parse run off the GUI thread; table appends are chunked on the
        GUI thread (same pattern as session restore). If a SMILES column exists
        (case-insensitive), molecules are created and 2D structures are drawn
        automatically after apply.

        ``read_only`` (default True) opens SQLite with ``mode=ro`` and refuses queries that
        look destructive. Uncheck read-only in the Query Database SQL dialog only when you
        intentionally need a write connection.
        """
        try:
            from sqlalchemy import create_engine, text
        except Exception as e:
            raise RuntimeError(
                "sqlalchemy is required for SQL loading. Install requirements-core.txt "
                "(or requirements.txt)."
            ) from e

        if bool(query) == bool(table):
            raise ValueError("Provide exactly one of: query or table.")

        if table is not None:
            tname = str(table).strip()
            if re.fullmatch(r"[A-Za-z0-9_]+", tname) is None:
                raise ValueError(
                    "SQL table name may only contain letters, digits, and underscores (identifier guard)."
                )
            table = tname

        from ...platform_support.session_runtime import sql_writes_allowed

        policy_blocks_writes = not sql_writes_allowed()
        if policy_blocks_writes:
            read_only = True
        if query and sql_looks_destructive(query):
            if policy_blocks_writes:
                raise ValueError(
                    "SQL that modifies the database is disabled (MOLMANAGER_SQL_WRITES=0)."
                )
            if read_only:
                raise ValueError(
                    "This SQL looks like it may modify the database. "
                    "Uncheck “Read-only connection” in the Query Database SQL dialog only if you "
                    "intentionally need a write connection, then confirm the warning."
                )
            r = QMessageBox.warning(
                self,
                "Destructive SQL",
                "This SQL looks like it may modify the database (INSERT/UPDATE/DELETE/DROP/…). "
                "MolManager is meant for loading query results into the table.\n\n"
                "Continue and run this statement anyway?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return

        sql_cfg = load_config()
        hard_cap = sql_cfg.sql_max_rows_hard
        precowarn = sql_cfg.sql_precount_warn
        try:
            li = int(limit) if limit is not None else 0
        except (TypeError, ValueError):
            li = 0
        if li > hard_cap:
            li = hard_cap
        if li < 0:
            li = 0

        logger.debug("load_from_sql url=%s read_only=%s", redact_sqlalchemy_url(url), read_only)
        from ...platform_support.session_runtime import audit_sql_load

        audit_sql_load(url)

        out_url, eng_kw = engine_kwargs_for_sql_load(
            url,
            read_only=bool(read_only),
            sqlite_timeout_s=sql_cfg.sqlite_timeout_s,
            pg_connect_timeout=sql_cfg.pg_connect_timeout,
        )
        page_size = max(64, int(sql_cfg.ingest_gui_chunk_size))
        limit_eff = int(li) if apply_limit and li else 0

        # Precount warning stays on the GUI (needs a modal confirm).
        if apply_limit and limit_eff > 0 and precowarn > 0:
            eng = create_engine(out_url, **eng_kw)
            try:
                with eng.connect() as conn:
                    est = None
                    try:
                        if table:
                            crow = (
                                conn.execute(text(f"SELECT COUNT(*) AS c FROM {table}"))
                                .mappings()
                                .first()
                            )
                            est = int(crow["c"]) if crow and crow.get("c") is not None else None
                        else:
                            base = (query or "").strip().rstrip(";")
                            if base:
                                crow = (
                                    conn.execute(
                                        text(f"SELECT COUNT(*) AS c FROM ({base}) AS __chem_cnt")
                                    )
                                    .mappings()
                                    .first()
                                )
                                est = int(crow["c"]) if crow and crow.get("c") is not None else None
                    except Exception:
                        est = None
                    if est is not None and est >= precowarn:
                        r = QMessageBox.question(
                            self,
                            "Large SQL result",
                            f"The data source reports about {est:,} row(s). Up to {limit_eff:,} row(s) will be fetched, "
                            "which may use significant time and memory.\n\nContinue?",
                            QMessageBox.Yes | QMessageBox.No,
                            QMessageBox.No,
                        )
                        if r != QMessageBox.Yes:
                            return
            finally:
                eng.dispose()

        if table:
            sql = f"SELECT * FROM {table}"
            if apply_limit and limit_eff:
                sql += f" LIMIT {int(limit_eff)}"
        else:
            sql = query or ""
            if apply_limit and limit_eff:
                if re.search(r"\blimit\b", sql, flags=re.IGNORECASE) is None:
                    sql = f"SELECT * FROM ({sql}) AS subq LIMIT {int(limit_eff)}"

        self._sql_load_generation = int(getattr(self, "_sql_load_generation", 0)) + 1
        gen = self._sql_load_generation
        self._sql_load_busy = True
        self._sql_load_error = None
        self._sql_load_ctx = None
        self._sql_load_clear_first = bool(clear_first)

        progress_total = limit_eff if limit_eff > 0 else 1
        cancel_event = threading.Event()
        self._sql_load_cancel_event = cancel_event
        job_id = f"sql-load-{gen}"
        self._sql_load_job_id = job_id
        register_background_job(
            self,
            job_id,
            "SQL load…",
            cancel=cancel_event.set,
        )
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("SQL load", progress_total, job_id=job_id)
        else:
            try:
                self.status_label.setText("SQL load: fetching…")
            except Exception:
                pass

        prog = getattr(self, "_tool_progress_state", None)
        bind = getattr(prog, "bind", None)
        if callable(bind):
            prog = bind(job_id)
        signals = SqlLoadSignals(self)

        def _on_chunk(result, g=gen) -> None:
            self._on_sql_load_chunk(result, g)

        def _on_parsed(result, g=gen) -> None:
            self._on_sql_load_finished(result, g)

        def _on_failed(message, g=gen) -> None:
            self._on_sql_load_failed(message, g)

        worker = SqlLoadWorker(
            url=out_url,
            engine_kwargs=eng_kw,
            sql=sql,
            page_size=page_size,
            limit_eff=limit_eff,
            apply_limit=bool(apply_limit),
            signals=signals,
            generation=gen,
            cancel_event=cancel_event,
            progress_state=prog,
        )
        if "pytest" in sys.modules:
            signals.chunk.connect(_on_chunk, type=Qt.DirectConnection)
            signals.finished.connect(_on_parsed, type=Qt.DirectConnection)
            signals.failed.connect(_on_failed, type=Qt.DirectConnection)
            worker.run()
            self._drain_sql_load()
            err = getattr(self, "_sql_load_error", None)
            if err:
                raise RuntimeError(err)
        else:
            signals.chunk.connect(_on_chunk, type=Qt.QueuedConnection)
            signals.finished.connect(_on_parsed, type=Qt.QueuedConnection)
            signals.failed.connect(_on_failed, type=Qt.QueuedConnection)
            start_runnable_on_app_pool(self, worker)

    def _clear_sql_load_job(self) -> None:
        job_id = getattr(self, "_sql_load_job_id", None)
        if job_id:
            unregister_background_job(self, job_id)
        self._sql_load_job_id = None
        self._sql_load_cancel_event = None

    def _drain_sql_load(self, *, timeout_s: float = 60.0) -> None:
        """Process Qt events until SQL fetch/apply completes (tests / sync path)."""
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            busy = bool(getattr(self, "_sql_load_busy", False))
            busy = busy or getattr(self, "_sql_load_ctx", None) is not None
            if not busy:
                return
            QApplication.processEvents()
            time.sleep(0.001)
        raise TimeoutError("Timed out waiting for SQL load to finish.")

    def _on_sql_load_failed(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_sql_load_generation", 0):
            return
        self._sql_load_busy = False
        self._sql_load_ctx = None
        job_id = getattr(self, "_sql_load_job_id", None)
        self._clear_sql_load_job()
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("SQL load", status_message=None, job_id=job_id)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        msg = message or "SQL load failed."
        self._sql_load_error = msg
        if "pytest" not in sys.modules:
            if msg == "Cancelled.":
                try:
                    self.status_label.setText("SQL load: cancelled.")
                except Exception:
                    pass
            else:
                QMessageBox.critical(self, "SQL load", msg)

    def _on_sql_load_chunk(self, result: object, generation: int) -> None:
        if generation != getattr(self, "_sql_load_generation", 0):
            return
        if not isinstance(result, SqlLoadParseResult):
            self._on_sql_load_failed("Invalid SQL load result.", generation)
            return
        cancel = getattr(self, "_sql_load_cancel_event", None)
        if cancel is not None and cancel.is_set():
            self._on_sql_load_failed("Cancelled.", generation)
            return
        prepared = list(result.prepared_rows or [])
        if not prepared:
            return

        ctx = getattr(self, "_sql_load_ctx", None)
        first = ctx is None or bool(result.is_first)
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        with scope("sql.apply_rows"):
            if first:
                if getattr(self, "_sql_load_clear_first", True):
                    self.clear_all()
                cols = list(result.columns or [])
                self.headers = ["ID_HIDDEN", "Structure"] + cols
                self.table.setSortingEnabled(False)
                try:
                    self.table.setUpdatesEnabled(False)
                except Exception:
                    pass
                self._table_model.clear_rows()
                self._table_model.set_headers(list(self.headers))
                self.table.setColumnHidden(0, True)
                load_mols_from_parse_result(self, result, replace=True)
                self._clear_filter_target_smiles_cache()
                self.global_bounds = {}
                self._sql_load_ctx = {
                    "gen": generation,
                    "applied": 0,
                    "rows_hit_limit": bool(result.rows_hit_limit),
                    "limit_eff": int(result.limit_eff),
                }
                ctx = self._sql_load_ctx
            else:
                load_mols_from_parse_result(self, result, replace=False)
                if ctx is not None:
                    ctx["rows_hit_limit"] = ctx.get("rows_hit_limit") or bool(result.rows_hit_limit)

            self._table_model.append_rows_batch(prepared, defer_color_cache=True)
            self.next_oid = int(result.next_oid)
            applied = int((ctx or {}).get("applied", 0)) + len(prepared)
            if ctx is not None:
                ctx["applied"] = applied
            on_prog = getattr(self, "_on_tool_progress", None)
            total_ui = int(result.limit_eff) if result.limit_eff else max(applied, 1)
            if callable(on_prog):
                on_prog("SQL load: applying…", applied, total_ui)
            else:
                try:
                    self.status_label.setText(f"SQL load: applying… ({applied:,})")
                except Exception:
                    pass
            self._sql_load_busy = True

    def _on_sql_load_finished(self, result: object, generation: int) -> None:
        if generation != getattr(self, "_sql_load_generation", 0):
            return
        if not isinstance(result, SqlLoadParseResult):
            self._on_sql_load_failed("Invalid SQL load result.", generation)
            return
        ctx = getattr(self, "_sql_load_ctx", None)
        n = int((ctx or {}).get("applied") or 0)
        if n <= 0:
            self._on_sql_load_failed("Query returned 0 rows.", generation)
            return
        rows_hit_limit = bool((ctx or {}).get("rows_hit_limit") or result.rows_hit_limit)
        limit_eff = int((ctx or {}).get("limit_eff") or result.limit_eff or 0)
        self.next_oid = int(result.next_oid or self.next_oid)
        self._sql_load_ctx = None
        self._sql_load_busy = False
        job_id = getattr(self, "_sql_load_job_id", None)
        self._clear_sql_load_job()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("SQL load", status_message=None, job_id=job_id)

        if rows_hit_limit:
            QMessageBox.information(
                self,
                "SQL load",
                f"The result has {n:,} row(s), reaching the row limit ({limit_eff:,}). "
                "If you expected more rows, raise “Max rows” in the SQL dialog or adjust your query.",
            )

        if self._sqlite_store is not None:
            self._sqlite_store_dirty = True

        self.table.setSortingEnabled(False)
        smiles_loaded = any(str(h).lower() == "smiles" for h in (self.headers or []))
        QTimer.singleShot(0, lambda: self._deferred_sql_post_load_follow_up(n, smiles_loaded))

    def _deferred_sql_post_load_follow_up(self, nrows: int, smiles_loaded: bool) -> None:
        """Defer bounds scan and 2D batch so the SQL load dialog can close and the table can paint."""
        self._table_model.rebuild_column_color_caches_after_bulk_load()
        self.schedule_calculate_global_bounds(delay_ms=500)
        if smiles_loaded and self._try_auto_render_all_structures_after_ingest():
            self.status_label.setText(f"Loaded {nrows:,} row(s) from SQL — drawing 2D structures…")
        else:
            self.status_label.setText(
                loaded_sql_status(nrows)
                if smiles_loaded
                else f"Loaded {nrows:,} row(s) from SQL (no SMILES column)."
            )
