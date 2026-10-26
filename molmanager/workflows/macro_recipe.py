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

"""Saved macro recipes: plain data, column references, and validation.

A recipe is an ordered list of steps. It does not touch the table. The UI editor
writes this document, and ``molmanager.ui.macro_runner`` is what actually starts
each tool. Click-by-click recording is a separate architecture; see
``docs/MACRO_RECORDING.md``.

Column references look like ``${stepId.key}``. Descriptor steps publish each
internal descriptor key (``MolWt``, not the column title ``Mol Weight``).
Calculator and random-number steps publish ``output``. Protonate steps publish
``output``, ``percent``, and ``pka``. Reaction-extract steps publish ``col_1``,
``col_2``, and so on, in the order the columns were written.
"""

from __future__ import annotations

import ast
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

STEP_DESCRIPTORS = "descriptors"
STEP_CALCULATOR = "calculator"
STEP_PROTONATE = "protonate"
STEP_FILTER = "filter"
STEP_REACTION = "reaction"
STEP_RANDOM = "random_number"
STEP_EXTRACT = "reaction_extract"
STEP_PLOT = "plot"
STEP_POTENCY = "potency"
STEP_RGROUP = "rgroup"
STEP_EXPLICIT_H = "explicit_hydrogens"
STEP_REMOVE_H = "remove_explicit_hydrogens"
STEP_NEUTRALIZE = "neutralize"
STEP_FAST_PREPARE = "fast_prepare"

STEP_KINDS: tuple[str, ...] = (
    STEP_DESCRIPTORS,
    STEP_CALCULATOR,
    STEP_PROTONATE,
    STEP_FILTER,
    STEP_REACTION,
)

STEP_LABELS: dict[str, str] = {
    STEP_DESCRIPTORS: "Calculate descriptors",
    STEP_CALCULATOR: "Calculator",
    STEP_PROTONATE: "Protonate",
    STEP_FILTER: "Filter",
    STEP_REACTION: "Reaction enumeration",
    STEP_RANDOM: "Random number",
    STEP_EXTRACT: "Extract reaction",
    STEP_PLOT: "Plot",
    STEP_POTENCY: "Potency",
    STEP_RGROUP: "R-group enumeration",
    STEP_EXPLICIT_H: "Add explicit hydrogens",
    STEP_REMOVE_H: "Remove explicit hydrogens",
    STEP_NEUTRALIZE: "Neutralize",
    STEP_FAST_PREPARE: "Fast prepare",
}

ROW_SCOPE_TABLE = "table"
ROW_SCOPE_SELECTION = "selection"
ROW_SCOPE_VISIBLE = "visible"
ROW_SCOPES: tuple[str, ...] = (ROW_SCOPE_TABLE, ROW_SCOPE_SELECTION, ROW_SCOPE_VISIBLE)

ROW_SCOPE_LABELS: dict[str, str] = {
    ROW_SCOPE_TABLE: "All rows",
    ROW_SCOPE_SELECTION: "Selected rows",
    ROW_SCOPE_VISIBLE: "Visible rows",
}

FILTER_NUMERIC = "numeric"
FILTER_TEXT = "text"
FILTER_SUBSTRUCTURE = "substructure"
FILTER_KINDS: tuple[str, ...] = (FILTER_NUMERIC, FILTER_TEXT, FILTER_SUBSTRUCTURE)

_STEP_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REF = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\}")
_KIND_PREFIX = {
    STEP_DESCRIPTORS: "desc",
    STEP_CALCULATOR: "calc",
    STEP_PROTONATE: "prot",
    STEP_FILTER: "filt",
    STEP_REACTION: "rxn",
    STEP_RANDOM: "rand",
    STEP_EXTRACT: "ext",
    STEP_PLOT: "plot",
    STEP_POTENCY: "pot",
    STEP_RGROUP: "rgrp",
    STEP_EXPLICIT_H: "hadd",
    STEP_REMOVE_H: "hrem",
    STEP_NEUTRALIZE: "neut",
    STEP_FAST_PREPARE: "prep",
}

