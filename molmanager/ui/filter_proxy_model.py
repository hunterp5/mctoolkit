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

"""Proxy model for scalable table visibility filtering."""

from __future__ import annotations

from PyQt5.QtCore import QAbstractProxyModel, QModelIndex, Qt


class FilterProxyModel(QAbstractProxyModel):
    """Filter rows by source-model OID membership via an explicit row map.

    When the accepted OID set changes, rebuild ``_source_rows`` once and reset
    the proxy. That avoids ``QSortFilterProxyModel.invalidateFilter``, which
    walks every source row through Python ``filterAcceptsRow`` (costly once a
    view is attached).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_oids: frozenset[int] | None = None
        # None => identity mapping (all source rows visible, in order).
        self._source_rows: list[int] | None = None
        self._proxy_for_source: list[int] | None = None
        self._source_connected = False

    def visible_oids(self) -> frozenset[int] | None:
        """OIDs currently accepted by the filter. ``None`` means every row is visible."""
        return self._visible_oids

    def visible_source_rows(self) -> list[int] | None:
        """Source-row indices currently shown, or ``None`` when unfiltered (all rows)."""
        if self._visible_oids is None:
            return None
        return list(self._source_rows or [])

    def source_rows_for_row_spans(self, spans: list[tuple[int, int]]) -> list[int]:
        """Source rows for inclusive proxy-row spans, without per-row ``mapToSource`` calls.

        Ascending when *spans* are sorted and disjoint (the proxy keeps source order).
        """
        n = self.rowCount()
        out: list[int] = []
        for lo, hi in spans:
            lo, hi = max(0, int(lo)), min(n - 1, int(hi))
            if hi < lo:
                continue
            if self._source_rows is None:
                out.extend(range(lo, hi + 1))
            else:
                out.extend(self._source_rows[lo : hi + 1])
        return out

    def setSourceModel(self, source) -> None:  # noqa: N802
        old = self.sourceModel()
        if old is not None and self._source_connected:
            try:
                old.dataChanged.disconnect(self._on_source_data_changed)
                old.rowsInserted.disconnect(self._on_source_structure_changed)
                old.rowsRemoved.disconnect(self._on_source_structure_changed)
                old.modelReset.disconnect(self._on_source_structure_changed)
                old.layoutChanged.disconnect(self._on_source_structure_changed)
                old.headerDataChanged.disconnect(self._on_source_header_data_changed)
                old.columnsAboutToBeInserted.disconnect(
                    self._on_source_columns_about_to_be_inserted
                )
                old.columnsInserted.disconnect(self._on_source_columns_inserted)
                old.columnsAboutToBeRemoved.disconnect(self._on_source_columns_about_to_be_removed)
                old.columnsRemoved.disconnect(self._on_source_columns_removed)
            except TypeError:
                pass
            self._source_connected = False
        super().setSourceModel(source)
        if source is not None:
            source.dataChanged.connect(self._on_source_data_changed)
            source.rowsInserted.connect(self._on_source_structure_changed)
            source.rowsRemoved.connect(self._on_source_structure_changed)
            source.modelReset.connect(self._on_source_structure_changed)
            source.layoutChanged.connect(self._on_source_structure_changed)
            source.headerDataChanged.connect(self._on_source_header_data_changed)
            # Columns map 1:1 (only rows are filtered). Forward insert/remove so the
            # view drops/adds sections; a bare columnCount() change leaves blanks.
            source.columnsAboutToBeInserted.connect(self._on_source_columns_about_to_be_inserted)
            source.columnsInserted.connect(self._on_source_columns_inserted)
            source.columnsAboutToBeRemoved.connect(self._on_source_columns_about_to_be_removed)
            source.columnsRemoved.connect(self._on_source_columns_removed)
            self._source_connected = True
        self._rebuild_maps(emit_reset=True)

    def set_visible_oids(self, oids: frozenset[int] | None) -> bool:
        """Update visibility. Returns ``True`` when the accepted set changed."""
        new_oids = None if oids is None else frozenset(int(x) for x in oids)
        if new_oids == self._visible_oids:
            return False
        self._visible_oids = new_oids
        self._rebuild_maps(emit_reset=True)
        return True

    def _rebuild_maps(self, *, emit_reset: bool) -> None:
        src = self.sourceModel()
        if self._visible_oids is None or src is None:
            if emit_reset:
                self.beginResetModel()
            self._source_rows = None
            self._proxy_for_source = None
            if emit_reset:
                self.endResetModel()
            return

        n = int(src.rowCount())
        flags = bytearray(n)
        logical = getattr(src, "logical_row_for_oid", None)
        if callable(logical):
            for oid in self._visible_oids:
                r = int(logical(int(oid)))
                if 0 <= r < n:
                    flags[r] = 1
        else:
            row_oid = getattr(src, "row_oid", None)
            if callable(row_oid):
                visible = self._visible_oids
                for r in range(n):
                    if int(row_oid(r)) in visible:
                        flags[r] = 1

        source_rows = [r for r in range(n) if flags[r]]
        proxy_for_source = [-1] * n
        for pr, sr in enumerate(source_rows):
            proxy_for_source[sr] = pr

        if emit_reset:
            self.beginResetModel()
        self._source_rows = source_rows
        self._proxy_for_source = proxy_for_source
        if emit_reset:
            self.endResetModel()

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        src = self.sourceModel()
        if src is None:
            return 0
        if self._source_rows is None:
            return int(src.rowCount())
        return len(self._source_rows)

    def columnCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        if parent.isValid():
            return 0
        src = self.sourceModel()
        return 0 if src is None else int(src.columnCount())

    def index(self, row: int, column: int, parent=QModelIndex()):  # noqa: N802
        if parent.isValid() or row < 0 or column < 0:
            return QModelIndex()
        if row >= self.rowCount() or column >= self.columnCount():
            return QModelIndex()
        return self.createIndex(row, column)

    def parent(self, child):  # noqa: N802
        return QModelIndex()

    def mapToSource(self, proxy_index):  # noqa: N802
        if not proxy_index.isValid() or proxy_index.model() is not self:
            return QModelIndex()
        src = self.sourceModel()
        if src is None:
            return QModelIndex()
        row = int(proxy_index.row())
        col = int(proxy_index.column())
        if self._source_rows is None:
            return src.index(row, col)
        if row < 0 or row >= len(self._source_rows):
            return QModelIndex()
        return src.index(self._source_rows[row], col)

    def mapFromSource(self, source_index):  # noqa: N802
        if not source_index.isValid():
            return QModelIndex()
        src = self.sourceModel()
        if src is None or source_index.model() is not src:
            return QModelIndex()
        sr = int(source_index.row())
        col = int(source_index.column())
        if self._source_rows is None:
            return self.index(sr, col)
        mapping = self._proxy_for_source
        if mapping is None or sr < 0 or sr >= len(mapping):
            return QModelIndex()
        pr = mapping[sr]
        if pr < 0:
            return QModelIndex()
        return self.index(pr, col)

    def data(self, index, role=Qt.DisplayRole):  # noqa: N802
        src = self.mapToSource(index)
        if not src.isValid():
            return None
        return self.sourceModel().data(src, role)

    def setData(self, index, value, role=Qt.EditRole) -> bool:  # noqa: N802
        src = self.mapToSource(index)
        if not src.isValid():
            return False
        return bool(self.sourceModel().setData(src, value, role))

    def flags(self, index):  # noqa: N802
        src = self.mapToSource(index)
        if not src.isValid():
            return Qt.NoItemFlags
        return self.sourceModel().flags(src)

    def headerData(self, section, orientation, role=Qt.DisplayRole):  # noqa: N802
        src = self.sourceModel()
        if src is None:
            return None
        if orientation == Qt.Vertical:
            if self._source_rows is None:
                return src.headerData(section, orientation, role)
            if section < 0 or section >= len(self._source_rows):
                return None
            # Keep 1-based visual row numbers in the filtered view.
            if role == Qt.DisplayRole:
                return str(section + 1)
            return src.headerData(self._source_rows[section], orientation, role)
        return src.headerData(section, orientation, role)

    def _on_source_header_data_changed(self, orientation, first, last) -> None:
        if orientation == Qt.Horizontal:
            self.headerDataChanged.emit(orientation, first, last)
            return
        # Vertical headers are view-local when filtered.
        self.headerDataChanged.emit(orientation, 0, max(0, self.rowCount() - 1))

    def _on_source_columns_about_to_be_inserted(self, parent, first, last) -> None:
        if parent.isValid():
            return
        self.beginInsertColumns(QModelIndex(), int(first), int(last))

    def _on_source_columns_inserted(self, parent, _first, _last) -> None:
        if parent.isValid():
            return
        self.endInsertColumns()

    def _on_source_columns_about_to_be_removed(self, parent, first, last) -> None:
        if parent.isValid():
            return
        self.beginRemoveColumns(QModelIndex(), int(first), int(last))

    def _on_source_columns_removed(self, parent, _first, _last) -> None:
        if parent.isValid():
            return
        self.endRemoveColumns()

    def _on_source_structure_changed(self, *args) -> None:
        self._rebuild_maps(emit_reset=True)

    def _on_source_data_changed(self, top_left, bottom_right, roles=()) -> None:
        src = self.sourceModel()
        if src is None or not top_left.isValid() or not bottom_right.isValid():
            return
        if top_left.model() is not src:
            return
        lo = int(top_left.row())
        hi = int(bottom_right.row())
        c0 = int(top_left.column())
        c1 = int(bottom_right.column())
        role_list = list(roles) if roles else []

        src_n = int(src.rowCount())
        full_span = lo <= 0 and hi >= max(0, src_n - 1)
        if full_span and self._source_rows is not None:
            nproxy = self.rowCount()
            if nproxy <= 0:
                return
            self.dataChanged.emit(self.index(0, c0), self.index(nproxy - 1, c1), role_list)
            return

        if self._source_rows is None:
            self.dataChanged.emit(self.index(lo, c0), self.index(hi, c1), role_list)
            return

        mapping = self._proxy_for_source
        if mapping is None:
            return
        n = len(mapping)
        proxy_rows = [
            mapping[sr]
            for sr in range(max(0, lo), min(hi + 1, n))
            if 0 <= sr < n and mapping[sr] >= 0
        ]
        if not proxy_rows:
            return
        proxy_rows.sort()
        i = 0
        while i < len(proxy_rows):
            a = b = proxy_rows[i]
            while i + 1 < len(proxy_rows) and proxy_rows[i + 1] == b + 1:
                i += 1
                b = proxy_rows[i]
            self.dataChanged.emit(self.index(a, c0), self.index(b, c1), role_list)
            i += 1
