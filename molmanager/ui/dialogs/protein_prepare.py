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

"""Protein Viewer Fast Prepare dialog: PDBFixer, pdb2pqr, OpenMM restrained min."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...workers.protein_prepare import (
    ProteinPrepareSignals,
    ProteinPrepareWorker,
)
from ...workers.protein_prepare_plan import (
    build_protein_prepare_request,
    plan_protein_prepare_start,
    source_has_cif_ligand_bonds,
    source_has_ligand,
)
from ..qt_widget_utils import append_viewer_log, make_window_minimizable
from .protein_fixer_options import (
    add_fixer_extra_options,
    fixer_extra_request_kwargs,
    populate_fixer_chain_list,
)
from .protein_source_picker import (
    ProteinStructureSourceMixin,
    _PREPARE_SOURCE_FMTS,
    _browse_path_row,
)

_PREPARE_FMTS = _PREPARE_SOURCE_FMTS


def add_openmm_platform_combo(combo: QComboBox) -> QComboBox:
    """Fill Compute device choices for OpenMM minimization."""
    combo.addItem("Auto (GPU if available)", "auto")
    combo.addItem("OpenCL", "OpenCL")
    combo.addItem("CUDA", "CUDA")
    combo.addItem("CPU", "CPU")
    combo.setToolTip(
        "OpenMM device for restrained minimization. Auto prefers CUDA, then OpenCL, "
        "then CPU. The pip OpenMM wheel includes OpenCL (NVIDIA GPUs) but not CUDA. "
        "CPU uses all but one core if no GPU platform loads."
    )
    return combo


class ProteinPrepareDialog(ProteinStructureSourceMixin, QDialog):
    """Options for Protein Viewer → Tools → Prepare → Fast Prepare."""

    prepared = pyqtSignal(str)
    smina_prepared = pyqtSignal(object)
    _source_output_tag = "prepared"
    _source_tmp_prefix = "molmanager_prepare_in_"
    _source_tool_title = "Fast Prepare"
    _source_empty_message = "Choose a Manager structure or a PDB/mmCIF file."

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._viewer = viewer
        self.setWindowTitle("Fast Prepare")
        self.setMinimumWidth(500)
        self.resize(540, 640)
        self._build_prepare_ui()
        self._wire_prepare_ui()

    def _build_prepare_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Structure")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self._add_structure_source_rows(io_form)
        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("receptor_prepared.cif")
        io_form.addRow("Output:", _browse_path_row(self.edit_out, self._browse_output))
        self.combo_out_fmt = QComboBox()
        self.combo_out_fmt.addItem("mmCIF (.cif)", "cif")
        self.combo_out_fmt.addItem("PDB (.pdb)", "pdb")
        self.combo_out_fmt.setToolTip("mmCIF keeps ligand bond orders in _chem_comp_bond.")
        self.combo_out_fmt.currentIndexChanged.connect(self._sync_output_suffix)
        io_form.addRow("Format:", self.combo_out_fmt)
        root.addWidget(io_gb)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        host = QWidget()
        host_l = QVBoxLayout(host)
        host_l.setContentsMargins(0, 0, 0, 0)
        host_l.setSpacing(6)

        fixer_gb = QGroupBox("PDBFixer")
        fixer_form = QFormLayout(fixer_gb)
        fixer_form.setContentsMargins(8, 6, 8, 6)
        fixer_form.setSpacing(4)

        self.chk_repair = QCheckBox("Clean up")
        self.chk_repair.setChecked(True)
        self.chk_repair.setToolTip(
            "PDBFixer repair: rebuild missing atoms/loops, replace non-standard "
            "residues, and strip waters/additives. Uncheck to skip this step."
        )
        fixer_form.addRow(self.chk_repair)

        self.chk_rebuild_loops = QCheckBox("Rebuild missing loops from SEQRES")
        self.chk_rebuild_loops.setChecked(True)
        self.chk_rebuild_loops.setToolTip(
            "Model internal sequence gaps, then let restrained minimization relax "
            "the new residues. Uncheck to skip internal loops. Long terminal tags "
            "are skipped separately (Skip long missing stretches)."
        )
        fixer_form.addRow(self.chk_rebuild_loops)

        self.chk_skip_pocket_loops = QCheckBox("Skip loop rebuild near the ligand")
        self.chk_skip_pocket_loops.setChecked(True)
        self.chk_skip_pocket_loops.setToolTip(
            "Do not fill SEQRES gaps whose flanking residues sit within 8 Å of the ligand. "
            "Rebuilt loops next to the site are models, not crystal coordinates."
        )
        fixer_form.addRow(self.chk_skip_pocket_loops)

        add_fixer_extra_options(fixer_form, self)

        self.chk_keep_ligand = QCheckBox("Keep ligand in prepared mmCIF")
        self.chk_keep_ligand.setChecked(True)
        self.chk_keep_ligand.setToolTip(
            "Leave the ligand in the prepared file. Uncheck for an apo receptor "
            "(ligand can still be present during PROPKA). The prepared file is mmCIF "
            "so ligand bond orders are kept in _chem_comp_bond. mmCIF inputs stay mmCIF."
        )
        fixer_form.addRow(self.chk_keep_ligand)

        self.chk_keep_selected_waters = QCheckBox("Keep Manager-selected waters")
        self.chk_keep_selected_waters.setChecked(False)
        self.chk_keep_selected_waters.setToolTip(
            "Keep water groups currently selected in the Manager through protonation "
            "and into the output. Other waters are stripped unless bridging waters "
            "are also kept. Select a Chain group or its Water row first."
        )
        fixer_form.addRow(self.chk_keep_selected_waters)

        self.chk_keep_bridging_waters = QCheckBox("Keep waters near ligand")
        self.chk_keep_bridging_waters.setChecked(False)
        self.chk_keep_bridging_waters.setToolTip(
            "Keep crystallographic waters whose oxygen is within the water cutoff of a "
            "ligand heavy atom, occupancy ≥ 0.5, and B-factor ≤ 80. Combined with Manager "
            "selection when both are on."
        )
        fixer_form.addRow(self.chk_keep_bridging_waters)
        host_l.addWidget(fixer_gb)

        pqr_gb = QGroupBox("pdb2pqr")
        pqr_form = QFormLayout(pqr_gb)
        pqr_form.setContentsMargins(8, 6, 8, 6)
        pqr_form.setSpacing(4)

        self.chk_protonate = QCheckBox("Protonate")
        self.chk_protonate.setChecked(True)
        self.chk_protonate.setToolTip(
            "pdb2pqr/PROPKA protein protonation at the chosen pH. Uncheck to skip "
            "this step (ligand Uni-pKa is skipped with it)."
        )
        pqr_form.addRow(self.chk_protonate)

        self.chk_include_ligand = QCheckBox("Include ligand in PROPKA protonation")
        self.chk_include_ligand.setChecked(True)
        self.chk_include_ligand.setToolTip(
            "Keep organic HETATM in the structure while PROPKA assigns protein "
            "titration states (holo protonation). Recommended before docking."
        )
        pqr_form.addRow(self.chk_include_ligand)

        self.chk_protonate_ligand = QCheckBox("Protonate ligand (Uni-pKa at pH)")
        self.chk_protonate_ligand.setChecked(True)
        self.chk_protonate_ligand.setToolTip(
            "Pick the aqueous-dominant protomer at the same pH as PROPKA, then place it "
            "on the crystal coordinates. Needs SMILES, an SDF/MOL2, or mmCIF "
            "_chem_comp_bond. Requires the pka extra."
        )
        pqr_form.addRow(self.chk_protonate_ligand)

        self.chk_pocket_ligand = QCheckBox("Reweight ligand protomer in the pocket")
        self.chk_pocket_ligand.setChecked(True)
        self.chk_pocket_ligand.setToolTip(
            "After protein protonation, shift Uni-pKa microstate free energies by a Coulomb "
            "term from pdb2pqr charges (distance-dependent dielectric). This is a pocket "
            "electrostatic estimate, not Poisson–Boltzmann or GBSA. Only protomers that are "
            "already populated in water (≥5%) are considered."
        )
        pqr_form.addRow(self.chk_pocket_ligand)

        self.edit_ligand_smiles = QLineEdit()
        self.edit_ligand_smiles.setPlaceholderText(
            "SMILES, or empty when mmCIF has ligand _chem_comp_bond"
        )
        self.edit_ligand_smiles.setToolTip(
            "Used for Uni-pKa and to copy bond orders onto crystal coordinates. "
            "Leave empty if the mmCIF already has _chem_comp_bond for the ligand, "
            "or if ligand protonation is off (orders guessed from geometry)."
        )
        pqr_form.addRow("Ligand SMILES:", self.edit_ligand_smiles)

        self.edit_ligand_ref = QLineEdit()
        self.edit_ligand_ref.setPlaceholderText("Optional SDF or MOL2")
        pqr_form.addRow(
            "Bond-order file:",
            _browse_path_row(self.edit_ligand_ref, self._browse_ligand_ref),
        )

        self.spin_ph = QDoubleSpinBox()
        self.spin_ph.setRange(0.0, 14.0)
        self.spin_ph.setDecimals(1)
        self.spin_ph.setSingleStep(0.1)
        self.spin_ph.setValue(7.4)
        self.spin_ph.setToolTip(
            "pH for PROPKA protein titration and Uni-pKa ligand protomer selection."
        )
        pqr_form.addRow("pH:", self.spin_ph)
        host_l.addWidget(pqr_gb)

        min_gb = QGroupBox("Minimization")
        min_form = QFormLayout(min_gb)
        min_form.setContentsMargins(8, 6, 8, 6)
        min_form.setSpacing(4)

        self.chk_minimize = QCheckBox("Restrained minimization")
        self.chk_minimize.setChecked(True)
        self.chk_minimize.setToolTip(
            "Harmonic restraints on experimental protein atoms so rebuilt loops and "
            "hydrogens can relieve clashes without the fold drifting. Protein only "
            "holds the ligand out of OpenMM and restores it afterward. GAFF/GAFF2 "
            "minimizes the complex with AmberTools ligand parameters."
        )
        min_form.addRow(self.chk_minimize)

        self.combo_protein_ff = QComboBox()
        self.combo_protein_ff.addItem("AMBER ff14SB", "amber14")
        self.combo_protein_ff.addItem("AMBER ff99SB-ILDN", "amber99sbildn")
        self.combo_protein_ff.setToolTip("Protein force field for OpenMM minimization.")
        min_form.addRow("Protein force field:", self.combo_protein_ff)

        self.combo_ligand_ff = QComboBox()
        self.combo_ligand_ff.addItem("Protein only", "none")
        self.combo_ligand_ff.addItem("GAFF2", "gaff2")
        self.combo_ligand_ff.addItem("GAFF", "gaff")
        self.combo_ligand_ff.setToolTip(
            "Protein only holds the ligand out of OpenMM. GAFF2 (recommended) or classic "
            "GAFF parameterize the ligand with AmberTools (WSL on Windows) so the complex "
            "is minimized together. Needs ligand SMILES, SDF/MOL2, or mmCIF bonds."
        )
        min_form.addRow("Ligand force field:", self.combo_ligand_ff)

        self.combo_solvent = QComboBox()
        self.combo_solvent.addItem("GBn2 GBSA (recommended)", "gbn2")
        self.combo_solvent.addItem("OBC2 GBSA", "obc2")
        self.combo_solvent.addItem("Vacuum", "vacuum")
        self.combo_solvent.setToolTip(
            "GBn2 is the usual docking-prep implicit solvent. Vacuum over-attracts "
            "charges and can distort the pocket; it is a fallback if GB cannot be built."
        )
        min_form.addRow("Solvation:", self.combo_solvent)

        self.combo_openmm_platform = QComboBox()
        add_openmm_platform_combo(self.combo_openmm_platform)
        min_form.addRow("Compute:", self.combo_openmm_platform)

        self.spin_salt = QDoubleSpinBox()
        self.spin_salt.setRange(0.0, 2.0)
        self.spin_salt.setDecimals(2)
        self.spin_salt.setSingleStep(0.05)
        self.spin_salt.setValue(0.15)
        self.spin_salt.setSuffix(" M")
        self.spin_salt.setToolTip("1:1 salt for GB Debye screening (ignored in vacuum).")
        min_form.addRow("Salt:", self.spin_salt)

        self.combo_restraint = QComboBox()
        self.combo_restraint.addItem("Backbone heavy atoms", "backbone")
        self.combo_restraint.addItem("Cα only", "ca")
        self.combo_restraint.addItem("Backbone + ligand heavy atoms", "backbone_ligand")
        self.combo_restraint.setToolTip(
            "Backbone restraints keep the fold and pocket orientation. Cα-only lets "
            "side chains move more. Backbone + ligand is for GAFF/GAFF2 holo min so the "
            "ligand stays near the crystal pose."
        )
        min_form.addRow("Restrain:", self.combo_restraint)

        self.spin_k = QDoubleSpinBox()
        self.spin_k.setRange(0.5, 50.0)
        self.spin_k.setDecimals(1)
        self.spin_k.setSingleStep(1.0)
        self.spin_k.setValue(10.0)
        self.spin_k.setSuffix(" kcal/mol/Å²")
        min_form.addRow("Restraint k:", self.spin_k)

        self.spin_iters = QSpinBox()
        self.spin_iters.setRange(50, 5000)
        self.spin_iters.setSingleStep(50)
        self.spin_iters.setValue(400)
        min_form.addRow("Max iterations:", self.spin_iters)
        host_l.addWidget(min_gb)

        smina_gb = QGroupBox("Gnina docking")
        smina_form = QFormLayout(smina_gb)
        smina_form.setContentsMargins(8, 6, 8, 6)
        smina_form.setSpacing(4)
        self.chk_write_smina = QCheckBox("Write Gnina files (receptor PDBQT, ligand, box)")
        self.chk_write_smina.setChecked(True)
        self.chk_write_smina.setToolTip(
            "After chemistry prep, write an apo receptor PDBQT (Meeko), a crystal "
            "ligand PDB/SDF, and a Vina/Gnina box file from the ligand bounding box."
        )
        smina_form.addRow(self.chk_write_smina)
        self.radio_box_loaded = QRadioButton("Loaded structure")
        self.radio_box_loaded.setToolTip(
            "Build the search box from a ligand already in the Protein Viewer "
            "(the structure being prepared, or another loaded file in the same frame)."
        )
        self.radio_box_file = QRadioButton("Ligand file…")
        self.radio_box_file.setToolTip(
            "Build the search box from a separate PDB, SDF, MOL2, or PDBQT. Use this "
            "when the ligand is not in the structure being prepared."
        )
        self.radio_box_loaded.setChecked(True)
        box_src_group = QButtonGroup(self)
        box_src_group.addButton(self.radio_box_loaded)
        box_src_group.addButton(self.radio_box_file)
        box_src_row = QWidget()
        box_src_l = QHBoxLayout(box_src_row)
        box_src_l.setContentsMargins(0, 0, 0, 0)
        box_src_l.setSpacing(12)
        box_src_l.addWidget(self.radio_box_loaded)
        box_src_l.addWidget(self.radio_box_file)
        box_src_l.addStretch()
        smina_form.addRow("Box from:", box_src_row)
        self.combo_box_ligand = QComboBox()
        self.combo_box_ligand.setToolTip(
            "Ligand whose coordinates define the search box. Defaults to the Manager "
            "selection, or the largest ligand among loaded structures."
        )
        smina_form.addRow("Ligand in structure:", self.combo_box_ligand)
        self.edit_box_ligand = QLineEdit()
        self.edit_box_ligand.setPlaceholderText("PDB, SDF, MOL2, or PDBQT")
        self.edit_box_ligand.setToolTip(
            "Coordinates must be in the same frame as the receptor. Crystal ligand "
            "or a reference pose both work."
        )
        self.box_ligand_file_row = _browse_path_row(self.edit_box_ligand, self._browse_box_ligand)
        smina_form.addRow("Ligand file:", self.box_ligand_file_row)
        self.spin_box_padding = QDoubleSpinBox()
        self.spin_box_padding.setRange(0.0, 20.0)
        self.spin_box_padding.setDecimals(1)
        self.spin_box_padding.setSingleStep(0.5)
        self.spin_box_padding.setValue(4.0)
        self.spin_box_padding.setSuffix(" Å")
        self.spin_box_padding.setToolTip(
            "Padding added on each side of the ligand bounding box (Gnina --autobox_add)."
        )
        smina_form.addRow("Box padding:", self.spin_box_padding)
        self.lbl_box_preview = QLabel("Box: —")
        self.lbl_box_preview.setWordWrap(True)
        smina_form.addRow(self.lbl_box_preview)
        host_l.addWidget(smina_gb)
        host_l.addStretch()
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

    def _wire_prepare_ui(self) -> None:
        self.chk_repair.toggled.connect(self._sync_repair_options)
        self.chk_protonate.toggled.connect(self._sync_ligand_options)
        self.chk_include_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_protonate_ligand.toggled.connect(self._sync_ligand_options)
        self.chk_minimize.toggled.connect(self._sync_min_options)
        self.combo_solvent.currentIndexChanged.connect(self._sync_min_options)
        self.chk_rebuild_loops.toggled.connect(self._sync_min_options)
        self.chk_write_smina.toggled.connect(self._sync_smina_options)
        self.radio_box_loaded.toggled.connect(self._sync_smina_options)
        self.radio_box_file.toggled.connect(self._sync_smina_options)
        self.chk_keep_bridging_waters.toggled.connect(self._sync_water_cutoff)
        self._sync_repair_options()
        self._sync_ligand_options()
        self._sync_min_options()
        self._sync_smina_options()
        self._sync_water_cutoff()

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Fast Prepare")
        self.btn_run.clicked.connect(self._on_run)
        btn_row.addWidget(self.btn_run)
        self.btn_open_smina = QPushButton("Open Gnina…")
        self.btn_open_smina.setEnabled(False)
        self.btn_open_smina.setToolTip(
            "Open Protein → Dock Ligand → Gnina with the prepared receptor, box, and "
            "crystal ligand for internal validation. The docking ligand field is left "
            "empty so you can choose compounds to dock."
        )
        self.btn_open_smina.clicked.connect(self._on_open_smina)
        btn_row.addWidget(self.btn_open_smina)
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.clicked.connect(self.close)
        btn_row.addWidget(self.btn_close)
        self.layout().addLayout(btn_row)

        self._signals = ProteinPrepareSignals(self)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self._signals.progress.connect(self._append_log)
        self._input_tmp: Path | None = None
        self._smina_result = None

        make_window_minimizable(self)

    def prefill_from_viewer(self) -> None:
        self._refresh_structure_source()

    def _refresh_chain_list(self) -> None:
        populate_fixer_chain_list(self, self.chosen_chain_ids())

    def _refresh_water_label(self) -> None:
        keys = self.chosen_water_keys()
        if keys:
            self.chk_keep_selected_waters.setText(
                f"Keep Manager-selected waters ({len(keys)} residue{'s' if len(keys) != 1 else ''})"
            )
        else:
            self.chk_keep_selected_waters.setText("Keep Manager-selected waters")

    def _source_has_ligand(self, text: str, fmt: str) -> bool:
        try:
            return source_has_ligand(text, fmt)
        except Exception:
            return False

    def _source_has_cif_ligand_bonds(self, text: str, fmt: str) -> bool:
        try:
            return source_has_cif_ligand_bonds(text, fmt)
        except Exception:
            return False

    def _sync_repair_options(self) -> None:
        on = self.chk_repair.isChecked()
        self.chk_rebuild_loops.setEnabled(on)
        self.list_chains.setEnabled(on)
        self.chk_skip_long_gaps.setEnabled(on)
        self.spin_max_gap.setEnabled(on and self.chk_skip_long_gaps.isChecked())
        self.chk_add_missing_atoms.setEnabled(on)
        self.chk_highest_altloc.setEnabled(on)
        self.chk_keep_metals.setEnabled(on)
        self.chk_keep_cofactors.setEnabled(on)
        self.chk_strip_additives.setEnabled(on)
        self._sync_min_options()

    def _sync_ligand_options(self) -> None:
        include = self.chk_include_ligand.isChecked()
        run_pqr = self.chk_protonate.isChecked()
        self.spin_ph.setEnabled(run_pqr)
        self.chk_keep_ligand.setEnabled(include)
        self.chk_protonate_ligand.setEnabled(run_pqr and include)
        self.edit_ligand_smiles.setEnabled(include)
        self.edit_ligand_ref.setEnabled(include)
        protonate_lig = run_pqr and include and self.chk_protonate_ligand.isChecked()
        pocket_was_enabled = self.chk_pocket_ligand.isEnabled()
        self.chk_pocket_ligand.setEnabled(protonate_lig)
        if protonate_lig and not pocket_was_enabled:
            self.chk_pocket_ligand.setChecked(True)
        elif not protonate_lig:
            self.chk_pocket_ligand.blockSignals(True)
            self.chk_pocket_ligand.setChecked(False)
            self.chk_pocket_ligand.blockSignals(False)
        self.chk_keep_bridging_waters.setEnabled(include)
        if not include:
            self.chk_keep_bridging_waters.setChecked(False)
        self._sync_water_cutoff()
        self._sync_min_options()

    def _sync_min_options(self) -> None:
        on = self.chk_minimize.isChecked()
        include = self.chk_include_ligand.isChecked()
        self.combo_protein_ff.setEnabled(on)
        self.combo_ligand_ff.setEnabled(on and include)
        self.combo_solvent.setEnabled(on)
        self.combo_openmm_platform.setEnabled(on)
        gb = (self.combo_solvent.currentData() or "gbn2") != "vacuum"
        self.spin_salt.setEnabled(on and gb)
        self.combo_restraint.setEnabled(on)
        self.spin_k.setEnabled(on)
        self.spin_iters.setEnabled(on)
        loops = self.chk_rebuild_loops.isChecked()
        self.chk_skip_pocket_loops.setEnabled(self.chk_repair.isChecked() and loops)
        if not loops:
            self.chk_skip_pocket_loops.setChecked(False)

    def _sync_water_cutoff(self, *_args) -> None:
        self.spin_water_cutoff.setEnabled(
            self.chk_include_ligand.isChecked() and self.chk_keep_bridging_waters.isChecked()
        )

    def _sync_smina_options(self) -> None:
        on = self.chk_write_smina.isChecked()
        loaded = self.radio_box_loaded.isChecked()
        self.radio_box_loaded.setEnabled(on)
        self.radio_box_file.setEnabled(on)
        self.combo_box_ligand.setEnabled(on and loaded and self.combo_box_ligand.count() > 0)
        self.box_ligand_file_row.setEnabled(on and not loaded)
        self.spin_box_padding.setEnabled(on)

    def _refresh_box_ligand_combo(self) -> None:
        self.combo_box_ligand.clear()
        options = []
        getter = getattr(self._viewer, "prepare_ligand_options", None)
        if callable(getter):
            options = list(getter() or [])
        selected_index = 0
        for i, item in enumerate(options):
            label, key, selected = item[0], item[1], item[2]
            sid = item[3] if len(item) > 3 else ""
            self.combo_box_ligand.addItem(label, {"key": key, "structure_id": sid})
            if selected:
                selected_index = i
        if options:
            self.combo_box_ligand.setCurrentIndex(selected_index)
        self._sync_smina_options()

    def _box_ligand_choice(self) -> tuple[tuple[str, str, str] | None, str]:
        data = self.combo_box_ligand.currentData()
        if isinstance(data, dict):
            key = data.get("key")
            sid = str(data.get("structure_id") or "")
            if isinstance(key, (tuple, list)) and len(key) >= 3:
                return (str(key[0]), str(key[1]), str(key[2])), sid
            return None, sid
        if isinstance(data, (tuple, list)) and len(data) >= 3:
            return (str(data[0]), str(data[1]), str(data[2])), ""
        return None, ""

    def _box_ligand_keys(self) -> tuple[tuple[str, str, str], ...]:
        if not self.chk_write_smina.isChecked() or not self.radio_box_loaded.isChecked():
            return ()
        key, _sid = self._box_ligand_choice()
        if not key:
            return ()
        return (key,)

    def _box_ligand_path(self) -> str:
        if not self.chk_write_smina.isChecked() or not self.radio_box_file.isChecked():
            return ""
        return (self.edit_box_ligand.text() or "").strip()

    def _box_source_payload(self) -> tuple[str, str]:
        if not self.chk_write_smina.isChecked() or not self.radio_box_loaded.isChecked():
            return "", ""
        _key, sid = self._box_ligand_choice()
        if not sid:
            return "", ""
        chosen_sid = self._chosen_manager_id()
        if sid and chosen_sid and sid == chosen_sid:
            return "", ""
        getter = getattr(self._viewer, "prepare_slot_payload", None)
        if callable(getter):
            text, fmt = getter(sid)
            return text or "", fmt or "pdb"
        return "", ""

    def _sync_output_suffix(self) -> None:
        path = (self.edit_out.text() or "").strip()
        if not path:
            return
        rec = Path(path)
        fmt = self.combo_out_fmt.currentData() or "cif"
        if fmt == "pdb":
            if rec.suffix.lower() != ".pdb":
                self.edit_out.setText(str(rec.with_suffix(".pdb")))
        elif rec.suffix.lower() not in {".cif", ".mmcif", ".mcif"}:
            self.edit_out.setText(str(rec.with_suffix(".cif")))

    def _browse_ligand_ref(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ligand bond-order file",
            self.edit_ligand_ref.text().strip(),
            "Ligand files (*.sdf *.sd *.mol *.mol2);;All files (*.*)",
        )
        if path:
            self.edit_ligand_ref.setText(path)

    def _browse_box_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Ligand for docking box",
            self.edit_box_ligand.text().strip(),
            "Ligand files (*.pdb *.pdbqt *.sdf *.sd *.mol *.mol2 *.cif);;All files (*.*)",
        )
        if path:
            self.edit_box_ligand.setText(path)
            self.radio_box_file.setChecked(True)

    def _browse_output(self) -> None:
        fmt = self.combo_out_fmt.currentData() or "cif"
        if fmt == "pdb":
            title = "Prepared PDB"
            filt = "PDB (*.pdb);;All files (*.*)"
        else:
            title = "Prepared mmCIF"
            filt = "mmCIF (*.cif *.mmcif *.mcif);;All files (*.*)"
        path, _ = QFileDialog.getSaveFileName(
            self,
            title,
            self.edit_out.text().strip(),
            filt,
        )
        if path:
            self.edit_out.setText(path)

    def _append_log(self, text: str) -> None:
        append_viewer_log(self._viewer, text)

    def _process_host(self):
        parent = self._viewer
        while parent is not None:
            if hasattr(parent, "process_queue"):
                return parent
            parent = parent.parent()
        return None

    def _on_run(self) -> None:
        self._resolved_source = None
        try:
            _name, text, fmt, _path = self.chosen_structure_source()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Fast Prepare", str(exc))
            return
        fmt = fmt or "pdb"
        run_repair = self.chk_repair.isChecked()
        run_protonate = self.chk_protonate.isChecked()
        keep_water_keys: tuple[tuple[str, str, str], ...] = ()
        if self.chk_keep_selected_waters.isChecked():
            keep_water_keys = self.chosen_water_keys()
        box_from_file = self.chk_write_smina.isChecked() and self.radio_box_file.isChecked()
        out_fmt = self.combo_out_fmt.currentData() or "cif"
        start = plan_protein_prepare_start(
            source_text=text,
            source_fmt=fmt,
            supported_formats=_PREPARE_FMTS,
            output_path=(self.edit_out.text() or "").strip(),
            output_format=out_fmt,
            repair=run_repair,
            protonate=run_protonate,
            minimize=self.chk_minimize.isChecked(),
            write_smina=self.chk_write_smina.isChecked(),
            keep_selected_waters=self.chk_keep_selected_waters.isChecked(),
            keep_water_keys=keep_water_keys,
            include_ligand=self.chk_include_ligand.isChecked(),
            ligand_ff=self.combo_ligand_ff.currentData() or "none",
            ligand_smiles=self.edit_ligand_smiles.text(),
            ligand_ref=self.edit_ligand_ref.text(),
            protonate_ligand=self.chk_protonate_ligand.isChecked(),
            box_from_file=box_from_file,
            box_ligand_path=self._box_ligand_path() if box_from_file else "",
            ligand_present=lambda: self._source_has_ligand(text, fmt),
            cif_ligand_bonds=lambda: self._source_has_cif_ligand_bonds(text, fmt),
            empty_source_message=self._source_empty_message,
        )
        if start.output_path:
            self.edit_out.setText(start.output_path)
        if start.message:
            box = QMessageBox.warning if start.warning else QMessageBox.information
            box(self, "Fast Prepare", start.message)
            return
        try:
            in_path = self._write_input_snapshot()
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Fast Prepare", str(exc))
            return

        box_source_text, box_source_fmt = self._box_source_payload()
        req = build_protein_prepare_request(
            input_path=str(in_path),
            output_path=start.output_path,
            output_format=out_fmt,
            ph=float(self.spin_ph.value()),
            rebuild_missing_loops=self.chk_rebuild_loops.isChecked(),
            include_ligand=self.chk_include_ligand.isChecked(),
            keep_ligand=self.chk_keep_ligand.isChecked(),
            keep_water_keys=keep_water_keys,
            keep_bridging_waters=self.chk_keep_bridging_waters.isChecked(),
            repair=run_repair,
            protonate=run_protonate,
            minimize=self.chk_minimize.isChecked(),
            ligand_smiles=self.edit_ligand_smiles.text(),
            ligand_ref_path=self.edit_ligand_ref.text(),
            protonate_ligand=self.chk_protonate_ligand.isChecked(),
            pocket_ligand=self.chk_pocket_ligand.isChecked(),
            restraint_k_kcal_per_ang2=float(self.spin_k.value()),
            max_minimize_iterations=int(self.spin_iters.value()),
            protein_ff=self.combo_protein_ff.currentData() or "amber14",
            ligand_ff=self.combo_ligand_ff.currentData() or "none",
            solvent=self.combo_solvent.currentData() or "gbn2",
            openmm_platform=self.combo_openmm_platform.currentData() or "auto",
            salt_m=float(self.spin_salt.value()),
            restraint_set=self.combo_restraint.currentData() or "backbone",
            skip_pocket_loops=self.chk_skip_pocket_loops.isChecked(),
            write_smina=self.chk_write_smina.isChecked(),
            box_padding=float(self.spin_box_padding.value()),
            box_ligand_keys=self._box_ligand_keys(),
            box_ligand_path=self._box_ligand_path(),
            box_source_text=box_source_text,
            box_source_fmt=box_source_fmt,
            extra=fixer_extra_request_kwargs(self),
        )
        self.btn_run.setEnabled(False)
        self.btn_open_smina.setEnabled(False)
        self._smina_result = None
        self.lbl_box_preview.setText("Box: —")
        steps = []
        if run_repair:
            steps.append("PDBFixer")
        if (
            run_protonate
            and self.chk_include_ligand.isChecked()
            and self.chk_protonate_ligand.isChecked()
        ):
            steps.append("Uni-pKa")
        if run_protonate:
            steps.append("pdb2pqr/PROPKA")
        if self.chk_minimize.isChecked():
            lig_ff = (
                (self.combo_ligand_ff.currentData() or "none")
                if self.chk_include_ligand.isChecked()
                else "none"
            )
            if lig_ff in {"gaff", "gaff2"}:
                steps.append(f"AmberTools/{lig_ff.upper()} + OpenMM")
            else:
                steps.append("OpenMM protein min")
        if self.chk_write_smina.isChecked():
            steps.append("Gnina files")
        self._append_log("Starting Fast Prepare: " + " → ".join(steps))
        host = self._process_host()
        if host is not None:
            host.process_queue.enqueue(
                "Fast Prepare",
                lambda ev, r=req, sig=self._signals: ProteinPrepareWorker(
                    r, signals=sig, cancel_event=ev
                ),
            )
            return
        from PyQt5.QtCore import QThreadPool

        QThreadPool.globalInstance().start(ProteinPrepareWorker(req, signals=self._signals))

    def _on_finished(self, result) -> None:
        from ...workers.protein_prepare_smina import ProteinPrepareResult

        self.btn_run.setEnabled(True)
        if isinstance(result, str):
            path = result
            smina = None
        elif isinstance(result, ProteinPrepareResult):
            path = result.output_path
            smina = result
        else:
            path = str(getattr(result, "output_path", "") or result)
            smina = result if getattr(result, "output_path", None) else None
        self._append_log(f"Prepared file written: {path}")
        if smina is not None:
            if smina.receptor_pdbqt:
                self._append_log(f"Receptor PDBQT: {smina.receptor_pdbqt}")
            if smina.ligand_sdf:
                self._append_log(f"Ligand SDF: {smina.ligand_sdf}")
            if smina.ligand_pdb:
                self._append_log(f"Autobox ligand: {smina.ligand_pdb}")
            if smina.box_path:
                self._append_log(f"Search box: {smina.box_path}")
            if smina.box is not None:
                box = smina.box
                self.lbl_box_preview.setText(
                    f"Box: center ({box.center_x:.2f}, {box.center_y:.2f}, {box.center_z:.2f})  "
                    f"size ({box.size_x:.1f}, {box.size_y:.1f}, {box.size_z:.1f}) Å"
                )
            if smina.warning:
                self._append_log(smina.warning)
            self._smina_result = smina
            self.btn_open_smina.setEnabled(smina.can_open_smina())
            self.smina_prepared.emit(smina)
        self.prepared.emit(path)
        self.close()

    def _on_open_smina(self) -> None:
        result = self._smina_result
        if result is None or not result.can_open_smina():
            QMessageBox.information(
                self,
                "Fast Prepare",
                "Prepare with Write Gnina files checked first.",
            )
            return
        host = self._process_host()
        opener = (
            (getattr(host, "open_gnina_dock", None) or getattr(host, "open_smina_dock", None))
            if host is not None
            else None
        )
        if not callable(opener):
            QMessageBox.information(
                self,
                "Fast Prepare",
                "Open Gnina from Protein → Dock Ligand → Gnina… and browse to the written files.",
            )
            return
        dlg = opener()
        apply = getattr(dlg, "apply_prepare_result", None)
        if callable(apply):
            apply(result)

    def _on_failed(self, msg: str) -> None:
        self.btn_run.setEnabled(True)
        self._append_log(msg or "Structure preparation failed.")
