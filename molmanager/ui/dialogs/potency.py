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
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...chem.potency import CONCENTRATION_UNITS, DESIRED_UNITS, MEASURES, parse_concentration
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_POTENCY
from .scope import selection_scope_checked

_SOURCE_CONSTANT = "constant"
_SOURCE_COLUMN = "column"


@dataclass(frozen=True)
class AssayConcentration:
    """One Cheng–Prusoff term: an assay concentration divided by Km or Kd."""

    conc_constant: float | None
    conc_column: str | None
    conc_unit: str
    ref_constant: float | None
    ref_column: str | None
    ref_unit: str


@dataclass(frozen=True)
class PotencyRequest:
    """One apply pass: source columns, desired unit, and optional Ki terms."""

    column: str
    unit_column: str
    measure: str
    desired_unit: str
    write_p: bool
    write_ki: bool
    assay_concentrations: tuple[AssayConcentration, ...]
    mw_column: str | None


class _AssayRow:
    """Widgets for one assay concentration and its Km or Kd."""

    def __init__(
        self,
        host: QWidget,
        title: QLabel,
        conc_mode: QComboBox,
        conc_value: QLineEdit,
        conc_column: QComboBox,
        conc_unit: QComboBox,
        ref_mode: QComboBox,
        ref_value: QLineEdit,
        ref_column: QComboBox,
        ref_unit: QComboBox,
    ):
        self.host = host
        self.title = title
        self.conc_mode = conc_mode
        self.conc_value = conc_value
        self.conc_column = conc_column
        self.conc_unit = conc_unit
        self.ref_mode = ref_mode
        self.ref_value = ref_value
        self.ref_column = ref_column
        self.ref_unit = ref_unit


