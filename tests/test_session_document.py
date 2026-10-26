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

"""Session save/open round-trip through version-4 files (requires Qt + main window)."""

from __future__ import annotations

import json

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor
from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from session_roundtrip import open_saved, save_session_file, saved_document

_MINI_PDB = """\
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00           N
ATOM      2  CA  MET A   1      26.010  13.311  -8.124  1.00  0.00           C
ATOM      3  N   LEU B   2      10.000  11.000  12.000  1.00  0.00           N
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
END
"""


@pytest.fixture(autouse=True)
def _skip_session_auto_render(monkeypatch) -> None:
    """Session tests restore table chrome; skip the async 2D render that hangs teardown."""
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )


def test_session_file_roundtrip_preserves_keys(qapp):  # noqa: ARG001
    from molmanager.table.session_v4 import read_session_v4

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    opened = read_session_v4(save_session_file(w))
    try:
        doc = opened.manifest
        assert doc["headers"] == w.headers
        assert list(opened.rows.oids) == [0]
        assert opened.rows.get_text(0, "SMILES") == "CC"
        assert opened.mol_db is not None
        assert "rows" not in doc and "ids" not in doc
        assert "table_layout" in doc
        assert "docked_plots" in doc
        assert "column_widths" in doc["table_layout"]
        assert "hidden_columns" in doc["table_layout"]
        assert "workspace" in doc["table_layout"]
        layout_id = doc["workspace_layout"]["layout_id"]
        assert doc["table_layout"]["workspace"]["layout_id"] == layout_id
    finally:
        opened.discard_temp_files()


def test_selected_rows_session_keeps_only_selected_oids(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w._table_model.append_row(1, {"SMILES": "CCO", "Note": "ethanol"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("CCO")
    w.next_oid = 2
    w.zoomed_ids = {0, 1}
    w._confs_blocks_sidecar = {(0, "confs"): "aaa", (1, "confs"): "bbb"}

    doc = saved_document(w, oids={1})
    sidecar = doc.get("confs_sidecar") or {}
    assert "1:confs" in sidecar
    assert "0:confs" not in sidecar

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, oids={1})
    assert [w2._table_model.row_oid(r) for r in range(w2._table_model.rowCount())] == [1]
    assert set(w2.mols) == {1}
    assert w2.zoomed_ids == {1}


def test_session_open_restores_row(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    doc = saved_document(w)

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)

    assert w2.headers[:4] == ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    assert w2._table_model.rowCount() == 1
    smi_col = w2.headers.index("SMILES")
    assert "CC" in (w2._table_model.cell_text(0, smi_col) or "")
    assert 0 in w2.mols


def test_session_roundtrip_restores_mol_from_binary_not_smiles(qapp):  # noqa: ARG001
    """Saved RDKit binaries win over an unparseable SMILES cell on Open."""
    from molmanager.chem.molecule_conversion import mol_to_canonical_smiles

    parent = Chem.MolFromSmiles("CCN")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "not-a-smiles"})
    w.mols[0] = parent
    w.next_oid = 1

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2)
    assert w2.mols.blob_for(0)
    assert 0 in w2.mols
    assert mol_to_canonical_smiles(w2.mols[0]) == mol_to_canonical_smiles(parent)


