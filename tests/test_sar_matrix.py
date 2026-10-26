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

"""SAR matrix pivot: empty cells, pages, and shared cells."""

from __future__ import annotations

import pytest

from molmanager.analysis.sar_matrix import (
    SarMatrixLimit,
    SarObservation,
    build_sar_matrix,
    rgroup_index,
    sar_page_csv,
    sar_recommendation,
    suggest_rgroup_axes,
)


def _obs(oid, row, col, page="", activity=1.0):
    return SarObservation(oid, row, col, page, activity)


def test_missing_pair_is_absent_and_duplicates_average():
    matrix = build_sar_matrix(
        [
            _obs(2, "Me", "Cl", activity=6.0),
            _obs(1, "Me", "Cl", activity=8.0),
            _obs(3, "Et", "Cl", activity=5.0),
            _obs(4, "Me", "N/A", activity=9.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    assert matrix.row_labels == ("Et", "Me")
    assert matrix.col_labels == ("Cl",)
    page = matrix.pages[0]
    assert ("Me", "F") not in page.cells
    assert page.empty_count() == 0
    cell = page.cells[("Me", "Cl")]
    assert cell.oids == (1, 2)
    assert cell.display_value() == 7.0
    assert cell.grid_text() == "7 (2)"
    assert "Me,7 (2)" in sar_page_csv(page, row_axis="R1")


def test_third_substituent_becomes_pages_with_a_shared_grid():
    matrix = build_sar_matrix(
        [
            _obs(1, "Me", "Cl", "H", 6.0),
            _obs(2, "Et", "F", "H", 5.0),
            _obs(3, "Me", "Cl", "Ph", 8.0),
        ],
        row_axis="R1",
        col_axis="R2",
        page_axis="R3",
        activity_axis="pIC50",
    )
    assert [page.label for page in matrix.pages] == ["H", "Ph"]
    assert matrix.row_labels == ("Et", "Me")
    assert matrix.col_labels == ("Cl", "F")
    hydrogen = matrix.pages[0]
    assert hydrogen.cells[("Me", "Cl")].display_value() == 6.0
    assert ("Me", "F") not in hydrogen.cells
    assert ("Et", "Cl") not in hydrogen.cells
    phenyl = matrix.pages[1]
    assert set(phenyl.cells) == {("Me", "Cl")}
    assert phenyl.empty_count() == 3
    assert matrix.value_min == 5.0
    assert matrix.value_max == 8.0


def test_blank_page_is_left_out_when_a_page_axis_is_set():
    matrix = build_sar_matrix(
        [
            _obs(1, "Me", "Cl", "H", 6.0),
            _obs(2, "Et", "Cl", "", 4.0),
        ],
        row_axis="R1",
        col_axis="R2",
        page_axis="R3",
        activity_axis="pIC50",
    )
    assert matrix.row_labels == ("Me",)
    assert matrix.pages[0].label == "H"


def test_axis_cap_names_the_long_substituent():
    observations = [_obs(i, f"R{i}", "Cl") for i in range(3)]
    with pytest.raises(SarMatrixLimit, match="R1 has 3 substituents"):
        build_sar_matrix(
            observations,
            row_axis="R1",
            col_axis="R2",
            activity_axis="pIC50",
            max_labels=2,
        )


def test_suggest_rgroup_axes_orders_attachment_numbers():
    assert rgroup_index("RGD_R10") == 10
    assert rgroup_index("Core") is None
    assert suggest_rgroup_axes(["pIC50", "RGD_R2", "RGD_Core", "RGD_R1", "RGD_R3"]) == (
        "RGD_R1",
        "RGD_R2",
        "RGD_R3",
    )


def test_crossed_hole_is_predicted_and_named_when_it_wins():
    matrix = build_sar_matrix(
        [
            _obs(1, "H", "H", activity=1.0),
            _obs(2, "Me", "H", activity=2.0),
            _obs(3, "H", "F", activity=3.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    page = matrix.pages[0]
    assert page.predictions[("Me", "F")] == pytest.approx(4.0)
    assert ("H", "H") not in page.predictions
    text = sar_recommendation(matrix, higher_is_better=True)
    assert text == "Best unmade: R1=Me, R2=F, predicted 4, above R1=H, R2=F (3)."
    assert "≈4" in sar_page_csv(page, row_axis="R1")
    lower = sar_recommendation(matrix, higher_is_better=False)
    assert lower == "Best pair is already made (R1=H, R2=H, 1)."


def test_worse_hole_reports_the_best_made_pair():
    matrix = build_sar_matrix(
        [
            _obs(1, "H", "H", activity=5.0),
            _obs(2, "Me", "H", activity=6.0),
            _obs(3, "Cl", "H", activity=4.0),
            _obs(4, "H", "F", activity=8.0),
            _obs(5, "Me", "F", activity=9.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    assert matrix.pages[0].predictions[("Cl", "F")] == pytest.approx(7.0)
    text = sar_recommendation(matrix, higher_is_better=True)
    assert text == "Best pair is already made (R1=Me, R2=F, 9)."


def test_disjoint_series_does_not_invent_a_cross_term():
    matrix = build_sar_matrix(
        [
            _obs(1, "Me", "Cl", activity=6.0),
            _obs(2, "Et", "F", activity=5.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    assert matrix.pages[0].predictions == {}
    assert sar_recommendation(matrix, higher_is_better=True) == (
        "Best pair is already made (R1=Me, R2=Cl, 6)."
    )


def test_panel_leaves_an_unmade_cell_blank(qapp):
    from molmanager.ui.sar_matrix_panel import SarMatrixPanel

    matrix = build_sar_matrix(
        [
            _obs(1, "Me", "Cl", activity=6.0),
            _obs(2, "Et", "F", activity=5.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    panel = SarMatrixPanel(None)
    panel.set_matrix(matrix, higher_is_better=True)
    panel.show()
    qapp.processEvents()
    try:
        assert panel._table.rowCount() == 2
        assert panel._table.columnCount() == 2
        empty = panel._table.item(0, 0)
        assert empty is not None
        assert empty.text() == ""
        assert empty.toolTip() == (
            "Not made. Click to build this analog in the Drug Design Studio."
        )
        filled = panel._table.item(1, 0)
        assert filled is not None
        assert filled.text() == "6"
        assert "Best pair is already made" in panel._summary.text()
    finally:
        panel.close()


def test_panel_draws_a_prediction_in_italic(qapp):
    from molmanager.ui.sar_matrix_panel import SarMatrixPanel

    matrix = build_sar_matrix(
        [
            _obs(1, "H", "H", activity=1.0),
            _obs(2, "Me", "H", activity=2.0),
            _obs(3, "H", "F", activity=3.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    panel = SarMatrixPanel(None)
    panel.set_matrix(matrix, higher_is_better=True)
    panel.show()
    qapp.processEvents()
    try:
        labels = [panel._table.verticalHeaderItem(row).text() for row in range(2)]
        columns = [panel._table.horizontalHeaderItem(col).text() for col in range(2)]
        item = panel._table.item(labels.index("Me"), columns.index("F"))
        assert item is not None
        assert item.text() == "≈4"
        assert item.font().italic()
        assert "Free-Wilson prediction" in item.toolTip()
        assert "Best unmade: R1=Me, R2=F" in panel._summary.text()
    finally:
        panel.close()


def test_opening_sar_matrix_shows_an_undocked_window(qapp):
    from PyQt5.QtWidgets import QDialog

    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.sar_matrix_panel import SarMatrixPanel, SarMatrixWindow

    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure", "R1", "R2", "pIC50"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"R1": "H", "R2": "H", "pIC50": "1"})
    window._table_model.append_row(1, {"R1": "Me", "R2": "H", "pIC50": "2"})
    window._table_model.append_row(2, {"R1": "H", "R2": "F", "pIC50": "3"})
    window.next_oid = 3
    window._reveal_workspace_ready()
    try:
        window.open_sar_matrix_dialog()
        qapp.processEvents()
        settings = [
            dialog
            for dialog in qapp.topLevelWidgets()
            if isinstance(dialog, QDialog)
            and dialog.windowTitle() == "SAR Matrix"
            and not isinstance(dialog, SarMatrixWindow)
        ]
        assert len(settings) == 1
        settings[0].accept()
        qapp.processEvents()
        panels = [
            widget
            for widget in window.iter_docked_plot_widgets()
            if isinstance(widget, SarMatrixPanel)
        ]
        assert panels == []
        floating = [
            dialog
            for dialog in qapp.topLevelWidgets()
            if isinstance(dialog, SarMatrixWindow) and dialog.isVisible()
        ]
        assert len(floating) == 1
        assert "Best unmade" in floating[0]._panel._summary.text()
        assert "opened" in window.status_label.text()
    finally:
        window.close()


def test_sar_matrix_dialog_groups_options(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QGroupBox

    from molmanager.ui.dialogs.sar_matrix import SarMatrixDialog

    dialog = SarMatrixDialog(
        substituent_columns=["R1", "R2"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    assert [box.title() for box in dialog.findChildren(QGroupBox)] == ["Grid", "Activity"]
    dialog.deleteLater()
