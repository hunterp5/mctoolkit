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

"""Chemistry → Substructure dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ...chem.murcko import SCAFFOLD_COLUMNS
from ..qt_widget_utils import boxed_form, make_window_minimizable
from ..strings import TOOL_BEMIS_MURCKO, TOOL_COMMON_CORE
from .scope import selection_scope_checked


def _target_row(parent: QDialog, columns: list[str], selected_row_count: int):
    """Target column, selected-rows checkbox, and whether a selection exists."""
    row = QHBoxLayout()
    row.addWidget(QLabel("Target Column:"))
    combo = QComboBox(parent)
    combo.addItems([c for c in columns if (c or "").strip()])
    row.addWidget(combo, 1)
    selected = QCheckBox("Selected Rows Only", parent)
    count = int(selected_row_count)
    if count > 0:
        selected.setText(f"Selected Rows Only ({count} row(s))")
    else:
        selected.setEnabled(False)
    row.addWidget(selected)
    return row, combo, selected


class BemisMurckoDialog(QDialog):
    """Choose which Bemis–Murcko columns to write."""

    def __init__(self, columns, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_BEMIS_MURCKO)
        self.resize(480, 280)
        self._checks: dict[str, tuple[QCheckBox, str]] = {}
        root = QVBoxLayout(self)
        structures = QGroupBox("Structures")
        struct_ly = QVBoxLayout(structures)
        struct_ly.setContentsMargins(8, 6, 8, 6)
        target, self.src_combo, self.only_selected_cb = _target_row(
            self, list(columns), selected_row_count
        )
        self._only_selected_scope_prefix = "Selected Rows Only"
        struct_ly.addLayout(target)
        root.addWidget(structures)

        columns_box = QGroupBox("Columns")
        columns_ly = QVBoxLayout(columns_box)
        columns_ly.setContentsMargins(8, 6, 8, 6)
        columns_ly.setSpacing(4)
        for header, internal, tip in SCAFFOLD_COLUMNS:
            box = QCheckBox(header)
            box.setChecked(True)
            box.setToolTip(tip)
            columns_ly.addWidget(box)
            self._checks[header] = (box, internal)
        root.addWidget(columns_box)
        root.addStretch(1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not any(box.isChecked() for box, _internal in self._checks.values()):
            QMessageBox.information(self, TOOL_BEMIS_MURCKO, "Choose at least one column.")
            return
        self.accept()

    def get_selected(self) -> tuple[list[str], list[str]]:
        headers: list[str] = []
        keys: list[str] = []
        for header, (box, internal) in self._checks.items():
            if box.isChecked():
                headers.append(header)
                keys.append(internal)
        return headers, keys

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)


@dataclass(frozen=True)
class CommonCoreDialogParams:
    """Arguments from :class:`CommonCoreDialog`."""

    structure_source: str
    outliers: int
    complete_rings: bool
    timeout: int


class CommonCoreDialog(QDialog):
    """MCS over the chosen rows, with a cap on how many structures may miss the core."""

    def __init__(self, columns, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_COMMON_CORE)
        self.setMinimumWidth(460)
        root = QVBoxLayout(self)
        structures = QGroupBox("Structures")
        struct_ly = QVBoxLayout(structures)
        struct_ly.setContentsMargins(8, 6, 8, 6)
        target, self.src_combo, self.only_selected_cb = _target_row(
            self, list(columns), selected_row_count
        )
        self._only_selected_scope_prefix = "Selected Rows Only"
        struct_ly.addLayout(target)
        root.addWidget(structures)

        _search, form = boxed_form("Search")
        self.outliers = QSpinBox()
        self.outliers.setRange(0, 100_000)
        self.outliers.setValue(0)
        self.outliers.setToolTip(
            "How many structures may lack the core. The search still requires the core "
            "in at least two molecules."
        )
        form.addRow("Outliers to ignore:", self.outliers)

        self.timeout = QSpinBox()
        self.timeout.setRange(1, 600)
        self.timeout.setValue(30)
        self.timeout.setSuffix(" s")
        self.timeout.setToolTip("Stop the search if it runs longer than this.")
        form.addRow("Time limit:", self.timeout)

        self.complete_rings = QCheckBox("Complete rings only")
        self.complete_rings.setChecked(True)
        self.complete_rings.setToolTip(
            "Keep the core from ending in the middle of a ring, so it can be pasted "
            "into Structure Decomposition → Core-Based or Free-Wilson."
        )
        form.addRow("", self.complete_rings)
        root.addWidget(_search)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> CommonCoreDialogParams:
        return CommonCoreDialogParams(
            structure_source=self.src_combo.currentText(),
            outliers=int(self.outliers.value()),
            complete_rings=bool(self.complete_rings.isChecked()),
            timeout=int(self.timeout.value()),
        )
