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

"""
QAbstractTableModel for compound tables (row text, OIDs, structure pixmaps).

View/delegate live in ``compound_table_view``; domain helpers in services /
``column_color_compute``. Public re-exports keep historical import paths stable.

Run the standalone demo::

    python -m molmanager.table_model_demo
    python -m molmanager.ui.compound_table_model
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from PyQt5.QtCore import QAbstractItemModel, QAbstractTableModel, QModelIndex, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPixmap

from ..table.column_color_compute import ColumnColorRule
from ..storage.extra_pixmap_store import ExtraPixmapStore
from ..table.structure_depiction_layout import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    STRUCTURE_DEPICT_HEIGHT,
    STRUCTURE_DEPICT_WIDTH,
    STRUCTURE_ROW_DEFAULT_HEIGHT,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)
from ..storage.structure_render_store import StructureRenderStore
from ..chem.molecule_conversion import safe_float
from .column_store import ColumnStore
from .compound_table_bounds_mixin import CompoundTableBoundsMixin
from .compound_table_bulk_mixin import CompoundTableBulkMixin
from .compound_table_color_mixin import CompoundTableColorMixin
from .compound_table_structure_mixin import CompoundTableStructureMixin
from .compound_table_view import (
    CompoundTableHeaderView,
    CompoundTableView,
    StructureDelegate,
)
from .strings import STRUCTURE_PENDING_HINT
from .theme import table_text_alignment_flags

# Backward-compatible names (also re-export layout constants for ``from .compound_table_model import …``).
STRUCTURE_COLUMN_PENDING_HINT = STRUCTURE_PENDING_HINT

__all__ = [
    "CompoundTableHeaderView",
    "CompoundTableModel",
    "CompoundTableView",
    "StructureDelegate",
    "STRUCTURE_COLUMN_HORIZONTAL_PADDING",
    "STRUCTURE_COLUMN_PENDING_HINT",
    "STRUCTURE_DEPICT_HEIGHT",
    "STRUCTURE_DEPICT_WIDTH",
    "STRUCTURE_ROW_DEFAULT_HEIGHT",
    "structure_column_minimum_width",
    "structure_depict_height",
    "structure_depict_width",
    "structure_row_default_height",
]


def structure_cell_display_text(text: str) -> str:
    """What an undrawn Structure cell shows for its structure text.

    One-line text (SMILES, InChI) is shown as is. A mol block or an empty row shows the
    Render 2D hint instead, since a multi-line connection table is not readable in a cell.
    """
    text = (text or "").strip()
    if not text or "\n" in text:
        return STRUCTURE_COLUMN_PENDING_HINT
    return text


def structure_cell_edit_text(text: str) -> str:
    """Text placed in the Structure cell editor: one-line SMILES or InChI, else blank."""
    text = (text or "").strip()
    if not text or "\n" in text:
        return ""
    return text


@dataclass
class _Row:
    oid: int
    values: dict[str, str] = field(default_factory=dict)


class CompoundTableModel(
    CompoundTableStructureMixin,
    CompoundTableBoundsMixin,
    CompoundTableBulkMixin,
    CompoundTableColorMixin,
    QAbstractTableModel,
):
    """
    File-split of one table model (structure / bounds / bulk / color modules), not reusable mixins.

    Column 0: hidden id (string of oid).
    Column 1: Structure. The rendered pixmap, else the row's structure text, else a hint.
    Column 2..n: text from ``values`` keyed by header name.

    The Structure cell accepts typed SMILES or InChI. Committing the editor emits
    ``structureTextEdited``; the window parses that text and replaces the row's molecule.
    """

    structureTextEdited = pyqtSignal(int, str)

    STRUCTURE_COL = 1
    STRUCTURE_PAINT_ROLES = frozenset(
        {
            Qt.DecorationRole,
            Qt.SizeHintRole,
            Qt.DisplayRole,
            Qt.ToolTipRole,
        }
    )

    @classmethod
    def is_structure_paint_data_change(cls, top_left, bottom_right, roles=()) -> bool:
        """True when ``dataChanged`` is a Structure pixmap paint (lazy-scroll flush)."""
        if top_left is None or bottom_right is None:
            return False
        try:
            if not top_left.isValid() or not bottom_right.isValid():
                return False
            if top_left.column() != cls.STRUCTURE_COL or bottom_right.column() != cls.STRUCTURE_COL:
                return False
        except Exception:
            return False
        if not roles:
            return True
        try:
            return set(roles) <= cls.STRUCTURE_PAINT_ROLES
        except TypeError:
            return True

    def __init__(self, headers: list[str], parent=None):
        super().__init__(parent)
        self._headers = list(headers)
        self._rows = ColumnStore()
        self._pixmaps: dict[int, QPixmap] = {}
        self._structure_png_store: StructureRenderStore | None = None
        self._structure_text_source: Callable[[int], str] | None = None
        self._oid_to_row: dict[int, int] = {}
        # Optional extra columns that show a 2D pixmap (e.g. disconnected fragment) keyed by (oid, header).
        self._pixmap_columns: set[str] = set()
        from ..platform_support.config import load_config

        self._extra_pixmaps = ExtraPixmapStore(
            max_decoded_pixmaps=load_config().structure_render_pixmap_lru
        )
        # Incremental numeric min/max cache for filter sliders (see numeric_bounds_by_column).
        self._numeric_bounds_cache: dict[str, dict] | None = None
        self._numeric_bounds_key: tuple[str, ...] | None = (
            None  # sorted data header names used for last full build
        )
        self._numeric_bounds_dirty_cols: set[str] | None = None  # None = need full rebuild
        # Optional per-column background coloring with O(1) lookups in data().
        self._column_color_rules: dict[str, ColumnColorRule] = {}
        self._column_color_cache: dict[str, dict[int, int]] = {}
        self._rgb_qcolor_cache: dict[int, QColor] = {}
        # Logical row selection (OID set) for large selections — painted by delegates, not QItemSelection.
        self._highlighted_oids: frozenset[int] | None = None
        self._silent_append_depth = 0
        self._silent_append_start_row = 0

    def begin_silent_appends(self) -> None:
        """Defer ``beginInsertRows`` until :meth:`end_silent_appends` (bulk file ingest)."""
        if self._silent_append_depth == 0:
            self._silent_append_start_row = len(self._rows)
        self._silent_append_depth += 1

    def end_silent_appends(self) -> None:
        """Emit one insert notification for rows appended since :meth:`begin_silent_appends`."""
        if self._silent_append_depth <= 0:
            return
        self._silent_append_depth -= 1
        if self._silent_append_depth != 0:
            return
        start = int(self._silent_append_start_row)
        end = len(self._rows) - 1
        if end >= start:
            self.beginInsertRows(QModelIndex(), start, end)
            self.endInsertRows()

    @property
    def silent_appending(self) -> bool:
        return self._silent_append_depth > 0

    def set_headers(self, headers: list[str]) -> None:
        self.beginResetModel()
        self._headers = list(headers)
        self._pixmap_columns &= set(self._headers)
        self._extra_pixmaps.keep_headers(set(self._headers))
        keep = set(self._headers)
        self._column_color_rules = {h: r for h, r in self._column_color_rules.items() if h in keep}
        self._column_color_cache = {h: c for h, c in self._column_color_cache.items() if h in keep}
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def clear_rows(self) -> None:
        """Drop all rows and cached structure pixmaps; keep column headers."""
        self._silent_append_depth = 0
        self._silent_append_start_row = 0
        self.beginResetModel()
        self._rows.clear()
        self._pixmaps.clear()
        self.clear_structure_png_store()
        self._oid_to_row.clear()
        self._extra_pixmaps.clear()
        self._highlighted_oids = None
        for cache in self._column_color_cache.values():
            cache.clear()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def install_rows(self, rows: ColumnStore) -> None:
        """Replace every row with *rows* in one model reset; keeps headers and image stores."""
        self._silent_append_depth = 0
        self._silent_append_start_row = 0
        self.beginResetModel()
        self._rows = rows
        self._pixmaps.clear()
        self._extra_pixmaps.clear()
        self._highlighted_oids = None
        self._rebuild_oid_index()
        for cache in self._column_color_cache.values():
            cache.clear()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def append_columns_batch(self, oids: list[int], columns: dict[str, list[str]]) -> None:
        """Append rows given as one text list per column (bulk ingest).

        Color caches are left for :meth:`rebuild_column_color_caches_after_bulk_load`, the
        same as ``append_rows_batch(..., defer_color_cache=True)``.
        """
        if not oids:
            return
        start = len(self._rows)
        self._rows.append_columns(oids, columns)
        for offset, oid in enumerate(oids):
            self._oid_to_row[int(oid)] = start + offset
        bh = self._bounds_data_headers()
        dirty = {name for name in columns if name in bh}
        if dirty:
            self._mark_numeric_bounds_dirty(dirty)
        if self.silent_appending:
            return
        self.beginInsertRows(QModelIndex(), start, start + len(oids) - 1)
        self.endInsertRows()

    def rows_store(self) -> ColumnStore:
        """The live columnar row store (session save serializes it directly)."""
        return self._rows

    def set_highlighted_oids(self, oids: frozenset[int] | set[int] | None) -> None:
        """Rows whose OID is in *oids* are painted as selected (for large logical selections)."""
        new = None if oids is None else frozenset(int(x) for x in oids)
        if new == self._highlighted_oids:
            return
        self._highlighted_oids = new

    def highlighted_oids(self) -> frozenset[int] | None:
        return self._highlighted_oids

    def is_row_highlighted(self, row: int) -> bool:
        if self._highlighted_oids is None:
            return False
        if row < 0 or row >= len(self._rows):
            return False
        return int(self._rows[row].oid) in self._highlighted_oids

    def clear(self) -> None:
        """Remove rows and clear the header list (empty table)."""
        self._silent_append_depth = 0
        self._silent_append_start_row = 0
        self.beginResetModel()
        self._rows.clear()
        self._pixmaps.clear()
        self.clear_structure_png_store()
        self._headers.clear()
        self._oid_to_row.clear()
        self._pixmap_columns.clear()
        self._extra_pixmaps.clear()
        self._column_color_rules.clear()
        self._column_color_cache.clear()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def append_row(self, oid: int, cells: dict[str, str]) -> None:
        r = len(self._rows)
        self.beginInsertRows(QModelIndex(), r, r)
        row_obj = _Row(oid=oid, values=dict(cells))
        self._rows.append(row_obj)
        self.endInsertRows()
        self._oid_to_row[oid] = len(self._rows) - 1
        if self._column_color_rules:
            self._refresh_color_cache_for_row(row_obj, cells)
        bh = self._bounds_data_headers()
        for k in cells:
            if k in bh:
                self._mark_numeric_bounds_dirty({k})

    def append_rows_batch(
        self,
        entries: list[tuple[int, dict[str, str]]],
        *,
        defer_color_cache: bool = False,
        silent: bool | None = None,
    ) -> None:
        """Append many rows with a single insert-range notification."""
        if not entries:
            return
        use_silent = bool(silent) if silent is not None else self.silent_appending
        bh = self._bounds_data_headers()
        dirty_cols: set[str] = set()
        refresh_color = bool(self._column_color_rules) and not defer_color_cache
        start = len(self._rows)
        row_idx = start
        for oid, cells in entries:
            row_cells = dict(cells)
            row_obj = _Row(oid=int(oid), values=row_cells)
            self._rows.append(row_obj)
            self._oid_to_row[int(oid)] = row_idx
            row_idx += 1
            if refresh_color:
                self._refresh_color_cache_for_row(row_obj, row_cells)
            if bh:
                dirty_cols |= {k for k in row_cells if k in bh}
        if dirty_cols:
            self._mark_numeric_bounds_dirty(dirty_cols)
        if use_silent:
            return
        end = start + len(entries) - 1
        self.beginInsertRows(QModelIndex(), start, end)
        self.endInsertRows()

    def rebuild_column_color_caches_after_bulk_load(self) -> None:
        """Refresh conditional-format caches after a large append (skipped per row during ingest)."""
        if not self._column_color_rules:
            return
        for header_name in list(self._column_color_rules.keys()):
            self._rebuild_column_color_cache(header_name)

    def insert_row_at(self, logical_index: int, oid: int, cells: dict[str, str]) -> None:
        n = len(self._rows)
        logical_index = max(0, min(logical_index, n))
        self.beginInsertRows(QModelIndex(), logical_index, logical_index)
        self._rows.insert(logical_index, _Row(oid=oid, values=dict(cells)))
        self.endInsertRows()
        self._rebuild_oid_index()
        if self._column_color_rules:
            self._refresh_color_cache_for_row(self._rows[logical_index], cells)
        self._invalidate_numeric_bounds_all()

    def remove_row_at(self, logical_row: int) -> None:
        if logical_row < 0 or logical_row >= len(self._rows):
            return
        self.beginRemoveRows(QModelIndex(), logical_row, logical_row)
        oid = self._rows[logical_row].oid
        self._rows.pop(logical_row)
        self._drop_row_assets(oid)
        self.endRemoveRows()
        self._rebuild_oid_index()
        self._invalidate_numeric_bounds_all()

    def _drop_row_assets(self, oid: int) -> None:
        oid_i = int(oid)
        self._pixmaps.pop(oid_i, None)
        self._extra_pixmaps.remove_oid(oid_i)
        for cache in self._column_color_cache.values():
            cache.pop(oid_i, None)
        store = self._structure_png_store
        if store is not None:
            store.remove_oid(oid_i)

    def remove_rows_by_oids(self, oids: frozenset[int] | set[int]) -> int:
        """Remove every row whose OID is in *oids* with a single model reset (fast bulk delete)."""
        kill = {int(x) for x in oids}
        if not kill:
            return 0
        n_before = len(self._rows)
        self.beginResetModel()
        self._rows.delete_oids(kill)
        for oid in kill:
            self._drop_row_assets(oid)
        if self._highlighted_oids is not None:
            remaining = frozenset(x for x in self._highlighted_oids if int(x) not in kill)
            self._highlighted_oids = remaining if remaining else None
        self._rebuild_oid_index()
        self._invalidate_numeric_bounds_all()
        self.endResetModel()
        return n_before - len(self._rows)

    def insert_rows_batch(self, rows: list[tuple[int, int, dict[str, str]]]) -> None:
        """Restore rows deleted in bulk (undo). Each item is ``(orig_logical_index, oid, cells)``."""
        if not rows:
            return
        ordered = sorted(rows, key=lambda item: item[0])
        self.beginResetModel()
        for k, (orig_row, oid, cells) in enumerate(ordered):
            insert_at = max(0, min(int(orig_row) + k, len(self._rows)))
            self._rows.insert(insert_at, _Row(oid=int(oid), values=dict(cells)))
        self._rebuild_oid_index()
        if self._column_color_rules:
            for _orig_row, _oid, cells in ordered:
                row_obj = self._rows[self._oid_to_row[int(_oid)]]
                self._refresh_color_cache_for_row(row_obj, cells)
        self._invalidate_numeric_bounds_all()
        self.endResetModel()

    def row_oid(self, logical_row: int) -> int:
        return self._rows[logical_row].oid

    def _rebuild_oid_index(self) -> None:
        self._oid_to_row = {int(oid): i for i, oid in enumerate(self._rows.oids[: self._rows.n])}

    def logical_row_for_oid(self, oid: int) -> int:
        r = self._oid_to_row.get(oid, -1)
        if 0 <= r < len(self._rows) and self._rows[r].oid == oid:
            return r
        self._rebuild_oid_index()
        return self._oid_to_row.get(oid, -1)

    def present_oids(self, oids: frozenset[int]) -> frozenset[int]:
        """Subset of *oids* that still have a row (rebuilds the OID index once, not per miss)."""
        self._rebuild_oid_index()
        index = self._oid_to_row
        return frozenset(oid for oid in oids if oid in index)

    def export_rows_for_sqlite(self, data_headers: list[str]) -> list[tuple[int, dict[str, str]]]:
        """Bulk export text columns for the SQLite mirror (avoids per-cell lookup)."""
        return self.export_rows_for_sqlite_slice(data_headers, 0, len(self._rows))

    def export_rows_for_sqlite_slice(
        self,
        data_headers: list[str],
        start_row: int,
        end_row: int,
    ) -> list[tuple[int, dict[str, str]]]:
        """Export a row slice ``[start_row, end_row)`` for chunked SQLite indexing."""
        n = len(self._rows)
        lo = max(0, int(start_row))
        hi = min(n, int(end_row))
        out: list[tuple[int, dict[str, str]]] = []
        for r in range(lo, hi):
            row = self._rows[r]
            cells = {h: self._rows.get_text(r, h) or "" for h in data_headers}
            out.append((int(row.oid), cells))
        return out

    def set_cell_text(self, oid: int, column_name: str, text: str) -> None:
        if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        self._rows[r].values[column_name] = text
        self._refresh_color_cache_for_cell(self._rows[r], column_name, text)
        if column_name in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({column_name})
        try:
            c = self._headers.index(column_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def set_backing_text(self, oid: int, column_name: str, text: str) -> None:
        """Set stored cell text, including pixmap-only structure columns (hidden SMILES)."""
        if column_name in ("ID_HIDDEN", "Structure"):
            return
        if column_name not in self._pixmap_columns:
            self.set_cell_text(oid, column_name, text)
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        self._rows[r].values[column_name] = text
        try:
            c = self._headers.index(column_name)
        except ValueError:
            return
        idx = self.index(r, c)
        self.dataChanged.emit(
            idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.DecorationRole, Qt.SizeHintRole]
        )

    def set_cell_text_batch(self, oid: int, values: dict[str, str]) -> None:
        """Set several text cells on one row; emit ``dataChanged`` once for the affected column span."""
        if not values:
            return
        r = self.logical_row_for_oid(oid)
        if r < 0:
            return
        changed_cols: list[int] = []
        for column_name, text in values.items():
            if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
                continue
            try:
                c = self._headers.index(column_name)
            except ValueError:
                continue
            text_s = str(text)
            self._rows[r].values[column_name] = text_s
            self._refresh_color_cache_for_cell(self._rows[r], column_name, text_s)
            changed_cols.append(c)
        if not changed_cols:
            return
        dirty = {
            self._headers[c]
            for c in changed_cols
            if self._headers[c] in self._bounds_data_headers()
        }
        if dirty:
            self._mark_numeric_bounds_dirty(dirty)
        lo, hi = min(changed_cols), max(changed_cols)
        idx_tl = self.index(r, lo)
        idx_br = self.index(r, hi)
        self.dataChanged.emit(idx_tl, idx_br, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):  # noqa: N802
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._rows) or col < 0 or col >= len(self._headers):
            return None
        h = self._headers[col]
        oid = self._rows.oid_at(row)

        if col == 0:
            if role in (Qt.DisplayRole, Qt.EditRole):
                return str(oid)
            if role == Qt.TextAlignmentRole:
                return table_text_alignment_flags()
            return None

        if col == self.STRUCTURE_COL:
            pix = self.structure_pixmap_for_oid(oid)
            has_pix = pix is not None and not pix.isNull()
            if role == Qt.DecorationRole:
                return pix if has_pix else None
            if role == Qt.EditRole:
                return structure_cell_edit_text(self.structure_text_for_oid(oid))
            if role in (Qt.DisplayRole, Qt.ToolTipRole):
                if has_pix:
                    return None if role == Qt.ToolTipRole else ""
                store = self._structure_png_store
                if store is not None and store.has_png(oid):
                    return None if role == Qt.ToolTipRole else ""
                text = self.structure_text_for_oid(oid)
                if role == Qt.ToolTipRole:
                    return text or STRUCTURE_COLUMN_PENDING_HINT
                return structure_cell_display_text(text)
            if role == Qt.TextAlignmentRole:
                if has_pix:
                    return int(Qt.AlignCenter)
                return table_text_alignment_flags()
            if role == Qt.SizeHintRole:
                if has_pix:
                    return QSize(pix.width(), pix.height())
                return QSize(structure_depict_width(), structure_depict_height())
            return None

        if h in self._pixmap_columns:
            pix = self._extra_pixmaps.get((oid, h))
            has_pix = pix is not None and not pix.isNull()
            backing = self._rows.get_text(row, h) or ""
            if role == Qt.DecorationRole:
                return pix if has_pix else None
            if role == Qt.DisplayRole:
                return "" if has_pix else backing
            if role == Qt.ToolTipRole:
                return None if has_pix else (backing or None)
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter) if has_pix else table_text_alignment_flags()
            if role == Qt.SizeHintRole:
                if has_pix:
                    return QSize(pix.width(), pix.height())
                return None
            return None

        cell_pix = self._extra_pixmaps.get((oid, h))
        if cell_pix is not None and not cell_pix.isNull():
            if role == Qt.DecorationRole:
                return cell_pix
            if role == Qt.SizeHintRole:
                return QSize(cell_pix.width(), cell_pix.height())
            if role == Qt.TextAlignmentRole:
                return int(Qt.AlignCenter)

        if role == Qt.BackgroundRole:
            cmap = self._column_color_cache.get(h)
            if cmap:
                rgb = cmap.get(oid)
                if rgb is not None:
                    qc = self._rgb_qcolor_cache.get(rgb)
                    if qc is None:
                        qc = QColor.fromRgba(rgb)
                        self._rgb_qcolor_cache[rgb] = qc
                    return qc
            return None

        if role in (Qt.DisplayRole, Qt.EditRole):
            return self._rows.get_text(row, h)
        if role == Qt.TextAlignmentRole:
            return table_text_alignment_flags()
        return None

    def setData(self, index: QModelIndex, value, role: int = Qt.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.EditRole:
            return False
        row, col = index.row(), index.column()
        if row < 0 or row >= len(self._rows):
            return False
        if col == self.STRUCTURE_COL:
            self.structureTextEdited.emit(int(self._rows.oid_at(row)), str(value))
            return True
        if col < 2:
            return False
        h = self._headers[col]
        text_s = str(value)
        self._rows.set_text(row, h, text_s)
        self._refresh_color_cache_for_cell(self._rows[row], h, text_s)
        self.dataChanged.emit(index, index, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
        return True

    def flags(self, index: QModelIndex) -> Qt.ItemFlags:  # noqa: N802
        if not index.isValid():
            return Qt.NoItemFlags
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if index.column() == self.STRUCTURE_COL:
            return flags | Qt.ItemIsEditable
        return flags

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole):  # noqa: N802
        if role == Qt.TextAlignmentRole:
            if orientation == Qt.Vertical:
                return int(Qt.AlignCenter)
            return None
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal and 0 <= section < len(self._headers):
            return self._headers[section]
        if orientation == Qt.Vertical:
            return str(section + 1)
        return None

    def sort(
        self, column: int, order: Qt.SortOrder = Qt.AscendingOrder, *, sort_kind: str = "auto"
    ) -> None:  # noqa: N802
        """Sort rows by *column*. *sort_kind*: ``auto`` (numbers then text), ``numeric``, or ``alphabetic``."""
        if column < 0 or column >= len(self._headers):
            return
        h = self._headers[column]
        rev = order == Qt.DescendingOrder

        def key_auto(row: _Row) -> tuple:
            if column == 0:
                return (0, row.oid)
            if column == 1:
                return (0, row.oid)
            raw = row.values.get(h, "") or ""
            f = safe_float(raw)
            if f is not None:
                return (0, float(f))
            return (1, raw.lower())

        def key_numeric(row: _Row) -> tuple:
            if column == 0:
                return (0, row.oid)
            if column == 1:
                return (0, row.oid)
            raw = (row.values.get(h, "") or "").strip()
            f = safe_float(raw)
            if f is not None:
                return (0, float(f))
            return (1, raw.lower())

        def key_alpha(row: _Row) -> tuple:
            if column == 0:
                return (0, str(row.oid))
            if column == 1:
                return (0, str(row.oid))
            raw = (row.values.get(h, "") or "").strip()
            return (1, raw.lower())

        if sort_kind == "numeric":
            key = key_numeric
        elif sort_kind == "alphabetic":
            key = key_alpha
        else:
            key = key_auto

        self.layoutAboutToBeChanged.emit([], QAbstractItemModel.VerticalSortHint)
        self._rows.sort(key=key, reverse=rev)
        self.layoutChanged.emit([], QAbstractItemModel.VerticalSortHint)
        self._rebuild_oid_index()

    def all_oids_in_order(self) -> list[int]:
        return [r.oid for r in self._rows]

    def cell_text(self, row: int, col: int) -> str:
        if row < 0 or row >= len(self._rows) or col < 0 or col >= len(self._headers):
            return ""
        if col == 0:
            return str(self._rows.oid_at(row))
        if col == self.STRUCTURE_COL:
            return self.structure_text_for_oid(self._rows.oid_at(row))
        h = self._headers[col]
        if h in self._pixmap_columns:
            return ""
        return self._rows.get_text(row, h) or ""

    def analysis_column_texts(
        self, headers: list[str], rows: list[int] | None = None
    ) -> dict[str, list[str] | object]:
        """Per-column values for *rows* (all rows when ``None``).

        Uniform numeric columns are float64 arrays (blank cells are NaN). Text columns are
        stripped strings, including pixmap-column backing text. An empty *rows* list still
        returns every column name so pickers can list headers without reading cells.
        """
        n = len(self._rows)
        if rows is None:
            indices: list[int] | None = None
            width = n
        else:
            indices = [r for r in rows if 0 <= int(r) < n]
            width = len(indices)
        oids = self._rows.oids[:n]
        out: dict[str, list[str] | object] = {}
        for col, name in enumerate(headers):
            if col >= len(self._headers) or col == self.STRUCTURE_COL or name == "Structure":
                continue
            if col == 0:
                if indices is None:
                    out[name] = [str(int(oid)) for oid in oids]
                else:
                    out[name] = [str(int(oids[i])) for i in indices]
                continue
            if width == 0 and rows is not None:
                out[name] = []
                continue
            out[name] = self._rows.analysis_values(name, indices)
        return out

    def value_for_header(self, row: int, header_name: str) -> str:
        """Raw string cell for a data column (no QModelIndex); empty if unknown column."""
        if row < 0 or row >= len(self._rows):
            return ""
        if header_name in self._pixmap_columns:
            return ""
        return self._rows.get_text(row, header_name) or ""

    def backing_value_for_row_header(self, row: int, header_name: str) -> str:
        """Stored cell text even when ``header_name`` is a pixmap-only column (hidden from ``cell_text``)."""
        if row < 0 or row >= len(self._rows):
            return ""
        return (self._rows.get_text(row, header_name) or "").strip()

    def moveRow(
        self,
        sourceParent: QModelIndex,
        sourceRow: int,
        destinationParent: QModelIndex,
        destinationChild: int,
    ) -> bool:  # noqa: N802
        if sourceParent.isValid() or destinationParent.isValid():
            return False
        n = len(self._rows)
        if sourceRow < 0 or sourceRow >= n or destinationChild < 0 or destinationChild > n:
            return False
        if sourceRow == destinationChild:
            return True
        self.beginMoveRows(QModelIndex(), sourceRow, sourceRow, QModelIndex(), destinationChild)
        row = self._rows.pop(sourceRow)
        if destinationChild > sourceRow:
            self._rows.insert(destinationChild, row)
        else:
            self._rows.insert(destinationChild, row)
        self.endMoveRows()
        self._rebuild_oid_index()
        return True


def run_table_model_demo() -> int:
    from ..table_model_demo import run_table_model_demo as _run

    return _run()


if __name__ == "__main__":
    raise SystemExit(run_table_model_demo())
