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


def test_sali_dialog_defaults_to_morgan_r2_2048(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QGroupBox

    from molmanager.ui.dialogs.sali import SaliDialog

    dlg = SaliDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    assert dlg.fp_combo.currentText() == "Morgan (r=2, n=2048)"
    assert dlg.params().fp_choice == "Morgan (r=2, n=2048)"
    assert dlg.params().max_pairs == 25_000
    assert [box.title() for box in dlg.findChildren(QGroupBox)] == [
        "Activity",
        "Similarity",
        "Pairs",
    ]
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
    assert fig.layout.yaxis.title.text == "|ΔpIC50|"


def test_selectivity_sali_uses_on_minus_off():
    records = [(1, 8.0), (2, 6.0)]
    offs = {1: 5.0, 2: 6.0}
    points = build_sali_points(records, [(2, 1, 0.5)], off_by_oid=offs)
    assert len(points) == 1
    point = points[0]
    assert (point.oid_a, point.oid_b) == (1, 2)
    assert point.delta_on == -2.0
    assert point.delta_off == 1.0
    assert point.signed_delta == -3.0
    assert point.abs_delta == 3.0
    assert abs(point.sali - 6.0) < 1e-12


def test_selectivity_pair_order_is_canonical():
    records = [(1, 8.0), (2, 6.0)]
    offs = {1: 5.0, 2: 6.0}
    forward = build_sali_points(records, [(1, 2, 0.5)], off_by_oid=offs)
    reverse = build_sali_points(records, [(2, 1, 0.5)], off_by_oid=offs)
    assert (forward[0].delta_on, forward[0].delta_off, forward[0].signed_delta) == (
        reverse[0].delta_on,
        reverse[0].delta_off,
        reverse[0].signed_delta,
    )


def test_activity_sali_leaves_component_deltas_empty():
    points = build_sali_points([(1, 1.0), (2, 3.0)], [(1, 2, 0.7)])
    assert points[0].signed_delta == 2.0
    assert points[0].delta_on is None
    assert points[0].delta_off is None


def test_selectivity_min_difference_uses_abs_delta_selectivity():
    records = [(1, 8.0), (2, 6.0)]
    offs = {1: 5.0, 2: 6.0}
    kept = build_sali_points(
        records,
        [(1, 2, 0.5)],
        min_activity_difference=3,
        off_by_oid=offs,
    )
    dropped = build_sali_points(
        records,
        [(1, 2, 0.5)],
        min_activity_difference=3.1,
        off_by_oid=offs,
    )
    assert len(kept) == 1
    assert dropped == []


def test_missing_off_target_drops_the_pair():
    points = build_sali_points(
        [(1, 8.0), (2, 6.0)],
        [(1, 2, 0.5)],
        off_by_oid={1: 5.0},
    )
    assert points == []


def test_legacy_sali_point_dict_still_loads():
    from molmanager.analysis.sali_analysis import SaliPoint

    point = SaliPoint(
        **{
            "pair_index": 0,
            "oid_a": 1,
            "oid_b": 2,
            "similarity": 0.8,
            "abs_delta": 2.0,
            "signed_delta": 2.0,
            "sali": 10.0,
        }
    )
    assert point.delta_on is None
    assert point.delta_off is None


def test_sali_dialog_selectivity_requires_two_columns(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.sali import SaliDialog

    dlg = SaliDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("selectivity"))
    assert not dlg.off_combo.isHidden()
    assert dlg._ok_button is not None
    assert not dlg._ok_button.isEnabled()
    dlg.deleteLater()


def test_sali_dialog_selectivity_params(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.sali import SaliDialog

    dlg = SaliDialog(
        structure_sources=["Structure"],
        activity_columns=["pKi_off", "pIC50"],
        selected_row_count=0,
    )
    assert dlg.params().off_target_column == ""
    assert dlg.off_combo.isHidden()
    dlg.mode_combo.setCurrentIndex(dlg.mode_combo.findData("selectivity"))
    params = dlg.params()
    assert params.activity_column == "pIC50"
    assert params.off_target_column == "pKi_off"
    assert dlg._ok_button is not None
    assert dlg._ok_button.isEnabled()
    fig = build_sali_figure(
        build_sali_points([(1, 8.0), (2, 6.0)], [(1, 2, 0.5)], off_by_oid={1: 5.0, 2: 6.0}),
        activity_column=params.activity_column,
        selectivity=True,
    )
    assert fig.layout.yaxis.title.text == "|Δselectivity|"
    assert dlg.treat_log_cb.text() == "Treat Logarithmically"
    assert params.treat_logarithmically is False
    dlg.treat_log_cb.setChecked(True)
    assert dlg.params().treat_logarithmically is True
    dlg.deleteLater()


def test_treat_logarithmically_uses_negative_log10():
    points = build_sali_points(
        [(1, 1e-8), (2, 1e-6)],
        [(1, 2, 0.5)],
        treat_logarithmically=True,
    )
    assert len(points) == 1
    point = points[0]
    assert abs(point.signed_delta - (6.0 - 8.0)) < 1e-9
    assert abs(point.abs_delta - 2.0) < 1e-9
    fig = build_sali_figure(points, activity_column="IC50", treat_logarithmically=True)
    assert fig.layout.yaxis.title.text == "|ΔpIC50|"


def test_treat_logarithmically_drops_non_positive():
    points = build_sali_points(
        [(1, 1e-8), (2, 0.0), (3, 1e-6)],
        [(1, 2, 0.5), (1, 3, 0.5)],
        treat_logarithmically=True,
    )
    assert [(p.oid_a, p.oid_b) for p in points] == [(1, 3)]


def test_selectivity_logarithmic_differences_match_pactivity():
    records = [(1, 10.0), (2, 1000.0)]
    offs = {1: 100.0, 2: 100.0}
    points = build_sali_points(
        records,
        [(1, 2, 0.5)],
        off_by_oid=offs,
        treat_logarithmically=True,
    )
    assert len(points) == 1
    point = points[0]
    # −log10(nM) differs from pIC50 by a constant that cancels in selectivity.
    assert abs(point.signed_delta - (-2.0)) < 1e-9
    assert abs(point.abs_delta - 2.0) < 1e-9
