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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Background Quick QSAR search and prediction."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from ..analysis.auto_qsar import (
    AutoQSARCancelled,
    AutoQSARResult,
    predict_auto_qsar,
    search_auto_qsar,
    table_numeric_feature_columns,
)
from ..chem.structure_payload import mol_rows_from_job_params
from ..platform_support.exception_policy import log_swallowed_exception
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)

_JOB_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    RuntimeError,
    ArithmeticError,
    MemoryError,
    OSError,
    IndexError,
    AttributeError,
)


@dataclass
class AutoQSARJobResult:
    """Search outcome plus the frame the search was scored on."""

    search: AutoQSARResult
    dataframe: object
    oids: list[int]


def _emit_cancelled(signals: AutoQSARSignals) -> None:
    try:
        signals.failed.emit("Cancelled.")
    except RuntimeError:
        log_swallowed_exception(logger, "Quick QSAR cancel signal emit failed")


def _emit_failed(signals: AutoQSARSignals, message: str) -> None:
    try:
        signals.failed.emit(message)
    except RuntimeError:
        log_swallowed_exception(logger, "Quick QSAR failed-signal emit failed")


class AutoQSARSignals(QObject):
    search_finished = pyqtSignal(object)
    predict_finished = pyqtSignal(list)
    failed = pyqtSignal(str)


class AutoQSARSearchWorker(QRunnable):
    """Calculate descriptors if needed, then search models off the GUI thread."""

    def __init__(
        self,
        params: dict,
        signals: AutoQSARSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.params = dict(params)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            _emit_cancelled(self.signals)
            return
        try:
            result = self._search()
            if self.cancel_event is not None and self.cancel_event.is_set():
                _emit_cancelled(self.signals)
                return
            self.signals.search_finished.emit(result)
        except AutoQSARCancelled:
            _emit_cancelled(self.signals)
        except _JOB_ERRORS as exc:
            logger.exception("Quick QSAR search failed")
            _emit_failed(self.signals, str(exc) or exc.__class__.__name__)

    def _search(self) -> AutoQSARJobResult:
        oids = [int(oid) for oid in self.params["oids"]]
        activity = str(self.params["activity_column"])
        source = self.params["dataframe"]
        blocked = [str(self.params.get("prediction_column") or "").strip()]
        allowed = table_numeric_feature_columns(
            source,
            activity,
            blocked_columns=[column for column in blocked if column],
        )
        requested = self.params.get("table_columns")
        if requested is None:
            table_columns = allowed
        else:
            allowed_names = set(allowed)
            table_columns = [str(column) for column in requested if str(column) in allowed_names]

        def on_progress(done: int, total: int, message: str) -> None:
            report_tool_progress(
                message=message,
                done=done,
                total=max(1, total),
                progress_state=self.progress_state,
            )

        searched = search_auto_qsar(
            df=source,
            oids=oids,
            activity_column=activity,
            task_mode=str(self.params.get("task_mode") or "auto"),
            effort=str(self.params.get("effort") or "standard"),
            mol_rows=mol_rows_from_job_params(self.params),
            table_columns=table_columns,
            blocked_columns=[column for column in blocked if column],
            cancel_event=self.cancel_event,
            on_progress=on_progress,
        )
        return AutoQSARJobResult(search=searched, dataframe=source, oids=oids)


class AutoQSARPredictWorker(QRunnable):
    """Apply the winning model to the searched rows."""

    def __init__(
        self,
        params: dict,
        signals: AutoQSARSignals,
        cancel_event: threading.Event | None = None,
        progress_state: ToolProgressState | None = None,
    ):
        super().__init__()
        self.params = dict(params)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        if self.cancel_event is not None and self.cancel_event.is_set():
            _emit_cancelled(self.signals)
            return
        try:
            oids = list(self.params["oids"])
            n = max(1, len(oids))
            report_tool_progress(
                message="Quick QSAR predictions: scoring…",
                done=0,
                total=n,
                progress_state=self.progress_state,
            )
            rows = predict_auto_qsar(
                self.params["search"],
                df=self.params["dataframe"],
                oids=oids,
                mol_rows=mol_rows_from_job_params(self.params),
                output_column=str(self.params.get("output_column") or ""),
                model_index=self.params.get("model_index"),
                cancel_event=self.cancel_event,
            )
            if self.cancel_event is not None and self.cancel_event.is_set():
                _emit_cancelled(self.signals)
                return
            report_tool_progress(
                message="Quick QSAR predictions: done",
                done=n,
                total=n,
                progress_state=self.progress_state,
            )
            self.signals.predict_finished.emit(rows)
        except AutoQSARCancelled:
            _emit_cancelled(self.signals)
        except _JOB_ERRORS as exc:
            logger.exception("Quick QSAR prediction failed")
            _emit_failed(self.signals, str(exc) or exc.__class__.__name__)