# Two-reactant amide coupling. Used when a new reaction step needs a valid SMARTS.
_DEFAULT_REACTION_SMARTS = "[C:1](=[O:2])O.[N:3]>>[C:1](=[O:2])[N:3]"

_DESCRIPTOR_INDEX: dict[str, str] | None = None


class MacroDocumentError(ValueError):
    """The JSON is not a macro document."""


class MacroReferenceError(ValueError):
    """A ``${step.key}`` reference could not be resolved while a macro was running."""


@dataclass
class MacroStep:
    """One saved tool invocation."""

    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class MacroRecipe:
    """A named, ordered list of steps."""

    id: str
    name: str
    steps: list[MacroStep] = field(default_factory=list)


@dataclass(frozen=True)
class MacroIssue:
    """One reason a recipe should not run."""

    message: str
    step_id: str = ""


def new_recipe_id() -> str:
    """A new library id. Not used inside column references."""
    return uuid.uuid4().hex[:12]


def new_recipe(name: str) -> MacroRecipe:
    """An empty recipe with a fresh id."""
    return MacroRecipe(id=new_recipe_id(), name=str(name or "Macro").strip() or "Macro")


def new_step_id(kind: str, existing_ids: set[str]) -> str:
    """``desc1``, ``calc2``, … skipping ids already in the recipe."""
    prefix = _KIND_PREFIX.get(kind, "step")
    number = 1
    while f"{prefix}{number}" in existing_ids:
        number += 1
    return f"{prefix}{number}"


def default_step(kind: str, existing_ids: set[str]) -> MacroStep:
    """A runnable starting point for *kind*. Reaction reactants are small SMILES samples."""
    if kind not in STEP_LABELS:
        raise MacroDocumentError(f"Unknown step kind {kind!r}.")
    step_id = new_step_id(kind, existing_ids)
    return MacroStep(id=step_id, kind=kind, params=_default_params(kind))


def descriptor_display_by_key() -> dict[str, str]:
    """Internal descriptor key → column title, from the Calculate Descriptors catalog."""
    global _DESCRIPTOR_INDEX
    if _DESCRIPTOR_INDEX is None:
        from ..descriptors.catalog import iter_descriptor_tab_items

        index: dict[str, str] = {}
        for _tab, items in iter_descriptor_tab_items():
            for display, key in items:
                index[str(key)] = str(display)
        _DESCRIPTOR_INDEX = index
    return _DESCRIPTOR_INDEX


def descriptor_tabs() -> tuple[tuple[str, tuple[tuple[str, str], ...]], ...]:
    """Calculate Descriptors tabs as ``(tab, ((display, key), ...))``."""
    from ..descriptors.catalog import iter_descriptor_tab_items

    return iter_descriptor_tab_items()


def output_keys(kind: str, params: Mapping[str, Any]) -> tuple[str, ...]:
    """Binding names later steps may use as ``${thisStep.key}``."""
    if kind == STEP_DESCRIPTORS:
        keys: list[str] = []
        for key in params.get("descriptors") or []:
            text = str(key).strip()
            if _STEP_ID.match(text) and text not in keys:
                keys.append(text)
        return tuple(keys)
    if kind == STEP_CALCULATOR:
        return ("output",)
    if kind == STEP_PROTONATE:
        return ("output", "percent", "pka")
    if kind == STEP_RANDOM:
        return ("output",)
    if kind == STEP_EXTRACT:
        return _identifier_keys(params.get("published"))
    if kind == STEP_POTENCY:
        return potency_output_keys(params)
    if kind in (STEP_EXPLICIT_H, STEP_REMOVE_H, STEP_NEUTRALIZE):
        return ("output",)
    if kind == STEP_FAST_PREPARE:
        return ("output", "fragments")
    return ()


def potency_output_keys(params: Mapping[str, Any]) -> tuple[str, ...]:
    """Stable names for the columns one potency step writes, in write order."""
    from ..chem.potency import PKI_HEADER, activity_header, p_header

    measure = str(params.get("measure") or "")
    unit = str(params.get("desired_unit") or "")
    write_p = bool(params.get("write_p"))
    write_ki = bool(params.get("write_ki"))
    pairs: list[tuple[str, str]] = [("activity", activity_header(measure, unit))]
    if write_p:
        pairs.append(("p", p_header(measure)))
    if write_ki:
        ki_header = activity_header("Ki", unit)
        if ki_header not in [header for _key, header in pairs]:
            pairs.append(("ki", ki_header))
        if write_p and PKI_HEADER not in [header for _key, header in pairs]:
            pairs.append(("pki", PKI_HEADER))
    return tuple(key for key, _header in pairs)


