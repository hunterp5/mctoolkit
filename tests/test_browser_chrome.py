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

"""Result browsers share one floating shell and preview theme."""

from __future__ import annotations

from molmanager.ui.browsers.chrome import (
    BROWSER_DATA_TABLE_QSS,
    BROWSER_PREVIEW_CANVAS_QSS,
    BROWSER_PREVIEW_FRAME_QSS,
    BROWSER_PREVIEW_STRUCT_QSS,
    BrowserHostDialog,
)
from molmanager.ui.qt_widget_utils import group_box_stylesheet_for
from molmanager.ui.browsers.pair_browser import PairBrowserDialog
from molmanager.ui.dockable_plot import PLOT_BODY_MARGINS, PLOT_BODY_SPACING
from molmanager.ui.metabolite_browser import MetaboliteBrowserDialog, MetaboliteBrowserWidget
from molmanager.ui.mmp_browser import MmpBrowserDialog
from molmanager.ui.pose_browser import PoseBrowserDialog, PoseBrowserWidget
from molmanager.ui.random_molecule_browser import (
    RandomMoleculeBrowserDialog,
    RandomMoleculeBrowserWidget,
)
from molmanager.ui.sali_browser import SaliBrowserDialog
from molmanager.ui.selection_browser import SelectionBrowserDialog, SelectionBrowserWidget


def test_dockable_browser_dialogs_share_host_shell():
    for cls in (
        SelectionBrowserDialog,
        PoseBrowserDialog,
        MetaboliteBrowserDialog,
        RandomMoleculeBrowserDialog,
    ):
        assert issubclass(cls, BrowserHostDialog)


def test_pair_browsers_share_pair_shell():
    assert issubclass(MmpBrowserDialog, PairBrowserDialog)
    assert issubclass(SaliBrowserDialog, PairBrowserDialog)


