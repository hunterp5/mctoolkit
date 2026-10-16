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

"""Dialogs for naming a row list and deleting existing lists."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ..row_lists import MAX_LIST_NAME_LENGTH, normalize_list_name


class AddSelectedToListDialog(QDialog):
    """Name a new list, or pick an existing name to add the selection into."""

    def __init__(self, parent=None, *, existing_names: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Selected to List")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._name = ""

        root = QVBoxLayout(self)
        hint = QLabel("Name the list. An existing name adds the selection to that list.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.name_combo = QComboBox()
        self.name_combo.setEditable(True)
        self.name_combo.setInsertPolicy(QComboBox.NoInsert)
        for name in existing_names or []:
            self.name_combo.addItem(name)
        self.name_combo.setCurrentText("")
        edit = self.name_combo.lineEdit()
        if edit is not None:
            edit.setPlaceholderText("List name")
            edit.setMaxLength(MAX_LIST_NAME_LENGTH)
        form.addRow("Name:", self.name_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        buttons.accepted.connect(self._accept_name)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        if edit is not None:
            edit.textChanged.connect(self._sync_ok_enabled)
            edit.setFocus(Qt.OtherFocusReason)
        self._sync_ok_enabled()

    def list_name(self) -> str:
        return self._name

    def _sync_ok_enabled(self, *_args) -> None:
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(bool(normalize_list_name(self.name_combo.currentText())))

    def _accept_name(self) -> None:
        name = normalize_list_name(self.name_combo.currentText())
        if not name:
            return
        self._name = name
        self.accept()


class ManageListsDialog(QDialog):
    """Delete named lists. Changes apply when the dialog is accepted."""

    def __init__(self, parent=None, *, entries: list[tuple[str, int]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Lists")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setMinimumHeight(280)

        root = QVBoxLayout(self)
        hint = QLabel("Select lists to delete.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.setMinimumHeight(140)
        for name, count in entries or []:
            noun = "row" if count == 1 else "rows"
            item = QListWidgetItem(f"{name} ({count} {noun})")
            item.setData(Qt.UserRole, name)
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(lambda _item: self._delete_selected())
        root.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._delete_btn = buttons.addButton("Delete", QDialogButtonBox.ActionRole)
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._list.itemSelectionChanged.connect(self._sync_delete_enabled)
        self._sync_delete_enabled()

    def remaining_names(self) -> list[str]:
        names: list[str] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is None:
                continue
            name = item.data(Qt.UserRole)
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def _delete_selected(self) -> None:
        for item in list(self._list.selectedItems()):
            row = self._list.row(item)
            if row >= 0:
                self._list.takeItem(row)
        self._sync_delete_enabled()

    def _sync_delete_enabled(self) -> None:
        self._delete_btn.setEnabled(bool(self._list.selectedItems()))
