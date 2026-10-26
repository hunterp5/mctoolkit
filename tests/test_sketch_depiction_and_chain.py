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

"""Sketcher depiction scene, Clean Up layout, chain tool, and view navigation."""

from __future__ import annotations

import math

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QImage, QKeyEvent, QPainter
from PyQt5.QtWidgets import QWidget
from rdkit import Chem

from molmanager.chem.depiction_layout import LayoutOptions
from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.constants import SKETCH_COORD_SCALE
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.sketch_grid import chain_points
from molmanager.ui.sketcher.widget import SketchWidget


def _ethanol(widget: SketchWidget) -> None:
    widget.nodes = [
        {"id": 0, "pos": QPoint(80, 160), "element": "C"},
        {"id": 1, "pos": QPoint(140, 120), "element": "C"},
        {"id": 2, "pos": QPoint(200, 160), "element": "O"},
    ]
    widget.bonds = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0)]
    widget.next_id = 3


def test_chain_points_follow_the_hex_grid() -> None:
    points = chain_points((0.0, 0.0), (200.0, 0.0), 60.0)
    assert len(points) >= 3
    lengths = []
    previous = (0.0, 0.0)
    for point in points:
        lengths.append(math.hypot(point[0] - previous[0], point[1] - previous[1]))
        previous = point
    assert all(abs(length - 60.0) < 0.2 for length in lengths)
    first = math.atan2(points[0][1], points[0][0])
    second = math.atan2(points[1][1] - points[0][1], points[1][0] - points[0][0])
    turn = abs((second - first + math.pi) % (2 * math.pi) - math.pi)
    assert abs(turn - math.radians(60)) < 0.05


def test_canvas_scene_stays_on_sketch_coordinates(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    _ethanol(widget)
    image = QImage(widget.size(), QImage.Format_ARGB32)
    painter = QPainter(image)
    try:
        widget._paint_sketch_structure(painter, widget._acs_style())
    finally:
        painter.end()
    assert widget._last_structure_paint == "scene"
    scene = widget.depiction_scene_for_canvas()
    assert scene is not None
    for node, (sx, sy) in zip(widget.nodes, scene.atoms):
        assert abs(sx * SKETCH_COORD_SCALE - node["pos"].x()) < 1.5
        assert abs(-sy * SKETCH_COORD_SCALE - node["pos"].y()) < 1.5


def test_rgroup_label_uses_the_scene(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 300)
    widget.nodes = [
        {"id": 0, "pos": QPoint(80, 120), "element": "C"},
        {"id": 1, "pos": QPoint(140, 120), "element": "R1"},
    ]
    widget.bonds = [_bond_make(0, 1, 1, 0)]
    widget.next_id = 2
    scene = widget.depiction_scene_for_canvas()
    assert scene is not None, widget._depiction_scene_reason
    texts = ["".join(piece.text for piece in label.pieces) for label in scene.labels]
    assert "R1" in texts


def test_wildcard_list_is_a_scene_label(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 300)
    widget.nodes = [
        {"id": 0, "pos": QPoint(80, 120), "element": "C"},
        {
            "id": 1,
            "pos": QPoint(140, 120),
            "element": "*",
            "wildcard_els": ["N", "O"],
        },
    ]
    widget.bonds = [_bond_make(0, 1, 1, 0)]
    widget.next_id = 2
    scene = widget.depiction_scene_for_canvas()
    assert scene is not None, widget._depiction_scene_reason
    texts = ["".join(piece.text for piece in label.pieces) for label in scene.labels]
    assert any("N" in text and "O" in text for text in texts)


def test_cleanup_calls_depiction_layout_without_cell_rotation(qapp, monkeypatch) -> None:
    widget = SketchWidget()
    widget.resize(700, 500)
    _ethanol(widget)
    seen: dict[str, LayoutOptions] = {}
    real = __import__(
        "molmanager.chem.depiction_layout", fromlist=["layout_for_drawing"]
    ).layout_for_drawing

    def wrapped(mol, options=None):
        seen["options"] = options
        return real(mol, options)

    monkeypatch.setattr("molmanager.chem.depiction_layout.layout_for_drawing", wrapped)
    assert widget.cleanup_layout_2d()
    assert seen["options"] == LayoutOptions(
        macrocycle_coordgen=True,
        flip_inward_substituents=True,
        rotate_to_cell=False,
    )


def test_chain_drag_is_one_undo_step(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(640, 480)
    widget.chain_mode = True
    widget.nodes = [{"id": 0, "pos": QPoint(100, 200), "element": "C"}]
    widget.next_id = 1
    press = QPoint(100, 200)
    target = QPoint(280, 200)
    assert widget.finish_carbon_chain(0, press, target)
    assert len(widget.nodes) >= 3
    assert len(widget._undo) == 1
    assert widget._undo[-1][0] == "add_chain"
    widget.undo()
    assert len(widget.nodes) == 1
    widget.redo()
    assert len(widget.nodes) >= 3


def test_zoom_about_cursor_keeps_the_model_point(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 400)
    widget.nodes = [{"id": 0, "pos": QPoint(40, 40), "element": "C"}]
    cursor = QPoint(130, 160)
    before = widget._widget_point_to_model(cursor)
    widget.zoom_about_widget_point(1.4, cursor)
    after = widget._widget_point_to_model(cursor)
    assert abs(after.x() - before.x()) <= 1
    assert abs(after.y() - before.y()) <= 1
    widget.pan_by_widget_delta(25, -10)
    shifted = widget._widget_point_to_model(cursor)
    assert shifted != after


def test_arrow_nudge_moves_the_selection(qapp) -> None:  # noqa: ARG001
    widget = SketchWidget()
    widget.resize(400, 300)
    widget.nodes = [
        {"id": 0, "pos": QPoint(80, 80), "element": "C"},
        {"id": 1, "pos": QPoint(140, 80), "element": "C"},
    ]
    widget.bonds = [_bond_make(0, 1, 1, 0)]
    widget.selected_nodes = [0, 1]
    widget.select_mode = True
    assert widget.nudge_selection(4, 0)
    assert widget.nodes[0]["pos"].x() == 84
    widget.undo()
    assert widget.nodes[0]["pos"].x() == 80


def test_loaded_sketch_starts_in_select(qapp) -> None:  # noqa: ARG001
    dialog = SketcherDialog(QWidget(), initial_mol=Chem.MolFromSmiles("CCO"))
    assert dialog.select_btn.isChecked()
    assert dialog.canvas.select_mode
    assert dialog._status_tool.text() == "Select"
    dialog.close()


def test_bond_key_sets_order(qapp) -> None:  # noqa: ARG001
    dialog = SketcherDialog(QWidget())
    dialog.canvas.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_2, Qt.NoModifier))
    assert dialog.canvas.active_bond_order == 2
    assert dialog.bond_double.isChecked()
    dialog.close()
