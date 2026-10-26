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

"""Macro editor and runner sequencing. Tools themselves are faked."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.dialogs.macros import MacroDialog
from molmanager.ui.macro_runner import MacroRunner
from molmanager.ui.main_window.chemistry_workspace_window import ChemistryWorkspaceWindow
from molmanager.workflows.macro_recipe import (
    STEP_KINDS,
    MacroRecipe,
    MacroStep,
    default_step,
    format_issues,
    validate_recipe,
)


def test_macros_menu_slot_is_forwarded():
    assert callable(ChemistryWorkspaceWindow.open_macros)


def test_macro_dialog_round_trips_default_steps(qapp):  # noqa: ARG001
    dialog = MacroDialog(None, library=[], persist=False)
    dialog.add_macro()
    for kind in STEP_KINDS:
        dialog.add_step(kind)
    recipes = dialog.edited_library()
    dialog.close()
    assert len(recipes) == 1
    assert [step.kind for step in recipes[0].steps] == list(STEP_KINDS)
    issues = validate_recipe(recipes[0])
    assert issues == (), format_issues(issues)
    keys = set(recipes[0].steps[0].params["descriptors"])
    assert keys == {"MolWt", "MolLogP"}


def test_editor_keeps_a_recorded_plot_step(qapp):  # noqa: ARG001
    dialog = MacroDialog(None, library=[], persist=False)
    dialog.add_macro()
    dialog._docs[0]["steps"].append(
        {
            "id": "plot1",
            "kind": "plot",
            "params": {
                "state": {
                    "plot_type": "scatter",
                    "x": "Mol Weight",
                    "y": "LogP",
                    "plot_title": "Keep",
                }
            },
        }
    )
    dialog._step_index = 0
    dialog._reload_steps()
    dialog._show_step()
    dialog._editor._step_id.setText("plot2")
    recipes = dialog.edited_library()
    dialog.close()
    step = recipes[0].steps[0]
    assert step.id == "plot2"
    assert step.kind == "plot"
    assert step.params["state"]["x"] == "Mol Weight"
    assert step.params["state"]["plot_title"] == "Keep"
    assert step.params["state"]["plot_type"] == "scatter"


def test_runner_plays_random_number_then_restores_the_plot(qapp):
    random_step = MacroStep(
        id="rand1",
        kind="random_number",
        params={
            "row_scope": "table",
            "column": "Random",
            "distribution": "uniform",
            "low": 0,
            "high": 1,
        },
    )
    plot_step = MacroStep(
        id="plot1",
        kind="plot",
        params={"state": {"plot_type": "scatter", "x": "${rand1.output}", "y": "LogP"}},
    )
    recipe = MacroRecipe(id="abc", name="Plot", steps=[random_step, plot_step])
    calls: list[tuple] = []

    def start_random_number_job(params, *, allowed, on_done):
        calls.append(("random", params["column"], allowed))
        on_done(None, {"output": "Random (1)"})

    def apply_recorded_plot(state):
        calls.append(("plot", state["x"], state["y"], state["plot_type"]))

    app = SimpleNamespace(
        headers=["Structure"],
        _table_model=SimpleNamespace(rowCount=lambda: 4),
        process_queue=SimpleNamespace(has_outstanding_work=lambda: False),
        status_label=SimpleNamespace(setText=lambda _text: None),
        global_bounds={},
        _selected_oids_set=lambda: set(),
        start_random_number_job=start_random_number_job,
        apply_recorded_plot=apply_recorded_plot,
    )
    done: list[tuple[bool, str]] = []
    runner = MacroRunner(app)
    runner.finished.connect(lambda ok, message: done.append((ok, message)))
    runner.start(recipe)
    for _ in range(5):
        qapp.processEvents()
    assert calls == [
        ("random", "Random", None),
        ("plot", "Random (1)", "LogP", "scatter"),
    ]
    assert done == [(True, 'Macro "Plot" finished.')]


def test_editor_keeps_a_recorded_potency_step(qapp):  # noqa: ARG001
    dialog = MacroDialog(None, library=[], persist=False)
    dialog.add_macro()
    dialog._docs[0]["steps"].append(
        {
            "id": "pot1",
            "kind": "potency",
            "params": {
                "row_scope": "selection",
                "column": "IC50",
                "unit_column": "Unit",
                "measure": "IC50",
                "desired_unit": "nM",
                "write_p": True,
                "write_ki": False,
                "assay_concentrations": [],
                "mw_column": None,
            },
        }
    )
    dialog._step_index = 0
    dialog._reload_steps()
    dialog._show_step()
    dialog._editor._scope.setCurrentIndex(dialog._editor._scope.findData("table"))
    recipes = dialog.edited_library()
    dialog.close()
    step = recipes[0].steps[0]
    assert step.kind == "potency"
    assert step.params["row_scope"] == "table"
    assert step.params["column"] == "IC50"
    assert step.params["measure"] == "IC50"
    assert step.params["mw_column"] is None


def test_runner_plays_potency_then_neutralize(qapp):
    potency = MacroStep(
        id="pot1",
        kind="potency",
        params={
            "row_scope": "table",
            "column": "IC50",
            "unit_column": "Unit",
            "measure": "IC50",
            "desired_unit": "nM",
            "write_p": True,
            "write_ki": False,
        },
    )
    neutralize = MacroStep(
        id="neut1",
        kind="neutralize",
        params={
            "row_scope": "table",
            "structure_source": "${pot1.activity}",
            "no_render_2d": True,
        },
    )
    recipe = MacroRecipe(id="abc", name="Prep", steps=[potency, neutralize])
    calls: list[tuple] = []

    def start_potency_job(params, *, allowed, on_done):
        calls.append(("potency", params["column"], allowed))
        on_done(None, {"activity": "IC50 (1)", "p": "pIC50"})

    def start_neutralize_job(params, *, allowed, on_done, rows=None):
        calls.append(("neutralize", params["structure_source"], params["no_render_2d"]))
        on_done(None, {"output": params["structure_source"]})

    app = SimpleNamespace(
        headers=["Structure", "IC50", "Unit"],
        _table_model=SimpleNamespace(rowCount=lambda: 4),
        process_queue=SimpleNamespace(has_outstanding_work=lambda: False),
        status_label=SimpleNamespace(setText=lambda _text: None),
        global_bounds={},
        _selected_oids_set=lambda: set(),
        start_potency_job=start_potency_job,
        start_neutralize_job=start_neutralize_job,
    )
    done: list[tuple[bool, str]] = []
    runner = MacroRunner(app)
    runner.finished.connect(lambda ok, message: done.append((ok, message)))
    runner.start(recipe)
    for _ in range(5):
        qapp.processEvents()
    assert calls == [
        ("potency", "IC50", None),
        ("neutralize", "IC50 (1)", True),
    ]
    assert done == [(True, 'Macro "Prep" finished.')]


def test_runner_chains_steps_and_resolves_column_refs(qapp):
    desc = default_step("descriptors", set())
    calc = default_step("calculator", {desc.id})
    calc.params["expression"] = f"[${{{desc.id}.MolWt}}] / 2"
    recipe = MacroRecipe(id="abc", name="Prep", steps=[desc, calc])
    calls: list[tuple] = []

    def start_descriptor_calculation(request, *, allowed, on_done, **_kwargs):
        calls.append(("descriptors", request.structure_source, tuple(request.keys), allowed))
        on_done(None, {"MolWt": "Mol Weight", "MolLogP": "LogP"})

    def start_calculator_job(request, *, allowed, on_done):
        calls.append(("calculator", request.column, request.expression, allowed))
        on_done(None, {"output": request.column})

    app = SimpleNamespace(
        headers=["Structure"],
        _table_model=SimpleNamespace(rowCount=lambda: 4),
        process_queue=SimpleNamespace(has_outstanding_work=lambda: False),
        status_label=SimpleNamespace(setText=lambda _text: None),
        global_bounds={},
        start_descriptor_calculation=start_descriptor_calculation,
        start_calculator_job=start_calculator_job,
    )
    done: list[tuple[bool, str]] = []
    runner = MacroRunner(app)
    runner.finished.connect(lambda ok, message: done.append((ok, message)))
    runner.start(recipe)
    for _ in range(5):
        qapp.processEvents()
    assert calls == [
        ("descriptors", "Structure", ("MolWt", "MolLogP"), None),
        ("calculator", "Calc", "[Mol Weight] / 2", None),
    ]
    assert done == [(True, 'Macro "Prep" finished.')]
