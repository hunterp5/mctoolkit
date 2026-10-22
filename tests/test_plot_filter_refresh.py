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

"""Open plots follow the table filter's visible row set."""

from __future__ import annotations

from rdkit import Chem

from PyQt5.QtWidgets import QWidget

from molmanager.analysis.dimensionality_reduction import (
    DimensionReductionResult,
    subset_dimension_reduction_result,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.ui.plot_table_sync import (
    reindex_retained_point,
    retained_pair_points,
    retained_snapshot_oids,
    visible_oids_for_plot,
)
from molmanager.ui.widgets import FilterCard


def _setup_two_row_mw_table(w: ChemistryWorkspaceWindow) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "50"})
    w.mols[0] = Chem.MolFromSmiles("C")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2
    w.calculate_global_bounds()
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 5.0, 25.0)
    w.filters = [card]


class _FakePlotDialog(QWidget):
    def __init__(self, widget) -> None:
        super().__init__()
        self._plot_widget = widget


class _CountingPlotHost(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def _schedule_plot(self) -> None:
        self.calls += 1


def test_visible_oids_follow_numeric_filter(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    assert w._visible_oids_set() is None
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})
    assert visible_oids_for_plot(w) == frozenset({0})
    w.close()


def test_visible_source_rows_follow_filter(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    assert w._visible_source_row_indices() is None
    w._apply_filters_impl_sync(None)
    assert w._visible_source_row_indices() == [0]
    w.close()


def test_replot_walks_plot_hosts_not_just_selection_views(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    host = _CountingPlotHost()
    w._plot_dialogs = [_FakePlotDialog(host)]
    w._replot_active_plots()
    assert host.calls == 1
    w.close()


def test_replot_restores_ready_status_when_idle(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    host = _CountingPlotHost()
    w._plot_dialogs = [_FakePlotDialog(host)]
    w.status_label.setText("Calculate descriptors — 10/10 (100%)")
    w._replot_active_plots()
    assert w.status_label.text() == "Ready"
    w.close()


def test_replot_keeps_status_while_tool_progress_active(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    host = _CountingPlotHost()
    w._plot_dialogs = [_FakePlotDialog(host)]
    w._tool_progress_state.begin("Calculate descriptors", 10)
    w.status_label.setText("Calculate descriptors — 4/10 (40%)")
    w._replot_active_plots()
    assert host.calls == 1
    assert w.status_label.text() == "Calculate descriptors — 4/10 (40%)"
    w._tool_progress_state.end()
    w.close()


def test_visible_source_rows_cache_reused_until_invalidated(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    first = w._visible_source_row_indices()
    second = w._visible_source_row_indices()
    assert first == [0]
    assert first is second
    w._invalidate_visible_source_rows_cache()
    third = w._visible_source_row_indices()
    assert third == [0]
    assert third is not first
    w.close()


def test_unchanged_filter_visibility_skips_forced_replot(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    w._plot_replot_timer.stop()
    w._apply_filters_impl_sync(None)
    assert not w._plot_replot_timer.isActive()
    w.close()


def _two_row_table(w: ChemistryWorkspaceWindow) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "50"})


def test_deleting_a_row_schedules_every_open_plot(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _two_row_table(w)
    host = _CountingPlotHost()
    w._plot_dialogs = [_FakePlotDialog(host)]
    w._plot_replot_timer.stop()
    w._table_model.remove_row_at(1)
    assert w._plot_replot_timer.isActive()
    w._plot_replot_timer.stop()
    w._replot_active_plots()
    assert host.calls == 1
    w.close()


def test_bulk_delete_schedules_every_open_plot(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _two_row_table(w)
    w._plot_replot_timer.stop()
    w._table_model.remove_rows_by_oids(frozenset({0, 1}))
    assert w._plot_replot_timer.isActive()
    w.close()


def test_retained_snapshot_oids_drops_deleted_rows(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _two_row_table(w)
    assert retained_snapshot_oids(w, [0, 1]) is None
    assert retained_snapshot_oids(w, [0, 1, 9]) == frozenset({0, 1})
    w._table_model.remove_row_at(0)
    assert retained_snapshot_oids(w, [0, 1]) == frozenset({1})
    w.close()


def test_retained_snapshot_oids_can_ignore_filters(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    assert visible_oids_for_plot(w) == frozenset({0})
    assert retained_snapshot_oids(w, [0, 1]) == frozenset({0})
    assert retained_snapshot_oids(w, [0, 1], respect_filters=False) is None
    w.close()


def test_retained_pair_points_drop_a_deleted_endpoint(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _two_row_table(w)

    class _Pair:
        def __init__(self, oid_a: int, oid_b: int) -> None:
            self.oid_a = oid_a
            self.oid_b = oid_b

    kept_pair = _Pair(0, 1)
    gone_pair = _Pair(1, 9)
    assert retained_pair_points(w, [kept_pair, gone_pair]) == [kept_pair]
    w._table_model.remove_row_at(1)
    assert retained_pair_points(w, [kept_pair, gone_pair]) == []
    w.close()


def test_reindex_retained_point() -> None:
    points = ["a", "b", "c"]
    assert reindex_retained_point(points, ["a", "c"], 2) == 1
    assert reindex_retained_point(points, ["a", "c"], 1) is None
    assert reindex_retained_point(points, points, None) is None


def test_structure_paint_data_change_does_not_schedule_replot(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "C", "MW": "10"})
    w._plot_replot_timer.stop()
    w._table_model.notify_structure_column_changed()
    assert not w._plot_replot_timer.isActive()
    w._table_model.set_cell_text(0, "MW", "12")
    assert w._plot_replot_timer.isActive()
    w.close()


def test_filter_apply_replots_even_during_background_job(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._enter_background_job_ui()
    w._plot_replot_timer.stop()
    w._schedule_active_plots_replot()
    assert not w._plot_replot_timer.isActive()
    w._apply_filters_impl_sync(None)
    assert w._plot_replot_timer.isActive()
    w.close()


def test_subset_dimension_reduction_result_keeps_visible_oids() -> None:
    result = DimensionReductionResult(
        method="pca",
        x=[0.0, 1.0, 2.0],
        y=[3.0, 4.0, 5.0],
        oids=[10, 20, 30],
        hover=["a", "b", "c"],
        title="PCA",
        summary="",
        color_values=[1, 2, 3],
        color_label="MW",
    )
    subset = subset_dimension_reduction_result(result, frozenset({20, 30}))
    assert subset.oids == [20, 30]
    assert subset.x == [1.0, 2.0]
    assert subset.y == [4.0, 5.0]
    assert subset.color_values == [2, 3]
    assert subset_dimension_reduction_result(result, None) is result


def test_embedding_collect_ignores_table_filter(qapp):  # noqa: ARG001
    from molmanager.ui.data_analysis import table_to_dataframe

    w = ChemistryWorkspaceWindow()
    _setup_two_row_mw_table(w)
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})

    _df, rows = table_to_dataframe(w, visible_only=False, only_selected=False)
    assert set(rows) == {0, 1}
    _vis_df, vis_rows = table_to_dataframe(w, visible_only=True, only_selected=False)
    assert vis_rows == [0]

    mols = w.collect_scoped_table_mols("Structure", only_selected=False, only_visible=False)
    assert {oid for oid, _mol in mols} == {0, 1}
    vis_mols = w.collect_scoped_table_mols("Structure", only_selected=False, only_visible=True)
    assert {oid for oid, _mol in vis_mols} == {0}
    w.close()
