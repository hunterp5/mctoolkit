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

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSizePolicy,
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
    custom_range_labels,
    default_bin_column_name,
    default_class_column_name,
    parse_bin_names,
    parse_edges_text,
    parse_numeric_cell,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_BINNING
from .scope import selection_scope_checked

BinningDialogParams = BinningParams

_QT_WIDGET_MAX = 16777215
_DIALOG_WIDTH = 500


class BinningDialog(QDialog):
    """Choose a numeric column and write its bin range and classification."""

    def __init__(self, columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_BINNING)
        self.setMinimumWidth(_DIALOG_WIDTH)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 12)
        root.setSpacing(16)

        self._form = QFormLayout()
        self._form.setContentsMargins(0, 0, 0, 0)
        self._form.setHorizontalSpacing(16)
        self._form.setVerticalSpacing(2)
        self._form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self._form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        column_field = QWidget()
        column_row = QHBoxLayout(column_field)
        column_row.setContentsMargins(0, 0, 0, 0)
        column_row.setSpacing(16)
        self.col_combo = QComboBox()
        self.col_combo.addItems(columns)
        self.col_combo.setMinimumWidth(180)
        self.col_combo.setToolTip("Numeric column to bin. Non-numeric cells are left blank.")
        column_row.addWidget(self.col_combo, 1)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        column_row.addWidget(self.only_selected_cb, 0, Qt.AlignVCenter)
        self._form.addRow("Column:", column_field)
        root.addLayout(self._form)

        self.method_combo = QComboBox()
        for label, method in BIN_METHODS:
            self.method_combo.addItem(label, method)
        self.method_combo.setToolTip(
            "Equal width splits the range into equal spans. "
            "Equal count puts about the same number of values in each bin. "
            "Custom edges use the cut points you enter."
        )
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

        self.names_input = QLineEdit()
        self.names_input.setPlaceholderText("comma-separated, low to high")
        self.names_input.setToolTip(
            "Optional names for these bins, from low to high, separated by commas. "
            "The count must match the bins the edges produce, including open-end bins. "
            "Leave blank for the default class names."
        )
        self._form.addRow("Names:", self.names_input)

        self.open_ends_cb = QCheckBox("Open ends")
        self.open_ends_cb.setChecked(True)
        self.open_ends_cb.setToolTip(
            "Add a bin for values below the first edge and a bin for values at or above "
            "the last edge. Uncheck to leave those values blank."
        )
        self._form.addRow("", self.open_ends_cb)

        self.bin_summary = QLabel("")
        self.bin_summary.setWordWrap(True)
        self.bin_summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.bin_summary.setStyleSheet("color: palette(mid);")
        self.bin_summary.setToolTip("Bins these edges produce, from low to high.")
        self._form.addRow("", self.bin_summary)

        self.edges_input.textChanged.connect(self._on_custom_edited)
        self.open_ends_cb.toggled.connect(self._on_custom_edited)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._prefer_numeric_column()
        self.method_combo.currentIndexChanged.connect(self._sync_fields)
        self._sync_fields()
        make_window_minimizable(self)

    def _method(self) -> BinMethod:
        return self.method_combo.currentData() or "equal_width"

    def _set_row_visible(self, field: QWidget, visible: bool) -> None:
        """Show or hide a form row. Qt 5 leaves a gap unless the row height is collapsed."""
        label = self._form.labelForField(field)
        height = _QT_WIDGET_MAX if visible else 0
        for widget in (label, field):
            if widget is None:
                continue
            widget.setVisible(visible)
            widget.setMinimumHeight(0)
            widget.setMaximumHeight(height)

    def _schedule_fit(self) -> None:
        """Resize after Qt has applied show/hide, so hidden rows do not leave a gap."""
        self.setMinimumHeight(0)
        self.setMaximumHeight(_QT_WIDGET_MAX)
        timer = getattr(self, "_fit_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self._fit_dialog)
            self._fit_timer = timer
        if not timer.isActive():
            timer.start(0)

    def _fit_dialog(self) -> None:
        layout = self.layout()
        if layout is not None:
            layout.invalidate()
            layout.activate()
        height = self.sizeHint().height()
        if height <= 0:
            return
        self.setMinimumHeight(height)
        self.setMaximumHeight(height)
        self.resize(_DIALOG_WIDTH, height)

    def _sync_names_hint(self) -> None:
        if self._method() != "custom":
            return
        try:
            n_edges = len(parse_edges_text(self.edges_input.text()))
        except ValueError:
            self.names_input.setPlaceholderText("comma-separated, low to high")
            return
        count = n_edges + 1 if self.open_ends_cb.isChecked() else n_edges - 1
        if count < 1:
            self.names_input.setPlaceholderText("comma-separated, low to high")
            return
        noun = "name" if count == 1 else "names"
        self.names_input.setPlaceholderText(f"{count} {noun}, low to high")

    def _on_custom_edited(self) -> None:
        self._sync_names_hint()
        self._sync_bin_summary()
        self._schedule_fit()

    def _sync_bin_summary(self) -> None:
        labels: tuple[str, ...] = ()
        if self._method() == "custom":
            try:
                labels = custom_range_labels(
                    parse_edges_text(self.edges_input.text()),
                    open_ends=self.open_ends_cb.isChecked(),
                )
            except ValueError:
                labels = ()
        self.bin_summary.setText(" · ".join(labels))
        self._set_row_visible(self.bin_summary, bool(labels))

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
        self._set_row_visible(self.names_input, custom)
        self._set_row_visible(self.open_ends_cb, custom)
        self._sync_names_hint()
        self._sync_bin_summary()
        self._schedule_fit()
        if method == "equal_count":
            self.bin_count_spin.setToolTip(
                "Number of bins with as equal a count as ties allow. "
                "Identical values stay in the same bin, so you may get fewer bins."
            )
        else:
            self.bin_count_spin.setToolTip(
                "Number of equal-width bins across the range. Ignored when Bin width is set."
            )

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
        range_column = default_bin_column_name(source)
        class_column = default_class_column_name(source)
        method = self._method()
        minimum = maximum = bin_width = None
        edges: tuple[float, ...] = ()
        bin_names: tuple[str, ...] = ()
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
            bin_names = parse_bin_names(self.names_input.text())
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
            bin_names=bin_names,
        )

    def accept(self) -> None:
        try:
            params = self.params()
            bin_column_texts(self._read_texts(), params)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_BINNING, str(exc) or "Could not bin the column.")
            return
        super().accept()