class PotencyStandardizationDialog(QDialog):
    """Convert an activity column to nM or uM and pActivity, optionally to Ki."""

    apply_requested = pyqtSignal()

    def __init__(
        self,
        numeric_columns: list[str],
        selected_row_count: int = 0,
        parent=None,
        unit_columns: list[str] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle(TOOL_POTENCY)
        self.resize(540, 480)
        self._have_selection = selected_row_count > 0
        self._columns = list(numeric_columns)
        self._unit_columns = list(self._columns if unit_columns is None else unit_columns)
        self._assay_rows: list[_AssayRow] = []
        self.pending_request: PotencyRequest | None = None
        root = QVBoxLayout(self)
        root.setSpacing(10)

        source = QGroupBox("Activity")
        form = QFormLayout(source)
        self.column_combo = QComboBox()
        self.column_combo.setToolTip("Numeric activity values.")
        self.column_combo.addItems(self._columns)
        if not self._columns:
            self.column_combo.addItem("No numeric columns")
            self.column_combo.setEnabled(False)
        form.addRow("Data Column:", self.column_combo)
        self.unit_column_combo = QComboBox()
        self.unit_column_combo.setToolTip(
            "Per-row unit. Amount units such as nM, uM, and mol/L convert directly. "
            "Mass/volume units such as mg/mL, g/L, and kg/m^3 use molecular weight."
        )
        self.unit_column_combo.addItems(self._unit_columns)
        if not self._unit_columns:
            self.unit_column_combo.addItem("No columns")
            self.unit_column_combo.setEnabled(False)
        elif (
            self.unit_column_combo.count() > 1
            and self.unit_column_combo.currentText() == self.column_combo.currentText()
        ):
            self.unit_column_combo.setCurrentIndex(1)
        form.addRow("Unit Column:", self.unit_column_combo)
        self.mw_combo = QComboBox()
        self.mw_combo.addItem("From structure", "")
        for name in self._columns:
            self.mw_combo.addItem(name, name)
        preferred_mw = _preferred_mw_column(self._columns)
        if preferred_mw:
            index = self.mw_combo.findData(preferred_mw)
            if index >= 0:
                self.mw_combo.setCurrentIndex(index)
        self.mw_combo.setToolTip(
            "g/mol. Used when a row's unit is mass/volume. "
            "From structure is the RDKit average molecular weight."
        )
        form.addRow("Molecular Weight:", self.mw_combo)
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
        out_form = QFormLayout()
        out_form.setContentsMargins(0, 0, 0, 0)
        self.desired_unit = QComboBox()
        for unit in DESIRED_UNITS:
            self.desired_unit.addItem(unit, unit)
        self.desired_unit.setToolTip(
            "Activity is written in this unit. pActivity is still −log10 of the molar value."
        )
        out_form.addRow("Desired Unit:", self.desired_unit)
        out_layout.addLayout(out_form)
        self.chk_p = QCheckBox("pActivity")
        self.chk_p.setChecked(True)
        self.chk_p.setToolTip("−log10 of the molar value, for example pIC50.")
        out_layout.addWidget(self.chk_p)
        root.addWidget(outputs)

        self.cheng_box = QGroupBox("Cheng–Prusoff")
        cheng = QVBoxLayout(self.cheng_box)
        self.chk_cheng = QCheckBox("Convert IC50 to Ki")
        self.chk_cheng.setToolTip(
            "Ki = IC50 / (1 + Σ concentration / reference). "
            "Add each assay concentration with its Km or Kd."
        )
        self.chk_cheng.toggled.connect(self._sync_cheng_fields)
        cheng.addWidget(self.chk_cheng)
        self._cheng_fields = QWidget(self.cheng_box)
        fields = QVBoxLayout(self._cheng_fields)
        fields.setContentsMargins(0, 0, 0, 0)
        self._add_assay_btn = QPushButton("Add assay concentration")
        self._add_assay_btn.setAutoDefault(False)
        self._add_assay_btn.setToolTip(
            "Add a concentration and its Km or Kd. Every pair is included in the Ki correction."
        )
        self._add_assay_btn.clicked.connect(self._add_assay_row)
        fields.addWidget(self._add_assay_btn)
        self._assay_layout = QVBoxLayout()
        self._assay_layout.setContentsMargins(0, 0, 0, 0)
        fields.addLayout(self._assay_layout)
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
        if not self._unit_columns:
            QMessageBox.warning(
                self, TOOL_POTENCY, "Add a column that contains the activity unit for each row."
            )
            return None
        data_column = self.column_combo.currentText()
        unit_column = self.unit_column_combo.currentText()
        if data_column == unit_column:
            QMessageBox.warning(
                self, TOOL_POTENCY, "Choose a Unit Column that is not the Data Column."
            )
            return None
        measure = str(self.measure_combo.currentData())
        write_ki = self.chk_cheng.isChecked() and measure == "IC50"
        assay_concentrations: tuple[AssayConcentration, ...] = ()
        if write_ki:
            read = self._read_assay_rows()
            if read is None:
                return None
            assay_concentrations = read
        return PotencyRequest(
            column=data_column,
            unit_column=unit_column,
            measure=measure,
            desired_unit=str(self.desired_unit.currentData()),
            write_p=self.chk_p.isChecked(),
            write_ki=write_ki,
            assay_concentrations=assay_concentrations,
            mw_column=_mw_column(self.mw_combo.currentData()),
        )

    def _add_assay_row(self) -> None:
        host = QWidget(self._cheng_fields)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(0, 8, 0, 0)
        header = QHBoxLayout()
        title = QLabel(host)
        remove = QPushButton("Remove", host)
        remove.setAutoDefault(False)
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(remove)
        outer.addLayout(header)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        conc_mode, conc_value, conc_column, conc_unit = self._concentration_row(
            form,
            "Concentration:",
            allow_zero=True,
        )
        ref_mode, ref_value, ref_column, ref_unit = self._concentration_row(
            form,
            "Km or Kd:",
            allow_zero=False,
        )
        outer.addLayout(form)
        row = _AssayRow(
            host,
            title,
            conc_mode,
            conc_value,
            conc_column,
            conc_unit,
            ref_mode,
            ref_value,
            ref_column,
            ref_unit,
        )
        remove.clicked.connect(lambda _checked=False, row=row: self._remove_assay_row(row))
        self._assay_rows.append(row)
        self._assay_layout.addWidget(host)
        self._renumber_assay_rows()

    def _remove_assay_row(self, row: _AssayRow) -> None:
        if row not in self._assay_rows:
            return
        self._assay_rows.remove(row)
        self._assay_layout.removeWidget(row.host)
        row.host.deleteLater()
        self._renumber_assay_rows()

    def _renumber_assay_rows(self) -> None:
        for index, row in enumerate(self._assay_rows, start=1):
            row.title.setText(f"Assay concentration {index}")

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

    def _read_assay_rows(self) -> tuple[AssayConcentration, ...] | None:
        if not self._assay_rows:
            QMessageBox.warning(
                self,
                TOOL_POTENCY,
                "Add an assay concentration and its Km or Kd.",
            )
            return None
        terms: list[AssayConcentration] = []
        for index, row in enumerate(self._assay_rows, start=1):
            conc_constant, conc_column = self._read_concentration(
                f"assay concentration {index}",
                row.conc_mode,
                row.conc_value,
                row.conc_column,
                allow_zero=True,
            )
            if conc_constant is None and conc_column is None:
                return None
            ref_constant, ref_column = self._read_concentration(
                f"Km or Kd {index}",
                row.ref_mode,
                row.ref_value,
                row.ref_column,
                allow_zero=False,
            )
            if ref_constant is None and ref_column is None:
                return None
            terms.append(
                AssayConcentration(
                    conc_constant=conc_constant,
                    conc_column=conc_column,
                    conc_unit=str(row.conc_unit.currentData()),
                    ref_constant=ref_constant,
                    ref_column=ref_column,
                    ref_unit=str(row.ref_unit.currentData()),
                )
            )
        return tuple(terms)

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
        visible = self.chk_cheng.isChecked() and self.cheng_box.isEnabled()
        if visible and not self._assay_rows:
            self._add_assay_row()
        self._cheng_fields.setVisible(visible)

    def _on_apply_clicked(self) -> None:
        self.pending_request = self.request()
        if self.pending_request is not None:
            self.apply_requested.emit()


def _preferred_mw_column(columns: list[str]) -> str | None:
    aliases = {"mw", "molwt", "molweight", "molecularweight", "molecularwt", "exactmass"}
    for name in columns:
        key = "".join(char for char in name.lower() if char.isalnum())
        if key in aliases:
            return name
    return None


def _mw_column(value) -> str | None:
    text = "" if value is None else str(value).strip()
    return text or None


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
