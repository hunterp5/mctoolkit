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
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class ProtonateDialog(QDialog):
    """Configure dominant-protomer generation into a new column."""

    def __init__(self, source_labels: list[str], selected_row_count: int, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Protonate")
        self.setMinimumWidth(420)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_form = QFormLayout(structures)
        struct_form.setContentsMargins(8, 6, 8, 6)
        struct_form.setSpacing(4)
        struct_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.src_combo = QComboBox()
        self.src_combo.addItems(list(source_labels))
        struct_form.addRow("Structure source:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        struct_form.addRow("", self.only_selected_cb)
        root.addWidget(structures)

        protonation = QGroupBox("Protonation")
        ph_form = QFormLayout(protonation)
        ph_form.setContentsMargins(8, 6, 8, 6)
        ph_form.setSpacing(4)
        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0.0, 14.0)
        self.ph_spin.setDecimals(2)
        self.ph_spin.setSingleStep(0.1)
        self.ph_spin.setValue(7.40)
        self.ph_spin.setToolTip("Target pH for dominant protomer selection (approximate).")
        ph_form.addRow("pH:", self.ph_spin)
        root.addWidget(protonation)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.output_col = QLineEdit("Protonated")
        self.output_col.setPlaceholderText("New column name")
        out_form.addRow("Output column:", self.output_col)
        self.render_cb = QCheckBox("Render 2D in output column")
        self.render_cb.setChecked(True)
        self.render_cb.setToolTip(
            "Show 2D depictions in the output column (same display style as Structure). "
            "SMILES remain stored in the cell but are not shown as text."
        )
        out_form.addRow("", self.render_cb)
        root.addWidget(output)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.accept)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.adjustSize()
        make_window_minimizable(self)

    def config(self) -> tuple[str, float, str, bool, bool]:
        src = self.src_combo.currentText()
        ph = float(self.ph_spin.value())
        col = (self.output_col.text() or "").strip() or "Protonated"
        only_selected = selection_scope_checked(self)
        render_2d = bool(self.render_cb.isChecked())
        return src, ph, col, only_selected, render_2d
