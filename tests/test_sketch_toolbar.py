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

"""Sketcher toolbar glyph and top-toolbar wiring tests."""

from __future__ import annotations

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QPushButton, QWidget

from molmanager.ui.sketcher.bonds import BOND_STEREO_PLAIN, BOND_STEREO_WEDGE
from molmanager.ui.sketcher.constants import (
    SKETCH_RAIL_ELEMENTS,
    SKETCH_RING_TEMPLATES,
    TOOLBAR_ELEMENT_GROUPS,
)
from molmanager.ui.sketcher.fused_templates import FUSED_TEMPLATE_SMILES
from molmanager.ui.sketcher.customize_elements import default_toolbar_element_symbols
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.toolbar_glyphs import (
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
    mode_chain_icon,
    mode_draw_icon,
    mode_erase_icon,
    mode_lasso_icon,
    mode_select_icon,
    mode_text_icon,
    reaction_arrow_icon,
    ring_icon,
    view_3d_icon,
)


def test_toolbar_glyphs_are_non_null(qapp) -> None:  # noqa: ARG001
    icons = [
        bond_plain_icon(),
        bond_double_icon(),
        bond_triple_icon(),
        bond_wedge_icon(),
        bond_hash_icon(),
        bond_wavy_icon(),
        bond_dative_icon(),
        mode_select_icon(),
        mode_lasso_icon(),
        mode_text_icon(),
        mode_draw_icon(),
        mode_chain_icon(),
        mode_erase_icon(),
        clear_sketch_icon(),
        charge_plus_icon(),
        charge_minus_icon(),
        view_3d_icon(),
        reaction_arrow_icon(),
    ]
    for key, n_atoms, aromatic, _tip in TOOLBAR_RING_TEMPLATES:
        assert key in SKETCH_RING_TEMPLATES
        icons.append(ring_icon(n_atoms, aromatic=aromatic))
    for ic in icons:
        assert not ic.isNull()


def _rail_block_index(dialog: SketcherDialog, widget: QWidget) -> int:
    current: QWidget | None = widget
    while current is not None:
        if current in dialog._rail_blocks:
            return dialog._rail_blocks.index(current)
        current = current.parentWidget()
    return -1


