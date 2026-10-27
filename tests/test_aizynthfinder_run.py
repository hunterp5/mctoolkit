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

"""AiZynthFinder config checks, checkpoint parsing, and the local process wrapper."""

from __future__ import annotations

import json
from pathlib import Path

import molmanager.predictions.aizynthfinder_run as aizynth
from molmanager.platform_support.tool_paths import (
    TOOL_AIZYNTH_CONFIG,
    TOOL_AIZYNTH_PYTHON,
    save_tool_path,
)


_LOCAL_CONFIG = """
expansion:
  uspto:
    - uspto_model.onnx
    - uspto_templates.csv.gz
stock:
  zinc: zinc_stock.hdf5
"""


def test_remote_policy_and_remote_stock_are_refused() -> None:
    remote_model = _LOCAL_CONFIG + "\nexpansion_policy:\n  use_remote_models: true\n"
    assert "server" in (aizynth.config_text_problem(remote_model) or "")
    remote_stock = "stock:\n  type: mongodb\n  host: stock.example.com\n  expansion: []\n"
    assert "MongoDB" in (aizynth.config_text_problem(remote_stock) or "")
    local_mongo = "stock:\n  type: mongodb\n  host: localhost\nexpansion:\n  uspto: model.onnx\n"
    assert aizynth.config_text_problem(local_mongo) is None
    assert aizynth.config_text_problem(_LOCAL_CONFIG) is None


def test_ready_message_rejects_this_interpreter(tmp_path: Path) -> None:
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    message = aizynth.ready_message(aizynth.sys.executable, str(config))
    assert message is not None
    assert "own environment" in message


def test_saved_paths_roundtrip_into_ready_message(tmp_path: Path) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    save_tool_path(TOOL_AIZYNTH_PYTHON, str(python))
    save_tool_path(TOOL_AIZYNTH_CONFIG, str(config))
    assert aizynth.ready_message() is None
    assert aizynth.resolve_python() == str(python)
    assert aizynth.resolve_config() == config


