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

"""Systematic conformations dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QGroupBox

from molmanager.ui.dialogs.systematic_conformations import SystematicConformationsDialog


def test_systematic_conformations_dialog_defaults(qapp):  # noqa: ARG001
    dlg = SystematicConformationsDialog(0)
    p = dlg.params()
    assert dlg.windowTitle() == "Generate Conformations — Systematic"
    assert p.num_confs == 100
    assert p.rmsd_cutoff == pytest.approx(0.5)
    assert p.energy_cutoff == pytest.approx(50.0)
    assert p.include_original is False
    assert p.keep_hydrogens is False
    assert dlg.output_panel.add_to_table_cb.text() == "Add as Entries"
    assert p.obabel_path == ""
    boxes = {b.title(): b for b in dlg.findChildren(QGroupBox)}
    assert dlg.output_panel.add_to_table_cb.parent() is boxes["Output"]
    assert dlg.original_cb.parent() is boxes["Search"]
    assert dlg.output_panel.save_to_file_cb.parent() is dlg.output_panel
    assert dlg.output_panel.save_path_edit.parent() is dlg.output_panel
    dlg.close()


def test_systematic_conformations_dialog_params(qapp):  # noqa: ARG001
    dlg = SystematicConformationsDialog(2)
    dlg.num_confs_sb.setValue(40)
    dlg.rmsd_sb.setValue(0.8)
    dlg.energy_sb.setValue(25.0)
    dlg.original_cb.setChecked(True)
    dlg.keep_hs_cb.setChecked(True)
    p = dlg.params()
    assert p.num_confs == 40
    assert p.rmsd_cutoff == pytest.approx(0.8)
    assert p.energy_cutoff == pytest.approx(25.0)
    assert p.include_original is True
    assert p.keep_hydrogens is True
    assert p.obabel_path == ""
    dlg.close()
