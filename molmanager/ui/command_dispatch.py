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

"""Start one recipe step and return a handle for when it finishes.

Column references are resolved here, against the bindings from earlier steps.
The host is whatever object already has the tool entry points (the main
window). This module does not accept an AppKernel type and does not open a
dialog.
"""

from __future__ import annotations

from typing import Any

from ..chem.reaction_enumeration import ReactionEnumerationRequest
from ..workflows.command_catalog import command_for_step_kind
from ..workflows.tool_requests import (
    CalculatorColumnRequest,
    DescriptorCalculationRequest,
    ProtonateRequest,
    filter_request_from_params,
)
from ..workflows.macro_recipe import (
    ROW_SCOPE_SELECTION,
    ROW_SCOPE_TABLE,
    ROW_SCOPE_VISIBLE,
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
    STEP_SIMULATION,
    MacroReferenceError,
    MacroStep,
    substitute_column_refs,
)
from .job_handle import JobHandle
from .macro_filters import start_macro_filters
from .macro_recorder import observe_if_recording


def dispatch_step(
    app: Any,
    step: MacroStep,
    bindings: dict[str, dict[str, str]],
) -> JobHandle:
    """Run *step* on *app*. The handle finishes after the tool's writeback."""
    spec = command_for_step_kind(step.kind)
    command_id = spec.command_id if spec is not None else step.kind
    handle = JobHandle(command_id, app if _is_qobject(app) else None)

    def _done(error: str | None, outputs: dict[str, str] | None = None) -> None:
        if error:
            handle.fail(error, cancelled=error == "Cancelled.")
        else:
            handle.succeed(outputs)

    try:
        if step.kind == STEP_DESCRIPTORS:
            _descriptors(app, step, bindings, _done)
        elif step.kind == STEP_CALCULATOR:
            _calculator(app, step, bindings, _done)
        elif step.kind == STEP_PROTONATE:
            _protonate(app, step, bindings, _done)
        elif step.kind == STEP_FILTER:
            _filters(app, step, bindings, _done)
        elif step.kind == STEP_REACTION:
            _reaction(app, step, _done)
        elif step.kind == STEP_RANDOM:
            _random_number(app, step, bindings, _done)
        elif step.kind == STEP_EXTRACT:
            _extract(app, step, bindings, _done)
        elif step.kind == STEP_PLOT:
            _plot(app, step, bindings, _done)
        elif step.kind == STEP_POTENCY:
            _potency(app, step, bindings, _done)
        elif step.kind == STEP_RGROUP:
            _rgroup(app, step, _done)
        elif step.kind in (STEP_EXPLICIT_H, STEP_REMOVE_H, STEP_NEUTRALIZE):
            _structure_edit(app, step, bindings, _done)
        elif step.kind == STEP_FAST_PREPARE:
            _fast_prepare(app, step, bindings, _done)
        elif step.kind == STEP_SIMULATION:
            _simulation(app, step, _done)
        else:
            _done(f"Unknown step kind {step.kind!r}.")
    except MacroReferenceError as exc:
        _done(str(exc))
    observe_if_recording(app, step, handle)
    return handle


