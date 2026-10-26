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

"""Macro recipes: documents, references, and the editor. No running tools."""

from __future__ import annotations

import sys

import pytest

from molmanager.workflows.command_catalog import (
    COMMANDS,
    command_by_id,
    command_for_step_kind,
)
from molmanager.workflows.macro_recipe import (
    STEP_KINDS,
    MacroDocumentError,
    MacroRecipe,
    MacroReferenceError,
    MacroStep,
    default_step,
    descriptor_display_by_key,
    format_issues,
    library_from_json,
    library_to_json,
    new_recipe,
    output_keys,
    recipe_from_json,
    recipe_to_json,
    substitute_column_refs,
    validate_recipe,
)
from molmanager.workflows.macro_record import rewrite_recorded_params

_KEYS = {"MolWt", "MolLogP"}


def test_macro_recipe_module_does_not_import_qt():
    for name in list(sys.modules):
        if name.startswith("molmanager.workflows.macro_recipe"):
            del sys.modules[name]
    qt_already_loaded = "PyQt5.QtWidgets" in sys.modules
    import molmanager.workflows.macro_recipe  # noqa: F401

    if not qt_already_loaded:
        assert "PyQt5.QtWidgets" not in sys.modules


def test_recipe_round_trip():
    recipe = new_recipe("Prep")
    recipe.steps.append(default_step("descriptors", set()))
    payload = recipe_to_json(recipe)
    again = recipe_from_json(payload)
    assert again.name == "Prep"
    assert again.steps[0].kind == "descriptors"
    assert again.steps[0].params["descriptors"] == ["MolWt", "MolLogP"]


def test_default_recipe_validates():
    steps = []
    existing: set[str] = set()
    for kind in STEP_KINDS:
        step = default_step(kind, existing)
        existing.add(step.id)
        steps.append(step)
    recipe = MacroRecipe(id="abc", name="Prep", steps=steps)
    issues = validate_recipe(recipe, descriptor_keys=_KEYS)
    assert issues == (), format_issues(issues)


def test_forward_reference_is_rejected():
    first = default_step("calculator", set())
    first.params["expression"] = "${later.output}"
    later = default_step("calculator", {first.id})
    later.id = "later"
    recipe = MacroRecipe(id="abc", name="Prep", steps=[first, later])
    issues = validate_recipe(recipe, descriptor_keys=_KEYS)
    assert any("later" in issue.message for issue in issues)


def test_descriptor_output_reference_is_allowed():
    desc = default_step("descriptors", set())
    calc = default_step("calculator", {desc.id})
    calc.params["expression"] = f"[${{{desc.id}.MolWt}}]"
    recipe = MacroRecipe(id="abc", name="Prep", steps=[desc, calc])
    assert validate_recipe(recipe, descriptor_keys=_KEYS) == ()


def test_unknown_descriptor_and_bad_expression():
    desc = default_step("descriptors", set())
    desc.params["descriptors"] = ["NotADescriptor"]
    calc = default_step("calculator", {desc.id})
    calc.params["expression"] = "1 +"
    recipe = MacroRecipe(id="abc", name="Prep", steps=[desc, calc])
    messages = [issue.message for issue in validate_recipe(recipe, descriptor_keys=_KEYS)]
    assert any("NotADescriptor" in message for message in messages)
    assert any("not valid" in message for message in messages)


def test_protonate_ph_must_be_on_the_scale():
    step = default_step("protonate", set())
    step.params["ph"] = 15
    recipe = MacroRecipe(id="abc", name="Prep", steps=[step])
    issues = validate_recipe(recipe, descriptor_keys=_KEYS)
    assert any("pH" in issue.message for issue in issues)


def test_substitute_column_refs_quotes_uniquified_names():
    text = substitute_column_refs(
        "[${desc.MolWt}] + ${desc.LogP}",
        {"desc": {"MolWt": "MolWt (1)", "LogP": "LogP"}},
        quote_for_calculator=True,
    )
    assert text == "[MolWt (1)] + LogP"


def test_missing_reference_raises_when_substituting():
    with pytest.raises(MacroReferenceError):
        substitute_column_refs("${missing.output}", {})


def test_library_skips_a_broken_entry():
    good = recipe_to_json(new_recipe("Keep"))
    payload = library_to_json([])
    payload["macros"] = [good, {"name": "Broken", "steps": "nope"}]
    loaded = library_from_json(payload)
    assert [recipe.name for recipe in loaded] == ["Keep"]


def test_unsupported_library_version_is_rejected():
    with pytest.raises(MacroDocumentError):
        library_from_json({"version": 99, "macros": []})


def test_random_extract_and_plot_steps_validate():
    recipe = MacroRecipe(
        id="abc",
        name="More",
        steps=[
            MacroStep(
                id="rand1",
                kind="random_number",
                params={
                    "row_scope": "table",
                    "column": "Random",
                    "distribution": "uniform",
                    "low": 0,
                    "high": 1,
                },
            ),
            MacroStep(
                id="ext1",
                kind="reaction_extract",
                params={
                    "row_scope": "selection",
                    "source_column": "Reaction",
                    "mode": "both",
                    "published": ["col_1", "col_2"],
                },
            ),
            MacroStep(
                id="plot1",
                kind="plot",
                params={"state": {"plot_type": "scatter", "x": "${ext1.col_1}", "y": "LogP"}},
            ),
        ],
    )
    issues = validate_recipe(recipe, descriptor_keys=_KEYS)
    assert issues == (), format_issues(issues)
    assert output_keys("random_number", recipe.steps[0].params) == ("output",)
    assert output_keys("reaction_extract", recipe.steps[1].params) == ("col_1", "col_2")
    assert output_keys("plot", recipe.steps[2].params) == ()


def test_plot_axis_names_are_rewritten_and_titles_are_not():
    updated = rewrite_recorded_params(
        "plot",
        {
            "state": {
                "plot_type": "scatter",
                "x": "Mol Weight",
                "y": "LogP",
                "color": "Mol Weight",
                "radar_spokes": ["Mol Weight", "TPSA"],
                "hover_columns": ["Mol Weight"],
                "plot_title": "Mol Weight",
            }
        },
        {"desc1": {"MolWt": "Mol Weight", "TPSA": "TPSA"}},
    )
    state = updated["state"]
    assert state["x"] == "${desc1.MolWt}"
    assert state["color"] == "${desc1.MolWt}"
    assert state["radar_spokes"] == ["${desc1.MolWt}", "${desc1.TPSA}"]
    assert state["hover_columns"] == ["${desc1.MolWt}"]
    assert state["y"] == "LogP"
    assert state["plot_title"] == "Mol Weight"
    assert substitute_column_refs(state["x"], {"desc1": {"MolWt": "Mol Weight (1)"}}) == (
        "Mol Weight (1)"
    )


def test_potency_structure_and_rgroup_steps_validate():
    recipe = MacroRecipe(
        id="abc",
        name="Prep",
        steps=[
            MacroStep(
                id="pot1",
                kind="potency",
                params={
                    "row_scope": "table",
                    "column": "IC50",
                    "unit_column": "Unit",
                    "measure": "IC50",
                    "desired_unit": "nM",
                    "write_p": True,
                    "write_ki": True,
                    "mw_column": None,
                    "assay_concentrations": [
                        {
                            "conc_constant": 10.0,
                            "conc_column": None,
                            "conc_unit": "uM",
                            "ref_constant": None,
                            "ref_column": "Km",
                            "ref_unit": "uM",
                        }
                    ],
                },
            ),
            MacroStep(
                id="neut1",
                kind="neutralize",
                params={
                    "row_scope": "table",
                    "structure_source": "${pot1.activity}",
                    "no_render_2d": True,
                },
            ),
            MacroStep(
                id="prep1",
                kind="fast_prepare",
                params={
                    "row_scope": "selection",
                    "structure_source": "Structure",
                    "update_target": False,
                    "largest_column": "Largest",
                    "fragments_column": "Fragments",
                    "neutralize": True,
                },
            ),
            MacroStep(
                id="rgrp1",
                kind="rgroup",
                params={
                    "core_smiles": "[*:1]c1ccccc1",
                    "core_id": "core",
                    "pools": [
                        {"label": 1, "mode": "smiles", "file_path": "", "smiles_text": "CCN*"}
                    ],
                    "max_products": 5,
                    "add_to_table": True,
                    "save_to_file": False,
                },
            ),
        ],
    )
    issues = validate_recipe(recipe, descriptor_keys=_KEYS)
    assert issues == (), format_issues(issues)
    assert output_keys("potency", recipe.steps[0].params) == ("activity", "p", "ki", "pki")
    assert output_keys("neutralize", recipe.steps[1].params) == ("output",)
    assert output_keys("fast_prepare", recipe.steps[2].params) == ("output", "fragments")
    assert output_keys("rgroup", recipe.steps[3].params) == ()


def test_potency_columns_are_rewritten_and_new_fragment_names_are_not():
    potency = rewrite_recorded_params(
        "potency",
        {
            "column": "IC50",
            "unit_column": "Unit",
            "mw_column": "Mol Weight",
            "assay_concentrations": [{"conc_column": "Mol Weight", "ref_column": "Km"}],
        },
        {"desc1": {"MolWt": "Mol Weight"}},
    )
    assert potency["mw_column"] == "${desc1.MolWt}"
    assert potency["assay_concentrations"][0]["conc_column"] == "${desc1.MolWt}"
    assert potency["column"] == "IC50"
    prepared = rewrite_recorded_params(
        "fast_prepare",
        {
            "structure_source": "Mol Weight",
            "fragments_column": "Fragments",
            "largest_column": "Largest",
        },
        {"desc1": {"MolWt": "Mol Weight"}},
    )
    assert prepared["structure_source"] == "${desc1.MolWt}"
    assert prepared["fragments_column"] == "Fragments"
    assert prepared["largest_column"] == "Largest"


def test_catalog_uses_internal_keys():
    assert descriptor_display_by_key()["MolWt"] == "Mol Weight"


def test_command_catalog_lists_the_recipe_steps_without_qt():
    for name in list(sys.modules):
        if name.startswith("molmanager.workflows.command_catalog"):
            del sys.modules[name]
    qt_already_loaded = "PyQt5.QtWidgets" in sys.modules
    import molmanager.workflows.command_catalog  # noqa: F401

    if not qt_already_loaded:
        assert "PyQt5.QtWidgets" not in sys.modules
    assert len(COMMANDS) == 14
    descriptors = command_for_step_kind("descriptors")
    assert descriptors is not None
    assert descriptors.command_id == "chemistry.descriptors"
    assert command_by_id("chemistry.descriptors") is descriptors
    assert command_for_step_kind("not-a-step") is None
