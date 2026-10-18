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

"""Free-Wilson setup dialog (Data → Free-Wilson)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ...analysis.free_wilson import (
    DEFAULT_MAX_NEW_STRUCTURES,
    DEFAULT_MIN_COUNT,
    REPORT_FREE_WILSON,
    REPORT_FUJITA_BAN,
    FreeWilsonSettings,
)
from ...platform_support.memory_guards import clamp_max_products_ui
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_FREE_WILSON
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked


@dataclass(frozen=True)
class FreeWilsonDialogParams:
    """Arguments from :class:`FreeWilsonDialog`."""

    structure_source: str
    settings: FreeWilsonSettings


class FreeWilsonDialog(QDialog):
    """Core, activity column, and additive-model options for a congeneric series."""

    def __init__(
        self,
        *,
        structure_sources: list[str],
        activity_columns: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_FREE_WILSON)
        self.setMinimumWidth(480)
        self.resize(560, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        form = QFormLayout()

        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(220)
        if activity_columns:
            self.activity_combo.addItems(activity_columns)
            select_preferred_activity_column(self.activity_combo)
        else:
            self.activity_combo.addItem("(no numeric columns)")
            self.activity_combo.setEnabled(False)
        self.activity_combo.setToolTip(
            "Numeric activity fitted as an additive sum of substituent contributions."
        )
        form.addRow("Activity column:", self.activity_combo)

        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("e.g. c1ccc([*:1])cc1[*:2] or SMARTS with dummy labels")
        self.core_edit.setToolTip(
            "Shared core, parsed as SMARTS first, then as SMILES. Label each attachment "
            "point with a dummy atom ([*:1], [*:2], …)."
        )
        form.addRow("Core (SMARTS or SMILES):", self.core_edit)

        self.report_combo = QComboBox()
        self.report_combo.addItem("Fujita-Ban (vs reference)", REPORT_FUJITA_BAN)
        self.report_combo.addItem("Free-Wilson (sum to zero)", REPORT_FREE_WILSON)
        self.report_combo.setToolTip(
            "Both reports are the same fit. Fujita-Ban is the change versus hydrogen "
            "when that position has it, otherwise the most common substituent. "
            "Free-Wilson recenters each position so occurrence-weighted coefficients sum to zero."
        )
        form.addRow("Coefficient report:", self.report_combo)

        self.min_count_sb = QSpinBox()
        self.min_count_sb.setRange(1, 100)
        self.min_count_sb.setValue(DEFAULT_MIN_COUNT)
        self.min_count_sb.setToolTip(
            "Substituents seen fewer times than this are left out, and molecules that "
            "contain them are not fitted."
        )
        form.addRow("Minimum substituent count:", self.min_count_sb)

        hard_cap = clamp_max_products_ui(1_000_000_000)
        self.max_new_sb = QSpinBox()
        self.max_new_sb.setRange(1, hard_cap)
        self.max_new_sb.setValue(min(DEFAULT_MAX_NEW_STRUCTURES, hard_cap))
        self.max_new_sb.setToolTip(
            "Maximum number of missing substituent combinations to list. "
            "When there are more, only this many are kept."
        )
        form.addRow("Max new structures:", self.max_new_sb)

        self.direction_combo = QComboBox()
        self.direction_combo.addItem("Highest predicted activity", True)
        self.direction_combo.addItem("Lowest predicted activity", False)
        self.direction_combo.setToolTip(
            "Used only when missing combinations exceed Max new structures."
        )
        form.addRow("If the list is capped, keep:", self.direction_combo)

        self.match_combo = QComboBox()
        self.match_combo.addItems(["Greedy", "Exhaustive"])
        self.match_combo.setToolTip("Greedy is faster; Exhaustive explores more core matchings.")
        form.addRow("Matching strategy:", self.match_combo)

        self.only_rg_cb = QCheckBox("Only match at R-groups")
        self.only_rg_cb.setChecked(True)
        self.only_rg_cb.setToolTip(
            "When the core labels attachment points, require the match to use those dummies."
        )
        form.addRow(self.only_rg_cb)
        root.addLayout(form)

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
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(bool(activity_columns))
        root.addWidget(box)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not (self.core_edit.text() or "").strip():
            QMessageBox.warning(self, TOOL_FREE_WILSON, "Enter a core SMARTS or SMILES.")
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> FreeWilsonDialogParams:
        report = self.report_combo.currentData()
        direction = self.direction_combo.currentData()
        strat = self.match_combo.currentText().strip().lower()
        return FreeWilsonDialogParams(
            structure_source=self.src_combo.currentText(),
            settings=FreeWilsonSettings(
                core_query=(self.core_edit.text() or "").strip(),
                activity_column=self.activity_combo.currentText(),
                report=str(report or REPORT_FUJITA_BAN),
                min_count=int(self.min_count_sb.value()),
                max_new_structures=int(self.max_new_sb.value()),
                prefer_higher=True if direction is None else bool(direction),
                only_match_at_r_groups=bool(self.only_rg_cb.isChecked()),
                matching="exhaustive" if strat.startswith("exhaustive") else "greedy",
            ),
        )
