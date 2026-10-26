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

"""Generate Conformations dialog configuration."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QCheckBox, QGroupBox

from molmanager.ui.dialogs.mol_tools import GenerateConformationsDialog
from molmanager.workers.conformer_generation import (
    CONFORMER_FORCE_FIELDS,
    DEFAULT_CONFORMER_FORCE_FIELD,
)


def test_generate_conformations_dialog_align_params(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    p = dlg.params()
    assert p.align_pattern == ""
    assert p.align_pattern_is_smarts is False
    dlg.align_pat_edit.setText(" c1ccccc1 ")
    dlg.align_smarts_cb.setChecked(True)
    p = dlg.params()
    assert p.align_pattern == "c1ccccc1"
    assert p.align_pattern_is_smarts is True
    dlg.close()


def test_generate_conformations_dialog_fine_tune_params(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    p = dlg.params()
    assert p.force_field == DEFAULT_CONFORMER_FORCE_FIELD
    assert [dlg.ff_combo.itemData(i) for i in range(dlg.ff_combo.count())] == list(
        CONFORMER_FORCE_FIELDS
    )
    assert p.post_min_rms_threshold == 0.0
    assert p.num_confs == 50
    assert p.max_keep == 100
    assert dlg.num_confs_sb.maximum() == 1000
    assert dlg.max_keep_sb.maximum() == 1000
    assert p.use_random_coords is False
    assert p.keep_hydrogens is False
    dlg.ff_combo.setCurrentText("MMFF")
    dlg.post_min_rms_sb.setValue(0.5)
    dlg.max_keep_sb.setValue(5)
    dlg.random_coords_cb.setChecked(True)
    dlg.keep_hs_cb.setChecked(True)
    p = dlg.params()
    assert p.force_field == "MMFF"
    assert p.post_min_rms_threshold == pytest.approx(0.5)
    assert p.max_keep == 5
    assert p.use_random_coords is True
    assert p.keep_hydrogens is True
    assert p.enforce_chirality is True
    dlg.ff_combo.setCurrentText("GAFF2")
    assert dlg.params().force_field == "GAFF2"
    dlg.ff_combo.setCurrentText("GAFF")
    assert dlg.params().force_field == "GAFF"
    assert {dlg.ff_combo.itemText(i) for i in range(dlg.ff_combo.count())} >= {
        "MMFF",
        "MMFF94s",
        "UFF",
        "GAFF2",
        "GAFF",
    }
    dlg.close()


def test_generate_conformations_dialog_options_includes_etkdg_flags(qapp):  # noqa: ARG001
    dlg = GenerateConformationsDialog(0)
    assert not any(cb.text() == "Advanced" for cb in dlg.findChildren(QCheckBox))
    assert dlg.output_panel.add_to_table_cb.text() == "Add as Entries"
    assert dlg.windowTitle() == "Generate Conformations — Stochastic"
    boxes = {b.title(): b for b in dlg.findChildren(QGroupBox)}
    embed = boxes["Embed"]
    assert dlg.enforce_chirality_cb.parent() is embed
    assert dlg.random_coords_cb.parent() is embed
    assert dlg.exp_torsions_cb.parent() is embed
    assert dlg.small_ring_cb.parent() is embed
    assert dlg.macrocycle_cb.parent() is embed
    assert dlg.basic_knowledge_cb.parent() is embed
    assert dlg.heavy_rms_cb.parent() is boxes["Minimize"]
    assert dlg.keep_hs_cb.parent() is boxes["Output"]
    assert dlg.only_selected_cb.parent() is boxes["Output"]
    assert dlg.output_panel.add_to_table_cb.parent() is boxes["Output"]
    assert dlg.output_panel.save_to_file_cb.parent() is dlg.output_panel
    assert dlg.output_panel.save_path_edit.parent() is dlg.output_panel
    dlg.close()