def step_summary(step: MacroStep) -> str:
    """Short label for a step list."""
    label = STEP_LABELS.get(step.kind, step.kind)
    return f"{step.id}  {label}"


def substitute_column_refs(
    text: str,
    bindings: Mapping[str, Mapping[str, str]],
    *,
    quote_for_calculator: bool = False,
) -> str:
    """Replace ``${step.key}`` with the column name bound when that step finished.

    Calculator mode wraps a name that is not a Python identifier in ``[brackets]``
    unless the reference is already inside brackets. ``MolWt (1)`` is a real
    uniquified header and is not a bare calculator token.
    """

    def _replace(match: re.Match[str]) -> str:
        step_id, key = match.group(1), match.group(2)
        try:
            name = str(bindings[step_id][key])
        except KeyError as exc:
            raise MacroReferenceError(f"Unknown column reference ${{{step_id}.{key}}}.") from exc
        if not quote_for_calculator:
            return name
        if match.start() > 0 and text[match.start() - 1] == "[":
            return name
        if name.isidentifier():
            return name
        return f"[{name}]"

    return _REF.sub(_replace, str(text))


def recipe_to_json(recipe: MacroRecipe) -> dict[str, Any]:
    """A JSON-ready object. Library files wrap these in :func:`library_to_json`."""
    return {
        "id": recipe.id,
        "name": recipe.name,
        "steps": [step_to_json(step) for step in recipe.steps],
    }


def step_to_json(step: MacroStep) -> dict[str, Any]:
    """One step as plain JSON types."""
    return {"id": step.id, "kind": step.kind, "params": _plain(step.params)}


def recipe_from_json(payload: Any) -> MacroRecipe:
    """Parse one recipe. Raises :class:`MacroDocumentError` when the shape is wrong."""
    if not isinstance(payload, dict):
        raise MacroDocumentError("A macro must be an object.")
    name = payload.get("name", "")
    if not isinstance(name, str):
        raise MacroDocumentError("Macro name must be a string.")
    raw_steps = payload.get("steps", [])
    if not isinstance(raw_steps, list):
        raise MacroDocumentError('Macro "steps" must be a list.')
    recipe_id = payload.get("id")
    if not isinstance(recipe_id, str) or not recipe_id.strip():
        recipe_id = new_recipe_id()
    steps: list[MacroStep] = []
    for item in raw_steps:
        steps.append(_step_from_json(item))
    return MacroRecipe(id=recipe_id.strip(), name=name, steps=steps)


def library_to_json(recipes: Sequence[MacroRecipe]) -> dict[str, Any]:
    """The on-disk library document."""
    return {"version": 1, "macros": [recipe_to_json(recipe) for recipe in recipes]}


def library_from_json(payload: Any) -> list[MacroRecipe]:
    """Parse a library. Entries that are not documents are skipped.

    A wrong top-level shape or version still raises, so a settings blob from a
    newer MolManager is not silently treated as empty.
    """
    if not isinstance(payload, dict):
        raise MacroDocumentError("Macro library must be an object.")
    version = payload.get("version", 1)
    if version != 1:
        raise MacroDocumentError(f"Unsupported macro library version {version}.")
    raw = payload.get("macros", [])
    if not isinstance(raw, list):
        raise MacroDocumentError('Macro library "macros" must be a list.')
    recipes: list[MacroRecipe] = []
    for item in raw:
        try:
            recipes.append(recipe_from_json(item))
        except MacroDocumentError:
            continue
    return recipes