def test_canvas_browsers_use_shared_preview_theme(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    widgets = (
        SelectionBrowserWidget(ChemistryWorkspaceWindow()),
        MetaboliteBrowserWidget(None),
        RandomMoleculeBrowserWidget(None),
    )
    for panel in widgets:
        assert panel._preview_host.styleSheet() == BROWSER_PREVIEW_CANVAS_QSS
        assert panel._struct_label.styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        margins = panel.layout().contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == PLOT_BODY_MARGINS
        assert panel.layout().spacing() == PLOT_BODY_SPACING
        panel.deleteLater()


def test_pose_browser_uses_shared_frame_and_table_theme(qapp):  # noqa: ARG001
    panel = PoseBrowserWidget(None)
    assert panel._preview_host.styleSheet() == BROWSER_PREVIEW_FRAME_QSS
    assert panel._row_table.styleSheet() == BROWSER_DATA_TABLE_QSS
    panel.deleteLater()


def test_pair_browsers_use_shared_group_and_structure_theme(qapp):  # noqa: ARG001
    mmp = MmpBrowserDialog(None, [], activity_column="pIC50")
    sali = SaliBrowserDialog(None, [], activity_column="pIC50")
    for dlg in (mmp, sali):
        assert dlg._left_panel["struct"].styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        assert dlg._right_panel["struct"].styleSheet() == BROWSER_PREVIEW_STRUCT_QSS
        assert dlg._left_panel["box"].styleSheet() == group_box_stylesheet_for(
            dlg._left_panel["box"]
        )
        margins = dlg.layout().contentsMargins()
        assert (
            margins.left(),
            margins.top(),
            margins.right(),
            margins.bottom(),
        ) == PLOT_BODY_MARGINS
        assert dlg._row_table.styleSheet() == BROWSER_DATA_TABLE_QSS
        assert dlg._left_panel["box"].title() == ""
        assert dlg._left_panel["name"].text() == "Molecule A"
        assert dlg._right_panel["name"].text() == "Molecule B"
    assert sali._metrics_box.styleSheet() == group_box_stylesheet_for(sali._metrics_box)
    assert not hasattr(mmp, "_metrics_box")
    mmp.deleteLater()
    sali.deleteLater()


def test_sali_preview_pixmap_does_not_lock_vertical_resize(qapp):
    """A depiction rendered at the label size must not freeze the window height."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QSizePolicy

    from molmanager.analysis.sali_analysis import SaliPoint

    dlg = SaliBrowserDialog(
        None,
        [SaliPoint(0, 1, 2, 0.8, 2.0, 2.0, 10.0)],
        activity_column="pIC50",
    )
    dlg.resize(920, 620)
    dlg.show()
    qapp.processEvents()
    dlg.resize(920, 860)
    qapp.processEvents()

    for panel in (dlg._left_panel, dlg._right_panel):
        label = panel["struct"]
        policy = label.sizePolicy()
        assert policy.horizontalPolicy() == QSizePolicy.Ignored
        assert policy.verticalPolicy() == QSizePolicy.Ignored
        assert label.height() > label.minimumHeight()
        pixmap = QPixmap(max(label.width(), 1), max(label.height(), 1))
        pixmap.fill(Qt.white)
        label.setPixmap(pixmap)
    qapp.processEvents()

    layout = dlg.layout()
    assert layout.totalHeightForWidth(dlg.width()) < dlg.height() - 80
    assert dlg.sizeHint().height() < dlg.height() - 80
    grown = dlg.height()
    dlg.resize(dlg.width(), grown - 140)
    qapp.processEvents()
    assert dlg.height() == grown - 140
    dlg.resize(dlg.width() + 160, dlg.height())
    qapp.processEvents()
    assert dlg.width() == 920 + 160
    dlg.deleteLater()


def test_sali_side_name_is_inline_with_activity(qapp):  # noqa: ARG001
    from molmanager.analysis.sali_analysis import SaliPoint

    dlg = SaliBrowserDialog(
        None,
        [SaliPoint(0, 1, 2, 0.8, 2.0, 2.0, 10.0)],
        activity_column="pIC50",
    )
    for panel, name in (
        (dlg._left_panel, "Molecule A"),
        (dlg._right_panel, "Molecule B"),
    ):
        host = panel["caption_host"]
        row = host.layout()
        box = panel["box"].layout()
        assert panel["box"].title() == ""
        assert panel["name"].text() == name
        assert panel["activity"].text() == "pIC50: —"
        assert row.indexOf(panel["name"]) < row.indexOf(panel["activity"])
        assert box.indexOf(panel["struct"]) < box.indexOf(host)

    empty = SaliBrowserDialog(None, [], activity_column="pIC50")
    assert empty._left_panel["name"].text() == "Molecule A"
    assert empty._right_panel["name"].text() == "Molecule B"
    assert empty._left_panel["activity"].text() == "—"
    dlg.deleteLater()
    empty.deleteLater()


def test_sali_browser_pair_table_and_jump_field(qapp):  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QLineEdit

    from molmanager.analysis.sali_analysis import SaliPoint

    points = [
        SaliPoint(0, 1, 2, 0.8, 2.0, 2.0, 10.0),
        SaliPoint(1, 3, 4, 0.5, 1.0, -1.0, 2.0),
        SaliPoint(2, 5, 6, 0.2, 4.0, 4.0, 5.0),
    ]
    dlg = SaliBrowserDialog(
        None,
        points,
        activity_column="pIC50",
        fp_choice="Morgan",
        metric="Tanimoto",
        start_index=0,
    )
    assert not dlg._meta.isVisibleTo(dlg)
    assert dlg._nav_layout.indexOf(dlg._pair_index_host) < dlg._nav_layout.indexOf(dlg._btn_first)
    assert dlg._nav_layout.indexOf(dlg._cb_selected_only) > dlg._nav_layout.indexOf(dlg._btn_select)
    assert dlg.layout().indexOf(dlg._pair_index_host) == -1
    assert dlg._pair_index.value() == 1
    assert dlg._pair_count_label.text() == "/ 3"
    assert dlg._metrics_label.text().startswith("Similarity = ")
    assert "Morgan" not in dlg._metrics_label.text()
    assert "Tanimoto" not in dlg._metrics_label.text()
    root = dlg.layout()
    pair_index = next(
        i
        for i in range(root.count())
        if root.itemAt(i).layout() is not None
        and root.itemAt(i).layout().indexOf(dlg._left_panel["box"]) >= 0
    )
    assert dlg._metrics_box.styleSheet() == group_box_stylesheet_for(dlg._metrics_box)
    assert pair_index < root.indexOf(dlg._metrics_box) < root.indexOf(dlg._row_table)
    assert dlg._row_table.rowCount() == 2
    assert dlg._row_table.verticalHeaderItem(0).text() == "A"
    assert dlg._row_table.verticalHeaderItem(1).text() == "B"

    class _FakeApp:
        headers = ["ID_HIDDEN", "Structure", "Name", "pIC50"]
        mols: dict = {}
        table = None

        def logical_row_for_oid(self, oid: int) -> int:
            return {1: 0, 2: 1}.get(int(oid), -1)

        def _table_cell_text(self, row: int, col: int) -> str:
            return {
                (0, 2): "alpha",
                (0, 3): "1.0",
                (1, 2): "beta",
                (1, 3): "2.0",
            }.get((row, col), "")

    dlg._app = _FakeApp()
    dlg._update_ui()
    assert [dlg._row_table.horizontalHeaderItem(i).text() for i in range(2)] == [
        "Name",
        "pIC50",
    ]
    assert dlg._row_table.item(0, 0).text() == "alpha"
    assert dlg._row_table.item(1, 0).text() == "beta"
    assert dlg._row_table.item(0, 1).text() == "1.0"
    assert dlg._row_table.item(1, 1).text() == "2.0"

    edit = dlg._pair_index.lineEdit()
    assert isinstance(edit, QLineEdit)
    edit.setText("3")
    dlg._pair_index.interpretText()
    assert dlg._idx == 2
    assert dlg._pair_index.value() == 3
    assert dlg._row_table.item(0, 0).text() == ""

    dlg._pair_index.setFocus()
    qapp.processEvents()
    QTest.keyClick(dlg._pair_index, Qt.Key_Left)
    QTest.keyClick(dlg._pair_index, Qt.Key_Home)
    assert dlg._idx == 2

    dlg._step(-1)
    assert dlg._idx == 1
    assert dlg._pair_index.value() == 2

    empty = SaliBrowserDialog(None, [], activity_column="pIC50")
    assert empty._meta.isVisibleTo(empty)
    assert "No SALI pairs" in empty._meta.text()
    assert not empty._pair_index.isEnabled()
    assert empty._pair_count_label.text() == "/ 0"
    assert empty._row_table.rowCount() == 0

    dlg.deleteLater()
    empty.deleteLater()


def test_mmp_browser_uses_sali_layout(qapp):  # noqa: ARG001
    from molmanager.analysis.mmp_analysis import MmpPair

    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="C",
        smiles_b="CC",
        activity_a=1.0,
        activity_b=2.5,
        delta_activity=1.5,
        transform="[*:1]C>>[*:1]CC",
        core="*",
        sidechain_a="[*:1]C",
        sidechain_b="[*:1]CC",
    )
    dlg = MmpBrowserDialog(None, [pair], activity_column="pIC50")
    assert not dlg._meta.isVisibleTo(dlg)
    assert dlg._pair_index.value() == 1
    assert dlg._pair_count_label.text() == "/ 1"
    assert dlg._nav_layout.indexOf(dlg._pair_index_host) < dlg._nav_layout.indexOf(dlg._btn_first)
    assert dlg._nav_layout.indexOf(dlg._btn_write) > dlg._nav_layout.indexOf(dlg._btn_select)
    assert dlg._nav_layout.indexOf(dlg._cb_selected_only) > dlg._nav_layout.indexOf(dlg._btn_write)
    assert dlg._left_panel["box"].title() == ""
    assert dlg._left_panel["name"].text() == "Molecule A"
    assert dlg._left_panel["activity"].text() == "pIC50: 1"
    assert dlg._right_panel["activity"].text() == "pIC50: 2.5"
    assert not hasattr(dlg, "_metrics_box")
    assert not hasattr(dlg, "_transform_preview")
    root = dlg.layout()
    pair_index = next(
        i
        for i in range(root.count())
        if root.itemAt(i).layout() is not None
        and root.itemAt(i).layout().indexOf(dlg._left_panel["box"]) >= 0
    )
    assert pair_index < root.indexOf(dlg._row_table)
    assert dlg._row_table.rowCount() == 2
    assert dlg._row_table.verticalHeaderItem(0).text() == "A"
    assert dlg._row_table.verticalHeaderItem(1).text() == "B"

    empty = MmpBrowserDialog(None, [], activity_column="pIC50")
    assert empty._meta.isVisibleTo(empty)
    assert "No matched molecular pairs" in empty._meta.text()
    assert not empty._pair_index.isEnabled()
    assert empty._row_table.rowCount() == 0
    dlg.deleteLater()
    empty.deleteLater()


def test_pair_browsers_highlight_variable_atoms(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    from rdkit import Chem

    from molmanager.analysis.mmp_analysis import MmpPair
    from molmanager.analysis.mmp_depict import highlight_atoms_for_pair
    from molmanager.analysis.sali_analysis import SaliPoint
    from molmanager.ui.browsers.pair_browser import PairBrowserDialog

    phenol = Chem.MolFromSmiles("Oc1ccccc1")
    anisole = Chem.MolFromSmiles("COc1ccccc1")
    ha, hb = highlight_atoms_for_pair(phenol, anisole)
    assert ha or hb
    captured: list[tuple[int, list[int]]] = []

    def _capture(self, mol, pw, ph, highlight_atoms):  # noqa: ARG001
        captured.append((int(mol.GetNumAtoms()), [int(i) for i in highlight_atoms]))
        pm = QPixmap(max(int(pw), 1), max(int(ph), 1))
        pm.fill(Qt.white)
        return pm

    monkeypatch.setattr(PairBrowserDialog, "_render_highlighted", _capture)

    class _App:
        mols = {1: phenol, 2: anisole}
        headers: list[str] = []

        def logical_row_for_oid(self, _oid: int) -> int:
            return -1

    sali = SaliBrowserDialog(
        None,
        [SaliPoint(0, 1, 2, 0.8, 1.0, 1.0, 5.0)],
        activity_column="pIC50",
    )
    sali._app = _App()
    sali._update_ui()
    mol_calls = [atoms for n_atoms, atoms in captured if n_atoms >= phenol.GetNumAtoms()]
    assert mol_calls[0] == ha
    assert mol_calls[1] == hb

    captured.clear()
    pair = MmpPair(
        oid_a=1,
        oid_b=2,
        smiles_a="Oc1ccccc1",
        smiles_b="COc1ccccc1",
        activity_a=1.0,
        activity_b=2.0,
        delta_activity=1.0,
        transform="[*:1]O>>[*:1]OC",
        core="*",
        sidechain_a="[*:1]O",
        sidechain_b="[*:1]OC",
    )
    mmp = MmpBrowserDialog(None, [pair], activity_column="pIC50")
    mmp._app = _App()
    mmp._update_ui()
    mol_calls = [atoms for n_atoms, atoms in captured if n_atoms >= phenol.GetNumAtoms()]
    assert mol_calls[0] == ha
    assert mol_calls[1] == hb
    sali.deleteLater()
    mmp.deleteLater()


def test_render_highlighted_marks_changed_atoms(qapp, monkeypatch):  # noqa: ARG001
    from rdkit import Chem

    seen: dict = {}

    def _fake_highlight(mol, atoms, colour):  # noqa: ARG001
        seen["colour"] = colour
        seen["atoms"] = [int(i) for i in atoms]
        from molmanager.chem.depiction_scene import SceneHighlight

        return SceneHighlight()

    def _fake_pixmap(mol, pw, ph, highlight=None):  # noqa: ARG001
        from PyQt5.QtGui import QPixmap

        seen["highlight"] = highlight
        return QPixmap(max(int(pw), 1), max(int(ph), 1))

    monkeypatch.setattr("molmanager.chem.depiction_scene.atom_set_highlight", _fake_highlight)
    monkeypatch.setattr("molmanager.table.structure_image.molecule_pixmap", _fake_pixmap)
    dlg = SaliBrowserDialog(None, [], activity_column="pIC50")
    mol = Chem.MolFromSmiles("CCO")
    pm = dlg._render_highlighted(mol, 40, 30, [0, 2])
    assert pm is not None and not pm.isNull()
    assert seen["colour"] == (0.95, 0.55, 0.15)
    assert seen["atoms"] == [0, 2]
    assert seen["highlight"] is not None
    dlg.deleteLater()
