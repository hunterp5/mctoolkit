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

"""Dialogs for adding or removing rows in a named list, and for renaming or deleting lists."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QVBoxLayout,
)

from ..row_lists import MAX_LIST_NAME_LENGTH, normalize_list_name

_ORIGINAL_ROLE = Qt.UserRole
_NAME_ROLE = Qt.UserRole + 1
_COUNT_ROLE = Qt.UserRole + 2


def _list_row_label(name: str, count: int) -> str:
    noun = "row" if count == 1 else "rows"
    return f"{name} ({count} {noun})"


class AddSelectedToListDialog(QDialog):
    """Name a new list, or pick an existing name to add the selection into."""

    def __init__(self, parent=None, *, existing_names: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Add Selected to List")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._name = ""
        self._existing = [name for name in (existing_names or []) if name]

        root = QVBoxLayout(self)
        if self._existing:
            hint_text = "Choose an existing list to add the selection to it, or type a new name."
        else:
            hint_text = "Name the list for the selected rows."
        hint = QLabel(hint_text)
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.name_combo = QComboBox()
        self.name_combo.setEditable(True)
        self.name_combo.setInsertPolicy(QComboBox.NoInsert)
        for name in self._existing:
            self.name_combo.addItem(name)
        # addItem leaves the first name selected. Clear it so the field starts empty.
        self.name_combo.setCurrentIndex(-1)
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
        completer = self.name_combo.completer()
        if completer is not None:
            completer.setCaseSensitivity(Qt.CaseInsensitive)
        self.name_combo.activated[int].connect(self._use_existing_item)
        if edit is not None:
            edit.textChanged.connect(self._sync_ok_enabled)
            edit.setFocus(Qt.OtherFocusReason)
        self._sync_ok_enabled()

    def list_name(self) -> str:
        return self._name

    def _use_existing_item(self, index: int) -> None:
        """Copy a dropdown choice into the editor so it is the name that gets saved."""
        if index < 0:
            return
        name = self.name_combo.itemText(index)
        edit = self.name_combo.lineEdit()
        if edit is not None and edit.text() != name:
            edit.setText(name)
        self._sync_ok_enabled()

    def _match_existing(self, name: str) -> str:
        """Use the stored spelling when *name* is an existing list, ignoring case."""
        if name in self._existing:
            return name
        folded = name.casefold()
        matches = [existing for existing in self._existing if existing.casefold() == folded]
        if len(matches) == 1:
            return matches[0]
        return name

    def _sync_ok_enabled(self, *_args) -> None:
        if self._ok_btn is not None:
            edit = self.name_combo.lineEdit()
            raw = edit.text() if edit is not None else self.name_combo.currentText()
            self._ok_btn.setEnabled(bool(normalize_list_name(raw)))

    def _accept_name(self) -> None:
        edit = self.name_combo.lineEdit()
        raw = edit.text() if edit is not None else self.name_combo.currentText()
        name = self._match_existing(normalize_list_name(raw))
        if not name:
            return
        self._name = name
        self.accept()


class RemoveSelectedFromListDialog(QDialog):
    """Pick an existing list to remove the current selection from."""

    def __init__(self, parent=None, *, existing_names: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Remove Selected from List")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._name = ""
        self._existing = [name for name in (existing_names or []) if name]

        root = QVBoxLayout(self)
        hint = QLabel("Choose the list to remove the selected rows from. Rows stay in the table.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        self.name_combo = QComboBox()
        self.name_combo.setEditable(False)
        for name in self._existing:
            self.name_combo.addItem(name)
        # A single list is the obvious target. Several lists wait for an explicit choice.
        self.name_combo.setCurrentIndex(0 if len(self._existing) == 1 else -1)
        form.addRow("List:", self.name_combo)
        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = buttons.button(QDialogButtonBox.Ok)
        buttons.accepted.connect(self._accept_name)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self.name_combo.currentIndexChanged.connect(self._sync_ok_enabled)
        self._sync_ok_enabled()

    def list_name(self) -> str:
        return self._name

    def _sync_ok_enabled(self, *_args) -> None:
        if self._ok_btn is not None:
            self._ok_btn.setEnabled(self.name_combo.currentIndex() >= 0)

    def _accept_name(self) -> None:
        index = self.name_combo.currentIndex()
        if index < 0:
            return
        name = self.name_combo.itemText(index)
        if not name:
            return
        self._name = name
        self.accept()


class ManageListsDialog(QDialog):
    """Rename or delete named lists. Changes apply when the dialog is accepted."""

    def __init__(self, parent=None, *, entries: list[tuple[str, int]] | None = None):
        super().__init__(parent)
        self.setWindowTitle("Manage Lists")
        self.setModal(True)
        self.setMinimumWidth(360)
        self.setMinimumHeight(280)

        root = QVBoxLayout(self)
        hint = QLabel("Rename or delete lists. Click OK to apply the changes.")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.setMinimumHeight(140)
        for name, count in entries or []:
            item = QListWidgetItem(_list_row_label(name, count))
            item.setData(_ORIGINAL_ROLE, name)
            item.setData(_NAME_ROLE, name)
            item.setData(_COUNT_ROLE, int(count))
            self._list.addItem(item)
        self._list.itemDoubleClicked.connect(self._rename_from_item)
        root.addWidget(self._list)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._rename_btn = buttons.addButton("Rename", QDialogButtonBox.ActionRole)
        self._rename_btn.setToolTip("Rename the selected list.")
        self._rename_btn.clicked.connect(self._rename_selected)
        self._delete_btn = buttons.addButton("Delete", QDialogButtonBox.ActionRole)
        self._delete_btn.setToolTip("Delete the selected lists. The table rows are kept.")
        self._delete_btn.clicked.connect(self._delete_selected)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        self._list.itemSelectionChanged.connect(self._sync_action_buttons)
        self._sync_action_buttons()

    def kept_lists(self) -> list[tuple[str, str]]:
        """Lists still shown, as ``(original_name, current_name)`` in display order."""
        pairs: list[tuple[str, str]] = []
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item is None:
                continue
            original = item.data(_ORIGINAL_ROLE)
            current = item.data(_NAME_ROLE)
            if isinstance(original, str) and original and isinstance(current, str) and current:
                pairs.append((original, current))
        return pairs

    def remaining_names(self) -> list[str]:
        return [current for _original, current in self.kept_lists()]

    def _rename_from_item(self, item: QListWidgetItem) -> None:
        self._list.setCurrentItem(item)
        self._rename_item(item)

    def _rename_selected(self) -> None:
        items = self._list.selectedItems()
        if len(items) != 1:
            return
        self._rename_item(items[0])

    def _rename_item(self, item: QListWidgetItem) -> None:
        current = item.data(_NAME_ROLE)
        if not isinstance(current, str) or not current:
            return
        text, ok = QInputDialog.getText(self, "Rename List", "Name:", text=current)
        if not ok:
            return
        name = normalize_list_name(text)
        if not name or name == current:
            return
        if self._name_taken(name, item):
            QMessageBox.warning(
                self,
                "Rename List",
                f'A list named "{name}" already exists.',
            )
            return
        count = item.data(_COUNT_ROLE)
        item.setData(_NAME_ROLE, name)
        item.setText(_list_row_label(name, int(count) if isinstance(count, int) else 0))

    def _name_taken(self, name: str, except_item: QListWidgetItem) -> bool:
        folded = name.casefold()
        for row in range(self._list.count()):
            other = self._list.item(row)
            if other is None or other is except_item:
                continue
            current = other.data(_NAME_ROLE)
            if isinstance(current, str) and current.casefold() == folded:
                return True
        return False

    def _delete_selected(self) -> None:
        items = [item for item in self._list.selectedItems() if item is not None]
        if not items or not self._confirm_delete(items):
            return
        for item in items:
            row = self._list.row(item)
            if row >= 0:
                self._list.takeItem(row)
        self._sync_action_buttons()

    def _confirm_delete(self, items: list[QListWidgetItem]) -> bool:
        if len(items) == 1:
            name = items[0].data(_NAME_ROLE)
            title = "Delete List"
            label = f'"{name}"' if isinstance(name, str) and name else "this list"
            message = f"Delete list {label}?"
        else:
            title = "Delete Lists"
            message = f"Delete {len(items)} lists?"
        message += "\n\nRows in the table are kept."
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _sync_action_buttons(self) -> None:
        selected = self._list.selectedItems()
        self._rename_btn.setEnabled(len(selected) == 1)
        self._delete_btn.setEnabled(bool(selected))