def test_sketcher_top_toolbar_controls(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget(), element_symbols=default_toolbar_element_symbols())
    assert dlg.tb_3d.isCheckable()
    assert not dlg.tb_3d.isChecked()
    assert dlg.tb_chain.isCheckable()
    assert dlg.tb_draw.isChecked()
    assert not dlg.select_btn.isChecked()
    assert dlg.canvas.place_element == "C"
    assert not dlg.canvas.select_mode
    assert dlg.tb_draw.isCheckable()
    assert dlg.tb_erase.isCheckable()
    assert dlg.select_btn.isCheckable()
    assert dlg.lasso_btn.isCheckable()
    assert dlg.tb_text.isCheckable()
    assert dlg.tb_rxn_arrow.isCheckable()
    assert not dlg.tb_clear.isCheckable()
    assert dlg.bond_plain.isCheckable()
    assert dlg.charge_plus.isCheckable()
    assert dlg.view_3d.isHidden()
    dlg.tb_3d.setChecked(True)
    assert not dlg.view_3d.isHidden()
    dlg.tb_3d.setChecked(False)
    assert dlg.view_3d.isHidden()
    assert dlg._top_toolbar is None
    assert _rail_block_index(dlg, dlg.tb_draw) < _rail_block_index(dlg, dlg.bond_plain)
    assert _rail_block_index(dlg, dlg.bond_plain) < _rail_block_index(dlg, dlg.tb_rings)
    assert _rail_block_index(dlg, dlg.tb_rings) < _rail_block_index(dlg, dlg.charge_plus)
    assert _rail_block_index(dlg, dlg.tb_3d) == _rail_block_index(dlg, dlg.tb_rxn_arrow)
    assert _rail_block_index(dlg, dlg.tb_rxn_arrow) < _rail_block_index(dlg, dlg.element_buttons[0])
    assert _rail_block_index(dlg, dlg.tb_structure_status) == -1
    assert dlg.tb_structure_status.parent() is not None
    # Canvas sits under a splitter; dialog lookup must walk ancestors (right-click menu).
    assert dlg.canvas.parent() is dlg._canvas_splitter
    assert dlg.canvas._sketcher_dialog_if() is dlg
    assert list(dlg._element_btn_by_symbol) == list(SKETCH_RAIL_ELEMENTS)
    assert "Ni" in dlg._more_element_symbols
    assert "Pd" in dlg._more_element_symbols
    assert "D" in dlg._more_element_symbols
    assert "T" in dlg._more_element_symbols
    assert "Li" in dlg._more_element_symbols
    titles = [t for t, _ in TOOLBAR_ELEMENT_GROUPS]
    assert "Hydrogen Isotopes" in titles
    assert "Halogens" in titles
    assert "Alkaline Earth Metals" in titles
    assert "Alkali Earth Metals" not in titles
    assert "Transition Metals" in titles
    assert "Group 1" not in titles
    alkali = dict(TOOLBAR_ELEMENT_GROUPS)["Alkali Metals"]
    assert alkali == ("Li", "Na", "K", "Cs")
    assert dict(TOOLBAR_ELEMENT_GROUPS)["Boron Group"] == ("B", "Al")
    assert dict(TOOLBAR_ELEMENT_GROUPS)["Chalcogens"] == ("O", "S", "Se")
    assert dlg.tb_any_element is not None
    assert dlg.tb_wildcard is not None
    assert dlg.tb_r1.text() == "R1"
    assert dlg.tb_r2.text() == "R2"
    dlg.tb_r1.setChecked(True)
    assert dlg.canvas.place_element == "R1"
    assert not dlg.tb_r2.isChecked()
    assert not dlg.tb_wildcard.isChecked()
    dlg.tb_r2.setChecked(True)
    assert dlg.canvas.place_element == "R2"
    assert not dlg.tb_r1.isChecked()
    assert set(dlg._ring_btn_by_key) == set(SKETCH_RING_TEMPLATES) | set(FUSED_TEMPLATE_SMILES)

    dlg._on_ring_tool_clicked("Benzene", True)
    assert dlg.canvas.active_template == "Benzene"
    assert dlg._ring_btn_by_key["Benzene"].isChecked()
    assert dlg.canvas.place_element is None

    dlg._on_element_tool_clicked("N", True)
    assert dlg.canvas.active_template is None
    assert not dlg._ring_btn_by_key["Benzene"].isChecked()
    assert dlg.canvas.place_element == "N"

    dlg._enter_draw_mode()
    assert dlg.tb_draw.isChecked()
    assert not dlg.tb_erase.isChecked()
    assert not dlg.select_btn.isChecked()
    assert not dlg.lasso_btn.isChecked()
    assert not dlg.tb_text.isChecked()
    assert dlg.canvas.place_element == "C"

    dlg.select_btn.setChecked(True)
    assert dlg.canvas.select_mode
    assert dlg.canvas.select_tool == "box"
    assert not dlg.canvas.text_mode
    assert not dlg.lasso_btn.isChecked()

    dlg.lasso_btn.setChecked(True)
    assert dlg.canvas.select_mode
    assert dlg.canvas.select_tool == "lasso"
    assert not dlg.select_btn.isChecked()

    dlg.tb_text.setChecked(True)
    assert dlg.canvas.text_mode
    assert not dlg.canvas.select_mode
    assert not dlg.tb_draw.isChecked()
    assert not dlg.lasso_btn.isChecked()
    assert not dlg.tb_rxn_arrow.isChecked()

    dlg.tb_rxn_arrow.setChecked(True)
    assert dlg.canvas.reaction_arrow_mode
    assert not dlg.canvas.text_mode
    assert not dlg.tb_draw.isChecked()
    assert dlg.canvas.place_element is None

    dlg._on_bond_tool(2, BOND_STEREO_PLAIN)
    assert dlg.tb_draw.isChecked()
    assert not dlg.tb_rxn_arrow.isChecked()
    assert not dlg.canvas.reaction_arrow_mode
    assert not dlg.select_btn.isChecked()
    assert not dlg.lasso_btn.isChecked()
    assert not dlg.tb_text.isChecked()
    assert not dlg.canvas.select_mode
    assert not dlg.canvas.text_mode
    assert dlg.canvas.active_bond_order == 2
    assert dlg.canvas.place_element == "C"
    assert dlg.bond_double.isChecked()

    dlg._on_bond_tool(1, BOND_STEREO_WEDGE)
    assert dlg.canvas.active_bond_order == 1
    assert dlg.canvas.active_bond_stereo == BOND_STEREO_WEDGE
    assert dlg.bond_wedge.isChecked()
    assert dlg.tb_draw.isChecked()

    assert hasattr(dlg, "_act_show_lone_pairs")
    assert dlg._act_show_lone_pairs.isCheckable()
    assert not dlg.canvas.show_lone_pairs
    dlg._act_show_lone_pairs.setChecked(True)
    assert dlg.canvas.show_lone_pairs

    dlg.close()


