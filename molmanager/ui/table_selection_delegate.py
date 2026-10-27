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

"""Delegates that paint logical (OID) row selection without Qt selection-model cost."""

from __future__ import annotations

from PyQt5.QtCore import QAbstractProxyModel, QModelIndex, Qt
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QApplication, QStyle, QStyleOptionViewItem, QStyledItemDelegate

from .compound_table_model import CompoundTableModel


def source_row_for_view_index(index: QModelIndex, compound_model: CompoundTableModel) -> int:
    """Map a view (possibly proxy) index to a source-model row index."""
    if not index.isValid():
        return -1
    model = index.model()
    if isinstance(model, QAbstractProxyModel):
        src = model.mapToSource(index)
        if not src.isValid():
            return -1
        return int(src.row())
    return int(index.row())


def row_is_highlighted(index: QModelIndex, compound_model: CompoundTableModel | None) -> bool:
    if compound_model is None:
        return False
    row = source_row_for_view_index(index, compound_model)
    if row < 0:
        return False
    return compound_model.is_row_highlighted(row)


class RowHighlightDelegate(QStyledItemDelegate):
    """Default table delegate: paints Qt selection chrome for logical OID highlights."""

    def __init__(self, compound_model: CompoundTableModel, parent=None) -> None:
        super().__init__(parent)
        self._compound_model = compound_model
        self._pixmap_delegate = None

    def _source_index(self, index: QModelIndex) -> QModelIndex:
        model = index.model()
        if isinstance(model, QAbstractProxyModel):
            return model.mapToSource(index)
        return index

    def _index_is_pixmap_column(self, index: QModelIndex) -> bool:
        src = self._source_index(index)
        if not src.isValid():
            return False
        col = int(src.column())
        headers = getattr(self._compound_model, "_headers", ())
        if col < 0 or col >= len(headers):
            return False
        return bool(self._compound_model.is_pixmap_data_column(headers[col]))

    def _cell_has_pixmap(self, index: QModelIndex) -> bool:
        """True only when this pixmap-column cell actually has an image to paint."""
        if not self._index_is_pixmap_column(index):
            return False
        pix = index.data(Qt.DecorationRole)
        return isinstance(pix, QPixmap) and not pix.isNull()

    def _pixmap_style_delegate(self):
        delg = self._pixmap_delegate
        if delg is None:
            from .compound_table_model import StructureDelegate

            delg = StructureDelegate(self.parent(), self._compound_model)
            self._pixmap_delegate = delg
        return delg

    def depiction_delegates(self) -> list:
        """Structure painters used for pixmap columns (created on first use)."""
        return [self._pixmap_style_delegate()]

    def paint(self, painter, option, index) -> None:  # noqa: N802
        if self._cell_has_pixmap(index):
            self._pixmap_style_delegate().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        if row_is_highlighted(index, self._compound_model):
            opt.state |= QStyle.State_Selected
        widget = opt.widget
        style = widget.style() if widget is not None else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, widget)

    def sizeHint(self, option, index):  # noqa: N802
        if self._cell_has_pixmap(index):
            return self._pixmap_style_delegate().sizeHint(option, index)
        return super().sizeHint(option, index)
