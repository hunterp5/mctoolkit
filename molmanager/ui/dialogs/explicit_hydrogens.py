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

"""Chemistry → Prepare Structures → Explicit Hydrogens (Add / Remove)."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_ADD_EXPLICIT_HYDROGENS, TOOL_REMOVE_EXPLICIT_HYDROGENS
from .scope import selection_scope_checked


class AddExplicitHydrogensDialog(QDialog):
    """Add explicit hydrogen atoms to structures in a chosen column."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_ADD_EXPLICIT_HYDROGENS)
        self.resize(420, 140)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        f = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        f.addRow("Target column:", self.src_combo)
        root.addLayout(f)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after adding hydrogens.")
        root.addWidget(self.no_render_2d_cb)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )


class RemoveExplicitHydrogensDialog(QDialog):
    """Remove explicit hydrogen atoms from structures in a chosen column."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_REMOVE_EXPLICIT_HYDROGENS)
        self.resize(420, 140)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        f = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        f.addRow("Target column:", self.src_combo)
        root.addLayout(f)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after removing hydrogens.")
        root.addWidget(self.no_render_2d_cb)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )
