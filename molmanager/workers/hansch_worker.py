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

"""Hansch analysis worker (Data menu)."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from contextlib import suppress

from PyQt5.QtCore import QRunnable
from rdkit import Chem

from ..analysis.hansch import HanschResult, HanschSettings, run_hansch
from .signals import WorkerSignals

logger = logging.getLogger(__name__)

_JOB_ERRORS = (ValueError, RuntimeError, TypeError, OSError, KeyError, ArithmeticError)


class HanschWorker(QRunnable):
    """Decompose a series, look up substituent constants, and fit the Hansch equation."""

    def __init__(
        self,
        records: Sequence[tuple[int, Chem.Mol, float]],
        settings: HanschSettings,
        signals: WorkerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.records = list(records)
        self.settings = settings
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            self._emit_failed("Cancelled.")
            return
        from ..platform_support.tool_progress import report_tool_progress

        throttle = [0, 0.0]

        def on_progress(message: str, done: int, total: int) -> None:
            report_tool_progress(
                message=message,
                done=done,
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )

        try:
            result = run_hansch(
                self.records,
                self.settings,
                cancel_event=self.cancel_event,
                progress=on_progress,
            )
        except _JOB_ERRORS as exc:
            if self.cancel_event is not None and self.cancel_event.is_set():
                self._emit_failed("Cancelled.")
                return
            logger.exception("Hansch analysis failed")
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        if result.cancelled or (self.cancel_event is not None and self.cancel_event.is_set()):
            self._emit_failed("Cancelled.")
            return
        report_tool_progress(
            message="Hansch",
            done=1,
            total=1,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self._emit_finished(result)

    def _emit_failed(self, message: str) -> None:
        with suppress(RuntimeError, TypeError):
            self.signals.hansch_failed.emit(message)

    def _emit_finished(self, result: HanschResult) -> None:
        with suppress(RuntimeError, TypeError):
            self.signals.hansch_finished.emit(result)
