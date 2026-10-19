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
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.bundled_paths import default_external_executable
from ...conformers.openbabel_confab import SystematicConfParams, ensure_openbabel_confab_ready
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import (
    ConformerOutputOptions,
    ConformerOutputOptionsPanel,
    conformer_options_group,
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

        hint = QLabel(
            "Systematic torsion search with Open Babel Confab. Defaults to the Open Babel "
            "install in this Python environment (`pip install openbabel`)."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(6)

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

        exe_row = QHBoxLayout()
        exe_row.setContentsMargins(0, 0, 0, 0)
        self.obabel_edit = QLineEdit(default_external_executable("obabel"))
        self.obabel_edit.setToolTip(
            "Open Babel executable. Defaults to a bundled copy under resources/bin if present, "
            "otherwise the pip wheel (`openbabel/bin/obabel`)."
        )
        exe_row.addWidget(self.obabel_edit, 1)
        btn_e = QPushButton("Browse…")
        btn_e.clicked.connect(self._browse_obabel)
        exe_row.addWidget(btn_e)
        exe_w = QWidget()
        exe_w.setLayout(exe_row)
        form.addRow("Open Babel:", exe_w)

        root.addLayout(form)

        self.original_cb = QCheckBox("Include input conformation")
        self.original_cb.setToolTip(
            "Write the starting 3D geometry as the first Confab conformer (--original)."
        )

        self.keep_hs_cb = QCheckBox("Keep explicit hydrogens")
        self.keep_hs_cb.setToolTip(
            "Leave hydrogens on the packed ensemble. Off (default) matches Stochastic."
        )

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)

        self.output_panel = ConformerOutputOptionsPanel(self)
        root.addWidget(
            conformer_options_group(
                self.original_cb,
                self.keep_hs_cb,
                self.only_selected_cb,
                self.output_panel.add_to_table_cb,
            )
        )
        root.addWidget(self.output_panel)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _browse_obabel(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Babel executable", self.obabel_edit.text() or "", "All files (*.*)"
        )
        if path:
            self.obabel_edit.setText(path)

    def _try_accept(self) -> None:
        if not self.output_panel.validate(self):
            return
        err = ensure_openbabel_confab_ready(self.obabel_edit.text())
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
            obabel_path=(self.obabel_edit.text() or "").strip(),
        )
