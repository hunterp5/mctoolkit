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


"""Standalone Protein Viewer window (3D canvas + chain Manager)."""

from __future__ import annotations

import base64
import logging
import sys
from datetime import datetime

from PyQt5.QtCore import QEventLoop, Qt, QTimer
from PyQt5.QtGui import QCloseEvent, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMenuBar,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..protein.structure_components import PolymerChain, cif_viewer_bond_tables
from .protein_chain_manager import ProteinChainManager
from .protein_embed import ProteinEmbedView
from .protein_sequence import ProteinSequenceDialog
from .protein_viewer_edit_mixin import ProteinViewerEditMixin
from .protein_viewer_io_mixin import ProteinViewerIoMixin
from .protein_viewer_models import (
    LIGAND_STYLE_CHOICES,
    LIGAND_STYLE_IDS,
    NamedManagerGroup,
    _LoadedSlot,
    _RENDER_COLOR_SPEC,
)
from .protein_viewer_overlays import ProteinViewerOverlayJobMixin
from .protein_viewer_pharmacophore_mixin import ProteinViewerPharmacophoreMixin
from .protein_viewer_sequence_mixin import ProteinViewerSequenceMixin
from .protein_viewer_style_mixin import ProteinViewerStyleMixin
from .qt_widget_utils import apply_monospace_to_text_edit, make_window_resizable

logger = logging.getLogger(__name__)


