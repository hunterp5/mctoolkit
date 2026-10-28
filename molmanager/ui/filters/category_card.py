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

"""Categorical value filter card."""

from PyQt5.QtCore import QTimer, Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QSizePolicy,
)

from .card_chrome import (
    _FC_LIST_MAX,
    _FC_TOOL_BTN_MIN_W,
    _FILTER_CARD_MIN_HEIGHT_CATEGORY,
    _FilterCardDragMixin,
    _FilterCardEnableInvertMixin,
    _fc_card_layout,
    _fc_configure_column_combo,
    _fc_install_card_shell,
    _fc_toolbar_button,
)


class CategoryFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    """Filter rows by membership in selected distinct values of a column."""

    changed = pyqtSignal()
    removed = pyqtSignal(object)
    _BLANK = "\u0000blank\u0000"

    def __init__(self, columns: list[str], app):
        super().__init__()
        self.app = app
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_CATEGORY)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Category")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(columns)
        self.cb.currentTextChanged.connect(self._on_column_changed)
        self._fc_init_enable_invert(
            "Invert category selection.",
            toolbar_min_width=_FC_TOOL_BTN_MIN_W,
        )
        self.all_btn = _fc_toolbar_button("All")
        self.all_btn.setToolTip("Check every category in the list.")
        self.all_btn.clicked.connect(self._select_all_categories)
        self.none_btn = _fc_toolbar_button("None")
        self.none_btn.setToolTip("Uncheck every category in the list.")
        self.none_btn.clicked.connect(self._select_no_categories)
        self._fc_add_header_toolbar(
            l,
            extra_buttons=[self.all_btn, self.none_btn],
        )
        l.addWidget(self.cb)
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(QAbstractItemView.NoSelection)
        self.list_widget.setMaximumHeight(_FC_LIST_MAX)
        self.list_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.list_widget.setMinimumWidth(0)
        # Cached for ``row_matches`` during a single ``apply_filters`` pass (avoid O(rows × list) work).
        self._category_checked_cache: frozenset[str] | None = None
        self._category_n_checkable_cache: int | None = None
        self.list_widget.itemChanged.connect(self._on_category_list_item_changed)
        l.addWidget(self.list_widget)
        self._populate_list()

    def _bust_category_selection_cache(self) -> None:
        self._category_checked_cache = None
        self._category_n_checkable_cache = None

    def _on_category_list_item_changed(self, _it) -> None:
        self._bust_category_selection_cache()
        self.changed.emit()

    def _set_all_category_checkstates(self, state) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                it.setCheckState(state)
        self.list_widget.blockSignals(False)
        self._bust_category_selection_cache()
        self.changed.emit()

    def _select_all_categories(self) -> None:
        self._set_all_category_checkstates(Qt.Checked)

    def _select_no_categories(self) -> None:
        self._set_all_category_checkstates(Qt.Unchecked)

    def _ensure_category_filter_cache(self) -> None:
        if self._category_checked_cache is not None:
            return
        out: list[str] = []
        n_checkable = 0
        for i in range(self.list_widget.count()):
            it = self.list_widget.item(i)
            if it.flags() & Qt.ItemIsUserCheckable:
                n_checkable += 1
                if it.checkState() == Qt.Checked:
                    out.append(self._role_value(it))
        self._category_checked_cache = frozenset(out)
        self._category_n_checkable_cache = n_checkable

    def _on_column_changed(self, _t: str) -> None:
        QTimer.singleShot(0, lambda: self._populate_list())

    def set_column(self, name: str) -> None:
        if name and self.cb.findText(name) >= 0:
            self.cb.blockSignals(True)
            self.cb.setCurrentText(name)
            self.cb.blockSignals(False)
            self._populate_list()

    def column_name(self) -> str:
        return (self.cb.currentText() or "").strip()

    def checked_values(self) -> frozenset[str]:
        self._ensure_category_filter_cache()
        return self._category_checked_cache or frozenset()

    def _role_value(self, item: QListWidgetItem) -> str:
        d = item.data(Qt.UserRole)
        if d == self._BLANK:
            return ""
        return str(d) if d is not None else (item.text() or "")

    def _populate_list(self, select_values: frozenset[str] | None = None) -> None:
        self._bust_category_selection_cache()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        prop = self.cb.currentText()
        if not prop or prop not in self.app.headers:
            self.list_widget.blockSignals(False)
            self.changed.emit()
            return
        ordered: list[str] = []
        cap = 2000
        ensure_sqlite = getattr(self.app, "_ensure_sqlite_store_current", None)
        store = getattr(self.app, "_sqlite_store", None)
        sqlite_ready = True
        if callable(ensure_sqlite):
            sqlite_ready = ensure_sqlite()
        if sqlite_ready and store is not None and prop in store.headers:
            ordered = store.distinct_values(prop, limit=cap + 1)
        else:
            seen: set[str] = set()
            for r in range(self.app._table_model.rowCount()):
                v = self.app._table_model.value_for_header(r, prop) or ""
                if v not in seen:
                    seen.add(v)
                    ordered.append(v)
            ordered.sort(key=lambda x: x.lower())
        ordered = [v for v in ordered if str(v).strip()]
        truncated = len(ordered) > cap
        for v in ordered[:cap]:
            label = "(blank)" if v == "" else v
            it = QListWidgetItem(label)
            it.setData(Qt.UserRole, self._BLANK if v == "" else v)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            want = select_values
            if want is None:
                it.setCheckState(Qt.Checked)
            else:
                it.setCheckState(Qt.Checked if v in want else Qt.Unchecked)
            self.list_widget.addItem(it)
        self.list_widget.blockSignals(False)
        if truncated:
            tip = QListWidgetItem(f"… ({len(ordered)} distinct; showing first {cap})")
            tip.setFlags(tip.flags() & ~Qt.ItemIsUserCheckable)
            self.list_widget.addItem(tip)
        self.changed.emit()

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self._populate_list()
                return False
            self.cb.blockSignals(False)
            return True
        if current and self.cb.findText(current) >= 0:
            self.cb.setCurrentText(current)
        elif self.cb.count():
            self.cb.setCurrentIndex(0)
        self.cb.blockSignals(False)
        self._populate_list()
        return False

    def _checked_values(self) -> frozenset[str]:
        self._ensure_category_filter_cache()
        return self._category_checked_cache or frozenset()

    def row_matches(self, row: int) -> bool:
        self._ensure_category_filter_cache()
        prop = self.cb.currentText()
        if not prop:
            return True
        raw = self.app._table_model.value_for_header(row, prop) or ""
        if not str(raw).strip():
            return False
        n_checkable = int(self._category_n_checkable_cache or 0)
        if n_checkable == 0:
            return True
        sel = self._category_checked_cache or frozenset()
        inside = raw in sel if sel else False
        if self._invert_on:
            return not inside
        return inside

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "values": sorted(self._checked_values()),
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
        }

    def restore_from_session(self, prop: str, values: list[str]) -> None:
        self.cb.blockSignals(True)
        if prop and self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        self.cb.blockSignals(False)
        self._populate_list(frozenset(str(x) for x in (values or [])))
