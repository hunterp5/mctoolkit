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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Pose browser overlay into an open Protein Viewer."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")


def _ethanol_pose(affinity: str, x: float):
    from rdkit import Chem
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


def test_protein_viewer_html_has_dock_pose_setter():
    from molmanager.ui.protein_viewer import build_protein_viewer_html

    html = build_protein_viewer_html()
    assert "molmanagerSetDockPose" in html
    assert "applyDockPose" in html
    assert "zoomToDockPose" in html
    assert "magentaCarbon" in html
    assert "selOf(comps[i]), {hidden: true}" not in html


def test_set_dock_pose_overlay(qapp):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    mol = _ethanol_pose("-7.250", 1.0)
    dlg = ProteinViewerDialog()
    assert dlg.set_dock_pose(mol, zoom=True, caption="Dock pose 1 of 1") is True
    payload = dlg._dock_pose_payload
    assert payload is not None
    assert payload["active"] is True
    assert payload["fmt"] == "sdf"
    assert payload["data"]
    assert payload["zoom"] is False
    pending = dlg.viewer._pending_dock_pose or (dlg.viewer._pending_payload or {}).get("dockPose")
    assert pending is not None
    assert pending["zoom"] is True
    assert "Dock pose 1 of 1" in dlg._atom_status.text()
    dlg.clear_dock_pose()
    assert dlg._dock_pose_payload is None
    dlg.close()


def test_ligand_mol_to_pdb_inventories_as_ligand():
    from molmanager.protein.structure_components import parse_structure_components
    from molmanager.ui.dock_complex_viewer import ligand_mol_to_pdb_text, pose_manager_slot_name

    mol = _ethanol_pose("-7.1", 0.0)
    pdb = ligand_mol_to_pdb_text(mol)
    assert "HETATM" in pdb
    comps = parse_structure_components(pdb, "pdb")
    assert comps
    assert all(c.kind == "ligand" for c in comps)
    assert pose_manager_slot_name(mol, 2).startswith("Pose 2")
    assert "-7.1" in pose_manager_slot_name(mol, 2)


