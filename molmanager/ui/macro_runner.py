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

Each step goes through ``dispatch_step``, which returns a ``JobHandle``.
The next step starts after that handle finishes, which is after the tool's
table write or filter pass. The tools still store a one-shot callback
internally; the runner does not.
"""

from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import QObject, QTimer, pyqtSignal

from ..workflows.macro_recipe import (
    MacroRecipe,
    MacroStep,
    step_summary,
    validate_recipe,
)
from .command_dispatch import dispatch_step
from .job_handle import JobHandle, JobOutcome
from .macro_filters import ensure_numeric_bounds

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
        self._handle: JobHandle | None = None

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
        handle = self._handle
        self._handle = None
        if handle is not None:
            handle.abandon()
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
            handle = dispatch_step(self._app, step, self._bindings)
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            logger.exception("Macro step failed to start")
            self._on_step_finished(generation, step.id, str(exc) or "The step could not start.", {})
            return
        self._handle = handle
        seen = False

        def _on_handle(outcome: JobOutcome, gen: int = generation, step_id: str = step.id) -> None:
            nonlocal seen
            if seen or outcome.cancelled:
                return
            seen = True
            error = None if outcome.ok else (outcome.error or "The step failed.")
            self._on_step_finished(gen, step_id, error, outcome.outputs)

        handle.finished.connect(_on_handle)
        if handle.outcome is not None:
            _on_handle(handle.outcome)

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
