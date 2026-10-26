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

"""Record accepted tool jobs into a recipe. Replay does not record again.

A step is appended only from ``JobHandle.finished`` when the job succeeded.
Cancelling a dialog never reaches dispatch, so it is not a step. A macro
run sets the replaying flag so those dispatches are not appended.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..workflows.macro_recipe import (
    STEP_EXTRACT,
    MacroRecipe,
    MacroStep,
    new_recipe_id,
    new_step_id,
)
from ..workflows.macro_record import rewrite_recorded_params
from .job_handle import JobHandle, JobOutcome


class MacroRecorder:
    """Idle until :meth:`start`. Listeners hear each appended step."""

    def __init__(self) -> None:
        self.recording = False
        self.name = "Recording"
        self._replaying = 0
        self._steps: list[MacroStep] = []
        self._bindings: dict[str, dict[str, str]] = {}
        self._listeners: list[Callable[[], None]] = []

    @property
    def steps(self) -> list[MacroStep]:
        return list(self._steps)

    @property
    def replaying(self) -> bool:
        """True while a macro run is playing steps back."""
        return self._replaying > 0

    def add_listener(self, listener: Callable[[], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def start(self, name: str = "Recording") -> None:
        """Begin a new recipe. Steps already stored are dropped."""
        self.recording = True
        self.name = (name or "").strip() or "Recording"
        self._steps = []
        self._bindings = {}
        self._notify()

    def stop(self) -> MacroRecipe:
        """End recording and return the recipe collected so far."""
        self.recording = False
        recipe = MacroRecipe(id=new_recipe_id(), name=self.name, steps=list(self._steps))
        self._notify()
        return recipe

    def begin_replay(self) -> None:
        """Macro playback. ``observe`` appends nothing until :meth:`end_replay`."""
        self._replaying += 1

    def end_replay(self) -> None:
        self._replaying = max(0, self._replaying - 1)

    def observe(self, step: MacroStep, handle: JobHandle) -> None:
        """Append *step* if *handle* later finishes successfully."""
        if not self.recording or self._replaying:
            return
        kind = step.kind
        params = {key: _copy(value) for key, value in step.params.items()}

        def _on_finished(outcome: JobOutcome) -> None:
            if not self.recording or self._replaying:
                return
            if outcome is None or not outcome.ok or outcome.cancelled:
                return
            rewritten = rewrite_recorded_params(kind, params, self._bindings)
            if kind == STEP_EXTRACT and outcome.outputs:
                rewritten["published"] = [str(key) for key in outcome.outputs]
            step_id = new_step_id(kind, {item.id for item in self._steps})
            self._steps.append(MacroStep(id=step_id, kind=kind, params=rewritten))
            self._bindings[step_id] = dict(outcome.outputs)
            self._notify()

        handle.finished.connect(_on_finished)
        if handle.outcome is not None:
            _on_finished(handle.outcome)

    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()


def ensure_recorder(app: Any) -> MacroRecorder:
    """The window's recorder, created on first use."""
    recorder = getattr(app, "macro_recorder", None)
    if not isinstance(recorder, MacroRecorder):
        recorder = MacroRecorder()
        app.macro_recorder = recorder
    return recorder


def observe_if_recording(app: Any, step: MacroStep, handle: JobHandle) -> None:
    """Let the window recorder see *handle* when a recording is in progress."""
    recorder = getattr(app, "macro_recorder", None)
    if isinstance(recorder, MacroRecorder):
        recorder.observe(step, handle)


def report_unless_replaying(app: Any, title: str, message: str, *, warning: bool = True) -> None:
    """Show *message* for a dialog-started job. Macro replay reports through the runner."""
    recorder = getattr(app, "macro_recorder", None)
    if isinstance(recorder, MacroRecorder) and recorder.replaying:
        return
    from PyQt5.QtWidgets import QMessageBox

    if warning:
        QMessageBox.warning(app, title, message)
    else:
        QMessageBox.information(app, title, message)


def _copy(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value
