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

"""Sketcher reaction-arrow geometry and export."""

from __future__ import annotations

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QLabel, QWidget

from molmanager.table.structure_depiction_layout import reaction_depict_size
from molmanager.chem.reaction_file_io import (
    RXN_NAME_HEADER,
    RXN_PRODUCTS_HEADER,
    RXN_REACTANTS_HEADER,
    RXN_SMARTS_HEADER,
    looks_like_reaction_smarts,
    parse_reaction_smarts,
)
from molmanager.chem.structure_2d_depiction import ReactionDrawSpec
from molmanager.ui.compound_table_model import CompoundTableModel
from molmanager.ui.compound_table_view import CompoundTableView
from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.sketch_reactions import (
    fragment_side,
    join_reaction_string,
    plus_sign_positions,
    snap_arrow_end,
)
from molmanager.ui.sketcher.widget import SketchWidget


def test_fragment_side_tail_is_reactant() -> None:
    assert fragment_side(0.0, 0.0, 10.0, 0.0, 40.0, 0.0) == "reactant"
    assert fragment_side(50.0, 0.0, 10.0, 0.0, 40.0, 0.0) == "product"


def test_join_reaction_string() -> None:
    assert join_reaction_string(["CCO", "O"], ["CC=O"]) == "CCO.O>>CC=O"
    assert join_reaction_string([], []) == ""


def test_plus_sign_positions_order_along_arrow() -> None:
    pts = plus_sign_positions([(0.0, 0.0), (20.0, 0.0)], 0.0, 0.0, 40.0, 0.0)
    assert len(pts) == 1
    assert pts[0] == (10.0, 0.0)


def test_snap_arrow_end_horizontal() -> None:
    x, y = snap_arrow_end(0.0, 0.0, 40.0, 3.0, snap=True)
    assert abs(y) < 1.0
    assert x > 30.0


def _ethanol_and_ethene(w: SketchWidget) -> None:
    """CCO left of the origin, C=C to the right (two isolated fragments)."""
    left = []
    for i, el in enumerate(("C", "C", "O")):
        nid = w.next_id
        w.next_id += 1
        w.nodes.append({"id": nid, "pos": QPoint(20 + i * 40, 40), "element": el})
        left.append(nid)
    w.bonds.append(_bond_make(left[0], left[1], 1, 0))
    w.bonds.append(_bond_make(left[1], left[2], 1, 0))
    right = []
    for i in range(2):
        nid = w.next_id
        w.next_id += 1
        w.nodes.append({"id": nid, "pos": QPoint(220 + i * 40, 40), "element": "C"})
        right.append(nid)
    w.bonds.append(_bond_make(right[0], right[1], 2, 0))


def test_sketch_reaction_export(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    _ethanol_and_ethene(w)
    w.reaction_arrow = (QPoint(140, 40), QPoint(190, 40))
    smarts = w.to_reaction_smarts()
    assert looks_like_reaction_smarts(smarts)
    assert ">>" in smarts
    left, right = smarts.split(">>", 1)
    assert left
    assert right
    rxn = parse_reaction_smarts(smarts)
    assert rxn is not None
    assert int(rxn.GetNumReactantTemplates()) >= 1
    assert int(rxn.GetNumProductTemplates()) >= 1


def test_sketch_reaction_arrow_undo(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w._set_reaction_arrow((QPoint(10, 10), QPoint(80, 10)))
    assert w.reaction_arrow is not None
    w.undo()
    assert w.reaction_arrow is None
    w.redo()
    assert w.reaction_arrow is not None
    w.clear()
    assert w.reaction_arrow is None
    w.undo()
    assert w.reaction_arrow is not None


class _FakeTableApp(QWidget):
    """Minimal table host for sketcher Add to Table."""

    def __init__(self, headers: list[str] | None = None) -> None:
        super().__init__()
        self.headers = list(headers) if headers else []
        self._table_model = CompoundTableModel(list(self.headers))
        self.table = CompoundTableView()
        self.table.set_compound_model(self._table_model)
        self.next_oid = 1
        self.mols: dict[int, object] = {}
        self.status_label = QLabel("")
        self.render_jobs: list[tuple] = []

    def start_render_worker(self, oid, mol, w=None, h=None, **kwargs):
        self.render_jobs.append((int(oid), mol, w, h, kwargs))


def _dialog_with_reaction(parent: QWidget) -> SketcherDialog:
    dlg = SketcherDialog(parent)
    _ethanol_and_ethene(dlg.canvas)
    dlg.canvas.reaction_arrow = (QPoint(140, 40), QPoint(190, 40))
    return dlg


def test_append_reaction_only_smarts_and_auto_render(qapp) -> None:  # noqa: ARG001
    app = _FakeTableApp()
    dlg = _dialog_with_reaction(app)
    try:
        assert dlg._append_reaction_from_sketch() == 1
        assert RXN_SMARTS_HEADER in app.headers
        assert "SMILES" not in app.headers
        assert RXN_REACTANTS_HEADER not in app.headers
        assert RXN_PRODUCTS_HEADER not in app.headers
        assert RXN_NAME_HEADER not in app.headers
        assert app._table_model.rowCount() == 1
        ci = app.headers.index(RXN_SMARTS_HEADER)
        smarts = app._table_model.cell_text(0, ci)
        assert looks_like_reaction_smarts(smarts)
        oid = app._table_model.row_oid(0)
        assert oid not in app.mols
        assert len(app.render_jobs) == 1
        job_oid, spec, width, height, kwargs = app.render_jobs[0]
        assert job_oid == oid
        assert isinstance(spec, ReactionDrawSpec)
        assert spec.smarts == smarts
        assert (width, height) == reaction_depict_size()
        assert kwargs.get("skip_mol_props") is True
    finally:
        dlg.close()


def test_append_reaction_does_not_fill_smiles_on_molecule_table(qapp) -> None:  # noqa: ARG001
    app = _FakeTableApp(["ID_HIDDEN", "Structure", "SMILES"])
    app._table_model.append_row(1, {"SMILES": "CCO"})
    app.next_oid = 2
    app.mols[1] = object()
    dlg = _dialog_with_reaction(app)
    try:
        assert dlg._append_reaction_from_sketch() == 1
        assert "SMILES" in app.headers
        assert RXN_REACTANTS_HEADER not in app.headers
        smiles_ci = app.headers.index("SMILES")
        rxn_ci = app.headers.index(RXN_SMARTS_HEADER)
        assert app._table_model.cell_text(0, smiles_ci) == "CCO"
        assert (app._table_model.cell_text(1, smiles_ci) or "") == ""
        assert looks_like_reaction_smarts(app._table_model.cell_text(1, rxn_ci))
        assert 2 not in app.mols
    finally:
        dlg.close()
