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

"""Batch 2D structure rendering for the main table."""

from __future__ import annotations

import threading

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ...platform_support.config import load_config
from ...table.structure_depiction_layout import (
    reaction_depict_size,
    structure_depict_height,
    structure_depict_width,
)
from ...chem.reaction_file_io import looks_like_reaction_smarts, parse_reaction_smarts
from ...chem.render2d_mp import REACTION_PAYLOAD_TAG
from ...chem.structure_2d_depiction import ReactionDrawSpec
from ...chem.structure_source_headers import (
    is_common_core_structure_header,
    is_murcko_structure_header,
)
from ...workers import (
    STRUCTURE_PAYLOAD_TAG,
    Render2DBatchHeldJob,
    Render2DBatchProcessWorker,
)
from ..strings import TOOL_RENDER_2D
from .column_write_mixin import cell_looks_uncalculated

# PNG bytes for cancel. Above this, redrawing costs less than retaining every image.
_RENDER2D_UNDO_SNAPSHOT_MAX_ROWS = 5000


def _draws_on_write(header: str) -> bool:
    return is_murcko_structure_header(header) or is_common_core_structure_header(header)


def _render_task_has_structure(task) -> bool:
    """True when a render task carries SMILES rather than a blank or placeholder cell."""
    payload = task[1] if len(task) > 1 else None
    if not isinstance(payload, tuple) or len(payload) < 3:
        return bool(payload)
    raw = payload[2]
    if isinstance(raw, (bytes, bytearray)):
        text = raw.decode("utf-8", errors="replace")
    else:
        text = str(raw or "")
    return bool(text.strip()) and not cell_looks_uncalculated(text)


