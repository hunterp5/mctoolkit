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

"""R-group assembly and the druglike score used by the design studio."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.analysis.design_studio import (
    DesignAssemblyError,
    SeriesRow,
    assemble_rgroup_product,
    compute_design_snapshot,
    mmp_suggestions,
    rgroup_swap_suggestions,
    series_core_from_labels,
    suggest_core_column,
)
from molmanager.analysis.mmp_analysis import MmpPair


def test_assemble_methyl_and_chloro_on_a_phenyl_core():
    smiles = assemble_rgroup_product(
        "c1ccc([*:1])c([*:2])c1",
        [("R1", "C[*:1]"), ("R2", "Cl[*:2]")],
    )
    assert smiles == Chem.MolToSmiles(Chem.MolFromSmiles("Cc1ccccc1Cl"))


def test_hydrogen_cap_is_removed_after_zip():
    smiles = assemble_rgroup_product(
        "c1ccc([*:2])c([*:1])c1",
        [("R1", "Cl[*:1]"), ("R2", "[H][*:2]")],
    )
    assert smiles == "Clc1ccccc1"


def test_label_without_an_attachment_point_is_rejected():
    with pytest.raises(DesignAssemblyError, match="R2"):
        assemble_rgroup_product("c1ccc([*:1])cc1", [("R1", "C[*:1]"), ("R2", "Me")])


def test_core_column_follows_the_decomposition_prefix():
    headers = ["pIC50", "RGD_R2", "RGD_Core", "RGD_R1", "Other_Core"]
    assert suggest_core_column(headers, "RGD_R1") == "RGD_Core"
    assert suggest_core_column(["Core", "R1", "R2"], "R1") == "Core"
    assert suggest_core_column(["R1", "R2"], "R1") is None


def test_series_core_states():
    assert series_core_from_labels(["c1ccc([*:1])cc1", "c1ccc([*:1])cc1", "N/A"]) == (
        "c1ccc([*:1])cc1",
        "ok",
    )
    assert series_core_from_labels(["", "N/A"]) == (None, "missing")
    assert series_core_from_labels(["c1ccc([*:1])cc1", "c1ccc([*:2])cc1"])[1] == "conflict"


def test_design_snapshot_scores_anisole():
    snapshot = compute_design_snapshot(Chem.MolFromSmiles("COc1ccccc1"))
    assert snapshot.error is None
    assert snapshot.mpo is not None
    assert 0.0 <= snapshot.mpo <= 1.0
    by_key = {term.key: term for term in snapshot.terms}
    assert by_key["MW"].value == pytest.approx(108.14, abs=0.1)
    assert by_key["MW"].desirability == 1.0
    assert snapshot.hbd == 0
    assert snapshot.hba == 1
    assert snapshot.cns_mpo is not None
    assert snapshot.logd is not None


def test_empty_sketch_has_no_score():
    snapshot = compute_design_snapshot(None)
    assert snapshot.error == "empty"
    assert snapshot.mpo is None


class _StudioApp:
    def __init__(self):
        self.status_label = self
        self.messages: list[str] = []
        self.smiles = ""
        self.caption = ""
        self.mol = None

    def setText(self, text: str) -> None:
        self.messages.append(text)

    def open_design_studio_for_smiles(self, smiles: str, *, caption: str = "") -> None:
        self.smiles = smiles
        self.caption = caption

    def open_design_studio_for_molecule(self, mol, *, caption: str = "") -> None:
        self.mol = mol
        self.caption = caption


def test_clicking_an_unmade_pair_sends_its_smiles(qapp):
    from molmanager.analysis.sar_matrix import SarObservation, build_sar_matrix
    from molmanager.ui.sar_matrix_panel import SarMatrixPanel

    matrix = build_sar_matrix(
        [
            SarObservation(1, "C[*:1]", "[H][*:2]", "", 6.0),
            SarObservation(2, "Cl[*:1]", "F[*:2]", "", 7.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    page = matrix.page(0)
    target = None
    for row, row_label in enumerate(page.row_labels):
        for col, col_label in enumerate(page.col_labels):
            if (row_label, col_label) not in page.cells:
                target = (row, col, row_label, col_label)
                break
        if target is not None:
            break
    assert target is not None
    app = _StudioApp()
    panel = SarMatrixPanel(app)
    panel.set_matrix(
        matrix,
        higher_is_better=True,
        series_core="c1ccc([*:1])c([*:2])c1",
        series_core_state="ok",
    )
    panel.show()
    qapp.processEvents()
    try:
        panel._on_cell_clicked(target[0], target[1])
        assert app.smiles == assemble_rgroup_product(
            "c1ccc([*:1])c([*:2])c1",
            [("R1", target[2]), ("R2", target[3])],
        )
        assert target[2] in app.caption
        assert target[3] in app.caption
    finally:
        panel.close()
        panel.deleteLater()
        qapp.processEvents()


def test_conflicting_cores_do_not_build_a_cell(qapp):
    from molmanager.analysis.sar_matrix import SarObservation, build_sar_matrix
    from molmanager.ui.sar_matrix_panel import SarMatrixPanel

    matrix = build_sar_matrix(
        [
            SarObservation(1, "C[*:1]", "[H][*:2]", "", 6.0),
            SarObservation(2, "Cl[*:1]", "F[*:2]", "", 7.0),
        ],
        row_axis="R1",
        col_axis="R2",
        activity_axis="pIC50",
    )
    page = matrix.page(0)
    empty = next(
        (row, col)
        for row, row_label in enumerate(page.row_labels)
        for col, col_label in enumerate(page.col_labels)
        if (row_label, col_label) not in page.cells
    )
    app = _StudioApp()
    panel = SarMatrixPanel(app)
    panel.set_matrix(matrix, higher_is_better=True, series_core_state="conflict")
    panel.show()
    qapp.processEvents()
    try:
        panel._on_cell_clicked(*empty)
        assert app.smiles == ""
        assert any("more than one core" in message for message in app.messages)
    finally:
        panel.close()
        panel.deleteLater()
        qapp.processEvents()


def test_studio_strip_scores_a_loaded_molecule(qapp):
    from molmanager.ui.design_studio_panel import DesignStudioPanel

    panel = DesignStudioPanel(None)
    panel._strip._start_or_coalesce_ionization = lambda *_args, **_kwargs: None
    try:
        assert not panel._sketcher.isWindow()
        assert panel.load_molecule(Chem.MolFromSmiles("Cc1ccccc1"), caption="toluene")
        qapp.processEvents()
        panel._strip._refresh_now()
        assert panel._strip._value_labels["MW"].text().startswith("92")
        assert panel._strip._druglike_details.isHidden() is False
        assert panel._strip._hbd.text() == "0"
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        qapp.processEvents()


def test_mmp_suggestion_applies_a_gain_and_marks_a_cliff():
    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="Cc1ccccc1",
        smiles_b="Clc1ccccc1",
        activity_a=5.0,
        activity_b=6.5,
        delta_activity=1.5,
        transform="C[*:1]>>Cl[*:1]",
        core="c1ccc([*:1])cc1",
        sidechain_a="C[*:1]",
        sidechain_b="Cl[*:1]",
    )
    found = mmp_suggestions(Chem.MolFromSmiles("Cc1ccccc1"), [pair])
    assert len(found) == 1
    assert found[0].smiles == "Clc1ccccc1"
    assert "median Δ +1.50" in found[0].detail
    assert "activity cliff" in found[0].detail
    assert "SALI" in found[0].detail


def test_rgroup_swap_estimates_the_series_shift():
    core = "c1ccc([*:1])c([*:2])c1"
    rows = [
        SeriesRow(core, (("R1", "C[*:1]"), ("R2", "[H][*:2]")), 5.0, "Cc1ccccc1"),
        SeriesRow(core, (("R1", "Cl[*:1]"), ("R2", "[H][*:2]")), 7.0, "Clc1ccccc1"),
        SeriesRow(core, (("R1", "C[*:1]"), ("R2", "F[*:2]")), 9.0, ""),
    ]
    found = rgroup_swap_suggestions("Clc1ccccc1", rows)
    assert len(found) == 1
    assert found[0].smiles == assemble_rgroup_product(core, (("R1", "Cl[*:1]"), ("R2", "F[*:2]")))
    assert "10.00" in found[0].detail
    assert "+3.00" in found[0].detail


def test_structure_menu_opens_design_studio(qapp, monkeypatch):
    from PyQt5.QtWidgets import QMenu

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    window = ChemistryWorkspaceWindow()
    window.start_render_worker = lambda *_args, **_kwargs: None
    window.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    window._table_model.set_headers(list(window.headers))
    window.mols[0] = Chem.MolFromSmiles("CCN")
    window._table_model.append_row(0, {"SMILES": "CCN"})
    window.next_oid = 1
    opened: dict = {}

    def fake_exec(menu, *_args, **_kwargs):
        opened["texts"] = [act.text() for act in menu.actions() if act.text()]
        return next(act for act in menu.actions() if act.text() == "Open in Design Studio")

    def capture(mol=None, **kwargs):
        opened["mol"] = mol
        opened["kwargs"] = kwargs

    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    window.open_design_studio_for_molecule = capture
    try:
        window.show()
        qapp.processEvents()
        proxy = window.table.model()
        source = window._table_model.index(0, 1)
        rect = window.table.visualRect(proxy.mapFromSource(source))
        window.show_table_menu(rect.center())
        texts = opened["texts"]
        assert texts[texts.index("Open in Sketcher") + 1] == "Open in Design Studio"
        assert opened["kwargs"] == {}
        assert Chem.MolToSmiles(opened["mol"]) == "CCN"
    finally:
        window.close()


def test_design_studio_keeps_other_shortcuts_and_takes_undo(qapp):
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QKeySequence
    from PyQt5.QtWidgets import QAction, QWidget

    from molmanager.ui.design_studio_panel import DesignStudioPanel

    class Host(QWidget):
        def __init__(self) -> None:
            super().__init__()
            undo = QAction("Undo", self)
            undo.setShortcut(QKeySequence("Ctrl+Z"))
            undo.setShortcutContext(Qt.ApplicationShortcut)
            other = QAction("Toggle Filter Panel", self)
            other.setShortcut(QKeySequence("Ctrl+Shift+L"))
            other.setShortcutContext(Qt.ApplicationShortcut)
            self.addAction(undo)
            self.addAction(other)
            self._hotkey_actions = {
                "edit.undo": undo,
                "edit.redo": QAction(self),
                "edit.copy": QAction(self),
                "edit.paste": QAction(self),
                "edit.delete_selection": QAction(self),
                "tools.toggle_filter_panel": other,
            }
            self.undo = undo
            self.other = other

    host = Host()
    panel = DesignStudioPanel(host)
    dialog = panel.create_floating_dialog(host)
    try:
        dialog.show()
        dialog.activateWindow()
        dialog.raise_()
        qapp.processEvents()
        panel._sketcher._sync_parent_edit_hotkeys()
        assert host.other.isEnabled() is True
        assert host.undo.isEnabled() is False
        assert panel._sketcher.isWindow() is False
    finally:
        panel.shutdown()
        dialog._force_close = True
        dialog.close()
        host.close()
        qapp.processEvents()


def test_design_studio_has_chemistry_between_view_and_settings(qapp):
    from PyQt5.QtWidgets import QMenuBar, QWidget

    from molmanager.ui.design_studio_panel import DesignStudioPanel
    from molmanager.ui.sketcher.dialog import SketcherDialog

    panel = DesignStudioPanel(None)
    try:
        bar = panel._sketcher.findChild(QMenuBar)
        names = [action.text() for action in bar.actions()]
        assert names.index("Chemistry") == names.index("View") + 1
        assert names.index("Settings") == names.index("Chemistry") + 1
        chemistry = bar.actions()[names.index("Chemistry")].menu()
        assert [action.text() for action in chemistry.actions()] == [
            "Bioisosteric Replacement…"
        ]
    finally:
        panel.shutdown()
        panel.close()

    sketcher = SketcherDialog(QWidget())
    try:
        bar = sketcher.findChild(QMenuBar)
        assert "Chemistry" not in [action.text() for action in bar.actions()]
    finally:
        sketcher.close()


def test_closing_the_design_studio_asks_first(qapp, monkeypatch):
    from PyQt5.QtWidgets import QMessageBox, QWidget

    from molmanager.ui.design_studio_panel import DesignStudioPanel

    host = QWidget()
    panel = DesignStudioPanel(host)
    dialog = panel.create_floating_dialog(host)
    answers = {"value": QMessageBox.No}
    monkeypatch.setattr(QMessageBox, "question", lambda *_a, **_k: answers["value"])
    try:
        dialog.show()
        qapp.processEvents()
        dialog.close()
        qapp.processEvents()
        assert dialog.isVisible()
        answers["value"] = QMessageBox.Yes
        dialog.close()
        qapp.processEvents()
        assert dialog.isVisible() is False
    finally:
        dialog._force_close = True
        dialog.close()
        host.close()
        qapp.processEvents()


def _menu_labels(sketcher, title: str) -> list[str]:
    bar = sketcher.layout().menuBar()
    for action in bar.actions():
        menu = action.menu()
        if menu is not None and action.text() == title:
            return [item.text().replace("&", "") for item in menu.actions()]
    return []


def test_design_studio_has_original_size_clear_and_ring_pictures(qapp):
    from PyQt5.QtCore import QPoint

    from molmanager.ui.design_studio_panel import DesignStudioPanel

    panel = DesignStudioPanel(None)
    panel._strip._start_or_coalesce_ionization = lambda *_args, **_kwargs: None
    dialog = panel.create_floating_dialog(None)
    dialog.resize(1100, 700)
    dialog.show()
    qapp.processEvents()
    sketcher = panel._sketcher
    try:
        assert "Clear Sketch" in _menu_labels(sketcher, "Edit")
        assert "Original size" in _menu_labels(sketcher, "View")
        assert "Fit structure to window" in _menu_labels(sketcher, "View")
        assert sketcher.tb_structure_status.parent() is panel._status
        assert sketcher.tb_structure_status.isVisible()
        assert not sketcher._status_bar.isVisible()
        assert panel._status.height() == sketcher._status_bar.height()
        assert not panel._status.isSizeGripEnabled()
        benzene = sketcher._ring_btn_by_key["Benzene"].icon()
        pyridine = sketcher._ring_btn_by_key["Pyridine"].icon()
        assert not benzene.isNull() and not pyridine.isNull()
        assert benzene.cacheKey() != pyridine.cacheKey()

        assert panel.load_molecule(Chem.MolFromSmiles("c1ccncc1"), caption="pyridine")
        qapp.processEvents()
        assert sketcher._act_original_size.isEnabled()
        opened = [(node["id"], node["pos"].x(), node["pos"].y()) for node in sketcher.canvas.nodes]
        for node in sketcher.canvas.nodes:
            node["pos"] = QPoint(node["pos"].x() + 70, node["pos"].y() - 30)
        sketcher.canvas._view_scale = 2.0
        sketcher._act_original_size.trigger()
        restored = [
            (node["id"], node["pos"].x(), node["pos"].y()) for node in sketcher.canvas.nodes
        ]
        assert restored == opened
        assert sketcher.canvas._view_scale == 1.0
        assert panel._status.currentMessage().startswith("Restored the size")

        sketcher._act_canvas_clear.trigger()
        assert sketcher.canvas.nodes == []
        assert sketcher._act_original_size.isEnabled() is False
        assert panel._status.currentMessage() == "Sketch cleared."
    finally:
        panel.shutdown()
        dialog._force_close = True
        dialog.close()
        qapp.processEvents()


def test_design_list_collects_suggestions_and_bioisosteres(qapp):
    from types import SimpleNamespace

    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.design_studio_panel import DesignStudioPanel

    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="Cc1ccccc1",
        smiles_b="Clc1ccccc1",
        activity_a=5.0,
        activity_b=6.5,
        delta_activity=1.5,
        transform="C[*:1]>>Cl[*:1]",
        core="c1ccc([*:1])cc1",
        sidechain_a="C[*:1]",
        sidechain_b="Cl[*:1]",
    )
    sent: list[str] = []
    app = SimpleNamespace(
        _mmp_last_pairs=[pair],
        mols={1: Chem.MolFromSmiles("CCO")},
        status_label=QLabel(),
    )
    panel = DesignStudioPanel(app)
    panel._strip._start_or_coalesce_ionization = lambda *_args, **_kwargs: None
    panel._sketcher._append_molecules_from_smiles_parts = (
        lambda parts: sent.extend(parts) or len(parts)
    )
    try:
        assert panel._design_list._add_btn.text() == "Add suggestions"
        assert panel._design_list._send_btn.text() == "Send to table"
        assert panel.load_molecule(Chem.MolFromSmiles("Cc1ccccc1"))
        panel._design_list.add_bioisosteres([("Carboxylic acid to tetrazole", "CC(=O)O")])
        panel._design_list.add_suggestions()
        labels = _design_labels(panel)
        assert any(label.startswith("Bioisostere") for label in labels)
        assert any(label.startswith("Suggestion") for label in labels)
        count = panel._design_list._list.count()
        panel._design_list.add_suggestions()
        assert panel._design_list._list.count() == count
        assert "already on the design list" in panel._status.currentMessage()

        _select_where(panel, lambda item: item.text().startswith("Suggestion"))
        panel._design_list.send_selected()
        assert sent == ["Clc1ccccc1"]

        sent.clear()
        panel._design_list.add_bioisosteres([("Known", "CCO")])
        ethanol = Chem.MolToSmiles(Chem.MolFromSmiles("CCO"))
        _select_where(panel, lambda item: item.data(Qt.UserRole) == ethanol)
        panel._design_list.send_selected()
        assert sent == []
        assert "already in the table" in panel._status.currentMessage()
    finally:
        panel.shutdown()
        panel.close()
        qapp.processEvents()


def test_bioisostere_replacement_adds_to_the_design_list(qapp, monkeypatch):
    from PyQt5.QtWidgets import QDialog

    from molmanager.chem.bioisosteres import get_bioisostere
    from molmanager.ui.design_studio_panel import DesignStudioPanel
    from molmanager.ui.sketcher.bioisostere_dialog import BioisostereReplacementDialog

    acid = get_bioisostere("acid_to_tetrazole")
    monkeypatch.setattr(
        "molmanager.chem.bioisosteres.matching_bioisosteres",
        lambda _mol, _atom_indices: ((acid, ("Cc1nn[nH]n1",)),),
    )
    monkeypatch.setattr(BioisostereReplacementDialog, "exec_", lambda _self: QDialog.Accepted)
    panel = DesignStudioPanel(None)
    panel._strip._start_or_coalesce_ionization = lambda *_args, **_kwargs: None
    try:
        assert panel.load_molecule(Chem.MolFromSmiles("CC(=O)O"))
        before = panel.current_smiles()
        canvas = panel._sketcher.canvas
        canvas.selected_nodes = [int(node["id"]) for node in canvas.nodes]
        panel._sketcher._open_bioisostere_replacement()
        assert panel.current_smiles() == before
        assert any("tetrazole" in label for label in _design_labels(panel))
        assert panel._status.currentMessage() == "Added 1 bioisostere to the design list."
    finally:
        panel.shutdown()
        panel.close()
        qapp.processEvents()


def _design_labels(panel) -> list[str]:
    widget = panel._design_list._list
    return [widget.item(index).text() for index in range(widget.count())]


def _select_where(panel, predicate) -> None:
    widget = panel._design_list._list
    widget.clearSelection()
    for index in range(widget.count()):
        item = widget.item(index)
        item.setSelected(bool(predicate(item)))
