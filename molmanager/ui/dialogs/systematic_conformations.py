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

"""Chemistry → Conformations → Generate → Systematic…"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QMessageBox,
    QSpinBox,
    QVBoxLayout,
)

from ...conformers.openbabel_confab import SystematicConfParams, ensure_openbabel_confab_ready
from ..qt_widget_utils import boxed_form, make_window_minimizable
from .conformer_output import (
    ConformerOutputOptions,
    ConformerOutputOptionsPanel,
    add_centered_run_button,
)
from .scope import selection_scope_checked


class SystematicConformationsDialog(QDialog):
    """Configure Open Babel Confab (RMSD / energy cutoffs, max conformers, table scope)."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Conformations — Systematic")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        search, form = boxed_form("Search")

        self.num_confs_sb = QSpinBox()
        self.num_confs_sb.setRange(1, 10_000)
        self.num_confs_sb.setValue(100)
        self.num_confs_sb.setToolTip(
            "Maximum number of Confab conformers to test (--conf). "
            "Fewer unique poses are kept after RMSD and energy pruning."
        )
        form.addRow("Max conformers:", self.num_confs_sb)

        self.rmsd_sb = QDoubleSpinBox()
        self.rmsd_sb.setRange(0.05, 5.0)
        self.rmsd_sb.setDecimals(2)
        self.rmsd_sb.setSingleStep(0.05)
        self.rmsd_sb.setValue(0.5)
        self.rmsd_sb.setSuffix(" Å")
        self.rmsd_sb.setToolTip("Confab RMSD diversity cutoff (--rcutoff). Default 0.5 Å.")
        form.addRow("RMSD cutoff:", self.rmsd_sb)

        self.energy_sb = QDoubleSpinBox()
        self.energy_sb.setRange(0.0, 200.0)
        self.energy_sb.setDecimals(1)
        self.energy_sb.setSingleStep(5.0)
        self.energy_sb.setValue(50.0)
        self.energy_sb.setSuffix(" kcal/mol")
        self.energy_sb.setToolTip(
            "Keep conformers within this energy of the lowest Confab pose (--ecutoff). "
            "Default 50 kcal/mol."
        )
        form.addRow("Energy cutoff:", self.energy_sb)

        self.original_cb = QCheckBox("Include input conformation")
        self.original_cb.setToolTip(
            "Write the starting 3D geometry as the first Confab conformer (--original)."
        )
        form.addRow("", self.original_cb)
        root.addWidget(search)

        output, out_form = boxed_form("Output")
        self.keep_hs_cb = QCheckBox("Keep explicit hydrogens")
        self.keep_hs_cb.setToolTip(
            "Leave hydrogens on the packed ensemble. Off (default) matches Stochastic."
        )
        out_form.addRow("", self.keep_hs_cb)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        out_form.addRow("", self.only_selected_cb)

        self.output_panel = ConformerOutputOptionsPanel(self)
        out_form.addRow("", self.output_panel.add_to_table_cb)
        out_form.addRow(self.output_panel)
        root.addWidget(output)

        self.run_btn = add_centered_run_button(root)
        self.run_btn.clicked.connect(self._try_accept)
        make_window_minimizable(self)

    def _try_accept(self) -> None:
        if not self.output_panel.validate(self):
            return
        err = ensure_openbabel_confab_ready()
        if err:
            QMessageBox.warning(self, self.windowTitle(), err)
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def output_options(self) -> ConformerOutputOptions:
        return self.output_panel.options()

    def params(self) -> SystematicConfParams:
        return SystematicConfParams(
            num_confs=int(self.num_confs_sb.value()),
            rmsd_cutoff=float(self.rmsd_sb.value()),
            energy_cutoff=float(self.energy_sb.value()),
            include_original=bool(self.original_cb.isChecked()),
            keep_hydrogens=bool(self.keep_hs_cb.isChecked()),
        )