def validate_recipe(
    recipe: MacroRecipe,
    *,
    descriptor_keys: set[str] | None = None,
) -> tuple[MacroIssue, ...]:
    """Return every problem that should stop Run. An empty tuple means the recipe can start.

    Pass *descriptor_keys* in tests to avoid loading the descriptor catalog. The
    editor leaves it unset and checks the real catalog.
    """
    issues: list[MacroIssue] = []
    if not str(recipe.name or "").strip():
        issues.append(MacroIssue("Enter a name for the macro."))
    if not recipe.steps:
        issues.append(MacroIssue("Add at least one step."))
    known = descriptor_keys
    seen: set[str] = set()
    declared: dict[str, set[str]] = {}
    order = [step.id for step in recipe.steps]
    for step in recipe.steps:
        if not _STEP_ID.match(step.id):
            issues.append(
                MacroIssue(
                    "Step id must start with a letter and use only "
                    "letters, digits, and underscores.",
                    step.id or "?",
                )
            )
        elif step.id in seen:
            issues.append(MacroIssue(f"Step id {step.id} is used more than once.", step.id))
        else:
            seen.add(step.id)
        if step.kind not in STEP_LABELS:
            issues.append(MacroIssue(f"Unknown step kind {step.kind!r}.", step.id))
            declared[step.id] = set()
            continue
        issues.extend(_validate_step(step, known))
        declared[step.id] = set(output_keys(step.kind, step.params))
        issues.extend(_validate_refs(step, declared, order))
    return tuple(issues)


def format_issues(issues: Sequence[MacroIssue]) -> str:
    """One problem per line, with the step id when the problem belongs to a step."""
    lines: list[str] = []
    for issue in issues:
        if issue.step_id:
            lines.append(f"{issue.step_id}: {issue.message}")
        else:
            lines.append(issue.message)
    return "\n".join(lines)


def _default_params(kind: str) -> dict[str, Any]:
    if kind == STEP_DESCRIPTORS:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "structure_source": "Structure",
            "descriptors": ["MolWt", "MolLogP"],
        }
    if kind == STEP_CALCULATOR:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "column": "Calc",
            "expression": "[MolWt]",
        }
    if kind == STEP_PROTONATE:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "structure_source": "Structure",
            "ph": 7.4,
            "output_column": "Protonated",
            "render_2d": False,
        }
    if kind == STEP_FILTER:
        return {
            "replace": True,
            "clauses": [
                {
                    "kind": FILTER_NUMERIC,
                    "column": "MolWt",
                    "min": 0,
                    "max": 500,
                    "inverted": False,
                }
            ],
        }
    if kind == STEP_RANDOM:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "column": "Random",
            "distribution": "uniform",
            "low": 0.0,
            "high": 1.0,
            "mean": 0.0,
            "std": 1.0,
            "seed": None,
            "decimals": 4,
            "clip_normal": False,
        }
    if kind == STEP_EXTRACT:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "source_column": "Reaction",
            "mode": "both",
            "reactant_prefix": "Reactant",
            "product_prefix": "Product",
            "published": [],
        }
    if kind == STEP_PLOT:
        return {"state": {"kind": "plotter", "plot_type": "scatter", "x": "", "y": ""}}
    if kind == STEP_POTENCY:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "column": "IC50",
            "unit_column": "Unit",
            "measure": "IC50",
            "desired_unit": "nM",
            "write_p": True,
            "write_ki": False,
            "assay_concentrations": [],
            "mw_column": None,
        }
    if kind == STEP_RGROUP:
        return {
            "core_smiles": "[*:1]c1ccccc1",
            "core_id": "core",
            "pools": [{"label": 1, "mode": "smiles", "file_path": "", "smiles_text": "CCN*"}],
            "max_products": 10,
            "output_filters": "",
            "add_to_table": True,
            "save_to_file": False,
            "save_path": "",
        }
    if kind in (STEP_EXPLICIT_H, STEP_REMOVE_H, STEP_NEUTRALIZE):
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "structure_source": "Structure",
            "no_render_2d": False,
        }
    if kind == STEP_FAST_PREPARE:
        return {
            "row_scope": ROW_SCOPE_TABLE,
            "structure_source": "Structure",
            "update_target": True,
            "largest_column": None,
            "fragments_column": "Fragments",
            "neutralize": False,
        }
    return {
        "reaction_name": "Amide coupling",
        "smarts": _DEFAULT_REACTION_SMARTS,
        "reactant_1_mode": "smiles",
        "reactant_1": "CC(=O)O",
        "reactant_2_mode": "smiles",
        "reactant_2": "CN",
        "max_products": 100,
        "output_filters": "",
        "add_to_table": True,
        "save_to_file": False,
        "save_path": "",
    }