class Render2DMixin:
    def _build_render2d_tasks_from_mols(
        self,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Build render tasks from ``self.mols`` (O(n) with O(1) row lookup; used after file/SQL ingest).

        Structures stay serialized. The render subprocesses rebuild each one themselves, so
        hydrating RDKit mols here only to re-pickle them in the worker costs seconds of GUI
        freeze on large tables.
        """
        renders: list = []
        row_by_oid: dict[int, int] = {}
        row_for_oid = self._table_model.logical_row_for_oid
        zoom_w, zoom_h = structure_depict_width() * 2, structure_depict_height() * 2
        for oid, payload in self._iter_render2d_structure_payloads():
            if allowed_oids is not None and oid not in allowed_oids:
                continue
            row = row_for_oid(oid)
            if row < 0:
                continue
            rw, rh = (zoom_w, zoom_h) if oid in self.zoomed_ids else (base_w, base_h)
            renders.append((oid, payload, rw, rh))
            row_by_oid[oid] = row
        return renders, row_by_oid

    def _depiction_bytes_for_render(self, column: str, oid: int) -> bytes:
        """Packed orientation for one cell, or empty bytes for the usual layout."""
        store = getattr(self, "_depiction_coords", None)
        if store is None:
            return b""
        return store.get(str(column), int(oid)) or b""

    def _iter_render2d_structure_payloads(self):
        """Yield ``(oid, payload)`` for every stored structure, preferring unhydrated payloads.

        ``payload`` is a :data:`STRUCTURE_PAYLOAD_TAG` tuple when the store can hand over raw
        bytes, otherwise a live mol (plain-dict stores used by tests and older sessions).
        """
        store = self.mols
        bulk = getattr(store, "iter_structure_payloads", None)
        if not callable(bulk):
            from ...chem.depiction_coords import apply_depiction_coords

            for oid in list(store):
                mol = store.get(int(oid))
                if mol is not None:
                    yield (
                        int(oid),
                        apply_depiction_coords(
                            mol, self._depiction_bytes_for_render("Structure", int(oid))
                        ),
                    )
            return
        for oid, blob, smiles in bulk():
            if not blob and not smiles:
                continue
            yield (
                oid,
                (
                    STRUCTURE_PAYLOAD_TAG,
                    blob or b"",
                    smiles.encode("utf-8"),
                    self._depiction_bytes_for_render("Structure", int(oid)),
                ),
            )

    def _build_render2d_tasks_in_table_order(
        self,
        src: str,
        base_w: int,
        base_h: int,
        allowed_oids: set[int] | None = None,
    ) -> tuple[list, dict[int, int]]:
        """Collect ``(oid, payload, w, h)`` tasks in table row order, plus the oid→row map.

        Payloads stay serialized (:data:`STRUCTURE_PAYLOAD_TAG` / :data:`REACTION_PAYLOAD_TAG`
        tuples); the render subprocesses parse them. Hydrating every row here costs tens of
        seconds of GUI freeze on 100k-row tables.
        """
        if src != "Structure" and src not in self.headers:
            return [], {}
        payloads = self.collect_scoped_table_structure_payloads(src, allowed_oids=allowed_oids)
        renders: list = []
        row_by_oid: dict[int, int] = {}
        row_for_oid = self._table_model.logical_row_for_oid
        zoom_w, zoom_h = structure_depict_width() * 2, structure_depict_height() * 2
        for payload in payloads:
            oid = int(payload.oid)
            text = (payload.smiles or "").strip()
            zoomed = oid in self.zoomed_ids
            if src != "Structure" and looks_like_reaction_smarts(text):
                task_payload: tuple = (REACTION_PAYLOAD_TAG, text.encode("utf-8"))
                rw, rh = reaction_depict_size(zoomed=zoomed)
            else:
                task_payload = (
                    STRUCTURE_PAYLOAD_TAG,
                    payload.blob or b"",
                    text.encode("utf-8"),
                    self._depiction_bytes_for_render(src, oid),
                )
                rw, rh = (zoom_w, zoom_h) if zoomed else (base_w, base_h)
            renders.append((oid, task_payload, rw, rh))
            row_by_oid[oid] = row_for_oid(oid)
        return renders, row_by_oid

    def _build_render2d_tasks_for_oids(
        self,
        oids: list[int],
        base_w: int,
        base_h: int,
    ) -> tuple[list, dict[int, int]]:
        """Build Structure render tasks for explicit oids (used after bulk external append)."""
        return self._build_render2d_tasks_in_table_order(
            "Structure", base_w, base_h, {int(oid) for oid in oids}
        )

    def _try_auto_render_all_structures_after_ingest(self) -> bool:
        """Queue 2D renders for every row with an in-memory Structure mol (file ingest, SQL, or session)."""
        if getattr(self, "_render2d_batch_active", False):
            return False
        if not self.headers or self._table_model.rowCount() == 0:
            return False
        n_rows = self._table_model.rowCount()
        cfg = load_config()
        max_auto = int(cfg.auto_render_2d_max_rows)
        if max_auto > 0 and n_rows > max_auto:
            self.status_label.setText(
                f"Loaded {n_rows:,} rows — auto 2D render skipped (limit {max_auto:,}). "
                "Use Chemistry → Render 2D for visible or selected rows."
            )
            return False
        self.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_from_mols(base_w, base_h, None)
        if not renders:
            # Session restore may have rows before mols are keyed; rebuild from table cells.
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                "Structure", base_w, base_h, None
            )
        if not renders:
            return False
        self._render2d_after_ingest = True
        self._start_render_2d_batch(renders, row_by_oid, "Structure")
        return True

    def _auto_render2d_blocks_workspace_reveal(self, n_rows: int | None = None) -> bool:
        """True when ingest/session should wait for auto Render 2D before showing the table.

        Auto 2D continues in the background after the workspace appears. ``n_rows`` is
        accepted for call-site compatibility.
        """
        _ = n_rows
        return False

    def _restore_render2d_batch_environment(self) -> None:
        """Re-enable sorting and thread pool after a Render 2D run (or if cleared mid-batch)."""
        self._render2d_accept_session = None
        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        self._render2d_row_by_oid = None
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        self._render2d_pixmap_target = None
        self._render2d_column_pixmap_mode = True
        self._resize_columns_after_render2d(pix_target)
        finishing_batch = bool(getattr(self, "_render2d_batch_active", False))
        if finishing_batch:
            pending = getattr(self, "_pending_session_table_layout", None)
            restore_chrome = getattr(self, "_restore_session_table_chrome", None)
            if pending and callable(restore_chrome):
                restore_chrome(pending)
            elif pending:
                restore = getattr(self, "_restore_table_layout", None)
                if callable(restore):
                    restore(pending)
            restore_ws = getattr(self, "_restore_pending_workspace_layout", None)
            if callable(restore_ws):
                restore_ws()
            finish_ws = getattr(self, "_finish_deferred_session_workspace_restore", None)
            if callable(finish_ws):
                from PyQt5.QtCore import QTimer

                QTimer.singleShot(0, finish_ws)
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        if self._render2d_saved_sort_enabled is not None:
            try:
                self.table.setSortingEnabled(self._render2d_saved_sort_enabled)
            except Exception:
                pass
            self._render2d_saved_sort_enabled = None
        self._render2d_batch_active = False
        self._render2d_cancel_event = None
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        done_ev = getattr(self, "_render2d_batch_done_event", None)
        if done_ev is not None:
            done_ev.set()
        pq = getattr(self, "process_queue", None)
        if pq is not None:
            pq.schedule_resume()
        on_ingest = getattr(self, "_ingest_on_render2d_batch_finished", None)
        if callable(on_ingest):
            on_ingest()
        on_session = getattr(self, "_session_on_render2d_batch_finished", None)
        if callable(on_session):
            on_session()

    def _running_process_queue_title(self) -> str:
        """Title of the serial process-queue job, or ``""`` if none is running."""
        pq = getattr(self, "process_queue", None)
        if pq is None or not pq.has_running_job():
            return ""
        snap = pq.snapshot() if hasattr(pq, "snapshot") else {}
        return str((snap.get("running") or {}).get("title") or "")

    def _render2d_shares_ui_with_queue_job(self) -> bool:
        """True when Render 2D is drawing while another serial tool owns the status line."""
        title = self._running_process_queue_title()
        return bool(title) and "render 2d" not in title.lower()

    def cancel_render_2d_batch(self) -> bool:
        """Stop a Chemistry → Render 2D batch: no further chunks, workers skip drawing if not started."""
        if not self._render2d_batch_active:
            return False
        ev = getattr(self, "_render2d_cancel_event", None)
        if ev is not None:
            ev.set()
        self._render2d_queue = None
        self._render2d_accept_session = None
        rendered_oids = list(getattr(self, "_render2d_batch_oids_ordered", []) or [])
        self._close_render2d_stream_store()
        self._render2d_pending.clear()
        self._render2d_batch_oids_ordered.clear()
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        if getattr(self, "_render2d_lazy_flush", False) and not getattr(
            self, "_render2d_pixmap_target", None
        ):
            self._table_model.clear_structure_png_store()
        snap = getattr(self, "_render2d_snapshot", None)
        target = getattr(self, "_render2d_pixmap_target", None)
        streamed_column = bool(getattr(self, "_render2d_streamed_column", False))
        self._render2d_streamed_column = False
        if streamed_column and not snap and target:
            self._table_model.clear_column_pixmaps_for_oids(target, rendered_oids)
        elif snap:
            column_pixmap_mode = getattr(self, "_render2d_column_pixmap_mode", True)
            items = [(int(oid), raw) for oid, raw in snap.items()]
            if target and column_pixmap_mode:
                self._table_model.set_column_png_bytes_batch(target, items)
            elif target:
                for oid, raw in items:
                    self._table_model.set_cell_png_bytes(oid, target, raw)
            else:
                self._table_model.restore_structure_pngs(items)
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False
        self._import_progress_active = False
        if not self._render2d_shares_ui_with_queue_job():
            self._clear_tool_progress()
        self._restore_render2d_batch_environment()
        return True

    def run_render_2d_structures(self) -> None:
        """Queue 2D structure renders for all rows (after deferred load)."""
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._render2d_batch_active:
            QMessageBox.warning(
                self,
                TOOL_RENDER_2D,
                "A 2D render is already running. Wait for it to finish or cancel it from Log.",
            )
            return
        candidates = self.chemistry_tool_structure_sources()
        from ..dialogs import Render2DStructureDialog

        rd = Render2DStructureDialog(candidates, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(rd)
        rd.setAttribute(Qt.WA_DeleteOnClose, True)
        rd.accepted.connect(lambda *_, d=rd: self._on_render_2d_dialog_accepted(d))
        rd.show()

    def _on_render_2d_dialog_accepted(self, rd) -> None:
        src = rd.chosen_source()
        only_selected = rd.only_selected_rows()
        allowed_oids = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed_oids, TOOL_RENDER_2D):
            return
        if not self._render2d_shares_ui_with_queue_job():
            self.status_label.setText(f"{TOOL_RENDER_2D}: collecting structures…")
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(
            src, base_w, base_h, allowed_oids
        )
        if not renders:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                "No valid structures were found for the selected source.",
            )
            self.status_label.setText("No structures rendered.")
            return
        self._start_render_2d_batch(
            renders, row_by_oid, src, column_pixmap_mode=(src != "Structure")
        )

    def _queue_murcko_column_renders(
        self, headers: list[str], allowed_oids: set[int] | None
    ) -> None:
        """Draw generated structure columns after their text lands in the table.

        Murcko scaffold, framework, and ring systems are drawn. Scaffold count stays a
        number. The common-core SMARTS column is drawn the same way. Blank and ``N/A``
        cells are skipped. Each column is its own queue job.
        """
        columns = [
            header
            for header in headers
            if header in getattr(self, "headers", []) and _draws_on_write(header)
        ]
        if not columns:
            return
        queue = getattr(self, "process_queue", None)
        if queue is None:
            return
        base_w, base_h = structure_depict_width(), structure_depict_height()
        for header in columns:
            renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                header, base_w, base_h, allowed_oids
            )
            renders = [task for task in renders if _render_task_has_structure(task)]
            if not renders:
                continue
            kept = {int(task[0]) for task in renders}
            rows = {oid: row for oid, row in row_by_oid.items() if oid in kept}
            payload = (renders, rows, header, True)
            queue.enqueue(
                f"Render 2D: {header} ({len(renders)} rows)",
                lambda ev, p=payload: Render2DBatchHeldJob(self, p, ev),
            )

    def _start_render_2d_batch(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        queue_title_prefix: str = "",
    ) -> None:
        """Start a batch 2D render.

        When the serial process queue is idle, the job is queued (and typically starts
        immediately). When another tool is already running, the render starts off-queue
        so structures can be drawn without waiting for that tool to finish.
        """
        if getattr(self, "_render2d_batch_active", False):
            return
        if self._render2d_shares_ui_with_queue_job():
            self._begin_render2d_batch_impl(
                renders,
                row_by_oid,
                src,
                column_pixmap_mode=column_pixmap_mode,
            )
            return
        title = f"{queue_title_prefix}render 2D ({len(renders)} rows)".strip()
        payload = (renders, row_by_oid, src, column_pixmap_mode)
        self.process_queue.enqueue(
            title,
            lambda ev, p=payload: Render2DBatchHeldJob(self, p, ev),
        )

    def _begin_render2d_batch_impl(
        self,
        renders,
        row_by_oid,
        src: str = "Structure",
        *,
        column_pixmap_mode: bool = True,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """Start batch 2D rendering on the GUI thread (called from :class:`Render2DBatchHeldJob`)."""
        if cancel_event is not None and cancel_event.is_set():
            return
        self._render2d_session_id += 1
        self._render2d_batch_session_tag = self._render2d_session_id
        self._render2d_accept_session = self._render2d_batch_session_tag
        self._render2d_pixmap_target = None if src == "Structure" else src
        self._render2d_column_pixmap_mode = bool(column_pixmap_mode)
        if self._render2d_pixmap_target and self._render2d_column_pixmap_mode:
            self._table_model.register_pixmap_column(self._render2d_pixmap_target)
        self._render2d_saved_sort_enabled = self.table.isSortingEnabled()
        self.table.setSortingEnabled(False)
        self._render2d_batch_active = True
        self._render2d_row_by_oid = row_by_oid
        oids = [oid for oid, _, _, _ in renders]
        self._render2d_batch_oids_ordered = oids
        self._render2d_pending = {}
        structure_column = self._render2d_pixmap_target is None
        after_ingest = bool(getattr(self, "_render2d_after_ingest", False))
        self._render2d_after_ingest = False
        cfg = load_config()
        if after_ingest and structure_column:
            lazy_structure = len(oids) >= int(cfg.structure_render_lazy_after_ingest_min_rows)
        else:
            lazy_structure = self._render2d_use_lazy_structure_flush(
                len(oids), structure_column=structure_column
            )
        self._render2d_lazy_flush = lazy_structure
        self._render2d_streamed_column = False
        keep_snapshot = (not after_ingest) and len(oids) <= _RENDER2D_UNDO_SNAPSHOT_MAX_ROWS
        tgt = self._render2d_pixmap_target
        if tgt:
            # PNG bytes, not decoded QPixmaps. Large batches are cheaper to redraw than to keep.
            self._render2d_snapshot = (
                self._table_model.snapshot_column_pngs(tgt, oids) if keep_snapshot else {}
            )
            self._table_model.clear_column_pixmaps_for_oids(tgt, oids)
        elif lazy_structure:
            self._render2d_snapshot = (
                self._table_model.snapshot_structure_pngs(oids) if keep_snapshot else {}
            )
            self._table_model.clear_structure_png_store()
            self._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        else:
            self._render2d_snapshot = (
                self._table_model.snapshot_structure_pngs(oids) if keep_snapshot else {}
            )
            self._table_model.clear_structure_pixmaps_for_oids(oids, emit=False)
        self._open_render2d_stream_store(len(oids) if lazy_structure else 0)
        if structure_column and not lazy_structure:
            self._table_model.notify_structure_column_changed()
        self._render2d_progress_last_emit = 0.0
        self._render2d_progress_last_done = 0
        self._import_progress_active = True
        self._import_render_goal = len(renders)
        self._import_render_done = 0
        if not self._render2d_shares_ui_with_queue_job():
            self._on_tool_progress(TOOL_RENDER_2D, 0, len(renders))
        self._render2d_cancel_event = (
            cancel_event if cancel_event is not None else threading.Event()
        )
        self._render2d_queue = None
        hub = getattr(self, "background_activity", None)
        if hub is not None:
            hub.notify_changed()
        self._render_threadpool.start(
            Render2DBatchProcessWorker(
                renders,
                self.signals,
                self._render2d_cancel_event,
                self._render2d_batch_session_tag,
            )
        )

    def _render2d_source_header_for_column(self, col: int) -> str:
        """Header used as Render 2D source and pixmap target (clicked column, else Structure)."""
        if 0 <= col < len(self.headers):
            return self.headers[col]
        return "Structure"

    def _depict_payload_for_render2d_source(self, row: int, src: str):
        """Molecule or reaction SMARTS to draw for one row from the chosen source column."""
        if row < 0 or row >= self._table_model.rowCount():
            return None
        if src == "Structure":
            return self._mol_for_structure_row(row)
        if src not in self.headers:
            return None
        ci = self.headers.index(src)
        if self._table_model.is_pixmap_data_column(src):
            raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        else:
            raw = (self._table_cell_text(row, ci) or "").strip()
            if not raw:
                raw = (self._table_model.backing_value_for_row_header(row, src) or "").strip()
        if not raw:
            return None
        if looks_like_reaction_smarts(raw) and parse_reaction_smarts(raw) is not None:
            return ReactionDrawSpec(raw)
        return self._mol_from_structure_text(raw)

    def _mol_for_render2d_source(self, row: int, src: str) -> Chem.Mol | None:
        """Molecule to draw for one row from the chosen source column."""
        payload = self._depict_payload_for_render2d_source(row, src)
        if isinstance(payload, Chem.Mol):
            return payload
        return None

    def run_render_2d_for_table_row(self, row: int, col: int | None = None) -> None:
        """Run Render 2D for one row: read chemistry from ``col`` and write the pixmap into that column."""
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Load a table with at least one row first."
            )
            return
        if self._render2d_batch_active:
            QMessageBox.warning(
                self,
                TOOL_RENDER_2D,
                "A 2D render is already running. Wait for it to finish or cancel it from Log.",
            )
            return
        if row < 0 or row >= self._table_model.rowCount():
            return
        t0 = self._table_model.cell_text(row, 0)
        oid = int(t0) if t0.isdigit() else None
        if oid is None:
            QMessageBox.information(
                self, TOOL_RENDER_2D, "Could not resolve this row’s compound id."
            )
            return
        src = self._render2d_source_header_for_column(col if col is not None else -1)
        payload = self._depict_payload_for_render2d_source(row, src)
        if payload is None:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        if src == "Structure" and isinstance(payload, Chem.Mol):
            self.mols[oid] = payload
        pixmap_mode = src != "Structure" and self._table_model.is_pixmap_data_column(src)
        base_w, base_h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(src, base_w, base_h, {oid})
        if not renders:
            QMessageBox.information(
                self,
                TOOL_RENDER_2D,
                f"No structure could be read from column “{src}” for this row.",
            )
            return
        self._start_render_2d_batch(renders, row_by_oid, src, column_pixmap_mode=pixmap_mode)
