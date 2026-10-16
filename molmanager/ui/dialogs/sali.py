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

"""SALI configuration dialog (Data → SALI)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QSpinBox,
    QVBoxLayout,
)

from ...workers import SIMILARITY_FP_TYPE_LABELS, SIMILARITY_METRIC_LABELS
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_SALI_MAP
from .mmp import activity_columns_for_mmp, select_preferred_activity_column
from .scope import selection_scope_checked

# Radius 3 / 2048 bits, so close analogs are less likely to share one fingerprint.
_DEFAULT_SALI_FINGERPRINT = "Morgan (r=3, n=2048)"


@dataclass(frozen=True)
class SaliDialogParams:
    """Arguments for the SALI analysis worker."""

    structure_source: str
    activity_column: str
    fp_choice: str
    metric: str
    min_similarity: float
    min_activity_difference: float
    max_pairs: int


class SaliDialog(QDialog):
    """Configure fingerprint-based SALI landscape on a numeric activity column."""

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
        self.setWindowTitle(TOOL_SALI_MAP)
        self.setMinimumWidth(460)
        self.resize(520, 0)
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
        self.activity_combo.setToolTip("Numeric activity used for Δactivity and SALI.")
        form.addRow("Activity column:", self.activity_combo)

        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        default_fp = self.fp_combo.findText(_DEFAULT_SALI_FINGERPRINT)
        if default_fp >= 0:
            self.fp_combo.setCurrentIndex(default_fp)
        self.fp_combo.setToolTip(
            "Fingerprint for pairwise chemical similarity. "
            "Morgan radius 3 with 2048 bits is the default so close analogs "
            "are less likely to share an identical fingerprint."
        )
        form.addRow("Fingerprint:", self.fp_combo)

        self.metric_combo = QComboBox()
        self.metric_combo.addItems(SIMILARITY_METRIC_LABELS)
        self.metric_combo.setToolTip("Similarity metric (Tanimoto recommended for SALI).")
        form.addRow("Similarity metric:", self.metric_combo)

        self.min_sim_sb = QDoubleSpinBox()
        self.min_sim_sb.setDecimals(3)
        self.min_sim_sb.setRange(0.0, 1.0)
        self.min_sim_sb.setSingleStep(0.05)
        self.min_sim_sb.setValue(0.30)
        self.min_sim_sb.setToolTip(
            "Keep only pairs at or above this fingerprint similarity (0 = all pairs)."
        )
        form.addRow("Minimum similarity:", self.min_sim_sb)

        self.min_dact_sb = QDoubleSpinBox()
        self.min_dact_sb.setDecimals(6)
        self.min_dact_sb.setRange(0.0, 1e12)
        self.min_dact_sb.setValue(0.0)
        self.min_dact_sb.setSingleStep(0.1)
        self.min_dact_sb.setToolTip(
            "Keep only pairs whose absolute activity difference is at least this value."
        )
        form.addRow("Minimum activity difference:", self.min_dact_sb)

        self.max_pairs_sb = QSpinBox()
        self.max_pairs_sb.setRange(100, 200000)
        self.max_pairs_sb.setValue(10000)
        self.max_pairs_sb.setSingleStep(500)
        self.max_pairs_sb.setToolTip(
            "Maximum pairs to plot (highest SALI kept when more pairs qualify)."
        )
        form.addRow("Max pairs to plot:", self.max_pairs_sb)
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
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        ok = box.button(QDialogButtonBox.Ok)
        if ok is not None:
            ok.setEnabled(bool(activity_columns))
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SaliDialogParams:
        return SaliDialogParams(
            structure_source=self.src_combo.currentText(),
            activity_column=self.activity_combo.currentText(),
            fp_choice=self.fp_combo.currentText(),
            metric=self.metric_combo.currentText(),
            min_similarity=float(self.min_sim_sb.value()),
            min_activity_difference=float(self.min_dact_sb.value()),
            max_pairs=int(self.max_pairs_sb.value()),
        )


__all__ = ["SaliDialog", "SaliDialogParams", "activity_columns_for_mmp"]
