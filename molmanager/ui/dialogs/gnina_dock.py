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

"""Modeless UI to run Gnina for receptor–ligand docking (optional flexible side chains)."""

from __future__ import annotations

import re
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

from PyQt5.QtCore import QProcess, Qt
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.bundled_paths import default_external_executable, resolve_user_executable
from ...platform_support.tool_paths import TOOL_GNINA, configured_executable
from ...docking.pose_file_io import AUTOBOX_LIGAND_FILTER
from ...docking.gnina_job import (
    GninaJobSettings,
    apply_dock_pharmacophore_filter,
    effective_out_path,
    ensemble_column_headers,
    flex_out_path,
    launch_argv_with_config,
    ligand_arg,
    ligand_cli_args,
    ligand_mol_from_ensemble,
    ligands_from_row_mols,
    load_ligand_template_mols,
    gnina_output_problem,
    gnina_receptor_problem,
    no_table_ligands_message,
    plan_gnina_run,
    table_row_dock_problem,
    normalize_flexres,
    require_dock_pharmacophore,
    resolve_work_path,
    same_input_path,
    write_smina_config,
)
from ...docking.gnina_launch import (
    cuda_available,
    gnina_missing_message,
    gnina_uses_wsl,
    resolve_gnina_command,
)
from ...protein.pharmacophore import PHARMACOPHORE_FILE_FILTER
from ...protein.pharmacophore_screen import DEFAULT_DOCK_SLACK_ANGSTROM
from ...workers.gnina_dock_worker import GninaDockWorker, system_stamp
from ..qt_widget_utils import append_viewer_log, make_window_minimizable

_RECEPTOR_FILE_FILTER = "Receptor (*.pdbqt *.pdb);;PDBQT (*.pdbqt);;PDB (*.pdb);;All files (*.*)"

_LIGAND_FILE_FILTER = (
    "Ligand (*.sdf *.sd *.mol2 *.mol *.pdbqt);;SDF (*.sdf *.sd);;"
    "MOL2 (*.mol2);;Molfile (*.mol);;PDBQT (*.pdbqt);;All files (*.*)"
)
_OUT_FILE_FILTER = "SDF (*.sdf *.sd);;PDBQT (*.pdbqt);;All files (*.*)"
_LOG_STAMP_RE = re.compile(r"^\[\d{2}:\d{2}:\d{2}\](?:\[system\])?\s*")

# Compat re-exports (tests import these from the dialog module).
_ligand_cli_args = ligand_cli_args
_write_smina_config = write_smina_config

__all__ = [
    "GninaDockDialog",
    "SminaDockDialog",
    "_ligand_cli_args",
    "_write_smina_config",
    "ensemble_column_headers",
    "flex_out_path",
    "ligand_mol_from_ensemble",
    "normalize_flexres",
]


class _GninaLogProxy:
    """Forward Gnina log lines to Protein Viewer without a dialog log pane."""

    def __init__(self, dialog: "GninaDockDialog") -> None:
        self._dialog = dialog

    def append(self, text: str) -> None:
        self._dialog._append_log(text)


def _browse_path_row(edit: QLineEdit, on_browse) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(4)
    row.addWidget(edit, 1)
    btn = QPushButton("Browse…")
    btn.setFixedWidth(76)
    btn.clicked.connect(on_browse)
    row.addWidget(btn)
    wrap = QWidget()
    wrap.setLayout(row)
    return wrap


def _spin_row(pairs: tuple[tuple[str, QWidget], ...]) -> QWidget:
    row = QHBoxLayout()
    row.setContentsMargins(0, 0, 0, 0)
    row.setSpacing(6)
    for label, widget in pairs:
        row.addWidget(QLabel(label))
        row.addWidget(widget, 1)
    wrap = QWidget()
    wrap.setLayout(row)
    return wrap


