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
    dialog.route_table.selectRow(1)
    assert dialog.molecule_cards() == []
    step_titles = [
        label.text() for label in dialog.findChildren(QLabel) if label.text().startswith("Step ")
    ]
    assert step_titles == ["Step 1"]
    _assert_canvas_pans(dialog)
    dialog.close()


def _assert_step_details_toggle(dialog) -> None:
    from PyQt5.QtWidgets import QApplication, QLabel, QPushButton

    dialog.show()
    QApplication.processEvents()
    buttons = [button for button in dialog.findChildren(QPushButton) if button.text() == "Step 1"]
    assert len(buttons) == 1
    cards = dialog.molecule_cards()
    assert cards
    assert max(card.width() for card in cards) <= 200
    assert buttons[0].parentWidget().width() > max(card.width() for card in cards)
    labels = buttons[0].parentWidget().findChildren(QLabel)
    detail = next(label for label in labels if label.text().startswith("uspto · 0.4210"))
    assert not detail.isVisible()
    assert "[C:1]>>[C:1]" in detail.text()
    buttons[0].click()
    QApplication.processEvents()
    assert detail.isVisible()
    buttons[0].click()
    QApplication.processEvents()
    assert not detail.isVisible()


def _assert_tree_overflows(dialog) -> None:
    from PyQt5.QtWidgets import QApplication

    dialog.show()
    QApplication.processEvents()
    dialog._route_scroll.setFixedWidth(220)
    dialog._pin_canvas()
    QApplication.processEvents()
    assert dialog._route_scroll.horizontalScrollBar().maximum() > 0


def _assert_canvas_pans(dialog) -> None:
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication, QWidget

    canvas = dialog._route_scroll
    bar = canvas.horizontalScrollBar()
    bar.setRange(0, 400)
    bar.setValue(200)
    target = dialog._steps_host
    child = target.findChild(QWidget) or canvas.viewport()
    origin = child.mapToGlobal(QPoint(20, 20))
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        QPoint(20, 20),
        origin,
        Qt.MiddleButton,
        Qt.MiddleButton,
        Qt.NoModifier,
    )
    QApplication.sendEvent(child, press)
    shift = QPoint(50, 20)
    move = QMouseEvent(
        QEvent.MouseMove,
        QPoint(8, 8),
        origin + shift,
        Qt.NoButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    release = QMouseEvent(
        QEvent.MouseButtonRelease,
        QPoint(8, 8),
        origin + shift,
        Qt.MiddleButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    try:
        QApplication.sendEvent(dialog.summary_log, move)
        assert bar.value() == 150
    finally:
        QApplication.sendEvent(dialog.summary_log, release)
        canvas.end_pan()
    assert canvas._pan is None


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
