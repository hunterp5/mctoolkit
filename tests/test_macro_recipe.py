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

from molmanager.workflows.macro_recipe import (
    STEP_KINDS,
    MacroDocumentError,
    MacroRecipe,
    MacroReferenceError,
    default_step,
    descriptor_display_by_key,
    format_issues,
    library_from_json,
    library_to_json,
    new_recipe,
    recipe_from_json,
    recipe_to_json,
    substitute_column_refs,
    validate_recipe,
)

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


def test_catalog_uses_internal_keys():
    assert descriptor_display_by_key()["MolWt"] == "Mol Weight"
