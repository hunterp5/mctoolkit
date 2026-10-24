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

"""Table row/column selection, visibility, and OID override helpers."""

from __future__ import annotations

from PyQt5.QtCore import QEventLoop, QItemSelection, QItemSelectionModel, Qt, QTimer
from PyQt5.QtWidgets import QAbstractItemView, QApplication
from rdkit import Chem

from ...platform_support.config import load_config
from ...services.table_selection import (
    cached_string_key,
    first_rows_for_distinct_keys,
    logical_rows_for_oids,
    oids_for_source_rows,
    oids_from_id_hidden_cells,
    rows_where,
)
from ..layout_perf import perf_span
from ..qt_widget_utils import qobject_is_deleted
from ..selection_store import ORIGIN_TABLE
from ..table_selection import merge_sorted_row_indices

# Sentinel: visible source-row cache is empty (distinct from cached ``None`` = all rows visible).
_VISIBLE_SOURCE_ROWS_UNSET = object()


class TableSelectionMixin:
    """Programmatic and user-driven table selection (including large OID overrides)."""

    def _select_column_range(self, anchor_col: int, end_col: int, *, mode: str = "replace") -> None:
        """Select visible columns from ``anchor_col`` to ``end_col`` (inclusive).

        ``mode`` is forwarded to :meth:`_select_columns` (``replace`` or ``add``).
        """
        hh = self.table.horizontalHeader()
        vis_a = hh.visualIndex(int(anchor_col))
        vis_b = hh.visualIndex(int(end_col))
        if vis_a < 0 or vis_b < 0:
            self._select_columns([end_col], anchor_col=end_col, mode=mode)
            return
        lo, hi = (vis_a, vis_b) if vis_a <= vis_b else (vis_b, vis_a)
        cols: list[int] = []
        for vis in range(lo, hi + 1):
            logical = hh.logicalIndex(vis)
            if logical < 0 or logical >= len(self.headers):
                continue
            if self.headers[logical] == "ID_HIDDEN":
                continue
            cols.append(logical)
        self._select_columns(cols, anchor_col=end_col, mode=mode)

    def _column_span_selection(self, view_model, row_count: int, cols: list[int]) -> QItemSelection:
        """Full-height selection covering ``cols`` in the table view."""
        sel = QItemSelection()
        if row_count <= 0:
            return sel
        last = row_count - 1
        for col in cols:
            sel.select(view_model.index(0, col), view_model.index(last, col))
        return sel

    def _select_columns(
        self, cols: list[int], *, anchor_col: int | None = None, mode: str = "replace"
    ) -> None:
        """Select full columns in the table view.

        ``mode`` matches row-header modifiers: ``replace`` (plain or Shift click)
        clears the entry selection, ``toggle`` (Ctrl click) flips each column,
        and ``add`` (Ctrl+Shift range) unions the columns in. Add and toggle keep
        any entry selection.
        """
        view_model = self.table.model()
        if view_model is None:
            self._report_table_selection_status(0)
            return
        n = view_model.rowCount()
        if n <= 0:
            self._report_table_selection_status(0)
            return
        unique_cols: list[int] = []
        seen: set[int] = set()
        for col in cols:
            c = int(col)
            if c < 0 or c >= len(self.headers) or c in seen:
                continue
            if self.headers[c] == "ID_HIDDEN":
                continue
            seen.add(c)
            unique_cols.append(c)
        if not unique_cols:
            self._report_table_selection_status(0)
            return
        sm = self.table.selectionModel()
        select_cols = unique_cols
        deselect_cols: list[int] = []
        if mode == "toggle" and sm is not None:
            select_cols = []
            for col in unique_cols:
                if sm.isColumnSelected(col):
                    deselect_cols.append(col)
                else:
                    select_cols.append(col)
        prev_behavior = self.table.selectionBehavior()
        was_auto_scroll = bool(self.table.hasAutoScroll())
        self.table.setSelectionBehavior(QAbstractItemView.SelectColumns)
        self.table.setAutoScroll(False)
        scroll_pos = self._table_scroll_pos()
        current = sm.currentIndex() if sm is not None else None
        try:
            if sm is not None:
                if mode == "toggle":
                    if deselect_cols:
                        sm.select(
                            self._column_span_selection(view_model, n, deselect_cols),
                            QItemSelectionModel.Deselect | QItemSelectionModel.Columns,
                        )
                    if select_cols:
                        sm.select(
                            self._column_span_selection(view_model, n, select_cols),
                            QItemSelectionModel.Select | QItemSelectionModel.Columns,
                        )
                elif mode == "add":
                    sm.select(
                        self._column_span_selection(view_model, n, unique_cols),
                        QItemSelectionModel.Select | QItemSelectionModel.Columns,
                    )
                else:
                    sm.select(
                        self._column_span_selection(view_model, n, unique_cols),
                        QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Columns,
                    )
                if mode == "replace" and current is not None and current.isValid():
                    keep = view_model.index(current.row(), unique_cols[0])
                    if keep.isValid():
                        sm.setCurrentIndex(keep, QItemSelectionModel.NoUpdate)
                elif mode != "replace":
                    row = current.row() if current is not None and current.isValid() else 0
                    focus = (
                        int(anchor_col)
                        if anchor_col is not None and int(anchor_col) in seen
                        else unique_cols[-1]
                    )
                    keep = view_model.index(max(0, row), focus)
                    if keep.isValid():
                        sm.setCurrentIndex(keep, QItemSelectionModel.NoUpdate)
        finally:
            self.table.setSelectionBehavior(prev_behavior)
            self.table.setAutoScroll(was_auto_scroll)
            self._restore_table_scroll_pos(scroll_pos)
        # A replacing column click drops any entry selection. This clear is not a
        # user entry selection: the column status below is the message to show.
        # Ctrl add/toggle keeps entries, the way a Ctrl row click keeps cells.
        if mode == "replace":
            self.selection_store.clear()
        focus_col = (
            int(anchor_col)
            if anchor_col is not None and int(anchor_col) in seen
            else unique_cols[-1]
        )
        self._refresh_table_selection_visual(
            None,
            anchor_col=focus_col,
            preserve_scroll=True,
            scroll_pos=scroll_pos,
        )
        n_cols = len(unique_cols) if mode == "replace" else self._full_selected_column_count()
        if n_cols <= 0:
            self._report_table_selection_status(self.selection_store.count())
        else:
            extra = f"{n_cols} column{'s' if n_cols != 1 else ''}."
            self._report_table_selection_status(n, extra=extra)
        self._restore_table_scroll_pos(scroll_pos)

    def _full_selected_column_count(self) -> int:
        """How many data columns are selected for every visible row."""
        sm = self.table.selectionModel()
        if sm is None or not self.headers:
            return 0
        n = 0
        for ix in sm.selectedColumns():
            if not ix.isValid():
                continue
            col = int(ix.column())
            if col <= 0 or col >= len(self.headers) or self.headers[col] == "ID_HIDDEN":
                continue
            n += 1
        return n

    def _table_scroll_pos(self) -> tuple[int, int]:
        vbar = self.table.verticalScrollBar()
        hbar = self.table.horizontalScrollBar()
        return (
            int(vbar.value()) if vbar is not None else 0,
            int(hbar.value()) if hbar is not None else 0,
        )

    def _restore_table_scroll_pos(self, pos: tuple[int, int]) -> None:
        vbar = self.table.verticalScrollBar()
        hbar = self.table.horizontalScrollBar()
        if vbar is not None:
            vbar.setValue(int(pos[0]))
        if hbar is not None:
            hbar.setValue(int(pos[1]))

    def _refresh_table_selection_visual(
        self,
        anchor_rows: list[int] | None,
        anchor_col: int | None = None,
        *,
        preserve_scroll: bool = False,
        scroll_pos: tuple[int, int] | None = None,
        focus: bool = True,
        center: bool = False,
    ) -> None:
        """
        Show selection highlight immediately after programmatic select.

        Deferred one event-loop tick so context-menu focus is released first; then
        anchor the current cell, scroll if needed, optionally focus the table, and repaint.

        When ``anchor_col`` is given (e.g. column selection), the current cell and any
        auto-scroll target that column so the horizontal scroll position is preserved;
        otherwise it defaults to the Structure column for row-based selections.
        ``preserve_scroll`` keeps the current viewport (column header clicks).
        ``scroll_pos`` is the viewport to restore when ``preserve_scroll`` is set.
        ``center`` places the anchor row in the middle of the viewport. ``focus`` gives
        the table keyboard focus.
        """
        frozen = scroll_pos if preserve_scroll else None
        scroll_hint = (
            QAbstractItemView.PositionAtCenter if center else QAbstractItemView.EnsureVisible
        )

        def _apply() -> None:
            # This runs a tick later, by which point the window may be gone: a test has ended, or
            # the cycle collector has freed it. Touching the table then reaches freed C++ memory
            # and takes the process down instead of raising.
            if qobject_is_deleted(self) or qobject_is_deleted(self.table):
                return
            try:
                if anchor_rows and not preserve_scroll:
                    first = min(anchor_rows)
                    ncol = self._table_model.columnCount()
                    if anchor_col is not None:
                        target_col = max(0, min(anchor_col, ncol - 1))
                    else:
                        target_col = 1 if ncol > 1 else 0
                    view_model = self.table.model()
                    proxy = getattr(self, "_filter_proxy_model", None)
                    if proxy is not None and view_model is proxy:
                        pidx = proxy.mapFromSource(self._table_model.index(first, 0))
                        if not pidx.isValid():
                            return
                        idx = view_model.index(pidx.row(), target_col)
                    else:
                        idx = self._table_model.index(first, target_col)
                    sm = self.table.selectionModel()
                    if sm is not None and idx.isValid():
                        sm.setCurrentIndex(idx, QItemSelectionModel.NoUpdate)
                        self.table.scrollTo(idx, scroll_hint)
            finally:
                if frozen is not None:
                    self._restore_table_scroll_pos(frozen)
                if not preserve_scroll and focus:
                    self.table.setFocus(Qt.OtherFocusReason)
                self.table.viewport().update()

        QTimer.singleShot(0, _apply)

    def _set_selection_status(self, message: str, *, pump: bool = False) -> None:
        self.status_label.setText(message)
        if pump:
            QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def _report_table_selection_status(
        self, n_selected: int, *, extra: str = "", pump: bool = True
    ) -> None:
        total = self._table_model.rowCount()
        if total <= 0:
            self._set_selection_status("No rows in table.", pump=pump)
            return
        msg = f"Selected {n_selected:,} of {total:,} row(s)."
        if extra:
            msg = f"{msg} {extra}"
        self._set_selection_status(msg, pump=pump)

    def _maybe_status_before_large_select(self) -> None:
        total = self._table_model.rowCount()
        if total >= load_config().selection_status_min_rows:
            self._set_selection_status(f"Selecting from {total:,} rows…", pump=True)

    def _use_filter_proxy_for_table(self) -> bool:
        proxy = getattr(self, "_filter_proxy_model", None)
        view_model = self.table.model()
        return proxy is not None and view_model is proxy

    def _is_source_row_visible(self, source_row: int) -> bool:
        """Proxy-aware check for whether a source-model row index is currently shown."""
        if self._use_filter_proxy_for_table():
            proxy = self._filter_proxy_model
            return proxy.mapFromSource(self._table_model.index(source_row, 0)).isValid()
        return not self.table.isRowHidden(source_row)

    def _visible_oids_set(self) -> frozenset[int] | None:
        """OIDs currently shown by table filters. ``None`` means every row is visible."""
        if self._use_filter_proxy_for_table():
            proxy = self._filter_proxy_model
            oids = proxy.visible_oids()
            if oids is None:
                return None
            src_n = self._table_model.rowCount()
            if src_n > 0 and len(oids) >= src_n:
                return None
            return oids
        n = self._table_model.rowCount()
        hidden = [r for r in range(n) if self.table.isRowHidden(r)]
        if not hidden:
            return None
        return frozenset(
            int(self._table_model.row_oid(r)) for r in range(n) if not self.table.isRowHidden(r)
        )

    def _invalidate_visible_source_rows_cache(self) -> None:
        """Drop cached visible source-row indices (call when filter visibility changes)."""
        self._visible_source_rows_cache = _VISIBLE_SOURCE_ROWS_UNSET

    def _visible_source_row_indices(self) -> list[int] | None:
        """Source-model row indices for rows currently shown in the table view.

        Returns ``None`` when every source row is visible (no list allocation).
        Results are cached until :meth:`_invalidate_visible_source_rows_cache` so
        multi-plot replot (including debounced Plotter rebuilds) does not rematerialize.
        """
        cache = self._visible_source_rows_cache
        if cache is not _VISIBLE_SOURCE_ROWS_UNSET:
            return cache  # type: ignore[return-value]
        oids = self._visible_oids_set()
        if oids is None:
            self._visible_source_rows_cache = None
            return None
        if self._use_filter_proxy_for_table():
            proxy = self._filter_proxy_model
            rows = proxy.visible_source_rows()
            if rows is not None:
                self._visible_source_rows_cache = rows
                return rows
        n = self._table_model.rowCount()
        out = [r for r in range(n) if int(self._table_model.row_oid(r)) in oids]
        self._visible_source_rows_cache = out
        return out

    def _iter_visible_source_row_indices(self):
        """Iterate visible source rows without building a full index list when possible."""
        indices = self._visible_source_row_indices()
        if indices is None:
            yield from range(self._table_model.rowCount())
        else:
            yield from indices

    def _repaint_table_selection_viewport(self) -> None:
        vp = self.table.viewport()
        if vp is not None:
            vp.update()

    def _sync_table_selection_highlight(self) -> None:
        """Paint every selected entry from the store (covers rows Qt does not hold, e.g.
        large or filtered-out selections), without building a giant QItemSelection."""
        oids = self.selection_store.oids
        self._table_model.set_highlighted_oids(oids or None)
        self._repaint_table_selection_viewport()
        row_header = self.table.verticalHeader()
        if row_header is not None:
            row_header.viewport().update()

    def _on_selection_store_changed(self, origin: object) -> None:
        """Window-side fan-out for every entry-selection change, whoever made it.

        Paints table highlights and pushes the selection to open plots. A change made in
        the compound table (``ORIGIN_TABLE``) also reports how many entries are selected.
        Browsers subscribe to ``selection_store.changed`` themselves.
        """
        with perf_span("selection.store_changed"):
            self._sync_table_selection_highlight()
            self._schedule_sync_active_plots_from_table_selection()
            if origin is ORIGIN_TABLE:
                self._report_table_selection_status(self.selection_store.count(), pump=False)

    def _prune_selection_store(self, *_args) -> None:
        """Forget selected OIDs whose rows were deleted or replaced."""
        self.selection_store.prune(self._table_model.present_oids)

    def _oids_for_view_rows(self, view_rows: list[int]) -> frozenset[int]:
        """OIDs shown at the given table-view rows (filter-proxy rows when filtering)."""
        if not view_rows:
            return frozenset()
        if self._use_filter_proxy_for_table():
            spans = merge_sorted_row_indices(view_rows)
            rows = self._filter_proxy_model.source_rows_for_row_spans(spans)
        else:
            n = self._table_model.rowCount()
            rows = [int(r) for r in view_rows if 0 <= int(r) < n]
        return self._oids_for_source_rows(rows)

    def _clear_qt_cell_selection(self) -> None:
        sm = self.table.selectionModel()
        if sm is not None and sm.hasSelection():
            sm.clearSelection()

    def select_table_rows(
        self,
        rows: list[int],
        *,
        extra_status: str = "",
        origin: object = None,
        reveal: bool = True,
        focus: bool = True,
        center: bool = False,
    ) -> int:
        """Replace the selection with the given source-model rows (an empty list clears it).

        Rows hidden by filters stay selected. ``origin`` tags the resulting
        ``selection_store.changed`` so a subscriber can recognise its own change.
        ``reveal`` moves the current cell to the first visible row and scrolls it into
        view. ``center`` places that row in the middle of the viewport. ``focus`` gives
        the table keyboard focus. Plot clicks reveal and center without taking focus, so
        Shift+select stays in the plot.
        """
        with perf_span("selection.select_rows"):
            return self._apply_table_row_selection(
                rows,
                extra_status=extra_status,
                origin=origin,
                reveal=reveal,
                focus=focus,
                center=center,
            )

    def select_table_oids(
        self,
        oids: list[int] | set[int] | frozenset[int],
        *,
        extra_status: str = "",
        origin: object = None,
        reveal: bool = True,
        focus: bool = True,
        center: bool = False,
    ) -> int:
        """Replace the selection with the given OIDs (an empty set clears it)."""
        source_rows: list[int] = []
        for oid in oids:
            try:
                row = self.logical_row_for_oid(int(oid))
            except (TypeError, ValueError):
                continue
            if row >= 0:
                source_rows.append(int(row))
        return self.select_table_rows(
            source_rows,
            extra_status=extra_status,
            origin=origin,
            reveal=reveal,
            focus=focus,
            center=center,
        )

    def _source_rows_to_view_rows(self, source_rows: list[int]) -> list[int]:
        view_model = self.table.model()
        proxy = getattr(self, "_filter_proxy_model", None)
        use_proxy = proxy is not None and view_model is proxy
        if not use_proxy:
            return list(source_rows)
        view_rows: list[int] = []
        for src_r in source_rows:
            pidx = proxy.mapFromSource(self._table_model.index(src_r, 0))
            if pidx.isValid():
                view_rows.append(int(pidx.row()))
        return view_rows

    def _oids_for_source_rows(self, source_rows: list[int]) -> frozenset[int]:
        return oids_for_source_rows(source_rows, row_oid=self._table_model.row_oid)

    def _apply_table_row_selection(
        self,
        rows: list[int],
        *,
        extra_status: str = "",
        origin: object = None,
        reveal: bool = True,
        focus: bool = True,
        center: bool = False,
    ) -> int:
        """Store the entry selection; the table paints it from the store (no Qt mirror)."""
        n_rows = self._table_model.rowCount()
        uniq = sorted({int(r) for r in rows if 0 <= int(r) < n_rows})
        if not uniq:
            self.clear_table_selection(origin=origin)
            return 0
        oids = self._oids_for_source_rows(uniq)
        self._clear_qt_cell_selection()
        self.selection_store.set(oids, origin=origin)
        extra = str(extra_status or "")
        visible = self._visible_oids_set()
        if visible is not None and not oids <= visible:
            hint = "(includes rows hidden by filters)"
            extra = f"{extra} {hint}".strip() if extra else hint
        if reveal:
            first_shown = next((r for r in uniq if self._is_source_row_visible(r)), None)
            self._refresh_table_selection_visual(
                None if first_shown is None else [first_shown],
                focus=focus,
                center=center,
            )
        n = len(oids)
        self._report_table_selection_status(n, extra=extra, pump=True)
        return n

    def _select_all_visible_rows(self) -> None:
        """Select every row currently visible in the table (respects active filters)."""
        self._maybe_status_before_large_select()
        vis = self._visible_source_row_indices()
        if vis is None:
            vis = list(range(self._table_model.rowCount()))
        self.select_table_rows(vis)

    def _select_all_rows(self) -> None:
        """Select every visible table row (same as Select All on a column header)."""
        self._select_all_visible_rows()

    def _clear_entry_selection(self, *, origin: object = None) -> None:
        self._clear_qt_cell_selection()
        self.selection_store.clear(origin=origin)

    def clear_table_selection(self, *, origin: object = None) -> None:
        """Clear the entry selection and any selected cells (store, highlights, plots)."""
        self._clear_entry_selection(origin=origin)
        self._report_table_selection_status(0)

    def invert_table_selection(self) -> None:
        """Select every table row that is not currently selected (full table, including filtered-out rows)."""
        n_rows = self._table_model.rowCount()
        if n_rows <= 0:
            self.clear_table_selection()
            return
        selected_rows = set(self._selected_logical_rows())
        inverted = [r for r in range(n_rows) if r not in selected_rows]
        if not inverted:
            self.clear_table_selection()
            return
        if len(inverted) >= load_config().selection_status_min_rows:
            self._maybe_status_before_large_select()
        self.select_table_rows(inverted, extra_status="Inverted.")

    def _select_first_occurrence_per_distinct_value(self, col: int) -> None:
        """Select the first visible row for each distinct non-empty cell text in this column."""
        self._maybe_status_before_large_select()
        to_sel = first_rows_for_distinct_keys(
            self._iter_visible_source_row_indices(),
            key_for_row=lambda r: (self._table_model.cell_text(r, col) or "").strip(),
        )
        self.select_table_rows(to_sel)

    def _select_empty_cells_in_column(self, col: int) -> None:
        """Select visible rows where this column is empty or whitespace-only."""
        self._maybe_status_before_large_select()
        to_sel = rows_where(
            self._iter_visible_source_row_indices(),
            predicate=lambda r: not (self._table_model.cell_text(r, col) or "").strip(),
        )
        self.select_table_rows(to_sel)

    def _structure_column_row_is_empty(self, row: int) -> bool:
        """True when the molecule store has no structure for the row."""
        try:
            oid = self._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return True
        return not self._structure_text_for_oid(oid)

    def _select_empty_structure_cells(self) -> None:
        self._maybe_status_before_large_select()
        to_sel = rows_where(
            self._iter_visible_source_row_indices(),
            predicate=self._structure_column_row_is_empty,
        )
        self.select_table_rows(to_sel)

    def _structure_distinct_key_for_row(
        self, row: int, *, smiles_key_cache: dict[str, str] | None = None
    ) -> str:
        """Canonical structure key for Select → first occurrence on the Structure column."""
        try:
            oid = self._table_model.row_oid(row)
        except (IndexError, ValueError, TypeError):
            return ""
        mol = self.mols.get(oid)
        if mol is not None:
            try:
                raw = Chem.MolToSmiles(mol)
            except Exception:
                raw = ""
            if raw:
                return self._canonical_structure_key_cached(raw, smiles_key_cache)
        return ""

    def _canonical_structure_key_cached(self, smiles: str, cache: dict[str, str] | None) -> str:
        return cached_string_key(
            smiles,
            cache,
            key_fn=self.canonical_structure_key_from_smiles,
        )

    def _select_first_occurrence_per_distinct_structure(self) -> None:
        self._maybe_status_before_large_select()
        smiles_key_cache: dict[str, str] = {}
        to_sel = first_rows_for_distinct_keys(
            self._iter_visible_source_row_indices(),
            key_for_row=lambda r: self._structure_distinct_key_for_row(
                r, smiles_key_cache=smiles_key_cache
            ),
        )
        self.select_table_rows(to_sel)

    def reveal_first_selected_row(self, *, focus: bool = False, center: bool = True) -> None:
        """Scroll the compound table to the first visible selected entry."""
        rows = self._selected_logical_rows()
        first = next((r for r in rows if self._is_source_row_visible(r)), None)
        if first is None:
            return
        self._refresh_table_selection_visual([first], focus=focus, center=center)

    def _selected_logical_rows(self) -> list[int]:
        """Sorted source-model rows of the selected entries (includes filtered-out rows)."""
        return logical_rows_for_oids(
            self.selection_store.oids,
            logical_row_for_oid=self._table_model.logical_row_for_oid,
        )

    def _selected_row_count_fast(self) -> int:
        """Number of selected entries (no row scan)."""
        return self.selection_store.count()

    def _selected_oids_set(self) -> set[int]:
        return set(self.selection_store.oids)

    def _selected_shown_logical_rows(self) -> list[int]:
        """Sorted source rows of selected entries that table filters currently show."""
        rows = self._selected_logical_rows()
        visible = self._visible_oids_set()
        if visible is None:
            return rows
        row_oid = self._table_model.row_oid
        return [r for r in rows if int(row_oid(r)) in visible]

    def _selected_entry_source_cells(self) -> list[tuple[int, int]]:
        """``(source_row, source_col)`` for every shown data cell of the shown selected entries.

        Entry selection is not in Qt's selection model, so cell-based actions (copy, paste
        origin) add these to Qt's selected cells to treat selected rows as whole rows.
        """
        rows = self._selected_shown_logical_rows()
        if not rows:
            return []
        cols = [
            c for c in range(1, self._table_model.columnCount()) if not self.table.isColumnHidden(c)
        ]
        return [(r, c) for r in rows for c in cols]

    def _selected_oids_for_delete(self) -> frozenset[int]:
        return self.selection_store.oids

    def _oids_for_row_indices(self, rows: list[int]) -> frozenset[int]:
        return oids_from_id_hidden_cells(
            rows,
            cell_text_col0=lambda r: self._table_model.cell_text(r, 0),
        )

    def _clear_table_selection_after_delete(self) -> None:
        self._clear_entry_selection()

    def _refresh_table_after_bulk_delete(self) -> None:
        self.calculate_global_bounds()
        self.apply_filters()

    def _all_oids_in_table_order(self) -> list[int]:
        """Every row OID top-to-bottom (only rows with a numeric hidden id)."""
        out: list[int] = []
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            if t0.isdigit():
                out.append(int(t0))
        return out
