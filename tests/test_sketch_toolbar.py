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

from PyQt5.QtWidgets import QWidget

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
    bar = dlg._top_toolbar.layout()
    tools = [
        bar.itemAt(i).widget() for i in range(bar.count()) if bar.itemAt(i).widget() is not None
    ]
    idx_3d = next(i for i in range(bar.count()) if bar.itemAt(i).widget() is dlg.tb_3d)
    assert bar.itemAt(idx_3d + 1).widget() is not None
    assert bar.itemAt(idx_3d + 1).widget() is not dlg.tb_rxn_arrow
    assert bar.itemAt(idx_3d + 2).widget() is dlg.tb_rxn_arrow
    assert tools.index(dlg.tb_rxn_arrow) > tools.index(dlg.tb_3d)
    assert tools.index(dlg.tb_rxn_arrow) < tools.index(dlg.tb_structure_status)
    assert tools[-1] is dlg.tb_structure_status
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
