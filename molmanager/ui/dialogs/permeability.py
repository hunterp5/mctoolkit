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

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...predictions.permeability_prediction import PERMEABILITY_ENDPOINT_OPTIONS
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class PermeabilityPredictorDialog(QDialog):
    """Predict Caco-2 / MDCK permeability and efflux endpoints (Chemprop GNN-MTL)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Predict Permeability")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_form = QFormLayout(structures)
        struct_form.setContentsMargins(8, 6, 8, 6)
        struct_form.setSpacing(4)
        struct_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(160)
        struct_form.addRow("Structure source:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        struct_form.addRow("", self.only_selected_cb)
        root.addWidget(structures)

        endpoints_box = QGroupBox("Cell lines / endpoints")
        ep_layout = QVBoxLayout(endpoints_box)
        ep_layout.setContentsMargins(8, 6, 8, 6)
        ep_layout.setSpacing(4)
        self._endpoint_cbs: dict[str, QCheckBox] = {}
        for column, label in PERMEABILITY_ENDPOINT_OPTIONS:
            cb = QCheckBox(label)
            cb.setChecked(True)
            self._endpoint_cbs[column] = cb
            ep_layout.addWidget(cb)
        root.addWidget(endpoints_box)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        if parent is not None:
            self.src_combo.addItems(parent.chemistry_tool_structure_sources())
        self.adjustSize()
        make_window_minimizable(self)

    def _selected_output_columns(self) -> list[str]:
        return [col for col, cb in self._endpoint_cbs.items() if cb.isChecked()]

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        output_columns = self._selected_output_columns()
        if not output_columns:
            QMessageBox.warning(
                self,
                "Predict Permeability",
                "Select at least one cell line / endpoint.",
            )
            return
        only_selected = selection_scope_checked(self)
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        if only_selected and not allowed:
            QMessageBox.warning(
                self,
                "Predict Permeability",
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return
        src = self.src_combo.currentText()
        self.parent_app.schedule_permeability_prediction(
            src, only_selected=only_selected, output_columns=tuple(output_columns)
        )
        self.close()
