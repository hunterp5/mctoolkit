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

"""Structure column width, depict size, and zoom layout."""

from __future__ import annotations

from PyQt5.QtGui import QPixmap

from ...chem.depiction_scene import is_scene_blob
from ...table.structure_image import pixmap_from_structure_image
from ..compound_table_model import CompoundTableModel
from ...table.structure_depiction_layout import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)


class StructureLayoutMixin:
    def _view_row_to_source_row(self, view_row: int) -> int:
        """Map a table view row index to the source ``CompoundTableModel`` row."""
        proxy = getattr(self, "_filter_proxy_model", None)
        if proxy is not None:
            src = proxy.mapToSource(proxy.index(int(view_row), 0))
            if src.isValid():
                return int(src.row())
        return int(view_row)

    def apply_structure_table_layout(self) -> None:
        """Sync Structure column row/column chrome to the current depiction size."""
        if not hasattr(self, "table") or self.table is None:
            return
        row_h = structure_row_default_height()
        col = CompoundTableModel.STRUCTURE_COL
        vh = self.table.verticalHeader()
        if vh is not None:
            vh.setDefaultSectionSize(row_h)
        zoomed = bool(getattr(self, "zoomed_ids", None))
        min_col = structure_column_minimum_width(zoomed=zoomed)
        self.table.set_structure_column_minimum_width(min_col)
        if int(self.table.columnWidth(col)) < min_col:
            self.table.setColumnWidth(col, min_col)
        if hasattr(self, "_table_model") and self._table_model is not None:
            self._table_model.notify_structure_column_changed()
        self.table.viewport().update()

    def apply_structure_depict_size(self, width: int, height: int, *, persist: bool = True) -> None:
        """Apply depiction size from Settings and optionally re-render the Structure column."""
        from ...table.structure_depiction_layout import set_structure_depict_size

        set_structure_depict_size(width, height, persist=persist)
        self.apply_structure_table_layout()
        if persist:
            self.rerender_structure_column_for_new_size()

    def commit_structure_depict_resize(self, width: int, height: int) -> None:
        """Save a depiction size chosen by dragging a column or row border, and redraw."""
        self.apply_structure_depict_size(int(width), int(height), persist=True)

    def rerender_structure_column_for_new_size(self) -> None:
        """Re-draw structure pictures after the depiction size changes.

        The Structure column paints its stored scenes at the new size. Other depiction
        columns do the same when they hold scenes. A column that only has a fixed-size
        picture is drawn again so the resize does not leave a scaled bitmap.
        """
        if not hasattr(self, "_table_model") or self._table_model.rowCount() <= 0:
            if hasattr(self, "_table_model") and self._table_model is not None:
                self._table_model.notify_structure_column_changed()
            return
        self._rerender_structure_scenes_for_new_size()
        self._redraw_pixmap_depiction_columns()

    def _rerender_structure_scenes_for_new_size(self) -> None:
        """Paint stored Structure scenes, and render rows that have no scene."""
        missing = self._structure_oids_without_scene()
        if not missing:
            self._repaint_stored_scenes()
            return
        self._repaint_stored_scenes()
        if getattr(self, "_render2d_batch_active", False) or self.process_queue.has_running_job():
            if hasattr(self, "status_label"):
                self.status_label.setText(
                    "2D render size saved. Re-draw structures when the current job finishes."
                )
            return
        merge = len(missing) < self._table_model.rowCount()
        if not merge:
            self.zoomed_ids.clear()
            self._table_model.clear_structure_png_store()
        w, h = structure_depict_width(), structure_depict_height()
        renders, row_by_oid = self._build_render2d_tasks_in_table_order(
            "Structure", w, h, set(missing)
        )
        if not renders:
            self._table_model.notify_structure_column_changed()
            return
        self._start_render_2d_batch(
            renders,
            row_by_oid,
            "Structure",
            column_pixmap_mode=False,
            queue_title_prefix="structure resize ",
            merge_structure_store=merge,
        )

    def _redraw_pixmap_depiction_columns(self) -> None:
        """Paint depiction-column scenes at the new size and redraw fixed bitmaps.

        Scenes are resolution-independent, so dropping the decoded cache is enough.
        A PNG was drawn for one cell size; scaling it is what makes the column blurry,
        so those columns are rendered again at the current size.
        """
        model = self._table_model
        headers_fn = getattr(model, "pixmap_data_column_headers", None)
        if not callable(headers_fn):
            return
        headers = [str(header) for header in headers_fn()]
        if not headers:
            return
        width, height = structure_depict_width(), structure_depict_height()
        for header in headers:
            note = getattr(self, "_note_pixmap_render_source_size", None)
            if callable(note):
                note(header, width, height)
            else:
                model.note_pixmap_column_source_size(header, width, height)
        store = getattr(model, "_extra_pixmaps", None)
        if store is not None and hasattr(store, "clear_decoded"):
            store.clear_decoded()
        notify = getattr(model, "notify_pixmap_columns_changed", None)
        if callable(notify):
            notify(headers)
        if store is None or not hasattr(store, "headers_with_rasters"):
            return
        rasters = list(store.headers_with_rasters(headers))
        if not rasters:
            return
        queue = getattr(self, "_queue_generated_structure_renders", None)
        if callable(queue):
            queue(rasters, None, written_rows=None, force=True)

    def _repaint_stored_scenes(self) -> None:
        """Drop decoded pixmaps so stored scenes paint at the current cell size."""
        model = self._table_model
        if not self._stored_structure_scene_oids():
            return
        store = model._structure_png_store
        store.trim_decoded_cache()
        model.apply_structure_pixmaps_batch(
            [(oid, None) for oid in list(model._pixmaps)], emit=False
        )
        self._apply_scene_zoom_overrides()
        model.notify_structure_column_changed()

    def _stored_structure_scene_oids(self) -> set[int]:
        """Row ids that have a depiction scene in the Structure store."""
        store = getattr(self._table_model, "_structure_png_store", None)
        if store is None:
            return set()
        return store.scene_oids()

    def _structure_oids_without_scene(self) -> list[int]:
        """Table row ids with no stored depiction scene, in table order."""
        model = self._table_model
        have = self._stored_structure_scene_oids()
        missing: list[int] = []
        for row in range(model.rowCount()):
            try:
                oid = int(model.row_oid(row))
            except (TypeError, ValueError):
                continue
            if oid not in have:
                missing.append(oid)
        return missing

    def _stored_scene(self, oid: int) -> bytes | None:
        """The row's stored depiction scene, or ``None`` when it has a PNG or nothing."""
        store = self._table_model._structure_png_store
        raw = store.png_bytes(int(oid)) if store is not None else None
        return raw if is_scene_blob(raw) else None

    def _show_scene_zoom(self, oid: int, zoomed: bool) -> bool:
        """Paint a row's stored scene at 2x, or back at 1x, without a worker.

        False when the row has no stored scene, so the caller re-renders instead.
        """
        blob = self._stored_scene(oid)
        if blob is None:
            return False
        w, h = structure_depict_width(), structure_depict_height()
        if zoomed:
            w, h = w * 2, h * 2
            self._table_model.set_structure_pixmap(oid, pixmap_from_structure_image(blob, w, h))
        else:
            self._table_model.set_structure_pixmap(oid, None)
        view_row = self._resolve_structure_row_for_oid(int(oid))
        if view_row != -1:
            self.table.setRowHeight(int(view_row), h)
        self._sync_structure_column_width_for_zoom_state()
        return True

    def _store_structure_scene(self, oid: int, image: bytes) -> bool:
        """Keep a scene drawn for one row (after an edit) in the Structure store.

        Batch rows already live there; without this an edited row would only exist as a
        pixmap, so it would miss resizes and the session cache. False when *image* is
        not a scene or no store is attached, so the caller keeps the pixmap instead.
        """
        store = self._table_model._structure_png_store
        if store is None or not is_scene_blob(image):
            return False
        store.ingest_png(int(oid), bytes(image))
        self._table_model.set_structure_pixmap(int(oid), None)
        if int(oid) in (getattr(self, "zoomed_ids", None) or ()):
            self._show_scene_zoom(int(oid), True)
        return True

    def _apply_scene_zoom_overrides(self) -> None:
        """Draw every zoomed row that has a stored scene at 2x (after a store is attached)."""
        for oid in list(getattr(self, "zoomed_ids", None) or ()):
            self._show_scene_zoom(int(oid), True)

    def _sync_structure_column_width_for_zoom_state(self) -> None:
        """Set Structure column width from zoom state (O(1), no full-table scan)."""
        zoomed = bool(getattr(self, "zoomed_ids", None))
        need = structure_column_minimum_width(zoomed=zoomed)
        self.table.set_structure_column_minimum_width(need)
        col = CompoundTableModel.STRUCTURE_COL
        if int(self.table.columnWidth(col)) != need:
            self.table.setColumnWidth(col, need)

    def _sync_structure_column_width_for_pixmap(self, pm: QPixmap | None, fallback_w: int) -> None:
        """Grow the Structure column to fit the pixmap + padding (never shrink — avoids fighting user resizes)."""
        col = CompoundTableModel.STRUCTURE_COL
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self.table.columnWidth(col))
        if need > cur:
            self.table.setColumnWidth(col, need)
        if need > self.table.structure_column_minimum_width():
            self.table.set_structure_column_minimum_width(need)

    def _sync_data_pixmap_column_width(
        self, header_name: str, pm: QPixmap | None, fallback_w: int
    ) -> None:
        try:
            col = self.headers.index(header_name)
        except ValueError:
            return
        pad = STRUCTURE_COLUMN_HORIZONTAL_PADDING
        pix_w = int(pm.width()) if pm is not None and not pm.isNull() else int(fallback_w)
        need = max(1, pix_w + pad)
        cur = int(self.table.columnWidth(col))
        if need > cur:
            self.table.setColumnWidth(col, need)