def test_session_roundtrip_restores_saved_filter_bounds(qapp, monkeypatch):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.1"})
    w._table_model.append_row(1, {"SMILES": "CCN", "MW": "45.1"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2
    w.calculate_global_bounds()
    assert "MW" in w.global_bounds
    doc = saved_document(w)
    assert doc["global_bounds"]["MW"]["min"] == pytest.approx(float(w.global_bounds["MW"]["min"]))

    def boom(self, *args, **kwargs):
        raise AssertionError("session restore should use saved global_bounds")

    monkeypatch.setattr(ChemistryWorkspaceWindow, "calculate_global_bounds", boom)
    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert "MW" in w2.global_bounds
    assert w2.global_bounds["MW"]["max"] == pytest.approx(float(w.global_bounds["MW"]["max"]))


def test_session_open_rejects_legacy_files_with_converter_hint(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    import gzip

    legacy = tmp_path / "old.cms"
    legacy.write_bytes(gzip.compress(json.dumps({"version": 2, "ids": []}).encode()))
    warnings: list[str] = []
    w = ChemistryWorkspaceWindow()
    monkeypatch.setattr(w, "_warn_could_not_open", lambda _title, msg: warnings.append(msg))
    assert w.apply_saved_session_from_file(str(legacy)) is False
    assert warnings and "convert_session.py" in warnings[0]


def test_session_plots_ready_without_waiting_for_webengine(qapp):  # noqa: ARG001
    class _Host:
        web = object()
        _web_ready = False
        _pending_payload_json = "{}"

    class _PlainHost:
        _web_ready = False
        _pending_payload_json = "{}"

    w = ChemistryWorkspaceWindow()
    # No WebEngine view → reveal does not wait.
    w._iter_active_plot_hosts = lambda: [_PlainHost()]
    assert w._session_plots_ready_for_reveal() is True
    # Host with a web view that has not finished loading → wait.
    assert w._session_plot_host_waiting_for_web(_Host()) is True


def test_session_roundtrip_keeps_structure_independent_of_protonated(qapp):  # noqa: ARG001
    """Structure mols stay parent even when a Protonated column holds the ionized form."""
    from molmanager.chem.molecule_conversion import mol_to_canonical_smiles

    parent = Chem.MolFromSmiles("CCN")
    ionized = "CC[NH3+]"
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": ionized})
    w.mols[0] = parent
    w._table_model.register_pixmap_column("Protonated")
    w.next_oid = 1

    doc = saved_document(w)
    layout = doc.get("table_layout") or {}
    assert "Protonated" in (layout.get("pixmap_columns") or [])

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert 0 in w2.mols
    restored = mol_to_canonical_smiles(w2.mols[0])
    assert restored == mol_to_canonical_smiles(parent)
    assert "+" not in restored
    backing = w2._table_model.backing_value_for_row_header(0, "Protonated")
    assert ionized in backing
    assert w2._table_model.is_pixmap_data_column("Protonated")
    prot_col = w2.headers.index("Protonated")
    prot_idx = w2._table_model.index(0, prot_col)
    assert ionized in (w2._table_model.data(prot_idx, Qt.DisplayRole) or "")
    assert w2._mol_for_structure_row(0) is not None
    assert mol_to_canonical_smiles(w2._mol_for_structure_row(0)) == restored


def test_mol_for_structure_row_ignores_protonated_without_cached_mol(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": "CC[NH3+]"})
    w.mols = {}
    assert w._mol_for_structure_row(0) is None


def test_session_restore_render_tasks_keep_neutral_structure(qapp):  # noqa: ARG001
    from molmanager.chem.molecule_conversion import mol_to_canonical_smiles

    parent = Chem.MolFromSmiles("CCN")
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "Protonated"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"Protonated": "CC[NH3+]"})
    w.mols[0] = parent
    w.next_oid = 1
    doc = saved_document(w)

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    from molmanager.chem.render2d_mp import mol_from_render_payload

    renders, _ = w2._build_render2d_tasks_in_table_order("Structure", 80, 80, None)
    assert renders
    restored = mol_to_canonical_smiles(mol_from_render_payload(renders[0][1]))
    assert restored == mol_to_canonical_smiles(parent)
    assert "+" not in restored


def test_session_document_roundtrip_restores_column_coloring(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "10"})
    w._table_model.append_row(1, {"SMILES": "CCC", "MW": "20"})
    w._table_model.set_column_color_three_point_gradient(
        "MW",
        min_value=10.0,
        mid_value=15.0,
        max_value=20.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=111,
    )
    doc = saved_document(w)

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    mwi = w2.headers.index("MW")
    c0 = w2._table_model.data(w2._table_model.index(0, mwi), Qt.BackgroundRole)
    c1 = w2._table_model.data(w2._table_model.index(1, mwi), Qt.BackgroundRole)
    assert c0 is not None and c1 is not None
    assert c0.alpha() == 111 and c1.alpha() == 111
    spec = w2._table_model.column_color_rule_spec("MW")
    assert isinstance(spec, dict)
    assert spec.get("mode") == "numeric3"


def test_session_document_roundtrip_restores_logarithmic_columns(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "2"})
    w._logarithmic_columns = {"MW"}
    doc = saved_document(w)
    assert doc["logarithmic_columns"] == ["MW"]

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert "MW" in w2._logarithmic_columns


def test_session_open_keeps_legacy_som_map_as_text(qapp) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "SOM Map", "SOM Sites"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.register_pixmap_column("SOM Map")
    w._table_model.append_row(7, {"SMILES": "CCO", "SOM Map": "CCO", "SOM Sites": "0"})
    w.mols[7] = Chem.MolFromSmiles("CCO")
    w.next_oid = 8

    doc = saved_document(w)
    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert w2._table_model.is_pixmap_data_column("SOM Map") is False
    assert w2._table_model.backing_value_for_row_header(0, "SOM Map") == "CCO"
    assert w2._table_model.cell_text(0, w2.headers.index("SOM Map")) == "CCO"
    assert w2._table_model.cell_text(0, w2.headers.index("SOM Sites")) == "0"


def test_session_roundtrip_restores_mmp_ledger(qapp):  # noqa: ARG001
    from molmanager.analysis.mmp_analysis import MmpPair

    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="Clc1ccccc1",
        smiles_b="Fc1ccccc1",
        activity_a=1.0,
        activity_b=0.5,
        delta_activity=-0.5,
        transform="Cl[*:1]>>F[*:1]",
        core="c1ccccc1",
        sidechain_a="Cl[*:1]",
        sidechain_b="F[*:1]",
    )
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MMP_Partners"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(1, {"SMILES": "Clc1ccccc1", "MMP_Partners": "2"})
    w.mols[1] = Chem.MolFromSmiles("Clc1ccccc1")
    w.next_oid = 3
    w._mmp_last_pairs = [pair]
    w._mmp_last_activity_column = "IC50"

    doc = saved_document(w)
    assert doc["mmp_ledger"]["activity_column"] == "IC50"
    assert doc["mmp_ledger"]["pairs"][0]["oid_a"] == 1

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    restored = list(getattr(w2, "_mmp_last_pairs", None) or [])
    assert len(restored) == 1
    assert restored[0] == pair
    assert w2._mmp_last_activity_column == "IC50"
    w.close()
    w2.close()