def test_add_dock_poses_keeps_crystal_in_manager(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    rec = tmp_path / "holo.pdb"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  99       1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(rec)
    crystal_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    added = dlg.add_dock_pose_mols([_ethanol_pose("-8.0", 1.0), _ethanol_pose("-6.0", 4.0)])
    assert added == 2
    assert len(dlg._slots) == 3
    assert crystal_id in {r.spec.component_id for r in dlg._rows}
    pose_slots = [s for s in dlg._slots if s.name.startswith("Pose")]
    assert len(pose_slots) == 2
    assert all(
        row.color_scheme == "magenta"
        for slot in pose_slots
        for row in slot.rows
        if row.spec.kind == "ligand"
    )
    dlg.close()


def test_prepare_viewer_adds_crystal_when_receptor_is_apo(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    apo = tmp_path / "apo.pdb"
    apo.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n",
        encoding="utf-8",
    )
    xtal = tmp_path / "xtal.pdb"
    xtal.write_text(
        "HETATM    1  C1  LIG Z   1       4.000   0.000   0.000  1.00  0.00           C\nEND\n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    viewer = ProteinViewerDialog(parent)
    parent._protein_viewer_dialog = viewer
    parent._prepare_protein_viewer_for_poses(viewer, str(apo), crystal_path=str(xtal))
    kinds = {row.spec.kind for row in viewer._rows}
    assert "polymer" in kinds
    assert "ligand" in kinds
    assert len(viewer._slots) == 2
    viewer.close()
    parent.close()


def test_pose_browser_overlays_open_protein_viewer(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_embed import ProteinEmbedView
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    rec = tmp_path / "rec.pdb"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  99       1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    viewer = ProteinViewerDialog(parent)
    parent._protein_viewer_dialog = viewer
    viewer.load_structure_path(rec)
    pose_a = _ethanol_pose("-8.100", 1.0)
    pose_b = _ethanol_pose("-6.400", 4.0)
    win = parent.open_dock_results_window(
        [pose_a, pose_b],
        title="Pose browser",
        receptor_path=str(rec),
    )
    try:
        assert win is not None
        panel = parent._live_pose_browser()
        assert panel is win
        assert parent.is_plot_docked(panel) is False
        assert viewer.manager.is_docked(panel)
        assert viewer.manager._stack.currentWidget() is panel
        assert panel._viewer is not None
        payload = viewer._dock_pose_payload
        assert payload is not None
        assert payload.get("active") is True
        first_data = payload.get("data")
        assert first_data
        assert "1 of 2" in viewer._atom_status.text()
        assert "-8.100" in viewer._atom_status.text()
        assert panel._row_table.rowCount() == 2
        panel.set_pose_index(1)
        second = viewer._dock_pose_payload
        assert second is not None
        assert second.get("data")
        assert second["data"] != first_data
        assert "2 of 2" in viewer._atom_status.text()
        assert "-6.400" in viewer._atom_status.text()
        crystal = next(r for r in viewer._rows if r.spec.kind == "ligand")
        assert crystal.spec.resn == "LIG"
        assert panel._btn_add_pose is not None
        assert panel._btn_add_all_poses is not None
        n_before = len(viewer._slots)
        panel._add_current_pose_to_viewer()
        assert len(viewer._slots) == n_before + 1
        assert any(slot.name.startswith("Pose") for slot in viewer._slots)
        assert any(r.spec.kind == "ligand" and r.color_scheme == "magenta" for r in viewer._rows)
        assert any(
            r.spec.kind == "ligand" and r.spec.structure_id == crystal.spec.structure_id
            for r in viewer._rows
        )
        viewer.close_side_dock_widget(panel)
        qapp.processEvents()
        assert viewer._dock_pose_payload is None
    finally:
        live = parent._live_pose_browser()
        if live is not None and viewer.is_side_docked(live):
            viewer.close_side_dock_widget(live)
        viewer.close()
        parent.close()


def test_closed_pose_browser_does_not_restore_overlay_on_viewer_reopen(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_embed import ProteinEmbedView

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    rec = tmp_path / "rec.pdb"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  99       1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    viewer = parent.open_protein_viewer()
    viewer.load_structure_path(rec)
    parent.open_dock_results_window(
        [_ethanol_pose("-8.100", 1.0)],
        title="Pose browser",
        receptor_path=str(rec),
    )
    panel = parent._live_pose_browser()
    try:
        assert panel is not None
        assert viewer.manager.is_docked(panel)
        assert viewer._dock_pose_payload is not None
        viewer.close_side_dock_widget(panel)
        qapp.processEvents()
        assert parent._live_pose_browser() is None
        assert viewer._dock_pose_payload is None
        viewer.close()
        qapp.processEvents()
        again = parent.open_protein_viewer()
        qapp.processEvents()
        assert again._dock_pose_payload is None
        assert parent._live_pose_browser() is None
    finally:
        live = parent._live_pose_browser()
        if live is not None:
            host = live.window()
            if host is not None and host is not live:
                host.close()
        viewer = parent._live_protein_viewer()
        if viewer is not None:
            viewer.close()
        parent.close()


def test_closing_protein_viewer_closes_docked_pose_browser(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.pose_browser import PoseBrowserDialog
    from molmanager.ui.protein_embed import ProteinEmbedView
    from molmanager.ui.qt_widget_utils import qobject_is_deleted

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    rec = tmp_path / "rec.pdb"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  99       1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    viewer = parent.open_protein_viewer()
    viewer.load_structure_path(rec)
    parent.open_dock_results_window(
        [_ethanol_pose("-8.100", 1.0)],
        title="Pose browser",
        receptor_path=str(rec),
    )
    panel = parent._live_pose_browser()
    try:
        assert panel is not None
        assert viewer.is_side_docked(panel)
        viewer.close()
        qapp.processEvents()
        assert parent._live_pose_browser() is None
        dlg = getattr(parent, "_pose_browser_dialog", None)
        assert dlg is None or qobject_is_deleted(dlg)
        floating = [
            w
            for w in QApplication.topLevelWidgets()
            if isinstance(w, PoseBrowserDialog) and w.isVisible()
        ]
        assert floating == []
        assert parent._last_dock_results
    finally:
        live = parent._live_pose_browser()
        if live is not None:
            host = live.window()
            if host is not None and host is not live:
                host.close()
        viewer = parent._live_protein_viewer()
        if viewer is not None:
            viewer.close()
        parent.close()


def test_hidden_pose_browser_does_not_restore_overlay_on_viewer_reopen(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_embed import ProteinEmbedView

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    rec = tmp_path / "rec.pdb"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM    2  C1  LIG A  99       1.000   0.000   0.000  1.00  0.00           C\n"
        "END\n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    viewer = parent.open_protein_viewer()
    viewer.load_structure_path(rec)
    parent.open_dock_results_window(
        [_ethanol_pose("-8.100", 1.0)],
        title="Pose browser",
        receptor_path=str(rec),
    )
    panel = parent._live_pose_browser()
    try:
        assert panel is not None
        assert viewer._dock_pose_payload is not None
        viewer.close()
        qapp.processEvents()
        live = parent._live_pose_browser()
        assert live is not None
        host = live.window()
        assert host is not None and host is not viewer
        host.close()
        qapp.processEvents()
        assert parent._live_pose_browser() is None
        again = parent.open_protein_viewer()
        qapp.processEvents()
        assert again._dock_pose_payload is None
        assert parent._live_pose_browser() is None
    finally:
        live = parent._live_pose_browser()
        if live is not None:
            host = live.window()
            if host is not None and host is not live:
                host.close()
        viewer = parent._live_protein_viewer()
        if viewer is not None:
            viewer.close()
        parent.close()


def test_write_dock_poses_to_table_packs_parent_row(qapp):  # noqa: ARG001
    from molmanager.conformers.conformer_column_codec import (
        mol_from_packed_confs_cell,
        rehydrate_v1_confs_cell,
    )
    from molmanager.services.column_labels import COLUMN_PARENT_OID
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO"})
    w.next_oid = 1
    a = _ethanol_pose("-8.100", 1.0)
    b = _ethanol_pose("-6.400", 4.0)
    a.SetProp(COLUMN_PARENT_OID, "0")
    b.SetProp(COLUMN_PARENT_OID, "0")
    col = w.write_dock_poses_to_table([a, b])
    assert col == "poses"
    assert "poses" in w.headers
    raw = w._table_model.backing_value_for_row_header(0, "poses")
    full = rehydrate_v1_confs_cell(raw, "poses", 0, getattr(w, "_confs_blocks_sidecar", {}) or {})
    packed = mol_from_packed_confs_cell(full, min_conformers=1)
    assert packed is not None
    assert packed.GetNumConformers() == 2
    col2 = w.write_dock_poses_to_table([a, b])
    assert col2 == "poses (1)"
    w.close()


def test_write_dock_poses_to_table_adds_row_for_file_ligand(qapp):  # noqa: ARG001
    from molmanager.conformers.conformer_column_codec import (
        mol_from_packed_confs_cell,
        rehydrate_v1_confs_cell,
    )
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w.next_oid = 0
    a = _ethanol_pose("-8.100", 1.0)
    b = _ethanol_pose("-6.400", 4.0)
    a.SetProp("_Name", "lig")
    b.SetProp("_Name", "lig")
    col = w.write_dock_poses_to_table([a, b])
    assert col == "poses"
    assert w._table_model.rowCount() == 1
    oid = int(w._table_model.row_oid(0))
    raw = w._table_model.backing_value_for_row_header(0, "poses")
    full = rehydrate_v1_confs_cell(raw, "poses", oid, getattr(w, "_confs_blocks_sidecar", {}) or {})
    packed = mol_from_packed_confs_cell(full, min_conformers=1)
    assert packed is not None
    assert packed.GetNumConformers() == 2
    w.close()


def test_pose_browser_not_workspace_dockable():
    from molmanager.ui.pose_browser import PoseBrowserWidget

    assert getattr(PoseBrowserWidget, "dockable_in_workspace", True) is False


def test_protein_chain_manager_docks_widget(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.protein_chain_manager import ProteinChainManager

    mgr = ProteinChainManager()
    panel = QLabel("poses")
    panel.setWindowTitle("Pose Browser")
    assert mgr.dock_widget(panel)
    assert mgr.is_docked(panel)
    assert panel in mgr.docked_widgets()
    assert mgr.page_count() == 2
    assert mgr._stack.currentWidget() is panel
    assert mgr._header.isHidden() is False
    assert mgr._title_edit.text() == "Pose Browser"
    mgr.show_previous_page()
    assert mgr._stack.currentWidget() is mgr.tree
    assert mgr._title_edit.text() == "Manager"
    mgr.show_next_page()
    assert mgr._stack.currentWidget() is panel
    assert mgr.undock_widget(panel)
    assert mgr.is_docked(panel) is False
    assert mgr._stack.currentWidget() is mgr.tree
    assert mgr.page_count() == 1
    assert mgr._header.isHidden() is True
    mgr.close()


def test_pose_browser_headers_use_pose_id_not_smiles():
    from molmanager.ui.browsers.pose_browser import (
        POSE_ID_HEADER,
        pose_browser_headers,
        pose_browser_id,
    )

    mol = _ethanol_pose("-8.100", 1.0)
    mol.SetProp("SMILES", "CCO")
    mol.SetProp("mode", "1")
    headers = pose_browser_headers([mol])
    assert headers[0] == POSE_ID_HEADER
    assert "SMILES" not in headers
    assert "minimizedAffinity" in headers
    assert pose_browser_id(ligand=0, pose=0) == "1.1"
    assert pose_browser_id(ligand=1, pose=2) == "2.3"


def test_pose_browser_table_shows_unique_pose_ids(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.pose_browser import POSE_ID_HEADER, PoseBrowserWidget

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    panel = PoseBrowserWidget(None)
    lig_a1 = _ethanol_pose("-8.100", 1.0)
    lig_a2 = _ethanol_pose("-6.400", 4.0)
    lig_b1 = _ethanol_pose("-5.000", 7.0)
    lig_a1.SetProp("SMILES", "CCO")
    lig_a2.SetProp("SMILES", "CCO")
    lig_b1.SetProp("SMILES", "CCN")
    lig_a1.SetProp("_Name", "ligA")
    lig_a2.SetProp("_Name", "ligA")
    lig_b1.SetProp("_Name", "ligB")
    panel.set_poses([lig_a1, lig_a2, lig_b1])
    headers = [
        panel._row_table.horizontalHeaderItem(i).text()
        for i in range(panel._row_table.columnCount())
    ]
    assert headers[0] == POSE_ID_HEADER
    assert "SMILES" not in headers
    assert panel._row_table.rowCount() == 2
    assert panel._row_table.item(0, 0).text() == "1.1"
    assert panel._row_table.item(1, 0).text() == "1.2"
    panel._step(1)
    assert panel._row_table.rowCount() == 1
    assert panel._row_table.item(0, 0).text() == "2.1"
    panel.close()
