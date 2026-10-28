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

"""Text / regex filter card."""

from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QFrame,
    QLineEdit,
    QSizePolicy,
)

from .card_chrome import (
    _FC_TOOL_BTN_MIN_W,
    _FILTER_CARD_MIN_HEIGHT_TEXT,
    _FilterCardDragMixin,
    _FilterCardEnableInvertMixin,
    _fc_card_layout,
    _fc_configure_column_combo,
    _fc_install_card_shell,
    _fc_set_toggle_active,
    _fc_toolbar_button,
)


class TextFilterCard(_FilterCardDragMixin, _FilterCardEnableInvertMixin, QFrame):
    """Filter rows by text in a chosen column (partial or exact, case optional)."""

    changed = pyqtSignal()
    removed = pyqtSignal(object)

    def __init__(self, columns: list[str], app):
        super().__init__()
        self.app = app
        self._case_sensitive = False
        self._partial_match = True
        _fc_install_card_shell(self, _FILTER_CARD_MIN_HEIGHT_TEXT)
        l = _fc_card_layout(self)
        self._fc_add_title_row(l, "Text")
        self.cb = QComboBox()
        _fc_configure_column_combo(self.cb)
        self.cb.addItems(columns)
        self.cb.currentTextChanged.connect(lambda _t: self.changed.emit())
        self._fc_init_enable_invert(
            "Invert matching rows.",
            toolbar_min_width=_FC_TOOL_BTN_MIN_W,
        )
        self.partial_btn = _fc_toolbar_button("Partial")
        self.partial_btn.setToolTip("Substring vs exact cell match.")
        self.partial_btn.clicked.connect(self._on_partial_clicked)
        self._sync_partial_button_appearance()
        self.case_btn = _fc_toolbar_button("Ignore Case", wide=True)
        self.case_btn.setToolTip("Case-sensitive vs ignore case.")
        self.case_btn.clicked.connect(self._on_case_clicked)
        self._sync_case_button_appearance()
        self._fc_add_header_toolbar(
            l,
            extra_buttons=[self.partial_btn, self.case_btn],
        )
        l.addWidget(self.cb)
        self.text_edit = QLineEdit()
        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.text_edit.setMinimumWidth(0)
        self._sync_match_placeholder()
        self._text_filter_timer = QTimer(self)
        self._text_filter_timer.setSingleShot(True)
        self._text_filter_timer.timeout.connect(self.changed.emit)
        self.text_edit.textChanged.connect(self._schedule_text_filter_changed)
        l.addWidget(self.text_edit)

    def _schedule_text_filter_changed(self, _text: str = "") -> None:
        self._text_filter_timer.start(280)

    def _sync_match_placeholder(self) -> None:
        if self._partial_match:
            self.text_edit.setPlaceholderText("Match substring (empty = no filter)")
        else:
            self.text_edit.setPlaceholderText("Match full cell (empty = no filter)")

    def _sync_case_button_appearance(self) -> None:
        if self._case_sensitive:
            self.case_btn.setText("Case")
        else:
            self.case_btn.setText("Ignore Case")
        _fc_set_toggle_active(self.case_btn, self._case_sensitive)

    def _on_case_clicked(self) -> None:
        self._case_sensitive = not self._case_sensitive
        self._sync_case_button_appearance()
        self.changed.emit()

    def _sync_partial_button_appearance(self) -> None:
        if self._partial_match:
            self.partial_btn.setText("Partial")
        else:
            self.partial_btn.setText("Exact")
        _fc_set_toggle_active(self.partial_btn, self._partial_match)

    def _on_partial_clicked(self) -> None:
        self._partial_match = not self._partial_match
        self._sync_partial_button_appearance()
        self._sync_match_placeholder()
        self.changed.emit()

    def set_column(self, name: str) -> None:
        if name and self.cb.findText(name) >= 0:
            self.cb.setCurrentText(name)

    def update_prop_list(self, new_props, old_n=None, new_n=None):
        self.cb.blockSignals(True)
        current = self.cb.currentText()
        self.cb.clear()
        self.cb.addItems(new_props)
        if old_n and current == old_n:
            if new_n:
                self.cb.setCurrentText(new_n)
                self.cb.blockSignals(False)
                self.changed.emit()
                return False
            self.cb.blockSignals(False)
            return True
        if current and self.cb.findText(current) >= 0:
            self.cb.setCurrentText(current)
        elif self.cb.count():
            self.cb.setCurrentIndex(0)
        self.cb.blockSignals(False)
        return False

    def row_matches(self, row: int) -> bool:
        prop = self.cb.currentText()
        if not prop:
            return True
        needle = (self.text_edit.text() or "").strip()
        if not needle:
            return True
        raw = self.app._table_model.value_for_header(row, prop) or ""
        if not str(raw).strip():
            return False
        if self._partial_match:
            if self._case_sensitive:
                inside = needle in raw
            else:
                inside = needle.lower() in raw.lower()
        else:
            if self._case_sensitive:
                inside = raw == needle
            else:
                inside = raw.lower() == needle.lower()
        return not inside if self._invert_on else inside

    def get_cfg(self):
        return {
            "column": self.cb.currentText(),
            "text": self.text_edit.text() or "",
            "enabled": self._filter_enabled_on,
            "inverted": self._invert_on,
            "case_sensitive": self._case_sensitive,
            "partial_match": self._partial_match,
        }

    def restore_from_session(
        self,
        prop: str,
        text: str,
        *,
        case_sensitive: bool = False,
        partial_match: bool = True,
    ) -> None:
        self.cb.blockSignals(True)
        if prop and self.cb.findText(prop) >= 0:
            self.cb.setCurrentText(prop)
        self.cb.blockSignals(False)
        self.text_edit.blockSignals(True)
        self.text_edit.setText(text or "")
        self.text_edit.blockSignals(False)
        self._case_sensitive = bool(case_sensitive)
        self._partial_match = bool(partial_match)
        self._sync_case_button_appearance()
        self._sync_partial_button_appearance()
        self._sync_match_placeholder()
