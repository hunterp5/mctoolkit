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

"""Apply batched Render 2D results and lazy Structure-cell refresh."""

from __future__ import annotations

import time

from PyQt5.QtCore import QEventLoop, Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication

from ...chem.depiction_scene import is_scene_blob
from ...platform_support.config import load_config
from ...table.structure_depiction_layout import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)
from ...storage.structure_render_store import StructureRenderStore
from ...table.structure_image import pixmap_from_structure_image
from ..strings import TOOL_RENDER_2D


class Render2DResultsMixin:
    def _render2d_batch_session_accepted(self, batch_session) -> bool:
        """False when a render result belongs to a superseded / cancelled batch."""
        rs = 0 if batch_session is None else int(batch_session)
        if rs == 0:
            return True
        cur = getattr(self, "_render2d_accept_session", None)
        return cur is not None and rs == cur

    def on_render2d_rows_ready(self, rows, batch_session) -> None:
        """Store one batch of subprocess render results (see ``WorkerSignals.rendered_batch``).

        The per-molecule path below does the same work one row at a time; batching keeps the GUI
        thread from being the bottleneck when tens of thousands of rows are drawn.
        """
        if not rows or not self._render2d_batch_session_accepted(batch_session):
            return
        # getattr: unit tests invoke this on a stand-in that only buffers ``_render2d_pending``.
        writer = getattr(self, "_render2d_write_png_rows", None)
        if callable(writer) and writer(rows):
            release = getattr(self, "_release_session_wait_when_viewport_drawn", None)
            if callable(release):
                release(rows)
            self._advance_render2d_batch_progress(len(rows))
            return
        pending = self._render2d_pending
        for oid, img, success, w, h in rows:
            oid = int(oid)
            if success and self._resolve_structure_row_for_oid(oid) != -1:
                pending[oid] = (bytes(img), True, int(w), int(h))
            else:
                pending[oid] = (b"", False, int(w), int(h))
        self._advance_render2d_batch_progress(len(rows))

    def _release_session_wait_when_viewport_drawn(self, rows) -> None:
        """Reveal an opening session once every on-screen row of the batch has landed.

        Rows off screen keep drawing behind the revealed workspace. Rows that failed to
        draw count as landed, so one bad structure cannot hold the overlay up.
        """
        if not getattr(self, "_session_waiting_for_render", False):
            return
        landed = getattr(self, "_render2d_landed_oids", None)
        if landed is None:
            landed = self._render2d_landed_oids = set()
        landed.update(int(row[0]) for row in rows)
        batch = getattr(self, "_render2d_row_by_oid", None) or {}
        model = self._table_model
        source_rows, _keep = self._visible_structure_source_rows()
        for source_row in source_rows:
            oid = int(model.row_oid(source_row))
            if oid in batch and oid not in landed:
                return
        self._session_on_render2d_batch_finished()

    def _advance_render2d_batch_progress(self, n_done: int) -> None:
        """Report render progress and finish the batch once every row has landed."""
        if not getattr(self, "_import_progress_active", False) or self._import_render_goal <= 0:
            return
        self._import_render_done += int(n_done)
        done = min(self._import_render_done, self._import_render_goal)
        total_g = self._import_render_goal
        sharing = bool(getattr(self, "_render2d_shares_ui_with_queue_job", lambda: False)())
        if getattr(self, "_render2d_batch_active", False):
            now = time.monotonic()
            last_t = float(getattr(self, "_render2d_progress_last_emit", 0.0))
            last_d = int(getattr(self, "_render2d_progress_last_done", 0))
            step = max(1, total_g // 50)
            if done <= 1 or done >= total_g or (done - last_d) >= step or (now - last_t) >= 0.12:
                self._render2d_progress_last_emit = now
                self._render2d_progress_last_done = done
                if not sharing:
                    self._on_tool_progress(TOOL_RENDER_2D, done, total_g)
        elif not sharing:
            self._on_tool_progress(TOOL_RENDER_2D, done, total_g)
        if self._import_render_done >= self._import_render_goal:
            self._import_progress_active = False
            if not sharing:
                self._clear_tool_progress()
                self.status_label.setText("Ready")
            self._flush_render2d_batch_results()
            self._restore_render2d_batch_environment()

    def on_row_ready(self, idx, props, img, success, w, h, batch_session=None):
        if not self._render2d_batch_session_accepted(batch_session):
            return

        row = self._resolve_structure_row_for_oid(int(idx))
        oid = int(idx)
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        batch = getattr(self, "_render2d_batch_active", False)
        if success and row != -1:
            if batch and self._render2d_write_png_rows([(oid, img, True, w, h)]):
                pass
            elif batch:
                self._render2d_pending[oid] = (bytes(img), True, int(w), int(h))
            else:
                pm = pixmap_from_structure_image(img, w, h)
                if pix_target:
                    if getattr(self, "_render2d_column_pixmap_mode", True):
                        self._table_model.register_pixmap_column(pix_target)
                        self._table_model.set_column_pixmap(oid, pix_target, pm)
                    else:
                        self._table_model.set_cell_pixmap(oid, pix_target, pm)
                elif not self._store_structure_scene(oid, img):
                    self._table_model.set_structure_pixmap(oid, pm)
                if self.table.rowHeight(row) != h:
                    self.table.setRowHeight(row, h)
                if pix_target:
                    self._sync_data_pixmap_column_width(pix_target, pm, w)
                else:
                    self._sync_structure_column_width_for_pixmap(pm, w)
                if props:
                    updates = {
                        name: str(props.get(name, "")) for name in self.headers[2:] if name in props
                    }
                    if updates:
                        self._table_model.set_cell_text_batch(oid, updates)
                if not pix_target and oid not in self.zoomed_ids:
                    self._sync_structure_column_width_for_zoom_state()
        else:
            if batch:
                self._render2d_pending[oid] = (b"", False, int(w), int(h))

        self._advance_render2d_batch_progress(1)

    def _resize_columns_after_render2d(self, pix_target: str | None) -> None:
        """Set structure / pixmap column width from depict size (O(1), safe for huge tables)."""
        # Session restore owns column widths, also when it revealed before the batch ended.
        if getattr(self, "_pending_session_table_layout", None) or getattr(
            self, "_render2d_keeps_session_layout", False
        ):
            return
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        hint = int(getattr(self, "_render2d_flush_max_width", 0) or 0)
        self._render2d_flush_max_width = 0
        need = max(1, max(int(structure_depict_width()), hint) + pad)
        try:
            if pix_target:
                col = self.headers.index(pix_target)
                if self.table.columnWidth(col) < need:
                    self.table.setColumnWidth(col, need)
            else:
                self._sync_structure_column_width_for_pixmap(
                    None, max(int(structure_depict_width()), hint)
                )
        except Exception:
            pass

    def _close_render2d_stream_store(self) -> None:
        """Drop a scene store that was filled during a render and never attached to the table.

        A store borrowed from the table (a resize that keeps existing scenes) is only
        detached here. Closing it would wipe the rows that were not being redrawn.
        """
        store = getattr(self, "_render2d_stream_store", None)
        owned = bool(getattr(self, "_render2d_stream_store_owned", True))
        self._render2d_stream_store = None
        self._render2d_stream_store_owned = True
        if not owned:
            return
        closer = getattr(store, "close", None)
        if callable(closer):
            closer()

    def _open_render2d_stream_store(self, n_rows: int, *, reuse: bool = False) -> None:
        """Create the structure scene store up front so results can be written as they arrive.

        *reuse* keeps writing into the store already on the table.
        """
        if reuse:
            self._render2d_stream_store = self._table_model._structure_png_store
            self._render2d_stream_store_owned = False
            return
        self._close_render2d_stream_store()
        self._render2d_stream_store_owned = True
        if int(n_rows) <= 0:
            return
        cfg = load_config()
        cap = int(cfg.structure_render_png_max_entries)
        if cap > 0:
            cap = max(cap, int(n_rows))
        self._render2d_flush_max_width = 0
        self._render2d_stream_store = StructureRenderStore(
            max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
            max_png_entries=cap,
        )

    def _render2d_write_png_rows(self, rows) -> bool:
        """Write one result batch to disk. False when the caller should keep the bytes in memory."""
        store = getattr(self, "_render2d_stream_store", None)
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        if store is None and not pix_target:
            return False
        items: list[tuple[int, bytes]] = []
        scenes: list[tuple[int, bytes]] = []
        fallbacks: list[tuple[int, bytes, int, int]] = []
        structure_store = store is not None and not pix_target
        max_w = int(getattr(self, "_render2d_flush_max_width", 0) or 0)
        for oid, img, success, w, h in rows:
            oid_i = int(oid)
            if not success or not img or self._resolve_structure_row_for_oid(oid_i) == -1:
                continue
            raw = bytes(img)
            max_w = max(max_w, int(w))
            if structure_store and is_scene_blob(raw):
                scenes.append((oid_i, raw))
            elif structure_store:
                fallbacks.append((oid_i, raw, int(w), int(h)))
            else:
                items.append((oid_i, raw))
        self._render2d_flush_max_width = max_w
        if structure_store:
            if scenes:
                store.ingest_batch(scenes)
            keep = getattr(self, "_keep_structure_fallbacks", None)
            if callable(keep):
                keep(fallbacks)
            repaint = getattr(self, "_repaint_visible_rendered_rows", None)
            model = getattr(self, "_table_model", None)
            if callable(repaint) and getattr(model, "_structure_png_store", None) is store:
                repaint({oid for oid, _raw in scenes} | {item[0] for item in fallbacks})
            return True
        if not items:
            return True
        column_mode = getattr(self, "_render2d_column_pixmap_mode", True)
        if column_mode:
            self._table_model.register_pixmap_column(pix_target)
            self._table_model.set_column_png_bytes_batch(pix_target, items, emit=False)
        else:
            for oid_i, raw in items:
                self._table_model.set_cell_png_bytes(oid_i, pix_target, raw, emit=False)
        self._render2d_streamed_column = True
        return True

    def _keep_structure_fallbacks(self, items: list[tuple[int, bytes, int, int]]) -> None:
        """Show RDKit fallback pictures without putting them in the scene store.

        A fallback is drawn for one cell size, so it lives as a pixmap. The next resize
        redraws it. Any scene previously stored for the row is removed.
        """
        if not items:
            return
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        store = model._structure_png_store
        pictures: list[tuple[int, QPixmap | None]] = []
        for oid, raw, width, height in items:
            if store is not None:
                store.remove_oid(oid)
            pictures.append((oid, pixmap_from_structure_image(raw, width, height)))
        if pictures:
            model.apply_structure_pixmaps_batch(pictures, emit=False)

    def _render2d_use_lazy_structure_flush(self, count: int, *, structure_column: bool) -> bool:
        if not structure_column:
            return False
        cfg = load_config()
        return count >= int(cfg.structure_render_lazy_min_rows)

    def _ensure_structure_lazy_scroll_hook(self) -> None:
        if getattr(self, "_structure_lazy_scroll_hooked", False):
            return
        try:
            self.table.verticalScrollBar().valueChanged.connect(self._on_structure_lazy_scroll)
            self._structure_lazy_scroll_hooked = True
        except Exception:
            pass

    def _on_structure_lazy_scroll(self, *_args) -> None:
        """Trim the decoded Structure LRU; do not emit ``dataChanged`` on every scroll tick."""
        if not self._table_model.structure_png_store_active():
            return
        self._trim_visible_structure_pixmap_cache()

    def _visible_structure_source_rows(self) -> tuple[list[int], set[int]]:
        """Viewport source rows and molecule ids that currently have Structure PNGs on screen."""
        src = self._table_model
        if src.rowCount() <= 0:
            return [], set()
        view = self.table
        proxy = view.model()
        try:
            vr0 = view.rowAt(0)
            height = view.viewport().height() if view.viewport() is not None else 0
            vr1 = view.rowAt(max(0, int(height) - 1))
        except Exception:
            vr0, vr1 = 0, src.rowCount() - 1
        if vr0 < 0:
            vr0 = 0
        if vr1 < 0:
            vr1 = max(0, (proxy.rowCount() if proxy is not None else src.rowCount()) - 1)

        source_rows: list[int] = []
        keep: set[int] = set()
        store = getattr(src, "_structure_png_store", None)
        for vr in range(vr0, vr1 + 1):
            sr = self._view_row_to_source_row(vr)
            if sr < 0:
                continue
            source_rows.append(sr)
            oid = src.row_oid(sr)
            if store is not None and store.has_png(oid):
                keep.add(int(oid))
        return source_rows, keep

    def _view_row_to_source_row(self, view_row: int) -> int:
        """Model row behind *view_row* of the table view, or -1 when it maps to none."""
        src = self._table_model
        proxy = self.table.model()
        if proxy is None or proxy is src:
            return int(view_row)
        mapper = getattr(proxy, "mapToSource", None)
        if not callable(mapper):
            return int(view_row)
        mapped = mapper(proxy.index(int(view_row), 0))
        return int(mapped.row()) if mapped.isValid() else -1

    def _repaint_visible_rendered_rows(self, oids: set[int]) -> None:
        """Repaint the Structure cells on screen when any of *oids* just got an image."""
        if not oids:
            return
        source_rows, _keep = self._visible_structure_source_rows()
        model = self._table_model
        hit = [row for row in source_rows if int(model.row_oid(row)) in oids]
        if hit:
            model.notify_structure_column_changed(min(hit), max(hit))

    def _trim_visible_structure_pixmap_cache(self) -> None:
        """Drop decoded Structure pixmaps that scrolled out of the viewport."""
        store = getattr(self._table_model, "_structure_png_store", None)
        if store is None:
            return
        _source_rows, keep = self._visible_structure_source_rows()
        store.trim_decoded_cache(keep_oids=keep)

    def _refresh_visible_structure_cells(self) -> None:
        """Repaint viewport-visible Structure cells after attaching a lazy PNG store."""
        source_rows, keep = self._visible_structure_source_rows()
        src = self._table_model
        store = getattr(src, "_structure_png_store", None)
        if store is not None:
            store.trim_decoded_cache(keep_oids=keep)
        if source_rows:
            src.notify_structure_column_changed(min(source_rows), max(source_rows))

    def _flush_render2d_batch_results(self) -> None:
        """Apply buffered PNGs in slices so the GUI thread stays responsive."""
        if not getattr(self, "_render2d_batch_active", False):
            return
        pix_target = getattr(self, "_render2d_pixmap_target", None)
        column_pixmap_mode = getattr(self, "_render2d_column_pixmap_mode", True)
        lazy_structure = bool(getattr(self, "_render2d_lazy_flush", False)) and not pix_target

        queue = getattr(self, "_render2d_eager_flush_queue", None)
        if queue is None:
            self._render2d_accept_session = None
            ordered = list(getattr(self, "_render2d_batch_oids_ordered", []) or [])
            pending = getattr(self, "_render2d_pending", None) or {}
            if pix_target and column_pixmap_mode:
                self._table_model.register_pixmap_column(pix_target)
            if lazy_structure:
                store = getattr(self, "_render2d_stream_store", None)
                self._render2d_stream_store = None
                self._render2d_stream_store_owned = True
                fallbacks: list[tuple[int, bytes, int, int]] = []
                if store is None:
                    cfg = load_config()
                    cap = int(cfg.structure_render_png_max_entries)
                    scenes: list[tuple[int, bytes]] = []
                    for oid in ordered:
                        rec = pending.get(oid)
                        if not rec:
                            continue
                        img_b, ok, rw, rh = rec
                        if not ok or not img_b:
                            continue
                        if is_scene_blob(img_b):
                            scenes.append((int(oid), bytes(img_b)))
                        else:
                            fallbacks.append((int(oid), bytes(img_b), int(rw), int(rh)))
                    if cap > 0:
                        cap = max(cap, len(scenes) + len(fallbacks))
                    store = StructureRenderStore(
                        max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                        max_png_entries=cap,
                    )
                    if scenes:
                        store.ingest_batch(scenes)
                    self._render2d_flush_max_width = max(
                        (int(rec[2]) for rec in pending.values() if rec and rec[1]),
                        default=0,
                    )
                self._table_model.set_structure_png_store(store)
                self._keep_structure_fallbacks(fallbacks)
                self._ensure_structure_lazy_scroll_hook()
                self._render2d_eager_flush_queue = []
                self._render2d_eager_flush_idx = 0
                self._render2d_eager_uniform_height = False
            elif getattr(self, "_render2d_streamed_column", False) and pix_target:
                # Bytes were written as they arrived; do not rebuild an eager pixmap queue.
                self._render2d_eager_flush_queue = []
                self._render2d_eager_flush_idx = 0
                self._render2d_eager_uniform_height = False
            else:
                # PNGs are decoded chunk by chunk below, so a large batch never decodes and
                # stores every image in one GUI-thread pass.
                cfg = load_config()
                set_uniform_height = len(ordered) >= cfg.structure_render_lazy_min_rows
                eager: list[tuple[int, tuple | None]] = []
                max_w = 0
                for oid in ordered:
                    rec = pending.get(oid)
                    if rec and rec[1]:
                        max_w = max(max_w, int(rec[2]))
                        eager.append((int(oid), rec))
                    elif not pix_target:
                        eager.append((int(oid), None))
                self._render2d_flush_max_width = max_w
                self._render2d_eager_flush_queue = eager
                self._render2d_eager_flush_idx = 0
                self._render2d_eager_uniform_height = bool(set_uniform_height and not pix_target)
                self._render2d_eager_set_row_heights = not set_uniform_height

        queue = getattr(self, "_render2d_eager_flush_queue", None) or []
        idx = int(getattr(self, "_render2d_eager_flush_idx", 0))
        if queue and idx < len(queue):
            chunk = 120
            try:
                self.table.setUpdatesEnabled(False)
            except Exception:
                pass
            try:
                slice_items = queue[idx : idx + chunk]
                decoded = self._decode_render2d_flush_slice(slice_items)
                if pix_target:
                    self._table_model.set_column_pixmaps_batch(pix_target, decoded)
                else:
                    self._table_model.apply_structure_pixmaps_batch(decoded, emit=False)
            finally:
                try:
                    self.table.setUpdatesEnabled(True)
                except Exception:
                    pass
            self._render2d_eager_flush_idx = idx + len(slice_items)
            QTimer.singleShot(0, self._flush_render2d_batch_results)
            app = QApplication.instance()
            if app is not None:
                app.processEvents(QEventLoop.ExcludeUserInputEvents)
            return

        if queue and not pix_target:
            self._table_model.notify_structure_column_changed()
        if getattr(self, "_render2d_eager_uniform_height", False):
            default_rh = structure_row_default_height()
            vh = self.table.verticalHeader()
            try:
                vh.setSectionResizeMode(vh.Fixed)
                vh.setDefaultSectionSize(default_rh)
            except Exception:
                pass
        if lazy_structure:
            self._apply_scene_zoom_overrides()
            self._refresh_visible_structure_cells()
        if getattr(self, "_render2d_streamed_column", False) and pix_target:
            self._notify_streamed_pixmap_column(pix_target)

        self._render2d_streamed_column = False
        self._render2d_pending = {}
        self._render2d_batch_oids_ordered = []
        self._render2d_snapshot = None
        self._render2d_lazy_flush = False
        self._render2d_eager_flush_queue = None
        self._render2d_eager_flush_idx = 0
        self._render2d_eager_uniform_height = False

    def _notify_streamed_pixmap_column(self, header_name: str) -> None:
        """One repaint after PNG bytes were written during the render, without decoding them."""
        model = self._table_model
        try:
            col = model._headers.index(header_name)
        except ValueError:
            return
        n = model.rowCount()
        if col < 0 or n <= 0:
            return
        model.dataChanged.emit(
            model.index(0, col),
            model.index(n - 1, col),
            [Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole],
        )

    def _decode_render2d_flush_slice(
        self, slice_items: list[tuple[int, tuple | None]]
    ) -> list[tuple[int, QPixmap | None]]:
        """Decode one flush chunk's PNGs; set per-row heights when the batch is not uniform."""
        set_heights = bool(getattr(self, "_render2d_eager_set_row_heights", False))
        decoded: list[tuple[int, QPixmap | None]] = []
        for oid, rec in slice_items:
            if rec is None:
                decoded.append((oid, None))
                continue
            img_b, _ok, rw, rh = rec
            row = self._resolve_structure_row_for_oid(oid)
            if row < 0:
                decoded.append((oid, None))
                continue
            if not getattr(self, "_render2d_pixmap_target", None) and is_scene_blob(img_b):
                store_scene = getattr(self, "_store_structure_scene", None)
                if callable(store_scene) and store_scene(oid, img_b):
                    decoded.append((oid, None))
                    continue
            decoded.append((oid, pixmap_from_structure_image(img_b, rw, rh)))
            if set_heights and self.table.rowHeight(row) != rh:
                self.table.setRowHeight(row, rh)
        return decoded

    def on_cell_double_click(self, view_row, c):
        if c != 1:
            return
        src_row = self._view_row_to_source_row(view_row)
        t0 = self._table_model.cell_text(src_row, 0)
        if not t0.isdigit():
            return
        oid = int(t0)
        mol = self._mol_for_structure_row(src_row)
        if mol is None:
            self.status_label.setText("No structure available for this row.")
            return
        if oid in self.zoomed_ids:
            self.zoomed_ids.remove(oid)
            if self._show_scene_zoom(oid, False):
                return
            if self._try_restore_structure_zoom_out(oid, view_row):
                return
            w, h = structure_depict_width(), structure_depict_height()
        else:
            self.zoomed_ids.add(oid)
            if self._show_scene_zoom(oid, True):
                return
            w, h = structure_depict_width() * 2, structure_depict_height() * 2
        self.start_render_worker(oid, mol, w, h)
