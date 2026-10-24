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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

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
from ..strings import TOOL_RENDER_2D
from .scope import selection_scope_checked


class Render2DStructureDialog(QDialog):
    """Pick structure source and whether to render only selected table rows."""

    def __init__(self, candidates: list[str], selected_row_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_RENDER_2D)
        self.setMinimumWidth(360)
        self._have_selection = selected_row_count > 0
        ly = QVBoxLayout(self)
        ly.setContentsMargins(10, 10, 10, 8)
        ly.setSpacing(8)
        structures = QGroupBox("Structures")
        form = QFormLayout(structures)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setContentsMargins(8, 6, 8, 6)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        self.src_combo = QComboBox()
        self.src_combo.addItems(candidates)
        form.addRow("Draw from:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count})"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        ly.addWidget(structures)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        ly.addWidget(bb)
        self.adjustSize()
        make_window_minimizable(self)

    def chosen_source(self) -> str:
        return self.src_combo.currentText()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)
