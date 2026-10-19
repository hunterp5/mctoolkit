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
        assert empty.toolTip() == "Not made"
        filled = panel._table.item(1, 0)
        assert filled is not None
        assert filled.text() == "6"
    finally:
        panel.close()
