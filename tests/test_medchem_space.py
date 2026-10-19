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

"""Tests for BOILED-Egg / golden-triangle medicinal chemistry plots."""

from __future__ import annotations

from rdkit import Chem

from molmanager.analysis.medchem_space import (
    MedChemRowSnapshot,
    MedChemSpaceDataset,
    MedChemSpacePoint,
    build_medchem_space_dataset,
    build_medchem_space_from_snapshots,
    classify_boiled_egg,
    in_golden_triangle,
    medchem_plot_max_points,
    oids_in_egg_gia,
    oids_in_egg_yolk,
    oids_in_golden_triangle_region,
    required_descriptor_columns_ok,
    resolve_descriptor_column,
    snapshot_scope_row_indices,
    snapshot_table_values_complete,
    subsample_dataset,
)
from molmanager.ui.medchem_space_plot import (
    build_boiled_egg_figure,
    build_golden_triangle_figure,
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


def test_large_medchem_cloud_fades_markers():
    assert marker_opacity_for_point_count(100) == 0.88
    assert marker_opacity_for_point_count(5_000) == 0.88
    faded = marker_opacity_for_point_count(106_000)
    assert 0.08 < faded < 0.25
    fig = build_boiled_egg_figure(_cloud(8_000))
    rest = float(fig.data[0].marker.opacity)
    assert rest < 0.88
    assert float(fig.data[0].unselected.marker.opacity) < rest
