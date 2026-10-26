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

"""Tests for Data → Selectivity Ratio."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialogButtonBox

from molmanager.analysis.selectivity_ratio import (
    NARROW_WINDOW_HEADER,
    log_selectivity,
    looks_like_assay_column,
    selectivity_cells,
    selectivity_column_name,
    selectivity_headers,
)
from molmanager.ui.dialogs.selectivity_ratio import SelectivityRatioDialog


def test_log_selectivity_is_primary_minus_off_target():
    assert log_selectivity(8.0, 6.0) == 2.0
    assert looks_like_assay_column("pIC50")
    assert looks_like_assay_column("Ki")
    assert not looks_like_assay_column("LogP")
    assert selectivity_column_name("pHERG") == "logSel vs pHERG"


def test_narrow_window_uses_the_smallest_off_target():
    cells = selectivity_cells(
        7.0,
        [("pHERG", 6.5), ("pKi_2d6", 4.0)],
        potency_cutoff=6.0,
        window=1.0,
    )
    assert cells["logSel vs pHERG"] == "0.50"
    assert cells["logSel vs pKi_2d6"] == "3.00"
    assert cells[NARROW_WINDOW_HEADER] == "yes"
    selective = selectivity_cells(
        7.0,
        [("pHERG", 5.5), ("pKi_2d6", 4.0)],
        potency_cutoff=6.0,
        window=1.0,
    )
    assert selective[NARROW_WINDOW_HEADER] == "no"
    weak = selectivity_cells(
        5.0,
        [("pHERG", 4.8)],
        potency_cutoff=6.0,
        window=1.0,
    )
    assert weak[NARROW_WINDOW_HEADER] == "no"
    blank = selectivity_cells(None, [("pHERG", 6.0)], potency_cutoff=6.0, window=1.0)
    assert blank["logSel vs pHERG"] == ""
    assert blank[NARROW_WINDOW_HEADER] == ""
    assert selectivity_headers(["pHERG"]) == ("logSel vs pHERG", NARROW_WINDOW_HEADER)


def test_dialog_checks_other_assay_columns(qapp):  # noqa: ARG001
    dialog = SelectivityRatioDialog(["pIC50", "pKi", "LogP"])
    try:
        assert dialog.primary_combo.currentText() == "pIC50"
        checked = dialog._checked_secondaries()
        assert checked == ["pKi"]
        params = dialog.params()
        assert params.primary_column == "pIC50"
        assert params.secondary_columns == ("pKi",)
        assert params.potency_cutoff == 6.0
        assert params.window == 1.0
        ok = dialog._buttons.button(QDialogButtonBox.Ok)
        assert ok is not None and ok.isEnabled()
        item = dialog.secondary_list.item(1)
        item.setCheckState(Qt.Unchecked)
        assert not dialog._buttons.button(QDialogButtonBox.Ok).isEnabled()
    finally:
        dialog.deleteLater()
        qapp.processEvents()