def test_session_roundtrip_restores_metabolite_viewer(qapp):  # noqa: ARG001
    from molmanager.predictions.biotransformer_metabolites import (
        METABOLITE_COUNT_COLUMN,
        METABOLITE_SMILES_COLUMN,
    )
    from molmanager.ui.metabolite_browser import MetaboliteBrowseHit, MetaboliteBrowseRecord

    w = ChemistryWorkspaceWindow()
    w.headers = [
        "ID_HIDDEN",
        "Structure",
        "SMILES",
        METABOLITE_COUNT_COLUMN,
        METABOLITE_SMILES_COLUMN,
    ]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(
        1,
        {
            "SMILES": "c1ccccc1",
            METABOLITE_COUNT_COLUMN: "1",
            METABOLITE_SMILES_COLUMN: "Oc1ccccc1",
        },
    )
    w._table_model.append_row(
        2,
        {"SMILES": "CCO", METABOLITE_COUNT_COLUMN: "1", METABOLITE_SMILES_COLUMN: "CC=O"},
    )
    w.mols[1] = Chem.MolFromSmiles("c1ccccc1")
    w.mols[2] = Chem.MolFromSmiles("CCO")
    w.next_oid = 3
    w._metabolite_browse_records = [
        MetaboliteBrowseRecord(
            oid=1,
            smiles="c1ccccc1",
            metabolites=(
                MetaboliteBrowseHit(
                    smiles="Oc1ccccc1",
                    reaction="Hydroxylation",
                    enzyme="CYP3A4",
                    generation=1,
                    precursor_smiles="c1ccccc1",
                ),
            ),
        ),
        MetaboliteBrowseRecord(
            oid=2,
            smiles="CCO",
            metabolites=(
                MetaboliteBrowseHit(
                    smiles="CC=O",
                    reaction="Oxidation",
                    enzyme="ADH",
                    generation=2,
                ),
            ),
        ),
    ]
    doc = saved_document(w)
    assert doc["metabolite_browse"][0]["metabolites"][0]["enzyme"] == "CYP3A4"
    selected = w._session_metabolite_browse_payload(oids={2})
    assert [item["oid"] for item in selected] == [2]

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    recs = list(w2._metabolite_browse_records)
    assert [(rec.oid, rec.metabolites[0].enzyme) for rec in recs] == [(1, "CYP3A4"), (2, "ADH")]
    assert recs[0].metabolites[0].generation == 1
    assert recs[0].metabolites[0].precursor_smiles == "c1ccccc1"
    assert recs[0].metabolites[0].reaction == "Hydroxylation"
    w.close()
    w2.close()


