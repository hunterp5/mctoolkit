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

"""Shared output-option widgets for conformation dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True)
class ConformerOutputOptions:
    """Optional destinations for generated conformers beyond the ``confs`` column."""

    add_to_table: bool = False
    save_to_file: bool = False
    save_path: str | None = None


def conformer_options_group(*checkboxes: QWidget) -> QGroupBox:
    """Checkbox cluster used by Generate Conformations dialogs."""
    gb = QGroupBox("Options")
    layout = QVBoxLayout(gb)
    layout.setContentsMargins(8, 6, 8, 6)
    layout.setSpacing(4)
    for widget in checkboxes:
        if widget is not None:
            layout.addWidget(widget)
    return gb


def add_centered_run_button(parent_layout) -> QPushButton:
    """Centered padded Run button, matching dimensionality reduction and clustering."""
    row = QHBoxLayout()
    row.setContentsMargins(0, 10, 0, 6)
    row.addStretch()
    button = QPushButton("Run")
    button.setMinimumWidth(160)
    button.setStyleSheet("QPushButton { padding: 8px 28px; }")
    row.addWidget(button)
    row.addStretch()
    parent_layout.addLayout(row)
    return button


class ConformerOutputOptionsPanel(QWidget):
    """Add-as-entries checkbox plus a one-line Save to SDF path picker."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.add_to_table_cb = QCheckBox("Add as Entries")
        self.add_to_table_cb.setToolTip(
            "Append each generated conformer as a new table row (Parent OID and Conformer columns)."
        )

        self.save_to_file_cb = QCheckBox("Save to SDF")
        self.save_to_file_cb.setToolTip("Write all generated conformers to an SDF file.")
        self.save_to_file_cb.toggled.connect(self._sync_save_path_enabled)
        layout.addWidget(self.save_to_file_cb)

        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText("conformers.sdf")
        self.save_path_edit.setEnabled(False)
        layout.addWidget(self.save_path_edit, 1)
        self.save_browse_btn = QPushButton("Browse…")
        self.save_browse_btn.setEnabled(False)
        self.save_browse_btn.clicked.connect(self._browse_save_path)
        layout.addWidget(self.save_browse_btn)

    def _sync_save_path_enabled(self, enabled: bool) -> None:
        self.save_path_edit.setEnabled(bool(enabled))
        self.save_browse_btn.setEnabled(bool(enabled))

    def _browse_save_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save conformations",
            self.save_path_edit.text() or "conformers.sdf",
            "SDF (*.sdf);;All files (*.*)",
        )
        if path:
            if not path.lower().endswith(".sdf"):
                path = f"{path}.sdf"
            self.save_path_edit.setText(path)

    def options(self) -> ConformerOutputOptions:
        save = bool(self.save_to_file_cb.isChecked())
        path = (self.save_path_edit.text() or "").strip() or None
        return ConformerOutputOptions(
            add_to_table=bool(self.add_to_table_cb.isChecked()),
            save_to_file=save,
            save_path=path if save else None,
        )

    def validate(self, dialog: QDialog) -> bool:
        opts = self.options()
        if opts.save_to_file and not opts.save_path:
            QMessageBox.warning(dialog, dialog.windowTitle(), "Choose an output SDF file path.")
            return False
        return True
