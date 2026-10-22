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

"""File ingest chunks, silent-model append, and post-ingest follow-up."""

from __future__ import annotations

import logging
import time
from contextlib import nullcontext

from PyQt5.QtCore import QEventLoop, QTimer
from PyQt5.QtWidgets import QApplication

from rdkit import Chem

from ...platform_support.config import load_config
from ...conformers.conformer_column_codec import (
    is_packed_ensemble_header,
    make_sidecar_cell,
    mol_coordinates_fill_blank_confs,
    mol_has_3d_coordinates,
)
from ...storage import ensure_confs_sidecar
from ...table.open_messages import damaged_file_message
from ...table.text_file_ingest import is_ingest_cell_batch
from ..strings import LOADING_DETAIL_AFTER_FILE_READ, STATUS_READY_RENDER_2D, TOOL_RENDER_2D

logger = logging.getLogger(__name__)


class IngestLoadMixin:
    def _on_structure_source_probe(self, headers: list) -> None:
        """Worker paused after first record; pick structure column before bulk read."""
        incoming = list(headers)
        if self._ingest_append_mode and self._table_model.rowCount() > 0:
            self._merge_import_headers(incoming)
        else:
            self.headers = incoming
        from ...chem.structure_source_headers import structure_source_picker_candidates
        from ..dialogs.structure_source import StructureSourcePickerDialog

        struct_cols = structure_source_picker_candidates(self.headers)
        if len(struct_cols) >= 2:
            picked, ok = StructureSourcePickerDialog.pick_column(self, struct_cols)
            if ok and picked:
                self._ingest_structure_field = picked
            elif not ok:
                self._ingest_structure_field = None
        ev = getattr(self, "_structure_choice_event", None)
        if ev is not None:
            ev.set()

    def _maybe_start_ingest_processing(self) -> None:
        if self._processing_batches:
            return
        if not self._pending_batches and not self._last_batch_received:
            return
        self._processing_batches = True
        QTimer.singleShot(0, self._process_next_chunk)

    def _ingest_use_silent_model(self) -> bool:
        return bool(load_config().ingest_silent_model_append)

    def _ingest_use_sqlite_incremental(self) -> bool:
        return bool(load_config().ingest_sqlite_incremental)

    def _sqlite_data_headers(self) -> list[str]:
        return [h for h in self.headers[2:] if h and not self._table_model.is_pixmap_data_column(h)]

    def _ingest_sqlite_entries_from_rows(
        self,
        new_rows: list[tuple[int, dict[str, str]]],
        data_headers: list[str],
    ) -> list[tuple[int, dict[str, str]]]:
        return [
            (int(oid), {h: str(cells.get(h, "") or "") for h in data_headers})
            for oid, cells in new_rows
        ]

    def _ingest_sqlite_begin_bulk(self) -> None:
        store = getattr(self, "_sqlite_store", None)
        if store is None or not self._ingest_use_sqlite_incremental():
            return
        data_headers = self._sqlite_data_headers()
        if self._ingest_append_mode and self._table_model.rowCount() > 0:
            if frozenset(store.headers) != frozenset(data_headers):
                return
            self._ingest_sqlite_bulk_active = True
            self._ingest_sqlite_bulk_headers = list(data_headers)
            self._ingest_sqlite_paused_dirty = True
            return
        try:
            store.begin_bulk_load(self.headers)
        except Exception:
            logger.exception("Failed to begin incremental SQLite ingest")
            self._ingest_sqlite_bulk_active = False
            self._ingest_sqlite_paused_dirty = False
            return
        self._ingest_sqlite_bulk_active = True
        self._ingest_sqlite_bulk_headers = list(data_headers)
        self._ingest_sqlite_paused_dirty = True

    def _ingest_sqlite_append_batch(self, new_rows: list[tuple[int, dict[str, str]]]) -> None:
        if not getattr(self, "_ingest_sqlite_bulk_active", False) or not new_rows:
            return
        store = getattr(self, "_sqlite_store", None)
        headers = getattr(self, "_ingest_sqlite_bulk_headers", None)
        if store is None or not headers:
            return
        try:
            store.append_bulk_rows(self._ingest_sqlite_entries_from_rows(new_rows, headers))
        except Exception:
            logger.exception("Incremental SQLite ingest append failed")
            self._ingest_sqlite_bulk_active = False
            self._ingest_sqlite_paused_dirty = False
            self._sqlite_store_dirty = True

    def _ingest_sqlite_finalize_bulk(self) -> bool:
        """Return True when the SQLite mirror is ready and no rebuild is needed."""
        if not getattr(self, "_ingest_sqlite_bulk_active", False):
            self._ingest_sqlite_paused_dirty = False
            return False
        store = getattr(self, "_sqlite_store", None)
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        if store is None:
            return False
        if store.bulk_loading:
            try:
                store.finalize_bulk_load()
            except Exception:
                logger.exception("Failed to finalize incremental SQLite ingest")
                self._sqlite_store_dirty = True
                return False
        self._sqlite_store_dirty = False
        return True

    def _ingest_begin_silent_if_needed(self) -> None:
        if self._ingest_use_silent_model() and not self._table_model.silent_appending:
            self._table_model.begin_silent_appends()

    def _ingest_append_batch_items(
        self, items: list, new_rows: list[tuple[int, dict[str, str]]]
    ) -> None:
        """Convert one worker batch (mol blobs or cell dicts) into pending table rows.

        Every row's molecule goes to the store here, once. Cells are kept exactly as read.
        When the user picked a structure column at open, that column's text is the row's
        molecule; otherwise it is the file's structure (or the ``SMILES`` cell of a text file).
        """
        source_field = self._ingest_structure_source_field()
        texts: list[tuple[int, str]] = []
        if is_ingest_cell_batch(items):
            for cells in items:
                oid = self.next_oid
                self.next_oid += 1
                new_rows.append((oid, dict(cells)))
                text = (
                    source_field and self._ingest_cell_structure_text(cells, source_field)
                ) or self._ingest_cell_structure_text(cells, "SMILES")
                if text:
                    texts.append((oid, text))
            self._ingest_store_structure_texts(texts)
            return
        # Structures go to the store in one write per batch; see ``_ingest_store_mol``.
        batch: list | None = [] if callable(getattr(self.mols, "ingest_structures", None)) else None
        for item in items:
            blob, cells, smiles = self._split_ingest_item(item)
            oid = self.next_oid
            self.next_oid += 1
            text = self._ingest_cell_structure_text(cells, source_field) if source_field else ""
            if text:
                new_rows.append((oid, dict(cells)))
                texts.append((oid, text))
                continue
            new_rows.append(
                (
                    oid,
                    self._ingest_store_mol(
                        oid,
                        self._coerce_ingest_mol(blob),
                        precomputed_cells=cells,
                        source_blob=blob if isinstance(blob, (bytes, bytearray)) else None,
                        source_text=smiles,
                        batch=batch,
                    ),
                )
            )
        if batch:
            self.mols.ingest_structures(batch)
        self._ingest_store_structure_texts(texts)

    def _ingest_structure_source_field(self) -> str | None:
        """The column the user picked as the structure source for this open, if any."""
        field = getattr(self, "_ingest_structure_field", None)
        if not isinstance(field, str) or not field.strip():
            return None
        from ...chem.structure_source_headers import is_tool_generated_structure_header

        return None if is_tool_generated_structure_header(field) else field.strip()

    @staticmethod
    def _ingest_cell_structure_text(cells, field: str) -> str:
        if not isinstance(cells, dict):
            return ""
        return str(cells.get(field) or "").strip()

    def _ingest_store_structure_texts(self, texts: list[tuple[int, str]]) -> None:
        """Store rows whose molecule is cell text; RDKit parses each one when it is first needed."""
        if not texts:
            return
        ingest_jobs = getattr(self.mols, "ingest_jobs", None)
        if callable(ingest_jobs):
            ingest_jobs((oid, None, text) for oid, text in texts)
            return
        for oid, text in texts:
            mol = self._mol_from_structure_text(text)
            if mol is not None:
                self.mols[oid] = mol

    @staticmethod
    def _split_ingest_item(item):
        """Return ``(blob_or_mol, precomputed_cells, canonical_smiles)`` from a worker item."""
        if isinstance(item, tuple):
            return item[0], item[1], item[2] if len(item) > 2 else ""
        return item, None, ""

    @staticmethod
    def _coerce_ingest_mol(item) -> Chem.Mol | None:
        """Rebuild a live RDKit mol from an ingest blob (worker sends binary to avoid UI freezes)."""
        if isinstance(item, (bytes, bytearray)):
            try:
                return Chem.Mol(bytes(item))
            except Exception:
                return None
        return item

    def _ingest_store_mol(
        self,
        oid: int,
        mol: Chem.Mol,
        precomputed_cells: dict[str, str] | None = None,
        *,
        source_blob: bytes | None = None,
        source_text: str = "",
        batch: list | None = None,
    ) -> dict[str, str]:
        """
        Store *mol* for row *oid*.

        When the molecule carries 3D coordinates, pack them into ``confs`` (for View
        Conformers) and keep a 2D depiction in ``self.mols`` for the Structure column.
        A 2D structure is packed the same way when the file already has a ``confs``
        column and that cell is empty, so a structure with no ensemble is not blank.

        *precomputed_cells* are row cells built off the GUI thread by the load worker; when
        provided they are used verbatim (avoids re-reading every property on the GUI thread).

        *batch*, when given, collects ``(oid, mol, blob, smiles)`` for one bulk store write
        instead of a per-row insert. *source_blob* is the load worker's already-serialized
        structure, reused so ingest never re-pickles a molecule the worker just pickled.
        *source_text* is the worker's canonical SMILES for *mol*; without it the store
        computes the text the first time the Structure cell asks for it.
        """
        cells = (
            dict(precomputed_cells)
            if precomputed_cells is not None
            else self._row_cells_from_mol(mol)
        )
        confs_cell = cells.get("confs") if "confs" in cells else None
        if mol is not None and (
            mol_has_3d_coordinates(mol) or mol_coordinates_fill_blank_confs(mol, confs_cell)
        ):
            from ..mol_viewer_3d import prepare_mol_2d

            self._ensure_columns(["confs"])
            try:
                n_conf = int(mol.GetNumConformers())
            except Exception:
                n_conf = 0
            meta = {
                "ok": True,
                "op": "ingest",
                "n_kept": n_conf,
                "n_packed": n_conf,
            }
            sc = ensure_confs_sidecar(self)
            sc.store_mol(int(oid), "confs", mol)
            light = make_sidecar_cell("confs", meta)
            depict = prepare_mol_2d(mol)
            # The depiction is a fresh 2D copy, so the worker blob does not describe it.
            self._ingest_remember_mol(
                oid, depict if depict is not None else mol, None, source_text, batch
            )
            cells["confs"] = light
            return cells
        self._ingest_remember_mol(oid, mol, source_blob, source_text, batch)
        return cells

    def _ingest_remember_mol(
        self,
        oid: int,
        mol: Chem.Mol | None,
        source_blob: bytes | None,
        source_text: str,
        batch: list | None,
    ) -> None:
        """Hand one ingested structure to the molecule store, batched when the store supports it."""
        if batch is None:
            self.mols[oid] = mol
            return
        if mol is None:
            return
        # The store keeps connection tables only. The worker blob matches that byte for byte
        # when the molecule carries no conformers; otherwise it has coordinates to strip.
        if source_blob is not None and mol.GetNumConformers():
            source_blob = None
        batch.append((int(oid), mol, source_blob, source_text or ""))

    def _note_open_attempt(self, title: str) -> None:
        """Remember workspace state so a failed open can restore the dirty flag."""
        self._file_open_dialog_title = title
        unsaved = getattr(self, "_session_has_unsaved_changes", None)
        self._file_open_was_dirty = bool(unsaved()) if callable(unsaved) else False
        has_content = getattr(self, "_session_has_workspace_content", None)
        self._file_open_had_content = bool(has_content()) if callable(has_content) else False

    def _abort_ingest_sqlite_bulk(self) -> None:
        if not getattr(self, "_ingest_sqlite_bulk_active", False):
            self._ingest_sqlite_paused_dirty = False
            return
        store = getattr(self, "_sqlite_store", None)
        self._ingest_sqlite_bulk_active = False
        self._ingest_sqlite_paused_dirty = False
        self._ingest_sqlite_bulk_headers = None
        if store is not None:
            abort = getattr(store, "abort_bulk_load", None)
            if callable(abort):
                abort()
        self._sqlite_store_dirty = True

    def _finish_failed_open(self) -> None:
        """Drop the loading page after a file or session read fails."""
        self._pending_session_clean_on_ready = False
        self._pending_batches = []
        self._processing_batches = False
        self._last_batch_received = False
        self._ingest_append_mode = False
        model = getattr(self, "_table_model", None)
        if model is not None:
            try:
                if model.silent_appending:
                    model.end_silent_appends()
            except Exception:
                logger.debug("end_silent_appends failed after open error", exc_info=True)
        self._abort_ingest_sqlite_bulk()
        table = getattr(self, "table", None)
        if table is not None:
            try:
                table.setUpdatesEnabled(True)
            except Exception:
                pass
        self._import_progress_active = False
        clear = getattr(self, "_clear_tool_progress", None)
        if callable(clear):
            clear(status_message=None)
        self._set_ingest_loading(False)
        self._set_workspace_stack_index(1)
        rows = int(model.rowCount()) if model is not None else 0
        title = str(getattr(self, "_file_open_dialog_title", "") or "")
        had = bool(getattr(self, "_file_open_had_content", False))
        was_dirty = bool(getattr(self, "_file_open_was_dirty", False))
        self._session_mutation_paused = False
        if title in ("Open File", "Open Session"):
            self._session_source_path = None
        if rows > 0 or (title in ("Open File", "Open Session") and had):
            self._session_dirty = True
        elif not was_dirty:
            self._session_dirty = False
        status = getattr(self, "status_label", None)
        if status is not None:
            status.setText("Ready.")

    def on_file_load_failed(self, generation: int, message: str) -> None:
        """A replace/import read failed after the loading page was shown."""
        if int(generation) != int(getattr(self, "_file_ingest_generation", 0)):
            return
        self._finish_failed_open()
        title = str(getattr(self, "_file_open_dialog_title", "") or "Open File")
        text = message or damaged_file_message("")
        warn = getattr(self, "_warn_could_not_open", None)
        if callable(warn):
            warn(title, text)

    def on_file_loaded(self, mols_list, headers, is_first, is_last):
        # A Close Session bumps the generation so a load still in flight cannot refill the table.
        if getattr(self, "_file_ingest_epoch", 0) != getattr(self, "_file_ingest_generation", 0):
            self._pending_batches = []
            self._processing_batches = False
            self._last_batch_received = False
            return
        # Append batch to pending queue and schedule incremental processing
        if is_first:
            self._clear_filter_target_smiles_cache()
            incoming = list(headers)
            if self._ingest_append_mode and self._table_model.rowCount() > 0:
                self._merge_import_headers(incoming)
            else:
                self.headers = incoming
                self.table.setSortingEnabled(False)
                self._table_model.clear_rows()
                self._table_model.set_headers(list(self.headers))
                self.table.setColumnHidden(0, True)
            if self._table_stack.currentIndex() == 0:
                self._loading_detail.setText(LOADING_DETAIL_AFTER_FILE_READ)
            self._ingest_begin_silent_if_needed()
            self._ingest_sqlite_begin_bulk()
        if mols_list:
            self._pending_batches.append((mols_list, is_last))
        if is_last:
            self._last_batch_received = True
        if mols_list and not self._processing_batches:
            self._ingest_begin_silent_if_needed()
        self._maybe_start_ingest_processing()

    def _process_next_chunk(self, chunk_size: int | None = None):
        cfg = load_config()
        if chunk_size is None:
            chunk_size = int(cfg.ingest_gui_chunk_size)
        budget_s = max(0.005, int(cfg.ingest_gui_time_budget_ms) / 1000.0)
        deadline = time.monotonic() + budget_s
        processed = 0
        perf = getattr(self, "_perf", None)
        scope = perf.track if perf is not None else (lambda *_args, **_kwargs: nullcontext())
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        # Consume each worker batch in small sub-slices, re-checking the time budget between them,
        # so a single tick stays near ``ingest_gui_time_budget_ms`` even as per-row cost grows
        # (mol rebuild + property extraction + SQLite). This keeps the UI smooth during ingest.
        sub_slice = max(32, min(int(chunk_size), int(cfg.ingest_gui_subslice_rows)))
        try:
            with scope("ingest.process_chunk"):
                while (
                    self._pending_batches and processed < chunk_size and time.monotonic() < deadline
                ):
                    mols_list, is_last = self._pending_batches[0]
                    step = min(len(mols_list), sub_slice, max(0, int(chunk_size - processed)))
                    if step:
                        take = mols_list[:step]
                        new_rows: list[tuple[int, dict[str, str]]] = []
                        self._ingest_append_batch_items(take, new_rows)
                        self._table_model.append_rows_batch(new_rows, defer_color_cache=True)
                        self._ingest_sqlite_append_batch(new_rows)
                        processed += len(new_rows)
                        del mols_list[:step]
                    if not mols_list:
                        self._pending_batches.pop(0)
                        if is_last:
                            self._last_batch_received = True
            if processed:
                n = self._table_model.rowCount()
                self.status_label.setText(f"Loaded {n:,} molecules — preparing table…")
                if self._table_stack.currentIndex() == 0:
                    self._loading_detail.setText(
                        f"Building table…\n{n} molecule(s); 2D structures draw after the table is shown"
                    )
                if (
                    getattr(self, "_ingest_loading", False)
                    and not self._import_building_progress_shown
                ):
                    self._import_building_progress_shown = True
                    self._on_tool_progress("Building table…", -1, -1)
        finally:
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass

        if self._pending_batches:
            QTimer.singleShot(0, lambda: self._process_next_chunk(chunk_size))
        elif self._last_batch_received:
            QTimer.singleShot(0, self._finalize_ingest_on_gui_thread)
        else:
            self._processing_batches = False

    def _finalize_ingest_on_gui_thread(self) -> None:
        """Finish ingest on the loading page; reveal once filters and auto 2D are ready."""
        if self._table_model.silent_appending:
            self._table_model.end_silent_appends()
        if not self._ingest_sqlite_finalize_bulk():
            if getattr(self, "_sqlite_store", None) is not None:
                self._sqlite_store_dirty = True
            else:
                self._rebuild_sqlite_store_from_model()
        self.table.setSortingEnabled(False)
        self._structures_queued = 0
        self._ingest_prep_before_reveal = True
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        self._import_progress_active = False
        self._clear_tool_progress(status_message=None)
        self._ingest_append_mode = False
        self._last_batch_received = False
        self._processing_batches = False
        n = self._table_model.rowCount()
        self._loading_detail.setText(
            f"Table built ({n:,} row(s)).\nPreparing table, then {TOOL_RENDER_2D}…"
        )
        if any(is_packed_ensemble_header(h) for h in self.headers):
            QTimer.singleShot(0, self._migrate_legacy_confs_cells_to_sidecar)
        QTimer.singleShot(0, self._deferred_post_ingest_follow_up)

    def _deferred_post_ingest_follow_up(self) -> None:
        """Runs on the loading page: color caches and bounds, then reveal; auto 2D follows."""
        headers = self._table_model.pending_color_cache_headers()
        if headers:
            self._post_ingest_color_headers = headers
            self._post_ingest_color_idx = 0
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._post_ingest_after_color_caches()

    def _post_ingest_color_cache_step(self) -> None:
        headers = getattr(self, "_post_ingest_color_headers", None) or []
        idx = int(getattr(self, "_post_ingest_color_idx", 0))
        if idx < len(headers):
            if getattr(self, "_ingest_prep_before_reveal", False):
                self._loading_detail.setText(
                    f"Preparing conditional formatting…\n({idx + 1}/{len(headers)} columns)"
                )
            self._table_model._rebuild_column_color_cache(headers[idx])
            self._post_ingest_color_idx = idx + 1
            QTimer.singleShot(0, self._post_ingest_color_cache_step)
            return
        self._post_ingest_color_headers = []
        self._post_ingest_after_color_caches()

    def _post_ingest_after_color_caches(self) -> None:
        """Finish filter bounds, then auto Render 2D; reveal after bounds are ready."""
        self._ingest_waiting_for_render = False
        if getattr(self, "_ingest_prep_before_reveal", False):
            self._loading_detail.setText("Preparing filters…")
        self.calculate_global_bounds(on_complete=self._post_ingest_after_bounds)

    def _post_ingest_after_bounds(self) -> None:
        """Start auto Render 2D after bounds; show the table without waiting on images."""
        n = self._table_model.rowCount()
        started_render = self._try_auto_render_all_structures_after_ingest()
        if started_render and self._auto_render2d_blocks_workspace_reveal(n):
            self._loading_detail.setText(f"{TOOL_RENDER_2D}…\n{n:,} row(s)")
            self._ingest_waiting_for_render = True
            return
        keep_status = started_render or "auto 2D render skipped" in (self.status_label.text() or "")
        self._reveal_table_after_ingest_prep(keep_status=keep_status)

    def _ingest_on_render2d_batch_finished(self) -> None:
        """Reveal the workspace after auto Render 2D if ingest was waiting on it."""
        if not getattr(self, "_ingest_waiting_for_render", False):
            return
        self._ingest_waiting_for_render = False
        self._reveal_table_after_ingest_prep()

    def _reveal_table_after_ingest_prep(self, *, keep_status: bool = False) -> None:
        """Switch from the loading page to the table once rows and filter bounds are ready."""
        self._ingest_prep_before_reveal = False
        self._ingest_waiting_for_render = False
        self._set_ingest_loading(False)
        self._set_workspace_stack_index(1)
        finish_clean = getattr(self, "_finish_session_clean_if_pending", None)
        if callable(finish_clean):
            finish_clean()
        app = QApplication.instance()
        if app is not None:
            app.processEvents(QEventLoop.ExcludeUserInputEvents)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if keep_status:
            return
        n = self._table_model.rowCount()
        self.status_label.setText(STATUS_READY_RENDER_2D if n else "Ready.")
