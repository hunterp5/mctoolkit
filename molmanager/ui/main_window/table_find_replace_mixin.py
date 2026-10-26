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

"""Find-and-replace for editable table text cells."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from PyQt5.QtCore import QItemSelectionModel, QTimer, Qt
from PyQt5.QtWidgets import QAbstractItemView, QFrame, QMessageBox, QVBoxLayout

from ..find_replace_panel import FIND_REPLACE_ALL_COLUMNS, FindReplaceBar
from ..text_replace import LiteralReplace, compile_literal_replace
from .table_undo_commands import UndoReplaceTextCommand

_FIND_REPLACE_SCOPES = frozenset({"visible", "table", "selection"})


@dataclass(frozen=True)
class _FindReplaceRequest:
    compiled: LiteralReplace
    scope: str
    columns: tuple[int, ...]
    column_set: frozenset[int]
    selected: frozenset[tuple[int, int]]


class TableFindReplaceMixin:
    """Find and Replace bar above the table.

    Uses the table model, selection, undo stack, and status label from the window.
    Search stays a read-only row query; this mixin writes literal cell text.
    """

    _find_replace_bar: FindReplaceBar
    _find_replace_cursor: tuple[int, int] | None
    _find_replace_query_key_seen: tuple[object, ...] | None

    def _init_find_replace_panel(self, panel: QFrame) -> None:
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(6, 4, 6, 4)
        outer.setSpacing(0)
        self._find_replace_bar = FindReplaceBar(panel)
        outer.addWidget(self._find_replace_bar)
        bar = self._find_replace_bar
        bar.close_btn.clicked.connect(self._close_find_replace_panel)
        bar.find_edit.returnPressed.connect(self.find_replace_find_next)
        bar.replace_edit.returnPressed.connect(self.find_replace_replace)
        bar.find_next_btn.clicked.connect(self.find_replace_find_next)
        bar.replace_btn.clicked.connect(self.find_replace_replace)
        bar.replace_all_btn.clicked.connect(self.find_replace_replace_all)
        self._find_replace_cursor = None
        self._find_replace_query_key_seen = None
        self._session_find_replace_want_visible = False
        self._wire_find_replace_column_refresh()
        self._populate_find_replace_columns()

    def _wire_find_replace_column_refresh(self) -> None:
        if getattr(self, "_find_replace_column_refresh_wired", False):
            return
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        model.columnsInserted.connect(self._on_find_replace_columns_changed)
        model.columnsRemoved.connect(self._on_find_replace_columns_changed)
        model.modelReset.connect(self._on_find_replace_columns_changed)
        model.rowsInserted.connect(self._on_find_replace_rows_changed)
        model.rowsRemoved.connect(self._on_find_replace_rows_changed)
        model.headerDataChanged.connect(self._on_find_replace_header_changed)
        self._find_replace_column_refresh_wired = True

    def _on_find_replace_columns_changed(self, *_args) -> None:
        self._find_replace_cursor = None
        self._find_replace_query_key_seen = None
        self._populate_find_replace_columns()

    def _on_find_replace_rows_changed(self, *_args) -> None:
        self._find_replace_cursor = None
        self._find_replace_query_key_seen = None

    def _on_find_replace_header_changed(self, orientation, *_args) -> None:
        if int(orientation) == int(Qt.Horizontal):
            self._populate_find_replace_columns()

    def _set_find_replace_status(self, detail: str) -> None:
        self.status_label.setText(f"Find and Replace: {detail}")

    def _find_replace_editable_columns(self) -> list[int]:
        model = getattr(self, "_table_model", None)
        headers = getattr(self, "headers", None) or []
        if model is None:
            return []
        limit = min(model.columnCount(), len(headers))
        return [index for index in range(limit) if model.column_accepts_text_edit(index)]

    def _populate_find_replace_columns(
        self,
        *,
        preferred_col: int | None = None,
        preferred_header: str | None = None,
        prefer_all: bool = False,
    ) -> None:
        bar = getattr(self, "_find_replace_bar", None)
        if bar is None:
            return
        combo = bar.column_combo
        prev = combo.currentData()
        prev_header: str | None = None
        if isinstance(prev, int) and 0 <= prev < len(self.headers):
            prev_header = str(self.headers[prev])
        elif prev == FIND_REPLACE_ALL_COLUMNS:
            prev_header = FIND_REPLACE_ALL_COLUMNS
        combo.blockSignals(True)
        combo.clear()
        columns = self._find_replace_editable_columns()
        if not columns:
            combo.addItem("(no text columns)", None)
        else:
            combo.addItem("All text columns", FIND_REPLACE_ALL_COLUMNS)
            for index in columns:
                combo.addItem(str(self.headers[index]), index)
        combo.blockSignals(False)
        want = None if prefer_all else (preferred_header or None)
        if want is None and not prefer_all and preferred_col is not None:
            if 0 <= preferred_col < len(
                self.headers
            ) and self._table_model.column_accepts_text_edit(preferred_col):
                want = str(self.headers[preferred_col])
        if want is None and not prefer_all:
            want = prev_header
        if want and want != FIND_REPLACE_ALL_COLUMNS:
            for row_index in range(combo.count()):
                data = combo.itemData(row_index)
                if (
                    isinstance(data, int)
                    and 0 <= data < len(self.headers)
                    and self.headers[data] == want
                ):
                    combo.setCurrentIndex(row_index)
                    return
        if combo.count():
            combo.setCurrentIndex(0)

    def toggle_find_replace_panel(self) -> None:
        """Show or hide Find and Replace. Field text stays until a new session clears it."""
        panel = getattr(self, "_find_replace_panel", None)
        if panel is None:
            return
        if panel.isHidden():
            panel.setVisible(True)
            self._populate_find_replace_columns()
            self._find_replace_bar.find_edit.setFocus(Qt.ShortcutFocusReason)
            self._set_find_replace_status(
                "text, wildcards (* ?), or comparisons (>10, empty) in editable columns. "
                "Find Next, Replace, or Replace All."
            )
        else:
            panel.setVisible(False)
            self._set_find_replace_status("closed.")
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def _close_find_replace_panel(self) -> None:
        panel = getattr(self, "_find_replace_panel", None)
        if panel is None or panel.isHidden():
            return
        panel.setVisible(False)
        self._set_find_replace_status("closed.")
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def open_find_replace_with_column(self, logical_col: int) -> None:
        """Show the bar and pre-select *logical_col* when that column accepts text edits."""
        panel = getattr(self, "_find_replace_panel", None)
        if panel is None:
            return
        if logical_col < 0 or logical_col >= len(self.headers):
            return
        panel.setVisible(True)
        if self._table_model.column_accepts_text_edit(logical_col):
            self._populate_find_replace_columns(preferred_col=logical_col)
            self._set_find_replace_status(f'column "{self.headers[logical_col]}" selected.')
        else:
            self._populate_find_replace_columns()
            self._set_find_replace_status("this column cannot be edited.")
        self._find_replace_bar.find_edit.setFocus(Qt.ShortcutFocusReason)
        QTimer.singleShot(0, self._sync_filter_panel_scroll_content)

    def _find_replace_query_key(self) -> tuple[object, ...]:
        bar = self._find_replace_bar
        return (
            bar.find_edit.text(),
            bar.column_combo.currentData(),
            bar.scope_combo.currentData(),
            bar.case_cb.isChecked(),
            bar.whole_cb.isChecked(),
        )

    def _note_find_replace_query(self) -> None:
        key = self._find_replace_query_key()
        if key != getattr(self, "_find_replace_query_key_seen", None):
            self._find_replace_query_key_seen = key
            self._find_replace_cursor = None

    def _find_replace_columns(self) -> list[int] | None:
        """Editable columns for the combo, ``None`` when the table has no text columns."""
        editable = self._find_replace_editable_columns()
        if not editable:
            return None
        data = self._find_replace_bar.column_combo.currentData()
        if data == FIND_REPLACE_ALL_COLUMNS:
            return editable
        if isinstance(data, int) and data in set(editable):
            return [data]
        return []

    def _begin_find_replace(self) -> _FindReplaceRequest | None:
        self._note_find_replace_query()
        if getattr(self, "_find_replace_bar", None) is None:
            return None
        bar = self._find_replace_bar
        find = bar.find_edit.text()
        if find == "":
            self._set_find_replace_status("enter text to find.")
            return None
        columns = self._find_replace_columns()
        if columns is None:
            self._set_find_replace_status("no text columns.")
            return None
        if not columns:
            self._set_find_replace_status("this column cannot be edited.")
            return None
        compiled = compile_literal_replace(
            find,
            bar.replace_edit.text(),
            case_sensitive=bar.case_cb.isChecked(),
            whole_cell=bar.whole_cb.isChecked(),
        )
        if compiled is None:
            self._set_find_replace_status("enter text to find.")
            return None
        scope = bar.scope_combo.currentData()
        if scope not in _FIND_REPLACE_SCOPES:
            scope = "visible"
        column_set = frozenset(columns)
        selected: frozenset[tuple[int, int]] = frozenset()
        if scope == "selection":
            raw = self._selected_source_cells()
            selected = frozenset((int(row), int(col)) for row, col in raw if col in column_set)
            if not selected:
                if raw:
                    self._set_find_replace_status("no editable cells selected.")
                else:
                    self._set_find_replace_status("no cells selected.")
                return None
        return _FindReplaceRequest(
            compiled=compiled,
            scope=str(scope),
            columns=tuple(columns),
            column_set=column_set,
            selected=selected,
        )

    def _request_contains(self, request: _FindReplaceRequest, row: int, col: int) -> bool:
        if col not in request.column_set:
            return False
        if request.scope == "selection":
            return (row, col) in request.selected
        if request.scope == "visible":
            return self._is_source_row_visible(row)
        return 0 <= row < self._table_model.rowCount()

    def _iter_request_cells(self, request: _FindReplaceRequest) -> Iterator[tuple[int, int]]:
        if request.scope == "selection":
            for row, col in sorted(request.selected):
                if col in request.column_set:
                    yield row, col
            return
        visible_only = request.scope == "visible"
        for row in range(self._table_model.rowCount()):
            if visible_only and not self._is_source_row_visible(row):
                continue
            for col in request.columns:
                yield row, col

    def _next_match(
        self,
        request: _FindReplaceRequest,
        after: tuple[int, int] | None,
    ) -> tuple[tuple[int, int] | None, bool]:
        """Next in-scope match after *after*. The second value is True when the walk wrapped."""
        first: tuple[int, int] | None = None
        compiled = request.compiled
        for row, col in self._iter_request_cells(request):
            if not compiled.matches(self._table_model.cell_text(row, col)):
                continue
            cell = (row, col)
            if first is None:
                first = cell
            if after is None or cell > after:
                return cell, False
        if first is None:
            return None, False
        return first, True

    def _current_find_replace_cell(self) -> tuple[int, int] | None:
        mapped = self._source_cell_from_view_index(self.table.currentIndex())
        if mapped is None:
            return None
        row, col = mapped
        if row < 0 or col < 0:
            return None
        return row, col

    def _cell_matches_request(self, request: _FindReplaceRequest, row: int, col: int) -> bool:
        if not self._request_contains(request, row, col):
            return False
        return request.compiled.matches(self._table_model.cell_text(row, col))

    def _plan_find_replace(
        self,
        request: _FindReplaceRequest,
        cells: list[tuple[int, int]] | None = None,
    ) -> tuple[list[tuple[int, str, str, str]], int, bool]:
        changes: list[tuple[int, str, str, str]] = []
        occurrences = 0
        matched = False
        source: Iterator[tuple[int, int]]
        if cells is None:
            source = self._iter_request_cells(request)
        else:
            source = iter(cells)
        for row, col in source:
            old = self._table_model.cell_text(row, col)
            if not request.compiled.matches(old):
                continue
            matched = True
            new = request.compiled.apply(old)
            if new is None or col >= len(self.headers):
                continue
            oid = self._oid_for_source_row(row)
            if oid is None:
                continue
            changes.append((int(oid), str(self.headers[col]), old, new))
            occurrences += request.compiled.occurrence_count(old)
        return changes, occurrences, matched

    def _reveal_find_replace_cell(self, row: int, col: int, scope: str) -> bool:
        """Select *row*/*col* and scroll it into view. False when a filter hides the row."""
        model = self._table_model
        if row < 0 or row >= model.rowCount() or col < 0 or col >= model.columnCount():
            return False
        source = model.index(row, col)
        view_model = self.table.model()
        proxy = getattr(self, "_filter_proxy_model", None)
        if proxy is not None and view_model is proxy:
            index = proxy.mapFromSource(source)
        else:
            index = source
        if index is None or not index.isValid():
            return False
        selection = self.table.selectionModel()
        if selection is None:
            return False
        if scope == "selection":
            selection.setCurrentIndex(index, QItemSelectionModel.NoUpdate)
        else:
            selection.setCurrentIndex(
                index,
                QItemSelectionModel.ClearAndSelect | QItemSelectionModel.Current,
            )
        self.table.scrollTo(index, QAbstractItemView.PositionAtCenter)
        viewport = self.table.viewport()
        if viewport is not None:
            viewport.update()
        return True

    def _describe_find_replace_hit(
        self,
        row: int,
        col: int,
        *,
        wrapped: bool,
        revealed: bool,
    ) -> str:
        header = self.headers[col] if 0 <= col < len(self.headers) else "column"
        parts: list[str] = []
        if wrapped:
            parts.append("Wrapped to the first match.")
        if revealed:
            parts.append(f"Match in {header}.")
        else:
            parts.append(f"Match in {header} is hidden by a filter.")
        return " ".join(parts)

    def find_replace_find_next(self) -> None:
        """Select the next in-scope match and wrap to the first after the last."""
        request = self._begin_find_replace()
        if request is None:
            return
        after = getattr(self, "_find_replace_cursor", None)
        if after is None:
            after = self._current_find_replace_cell()
        cell, wrapped = self._next_match(request, after)
        if cell is None:
            self._set_find_replace_status("no matches.")
            return
        revealed = self._reveal_find_replace_cell(cell[0], cell[1], request.scope)
        self._find_replace_cursor = cell
        self._set_find_replace_status(
            self._describe_find_replace_hit(cell[0], cell[1], wrapped=wrapped, revealed=revealed)
        )

    def _replace_target(self, request: _FindReplaceRequest) -> tuple[tuple[int, int] | None, bool]:
        cursor = getattr(self, "_find_replace_cursor", None)
        current = self._current_find_replace_cell()
        if cursor is not None and self._cell_matches_request(request, cursor[0], cursor[1]):
            return cursor, False
        if current is not None and self._cell_matches_request(request, current[0], current[1]):
            return current, False
        after = cursor if cursor is not None else current
        return self._next_match(request, after)

    def _move_after_replace(
        self,
        request: _FindReplaceRequest,
        target: tuple[int, int],
        lead: str,
    ) -> None:
        nxt, wrapped = self._next_match(request, target)
        if nxt is None:
            self._find_replace_cursor = target
            self._reveal_find_replace_cell(target[0], target[1], request.scope)
            self._set_find_replace_status(f"{lead} No further matches.")
            return
        self._find_replace_cursor = nxt
        revealed = self._reveal_find_replace_cell(nxt[0], nxt[1], request.scope)
        hit = self._describe_find_replace_hit(nxt[0], nxt[1], wrapped=wrapped, revealed=revealed)
        self._set_find_replace_status(f"{lead} {hit}")

    def find_replace_replace(self) -> None:
        """Replace matches in the current cell, or the next match, then move on."""
        request = self._begin_find_replace()
        if request is None:
            return
        target, _wrapped = self._replace_target(request)
        if target is None:
            self._set_find_replace_status("no matches.")
            return
        changes, occurrences, matched = self._plan_find_replace(request, [target])
        if changes:
            self._undo_stack.push(UndoReplaceTextCommand(self, changes))
        if occurrences:
            noun = "occurrence" if occurrences == 1 else "occurrences"
            lead = f"replaced {occurrences} {noun} in 1 cell."
        elif matched:
            lead = "cell unchanged."
        else:
            lead = "no matches."
        self._move_after_replace(request, target, lead)

    def _confirm_replace_all(self, occurrences: int, cells: int) -> bool:
        occ = "1 occurrence" if occurrences == 1 else f"{occurrences:,} occurrences"
        cell = "1 cell" if cells == 1 else f"{cells:,} cells"
        reply = QMessageBox.question(
            self,
            "Replace All",
            f"Replace {occ} in {cell}?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def find_replace_replace_all(self) -> None:
        """Replace every in-scope match in one undo step, after confirmation."""
        request = self._begin_find_replace()
        if request is None:
            return
        changes, occurrences, matched = self._plan_find_replace(request)
        if not changes:
            if matched:
                self._set_find_replace_status("nothing to replace.")
            else:
                self._set_find_replace_status("no matches.")
            return
        if not self._confirm_replace_all(occurrences, len(changes)):
            self._set_find_replace_status("cancelled.")
            return
        self._undo_stack.push(UndoReplaceTextCommand(self, changes))
        self._find_replace_cursor = None
        occ = "occurrence" if occurrences == 1 else "occurrences"
        cell = "cell" if len(changes) == 1 else "cells"
        self._set_find_replace_status(f"replaced {occurrences:,} {occ} in {len(changes):,} {cell}.")

    def _reset_find_replace_panel(self) -> None:
        """Clear the bar and hide it (session New / Open)."""
        bar = getattr(self, "_find_replace_bar", None)
        panel = getattr(self, "_find_replace_panel", None)
        if bar is not None:
            bar.find_edit.clear()
            bar.replace_edit.clear()
            bar.case_cb.setChecked(False)
            bar.whole_cb.setChecked(False)
            visible = bar.scope_combo.findData("visible")
            if visible >= 0:
                bar.scope_combo.setCurrentIndex(visible)
        self._populate_find_replace_columns(prefer_all=True)
        if panel is not None:
            panel.setVisible(False)
        self._find_replace_cursor = None
        self._find_replace_query_key_seen = None
        self._session_find_replace_want_visible = False

    def collect_find_replace_session(self) -> dict | None:
        """Serialize the bar when it is open or either field has text."""
        bar = getattr(self, "_find_replace_bar", None)
        panel = getattr(self, "_find_replace_panel", None)
        if bar is None or panel is None:
            return None
        visible = not panel.isHidden()
        find = str(bar.find_edit.text() or "")
        replacement = str(bar.replace_edit.text() or "")
        if not visible and not find and not replacement:
            return None
        data = bar.column_combo.currentData()
        header = ""
        if isinstance(data, int) and 0 <= data < len(self.headers):
            header = str(self.headers[data])
        scope = bar.scope_combo.currentData()
        if scope not in _FIND_REPLACE_SCOPES:
            scope = "visible"
        return {
            "visible": visible,
            "find": find,
            "replace": replacement,
            "column": header,
            "scope": scope,
            "case_sensitive": bool(bar.case_cb.isChecked()),
            "whole_cell": bool(bar.whole_cb.isChecked()),
        }

    def restore_find_replace_session(self, payload: object | None) -> None:
        """Rebuild the bar from a session document and keep it hidden until reveal."""
        self._reset_find_replace_panel()
        if not isinstance(payload, dict):
            return
        bar = getattr(self, "_find_replace_bar", None)
        panel = getattr(self, "_find_replace_panel", None)
        if bar is None or panel is None:
            return
        header = str(payload.get("column") or "")
        self._populate_find_replace_columns(preferred_header=header or None)
        bar.find_edit.setText(str(payload.get("find") or ""))
        bar.replace_edit.setText(str(payload.get("replace") or ""))
        bar.case_cb.setChecked(bool(payload.get("case_sensitive", False)))
        bar.whole_cb.setChecked(bool(payload.get("whole_cell", False)))
        scope = payload.get("scope")
        if scope in _FIND_REPLACE_SCOPES:
            idx = bar.scope_combo.findData(scope)
            if idx >= 0:
                bar.scope_combo.setCurrentIndex(idx)
        self._session_find_replace_want_visible = bool(payload.get("visible", False))
        panel.setVisible(False)
        self._find_replace_cursor = None
        self._find_replace_query_key_seen = None
