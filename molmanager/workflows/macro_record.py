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

"""Turn an accepted tool request into a recipe step, and rewrite column names.

The recorder stores the user's choices. When a later step refers to a header
this recording just wrote, the header is replaced with ``${stepId.key}`` so
replay does not depend on that table's uniquified name.
"""

from __future__ import annotations

import re
from typing import Any

from .macro_recipe import (
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_EXPLICIT_H,
    STEP_EXTRACT,
    STEP_FAST_PREPARE,
    STEP_FILTER,
    STEP_NEUTRALIZE,
    STEP_PLOT,
    STEP_POTENCY,
    STEP_PROTONATE,
    STEP_RANDOM,
    STEP_REACTION,
    STEP_REMOVE_H,
    STEP_RGROUP,
    MacroStep,
)
from .tool_requests import (
    CalculatorColumnRequest,
    DescriptorCalculationRequest,
    ProtonateRequest,
)


def descriptor_step(request: DescriptorCalculationRequest) -> MacroStep:
    """A recipe step for one accepted Calculate Descriptors dialog."""
    return MacroStep(
        id="pending",
        kind=STEP_DESCRIPTORS,
        params={
            "row_scope": request.row_scope,
            "structure_source": request.structure_source,
            "descriptors": list(request.keys),
        },
    )


def calculator_step(request: CalculatorColumnRequest) -> MacroStep:
    """A recipe step for one accepted calculator apply."""
    return MacroStep(
        id="pending",
        kind=STEP_CALCULATOR,
        params={
            "row_scope": request.row_scope,
            "column": request.column,
            "expression": request.expression,
        },
    )


def protonate_step(request: ProtonateRequest) -> MacroStep:
    """A recipe step for one accepted Protonate dialog."""
    return MacroStep(
        id="pending",
        kind=STEP_PROTONATE,
        params={
            "row_scope": request.row_scope,
            "structure_source": request.structure_source,
            "ph": request.ph,
            "output_column": request.output_column,
            "render_2d": request.render_2d,
        },
    )


def reaction_step(request: Any) -> MacroStep:
    """A recipe step for one accepted reaction-enumeration dialog."""
    smiles_1 = request.reactant_smiles_1 if request.reactant_1_mode == "smiles" else ""
    smiles_2 = request.reactant_smiles_2 if request.reactant_2_mode == "smiles" else ""
    file_1 = request.reactant_file_1 if request.reactant_1_mode == "file" else ""
    file_2 = request.reactant_file_2 if request.reactant_2_mode == "file" else ""
    return MacroStep(
        id="pending",
        kind=STEP_REACTION,
        params={
            "reaction_name": request.reaction_name,
            "smarts": request.rxn_smarts,
            "reactant_1_mode": request.reactant_1_mode,
            "reactant_1": smiles_1 or file_1,
            "reactant_2_mode": request.reactant_2_mode,
            "reactant_2": smiles_2 or file_2,
            "max_products": int(request.max_products),
            "output_filters": request.output_filters or "",
            "add_to_table": bool(request.add_to_table),
            "save_to_file": bool(request.save_to_file),
            "save_path": request.save_path or "",
        },
    )


def random_number_step(request: Any, row_scope: str) -> MacroStep:
    """A recipe step for one accepted Random Number dialog."""
    settings = request.params
    return MacroStep(
        id="pending",
        kind=STEP_RANDOM,
        params={
            "row_scope": row_scope,
            "column": request.column_name,
            "distribution": settings.distribution,
            "low": settings.low,
            "high": settings.high,
            "mean": settings.mean,
            "std": settings.std,
            "seed": settings.seed,
            "decimals": settings.decimals,
            "clip_normal": settings.clip_normal,
        },
    )


def extract_step(request: Any, row_scope: str) -> MacroStep:
    """A recipe step for one accepted Extract Reaction Info dialog."""
    return MacroStep(
        id="pending",
        kind=STEP_EXTRACT,
        params={
            "row_scope": row_scope,
            "source_column": request.source_column,
            "mode": request.mode,
            "reactant_prefix": request.reactant_prefix,
            "product_prefix": request.product_prefix,
        },
    )


def potency_step(request: Any, row_scope: str) -> MacroStep:
    """A recipe step for one accepted potency apply."""
    return MacroStep(
        id="pending",
        kind=STEP_POTENCY,
        params={
            "row_scope": row_scope,
            "column": request.column,
            "unit_column": request.unit_column,
            "measure": request.measure,
            "desired_unit": request.desired_unit,
            "write_p": bool(request.write_p),
            "write_ki": bool(request.write_ki),
            "mw_column": request.mw_column,
            "assay_concentrations": [_assay_param(term) for term in request.assay_concentrations],
        },
    )


def _assay_param(term: Any) -> dict[str, Any]:
    return {
        "conc_constant": term.conc_constant,
        "conc_column": term.conc_column,
        "conc_unit": term.conc_unit,
        "ref_constant": term.ref_constant,
        "ref_column": term.ref_column,
        "ref_unit": term.ref_unit,
    }


def rgroup_step(request: Any) -> MacroStep:
    """A recipe step for one accepted R-group enumeration."""
    pools = [
        {
            "label": int(pool.label),
            "mode": pool.mode,
            "file_path": pool.file_path or "",
            "smiles_text": pool.smiles_text or "",
        }
        for pool in request.pools
    ]
    return MacroStep(
        id="pending",
        kind=STEP_RGROUP,
        params={
            "core_smiles": request.core_smiles,
            "core_id": request.core_id,
            "pools": pools,
            "max_products": int(request.max_products),
            "output_filters": request.output_filters or "",
            "add_to_table": bool(request.add_to_table),
            "save_to_file": bool(request.save_to_file),
            "save_path": request.save_path or "",
        },
    )