def _descriptors(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    source = _resolve(str(step.params.get("structure_source") or ""), bindings)
    keys = tuple(
        str(key).strip() for key in step.params.get("descriptors") or [] if str(key).strip()
    )
    app.start_descriptor_calculation(
        DescriptorCalculationRequest(
            structure_source=source,
            keys=keys,
            row_scope=str(step.params.get("row_scope") or ROW_SCOPE_TABLE),
        ),
        allowed=allowed,
        on_done=done,
    )


def _calculator(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    column = _resolve(str(step.params.get("column") or ""), bindings).strip()
    expression = substitute_column_refs(
        str(step.params.get("expression") or ""),
        bindings,
        quote_for_calculator=True,
    )
    app.start_calculator_job(
        CalculatorColumnRequest(
            column=column,
            expression=expression,
            row_scope=str(step.params.get("row_scope") or ROW_SCOPE_TABLE),
        ),
        allowed=allowed,
        on_done=done,
    )


def _protonate(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = step.params
    app.start_protonate_job(
        ProtonateRequest(
            structure_source=_resolve(str(params.get("structure_source") or ""), bindings),
            ph=float(params.get("ph", 7.4)),
            output_column=_resolve(str(params.get("output_column") or ""), bindings).strip(),
            render_2d=bool(params.get("render_2d", False)),
            row_scope=str(params.get("row_scope") or ROW_SCOPE_TABLE),
        ),
        allowed=allowed,
        on_done=done,
    )


def _filters(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    try:
        request = filter_request_from_params(
            step.params, resolve=lambda text: _resolve(text, bindings)
        )
    except (KeyError, TypeError, ValueError) as exc:
        done(str(exc) or "The filter step could not be read.")
        return
    start_macro_filters(app, request, on_done=lambda error: done(error, {}))


def _reaction(app: Any, step: MacroStep, done) -> None:
    params = step.params
    request = ReactionEnumerationRequest(
        reaction_name=str(params.get("reaction_name") or "Reaction").strip() or "Reaction",
        rxn_smarts=str(params.get("smarts") or "").strip(),
        reactant_1_mode=str(params.get("reactant_1_mode") or "smiles"),
        reactant_2_mode=str(params.get("reactant_2_mode") or "smiles"),
        reactant_file_1=_reactant_file(params, 1),
        reactant_file_2=_reactant_file(params, 2),
        reactant_smiles_1=_reactant_smiles(params, 1),
        reactant_smiles_2=_reactant_smiles(params, 2),
        max_products=int(params.get("max_products") or 1),
        output_filters=str(params.get("output_filters") or ""),
        add_to_table=bool(params.get("add_to_table", True)),
        save_to_file=bool(params.get("save_to_file", False)),
        save_path=str(params.get("save_path") or "").strip() or None,
    )
    app.start_reaction_enumeration(request, on_done=done)


def _random_number(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = dict(step.params)
    params["column"] = _resolve(str(params.get("column") or ""), bindings).strip()
    app.start_random_number_job(params, allowed=allowed, on_done=done)


def _extract(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = dict(step.params)
    params["source_column"] = _resolve(str(params.get("source_column") or ""), bindings).strip()
    app.start_reaction_extract_job(params, allowed=allowed, on_done=done)


def _potency(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = _copy_state(step.params)
    for name in ("column", "unit_column", "mw_column"):
        value = params.get(name)
        if isinstance(value, str) and value:
            params[name] = _resolve(value, bindings).strip()
    assays = []
    for item in params.get("assay_concentrations") or []:
        if not isinstance(item, dict):
            assays.append(item)
            continue
        row = dict(item)
        for name in ("conc_column", "ref_column"):
            value = row.get(name)
            if isinstance(value, str) and value:
                row[name] = _resolve(value, bindings).strip()
        assays.append(row)
    params["assay_concentrations"] = assays
    app.start_potency_job(params, allowed=allowed, on_done=done)


def _rgroup(app: Any, step: MacroStep, done) -> None:
    app.start_rgroup_enumeration(dict(step.params), on_done=done)


def _structure_edit(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = dict(step.params)
    params["structure_source"] = _resolve(
        str(params.get("structure_source") or ""), bindings
    ).strip()
    if step.kind == STEP_EXPLICIT_H:
        app.start_explicit_hydrogens_job(params, allowed=allowed, on_done=done)
    elif step.kind == STEP_REMOVE_H:
        app.start_remove_explicit_hydrogens_job(params, allowed=allowed, on_done=done)
    else:
        app.start_neutralize_job(params, allowed=allowed, on_done=done)


def _fast_prepare(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    params = dict(step.params)
    params["structure_source"] = _resolve(
        str(params.get("structure_source") or ""), bindings
    ).strip()
    app.start_fast_prepare_job(params, allowed=allowed, on_done=done)


def _simulation(app: Any, step: MacroStep, done) -> None:
    """Run a saved simulation document, or a shipped preset, from a macro."""
    starter = getattr(app, "start_simulation_macro", None)
    if not callable(starter):
        done("Simulation is not available in this window.")
        return
    params = step.params
    starter(
        str(params.get("document_path") or ""),
        str(params.get("preset") or ""),
        str(params.get("row_scope") or "selection"),
        done,
    )


def _plot(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    state = step.params.get("state")
    if not isinstance(state, dict):
        done("This plot step has no saved plot settings.")
        return
    try:
        app.apply_recorded_plot(_resolve_plot_state(state, bindings))
    except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
        done(str(exc) or "The plot could not be restored.")
        return
    done(None, {})


_PLOT_TEXT_FIELDS = ("x", "y", "z", "color", "size")
_PLOT_LIST_FIELDS = ("radar_spokes", "hover_columns")


def _resolve_plot_state(
    state: dict[str, Any], bindings: dict[str, dict[str, str]]
) -> dict[str, Any]:
    updated = _copy_state(state)
    for key in _PLOT_TEXT_FIELDS:
        value = updated.get(key)
        if isinstance(value, str) and value:
            updated[key] = _resolve(value, bindings)
    for key in _PLOT_LIST_FIELDS:
        values = updated.get(key)
        if isinstance(values, list):
            updated[key] = [
                _resolve(item, bindings) if isinstance(item, str) and item else item
                for item in values
            ]
    return updated


def _copy_state(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy_state(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy_state(item) for item in value]
    return value


def _allowed(app: Any, step: MacroStep) -> tuple[str | None, set[int] | None]:
    """``(error, oids)``. ``oids is None`` means every row."""
    scope = str(step.params.get("row_scope") or ROW_SCOPE_TABLE)
    if scope == ROW_SCOPE_TABLE:
        return None, None
    if scope == ROW_SCOPE_SELECTION:
        selected = {int(oid) for oid in (app._selected_oids_set() or set())}
        if not selected:
            return "This step uses selected rows, and nothing is selected.", None
        return None, selected
    if scope == ROW_SCOPE_VISIBLE:
        visible = app._filter_proxy_model.visible_oids()
        if visible is None:
            return None, None
        if not visible:
            return "This step uses visible rows, and the filters hide every row.", None
        return None, {int(oid) for oid in visible}
    return f"Unknown row scope {scope!r}.", None


def _resolve(text: str, bindings: dict[str, dict[str, str]]) -> str:
    return substitute_column_refs(text, bindings)


def _reactant_file(params: dict[str, Any], slot: int) -> str:
    if str(params.get(f"reactant_{slot}_mode") or "") != "file":
        return ""
    return str(params.get(f"reactant_{slot}") or "")


def _reactant_smiles(params: dict[str, Any], slot: int) -> str:
    if str(params.get(f"reactant_{slot}_mode") or "smiles") != "smiles":
        return ""
    return str(params.get(f"reactant_{slot}") or "")


def _is_qobject(obj: Any) -> bool:
    try:
        from PyQt5.QtCore import QObject
    except ImportError:
        return False
    return isinstance(obj, QObject)
