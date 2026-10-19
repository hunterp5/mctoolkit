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

"""Dock menu, Gnina results viewer, and dock-results chrome."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")


def _live_pose_panel(parent, win):
    from molmanager.ui.pose_browser import PoseBrowserDialog, PoseBrowserWidget

    live = parent._live_pose_browser()
    if isinstance(live, PoseBrowserWidget):
        return live
    if isinstance(win, PoseBrowserWidget):
        return win
    if isinstance(win, PoseBrowserDialog):
        return win._panel
    return live


def test_dock_menu_includes_smina(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    assert hasattr(w, "open_gnina_dock")
    assert hasattr(w, "open_smina_dock")
    assert not hasattr(w, "open_easydock")
    protein_menu = None
    for act in w.menuBar().actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Protein":
            protein_menu = menu
            break
    assert protein_menu is not None
    dock = None
    for act in protein_menu.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Dock Ligand":
            dock = menu
            break
    assert dock is not None
    dock_actions = list(dock.actions())
    assert dock_actions[0].menu() is not None
    assert dock_actions[0].text().replace("&", "") == "Prepare"
    assert dock_actions[1].isSeparator()
    labels = [a.text() for a in dock_actions if a.text()]
    assert not any(t.startswith("EasyDock") for t in labels)
    assert any(t.startswith("Gnina") for t in labels)
    assert any(t.replace("&", "") == "Pose Browser" for t in labels)
    assert not any("Smina CLI" in t for t in labels)
    assert not any(t.startswith("Smina") for t in labels)
    viewer_act = next(a for a in dock_actions if a.text().replace("&", "") == "Pose Browser")
    assert viewer_act.isEnabled() is False
    tools = next(a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Tools")
    chemistry = next(
        a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Chemistry"
    )
    assert not any(a.text().replace("&", "") == "Dock" for a in tools.actions())
    assert not any(a.text().replace("&", "") == "Dock" for a in chemistry.actions())
    predict = None
    for act in chemistry.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Predict":
            predict = menu
            break
    assert predict is not None
    pred_labels = [a.text() for a in predict.actions() if a.text()]
    assert any("pKa" in t for t in pred_labels)
    assert any("Permeability" in t for t in pred_labels)
    som = None
    mets = None
    for act in predict.actions():
        menu = act.menu()
        label = act.text().replace("&", "")
        if menu is not None and label == "SOM":
            som = menu
        if menu is not None and label == "Metabolites":
            mets = menu
    assert som is not None
    assert mets is not None
    som_labels = [a.text().replace("&", "") for a in som.actions() if a.text()]
    met_labels = [a.text().replace("&", "") for a in mets.actions() if a.text()]
    assert som_labels[0].startswith("Predict")
    assert "Viewer" in som_labels
    assert met_labels[0].startswith("Predict")
    assert "Viewer" in met_labels
    som_viewer = next(a for a in som.actions() if a.text().replace("&", "") == "Viewer")
    met_viewer = next(a for a in mets.actions() if a.text().replace("&", "") == "Viewer")
    assert som_viewer.isEnabled() is False
    assert met_viewer.isEnabled() is False
    prepare = None
    for act in dock.actions():
        menu = act.menu()
        if menu is not None and act.text().replace("&", "") == "Prepare":
            prepare = menu
            break
    assert prepare is not None
    prep_labels = [a.text() for a in prepare.actions() if a.text()]
    assert any("PDBQT" in t for t in prep_labels)
    assert any("PDB" in t for t in prep_labels)
    w.close()


def test_predict_viewers_enable_when_table_has_results(qapp):  # noqa: ARG001
    from molmanager.predictions.biotransformer_metabolites import METABOLITE_SMILES_COLUMN
    from molmanager.predictions.som_prediction import SOM_MAP_COLUMN
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    w._sync_predict_viewer_actions()
    assert w._act_som_viewer.isEnabled() is False
    assert w._act_metabolite_viewer.isEnabled() is False
    w.headers = ["ID_HIDDEN", "Structure", SOM_MAP_COLUMN]
    w._table_model.set_headers(list(w.headers))
    w._sync_predict_viewer_actions()
    assert w._act_som_viewer.isEnabled() is True
    assert w._act_metabolite_viewer.isEnabled() is False
    w.headers.append(METABOLITE_SMILES_COLUMN)
    w._table_model.set_headers(list(w.headers))
    w._sync_predict_viewer_actions()
    assert w._act_metabolite_viewer.isEnabled() is True
    w.close()


def test_open_dock_results_window_lists_smina_fields(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QSizePolicy
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.dockable_plot_title import plot_widget_display_title
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.pose_browser import PoseBrowserWidget

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(1.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(2.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(3.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", "-7.250")
    mol.SetProp("rmsd_lb", "0.000")
    mol.SetProp("rmsd_ub", "0.000")
    mol.SetProp("mode", "1")
    mol.SetProp("poseStage", "minimized")
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    win = parent.open_dock_results_window([mol], title="Dock results", receptor_path=str(rec))
    assert win is not None
    panel = parent._live_pose_browser()
    assert isinstance(panel, PoseBrowserWidget)
    assert parent.is_plot_docked(panel) is False
    assert plot_widget_display_title(panel) == "Pose Browser"
    assert parent.pane_for_plot_widget(panel) is None
    headers = list(panel._headers)
    assert "minimizedAffinity" in headers
    assert "rmsd_lb" in headers
    assert "mode" in headers
    assert "poseStage" in headers
    table = panel._row_table
    assert table.rowCount() == 1
    aff_col = headers.index("minimizedAffinity")
    assert table.item(0, aff_col).toolTip() == "-7.250"
    viewer = panel._viewer
    assert viewer is not None
    assert not viewer._rec_b64
    assert viewer._lig_b64
    assert panel._btn_toggle_select.isCheckable()
    assert panel._btn_toggle_select.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert panel._cb_only_selected.text() == "Browse Selected"
    assert panel._opts_btn is not None
    assert set(panel._render_combos) == {"ligand"}
    ligand_cb = panel._render_combos["ligand"]
    sphere_idx = ligand_cb.findData("sphere")
    ligand_cb.setCurrentIndex(sphere_idx)
    assert viewer.render_styles()["ligand"] == "sphere"
    bar = table.horizontalScrollBar()
    reserved = table.height() - table.horizontalHeader().sizeHint().height() - table.rowHeight(0)
    assert reserved >= max(int(bar.sizeHint().height()), 16)
    parent.headers = ["ID_HIDDEN", "Structure", "MW"]
    parent._table_model.set_headers(list(parent.headers))
    main_hdr = parent._create_header_context_menu(2)
    assert main_hdr is not None
    main_titles = [a.text() for a in main_hdr.actions() if a.text()]
    assert "Search" in main_titles
    assert "Color" in main_titles
    parent.close()


def test_dock_viewer_reopens_closed_results_window(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(1.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(2.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(3.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", "-7.250")
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    try:
        assert parent._act_dock_viewer.isEnabled() is False
        win = parent.open_dock_results_window([mol], title="Dock results", receptor_path=str(rec))
        panel = _live_pose_panel(parent, win)
        assert panel is not None
        assert parent.is_plot_docked(panel) is False
        assert parent._act_dock_viewer.isEnabled() is True
        raised = parent.open_dock_results_viewer()
        assert raised is win
        panel.window().close()
        QApplication.processEvents()
        again = parent.open_dock_results_viewer()
        panel2 = parent._live_pose_browser()
        assert panel2 is panel
        assert again is panel2.window()
        assert parent.is_plot_docked(panel2) is False
        assert panel2._row_table.rowCount() == 1
        aff_col = panel2._headers.index("minimizedAffinity")
        assert panel2._row_table.item(0, aff_col).toolTip() == "-7.250"
        panel2.window().close()
    finally:
        parent.close()


def _pose_mol(smiles: str, affinity: str, x: float, *, name: str | None = None):
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    for i in range(mol.GetNumAtoms()):
        conf.SetAtomPosition(i, Point3D(x + (1.4 * i), 0.0 if i < 2 else 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", affinity)
    if name:
        mol.SetProp("_Name", name)
    return mol


def test_pose_browser_table_lists_poses_for_one_ligand(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    try:
        panel = parent.open_dock_results_window(
            [_pose_mol("CCO", "-8.100", 1.0), _pose_mol("CCO", "-6.400", 4.0)],
            title="Dock results",
            receptor_path=str(rec),
        )
        panel = _live_pose_panel(parent, panel)
        assert parent.is_plot_docked(panel) is False
        assert len(panel._groups) == 1
        assert panel._row_table.rowCount() == 2
        assert panel._btn_fwd.isEnabled() is False
        aff_col = panel._headers.index("minimizedAffinity")
        assert panel._row_table.item(0, aff_col).toolTip() == "-8.100"
        assert panel._row_table.item(1, aff_col).toolTip() == "-6.400"
        panel._row_table.selectRow(1)
        qapp.processEvents()
        assert panel._idx == 1
        assert panel.current_mol().GetProp("minimizedAffinity") == "-6.400"
        panel.window().close()
    finally:
        parent.close()


def test_pose_browser_nav_steps_ligand_groups(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.pose_browser import PoseBrowserDialog

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    try:
        panel = parent.open_dock_results_window(
            [
                _pose_mol("CCO", "-8.100", 1.0, name="ligA"),
                _pose_mol("CCO", "-6.400", 4.0, name="ligA"),
                _pose_mol("CCC", "-5.000", 0.0, name="ligB"),
            ],
            title="Dock results",
            receptor_path=str(rec),
        )
        panel = _live_pose_panel(parent, panel)
        assert len(panel._groups) == 2
        assert panel._row_table.rowCount() == 2
        assert panel._btn_fwd.isEnabled() is True
        aff_col = panel._headers.index("minimizedAffinity")
        assert panel._row_table.item(0, aff_col).toolTip() == "-8.100"
        panel._step(1)
        assert panel._group_idx == 1
        assert panel._idx == 0
        assert panel._row_table.rowCount() == 1
        assert panel._row_table.item(0, aff_col).toolTip() == "-5.000"
        assert "Ligands: 2 / 2" in panel._meta.text()
        assert parent.is_plot_docked(panel) is False
        assert isinstance(panel.window(), PoseBrowserDialog)
        panel.window().close()
    finally:
        parent.close()


def test_pose_browser_table_has_horizontal_scrollbar(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import Qt

    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    mol = _pose_mol("CCO", "-8.100", 1.0)
    for key, val in (
        ("CNNscore", "0.812"),
        ("CNNaffinity", "6.410"),
        ("rmsd_lb", "0.000"),
        ("rmsd_ub", "1.250"),
        ("crystalRMSD", "1.842"),
        ("crystalRef", "LIG A 99"),
        ("poseStage", "minimized"),
        ("mode", "1"),
        ("CNNvariance_affinity", "0.110"),
        ("CNNvariance_pose", "0.040"),
    ):
        mol.SetProp(key, val)
    parent = ChemistryWorkspaceWindow()
    try:
        panel = parent.open_dock_results_window(
            [mol],
            title="Dock results",
            receptor_path=str(rec),
        )
        panel = _live_pose_panel(parent, panel)
        table = panel._row_table
        hdr = table.horizontalHeader()
        assert hdr.stretchLastSection() is False
        assert table.horizontalScrollBarPolicy() == Qt.ScrollBarAsNeeded
        table.resize(220, table.height())
        qapp.processEvents()
        total = sum(table.columnWidth(c) for c in range(table.columnCount()))
        assert total > table.viewport().width()
        bar = table.horizontalScrollBar()
        assert bar is not None
        assert bar.maximum() > 0
        panel.window().close()
    finally:
        parent.close()


def test_pose_browser_table_sorts_highest_first_on_header_click(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.dock_complex_viewer import DockComplexEmbedView
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    monkeypatch.setattr(DockComplexEmbedView, "_ensure_web", lambda self: None)
    rec = tmp_path / "rec.pdbqt"
    rec.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n",
        encoding="utf-8",
    )
    parent = ChemistryWorkspaceWindow()
    try:
        panel = parent.open_dock_results_window(
            [
                _pose_mol("CCO", "-8.100", 1.0),
                _pose_mol("CCO", "-6.400", 4.0),
                _pose_mol("CCO", "-9.200", 2.0),
            ],
            title="Dock results",
            receptor_path=str(rec),
        )
        panel = _live_pose_panel(parent, panel)
        table = panel._row_table
        hdr = table.horizontalHeader()
        aff_col = panel._headers.index("minimizedAffinity")
        assert hdr.sectionsClickable()
        assert hdr.isSortIndicatorShown()
        assert [table.item(r, aff_col).toolTip() for r in range(3)] == [
            "-8.100",
            "-6.400",
            "-9.200",
        ]
        panel._on_pose_header_clicked(aff_col)
        qapp.processEvents()
        assert [table.item(r, aff_col).toolTip() for r in range(3)] == [
            "-6.400",
            "-8.100",
            "-9.200",
        ]
        assert panel._idx == 0
        assert panel.current_mol().GetProp("minimizedAffinity") == "-8.100"
        selected = table.selectionModel().selectedRows()
        assert selected
        assert table.item(selected[0].row(), aff_col).toolTip() == "-8.100"
        table.selectRow(0)
        qapp.processEvents()
        assert panel._idx == 1
        assert panel.current_mol().GetProp("minimizedAffinity") == "-6.400"
        panel._on_pose_header_clicked(aff_col)
        qapp.processEvents()
        assert [table.item(r, aff_col).toolTip() for r in range(3)] == [
            "-9.200",
            "-8.100",
            "-6.400",
        ]
        panel.window().close()
    finally:
        parent.close()
