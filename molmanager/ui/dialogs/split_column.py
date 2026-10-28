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

"""Split a delimited table column into new columns (Data → Table → Split Column)."""

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

from ...table.column_split import (
    DELIMITER_MODES,
    DelimiterMode,
    KeepMode,
    SplitColumnParams,
    apply_keep_mode,
    output_column_names,
    split_column_values,
    split_width,
    unescape_custom_delimiter,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_SPLIT_COLUMN
from .delimiter_picker import DelimiterPicker
from .scope import selection_scope_checked

SplitColumnDialogParams = SplitColumnParams


class SplitColumnDialog(QDialog):
    """Choose a source column and delimiter; writes one new column per field."""

    def __init__(self, columns: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_SPLIT_COLUMN)
        self.setMinimumWidth(440)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0
        self._updating_preview = False

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
        self.col_combo.setToolTip("Column whose cells are split into new columns.")
        self.col_combo.currentTextChanged.connect(self._on_source_changed)
        source_form.addRow("Column:", self.col_combo)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.toggled.connect(self._update_preview)
        source_form.addRow("", self.only_selected_cb)
        root.addWidget(source)

        separator = QGroupBox("Separator")
        sep_form = QFormLayout(separator)
        sep_form.setContentsMargins(8, 6, 8, 6)
        sep_form.setSpacing(4)
        sep_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._delim = DelimiterPicker(
            DELIMITER_MODES,
            combo_tooltip=(
                "Auto uses comma, semicolon, tab, or pipe when present; otherwise whitespace."
            ),
            custom_placeholder=r"e.g. :  or  \t",
            custom_tooltip="Used when Separator is Custom. \\t is a tab.",
            custom_max_length=8,
        )
        self._delim.add_rows(sep_form, combo_label="Separator:")
        self.delim_combo = self._delim.combo
        self.custom_input = self._delim.custom_input
        root.addWidget(separator)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.prefix_input = QLineEdit()
        self.prefix_input.setPlaceholderText("New column prefix")
        self.prefix_input.setToolTip(
            "New columns are named Prefix_1, Prefix_2, …. "
            "Defaults to the source column name. Existing names get a (1) suffix."
        )
        self.prefix_input.textChanged.connect(self._update_preview)
        out_form.addRow("Prefix:", self.prefix_input)

        self.largest_cb = QCheckBox("Only Split Largest Value")
        self.largest_cb.setToolTip(
            "Write one column with the largest numeric field from each cell. "
            "If no numbers are present, the last non-empty field in sort order is used."
        )
        self.smallest_cb = QCheckBox("Only Split Smallest Value")
        self.smallest_cb.setToolTip(
            "Write one column with the smallest numeric field from each cell. "
            "If no numbers are present, the first non-empty field in sort order is used."
        )
        self.largest_cb.toggled.connect(self._on_largest_toggled)
        self.smallest_cb.toggled.connect(self._on_smallest_toggled)
        out_form.addRow("", self.largest_cb)
        out_form.addRow("", self.smallest_cb)
        root.addWidget(output)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #444;")
        root.addWidget(self.preview_label)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)

        self._delim.connect_changed(self._update_preview)
        self._on_source_changed(self.col_combo.currentText())
        make_window_minimizable(self)

    def _delimiter_mode(self) -> DelimiterMode:
        return self._delim.mode()

    def _on_source_changed(self, name: str) -> None:
        if not (self.prefix_input.text() or "").strip():
            self._updating_preview = True
            try:
                self.prefix_input.setPlaceholderText((name or "").strip() or "Split")
            finally:
                self._updating_preview = False
        self._update_preview()

    def _keep_mode(self) -> KeepMode:
        if self.largest_cb.isChecked():
            return "largest"
        if self.smallest_cb.isChecked():
            return "smallest"
        return "all"

    def _on_largest_toggled(self, checked: bool) -> None:
        if checked and self.smallest_cb.isChecked():
            self.smallest_cb.blockSignals(True)
            self.smallest_cb.setChecked(False)
            self.smallest_cb.blockSignals(False)
        self._update_preview()

    def _on_smallest_toggled(self, checked: bool) -> None:
        if checked and self.largest_cb.isChecked():
            self.largest_cb.blockSignals(True)
            self.largest_cb.setChecked(False)
            self.largest_cb.blockSignals(False)
        self._update_preview()

    def _sample_texts(self) -> list[str]:
        app = self.parent_app
        col = (self.col_combo.currentText() or "").strip()
        if app is None or not col:
            return []
        only_sel = self.only_selected_rows()
        allowed = app._selected_oids_set() if only_sel else None
        from ...services.table_reader import backing_then_cell
        from ..table_reader_view import WindowTableReader

        if col not in app.headers:
            return []
        texts: list[str] = []
        m = app._table_model
        reader = WindowTableReader(app)
        for r in range(m.rowCount()):
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue
            texts.append(backing_then_cell(reader, r, col))
            if len(texts) >= 400:
                break
        return texts

    def _update_preview(self) -> None:
        if self._updating_preview:
            return
        col = (self.col_combo.currentText() or "").strip()
        if not col:
            self.preview_label.setText("Choose a column to split.")
            return
        try:
            _delim, parts = split_column_values(
                self._sample_texts(),
                self._delimiter_mode(),
                custom=self.custom_input.text(),
            )
        except ValueError as exc:
            self.preview_label.setText(str(exc))
            return
        n = split_width(parts)
        keep = self._keep_mode()
        if keep in ("largest", "smallest"):
            parts = apply_keep_mode(parts, keep)
            n = split_width(parts)
        prefix = (self.prefix_input.text() or "").strip() or col or "Split"
        if keep in ("largest", "smallest"):
            names = [prefix]
            kind = "largest" if keep == "largest" else "smallest"
            if n <= 0:
                self.preview_label.setText("No values to split in the current scope.")
                return
            self.preview_label.setText(f"New column: {names[0]} ({kind} value from each cell)")
            return
        names = output_column_names(prefix, n)
        if n <= 0:
            self.preview_label.setText("No values to split in the current scope.")
            return
        shown = ", ".join(names[:6])
        extra = "" if n <= 6 else f", … ({n} total)"
        self.preview_label.setText(f"New columns: {shown}{extra}")

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SplitColumnDialogParams:
        prefix = (self.prefix_input.text() or "").strip()
        source = (self.col_combo.currentText() or "").strip()
        return SplitColumnDialogParams(
            source_column=source,
            mode=self._delimiter_mode(),
            custom=self.custom_input.text(),
            prefix=prefix or source,
            keep=self._keep_mode(),
        )

    def accept(self) -> None:
        if not (self.col_combo.currentText() or "").strip():
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Choose a column to split.")
            self.col_combo.setFocus(Qt.OtherFocusReason)
            return
        if self._delimiter_mode() == "custom" and not unescape_custom_delimiter(
            self.custom_input.text()
        ):
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Enter a custom delimiter character.")
            self.custom_input.setFocus(Qt.OtherFocusReason)
            return
        super().accept()