class ProteinViewerDialog(
    ProteinViewerEditMixin,
    ProteinViewerIoMixin,
    ProteinViewerOverlayJobMixin,
    ProteinViewerStyleMixin,
    ProteinViewerSequenceMixin,
    ProteinViewerPharmacophoreMixin,
    QDialog,
):
    """Standalone Protein → Viewer window (3D canvas + chain Manager).

    Mixin bases are a file-split of this dialog (IO/style/sequence/pharmacophore).
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._init_viewer_state(parent)
        self._build_viewer_ui()

    def open_dock_ligand(self) -> None:
        """Open the main window's Gnina docking dialog."""
        host = self.parent()
        opener = getattr(host, "open_gnina_dock", None)
        if not callable(opener):
            from PyQt5.QtWidgets import QMessageBox

            QMessageBox.information(
                self,
                "Dock Ligand",
                "Gnina docking is available from the main MolManager window.",
            )
            return
        opener()

    def _init_viewer_state(self, parent) -> None:
        self.setWindowTitle("Protein Viewer")
        self.resize(1180, 760)
        make_window_resizable(self)

        self._slots: list[_LoadedSlot] = []
        self._slot_seq = 0
        self._named_groups: list[NamedManagerGroup] = []
        self._group_seq = 0
        self._manager_delete_undo: list[tuple[list[_LoadedSlot], list[_LoadedSlot]]] = []
        self._manager_delete_redo: list[tuple[list[_LoadedSlot], list[_LoadedSlot]]] = []
        self._act_undo: QAction | None = None
        self._act_redo: QAction | None = None
        self._act_edit_structure: QAction | None = None
        self._act_delete_atoms: QAction | None = None
        self._act_add_bond: QAction | None = None
        self._act_delete_bond: QAction | None = None
        self._sequence_chains: list[PolymerChain] = []
        self._sequence_dialog: ProteinSequenceDialog | None = None
        self._prepare_dialog = None
        self._pdbfixer_dialog = None
        self._pdb2pqr_dialog = None
        self._minimize_dialog = None
        self._dock_file_dialog = None
        self._residue_highlight: list[dict] = []
        self._syncing_from_atom = False
        self._pocket_payload_data: dict | None = None
        self._pocket_surface_payload: dict | None = None
        self._pocket_surface_settings: dict = {}
        self._pocket_surface_dialog = None
        self._pharmacophore = None
        self._pharmacophore_path: str | None = None
        self._pharmacophore_temp_path: str | None = None
        self._pharmacophore_dialog = None
        self._pharmacophore_overlay_visible = False
        self._docking_box_payload: dict | None = None
        self._dock_pose_payload: dict | None = None
        self._dock_pose_mol = None
        self._dock_pose_overlay = None
        self._dock_pose_overlay_gen = 0
        self._protein_style_actions: dict[str, QAction] = {}
        self._ligand_style_actions: dict[str, QAction] = {}
        self._protein_color_actions: dict[str, QAction] = {}
        self._ligand_color_actions: dict[str, QAction] = {}
        self._act_hydrogens_all: QAction | None = None
        self._act_hydrogens_polar: QAction | None = None
        self._act_hydrogens_none: QAction | None = None
        self._hydrogen_mode_actions: dict[str, list[QAction]] = {
            "all": [],
            "polar": [],
            "none": [],
        }
        self._act_hbond_protein: QAction | None = None
        self._act_hbond_ligand: QAction | None = None
        self._act_hbond_complex: QAction | None = None
        self._act_interact_hydrophobic: QAction | None = None
        self._act_interact_ionic: QAction | None = None
        self._act_interact_pi_stacking: QAction | None = None
        self._act_interact_pi_cation: QAction | None = None
        self._act_interact_halogen: QAction | None = None
        self._act_pocket_surface: QAction | None = None
        self._act_docking_box: QAction | None = None
        self._hbond_cache: dict[str, tuple] = {}
        self._prolif_cache: dict[str, tuple] = {}
        self._prolif_missing_logged = False
        self._overlay_job_gen = 0
        self._session_dirty = False
        self._canvas_load_depth = 0
        self._canvas_bootstrapped = False
        self._waiting_for_web = False
        self._pending_session_state = None
        self._pending_after_bootstrap: list = []
        self._suppress_close_prompt = "pytest" in sys.modules
        if parent is not None:
            self._suppress_close_prompt = bool(
                getattr(parent, "_suppress_exit_session_prompt", self._suppress_close_prompt)
            )

    def _build_viewer_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("&File")
        act_open = QAction("&Open…", self, triggered=self.open_structure_dialog)
        act_open.setShortcut(QKeySequence.Open)
        file_menu.addAction(act_open)
        act_save = QAction("&Save Structure…", self, triggered=self.save_structure_dialog)
        act_save.setShortcut(QKeySequence.Save)
        act_save.setToolTip(
            "Write the Manager-selected structure (or the last loaded file) to disk."
        )
        file_menu.addAction(act_save)
        act_save_session = QAction("Save to Session", self, triggered=self.save_viewer_to_session)
        act_save_session.setToolTip(
            "Write the current Protein Viewer into the open MolManager session. "
            "Closing without this leaves the session unchanged."
        )
        file_menu.addAction(act_save_session)
        file_menu.addSeparator()
        act_close = QAction("&Close Structure", self, triggered=self.close_structure)
        file_menu.addAction(act_close)
        edit_menu = menubar.addMenu("&Edit")
        self._act_undo = QAction("&Undo", self, triggered=self.undo_manager_delete)
        self._act_undo.setShortcut(QKeySequence.Undo)
        self._act_undo.setToolTip("Undo the last atom, bond, Manager chain, or rendering change.")
        self._act_undo.setEnabled(False)
        edit_menu.addAction(self._act_undo)
        self._act_redo = QAction("&Redo", self, triggered=self.redo_manager_delete)
        self._act_redo.setShortcut(QKeySequence.Redo)
        self._act_redo.setToolTip("Redo the last atom, bond, Manager chain, or rendering change.")
        self._act_redo.setEnabled(False)
        edit_menu.addAction(self._act_redo)
        edit_menu.addSeparator()
        self._act_edit_structure = QAction("Edit &Structure", self, checkable=True)
        self._act_edit_structure.setToolTip(
            "Click a second atom to pick a ligand bond. Delete removes the current 3D selection."
        )
        self._act_edit_structure.toggled.connect(self._on_edit_structure_toggled)
        edit_menu.addAction(self._act_edit_structure)
        self._act_delete_atoms = QAction(
            "Delete &Atom(s)", self, triggered=self.delete_highlighted_atoms
        )
        self._act_delete_atoms.setToolTip("Remove the highlighted atom(s) from the structure file.")
        self._act_delete_atoms.setEnabled(False)
        edit_menu.addAction(self._act_delete_atoms)
        self._act_add_bond = QAction("&Add Bond", self, triggered=self.add_highlighted_bond)
        self._act_add_bond.setToolTip(
            "Add a ligand bond between the two highlighted atoms (PDB CONECT or mmCIF _chem_comp_bond)."
        )
        self._act_add_bond.setEnabled(False)
        edit_menu.addAction(self._act_add_bond)
        self._act_delete_bond = QAction(
            "Delete &Bond", self, triggered=self.delete_highlighted_bond
        )
        self._act_delete_bond.setToolTip(
            "Remove the ligand bond between the two highlighted atoms."
        )
        self._act_delete_bond.setEnabled(False)
        edit_menu.addAction(self._act_delete_bond)
        tools_menu = menubar.addMenu("&Tools")
        tools_menu.setToolTipsVisible(True)
        prepare_menu = tools_menu.addMenu("&Prepare")
        prepare_menu.setToolTipsVisible(True)
        act_fast_prepare = QAction("&Fast Prepare…", self, triggered=self.open_prepare_dialog)
        act_fast_prepare.setToolTip(
            "Repair missing atoms, strip waters/heterogens, protonate at pH, and relax with OpenMM."
        )
        prepare_menu.addAction(act_fast_prepare)
        act_pdbfixer = QAction("&PDBFixer…", self, triggered=self.open_pdbfixer_dialog)
        act_pdbfixer.setToolTip(
            "Repair missing atoms and strip waters/heterogens. No protonation or minimization."
        )
        prepare_menu.addAction(act_pdbfixer)
        act_pdb2pqr = QAction("pdb&2pqr…", self, triggered=self.open_pdb2pqr_dialog)
        act_pdb2pqr.setToolTip(
            "Assign protonation states at a chosen pH with pdb2pqr/PROPKA. "
            "No PDBFixer repair or minimization."
        )
        prepare_menu.addAction(act_pdb2pqr)
        act_minimize = QAction("&Minimize…", self, triggered=self.open_minimize_dialog)
        act_minimize.setToolTip(
            "Restrained OpenMM minimization of the loaded protein–ligand complex (GAFF2)."
        )
        prepare_menu.addAction(act_minimize)
        act_dock_file = QAction("&Dock File…", self, triggered=self.open_dock_file_dialog)
        act_dock_file.setToolTip(
            "Write Gnina receptor PDBQT, crystal ligand, and search box from a ready "
            "structure, then open Protein → Dock Ligand → Gnina filled in (crystal "
            "ligand is kept for internal validation)."
        )
        prepare_menu.addAction(act_dock_file)
        self._act_dock_ligand = QAction("Dock &Ligand…", self)
        self._act_dock_ligand.setToolTip("Open the Gnina docking dialog.")
        self._act_dock_ligand.triggered.connect(self.open_dock_ligand)
        tools_menu.addAction(self._act_dock_ligand)
        pharma_menu = tools_menu.addMenu("&Pharmacophore")
        pharma_menu.setToolTipsVisible(True)
        act_pharma_edit = QAction("&Editor", self, triggered=self.open_pharmacophore_dialog)
        act_pharma_edit.setToolTip(
            "Place and edit pharmacophore features, save them, and send them to Gnina."
        )
        pharma_menu.addAction(act_pharma_edit)
        act_pharma_screen = QAction(
            "Screen &Table…", self, triggered=self.screen_pharmacophore_table
        )
        act_pharma_screen.setToolTip(
            "Screen packed table ensembles (confs / superpose / poses) against this pharmacophore."
        )
        pharma_menu.addAction(act_pharma_screen)
        act_pharma_open = QAction("&Open…", self, triggered=self.open_pharmacophore_file)
        act_pharma_open.setToolTip("Load a saved pharmacophore JSON onto the canvas.")
        pharma_menu.addAction(act_pharma_open)
        render_menu = menubar.addMenu("&Render")
        select_menu = menubar.addMenu("&Select")
        protein_menu = render_menu.addMenu("&Protein")
        self._protein_style_actions = self._add_render_style_menu(
            protein_menu,
            kind="polymer",
            default="cartoon",
        )
        protein_menu.addSeparator()
        self._protein_color_actions = self._add_render_color_menu(
            protein_menu.addMenu("&Color"),
            kind="polymer",
        )
        ligand_menu = render_menu.addMenu("&Ligand")
        self._ligand_style_actions = self._add_render_style_menu(
            ligand_menu,
            kind="ligand",
            default="ballstick",
            choices=LIGAND_STYLE_CHOICES,
        )
        ligand_menu.addSeparator()
        self._ligand_color_actions = self._add_render_color_menu(
            ligand_menu.addMenu("&Color"),
            kind="ligand",
        )
        hydrogens_menu = render_menu.addMenu("&Hydrogens")
        self._add_hydrogen_mode_menu(hydrogens_menu)
        self._act_hydrogens_all = (self._hydrogen_mode_actions.get("all") or [None])[0]
        self._act_hydrogens_polar = (self._hydrogen_mode_actions.get("polar") or [None])[0]
        self._act_hydrogens_none = (self._hydrogen_mode_actions.get("none") or [None])[0]
        self._sync_hydrogen_mode_actions("polar")
        interactions_menu = render_menu.addMenu("&Interactions")
        hbonds_menu = interactions_menu.addMenu("Hydrogen &Bonds")
        self._act_hbond_protein = QAction("&Protein", self)
        self._act_hbond_protein.setCheckable(True)
        self._act_hbond_protein.setToolTip(
            "Show intramolecular hydrogen bonds within protein chains (gold)."
        )
        self._act_hbond_ligand = QAction("&Ligand", self)
        self._act_hbond_ligand.setCheckable(True)
        self._act_hbond_ligand.setToolTip(
            "Show intramolecular hydrogen bonds within ligands (cyan)."
        )
        self._act_hbond_complex = QAction("Protein–&Ligand", self)
        self._act_hbond_complex.setCheckable(True)
        self._act_hbond_complex.setToolTip(
            "Show intermolecular hydrogen bonds between protein and ligand (green). "
            "Uses ProLIF when installed, otherwise geometric donor–acceptor distances."
        )
        hbonds_menu.addAction(self._act_hbond_protein)
        hbonds_menu.addAction(self._act_hbond_ligand)
        hbonds_menu.addAction(self._act_hbond_complex)
        self._act_interact_hydrophobic = QAction("H&ydrophobic", self)
        self._act_interact_hydrophobic.setCheckable(True)
        self._act_interact_hydrophobic.setToolTip(
            "Show protein–ligand hydrophobic contacts from ProLIF (orange)."
        )
        self._act_interact_ionic = QAction("&Ionic", self)
        self._act_interact_ionic.setCheckable(True)
        self._act_interact_ionic.setToolTip("Show protein–ligand salt bridges from ProLIF (red).")
        self._act_interact_pi_stacking = QAction("π-&Stacking", self)
        self._act_interact_pi_stacking.setCheckable(True)
        self._act_interact_pi_stacking.setToolTip(
            "Show protein–ligand π-stacking from ProLIF (purple)."
        )
        self._act_interact_pi_cation = QAction("π–&Cation", self)
        self._act_interact_pi_cation.setCheckable(True)
        self._act_interact_pi_cation.setToolTip(
            "Show protein–ligand π-cation contacts from ProLIF (magenta)."
        )
        self._act_interact_halogen = QAction("Halo&gen Bond", self)
        self._act_interact_halogen.setCheckable(True)
        self._act_interact_halogen.setToolTip(
            "Show protein–ligand halogen bonds from ProLIF (amber)."
        )
        interactions_menu.addAction(self._act_interact_hydrophobic)
        interactions_menu.addAction(self._act_interact_ionic)
        interactions_menu.addAction(self._act_interact_pi_stacking)
        interactions_menu.addAction(self._act_interact_pi_cation)
        interactions_menu.addAction(self._act_interact_halogen)
        self._act_hbond_protein.toggled.connect(self._on_hbond_toggles)
        self._act_hbond_ligand.toggled.connect(self._on_hbond_toggles)
        self._act_hbond_complex.toggled.connect(self._on_hbond_toggles)
        self._act_interact_hydrophobic.toggled.connect(self._on_hbond_toggles)
        self._act_interact_ionic.toggled.connect(self._on_hbond_toggles)
        self._act_interact_pi_stacking.toggled.connect(self._on_hbond_toggles)
        self._act_interact_pi_cation.toggled.connect(self._on_hbond_toggles)
        self._act_interact_halogen.toggled.connect(self._on_hbond_toggles)
        self._act_pocket_surface = QAction("Pocket &Surface…", self)
        self._act_pocket_surface.setToolTip(
            "Choose options for a molecular surface on protein residues within 4.5 Å of the ligand. "
            "OK in that window draws the surface."
        )
        self._act_pocket_surface.triggered.connect(self.open_pocket_surface_dialog)
        render_menu.addAction(self._act_pocket_surface)
        self._act_docking_box = QAction("&Docking Box", self)
        self._act_docking_box.setCheckable(True)
        self._act_docking_box.setToolTip(
            "Show the Gnina search box written by Prepare (ligand bounding box + padding)."
        )
        self._act_docking_box.toggled.connect(self._on_docking_box_toggled)
        render_menu.addAction(self._act_docking_box)
        render_menu.addSeparator()
        self._act_all_atoms = QAction("All &Atoms", self)
        self._act_all_atoms.setCheckable(True)
        self._act_all_atoms.setToolTip(
            "Draw protein residues as ball-and-stick (all atoms) instead of a ribbon cartoon."
        )
        self._act_all_atoms.toggled.connect(self._on_all_atoms_toggled)
        render_menu.addAction(self._act_all_atoms)
        render_menu.addSeparator()
        self._act_pocket = QAction("Focus &Pocket", self)
        self._act_pocket.setToolTip(
            "Zoom to the ligand, show nearby protein residues as ball-and-stick, "
            "and display polar hydrogens on heteroatoms in the pocket."
        )
        self._act_pocket.triggered.connect(self._on_pocket)
        render_menu.addAction(self._act_pocket)
        self._act_reset_camera = QAction("Reset Camera", self, triggered=self._reset_camera)
        self._act_reset_camera.setToolTip(
            "Restore the fitted view and the protein/ligand styles from when they were loaded."
        )
        render_menu.addAction(self._act_reset_camera)
        act_hide = QAction("&Hide", self, triggered=lambda: self._set_selected_visible(False))
        act_hide.setToolTip("Hide the chains selected in the Manager.")
        select_menu.addAction(act_hide)
        act_show = QAction("&Show", self, triggered=lambda: self._set_selected_visible(True))
        act_show.setToolTip("Show the chains selected in the Manager.")
        select_menu.addAction(act_show)
        act_focus = QAction("&Focus", self, triggered=self.focus_selected)
        act_focus.setToolTip("Zoom the 3D view to the Manager selection.")
        select_menu.addAction(act_focus)
        select_menu.addSeparator()
        act_invert = QAction("&Invert Selection", self, triggered=self.invert_selection)
        act_invert.setToolTip(
            "Select unselected Manager chains and deselect the current selection."
        )
        select_menu.addAction(act_invert)
        act_delete = QAction("&Delete", self, triggered=self.delete_selected)
        act_delete.setToolTip("Delete highlighted atoms or residues, or selected Manager chains.")
        select_menu.addAction(act_delete)
        act_duplicate = QAction("D&uplicate", self, triggered=self.duplicate_selected)
        act_duplicate.setToolTip("Copy the Manager selection as a new overlay structure.")
        select_menu.addAction(act_duplicate)
        act_clear = QAction("C&lear Selection", self, triggered=self.clear_selection)
        act_clear.setToolTip("Deselect Manager rows and clear the 3D atom/residue highlight.")
        select_menu.addAction(act_clear)
        select_menu.addSeparator()
        select_render = select_menu.addMenu("&Render")
        self._add_select_style_menu(select_render)
        self._add_select_color_menu(select_menu.addMenu("&Color"))
        self._sync_hydrogen_mode_actions(self._hydrogen_mode())
        # Native Windows menu bars can swallow clicks meant for the corner widget.
        if sys.platform == "win32":
            menubar.setNativeMenuBar(False)
        corner = QWidget(menubar)
        corner_ly = QHBoxLayout(corner)
        corner_ly.setContentsMargins(0, 0, 4, 0)
        btn_sequence = QToolButton(corner)
        btn_sequence.setText("Sequence")
        btn_sequence.setToolTip("Show the editable amino-acid sequence and select residues in 3D.")
        btn_sequence.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_sequence.setAutoRaise(True)
        btn_sequence.setFocusPolicy(Qt.NoFocus)
        btn_sequence.setFont(menubar.font())
        btn_sequence.clicked.connect(self.open_sequence_window)
        self._btn_sequence = btn_sequence
        corner_ly.addWidget(btn_sequence)
        menubar.setCornerWidget(corner, Qt.TopRightCorner)
        root.setMenuBar(menubar)

        splitter = QSplitter(Qt.Horizontal)
        self._main_splitter = splitter
        self.viewer = ProteinEmbedView(self)
        self.viewer.atom_picked.connect(self._on_atom_picked)
        self.viewer.delete_requested.connect(self.delete_selected)
        self.viewer.undo_requested.connect(self.undo_manager_delete)
        self.viewer.redo_requested.connect(self.redo_manager_delete)
        self.viewer.web_ready.connect(self._on_canvas_web_ready)
        self.manager = ProteinChainManager(self)
        self.manager.visibility_changed.connect(self._on_visibility_changed)
        self.manager.selection_changed.connect(self._on_manager_selection)
        self.manager.focus_requested.connect(self.focus_selected)
        self.manager.delete_requested.connect(self.delete_selected_chains)
        self.manager.duplicate_requested.connect(self.duplicate_selected)
        self.manager.add_to_group_requested.connect(self._on_add_to_group)
        self.manager.remove_from_group_requested.connect(self._on_remove_from_group)
        self.manager.rename_group_requested.connect(self._on_rename_group)
        self.manager.delete_group_requested.connect(self._on_delete_group)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMinimumHeight(36)
        self.log.setPlaceholderText(
            "Progress from Fast Prepare, PDBFixer, pdb2pqr, Minimize, and Gnina appears here."
        )
        apply_monospace_to_text_edit(self.log)
        self.log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.log.document().setDocumentMargin(2)

        self._atom_status = QLabel("")
        self._atom_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._atom_status.setStyleSheet("padding: 0px 6px; color: palette(window-text);")
        self._atom_status.setToolTip("Clicked atom in the 3D view.")

        canvas_host = QWidget(self)
        canvas_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        canvas_ly = QVBoxLayout(canvas_host)
        canvas_ly.setContentsMargins(0, 0, 0, 0)
        canvas_ly.setSpacing(0)
        canvas_ly.addWidget(self.viewer, 1)
        canvas_ly.addWidget(self._atom_status)

        vsplit = QSplitter(Qt.Vertical)
        self._log_splitter = vsplit
        vsplit.addWidget(canvas_host)
        vsplit.addWidget(self.log)
        vsplit.setHandleWidth(3)
        vsplit.setStretchFactor(0, 1)
        vsplit.setStretchFactor(1, 0)
        vsplit.setSizes([800, 48])
        vsplit.setChildrenCollapsible(False)

        splitter.addWidget(vsplit)
        splitter.addWidget(self.manager)
        splitter.setStretchFactor(0, 4)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([860, 300])
        splitter.setChildrenCollapsible(False)

        self._loading_page = QWidget()
        load_lyt = QVBoxLayout(self._loading_page)
        load_lyt.setContentsMargins(0, 0, 0, 0)
        load_lyt.addStretch()
        self._loading_detail = QLabel("")
        self._loading_detail.setAlignment(Qt.AlignCenter)
        self._loading_detail.setWordWrap(True)
        self._loading_detail.setStyleSheet("font-size: 14px; color: palette(mid); padding: 24px;")
        load_lyt.addWidget(self._loading_detail)
        load_lyt.addStretch()

        self._workspace_ready_page = QWidget()
        ready_lyt = QVBoxLayout(self._workspace_ready_page)
        ready_lyt.setContentsMargins(0, 0, 0, 0)
        ready_lyt.setSpacing(0)
        ready_lyt.addWidget(splitter, 1)

        self._content_stack = QStackedWidget()
        self._content_stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._content_stack.addWidget(self._loading_page)
        self._content_stack.addWidget(self._workspace_ready_page)
        self._content_stack.setCurrentIndex(1)
        root.addWidget(self._content_stack, 1)

        QShortcut(QKeySequence.Delete, self, activated=self.delete_selected)
        QShortcut(QKeySequence("Backspace"), self, activated=self.delete_selected)

    def canvas_loading_visible(self) -> bool:
        """True while the loading page covers the 3D canvas and Manager."""
        stack = getattr(self, "_content_stack", None)
        try:
            return stack is not None and int(stack.currentIndex()) == 0
        except RuntimeError:
            return False

    def begin_canvas_load(self, message: str, *, paint: bool = True) -> None:
        """Cover the canvas with the session/table-style loading page (nested)."""
        depth = int(getattr(self, "_canvas_load_depth", 0))
        self._canvas_load_depth = depth + 1
        label = getattr(self, "_loading_detail", None)
        if label is not None and (message or "").strip():
            try:
                label.setText(message)
            except RuntimeError:
                pass
        stack = getattr(self, "_content_stack", None)
        if stack is not None:
            try:
                stack.setCurrentIndex(0)
            except RuntimeError:
                return
        if paint:
            self.flush_canvas_load_paint()

    def end_canvas_load(self) -> None:
        """Reveal the canvas when the outermost load finishes."""
        depth = max(0, int(getattr(self, "_canvas_load_depth", 0)) - 1)
        self._canvas_load_depth = depth
        if depth:
            return
        stack = getattr(self, "_content_stack", None)
        if stack is None:
            return
        try:
            stack.setCurrentIndex(1)
        except RuntimeError:
            pass

    def flush_canvas_load_paint(self) -> None:
        """Paint the loading page before a blocking restore or file parse."""
        if not self.isVisible() or not self.canvas_loading_visible():
            return
        try:
            self.repaint()
        except RuntimeError:
            return
        QApplication.processEvents(QEventLoop.ExcludeUserInputEvents)

    def set_pending_session_state(self, state: dict | None) -> None:
        """Queue a session snapshot to apply after the window has been shown."""
        self._pending_session_state = state if isinstance(state, dict) else None

    def queue_after_canvas_bootstrap(self, callback) -> None:
        """Run ``callback`` after session restore during the first canvas start."""
        if not callable(callback):
            return
        if self._canvas_bootstrapped:
            callback()
            return
        self._pending_after_bootstrap.append(callback)

    def schedule_canvas_bootstrap(self) -> None:
        """Start the 3D canvas after the dialog chrome has a chance to paint."""
        if self._canvas_bootstrapped:
            return
        if "pytest" in sys.modules:
            self._bootstrap_canvas()
            return
        QTimer.singleShot(0, self._bootstrap_canvas)

    def _bootstrap_canvas(self) -> None:
        if self._canvas_bootstrapped:
            return
        self._canvas_bootstrapped = True
        try:
            self.viewer._ensure_web()
        except Exception:
            logger.exception("Protein viewer canvas bootstrap failed")
        pending = self._pending_session_state
        self._pending_session_state = None
        if isinstance(pending, dict) and pending.get("structures"):
            try:
                self.apply_session_state(pending)
                self._session_dirty = False
            except Exception:
                logger.exception("Protein viewer session restore failed")
        queued = list(self._pending_after_bootstrap)
        self._pending_after_bootstrap.clear()
        for callback in queued:
            try:
                callback()
            except Exception:
                logger.exception("Protein viewer post-bootstrap callback failed")
        web = getattr(self.viewer, "_web", None)
        web_ready = bool(getattr(self.viewer, "_web_ready", False))
        if web_ready or web is None or "pytest" in sys.modules:
            self._waiting_for_web = False
            self._release_open_overlay()
            return
        self._waiting_for_web = True
        QTimer.singleShot(8000, self._on_canvas_web_ready)

    def _on_canvas_web_ready(self) -> None:
        if not self._waiting_for_web:
            return
        self._waiting_for_web = False
        self._release_open_overlay()

    def _release_open_overlay(self) -> None:
        while int(getattr(self, "_canvas_load_depth", 0)) > 0:
            self.end_canvas_load()

    def append_log(self, text: str) -> None:
        """Append a timestamped line to the viewer log."""
        t = (text or "").rstrip()
        if not t:
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.append(f"[{stamp}] {t}")

    def _reset_camera(self) -> None:
        before = self._capture_render()
        styles_changed = self._restore_loaded_render_styles()
        self._clear_pocket_overlay()
        if styles_changed:
            self.manager.apply_row_states(self._rows)
            self._sync_render_menus_from_rows()
            self._push_states()
        elif self._slots:
            self._sync_render_menus_from_rows()
        self._commit_render(before)
        web = getattr(self.viewer, "_web", None)
        if web is None:
            return
        try:
            web.page().runJavaScript(
                "if (window.molmanagerResetStructure) window.molmanagerResetStructure();"
            )
        except Exception:
            logger.debug("Protein viewer reset camera failed", exc_info=True)

    def _component_payloads(self) -> list[dict]:
        out: list[dict] = []
        for row in self._rows:
            payload = row.spec.to_payload()
            payload["visible"] = row.visible
            payload["selected"] = row.selected
            payload["style"] = (
                row.style
                if row.spec.kind != "ligand" or row.style in LIGAND_STYLE_IDS
                else "ballstick"
            )
            scheme = row.color_scheme or "default"
            spec = _RENDER_COLOR_SPEC.get(scheme)
            if spec is not None:
                payload["cartoonColor"] = spec[0]
                payload["carbonScheme"] = spec[1]
            elif str(scheme).startswith("#"):
                payload["cartoonColor"] = scheme
                payload["carbonScheme"] = scheme
            out.append(payload)
        return out

    def _slot_model_payload(self, slot: _LoadedSlot) -> dict:
        model = {
            "data": base64.b64encode(slot.text.encode("utf-8")).decode("ascii"),
            "fmt": slot.fmt,
            "name": slot.name,
        }
        if slot.fmt == "cif":
            cache = getattr(self, "_cif_bond_cache", None)
            if cache is None:
                cache = {}
                self._cif_bond_cache = cache
            prev = cache.get(slot.structure_id)
            if prev is None or prev[0] is not slot.text:
                tables = cif_viewer_bond_tables(slot.text)
                cache[slot.structure_id] = (slot.text, tables)
            else:
                tables = prev[1]
            if tables:
                model["cifBonds"] = tables
        return model

    def _structure_canvas_payload(
        self,
        models: list[dict],
        *,
        refit: bool,
        camera=None,
    ) -> dict:
        payload = {
            "models": models,
            "fmt": models[0]["fmt"] if models else "pdb",
            "data": models[0]["data"] if models else "",
            "components": self._component_payloads(),
            "residueHighlight": self._residue_highlight,
            "pocket": self._pocket_payload_data,
            "pocketSurface": self._pocket_surface_overlay_payload(),
            "dockingBox": self._docking_box_overlay_payload(),
            "dockPose": self._dock_pose_overlay_payload(),
            "pharmacophore": self._pharmacophore_overlay_payload(),
            "hbonds": self._hbond_payload_for_structure_push(),
            "hydrogens": self._hydrogen_mode(),
            "refit": bool(refit) and camera is None,
        }
        if camera is not None:
            payload["camera"] = camera
        return payload

    def _push_structure(self, *, refit: bool, camera=None, append_from: int | None = None) -> None:
        web_ready = bool(getattr(self.viewer, "_web_ready", False))
        can_append = (
            append_from is not None
            and append_from > 0
            and append_from < len(self._slots)
            and camera is None
            and web_ready
        )
        if can_append:
            models = [self._slot_model_payload(slot) for slot in self._slots[append_from:]]
            self.viewer.add_models(self._structure_canvas_payload(models, refit=refit))
            return
        models = [self._slot_model_payload(slot) for slot in self._slots]
        self.viewer.set_payload(self._structure_canvas_payload(models, refit=refit, camera=camera))

    def _schedule_canvas_structure_push(self, *, refit: bool = False) -> None:
        """Coalesce rapid Manager deletes into one canvas rebuild."""
        self._pending_canvas_refit = bool(getattr(self, "_pending_canvas_refit", False) or refit)
        if "pytest" in sys.modules:
            self._flush_canvas_structure_push()
            return
        timer = getattr(self, "_canvas_push_timer", None)
        if timer is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.setInterval(50)
            timer.timeout.connect(self._flush_canvas_structure_push)
            self._canvas_push_timer = timer
        timer.start()

    def _flush_canvas_structure_push(self) -> None:
        refit = bool(getattr(self, "_pending_canvas_refit", False))
        self._pending_canvas_refit = False
        if not self._slots:
            return
        self._push_structure(refit=refit)
        self._refresh_pocket_overlays(zoom=False)
        if self._interaction_overlay_active():
            self._push_hbonds()

    def _push_states(self) -> None:
        self.viewer.apply_component_states(self._component_payloads())
        if self._interaction_overlay_active():
            self._push_hbonds()
        self._mark_viewer_unsaved()

    def dock_side_widget(self, widget) -> bool:
        """Dock a panel as a full-height Manager page and show it."""
        dock = getattr(self.manager, "dock_widget", None)
        if not callable(dock) or not dock(widget):
            return False
        self._widen_manager_for_side_dock()
        sync = getattr(widget, "_sync_footer_chrome", None)
        if callable(sync):
            sync()
        return True

    def show_side_widget(self, widget) -> bool:
        """Show a Manager page (chain list or a docked panel)."""
        show = getattr(self.manager, "show_widget", None)
        return callable(show) and bool(show(widget))

    def undock_side_widget(self, widget) -> bool:
        """Remove a panel from the Manager dock without destroying it."""
        undock = getattr(self.manager, "undock_widget", None)
        if not callable(undock):
            return False
        ok = bool(undock(widget))
        if ok:
            sync = getattr(widget, "_sync_footer_chrome", None)
            if callable(sync):
                sync()
        return ok

    def close_side_dock_widget(self, widget) -> bool:
        """Close and destroy a panel docked in the Manager."""
        if not self.is_side_docked(widget):
            return False
        closer = getattr(widget, "on_docked_plot_closing", None)
        if callable(closer):
            closer()
        self.undock_side_widget(widget)
        try:
            widget.close()
            widget.deleteLater()
        except RuntimeError:
            pass
        return True

    def is_side_docked(self, widget) -> bool:
        check = getattr(self.manager, "is_docked", None)
        return callable(check) and bool(check(widget))

    def side_docked_widgets(self) -> list:
        lister = getattr(self.manager, "docked_widgets", None)
        if callable(lister):
            return list(lister())
        return []

    def _widen_manager_for_side_dock(self) -> None:
        splitter = getattr(self, "_main_splitter", None)
        if splitter is None:
            return
        sizes = splitter.sizes()
        if len(sizes) < 2:
            return
        if sizes[1] >= 380:
            return
        extra = 380 - sizes[1]
        splitter.setSizes([max(sizes[0] - extra, 400), 380])

    def _float_side_docks(self) -> None:
        """Close a docked pose browser; float any other Manager panels before this viewer closes."""
        from .browsers.pose_browser import PoseBrowserWidget

        for widget in list(self.side_docked_widgets()):
            if isinstance(widget, PoseBrowserWidget):
                self.close_side_dock_widget(widget)
                continue
            app = getattr(widget, "parent_app", None)
            factory = getattr(widget, "create_floating_dialog", None)
            self.undock_side_widget(widget)
            if app is None or not callable(factory):
                continue
            dlg = factory(app)
            from .pose_browser import PoseBrowserDialog

            if isinstance(dlg, PoseBrowserDialog):
                setattr(app, "_pose_browser_dialog", dlg)
                slot = getattr(app, "_on_pose_browser_dialog_destroyed", None)
                if callable(slot):
                    try:
                        dlg.destroyed.disconnect(slot)
                    except TypeError:
                        pass
                    dlg.destroyed.connect(slot)
            try:
                dlg.show()
            except RuntimeError:
                pass

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if not self.confirm_close_or_save_to_session():
            event.ignore()
            return
        self._float_side_docks()
        clearer = getattr(self, "clear_dock_pose", None)
        if callable(clearer):
            clearer()
        super().closeEvent(event)