class GninaDockDialog(QDialog):
    """
    Front-end for the Gnina CLI (Smina/Vina-compatible docking with CNN scoring).

    Expects a receptor PDB or PDBQT, ligands from a file or selected table
    rows (conformations column), and a search box. Optional flexible side chains
    (--flexres / --flexdist); the backbone stays rigid. On Windows Gnina runs
    through Settings → Configure → WSL.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_dock_state(parent)
        self._build_dock_ui()

    def _init_dock_state(self, parent) -> None:
        self._main_window = parent
        self.setWindowTitle("Dock — Gnina")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumWidth(480)
        self.resize(540, 580)

        self._worker = GninaDockWorker(self)
        self._proc = self._worker.proc
        self._stdout_buf = ""
        self._stderr_buf = ""
        self._resolved_exe = ""
        self._batch_tmp: tempfile.TemporaryDirectory[str] | None = None
        self._batch_ligands: list[Path] = []
        self._batch_cancelled = False
        self._minimize_ins: list[Path] = []
        self._minimize_out: Path | None = None
        self._minimize_n_poses = 0
        self._placement_out = ""
        self._force_no_gpu = False
        self._crystal_ligand_path = ""
        self._prepare_receptor_path = ""
        self._apo_receptor_path = ""
        self._validation_tmp: tempfile.TemporaryDirectory[str] | None = None
        self._validation_phase = False
        self._validation_out = ""
        self._crystal_ref_mol = None
        self._crystal_rmsd: float | None = None
        self._pending_user_ligand: str | list[str] | None = None
        self._pending_user_out = ""
        self._stamp_crystal_on_poses = False
        self._validation_ligand_path = ""
        self._validation_pose_mols: list = []

    def _build_dock_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        io_gb = QGroupBox("Input / output")
        io_form = QFormLayout(io_gb)
        io_form.setContentsMargins(8, 6, 8, 6)
        io_form.setSpacing(4)
        self.edit_receptor = QLineEdit()
        self.edit_receptor.setPlaceholderText("receptor.pdbqt")
        self.edit_receptor.setToolTip(
            "Rigid receptor in PDB or PDBQT format. If this file still contains a "
            "ligand, it is stripped to apo for docking. Internal validation (on by "
            "default) redocks that crystal pose and reports RMSD."
        )
        io_form.addRow("Receptor:", _browse_path_row(self.edit_receptor, self._browse_receptor))

        self.combo_ligand_source = QComboBox()
        self.combo_ligand_source.addItem("File", "file")
        self.combo_ligand_source.addItem("Selected rows", "rows")
        self.combo_ligand_source.setToolTip(
            "Dock a ligand file, or every selected table row using a conformations column."
        )
        io_form.addRow("Ligand:", self.combo_ligand_source)

        self.edit_ligand = QLineEdit()
        self.edit_ligand.setPlaceholderText("ligand.sdf")
        self.edit_ligand.setToolTip(
            "Ligand SDF (also MOL/MOL2). PDBQT is accepted but converted to SDF first so "
            "aromatic and double bonds are not guessed from PDBQT."
        )
        self._lig_stack = QStackedWidget()
        self._lig_stack.addWidget(_browse_path_row(self.edit_ligand, self._browse_ligand))
        confs_wrap = QWidget()
        confs_row = QHBoxLayout(confs_wrap)
        confs_row.setContentsMargins(0, 0, 0, 0)
        confs_row.setSpacing(6)
        confs_row.addWidget(QLabel("Conformations:"))
        self.combo_confs = QComboBox()
        self.combo_confs.setToolTip(
            "Packed ensemble column (confs, superpose, …) or Structure for selected rows."
        )
        confs_row.addWidget(self.combo_confs, 1)
        self._lig_stack.addWidget(confs_wrap)
        io_form.addRow("", self._lig_stack)
        self.combo_ligand_source.currentIndexChanged.connect(self._sync_ligand_source)
        self._refresh_confs_columns()
        self._sync_ligand_source()

        self.edit_out = QLineEdit()
        self.edit_out.setPlaceholderText("out.sdf")
        self.edit_out.setToolTip(
            "Gnina writes docked poses here. SDF keeps bond orders; PDBQT does not."
        )
        self.save_sdf_cb = QCheckBox("Save as SDF")
        self.save_sdf_cb.setChecked(True)
        self.save_sdf_cb.setToolTip(
            "Write poses as SDF (Gnina --out). Uncheck to write PDBQT instead. "
            "PDBQT has no bond orders, so aromatics become singles."
        )
        self.save_sdf_cb.toggled.connect(self._sync_out_suffix)
        out_row = QHBoxLayout()
        out_row.setContentsMargins(0, 0, 0, 0)
        out_row.setSpacing(4)
        out_row.addWidget(self.edit_out, 1)
        btn_out = QPushButton("Browse…")
        btn_out.setFixedWidth(76)
        btn_out.clicked.connect(self._browse_out)
        out_row.addWidget(btn_out)
        out_row.addWidget(self.save_sdf_cb)
        out_wrap = QWidget()
        out_wrap.setLayout(out_row)
        io_form.addRow("Output:", out_wrap)

        self.edit_pharmacophore = QLineEdit()
        self.edit_pharmacophore.setPlaceholderText("pharmacophore.json (optional)")
        self.edit_pharmacophore.setToolTip(
            "MolManager pharmacophore JSON from Protein Viewer → Tools → Pharmacophore. "
            "Docking itself is unchanged (CNN/Vina). After poses are written, MolManager "
            "keeps only those whose RDKit feature sites sit in the query spheres "
            "(protein frame). Exclusion spheres reject poses with a heavy atom inside."
        )
        self.spin_pharma_slack = QDoubleSpinBox()
        self.spin_pharma_slack.setRange(0.0, 5.0)
        self.spin_pharma_slack.setDecimals(2)
        self.spin_pharma_slack.setSingleStep(0.1)
        self.spin_pharma_slack.setValue(0.50)
        self.spin_pharma_slack.setSuffix(" Å")
        self.spin_pharma_slack.setToolTip(
            "Extra tolerance (Å) added to each feature radius when matching docked poses. "
            "0 keeps the sphere as drawn."
        )
        ph_row = QHBoxLayout()
        ph_row.setContentsMargins(0, 0, 0, 0)
        ph_row.setSpacing(4)
        ph_row.addWidget(self.edit_pharmacophore, 1)
        btn_pharma = QPushButton("Browse…")
        btn_pharma.setFixedWidth(76)
        btn_pharma.clicked.connect(self._browse_pharmacophore)
        ph_row.addWidget(btn_pharma)
        ph_row.addWidget(QLabel("Slack:"))
        ph_row.addWidget(self.spin_pharma_slack)
        ph_wrap = QWidget()
        ph_wrap.setLayout(ph_row)
        io_form.addRow("Pharmacophore:", ph_wrap)
        root.addWidget(io_gb)

        box_gb = QGroupBox("Search box (Å)")
        box_form = QFormLayout(box_gb)
        box_form.setContentsMargins(8, 6, 8, 6)
        box_form.setSpacing(4)
        auto_row = QHBoxLayout()
        auto_row.setContentsMargins(0, 0, 0, 0)
        self.autobox_cb = QCheckBox("Autobox")
        self.autobox_cb.setToolTip(
            "Let Gnina set the search box from a ligand (--autobox_ligand). "
            "Browse for a reference ligand, or leave empty to use the docking ligand. "
            "Center and size are ignored."
        )
        auto_row.addWidget(self.autobox_cb)
        self.edit_autobox_ligand = QLineEdit()
        self.edit_autobox_ligand.setPlaceholderText("ligand.pdb or ligand.pdbqt (optional)")
        self.edit_autobox_ligand.setToolTip(
            "Ligand file whose coordinates define the autobox (PDB or PDBQT). "
            "Leave empty to use the docking ligand."
        )
        self.btn_autobox_ligand = QPushButton("Browse…")
        self.btn_autobox_ligand.setFixedWidth(76)
        self.btn_autobox_ligand.setToolTip("Choose a reference ligand for the autobox.")
        self.btn_autobox_ligand.clicked.connect(self._browse_autobox_ligand)
        lig_row = QHBoxLayout()
        lig_row.setContentsMargins(0, 0, 0, 0)
        lig_row.setSpacing(4)
        lig_row.addWidget(self.edit_autobox_ligand, 1)
        lig_row.addWidget(self.btn_autobox_ligand)
        lig_w = QWidget()
        lig_w.setLayout(lig_row)
        self._autobox_lig_row = lig_w
        auto_row.addWidget(lig_w, 1)
        auto_row.addWidget(QLabel("Pad:"))
        self.spin_autobox_add = QDoubleSpinBox()
        self.spin_autobox_add.setRange(0.0, 50.0)
        self.spin_autobox_add.setDecimals(2)
        self.spin_autobox_add.setSingleStep(0.5)
        self.spin_autobox_add.setValue(4.0)
        self.spin_autobox_add.setSuffix(" Å")
        self.spin_autobox_add.setToolTip(
            "Buffer added around the ligand bounding box (--autobox_add). Gnina default is 4 Å."
        )
        auto_row.addWidget(self.spin_autobox_add)
        auto_w = QWidget()
        auto_w.setLayout(auto_row)
        box_form.addRow(auto_w)

        self.spin_cx = QDoubleSpinBox()
        self.spin_cy = QDoubleSpinBox()
        self.spin_cz = QDoubleSpinBox()
        for sp in (self.spin_cx, self.spin_cy, self.spin_cz):
            sp.setRange(-10_000.0, 10_000.0)
            sp.setDecimals(3)
            sp.setSingleStep(0.5)
        self.spin_cx.setToolTip("Box center X (same coordinates as the receptor).")
        self.spin_cy.setToolTip("Box center Y.")
        self.spin_cz.setToolTip("Box center Z.")
        box_form.addRow(
            "Center:",
            _spin_row((("X", self.spin_cx), ("Y", self.spin_cy), ("Z", self.spin_cz))),
        )

        self.spin_sx = QDoubleSpinBox()
        self.spin_sy = QDoubleSpinBox()
        self.spin_sz = QDoubleSpinBox()
        for sp in (self.spin_sx, self.spin_sy, self.spin_sz):
            sp.setRange(1.0, 500.0)
            sp.setDecimals(2)
            sp.setSingleStep(1.0)
            sp.setValue(20.0)
        self.spin_sx.setToolTip("Box side length along X (default 20 Å).")
        box_form.addRow(
            "Size:",
            _spin_row((("X", self.spin_sx), ("Y", self.spin_sy), ("Z", self.spin_sz))),
        )
        self.autobox_cb.toggled.connect(self._sync_autobox)
        self._sync_autobox()
        root.addWidget(box_gb)

        flex_gb = QGroupBox("Flexible side chains")
        flex_form = QFormLayout(flex_gb)
        flex_form.setContentsMargins(8, 6, 8, 6)
        flex_form.setSpacing(4)
        self.combo_flex_mode = QComboBox()
        self.combo_flex_mode.addItem("Off (rigid receptor)", "off")
        self.combo_flex_mode.addItem("Distance from ligand", "dist")
        self.combo_flex_mode.addItem("Named residues", "res")
        self.combo_flex_mode.setToolTip(
            "Sample pocket side-chain rotamers during docking. The backbone stays rigid. "
            "Slower than a rigid receptor. Distance mode selects residues near a reference "
            "ligand (--flexdist). Named residues use CHAIN:RESNUM (--flexres)."
        )
        flex_form.addRow("Mode:", self.combo_flex_mode)

        self.edit_flexdist_ligand = QLineEdit()
        self.edit_flexdist_ligand.setPlaceholderText("crystal ligand (optional)")
        self.edit_flexdist_ligand.setToolTip(
            "Reference ligand for --flexdist_ligand. Empty uses the Autobox ligand, "
            "then the Prepare crystal ligand, then the docking ligand."
        )
        self.btn_flexdist_ligand = QPushButton("Browse…")
        self.btn_flexdist_ligand.setFixedWidth(76)
        self.btn_flexdist_ligand.setToolTip("Choose a reference ligand for flexible residues.")
        self.btn_flexdist_ligand.clicked.connect(self._browse_flexdist_ligand)
        flex_lig_row = QHBoxLayout()
        flex_lig_row.setContentsMargins(0, 0, 0, 0)
        flex_lig_row.setSpacing(4)
        flex_lig_row.addWidget(self.edit_flexdist_ligand, 1)
        flex_lig_row.addWidget(self.btn_flexdist_ligand)
        flex_lig_w = QWidget()
        flex_lig_w.setLayout(flex_lig_row)
        self.spin_flexdist = QDoubleSpinBox()
        self.spin_flexdist.setRange(0.5, 20.0)
        self.spin_flexdist.setDecimals(2)
        self.spin_flexdist.setSingleStep(0.5)
        self.spin_flexdist.setValue(3.5)
        self.spin_flexdist.setSuffix(" Å")
        self.spin_flexdist.setToolTip(
            "Any residue with a side-chain atom within this distance of the reference "
            "ligand is flexible (--flexdist). Gnina paper default is 3.5 Å."
        )
        dist_row = QHBoxLayout()
        dist_row.setContentsMargins(0, 0, 0, 0)
        dist_row.setSpacing(6)
        dist_row.addWidget(flex_lig_w, 1)
        dist_row.addWidget(QLabel("Dist:"))
        dist_row.addWidget(self.spin_flexdist)
        dist_w = QWidget()
        dist_w.setLayout(dist_row)
        self.edit_flexres = QLineEdit()
        self.edit_flexres.setPlaceholderText("A:123,A:145")
        self.edit_flexres.setToolTip(
            "Comma-separated residues to flex (--flexres), as CHAIN:RESNUM. "
            "Optional insertion code: A:123A."
        )
        self._flex_stack = QStackedWidget()
        self._flex_stack.addWidget(QWidget())
        self._flex_stack.addWidget(dist_w)
        res_w = QWidget()
        res_ly = QHBoxLayout(res_w)
        res_ly.setContentsMargins(0, 0, 0, 0)
        res_ly.addWidget(self.edit_flexres, 1)
        self._flex_stack.addWidget(res_w)
        flex_form.addRow("", self._flex_stack)

        self.spin_flex_max = QSpinBox()
        self.spin_flex_max.setRange(0, 64)
        self.spin_flex_max.setValue(0)
        self.spin_flex_max.setSpecialValueText("all")
        self.spin_flex_max.setToolTip(
            "Keep at most this many closest residues (--flex_max). 0 / all keeps every "
            "residue selected by distance. Ignored for named residues."
        )
        self.chk_full_flex = QCheckBox("Write full receptor")
        self.chk_full_flex.setToolTip(
            "Gnina --full_flex_output: --out_flex is the whole structure, not only "
            "the flexible residues. Off writes the side chains for each pose."
        )
        flex_extra = QHBoxLayout()
        flex_extra.setContentsMargins(0, 0, 0, 0)
        flex_extra.setSpacing(12)
        flex_extra.addWidget(QLabel("Max:"))
        flex_extra.addWidget(self.spin_flex_max)
        flex_extra.addWidget(self.chk_full_flex)
        flex_extra.addStretch()
        self._flex_extra_row = QWidget()
        self._flex_extra_row.setLayout(flex_extra)
        flex_form.addRow(self._flex_extra_row)
        self.combo_flex_mode.currentIndexChanged.connect(self._sync_flex_mode)
        self._sync_flex_mode()
        root.addWidget(flex_gb)

        opt_gb = QGroupBox("Search")
        opt_form = QFormLayout(opt_gb)
        opt_form.setContentsMargins(8, 6, 8, 6)
        opt_form.setSpacing(4)
        self.spin_exhaust = QSpinBox()
        self.spin_exhaust.setRange(1, 32)
        self.spin_exhaust.setValue(8)
        self.spin_exhaust.setToolTip("Exhaustiveness of the global search (typical 8).")
        self.spin_modes = QSpinBox()
        self.spin_modes.setRange(1, 100)
        self.spin_modes.setValue(9)
        self.spin_modes.setToolTip("Maximum number of binding modes to generate.")
        self.spin_cpu = QSpinBox()
        self.spin_cpu.setRange(0, 128)
        self.spin_cpu.setValue(0)
        self.spin_cpu.setSpecialValueText("auto")
        self.spin_cpu.setToolTip("CPU threads for Gnina; 0 / auto omits --cpu (tool default).")
        opt_form.addRow(
            "Search:",
            _spin_row(
                (
                    ("Exh.", self.spin_exhaust),
                    ("Modes", self.spin_modes),
                    ("CPU", self.spin_cpu),
                )
            ),
        )
        self.validate_crystal_cb = QCheckBox("Internal validation")
        self.validate_crystal_cb.setChecked(True)
        self.validate_crystal_cb.setToolTip(
            "When a crystal ligand is available (in the receptor file, or from Dock File / "
            "Fast Prepare), redock it with the same box and search settings and report "
            "heavy-atom RMSD of the top pose versus the crystal coordinates. Uncheck to skip."
        )
        self.minimize_poses_cb = QCheckBox("Minimize Docked Poses")
        self.minimize_poses_cb.setChecked(False)
        self.minimize_poses_cb.setToolTip(
            "After docking, energy-minimize all poses in the receptor in one Gnina process "
            "(--minimize). Results include both the placement pose and the minimized pose."
        )
        chk_row = QHBoxLayout()
        chk_row.setContentsMargins(0, 0, 0, 0)
        chk_row.setSpacing(12)
        chk_row.addWidget(self.validate_crystal_cb)
        chk_row.addWidget(self.minimize_poses_cb)
        chk_row.addStretch()
        chk_wrap = QWidget()
        chk_wrap.setLayout(chk_row)
        opt_form.addRow(chk_wrap)

        self.edit_wd = QLineEdit()
        self.edit_wd.setPlaceholderText("Optional working directory")
        self.edit_wd.setToolTip(
            "If set, Gnina starts with this as the current directory (relative paths resolve here)."
        )
        opt_form.addRow("Work dir:", self.edit_wd)

        self.edit_extra = QLineEdit()
        self.edit_extra.setPlaceholderText("Optional extra args (e.g. --seed 42)")
        self.edit_extra.setToolTip(
            "Additional Gnina flags. Flexible side chains have their own section above."
        )
        opt_form.addRow("Extra:", self.edit_extra)
        root.addWidget(opt_gb)

        cnn_gb = QGroupBox("CNN scoring")
        cnn_form = QFormLayout(cnn_gb)
        cnn_form.setContentsMargins(8, 6, 8, 6)
        cnn_form.setSpacing(4)
        self.combo_cnn_scoring = QComboBox()
        self.combo_cnn_scoring.addItem("Rescore", "rescore")
        self.combo_cnn_scoring.addItem("None (empirical)", "none")
        self.combo_cnn_scoring.addItem("Refinement", "refinement")
        self.combo_cnn_scoring.setToolTip(
            "When CNN scoring is applied. Rescore reranks final poses (Gnina default). "
            "None uses the empirical scoring function only. Refinement is slower."
        )
        cnn_form.addRow("CNN:", self.combo_cnn_scoring)
        self.combo_cnn_model = QComboBox()
        self.combo_cnn_model.addItem("Default ensemble", "")
        self.combo_cnn_model.addItem("dense", "dense")
        self.combo_cnn_model.addItem("fast", "fast")
        self.combo_cnn_model.addItem("crossdock_default2018", "crossdock_default2018")
        self.combo_cnn_model.setToolTip(
            "Built-in CNN. Default omits --cnn so Gnina uses its current ensemble."
        )
        cnn_form.addRow("Model:", self.combo_cnn_model)
        self.combo_pose_sort = QComboBox()
        self.combo_pose_sort.addItem("CNNscore", "CNNscore")
        self.combo_pose_sort.addItem("CNNaffinity", "CNNaffinity")
        self.combo_pose_sort.addItem("Energy", "Energy")
        self.combo_pose_sort.setToolTip("How Gnina sorts output poses (--pose_sort_order).")
        cnn_form.addRow("Sort poses:", self.combo_pose_sort)
        self.combo_emp_scoring = QComboBox()
        self.combo_emp_scoring.addItem("vina", "vina")
        self.combo_emp_scoring.addItem("vinardo", "vinardo")
        self.combo_emp_scoring.setToolTip(
            "Empirical scoring function used when CNN scoring is None (--scoring)."
        )
        cnn_form.addRow("Empirical:", self.combo_emp_scoring)
        self.gpu_cb = QCheckBox("Use GPU")
        self.gpu_cb.setChecked(sys.platform != "darwin")
        self.gpu_cb.setToolTip(
            "Use CUDA when available. Uncheck to pass --no_gpu. On Windows CUDA is probed "
            "inside WSL; if nvidia-smi fails, --no_gpu is added automatically."
        )
        cnn_form.addRow(self.gpu_cb)
        self.combo_cnn_scoring.currentIndexChanged.connect(self._sync_cnn_options)
        self._sync_cnn_options()
        root.addWidget(cnn_gb)

        self.log = _GninaLogProxy(self)

        btn_row = QHBoxLayout()
        self.btn_run = QPushButton("Run Gnina")
        self.btn_run.clicked.connect(self._run_gnina)
        btn_row.addWidget(self.btn_run)
        self.btn_stop = QPushButton("Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self._worker.stop)
        btn_row.addWidget(self.btn_stop)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_gnina)
        make_window_minimizable(self)

    def is_gnina_running(self) -> bool:
        return self._worker.is_running()

    is_smina_running = is_gnina_running

    def cancel_gnina(self) -> bool:
        if not self._worker.is_running():
            return False
        self._worker.stop()
        return True

    cancel_smina = cancel_gnina

    def _notify_activity(self) -> None:
        w = self._main_window
        hub = getattr(w, "background_activity", None) if w is not None else None
        if hub is not None:
            hub.notify_changed()

    def _protein_viewer(self):
        w = self._main_window
        finder = getattr(w, "_live_protein_viewer", None) if w is not None else None
        if callable(finder):
            dlg = finder()
            if dlg is not None:
                return dlg
        parent = self.parent()
        if hasattr(parent, "append_log"):
            return parent
        return None

    def _append_log(self, text: str) -> None:
        t = (text or "").rstrip()
        if not t:
            return
        t = _LOG_STAMP_RE.sub("", t, count=1)
        if not t:
            return
        append_viewer_log(self._protein_viewer(), t)

    def _dismiss_for_run(self) -> None:
        """Hide the setup dialog so CUDA/prep work cannot freeze it."""
        if self.isVisible():
            self.hide()
            QApplication.processEvents()

    def _reveal_dock_dialog(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _browse_receptor(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Receptor PDB / PDBQT", "", _RECEPTOR_FILE_FILTER
        )
        if path:
            self.edit_receptor.setText(path)
            prep = (self._prepare_receptor_path or "").strip()
            if prep and not self._same_input_path(path, prep):
                self._crystal_ligand_path = ""
                self._prepare_receptor_path = ""

    def _browse_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Ligand", "", _LIGAND_FILE_FILTER)
        if path:
            self.edit_ligand.setText(path)

    def _browse_pharmacophore(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Pharmacophore",
            self.edit_pharmacophore.text(),
            PHARMACOPHORE_FILE_FILTER,
        )
        if path:
            self.edit_pharmacophore.setText(path)

    def set_pharmacophore_path(self, path: str) -> None:
        """Fill the pharmacophore field (Protein Viewer → Send to Gnina)."""
        text = (path or "").strip()
        if text:
            self.edit_pharmacophore.setText(text)

    def _ligand_source_key(self) -> str:
        return str(self.combo_ligand_source.currentData() or "file")

    def _sync_ligand_source(self) -> None:
        rows = self._ligand_source_key() == "rows"
        self._lig_stack.setCurrentIndex(1 if rows else 0)
        if rows:
            self._refresh_confs_columns()

    def _refresh_confs_columns(self) -> None:
        current = (self.combo_confs.currentText() or "").strip()
        self.combo_confs.blockSignals(True)
        self.combo_confs.clear()
        for name in ensemble_column_headers(self._main_window):
            self.combo_confs.addItem(name)
        self.combo_confs.addItem("Structure")
        idx = self.combo_confs.findText(current)
        if idx < 0:
            idx = self.combo_confs.findText("confs")
        if idx >= 0:
            self.combo_confs.setCurrentIndex(idx)
        self.combo_confs.blockSignals(False)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if self._ligand_source_key() == "rows":
            self._refresh_confs_columns()

    def _browse_autobox_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Autobox reference ligand",
            self.edit_autobox_ligand.text() or self.edit_ligand.text(),
            AUTOBOX_LIGAND_FILTER,
        )
        if path:
            self.edit_autobox_ligand.setText(path)

    def _sync_autobox(self) -> None:
        auto = bool(self.autobox_cb.isChecked())
        self.spin_autobox_add.setEnabled(auto)
        self._autobox_lig_row.setEnabled(auto)
        for sp in (
            self.spin_cx,
            self.spin_cy,
            self.spin_cz,
            self.spin_sx,
            self.spin_sy,
            self.spin_sz,
        ):
            sp.setEnabled(not auto)

    def _browse_flexdist_ligand(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Flexible-residue reference ligand",
            self.edit_flexdist_ligand.text()
            or self.edit_autobox_ligand.text()
            or self.edit_ligand.text(),
            AUTOBOX_LIGAND_FILTER,
        )
        if path:
            self.edit_flexdist_ligand.setText(path)

    def _flex_mode(self) -> str:
        return str(self.combo_flex_mode.currentData() or "off")

    def _sync_flex_mode(self) -> None:
        mode = self._flex_mode()
        on = mode != "off"
        page = {"off": 0, "dist": 1, "res": 2}.get(mode, 0)
        self._flex_stack.setCurrentIndex(page)
        self._flex_stack.setVisible(on)
        self._flex_extra_row.setVisible(on)
        self.spin_flex_max.setEnabled(mode == "dist")
        self.chk_full_flex.setEnabled(on)

    def _flexdist_ligand_path(self, dock_ligand: str) -> str:
        from ...docking.gnina_job import flexdist_ligand_path

        return flexdist_ligand_path(
            explicit=self.edit_flexdist_ligand.text(),
            autobox=self.edit_autobox_ligand.text(),
            crystal=self._crystal_ligand_path,
            dock_ligand=dock_ligand,
        )

    def _job_settings(self, *, no_gpu: bool | None = None) -> GninaJobSettings:
        force_cpu = (
            bool(no_gpu)
            if no_gpu is not None
            else (
                (not self.gpu_cb.isChecked())
                or sys.platform == "darwin"
                or bool(getattr(self, "_force_no_gpu", False))
            )
        )
        return GninaJobSettings(
            receptor=self._receptor_for_gnina(),
            autobox=bool(self.autobox_cb.isChecked()),
            autobox_ligand=(self.edit_autobox_ligand.text() or "").strip(),
            autobox_add=float(self.spin_autobox_add.value()),
            center_x=float(self.spin_cx.value()),
            center_y=float(self.spin_cy.value()),
            center_z=float(self.spin_cz.value()),
            size_x=float(self.spin_sx.value()),
            size_y=float(self.spin_sy.value()),
            size_z=float(self.spin_sz.value()),
            exhaustiveness=int(self.spin_exhaust.value()),
            num_modes=int(self.spin_modes.value()),
            cpu=int(self.spin_cpu.value()),
            extra=(self.edit_extra.text() or "").strip(),
            flex_mode=self._flex_mode(),
            flexdist_ligand=(self.edit_flexdist_ligand.text() or "").strip(),
            crystal_ligand=(self._crystal_ligand_path or "").strip(),
            flexdist=float(self.spin_flexdist.value()),
            flex_max=int(self.spin_flex_max.value()),
            flexres=self.edit_flexres.text(),
            full_flex=bool(self.chk_full_flex.isChecked()),
            cnn_scoring=str(self.combo_cnn_scoring.currentData() or "rescore"),
            emp_scoring=str(self.combo_emp_scoring.currentData() or "vina"),
            pose_sort=str(self.combo_pose_sort.currentData() or "CNNscore"),
            cnn_model=str(self.combo_cnn_model.currentData() or ""),
            no_gpu=force_cpu,
            save_sdf=bool(self.save_sdf_cb.isChecked()),
            work_dir=(self.edit_wd.text() or "").strip(),
        )

    def _flex_argv(self, *, dock_ligand: str, out_path: str) -> list[str]:
        """Gnina flexible-side-chain flags, or empty when the receptor is rigid."""
        from ...docking.gnina_job import build_flex_argv

        return build_flex_argv(self._job_settings(), dock_ligand=dock_ligand, out_path=out_path)

    def _sync_cnn_options(self) -> None:
        cnn_none = self.combo_cnn_scoring.currentData() == "none"
        self.combo_emp_scoring.setEnabled(cnn_none)
        self.combo_cnn_model.setEnabled(not cnn_none)
        self.combo_pose_sort.setEnabled(not cnn_none)

    def apply_prepare_result(self, result) -> None:
        """Fill receptor and numeric box from Protein Viewer Prepare; leave ligand empty.

        Crystal ligand SDF/PDB from Dock File / Fast Prepare is kept for internal
        validation (redock + RMSD), not as the docking ligand field.
        """
        from ...docking.redock_validation import existing_crystal_ligand_path

        receptor = ""
        getter = getattr(result, "receptor_pdbqt_path", None)
        if callable(getter):
            receptor = str(getter() or "").strip()
        if not receptor:
            receptor = str(getattr(result, "receptor_pdbqt", "") or "").strip()
        if Path(receptor).suffix.lower() != ".pdbqt":
            output = str(getattr(result, "output_path", "") or "").strip()
            receptor = (
                output if Path(output).suffix.lower() == ".pdbqt" and Path(output).is_file() else ""
            )
        elif receptor and not Path(receptor).is_file():
            receptor = ""
        autobox = str(getattr(result, "ligand_pdb", "") or "").strip()
        sdf = existing_crystal_ligand_path(getattr(result, "ligand_sdf", ""))
        pdb = existing_crystal_ligand_path(getattr(result, "ligand_pdb", ""))
        self._crystal_ligand_path = sdf or pdb
        self._prepare_receptor_path = receptor
        self.combo_ligand_source.setCurrentIndex(self.combo_ligand_source.findData("file"))
        self.edit_ligand.clear()
        if receptor:
            self.edit_receptor.setText(receptor)
            if not (self.edit_out.text() or "").strip():
                rec_path = Path(receptor)
                self.edit_out.setText(str(rec_path.with_name(f"{rec_path.stem}_docked.sdf")))
        if autobox:
            self.edit_autobox_ligand.setText(autobox)
            self.edit_flexdist_ligand.setText(autobox)
        box = getattr(result, "box", None)
        if box is not None:
            self.autobox_cb.setChecked(False)
            self.spin_cx.setValue(float(box.center_x))
            self.spin_cy.setValue(float(box.center_y))
            self.spin_cz.setValue(float(box.center_z))
            self.spin_sx.setValue(float(box.size_x))
            self.spin_sy.setValue(float(box.size_y))
            self.spin_sz.setValue(float(box.size_z))
        self._sync_autobox()

    def _autobox_ligand_path(self, dock_ligand: str) -> str:
        from ...docking.gnina_job import autobox_ligand_path

        return autobox_ligand_path((self.edit_autobox_ligand.text() or "").strip(), dock_ligand)

    def _browse_out(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Docked output", "", _OUT_FILE_FILTER)
        if path:
            self.edit_out.setText(path)

    def _sync_out_suffix(self, checked: bool) -> None:
        text = (self.edit_out.text() or "").strip()
        if not text:
            self.edit_out.setPlaceholderText("out.sdf" if checked else "out.pdbqt")
            return
        path = Path(text)
        suf = path.suffix.lower()
        if checked and suf == ".pdbqt":
            self.edit_out.setText(str(path.with_suffix(".sdf")))
        elif not checked and suf in {".sdf", ".sd"}:
            self.edit_out.setText(str(path.with_suffix(".pdbqt")))

    def _effective_out_path(self, out: str | None = None) -> str:
        text = (out if out is not None else self.edit_out.text() or "").strip()
        return effective_out_path(text, save_sdf=self.save_sdf_cb.isChecked())

    def _gnina_executable(self) -> str:
        return configured_executable(TOOL_GNINA) or default_external_executable("gnina")

    def _smina_executable(self) -> str:
        return self._gnina_executable()

    def _set_running_ui(self, running: bool) -> None:
        self.btn_run.setEnabled(not running)
        self.btn_stop.setEnabled(running)

    def _ensure_batch_tmp(self, prefix: str) -> Path:
        if self._batch_tmp is None:
            self._batch_tmp = tempfile.TemporaryDirectory(prefix=prefix)
        return Path(self._batch_tmp.name)

    def _launch_argv(self, argv: list[str]) -> list[str]:
        """Use ``--config`` when several ligands would bloat the command line."""
        if argv.count("--ligand") <= 1:
            return argv
        cfg = self._ensure_batch_tmp("gnina_cfg_") / "gnina.conf"
        return launch_argv_with_config(argv, cfg)

    def _receptor_for_gnina(self) -> str:
        return (self._apo_receptor_path or self.edit_receptor.text() or "").strip()

    def _build_argv(
        self,
        *,
        ligand: str | Sequence[str] | None = None,
        out: str | None = None,
        receptor: str | None = None,
    ) -> list[str]:
        from ...docking.gnina_job import build_gnina_argv

        lig_src: str | Sequence[str] = (
            ligand if ligand is not None else (self.edit_ligand.text() or "")
        )
        out_path = (out if out is not None else self._effective_out_path()).strip()
        rec = (receptor if receptor is not None else self._receptor_for_gnina()).strip()
        return build_gnina_argv(self._job_settings(), ligand=lig_src, out=out_path, receptor=rec)

    def _require_dock_pharmacophore(self) -> None:
        """Raise if the Pharmacophore field is set but the JSON cannot be used."""
        require_dock_pharmacophore((self.edit_pharmacophore.text() or "").strip())

    def _apply_pharmacophore_filter(self, mols: list, *, log: bool = True) -> list:
        """Keep docked poses that occupy the query spheres in the protein frame."""
        slack = (
            float(self.spin_pharma_slack.value())
            if getattr(self, "spin_pharma_slack", None) is not None
            else DEFAULT_DOCK_SLACK_ANGSTROM
        )
        kept, msg = apply_dock_pharmacophore_filter(
            mols,
            (self.edit_pharmacophore.text() or "").strip(),
            slack=slack,
        )
        if log and msg:
            self.log.append(system_stamp(msg))
        return kept

    def _cnn_argv(self, *, no_gpu: bool | None = None) -> list[str]:
        from ...docking.gnina_job import build_cnn_argv

        return build_cnn_argv(self._job_settings(no_gpu=no_gpu))

    def _build_minimize_argv(self, ligand: str | Sequence[str], out: str) -> list[str]:
        from ...docking.gnina_job import build_minimize_argv

        return build_minimize_argv(
            self._job_settings(),
            ligand,
            out,
            receptor=self._receptor_for_gnina(),
        )

    def _clear_batch(self) -> None:
        self._batch_ligands = []
        self._batch_cancelled = False
        self._minimize_ins = []
        self._minimize_out = None
        self._minimize_n_poses = 0
        self._placement_out = ""
        self._apo_receptor_path = ""
        self._validation_phase = False
        self._validation_out = ""
        self._crystal_ref_mol = None
        self._pending_user_ligand = None
        self._pending_user_out = ""
        self._stamp_crystal_on_poses = False
        self._validation_ligand_path = ""
        self._validation_pose_mols = []
        tmp = self._batch_tmp
        self._batch_tmp = None
        if tmp is not None:
            try:
                tmp.cleanup()
            except Exception:
                pass
        vtmp = self._validation_tmp
        self._validation_tmp = None
        if vtmp is not None:
            try:
                vtmp.cleanup()
            except Exception:
                pass

    def _resolve_path(self, path: str) -> Path:
        return resolve_work_path(path, self.edit_wd.text())

    def _is_openbabel_ligand(self, path: str) -> bool:
        from ...docking.pose_file_io import ligand_is_openbabel_format

        return ligand_is_openbabel_format(self._resolve_path(path))

    def _ligand_template_mols(self):
        """Input ligand molecules used to restore Kekulé/aromatic bonds on SDF poses."""
        paths: list[Path] = []
        paths.extend(self._batch_ligands)
        lig = (self.edit_ligand.text() or "").strip()
        if lig:
            paths.append(self._resolve_path(lig))
        return load_ligand_template_mols(paths)

    def _ligand_template_mol(self):
        """First input ligand molecule, used to restore bond orders."""
        mols = self._ligand_template_mols()
        return mols[0] if mols else None

    def _prepare_gnina_ligands(self, ligand: str) -> list[Path]:
        """Return ligand files to pass to Gnina (SDF when bond orders can be restored)."""
        if self._ligand_source_key() == "rows":
            return self._prepare_table_row_ligands()
        return self._worker.prepare_file_ligands(ligand)

    def _prepare_table_row_ligands(self) -> list[Path]:
        """Write selected-row ensembles to a temp SDF for one Gnina process."""
        from ...docking.pose_file_io import write_pose_mols_sdf

        mols = self._mols_from_selected_rows()
        if not mols:
            col = (self.combo_confs.currentText() or "").strip()
            raise ValueError(no_table_ligands_message(col))
        self._clear_batch()
        tmp = self._ensure_batch_tmp("gnina_table_")
        dest = tmp / "table_ligands.sdf"
        n_written = write_pose_mols_sdf(mols, dest)
        if n_written < 1:
            raise ValueError("Could not write selected-row ligands as SDF.")
        self._batch_ligands = [dest]
        self.log.append(
            system_stamp(
                f"Docking {n_written} ligand(s) from "
                f"{len(self._selected_row_indices())} selected row(s) "
                f"({self.combo_confs.currentText() or 'Structure'})."
            )
        )
        return [dest]

    def _selected_row_indices(self) -> list[int]:
        app = self._main_window
        getter = getattr(app, "_selected_logical_rows", None) if app is not None else None
        if not callable(getter):
            return []
        try:
            return [int(r) for r in getter()]
        except Exception:
            return []

    def _mols_from_selected_rows(self) -> list:
        from ...ui.main_window.conformer_writeback import mol_for_ensemble_column

        app = self._main_window
        rows = self._selected_row_indices()
        column = (self.combo_confs.currentText() or "").strip()
        problem = table_row_dock_problem(
            has_window=app is not None,
            selected_rows=len(rows),
            column=column,
        )
        if problem:
            raise ValueError(problem)
        if column == "Structure":
            collect = getattr(app, "collect_scoped_table_mols", None)
            if not callable(collect):
                raise ValueError("The table is not available for selected-row docking.")
            return ligands_from_row_mols(list(collect("Structure", only_selected=True)))
        model = getattr(app, "_table_model", None)
        if model is None:
            raise ValueError("The table is not available for selected-row docking.")
        pairs: list[tuple[int, object]] = []
        for row in rows:
            try:
                oid = int(model.row_oid(row))
            except Exception:
                continue
            pairs.append((oid, mol_for_ensemble_column(app, oid, column, min_conformers=1)))
        return ligands_from_row_mols(pairs)

    def _prepare_ligand_batch(self, ligand: str) -> int:
        paths = self._prepare_gnina_ligands(ligand)
        return len(paths)

    def _same_input_path(self, left: str, right: str) -> bool:
        return same_input_path(left, right, work_dir=self.edit_wd.text())

    def _ensure_validation_tmp(self) -> Path:
        if self._validation_tmp is None:
            self._validation_tmp = tempfile.TemporaryDirectory(prefix="gnina_valid_")
        return Path(self._validation_tmp.name)

    def _ligand_arg(self, lig_paths: list[Path]) -> str | list[str]:
        return ligand_arg(lig_paths)

    def _sidecar_for_receptor(self, rec: str) -> str:
        from ...docking.gnina_job import sidecar_for_receptor

        return sidecar_for_receptor(
            rec,
            sidecar=self._crystal_ligand_path,
            prepare_receptor=self._prepare_receptor_path,
            work_dir=self.edit_wd.text(),
        )

    def _run_gnina(self) -> None:
        if self._proc.state() != QProcess.NotRunning:
            QMessageBox.information(self, "Dock", "A Gnina run is already in progress.")
            return
        try:
            exe = self._gnina_executable()
        except Exception as e:
            QMessageBox.warning(self, "Dock", str(e))
            return
        if gnina_uses_wsl():
            from ...platform_support.wsl_launcher import wsl_available

            if not wsl_available():
                QMessageBox.warning(
                    self,
                    "Dock",
                    "WSL was not found. Set the WSL executable under Settings → Configure → WSL, "
                    "then install Gnina in that distro so `gnina` is on PATH.",
                )
                return
            resolved = resolve_gnina_command(exe)
            if resolved is None:
                QMessageBox.warning(self, "Dock", gnina_missing_message(exe))
                return
            exe = resolved
        else:
            resolved = resolve_gnina_command(exe) or resolve_user_executable(exe)
            if resolved is None:
                QMessageBox.warning(self, "Dock", gnina_missing_message(exe))
                return
            exe = resolved
        self._resolved_exe = exe
        self._dismiss_for_run()
        self._force_no_gpu = False
        self._crystal_rmsd = None
        self._apo_receptor_path = ""
        self._validation_phase = False
        self._stamp_crystal_on_poses = False
        self._pending_user_ligand = None
        self._pending_user_out = ""
        self._validation_ligand_path = ""
        self._validation_pose_mols = []
        if self.gpu_cb.isChecked() and sys.platform != "darwin":
            if not cuda_available():
                self._force_no_gpu = True
                self.log.append(system_stamp("CUDA not found (nvidia-smi); using --no_gpu."))
        elif not self.gpu_cb.isChecked() or sys.platform == "darwin":
            self._force_no_gpu = True

        rec = (self.edit_receptor.text() or "").strip()
        lig = (self.edit_ligand.text() or "").strip()
        rows = self._ligand_source_key() == "rows"
        lig_paths: list[Path] = []
        try:
            if rows or lig:
                lig_paths = self._prepare_gnina_ligands(lig)
            out = self._effective_out_path()
            rec_path = self._resolve_path(rec) if rec else Path()
            receptor_problem = gnina_receptor_problem(rec, rec_path)
            if receptor_problem:
                raise ValueError(receptor_problem)
            self._require_dock_pharmacophore()
            output_problem = gnina_output_problem(out)
            if output_problem:
                raise ValueError(output_problem)
            self._worker.setup_crystal_validation(
                rec,
                durable_dir=self._resolve_path(out).parent,
                validate=self.validate_crystal_cb.isChecked(),
            )
            crystal_lig = (self._validation_ligand_path or "").strip()
            same_crystal = bool(
                lig_paths and crystal_lig and self._same_input_path(str(lig_paths[0]), crystal_lig)
            )
            run_plan = plan_gnina_run(
                ligand_paths=lig_paths,
                crystal_ligand=crystal_lig,
                same_crystal_ligand=same_crystal,
            )
            if run_plan.message:
                raise ValueError(run_plan.message)
            extra_validation = run_plan.extra_validation
            if run_plan.ligand_paths_are_crystal:
                lig_paths = [Path(crystal_lig)]
                self._stamp_crystal_on_poses = True
                self.log.append(system_stamp("No docking ligand; redocking the crystal ligand."))
            elif run_plan.stamp_crystal_on_poses:
                self._stamp_crystal_on_poses = True
            ligand_spec = self._ligand_arg(lig_paths)
            if extra_validation:
                vout = str(self._ensure_validation_tmp() / "crystal_redock.sdf")
                self._validation_out = vout
                self._pending_user_ligand = ligand_spec
                self._pending_user_out = out
                self._validation_phase = True
                argv = self._build_argv(ligand=crystal_lig, out=vout)
            else:
                argv = self._build_argv(ligand=ligand_spec, out=out)
        except Exception as e:
            self._clear_batch()
            self._reveal_dock_dialog()
            QMessageBox.warning(self, "Dock", str(e))
            return

        out_path = Path(out)
        if lig_paths and self._is_openbabel_ligand(str(lig_paths[0])):
            self.log.append(
                system_stamp(f"Ligand and output are {out_path.suffix.lower() or 'SDF'}.")
            )
        if len(lig_paths) > 1:
            self.log.append(
                system_stamp(
                    f"Ligand PDBQT has {len(lig_paths)} records; docking them in one Gnina process."
                )
            )
        elif self._batch_ligands and self._is_openbabel_ligand(str(self._batch_ligands[0])):
            self.log.append(
                system_stamp("Converted ligand PDBQT to SDF so OpenBabel can use bond orders.")
            )
        launch = self._launch_argv(argv)
        self.log.append(system_stamp(f"Launch: {exe} {' '.join(launch)}"))
        self._notify_activity()
        self._worker.start_process(launch)

    _run_smina = _run_gnina
    _prepare_smina_ligands = _prepare_gnina_ligands

    def gnina_session_state(self) -> dict:
        """Paths and options to restore this Gnina dialog in a later session."""
        return {
            "receptor": (self.edit_receptor.text() or "").strip(),
            "ligand_source": str(self.combo_ligand_source.currentData() or "file"),
            "ligand": (self.edit_ligand.text() or "").strip(),
            "confs_column": (self.combo_confs.currentText() or "").strip(),
            "output": (self.edit_out.text() or "").strip(),
            "save_sdf": bool(self.save_sdf_cb.isChecked()),
            "pharmacophore": (self.edit_pharmacophore.text() or "").strip(),
            "pharma_slack": float(self.spin_pharma_slack.value()),
            "autobox": bool(self.autobox_cb.isChecked()),
            "autobox_ligand": (self.edit_autobox_ligand.text() or "").strip(),
            "autobox_add": float(self.spin_autobox_add.value()),
            "center_x": float(self.spin_cx.value()),
            "center_y": float(self.spin_cy.value()),
            "center_z": float(self.spin_cz.value()),
            "size_x": float(self.spin_sx.value()),
            "size_y": float(self.spin_sy.value()),
            "size_z": float(self.spin_sz.value()),
            "flex_mode": str(self.combo_flex_mode.currentData() or "off"),
            "flexdist_ligand": (self.edit_flexdist_ligand.text() or "").strip(),
            "flexdist": float(self.spin_flexdist.value()),
            "flexres": (self.edit_flexres.text() or "").strip(),
            "flex_max": int(self.spin_flex_max.value()),
            "full_flex": bool(self.chk_full_flex.isChecked()),
            "exhaustiveness": int(self.spin_exhaust.value()),
            "num_modes": int(self.spin_modes.value()),
            "cpu": int(self.spin_cpu.value()),
            "validate_crystal": bool(self.validate_crystal_cb.isChecked()),
            "minimize_poses": bool(self.minimize_poses_cb.isChecked()),
            "work_dir": (self.edit_wd.text() or "").strip(),
            "extra": (self.edit_extra.text() or "").strip(),
            "cnn_scoring": str(self.combo_cnn_scoring.currentData() or "rescore"),
            "cnn_model": str(self.combo_cnn_model.currentData() or ""),
            "pose_sort": str(self.combo_pose_sort.currentData() or "CNNscore"),
            "emp_scoring": str(self.combo_emp_scoring.currentData() or "vina"),
            "gpu": bool(self.gpu_cb.isChecked()),
            "crystal_ligand": (self._crystal_ligand_path or "").strip(),
            "prepare_receptor": (self._prepare_receptor_path or "").strip(),
        }

    def apply_gnina_session(self, state: dict) -> None:
        """Refill the dialog from a session snapshot."""
        if not isinstance(state, dict):
            return

        def _set_line(widget, key: str) -> None:
            if key not in state:
                return
            widget.setText(str(state.get(key) or ""))

        def _spin(widget, key: str, cast) -> None:
            if key not in state:
                return
            try:
                widget.setValue(cast(state[key]))
            except (TypeError, ValueError):
                return

        def _combo(widget, key: str) -> None:
            if key not in state:
                return
            idx = widget.findData(state.get(key))
            if idx < 0:
                idx = widget.findData(str(state.get(key) or ""))
            if idx >= 0:
                widget.setCurrentIndex(idx)

        def _check(widget, key: str) -> None:
            if isinstance(state.get(key), bool):
                widget.setChecked(state[key])

        _set_line(self.edit_receptor, "receptor")
        _combo(self.combo_ligand_source, "ligand_source")
        _set_line(self.edit_ligand, "ligand")
        confs = str(state.get("confs_column") or "").strip() if "confs_column" in state else ""
        if confs:
            idx = self.combo_confs.findText(confs)
            if idx < 0:
                self.combo_confs.addItem(confs)
                idx = self.combo_confs.findText(confs)
            if idx >= 0:
                self.combo_confs.setCurrentIndex(idx)
        if isinstance(state.get("save_sdf"), bool):
            self.save_sdf_cb.blockSignals(True)
            self.save_sdf_cb.setChecked(state["save_sdf"])
            self.save_sdf_cb.blockSignals(False)
        _set_line(self.edit_out, "output")
        if not (self.edit_out.text() or "").strip():
            self._sync_out_suffix(self.save_sdf_cb.isChecked())
        _set_line(self.edit_pharmacophore, "pharmacophore")
        _spin(self.spin_pharma_slack, "pharma_slack", float)
        _check(self.autobox_cb, "autobox")
        _set_line(self.edit_autobox_ligand, "autobox_ligand")
        _spin(self.spin_autobox_add, "autobox_add", float)
        _spin(self.spin_cx, "center_x", float)
        _spin(self.spin_cy, "center_y", float)
        _spin(self.spin_cz, "center_z", float)
        _spin(self.spin_sx, "size_x", float)
        _spin(self.spin_sy, "size_y", float)
        _spin(self.spin_sz, "size_z", float)
        _combo(self.combo_flex_mode, "flex_mode")
        _set_line(self.edit_flexdist_ligand, "flexdist_ligand")
        _spin(self.spin_flexdist, "flexdist", float)
        _set_line(self.edit_flexres, "flexres")
        _spin(self.spin_flex_max, "flex_max", int)
        _check(self.chk_full_flex, "full_flex")
        _spin(self.spin_exhaust, "exhaustiveness", int)
        _spin(self.spin_modes, "num_modes", int)
        _spin(self.spin_cpu, "cpu", int)
        _check(self.validate_crystal_cb, "validate_crystal")
        _check(self.minimize_poses_cb, "minimize_poses")
        _set_line(self.edit_wd, "work_dir")
        _set_line(self.edit_extra, "extra")
        _combo(self.combo_cnn_scoring, "cnn_scoring")
        _combo(self.combo_cnn_model, "cnn_model")
        _combo(self.combo_pose_sort, "pose_sort")
        _combo(self.combo_emp_scoring, "emp_scoring")
        _check(self.gpu_cb, "gpu")
        if "crystal_ligand" in state:
            self._crystal_ligand_path = str(state.get("crystal_ligand") or "").strip()
        if "prepare_receptor" in state:
            self._prepare_receptor_path = str(state.get("prepare_receptor") or "").strip()

    def _remember_gnina_session(self) -> None:
        host = self._main_window
        remember = getattr(host, "remember_gnina_dock_session", None)
        if callable(remember):
            remember(self.gnina_session_state())

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._remember_gnina_session()
        if self._worker.is_running():
            self._worker.stop()
        else:
            self._clear_batch()
        self._notify_activity()
        super().closeEvent(event)


def gnina_session_worth_saving(state: object) -> bool:
    """True when the snapshot has a docking setup worth keeping in the session file."""
    if not isinstance(state, dict):
        return False
    for key in (
        "receptor",
        "ligand",
        "output",
        "pharmacophore",
        "autobox_ligand",
        "flexdist_ligand",
        "flexres",
        "work_dir",
        "extra",
        "crystal_ligand",
        "prepare_receptor",
    ):
        if str(state.get(key) or "").strip():
            return True
    if str(state.get("ligand_source") or "") == "rows":
        return True
    return str(state.get("flex_mode") or "off") not in {"", "off"}


SminaDockDialog = GninaDockDialog
