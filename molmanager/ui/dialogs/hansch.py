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

"""Hansch setup dialog (Data → Hansch)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...analysis.hansch import (
    ELECTRONIC_FIELD_RESONANCE,
    ELECTRONIC_NONE,
    ELECTRONIC_SIGMA,
    SIGMA_META,
    SIGMA_PARA,
    STERIC_ES,
    STERIC_MR,
    STERIC_NONE,
    STERIC_UPSILON,
    HanschSettings,
    parse_sigma_assignments,
    settings_error,
)
from ...analysis.substituent_constants import load_substituent_constants
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_HANSCH
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked

_CSV_FILTER = "CSV (*.csv);;All files (*)"


@dataclass(frozen=True)
class HanschDialogParams:
    """Arguments from :class:`HanschDialog`."""

    structure_source: str
    settings: HanschSettings


class HanschDialog(QDialog):
    """Core, constants file, and Hansch terms for a congeneric series."""

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
        self.setWindowTitle(TOOL_HANSCH)
        self.setMinimumWidth(520)
        self.resize(640, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        root.addWidget(self._activity_box(structure_sources, activity_columns, selected_row_count))
        root.addWidget(self._core_box())
        root.addWidget(self._constants_box())
        root.addWidget(self._terms_box())

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(bool(activity_columns))
        root.addWidget(box)
        self._sync_term_widgets()
        make_window_minimizable(self)

    def _activity_box(
        self,
        structure_sources: list[str],
        activity_columns: list[str],
        selected_row_count: int,
    ) -> QGroupBox:
        activity = QGroupBox("Activity")
        form = QFormLayout(activity)
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
        self.activity_combo.setToolTip("Numeric activity fitted to the Hansch equation.")
        form.addRow("Activity column:", self.activity_combo)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        return activity

    def _core_box(self) -> QGroupBox:
        core = QGroupBox("Core")
        form = QFormLayout(core)
        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("e.g. c1ccc([*:1])cc1[*:2] or SMARTS with dummy labels")
        self.core_edit.setToolTip(
            "Shared core, parsed as SMARTS first, then as SMILES. Label each attachment "
            "point with a dummy atom ([*:1], [*:2], …)."
        )
        form.addRow("Core (SMARTS or SMILES):", self.core_edit)

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
        return core

    def _constants_box(self) -> QGroupBox:
        box = QGroupBox("Constants")
        form = QFormLayout(box)
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        self.constants_edit = QLineEdit()
        self.constants_edit.setPlaceholderText("CSV of attachment SMILES and substituent constants")
        self.constants_edit.setToolTip(
            "Local CSV. The smiles column is H for hydrogen and an attachment SMILES "
            "such as *C or *Cl for other groups. Es is used as stored."
        )
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_constants)
        layout.addWidget(self.constants_edit, 1)
        layout.addWidget(browse)
        form.addRow("Constants file:", row)
        return box

    def _terms_box(self) -> QGroupBox:
        box = QGroupBox("Terms")
        form = QFormLayout(box)
        self.pi_cb = QCheckBox("π")
        self.pi_cb.setChecked(True)
        self.pi_cb.toggled.connect(self._sync_term_widgets)
        form.addRow("Hydrophobic:", self.pi_cb)

        self.pi2_cb = QCheckBox("π²")
        self.pi2_cb.setToolTip("Square of π at each position. Requires π in the constants file.")
        form.addRow("", self.pi2_cb)

        self.electronic_combo = QComboBox()
        self.electronic_combo.addItem("Hammett σ", ELECTRONIC_SIGMA)
        self.electronic_combo.addItem("Field and resonance (F, R)", ELECTRONIC_FIELD_RESONANCE)
        self.electronic_combo.addItem("None", ELECTRONIC_NONE)
        self.electronic_combo.currentIndexChanged.connect(self._sync_term_widgets)
        form.addRow("Electronic:", self.electronic_combo)

        self.sigma_default_combo = QComboBox()
        self.sigma_default_combo.addItem("Para", SIGMA_PARA)
        self.sigma_default_combo.addItem("Meta", SIGMA_META)
        self.sigma_default_combo.setToolTip("Used for every position that is not listed below.")
        form.addRow("Default σ:", self.sigma_default_combo)

        self.sigma_edit = QLineEdit()
        self.sigma_edit.setPlaceholderText("R1=meta, R2=para")
        self.sigma_edit.setToolTip(
            "Optional per-position override. Unlisted positions use the default."
        )
        form.addRow("σ by position:", self.sigma_edit)

        self.steric_combo = QComboBox()
        self.steric_combo.addItem("None", STERIC_NONE)
        self.steric_combo.addItem("Es", STERIC_ES)
        self.steric_combo.addItem("Molar refractivity", STERIC_MR)
        self.steric_combo.addItem("υ", STERIC_UPSILON)
        self.steric_combo.setToolTip(
            "One steric column per position. Es is used on the scale stored in the file."
        )
        form.addRow("Steric:", self.steric_combo)
        return box

    def _sync_term_widgets(self) -> None:
        electronic = self.electronic_combo.currentData()
        sigma = electronic == ELECTRONIC_SIGMA
        self.sigma_default_combo.setEnabled(sigma)
        self.sigma_edit.setEnabled(sigma)
        if not self.pi_cb.isChecked():
            self.pi2_cb.setChecked(False)
        self.pi2_cb.setEnabled(self.pi_cb.isChecked())

    def _browse_constants(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Substituent constants",
            self.constants_edit.text(),
            _CSV_FILTER,
        )
        if path:
            self.constants_edit.setText(path)

    def _on_accept(self) -> None:
        try:
            self.params()
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_HANSCH, str(exc))
            return
        problem = settings_error(self.params().settings)
        if problem:
            QMessageBox.warning(self, TOOL_HANSCH, problem)
            return
        try:
            load_substituent_constants(self.params().settings.constants_path)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_HANSCH, str(exc))
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> HanschDialogParams:
        assignments = parse_sigma_assignments(self.sigma_edit.text())
        strat = self.match_combo.currentText().strip().lower()
        electronic = self.electronic_combo.currentData()
        steric = self.steric_combo.currentData()
        sigma_default = self.sigma_default_combo.currentData()
        return HanschDialogParams(
            structure_source=self.src_combo.currentText(),
            settings=HanschSettings(
                core_query=(self.core_edit.text() or "").strip(),
                constants_path=(self.constants_edit.text() or "").strip(),
                activity_column=self.activity_combo.currentText(),
                include_pi=bool(self.pi_cb.isChecked()),
                include_pi_squared=bool(self.pi2_cb.isChecked()),
                electronic=str(electronic or ELECTRONIC_SIGMA),
                sigma_default=str(sigma_default or SIGMA_PARA),
                sigma_positions=tuple(sorted(assignments.items())),
                steric=str(steric or STERIC_NONE),
                only_match_at_r_groups=bool(self.only_rg_cb.isChecked()),
                matching="exhaustive" if strat.startswith("exhaustive") else "greedy",
            ),
        )
