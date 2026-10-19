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

"""Chemistry → Conformations → Generate → Stochastic."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...workers.conformer_generation import (
    CONFORMER_FORCE_FIELDS,
    DEFAULT_CONFORMER_FORCE_FIELD,
    ConformerGenParams,
)
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import (
    ConformerOutputOptions,
    ConformerOutputOptionsPanel,
    add_centered_run_button,
    conformer_options_group,
)
from .scope import selection_scope_checked

_CONFORMER_FF_TOOLTIP = (
    "MMFF94 or MMFF94s when parameters exist; otherwise falls back to UFF automatically. "
    "GAFF2/GAFF minimize with AmberTools (antechamber) and OpenMM in vacuum; "
    "on Windows AmberTools runs in WSL (Settings → WSL)."
)
# Search budget can exceed what we store: packing/viewer stay healthy around 50–200 kept poses.
_STOCHASTIC_NUM_CONFS_MAX = 1000
_STOCHASTIC_NUM_CONFS_DEFAULT = 50
_STOCHASTIC_MAX_KEEP_MAX = 1000
_STOCHASTIC_MAX_KEEP_DEFAULT = 100


def _set_combo_current_data(combo: QComboBox, data) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return


class GenerateConformationsDialog(QDialog):
    """Configure stochastic ETKDG embedding, minimizer, energy window, optional alignment, and table scope."""

    def __init__(self, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self._init_generate_conformations_state(selected_row_count)
        self._build_generate_conformations_ui()
        self._wire_generate_conformations_ui()

    def _init_generate_conformations_state(self, selected_row_count: int) -> None:
        self.setWindowTitle("Generate Conformations — Stochastic")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._selected_row_count = int(selected_row_count)
        self._have_selection = selected_row_count > 0

    def _build_generate_conformations_ui(self) -> None:
        selected_row_count = self._selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        form = QFormLayout()
        form.setSpacing(6)
        self.num_confs_sb = QSpinBox()
        self.num_confs_sb.setRange(1, _STOCHASTIC_NUM_CONFS_MAX)
        self.num_confs_sb.setValue(_STOCHASTIC_NUM_CONFS_DEFAULT)
        self.num_confs_sb.setToolTip(
            "ETKDG search budget: how many conformers to embed before minimization and pruning. "
            "Use Max keep (and the energy / RMS filters) to limit what is stored."
        )
        form.addRow("Conformers:", self.num_confs_sb)

        self.energy_win_sb = QDoubleSpinBox()
        self.energy_win_sb.setRange(0.0, 200.0)
        self.energy_win_sb.setDecimals(2)
        self.energy_win_sb.setSingleStep(1.0)
        self.energy_win_sb.setValue(10.0)
        self.energy_win_sb.setSuffix(" kcal/mol")
        self.energy_win_sb.setSpecialValueText("0 = keep all (no window)")
        self.energy_win_sb.setToolTip(
            "Keep only conformers within this energy above the lowest-energy conformer. "
            "Set to 0 to skip energy pruning."
        )
        form.addRow("Energy window:", self.energy_win_sb)

        self.ff_combo = QComboBox()
        for name in CONFORMER_FORCE_FIELDS:
            self.ff_combo.addItem(name, name)
        _set_combo_current_data(self.ff_combo, DEFAULT_CONFORMER_FORCE_FIELD)
        self.ff_combo.setToolTip(_CONFORMER_FF_TOOLTIP)
        form.addRow("Force field:", self.ff_combo)

        self.seed_sb = QSpinBox()
        self.seed_sb.setRange(0, 2_147_483_647)
        self.seed_sb.setValue(0xC0FFEE)
        self.seed_sb.setToolTip("Random seed passed to the ETKDG embedder.")
        form.addRow("Seed:", self.seed_sb)

        self.prune_rms_sb = QDoubleSpinBox()
        self.prune_rms_sb.setRange(-1.0, 3.0)
        self.prune_rms_sb.setDecimals(3)
        self.prune_rms_sb.setSingleStep(0.05)
        self.prune_rms_sb.setValue(-1.0)
        self.prune_rms_sb.setSpecialValueText("default (ETKDG)")
        self.prune_rms_sb.setToolTip(
            "ETKDG pruneRmsThresh during embed; −1 uses the parameter object default."
        )
        form.addRow("RMS prune (embed):", self.prune_rms_sb)

        self.post_min_rms_sb = QDoubleSpinBox()
        self.post_min_rms_sb.setRange(0.0, 3.0)
        self.post_min_rms_sb.setDecimals(3)
        self.post_min_rms_sb.setSingleStep(0.05)
        self.post_min_rms_sb.setValue(0.0)
        self.post_min_rms_sb.setSpecialValueText("0 = off")
        self.post_min_rms_sb.setToolTip(
            "After minimization, drop higher-energy conformers within this heavy-atom RMS "
            "of a kept pose. 0 skips this extra prune."
        )
        form.addRow("RMS prune (post-min):", self.post_min_rms_sb)

        self.max_keep_sb = QSpinBox()
        self.max_keep_sb.setRange(0, _STOCHASTIC_MAX_KEEP_MAX)
        self.max_keep_sb.setValue(_STOCHASTIC_MAX_KEEP_DEFAULT)
        self.max_keep_sb.setSpecialValueText("0 = no extra cap")
        self.max_keep_sb.setToolTip(
            "Keep at most this many lowest-energy conformers after energy-window and RMS "
            "pruning. Default 100 keeps table cells and the 3D viewer compact. "
            "0 stores every survivor (coordinates go to the disk-backed ensemble store)."
        )
        form.addRow("Max keep:", self.max_keep_sb)

        self.max_iters_sb = QSpinBox()
        self.max_iters_sb.setRange(20, 2000)
        self.max_iters_sb.setValue(200)
        self.max_iters_sb.setToolTip("Maximum minimizer iterations per conformer.")
        form.addRow("Max iterations:", self.max_iters_sb)

        self.max_embed_sb = QSpinBox()
        self.max_embed_sb.setRange(0, 2000)
        self.max_embed_sb.setValue(0)
        self.max_embed_sb.setSpecialValueText("0 = ETKDG default")
        self.max_embed_sb.setToolTip(
            "Max embedding attempts per conformer (ETKDG maxIterations). "
            "0 leaves the RDKit default (typically 10 × number of atoms)."
        )
        form.addRow("Max embed attempts:", self.max_embed_sb)

        self.align_pat_edit = QLineEdit()
        self.align_pat_edit.setPlaceholderText("optional SMILES/SMARTS")
        self.align_pat_edit.setToolTip(
            "If set, generated conformers are rigidly aligned on atoms that match this query "
            "(same graph as the molecule). Leave empty to keep the embedder orientations."
        )
        self.align_smarts_cb = QCheckBox("SMARTS")
        self.align_smarts_cb.setChecked(False)
        self.align_smarts_cb.setToolTip("Parse the pattern as SMARTS instead of SMILES.")
        pat_row = QHBoxLayout()
        pat_row.setContentsMargins(0, 0, 0, 0)
        pat_row.setSpacing(6)
        pat_row.addWidget(self.align_pat_edit, 1)
        pat_row.addWidget(self.align_smarts_cb)
        form.addRow("Align on:", pat_row)

        root.addLayout(form)

        self.enforce_chirality_cb = QCheckBox("Enforce chirality")
        self.enforce_chirality_cb.setChecked(True)
        self.enforce_chirality_cb.setToolTip(
            "Preserve specified stereochemistry during ETKDG embedding."
        )

        self.random_coords_cb = QCheckBox("Use random coordinates")
        self.random_coords_cb.setChecked(False)
        self.random_coords_cb.setToolTip(
            "Start from random coords instead of distance-geometry embedding. "
            "Can help stubborn rings, usually slower and noisier."
        )

        self.exp_torsions_cb = QCheckBox("Experimental torsion preferences")
        self.exp_torsions_cb.setChecked(True)
        self.exp_torsions_cb.setToolTip(
            "Use ETKDG experimental torsion-angle preferences (recommended)."
        )

        self.small_ring_cb = QCheckBox("Small-ring torsions")
        self.small_ring_cb.setChecked(True)
        self.small_ring_cb.setToolTip("ETKDG small-ring torsion corrections.")

        self.macrocycle_cb = QCheckBox("Macrocycle torsions")
        self.macrocycle_cb.setChecked(True)
        self.macrocycle_cb.setToolTip("ETKDG macrocycle torsion corrections.")

        self.basic_knowledge_cb = QCheckBox("Basic knowledge terms")
        self.basic_knowledge_cb.setChecked(True)
        self.basic_knowledge_cb.setToolTip("ETKDG basic-knowledge terms (planar aromatics, etc.).")

        self.heavy_rms_cb = QCheckBox("Heavy atoms only for RMS")
        self.heavy_rms_cb.setChecked(True)
        self.heavy_rms_cb.setToolTip(
            "Embed RMS prune and post-minimize RMS prune ignore hydrogens."
        )

        self.keep_hs_cb = QCheckBox("Keep explicit hydrogens")
        self.keep_hs_cb.setChecked(False)
        self.keep_hs_cb.setToolTip(
            "Leave hydrogens on after minimization (useful for some docking exports)."
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
                self.enforce_chirality_cb,
                self.random_coords_cb,
                self.exp_torsions_cb,
                self.small_ring_cb,
                self.macrocycle_cb,
                self.basic_knowledge_cb,
                self.heavy_rms_cb,
                self.keep_hs_cb,
                self.only_selected_cb,
                self.output_panel.add_to_table_cb,
            )
        )
        root.addWidget(self.output_panel)

        self.run_btn = add_centered_run_button(root)

    def _wire_generate_conformations_ui(self) -> None:
        self.run_btn.clicked.connect(self._try_accept)
        make_window_minimizable(self)

    def _try_accept(self) -> None:
        if not self.output_panel.validate(self):
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def output_options(self) -> ConformerOutputOptions:
        return self.output_panel.options()

    def params(self) -> ConformerGenParams:
        return ConformerGenParams(
            num_confs=int(self.num_confs_sb.value()),
            energy_window_kcal=float(self.energy_win_sb.value()),
            force_field=str(self.ff_combo.currentData() or DEFAULT_CONFORMER_FORCE_FIELD),
            random_seed=int(self.seed_sb.value()),
            prune_rms_threshold=float(self.prune_rms_sb.value()),
            max_iterations=int(self.max_iters_sb.value()),
            align_pattern=(self.align_pat_edit.text() or "").strip(),
            align_pattern_is_smarts=bool(self.align_smarts_cb.isChecked()),
            post_min_rms_threshold=float(self.post_min_rms_sb.value()),
            max_keep=int(self.max_keep_sb.value()),
            enforce_chirality=bool(self.enforce_chirality_cb.isChecked()),
            use_random_coords=bool(self.random_coords_cb.isChecked()),
            use_exp_torsion_prefs=bool(self.exp_torsions_cb.isChecked()),
            use_small_ring_torsions=bool(self.small_ring_cb.isChecked()),
            use_macrocycle_torsions=bool(self.macrocycle_cb.isChecked()),
            use_basic_knowledge=bool(self.basic_knowledge_cb.isChecked()),
            only_heavy_atoms_for_rms=bool(self.heavy_rms_cb.isChecked()),
            max_embed_attempts=int(self.max_embed_sb.value()),
            keep_hydrogens=bool(self.keep_hs_cb.isChecked()),
        )