def structure_edit_step(
    kind: str, source: str, *, only_selected: bool, no_render_2d: bool
) -> MacroStep:
    """A recipe step for explicit hydrogens or neutralize."""
    from .tool_requests import row_scope_from_only_selected

    return MacroStep(
        id="pending",
        kind=kind,
        params={
            "row_scope": row_scope_from_only_selected(only_selected),
            "structure_source": source,
            "no_render_2d": bool(no_render_2d),
        },
    )


def fast_prepare_step(config: Any) -> MacroStep:
    """A recipe step for one accepted Fast Prepare dialog."""
    from .tool_requests import row_scope_from_only_selected

    return MacroStep(
        id="pending",
        kind=STEP_FAST_PREPARE,
        params={
            "row_scope": row_scope_from_only_selected(config.only_selected),
            "structure_source": config.source_column,
            "update_target": bool(config.update_target),
            "largest_column": config.largest_column,
            "fragments_column": config.fragments_column,
            "neutralize": bool(config.neutralize),
        },
    )


def plot_step(state: dict[str, Any]) -> MacroStep:
    """A recipe step that restores plotter settings. Zoom and pan are not included."""
    copied = _copy_param(state) if isinstance(state, dict) else {}
    return MacroStep(id="pending", kind=STEP_PLOT, params={"state": copied})


def rewrite_recorded_params(
    kind: str,
    params: dict[str, Any],
    bindings: dict[str, dict[str, str]],
) -> dict[str, Any]:
    """Copy *params*, replacing headers from *bindings* with ``${stepId.key}``."""
    updated = {key: _copy_param(value) for key, value in params.items()}
    if kind == STEP_DESCRIPTORS:
        updated["structure_source"] = rewrite_recorded_text(
            str(updated.get("structure_source") or ""), bindings
        )
    elif kind == STEP_CALCULATOR:
        updated["expression"] = rewrite_recorded_text(
            str(updated.get("expression") or ""), bindings
        )
    elif kind == STEP_PROTONATE:
        updated["structure_source"] = rewrite_recorded_text(
            str(updated.get("structure_source") or ""), bindings
        )
    elif kind == STEP_FILTER:
        clauses = []
        for clause in updated.get("clauses") or []:
            if not isinstance(clause, dict):
                clauses.append(clause)
                continue
            item = dict(clause)
            if item.get("column"):
                item["column"] = rewrite_recorded_text(str(item["column"]), bindings)
            if item.get("structure_source"):
                item["structure_source"] = rewrite_recorded_text(
                    str(item["structure_source"]), bindings
                )
            clauses.append(item)
        updated["clauses"] = clauses
    elif kind == STEP_EXTRACT:
        updated["source_column"] = rewrite_recorded_text(
            str(updated.get("source_column") or ""), bindings
        )
    elif kind == STEP_PLOT:
        state = updated.get("state")
        if isinstance(state, dict):
            updated["state"] = _rewrite_plot_state(state, bindings)
    elif kind == STEP_POTENCY:
        _rewrite_named_fields(updated, ("column", "unit_column", "mw_column"), bindings)
        assays = []
        for item in updated.get("assay_concentrations") or []:
            if not isinstance(item, dict):
                assays.append(item)
                continue
            row = dict(item)
            _rewrite_named_fields(row, ("conc_column", "ref_column"), bindings)
            assays.append(row)
        updated["assay_concentrations"] = assays
    elif kind in (STEP_EXPLICIT_H, STEP_REMOVE_H, STEP_NEUTRALIZE, STEP_FAST_PREPARE):
        _rewrite_named_fields(updated, ("structure_source",), bindings)
    return updated


def _rewrite_named_fields(
    params: dict[str, Any], names: tuple[str, ...], bindings: dict[str, dict[str, str]]
) -> None:
    for name in names:
        value = params.get(name)
        if isinstance(value, str) and value:
            params[name] = rewrite_recorded_text(value, bindings)


_PLOT_TEXT_FIELDS = ("x", "y", "z", "color", "size")
_PLOT_LIST_FIELDS = ("radar_spokes", "hover_columns")


def _rewrite_plot_state(
    state: dict[str, Any], bindings: dict[str, dict[str, str]]
) -> dict[str, Any]:
    """Rewrite axis, color, size, spoke, and hover column names. Titles stay as written."""
    updated = dict(state)
    for key in _PLOT_TEXT_FIELDS:
        value = updated.get(key)
        if isinstance(value, str) and value:
            updated[key] = rewrite_recorded_text(value, bindings)
    for key in _PLOT_LIST_FIELDS:
        values = updated.get(key)
        if isinstance(values, list):
            updated[key] = [
                rewrite_recorded_text(item, bindings) if isinstance(item, str) and item else item
                for item in values
            ]
    return updated


def rewrite_recorded_text(text: str, bindings: dict[str, dict[str, str]]) -> str:
    """Replace written headers with column references. Longer headers win."""
    pairs: list[tuple[str, str]] = []
    for step_id, outputs in bindings.items():
        for key, header in outputs.items():
            name = str(header or "")
            if name:
                pairs.append((name, f"${{{step_id}.{key}}}"))
    pairs.sort(key=lambda item: len(item[0]), reverse=True)
    updated = text
    for header, token in pairs:
        if header.isidentifier():
            updated = re.sub(rf"\b{re.escape(header)}\b", lambda _match, t=token: t, updated)
        elif header in updated:
            updated = updated.replace(header, token)
    return updated


def _copy_param(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy_param(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_param(item) for item in value]
    return value
