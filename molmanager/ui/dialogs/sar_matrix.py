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

"""SAR matrix configuration (Data → SAR Matrix)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QVBoxLayout,
)

from ...analysis.sar_matrix import suggest_rgroup_axes
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_SAR_MATRIX
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked

_NONE_PAGE = "(none)"


@dataclass(frozen=True)
class SarMatrixDialogParams:
    """Columns and color direction for one SAR grid."""

    row_column: str
    column_column: str
    page_column: str
    activity_column: str
    higher_is_better: bool
    only_selected: bool


class SarMatrixDialog(QDialog):
    """Choose the two substituents, an optional page substituent, and the activity."""

    def __init__(
        self,
        *,
        substituent_columns: list[str],
        activity_columns: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(TOOL_SAR_MATRIX)
        self.setMinimumWidth(460)
        self.resize(520, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        form = QFormLayout()

        self.row_combo = QComboBox()
        self.col_combo = QComboBox()
        self.page_combo = QComboBox()
        for combo in (self.row_combo, self.col_combo, self.page_combo):
            combo.setMinimumWidth(220)
        self.row_combo.addItems(substituent_columns)
        self.col_combo.addItems(substituent_columns)
        self.page_combo.addItem(_NONE_PAGE)
        self.page_combo.addItems(substituent_columns)
        row_name, col_name, page_name = suggest_rgroup_axes(substituent_columns)
        self._select_named(self.row_combo, row_name)
        if col_name:
            self._select_named(self.col_combo, col_name)
        elif self.col_combo.count() > 1:
            self.col_combo.setCurrentIndex(1)
        if page_name:
            self._select_named(self.page_combo, page_name)
        self.row_combo.setToolTip("Substituent written down the side of the grid, usually R1.")
        self.col_combo.setToolTip("Substituent written across the top of the grid, usually R2.")
        self.page_combo.setToolTip(
            "Optional third substituent. Each value becomes its own grid; "
            "the other two axes stay in place."
        )
        form.addRow("Row substituent:", self.row_combo)
        form.addRow("Column substituent:", self.col_combo)
        form.addRow("Page substituent:", self.page_combo)

        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(220)
        if activity_columns:
            self.activity_combo.addItems(activity_columns)
            select_preferred_activity_column(self.activity_combo)
        else:
            self.activity_combo.addItem("(no numeric columns)")
            self.activity_combo.setEnabled(False)
        self.activity_combo.setToolTip("Numeric column used to color each filled cell.")
        form.addRow("Activity column:", self.activity_combo)
        root.addLayout(form)

        self.higher_cb = QCheckBox("Higher values are better")
        self.higher_cb.setChecked(True)
        self.higher_cb.setToolTip(
            "Checked colors the largest activity darkest. Clear it for IC50 and other "
            "columns where a smaller number is the better result."
        )
        root.addWidget(self.higher_cb)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._ok = box.button(QDialogButtonBox.Ok)
        root.addWidget(box)
        self.row_combo.currentIndexChanged.connect(self._sync_ok)
        self.col_combo.currentIndexChanged.connect(self._sync_ok)
        self.page_combo.currentIndexChanged.connect(self._sync_ok)
        self._sync_ok()
        make_window_minimizable(self)

    @staticmethod
    def _select_named(combo: QComboBox, name: str | None) -> None:
        if not name:
            return
        index = combo.findText(name)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _axes_conflict(self) -> bool:
        row = self.row_combo.currentText()
        col = self.col_combo.currentText()
        page = self.page_column()
        if not row or not col or row == col:
            return True
        return bool(page) and page in {row, col}

    def _sync_ok(self) -> None:
        if self._ok is None:
            return
        self._ok.setEnabled(
            self.activity_combo.isEnabled()
            and self.row_combo.count() >= 2
            and not self._axes_conflict()
        )

    def page_column(self) -> str:
        text = self.page_combo.currentText()
        if text == _NONE_PAGE:
            return ""
        return text

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SarMatrixDialogParams:
        return SarMatrixDialogParams(
            row_column=self.row_combo.currentText(),
            column_column=self.col_combo.currentText(),
            page_column=self.page_column(),
            activity_column=self.activity_combo.currentText(),
            higher_is_better=self.higher_cb.isChecked(),
            only_selected=self.only_selected_rows(),
        )
