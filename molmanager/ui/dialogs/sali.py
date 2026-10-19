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
    QLabel,
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

_PACTIVITY_TIP = (
    "Use a higher-is-more-potent scale such as pIC50 or pKi. "
    "Raw IC50 in nM lets large weak values dominate |Δ|. "
    "Convert with Tools → Potency Standardization; SALI does not convert units."
)


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
    off_target_column: str = ""


class SaliDialog(QDialog):
    """Configure a fingerprint SALI map on one activity or on selectivity."""

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
        self._form = form
        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Activity", "activity")
        self.mode_combo.addItem("Selectivity", "selectivity")
        self.mode_combo.setToolTip(
            "Activity compares one column. Selectivity uses on-target minus off-target "
            "on a pIC50 or pKi scale (larger means more potent)."
        )
        form.addRow("Analysis:", self.mode_combo)

        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(220)
        if activity_columns:
            self.activity_combo.addItems(activity_columns)
            select_preferred_activity_column(self.activity_combo)
        else:
            self.activity_combo.addItem("(no numeric columns)")
            self.activity_combo.setEnabled(False)
        self.activity_combo.setToolTip(
            "Numeric activity used for Δactivity and SALI. " + _PACTIVITY_TIP
        )
        self._activity_label = QLabel("Activity column:")
        form.addRow(self._activity_label, self.activity_combo)

        self.off_combo = QComboBox()
        self.off_combo.setMinimumWidth(220)
        if activity_columns:
            self.off_combo.addItems(activity_columns)
            self._select_default_off_target()
        else:
            self.off_combo.addItem("(no numeric columns)")
            self.off_combo.setEnabled(False)
        self.off_combo.setToolTip(
            "Off-target activity. Selectivity = on-target − off-target. " + _PACTIVITY_TIP
        )
        self._off_label = QLabel("Off-target:")
        form.addRow(self._off_label, self.off_combo)

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
        self._min_diff_label = QLabel("Minimum activity difference:")
        form.addRow(self._min_diff_label, self.min_dact_sb)

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
        self._ok_button = box.button(QDialogButtonBox.Ok)
        self._has_activity = bool(activity_columns)
        root.addWidget(box)
        self.mode_combo.currentIndexChanged.connect(self._sync_mode)
        self.activity_combo.currentIndexChanged.connect(self._on_activity_changed)
        self.off_combo.currentIndexChanged.connect(self._refresh_ok)
        self._sync_mode()
        make_window_minimizable(self)

    def _selectivity_mode(self) -> bool:
        return self.mode_combo.currentData() == "selectivity"

    def _set_off_row_visible(self, visible: bool) -> None:
        self._off_label.setVisible(visible)
        self.off_combo.setVisible(visible)
        height = 16777215 if visible else 0
        self._off_label.setMaximumHeight(height)
        self.off_combo.setMaximumHeight(height)
        setter = getattr(self._form, "setRowVisible", None)
        if callable(setter):
            setter(self.off_combo, visible)

    def _select_default_off_target(self) -> None:
        on = self.activity_combo.currentText().casefold()
        for i in range(self.off_combo.count()):
            text = self.off_combo.itemText(i)
            if "off" in text.casefold() and text.casefold() != on:
                self.off_combo.setCurrentIndex(i)
                return
        self._ensure_distinct_off_target()

    def _ensure_distinct_off_target(self) -> None:
        on = self.activity_combo.currentText()
        if self.off_combo.currentText() != on:
            return
        for i in range(self.off_combo.count()):
            if self.off_combo.itemText(i) != on:
                self.off_combo.setCurrentIndex(i)
                return

    def _on_activity_changed(self) -> None:
        if self._selectivity_mode():
            self._ensure_distinct_off_target()
        self._refresh_ok()

    def _sync_mode(self) -> None:
        selective = self._selectivity_mode()
        self._set_off_row_visible(selective)
        self._activity_label.setText("On-target:" if selective else "Activity column:")
        self._min_diff_label.setText(
            "Minimum |Δselectivity|:" if selective else "Minimum activity difference:"
        )
        if selective:
            self.activity_combo.setToolTip("On-target activity. " + _PACTIVITY_TIP)
            self.min_dact_sb.setToolTip(
                "Keep only pairs whose absolute selectivity difference is at least this value."
            )
            self._ensure_distinct_off_target()
        else:
            self.activity_combo.setToolTip(
                "Numeric activity used for Δactivity and SALI. " + _PACTIVITY_TIP
            )
            self.min_dact_sb.setToolTip(
                "Keep only pairs whose absolute activity difference is at least this value."
            )
        self._refresh_ok()

    def _refresh_ok(self) -> None:
        if self._ok_button is None:
            return
        if not self._has_activity:
            self._ok_button.setEnabled(False)
            return
        if self._selectivity_mode():
            on = self.activity_combo.currentText().strip()
            off = self.off_combo.currentText().strip()
            self._ok_button.setEnabled(bool(on) and bool(off) and on != off)
            return
        self._ok_button.setEnabled(True)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> SaliDialogParams:
        off = ""
        if self._selectivity_mode():
            off = self.off_combo.currentText().strip()
        return SaliDialogParams(
            structure_source=self.src_combo.currentText(),
            activity_column=self.activity_combo.currentText(),
            fp_choice=self.fp_combo.currentText(),
            metric=self.metric_combo.currentText(),
            min_similarity=float(self.min_sim_sb.value()),
            min_activity_difference=float(self.min_dact_sb.value()),
            max_pairs=int(self.max_pairs_sb.value()),
            off_target_column=off,
        )


__all__ = ["SaliDialog", "SaliDialogParams", "activity_columns_for_mmp"]
