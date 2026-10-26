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

"""Join two table columns with a delimiter (Data → Table → Join Columns)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QVBoxLayout,
)

from ...table.column_join import (
    JOIN_DELIMITER_MODES,
    JoinColumnsParams,
    JoinDelimiterMode,
    default_join_output_name,
    join_two_values,
    resolve_join_delimiter,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_JOIN_COLUMNS
from .delimiter_picker import DelimiterPicker
from .scope import selection_scope_checked

JoinColumnsDialogParams = JoinColumnsParams


class JoinColumnsDialog(QDialog):
    """Choose two source columns and a delimiter; writes one new column."""

    def __init__(self, columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_JOIN_COLUMNS)
        self.setMinimumWidth(440)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0
        self._updating_preview = False

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        columns_box = QGroupBox("Columns")
        col_form = QFormLayout(columns_box)
        col_form.setContentsMargins(8, 6, 8, 6)
        col_form.setSpacing(4)
        col_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.left_combo = QComboBox()
        self.left_combo.addItems(columns)
        self.left_combo.setToolTip("First (left) column in the joined text.")
        self.left_combo.currentTextChanged.connect(self._on_source_changed)
        col_form.addRow("First column:", self.left_combo)

        self.right_combo = QComboBox()
        self.right_combo.addItems(columns)
        self.right_combo.setToolTip("Second (right) column in the joined text.")
        if len(columns) > 1:
            self.right_combo.setCurrentIndex(1)
        self.right_combo.currentTextChanged.connect(self._on_source_changed)
        col_form.addRow("Second column:", self.right_combo)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.toggled.connect(self._update_preview)
        col_form.addRow("", self.only_selected_cb)
        root.addWidget(columns_box)

        delimiter = QGroupBox("Delimiter")
        delim_form = QFormLayout(delimiter)
        delim_form.setContentsMargins(8, 6, 8, 6)
        delim_form.setSpacing(4)
        delim_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._delim = DelimiterPicker(
            JOIN_DELIMITER_MODES,
            combo_tooltip="Text placed between the two cell values.",
            custom_placeholder=r"e.g.  |  or  \t",
            custom_tooltip="Used when Delimiter is Custom. \\t is a tab.",
            custom_max_length=16,
        )
        self._delim.add_rows(delim_form, combo_label="Delimiter:")
        self.delim_combo = self._delim.combo
        self.custom_input = self._delim.custom_input

        self.skip_empty_cb = QCheckBox("Skip empty cells")
        self.skip_empty_cb.setChecked(True)
        self.skip_empty_cb.setToolTip(
            "If one side is blank, write the other value with no extra delimiter. "
            "Uncheck to always concatenate both sides, even when empty."
        )
        self.skip_empty_cb.toggled.connect(self._update_preview)
        delim_form.addRow("", self.skip_empty_cb)
        root.addWidget(delimiter)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("New column name")
        self.name_input.setToolTip(
            "Name of the new joined column. Defaults to First_Second. "
            "Existing names get a (1) suffix."
        )
        self.name_input.textChanged.connect(self._update_preview)
        out_form.addRow("New column:", self.name_input)
        root.addWidget(output)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: palette(mid);")
        root.addWidget(self.preview_label)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._delim.connect_changed(self._update_preview)
        self._on_source_changed()
        make_window_minimizable(self)

    def _delimiter_mode(self) -> JoinDelimiterMode:
        return self._delim.mode()

    def _on_source_changed(self, *_args) -> None:
        if not (self.name_input.text() or "").strip():
            self._updating_preview = True
            try:
                self.name_input.setPlaceholderText(
                    default_join_output_name(
                        self.left_combo.currentText(),
                        self.right_combo.currentText(),
                    )
                )
            finally:
                self._updating_preview = False
        self._update_preview()

    def _sample_pair(self) -> tuple[str, str] | None:
        app = self.parent_app
        left = (self.left_combo.currentText() or "").strip()
        right = (self.right_combo.currentText() or "").strip()
        if app is None or not left or not right:
            return None
        only_sel = self.only_selected_rows()
        allowed = app._selected_oids_set() if only_sel else None
        m = app._table_model
        try:
            li = app.headers.index(left)
            ri = app.headers.index(right)
        except ValueError:
            return None
        for r in range(m.rowCount()):
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue

            a = m.backing_value_for_row_header(r, left) or ""
            if not a:
                a = app._table_cell_text(r, li) or ""
            b = m.backing_value_for_row_header(r, right) or ""
            if not b:
                b = app._table_cell_text(r, ri) or ""
            if a.strip() or b.strip():
                return a, b
        return ("", "")

    def _update_preview(self) -> None:
        if self._updating_preview:
            return
        left = (self.left_combo.currentText() or "").strip()
        right = (self.right_combo.currentText() or "").strip()
        if not left or not right:
            self.preview_label.setText("Choose two columns to join.")
            return
        try:
            delim = resolve_join_delimiter(self._delimiter_mode(), self.custom_input.text())
        except ValueError as exc:
            self.preview_label.setText(str(exc))
            return
        sample = self._sample_pair()
        name = (self.name_input.text() or "").strip() or default_join_output_name(left, right)
        if sample is None:
            self.preview_label.setText(f"New column: {name}")
            return
        joined = join_two_values(
            sample[0], sample[1], delim, skip_empty=self.skip_empty_cb.isChecked()
        )
        shown = joined if joined else "(empty)"
        if len(shown) > 80:
            shown = shown[:77] + "…"
        self.preview_label.setText(f"New column: {name}  —  e.g. {shown}")

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> JoinColumnsDialogParams:
        left = (self.left_combo.currentText() or "").strip()
        right = (self.right_combo.currentText() or "").strip()
        name = (self.name_input.text() or "").strip()
        return JoinColumnsDialogParams(
            left_column=left,
            right_column=right,
            mode=self._delimiter_mode(),
            custom=self.custom_input.text(),
            output_column=name or default_join_output_name(left, right),
            skip_empty=self.skip_empty_cb.isChecked(),
        )

    def accept(self) -> None:
        left = (self.left_combo.currentText() or "").strip()
        right = (self.right_combo.currentText() or "").strip()
        if not left or not right:
            QMessageBox.warning(self, TOOL_JOIN_COLUMNS, "Choose two columns to join.")
            self.left_combo.setFocus(Qt.OtherFocusReason)
            return
        super().accept()
