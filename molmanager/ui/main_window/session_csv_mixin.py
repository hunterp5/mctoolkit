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

"""Legacy CSV session load path."""

from __future__ import annotations

import logging
import sys

from PyQt5.QtCore import QTimer, Qt

from ...storage import load_mols_from_parse_result
from ...table.open_messages import damaged_session_message, preflight_open_path
from ..strings import LOADING_DETAIL_SESSION
from ..threadpool_access import start_runnable_on_app_pool
from ...workers.session_rows_parse import (
    CsvSessionParseResult,
    CsvSessionParseWorker,
    SessionRowsParseSignals,
)

logger = logging.getLogger(__name__)


class SessionCsvMixin:
    def _abort_csv_session_load(self) -> None:
        """Cancel an in-progress legacy session CSV load."""
        self._session_parse_busy = False
        self._csv_session_ctx = None

    def load_session_csv(self, path: str) -> None:
        """Load a session CSV exported by `_write_session_csv`.

        File I/O and SMILES parsing run off the GUI thread; table appends stay
        chunked on the GUI thread (same pattern as ``.cms`` restore).
        """
        problem = preflight_open_path(path)
        if problem:
            logger.warning("Open session CSV: %s", problem)
            self._warn_could_not_open("Open Session", problem)
            return
        self._note_open_attempt("Open Session")
        self._session_mutation_paused = True
        self._pending_session_clean_on_ready = True
        self.clear_all()
        self._set_ingest_loading(True)
        self._set_workspace_stack_index(0)
        self._loading_detail.setText(LOADING_DETAIL_SESSION)
        self.status_label.setText("Loading session…")
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass

        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        gen = self._session_load_generation
        self._session_parse_busy = True
        self._loading_detail.setText("Parsing structures…")
        self.status_label.setText("Loading session… (parsing CSV)")
        signals = SessionRowsParseSignals(self)

        def _on_parsed(result, g=gen) -> None:
            self._on_csv_session_parsed(result, g)

        def _on_failed(message, g=gen) -> None:
            self._on_csv_session_parse_failed(message, g)

        worker = CsvSessionParseWorker(path, signals, gen)
        if "pytest" in sys.modules:
            signals.finished.connect(_on_parsed, type=Qt.DirectConnection)
            signals.failed.connect(_on_failed, type=Qt.DirectConnection)
            worker.run()
            self._drain_pending_session_load()
        else:
            signals.finished.connect(_on_parsed, type=Qt.QueuedConnection)
            signals.failed.connect(_on_failed, type=Qt.QueuedConnection)
            start_runnable_on_app_pool(self, worker)

    def _on_csv_session_parse_failed(self, message: str, generation: int) -> None:
        if generation != getattr(self, "_session_load_generation", 0):
            return
        self._session_parse_busy = False
        self._csv_session_ctx = None
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._session_hold_workspace_surfaces = False
        self._show_session_workspace_when_ready()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        path = str(getattr(self, "_session_source_path", None) or "")
        self._finish_failed_open()
        self._warn_could_not_open("Open Session", message or damaged_session_message(path))

    def _on_csv_session_parsed(self, result: object, generation: int) -> None:
        if generation != getattr(self, "_session_load_generation", 0):
            return
        self._session_parse_busy = False
        if not isinstance(result, CsvSessionParseResult):
            self._on_csv_session_parse_failed("Invalid session CSV parse result.", generation)
            return
        cols = list(result.columns or [])
        if "SMILES" not in cols:
            cols = ["SMILES"] + cols
        self.headers = ["ID_HIDDEN", "Structure"] + cols
        self.table.setSortingEnabled(False)
        self._table_model.clear_rows()
        self._table_model.set_headers(list(self.headers))
        self.table.setColumnHidden(0, True)
        load_mols_from_parse_result(self, result)
        self._clear_filter_target_smiles_cache()
        self.global_bounds = {}
        self.next_oid = int(result.next_oid)
        prepared = list(result.prepared_rows or [])
        if not prepared:
            self._finalize_session_csv_load()
            return
        chunk = self._session_gui_chunk_size()
        self._csv_session_ctx = {
            "gen": generation,
            "prepared_rows": prepared,
            "idx": 0,
            "chunk": chunk,
            "loaded": 0,
        }
        n = len(prepared)
        self.status_label.setText(f"Loading session… (0/{n:,} rows)")
        self._loading_detail.setText(f"Loading session…\n0 / {n:,} rows")
        QTimer.singleShot(0, self._load_session_csv_step)

    def _load_session_csv_step(self) -> None:
        ctx = getattr(self, "_csv_session_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            return
        prepared = ctx["prepared_rows"]
        i = int(ctx["idx"])
        chunk = int(ctx["chunk"])
        n = len(prepared)
        end = min(i + chunk, n)
        batch = prepared[i:end]
        if batch:
            self._table_model.append_rows_batch(batch)
        ctx["idx"] = end
        ctx["loaded"] = end
        self.status_label.setText(f"Loading session… ({end:,}/{n:,} rows)")
        self._loading_detail.setText(f"Loading session…\n{end:,} / {n:,} rows")
        if end < n:
            QTimer.singleShot(0, self._load_session_csv_step)
            return
        self._csv_session_ctx = None
        self._loading_detail.setText(f"Session loaded ({n:,} row(s)).\nPreparing table…")
        self._finalize_session_csv_load()

    def _finalize_session_csv_load(self) -> None:
        self.table.setSortingEnabled(False)
        rows_n = self._table_model.rowCount()
        if getattr(self, "_sqlite_store", None) is not None:
            self._sqlite_store_dirty = True
            schedule = getattr(self, "_schedule_sqlite_rebuild", None)
            if callable(schedule) and rows_n > 0:
                schedule()
        self._session_hold_workspace_surfaces = True
        self._session_awaiting_ready = True
        self._session_waiting_for_render = False
        self._session_plot_wait_deadline = None
        detail = getattr(self, "_loading_detail", None)
        if detail is not None:
            try:
                detail.setText("Preparing filters…")
            except RuntimeError:
                pass
        self.calculate_global_bounds(on_complete=self._deferred_session_post_load_follow_up)
