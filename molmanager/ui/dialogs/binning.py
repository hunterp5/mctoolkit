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

"""Bin a numeric column and write range and class columns (Data → Similarity → Binning)."""

from __future__ import annotations

import math

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...chem.molecule_conversion import safe_float
from ...table.column_binning import (
    BIN_METHODS,
    MAX_BINS,
    BinMethod,
    BinningParams,
    bin_column_texts,
    default_bin_column_name,
    default_class_column_name,
    parse_edges_text,
    parse_numeric_cell,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_BINNING
from .scope import selection_scope_checked

BinningDialogParams = BinningParams

_RESERVED_COLUMNS = frozenset({"ID_HIDDEN", "Structure"})


class BinningDialog(QDialog):
    """Choose a numeric column and write its bin range and classification."""

    def __init__(self, columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_BINNING)
        self.setMinimumWidth(460)
        self.resize(500, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        source = QGroupBox("Column")
        source_form = QFormLayout(source)
        source_form.setContentsMargins(8, 6, 8, 6)
        source_form.setSpacing(4)
        source_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.col_combo = QComboBox()
        self.col_combo.addItems(columns)
        self.col_combo.setToolTip("Numeric column to bin. Non-numeric cells are left blank.")
        source_form.addRow("Column:", self.col_combo)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        source_form.addRow("", self.only_selected_cb)
        root.addWidget(source)

        bins = QGroupBox("Bins")
        self._form = QFormLayout(bins)
        self._form.setContentsMargins(8, 6, 8, 6)
        self._form.setSpacing(4)
        self._form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.method_combo = QComboBox()
        for label, method in BIN_METHODS:
            self.method_combo.addItem(label, method)
        self.method_combo.setToolTip(
            "Equal width splits the range into equal spans. "
            "Equal count puts about the same number of values in each bin. "
            "Custom edges use the cut points you enter."
        )
        self.method_combo.currentIndexChanged.connect(self._sync_fields)
        self._form.addRow("Method:", self.method_combo)

        self.bin_count_spin = QSpinBox()
        self.bin_count_spin.setRange(2, MAX_BINS)
        self.bin_count_spin.setValue(5)
        self._form.addRow("Bins:", self.bin_count_spin)

        self.bin_width_input = QLineEdit()
        self.bin_width_input.setPlaceholderText("automatic")
        self.bin_width_input.setToolTip(
            "Optional width. When set, this is used instead of the bin count. "
            "With Min and Max empty, edges line up with histogram bins."
        )
        self._form.addRow("Bin width:", self.bin_width_input)

        self.min_input = QLineEdit()
        self.min_input.setPlaceholderText("data minimum")
        self.min_input.setToolTip(
            "Optional lower end of the range. Values below it are left blank."
        )
        self._form.addRow("Minimum:", self.min_input)

        self.max_input = QLineEdit()
        self.max_input.setPlaceholderText("data maximum")
        self.max_input.setToolTip(
            "Optional upper end of the range. Values above it are left blank."
        )
        self._form.addRow("Maximum:", self.max_input)

        self.edges_input = QLineEdit()
        self.edges_input.setPlaceholderText("e.g. 5, 6, 7")
        self.edges_input.setToolTip(
            "Cut points, separated by commas or spaces. They must increase."
        )
        self._form.addRow("Edges:", self.edges_input)

        self.open_ends_cb = QCheckBox("Open ends")
        self.open_ends_cb.setChecked(True)
        self.open_ends_cb.setToolTip(
            "Add a bin below the first edge and a bin at or above the last edge."
        )
        self._form.addRow(self.open_ends_cb)
        root.addWidget(bins)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.range_input = QLineEdit()
        self.range_input.setPlaceholderText("Range column")
        self.range_input.setToolTip(
            "Column for the bin range, such as [0, 1). "
            "Defaults to the source name plus _bin. Existing names get a (1) suffix."
        )
        out_form.addRow("Range column:", self.range_input)

        self.class_input = QLineEdit()
        self.class_input.setPlaceholderText("Class column")
        self.class_input.setToolTip(
            "Classification written beside the range. "
            "Two bins are Inactive and Active; three are Low, Medium, and High; "
            "four are Low, Medium, High, and Very high; otherwise Class 1, Class 2, …. "
            "Defaults to the source name plus _class. Existing names get a (1) suffix."
        )
        out_form.addRow("Class column:", self.class_input)
        root.addWidget(output)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._prefer_numeric_column()
        self._on_source_changed(self.col_combo.currentText())
        self.col_combo.currentTextChanged.connect(self._on_source_changed)
        self._sync_fields()
        make_window_minimizable(self)

    def _method(self) -> BinMethod:
        return self.method_combo.currentData() or "equal_width"

    def _set_row_visible(self, field: QWidget, visible: bool) -> None:
        label = self._form.labelForField(field)
        if label is not None:
            label.setVisible(visible)
        field.setVisible(visible)
        setter = getattr(self._form, "setRowVisible", None)
        if callable(setter):
            setter(field, visible)

    def _sync_fields(self) -> None:
        method = self._method()
        equal_width = method == "equal_width"
        counted = method in ("equal_width", "equal_count")
        custom = method == "custom"
        self._set_row_visible(self.bin_count_spin, counted)
        self._set_row_visible(self.bin_width_input, equal_width)
        self._set_row_visible(self.min_input, equal_width)
        self._set_row_visible(self.max_input, equal_width)
        self._set_row_visible(self.edges_input, custom)
        self._set_row_visible(self.open_ends_cb, custom)
        if method == "equal_count":
            self.bin_count_spin.setToolTip(
                "Number of bins with as equal a count as ties allow. "
                "Identical values stay in the same bin, so you may get fewer bins."
            )
        else:
            self.bin_count_spin.setToolTip(
                "Number of equal-width bins across the range. Ignored when Bin width is set."
            )

    def _on_source_changed(self, name: str) -> None:
        if not (self.range_input.text() or "").strip():
            self.range_input.setPlaceholderText(default_bin_column_name(name))
        if not (self.class_input.text() or "").strip():
            self.class_input.setPlaceholderText(default_class_column_name(name))

    def _prefer_numeric_column(self) -> None:
        app = self.parent_app
        if app is None:
            return
        for i in range(self.col_combo.count()):
            name = self.col_combo.itemText(i)
            sample = self._read_texts(name, limit=40)
            if any(parse_numeric_cell(text) is not None for text in sample):
                if i != self.col_combo.currentIndex():
                    self.col_combo.setCurrentIndex(i)
                return

    def _read_texts(self, column: str | None = None, *, limit: int | None = None) -> list[str]:
        app = self.parent_app
        col = (column if column is not None else self.col_combo.currentText() or "").strip()
        if app is None or not col:
            return []
        only_sel = self.only_selected_rows()
        allowed = app._selected_oids_set() if only_sel else None
        from ...services.table_reader import backing_then_cell
        from ..table_reader_view import WindowTableReader

        if col not in app.headers:
            return []
        texts: list[str] = []
        model = app._table_model
        reader = WindowTableReader(app)
        for row in range(model.rowCount()):
            oid = model.row_oid(row)
            if allowed is not None and oid not in allowed:
                continue
            texts.append(str(backing_then_cell(reader, row, col)))
            if limit is not None and len(texts) >= limit:
                break
        return texts

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def _optional_number(self, text: str, label: str, *, positive: bool) -> float | None:
        raw = (text or "").strip()
        if not raw:
            return None
        value = safe_float(raw)
        if value is None or not math.isfinite(value):
            raise ValueError(f"{label} must be a number.")
        if positive and not value > 0:
            raise ValueError(f"{label} must be greater than zero.")
        return float(value)

    def params(self) -> BinningDialogParams:
        return self._build_params()

    def _build_params(self) -> BinningDialogParams:
        source = (self.col_combo.currentText() or "").strip()
        if not source:
            raise ValueError("Choose a column to bin.")
        range_column = (self.range_input.text() or "").strip() or default_bin_column_name(source)
        class_column = (self.class_input.text() or "").strip() or default_class_column_name(source)
        if range_column in _RESERVED_COLUMNS or class_column in _RESERVED_COLUMNS:
            raise ValueError("That output name is reserved. Choose a different column name.")
        if range_column == class_column:
            raise ValueError("Choose different names for the range and classification columns.")
        method = self._method()
        minimum = maximum = bin_width = None
        edges: tuple[float, ...] = ()
        if method == "equal_width":
            bin_width = self._optional_number(
                self.bin_width_input.text(), "Bin width", positive=True
            )
            minimum = self._optional_number(self.min_input.text(), "Minimum", positive=False)
            maximum = self._optional_number(self.max_input.text(), "Maximum", positive=False)
            if minimum is not None and maximum is not None and maximum < minimum:
                raise ValueError("Maximum must be greater than minimum.")
        elif method == "custom":
            edges = parse_edges_text(self.edges_input.text())
        return BinningDialogParams(
            source_column=source,
            range_column=range_column,
            class_column=class_column,
            method=method,
            bin_count=int(self.bin_count_spin.value()),
            bin_width=bin_width,
            minimum=minimum,
            maximum=maximum,
            edges=edges,
            open_ends=self.open_ends_cb.isChecked(),
        )

    def accept(self) -> None:
        try:
            params = self.params()
            bin_column_texts(self._read_texts(), params)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_BINNING, str(exc) or "Could not bin the column.")
            return
        super().accept()
