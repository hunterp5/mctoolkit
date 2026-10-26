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

"""Choose a primary assay and off-target columns (Data → Selectivity Ratio)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ...analysis.selectivity_ratio import SelectivityRatioParams, looks_like_assay_column
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_SELECTIVITY_RATIO
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked


class SelectivityRatioDialog(QDialog):
    """Primary pActivity, one or more off-target columns, and the narrow window."""

    def __init__(self, columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_SELECTIVITY_RATIO)
        self.setMinimumWidth(460)
        self.resize(520, 460)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        assays = QGroupBox("Assays")
        form = QFormLayout(assays)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.primary_combo = QComboBox()
        self.primary_combo.addItems(columns)
        self.primary_combo.setToolTip(
            "On-target column on a p-scale (pIC50, pKi). Higher means more potent."
        )
        select_preferred_activity_column(self.primary_combo)
        form.addRow("Primary:", self.primary_combo)

        self.secondary_list = QListWidget()
        self.secondary_list.setToolTip(
            "Off-target columns on the same p-scale. "
            "Log selectivity is primary minus each of these."
        )
        self.secondary_list.setMinimumHeight(140)
        for name in columns:
            item = QListWidgetItem(name)
            item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
            item.setCheckState(Qt.Unchecked)
            self.secondary_list.addItem(item)
        self.secondary_list.itemChanged.connect(lambda _item: self._sync_ok())
        form.addRow("Off-target:", self.secondary_list)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        root.addWidget(assays)

        window = QGroupBox("Narrow window")
        window_form = QFormLayout(window)
        window_form.setContentsMargins(8, 6, 8, 6)
        window_form.setSpacing(4)
        window_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.potency_spin = QDoubleSpinBox()
        self.potency_spin.setDecimals(2)
        self.potency_spin.setRange(-5.0, 15.0)
        self.potency_spin.setSingleStep(0.1)
        self.potency_spin.setValue(6.0)
        self.potency_spin.setToolTip(
            "Primary pActivity at or above this counts as potent. "
            "6 is about 1 µM when the column is pIC50 in molar units."
        )
        window_form.addRow("Potent at:", self.potency_spin)

        self.window_spin = QDoubleSpinBox()
        self.window_spin.setDecimals(2)
        self.window_spin.setRange(0.0, 6.0)
        self.window_spin.setSingleStep(0.1)
        self.window_spin.setValue(1.0)
        self.window_spin.setToolTip(
            "Flag a potent row when its smallest log selectivity is below this. 1 is 10-fold."
        )
        window_form.addRow("Window below:", self.window_spin)
        root.addWidget(window)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

        self._check_default_secondaries()
        self._sync_primary()
        self.primary_combo.currentTextChanged.connect(self._sync_primary)
        make_window_minimizable(self)

    def _check_default_secondaries(self) -> None:
        primary = self.primary_combo.currentText()
        for index in range(self.secondary_list.count()):
            item = self.secondary_list.item(index)
            if item.text() == primary or not looks_like_assay_column(item.text()):
                continue
            item.setCheckState(Qt.Checked)

    def _sync_primary(self) -> None:
        primary = self.primary_combo.currentText()
        self.secondary_list.blockSignals(True)
        try:
            for index in range(self.secondary_list.count()):
                item = self.secondary_list.item(index)
                enabled = item.text() != primary
                if not enabled:
                    item.setCheckState(Qt.Unchecked)
                    item.setFlags(item.flags() & ~Qt.ItemIsEnabled)
                else:
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable | Qt.ItemIsSelectable)
        finally:
            self.secondary_list.blockSignals(False)
        self._sync_ok()

    def _checked_secondaries(self) -> list[str]:
        primary = self.primary_combo.currentText()
        names: list[str] = []
        for index in range(self.secondary_list.count()):
            item = self.secondary_list.item(index)
            if item.text() == primary:
                continue
            if item.checkState() == Qt.Checked:
                names.append(item.text())
        return names

    def _sync_ok(self) -> None:
        button = self._buttons.button(QDialogButtonBox.Ok)
        if button is not None:
            button.setEnabled(bool(self._checked_secondaries()))

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SelectivityRatioParams:
        secondaries = tuple(self._checked_secondaries())
        if not secondaries:
            raise ValueError("Choose at least one off-target column.")
        primary = self.primary_combo.currentText().strip()
        if not primary or primary in secondaries:
            raise ValueError("Choose a primary assay that is not also an off-target.")
        return SelectivityRatioParams(
            primary_column=primary,
            secondary_columns=secondaries,
            potency_cutoff=float(self.potency_spin.value()),
            window=float(self.window_spin.value()),
        )
