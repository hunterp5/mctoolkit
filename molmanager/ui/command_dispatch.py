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
from ..workflows.macro_recipe import (
    ROW_SCOPE_SELECTION,
    ROW_SCOPE_TABLE,
    ROW_SCOPE_VISIBLE,
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_FILTER,
    STEP_PROTONATE,
    STEP_REACTION,
    MacroReferenceError,
    MacroStep,
    substitute_column_refs,
)
from .job_handle import JobHandle
from .macro_filters import start_macro_filters


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
        else:
            _done(f"Unknown step kind {step.kind!r}.")
    except MacroReferenceError as exc:
        _done(str(exc))
    return handle


def _descriptors(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    error, allowed = _allowed(app, step)
    if error:
        done(error)
        return
    source = _resolve(str(step.params.get("structure_source") or ""), bindings)
    keys = [str(key).strip() for key in step.params.get("descriptors") or [] if str(key).strip()]
    app.start_descriptor_calculation(
        source=source,
        keys=keys,
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
        column=column,
        expression=expression,
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
        source=_resolve(str(params.get("structure_source") or ""), bindings),
        ph=float(params.get("ph", 7.4)),
        output_column=_resolve(str(params.get("output_column") or ""), bindings).strip(),
        render_2d=bool(params.get("render_2d", False)),
        allowed=allowed,
        on_done=done,
    )


def _filters(app: Any, step: MacroStep, bindings: dict[str, dict[str, str]], done) -> None:
    clauses: list[dict[str, Any]] = []
    for clause in step.params.get("clauses") or []:
        item = dict(clause)
        if item.get("column"):
            item["column"] = _resolve(str(item["column"]), bindings).strip()
        if item.get("structure_source"):
            item["structure_source"] = _resolve(str(item["structure_source"]), bindings).strip()
        clauses.append(item)
    start_macro_filters(
        app,
        clauses,
        replace=bool(step.params.get("replace", True)),
        on_done=lambda error: done(error, {}),
    )


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
