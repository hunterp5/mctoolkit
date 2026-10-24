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

"""Chemistry → Neutralize."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class NeutralizeDialog(QDialog):
    """Neutralize structures in a chosen column (net formal charge → 0)."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Neutralize")
        self.setMinimumWidth(420)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        form = QFormLayout(structures)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        form.addRow("Target column:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        root.addWidget(structures)

        options = QGroupBox("Options")
        opt_lyt = QVBoxLayout(options)
        opt_lyt.setContentsMargins(8, 6, 8, 6)
        opt_lyt.setSpacing(4)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        self.no_render_2d_cb.setToolTip("Skip redrawing 2D images after neutralization.")
        opt_lyt.addWidget(self.no_render_2d_cb)
        root.addWidget(options)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self.adjustSize()
        make_window_minimizable(self)

    def config(self) -> tuple[str, bool, bool]:
        """Returns ``(target_column, only_selected_rows, no_render_2d)``."""
        return (
            self.src_combo.currentText(),
            selection_scope_checked(self),
            self.no_render_2d_cb.isChecked(),
        )
