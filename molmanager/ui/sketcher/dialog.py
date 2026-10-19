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

import re

from PyQt5.QtCore import QEvent, QPoint, QSize, Qt, QTimer
from PyQt5.QtGui import QCursor, QFont, QIcon, QKeySequence
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QButtonGroup,
    QDialog,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QMenuBar,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...table.structure_depiction_layout import reaction_depict_size
from ...chem.reaction_file_io import RXN_SMARTS_HEADER
from ...chem.structure_2d_depiction import ReactionDrawSpec
from ...workers import ExportWorker

from ..mol_viewer_3d import Molecule3DEmbedView
from ..qt_widget_utils import make_window_minimizable
from .chem import _parse_periodic_element_symbol
from .constants import WILDCARD_ELEMENT
from .customize_elements import (
    CustomizeElementsDialog,
    element_groups_for_symbols,
    load_toolbar_element_symbols,
    save_toolbar_element_symbols,
)
from .toolbar_glyphs import (
    TOOLBAR_RING_TEMPLATES,
    bond_dative_icon,
    bond_double_icon,
    bond_hash_icon,
    bond_plain_icon,
    bond_triple_icon,
    bond_wavy_icon,
    bond_wedge_icon,
    charge_minus_icon,
    charge_plus_icon,
    clear_sketch_icon,
    mode_draw_icon,
    mode_erase_icon,
    mode_lasso_icon,
    mode_select_icon,
    mode_text_icon,
    ring_icon,
    status_caution_icon,
    status_error_icon,
    status_ok_icon,
    view_3d_icon,
    reaction_arrow_icon,
)
from .bonds import (
    BOND_STEREO_DATIVE,
    BOND_STEREO_HASH,
    BOND_STEREO_PLAIN,
    BOND_STEREO_WAVY,
    BOND_STEREO_WEDGE,
)
from .widget import SketchWidget


def _toolbar_vsep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.VLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setFixedWidth(8)
    return line


def _toolbar_hsep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setFixedHeight(8)
    return line


