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

"""User row-selection input on the compound table, applied to the :class:`SelectionStore`."""

from __future__ import annotations

from collections.abc import Callable

from PyQt5.QtCore import QItemSelectionModel, QPersistentModelIndex, Qt
from PyQt5.QtWidgets import QTableView

from .selection_store import ORIGIN_TABLE, SelectionStore


class TableRowSelectionController:
    """Turns row-header clicks, select-all, and cell input into entry-selection changes.

    Entry (row) selection lives only in the store; Qt's selection model keeps cell and
    column selection. The two interact the way a single Qt selection used to:

    * a plain or Shift row-header click replaces the entry selection and clears selected
      cells; Ctrl toggles (or with Shift, adds a range) and keeps them;
    * Ctrl+A / the corner button selects every visible entry;
    * cell input that makes Qt clear its selection (a plain click, arrow-key move) clears
      the entry selection too.

    ``oids_for_view_rows`` maps view-model rows (filter proxy rows) to compound OIDs.
    """

    def __init__(
        self,
        view: QTableView,
        store: SelectionStore,
        *,
        oids_for_view_rows: Callable[[list[int]], frozenset[int]],
    ) -> None:
        self._view = view
        self._store = store
        self._oids_for_view_rows = oids_for_view_rows
        self._anchor = QPersistentModelIndex()

    def is_view_row_selected(self, view_row: int) -> bool:
        oids = self._oids_for_view_rows([int(view_row)])
        return bool(oids) and not oids.isdisjoint(self._store.oids)

    def press_row(self, view_row: int, modifiers: Qt.KeyboardModifiers) -> None:
        """Apply a row-header press at *view_row* with the given keyboard *modifiers*."""
        model = self._view.model()
        if model is None or not 0 <= int(view_row) < model.rowCount():
            return
        ctrl = bool(modifiers & Qt.ControlModifier)
        anchor_row = self._anchor.row() if self._anchor.isValid() else -1
        if modifiers & Qt.ShiftModifier and anchor_row >= 0:
            oids = self._oids_for_view_rows(self._view_rows_between(anchor_row, int(view_row)))
            if ctrl:
                self._store.add(oids, origin=ORIGIN_TABLE)
            else:
                self._store.set(oids, origin=ORIGIN_TABLE)
        else:
            oids = self._oids_for_view_rows([int(view_row)])
            if ctrl:
                self._store.set(self._store.oids ^ oids, origin=ORIGIN_TABLE)
            else:
                self._store.set(oids, origin=ORIGIN_TABLE)
            self._anchor = QPersistentModelIndex(model.index(int(view_row), 0))
        sm = self._view.selectionModel()
        if sm is None:
            return
        if not ctrl:
            sm.clearSelection()
        current = sm.currentIndex()
        col = current.column() if current.isValid() else min(1, model.columnCount() - 1)
        target = model.index(int(view_row), max(0, col))
        if target.isValid():
            sm.setCurrentIndex(target, QItemSelectionModel.NoUpdate)

    def select_all(self) -> None:
        """Select every entry shown in the view (filtered-out rows stay unselected)."""
        model = self._view.model()
        n = model.rowCount() if model is not None else 0
        rows = [r for r in range(n) if not self._view.isRowHidden(r)]
        sm = self._view.selectionModel()
        if sm is not None:
            sm.clearSelection()
        self._store.set(self._oids_for_view_rows(rows), origin=ORIGIN_TABLE)

    def clear_for_cell_input(self) -> None:
        self._store.clear(origin=ORIGIN_TABLE)

    def _view_rows_between(self, row_a: int, row_b: int) -> list[int]:
        """Shown view rows from *row_a* to *row_b* inclusive, in on-screen (visual) order."""
        header = self._view.verticalHeader()
        vis_a, vis_b = header.visualIndex(row_a), header.visualIndex(row_b)
        lo, hi = (vis_a, vis_b) if vis_a <= vis_b else (vis_b, vis_a)
        if header.sectionsMoved():
            rows = [header.logicalIndex(v) for v in range(lo, hi + 1)]
        else:
            rows = list(range(lo, hi + 1))
        return [r for r in rows if r >= 0 and not self._view.isRowHidden(r)]
