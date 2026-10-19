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

"""Random Number column dialog (Tools → Random → Number)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...table.random_number_columns import (
    RANDOM_NUMBER_DISTRIBUTION_LABELS,
    DistributionName,
    RandomNumberParams,
    generate_random_values,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_RANDOM_NUMBER
from .scope import selection_scope_checked


def _inline_field(*widgets: QWidget) -> QWidget:
    """Spinbox plus trailing checkboxes on one form-row field."""
    host = QWidget()
    row = QHBoxLayout(host)
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(8)
    for widget in widgets:
        stretch = 0 if isinstance(widget, QCheckBox) else 1
        row.addWidget(widget, stretch, Qt.AlignVCenter)
    return host


@dataclass(frozen=True)
class RandomNumberDialogParams:
    """Validated settings from :class:`RandomNumberDialog`."""

    column_name: str
    params: RandomNumberParams


class RandomNumberDialog(QDialog):
    """Fill a new column with random numbers for in-scope rows (unique name if needed)."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_random_number_state(selected_row_count)
        self._build_random_number_ui()
        self._wire_random_number_ui()

    def _init_random_number_state(self, selected_row_count: int) -> None:
        self.setWindowTitle(TOOL_RANDOM_NUMBER)
        self.setMinimumWidth(480)
        self.resize(520, 0)
        self._selected_row_count = int(selected_row_count)
        self._have_selection = selected_row_count > 0

    def _build_random_number_ui(self) -> None:
        selected_row_count = self._selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.name_input = QLineEdit()
        self.name_input.setText("Random")
        self.name_input.setPlaceholderText("Column name")
        self.name_input.setToolTip(
            "Values are written to a new column with this name. "
            "If the name already exists, a suffix like (1) is added so the existing column is kept."
        )
        form.addRow("Column name:", self.name_input)

        self.dist_combo = QComboBox()
        for key, label in RANDOM_NUMBER_DISTRIBUTION_LABELS:
            self.dist_combo.addItem(label, key)
        self.dist_combo.setToolTip("Distribution used to draw each row’s value.")
        form.addRow("Distribution:", self.dist_combo)

        self.min_sb = QDoubleSpinBox()
        self.min_sb.setDecimals(6)
        self.min_sb.setRange(-1e12, 1e12)
        self.min_sb.setValue(0.0)
        form.addRow("Minimum:", self.min_sb)

        self.max_sb = QDoubleSpinBox()
        self.max_sb.setDecimals(6)
        self.max_sb.setRange(-1e12, 1e12)
        self.max_sb.setValue(1.0)
        self.clip_cb = QCheckBox("Clip to min/max")
        self.clip_cb.setChecked(False)
        self.clip_cb.setToolTip("Clip normal draws to the min/max range.")
        form.addRow("Maximum:", _inline_field(self.max_sb, self.clip_cb))

        self.mean_sb = QDoubleSpinBox()
        self.mean_sb.setDecimals(6)
        self.mean_sb.setRange(-1e12, 1e12)
        self.mean_sb.setValue(0.0)
        form.addRow("Mean:", self.mean_sb)

        self.std_sb = QDoubleSpinBox()
        self.std_sb.setDecimals(6)
        self.std_sb.setRange(1e-12, 1e12)
        self.std_sb.setValue(1.0)
        form.addRow("Std. deviation:", self.std_sb)

        self.decimals_sb = QSpinBox()
        self.decimals_sb.setRange(0, 12)
        self.decimals_sb.setValue(4)
        self.decimals_sb.setToolTip(
            "Decimal places for continuous distributions (ignored for integers)."
        )
        form.addRow("Decimals:", self.decimals_sb)

        self.use_seed_cb = QCheckBox("Use seed")
        self.use_seed_cb.setChecked(False)
        self.seed_sb = QSpinBox()
        self.seed_sb.setRange(0, 2_147_483_647)
        self.seed_sb.setValue(0)
        self.seed_sb.setEnabled(False)
        self.seed_sb.setToolTip("Fixed seed for reproducible draws.")
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("Seed:", _inline_field(self.seed_sb, self.use_seed_cb, self.only_selected_cb))
        root.addLayout(form)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        root.addWidget(self._button_box)

    def _wire_random_number_ui(self) -> None:
        self.dist_combo.currentIndexChanged.connect(self._sync_distribution_fields)
        self.clip_cb.toggled.connect(self._sync_clip_bounds)
        self.use_seed_cb.toggled.connect(self._sync_seed_enabled)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)
        self._sync_distribution_fields()
        make_window_minimizable(self)

    def _distribution_key(self) -> DistributionName:
        data = self.dist_combo.currentData()
        if data in {"uniform", "integer", "normal"}:
            return data
        return "uniform"

    def _sync_distribution_fields(self) -> None:
        dist = self._distribution_key()
        is_normal = dist == "normal"
        is_integer = dist == "integer"
        self.mean_sb.setEnabled(is_normal)
        self.std_sb.setEnabled(is_normal)
        self.clip_cb.setEnabled(is_normal)
        self.decimals_sb.setEnabled(not is_integer)
        if is_normal:
            self._sync_clip_bounds(self.clip_cb.isChecked())
        else:
            self.min_sb.setEnabled(True)
            self.max_sb.setEnabled(True)

    def _sync_clip_bounds(self, checked: bool) -> None:
        if self._distribution_key() != "normal":
            return
        self.min_sb.setEnabled(bool(checked))
        self.max_sb.setEnabled(bool(checked))

    def _sync_seed_enabled(self, checked: bool) -> None:
        self.seed_sb.setEnabled(bool(checked))

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> RandomNumberDialogParams:
        name = (self.name_input.text() or "").strip()
        seed = int(self.seed_sb.value()) if self.use_seed_cb.isChecked() else None
        return RandomNumberDialogParams(
            column_name=name,
            params=RandomNumberParams(
                distribution=self._distribution_key(),
                low=float(self.min_sb.value()),
                high=float(self.max_sb.value()),
                mean=float(self.mean_sb.value()),
                std=float(self.std_sb.value()),
                seed=seed,
                decimals=int(self.decimals_sb.value()),
                clip_normal=bool(self.clip_cb.isChecked()),
            ),
        )

    def accept(self) -> None:
        if not (self.name_input.text() or "").strip():
            QMessageBox.warning(self, TOOL_RANDOM_NUMBER, "Enter a name for the output column.")
            self.name_input.setFocus(Qt.OtherFocusReason)
            return
        try:
            generate_random_values(1, self.params().params)
        except ValueError as exc:
            QMessageBox.warning(
                self, TOOL_RANDOM_NUMBER, str(exc) or "Invalid random-number settings."
            )
            return
        super().accept()