def test_routes_from_trees_keeps_step_order_and_stock() -> None:
    trees = [
        {
            "type": "mol",
            "smiles": "CCO",
            "in_stock": False,
            "scores": {"state score": 0.5, "number of reactions": 2},
            "metadata": {"created_at_iteration": 4, "is_solved": False},
            "children": [
                {
                    "type": "reaction",
                    "smiles": "CC.O>>CCO",
                    "metadata": {
                        "policy_name": "uspto",
                        "policy_probability": 0.421,
                        "policy_probability_rank": 0,
                        "classification": "1.2.3",
                        "library_occurence": 12,
                        "template": "[C:1]>>[C:1]",
                    },
                    "children": [
                        {"type": "mol", "smiles": "CC", "in_stock": True},
                        {
                            "type": "mol",
                            "smiles": "O",
                            "in_stock": True,
                            "children": [
                                {
                                    "type": "reaction",
                                    "smiles": "O>>O",
                                    "children": [{"type": "mol", "smiles": "O", "in_stock": False}],
                                }
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    routes = aizynth.routes_from_trees(trees)
    assert len(routes) == 1
    assert routes[0]["score"] == "0.500"
    assert routes[0]["solved"] is False
    assert routes[0]["steps"][0]["product"] == "CCO"
    assert routes[0]["steps"][0]["reactants"][0] == {"smiles": "CC", "in_stock": True}
    assert routes[0]["steps"][1]["product"] == "O"
    assert routes[0]["steps"][1]["reactants"][0]["in_stock"] is False
    tree = routes[0]["tree"]
    assert tree["smiles"] == "CCO"
    assert tree["in_stock"] is False
    reactants = tree["reactions"][0]["reactants"]
    assert reactants[0] == {"smiles": "CC", "in_stock": True, "reactions": []}
    deeper = reactants[1]
    assert deeper["smiles"] == "O"
    assert deeper["in_stock"] is True
    leaf = deeper["reactions"][0]["reactants"][0]
    assert leaf == {"smiles": "O", "in_stock": False, "reactions": []}
    assert aizynth.leaf_stock_counts(routes[0]) == (1, 2)
    assert routes[0]["scores"]["number of reactions"] == 2
    assert routes[0]["metadata"]["created_at_iteration"] == 4
    step_meta = routes[0]["steps"][0]["metadata"]
    assert step_meta["policy_probability"] == 0.421
    assert step_meta["template"] == "[C:1]>>[C:1]"
    reaction = routes[0]["tree"]["reactions"][0]
    assert reaction["smiles"] == "CC.O>>CCO"
    assert reaction["metadata"]["policy_name"] == "uspto"
    stocked = aizynth.routes_from_trees(trees, stock_info={"CC": ["zinc"]})
    cc = stocked[0]["tree"]["reactions"][0]["reactants"][0]
    assert cc["stock"] == ["zinc"]
    assert aizynth.routes_from_trees([{"huge": True}]) == []


def test_sort_routes_puts_solved_first() -> None:
    routes = [
        {"score": "0.900", "solved": False, "steps": [], "tree": None},
        {"score": "0.100", "solved": True, "steps": [], "tree": None},
        {"score": "0.800", "solved": True, "steps": [], "tree": None},
    ]
    ordered = aizynth.sort_routes(routes)
    assert [route["score"] for route in ordered] == ["0.800", "0.100", "0.900"]
    assert [route["solved"] for route in ordered] == [True, True, False]


def test_tree_from_steps_keeps_duplicate_smiles_apart() -> None:
    steps = [
        {
            "product": "CCO",
            "reactants": [
                {"smiles": "CC", "in_stock": True},
                {"smiles": "O", "in_stock": True},
            ],
        },
        {"product": "O", "reactants": [{"smiles": "O", "in_stock": False}]},
    ]
    tree = aizynth.tree_from_steps(steps)
    intermediate = tree["reactions"][0]["reactants"][1]
    leaf = intermediate["reactions"][0]["reactants"][0]
    assert intermediate["in_stock"] is True
    assert leaf["in_stock"] is False
    assert leaf is not intermediate
    assert aizynth.leaf_stock_counts({"steps": steps}) == (1, 2)


def test_checkpoint_and_output_table_become_columns(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.jsonl"
    checkpoint.write_text(
        json.dumps(
            {
                "processed_smiles": "CCO",
                "results": {
                    "is_solved": True,
                    "number_of_solved_routes": 2,
                    "top_score": 0.9876,
                    "number_of_steps": 3,
                    "search_time": 12.34,
                    "precursors_in_stock": "CCO, CC",
                    "precursors_not_in_stock": "",
                    "first_solution_time": 1.25,
                    "first_solution_iteration": 3,
                    "number_of_nodes": 10,
                    "policy_used_counts": {"uspto": 4},
                    "stock_info": {"CC": ["zinc"]},
                    "search_note": "kept",
                    "trees": [{"huge": True}],
                },
            }
        )
        + "\nnot-json\n",
        encoding="utf-8",
    )
    columns = aizynth.summaries_from_checkpoint(checkpoint)["CCO"]
    assert columns[aizynth.COLUMN_SOLVED] == "yes"
    assert columns[aizynth.COLUMN_SOLVED_ROUTES] == "2"
    assert columns[aizynth.COLUMN_SCORE] == "0.988"
    assert columns[aizynth.COLUMN_STEPS] == "3"
    assert columns[aizynth.COLUMN_TIME] == "12.3"
    assert columns[aizynth.COLUMN_IN_STOCK] == "CCO, CC"
    assert columns[aizynth.COLUMN_FIRST_SOLUTION_TIME] == "1.2"
    assert columns[aizynth.COLUMN_FIRST_SOLUTION_ITERATION] == "3"
    assert columns[aizynth.COLUMN_NODES] == "10"
    assert columns[aizynth.COLUMN_POLICIES] == "uspto: 4"
    assert columns[aizynth.COLUMN_STOCK] == "CC: zinc"
    assert columns["AiZynth Search note"] == "kept"
    assert "trees" not in columns

    output = tmp_path / "output.json.gz"
    payload = {
        "schema": {"fields": []},
        "data": [
            {
                "target": "CCN",
                "is_solved": False,
                "number_of_solved_routes": 0,
                "top_score": 0.1,
                "number_of_steps": 1,
                "search_time": 2,
                "precursors_in_stock": ["CC"],
                "precursors_not_in_stock": ["N"],
            }
        ],
    }
    import gzip

    with gzip.open(output, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    parsed = aizynth.summaries_from_output(output)["CCN"]
    assert parsed[aizynth.COLUMN_SOLVED] == "no"
    assert parsed[aizynth.COLUMN_IN_STOCK] == "CC"
    assert parsed[aizynth.COLUMN_NOT_IN_STOCK] == "N"


def _assert_card_copy_menu(cards, monkeypatch) -> None:
    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QContextMenuEvent
    from PyQt5.QtWidgets import QApplication, QMenu

    green = next(card for card in cards if "#2e7d32" in card.styleSheet())

    def fake_exec(self, *_args, **_kwargs):
        copy_action = next(action for action in self.actions() if action.menu() is not None)
        assert copy_action.text() == "Copy"
        labels = [action.text() for action in copy_action.menu().actions()]
        assert labels == ["SMILES", "InChI", "InChIKey", "Molfile", "SMARTS"]
        return next(action for action in copy_action.menu().actions() if action.text() == "SMILES")

    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    green.contextMenuEvent(
        QContextMenuEvent(
            QContextMenuEvent.Mouse,
            QPoint(8, 8),
            green.mapToGlobal(QPoint(8, 8)),
        )
    )
    assert QApplication.clipboard().text() == "CC"


def test_route_browser_lists_one_step(qapp, monkeypatch) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.browsers.route_browser import RouteBrowserDialog

    dialog = RouteBrowserDialog()
    dialog.set_targets(
        [
            {
                "smiles": "CCO",
                "routes": [
                    {
                        "score": "0.900",
                        "solved": False,
                        "steps": [
                            {
                                "product": "CCO",
                                "reaction": "",
                                "reactants": [{"smiles": "C", "in_stock": False}],
                            }
                        ],
                    },
                    {
                        "score": "0.500",
                        "solved": True,
                        "steps": [
                            {
                                "product": "CCO",
                                "reaction": "",
                                "reactants": [
                                    {"smiles": "CC", "in_stock": True},
                                    {"smiles": "O", "in_stock": False},
                                ],
                            }
                        ],
                        "tree": {
                            "smiles": "CCO",
                            "in_stock": False,
                            "reactions": [
                                {
                                    "smiles": "CC.O>>CCO",
                                    "metadata": {
                                        "policy_name": "uspto",
                                        "policy_probability": 0.421,
                                        "policy_probability_rank": 0,
                                        "template": "[C:1]>>[C:1]",
                                    },
                                    "reactants": [
                                        {
                                            "smiles": "CC",
                                            "in_stock": True,
                                            "reactions": [],
                                            "stock": ["zinc"],
                                        },
                                        {"smiles": "O", "in_stock": False, "reactions": []},
                                    ],
                                }
                            ],
                        },
                        "scores": {"state score": 0.5, "number of reactions": 1},
                    },
                ],
            }
        ]
    )
    assert dialog.route_table.rowCount() == 2
    assert dialog.route_table.item(0, 1).text() == "Solved"
    assert dialog.route_table.item(0, 2).text() == "0.500"
    assert dialog.route_table.item(0, 4).text() == "1/2"
    assert dialog.route_table.item(0, 5).text() == "1"
    assert "number of reactions" in dialog.summary_log.toPlainText()
    assert dialog.route_table.item(1, 1).text() == "Unsolved"
    assert dialog.route_table.item(1, 4).text() == "0/1"
    log_text = dialog.summary_log.toPlainText()
    assert "Solved" in log_text
    assert "0.500" in log_text
    log_parent = dialog.summary_log.parentWidget()
    pane = log_parent.layout()
    assert pane.indexOf(dialog._route_scroll) < pane.indexOf(dialog.summary_log)
    cards = dialog.molecule_cards()
    assert len(cards) == 3
    frames = [card.styleSheet() for card in cards]
    assert any("#2e7d32" in sheet for sheet in frames)
    assert any("#ef6c00" in sheet for sheet in frames)
    shown = [label.text() for card in cards for label in card.findChildren(QLabel)]
    assert "CCO" not in shown
    assert "CC" not in shown
    _assert_step_details_toggle(dialog)
    green = next(card for card in cards if "#2e7d32" in card.styleSheet())
    assert "zinc" in green.toolTip()
    _assert_card_copy_menu(cards, monkeypatch)
    _assert_tree_overflows(dialog)
    _assert_sharp_depictions(dialog)
    dialog.route_table.selectRow(1)
    assert dialog.molecule_cards() == []
    step_titles = [
        label.text()
        for label in dialog._steps_host.findChildren(QLabel)
        if label.text().startswith("Step ")
    ]
    assert step_titles == ["Step 1"]
    _assert_canvas_pans(dialog)
    dialog.close()


def _assert_step_details_toggle(dialog) -> None:
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QAbstractItemView, QApplication, QPushButton, QSplitter

    dialog.show()
    QApplication.processEvents()
    buttons = [
        button
        for button in dialog._steps_host.findChildren(QPushButton)
        if button.text() == "Step 1"
    ]
    assert len(buttons) == 1
    cards = dialog.molecule_cards()
    assert cards
    assert max(card.width() for card in cards) <= 200
    assert buttons[0].parentWidget().width() > max(card.width() for card in cards)
    assert buttons[0].reaction_smiles == "CC.O>>CCO"
    buttons[0].click()
    QApplication.processEvents()
    buttons[0].setChecked(False)
    dialog._clear_step_table()
    _click_step_button(buttons[0])
    assert buttons[0].isChecked()
    assert dialog.step_table.rowCount() > 0
    fields = [dialog.step_table.item(row, 0).text() for row in range(dialog.step_table.rowCount())]
    values = [dialog.step_table.item(row, 1).text() for row in range(dialog.step_table.rowCount())]
    assert "policy_name" in fields
    assert "uspto" in values
    assert "[C:1]>>[C:1]" in values
    assert dialog.step_table.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert dialog.step_table.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    dialog.step_table.selectRow(fields.index("template"))
    assert dialog.step_table.copy_selected_chemical()
    assert QApplication.clipboard().text() == "[C:1]>>[C:1]"
    dialog.step_table.selectRow(fields.index("policy_name"))
    assert dialog.step_table.copy_selected_chemical() is False
    assert QApplication.clipboard().text() == "[C:1]>>[C:1]"
    splitter = dialog.step_table.parentWidget()
    assert isinstance(splitter, QSplitter)
    assert splitter.widget(0) is dialog.route_table
    assert splitter.widget(2) is dialog.step_table
    assert dialog.step_table.maximumWidth() > 2000
    assert (
        dialog.step_table.mapToGlobal(QPoint(0, 0)).x()
        > dialog._route_scroll.mapToGlobal(QPoint(dialog._route_scroll.width() - 1, 0)).x()
    )


def _assert_tree_overflows(dialog) -> None:
    from PyQt5.QtWidgets import QApplication

    dialog.show()
    QApplication.processEvents()
    dialog._route_scroll.setFixedWidth(220)
    dialog._place_tree()
    QApplication.processEvents()
    host = dialog._steps_host
    canvas = dialog._route_scroll
    bounds = canvas._proxy.sceneBoundingRect()
    left = canvas.mapFromScene(bounds.topLeft()).x()
    right = canvas.mapFromScene(bounds.topRight()).x()
    view_width = canvas.viewport().width()
    assert host.width() > view_width
    assert left < 0
    assert 0 < right <= view_width


def _assert_canvas_pans(dialog) -> None:
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    import molmanager.ui.browsers.route_browser as route_browser

    class _Spontaneous(QMouseEvent):
        def spontaneous(self) -> bool:  # noqa: N802
            return True

    canvas = dialog._route_scroll
    viewport = canvas.viewport()
    origin = viewport.mapToGlobal(QPoint(20, 20))
    held = {"at": QPoint(origin)}

    class _Cursor:
        @staticmethod
        def pos() -> QPoint:
            return QPoint(held["at"])

    previous = route_browser.QCursor
    route_browser.QCursor = _Cursor
    shift = QPoint(50, 30)
    press = _Spontaneous(
        QEvent.MouseButtonPress,
        QPoint(20, 20),
        origin,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    move = _Spontaneous(
        QEvent.MouseMove,
        QPoint(70, 50),
        origin + shift,
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    drift = QMouseEvent(
        QEvent.MouseMove,
        QPoint(200, 20),
        origin + QPoint(400, 0),
        Qt.NoButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    release = _Spontaneous(
        QEvent.MouseButtonRelease,
        QPoint(70, 50),
        origin + shift,
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    try:
        across = canvas.horizontalScrollBar()
        down = canvas.verticalScrollBar()
        start_h, start_v = across.value(), down.value()
        watched = canvas.mapToScene(QPoint(40, 40))
        middle = _Spontaneous(
            QEvent.MouseButtonPress,
            QPoint(20, 20),
            origin,
            Qt.MiddleButton,
            Qt.MiddleButton,
            Qt.NoModifier,
        )
        middle_move = _Spontaneous(
            QEvent.MouseMove,
            QPoint(70, 50),
            origin + shift,
            Qt.NoButton,
            Qt.MiddleButton,
            Qt.NoModifier,
        )
        QApplication.sendEvent(viewport, middle)
        held["at"] = origin + shift
        QApplication.sendEvent(viewport, middle_move)
        assert across.value() == start_h
        assert down.value() == start_v
        assert canvas._pan is None
        held["at"] = origin
        QApplication.sendEvent(viewport, press)
        QApplication.sendEvent(
            viewport,
            _Spontaneous(
                QEvent.MouseButtonRelease,
                QPoint(20, 20),
                origin,
                Qt.LeftButton,
                Qt.NoButton,
                Qt.NoModifier,
            ),
        )
        assert across.value() == start_h
        assert down.value() == start_v
        assert canvas._pan is None
        QApplication.sendEvent(viewport, press)
        held["at"] = origin + shift
        QApplication.sendEvent(viewport, move)
        assert across.value() == start_h - shift.x()
        assert down.value() == start_v - shift.y()
        moved = canvas.mapFromScene(watched)
        assert moved.x() == 40 + shift.x()
        assert moved.y() == 40 + shift.y()
        QApplication.sendEvent(viewport, drift)
        assert across.value() == start_h - shift.x()
        assert down.value() == start_v - shift.y()
        far = QPoint(2500, -1800)
        held["at"] = origin + far
        QApplication.sendEvent(
            viewport,
            _Spontaneous(
                QEvent.MouseMove,
                QPoint(8, 8),
                origin + far,
                Qt.NoButton,
                Qt.LeftButton,
                Qt.NoModifier,
            ),
        )
        assert across.value() == start_h - far.x()
        assert down.value() == start_v - far.y()
        flung = canvas.mapFromScene(watched)
        assert flung.x() == 40 + far.x()
        assert flung.y() == 40 + far.y()
    finally:
        QApplication.sendEvent(viewport, release)
        canvas.end_pan()
        route_browser.QCursor = previous
    assert canvas._pan is None
    _assert_canvas_zooms(canvas, viewport, origin)


def _assert_canvas_zooms(canvas, viewport, origin) -> None:
    from PyQt5.QtCore import QPoint, QPointF, Qt
    from PyQt5.QtGui import QWheelEvent
    from PyQt5.QtWidgets import QApplication

    class _SpontaneousWheel(QWheelEvent):
        def spontaneous(self) -> bool:  # noqa: N802
            return True

    anchor = QPoint(30, 30)
    watched = canvas.mapToScene(anchor)
    wheel = _SpontaneousWheel(
        QPointF(anchor),
        QPointF(origin),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(viewport, wheel)
    assert abs(canvas._zoom - 1.1) < 1e-6
    back = canvas.mapFromScene(watched)
    assert abs(back.x() - anchor.x()) <= 2
    assert abs(back.y() - anchor.y()) <= 2


def _click_step_button(button) -> None:
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    class _Spontaneous(QMouseEvent):
        def spontaneous(self) -> bool:  # noqa: N802
            return True

    local = QPoint(max(1, button.width() // 2), max(1, button.height() // 2))
    global_pos = button.mapToGlobal(local)
    QApplication.sendEvent(
        button,
        _Spontaneous(
            QEvent.MouseButtonPress,
            local,
            global_pos,
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        ),
    )
    QApplication.sendEvent(
        button,
        _Spontaneous(
            QEvent.MouseButtonRelease,
            local,
            global_pos,
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        ),
    )
    QApplication.processEvents()


def _assert_sharp_depictions(dialog) -> None:
    from PyQt5.QtGui import QPalette
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.browsers.route_browser import _SharpProxy

    canvas = dialog._route_scroll
    _assert_canvas_zooms(canvas, canvas.viewport(), canvas.mapToGlobal(dialog.rect().topLeft()))
    ratio = canvas.depict_ratio()
    assert ratio > 1.05
    card = dialog.molecule_cards()[0]
    label = card.findChild(QLabel)
    pixmap = label.pixmap()
    assert pixmap is not None and not pixmap.isNull()
    assert abs(pixmap.devicePixelRatio() - ratio) < 0.05
    assert pixmap.width() > label.width()
    canvas.grab()
    cache = canvas._proxy._cache
    assert isinstance(canvas._proxy, _SharpProxy)
    assert cache is not None and not cache.isNull()
    assert abs(cache.devicePixelRatio() - ratio) < 0.05
    assert cache.width() > dialog._steps_host.width()
    host = dialog._steps_host
    assert host.objectName() == "route-tree"
    assert "palette(base)" in host.styleSheet()
    base = canvas.palette().color(QPalette.Base)
    assert canvas.backgroundBrush().color() == base
    assert host.palette().color(QPalette.Window) == base


def test_branch_lines_reach_reagent_cards(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QPoint
    from PyQt5.QtWidgets import QApplication, QPushButton

    from molmanager.ui.browsers.route_browser import (
        _HStem,
        _MoleculeNode,
        _VBranch,
        RouteBrowserDialog,
    )

    def leaf(smiles: str) -> dict:
        return {"smiles": smiles, "in_stock": False, "reactions": []}

    deep = {
        "smiles": "O",
        "in_stock": False,
        "reactions": [
            {
                "smiles": "C.CO>>O",
                "metadata": {},
                "reactants": [
                    leaf("C"),
                    {
                        "smiles": "CO",
                        "in_stock": False,
                        "reactions": [
                            {
                                "smiles": "C.O>>CO",
                                "metadata": {},
                                "reactants": [leaf("C"), leaf("O")],
                            }
                        ],
                    },
                ],
            }
        ],
    }
    dialog = RouteBrowserDialog()
    dialog.set_targets(
        [
            {
                "smiles": "CCO",
                "routes": [
                    {
                        "score": "0.5",
                        "solved": True,
                        "steps": [{"product": "CCO", "reaction": "", "reactants": []}],
                        "tree": {
                            "smiles": "CCO",
                            "in_stock": False,
                            "reactions": [
                                {
                                    "smiles": "CC.O>>CCO",
                                    "metadata": {},
                                    "reactants": [leaf("CC"), deep],
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    )
    dialog.resize(1100, 700)
    dialog.show()
    QApplication.processEvents()
    dialog._place_tree()
    host = dialog._steps_host
    canvas = dialog._route_scroll
    right = canvas.mapFromScene(canvas._proxy.sceneBoundingRect().topRight()).x()
    assert 0 < right <= canvas.viewport().width()
    gaps: list[int] = []
    for branch in host.findChildren(_VBranch):
        left = branch.mapTo(host, QPoint(0, 0)).x()
        column = branch.parentWidget().layout().itemAt(0).widget()
        for index in range(column.layout().count()):
            node = column.layout().itemAt(index).widget()
            if not isinstance(node, _MoleculeNode):
                continue
            tail = node.layout().itemAt(node.layout().count() - 1).widget()
            assert isinstance(tail, _HStem)
            right = tail.mapTo(host, QPoint(tail.width(), 0)).x()
            gaps.append(left - right)
    assert gaps
    assert max(gaps) <= 2
    buttons = sorted(
        (
            button
            for button in dialog._steps_host.findChildren(QPushButton)
            if button.objectName() == "route-step"
        ),
        key=lambda button: button.mapToGlobal(QPoint(0, 0)).x(),
    )
    assert [button.text() for button in buttons] == ["Step 1", "Step 2", "Step 3"]
    dialog.close()


def test_step_button_searches_open_reaction_database(qapp, monkeypatch) -> None:  # noqa: ARG001
    from urllib.parse import unquote

    from PyQt5.QtCore import QPoint
    from PyQt5.QtGui import QContextMenuEvent
    from PyQt5.QtWidgets import QApplication, QMenu, QPushButton

    import molmanager.ui.browsers.route_browser as route_browser

    url = route_browser.ord_conditions_url("[CH3:1][OH:2]>>[CH3:1][O:2][CH3]")
    decoded = unquote(url)
    assert decoded.startswith("https://open-reaction-database.org/search?")
    assert "reaction_smarts=CO>>COC" in decoded
    assert ":1" not in decoded
    assert route_browser.ord_conditions_url("not a reaction") == ""

    opened: list[str] = []

    def _open(target) -> bool:
        opened.append(target.toString())
        return True

    monkeypatch.setattr(route_browser.QDesktopServices, "openUrl", _open)

    class _ImmediateMenu(QMenu):
        def exec_(self, *_args, **_kwargs):  # noqa: N802
            return self.actions()[0]

    monkeypatch.setattr(route_browser, "QMenu", _ImmediateMenu)
    dialog = route_browser.RouteBrowserDialog()
    dialog.set_targets(
        [
            {
                "smiles": "CCO",
                "routes": [
                    {
                        "score": "0.5",
                        "solved": True,
                        "steps": [],
                        "tree": {
                            "smiles": "CCO",
                            "in_stock": False,
                            "reactions": [
                                {
                                    "smiles": "CC.O>>CCO",
                                    "metadata": {},
                                    "reactants": [
                                        {"smiles": "CC", "in_stock": True, "reactions": []},
                                        {"smiles": "O", "in_stock": False, "reactions": []},
                                    ],
                                }
                            ],
                        },
                    }
                ],
            }
        ]
    )
    dialog.show()
    QApplication.processEvents()
    button = next(
        button
        for button in dialog._steps_host.findChildren(QPushButton)
        if button.objectName() == "route-step"
    )
    QApplication.sendEvent(
        button,
        QContextMenuEvent(
            QContextMenuEvent.Mouse,
            QPoint(4, 4),
            button.mapToGlobal(QPoint(4, 4)),
        ),
    )
    assert len(opened) == 1
    assert unquote(opened[0]).startswith("https://open-reaction-database.org/search?")
    assert "CC.O>>CCO" in unquote(opened[0])
    dialog.close()


def test_search_options_select_policies_and_limits() -> None:
    text = _LOCAL_CONFIG + "\nfilter:\n  uspto: uspto_filter.onnx\n"
    catalog = aizynth.config_catalog(text)
    assert catalog["expansion"] == ["uspto"]
    assert catalog["filter"] == ["uspto"]
    assert catalog["stock"] == ["zinc"]
    options = aizynth.SearchOptions(
        policies=("uspto",),
        filters=("uspto",),
        stocks=("zinc",),
        iteration_limit=40,
        time_limit=180,
        max_transforms=4,
        max_routes=8,
        exploration=1.8,
        cluster=True,
    )
    restored = aizynth.SearchOptions.from_json(options.to_json())
    assert restored.policies == ("uspto",)
    assert restored.iteration_limit == 40
    assert restored.time_limit == 180
    assert restored.max_routes == 8
    assert restored.exploration == 1.8
    assert restored.cluster is True
    assert restored.all_algorithms is False
    command = aizynth.aizynthcli_command(
        "python",
        Path("config.yml"),
        Path("smiles.txt"),
        Path("out.json"),
        Path("checkpoint.jsonl"),
        options,
    )
    assert command[command.index("--policy") + 1] == "uspto"
    assert "--filter" in command
    assert "--stocks" in command
    assert "--cluster" in command
    assert "--nproc" not in command
    overlay = options.overlay()
    assert overlay["search"]["iteration_limit"] == 40
    assert overlay["search"]["time_limit"] == 180
    assert overlay["search"]["algorithm_config"]["C"] == 1.8
    assert overlay["post_processing"]["max_routes"] == 8


def test_all_algorithms_merges_distinct_routes() -> None:
    options = aizynth.SearchOptions(policies=("uspto",), max_routes=2, all_algorithms=True)
    restored = aizynth.SearchOptions.from_json(options.to_json())
    assert restored.all_algorithms is True
    payload = aizynth.all_algorithms_payload(options)
    assert [item[1] for item in payload["algorithms"]] == [
        value for _label, value in aizynth._ALGORITHMS
    ]
    assert payload["max_routes"] == 2
    command = aizynth.all_algorithms_command(
        "python",
        Path("config.yml"),
        Path("smiles.txt"),
        Path("checkpoint.jsonl"),
        Path("algorithms.json"),
    )
    assert "aizynthcli" not in command[2]
    assert command[3:] == ["config.yml", "smiles.txt", "checkpoint.jsonl", "algorithms.json"]
    namespace = {"__name__": "algorithms"}
    exec(aizynth._ALL_ALGORITHMS_SCRIPT, namespace)  # noqa: S102
    shared = {
        "smiles": "CCO",
        "metadata": {"is_solved": True},
        "scores": {"state score": 0.4},
        "children": [{"smiles": "CC.O>>CCO", "children": []}],
    }
    other = {
        "smiles": "CCO",
        "metadata": {"is_solved": False},
        "scores": {"state score": 0.9},
        "children": [{"smiles": "C.CO>>CCO", "children": []}],
    }
    duplicate = {
        "smiles": "CCO",
        "metadata": {"is_solved": True},
        "scores": {"state score": 0.2},
        "children": [{"smiles": "O.CC>>CCO", "children": []}],
    }
    merged = namespace["merge_runs"](
        [
            (
                "Monte Carlo",
                {
                    "search_time": 1.5,
                    "number_of_nodes": 10,
                    "is_solved": True,
                    "first_solution_time": 1.0,
                },
                [shared],
                {"CC": ["zinc"]},
            ),
            (
                "Retro*",
                {"search_time": 2.0, "number_of_nodes": 4, "is_solved": False},
                [other, duplicate],
                {},
            ),
        ],
        25,
    )
    assert len(merged["trees"]) == 2
    assert merged["trees"][0]["metadata"]["algorithm"] == "Monte Carlo, Retro*"
    assert merged["trees"][0]["metadata"]["is_solved"] is True
    assert merged["search_time"] == 3.5
    assert merged["number_of_nodes"] == 14
    assert merged["is_solved"] is True
    assert merged["number_of_routes"] == 2
    assert merged["algorithms"] == "Monte Carlo, Retro*"
    capped = namespace["merge_runs"](
        [
            ("Monte Carlo", {"search_time": 1, "number_of_nodes": 1}, [shared, other], {}),
        ],
        1,
    )
    assert len(capped["trees"]) == 1
    assert capped["trees"][0]["metadata"]["is_solved"] is True


def test_retrosynthesis_dialog_lists_config_policies(qapp, monkeypatch, tmp_path: Path) -> None:
    from PyQt5.QtWidgets import QGroupBox

    from molmanager.ui.dialogs.aizynthfinder import AizynthFinderDialog

    config = tmp_path / "config.yml"
    config.write_text(
        "expansion:\n"
        "  uspto:\n"
        "    - uspto_model.onnx\n"
        "    - uspto_templates.csv.gz\n"
        "  ringbreaker:\n"
        "    - ring.onnx\n"
        "    - ring.csv.gz\n"
        "stock:\n"
        "  zinc: zinc_stock.hdf5\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "molmanager.ui.dialogs.aizynthfinder.resolve_config",
        lambda _text="": config,
    )
    monkeypatch.setattr(
        "molmanager.ui.dialogs.aizynthfinder.load_search_options",
        lambda: aizynth.SearchOptions(),
    )
    dialog = AizynthFinderDialog()
    models = dialog.findChild(QGroupBox, "aizynth-models")
    assert models is not None
    assert models.sizeHint().height() <= 96
    assert [box.text() for box in dialog._policy_boxes] == ["uspto", "ringbreaker"]
    assert all(box.isChecked() for box in dialog._policy_boxes)
    assert dialog.time_minutes.value() == 2
    dialog._policy_boxes[1].setChecked(False)
    chosen = dialog._search_options()
    assert chosen.policies == ("uspto",)
    assert chosen.time_limit == 120
    assert dialog.try_all.isChecked() is False
    dialog.try_all.setChecked(True)
    assert dialog.algorithm.isEnabled() is False
    assert dialog.cluster.isEnabled() is False
    assert dialog._search_options().all_algorithms is True
    dialog.close()


def test_search_without_a_policy_is_refused(tmp_path: Path, monkeypatch) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    monkeypatch.setattr(
        aizynth.subprocess,
        "Popen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("search started")),
    )
    try:
        aizynth.run_search(
            python=str(python),
            config=config,
            smiles=["CCO"],
            options=aizynth.SearchOptions(),
        )
    except aizynth.AizynthRunError as exc:
        assert "policy" in str(exc)
    else:
        raise AssertionError("a search with no policy should be refused")


def test_conda_child_environment_prefixes_library_bin(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "env"
    lib = root / "Library" / "bin"
    lib.mkdir(parents=True)
    (root / "conda-meta").mkdir()
    python = root / "python.exe"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", r"C:\molmanager")
    monkeypatch.setenv("CONDA_PREFIX", r"C:\Users\hunte\miniconda3")
    monkeypatch.setenv("PATH", r"C:\Windows")
    env = aizynth.child_environment(python)
    assert "PYTHONPATH" not in env
    assert env["PYTHONNOUSERSITE"] == "1"
    assert env["CONDA_PREFIX"] == str(root)
    assert env["PATH"].startswith(str(root))
    assert str(lib) in env["PATH"]


def test_run_search_reads_checkpoint_and_kills_on_cancel(tmp_path: Path, monkeypatch) -> None:
    python = tmp_path / "python.exe"
    python.write_text("", encoding="utf-8")
    config = tmp_path / "config.yml"
    config.write_text(_LOCAL_CONFIG, encoding="utf-8")
    seen: dict[str, object] = {}

    class _Proc:
        def __init__(self, args, **kwargs):
            seen["args"] = list(args)
            seen["cwd"] = kwargs.get("cwd")
            seen["env"] = kwargs.get("env")
            checkpoint = Path(args[args.index("--checkpoint") + 1])
            checkpoint.write_text(
                json.dumps(
                    {
                        "processed_smiles": "CCO",
                        "results": {"is_solved": True, "number_of_solved_routes": 1},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            self.returncode = None
            self.stdout = None
            self.stderr = None
            self._polls = 0

        def poll(self):
            self._polls += 1
            if self._polls > 1:
                self.returncode = 0
            return self.returncode

        def kill(self):
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            self.returncode = 0
            return 0

    monkeypatch.setattr(aizynth.subprocess, "Popen", _Proc)
    monkeypatch.setattr(aizynth.time, "sleep", lambda _seconds: None)
    monkeypatch.delenv("PYTHONPATH", raising=False)
    result = aizynth.run_search(python=str(python), config=config, smiles=["CCO"])
    assert result.summaries["CCO"][aizynth.COLUMN_SOLVED] == "yes"
    command = seen["args"]
    assert isinstance(command, list)
    assert command[0] == str(python)
    assert "--nproc" not in command
    assert seen["cwd"] == str(config.parent)
    env = seen["env"]
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env

    kept = aizynth.run_search(
        python=str(python),
        config=config,
        smiles=["CCO"],
        cancel=lambda: True,
    )
    assert kept.cancelled
    assert kept.summaries["CCO"][aizynth.COLUMN_SOLVED] == "yes"

    class _Silent:
        def __init__(self, args, **kwargs):
            self.returncode = None
            self.stdout = None
            self.stderr = None

        def poll(self):
            return self.returncode

        def kill(self):
            self.returncode = 1

        def wait(self, timeout=None):  # noqa: ARG002
            return self.returncode

    monkeypatch.setattr(aizynth.subprocess, "Popen", _Silent)
    try:
        aizynth.run_search(
            python=str(python),
            config=config,
            smiles=["CCO"],
            cancel=lambda: True,
        )
    except aizynth.AizynthRunError as exc:
        assert str(exc) == "Cancelled."
    else:
        raise AssertionError("cancel before a checkpoint should fail the search")
