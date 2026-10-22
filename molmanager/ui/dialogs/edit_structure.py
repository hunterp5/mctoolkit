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

"""Compact dialog for replacing one row's structure text."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

_DIALOG_WIDTH = 360
_MOL_BLOCK_LINES = 5


class EditStructureDialog(QDialog):
    """SMILES or InChI on one line; a mol block in a short scrolling editor."""

    def __init__(self, parent: QWidget | None = None, text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Structure")
        self.setModal(True)
        current = text or ""
        multiline = "\n" in current

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(6)
        layout.addWidget(QLabel("SMILES, InChI, or mol block"))

        if multiline:
            editor = QPlainTextEdit(self)
            editor.setLineWrapMode(QPlainTextEdit.NoWrap)
            editor.setPlainText(current)
            editor.setFixedHeight(self._mol_block_height(editor))
            self._editor: QLineEdit | QPlainTextEdit = editor
        else:
            editor = QLineEdit(self)
            editor.setText(current)
            editor.selectAll()
            self._editor = editor
        layout.addWidget(self._editor)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        ok = buttons.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setDefault(True)
        layout.addWidget(buttons)

        self.setFixedWidth(_DIALOG_WIDTH)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

    def text(self) -> str:
        editor = self._editor
        if isinstance(editor, QPlainTextEdit):
            return editor.toPlainText()
        return editor.text()

    @staticmethod
    def _mol_block_height(editor: QPlainTextEdit) -> int:
        metrics = editor.fontMetrics()
        frame = editor.frameWidth() * 2
        return metrics.lineSpacing() * _MOL_BLOCK_LINES + frame + 8


def ask_edit_structure_text(parent: QWidget | None, current: str) -> tuple[str, bool]:
    """Return ``(text, accepted)``. Cancel yields the field's text and ``False``."""
    dialog = EditStructureDialog(parent, current)
    accepted = dialog.exec_() == QDialog.Accepted
    return dialog.text(), accepted