def _step_from_json(payload: Any) -> MacroStep:
    if not isinstance(payload, dict):
        raise MacroDocumentError("Each step must be an object.")
    kind = payload.get("kind")
    if not isinstance(kind, str) or not kind.strip():
        raise MacroDocumentError("Each step needs a kind.")
    step_id = payload.get("id")
    if not isinstance(step_id, str) or not step_id.strip():
        raise MacroDocumentError("Each step needs an id.")
    params = payload.get("params", {})
    if not isinstance(params, dict):
        raise MacroDocumentError(f"Step {step_id} params must be an object.")
    return MacroStep(id=step_id.strip(), kind=kind.strip(), params=_plain(params))


def _plain(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise MacroDocumentError(f"Unsupported JSON value {value!r}.")


def _validate_step(step: MacroStep, descriptor_keys: set[str] | None) -> list[MacroIssue]:
    params = step.params
    if step.kind == STEP_DESCRIPTORS:
        return _validate_descriptors(step, params, descriptor_keys)
    if step.kind == STEP_CALCULATOR:
        return _validate_calculator(step, params)
    if step.kind == STEP_PROTONATE:
        return _validate_protonate(step, params)
    if step.kind == STEP_FILTER:
        return _validate_filter(step, params)
    if step.kind == STEP_RANDOM:
        return _validate_random(step, params)
    if step.kind == STEP_EXTRACT:
        return _validate_extract(step, params)
    if step.kind == STEP_PLOT:
        return _validate_plot(step, params)
    if step.kind == STEP_POTENCY:
        return _validate_potency(step, params)
    if step.kind == STEP_RGROUP:
        return _validate_rgroup(step, params)
    if step.kind in (STEP_EXPLICIT_H, STEP_REMOVE_H, STEP_NEUTRALIZE):
        return _validate_structure_edit(step, params)
    if step.kind == STEP_FAST_PREPARE:
        return _validate_fast_prepare(step, params)
    return _validate_reaction(step, params)


def _validate_random(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    column = params.get("column", "")
    if not isinstance(column, str) or not column.strip():
        issues.append(MacroIssue("Enter a name for the random-number column.", step.id))
    distribution = params.get("distribution", "")
    if distribution not in ("uniform", "integer", "normal"):
        issues.append(MacroIssue("Choose a uniform, integer, or normal distribution.", step.id))
    return issues


def _validate_extract(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    source = params.get("source_column", "")
    if not isinstance(source, str) or not source.strip():
        issues.append(MacroIssue("Choose a reaction column to extract.", step.id))
    if params.get("mode") not in ("reactants", "products", "both"):
        issues.append(MacroIssue("Choose reactants, products, or both.", step.id))
    return issues


def _validate_plot(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    state = params.get("state")
    if not isinstance(state, dict) or not state.get("plot_type"):
        return [MacroIssue("This plot step has no saved plot settings.", step.id)]
    return []


def _validate_potency(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    from ..chem.potency import DESIRED_UNITS, MEASURES

    issues = _scope_issues(step, params)
    column = params.get("column", "")
    unit_column = params.get("unit_column", "")
    if not isinstance(column, str) or not column.strip():
        issues.append(MacroIssue("Choose the activity column.", step.id))
    if not isinstance(unit_column, str) or not unit_column.strip():
        issues.append(MacroIssue("Choose the unit column.", step.id))
    if params.get("measure") not in MEASURES:
        issues.append(MacroIssue("Choose an activity measure.", step.id))
    if params.get("desired_unit") not in DESIRED_UNITS:
        issues.append(MacroIssue("Choose nM or uM for the written activity.", step.id))
    if params.get("write_ki"):
        assays = params.get("assay_concentrations")
        if not isinstance(assays, list) or not assays:
            issues.append(MacroIssue("Add an assay concentration for the Ki conversion.", step.id))
    return issues


def _validate_rgroup(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues: list[MacroIssue] = []
    core = params.get("core_smiles", "")
    if not isinstance(core, str) or not core.strip():
        issues.append(MacroIssue("Enter a core SMILES.", step.id))
    pools = params.get("pools")
    if not isinstance(pools, list) or not pools:
        issues.append(MacroIssue("Add a building-block list for each attachment point.", step.id))
    else:
        for pool in pools:
            if not isinstance(pool, dict):
                issues.append(MacroIssue("Each building-block list must be an object.", step.id))
                break
            mode = pool.get("mode")
            text = pool.get("file_path") if mode == "file" else pool.get("smiles_text")
            if mode not in ("file", "smiles") or not str(text or "").strip():
                issues.append(
                    MacroIssue("Each attachment point needs a file or SMILES list.", step.id)
                )
                break
    try:
        if int(params.get("max_products") or 0) < 1:
            issues.append(MacroIssue("Set a product limit of at least 1.", step.id))
    except (TypeError, ValueError):
        issues.append(MacroIssue("Set a product limit of at least 1.", step.id))
    return issues


def _validate_structure_edit(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    source = params.get("structure_source", "")
    if not isinstance(source, str) or not source.strip():
        issues.append(MacroIssue("Choose a structure column.", step.id))
    return issues


def _validate_fast_prepare(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _validate_structure_edit(step, params)
    fragments = params.get("fragments_column", "")
    if not isinstance(fragments, str) or not fragments.strip():
        issues.append(MacroIssue("Name the fragments column.", step.id))
    if not params.get("update_target"):
        largest = params.get("largest_column", "")
        if not isinstance(largest, str) or not largest.strip():
            issues.append(MacroIssue("Name the column for the largest fragment.", step.id))
    return issues


def _validate_descriptors(
    step: MacroStep,
    params: Mapping[str, Any],
    descriptor_keys: set[str] | None,
) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    source = params.get("structure_source", "")
    if not isinstance(source, str) or not source.strip():
        issues.append(MacroIssue("Choose a structure source.", step.id))
    raw_keys = params.get("descriptors")
    if not isinstance(raw_keys, list) or not [
        str(key).strip() for key in raw_keys if str(key).strip()
    ]:
        issues.append(MacroIssue("Choose at least one descriptor.", step.id))
        return issues
    known = descriptor_display_by_key() if descriptor_keys is None else descriptor_keys
    for key in raw_keys:
        text = str(key).strip()
        if text and text not in known:
            issues.append(MacroIssue(f"Unknown descriptor {text}.", step.id))
    return issues


def _validate_calculator(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    column = params.get("column", "")
    if not isinstance(column, str) or not column.strip():
        issues.append(MacroIssue("Enter a name for the calculator column.", step.id))
    expression = params.get("expression", "")
    if not isinstance(expression, str) or not expression.strip():
        issues.append(MacroIssue("Enter a calculator expression.", step.id))
        return issues
    scrubbed = _REF.sub("ref_col", expression)
    scrubbed = re.sub(r"\[[^\]]*\]", "bracket_col", scrubbed)
    try:
        tree = ast.parse(scrubbed, mode="eval")
    except SyntaxError:
        issues.append(MacroIssue("The calculator expression is not valid.", step.id))
        return issues
    if not isinstance(tree, ast.Expression):
        issues.append(MacroIssue("The calculator expression is not valid.", step.id))
    return issues


def _validate_protonate(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues = _scope_issues(step, params)
    source = params.get("structure_source", "")
    if not isinstance(source, str) or not source.strip():
        issues.append(MacroIssue("Choose a structure source.", step.id))
    column = params.get("output_column", "")
    if not isinstance(column, str) or not column.strip():
        issues.append(MacroIssue("Enter an output column for protonation.", step.id))
    ph = _number(params.get("ph"))
    if ph is None or ph < 0.0 or ph > 14.0:
        issues.append(MacroIssue("pH must be a number from 0 to 14.", step.id))
    render = params.get("render_2d", False)
    if not isinstance(render, bool):
        issues.append(MacroIssue("Render 2D must be true or false.", step.id))
    return issues


def _validate_filter(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues: list[MacroIssue] = []
    replace = params.get("replace", True)
    if not isinstance(replace, bool):
        issues.append(MacroIssue("Replace filters must be true or false.", step.id))
    clauses = params.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        issues.append(MacroIssue("Add at least one filter.", step.id))
        return issues
    for index, clause in enumerate(clauses, start=1):
        if not isinstance(clause, dict):
            issues.append(MacroIssue(f"Filter {index} must be an object.", step.id))
            continue
        issues.extend(_validate_clause(step.id, index, clause))
    return issues


def _validate_clause(step_id: str, index: int, clause: Mapping[str, Any]) -> list[MacroIssue]:
    kind = clause.get("kind")
    prefix = f"Filter {index}"
    if kind not in FILTER_KINDS:
        return [MacroIssue(f"{prefix} has an unknown kind.", step_id)]
    inverted = clause.get("inverted", False)
    issues: list[MacroIssue] = []
    if not isinstance(inverted, bool):
        issues.append(MacroIssue(f"{prefix} inverted must be true or false.", step_id))
    if kind == FILTER_SUBSTRUCTURE:
        smarts = clause.get("smarts", "")
        source = clause.get("structure_source", "")
        if not isinstance(smarts, str) or not smarts.strip():
            issues.append(MacroIssue(f"{prefix} needs SMARTS.", step_id))
        elif _smarts_error(smarts.strip()):
            issues.append(MacroIssue(f"{prefix} SMARTS could not be parsed.", step_id))
        if not isinstance(source, str) or not source.strip():
            issues.append(MacroIssue(f"{prefix} needs a structure source.", step_id))
        return issues
    column = clause.get("column", "")
    if not isinstance(column, str) or not column.strip():
        issues.append(MacroIssue(f"{prefix} needs a column.", step_id))
    if kind == FILTER_TEXT:
        text = clause.get("text", "")
        if not isinstance(text, str):
            issues.append(MacroIssue(f"{prefix} text must be a string.", step_id))
        for flag in ("partial_match", "case_sensitive"):
            if flag in clause and not isinstance(clause[flag], bool):
                issues.append(MacroIssue(f"{prefix} {flag} must be true or false.", step_id))
        return issues
    lo = _number(clause.get("min"))
    hi = _number(clause.get("max"))
    if lo is None or hi is None:
        issues.append(MacroIssue(f"{prefix} min and max must be numbers.", step_id))
    elif lo > hi:
        issues.append(MacroIssue(f"{prefix} min is greater than max.", step_id))
    return issues


def _validate_reaction(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    issues: list[MacroIssue] = []
    name = params.get("reaction_name", "")
    if not isinstance(name, str) or not name.strip():
        issues.append(MacroIssue("Enter a reaction name.", step.id))
    smarts = params.get("smarts", "")
    if not isinstance(smarts, str) or not smarts.strip():
        issues.append(MacroIssue("Enter reaction SMARTS.", step.id))
    else:
        message = _reaction_smarts_error(smarts.strip())
        if message:
            issues.append(MacroIssue(message, step.id))
    for slot in (1, 2):
        issues.extend(_validate_reactant(step.id, slot, params))
    products = params.get("max_products")
    if isinstance(products, bool) or not isinstance(products, int):
        issues.append(MacroIssue("Max products must be a positive integer.", step.id))
    elif products < 1:
        issues.append(MacroIssue("Max products must be at least 1.", step.id))
    else:
        cap = _enumeration_cap()
        if products > cap:
            issues.append(
                MacroIssue(f"Max products is capped at {cap:,} (requested {products:,}).", step.id)
            )
    filters = params.get("output_filters", "")
    if filters and not isinstance(filters, str):
        issues.append(MacroIssue("Output filters must be text.", step.id))
    elif isinstance(filters, str) and filters.strip():
        message = _output_filter_error(filters)
        if message:
            issues.append(MacroIssue(message, step.id))
    add_to_table = params.get("add_to_table", True)
    save_to_file = params.get("save_to_file", False)
    if not isinstance(add_to_table, bool) or not isinstance(save_to_file, bool):
        issues.append(MacroIssue("Choose whether to add rows, save a file, or both.", step.id))
    elif not add_to_table and not save_to_file:
        issues.append(MacroIssue("Add the products to the table or save them to a file.", step.id))
    if save_to_file is True:
        path = params.get("save_path", "")
        if not isinstance(path, str) or not path.strip():
            issues.append(MacroIssue("Enter a file path for the products.", step.id))
    return issues


def _validate_reactant(step_id: str, slot: int, params: Mapping[str, Any]) -> list[MacroIssue]:
    mode = params.get(f"reactant_{slot}_mode", "smiles")
    value = params.get(f"reactant_{slot}", "")
    label = f"Reactant {slot}"
    if mode not in ("smiles", "file"):
        return [MacroIssue(f"{label} mode must be smiles or file.", step_id)]
    if not isinstance(value, str) or not value.strip():
        if mode == "file":
            return [MacroIssue(f"{label} needs a file path.", step_id)]
        return [MacroIssue(f"{label} needs SMILES (one structure per line).", step_id)]
    if mode == "smiles":
        message = _smiles_pool_error(value)
        if message:
            return [MacroIssue(f"{label}: {message}", step_id)]
    return []


def _validate_refs(
    step: MacroStep,
    declared: dict[str, set[str]],
    order: list[str],
) -> list[MacroIssue]:
    issues: list[MacroIssue] = []
    seen: set[tuple[str, str]] = set()
    try:
        here = order.index(step.id)
    except ValueError:
        here = -1
    for text in _strings(step.params):
        for step_id, key in _REF.findall(text):
            pair = (step_id, key)
            if pair in seen:
                continue
            seen.add(pair)
            token = f"${{{step_id}.{key}}}"
            if step_id not in order:
                issues.append(MacroIssue(f"Unknown column reference {token}.", step.id))
                continue
            if order.index(step_id) >= here:
                issues.append(MacroIssue(f"{token} points at this step or a later one.", step.id))
                continue
            if key not in declared.get(step_id, set()):
                issues.append(MacroIssue(f"Step {step_id} does not write {token}.", step.id))
    return issues


def _identifier_keys(raw: Any) -> tuple[str, ...]:
    if not isinstance(raw, list):
        return ()
    keys: list[str] = []
    for key in raw:
        text = str(key).strip()
        if _STEP_ID.match(text) and text not in keys:
            keys.append(text)
    return tuple(keys)


def _scope_issues(step: MacroStep, params: Mapping[str, Any]) -> list[MacroIssue]:
    scope = params.get("row_scope", ROW_SCOPE_TABLE)
    if scope not in ROW_SCOPES:
        return [MacroIssue("Row scope must be all rows, selected rows, or visible rows.", step.id)]
    return []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        found: list[str] = []
        for item in value.values():
            found.extend(_strings(item))
        return found
    if isinstance(value, list):
        found = []
        for item in value:
            found.extend(_strings(item))
        return found
    return []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _enumeration_cap() -> int:
    from ..platform_support.config import load_config

    return max(1, int(load_config().memory_guard_enum_max_products))


def _reaction_smarts_error(smarts: str) -> str | None:
    from ..chem.reaction_enumeration import validate_reaction_smarts

    try:
        validate_reaction_smarts(smarts)
    except ValueError as exc:
        return str(exc) or "Reaction SMARTS could not be parsed."
    return None


def _smiles_pool_error(text: str) -> str | None:
    from ..chem.reaction_enumeration import load_reactant_molecules_from_smiles_text

    try:
        load_reactant_molecules_from_smiles_text(text)
    except ValueError as exc:
        return str(exc) or "No valid SMILES were found."
    return None


def _smarts_error(smarts: str) -> str | None:
    from rdkit import Chem

    if Chem.MolFromSmarts(smarts) is None:
        return "SMARTS could not be parsed."
    return None


def _output_filter_error(text: str) -> str | None:
    from ..chem.fragment_recomposition_filters import parse_recomposition_filter_text

    try:
        parse_recomposition_filter_text(text)
    except ValueError as exc:
        return str(exc) or "Output filters could not be parsed."
    return None
