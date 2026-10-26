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
from PyQt5.QtGui import QCursor, QFont, QFontMetrics, QIcon, QKeySequence
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
    QScrollArea,
    QShortcut,
    QStatusBar,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from ...table.structure_depiction_layout import reaction_depict_size
from ...chem.molecule_conversion import mol_to_canonical_smiles
from ...chem.reaction_file_io import RXN_ANNOTATION_HEADER, RXN_SMARTS_HEADER
from ...chem.structure_2d_depiction import ReactionDrawSpec
from ...workers import ExportWorker

from ..mol_viewer_3d import Molecule3DEmbedView
from ..qt_widget_utils import make_window_resizable
from ..theme import default_app_font_pt, status_bar_font_pt
from .chem import _parse_periodic_element_symbol
from .constants import SKETCH_RAIL_ELEMENTS, SKETCH_RING_TEMPLATES, WILDCARD_ELEMENT
from .contracted_labels import TABLE_CONTRACTED_LABELS
from .fused_templates import FUSED_TEMPLATE_SMILES, fused_template
from .rgroups import is_rgroup_element, rgroup_element
from .customize_elements import (
    CustomizeElementsDialog,
    load_toolbar_element_symbols,
    save_toolbar_element_symbols,
)
from .toolbar_glyphs import (
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
    mode_chain_icon,
    mode_draw_icon,
    mode_erase_icon,
    mode_lasso_icon,
    mode_select_icon,
    mode_text_icon,
    ring_icon,
    ring_template_icon,
    fused_ring_icon,
    status_caution_icon,
    status_error_icon,
    status_ok_icon,
    TOOLBAR_RING_TEMPLATES,
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


_RAIL_COLUMNS = 2
_RAIL_BUTTON_SIZE = 28
_RAIL_H_SPACING = 2
_RAIL_V_SPACING = 2
_RAIL_MARGIN_X = 2
_RAIL_SCROLLBAR = 8


def _rail_content_width() -> int:
    """Width of two buttons and the gap between them."""
    return _RAIL_BUTTON_SIZE * _RAIL_COLUMNS + _RAIL_H_SPACING * (_RAIL_COLUMNS - 1)


def _rail_panel_width() -> int:
    """Left rail width: the button grid, side margins, and a narrow scrollbar."""
    return _rail_content_width() + _RAIL_MARGIN_X * 2 + _RAIL_SCROLLBAR


def _configure_rail_grid(grid: QGridLayout) -> None:
    """Give every rail block the same two columns so the buttons share x positions."""
    grid.setContentsMargins(0, 0, 0, 0)
    grid.setHorizontalSpacing(_RAIL_H_SPACING)
    grid.setVerticalSpacing(_RAIL_V_SPACING)
    for column in range(_RAIL_COLUMNS):
        grid.setColumnMinimumWidth(column, _RAIL_BUTTON_SIZE)
        grid.setColumnStretch(column, 0)


def _toolbar_hsep() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.HLine)
    line.setFrameShadow(QFrame.Sunken)
    line.setFixedSize(_rail_content_width(), 8)
    return line


def _rail_more_button(text: str, tip: str) -> QPushButton:
    """Full-width label under a two-column block, the same height as the buttons."""
    button = QPushButton(text)
    font = QFont("Sans", 9)
    font.setStyleHint(QFont.SansSerif)
    button.setFont(font)
    button.setToolTip(tip)
    button.setFocusPolicy(Qt.NoFocus)
    button.setFixedHeight(_RAIL_BUTTON_SIZE)
    button.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
    button.setStyleSheet("padding: 0px;")
    return button


