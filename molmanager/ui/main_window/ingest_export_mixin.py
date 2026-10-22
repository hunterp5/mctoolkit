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

from __future__ import annotations

import logging
import re
import sys
import threading
from contextlib import nullcontext

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ...platform_support.config import load_config
from ...table.open_messages import preflight_open_path
from ...table.table_file_formats import TABLE_OPEN_FILTER, TABLE_SAVE_FILTER
from ...workers import ExportWorker, UniversalLoadWorker
from ..recent_paths import KIND_FILE, remember_recent
from ..strings import LOADING_DETAIL_APPEND, LOADING_DETAIL_READING_DISK

logger = logging.getLogger(__name__)


class IngestExportMixin:
    def _warn_could_not_open(self, title: str, message: str) -> None:
        """Show one open failure. Headless tests record the message and skip the dialog."""
        text = message or "Could not open that file."
        self._last_open_error = text
        logger.warning("%s: %s", title, text)
        if "pytest" in sys.modules:
            return
        QMessageBox.warning(self, title, text)

    def _reject_unopenable_path(self, path: str, *, title: str) -> bool:
        """Warn and return True when *path* is missing, a folder, or not readable."""
        problem = preflight_open_path(path)
        if not problem:
            self._last_open_error = None
            return False
        self._warn_could_not_open(title, problem)
        return True

    def open_file_dialog(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open File", "", TABLE_OPEN_FILTER)
        if path:
            self.load_file(path)

    def open_import_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import Data", "", TABLE_OPEN_FILTER)
        if path:
            self.import_file(path)

    def load_file(self, path: str) -> None:
        if self._reject_unopenable_path(path, title="Open File"):
            return
        remember_recent(KIND_FILE, path)
        self._note_open_attempt("Open File")
        self._accept_file_ingest_results()
        self._ingest_append_mode = False
        self._ingest_structure_field = None
        self._session_mutation_paused = True
        self._pending_session_clean_on_ready = True
        self.clear_all()
        self._apply_table_only_layout_for_file_load()
        self._set_ingest_loading(True)
        self._structures_queued = 0
        self._import_building_progress_shown = False
        self._set_workspace_stack_index(0)
        self._loading_detail.setText(LOADING_DETAIL_READING_DISK)
        self.status_label.setText("Reading file…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        gen = int(self._file_ingest_generation)
        self.process_queue.enqueue(
            f"Open file: {path}",
            lambda ev, p=path, s=self.signals, sce=self._structure_choice_event, bs=batch_size, g=gen: (
                UniversalLoadWorker(
                    p,
                    s,
                    batch_size=bs,
                    cancel_event=ev,
                    structure_choice_event=sce,
                    ingest_generation=g,
                )
            ),
        )

    def _apply_table_only_layout_for_file_load(self) -> None:
        """Give the table the full workspace when replacing the session from a file."""
        from .workspace_layout import LAYOUT_TABLE_ONLY

        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None or mgr.layout_id == LAYOUT_TABLE_ONLY:
            return
        apply = getattr(self, "apply_workspace_layout", None)
        if callable(apply):
            apply(LAYOUT_TABLE_ONLY)

    def import_file(self, path: str) -> None:
        """Load molecules from disk and append them to the current table (merge columns as needed)."""
        if self._reject_unopenable_path(path, title="Import Data"):
            return
        remember_recent(KIND_FILE, path)
        self._note_open_attempt("Import Data")
        self._accept_file_ingest_results()
        self._pending_batches = []
        self._processing_batches = False
        self._last_batch_received = False
        self._ingest_structure_field = None
        self._ingest_append_mode = True
        self._pending_session_clean_on_ready = False
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self._set_ingest_loading(True)
        self._structures_queued = 0
        self._import_building_progress_shown = False
        self._set_workspace_stack_index(0)
        self._loading_detail.setText(LOADING_DETAIL_APPEND)
        self.status_label.setText("Importing…")
        self._ensure_structure_choice_event().set()
        batch_size = load_config().ingest_worker_batch_size
        gen = int(self._file_ingest_generation)
        self.process_queue.enqueue(
            f"Import data: {path}",
            lambda ev, p=path, s=self.signals, sce=self._structure_choice_event, bs=batch_size, g=gen: (
                UniversalLoadWorker(
                    p,
                    s,
                    batch_size=bs,
                    cancel_event=ev,
                    structure_choice_event=sce,
                    ingest_generation=g,
                )
            ),
        )

    def _accept_file_ingest_results(self) -> None:
        """Let the next file-load batches reach the table after a Close Session."""
        generation = int(getattr(self, "_file_ingest_generation", 0)) + 1
        self._file_ingest_generation = generation
        self._file_ingest_epoch = generation

    def _reject_file_ingest_results(self) -> None:
        """Drop batches from a file load that was in flight when the session closed."""
        self._file_ingest_generation = int(getattr(self, "_file_ingest_generation", 0)) + 1

    def _ensure_structure_choice_event(self) -> threading.Event:
        ev = getattr(self, "_structure_choice_event", None)
        if ev is None:
            ev = threading.Event()
            ev.set()
            self._structure_choice_event = ev
        return ev

    def _merge_import_headers(self, incoming: list[str]) -> None:
        """Extend ``self.headers`` / the table model with columns from an appended file."""
        old_tail = list(self.headers[2:]) if len(self.headers) > 2 else []
        inc_tail = list(incoming[2:]) if len(incoming) > 2 else []
        seen = set(old_tail)
        merged_tail = list(old_tail)
        for h in inc_tail:
            if h not in seen:
                seen.add(h)
                merged_tail.append(h)
        self.table.setSortingEnabled(False)
        old_set = set(old_tail)
        for h in merged_tail:
            if h not in old_set:
                nc = self._table_model.columnCount()
                self._table_model.insert_column_at(nc, h, None)
                old_set.add(h)
        self.headers = ["ID_HIDDEN", "Structure"] + merged_tail

    def run_export(self, selected=False):
        if self._table_model.rowCount() == 0:
            return
        if getattr(self, "_export_busy", False):
            QMessageBox.warning(self, "Export", "An export is already in progress.")
            return
        # Export in current visual column order (but always include ID/Structure first).
        vis_cols = self._visual_logical_columns()
        ordered_headers = [self.headers[i] for i in vis_cols if i < len(self.headers)]
        headers = ["ID_HIDDEN", "Structure"] + [
            h for h in ordered_headers if h not in ("ID_HIDDEN", "Structure")
        ]
        if selected:
            # Prefer logical selection (OID override / Qt / model highlights) so tool
            # picks like Diverse Subset export correctly even when Qt selection was cleared.
            oids = sorted(int(o) for o in self._selected_oids_set())
            if not oids:
                QMessageBox.information(
                    self,
                    "Export Selected",
                    "No rows are selected. Select one or more rows in the table first.",
                )
                return
            oids_list = oids
        else:
            oids_list = list(self._table_model.all_oids_in_order())
        path, sel_f = QFileDialog.getSaveFileName(self, "Export Data", "", TABLE_SAVE_FILTER)
        if path:
            # Robustly infer the extension even if the Qt filter string is empty/unexpected.
            ext = ""
            m = re.search(r"\(([^)]+)\)", sel_f or "")
            if m:
                # e.g. "*.sdf" or "*.sdf *.mol" -> take first token
                tok = (m.group(1).split() or [""])[0]
                ext = tok.replace("*", "").strip()
            if not ext:
                # Fall back to what user typed.
                ext = ("." + path.split(".")[-1]) if "." in path else ""
            if not ext:
                # Last resort: default to .sdf
                ext = ".sdf"
            if not path.lower().endswith(ext.lower()):
                path += ext
            h_map = {h: i for i, h in enumerate(self.headers)}
            chunk = max(256, int(load_config().ingest_gui_chunk_size))
            self._export_busy = True
            self._export_prep = {
                "path": path,
                "ext": ext,
                "headers": headers,
                "h_map": h_map,
                "oids": oids_list,
                "cells": {},
                "idx": 0,
                "chunk": chunk,
                "cols": [h for h in headers if h in self.headers],
            }
            self._on_tool_progress("Preparing export…", 0, max(len(oids_list), 1))
            QTimer.singleShot(0, self._export_snapshots_continue)

    def _export_snapshots_continue(self) -> None:
        prep = self._export_prep
        if not prep:
            return
        try:
            oids = prep["oids"]
            h_map = prep["h_map"]
            cols = prep["cols"]
            n = len(oids)
            chunk = prep["chunk"]
            start = prep["idx"]
            end = min(start + chunk, n)
            perf = getattr(self, "_perf", None)
            scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
            with scope("export.snapshot_chunk"):
                for j in range(start, end):
                    oid = oids[j]
                    r = self.logical_row_for_oid(oid)
                    if r != -1:
                        prep["cells"][oid] = {h: self._export_cell_text(r, h_map[h]) for h in cols}
                    else:
                        prep["cells"][oid] = {h: "" for h in cols}
            prep["idx"] = end
            self._on_tool_progress("Preparing export…", end, max(n, 1))
            if end < n:
                QTimer.singleShot(0, self._export_snapshots_continue)
                return
            path = prep["path"]
            ext = prep["ext"]
            cells = prep["cells"]
            headers = prep["headers"]
            oids_out = list(prep["oids"])
            mols = self.mols
            depiction_store = getattr(self, "_depiction_coords", None)
            depiction = (
                depiction_store.column_items("Structure", set(oids_out))
                if depiction_store is not None
                else {}
            )
            self._export_prep = None
            self.process_queue.enqueue(
                f"Export to {path}",
                lambda ev, p=path, e=ext, m=mols, h=headers, d=cells, o=oids_out, s=self.signals, coords=depiction: (
                    ExportWorker(p, e, m, h, d, s, cancel_event=ev, oids=o, depiction_coords=coords)
                ),
            )
        except Exception as e:
            self._export_prep = None
            self._export_busy = False
            self._clear_tool_progress()
            QMessageBox.warning(self, "Export", str(e))
            self.status_label.setText("Ready")
