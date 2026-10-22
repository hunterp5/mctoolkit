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

"""Structure / pixmap storage helpers — file-split of ``CompoundTableModel``, not a reusable mixin."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPixmap

from ..storage.extra_pixmap_store import pixmap_to_png_bytes
from ..storage.structure_render_store import StructureRenderStore


class CompoundTableStructureMixin:
    def structure_png_store_active(self) -> bool:
        store = self._structure_png_store
        return store is not None and len(store) > 0

    def set_structure_png_store(self, store: StructureRenderStore | None) -> None:
        old = self._structure_png_store
        if old is not None and old is not store:
            closer = getattr(old, "close", None)
            if callable(closer):
                closer()
        self._structure_png_store = store

    def clear_structure_png_store(self) -> None:
        self.set_structure_png_store(None)

    def set_structure_text_source(self, source) -> None:
        """Set ``source(oid) -> str``, the row's structure text from the molecule store."""
        self._structure_text_source = source

    def structure_text_for_oid(self, oid: int) -> str:
        """The row's structure text (SMILES, InChI, or a mol block), or ``""``."""
        source = self._structure_text_source
        if source is None:
            return ""
        try:
            return (source(int(oid)) or "").strip()
        except Exception:  # noqa: BLE001 — a failed lookup must not break painting the cell
            return ""

    def structure_pixmap_for_oid(self, oid: int) -> QPixmap | None:
        pix = self._pixmaps.get(int(oid))
        if pix is not None and not pix.isNull():
            return pix
        store = self._structure_png_store
        if store is not None and store.has_png(oid):
            return store.pixmap(oid)
        return None

    def notify_structure_column_changed(self, row_lo: int = 0, row_hi: int | None = None) -> None:
        if not self._rows:
            return
        hi = (
            len(self._rows) - 1 if row_hi is None else max(0, min(int(row_hi), len(self._rows) - 1))
        )
        lo = max(0, min(int(row_lo), hi))
        roles = list(self.STRUCTURE_PAINT_ROLES)
        self.dataChanged.emit(
            self.index(lo, self.STRUCTURE_COL), self.index(hi, self.STRUCTURE_COL), roles
        )

    def clear_structure_pixmaps_for_oids(self, oids: list[int], *, emit: bool = True) -> None:
        for oid in oids:
            self._pixmaps.pop(int(oid), None)
            store = self._structure_png_store
            if store is not None:
                store.remove_oid(oid)
        if emit and oids and self._rows:
            self.notify_structure_column_changed()

    def apply_structure_pixmaps_batch(
        self,
        items: list[tuple[int, QPixmap | None]],
        *,
        emit: bool = True,
    ) -> None:
        rows: list[int] = []
        for oid, pixmap in items:
            oid_i = int(oid)
            if pixmap is not None and not pixmap.isNull():
                self._pixmaps[oid_i] = pixmap
            else:
                self._pixmaps.pop(oid_i, None)
            r = self.logical_row_for_oid(oid_i)
            if r >= 0:
                rows.append(r)
        if emit and rows and self._rows:
            lo, hi = min(rows), max(rows)
            self.notify_structure_column_changed(lo, hi)

    def set_structure_pixmap(self, oid: int, pixmap: QPixmap | None) -> None:
        if pixmap is not None:
            self._pixmaps[oid] = pixmap
        else:
            self._pixmaps.pop(oid, None)
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        idx = self.index(r, self.STRUCTURE_COL)
        self.dataChanged.emit(idx, idx, list(self.STRUCTURE_PAINT_ROLES))

    def register_pixmap_column(self, header_name: str) -> None:
        """Mark a data column as image-only (2D pixmap via ``set_column_pixmap``)."""
        if header_name in self._headers:
            self._pixmap_columns.add(header_name)

    def pixmap_data_column_headers(self) -> list[str]:
        """Data-column headers currently displayed as 2D images rather than text."""
        return [h for h in self._headers[2:] if h in self._pixmap_columns]

    def column_accepts_text_edit(self, logical_col: int) -> bool:
        """Plain string cells: not id, not structure, not pixmap-only columns."""
        if logical_col < 2 or logical_col >= len(self._headers):
            return False
        return self._headers[logical_col] not in self._pixmap_columns

    def set_column_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        """Set pixmap for one row in a pixmap-only column (see ``register_pixmap_column``)."""
        if header_name not in self._pixmap_columns:
            return
        self._set_extra_pixmap(oid, header_name, pixmap)

    def set_cell_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        """Set an optional 2D image for one cell; other rows in the column keep their text."""
        if header_name in self._pixmap_columns:
            self.set_column_pixmap(oid, header_name, pixmap)
            return
        self._set_extra_pixmap(oid, header_name, pixmap)

    def set_column_pixmaps_batch(
        self, header_name: str, items: list[tuple[int, QPixmap | None]], *, emit: bool = True
    ) -> None:
        """Set extra-column images for many rows in one store write; batched ``dataChanged``."""
        if not items or header_name not in self._headers:
            return
        if header_name in ("ID_HIDDEN", "Structure"):
            return
        self._extra_pixmaps.set_pixmaps_batch(header_name, items)
        if not emit:
            return
        rows_changed = [r for r in (self.logical_row_for_oid(int(o)) for o, _p in items) if r >= 0]
        c = self._headers.index(header_name)
        self._emit_data_changed_row_spans(
            rows_changed,
            c,
            c,
            roles=[Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole],
        )

    def clear_column_pixmaps_for_oids(
        self, header_name: str, oids: list[int], *, emit: bool = True
    ) -> None:
        """Drop extra-column images for many rows; ``dataChanged`` only for the changed row runs."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        keys = [
            (int(oid), header_name)
            for oid in oids
            if (int(oid), header_name) in self._extra_pixmaps
        ]
        self._extra_pixmaps.remove_keys(keys)
        rows_changed = [r for r in (self.logical_row_for_oid(oid) for oid, _h in keys) if r >= 0]
        if emit and rows_changed:
            c = self._headers.index(header_name)
            self._emit_data_changed_row_spans(
                rows_changed,
                c,
                c,
                roles=[Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole],
            )

    def _set_extra_pixmap(self, oid: int, header_name: str, pixmap: QPixmap | None) -> None:
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        self._extra_pixmaps.set_pixmap(oid, header_name, pixmap)
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        try:
            c = self._headers.index(header_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(
            idx, idx, [Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole]
        )

    def cell_pixmap_copy(self, oid: int, header_name: str) -> QPixmap | None:
        return self.column_pixmap_copy(oid, header_name)

    def snapshot_structure_pngs(self, oids: list[int]) -> dict[int, bytes | None]:
        """PNG bytes for undo/cancel. Does not decode the lazy store into ``QPixmap``s."""
        out: dict[int, bytes | None] = {}
        store = self._structure_png_store
        for oid in oids:
            oid_i = int(oid)
            raw = store.png_bytes(oid_i) if store is not None else None
            if not raw:
                pix = self._pixmaps.get(oid_i)
                raw = pixmap_to_png_bytes(pix) if pix is not None and not pix.isNull() else None
            out[oid_i] = raw
        return out

    def snapshot_column_pngs(self, header_name: str, oids: list[int]) -> dict[int, bytes | None]:
        """PNG bytes for one image column. Does not decode every row."""
        out: dict[int, bytes | None] = {}
        if header_name not in self._headers:
            return out
        for oid in oids:
            out[int(oid)] = self._extra_pixmaps.png_bytes(int(oid), header_name)
        return out

    def column_png_bytes_by_oid(self, header_name: str) -> dict[int, bytes]:
        """Every stored PNG in *header_name*, for an undo snapshot."""
        return self._extra_pixmaps.png_bytes_for_header(str(header_name))

    def set_column_png_bytes_batch(
        self,
        header_name: str,
        items: list[tuple[int, bytes | None]],
        *,
        emit: bool = True,
    ) -> None:
        """Restore or replace image-column PNGs without decoding them first."""
        if not items or header_name not in self._headers:
            return
        if header_name in ("ID_HIDDEN", "Structure"):
            return
        self._extra_pixmaps.set_png_bytes_batch(header_name, items)
        if not emit:
            return
        rows_changed = [
            r for r in (self.logical_row_for_oid(int(o)) for o, _raw in items) if r >= 0
        ]
        if not rows_changed:
            return
        c = self._headers.index(header_name)
        self._emit_data_changed_row_spans(
            rows_changed,
            c,
            c,
            roles=[Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole],
        )

    def set_cell_png_bytes(
        self, oid: int, header_name: str, raw: bytes | None, *, emit: bool = True
    ) -> None:
        """Store one extra-column PNG. *emit* is false while a batch render is still running."""
        if header_name not in self._headers or header_name in ("ID_HIDDEN", "Structure"):
            return
        self._extra_pixmaps.set_png_bytes(int(oid), header_name, raw)
        if not emit:
            return
        r = self.logical_row_for_oid(int(oid))
        if r < 0:
            return
        try:
            c = self._headers.index(header_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(
            idx, idx, [Qt.DecorationRole, Qt.SizeHintRole, Qt.DisplayRole, Qt.ToolTipRole]
        )

    def restore_structure_pngs(self, items: list[tuple[int, bytes | None]]) -> None:
        """Put structure PNGs back after a cancelled render. Missing bytes clear that row."""
        pngs = [(int(oid), bytes(raw)) for oid, raw in items if raw]
        if pngs:
            store = self._structure_png_store
            if store is None:
                from ..platform_support.config import load_config

                cfg = load_config()
                store = StructureRenderStore(
                    max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                    max_png_entries=cfg.structure_render_png_max_entries,
                )
                self._structure_png_store = store
            store.expand_png_capacity(len(pngs))
            store.ingest_batch(pngs)
        for oid, raw in items:
            if raw:
                continue
            self._pixmaps.pop(int(oid), None)
            if self._structure_png_store is not None:
                self._structure_png_store.remove_oid(int(oid))
        if self._rows:
            self.notify_structure_column_changed()

    def snapshot_structure_pixmaps(self, oids: list[int]) -> dict[int, QPixmap | None]:
        """Shallow copies of structure pixmaps for undo/cancel (caller owns QPixmap copies)."""
        out: dict[int, QPixmap | None] = {}
        for oid in oids:
            p = self._pixmaps.get(oid)
            if p is not None and not p.isNull():
                out[oid] = QPixmap(p)
            else:
                out[oid] = None
        return out

    def snapshot_column_pixmaps(
        self, header_name: str, oids: list[int]
    ) -> dict[int, QPixmap | None]:
        """Shallow copies of pixmap-column images for a header (e.g. Render 2D target column)."""
        out: dict[int, QPixmap | None] = {}
        if header_name not in self._headers:
            return out
        for oid in oids:
            key = (oid, header_name)
            p = self._extra_pixmaps.get(key)
            if p is not None and not p.isNull():
                out[oid] = QPixmap(p)
            else:
                out[oid] = None
        return out

    def structure_pixmap_copy(self, oid: int) -> QPixmap | None:
        """Detached copy of the main structure pixmap for this molecule id, if any."""
        pm = self._pixmaps.get(oid)
        if pm is not None and not pm.isNull():
            return QPixmap(pm)
        return None

    def structure_png_bytes(self, oid: int) -> bytes | None:
        """Raw structure PNG bytes from the lazy store, if present."""
        store = self._structure_png_store
        if store is None:
            return None
        return store.png_bytes(oid)

    def set_structure_png_bytes(self, oid: int, png: bytes | None) -> None:
        """Restore structure PNG into the lazy store (decoded on demand)."""
        store = self._structure_png_store
        if png:
            if store is None:
                from ..platform_support.config import load_config
                from ..storage.structure_render_store import StructureRenderStore

                cfg = load_config()
                store = StructureRenderStore(
                    max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                    max_png_entries=cfg.structure_render_png_max_entries,
                )
                self._structure_png_store = store
            store.ingest_png(int(oid), png)
        elif store is not None:
            store.remove_oid(int(oid))
        r = self.logical_row_for_oid(int(oid))
        if r < 0:
            return
        idx = self.index(r, self.STRUCTURE_COL)
        self.dataChanged.emit(idx, idx, list(self.STRUCTURE_PAINT_ROLES))

    def extra_column_pixmaps_copy(self, oid: int) -> dict[str, QPixmap]:
        """Detached copies of extra pixmap-column images for this oid."""
        return self._extra_pixmaps.pixmaps_for_oid(int(oid))

    def is_pixmap_data_column(self, header_name: str) -> bool:
        return header_name in self._pixmap_columns

    def column_pixmap_copy(self, oid: int, header_name: str) -> QPixmap | None:
        pm = self._extra_pixmaps.get((oid, header_name))
        if pm is not None and not pm.isNull():
            return QPixmap(pm)
        return None

    def column_pixmaps_by_oid(self, header_name: str) -> dict[int, QPixmap]:
        """Snapshot pixmap-column cells for undo (only rows that have an image)."""
        return self._extra_pixmaps.pixmaps_for_header(str(header_name))