def _toolbar_header(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setObjectName("SketcherToolbarHeader")
    lab.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
    lab.setStyleSheet(
        "color: palette(mid); font-size: 11px; font-weight: 600; letter-spacing: 0.3px; "
        "padding-top: 2px; padding-bottom: 2px;"
    )
    return lab


def _glyph_tool_button(
    icon: QIcon,
    tip: str,
    *,
    checkable: bool = True,
    size: int = 34,
) -> QPushButton:
    b = QPushButton()
    b.setIcon(icon)
    b.setIconSize(QSize(size - 6, size - 6))
    b.setFixedSize(size, size)
    b.setCheckable(checkable)
    b.setToolTip(tip)
    b.setStyleSheet("padding: 1px;")
    b.setFocusPolicy(Qt.NoFocus)
    return b


def _sketcher_preferred_dialog_size() -> tuple[int, int]:
    scr = QApplication.primaryScreen()
    if scr is None:
        return (1280, 860)
    ag = scr.availableGeometry()
    w = max(1000, min(int(ag.width() * 0.74), ag.width() - 32))
    h = max(720, min(int(ag.height() * 0.76), ag.height() - 48))
    return (w, h)


class SketcherDialog(QDialog):
    def __init__(
        self,
        parent=None,
        initial_mol: Chem.Mol | None = None,
        *,
        element_symbols: list[str] | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        if initial_mol is not None and not isinstance(initial_mol, Chem.Mol):
            initial_mol = None
        self._initial_mol = initial_mol
        self._element_symbols_override = element_symbols
        self.setWindowTitle("Sketcher")
        self.resize(*_sketcher_preferred_dialog_size())
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._phys_props_dlg = None

        l = QVBoxLayout(self)
        l.setContentsMargins(0, 0, 0, 0)
        l.setSpacing(0)

        menubar = QMenuBar(self)
        file_menu = menubar.addMenu("File")
        export_act = QAction("Save Sketch…", self)
        export_act.triggered.connect(self._save_sketch)
        file_menu.addAction(export_act)
        export_table_act = QAction("Export to Table", self)
        export_table_act.triggered.connect(self._add_to_table)
        export_table_act.setShortcut(QKeySequence("Ctrl+Shift+T"))
        export_table_act.setShortcutContext(Qt.WindowShortcut)
        file_menu.addAction(export_table_act)

        edit_menu = menubar.addMenu("Edit")
        undo_act = QAction("Undo", self)
        undo_act.setShortcut(QKeySequence.Undo)
        undo_act.setShortcutContext(Qt.WindowShortcut)
        undo_act.setToolTip("Undo the last sketch change (Ctrl+Z).")
        undo_act.triggered.connect(self._undo_sketch)
        edit_menu.addAction(undo_act)
        redo_act = QAction("Redo", self)
        redo_act.setShortcut(QKeySequence.Redo)
        redo_act.setShortcutContext(Qt.WindowShortcut)
        redo_act.setToolTip("Redo the last undone sketch change (Ctrl+Y / Ctrl+Shift+Z).")
        redo_act.triggered.connect(self._redo_sketch)
        edit_menu.addAction(redo_act)
        edit_menu.addSeparator()
        copy_act = QAction("&Copy", self)
        copy_act.setShortcut(QKeySequence.Copy)
        copy_act.setShortcutContext(Qt.WindowShortcut)
        copy_act.setToolTip(
            "Copy the selected atoms and bonds so they can be pasted on the canvas (Ctrl+C)."
        )
        copy_act.triggered.connect(self._shortcut_copy_selection)
        edit_menu.addAction(copy_act)
        paste_act = QAction("&Paste", self)
        paste_act.setShortcut(QKeySequence.Paste)
        paste_act.setShortcutContext(Qt.WindowShortcut)
        paste_act.setToolTip("Paste a copied sketch fragment at the cursor (Ctrl+V).")
        paste_act.triggered.connect(self._shortcut_paste_selection)
        edit_menu.addAction(paste_act)
        delete_act = QAction("Delete &Selection", self)
        delete_act.setShortcut(QKeySequence.Delete)
        delete_act.setShortcutContext(Qt.WindowShortcut)
        delete_act.setToolTip(
            "Delete the atom or bond under the cursor, or the current selection (Del)."
        )
        delete_act.triggered.connect(self._on_edit_delete)
        edit_menu.addAction(delete_act)
        self._act_edit_copy = copy_act
        self._act_edit_paste = paste_act
        self._act_edit_delete = delete_act

        # Mode tools: Draw / Erase / Select / Text (toolbar; empty-canvas menu omits Text).
        self.tb_draw = _glyph_tool_button(
            mode_draw_icon(),
            "Draw with the carbon tool (Ctrl+D). "
            "Right-click empty canvas for templates, cleanup, and other commands.",
        )
        self.tb_draw.setChecked(True)
        self.tb_draw.clicked.connect(lambda *_: self._enter_draw_mode())

        self.tb_erase = _glyph_tool_button(mode_erase_icon(), "Erase atoms and bonds (Ctrl+E).")
        self.tb_erase.toggled.connect(self._toggle_erase)

        self.select_btn = _glyph_tool_button(
            mode_select_icon(),
            "Box select and move atoms/bonds (Ctrl+T). "
            "Drag empty space for a rectangle; hold Shift to add to the selection.",
        )
        self.select_btn.toggled.connect(self._toggle_select)

        self.lasso_btn = _glyph_tool_button(
            mode_lasso_icon(),
            "Lasso select and move atoms/bonds (Ctrl+Shift+L). "
            "Drag a freeform shape around atoms/bonds; hold Shift to add to the selection.",
        )
        self.lasso_btn.toggled.connect(self._toggle_lasso)

        self.tb_text = _glyph_tool_button(
            mode_text_icon(),
            "Text: click an atom to edit its element or contracted label "
            "(CF3, SO2, Ph, OMe, …) (Ctrl+Shift+A).",
        )
        self.tb_text.toggled.connect(self._toggle_text)

        self._act_mode_draw = QAction("Draw", self)
        self._act_mode_draw.setCheckable(True)
        self._act_mode_draw.setChecked(True)
        self._act_mode_draw.setToolTip(self.tb_draw.toolTip())
        self._act_mode_draw.setShortcut(QKeySequence("Ctrl+D"))
        self._act_mode_draw.setShortcutContext(Qt.WindowShortcut)
        self._act_mode_draw.toggled.connect(self._on_menu_mode_draw)

        self._act_mode_erase = QAction("Erase", self)
        self._act_mode_erase.setCheckable(True)
        self._act_mode_erase.setToolTip(self.tb_erase.toolTip())
        self._act_mode_erase.setShortcut(QKeySequence("Ctrl+E"))
        self._act_mode_erase.setShortcutContext(Qt.WindowShortcut)
        self._act_mode_erase.toggled.connect(self._on_menu_mode_erase)

        self._act_mode_select = QAction("Select", self)
        self._act_mode_select.setCheckable(True)
        self._act_mode_select.setToolTip(self.select_btn.toolTip())
        self._act_mode_select.setShortcut(QKeySequence("Ctrl+T"))
        self._act_mode_select.setShortcutContext(Qt.WindowShortcut)
        self._act_mode_select.toggled.connect(self._on_menu_mode_select)

        self._act_mode_lasso = QAction("Lasso Select", self)
        self._act_mode_lasso.setCheckable(True)
        self._act_mode_lasso.setToolTip(self.lasso_btn.toolTip())
        self._act_mode_lasso.setShortcut(QKeySequence("Ctrl+Shift+L"))
        self._act_mode_lasso.setShortcutContext(Qt.WindowShortcut)
        self._act_mode_lasso.toggled.connect(self._on_menu_mode_lasso)

        self._act_mode_text = QAction("Text", self)
        self._act_mode_text.setCheckable(True)
        self._act_mode_text.setToolTip(self.tb_text.toolTip())
        self._act_mode_text.setShortcut(QKeySequence("Ctrl+Shift+A"))
        self._act_mode_text.setShortcutContext(Qt.WindowShortcut)
        self._act_mode_text.toggled.connect(self._on_menu_mode_text)

        self.tb_erase.toggled.connect(self._sync_mode_menu_checks)
        self.select_btn.toggled.connect(self._sync_mode_menu_checks)
        self.lasso_btn.toggled.connect(self._sync_mode_menu_checks)
        self.tb_text.toggled.connect(self._sync_mode_menu_checks)

        self._act_canvas_group = QAction("Group", self)
        self._act_canvas_group.triggered.connect(self._shortcut_group)
        self._act_canvas_group.setShortcut(QKeySequence("Ctrl+G"))
        self._act_canvas_group.setShortcutContext(Qt.WindowShortcut)

        self._act_canvas_ungroup = QAction("Ungroup", self)
        self._act_canvas_ungroup.triggered.connect(self._shortcut_ungroup)
        self._act_canvas_ungroup.setShortcut(QKeySequence("Ctrl+Shift+G"))
        self._act_canvas_ungroup.setShortcutContext(Qt.WindowShortcut)

        self._act_canvas_clear = QAction("Clear sketch", self)
        self._act_canvas_clear.triggered.connect(self._clear_sketch)
        self._act_canvas_clear.setShortcut(QKeySequence("Ctrl+Shift+K"))
        self._act_canvas_clear.setShortcutContext(Qt.WindowShortcut)

        self._act_canvas_cleanup = QAction("Clean Up", self)
        self._act_canvas_cleanup.triggered.connect(self._on_cleanup_layout)
        self._act_canvas_cleanup.setShortcut(QKeySequence("Ctrl+K"))
        self._act_canvas_cleanup.setShortcutContext(Qt.WindowShortcut)

        self._act_canvas_cleanup_selected = QAction("Clean Up Selected", self)
        self._act_canvas_cleanup_selected.setToolTip(
            "Re-layout only the currently selected atoms; the rest of the sketch stays put."
        )
        self._act_canvas_cleanup_selected.triggered.connect(self._on_cleanup_layout_selected)

        self._act_canvas_add_hs = QAction("Implicit Hydrogens", self)
        self._act_canvas_add_hs.setCheckable(True)
        self._act_canvas_add_hs.setToolTip(
            "Toggle showing implicit hydrogens as explicit H atoms on the sketch "
            "(RDKit AddHs / remove explicit H)."
        )
        self._act_canvas_add_hs.triggered.connect(self._on_toggle_implicit_hydrogens)

        view_menu = menubar.addMenu("View")
        zoom_in_act = QAction("Zoom in", self)
        zoom_in_act.setToolTip(
            "Zoom in (bonds and labels scale together; does not change the sketch coordinates)."
        )
        zoom_in_act.triggered.connect(self._on_view_zoom_in)
        zoom_in_act.setShortcut(QKeySequence.ZoomIn)
        zoom_in_act.setShortcutContext(Qt.WindowShortcut)
        view_menu.addAction(zoom_in_act)
        zoom_out_act = QAction("Zoom out", self)
        zoom_out_act.setToolTip(
            "Zoom out (bonds and labels scale together; does not change the sketch coordinates)."
        )
        zoom_out_act.triggered.connect(self._on_view_zoom_out)
        zoom_out_act.setShortcut(QKeySequence.ZoomOut)
        zoom_out_act.setShortcutContext(Qt.WindowShortcut)
        view_menu.addAction(zoom_out_act)
        view_menu.addSeparator()
        fit_v_act = QAction("Fit structure to window", self)
        fit_v_act.setToolTip("Scale and center so the whole sketch fits in the canvas with margin.")
        fit_v_act.triggered.connect(self._on_view_fit_structure)
        view_menu.addAction(fit_v_act)
        center_draw_act = QAction("Center Drawing", self)
        center_draw_act.setToolTip(
            "Move the whole sketch so it is centered in the canvas (undo: Ctrl+Z)."
        )
        center_draw_act.triggered.connect(self._on_center_molecule)
        view_menu.addAction(center_draw_act)
        view_menu.addSeparator()
        self._act_show_lone_pairs = QAction("Show Lone Pairs", self)
        self._act_show_lone_pairs.setCheckable(True)
        self._act_show_lone_pairs.setToolTip(
            "Draw Lewis lone pairs (dot pairs) on heteroatoms using valence electrons and bonding."
        )
        self._act_show_lone_pairs.toggled.connect(self._on_toggle_show_lone_pairs)
        view_menu.addAction(self._act_show_lone_pairs)
        view_menu.addSeparator()
        phys_props_act = QAction("Physical Properties", self)
        phys_props_act.setToolTip(
            "Show MW, TPSA, LogP, LogD (pH 7.4), and pKa for the current sketch; "
            "values update when the sketch changes."
        )
        phys_props_act.triggered.connect(self._open_physical_properties)
        view_menu.addAction(phys_props_act)

        tools = menubar.addMenu("Tools")

        copy_act = QAction("Copy SMILES", self)
        copy_act.triggered.connect(self._copy_smiles)
        copy_act.setShortcut(QKeySequence("Ctrl+Shift+C"))
        tools.addAction(copy_act)
        copy_sel_act = QAction("Copy Selected as SMILES", self)
        copy_sel_act.setToolTip(
            "Copy SMILES (or SMARTS) for the currently selected atoms/bonds only."
        )
        copy_sel_act.triggered.connect(self._copy_selected_smiles)
        tools.addAction(copy_sel_act)
        copy_smarts_act = QAction("Copy SMARTS", self)
        copy_smarts_act.triggered.connect(self._copy_smarts)
        tools.addAction(copy_smarts_act)

        settings_menu = menubar.addMenu("Settings")
        customize_el_act = QAction("Customize Elements", self)
        customize_el_act.setToolTip(
            "Choose which element buttons appear in the left element panel."
        )
        customize_el_act.triggered.connect(self._customize_elements)
        settings_menu.addAction(customize_el_act)

        l.setMenuBar(menubar)

        # --- Top glyph toolbar: modes, bonds, rings, charge, 3D, reaction arrow ---
        top_bar = QHBoxLayout()
        top_bar.setSpacing(4)
        top_bar.setContentsMargins(6, 4, 6, 4)
        top_bar.addStretch(1)

        top_bar.addWidget(self.tb_draw)
        top_bar.addWidget(self.tb_erase)
        top_bar.addWidget(self.select_btn)
        top_bar.addWidget(self.lasso_btn)
        top_bar.addWidget(self.tb_text)
        self.tb_clear = _glyph_tool_button(
            clear_sketch_icon(),
            "Clear the sketch (also in the right-click empty-canvas menu).",
            checkable=False,
        )
        self.tb_clear.clicked.connect(self._clear_sketch)
        top_bar.addWidget(self.tb_clear)
        top_bar.addWidget(_toolbar_vsep())

        self._bond_tool_group = QButtonGroup(self)
        self._bond_tool_group.setExclusive(True)
        self._bond_tool_buttons: list[tuple[QPushButton, int, int]] = []

        def _add_bond_tool(
            icon, tip: str, order: int, stereo: int, *, checked: bool = False
        ) -> QPushButton:
            btn = _glyph_tool_button(icon, tip)
            btn.setChecked(checked)
            btn.clicked.connect(lambda _=False, o=order, s=stereo: self._on_bond_tool(o, s))
            self._bond_tool_group.addButton(btn)
            self._bond_tool_buttons.append((btn, order, stereo))
            top_bar.addWidget(btn)
            return btn

        self.bond_plain = _add_bond_tool(
            bond_plain_icon(), "Single bond (plain).", 1, BOND_STEREO_PLAIN, checked=True
        )
        self.bond_double = _add_bond_tool(bond_double_icon(), "Double bond.", 2, BOND_STEREO_PLAIN)
        self.bond_triple = _add_bond_tool(bond_triple_icon(), "Triple bond.", 3, BOND_STEREO_PLAIN)
        self.bond_wedge = _add_bond_tool(
            bond_wedge_icon(), "Wedge bond (solid stereo).", 1, BOND_STEREO_WEDGE
        )
        self.bond_hash = _add_bond_tool(
            bond_hash_icon(), "Hash bond (dashed stereo).", 1, BOND_STEREO_HASH
        )
        self.bond_wavy = _add_bond_tool(
            bond_wavy_icon(),
            "Wavy bond (unspecified / undetermined stereochemistry).",
            1,
            BOND_STEREO_WAVY,
        )
        self.bond_dative = _add_bond_tool(
            bond_dative_icon(),
            "Dative / coordinate bond (arrow from donor to acceptor).",
            1,
            BOND_STEREO_DATIVE,
        )
        top_bar.addWidget(_toolbar_vsep())

        self._ring_button_group = QButtonGroup(self)
        self._ring_button_group.setExclusive(False)
        self._ring_btn_by_key: dict[str, QPushButton] = {}
        for key, n_atoms, aromatic, tip in TOOLBAR_RING_TEMPLATES:
            rb = _glyph_tool_button(ring_icon(n_atoms, aromatic=aromatic), tip)
            rb.clicked.connect(lambda checked=False, k=key: self._on_ring_tool_clicked(k, checked))
            self._ring_button_group.addButton(rb)
            self._ring_btn_by_key[key] = rb
            top_bar.addWidget(rb)
        top_bar.addWidget(_toolbar_vsep())

        self.charge_plus = _glyph_tool_button(
            charge_plus_icon(), "Set formal charge +1 on the next atom click."
        )
        self.charge_plus.clicked.connect(
            lambda checked: self._toggle_charge(1 if checked else None)
        )
        self.charge_minus = _glyph_tool_button(
            charge_minus_icon(), "Set formal charge −1 on the next atom click."
        )
        self.charge_minus.clicked.connect(
            lambda checked: self._toggle_charge(-1 if checked else None)
        )
        top_bar.addWidget(self.charge_plus)
        top_bar.addWidget(self.charge_minus)

        self.tb_3d = _glyph_tool_button(
            view_3d_icon(),
            "Show a live 3D preview of the sketch beside the canvas.",
        )
        self.tb_3d.setChecked(False)
        self.tb_3d.toggled.connect(self._toggle_3d_view)
        top_bar.addWidget(self.tb_3d)
        top_bar.addWidget(_toolbar_vsep())
        self.tb_rxn_arrow = _glyph_tool_button(
            reaction_arrow_icon(),
            "Reaction arrow: drag to draw. Fragments on the tail are reactants; "
            "fragments on the head are products. Export to Table adds Reaction SMARTS "
            "and renders the 2D scheme. Hold Shift to snap.",
        )
        self.tb_rxn_arrow.toggled.connect(self._toggle_reaction_arrow)
        top_bar.addWidget(self.tb_rxn_arrow)
        top_bar.addStretch(1)

        self.tb_structure_status = _glyph_tool_button(
            status_ok_icon(),
            "Structure status: click for valence and stereochemistry issues.",
            checkable=False,
        )
        self.tb_structure_status.clicked.connect(self._on_structure_status_clicked)
        top_bar.addWidget(self.tb_structure_status)

        top_toolbar = QWidget()
        top_toolbar.setObjectName("SketcherTopToolbar")
        top_toolbar.setStyleSheet(
            "#SketcherTopToolbar { background-color: palette(window); border: none; }"
        )
        top_toolbar.setLayout(top_bar)
        top_toolbar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self._top_toolbar = top_toolbar
        l.addWidget(top_toolbar)

        main_h = QHBoxLayout()
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        toolbar_outer = QVBoxLayout()
        toolbar_outer.setSpacing(4)
        toolbar_outer.setContentsMargins(8, 4, 8, 6)
        toolbar_outer.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        self._toolbar_outer = toolbar_outer

        # --- Elements by informal PT family; Custom: * wildcard and ? any-element ---
        self.element_buttons: list[QPushButton] = []
        self._element_btn_by_symbol: dict[str, QPushButton] = {}
        self._element_button_group = QButtonGroup(self)
        self._element_button_group.setExclusive(True)
        self._el_btn_font = QFont("Sans", 8, QFont.Bold)
        self._el_btn_font.setStyleHint(QFont.SansSerif)
        self._el_ncols = 4
        self._el_grid = QGridLayout()
        self._el_grid.setHorizontalSpacing(4)
        self._el_grid.setVerticalSpacing(3)
        self._any_element_symbol: str | None = None
        self.tb_wildcard = QPushButton("*")
        self.tb_any_element = QPushButton("?")
        toolbar_outer.addLayout(self._el_grid)
        initial_els = (
            list(self._element_symbols_override)
            if self._element_symbols_override is not None
            else load_toolbar_element_symbols()
        )
        self._populate_element_toolbar(initial_els)

        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("SketcherToolbarPanel")
        toolbar_widget.setStyleSheet(
            "#SketcherToolbarPanel { background-color: palette(window); border: none; }"
        )
        # Wide enough for "Alkaline Earth Metals" header + margins (4×28px buttons).
        toolbar_widget.setFixedWidth(172)
        toolbar_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Maximum)
        toolbar_widget.setLayout(toolbar_outer)
        self._toolbar_panel = toolbar_widget
        main_h.addWidget(toolbar_widget, 0, Qt.AlignTop)

        self.canvas = SketchWidget(self)
        self.canvas.select_mode = False
        self.canvas.setToolTip(
            "Right-click empty canvas for templates, modes, cleanup, and zoom-related commands in the menu bar."
        )
        self.canvas.setFocus()

        self.view_3d = Molecule3DEmbedView(self)
        self.view_3d.setVisible(False)
        self.view_3d.setMinimumWidth(420)

        self._canvas_splitter = QSplitter(Qt.Horizontal)
        self._canvas_splitter.setChildrenCollapsible(False)
        self._canvas_splitter.addWidget(self.canvas)
        self._canvas_splitter.addWidget(self.view_3d)
        self._canvas_splitter.setStretchFactor(0, 1)
        self._canvas_splitter.setStretchFactor(1, 1)
        main_h.addWidget(self._canvas_splitter, 1)
        l.addLayout(main_h)

        self._3d_refresh_timer = QTimer(self)
        self._3d_refresh_timer.setSingleShot(True)
        self._3d_refresh_timer.setInterval(350)
        self._3d_refresh_timer.timeout.connect(self._refresh_3d_view_now)

        self.canvas.sketchChanged.connect(self._update_sketch_status)
        self.canvas.sketchChanged.connect(self._schedule_3d_refresh)
        self.tb_erase.blockSignals(True)
        self.tb_erase.setChecked(False)
        self.tb_erase.blockSignals(False)
        self.select_btn.blockSignals(True)
        self.select_btn.setChecked(True)
        self.select_btn.blockSignals(False)
        self._toggle_select(True)
        self._update_sketch_status()

        if self._initial_mol is not None:
            QTimer.singleShot(0, self._apply_initial_mol)

        self._sync_mode_menu_checks()

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._escape_asks_close)

        self._parent_delete_action = None
        self._parent_delete_was_enabled = False
        self._sketch_key_filters_installed = False
        make_window_minimizable(self)

    @staticmethod
    def _is_sketch_delete_key(event) -> bool:
        if event.key() not in (Qt.Key_Delete, Qt.Key_Backspace):
            return False
        mods = event.modifiers()
        return not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))

    def _resolve_parent_delete_action(self):
        if self._parent_delete_action is not None:
            return self._parent_delete_action
        parent = self.parent()
        if parent is not None and hasattr(parent, "_hotkey_actions"):
            self._parent_delete_action = parent._hotkey_actions.get("edit.delete_selection")
        return self._parent_delete_action

    def _set_parent_delete_action_blocked(self, blocked: bool) -> None:
        act = self._resolve_parent_delete_action()
        if act is None:
            return
        if blocked:
            if act.isEnabled():
                self._parent_delete_was_enabled = True
                act.setEnabled(False)
        elif self._parent_delete_was_enabled:
            act.setEnabled(True)
            self._parent_delete_was_enabled = False

    def _install_sketch_key_filters(self) -> None:
        if self._sketch_key_filters_installed:
            return
        for widget in (self, *self.findChildren(QWidget)):
            widget.installEventFilter(self)
        self._sketch_key_filters_installed = True

    def _remove_sketch_key_filters(self) -> None:
        if not self._sketch_key_filters_installed:
            return
        for widget in (self, *self.findChildren(QWidget)):
            widget.removeEventFilter(self)
        self._sketch_key_filters_installed = False

    def eventFilter(self, obj, event) -> bool:  # noqa: ARG002
        if not self.isVisible():
            return False
        if event.type() == QEvent.ShortcutOverride and self._is_sketch_delete_key(event):
            event.accept()
            return False
        if event.type() == QEvent.KeyPress and self._is_sketch_delete_key(event):
            self._on_edit_delete()
            return True
        return False

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._set_parent_delete_action_blocked(True)
        self._install_sketch_key_filters()

    def hideEvent(self, event) -> None:
        self._set_parent_delete_action_blocked(False)
        self._remove_sketch_key_filters()
        super().hideEvent(event)

    def _sync_mode_menu_checks(self) -> None:
        if not getattr(self, "_act_mode_erase", None):
            return
        rxn_on = bool(
            getattr(self, "tb_rxn_arrow", None) is not None and self.tb_rxn_arrow.isChecked()
        )
        draw_on = (
            not self.tb_erase.isChecked()
            and not self.select_btn.isChecked()
            and not self.lasso_btn.isChecked()
            and not self.tb_text.isChecked()
            and not rxn_on
        )
        self._act_mode_draw.blockSignals(True)
        self._act_mode_draw.setChecked(draw_on)
        self._act_mode_draw.blockSignals(False)
        if getattr(self, "tb_draw", None) is not None:
            self.tb_draw.blockSignals(True)
            self.tb_draw.setChecked(draw_on)
            self.tb_draw.blockSignals(False)
        self._act_mode_erase.blockSignals(True)
        self._act_mode_erase.setChecked(self.tb_erase.isChecked())
        self._act_mode_erase.blockSignals(False)
        self._act_mode_select.blockSignals(True)
        self._act_mode_select.setChecked(self.select_btn.isChecked())
        self._act_mode_select.blockSignals(False)
        if getattr(self, "_act_mode_lasso", None) is not None:
            self._act_mode_lasso.blockSignals(True)
            self._act_mode_lasso.setChecked(self.lasso_btn.isChecked())
            self._act_mode_lasso.blockSignals(False)
        if getattr(self, "_act_mode_text", None) is not None:
            self._act_mode_text.blockSignals(True)
            self._act_mode_text.setChecked(self.tb_text.isChecked())
            self._act_mode_text.blockSignals(False)

    def show_sketch_canvas_menu(self, global_pos: QPoint) -> None:
        """Templates, modes, and cleanup (formerly the Draw menu). Right-click empty canvas."""
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        wpt = self.canvas.mapFromGlobal(global_pos)
        self.canvas._add_copy_paste_menu_actions(
            menu, paste_anchor=self.canvas._widget_point_to_model(wpt)
        )

        def _sync_menu() -> None:
            self._sync_mode_menu_checks()
            self._act_canvas_add_hs.blockSignals(True)
            self._act_canvas_add_hs.setChecked(self.canvas.sketch_has_explicit_hydrogens())
            self._act_canvas_add_hs.blockSignals(False)

        menu.aboutToShow.connect(_sync_menu)
        menu.addAction(self._act_mode_draw)
        menu.addAction(self._act_mode_erase)
        menu.addAction(self._act_mode_select)
        menu.addAction(self._act_mode_lasso)
        menu.addAction(self._act_mode_text)
        menu.addSeparator()
        tpl_menu = menu.addMenu("Templates")
        tpl_menu.setToolTipsVisible(True)
        self._populate_templates_menu(tpl_menu)
        menu.addSeparator()
        menu.addAction(self._act_canvas_group)
        menu.addAction(self._act_canvas_ungroup)
        menu.addAction(self._act_canvas_clear)
        menu.addAction(self._act_canvas_cleanup)
        self._act_canvas_cleanup_selected.setEnabled(
            len(self.canvas._atoms_for_selection_move()) >= 2
        )
        menu.addAction(self._act_canvas_cleanup_selected)
        menu.addAction(self._act_canvas_add_hs)
        menu.exec_(global_pos)

    def _on_view_zoom_in(self) -> None:
        self.canvas.zoom_about_viewport_center(1.15, True)
        self._update_sketch_status()

    def _on_view_zoom_out(self) -> None:
        self.canvas.zoom_about_viewport_center(1.0 / 1.15, True)
        self._update_sketch_status()

    def _on_view_fit_structure(self) -> None:
        self.canvas.fit_sketch_to_viewport()
        self._update_sketch_status()

    def _on_menu_mode_draw(self, checked: bool) -> None:
        if checked:
            self._enter_draw_mode()
            return
        # Keep one mode active: unchecking Draw while erase/select/text are off re-checks Draw.
        if (
            not self.tb_erase.isChecked()
            and not self.select_btn.isChecked()
            and not self.lasso_btn.isChecked()
            and not self.tb_text.isChecked()
            and not (
                getattr(self, "tb_rxn_arrow", None) is not None and self.tb_rxn_arrow.isChecked()
            )
        ):
            self._act_mode_draw.blockSignals(True)
            self._act_mode_draw.setChecked(True)
            self._act_mode_draw.blockSignals(False)

    def _on_menu_mode_erase(self, checked: bool) -> None:
        prev = self.tb_erase.isChecked()
        self.tb_erase.blockSignals(True)
        if prev != checked:
            self.tb_erase.setChecked(checked)
        self.tb_erase.blockSignals(False)
        if prev != checked:
            self._toggle_erase(checked)
        else:
            self._sync_mode_menu_checks()

    def _on_menu_mode_select(self, checked: bool) -> None:
        prev = self.select_btn.isChecked()
        self.select_btn.blockSignals(True)
        if prev != checked:
            self.select_btn.setChecked(checked)
        self.select_btn.blockSignals(False)
        if prev != checked:
            self._toggle_select(checked)
        else:
            self._sync_mode_menu_checks()

    def _on_menu_mode_lasso(self, checked: bool) -> None:
        prev = self.lasso_btn.isChecked()
        self.lasso_btn.blockSignals(True)
        if prev != checked:
            self.lasso_btn.setChecked(checked)
        self.lasso_btn.blockSignals(False)
        if prev != checked:
            self._toggle_lasso(checked)
        else:
            self._sync_mode_menu_checks()

    def _on_menu_mode_text(self, checked: bool) -> None:
        prev = self.tb_text.isChecked()
        self.tb_text.blockSignals(True)
        if prev != checked:
            self.tb_text.setChecked(checked)
        self.tb_text.blockSignals(False)
        if prev != checked:
            self._toggle_text(checked)
        else:
            self._sync_mode_menu_checks()

    def _select_element_tool(self, el: str) -> None:
        self._on_element_tool_clicked(el, True)

    def _select_wildcard_element_tool(self) -> None:
        if getattr(self, "tb_wildcard", None) is None:
            return
        self.tb_wildcard.blockSignals(True)
        self.tb_wildcard.setChecked(True)
        self.tb_wildcard.blockSignals(False)
        self._on_wildcard_tool_toggled(True)

    def _enter_draw_mode(self) -> None:
        """Leave erase/select/template, choose carbon, and focus the canvas for drawing."""
        self._leave_special_modes_for_drawing()
        self.canvas.active_template = None
        self._uncheck_ring_buttons()
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._select_default_element_tool()
        self.canvas.setFocus()
        self._update_sketch_status()
        self._sync_mode_menu_checks()

    def _on_edit_delete(self) -> None:
        """Edit → Delete Selection / Del: hover target first, else the current selection."""
        if getattr(self, "_edit_delete_busy", False):
            return
        self._edit_delete_busy = True
        try:
            self.canvas._handle_delete_key()
        finally:
            self._edit_delete_busy = False

    def _shortcut_copy_selection(self) -> None:
        if not self.canvas.copy_selection_to_clipboard():
            QMessageBox.information(
                self,
                "Copy",
                "Turn on Select, pick atoms/bonds, then Ctrl+C to copy.",
            )

    def _shortcut_paste_selection(self) -> None:
        anchor = self.canvas.mapFromGlobal(QCursor.pos())
        if not self.canvas.paste_from_clipboard(anchor):
            QMessageBox.information(
                self,
                "Paste",
                "Clipboard has no sketch selection (use Ctrl+C in Select mode first).",
            )

    def _populate_templates_menu(self, tpl_menu: QMenu) -> None:
        def add_section(title: str, pairs: list[tuple[str, str]]) -> None:
            tpl_menu.addSection(title)
            for label, key in pairs:
                act = QAction(label, self)
                act.triggered.connect(lambda _=False, k=key: self._select_template_from_menu(k))
                tpl_menu.addAction(act)

        add_section(
            "Carbocycles",
            [
                ("Benzene", "Benzene"),
                ("Cyclopropane", "Cyclopropane"),
                ("Cyclobutane", "Cyclobutane"),
                ("Cyclopentyl", "Cyclopentyl"),
                ("Cyclohexyl", "Cyclohexyl"),
                ("Cycloheptane", "Cycloheptane"),
                ("Cyclooctane", "Cyclooctane"),
                ("Cyclononane", "Cyclononane"),
                ("Cyclodecane", "Cyclodecane"),
                ("Cycloundecane", "Cycloundecane"),
                ("Cyclododecane", "Cyclododecane"),
            ],
        )
        add_section(
            "Nitrogen heterocycles",
            [
                ("Pyridine", "Pyridine"),
                ("Pyrimidine", "Pyrimidine"),
                ("Pyrazine", "Pyrazine"),
                ("Pyridazine", "Pyridazine"),
                ("1,3,5-Triazine", "Triazine"),
                ("Pyrrole", "Pyrrole"),
                ("Imidazole", "Imidazole"),
                ("Pyrazole", "Pyrazole"),
                ("1,2,4-Triazole", "Triazole_124"),
                ("1,2,3-Triazole", "Triazole_123"),
                ("Piperidine", "Piperidine"),
                ("Piperazine", "Piperazine"),
                ("Morpholine", "Morpholine"),
            ],
        )
        add_section(
            "Oxygen heterocycles",
            [
                ("Furan", "Furan"),
                ("Oxazole", "Oxazole"),
                ("Isoxazole", "Isoxazole"),
                ("Tetrahydrofuran (THF)", "THF"),
                ("Oxetane", "Oxetane"),
                ("1,4-Dioxane", "Dioxane"),
                ("1,3-Dioxolane", "Dioxolane"),
                ("1,3,4-Oxadiazole", "Oxadiazole"),
            ],
        )
        add_section(
            "Sulfur heterocycles",
            [
                ("Thiophene", "Thiophene"),
                ("Thiazole", "Thiazole"),
                ("Isothiazole", "Isothiazole"),
                ("Thietane", "Thietane"),
                ("Thiane (tetrahydrothiopyran)", "Thiane"),
                ("1,3,4-Thiadiazole", "Thiadiazole"),
            ],
        )

    def _leave_special_modes_for_drawing(self, *, reset_bond: bool = True) -> None:
        """Exit Select, Erase, Text, and Reaction arrow so drawing tools (element/template) apply."""
        if self.tb_erase.isChecked():
            self.tb_erase.blockSignals(True)
            self.tb_erase.setChecked(False)
            self.tb_erase.blockSignals(False)
        self._uncheck_select_tool_buttons()
        if self.tb_text.isChecked():
            self.tb_text.blockSignals(True)
            self.tb_text.setChecked(False)
            self.tb_text.blockSignals(False)
        self._uncheck_reaction_arrow_tool()
        self.canvas.erase_mode = False
        self.canvas.select_mode = False
        self.canvas.select_tool = "box"
        self.canvas.text_mode = False
        self.canvas.reaction_arrow_mode = False
        self.canvas.setCursor(Qt.ArrowCursor)
        self._clear_canvas_selection_ui()
        if reset_bond:
            self._reset_bond_stereo_toolbar()
        self.canvas.update()
        self._sync_mode_menu_checks()

    def _uncheck_select_tool_buttons(self) -> None:
        for btn in (self.select_btn, self.lasso_btn):
            if btn.isChecked():
                btn.blockSignals(True)
                btn.setChecked(False)
                btn.blockSignals(False)

    def _clear_canvas_selection_ui(self) -> None:
        self.canvas.selected_nodes = []
        self.canvas.selected_bond_indices = set()
        self.canvas.selected_reaction_arrow = False
        self.canvas._selection_rect = None
        self.canvas._selecting = False
        self.canvas._lasso_points = []
        self.canvas._release_marquee_mouse_grab_if_any()
        self.canvas._maybe_move = False
        self.canvas._moving = False

    def _uncheck_reaction_arrow_tool(self) -> None:
        btn = getattr(self, "tb_rxn_arrow", None)
        if btn is None or not btn.isChecked():
            return
        btn.blockSignals(True)
        btn.setChecked(False)
        btn.blockSignals(False)
        self.canvas.reaction_arrow_mode = False

    def _uncheck_bond_tools(self) -> None:
        group = getattr(self, "_bond_tool_group", None)
        if group is not None:
            group.setExclusive(False)
        for btn, _o, _s in getattr(self, "_bond_tool_buttons", []):
            btn.blockSignals(True)
            btn.setChecked(False)
            btn.blockSignals(False)
        if group is not None:
            group.setExclusive(True)

    def _toggle_reaction_arrow(self, checked: bool) -> None:
        if checked:
            if self.tb_erase.isChecked():
                self.tb_erase.blockSignals(True)
                self.tb_erase.setChecked(False)
                self.tb_erase.blockSignals(False)
                self.canvas.erase_mode = False
            if self._any_select_tool_on():
                self._uncheck_select_tool_buttons()
                self._clear_canvas_selection_ui()
                self.canvas.select_mode = False
            if self.tb_text.isChecked():
                self.tb_text.blockSignals(True)
                self.tb_text.setChecked(False)
                self.tb_text.blockSignals(False)
                self.canvas.text_mode = False
            self.canvas.reaction_arrow_mode = True
            self.canvas.place_element = None
            self.canvas.active_template = None
            self._uncheck_element_buttons_clear_place()
            self._uncheck_ring_buttons()
            self._uncheck_bond_tools()
            self.canvas.setCursor(Qt.CrossCursor)
            self.canvas.setFocus()
        else:
            self.canvas.reaction_arrow_mode = False
            self.canvas.setCursor(Qt.ArrowCursor)
            if (
                not self.tb_erase.isChecked()
                and not self._any_select_tool_on()
                and not self.tb_text.isChecked()
            ):
                self._select_default_element_tool()
                self._reset_bond_stereo_toolbar()
        self._sync_mode_menu_checks()

    def _any_select_tool_on(self) -> bool:
        return self.select_btn.isChecked() or self.lasso_btn.isChecked()

    def _reset_bond_stereo_toolbar(self) -> None:
        self._set_bond_tool(1, BOND_STEREO_PLAIN)

    def _set_bond_tool(self, order: int, stereo: int) -> None:
        self.canvas.active_bond_order = int(order)
        self.canvas.active_bond_stereo = int(stereo) if int(order) == 1 else BOND_STEREO_PLAIN
        for btn, o, s in getattr(self, "_bond_tool_buttons", []):
            btn.blockSignals(True)
            btn.setChecked(o == order and s == (stereo if order == 1 else BOND_STEREO_PLAIN))
            btn.blockSignals(False)

    def _on_bond_tool(self, order: int, stereo: int) -> None:
        """Select a bond type and switch the canvas to draw mode."""
        self._leave_special_modes_for_drawing(reset_bond=False)
        self.canvas.active_template = None
        self._uncheck_ring_buttons()
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._select_default_element_tool()
        self._set_bond_tool(order, stereo)
        self.canvas.setFocus()
        self._update_sketch_status()
        self._sync_mode_menu_checks()

    def _on_bond_stereo_tool(self, val: int) -> None:
        """Backward-compatible alias: stereo tools imply order 1."""
        self._on_bond_tool(1, val)

    def _on_toggle_show_lone_pairs(self, checked: bool) -> None:
        self.canvas.show_lone_pairs = bool(checked)
        self.canvas.update()

    def _clear_element_grid_widgets(self) -> None:
        """Remove element-panel widgets; keep wildcard/? buttons for reuse."""
        while self._el_grid.count():
            item = self._el_grid.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w is self.tb_wildcard or w is self.tb_any_element:
                w.setParent(None)
                continue
            if isinstance(w, QPushButton) and w.property("sketch_element"):
                self._element_button_group.removeButton(w)
            w.deleteLater()
        self.element_buttons.clear()
        self._element_btn_by_symbol.clear()

    def _populate_element_toolbar(self, symbols: list[str]) -> None:
        """Build left-panel element buttons for ``symbols`` (plus Custom * / ?)."""
        self._visible_element_symbols = list(symbols)
        self._clear_element_grid_widgets()
        el_ncols = self._el_ncols
        btn_font = self._el_btn_font
        grid_row = 0
        groups = element_groups_for_symbols(symbols)
        for gi, (group_title, group_symbols) in enumerate(groups):
            if gi > 0:
                self._el_grid.addWidget(_toolbar_hsep(), grid_row, 0, 1, el_ncols)
                grid_row += 1
            self._el_grid.addWidget(_toolbar_header(group_title), grid_row, 0, 1, el_ncols)
            grid_row += 1
            for i, el in enumerate(group_symbols):
                b = QPushButton(el)
                b.setCheckable(True)
                b.setProperty("sketch_element", el)
                b.setFont(btn_font)
                b.setFixedSize(28, 26)
                b.setStyleSheet("padding: 0px;")
                row, col = i // el_ncols, i % el_ncols
                if el == "C":
                    b.setToolTip(
                        "Carbon: click empty space to place C; click another C to extend a chain; "
                        "click any other atom to replace it with carbon."
                    )
                elif el == "D":
                    b.setToolTip("Deuterium (hydrogen isotope).")
                elif el == "T":
                    b.setToolTip("Tritium (hydrogen isotope).")
                else:
                    b.setToolTip(f"Place {el} ({group_title}).")
                b.clicked.connect(lambda checked, e=el: self._on_element_tool_clicked(e, checked))
                self._element_button_group.addButton(b)
                self._el_grid.addWidget(b, grid_row + row, col)
                self.element_buttons.append(b)
                self._element_btn_by_symbol[el] = b
            grid_row += (len(group_symbols) + el_ncols - 1) // el_ncols

        self._el_grid.addWidget(_toolbar_hsep(), grid_row, 0, 1, el_ncols)
        grid_row += 1
        self._el_grid.addWidget(_toolbar_header("Custom"), grid_row, 0, 1, el_ncols)
        grid_row += 1

        self.tb_wildcard.setCheckable(True)
        self.tb_wildcard.setFont(btn_font)
        self.tb_wildcard.setToolTip(
            "Wildcard atom: SMARTS query over selected elements. Right-click a wildcard to edit choices."
        )
        self.tb_wildcard.setFixedSize(28, 26)
        self.tb_wildcard.setStyleSheet("padding: 0px;")
        try:
            self.tb_wildcard.toggled.disconnect()
        except TypeError:
            pass
        self.tb_wildcard.toggled.connect(self._on_wildcard_tool_toggled)

        self.tb_any_element.setCheckable(True)
        self.tb_any_element.setFont(btn_font)
        self.tb_any_element.setToolTip(
            "Type any periodic-table element symbol (e.g. Au, Ru, Se) to place or replace atoms."
        )
        self.tb_any_element.setFixedSize(28, 26)
        self.tb_any_element.setStyleSheet("padding: 0px;")
        try:
            self.tb_any_element.clicked.disconnect()
        except TypeError:
            pass
        self.tb_any_element.clicked.connect(self._on_any_element_tool_clicked)

        self._el_grid.addWidget(self.tb_wildcard, grid_row, 0)
        self._el_grid.addWidget(self.tb_any_element, grid_row, 1)

        # Drop place-tool if the selected element was removed from the panel.
        place = getattr(self.canvas, "place_element", None) if hasattr(self, "canvas") else None
        if place and place not in self._element_btn_by_symbol and place != WILDCARD_ELEMENT:
            if getattr(self, "canvas", None) is not None:
                self.canvas.place_element = None

    def _customize_elements(self) -> None:
        """Settings → Customize Elements: add/remove left-panel element buttons."""
        current = getattr(self, "_visible_element_symbols", None) or load_toolbar_element_symbols()
        dlg = CustomizeElementsDialog(self, selected=current)
        if dlg.exec_() != QDialog.Accepted:
            return
        symbols = dlg.selected_symbols()
        save_toolbar_element_symbols(symbols)
        self._populate_element_toolbar(symbols)
        if getattr(self, "_toolbar_panel", None) is not None:
            self._toolbar_panel.adjustSize()

    def _open_physical_properties(self) -> None:
        """Open (or raise) the modeless Physical Properties window."""
        from .physical_properties import SketchPhysicalPropertiesDialog

        dlg = self._phys_props_dlg
        if dlg is None:
            dlg = SketchPhysicalPropertiesDialog(self)
            self._phys_props_dlg = dlg
            dlg.destroyed.connect(lambda *_: setattr(self, "_phys_props_dlg", None))
            self.canvas.sketchChanged.connect(dlg.schedule_refresh)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.schedule_refresh()

    def _undo_sketch(self) -> None:
        self.canvas.undo()
        self._update_sketch_status()

    def _redo_sketch(self) -> None:
        self.canvas.redo()
        self._update_sketch_status()

    def _uncheck_ring_buttons(self) -> None:
        for b in getattr(self, "_ring_btn_by_key", {}).values():
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)

    def _sync_ring_toolbar_checks(self, name: str | None) -> None:
        for key, b in getattr(self, "_ring_btn_by_key", {}).items():
            b.blockSignals(True)
            b.setChecked(key == name)
            b.blockSignals(False)

    def _on_ring_tool_clicked(self, name: str, checked: bool) -> None:
        if not checked:
            if self.canvas.active_template == name:
                self.canvas.active_template = None
                self._enter_draw_mode()
            return
        self._select_template_from_menu(name)

    def _uncheck_element_buttons_clear_place(self) -> None:
        for b in self.element_buttons:
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._uncheck_any_element_button()
        self.canvas.place_element = None

    def _select_template_from_menu(self, name: str) -> None:
        self._leave_special_modes_for_drawing()
        self._uncheck_element_buttons_clear_place()
        self.canvas.active_template = name
        self._sync_ring_toolbar_checks(name)

    def _save_sketch(self) -> None:
        smi = self.canvas.to_smiles().strip()
        if not smi:
            QMessageBox.warning(self, "Save Sketch", "No valid structure to save from the sketch.")
            return
        mol = Chem.MolFromSmiles(smi) or Chem.MolFromSmarts(smi)
        if mol is None:
            QMessageBox.warning(
                self,
                "Save Sketch",
                "RDKit could not build a molecule from the sketch (SMILES/SMARTS).",
            )
            return
        app = self.parent_app
        if app is None or not hasattr(app, "threadpool") or not hasattr(app, "signals"):
            QMessageBox.warning(
                self, "Save Sketch", "Main application is not available for export."
            )
            return
        f_filter = "SDF (*.sdf);;Molfile (*.mol);;SMILES (*.smi)"
        path, sel_f = QFileDialog.getSaveFileName(self, "Save Sketch", "", f_filter)
        if not path or not sel_f:
            return
        m = re.search(r"\((.*)\)", sel_f)
        if not m:
            return
        ext = m.group(1).replace("*", "")
        if not path.endswith(ext):
            path += ext
        oid = 0
        mols = {oid: mol}
        heads = ["ID_HIDDEN", "Structure", "SMILES"]
        data = {oid: {"SMILES": smi}}
        app.process_queue.enqueue(
            f"Save sketch: {path}",
            lambda ev, p=path, e=ext, m=mols, h=heads, d=data, s=app.signals: ExportWorker(
                p, e, m, h, d, s, cancel_event=ev
            ),
        )

    def _escape_asks_close(self) -> None:
        self.close()

    def _uncheck_any_element_button(self) -> None:
        if getattr(self, "tb_any_element", None) is None:
            return
        self.tb_any_element.blockSignals(True)
        self.tb_any_element.setChecked(False)
        self.tb_any_element.blockSignals(False)
        self._any_element_symbol = None

    def _on_element_tool_clicked(self, el: str, checked: bool) -> None:
        if not checked:
            return
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._uncheck_any_element_button()
        self._leave_special_modes_for_drawing()
        self.canvas.active_template = None
        self._uncheck_ring_buttons()
        self.canvas.place_element = el
        for b in self.element_buttons:
            bel = b.property("sketch_element")
            b.blockSignals(True)
            b.setChecked(bel == el)
            b.blockSignals(False)

    def _on_wildcard_tool_toggled(self, on: bool) -> None:
        if on:
            for b in self.element_buttons:
                b.blockSignals(True)
                b.setChecked(False)
                b.blockSignals(False)
            self._uncheck_any_element_button()
            self._leave_special_modes_for_drawing()
            self.canvas.active_template = None
            self._uncheck_ring_buttons()
            self.canvas.place_element = WILDCARD_ELEMENT
        elif self.canvas.place_element == WILDCARD_ELEMENT:
            self._select_default_element_tool()

    def _on_any_element_tool_clicked(self, checked: bool) -> None:
        if not checked:
            if self._any_element_symbol and self.canvas.place_element == self._any_element_symbol:
                self._any_element_symbol = None
                self._select_default_element_tool()
            return
        hint = self._any_element_symbol or "Au"
        txt, ok = QInputDialog.getText(
            self,
            "Element",
            "Enter any periodic-table element symbol (e.g. Au, Ru, Se, Cl):",
            text=hint,
        )
        if not ok:
            self._uncheck_any_element_button()
            return
        sym = _parse_periodic_element_symbol(txt)
        if sym is None:
            QMessageBox.warning(
                self,
                "Element",
                "Unknown or invalid element symbol. Enter a standard periodic-table symbol.",
            )
            self._uncheck_any_element_button()
            return
        for b in self.element_buttons:
            b.blockSignals(True)
            b.setChecked(False)
            b.blockSignals(False)
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._leave_special_modes_for_drawing()
        self.canvas.active_template = None
        self._uncheck_ring_buttons()
        self._any_element_symbol = sym
        self.canvas.place_element = sym
        # Prefer highlighting the toolbar button if this element is already listed.
        listed = self._element_btn_by_symbol.get(sym)
        if listed is not None:
            self._uncheck_any_element_button()
            listed.blockSignals(True)
            listed.setChecked(True)
            listed.blockSignals(False)
        else:
            self.tb_any_element.blockSignals(True)
            self.tb_any_element.setChecked(True)
            self.tb_any_element.blockSignals(False)
            self.tb_any_element.setToolTip(
                f"Place {sym} (click again to choose a different element)."
            )

    def _select_default_element_tool(self) -> None:
        self.canvas.place_element = "C"
        self._any_element_symbol = None
        if getattr(self, "tb_wildcard", None) is not None:
            self.tb_wildcard.blockSignals(True)
            self.tb_wildcard.setChecked(False)
            self.tb_wildcard.blockSignals(False)
        self._uncheck_any_element_button()
        bc = self._element_btn_by_symbol.get("C")
        if bc is not None:
            bc.setChecked(True)

    def _ensure_main_table_for_sketch_import(
        self, app, extra: tuple[str, ...] = ("SMILES",)
    ) -> None:
        """Allow sketcher add before any file load: minimal columns + visible table."""
        if app.headers and app._table_model.columnCount() >= 2:
            return
        app.headers = ["ID_HIDDEN", "Structure", *extra]
        app.table.setSortingEnabled(False)
        app._table_model.clear_rows()
        app._table_model.set_headers(list(app.headers))
        app.table.setColumnHidden(0, True)
        if hasattr(app, "_table_stack"):
            app._table_stack.setCurrentIndex(1)

    def _ensure_table_columns(self, app, headers: tuple[str, ...] | list[str]) -> None:
        """Add missing data columns so sketched reactions can be stored."""
        self._ensure_main_table_for_sketch_import(app, extra=tuple(headers))
        for h in headers:
            if h in app.headers:
                continue
            nc = app._table_model.columnCount()
            app._table_model.insert_column_at(nc, h, None)
            app.headers.append(h)

    def _queue_reaction_structure_render(self, app, oid: int, smarts: str) -> None:
        """Render the reaction scheme into Structure (same PNG path as Chemistry → Render 2D)."""
        spec = ReactionDrawSpec(smarts)
        rw, rh = reaction_depict_size()
        if hasattr(app, "start_render_worker"):
            app.start_render_worker(oid, spec, rw, rh, skip_mol_props=True)
            return
        start_batch = getattr(app, "_start_render_2d_batch", None)
        if not callable(start_batch):
            return
        row = app._table_model.logical_row_for_oid(oid)
        start_batch([(oid, spec, rw, rh)], {oid: row}, "Structure")

    def _append_reaction_from_sketch(self) -> int:
        """Insert one reaction table row. Returns 1 on success, 0 otherwise."""
        app = self.parent_app
        smarts = (self.canvas.to_reaction_smarts() or "").strip()
        if not smarts:
            return 0
        self._ensure_table_columns(app, (RXN_SMARTS_HEADER,))
        oid = app.next_oid
        app.next_oid += 1
        app._table_model.append_row(oid, {RXN_SMARTS_HEADER: smarts})
        self._queue_reaction_structure_render(app, oid, smarts)
        app.status_label.setText("Added 1 reaction from sketcher")
        if hasattr(app, "calculate_global_bounds"):
            app.calculate_global_bounds()
        if hasattr(app, "apply_filters"):
            app.apply_filters()
        return 1

    def _append_molecules_from_smiles_parts(self, parts: list[str]) -> int:
        """Insert one table row per SMILES string. Returns number added."""
        app = self.parent_app
        self._ensure_main_table_for_sketch_import(app)
        n_added = 0
        smiles_col = app.headers.index("SMILES") if "SMILES" in app.headers else None
        for smi in parts:
            smi = (smi or "").strip()
            if not smi:
                continue
            mol = Chem.MolFromSmiles(smi) or Chem.MolFromSmarts(smi)
            if mol is None:
                continue
            oid = app.next_oid
            app.next_oid += 1
            app.mols[oid] = mol
            cells: dict[str, str] = {}
            if smiles_col is not None:
                cells[app.headers[smiles_col]] = smi
            app._table_model.append_row(oid, cells)
            app.start_render_worker(oid, mol)
            n_added += 1
        if n_added:
            app.status_label.setText(f"Added {n_added} molecule(s) from sketcher")
            if hasattr(app, "calculate_global_bounds"):
                app.calculate_global_bounds()
            if hasattr(app, "apply_filters"):
                app.apply_filters()
        return n_added

    def refresh_theme(self) -> None:
        """Re-apply palette-driven chrome after a live light/dark/groovy switch."""
        top = getattr(self, "_top_toolbar", None)
        if top is not None:
            top.setStyleSheet(
                "#SketcherTopToolbar { background-color: palette(window); border: none; }"
            )
        panel = getattr(self, "_toolbar_panel", None)
        if panel is not None:
            panel.setStyleSheet(
                "#SketcherToolbarPanel { background-color: palette(window); border: none; }"
            )
        header_qss = (
            "color: palette(mid); font-size: 11px; font-weight: 600; letter-spacing: 0.3px; "
            "padding-top: 2px; padding-bottom: 2px;"
        )
        for lab in self.findChildren(QLabel, "SketcherToolbarHeader"):
            lab.setStyleSheet(header_qss)
        if hasattr(self, "canvas") and self.canvas is not None:
            self.canvas.update()
        self.update()

    def _toggle_3d_view(self, checked: bool) -> None:
        """Show or hide the live 3D preview beside the sketch canvas."""
        on = bool(checked)
        self.view_3d.setVisible(on)
        if on:
            # Keep sketch + 3D comfortable: target ~half the splitter for 3D (≥420px).
            geo = self.geometry()
            if geo.width() < 1280:
                self.resize(max(geo.width() + 420, 1280), max(geo.height(), 720))
            QTimer.singleShot(0, self._apply_3d_splitter_sizes)
            self._refresh_3d_view_now()
            QTimer.singleShot(0, self._recenter_sketch_after_3d_layout)
            QTimer.singleShot(120, self.view_3d.refit_view)
            QTimer.singleShot(300, self.view_3d.refit_view)
        else:
            self._3d_refresh_timer.stop()
            QTimer.singleShot(0, self._recenter_sketch_after_3d_layout)

    def _apply_3d_splitter_sizes(self) -> None:
        total = max(self._canvas_splitter.width(), 1)
        min_3d = max(420, int(self.view_3d.minimumWidth()))
        # Prefer ~48% for 3D, but never below min_3d when the window is wide enough.
        w3 = max(min_3d, int(total * 0.48))
        if w3 >= total - 280:
            w3 = max(min_3d, total // 2)
        self._canvas_splitter.setSizes([max(total - w3, 280), w3])
        self.view_3d.schedule_refit()

    def _recenter_sketch_after_3d_layout(self) -> None:
        """Keep the sketched molecule centered when the canvas width changes."""
        try:
            self.canvas.ensure_sketch_fits_viewport(refresh=True)
        except Exception:
            pass

    def _schedule_3d_refresh(self) -> None:
        if not self.tb_3d.isChecked() or self.view_3d.isHidden():
            return
        self._3d_refresh_timer.start()

    def _sketch_mol_for_3d(self):
        ids = {n["id"] for n in self.canvas.nodes}
        if not ids:
            return None
        try:
            return self.canvas._mol_from_node_ids(ids)
        except Exception:
            return None

    def _refresh_3d_view_now(self) -> None:
        if not self.tb_3d.isChecked() or self.view_3d.isHidden():
            return
        mol = self._sketch_mol_for_3d()
        try:
            self.view_3d.set_molecule(mol)
        except Exception:
            pass

    def _update_sketch_status(self) -> None:
        """Refresh the pinned structure-status glyph (ok / caution / error)."""
        btn = getattr(self, "tb_structure_status", None)
        if btn is None:
            return
        level, msgs = self.canvas.structure_issue_report()
        if level == "error":
            btn.setIcon(status_error_icon())
            tip = "Structure has errors (click for details)."
        elif level == "caution":
            btn.setIcon(status_caution_icon())
            tip = "Structure has warnings (click for details)."
        else:
            btn.setIcon(status_ok_icon())
            tip = "No valence or stereochemistry issues flagged (click for details)."
        if msgs:
            tip = tip + "\n" + "\n".join(f"• {m}" for m in msgs[:6])
            if len(msgs) > 6:
                tip += f"\n• (+{len(msgs) - 6} more)"
        btn.setToolTip(tip)
        self._structure_status_level = level
        self._structure_status_messages = msgs

    def _on_structure_status_clicked(self) -> None:
        """Show a silent status dropdown under the toolbar button, kept inside this window."""
        level, msgs = self.canvas.structure_issue_report()
        self._update_sketch_status()
        title = {
            "ok": "Structure OK",
            "caution": "Structure Warnings",
            "error": "Structure Errors",
        }.get(level, "Structure Status")
        menu = QMenu(self)
        menu.setObjectName("SketcherStatusMenu")
        menu.setToolTipsVisible(True)
        hdr = menu.addAction(title)
        hdr.setEnabled(False)
        menu.addSeparator()
        if not msgs:
            act = menu.addAction("No issues.")
            act.setEnabled(False)
        else:
            for m in msgs:
                act = menu.addAction(m)
                act.setEnabled(False)
        btn = self.tb_structure_status
        hint = menu.sizeHint()
        # Prefer below the button; flip above if needed. Clamp to this dialog's frame.
        win = self.window()
        frame = win.frameGeometry() if win is not None else self.frameGeometry()
        # Use client area in global coords so the menu stays on-screen within the app.
        top_left = self.mapToGlobal(self.rect().topLeft())
        bottom_right = self.mapToGlobal(self.rect().bottomRight())
        x0, y0 = top_left.x(), top_left.y()
        x1, y1 = bottom_right.x(), bottom_right.y()
        # Also respect the OS window frame when available.
        x0 = max(x0, frame.left() + 4)
        y0 = max(y0, frame.top() + 4)
        x1 = min(x1, frame.right() - 4)
        y1 = min(y1, frame.bottom() - 4)

        below = btn.mapToGlobal(btn.rect().bottomLeft())
        above = btn.mapToGlobal(btn.rect().topLeft())
        x = below.x()
        y = below.y()
        if y + hint.height() > y1:
            y = above.y() - hint.height()
        if y < y0:
            y = y0
        if y + hint.height() > y1:
            y = max(y0, y1 - hint.height())
        if x + hint.width() > x1:
            x = x1 - hint.width()
        if x < x0:
            x = x0
        menu.exec_(QPoint(x, y))

    def _shortcut_group(self) -> None:
        if not self.canvas.select_mode:
            QMessageBox.information(
                self,
                "Group",
                "Turn on Select or Lasso, select atoms from at least two disconnected structures, then press Ctrl+G.",
            )
            return
        self.canvas._run_group_selection_menu()

    def _shortcut_ungroup(self) -> None:
        ok = self.canvas.ungroup_for_export()
        if not ok:
            QMessageBox.information(
                self,
                "Ungroup",
                "No export group to remove (Ctrl+G groups fragments).",
            )

    def _toggle_erase(self, checked: bool):
        if checked:
            if self._any_select_tool_on():
                self._uncheck_select_tool_buttons()
                self._clear_canvas_selection_ui()
                self.canvas.select_mode = False
            if self.tb_text.isChecked():
                self.tb_text.blockSignals(True)
                self.tb_text.setChecked(False)
                self.tb_text.blockSignals(False)
                self.canvas.text_mode = False
            self._uncheck_reaction_arrow_tool()
        self.canvas.erase_mode = checked
        if checked:
            self.canvas.setCursor(Qt.CrossCursor)
            self.canvas.place_element = None
            self.canvas.active_template = None
            self._uncheck_element_buttons_clear_place()
            self._uncheck_ring_buttons()
        else:
            self.canvas.setCursor(Qt.ArrowCursor)
            if not self._any_select_tool_on() and not self.tb_text.isChecked():
                self._select_default_element_tool()

    def _enter_select_tool(self, tool: str, checked: bool) -> None:
        """Enable box or lasso select; *tool* is ``\"box\"`` or ``\"lasso\"``."""
        other = self.lasso_btn if tool == "box" else self.select_btn
        if checked:
            if other.isChecked():
                other.blockSignals(True)
                other.setChecked(False)
                other.blockSignals(False)
            if self.tb_erase.isChecked():
                self.tb_erase.blockSignals(True)
                self.tb_erase.setChecked(False)
                self.tb_erase.blockSignals(False)
                self.canvas.erase_mode = False
                self.canvas.setCursor(Qt.ArrowCursor)
            if self.tb_text.isChecked():
                self.tb_text.blockSignals(True)
                self.tb_text.setChecked(False)
                self.tb_text.blockSignals(False)
                self.canvas.text_mode = False
            self._uncheck_reaction_arrow_tool()
            self.canvas.select_tool = tool
            self.canvas.select_mode = True
            self.canvas.place_element = None
            self.canvas.active_template = None
            self._uncheck_element_buttons_clear_place()
            self._uncheck_ring_buttons()
            try:
                self.canvas._refresh_hover_from_cursor()
            except Exception:
                self.canvas.setCursor(Qt.ArrowCursor)
            return
        # Unchecking this tool: leave select mode only if the other select tool is also off.
        if not other.isChecked():
            self.canvas.select_mode = False
            self.canvas.select_tool = "box"
            self._clear_canvas_selection_ui()
            self.canvas.setCursor(Qt.ArrowCursor)
            if not self.tb_erase.isChecked() and not self.tb_text.isChecked():
                if getattr(self, "tb_rxn_arrow", None) is None or not self.tb_rxn_arrow.isChecked():
                    self._select_default_element_tool()

    def _toggle_select(self, checked: bool):
        self._enter_select_tool("box", checked)

    def _toggle_lasso(self, checked: bool):
        self._enter_select_tool("lasso", checked)

    def _toggle_text(self, checked: bool):
        if checked:
            if self.tb_erase.isChecked():
                self.tb_erase.blockSignals(True)
                self.tb_erase.setChecked(False)
                self.tb_erase.blockSignals(False)
                self.canvas.erase_mode = False
            if self._any_select_tool_on():
                self._uncheck_select_tool_buttons()
                self._clear_canvas_selection_ui()
                self.canvas.select_mode = False
            self._uncheck_reaction_arrow_tool()
        self.canvas.text_mode = checked
        if checked:
            self.canvas.setCursor(Qt.IBeamCursor)
            self.canvas.place_element = None
            self.canvas.active_template = None
            self._uncheck_element_buttons_clear_place()
            self._uncheck_ring_buttons()
        else:
            self.canvas.setCursor(Qt.ArrowCursor)
            if not self.tb_erase.isChecked() and not self._any_select_tool_on():
                self._select_default_element_tool()

    def _toggle_charge(self, val: int | None):
        try:
            self.canvas.active_charge = val
        except Exception:
            pass
        if val == 1:
            self.charge_minus.setChecked(False)
        if val == -1:
            self.charge_plus.setChecked(False)

    def _clear_sketch(self) -> None:
        self.canvas.clear()

    def _on_center_molecule(self) -> None:
        self.canvas.center_sketch_in_viewport(True)
        self._update_sketch_status()

    def _on_toggle_implicit_hydrogens(self, checked: bool) -> None:
        """Canvas menu toggle: show (AddHs) or hide (remove explicit H) hydrogens."""
        if checked:
            ok, err = self.canvas.add_explicit_hydrogens_from_implicit()
        else:
            ok, err = self.canvas.remove_explicit_hydrogens_from_sketch()
        if not ok:
            self._act_canvas_add_hs.blockSignals(True)
            self._act_canvas_add_hs.setChecked(self.canvas.sketch_has_explicit_hydrogens())
            self._act_canvas_add_hs.blockSignals(False)
            QMessageBox.information(self, "Implicit Hydrogens", err)
            return
        self._leave_special_modes_for_drawing()
        self._select_default_element_tool()
        self._update_sketch_status()

    def _apply_initial_mol(self) -> None:
        mol = self._initial_mol
        self._initial_mol = None
        if mol is None or not isinstance(mol, Chem.Mol):
            return
        self.load_structure_from_mol(mol, confirm_if_nonempty=False)

    def load_structure_from_mol(
        self, mol: Chem.Mol | None, confirm_if_nonempty: bool = True
    ) -> None:
        """Load an RDKit molecule into the canvas (optionally confirm if the sketch is non-empty)."""
        if mol is None or not isinstance(mol, Chem.Mol):
            return
        try:
            m = Chem.Mol(mol)
        except Exception:
            QMessageBox.warning(self, "Sketcher", "Could not copy this structure for editing.")
            return
        if confirm_if_nonempty and self.canvas.to_smiles().strip():
            res = QMessageBox.question(
                self,
                "Replace sketch",
                "Replace the current sketch with this structure?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                return
        c = self.canvas.rect().center()
        center = c if self.canvas.rect().width() > 8 and self.canvas.rect().height() > 8 else None
        if not self.canvas.load_from_rdkit_mol(m, center=center):
            QMessageBox.warning(
                self,
                "Sketcher",
                "Could not build a 2D layout for this structure. It may be unsupported or invalid.",
            )
            return
        self.tb_erase.blockSignals(True)
        self.tb_erase.setChecked(False)
        self.tb_erase.blockSignals(False)
        self.select_btn.blockSignals(True)
        self.select_btn.setChecked(True)
        self.select_btn.blockSignals(False)
        self._toggle_select(True)
        self._update_sketch_status()

    def _on_cleanup_layout(self) -> None:
        ok = self.canvas.cleanup_layout_2d()
        if not ok:
            QMessageBox.information(
                self,
                "Clean Up",
                "Could not re-layout the structure. Try fixing valence or connectivity issues first.",
            )
            return
        issues = self.canvas.refresh_iupac_validation()
        if issues:
            from molmanager.ui.sketcher.iupac_validate import format_iupac_issues

            summary = format_iupac_issues(issues, limit=5)
            QMessageBox.information(
                self,
                "Clean Up",
                f"Layout updated. IUPAC notes:\n{summary}",
            )
            self.canvas.update()

    def _on_cleanup_layout_selected(self) -> None:
        if len(self.canvas._atoms_for_selection_move()) < 2:
            QMessageBox.information(
                self,
                "Clean Up Selected",
                "Select at least two atoms (or a bond) first.",
            )
            return
        ok = self.canvas.cleanup_layout_2d_selected()
        if not ok:
            QMessageBox.information(
                self,
                "Clean Up Selected",
                "Could not re-layout the selection. Try fixing valence or connectivity issues first.",
            )
            return
        issues = self.canvas.refresh_iupac_validation()
        if issues:
            from molmanager.ui.sketcher.iupac_validate import format_iupac_issues

            summary = format_iupac_issues(issues, limit=5)
            QMessageBox.information(
                self,
                "Clean Up Selected",
                f"Selection layout updated. IUPAC notes:\n{summary}",
            )
            self.canvas.update()
        self._update_sketch_status()

    def _copy_smiles(self):
        rxn = (self.canvas.to_reaction_smarts() or "").strip()
        smi = rxn or self.canvas.to_smiles()
        if smi:
            QApplication.clipboard().setText(smi)
        else:
            QMessageBox.warning(
                self,
                "Copy",
                "Could not copy — no valid SMILES/SMARTS for the sketch.",
            )

    def _copy_selected_smiles(self) -> None:
        if not self.canvas._atoms_for_selection_move():
            QMessageBox.information(
                self,
                "Copy Selected as SMILES",
                "Select one or more atoms (or bonds) first.",
            )
            return
        if self.canvas.copy_selected_as_smiles_to_clipboard():
            return
        QMessageBox.warning(
            self,
            "Copy Selected as SMILES",
            "Could not copy — no valid SMILES/SMARTS for the selection.",
        )

    def _copy_smarts(self) -> None:
        smt = (self.canvas.to_reaction_smarts() or self.canvas.to_smarts() or "").strip()
        if smt:
            QApplication.clipboard().setText(smt)
        else:
            QMessageBox.warning(
                self,
                "Copy SMARTS",
                "Could not copy SMARTS (empty sketch or invalid structure).",
            )

    def _add_to_table(self):
        app = self.parent_app

        def _main_status(msg: str) -> None:
            if app is not None and hasattr(app, "status_label"):
                app.status_label.setText(msg)

        if self.canvas.reaction_arrow is not None:
            n = self._append_reaction_from_sketch()
            if n == 0:
                msg = (
                    "Sketcher: could not export a reaction. Draw reactants on the "
                    "arrow tail and products on the head."
                )
                _main_status(msg)
                QMessageBox.warning(self, "Add to Table", msg)
            return

        parts = self.canvas.fragment_smiles_parts()
        if not parts:
            msg = "Sketcher: could not build a valid structure to add to the table (check bonding/valence)."
            _main_status(msg)
            QMessageBox.warning(self, "Add to Table", msg)
            return
        n = self._append_molecules_from_smiles_parts(parts)
        if n == 0:
            msg = "Sketcher: could not parse fragments when adding to the table."
            _main_status(msg)
            QMessageBox.warning(self, "Add to Table", msg)
            return

    def closeEvent(self, event):
        self._set_parent_delete_action_blocked(False)
        self._remove_sketch_key_filters()
        event.accept()