def _image_pixels(image) -> tuple[int, ...]:
    return tuple(image.pixel(x, y) for y in range(image.height()) for x in range(image.width()))


def test_ring_template_icons_match_heavy_atoms(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.sketcher.fused_templates import fused_template
    from molmanager.ui.sketcher.toolbar_glyphs import fused_ring_image, ring_template_image

    benzene = SKETCH_RING_TEMPLATES["Benzene"]
    pyridine = SKETCH_RING_TEMPLATES["Pyridine"]
    benzene_image = ring_template_image(benzene[1], benzene[2])
    pyridine_image = ring_template_image(pyridine[1], pyridine[2])
    assert any(pixel for pixel in _image_pixels(benzene_image))
    assert _image_pixels(benzene_image) != _image_pixels(pyridine_image)
    pyrazine = SKETCH_RING_TEMPLATES["Pyrazine"][1]
    assert pyrazine == ["N", "C", "C", "N", "C", "C"]
    naphthalene = fused_template("Naphthalene")
    indole = fused_template("Indole")
    assert naphthalene is not None and indole is not None
    assert _image_pixels(fused_ring_image(naphthalene)) != _image_pixels(fused_ring_image(indole))
    assert "N" in indole.elements
    assert "N" not in naphthalene.elements

    widget = SketcherDialog(QWidget()).canvas
    widget.resize(480, 360)
    widget.place_template("Pyridine", center=QPoint(200, 160))
    assert len(widget.nodes) == 6
    assert sum(node["element"] == "N" for node in widget.nodes) == 1
    widget.clear(push_undo=False)
    widget.place_template("Indole", center=QPoint(200, 160))
    assert sum(node["element"] == "N" for node in widget.nodes) == 1
    assert len(widget.nodes) == 9


def test_left_rail_sections_are_split_without_titles(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QFrame, QLabel, QSplitter

    dialog = SketcherDialog(QWidget())
    try:
        assert dialog.findChildren(QLabel, "SketcherToolbarHeader") == []
        assert dialog._toolbar_panel.findChildren(QSplitter) == []
        lines = [
            frame
            for frame in dialog._toolbar_panel.findChildren(QFrame)
            if frame.frameShape() == QFrame.HLine and frame.frameShadow() == QFrame.Sunken
        ]
        assert len(lines) == 5
        assert all(line.height() == 8 or line.maximumHeight() == 8 for line in lines)
        assert dialog.tb_draw.parent() is not dialog.tb_wildcard.parent()
        assert dialog.element_buttons[0].parent() is not dialog.tb_wildcard.parent()
        dialog._populate_element_toolbar(list(SKETCH_RAIL_ELEMENTS))
        assert dialog.tb_wildcard.parent() is not None
        assert dialog.tb_rn.text() == "Rn"
        assert len(dialog.element_buttons) == len(SKETCH_RAIL_ELEMENTS)
    finally:
        dialog.close()


def _grid_cell(button) -> tuple[int, int]:
    grid = button.parentWidget().layout().itemAt(0).layout()
    row, column, _row_span, _col_span = grid.getItemPosition(grid.indexOf(button))
    return row, column


def test_rail_buttons_match_and_sit_two_across(qapp) -> None:
    dialog = SketcherDialog(QWidget())
    try:
        buttons = [
            dialog.tb_draw,
            dialog.tb_erase,
            dialog.select_btn,
            dialog.bond_plain,
            dialog._ring_btn_by_key["Benzene"],
            dialog.charge_plus,
            dialog.element_buttons[0],
            dialog.tb_wildcard,
            dialog.tb_r1,
            dialog.tb_rn,
        ]
        size = dialog.tb_draw.size()
        assert (size.width(), size.height()) == (28, 28)
        assert all(button.size() == size for button in buttons)
        assert _grid_cell(dialog.tb_draw) == (0, 0)
        assert _grid_cell(dialog.tb_erase) == (0, 1)
        assert _grid_cell(dialog.select_btn) == (1, 0)
        assert _grid_cell(dialog._ring_btn_by_key["Benzene"]) == (0, 0)
        assert _grid_cell(dialog._ring_btn_by_key["Pyridine"]) == (0, 1)
        assert _grid_cell(dialog.element_buttons[0]) == (0, 0)
        assert _grid_cell(dialog.element_buttons[1]) == (0, 1)
        assert _grid_cell(dialog.element_buttons[2]) == (1, 0)
        assert _grid_cell(dialog.tb_r1) == (1, 0)
        assert _grid_cell(dialog.tb_r2) == (1, 1)
        assert dialog.tb_rings.text() == "More…"
        assert dialog._toolbar_panel.width() < 80
        assert dialog._el_ncols == 2
        palette_names = {
            button.toolTip().split(" (", 1)[0]
            for button in dialog._ring_palette.findChildren(QPushButton)
        }
        assert "Benzene" not in palette_names
        assert "Pyridine" not in palette_names
        assert "Naphthalene" in palette_names

        dialog.resize(900, 700)
        dialog.show()
        qapp.processEvents()
        panel = dialog._toolbar_panel

        def column_x(button: QPushButton) -> int:
            return button.mapTo(panel, QPoint(0, 0)).x()

        left = column_x(dialog.tb_draw)
        right = column_x(dialog.tb_erase)
        assert right > left
        for button in (
            dialog.bond_plain,
            dialog._ring_btn_by_key["Benzene"],
            dialog.charge_plus,
            dialog.element_buttons[0],
            dialog.tb_wildcard,
            dialog.tb_r1,
        ):
            assert column_x(button) == left
        for button in (
            dialog.bond_double,
            dialog._ring_btn_by_key["Pyridine"],
            dialog.charge_minus,
            dialog.element_buttons[1],
            dialog.tb_any_element,
            dialog.tb_r2,
        ):
            assert column_x(button) == right
        assert column_x(dialog.tb_rings) == left
        assert dialog.tb_rings.width() == dialog._more_elements_btn.width()
        assert dialog.tb_rings.height() == size.height()
    finally:
        dialog.close()


def test_structure_health_sits_on_the_status_bar(qapp) -> None:
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QFont, QFontMetrics
    from PyQt5.QtWidgets import QSizeGrip

    from molmanager.ui.theme import default_app_font_pt, status_bar_font_pt

    dialog = SketcherDialog(QWidget())
    dialog.resize(900, 700)
    dialog.show()
    qapp.processEvents()
    try:
        bar = dialog._status_bar
        button = dialog.tb_structure_status
        font = QFont(qapp.font())
        point = font.pointSize()
        if point <= 0:
            point = default_app_font_pt()
        font.setPointSize(status_bar_font_pt(point))
        assert bar.font().pointSize() == font.pointSize()
        assert bar.height() == QFontMetrics(bar.font()).height() + 12
        assert not bar.isSizeGripEnabled()
        assert not (dialog.windowFlags() & Qt.MSWindowsFixedSizeDialogHint)
        assert dialog.maximumWidth() > dialog.minimumWidth()
        assert all(not grip.isVisible() for grip in dialog.findChildren(QSizeGrip))
        assert button.parent() is bar
        assert button not in dialog._toolbar_panel.findChildren(QPushButton)
        assert button.width() == button.height()
        assert button.height() == max(16, bar.height() - 6)
        corner = button.mapTo(bar, QPoint(button.width(), 0))
        assert bar.width() - corner.x() <= 4
        assert corner.x() > bar.width() // 2
        top = button.mapTo(bar, QPoint(0, 0)).y()
        assert abs((bar.height() - button.height()) // 2 - top) <= 3
    finally:
        dialog.close()
