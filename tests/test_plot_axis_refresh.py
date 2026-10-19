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

"""Tests for plot axis column list helpers."""

import pytest
from PyQt5.QtWidgets import QApplication, QComboBox

from molmanager.ui.plot import AXIS_NONE, PlotWidget, normalize_axis_name


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_set_axis_combo_items_preserves_selection(qapp):
    combo = QComboBox()
    PlotWidget._set_axis_combo_items(combo, ["MW", "LogP"], previous="LogP", allow_none=False)
    assert combo.currentText() == "LogP"

    PlotWidget._set_axis_combo_items(combo, ["MW"], previous="LogP", allow_none=False)
    assert combo.currentText() == "MW"


def test_on_table_data_changed_ignores_structure_paint(qapp):  # noqa: ARG001
    from PyQt5.QtCore import Qt

    from molmanager.ui.compound_table_model import CompoundTableModel

    class _Host:
        def __init__(self) -> None:
            self.n = 0

        def _schedule_plot(self) -> None:
            self.n += 1

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES", "MW"])
    model.append_row(0, {"SMILES": "C", "MW": "10"})
    host = _Host()
    struct = model.index(0, CompoundTableModel.STRUCTURE_COL)
    PlotWidget._on_table_data_changed(
        host, struct, struct, list(CompoundTableModel.STRUCTURE_PAINT_ROLES)
    )
    assert host.n == 0
    mw = model.index(0, model._headers.index("MW"))
    PlotWidget._on_table_data_changed(
        host, mw, mw, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
    )
    assert host.n == 1


def test_set_axis_combo_items_optional_none(qapp):
    combo = QComboBox()
    PlotWidget._set_axis_combo_items(combo, ["MW", "LogP"], previous=AXIS_NONE, allow_none=True)
    assert normalize_axis_name(combo.currentText()) is None


def test_plotter_markers_box_is_shared(qapp):
    from molmanager.ui.plot_markers_controls import PlotMarkersControls

    plot = PlotWidget(None)
    try:
        markers = plot._markers_group
        assert isinstance(markers, PlotMarkersControls)
        assert markers.title() == "Markers"
        assert markers.isAncestorOf(plot.color_combo)
        assert markers.isAncestorOf(plot.size_combo)
        assert not plot._axes_group.isAncestorOf(plot.color_combo)
        assert not plot._axes_group.isAncestorOf(plot.size_combo)
    finally:
        plot.deleteLater()
        qapp.processEvents()
