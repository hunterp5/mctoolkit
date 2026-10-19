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

"""Chemistry → Conformations → Generate → CONFORGE…"""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.bundled_paths import default_external_executable
from ...conformers.conforge_generation import (
    CONFORGE_MODES,
    CONFORGE_PRESETS,
    ConforgeParams,
    ensure_conforge_ready,
    normalize_conforge_mode,
    normalize_conforge_preset,
)
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import (
    ConformerOutputOptions,
    ConformerOutputOptionsPanel,
    add_centered_run_button,
    conformer_options_group,
)
from .scope import selection_scope_checked

_PRESET_LABELS = {
    "SMALL_SET_DIVERSE": "Small diverse",
    "MEDIUM_SET_DIVERSE": "Medium diverse",
    "LARGE_SET_DIVERSE": "Large diverse",
    "SMALL_SET_DENSE": "Small dense",
    "MEDIUM_SET_DENSE": "Medium dense",
    "LARGE_SET_DENSE": "Large dense",
}
_MODE_LABELS = {
    "AUTO": "Auto",
    "SYSTEMATIC": "Systematic",
    "STOCHASTIC": "Stochastic",
}


class ConforgeConformationsDialog(QDialog):
    """Configure CONFORGE (CDPKit) ensemble size, energy/RMSD, sampling mode, and table scope."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Generate Conformations — CONFORGE")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)

        self.num_confs_sb = QSpinBox()
        self.num_confs_sb.setRange(0, 10_000)
        self.num_confs_sb.setValue(100)
        self.num_confs_sb.setSpecialValueText("0 = no cap")
        self.num_confs_sb.setToolTip(
            "Maximum output conformers per molecule (confgen -n). 0 disables the cap."
        )
        form.addRow("Max conformers:", self.num_confs_sb)

        self.energy_sb = QDoubleSpinBox()
        self.energy_sb.setRange(0.0, 200.0)
        self.energy_sb.setDecimals(1)
        self.energy_sb.setSingleStep(1.0)
        self.energy_sb.setValue(15.0)
        self.energy_sb.setSuffix(" kcal/mol")
        self.energy_sb.setToolTip(
            "Keep conformers within this window of the lowest CONFORGE energy (confgen -e). "
            "Default 15 kcal/mol."
        )
        form.addRow("Energy window:", self.energy_sb)

        self.rmsd_sb = QDoubleSpinBox()
        self.rmsd_sb.setRange(0.0, 5.0)
        self.rmsd_sb.setDecimals(2)
        self.rmsd_sb.setSingleStep(0.05)
        self.rmsd_sb.setValue(0.5)
        self.rmsd_sb.setSuffix(" Å")
        self.rmsd_sb.setSpecialValueText("0 = off")
        self.rmsd_sb.setToolTip(
            "Minimum RMSD between kept poses (confgen -r). 0 disables RMSD checking. Default 0.5 Å."
        )
        form.addRow("RMSD cutoff:", self.rmsd_sb)

        self.preset_combo = QComboBox()
        for key in CONFORGE_PRESETS:
            self.preset_combo.addItem(_PRESET_LABELS.get(key, key), key)
        mid = self.preset_combo.findData("MEDIUM_SET_DIVERSE")
        if mid >= 0:
            self.preset_combo.setCurrentIndex(mid)
        self.preset_combo.setToolTip(
            "CONFORGE size/diversity preset (confgen -C). Energy, RMSD, and max conformers "
            "below still apply after the preset."
        )
        form.addRow("Preset:", self.preset_combo)

        self.mode_combo = QComboBox()
        for key in CONFORGE_MODES:
            self.mode_combo.addItem(_MODE_LABELS.get(key, key), key)
        self.mode_combo.setToolTip(
            "Sampling mode (confgen -m). Auto uses systematic fragment/torsion sampling for "
            "typical drug-like molecules and stochastic DG for large macrocycles."
        )
        form.addRow("Sampling:", self.mode_combo)

        self.timeout_sb = QSpinBox()
        self.timeout_sb.setRange(0, 86_400)
        self.timeout_sb.setValue(3600)
        self.timeout_sb.setSuffix(" s")
        self.timeout_sb.setSpecialValueText("0 = no limit")
        self.timeout_sb.setToolTip("Per-molecule timeout (confgen -T). Default 3600 s.")
        form.addRow("Timeout:", self.timeout_sb)

        exe_row = QHBoxLayout()
        exe_row.setContentsMargins(0, 0, 0, 0)
        self.confgen_edit = QLineEdit(default_external_executable("confgen"))
        self.confgen_edit.setToolTip(
            "confgen executable from a CDPKit install. On Windows, Browse to "
            r"C:\Program Files\CDPKit\Bin\confgen.exe after running the MSVC installer."
        )
        exe_row.addWidget(self.confgen_edit, 1)
        btn_e = QPushButton("Browse…")
        btn_e.clicked.connect(self._browse_confgen)
        exe_row.addWidget(btn_e)
        exe_w = QWidget()
        exe_w.setLayout(exe_row)
        form.addRow("CONFORGE:", exe_w)

        root.addLayout(form)

        self.original_cb = QCheckBox("Include input conformation")
        self.original_cb.setToolTip(
            "Add the starting 3D geometry to the output ensemble when coordinates exist."
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

        self.run_btn = add_centered_run_button(root)
        self.run_btn.clicked.connect(self._try_accept)
        make_window_minimizable(self)

    def _browse_confgen(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "CONFORGE executable", self.confgen_edit.text() or "", "All files (*.*)"
        )
        if path:
            self.confgen_edit.setText(path)

    def _try_accept(self) -> None:
        if not self.output_panel.validate(self):
            return
        err = ensure_conforge_ready(self.confgen_edit.text())
        if err:
            QMessageBox.warning(self, self.windowTitle(), err)
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def output_options(self) -> ConformerOutputOptions:
        return self.output_panel.options()

    def params(self) -> ConforgeParams:
        preset = self.preset_combo.currentData()
        mode = self.mode_combo.currentData()
        return ConforgeParams(
            num_confs=int(self.num_confs_sb.value()),
            energy_window=float(self.energy_sb.value()),
            rmsd_cutoff=float(self.rmsd_sb.value()),
            mode=normalize_conforge_mode(str(mode or "AUTO")),
            preset=normalize_conforge_preset(str(preset or "MEDIUM_SET_DIVERSE")),
            timeout_s=int(self.timeout_sb.value()),
            include_input=bool(self.original_cb.isChecked()),
            keep_hydrogens=bool(self.keep_hs_cb.isChecked()),
            confgen_path=(self.confgen_edit.text() or "").strip(),
        )
