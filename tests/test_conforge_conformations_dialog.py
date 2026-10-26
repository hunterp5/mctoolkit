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

"""CONFORGE conformations dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QGroupBox

from molmanager.ui.dialogs.conforge_conformations import ConforgeConformationsDialog


def test_conforge_conformations_dialog_defaults(qapp):  # noqa: ARG001
    dlg = ConforgeConformationsDialog(0)
    p = dlg.params()
    assert dlg.windowTitle() == "Generate Conformations — CONFORGE"
    assert p.num_confs == 100
    assert p.rmsd_cutoff == pytest.approx(0.5)
    assert p.energy_window == pytest.approx(15.0)
    assert p.mode == "AUTO"
    assert p.preset == "MEDIUM_SET_DIVERSE"
    assert p.timeout_s == 3600
    assert p.include_input is False
    assert p.keep_hydrogens is False
    assert p.from_scratch is True
    assert dlg.output_panel.add_to_table_cb.text() == "Add as Entries"
    assert p.confgen_path == ""
    boxes = {b.title(): b for b in dlg.findChildren(QGroupBox)}
    assert dlg.output_panel.add_to_table_cb.parent() is boxes["Output"]
    assert dlg.original_cb.parent() is boxes["Ensemble"]
    dlg.close()


def test_conforge_conformations_dialog_params(qapp):  # noqa: ARG001
    dlg = ConforgeConformationsDialog(2)
    dlg.num_confs_sb.setValue(40)
    dlg.rmsd_sb.setValue(0.8)
    dlg.energy_sb.setValue(25.0)
    dlg.timeout_sb.setValue(120)
    idx = dlg.preset_combo.findData("LARGE_SET_DENSE")
    assert idx >= 0
    dlg.preset_combo.setCurrentIndex(idx)
    midx = dlg.mode_combo.findData("STOCHASTIC")
    assert midx >= 0
    dlg.mode_combo.setCurrentIndex(midx)
    dlg.original_cb.setChecked(True)
    dlg.keep_hs_cb.setChecked(True)
    p = dlg.params()
    assert p.num_confs == 40
    assert p.rmsd_cutoff == pytest.approx(0.8)
    assert p.energy_window == pytest.approx(25.0)
    assert p.timeout_s == 120
    assert p.preset == "LARGE_SET_DENSE"
    assert p.mode == "STOCHASTIC"
    assert p.include_input is True
    assert p.keep_hydrogens is True
    assert p.confgen_path == ""
    dlg.close()
