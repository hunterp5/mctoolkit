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

"""Shared query strip for the PubChem, ChEMBL, and vendor dialogs."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

MODE_IDENTITY = "identity"
MODE_SIMILARITY = "similarity"


class DatabaseQueryBar(QWidget):
    """SMILES query row plus similarity limits that appear only for Similarity."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        tanimoto_tooltip: str = "",
        max_tooltip: str = "",
        include_mode: bool = True,
    ) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.mode = QComboBox(self)
        self.mode.addItem("Identity", MODE_IDENTITY)
        if include_mode:
            self.mode.addItem("Similarity", MODE_SIMILARITY)
            self.mode.setToolTip(
                "Identity looks up the SMILES. Similarity searches 2D Tanimoto neighbors."
            )
            row.addWidget(self.mode)
        else:
            self.mode.hide()
        row.addWidget(QLabel("SMILES:"))
        self.smiles = QLineEdit()
        self.smiles.setPlaceholderText("Paste SMILES here, or use the Sketcher button…")
        row.addWidget(self.smiles, 1)
        self.btn_sketch = QPushButton("Sketcher…")
        row.addWidget(self.btn_sketch)
        self.chk_only_selected = QCheckBox("Only Query Selected")
        self.chk_only_selected.setToolTip(
            "When checked, Query uses SMILES from selected rows in the main table (ignores the text box)."
        )
        row.addWidget(self.chk_only_selected)
        self.btn_query = QPushButton("Query")
        row.addWidget(self.btn_query)
        root.addLayout(row)

        self.sim_row = QWidget(self)
        sim = QHBoxLayout(self.sim_row)
        sim.setContentsMargins(0, 0, 0, 0)
        sim.setSpacing(6)
        sim.addWidget(QLabel("Min. Tanimoto:"))
        self.spin_tc = QDoubleSpinBox()
        self.spin_tc.setRange(0.30, 1.00)
        self.spin_tc.setDecimals(2)
        self.spin_tc.setSingleStep(0.05)
        self.spin_tc.setValue(0.70)
        if tanimoto_tooltip:
            self.spin_tc.setToolTip(tanimoto_tooltip)
        sim.addWidget(self.spin_tc)
        sim.addWidget(QLabel("Max. structures:"))
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 500)
        self.spin_max.setValue(25)
        if max_tooltip:
            self.spin_max.setToolTip(max_tooltip)
        sim.addWidget(self.spin_max)
        sim.addStretch(1)
        self.sim_row.setVisible(False)
        root.addWidget(self.sim_row)

        self.mode.currentIndexChanged.connect(self._sync_similarity_row)

    def similarity_selected(self) -> bool:
        return self.mode.currentData() == MODE_SIMILARITY

    def _sync_similarity_row(self) -> None:
        self.sim_row.setVisible(self.similarity_selected())

    def set_busy(self, busy: bool) -> None:
        """Lock the query controls while a request is running."""
        for widget in (
            self.mode,
            self.smiles,
            self.btn_sketch,
            self.chk_only_selected,
            self.btn_query,
            self.spin_tc,
            self.spin_max,
        ):
            widget.setEnabled(not busy)
