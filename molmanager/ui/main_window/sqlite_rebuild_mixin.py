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

"""SQLite mirror rebuild after ingest or table edits."""

from __future__ import annotations

import logging
from contextlib import nullcontext

from PyQt5.QtCore import QTimer

from ...platform_support.config import load_config
from ...storage import SqliteTableStore
from ... import workers
from ..strings import loaded_session_status

logger = logging.getLogger(__name__)


class SqliteRebuildMixin:
    def _rebuild_sqlite_store_from_model(self) -> None:
        """Synchronous rebuild (clear table, tests). Large tables use ``_schedule_sqlite_rebuild``."""
        store = getattr(self, "_sqlite_store", None)
        if store is None:
            return
        self._sqlite_rebuild_in_progress = True
        data_headers = [
            h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)
        ]
        entries = self._table_model.export_rows_for_sqlite(data_headers)
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        try:
            with scope("sqlite.rebuild"):
                store.rebuild(self.headers, entries)
            self._sqlite_store_dirty = False
        finally:
            self._sqlite_rebuild_in_progress = False

    def _close_sqlite_rebuild_writer(self, ctx: dict | None) -> None:
        writer = None if ctx is None else ctx.pop("writer", None)
        if writer is None:
            return
        try:
            writer.close()
        except Exception:
            logger.exception("Failed to close SQLite rebuild writer")

    def _schedule_sqlite_rebuild(self) -> None:
        """Chunk-export and stream-write row text, then index SQLite in a worker."""
        store = getattr(self, "_sqlite_store", None)
        if store is None or self._sqlite_rebuild_in_progress:
            return
        sigs = getattr(self, "_sqlite_rebuild_signals", None)
        pool = getattr(self, "threadpool", None)
        if sigs is None or pool is None:
            self._rebuild_sqlite_store_from_model()
            return
        self._sqlite_rebuild_gen = int(getattr(self, "_sqlite_rebuild_gen", 0)) + 1
        gen = self._sqlite_rebuild_gen
        self._sqlite_rebuild_in_progress = True
        data_headers = [
            h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)
        ]
        from pathlib import Path

        from ...platform_support.session_runtime import current_runtime

        db_path = str(current_runtime().allocate_sqlite("sqlite-rebuild-"))
        self._sqlite_rebuild_pending_path = Path(db_path)
        n_rows = self._table_model.rowCount()
        from ..background_jobs import register_background_job

        job_id = f"sqlite-rebuild-{gen}"
        self._sqlite_rebuild_bg_job_id = job_id
        register_background_job(self, job_id, f"Indexing table ({n_rows:,} rows)")
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Indexing table", max(1, n_rows), job_id=job_id)
        chunk = max(500, load_config().ingest_gui_chunk_size)
        writer = SqliteTableStore(db_path)
        writer.start_stream_rebuild(list(self.headers))
        self._sqlite_export_ctx = {
            "gen": gen,
            "data_headers": data_headers,
            "row_idx": 0,
            "n_rows": n_rows,
            "chunk": chunk,
            "db_path": str(db_path),
            "signals": sigs,
            "writer": writer,
            "headers": list(self.headers),
        }
        self.status_label.setText(f"Indexing table… (0/{n_rows:,} rows)")
        QTimer.singleShot(0, self._sqlite_export_chunk_step)

    def _sqlite_export_chunk_step(self) -> None:
        ctx = getattr(self, "_sqlite_export_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_sqlite_rebuild_gen", -1):
            self._close_sqlite_rebuild_writer(ctx)
            self._sqlite_export_ctx = None
            return
        if not self._sqlite_rebuild_in_progress:
            self._close_sqlite_rebuild_writer(ctx)
            self._sqlite_export_ctx = None
            return
        data_headers = ctx["data_headers"]
        row_idx = int(ctx["row_idx"])
        n_rows = int(ctx["n_rows"])
        chunk = int(ctx["chunk"])
        end = min(row_idx + chunk, n_rows)
        slice_rows = self._table_model.export_rows_for_sqlite_slice(data_headers, row_idx, end)
        writer = ctx.get("writer")
        if writer is not None and slice_rows:
            writer.append_stream_rows(slice_rows)
        ctx["row_idx"] = end
        on_prog = getattr(self, "_on_tool_progress", None)
        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        if callable(on_prog):
            on_prog("Indexing table…", end, max(1, n_rows), job_id=job_id)
        else:
            self.status_label.setText(f"Indexing table… ({end:,}/{n_rows:,} rows)")
        if end < n_rows:
            QTimer.singleShot(0, self._sqlite_export_chunk_step)
            return
        gen = int(ctx["gen"])
        db_path = ctx["db_path"]
        sigs = ctx["signals"]
        headers = list(ctx.get("headers") or self.headers)
        self._close_sqlite_rebuild_writer(ctx)
        self._sqlite_export_ctx = None
        pool = getattr(self, "threadpool", None)
        if pool is None:
            self._sqlite_rebuild_in_progress = False
            finish = getattr(self, "_finish_tool_progress", None)
            if callable(finish):
                finish("Indexing table", status_message=None)
            return
        self.status_label.setText(f"Indexing table… (writing {n_rows:,} rows)")
        prog = getattr(self, "_tool_progress_state", None)
        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        bind = getattr(prog, "bind", None)
        if callable(bind) and job_id:
            prog = bind(job_id)
        pool.start(
            workers.SqliteRebuildWorker(
                gen,
                headers,
                None,
                db_path,
                sigs,
                stream_finalize=True,
                progress_state=prog,
            )
        )

    def _unregister_sqlite_rebuild_background_job(self, job_gen: int) -> None:
        from ..background_jobs import unregister_background_job

        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        if job_id == f"sqlite-rebuild-{job_gen}":
            unregister_background_job(self, job_id)
            self._sqlite_rebuild_bg_job_id = None

    def _on_sqlite_rebuild_finished(self, job_gen: int, db_path: str) -> None:
        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        self._unregister_sqlite_rebuild_background_job(job_gen)
        if job_gen != getattr(self, "_sqlite_rebuild_gen", -1):
            from ...storage.sqlite_table_store import unlink_sqlite_files

            unlink_sqlite_files(db_path)
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Indexing table", status_message=None, job_id=job_id)
        try:
            new_store = SqliteTableStore(db_path, delete_on_close=True)
            old = getattr(self, "_sqlite_store", None)
            self._sqlite_store = new_store
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._sqlite_store_dirty = False
        except Exception:
            logger.exception("Failed to swap SQLite row store after background rebuild")
        finally:
            self._sqlite_rebuild_in_progress = False
            self._sqlite_rebuild_pending_path = None
        if getattr(self, "_sqlite_rebuild_stale", False):
            self._sqlite_rebuild_stale = False
            self._sqlite_store_dirty = True
            self._schedule_sqlite_rebuild()
            return
        n_rows = self._table_model.rowCount()
        if getattr(self, "_sqlite_rebuild_pending_filters", False):
            self._sqlite_rebuild_pending_filters = False
            self.apply_filters()
        elif n_rows:
            self.status_label.setText(loaded_session_status(n_rows))

    def _on_sqlite_rebuild_failed(self, job_gen: int, msg: str) -> None:
        job_id = getattr(self, "_sqlite_rebuild_bg_job_id", None)
        self._unregister_sqlite_rebuild_background_job(job_gen)
        if job_gen != getattr(self, "_sqlite_rebuild_gen", -1):
            return
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Indexing table", status_message=None, job_id=job_id)
        logger.warning("SQLite rebuild failed: %s", msg)
        self._sqlite_rebuild_in_progress = False
        pending = getattr(self, "_sqlite_rebuild_pending_path", None)
        self._sqlite_rebuild_pending_path = None
        if pending is not None:
            from ...storage.sqlite_table_store import unlink_sqlite_files

            unlink_sqlite_files(pending)
        self._sqlite_rebuild_pending_filters = False
        self.status_label.setText("Table indexing failed — filters may be slow until data changes.")
