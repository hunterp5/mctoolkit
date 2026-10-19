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

"""Dialog for Tools → Potency Standardization."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from ...chem.potency import CONCENTRATION_UNITS, MEASURES, parse_concentration
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_POTENCY
from .scope import selection_scope_checked

_SOURCE_CONSTANT = "constant"
_SOURCE_COLUMN = "column"


@dataclass(frozen=True)
class PotencyRequest:
    """One apply pass: which column, which unit, and which columns to write."""

    column: str
    unit: str
    measure: str
    write_molar: bool
    write_p: bool
    write_ki: bool
    substrate_unit: str
    km_unit: str
    substrate_constant: float | None
    substrate_column: str | None
    km_constant: float | None
    km_column: str | None


class PotencyStandardizationDialog(QDialog):
    """Convert an activity column to molar and pActivity, optionally to Ki."""

    apply_requested = pyqtSignal()

    def __init__(self, numeric_columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_POTENCY)
        self.resize(520, 560)
        self._have_selection = selected_row_count > 0
        self._columns = list(numeric_columns)
        self.pending_request: PotencyRequest | None = None
        root = QVBoxLayout(self)
        root.setSpacing(10)

        source = QGroupBox("Activity")
        form = QFormLayout(source)
        self.column_combo = QComboBox()
        self.column_combo.addItems(self._columns)
        if not self._columns:
            self.column_combo.addItem("No numeric columns")
            self.column_combo.setEnabled(False)
        form.addRow("Column:", self.column_combo)
        self.unit_combo = _unit_combo("nM")
        form.addRow("Unit:", self.unit_combo)
        self.measure_combo = QComboBox()
        for measure in MEASURES:
            self.measure_combo.addItem(measure, measure)
        self.measure_combo.setToolTip(
            "Names the output columns. Cheng–Prusoff is available for IC50."
        )
        self.measure_combo.currentIndexChanged.connect(self._sync_cheng)
        form.addRow("Measure:", self.measure_combo)
        root.addWidget(source)

        outputs = QGroupBox("Write")
        out_layout = QVBoxLayout(outputs)
        self.chk_molar = QCheckBox("Molar activity")
        self.chk_molar.setChecked(True)
        self.chk_molar.setToolTip("Activity in mol/L, for example IC50 (M).")
        self.chk_p = QCheckBox("pActivity")
        self.chk_p.setChecked(True)
        self.chk_p.setToolTip("−log10 of the molar value, for example pIC50.")
        out_layout.addWidget(self.chk_molar)
        out_layout.addWidget(self.chk_p)
        root.addWidget(outputs)

        self.cheng_box = QGroupBox("Cheng–Prusoff")
        cheng = QVBoxLayout(self.cheng_box)
        self.chk_cheng = QCheckBox("Convert IC50 to Ki")
        self.chk_cheng.setToolTip("Ki = IC50 / (1 + [S]/Km), for competitive inhibition.")
        self.chk_cheng.toggled.connect(self._sync_cheng_fields)
        cheng.addWidget(self.chk_cheng)
        self._cheng_fields = QWidget(self.cheng_box)
        fields = QFormLayout(self._cheng_fields)
        fields.setContentsMargins(0, 0, 0, 0)
        self.substrate_mode, self.substrate_value, self.substrate_column, self.substrate_unit = (
            self._concentration_row(fields, "Substrate [S]:", allow_zero=True)
        )
        self.km_mode, self.km_value, self.km_column, self.km_unit = self._concentration_row(
            fields, "Km:", allow_zero=False
        )
        cheng.addWidget(self._cheng_fields)
        self._cheng_fields.setVisible(False)
        root.addWidget(self.cheng_box)
        self._sync_cheng()

        scope_box = QGroupBox("Scope")
        scope_layout = QVBoxLayout(scope_box)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        scope_layout.addWidget(self.only_selected_cb)
        root.addWidget(scope_box)

        note = QLabel(
            "Values with <, >, or ~ are left blank. Zero and negative activities are left blank."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        apply_btn = buttons.button(QDialogButtonBox.Ok)
        apply_btn.setText("Apply to Table")
        apply_btn.clicked.connect(self._on_apply_clicked)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def request(self) -> PotencyRequest | None:
        """Validated settings, or ``None`` after a warning."""
        if not self._columns:
            QMessageBox.warning(self, TOOL_POTENCY, "Add a numeric activity column first.")
            return None
        measure = str(self.measure_combo.currentData())
        write_ki = self.chk_cheng.isChecked() and measure == "IC50"
        if not self.chk_molar.isChecked() and not self.chk_p.isChecked() and not write_ki:
            QMessageBox.warning(self, TOOL_POTENCY, "Choose at least one column to write.")
            return None
        substrate_constant = None
        substrate_column = None
        km_constant = None
        km_column = None
        if write_ki:
            substrate_constant, substrate_column = self._read_concentration(
                "Substrate concentration",
                self.substrate_mode,
                self.substrate_value,
                self.substrate_column,
                allow_zero=True,
            )
            if substrate_constant is None and substrate_column is None:
                return None
            km_constant, km_column = self._read_concentration(
                "Km",
                self.km_mode,
                self.km_value,
                self.km_column,
                allow_zero=False,
            )
            if km_constant is None and km_column is None:
                return None
        return PotencyRequest(
            column=self.column_combo.currentText(),
            unit=str(self.unit_combo.currentData()),
            measure=measure,
            write_molar=self.chk_molar.isChecked(),
            write_p=self.chk_p.isChecked(),
            write_ki=write_ki,
            substrate_unit=str(self.substrate_unit.currentData()),
            km_unit=str(self.km_unit.currentData()),
            substrate_constant=substrate_constant,
            substrate_column=substrate_column,
            km_constant=km_constant,
            km_column=km_column,
        )

    def _concentration_row(
        self,
        form: QFormLayout,
        label: str,
        *,
        allow_zero: bool,
    ) -> tuple[QComboBox, QLineEdit, QComboBox, QComboBox]:
        mode = QComboBox()
        mode.addItem("Constant", _SOURCE_CONSTANT)
        mode.addItem("Column", _SOURCE_COLUMN)
        if not self._columns:
            mode.setEnabled(False)
        value = QLineEdit()
        value.setPlaceholderText("0" if allow_zero else "Positive value")
        column = QComboBox()
        column.addItems(self._columns)
        column.setVisible(False)
        unit = _unit_combo("µM")
        mode.currentIndexChanged.connect(
            lambda _index, value=value, column=column, mode=mode: _show_source(mode, value, column)
        )
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(mode)
        layout.addWidget(value, 1)
        layout.addWidget(column, 1)
        layout.addWidget(unit)
        form.addRow(label, row)
        return mode, value, column, unit

    def _read_concentration(
        self,
        label: str,
        mode: QComboBox,
        value: QLineEdit,
        column: QComboBox,
        *,
        allow_zero: bool,
    ) -> tuple[float | None, str | None]:
        if mode.currentData() == _SOURCE_COLUMN:
            name = column.currentText().strip()
            if not name:
                QMessageBox.warning(self, TOOL_POTENCY, f"Choose a column for {label}.")
                return None, None
            return None, name
        parsed = parse_concentration(value.text(), allow_zero=allow_zero)
        if parsed is None:
            hint = "zero or positive" if allow_zero else "positive"
            QMessageBox.warning(self, TOOL_POTENCY, f"Enter a {hint} {label}.")
            return None, None
        return parsed, None

    def _sync_cheng(self) -> None:
        ic50 = self.measure_combo.currentData() == "IC50"
        self.cheng_box.setEnabled(ic50)
        if not ic50:
            self.chk_cheng.setChecked(False)
        self._sync_cheng_fields()

    def _sync_cheng_fields(self) -> None:
        self._cheng_fields.setVisible(self.chk_cheng.isChecked() and self.cheng_box.isEnabled())

    def _on_apply_clicked(self) -> None:
        self.pending_request = self.request()
        if self.pending_request is not None:
            self.apply_requested.emit()


def _unit_combo(default: str) -> QComboBox:
    combo = QComboBox()
    for name, _factor in CONCENTRATION_UNITS:
        combo.addItem(name, name)
    index = combo.findData(default)
    if index >= 0:
        combo.setCurrentIndex(index)
    return combo


def _show_source(mode: QComboBox, value: QLineEdit, column: QComboBox) -> None:
    use_column = mode.currentData() == _SOURCE_COLUMN
    value.setVisible(not use_column)
    column.setVisible(use_column)