def _rail_tool_section(widgets: list[QWidget], *, more: QPushButton | None = None) -> QWidget:
    """One unlabeled block of the left tool rail, two buttons across."""
    box = QWidget()
    box.setFixedWidth(_rail_content_width())
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(0)
    grid = QGridLayout()
    _configure_rail_grid(grid)
    for index, widget in enumerate(widgets):
        grid.addWidget(widget, index // _RAIL_COLUMNS, index % _RAIL_COLUMNS)
    if more is not None:
        row = (len(widgets) + _RAIL_COLUMNS - 1) // _RAIL_COLUMNS
        grid.addWidget(more, row, 0, 1, _RAIL_COLUMNS)
    lay.addLayout(grid)
    return box


def _status_message_font() -> QFont:
    """Same point size as the main-window status line."""
    app = QApplication.instance()
    font = QFont(app.font() if app is not None else QFont())
    point = font.pointSize()
    if point <= 0:
        point = default_app_font_pt()
    font.setPointSize(status_bar_font_pt(point))
    return font


def _workspace_status_bar_height() -> int:
    """Main-window status row: the message line plus 6px above and below."""
    return QFontMetrics(_status_message_font()).height() + 12


def _apply_status_bar_metrics(bar: QStatusBar) -> None:
    """Match the main-window status row and leave the right edge for one widget."""
    bar.setFixedHeight(_workspace_status_bar_height())
    bar.setFont(_status_message_font())
    layout = bar.layout()
    if layout is not None:
        layout.setContentsMargins(8, 0, 0, 0)
        layout.setSpacing(6)


def _glyph_tool_button(
    icon: QIcon,
    tip: str,
    *,
    checkable: bool = True,
    size: int = _RAIL_BUTTON_SIZE,
) -> QPushButton:
    b = QPushButton()
    b.setIcon(icon)
    b.setIconSize(QSize(size - 6, size - 6))
    b.setFixedSize(size, size)
    b.setCheckable(checkable)
    b.setToolTip(tip)
    b.setStyleSheet("padding: 0px;")
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


def _standard_key_shortcuts(standard_key) -> list[QKeySequence]:
    """Every binding Qt uses for a standard key on this platform."""
    bindings = list(QKeySequence.keyBindings(standard_key))
    if bindings:
        return bindings
    return [QKeySequence(standard_key)]


def _shortcut_texts(action: QAction) -> set[str]:
    texts: set[str] = set()
    for sequence in action.shortcuts():
        text = sequence.toString(QKeySequence.PortableText).strip()
        if text:
            texts.add(text)
    return texts


# Table commands the sketcher replaces while its window is active.
_SKETCH_EDIT_PARENT_ACTION_IDS = frozenset(
    {
        "edit.undo",
        "edit.redo",
        "edit.copy",
        "edit.paste",
        "edit.delete_selection",
    }
)


class _ParentHotkeyClaim:
    """How many open sketchers are holding one table shortcut off."""

    __slots__ = ("count", "was_enabled")

    def __init__(self, was_enabled: bool) -> None:
        self.count = 1
        self.was_enabled = was_enabled


# id(QAction) -> claim. Shared so two sketchers do not re-enable each other's keys.
_PARENT_HOTKEY_CLAIMS: dict[int, _ParentHotkeyClaim] = {}


class SketcherDialog(QDialog):
    def __init__(
        self,
        parent=None,
        initial_mol: Chem.Mol | None = None,
        *,
        element_symbols: list[str] | None = None,
        source_oid: int | None = None,
        app=None,
    ):
        super().__init__(parent)
        self.parent_app = app if app is not None else parent
        self._embedded = False
        if initial_mol is not None and not isinstance(initial_mol, Chem.Mol):
            initial_mol = None
        self._initial_mol = initial_mol
        self._source_oid = int(source_oid) if source_oid is not None else None
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
        export_table_act = QAction("Add to Table", self)
        export_table_act.triggered.connect(self._add_to_table)
        export_table_act.setShortcut(QKeySequence("Ctrl+Shift+T"))
        export_table_act.setShortcutContext(Qt.WindowShortcut)
        export_table_act.setToolTip("Add the sketch to the table as new rows.")
        file_menu.addAction(export_table_act)
        self._act_add_to_table = export_table_act
        self._act_update_table_entry = QAction("Update Table Entry", self)
        self._act_update_table_entry.setToolTip(
            "Replace the table row this sketch was opened from."
        )
        self._act_update_table_entry.triggered.connect(self._update_table_entry)
        self._act_update_table_entry.setVisible(self._source_oid is not None)
        file_menu.addAction(self._act_update_table_entry)
        file_menu.aboutToShow.connect(self._sync_table_entry_action)

        edit_menu = menubar.addMenu("Edit")
        undo_act = QAction("Undo", self)
        undo_act.setShortcuts(_standard_key_shortcuts(QKeySequence.Undo))
        undo_act.setShortcutContext(Qt.WindowShortcut)
        undo_act.setToolTip("Undo the last sketch change (Ctrl+Z).")
        undo_act.triggered.connect(self._undo_sketch)
        edit_menu.addAction(undo_act)
        redo_act = QAction("Redo", self)
        redo_act.setShortcuts(_standard_key_shortcuts(QKeySequence.Redo))
        redo_act.setShortcutContext(Qt.WindowShortcut)
        redo_act.setToolTip("Redo the last undone sketch change (Ctrl+Y / Ctrl+Shift+Z).")
        redo_act.triggered.connect(self._redo_sketch)
        edit_menu.addAction(redo_act)
        self._act_edit_undo = undo_act
        self._act_edit_redo = redo_act
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

        self.tb_groups = _glyph_tool_button(
            mode_text_icon(),
            "Contract a terminal group the Structure column also contracts "
            "(CF3, CN, N3, CO2H, SO3H, PO3H2, OMe, Boc). "
            "Click an atom, or click empty canvas to place the label.",
            checkable=False,
        )
        self.tb_groups.clicked.connect(self._show_group_menu)

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

        self._act_canvas_clear = QAction("Clear Sketch", self)
        self._act_canvas_clear.setToolTip(
            "Remove every atom and bond from the canvas (Ctrl+Shift+K)."
        )
        self._act_canvas_clear.triggered.connect(self._clear_sketch)
        self._act_canvas_clear.setShortcut(QKeySequence("Ctrl+Shift+K"))
        self._act_canvas_clear.setShortcutContext(Qt.WindowShortcut)
        edit_menu.addMenu(self._build_copy_as_menu())
        edit_menu.addSeparator()
        edit_menu.addAction(self._act_canvas_clear)

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
        self._act_original_size = QAction("Original size", self)
        self._act_original_size.setToolTip(
            "Restore the size this structure had when it was opened from the table."
        )
        self._act_original_size.triggered.connect(self._on_view_original_size)
        self._act_original_size.setEnabled(False)
        view_menu.addAction(self._act_original_size)
        view_menu.aboutToShow.connect(self._sync_original_size_action)
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

        settings_menu = menubar.addMenu("Settings")
        customize_el_act = QAction("Customize Elements", self)
        customize_el_act.setToolTip(
            "Choose which element buttons appear in the left element panel."
        )
        customize_el_act.triggered.connect(self._customize_elements)
        settings_menu.addAction(customize_el_act)

        l.setMenuBar(menubar)
        self._settings_menu_action = settings_menu.menuAction()

        # Tools live in the left rail, under the menu. The canvas starts beside that rail.
        self.tb_clear = _glyph_tool_button(
            clear_sketch_icon(),
            "Clear the sketch (also in the right-click empty-canvas menu).",
            checkable=False,
        )
        self.tb_clear.clicked.connect(self._clear_sketch)
        self.tb_chain = _glyph_tool_button(
            mode_chain_icon(),
            "Chain: drag a zigzag carbon chain on the 30° grid. A short click places one atom.",
        )
        self.tb_chain.toggled.connect(self._toggle_chain)

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
            return btn

        self.bond_plain = _add_bond_tool(
            bond_plain_icon(), "Single bond (plain). Key 1.", 1, BOND_STEREO_PLAIN, checked=True
        )
        self.bond_double = _add_bond_tool(
            bond_double_icon(), "Double bond. Key 2.", 2, BOND_STEREO_PLAIN
        )
        self.bond_triple = _add_bond_tool(
            bond_triple_icon(), "Triple bond. Key 3.", 3, BOND_STEREO_PLAIN
        )
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
            "Dative bond, drawn dashed from donor to acceptor.",
            1,
            BOND_STEREO_DATIVE,
        )
        self.tb_bond = None

        self._ring_button_group = QButtonGroup(self)
        self._ring_button_group.setExclusive(False)
        self._ring_btn_by_key: dict[str, QPushButton] = {}
        self._rail_ring_keys = tuple(key for key, *_rest in TOOLBAR_RING_TEMPLATES)
        rail_rings = [self._new_ring_button(key) for key in self._rail_ring_keys]
        self.tb_rings = _rail_more_button(
            "More…",
            "Other ring templates, including heterocycles and fused systems.",
        )
        self.tb_rings.clicked.connect(self._show_ring_palette)
        self._ring_palette = QFrame(self, Qt.Popup)
        self._ring_palette.setFrameShape(QFrame.StyledPanel)
        ring_grid = QGridLayout(self._ring_palette)
        ring_grid.setContentsMargins(8, 8, 8, 8)
        ring_grid.setHorizontalSpacing(4)
        ring_grid.setVerticalSpacing(4)
        ring_columns = 6
        ring_row = 0
        for title, names in self._ring_palette_groups():
            header = QLabel(title)
            header.setStyleSheet("font-weight: 600;")
            ring_grid.addWidget(header, ring_row, 0, 1, ring_columns)
            ring_row += 1
            for index, key in enumerate(names):
                button = self._new_ring_button(key)
                ring_grid.addWidget(button, ring_row + index // ring_columns, index % ring_columns)
            ring_row += (len(names) + ring_columns - 1) // ring_columns

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

        self.tb_3d = _glyph_tool_button(
            view_3d_icon(),
            "Show a live 3D preview of the sketch beside the canvas.",
        )
        self.tb_3d.setChecked(False)
        self.tb_3d.toggled.connect(self._toggle_3d_view)
        self.tb_rxn_arrow = _glyph_tool_button(
            reaction_arrow_icon(),
            "Reaction arrow: drag to draw. Fragments on the tail are reactants; "
            "fragments on the head are products. Add to Table adds Reaction SMARTS "
            "and renders the 2D scheme. Hold Shift to snap.",
        )
        self.tb_rxn_arrow.toggled.connect(self._toggle_reaction_arrow)

        health = max(16, _workspace_status_bar_height() - 6)
        self.tb_structure_status = _glyph_tool_button(
            status_ok_icon(health),
            "Structure health: click for valence and stereochemistry issues.",
            checkable=False,
            size=health,
        )
        self.tb_structure_status.setIconSize(QSize(health - 2, health - 2))
        self.tb_structure_status.setStyleSheet(
            "QPushButton { padding: 0px; border: none; background: transparent; }"
            "QPushButton:hover { background: palette(midlight); border-radius: 3px; }"
        )
        self.tb_structure_status.clicked.connect(self._on_structure_status_clicked)
        self._top_toolbar = None
        toolbar_outer = QVBoxLayout()
        toolbar_outer.setSpacing(4)
        toolbar_outer.setContentsMargins(_RAIL_MARGIN_X, 4, _RAIL_MARGIN_X, 6)
        toolbar_outer.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self._rail_blocks: list[QWidget] = []
        sections: tuple[tuple[list[QWidget], QPushButton | None], ...] = (
            (
                [
                    self.tb_draw,
                    self.tb_erase,
                    self.select_btn,
                    self.lasso_btn,
                    self.tb_text,
                    self.tb_groups,
                    self.tb_clear,
                    self.tb_chain,
                ],
                None,
            ),
            (
                [
                    self.bond_plain,
                    self.bond_double,
                    self.bond_triple,
                    self.bond_wedge,
                    self.bond_hash,
                    self.bond_wavy,
                    self.bond_dative,
                ],
                None,
            ),
            (rail_rings, self.tb_rings),
            (
                [self.charge_plus, self.charge_minus, self.tb_3d, self.tb_rxn_arrow],
                None,
            ),
        )
        for widgets, more in sections:
            if self._rail_blocks:
                toolbar_outer.addWidget(_toolbar_hsep())
            block = _rail_tool_section(widgets, more=more)
            self._rail_blocks.append(block)
            toolbar_outer.addWidget(block)

        # Elements, then a sunken line, then * / ? / R.
        self.element_buttons: list[QPushButton] = []
        self._element_btn_by_symbol: dict[str, QPushButton] = {}
        self._element_button_group = QButtonGroup(self)
        self._element_button_group.setExclusive(True)
        self._el_btn_font = QFont("Sans", 9)
        self._el_btn_font.setStyleHint(QFont.SansSerif)
        self._el_ncols = _RAIL_COLUMNS
        elements_page = QWidget()
        elements_page.setFixedWidth(_rail_content_width())
        elements_lay = QVBoxLayout(elements_page)
        elements_lay.setContentsMargins(0, 0, 0, 0)
        elements_lay.setSpacing(0)
        self._el_grid = QGridLayout()
        _configure_rail_grid(self._el_grid)
        elements_lay.addLayout(self._el_grid)
        toolbar_outer.addWidget(_toolbar_hsep())
        self._rail_blocks.append(elements_page)
        toolbar_outer.addWidget(elements_page)

        custom_page = QWidget()
        custom_page.setFixedWidth(_rail_content_width())
        custom_lay = QVBoxLayout(custom_page)
        custom_lay.setContentsMargins(0, 0, 0, 0)
        custom_lay.setSpacing(0)
        self._custom_grid = QGridLayout()
        _configure_rail_grid(self._custom_grid)
        custom_lay.addLayout(self._custom_grid)
        toolbar_outer.addWidget(_toolbar_hsep())
        self._rail_blocks.append(custom_page)
        toolbar_outer.addWidget(custom_page)
        toolbar_outer.addStretch(1)

        self._any_element_symbol: str | None = None
        self.tb_wildcard = QPushButton("*")
        self.tb_any_element = QPushButton("?")
        self.tb_r1 = QPushButton("R1")
        self.tb_r2 = QPushButton("R2")
        self._rgroup_buttons = {1: self.tb_r1, 2: self.tb_r2}
        initial_els = (
            list(self._element_symbols_override)
            if self._element_symbols_override is not None
            else load_toolbar_element_symbols()
        )
        self._populate_element_toolbar(initial_els)

        rail_page = QWidget()
        rail_page.setLayout(toolbar_outer)
        rail_scroll = QScrollArea()
        rail_scroll.setWidgetResizable(True)
        rail_scroll.setFrameShape(QFrame.NoFrame)
        rail_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        rail_scroll.setWidget(rail_page)
        rail_scroll.setStyleSheet("QScrollBar:vertical { width: 8px; margin: 0px; }")

        main_h = QHBoxLayout()
        main_h.setContentsMargins(0, 0, 0, 0)
        main_h.setSpacing(0)

        panel_layout = QVBoxLayout()
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)
        panel_layout.addWidget(rail_scroll, 1)

        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("SketcherToolbarPanel")
        toolbar_widget.setStyleSheet(
            "#SketcherToolbarPanel {"
            " background-color: palette(window);"
            " border: none;"
            " border-right: 1px solid palette(mid);"
            "}"
            "QPushButton:checked {"
            " background-color: #d6e6f8;"
            " border: 1px solid #6f93c4;"
            " border-radius: 3px;"
            "}"
        )
        toolbar_widget.setFixedWidth(_rail_panel_width())
        toolbar_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        toolbar_widget.setLayout(panel_layout)
        self._toolbar_panel = toolbar_widget
        main_h.addWidget(toolbar_widget, 0)

        self.canvas = SketchWidget(self)
        self.canvas.select_mode = False
        self.canvas.setToolTip(
            "Right-click empty canvas for templates, modes, cleanup, and zoom-related commands in the menu bar."
        )
        self.canvas.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
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
        self._canvas_splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        main_h.addWidget(self._canvas_splitter, 1)
        self._body_row = main_h
        l.addLayout(main_h, 1)

        self._status_bar = QStatusBar(self)
        self._status_bar.setObjectName("SketcherStatusBar")
        self._status_bar.setSizeGripEnabled(False)
        self._status_bar.setStyleSheet(
            "#SketcherStatusBar {"
            " background-color: palette(window);"
            " border-top: 1px solid palette(mid);"
            "}"
            "#SketcherStatusBar::item { border: none; }"
        )
        _apply_status_bar_metrics(self._status_bar)
        self._status_bar.addPermanentWidget(self.tb_structure_status)
        self._status_bar.showMessage("Ready.")
        l.addWidget(self._status_bar)

        self._3d_refresh_timer = QTimer(self)
        self._3d_refresh_timer.setSingleShot(True)
        self._3d_refresh_timer.setInterval(350)
        self._3d_refresh_timer.timeout.connect(self._refresh_3d_view_now)

        self.canvas.sketchChanged.connect(self._update_sketch_status)
        self.canvas.statusMessage.connect(self.show_sketch_status)
        self.canvas.sketchChanged.connect(self._schedule_3d_refresh)
        self.tb_erase.blockSignals(True)
        self.tb_erase.setChecked(False)
        self.tb_erase.blockSignals(False)
        if self._initial_mol is not None:
            self.select_btn.blockSignals(True)
            self.select_btn.setChecked(True)
            self.select_btn.blockSignals(False)
            self._toggle_select(True)
        else:
            self._enter_draw_mode()
        self._update_sketch_status()

        if self._initial_mol is not None:
            QTimer.singleShot(0, self._apply_initial_mol)

        self._sync_mode_menu_checks()

        esc = QShortcut(QKeySequence(Qt.Key_Escape), self)
        esc.setContext(Qt.WidgetWithChildrenShortcut)
        esc.activated.connect(self._escape_asks_close)

        self._parent_hotkeys_blocked = False
        self._claimed_parent_actions: list[QAction] = []
        self._host_window_edit_keys = False
        self._sketch_key_filters_installed = False
        make_window_resizable(self)

    @staticmethod
    def _is_sketch_delete_key(event) -> bool:
        if event.key() not in (Qt.Key_Delete, Qt.Key_Backspace):
            return False
        mods = event.modifiers()
        return not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))

    def _host_hotkey_actions(self) -> dict:
        """Table hotkey map on the nearest ancestor, or on the hosting application."""
        hosts: list[QWidget] = []
        seen: set[int] = set()
        widget = self.parent()
        while widget is not None and id(widget) not in seen:
            seen.add(id(widget))
            hosts.append(widget)
            widget = widget.parent()
        app = getattr(self, "parent_app", None)
        if isinstance(app, QWidget) and id(app) not in seen:
            hosts.append(app)
        for host in hosts:
            actions = getattr(host, "_hotkey_actions", None)
            if isinstance(actions, dict) and actions:
                return actions
        return {}

    def _conflicting_parent_actions(self) -> list[QAction]:
        """Table shortcuts that would steal undo, redo, or another sketch edit key."""
        host_actions = self._host_hotkey_actions()
        if not host_actions:
            return []
        sketch_keys: set[str] = set()
        for action in self.findChildren(QAction):
            sketch_keys.update(_shortcut_texts(action))
        found: list[QAction] = []
        seen: set[int] = set()
        for action_id, action in host_actions.items():
            if not isinstance(action, QAction) or id(action) in seen:
                continue
            overlaps = bool(_shortcut_texts(action) & sketch_keys)
            edit_key = action_id in _SKETCH_EDIT_PARENT_ACTION_IDS
            if self._host_window_edit_keys:
                overlaps = False
            if edit_key or overlaps:
                seen.add(id(action))
                found.append(action)
        return found

    def _sketch_owns_edit_hotkeys(self) -> bool:
        """Sketch edit keys apply while this window, or the window hosting an embed, is active.

        Other application shortcuts stay enabled. Only undo, redo, copy, paste,
        delete, and keys the sketch itself uses are held off the table.
        """
        if not self.isVisible():
            return False
        if self._embedded and self._host_window_edit_keys:
            window = self.window()
            return window is not None and bool(window.isActiveWindow())
        if self._embedded:
            focus = QApplication.focusWidget()
            return focus is not None and (focus is self or self.isAncestorOf(focus))
        return self.isActiveWindow()

    def _claim_parent_edit_hotkeys(self) -> None:
        if self._parent_hotkeys_blocked:
            return
        claimed: list[QAction] = []
        for action in self._conflicting_parent_actions():
            key = id(action)
            claim = _PARENT_HOTKEY_CLAIMS.get(key)
            if claim is None:
                _PARENT_HOTKEY_CLAIMS[key] = _ParentHotkeyClaim(bool(action.isEnabled()))
                action.setEnabled(False)
            else:
                claim.count += 1
            claimed.append(action)
        self._claimed_parent_actions = claimed
        self._parent_hotkeys_blocked = True

    def _release_parent_edit_hotkeys(self) -> None:
        if not self._parent_hotkeys_blocked:
            return
        for action in self._claimed_parent_actions:
            claim = _PARENT_HOTKEY_CLAIMS.get(id(action))
            if claim is None:
                continue
            claim.count -= 1
            if claim.count <= 0:
                _PARENT_HOTKEY_CLAIMS.pop(id(action), None)
                if claim.was_enabled:
                    action.setEnabled(True)
        self._claimed_parent_actions = []
        self._parent_hotkeys_blocked = False

    def _sync_parent_edit_hotkeys(self) -> None:
        if self._sketch_owns_edit_hotkeys():
            self._claim_parent_edit_hotkeys()
        else:
            self._release_parent_edit_hotkeys()

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
        if self._embedded and event.type() in (QEvent.FocusIn, QEvent.FocusOut):
            QTimer.singleShot(0, self._sync_parent_edit_hotkeys)
        if not self.isVisible():
            return False
        if event.type() == QEvent.ShortcutOverride and self._is_sketch_delete_key(event):
            event.accept()
            return False
        if event.type() == QEvent.KeyPress and self._is_sketch_delete_key(event):
            self._on_edit_delete()
            return True
        return False

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.ActivationChange:
            self._sync_parent_edit_hotkeys()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._sync_parent_edit_hotkeys()
        self._install_sketch_key_filters()

    def hideEvent(self, event) -> None:
        self._release_parent_edit_hotkeys()
        self._remove_sketch_key_filters()
        super().hideEvent(event)

    def _sync_mode_menu_checks(self) -> None:
        if not getattr(self, "_act_mode_erase", None):
            return
        rxn_on = bool(
            getattr(self, "tb_rxn_arrow", None) is not None and self.tb_rxn_arrow.isChecked()
        )
        chain_on = bool(getattr(self, "tb_chain", None) is not None and self.tb_chain.isChecked())
        draw_on = (
            not self.tb_erase.isChecked()
            and not self.select_btn.isChecked()
            and not self.lasso_btn.isChecked()
            and not self.tb_text.isChecked()
            and not rxn_on
            and not chain_on
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

    def _sync_original_size_action(self) -> None:
        action = getattr(self, "_act_original_size", None)
        if action is not None:
            action.setEnabled(self.canvas.has_opened_render())

    def _on_view_original_size(self) -> None:
        if self.canvas.restore_opened_render():
            self.show_sketch_status("Restored the size from when this structure was opened.")
        else:
            self.show_sketch_status("Open a structure from the table to restore its original size.")
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

    def _new_ring_button(self, key: str) -> QPushButton:
        """Checkable button whose picture is the heavy-atom graph *key* places."""
        if key in SKETCH_RING_TEMPLATES:
            _count, elements, orders = SKETCH_RING_TEMPLATES[key]
            icon = ring_template_icon(elements, orders)
            n_atoms = len(elements)
        else:
            graph = fused_template(key)
            if graph is None:
                icon = ring_icon(6, aromatic=True)
                n_atoms = 6
            else:
                icon = fused_ring_icon(graph)
                n_atoms = len(graph.elements)
        button = _glyph_tool_button(icon, f"{key} ({n_atoms} atoms)")
        button.clicked.connect(
            lambda checked=False, name=key: self._on_ring_tool_clicked(name, checked)
        )
        self._ring_button_group.addButton(button)
        self._ring_btn_by_key[key] = button
        return button

    def _ring_palette_groups(self) -> list[tuple[str, list[str]]]:
        """Ring templates that are not already buttons on the left rail."""
        on_rail = set(getattr(self, "_rail_ring_keys", ()))
        buckets: dict[str, list[str]] = {
            "Carbocycles": [],
            "Nitrogen": [],
            "Oxygen": [],
            "Sulfur": [],
        }
        for name, (_count, elements, _orders) in SKETCH_RING_TEMPLATES.items():
            if name in on_rail:
                continue
            present = set(elements)
            if present <= {"C"}:
                buckets["Carbocycles"].append(name)
            elif "S" in present:
                buckets["Sulfur"].append(name)
            elif "O" in present and "N" not in present:
                buckets["Oxygen"].append(name)
            else:
                buckets["Nitrogen"].append(name)
        groups = [(title, names) for title, names in buckets.items() if names]
        fused = [name for name in FUSED_TEMPLATE_SMILES if name not in on_rail]
        if fused:
            groups.append(("Fused", fused))
        return groups

    def _popup_under(self, palette: QFrame, button: QPushButton) -> None:
        palette.adjustSize()
        palette.move(button.mapToGlobal(QPoint(0, button.height())))
        palette.show()

    def _show_bond_palette(self) -> None:
        palette = getattr(self, "_bond_palette", None)
        button = getattr(self, "tb_bond", None)
        if palette is None or button is None:
            return
        self._popup_under(palette, button)

    def _show_ring_palette(self) -> None:
        self._popup_under(self._ring_palette, self.tb_rings)

    def _show_more_elements(self) -> None:
        menu = QMenu(self)
        for element in getattr(self, "_more_element_symbols", []):
            action = menu.addAction(element)
            action.triggered.connect(
                lambda _checked=False, el=element: self._on_element_tool_clicked(el, True)
            )
        button = getattr(self, "_more_elements_btn", None)
        if button is None:
            menu.exec_(QCursor.pos())
            return
        menu.exec_(button.mapToGlobal(QPoint(0, button.height())))

    def _toggle_chain(self, checked: bool) -> None:
        if checked:
            self._leave_special_modes_for_drawing(keep_chain=True)
            self.canvas.chain_mode = True
            self.canvas.active_template = None
            self._uncheck_ring_buttons()
            self.canvas.place_element = "C"
            button = self._element_btn_by_symbol.get("C")
            if button is not None:
                button.setChecked(True)
            self.canvas.setCursor(Qt.CrossCursor)
            self.canvas.setFocus()
        else:
            self.canvas.chain_mode = False
            self.canvas._chain_preview = []
            self.canvas._chain_press = None
            if (
                not self.tb_erase.isChecked()
                and not self._any_select_tool_on()
                and not self.tb_text.isChecked()
            ):
                self._enter_draw_mode()
                return
        self.canvas.update()
        self._sync_mode_menu_checks()

    def show_sketch_status(self, message: str) -> None:
        """Show one line in the sketcher status bar, like the main window status line."""
        bar = getattr(self, "_status_bar", None)
        if bar is None:
            return
        text = (message or "").strip() or "Ready."
        bar.showMessage(text)

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
            deleted = self.canvas._handle_delete_key()
        finally:
            self._edit_delete_busy = False
        if not deleted:
            self.show_sketch_status("Nothing to delete.")

    def _shortcut_copy_selection(self) -> None:
        self.canvas.copy_selection_to_clipboard()

    def _shortcut_paste_selection(self) -> None:
        anchor = self.canvas.mapFromGlobal(QCursor.pos())
        self.canvas.paste_from_clipboard(anchor)

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

    def _leave_special_modes_for_drawing(
        self, *, reset_bond: bool = True, keep_chain: bool = False
    ) -> None:
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
        if not keep_chain:
            self.canvas.chain_mode = False
            self.canvas._chain_preview = []
            self.canvas._chain_press = None
            if getattr(self, "tb_chain", None) is not None and self.tb_chain.isChecked():
                self.tb_chain.blockSignals(True)
                self.tb_chain.setChecked(False)
                self.tb_chain.blockSignals(False)
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
            if getattr(self, "tb_chain", None) is not None and self.tb_chain.isChecked():
                self.tb_chain.blockSignals(True)
                self.tb_chain.setChecked(False)
                self.tb_chain.blockSignals(False)
            self.canvas.chain_mode = False
            self.canvas._chain_preview = []
            self.canvas._chain_press = None
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
        active_icon = None
        for btn, o, s in getattr(self, "_bond_tool_buttons", []):
            checked = o == order and s == (stereo if order == 1 else BOND_STEREO_PLAIN)
            btn.blockSignals(True)
            btn.setChecked(checked)
            btn.blockSignals(False)
            if checked:
                active_icon = btn.icon()
        if active_icon is not None and getattr(self, "tb_bond", None) is not None:
            self.tb_bond.setIcon(active_icon)
        if getattr(self, "_bond_palette", None) is not None:
            self._bond_palette.hide()

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
        """Remove element buttons so the rail can be rebuilt."""
        while self._el_grid.count():
            item = self._el_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, QPushButton) and widget.property("sketch_element"):
                self._element_button_group.removeButton(widget)
            widget.deleteLater()
        self.element_buttons.clear()
        self._element_btn_by_symbol.clear()

    def _place_custom_rail(self) -> None:
        """Put *, ?, R1, R2, and Rn below the element buttons."""
        while self._custom_grid.count():
            item = self._custom_grid.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        btn_font = self._el_btn_font
        self.tb_wildcard.setCheckable(True)
        self.tb_wildcard.setFont(btn_font)
        self.tb_wildcard.setToolTip(
            "Wildcard atom: SMARTS query over selected elements. Right-click a wildcard to edit choices."
        )
        self.tb_wildcard.setFixedSize(_RAIL_BUTTON_SIZE, _RAIL_BUTTON_SIZE)
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
        self.tb_any_element.setFixedSize(_RAIL_BUTTON_SIZE, _RAIL_BUTTON_SIZE)
        self.tb_any_element.setStyleSheet("padding: 0px;")
        try:
            self.tb_any_element.clicked.disconnect()
        except TypeError:
            pass
        self.tb_any_element.clicked.connect(self._on_any_element_tool_clicked)

        r_font = QFont(btn_font)
        r_font.setPointSize(7)
        for label, button in self._rgroup_buttons.items():
            button.setCheckable(True)
            button.setFont(r_font)
            button.setFixedSize(_RAIL_BUTTON_SIZE, _RAIL_BUTTON_SIZE)
            button.setStyleSheet("padding: 0px;")
            button.setToolTip(
                f"R{label}: click an atom to attach this point for R-group enumeration. "
                f"Click empty canvas to place it alone. Exports as [*:{label}]."
            )
            try:
                button.toggled.disconnect()
            except TypeError:
                pass
            button.toggled.connect(lambda on, lab=label: self._on_rgroup_tool_toggled(lab, on))

        if getattr(self, "tb_rn", None) is None:
            self.tb_rn = QPushButton("Rn")
            self.tb_rn.setFont(r_font)
            self.tb_rn.setFixedSize(_RAIL_BUTTON_SIZE, _RAIL_BUTTON_SIZE)
            self.tb_rn.setStyleSheet("padding: 0px;")
            self.tb_rn.setToolTip("Choose Rn (R3, R4, …). Exports as [*:n].")
            self.tb_rn.clicked.connect(self._on_rn_clicked)
        self._custom_grid.addWidget(self.tb_wildcard, 0, 0)
        self._custom_grid.addWidget(self.tb_any_element, 0, 1)
        self._custom_grid.addWidget(self.tb_r1, 1, 0)
        self._custom_grid.addWidget(self.tb_r2, 1, 1)
        self._custom_grid.addWidget(self.tb_rn, 2, 0)

    def _populate_element_toolbar(self, symbols: list[str]) -> None:
        """Short element rail. Other saved symbols sit under More. * / ? / R stay below a sunken line."""
        self._visible_element_symbols = list(symbols)
        self._clear_element_grid_widgets()
        el_ncols = self._el_ncols
        btn_font = self._el_btn_font
        rail = list(SKETCH_RAIL_ELEMENTS)
        for i, el in enumerate(rail):
            button = QPushButton(el)
            button.setCheckable(True)
            button.setProperty("sketch_element", el)
            button.setFont(btn_font)
            button.setFixedSize(_RAIL_BUTTON_SIZE, _RAIL_BUTTON_SIZE)
            button.setStyleSheet("padding: 0px;")
            row, col = i // el_ncols, i % el_ncols
            if el == "C":
                button.setToolTip(
                    "Carbon: click empty space to place C; drag to draw a bond; "
                    "click any other atom to replace it with carbon."
                )
            else:
                button.setToolTip(f"Place {el}.")
            button.clicked.connect(lambda checked, e=el: self._on_element_tool_clicked(e, checked))
            self._element_button_group.addButton(button)
            self._el_grid.addWidget(button, row, col)
            self.element_buttons.append(button)
            self._element_btn_by_symbol[el] = button
        grid_row = (len(rail) + el_ncols - 1) // el_ncols
        rail_set = set(rail)
        self._more_element_symbols = [s for s in symbols if s not in rail_set]
        if self._more_element_symbols:
            self._more_elements_btn = _rail_more_button(
                "More…",
                "Other elements from Customize Elements, including isotopes.",
            )
            self._more_elements_btn.clicked.connect(self._show_more_elements)
            self._el_grid.addWidget(self._more_elements_btn, grid_row, 0, 1, el_ncols)

        self._place_custom_rail()

        # Drop place-tool if the selected element was removed from the panel.
        place = getattr(self.canvas, "place_element", None) if hasattr(self, "canvas") else None
        if (
            place
            and place not in self._element_btn_by_symbol
            and place != WILDCARD_ELEMENT
            and not is_rgroup_element(place)
        ):
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

    def install_chemistry_menu(self) -> None:
        """Add Chemistry between View and Settings. The Design Studio calls this."""
        bar = self.layout().menuBar() if self.layout() is not None else None
        if bar is None:
            return
        if any(action.text() == "Chemistry" for action in bar.actions()):
            return
        menu = QMenu("Chemistry", bar)
        action = QAction("Bioisosteric Replacement…", self)
        action.setToolTip(
            "Replace the selected atoms with one bioisostere. The rest of the sketch is kept."
        )
        action.triggered.connect(self._open_bioisostere_replacement)
        menu.addAction(action)
        settings = getattr(self, "_settings_menu_action", None)
        if settings is not None:
            bar.insertMenu(settings, menu)
        else:
            bar.addMenu(menu)

    def _open_bioisostere_replacement(self) -> None:
        """Apply one bioisostere to the atoms selected on the canvas."""
        selected = self.canvas._atoms_for_selection_move()
        if not selected:
            QMessageBox.information(
                self,
                "Bioisosteric Replacement",
                "Select one or more atoms to replace.",
            )
            return
        node_ids = {int(node["id"]) for node in self.canvas.nodes}
        built = self.canvas._mol_from_node_ids(node_ids, return_idmap=True)
        if not isinstance(built, tuple):
            QMessageBox.warning(
                self,
                "Bioisosteric Replacement",
                "The sketch could not be read.",
            )
            return
        mol, idmap = built
        atom_indices = [idmap[node_id] for node_id in selected if node_id in idmap]
        if not atom_indices:
            QMessageBox.information(
                self,
                "Bioisosteric Replacement",
                "Select one or more atoms to replace.",
            )
            return
        from ...chem.bioisosteres import matching_bioisosteres

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            options = matching_bioisosteres(mol, atom_indices)
        finally:
            QApplication.restoreOverrideCursor()
        if not options:
            QMessageBox.information(
                self,
                "Bioisosteric Replacement",
                "None of the bioisosteres match the selected atoms.",
            )
            return
        from .bioisostere_dialog import BioisostereReplacementDialog

        dialog = BioisostereReplacementDialog(options, self)
        if dialog.exec_() != QDialog.Accepted:
            return
        smiles = dialog.chosen_smiles()
        product = Chem.MolFromSmiles(smiles) if smiles else None
        if product is None:
            return
        self.load_structure_from_mol(product, confirm_if_nonempty=False)
        self.show_sketch_status("Replaced the selection with a bioisostere.")

    def _open_physical_properties(self) -> None:
        """Open (or raise) the modeless Physical Properties window."""
        from .physical_properties import SketchPhysicalPropertiesDialog

        dlg = self._phys_props_dlg
        if dlg is not None:
            try:
                dlg.objectName()
            except RuntimeError:
                dlg = None
                self._phys_props_dlg = None
        if dlg is None:
            dlg = SketchPhysicalPropertiesDialog(self)
            self._phys_props_dlg = dlg
            dlg.destroyed.connect(self._forget_physical_properties)
            self.canvas.sketchChanged.connect(dlg.schedule_refresh)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        dlg.schedule_refresh()

    def _forget_physical_properties(self, *_args) -> None:
        self._phys_props_dlg = None

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
        self._uncheck_rgroup_buttons()
        self.canvas.place_element = None

    def _select_template_from_menu(self, name: str) -> None:
        if getattr(self, "_ring_palette", None) is not None:
            self._ring_palette.hide()
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

    def place_structure_status(self, bar: QStatusBar) -> None:
        """Pin the structure-health indicator on the right of another status bar."""
        home = getattr(self, "_status_bar", None)
        if home is not None and home is not bar:
            home.removeWidget(self.tb_structure_status)
        _apply_status_bar_metrics(bar)
        bar.setSizeGripEnabled(False)
        bar.addPermanentWidget(self.tb_structure_status)

    def set_embedded(self, embedded: bool) -> None:
        """Host this dialog inside another widget. Escape no longer closes it.

        Shortcuts stay inside the sketcher so they do not undo table edits while
        the canvas has focus.
        """
        self._embedded = bool(embedded)
        if not self._embedded:
            return
        self.setAttribute(Qt.WA_DeleteOnClose, False)
        self.setWindowFlags(Qt.Widget)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        status = getattr(self, "_status_bar", None)
        if status is not None:
            status.hide()
        # Window shortcuts follow the host window, so undo and the other sketch
        # keys work anywhere in the Design Studio, not only on the canvas.
        self._sync_parent_edit_hotkeys()

    def place_beside_canvas(self, widget: QWidget) -> None:
        """Put *widget* in the row under the top toolbar, to the right of the canvas."""
        row = getattr(self, "_body_row", None)
        if row is None:
            return
        widget.setParent(self)
        row.addWidget(widget, 0)

    def prefer_host_window_edit_keys(self) -> None:
        """Keep undo, copy, paste, and delete on the sketch while the host window is active.

        Application shortcuts that are not those edit keys stay enabled. A sketch
        tool that uses the same key, such as lasso on Ctrl+Shift+L, yields.
        """
        self._host_window_edit_keys = True
        self._yield_shortcuts_to_application()
        self._sync_parent_edit_hotkeys()

    def _yield_shortcuts_to_application(self) -> None:
        host_actions = self._host_hotkey_actions()
        protected: set[str] = set()
        for action_id, action in host_actions.items():
            if action_id in _SKETCH_EDIT_PARENT_ACTION_IDS or not isinstance(action, QAction):
                continue
            protected.update(_shortcut_texts(action))
        if not protected:
            return
        for action in self.findChildren(QAction):
            keys = _shortcut_texts(action)
            if keys and keys <= protected:
                action.setShortcuts([])

    def _escape_asks_close(self) -> None:
        if self._embedded:
            return
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
        self._uncheck_rgroup_buttons()
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
            self._uncheck_rgroup_buttons()
            self._leave_special_modes_for_drawing()
            self.canvas.active_template = None
            self._uncheck_ring_buttons()
            self.canvas.place_element = WILDCARD_ELEMENT
        elif self.canvas.place_element == WILDCARD_ELEMENT:
            self._select_default_element_tool()

    def _uncheck_rgroup_buttons(self) -> None:
        for button in getattr(self, "_rgroup_buttons", {}).values():
            button.blockSignals(True)
            button.setChecked(False)
            button.blockSignals(False)

    def _on_rgroup_tool_toggled(self, label: int, on: bool) -> None:
        element = rgroup_element(label)
        if on:
            for other, button in self._rgroup_buttons.items():
                if other == label:
                    continue
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            for button in self.element_buttons:
                button.blockSignals(True)
                button.setChecked(False)
                button.blockSignals(False)
            if getattr(self, "tb_wildcard", None) is not None:
                self.tb_wildcard.blockSignals(True)
                self.tb_wildcard.setChecked(False)
                self.tb_wildcard.blockSignals(False)
            self._uncheck_any_element_button()
            self._leave_special_modes_for_drawing()
            self.canvas.active_template = None
            self._uncheck_ring_buttons()
            self.canvas.place_element = element
            if getattr(self, "tb_rn", None) is not None:
                self.tb_rn.setText("Rn")
            return
        if self.canvas.place_element == element:
            self._select_default_element_tool()

    def _on_rn_clicked(self) -> None:
        number, ok = QInputDialog.getInt(self, "R-group", "R-group number:", 3, 1, 32)
        if not ok:
            return
        from .rgroups import rgroup_element

        self._uncheck_rgroup_buttons()
        self._uncheck_element_buttons_clear_place()
        self._leave_special_modes_for_drawing()
        self.canvas.active_template = None
        self._uncheck_ring_buttons()
        self.canvas.place_element = rgroup_element(number)
        self.tb_rn.setText(f"R{number}")
        self.canvas.setFocus()
        self._sync_mode_menu_checks()

    def _show_group_menu(self) -> None:
        menu = QMenu(self)
        menu.setToolTipsVisible(True)
        for name in TABLE_CONTRACTED_LABELS:
            action = menu.addAction(name)
            action.triggered.connect(lambda _checked=False, label=name: self._arm_group(label))
        menu.exec_(self.tb_groups.mapToGlobal(QPoint(0, self.tb_groups.height())))

    def _arm_group(self, label: str) -> None:
        self._leave_special_modes_for_drawing()
        self.canvas.arm_contracted_label(label)
        if self.canvas.armed_abbrev:
            self.canvas.setCursor(Qt.CrossCursor)
        self.canvas.setFocus()
        self._sync_mode_menu_checks()

    def _copy_molfile(self) -> None:
        self.canvas.copy_molblock_to_clipboard()

    def _copy_image(self) -> None:
        self.canvas.copy_depiction_png_to_clipboard()

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
        self._uncheck_rgroup_buttons()
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
        self._uncheck_rgroup_buttons()
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
        headers = [RXN_SMARTS_HEADER]
        annotation = self.canvas.reaction_annotation()
        cells = {RXN_SMARTS_HEADER: smarts}
        if annotation:
            headers.append(RXN_ANNOTATION_HEADER)
            cells[RXN_ANNOTATION_HEADER] = annotation
        self._ensure_table_columns(app, tuple(headers))
        oid = app.next_oid
        app.next_oid += 1
        app._table_model.append_row(oid, cells)
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
        icon_px = max(12, btn.iconSize().width())
        if level == "error":
            btn.setIcon(status_error_icon(icon_px))
            tip = "Structure has errors (click for details)."
        elif level == "caution":
            btn.setIcon(status_caution_icon(icon_px))
            tip = "Structure has warnings (click for details)."
        else:
            btn.setIcon(status_ok_icon(icon_px))
            tip = "No valence or stereochemistry issues flagged (click for details)."
        if msgs:
            tip = tip + "\n" + "\n".join(f"• {m}" for m in msgs[:6])
            if len(msgs) > 6:
                tip += f"\n• (+{len(msgs) - 6} more)"
        btn.setToolTip(tip)
        self._structure_status_level = level
        self._structure_status_messages = msgs

    def _on_structure_status_clicked(self) -> None:
        """Show a silent status dropdown from the health indicator, kept inside this window."""
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
        self._sync_original_size_action()

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

    def _build_copy_as_menu(self) -> QMenu:
        """Edit → Copy as: SMILES, SMARTS, molfile, and a depiction image."""
        menu = QMenu("Copy as", self)
        smiles = QAction("SMILES", self)
        smiles.setShortcut(QKeySequence("Ctrl+Shift+C"))
        smiles.setShortcutContext(Qt.WindowShortcut)
        smiles.setToolTip(
            "Copy the sketch as SMILES, or as reaction SMARTS when an arrow is present."
        )
        smiles.triggered.connect(self._copy_smiles)
        menu.addAction(smiles)
        selected = QAction("Selected SMILES", self)
        selected.setToolTip("Copy SMILES (or SMARTS) for the currently selected atoms and bonds.")
        selected.triggered.connect(self._copy_selected_smiles)
        menu.addAction(selected)
        smarts = QAction("SMARTS", self)
        smarts.setToolTip(
            "Copy the sketch as SMARTS, or as reaction SMARTS when an arrow is present."
        )
        smarts.triggered.connect(self._copy_smarts)
        menu.addAction(smarts)
        molfile = QAction("Molfile", self)
        molfile.setToolTip("Copy a molfile of the selection, or of the whole sketch.")
        molfile.triggered.connect(self._copy_molfile)
        menu.addAction(molfile)
        image = QAction("Image", self)
        image.setToolTip("Copy a PNG of the structure, without selection marks.")
        image.triggered.connect(self._copy_image)
        menu.addAction(image)
        return menu

    def _sync_table_entry_action(self) -> None:
        action = getattr(self, "_act_update_table_entry", None)
        if action is not None:
            action.setVisible(self._source_oid is not None)

    def set_source_entry(self, oid: int | None) -> None:
        """Remember the table row this sketch was opened from.

        File → Update Table Entry writes the sketch into that row. Without a source
        row, only Add to Table is available.
        """
        self._source_oid = int(oid) if oid is not None else None
        self._sync_table_entry_action()

    def load_structure_from_mol(
        self, mol: Chem.Mol | None, confirm_if_nonempty: bool = True
    ) -> bool:
        """Load an RDKit molecule into the canvas (optionally confirm if the sketch is non-empty)."""
        if mol is None or not isinstance(mol, Chem.Mol):
            return False
        try:
            m = Chem.Mol(mol)
        except Exception:
            QMessageBox.warning(self, "Sketcher", "Could not copy this structure for editing.")
            return False
        if confirm_if_nonempty and self.canvas.to_smiles().strip():
            res = QMessageBox.question(
                self,
                "Replace sketch",
                "Replace the current sketch with this structure?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if res != QMessageBox.Yes:
                return False
        c = self.canvas.rect().center()
        center = c if self.canvas.rect().width() > 8 and self.canvas.rect().height() > 8 else None
        if not self.canvas.load_from_rdkit_mol(m, center=center):
            QMessageBox.warning(
                self,
                "Sketcher",
                "Could not build a 2D layout for this structure. It may be unsupported or invalid.",
            )
            return False
        QTimer.singleShot(0, self._sync_original_size_action)
        self.tb_erase.blockSignals(True)
        self.tb_erase.setChecked(False)
        self.tb_erase.blockSignals(False)
        self.select_btn.blockSignals(True)
        self.select_btn.setChecked(True)
        self.select_btn.blockSignals(False)
        self._toggle_select(True)
        self._update_sketch_status()
        atoms = len(self.canvas.nodes)
        noun = "atom" if atoms == 1 else "atoms"
        self.show_sketch_status(f"Loaded {atoms} {noun}.")
        return True

    def _on_cleanup_layout(self) -> None:
        ok = self.canvas.cleanup_layout_2d()
        if not ok:
            QMessageBox.information(
                self,
                "Clean Up",
                "Could not re-layout the structure. Try fixing valence or connectivity issues first.",
            )
            return
        self.show_sketch_status("Cleaned up the structure.")
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
        self.show_sketch_status("Cleaned up the selection.")
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
            self.show_sketch_status("Copied SMILES.")
        else:
            self.show_sketch_status("Could not copy SMILES.")
            QMessageBox.warning(
                self,
                "Copy",
                "Could not copy — no valid SMILES/SMARTS for the sketch.",
            )

    def _copy_selected_smiles(self) -> None:
        if not self.canvas._atoms_for_selection_move():
            self.show_sketch_status("Select atoms to copy as SMILES.")
            return
        if self.canvas.copy_selected_as_smiles_to_clipboard():
            return
        self.show_sketch_status("Could not copy the selection as SMILES.")
        QMessageBox.warning(
            self,
            "Copy Selected as SMILES",
            "Could not copy — no valid SMILES/SMARTS for the selection.",
        )

    def _copy_smarts(self) -> None:
        smt = (self.canvas.to_reaction_smarts() or self.canvas.to_smarts() or "").strip()
        if smt:
            QApplication.clipboard().setText(smt)
            self.show_sketch_status("Copied SMARTS.")
        else:
            self.show_sketch_status("Could not copy SMARTS.")
            QMessageBox.warning(
                self,
                "Copy SMARTS",
                "Could not copy SMARTS (empty sketch or invalid structure).",
            )

    def _confirm_table_write(self, title: str, message: str) -> bool:
        """Ask before Add to Table or Update Table Entry changes the table.

        The offscreen test platform crashes inside the native question dialog.
        """
        app = QApplication.instance()
        if app is not None and app.platformName() == "offscreen":
            return True
        answer = QMessageBox.question(
            self,
            title,
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return answer == QMessageBox.Yes

    def _add_to_table(self):
        app = self.parent_app

        def _main_status(msg: str) -> None:
            if app is not None and hasattr(app, "status_label"):
                app.status_label.setText(msg)

        if self.canvas.reaction_arrow is not None:
            if not self._confirm_table_write(
                "Add to Table",
                "Add this reaction to the table as new rows?",
            ):
                return
            n = self._append_reaction_from_sketch()
            if n == 0:
                msg = (
                    "Sketcher: could not add a reaction. Draw reactants on the "
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
        if not self._confirm_table_write(
            "Add to Table",
            "Add this sketch to the table as new rows?",
        ):
            return
        n = self._append_molecules_from_smiles_parts(parts)
        if n == 0:
            msg = "Sketcher: could not parse fragments when adding to the table."
            _main_status(msg)
            QMessageBox.warning(self, "Add to Table", msg)
            return

    def _update_table_entry(self) -> None:
        """Write the sketch into the table row it was opened from."""
        if self._source_oid is None:
            return
        if self.canvas.reaction_arrow is not None:
            QMessageBox.information(
                self,
                "Update Table Entry",
                "A reaction is added as new rows. Use Add to Table.",
            )
            return
        parts = self.canvas.fragment_smiles_parts()
        if len(parts) != 1:
            QMessageBox.information(
                self,
                "Update Table Entry",
                "Update Table Entry needs a single structure. Use Add to Table for separate fragments.",
            )
            return
        if not self._confirm_table_write(
            "Update Table Entry",
            "Update this table entry with the sketch?",
        ):
            return
        self._update_source_row(parts[0])

    def _row_already_has_molecule(self, app, oid: int, mol) -> bool:
        current = app.mols.get(int(oid))
        if current is None:
            return False
        try:
            return mol_to_canonical_smiles(current) == mol_to_canonical_smiles(mol)
        except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
            return False

    def _update_source_row(self, smiles: str) -> bool:
        """Write one sketched molecule into the row the sketcher was opened from."""
        app = self.parent_app
        oid = self._source_oid
        if app is None or oid is None or not hasattr(app, "replace_row_structure"):
            return False
        mol = None
        if hasattr(app, "_mol_from_structure_text"):
            mol = app._mol_from_structure_text(smiles)
        if mol is None:
            mol = Chem.MolFromSmiles(smiles) or Chem.MolFromSmarts(smiles)
        if mol is None:
            QMessageBox.warning(
                self,
                "Update Table Entry",
                "Could not build a structure from this sketch, so the table row was left unchanged.",
            )
            return False
        if self._row_already_has_molecule(app, int(oid), mol):
            if hasattr(app, "status_label"):
                app.status_label.setText("That table row already has this structure.")
            return True
        if not app.replace_row_structure(int(oid), mol, description="Update row from sketcher"):
            QMessageBox.warning(
                self, "Update Table Entry", "That table row is no longer in the table."
            )
            return False
        return True

    def _ask_close(self) -> int:
        """Confirm closing. The offscreen test platform crashes inside the native dialog."""
        app = QApplication.instance()
        if app is not None and app.platformName() == "offscreen":
            return QMessageBox.Yes
        return QMessageBox.question(
            self,
            "Close Sketcher",
            "Close the sketcher?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )

    def _confirm_close(self) -> bool:
        return self._ask_close() == QMessageBox.Yes

    def closeEvent(self, event):
        if self._embedded:
            event.ignore()
            return
        if self.isVisible() and not self._confirm_close():
            event.ignore()
            return
        self._release_parent_edit_hotkeys()
        self._remove_sketch_key_filters()
        event.accept()