def _session_ethanol_pose(affinity: str, x: float):
    from rdkit.Geometry import Point3D

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(x, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(x + 1.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(x + 2.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", affinity)
    return mol


def test_session_roundtrip_restores_dock_results(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager.conformers.conformer_column_codec import (
        mol_from_packed_confs_cell,
        rehydrate_v1_confs_cell,
    )
    from molmanager.services.column_labels import COLUMN_PARENT_OID
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.pose_browser import PoseBrowserWidget

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    a = _session_ethanol_pose("-8.100", 1.0)
    b = _session_ethanol_pose("-6.400", 4.0)
    a.SetProp(COLUMN_PARENT_OID, "0")
    b.SetProp(COLUMN_PARENT_OID, "0")
    assert w.write_dock_poses_to_table([a, b]) == "poses"
    w.open_dock_results_window(
        [a, b],
        title="Pose browser — out.sdf",
        receptor_path="/tmp/rec.pdbqt",
        crystal_path="/tmp/xtal.sdf",
    )
    live = w._live_pose_browser()
    if live is not None:
        host = live.window()
        if host is not None and host is not live:
            host.close()
        else:
            live.close()

    doc = saved_document(w)
    assert doc["dock_results"]["title"] == "Pose browser — out.sdf"
    assert len(doc["dock_results"]["poses"]) == 2
    assert any(str(col) == "poses" for _oid, col in w._confs_blocks_sidecar)

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert w2._live_pose_browser() is None
    assert w2._act_dock_viewer.isEnabled() is True
    snap = getattr(w2, "_last_dock_results", None) or {}
    mols = list(snap.get("mols") or [])
    assert len(mols) == 2
    assert mols[0].GetProp("minimizedAffinity") == "-8.100"
    assert snap.get("receptor_path") == "/tmp/rec.pdbqt"
    assert snap.get("pose_column") == "poses"
    pocket = w2._pose_column_contexts["poses"]
    assert pocket["receptor_path"] == "/tmp/rec.pdbqt"
    assert pocket["crystal_path"] == "/tmp/xtal.sdf"
    assert "poses" in w2.headers
    raw = w2._table_model.backing_value_for_row_header(0, "poses")
    full = rehydrate_v1_confs_cell(raw, "poses", 0, getattr(w2, "_confs_blocks_sidecar", {}) or {})
    packed = mol_from_packed_confs_cell(full, min_conformers=1)
    assert packed is not None
    assert packed.GetNumConformers() == 2

    win = w2.open_dock_results_viewer()
    assert win is not None
    panel = w2._live_pose_browser()
    assert isinstance(panel, PoseBrowserWidget)
    assert len(panel._all_mols) == 2
    assert panel._all_mols[0].GetProp("minimizedAffinity") == "-8.100"
    legacy = dict(doc)
    legacy.pop("pose_column_contexts", None)
    legacy_dock = dict(legacy.get("dock_results") or {})
    legacy_dock.pop("pose_column", None)
    legacy["dock_results"] = legacy_dock
    w3 = ChemistryWorkspaceWindow()
    open_saved(w, w3, legacy)
    assert w3._pose_column_contexts["poses"]["receptor_path"] == "/tmp/rec.pdbqt"
    w3.close()
    w.close()
    w2.close()


def test_view_poses_reopens_the_column_pocket_after_session(qapp, monkeypatch, tmp_path) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QMenu

    from molmanager.services.column_labels import COLUMN_PARENT_OID
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.pose_browser import PoseBrowserWidget

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    rec_a = tmp_path / "pocket_a.pdb"
    rec_b = tmp_path / "pocket_b.pdb"
    crystal = tmp_path / "crystal.sdf"
    rec_a.write_text("ATOM\n", encoding="utf-8")
    rec_b.write_text("ATOM\n", encoding="utf-8")
    crystal.write_text("\n", encoding="utf-8")

    w = ChemistryWorkspaceWindow()
    w2 = None
    try:
        w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
        w._table_model.set_headers(list(w.headers))
        w._table_model.append_row(0, {"SMILES": "CCO"})
        w.mols[0] = Chem.MolFromSmiles("CCO")
        w.next_oid = 1
        a = _session_ethanol_pose("-8.100", 1.0)
        b = _session_ethanol_pose("-6.400", 4.0)
        a.SetProp(COLUMN_PARENT_OID, "0")
        b.SetProp(COLUMN_PARENT_OID, "0")
        assert (
            w.write_dock_poses_to_table([a, b], receptor_path=str(rec_a), crystal_path=str(crystal))
            == "poses"
        )
        assert w.write_dock_poses_to_table([a, b], receptor_path=str(rec_b)) == "poses (1)"
        w._rename_column_header(w.headers.index("poses"), "docked")
        assert w._pose_column_contexts["docked"]["receptor_path"] == str(rec_a)
        assert len(w._mols_for_pose_cell(0, "docked")) == 2
        assert float(w._mols_for_pose_cell(0, "docked")[0].GetProp("minimizedAffinity")) == -8.1

        labels: list[str] = []

        def _exec(menu, *_args, **_kwargs):
            labels.extend(act.text() for act in menu.actions())
            return None

        monkeypatch.setattr(QMenu, "exec_", _exec)
        src = w._table_model.index(0, w.headers.index("docked"))
        view_ix = w._filter_proxy_model.mapFromSource(src)
        monkeypatch.setattr(w.table, "indexAt", lambda _pos: view_ix)
        w.show_table_menu(QPoint(1, 1))
        assert "View Poses" in labels
        assert "View Conformers…" in labels

        w.open_dock_results_window([a, b], title="Pose browser — second", receptor_path=str(rec_b))
        doc = saved_document(w)
        assert doc["pose_column_contexts"]["docked"]["receptor_path"] == str(rec_a)
        assert doc["pose_column_contexts"]["docked"]["crystal_path"] == str(crystal)
        assert doc["pose_column_contexts"]["poses (1)"]["receptor_path"] == str(rec_b)

        w2 = ChemistryWorkspaceWindow()
        open_saved(w, w2, doc)
        assert w2._pose_column_contexts["docked"]["receptor_path"] == str(rec_a)
        assert w2._pose_column_contexts["poses (1)"]["receptor_path"] == str(rec_b)

        loaded: list[str] = []
        ligands: list[str] = []

        class _Viewer:
            _canvas_bootstrapped = True
            _slots: list = []

            def add_structure_path(self, path, *, refit=True):
                loaded.append(str(path))

            def add_ligand_path(self, path, **_kwargs):
                ligands.append(str(path))
                return True

            def show(self):
                return None

            def raise_(self):
                return None

            def activateWindow(self):
                return None

        w2._ensure_protein_viewer = lambda show=True: _Viewer()
        before = (w2._last_dock_results or {}).get("receptor_path")
        w2.show_packed_poses_in_viewer(0, "docked")
        assert loaded == [str(rec_a)]
        assert ligands == [str(crystal)]
        assert (w2._last_dock_results or {}).get("receptor_path") == before
        panel = w2._live_pose_browser()
        assert isinstance(panel, PoseBrowserWidget)
        assert len(panel._all_mols) == 2
        assert float(panel._all_mols[0].GetProp("minimizedAffinity")) == -8.1
        assert float(panel._all_mols[1].GetProp("minimizedAffinity")) == -6.4
    finally:
        for window in (w2, w):
            if window is None:
                continue
            live = window._live_pose_browser()
            if live is not None:
                host = live.window()
                if host is not None and host is not live:
                    host.close()
                else:
                    live.close()
            window.close()


def test_session_roundtrip_restores_pose_browser_from_table_poses(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager.services.column_labels import COLUMN_PARENT_OID
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.pose_browser import PoseBrowserWidget

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    a = _session_ethanol_pose("-8.100", 1.0)
    b = _session_ethanol_pose("-6.400", 4.0)
    a.SetProp(COLUMN_PARENT_OID, "0")
    b.SetProp(COLUMN_PARENT_OID, "0")
    assert w.write_dock_poses_to_table([a, b]) == "poses"
    w._store_last_dock_results([], title="Pose browser")

    doc = saved_document(w)
    assert not doc.get("dock_results")

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert w2._act_dock_viewer.isEnabled() is True
    win = w2.open_dock_results_viewer()
    assert win is not None
    panel = w2._live_pose_browser()
    assert isinstance(panel, PoseBrowserWidget)
    assert len(panel._all_mols) == 2
    w.close()
    w2.close()


def test_selected_rows_session_keeps_selected_dock_results(qapp):  # noqa: ARG001
    from molmanager.services.column_labels import COLUMN_PARENT_OID

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w._table_model.append_row(1, {"SMILES": "CCN"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CCN")
    w.next_oid = 2
    a = _session_ethanol_pose("-8.100", 1.0)
    b = _session_ethanol_pose("-6.400", 4.0)
    a.SetProp(COLUMN_PARENT_OID, "0")
    b.SetProp(COLUMN_PARENT_OID, "1")
    w._store_last_dock_results([a, b], title="Pose browser — out.sdf")
    doc = saved_document(w, oids={1})
    poses = (doc.get("dock_results") or {}).get("poses") or []
    assert len(poses) == 1
    w.close()


def test_session_roundtrip_restores_ionization_cache(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager.ionization import microstate_cache as mc
    from molmanager.ionization.unipka_ensembles import (
        PicklableIonizationEnsemble,
        PicklableIonizationMicrostate,
        microstates_for_mol,
    )
    from molmanager.workers.structure_grouping import structure_key

    mc.clear()
    try:
        mol = Chem.MolFromSmiles("CCO")
        assert mol is not None
        key = structure_key(mol)
        fake = PicklableIonizationEnsemble(
            microstates=(PicklableIonizationMicrostate("CCO", 0, 0.0, mol.ToBinary()),),
            macro_pkas=(15.9,),
        )
        w = ChemistryWorkspaceWindow()
        w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
        w._table_model.set_headers(list(w.headers))
        w._table_model.append_row(0, {"SMILES": "CCO"})
        w.mols[0] = mol
        w.next_oid = 1
        mc.store(key, fake)

        doc = saved_document(w)
        assert doc["ionization_sidecar"]["entries"][key]["macro_pkas"] == [15.9]
        wire = json.dumps(doc)
        doc2 = json.loads(wire)

        w2 = ChemistryWorkspaceWindow()
        open_saved(w, w2, doc2)
        hit, cached = mc.lookup(key)
        assert hit is True
        assert cached.macro_pkas == (15.9,)

        def boom(_m):
            raise AssertionError("Uni-pKa should not run after session restore")

        monkeypatch.setattr(
            "molmanager.ionization.unipka_ensembles.predict_ionization_ensemble", boom
        )
        out = microstates_for_mol(Chem.MolFromSmiles("CCO"))
        assert out.macro_pkas == (15.9,)
    finally:
        mc.clear()


def test_session_open_auto_renders_like_file_ingest(qapp, monkeypatch):  # noqa: ARG001
    """Opening a session queues the same auto 2D render used after file ingest."""
    calls: list[int] = []

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.next_oid = 1
    doc = saved_document(w)

    w2 = ChemistryWorkspaceWindow()

    def fake_auto_render(self) -> bool:
        if self is w2:
            calls.append(self._table_model.rowCount())
        return False

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        fake_auto_render,
    )
    open_saved(w, w2, doc)
    qapp.processEvents()

    assert calls == [1]


def test_session_roundtrip_restores_table_layout(qapp, monkeypatch) -> None:  # noqa: ARG001
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.resize(900, 400)
    w.show()
    qapp.processEvents()
    mwi = w.headers.index("MW")
    w.table.setColumnWidth(mwi, 142)
    w.table.setColumnHidden(mwi, True)
    w.table.verticalHeader().setDefaultSectionSize(88)
    doc = saved_document(w)
    layout = doc["table_layout"]
    assert layout["column_widths"]["MW"] == 142
    assert layout["default_row_height"] == 88
    assert "MW" in layout["hidden_columns"]
    assert "ID_HIDDEN" not in layout["hidden_columns"]

    w2 = ChemistryWorkspaceWindow()
    w2.resize(900, 400)
    w2.show()
    qapp.processEvents()
    open_saved(w, w2, doc)
    qapp.processEvents()
    mwi2 = w2.headers.index("MW")
    assert w2.table.isColumnHidden(mwi2)
    assert int(w2.table.verticalHeader().defaultSectionSize()) == 88
    assert w2.table.isColumnHidden(0)
    # Deferred finish must not clobber the restored chrome.
    w2._finish_deferred_session_workspace_restore()
    qapp.processEvents()
    assert w2.table.isColumnHidden(mwi2)
    assert int(w2.table.verticalHeader().defaultSectionSize()) == 88
    w2.table.setColumnHidden(mwi2, False)
    assert int(w2.table.columnWidth(mwi2)) == 142
    assert w2.table.isColumnHidden(0)


def test_session_roundtrip_restores_docked_plotter(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def __init__(self, state: dict | None = None) -> None:
            super().__init__(None)
            self._state = state or {
                "kind": "plotter",
                "x": "MW",
                "y": "LogP",
                "plot_title": "MW vs LogP",
                "color": "MW",
            }

        def collect_session_state(self) -> dict:
            return dict(self._state)

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else None
        w = FakePlot(state if isinstance(state, dict) else None)
        restored.append(w)
        return w

    monkeypatch.setattr(ChemistryWorkspaceWindow, "_restore_docked_plot_widget", fake_restore)
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW", "LogP"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30", "LogP": "1.2"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, FakePlot())
    doc = saved_document(w)
    panes = doc["docked_plots"]["panes"]
    assert panes
    assert panes[0]["plots"][0]["state"]["x"] == "MW"
    assert panes[0]["plots"][0]["state"]["y"] == "LogP"
    assert panes[0]["plots"][0]["state"]["plot_title"] == "MW vs LogP"
    wire = json.dumps(doc)
    doc2 = json.loads(wire)

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc2)
    assert restored
    docked = list(w2.iter_docked_plot_widgets())
    assert docked
    assert docked[0] is restored[0]
    assert restored[0]._state["x"] == "MW"
    assert restored[0]._state["plot_title"] == "MW vs LogP"


def test_session_roundtrip_keeps_side_by_side_layout(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def __init__(self, label: str = "a") -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        restored.append(w)
        return w

    monkeypatch.setattr(ChemistryWorkspaceWindow, "_restore_docked_plot_widget", fake_restore)
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    p0, p1 = w._workspace_layout.plot_panes()
    w._workspace_layout.dock_into_pane(p0, FakePlot("left"))
    w._workspace_layout.dock_into_pane(p1, FakePlot("right"))
    doc = saved_document(w)
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert doc["docked_plots"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert len(doc["docked_plots"]["panes"]) == 2

    # Simulate an older session missing workspace layout_id but keeping docked layout_id.
    doc_fallback = json.loads(json.dumps(doc))
    doc_fallback["workspace_layout"] = {
        "sizes": doc["workspace_layout"]["sizes"],
        "ratios": doc["workspace_layout"]["ratios"],
    }

    w2 = ChemistryWorkspaceWindow()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)  # wrong layout before open
    open_saved(w, w2, doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    assert len(w2._workspace_layout.plot_panes()) == 2

    w3 = ChemistryWorkspaceWindow()
    w3.apply_workspace_layout(LAYOUT_TABLE_STACK)
    open_saved(w, w3, doc_fallback)
    assert w3._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    assert len(w3._workspace_layout.plot_panes()) == 2


def test_session_roundtrip_keeps_split_view_not_stacked(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": "split"}

        def _sync_footer_chrome(self) -> None:
            return None

    def fake_restore(self, spec):  # noqa: ARG001
        return FakePlot()

    monkeypatch.setattr(ChemistryWorkspaceWindow, "_restore_docked_plot_widget", fake_restore)

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    w._workspace_layout.dock_into_pane(w._workspace_layout.plot_panes()[0], FakePlot())
    doc = saved_document(w)
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SINGLE
    assert doc["docked_plots"]["layout_id"] == LAYOUT_TABLE_SINGLE
    assert doc["table_layout"]["workspace"]["layout_id"] == LAYOUT_TABLE_SINGLE
    assert len(doc["docked_plots"]["panes"]) == 1

    w2 = ChemistryWorkspaceWindow()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_STACK
    open_saved(w, w2, doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    assert len(w2._workspace_layout.plot_panes()) == 1

    doc_embedded = json.loads(json.dumps(doc))
    doc_embedded.pop("workspace_layout", None)
    w3 = ChemistryWorkspaceWindow()
    w3.apply_workspace_layout(LAYOUT_TABLE_STACK)
    open_saved(w, w3, doc_embedded)
    assert w3._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    assert len(w3._workspace_layout.plot_panes()) == 1


def test_session_save_after_closing_stacked_pane_is_split_view(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": "kept"}

        def _sync_footer_chrome(self) -> None:
            return None

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_restore_docked_plot_widget",
        lambda self, spec: FakePlot(),
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_STACK)
    p0, p1 = w._workspace_layout.plot_panes()
    w._workspace_layout.dock_into_pane(p0, FakePlot())
    assert w._workspace_layout.remove_pane(p1) is True
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    doc = saved_document(w)
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SINGLE
    assert doc["table_layout"]["workspace"]["layout_id"] == LAYOUT_TABLE_SINGLE
    assert doc["docked_plots"]["layout_id"] == LAYOUT_TABLE_SINGLE

    w2 = ChemistryWorkspaceWindow()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)
    open_saved(w, w2, doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    assert len(w2._workspace_layout.plot_panes()) == 1


def test_session_roundtrip_restores_workspace_splitter(qapp, monkeypatch) -> None:  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.resize(1000, 600)
    w.show()
    qapp.processEvents()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    qapp.processEvents()
    mgr = w._workspace_layout
    outer = mgr._splitters[0]
    outer.setSizes([620, 380])
    qapp.processEvents()
    saved_sizes = [int(s) for s in outer.sizes()]
    assert len(saved_sizes) == 2 and sum(saved_sizes) > 0
    doc = saved_document(w)
    ws = doc["workspace_layout"]
    assert ws["layout_id"] == LAYOUT_TABLE_SINGLE
    assert "ratios" in ws
    assert ws["sizes"]["splitter_0"] == saved_sizes
    saved_total = float(sum(saved_sizes))
    want_table = saved_sizes[0] / saved_total
    want_plot = saved_sizes[1] / saved_total

    w2 = ChemistryWorkspaceWindow()
    w2.resize(1000, 600)
    w2.show()
    qapp.processEvents()
    open_saved(w, w2, doc)
    qapp.processEvents()
    w2._finish_deferred_session_workspace_restore()
    qapp.processEvents()
    restored = w2._workspace_layout.collect_splitter_sizes()
    assert restored["layout_id"] == LAYOUT_TABLE_SINGLE
    sizes = restored["sizes"]["splitter_0"]
    assert len(sizes) == 2
    total = sum(sizes) or 1
    assert abs(sizes[0] / total - want_table) < 0.08
    assert abs(sizes[1] / total - want_plot) < 0.08


def test_session_open_clears_previous_docked_plots(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW"}

        def _sync_footer_chrome(self) -> None:
            return None

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_restore_docked_plot_widget",
        lambda self, spec: FakePlot(),  # noqa: ARG005
    )
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    leftover_host = ChemistryWorkspaceWindow()
    leftover_host.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    leftover_host._table_model.set_headers(list(leftover_host.headers))
    leftover_host._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    leftover_host.mols[0] = Chem.MolFromSmiles("CC")
    leftover_host.next_oid = 1
    leftover_host.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    leftover_host._workspace_layout.dock_into_pane(
        leftover_host._workspace_layout.plot_panes()[0], FakePlot()
    )
    assert list(leftover_host.iter_docked_plot_widgets())

    source = ChemistryWorkspaceWindow()
    source.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    source._table_model.set_headers(list(source.headers))
    source._table_model.append_row(0, {"SMILES": "CCO"})
    source.mols[0] = Chem.MolFromSmiles("CCO")
    source.next_oid = 1
    doc = saved_document(source)
    assert not doc["docked_plots"]["panes"]

    open_saved(source, leftover_host, doc)
    qapp.processEvents()
    assert list(leftover_host.iter_docked_plot_widgets()) == []


def test_session_roundtrip_preserves_pane_title_and_active_page(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakePlot(QWidget):
        def __init__(self, label: str) -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        dt = spec.get("display_title") if isinstance(spec, dict) else None
        if isinstance(dt, str) and dt.strip():
            w._pane_display_title = dt.strip()
        restored.append(w)
        return w

    monkeypatch.setattr(ChemistryWorkspaceWindow, "_restore_docked_plot_widget", fake_restore)
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    first = FakePlot("first")
    first._pane_display_title = "Custom pane"
    second = FakePlot("second")
    w._workspace_layout.dock_into_pane(pane, first)
    w._workspace_layout.dock_into_pane(pane, second)
    pane.set_plot_widgets(pane.plot_widgets(), current=1)
    doc = saved_document(w)
    pane_spec = doc["docked_plots"]["panes"][0]
    assert pane_spec["current"] == 1
    assert pane_spec["plots"][0]["display_title"] == "Custom pane"
    assert len(pane_spec["plots"]) == 2

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    panes = w2._workspace_layout.plot_panes()
    assert panes[0].page_index() == 1
    docked = list(w2.iter_docked_plot_widgets())
    assert len(docked) == 2
    assert getattr(docked[0], "_pane_display_title", None) == "Custom pane"


def test_session_roundtrip_restores_floating_plots(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QDialog, QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE, LAYOUT_TABLE_STACK

    class FakePlot(QWidget):
        def __init__(self, label: str = "a") -> None:
            super().__init__(None)
            self._label = label

        def collect_session_state(self) -> dict:
            return {"kind": "plotter", "x": "MW", "plot_title": self._label}

        def _sync_footer_chrome(self) -> None:
            return None

        def create_floating_dialog(self, parent_app):
            dlg = QDialog(parent_app)
            dlg._plot_widget = self
            dlg._force_close = False
            return dlg

    restored: list[FakePlot] = []

    def fake_restore(self, spec):  # noqa: ARG001
        state = spec.get("state") if isinstance(spec, dict) else {}
        title = state.get("plot_title", "x") if isinstance(state, dict) else "x"
        w = FakePlot(str(title))
        dt = spec.get("display_title") if isinstance(spec, dict) else None
        if isinstance(dt, str) and dt.strip():
            w._pane_display_title = dt.strip()
        restored.append(w)
        return w

    monkeypatch.setattr(ChemistryWorkspaceWindow, "_restore_docked_plot_widget", fake_restore)
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "MW": "30"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    floater = FakePlot("float")
    floater._pane_display_title = "Floating A"
    dlg = floater.create_floating_dialog(w)
    w._register_floating_result_dialog(dlg)
    doc = saved_document(w)
    assert doc["workspace_layout"]["layout_id"] == LAYOUT_TABLE_SIDE
    assert len(doc["floating_plots"]) == 1
    assert doc["floating_plots"][0]["display_title"] == "Floating A"

    w2 = ChemistryWorkspaceWindow()
    w2.apply_workspace_layout(LAYOUT_TABLE_STACK)
    open_saved(w, w2, doc)
    assert w2._workspace_layout.layout_id == LAYOUT_TABLE_SIDE
    hosts = list(w2._iter_floating_plot_hosts())
    assert len(hosts) == 1
    panel = w2._floating_plot_panel(hosts[0])
    assert getattr(panel, "_pane_display_title", None) == "Floating A"


def test_session_restore_dispatches_analysis_plot_kind(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    class FakeSali(QWidget):
        def collect_session_state(self) -> dict:
            return {
                "kind": "sali_map",
                "activity_column": "pIC50",
                "fp_choice": "Morgan",
                "metric": "Tanimoto",
                "points": [],
                "color": "(none)",
            }

        def _sync_footer_chrome(self) -> None:
            return None

    created: list[dict] = []

    def fake_sali_from_session(cls, parent_app, state):  # noqa: ARG001,N805
        created.append(dict(state or {}))
        w = FakeSali()
        w._restored_state = state
        return w

    from molmanager.ui import sali_map

    monkeypatch.setattr(
        sali_map.SaliMapPanel, "from_session_state", classmethod(fake_sali_from_session)
    )
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "pIC50"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "pIC50": "7"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    w._workspace_layout.dock_into_pane(w._workspace_layout.plot_panes()[0], FakeSali())
    doc = saved_document(w)
    assert doc["docked_plots"]["panes"][0]["plots"][0]["kind"] == "sali_map"

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert created
    assert created[0].get("activity_column") == "pIC50"
    assert list(w2.iter_docked_plot_widgets())


def test_session_omits_idle_table_search(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    doc = saved_document(w)
    assert "table_search" not in doc
    assert "table_find_replace" not in doc


def test_session_document_roundtrip_table_search(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w._table_model.append_row(1, {"SMILES": "C", "Note": "methane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w._search_panel.setVisible(True)
    w._populate_table_search_columns_combo()
    note_col = w.headers.index("Note")
    for j in range(w._search_col_combo.count()):
        if w._search_col_combo.itemData(j) == note_col:
            w._search_col_combo.setCurrentIndex(j)
            break
    w._search_partial_cb.setChecked(False)
    w._search_query_edit.setText('"ethane"')
    w._add_search_criterion_row()
    second = w._search_criterion_rows[1]
    w._populate_search_row_columns(second, preferred_header="SMILES")
    second.query_edit.setText('"CC"')
    glue_idx = second.glue_combo.findData("or")
    assert glue_idx >= 0
    second.glue_combo.setCurrentIndex(glue_idx)
    second.partial_cb.setChecked(True)

    doc = saved_document(w)
    search = doc.get("table_search")
    assert isinstance(search, dict)
    assert search.get("visible") is True
    criteria = search.get("criteria") or []
    assert len(criteria) == 2
    assert criteria[0]["column"] == "Note"
    assert criteria[0]["query"] == '"ethane"'
    assert criteria[1]["column"] == "SMILES"
    assert criteria[1]["query"] == '"CC"'
    assert criteria[1]["glue"] == "or"

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert not w2._search_panel.isHidden()
    assert len(w2._search_criterion_rows) == 2
    assert w2._search_criterion_rows[0].query_edit.text() == '"ethane"'
    assert w2._search_criterion_rows[1].query_edit.text() == '"CC"'
    assert w2._search_criterion_rows[1].glue() == "or"
    first_col = w2._search_criterion_rows[0].col_combo.currentData()
    assert first_col == w2.headers.index("Note")
    second_col = w2._search_criterion_rows[1].col_combo.currentData()
    assert second_col == w2.headers.index("SMILES")
    assert w2._selected_logical_rows() == [0]


def test_session_document_roundtrip_find_replace(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    w._find_replace_panel.setVisible(True)
    note_col = w.headers.index("Note")
    w._populate_find_replace_columns(preferred_col=note_col)
    bar = w._find_replace_bar
    bar.find_edit.setText("eth")
    bar.replace_edit.setText("prop")
    bar.case_cb.setChecked(True)
    bar.whole_cb.setChecked(True)
    scope = bar.scope_combo.findData("table")
    assert scope >= 0
    bar.scope_combo.setCurrentIndex(scope)

    doc = saved_document(w)
    payload = doc.get("table_find_replace")
    assert isinstance(payload, dict)
    assert payload.get("visible") is True
    assert payload.get("find") == "eth"
    assert payload.get("replace") == "prop"
    assert payload.get("column") == "Note"
    assert payload.get("scope") == "table"
    assert payload.get("case_sensitive") is True
    assert payload.get("whole_cell") is True

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert not w2._find_replace_panel.isHidden()
    restored = w2._find_replace_bar
    assert restored.find_edit.text() == "eth"
    assert restored.replace_edit.text() == "prop"
    assert restored.case_cb.isChecked()
    assert restored.whole_cb.isChecked()
    assert restored.scope_combo.currentData() == "table"
    assert restored.column_combo.currentData() == w2.headers.index("Note")


def test_session_roundtrip_restores_protein_viewer(qapp, tmp_path) -> None:  # noqa: ARG001
    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    dlg = w.open_protein_viewer()
    dlg.add_structure_path(first, refit=True)
    dlg.add_structure_path(second, refit=False)
    lig = next(r for r in dlg._slots[0].rows if r.spec.kind == "ligand")
    dlg._on_visibility_changed(lig.spec.component_id, False)
    assert dlg.save_viewer_to_session() is True

    doc = saved_document(w)
    pv = doc.get("protein_viewer")
    assert isinstance(pv, dict)
    assert [s["name"] for s in pv["structures"]] == ["first.pdb", "second.pdb"]

    w2 = ChemistryWorkspaceWindow()
    open_saved(w, w2, doc)
    assert w2._protein_viewer_dialog is None
    assert [s["name"] for s in w2._collect_protein_viewer()["structures"]] == [
        "first.pdb",
        "second.pdb",
    ]
    dlg2 = w2.open_protein_viewer()
    assert dlg2 is not None
    assert dlg2.isVisible() is True
    assert [slot.name for slot in dlg2._slots] == ["first.pdb", "second.pdb"]
    assert dlg2.manager.tree.topLevelItemCount() == 2
    hidden = next(r for r in dlg2._slots[0].rows if r.spec.kind == "ligand")
    assert hidden.visible is False
    opened = w2.open_protein_viewer()
    assert opened is dlg2
    w.close()
    w2.close()


def test_session_roundtrip_restores_gnina_dock(qapp, tmp_path) -> None:  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    dlg = w.open_gnina_dock()
    dlg.edit_receptor.setText(str(tmp_path / "rec.pdbqt"))
    dlg.edit_ligand.setText(str(tmp_path / "lig.sdf"))
    dlg.edit_out.setText(str(tmp_path / "out.sdf"))
    dlg.autobox_cb.setChecked(False)
    dlg.spin_cx.setValue(1.25)
    dlg.spin_sx.setValue(18.0)
    dlg.combo_cnn_scoring.setCurrentIndex(dlg.combo_cnn_scoring.findData("none"))
    dlg.edit_extra.setText("--seed 7")
    dlg._crystal_ligand_path = str(tmp_path / "xtal.sdf")
    dlg.close()

    doc = saved_document(w)
    saved = doc.get("gnina_dock")
    assert isinstance(saved, dict)
    assert str(saved["receptor"]).endswith("rec.pdbqt")
    assert saved["center_x"] == 1.25
    assert str(saved["crystal_ligand"]).endswith("xtal.sdf")
    assert saved["cnn_scoring"] == "none"
    assert saved["extra"] == "--seed 7"

    w2 = ChemistryWorkspaceWindow()
    w2.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w2._table_model.set_headers(list(w2.headers))
    open_saved(w, w2, doc)
    dlg2 = w2.open_gnina_dock()
    assert str(dlg2.edit_receptor.text()).endswith("rec.pdbqt")
    assert str(dlg2.edit_ligand.text()).endswith("lig.sdf")
    assert str(dlg2.edit_out.text()).endswith("out.sdf")
    assert dlg2.autobox_cb.isChecked() is False
    assert dlg2.spin_cx.value() == pytest.approx(1.25)
    assert dlg2.spin_sx.value() == pytest.approx(18.0)
    assert dlg2.combo_cnn_scoring.currentData() == "none"
    assert dlg2.edit_extra.text() == "--seed 7"
    assert str(dlg2._crystal_ligand_path).endswith("xtal.sdf")
    w.close()
    w2.close()
