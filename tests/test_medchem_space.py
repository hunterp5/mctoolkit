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

"""Tests for BOILED-Egg, golden-triangle, and LipE medicinal chemistry plots."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import Crippen

from molmanager.analysis.medchem_space import (
    MedChemRowSnapshot,
    MedChemSpaceDataset,
    MedChemSpacePoint,
    build_medchem_space_dataset,
    build_medchem_space_from_snapshots,
    classify_boiled_egg,
    in_golden_triangle,
    MEDCHEM_NEED_ACTIVITY,
    MEDCHEM_NO_ROWS,
    MEDCHEM_SELECTED_EMPTY,
    medchem_plot_max_points,
    medchem_snapshot_from_cells,
    medchem_structure_text,
    plan_medchem_plot_start,
    oids_in_egg_gia,
    oids_in_egg_yolk,
    oids_in_golden_triangle_region,
    oids_with_lipe_at_least,
    prefer_pactivity_column,
    required_descriptor_columns_ok,
    resolve_descriptor_column,
    snapshot_scope_row_indices,
    snapshot_table_values_complete,
    subsample_dataset,
)
from molmanager.ui.medchem_space_plot import (
    build_boiled_egg_figure,
    build_golden_triangle_figure,
    build_lipe_figure,
    marker_opacity_for_point_count,
)


def test_snapshot_scope_row_indices():
    # None means "all rows [0, row_count)" — plotters must treat that as iterable.
    assert snapshot_scope_row_indices(10) is None
    assert snapshot_scope_row_indices(10, visible_row_indices=[2, 4]) == [2, 4]
    assert snapshot_scope_row_indices(10, only_selected_rows=[1, 2, 8]) == [1, 2, 8]
    assert snapshot_scope_row_indices(
        10, only_selected_rows=[1, 2, 8], visible_row_indices=[2, 4, 8]
    ) == [2, 8]


def test_required_descriptor_columns_ok():
    assert required_descriptor_columns_ok(
        "boiled_egg", tpsa_col="TPSA", logp_col="LogP", mw_col="MW", wlogp_col="LogP"
    )
    assert not required_descriptor_columns_ok(
        "boiled_egg", tpsa_col="TPSA", logp_col="LogP", mw_col=None, wlogp_col="LogP"
    )
    assert required_descriptor_columns_ok(
        "golden_triangle", tpsa_col=None, logp_col="LogP", mw_col="MW"
    )


def test_golden_triangle_uses_table_without_rdkit_when_populated():
    snap = MedChemRowSnapshot(
        oid=1,
        label="a",
        structure_text="CCO",
        tpsa_text="",
        wlogp_text="",
        mw_text="300.12",
        logp_text="2.50",
    )
    assert snapshot_table_values_complete(
        "golden_triangle", tpsa=None, wlogp=None, mw=300.12, logp=2.5
    )
    ds, updates = build_medchem_space_from_snapshots(
        [snap],
        plot_kind="golden_triangle",
        tpsa_col="TPSA",
        logp_col="LogP",
        mw_col="MolWt",
        wlogp_col=None,
        use_table_columns_only=True,
    )
    assert len(ds.points) == 1
    assert ds.golden_triangle_count == 1
    assert updates == []


def test_build_from_snapshots_fills_from_structure_when_cells_empty():
    snap = MedChemRowSnapshot(
        oid=1,
        label="ethanol",
        structure_text="CCO",
        tpsa_text="",
        wlogp_text="",
        mw_text="",
        logp_text="",
    )
    ds, updates = build_medchem_space_from_snapshots(
        [snap],
        plot_kind="boiled_egg",
        tpsa_col="TPSA",
        logp_col="LogP",
        mw_col="MW",
        wlogp_col="LogP",
        use_table_columns_only=True,
        oid_smiles={1: "CCO"},
    )
    assert len(ds.points) == 1
    assert len(updates) == 1
    assert "TPSA" in updates[0][1]


def test_resolve_descriptor_column_aliases():
    headers = ["Compound", "MolWt", "cLogP", "TPSA"]
    assert resolve_descriptor_column(headers, ("mw",)) == "MolWt"
    assert resolve_descriptor_column(headers, ("logp",)) == "cLogP"
    assert resolve_descriptor_column(headers, ("tpsa",)) == "TPSA"


def test_build_dataset_and_figures_from_ethanol():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    ds = build_medchem_space_dataset(mol_rows=[(1, mol)], id_labels={1: "ethanol"})
    assert len(ds.points) == 1
    p = ds.points[0]
    assert p.tpsa > 0
    assert isinstance(classify_boiled_egg(p.tpsa, p.wlogp), tuple)
    assert isinstance(in_golden_triangle(p.logp, p.mw), bool)
    egg = build_boiled_egg_figure(ds)
    assert len(egg.data) == 1
    assert len(egg.layout.shapes) == 3
    assert egg.layout.yaxis.title.text == "LogP"
    assert egg.data[0].hoverinfo == "none"
    assert egg.data[0].customdata[0][0] == 1
    assert "LogP" in ds.points[0].hover
    assert "WLOGP" not in ds.points[0].hover
    tri = build_golden_triangle_figure(ds)
    assert len(tri.data) == 1
    assert len(tri.layout.shapes) == 1
    assert tri.data[0].hoverinfo == "none"
    assert tri.layout.xaxis.title.text == "LogP"
    assert tri.layout.yaxis.title.text == "Molecular weight (Da)"
    assert isinstance(oids_in_egg_gia(ds), list)
    assert isinstance(oids_in_egg_yolk(ds), list)
    assert isinstance(oids_in_golden_triangle_region(ds), list)
    assert "GIA" in ds.summary_text(plot_kind="boiled_egg")
    assert "golden triangle" in ds.summary_text(plot_kind="golden_triangle").lower()
    big = build_medchem_space_dataset(mol_rows=[(i, mol) for i in range(1, 21)])
    sub = subsample_dataset(big, 5, random_state=0)
    assert len(sub.points) == 5
    assert "subsample" in sub.subsample_note.lower()
    snap = MedChemRowSnapshot(
        oid=1,
        label="a",
        structure_text="",
        tpsa_text="46",
        wlogp_text="-0.0",
        mw_text="46",
        logp_text="-0.0",
    )
    ds2, _updates2 = build_medchem_space_from_snapshots(
        [snap],
        plot_kind="boiled_egg",
        tpsa_col="TPSA",
        logp_col="LogP",
        mw_col="MW",
        wlogp_col="LogP",
        use_table_columns_only=True,
    )
    assert len(ds2.points) == 1
    fig_c = build_boiled_egg_figure(ds, color_values=[p.mw, p.mw + 10], color_label="MW")
    assert fig_c.data[0].marker.showscale is True
    assert len(fig_c.data[0].marker.color) == 2


def test_medchem_dataset_subset_oids():
    pts = (
        MedChemSpacePoint(
            oid=1,
            tpsa=40.0,
            wlogp=1.0,
            mw=100.0,
            logp=1.0,
            hover="a",
            gia=True,
            bbb=False,
            golden_triangle=False,
        ),
        MedChemSpacePoint(
            oid=2,
            tpsa=50.0,
            wlogp=2.0,
            mw=200.0,
            logp=2.0,
            hover="b",
            gia=True,
            bbb=False,
            golden_triangle=False,
        ),
    )
    ds = MedChemSpaceDataset(points=pts, skipped=0)
    assert ds.subset_oids(None) is ds
    sub = ds.subset_oids(frozenset({2}))
    assert sub.oids == [2]
    assert len(sub.points) == 1


def _cloud(n: int) -> MedChemSpaceDataset:
    points = tuple(
        MedChemSpacePoint(
            oid=i,
            tpsa=40.0,
            wlogp=1.0,
            mw=300.0,
            logp=2.0,
            hover="",
            gia=True,
            bbb=False,
            golden_triangle=True,
        )
        for i in range(n)
    )
    return MedChemSpaceDataset(points=points, skipped=0, gia_count=n, golden_triangle_count=n)


def test_medchem_plot_draws_every_point_unless_capped(monkeypatch):
    monkeypatch.delenv("MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS", raising=False)
    cloud = _cloud(6_000)
    assert medchem_plot_max_points() is None
    assert subsample_dataset(cloud) is cloud

    monkeypatch.setenv("MOLMANAGER_MEDCHEM_PLOT_MAX_POINTS", "1000")
    capped = subsample_dataset(cloud, random_state=0)
    assert len(capped.points) == 1000
    assert "6,000" in capped.subsample_note


def test_medchem_summary_is_in_app_log_only(qapp, caplog):
    import logging

    from PyQt5.QtWidgets import QLabel

    from molmanager.analysis.medchem_space import (
        MedChemSpaceBuildResult,
        MedChemSpaceDataset,
        MedChemSpacePoint,
    )
    from molmanager.platform_support.session_log import session_log_buffer
    from molmanager.ui.dialogs.medchem_space import MedChemPlotPanel

    point = MedChemSpacePoint(
        oid=1,
        tpsa=60.0,
        wlogp=1.0,
        mw=200.0,
        logp=1.0,
        hover="",
        gia=True,
        bbb=False,
        golden_triangle=False,
    )
    dataset = MedChemSpaceDataset(points=(point,), skipped=0, gia_count=1, bbb_count=0)
    panel = MedChemPlotPanel(
        None,
        plot_kind="boiled_egg",
        window_title="BOILED-Egg",
        session_restore=True,
    )
    try:
        labels = [widget.text() for widget in panel.findChildren(QLabel)]
        assert "Summary" not in labels
        assert not hasattr(panel, "summary_text")
        session_log_buffer().clear()
        with caplog.at_level(logging.DEBUG):
            panel._on_build_finished(MedChemSpaceBuildResult(full=dataset, plot=dataset))
            panel.apply_session_state(panel.collect_session_state())
        assert not any("GIA" in record.message for record in caplog.records)
        entries, _seq, _gen = session_log_buffer().snapshot()
        logged = [entry for entry in entries if "GIA" in entry.message]
        assert logged
        assert all(entry.source == "ui" for entry in logged)
        assert all("BOILED-Egg" in entry.message for entry in logged)
        assert "summary" not in panel.collect_session_state()
    finally:
        session_log_buffer().clear()
        panel.deleteLater()
        qapp.processEvents()


def test_large_medchem_cloud_fades_markers():
    assert marker_opacity_for_point_count(100) == 0.88
    assert marker_opacity_for_point_count(5_000) == 0.88
    faded = marker_opacity_for_point_count(106_000)
    assert 0.08 < faded < 0.25
    fig = build_boiled_egg_figure(_cloud(8_000))
    rest = float(fig.data[0].marker.opacity)
    assert rest < 0.88
    assert float(fig.data[0].unselected.marker.opacity) < rest


def test_lipe_is_pactivity_minus_logp_and_skips_missing_activity():
    assert prefer_pactivity_column(["IC50", "pIC50", "LogP"]) == "pIC50"
    assert required_descriptor_columns_ok("lipe", tpsa_col=None, logp_col="LogP", mw_col=None)
    kept = MedChemRowSnapshot(
        oid=1,
        label="a",
        structure_text="",
        tpsa_text="",
        wlogp_text="",
        mw_text="",
        logp_text="2.0",
        activity_text="8.5",
    )
    missing = MedChemRowSnapshot(
        oid=2,
        label="b",
        structure_text="CCO",
        tpsa_text="",
        wlogp_text="",
        mw_text="",
        logp_text="1.0",
        activity_text="",
    )
    ds, updates = build_medchem_space_from_snapshots(
        [kept, missing],
        plot_kind="lipe",
        tpsa_col=None,
        logp_col="LogP",
        mw_col=None,
        wlogp_col=None,
        use_table_columns_only=True,
    )
    assert updates == []
    assert ds.skipped == 1
    assert len(ds.points) == 1
    assert ds.points[0].lipe == 6.5
    assert ds.points[0].activity == 8.5
    assert oids_with_lipe_at_least(ds) == [1]
    assert "LipE ≥ 5: 1 of 1" in ds.summary_text(plot_kind="lipe")
    fig = build_lipe_figure(ds)
    assert list(fig.data[0].x) == [2.0]
    assert list(fig.data[0].y) == [8.5]
    assert any(shape.line.dash == "solid" for shape in fig.layout.shapes)


def test_lipe_fills_logp_from_structure():
    snap = MedChemRowSnapshot(
        oid=3,
        label="ethanol",
        structure_text="CCO",
        tpsa_text="",
        wlogp_text="",
        mw_text="",
        logp_text="",
        activity_text="7",
    )
    ds, updates = build_medchem_space_from_snapshots(
        [snap],
        plot_kind="lipe",
        tpsa_col=None,
        logp_col="LogP",
        mw_col=None,
        wlogp_col=None,
        use_table_columns_only=True,
    )
    assert len(ds.points) == 1
    point = ds.points[0]
    assert point.activity == 7.0
    assert abs(point.lipe - (7.0 - point.logp)) < 1e-9
    assert updates and "LogP" in updates[0][1]
    mol_logp = Crippen.MolLogP(Chem.MolFromSmiles("CCO"))
    assert abs(point.logp - mol_logp) < 1e-6


def test_lipe_activity_combo_lists_numeric_columns(qapp):  # noqa: ARG001
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.dialogs.medchem_space import MedChemPlotPanel

    headers = ["ID_HIDDEN", "Structure", "SMILES", "pIC50", "LogP"]
    model = CompoundTableModel(headers)
    model.append_row(1, {"SMILES": "CCO", "pIC50": "6.5", "LogP": "1.2"})

    class _Host:
        def __init__(self) -> None:
            self.headers = headers
            self._table_model = model
            self.global_bounds = {}

        def _selected_oids_set(self) -> set[int]:
            return set()

        def _selected_logical_rows(self) -> list[int]:
            return []

        def _visible_source_row_indices(self):
            return None

        def chemistry_tool_structure_sources(self) -> list[str]:
            return ["Structure"]

        def is_plot_docked(self, _widget) -> bool:
            return False

    panel = MedChemPlotPanel(_Host(), plot_kind="lipe", window_title="LipE plot")
    try:
        combo = panel.activity_combo
        assert combo is not None
        labels = [combo.itemText(i) for i in range(combo.count())]
        assert labels == ["pIC50", "LogP"]
        assert combo.currentText() == "pIC50"
    finally:
        panel._hide_lipe_dialogs()
        panel.deleteLater()
        qapp.processEvents()


def test_lipe_opens_activity_settings_before_the_plot(qapp):
    from molmanager.ui.dialogs.medchem_space import MedChemPlotPanel, MedChemSpaceDialog

    egg = MedChemPlotPanel(
        None,
        plot_kind="boiled_egg",
        window_title="BOILED-Egg",
        session_restore=True,
    )
    try:
        assert egg.activity_combo is None
        assert egg.run_btn is None
        assert not hasattr(egg, "_appearance_dialog")
    finally:
        egg.deleteLater()

    dlg = MedChemSpaceDialog(None, plot_kind="lipe", window_title="LipE plot")
    panel = dlg._panel
    try:
        panel.present_initial_ui()
        qapp.processEvents()
        assert not dlg.isVisible()
        assert panel._opts_dialog.isVisible()
        assert panel._opts_dialog.windowTitle() == "LipE plot"
        assert panel.activity_combo is not None
        assert panel.run_btn is not None
        assert panel._opts_dialog.isAncestorOf(panel.activity_combo)
        assert panel._opts_dialog.isAncestorOf(panel.run_btn)
        assert not panel._appearance_dialog.isVisible()
        assert not panel._opts_dialog.isAncestorOf(panel.color_combo)

        panel._open_plot_options()
        qapp.processEvents()
        assert panel._appearance_dialog.isVisible()
        assert panel._appearance_dialog.windowTitle() == "LipE plot — Plot Options"
        assert panel._appearance_dialog.isAncestorOf(panel.color_combo)
        assert not panel._appearance_dialog.isAncestorOf(panel.activity_combo)

        panel._appearance_dialog.hide()
        panel._full_dataset = object()
        panel.present_initial_ui()
        qapp.processEvents()
        assert dlg.isVisible()
        assert not panel._opts_dialog.isVisible()
        assert not panel._appearance_dialog.isVisible()
    finally:
        panel._hide_lipe_dialogs()
        dlg.close()
        dlg.deleteLater()
        qapp.processEvents()


def test_plan_medchem_plot_start_blocks_empty_selection_and_missing_activity():
    empty = plan_medchem_plot_start(
        plot_kind="boiled_egg",
        headers=["Structure", "TPSA", "LogP", "MW"],
        row_count=3,
        only_selected=True,
        selection_empty=True,
        selected_rows=[],
        activity_column=None,
    )
    assert empty.warning
    assert empty.message == MEDCHEM_SELECTED_EMPTY

    no_rows = plan_medchem_plot_start(
        plot_kind="golden_triangle",
        headers=["LogP", "MW"],
        row_count=0,
        only_selected=False,
        selection_empty=False,
        selected_rows=None,
        activity_column=None,
    )
    assert no_rows.message == MEDCHEM_NO_ROWS
    assert not no_rows.warning

    lipe = plan_medchem_plot_start(
        plot_kind="lipe",
        headers=["Name", "LogP", "pIC50"],
        row_count=2,
        only_selected=False,
        selection_empty=False,
        selected_rows=None,
        activity_column="  ",
    )
    assert lipe.message == MEDCHEM_NEED_ACTIVITY

    ready = plan_medchem_plot_start(
        plot_kind="lipe",
        headers=["Name", "LogP", "pIC50"],
        row_count=2,
        only_selected=True,
        selection_empty=False,
        selected_rows=[1],
        activity_column="pIC50",
    )
    assert ready.message == ""
    assert ready.scope_rows == [1]
    assert ready.id_col == "Name"
    assert ready.logp_col == "LogP"
    assert ready.activity_col == "pIC50"
    assert ready.use_table_columns


def test_medchem_snapshot_uses_backing_text_for_the_structure_column():
    assert (
        medchem_structure_text(source="Structure", display="", backing="CCO", pixmap=False) == "CCO"
    )
    assert medchem_structure_text(source="Depict", display="", backing="CCC", pixmap=True) == "CCC"
    snap = medchem_snapshot_from_cells(
        7,
        {"Name": "cmpd", "LogP": "1.2"},
        id_col="Name",
        tpsa_col=None,
        logp_col="LogP",
        mw_col=None,
        wlogp_col=None,
        activity_col=None,
        src="Structure",
        structure_text="CCO",
    )
    assert snap.oid == 7
    assert snap.label == "cmpd"
    assert snap.structure_text == "CCO"
    assert snap.logp_text == "1.2"
