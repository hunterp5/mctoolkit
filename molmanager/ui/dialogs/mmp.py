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

"""Matched molecular pair (MMP) analysis dialog (Data → MMP)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..table_dataframe import numeric_subset, table_to_dataframe
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


@dataclass(frozen=True)
class MmpDialogParams:
    """Arguments from :class:`MmpDialog` for the worker."""

    structure_source: str
    activity_column: str
    max_cuts: int
    max_variable_heavy_atoms: int
    min_activity_difference: float
    max_activity_difference: float
    core_smarts: str


class MmpDialog(QDialog):
    """Configure matched molecular pair analysis on table structures and an activity column."""

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
        self.setWindowTitle("Matched Molecular Pairs (MMP)")
        self.setMinimumWidth(480)
        self.resize(540, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

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
        self.activity_combo.setToolTip(
            "Biological activity (or other numeric property) used to compute Δactivity for each pair."
        )
        form.addRow("Activity column:", self.activity_combo)

        self.min_dact_sb = QDoubleSpinBox()
        self.min_dact_sb.setDecimals(6)
        self.min_dact_sb.setRange(0.0, 1e12)
        self.min_dact_sb.setValue(0.0)
        self.min_dact_sb.setSingleStep(0.1)
        self.min_dact_sb.setToolTip(
            "Report only pairs whose absolute activity difference is at least this value. "
            "0 reports all pairs."
        )
        form.addRow("Minimum activity difference:", self.min_dact_sb)

        self.max_dact_sb = QDoubleSpinBox()
        self.max_dact_sb.setDecimals(6)
        self.max_dact_sb.setRange(0.0, 1e12)
        self.max_dact_sb.setValue(0.0)
        self.max_dact_sb.setSingleStep(0.1)
        self.max_dact_sb.setToolTip(
            "Report only pairs whose absolute activity difference is at most this value. "
            "0 disables the upper bound."
        )
        form.addRow("Maximum activity difference:", self.max_dact_sb)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        root.addWidget(activity)

        core = QGroupBox("Core")
        core_form = QFormLayout(core)
        core_row = QHBoxLayout()
        core_row.setSpacing(6)
        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("Optional SMARTS or SMILES (constant core / MCS)")
        self.core_edit.setToolTip(
            "When set, only molecules containing this substructure are analyzed, and only "
            "MMP fragmentations whose constant core still contains it are kept. "
            "Use SMARTS or SMILES (for example an MCS)."
        )
        core_row.addWidget(self.core_edit, 1)
        self.core_mcs_btn = QPushButton("MCS from selection")
        self.core_mcs_btn.setToolTip(
            "Compute a maximum common substructure SMARTS from the currently selected "
            "table molecules (at least two) and fill this field."
        )
        self.core_mcs_btn.setEnabled(self._have_selection and selected_row_count >= 2)
        self.core_mcs_btn.clicked.connect(self._fill_core_from_selection_mcs)
        core_row.addWidget(self.core_mcs_btn)
        core_form.addRow("Core / MCS:", core_row)
        root.addWidget(core)

        fragments = QGroupBox("Fragmentation")
        frag_form = QFormLayout(fragments)
        self.max_cuts_sb = QSpinBox()
        self.max_cuts_sb.setRange(1, 3)
        self.max_cuts_sb.setValue(1)
        self.max_cuts_sb.setToolTip(
            "Maximum number of acyclic cuts (1 = classic single-point MMP transforms)."
        )
        frag_form.addRow("Max cuts:", self.max_cuts_sb)

        self.max_var_atoms_sb = QSpinBox()
        self.max_var_atoms_sb.setRange(1, 50)
        self.max_var_atoms_sb.setValue(13)
        self.max_var_atoms_sb.setToolTip(
            "Ignore pairs whose changing fragment exceeds this many heavy atoms."
        )
        frag_form.addRow("Max variable heavy atoms:", self.max_var_atoms_sb)
        root.addWidget(fragments)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(bool(activity_columns))
        root.addWidget(box)
        make_window_minimizable(self)

    def _fill_core_from_selection_mcs(self) -> None:
        app = self.parent_app
        if app is None:
            return
        try:
            oids = sorted(int(o) for o in app._selected_oids_set())
        except Exception:
            oids = []
        if len(oids) < 2:
            QMessageBox.information(
                self,
                "MMP",
                "Select at least two table molecules to compute an MCS.",
            )
            return
        mols = []
        for oid in oids:
            mol = getattr(app, "mols", {}).get(int(oid))
            if mol is not None:
                mols.append(mol)
        if len(mols) < 2:
            QMessageBox.information(
                self,
                "MMP",
                "Need at least two selected molecules with valid structures.",
            )
            return
        from ...analysis.mmp_analysis import compute_mcs_smarts

        smarts = compute_mcs_smarts(mols)
        if not smarts:
            QMessageBox.information(
                self,
                "MMP",
                "Could not find a maximum common substructure for the selection.",
            )
            return
        self.core_edit.setText(smarts)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> MmpDialogParams:
        return MmpDialogParams(
            structure_source=self.src_combo.currentText(),
            activity_column=self.activity_combo.currentText(),
            max_cuts=int(self.max_cuts_sb.value()),
            max_variable_heavy_atoms=int(self.max_var_atoms_sb.value()),
            min_activity_difference=float(self.min_dact_sb.value()),
            max_activity_difference=float(self.max_dact_sb.value()),
            core_smarts=self.core_edit.text().strip(),
        )


def activity_columns_for_mmp(parent_app, *, only_selected: bool = False) -> list[str]:
    """Numeric table columns suitable as MMP activity (Y) inputs."""
    if parent_app is None:
        return []
    try:
        df, _ = table_to_dataframe(
            parent_app,
            visible_only=False,
            only_selected=only_selected,
        )
        num = numeric_subset(df, exclude_id=True)
        return [str(c) for c in num.columns]
    except Exception:
        return []


def index_of_preferred_activity_column(
    names: list[str],
    *,
    keyword: str = "ic50",
) -> int:
    """First index whose header contains ``keyword`` (case-insensitive), else ``0``."""
    if not names:
        return -1
    key = (keyword or "ic50").casefold()
    for i, name in enumerate(names):
        text = str(name or "")
        if text.startswith("("):
            continue
        if key in text.casefold():
            return i
    return 0


def select_preferred_activity_column(combo: QComboBox, *, keyword: str = "ic50") -> None:
    """Default an Activity combo to a column whose name contains ``keyword`` when present."""
    if combo is None or combo.count() <= 0 or not combo.isEnabled():
        return
    names = [combo.itemText(i) for i in range(combo.count())]
    idx = index_of_preferred_activity_column(names, keyword=keyword)
    if idx >= 0:
        combo.setCurrentIndex(idx)
