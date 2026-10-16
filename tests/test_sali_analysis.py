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

"""Tests for Structure–Activity Landscape Index helpers."""

from molmanager.analysis.sali_analysis import build_sali_points, sali_index
from molmanager.ui.sali_plot import build_sali_figure


def test_sali_dialog_defaults_to_finer_morgan(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.sali import SaliDialog

    dlg = SaliDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    assert dlg.fp_combo.currentText() == "Morgan (r=3, n=2048)"
    assert dlg.params().fp_choice == "Morgan (r=3, n=2048)"
    dlg.deleteLater()


def test_sali_index_basic():
    assert abs(sali_index(1.0, 0.5) - 2.0) < 1e-12
    assert abs(sali_index(2.0, 0.0) - 2.0) < 1e-12


def test_sali_index_near_identical_is_finite():
    v = sali_index(1.0, 1.0)
    assert v == v  # not NaN
    assert v > 1e6


def test_build_sali_points_filters_and_caps():
    records = [(1, 1.0), (2, 3.0), (3, 1.1)]
    sims = [
        (1, 2, 0.8),  # |Δ|=2 → SALI = 2/0.2 = 10
        (1, 3, 0.9),  # |Δ|=0.1 → filtered by min_dact
        (2, 3, 0.2),  # low sim filtered
    ]
    points = build_sali_points(
        records,
        sims,
        min_similarity=0.5,
        min_activity_difference=0.5,
        max_pairs=10,
    )
    assert len(points) == 1
    assert {points[0].oid_a, points[0].oid_b} == {1, 2}
    assert abs(points[0].sali - 10.0) < 1e-9


def test_build_sali_points_max_pairs_keeps_highest_sali():
    records = [(1, 0.0), (2, 1.0), (3, 10.0)]
    sims = [
        (1, 2, 0.5),  # SALI = 1/0.5 = 2
        (1, 3, 0.5),  # SALI = 10/0.5 = 20
        (2, 3, 0.5),  # SALI = 9/0.5 = 18
    ]
    points = build_sali_points(records, sims, max_pairs=2)
    assert len(points) == 2
    assert points[0].sali >= points[1].sali
    assert points[0].sali == 20.0


def test_build_sali_points_canonical_oid_order():
    records = [(2, 3.0), (1, 1.0)]
    points = build_sali_points(records, [(2, 1, 0.8)])
    assert points[0].oid_a == 1
    assert points[0].oid_b == 2
    assert abs(points[0].signed_delta - 2.0) < 1e-12


def test_build_sali_points_heap_matches_full_sort():
    records = [(i, float(i)) for i in range(1, 12)]
    sims = [(a, b, 0.4 + 0.05 * ((a + b) % 7)) for a in range(1, 12) for b in range(a + 1, 12)]
    capped = build_sali_points(records, sims, max_pairs=5)
    full = build_sali_points(records, sims, max_pairs=0)
    assert [(p.oid_a, p.oid_b, round(p.sali, 12)) for p in capped] == [
        (p.oid_a, p.oid_b, round(p.sali, 12)) for p in full[:5]
    ]


def test_build_sali_figure():
    records = [(1, 1.0), (2, 3.0)]
    points = build_sali_points(records, [(1, 2, 0.7)])
    fig = build_sali_figure(points, activity_column="pIC50")
    assert fig.data
    assert "molmanager_selection_traces" in (fig.layout.meta or {})
