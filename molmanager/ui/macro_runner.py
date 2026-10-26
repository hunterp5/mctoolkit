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

"""Run a macro recipe one step at a time on the GUI thread.

Each step calls the same entry point as its dialog, then waits until that
tool's table write (or filter apply) finishes. The wait is a one-shot
callback on the window. That is enough for an explicit recipe and is the
piece click-recording has to replace with a real per-job handle.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from ..workflows.macro_recipe import (
    ROW_SCOPE_SELECTION,
    ROW_SCOPE_TABLE,
    ROW_SCOPE_VISIBLE,
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_FILTER,
    STEP_PROTONATE,
    STEP_REACTION,
    MacroRecipe,
    MacroReferenceError,
    MacroStep,
    step_summary,
    substitute_column_refs,
    validate_recipe,
)
from .macro_filters import ensure_numeric_bounds, start_macro_filters

logger = logging.getLogger(__name__)


class MacroRunner(QObject):
    """Play one recipe. ``finished(ok, message)`` fires on the GUI thread."""

    progressed = pyqtSignal(str)
    finished = pyqtSignal(bool, str)

    def __init__(self, app: Any, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._app = app
        self._recipe: MacroRecipe | None = None
        self._steps: list[MacroStep] = []
        self._index = 0
        self._bindings: dict[str, dict[str, str]] = {}
        self._generation = 0
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    def start(self, recipe: MacroRecipe) -> None:
        """Validate *recipe* and start step 1. A second start while running is ignored."""
        if self._running:
            self.finished.emit(False, "A macro is already running.")
            return
        issues = validate_recipe(recipe)
        if issues:
            self.finished.emit(False, issues[0].message)
            return
        app = self._app
        if app is None or not getattr(app, "headers", None) or app._table_model.rowCount() == 0:
            self.finished.emit(False, "Load a table before running a macro.")
            return
        queue = getattr(app, "process_queue", None)
        busy = getattr(queue, "has_outstanding_work", None)
        if callable(busy) and busy():
            self.finished.emit(
                False,
                "A tool is already running. Wait for it to finish before starting a macro.",
            )
            return
        self._generation += 1
        self._running = True
        self._recipe = recipe
        self._steps = list(recipe.steps)
        self._index = 0
        self._bindings = {}
        self._kick(self._generation)

    def cancel(self) -> None:
        """Stop after the current tool notices cancellation. Later steps do not start."""
        if not self._running:
            return
        self._clear_hooks()
        app = self._app
        queue = getattr(app, "process_queue", None)
        cancel_running = getattr(queue, "cancel_running", None)
        if callable(cancel_running):
            cancel_running()
        cancel_filters = getattr(app, "_cancel_async_filter_apply", None)
        if callable(cancel_filters):
            cancel_filters()
        self._finish(False, "Cancelled.")

    def _kick(self, generation: int) -> None:
        if generation != self._generation or not self._running:
            return
        recipe = self._recipe
        if recipe is None:
            return
        if self._index >= len(self._steps):
            self._finish(True, f'Macro "{recipe.name}" finished.')
            return
        step = self._steps[self._index]
        message = (
            f'Macro "{recipe.name}": step {self._index + 1} of {len(self._steps)}'
            f" — {step_summary(step)}"
        )
        self.progressed.emit(message)
        self._set_status(message)
        try:
            self._dispatch(step, generation)
        except (AttributeError, MacroReferenceError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("Macro step failed to start")
            self._on_step_finished(generation, step.id, str(exc) or "The step could not start.", {})

    def _dispatch(self, step: MacroStep, generation: int) -> None:
        def _done(error: str | None, outputs: dict[str, str] | None = None) -> None:
            self._on_step_finished(generation, step.id, error, outputs or {})

        try:
            if step.kind == STEP_DESCRIPTORS:
                self._descriptors(step, _done)
            elif step.kind == STEP_CALCULATOR:
                self._calculator(step, _done)
            elif step.kind == STEP_PROTONATE:
                self._protonate(step, _done)
            elif step.kind == STEP_FILTER:
                self._filters(step, _done)
            elif step.kind == STEP_REACTION:
                self._reaction(step, _done)
            else:
                _done(f"Unknown step kind {step.kind!r}.")
        except MacroReferenceError as exc:
            _done(str(exc))

    def _on_step_finished(
        self,
        generation: int,
        step_id: str,
        error: str | None,
        outputs: dict[str, str],
    ) -> None:
        if generation != self._generation or not self._running:
            return
        if self._index >= len(self._steps) or self._steps[self._index].id != step_id:
            return
        step = self._steps[self._index]
        if error:
            self._finish(False, f"{step_summary(step)}: {error}")
            return
        self._bindings[step_id] = dict(outputs)
        ensure_numeric_bounds(self._app, list(outputs.values()))
        self._index += 1
        QTimer.singleShot(0, lambda gen=generation: self._kick(gen))

    def _descriptors(self, step: MacroStep, done) -> None:
        error, allowed = self._allowed(step)
        if error:
            done(error)
            return
        source = self._resolve(str(step.params.get("structure_source") or ""))
        keys = [
            str(key).strip() for key in step.params.get("descriptors") or [] if str(key).strip()
        ]
        self._app.start_descriptor_calculation(
            source=source,
            keys=keys,
            allowed=allowed,
            on_done=done,
        )

    def _calculator(self, step: MacroStep, done) -> None:
        error, allowed = self._allowed(step)
        if error:
            done(error)
            return
        column = self._resolve(str(step.params.get("column") or "")).strip()
        expression = substitute_column_refs(
            str(step.params.get("expression") or ""),
            self._bindings,
            quote_for_calculator=True,
        )
        self._app.start_calculator_job(
            column=column,
            expression=expression,
            allowed=allowed,
            on_done=done,
        )

    def _protonate(self, step: MacroStep, done) -> None:
        error, allowed = self._allowed(step)
        if error:
            done(error)
            return
        params = step.params
        self._app.start_protonate_job(
            source=self._resolve(str(params.get("structure_source") or "")),
            ph=float(params.get("ph", 7.4)),
            output_column=self._resolve(str(params.get("output_column") or "")).strip(),
            render_2d=bool(params.get("render_2d", False)),
            allowed=allowed,
            on_done=done,
        )

    def _filters(self, step: MacroStep, done) -> None:
        clauses: list[dict[str, Any]] = []
        for clause in step.params.get("clauses") or []:
            item = dict(clause)
            if item.get("column"):
                item["column"] = self._resolve(str(item["column"])).strip()
            if item.get("structure_source"):
                item["structure_source"] = self._resolve(str(item["structure_source"])).strip()
            clauses.append(item)
        start_macro_filters(
            self._app,
            clauses,
            replace=bool(step.params.get("replace", True)),
            on_done=lambda error: done(error, {}),
        )

    def _reaction(self, step: MacroStep, done) -> None:
        from ..chem.reaction_enumeration import ReactionEnumerationRequest

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
        self._app.start_reaction_enumeration(request, on_done=done)

    def _allowed(self, step: MacroStep) -> tuple[str | None, set[int] | None]:
        """``(error, oids)``. ``oids is None`` means every row."""
        scope = str(step.params.get("row_scope") or ROW_SCOPE_TABLE)
        app = self._app
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

    def _resolve(self, text: str) -> str:
        return substitute_column_refs(text, self._bindings)

    def _finish(self, ok: bool, message: str) -> None:
        if not self._running:
            return
        self._running = False
        self._generation += 1
        self._clear_hooks()
        self._set_status(message)
        self.finished.emit(ok, message)

    def _clear_hooks(self) -> None:
        app = self._app
        if app is None:
            return
        for name in (
            "_macro_descriptor_done",
            "_calculator_on_done",
            "_protonate_on_done",
            "_macro_reaction_done",
            "_macro_filter_done",
        ):
            if getattr(app, name, None) is not None:
                setattr(app, name, None)

    def _set_status(self, message: str) -> None:
        label = getattr(self._app, "status_label", None)
        if label is not None:
            label.setText(message)


def _reactant_file(params: dict[str, Any], slot: int) -> str:
    if str(params.get(f"reactant_{slot}_mode") or "") != "file":
        return ""
    return str(params.get(f"reactant_{slot}") or "")


def _reactant_smiles(params: dict[str, Any], slot: int) -> str:
    if str(params.get(f"reactant_{slot}_mode") or "smiles") != "smiles":
        return ""
    return str(params.get(f"reactant_{slot}") or "")
