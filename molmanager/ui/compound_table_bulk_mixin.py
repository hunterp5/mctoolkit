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

"""Bulk cell/column mutation helpers for CompoundTableModel."""

from __future__ import annotations

from PyQt5.QtCore import QModelIndex, Qt
from PyQt5.QtGui import QPixmap


class CompoundTableBulkMixin:
    def set_cell_text_at(self, row: int, col: int, text: str) -> None:
        if row < 0 or row >= len(self._rows) or col < 2 or col >= len(self._headers):
            return
        h = self._headers[col]
        if h in self._pixmap_columns:
            return
        self._rows[row].values[h] = str(text)
        self._refresh_color_cache_for_cell(self._rows[row], h, str(text))
        if h in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({h})
        idx = self.index(row, col)
        self.dataChanged.emit(idx, idx, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])

    def column_text_by_oid(self, header_name: str) -> dict[int, str]:
        """Snapshot one text column as ``{oid: value}`` (fast path for undo / bulk ops)."""
        if header_name in ("ID_HIDDEN", "Structure") or header_name in self._pixmap_columns:
            return {}
        out: dict[int, str] = {}
        for row in self._rows:
            out[row.oid] = str(row.values.get(header_name, ""))
        return out

    def duplicate_column_at(
        self,
        dest_col: int,
        header_name: str,
        src_logical: int,
        *,
        value_by_oid: dict[int, str] | None = None,
        pixmap_by_oid: dict[int, QPixmap] | None = None,
        png_by_oid: dict[int, bytes] | None = None,
        as_pixmap: bool = False,
    ) -> None:
        """Insert a column and bulk-copy values from *src_logical* with one model notification.

        ``value_by_oid`` / ``pixmap_by_oid`` override the source cells (used when
        duplicating Structure, which does not store SMILES in ``row.values``).
        Pixmap source columns are copied as pixmap columns unless *as_pixmap* is
        forced on for Structure.
        """
        n = len(self._headers)
        if dest_col < 0 or dest_col > n or src_logical < 0 or src_logical >= n:
            return
        src_key = self._headers[src_logical]
        src_is_pixmap = src_key in self._pixmap_columns
        copy_as_pixmap = bool(as_pixmap) or src_is_pixmap
        self.beginInsertColumns(QModelIndex(), dest_col, dest_col)
        self._headers.insert(dest_col, header_name)
        for row in self._rows:
            if value_by_oid is not None:
                row.values[header_name] = str(value_by_oid.get(int(row.oid), "") or "")
            else:
                row.values[header_name] = str(row.values.get(src_key, "") or "")
        if src_key in self._column_color_rules:
            self._column_color_rules[header_name] = self._column_color_rules[src_key]
            self._rebuild_column_color_cache(header_name)
        if copy_as_pixmap:
            self._pixmap_columns.add(header_name)
            if png_by_oid:
                self._extra_pixmaps.set_png_bytes_batch(
                    header_name, [(int(oid), raw) for oid, raw in png_by_oid.items()]
                )
            elif pixmap_by_oid:
                for oid, pm in pixmap_by_oid.items():
                    if pm is not None and not pm.isNull():
                        self._extra_pixmaps.set_pixmap(int(oid), header_name, pm)
            elif src_is_pixmap:
                for oid, h in self._extra_pixmaps.keys():
                    if h == src_key:
                        self._extra_pixmaps.copy_png((oid, src_key), (oid, header_name))
        self._mark_headers_added_for_bounds([header_name])
        self.endInsertColumns()
        if self._rows:
            roles = [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
            if copy_as_pixmap:
                roles.extend([Qt.DecorationRole, Qt.SizeHintRole, Qt.ToolTipRole])
            self.dataChanged.emit(
                self.index(0, dest_col),
                self.index(len(self._rows) - 1, dest_col),
                roles,
            )

    def _emit_data_changed_row_spans(
        self,
        rows_changed: list[int],
        lo_col: int,
        hi_col: int,
        *,
        roles: list | None = None,
    ) -> None:
        """Notify the view only for changed rows (merged ranges), not the whole table."""
        if not rows_changed or not self._rows:
            return
        if roles is None:
            roles = [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
        n = len(self._rows)
        unique = sorted({int(r) for r in rows_changed if 0 <= int(r) < n})
        if not unique:
            return
        if len(unique) >= max(1, int(n * 0.85)):
            self.dataChanged.emit(self.index(0, lo_col), self.index(n - 1, hi_col), roles)
            return
        i = 0
        while i < len(unique):
            lo_r = hi_r = unique[i]
            while i + 1 < len(unique) and unique[i + 1] == hi_r + 1:
                i += 1
                hi_r = unique[i]
            self.dataChanged.emit(self.index(lo_r, lo_col), self.index(hi_r, hi_col), roles)
            i += 1

    def set_column_text_by_oids(self, column_name: str, oid_values: list[tuple[int, str]]) -> None:
        """Set one text column for many molecule ids; batch ``dataChanged`` (contiguous row runs)."""
        if (
            not oid_values
            or column_name in ("ID_HIDDEN", "Structure")
            or column_name in self._pixmap_columns
        ):
            return
        try:
            col = self._headers.index(column_name)
        except ValueError:
            return
        rows_changed: list[int] = []
        for oid, text in oid_values:
            r = self.logical_row_for_oid(oid)
            if r < 0:
                continue
            text_s = str(text)
            self._rows[r].values[column_name] = text_s
            self._refresh_color_cache_for_cell(self._rows[r], column_name, text_s)
            rows_changed.append(r)
        if not rows_changed:
            return
        if column_name in self._bounds_data_headers():
            self._mark_numeric_bounds_dirty({column_name})
        self._emit_data_changed_row_spans(rows_changed, col, col)

    def set_column_backing_text_by_oids(
        self, column_name: str, oid_values: list[tuple[int, str]]
    ) -> None:
        """Like :meth:`set_column_text_by_oids`, but also writes pixmap-only columns' hidden text."""
        if column_name not in self._pixmap_columns:
            self.set_column_text_by_oids(column_name, oid_values)
            return
        try:
            col = self._headers.index(column_name)
        except ValueError:
            return
        rows_changed: list[int] = []
        for oid, text in oid_values:
            r = self.logical_row_for_oid(oid)
            if r < 0:
                continue
            self._rows[r].values[column_name] = str(text)
            rows_changed.append(r)
        self._emit_data_changed_row_spans(
            rows_changed,
            col,
            col,
            roles=[Qt.DisplayRole, Qt.EditRole, Qt.DecorationRole, Qt.SizeHintRole],
        )

    def apply_columns_values_bulk(
        self,
        column_names: list[str],
        oid_value_rows: list[tuple[int, dict[str, str]]],
        *,
        emit: bool = True,
    ) -> None:
        """Fill several columns for many rows; one ``dataChanged`` for the affected column block."""
        if not column_names or not oid_value_rows:
            return
        cols: list[int] = []
        col_set: set[str] = set()
        for header_name in column_names:
            if header_name in ("ID_HIDDEN", "Structure") or header_name in self._pixmap_columns:
                continue
            try:
                cols.append(self._headers.index(header_name))
                col_set.add(header_name)
            except ValueError:
                continue
        if not cols or not col_set:
            return
        colored_cols = [h for h in col_set if h in self._column_color_rules]
        from ..platform_support.config import load_config

        defer_color = len(oid_value_rows) >= int(load_config().bulk_update_defer_color_cache_rows)
        rows_changed: list[int] = []
        for oid, row_d in oid_value_rows:
            r = self._oid_to_row.get(int(oid), -1)
            if r < 0 or r >= len(self._rows):
                continue
            row_obj = self._rows[r]
            for header_name in col_set:
                if header_name not in row_d:
                    continue
                row_obj.values[header_name] = str(row_d[header_name])
            rows_changed.append(r)
        if defer_color:
            for header_name in colored_cols:
                self._column_color_cache.pop(header_name, None)
        else:
            for header_name in colored_cols:
                self._rebuild_column_color_cache(header_name)
        dirty_bounds = {h for h in col_set if h in self._bounds_data_headers()}
        if dirty_bounds:
            self._mark_numeric_bounds_dirty(dirty_bounds)
        if emit and rows_changed and cols:
            roles = [Qt.DisplayRole, Qt.EditRole]
            if not defer_color:
                roles.append(Qt.BackgroundRole)
            self._emit_data_changed_row_spans(rows_changed, min(cols), max(cols), roles=roles)

    def fill_column_from_oid_map(
        self,
        column_name: str,
        oid_to_text: dict[int, str],
        *,
        default: str = "",
        emit: bool = True,
        start_row: int = 0,
        end_row: int | None = None,
        rebuild_color: bool | None = None,
    ) -> None:
        """
        Set one column for every row in a single pass (for sparse maps + default fill).

        Used when most rows share a default (e.g. fingerprint similarity ``N/A``).
        ``start_row``/``end_row`` limit the slice to ``[start_row, end_row)``. Color
        cache rebuild defaults to the full-column case.
        """
        if column_name in ("ID_HIDDEN", "Structure") or column_name in self._pixmap_columns:
            return
        try:
            col = self._headers.index(column_name)
        except ValueError:
            return
        n = len(self._rows)
        lo = max(0, int(start_row))
        hi = n if end_row is None else min(n, int(end_row))
        if lo >= hi:
            return
        for row in self._rows[lo:hi]:
            row.values[column_name] = oid_to_text.get(row.oid, default)
        full = lo == 0 and hi == n
        do_color = rebuild_color if rebuild_color is not None else full
        if do_color and column_name in self._column_color_rules:
            self._rebuild_column_color_cache(column_name)
        if column_name in self._bounds_data_headers() and full:
            self._mark_numeric_bounds_dirty({column_name})
        if emit and self._rows:
            self.dataChanged.emit(
                self.index(lo, col),
                self.index(hi - 1, col),
                [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole],
            )

    def insert_columns_at(
        self, col: int, header_names: list[str], copy_from_logical: int | None = None
    ) -> None:
        """Insert multiple headers in one model notification (large tables)."""
        if not header_names:
            return
        n = len(self._headers)
        if col < 0 or col > n:
            return
        copy_key = None
        if copy_from_logical is not None and 0 <= copy_from_logical < n:
            copy_key = self._headers[copy_from_logical]
        last = col + len(header_names) - 1
        self.beginInsertColumns(QModelIndex(), col, last)
        for i, header_name in enumerate(header_names):
            self._headers.insert(col + i, header_name)
        if copy_key is not None:
            for header_name in header_names:
                for row in self._rows:
                    row.values[header_name] = row.values.get(copy_key, "")
                if copy_key in self._column_color_rules:
                    self._column_color_rules[header_name] = self._column_color_rules[copy_key]
                    self._rebuild_column_color_cache(header_name)
        self._mark_headers_added_for_bounds(header_names)
        self.endInsertColumns()

    def insert_column_at(
        self, col: int, header_name: str, copy_from_logical: int | None = None
    ) -> None:
        n = len(self._headers)
        if col < 0 or col > n:
            return
        copy_key = None
        if copy_from_logical is not None and 0 <= copy_from_logical < n:
            copy_key = self._headers[copy_from_logical]
        self.beginInsertColumns(QModelIndex(), col, col)
        self._headers.insert(col, header_name)
        if copy_key is not None:
            for row in self._rows:
                row.values[header_name] = row.values.get(copy_key, "")
            if copy_key in self._column_color_rules:
                self._column_color_rules[header_name] = self._column_color_rules[copy_key]
                self._rebuild_column_color_cache(header_name)
            self._invalidate_numeric_bounds_all()
        else:
            self._mark_headers_added_for_bounds([header_name])
        self.endInsertColumns()

    def remove_column_at(self, col: int) -> None:
        if col < 0 or col >= len(self._headers):
            return
        h = self._headers[col]
        if h in self._pixmap_columns:
            self._pixmap_columns.discard(h)
            self._extra_pixmaps.remove_header(h)
        self._column_color_rules.pop(h, None)
        self._column_color_cache.pop(h, None)
        self.beginRemoveColumns(QModelIndex(), col, col)
        self._headers.pop(col)
        if col >= 2:
            for row in self._rows:
                row.values.pop(h, None)
        self._mark_header_removed_for_bounds(h)
        self.endRemoveColumns()

    def rename_header_at(self, col: int, new_name: str) -> None:
        if col < 0 or col >= len(self._headers) or self._headers[col] == new_name:
            return
        old = self._headers[col]
        self._headers[col] = new_name
        if old in self._column_color_rules:
            self._column_color_rules[new_name] = self._column_color_rules.pop(old)
        if old in self._column_color_cache:
            self._column_color_cache[new_name] = self._column_color_cache.pop(old)
        if col >= 2 and old in self._pixmap_columns:
            self._pixmap_columns.discard(old)
            self._pixmap_columns.add(new_name)
            self._extra_pixmaps.rename_header(old, new_name)
        if col >= 2:
            for row in self._rows:
                if old in row.values:
                    row.values[new_name] = row.values.pop(old)
        self.headerDataChanged.emit(Qt.Horizontal, col, col)
        c0 = self.index(0, col)
        c1 = self.index(max(len(self._rows) - 1, 0), col)
        self.dataChanged.emit(c0, c1, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole])
        self._invalidate_numeric_bounds_all()
