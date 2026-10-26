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


def test_runner_chains_steps_and_resolves_column_refs(qapp):
    desc = default_step("descriptors", set())
    calc = default_step("calculator", {desc.id})
    calc.params["expression"] = f"[${{{desc.id}.MolWt}}] / 2"
    recipe = MacroRecipe(id="abc", name="Prep", steps=[desc, calc])
    calls: list[tuple] = []

    def start_descriptor_calculation(*, source, keys, allowed, on_done, **_kwargs):
        calls.append(("descriptors", source, tuple(keys), allowed))
        on_done(None, {"MolWt": "Mol Weight", "MolLogP": "LogP"})

    def start_calculator_job(*, column, expression, allowed, on_done):
        calls.append(("calculator", column, expression, allowed))
        on_done(None, {"output": column})

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
