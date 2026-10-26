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
    assemble_rgroup_product,
    compute_design_snapshot,
    series_core_from_labels,
    suggest_core_column,
)


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
        assert panel._strip._caption.text() == "toluene"
        assert panel._strip._mpo_value.text() != "—"
        assert panel._strip._value_labels["MW"].text().startswith("92")
    finally:
        panel.shutdown()
        panel.close()
        panel.deleteLater()
        qapp.processEvents()


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
        assert texts[texts.index("Open in Sketcher…") + 1] == "Open in Design Studio"
        assert opened["kwargs"] == {"caption": "Row 0"}
        assert Chem.MolToSmiles(opened["mol"]) == "CCN"
    finally:
        window.close()
