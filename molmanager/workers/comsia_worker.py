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

"""Background CoMSIA training and prediction."""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from ..analysis.comsia import (
    ComsiaCancelled,
    ComsiaError,
    ComsiaModel,
    fit_comsia,
    pose_from_mol,
    predict_comsia,
)
from ..platform_support.exception_policy import log_swallowed_exception
from ..platform_support.tool_progress import ToolProgressState, report_tool_progress

logger = logging.getLogger(__name__)


def _emit_failed(signals: ComsiaSignals, message: str) -> None:
    try:
        signals.failed.emit(message)
    except (RuntimeError, TypeError):
        log_swallowed_exception(logger, "CoMSIA failed-signal emit failed")


class ComsiaSignals(QObject):
    train_finished = pyqtSignal(object)
    predict_finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class ComsiaTrainWorker(QRunnable):
    """Fit a CoMSIA model off the GUI thread."""

    def __init__(
        self,
        params: dict,
        signals: ComsiaSignals,
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
            _emit_failed(self.signals, "Cancelled.")
            return
        try:
            mols, activities, skipped = _training_poses(self.params["records"])
            report_tool_progress(
                message="CoMSIA: fitting…",
                done=0,
                total=max(1, len(mols)),
                progress_state=self.progress_state,
            )

            def _progress(message: str) -> None:
                report_tool_progress(
                    message=message,
                    done=0,
                    total=max(1, len(mols)),
                    progress_state=self.progress_state,
                )

            model = fit_comsia(
                mols,
                activities,
                fields=self.params.get("fields"),
                spacing=float(self.params.get("spacing", 2.0)),
                padding=float(self.params.get("padding", 4.0)),
                max_components=int(self.params.get("max_components", 5)),
                sd_fraction=float(self.params.get("sd_fraction", 0.01)),
                progress=_progress,
                cancelled=self.cancel_event.is_set if self.cancel_event is not None else None,
            )
            if skipped:
                model.metrics_text += f"\nSkipped rows without a 3D pose or activity: {skipped}"
            report_tool_progress(
                message="CoMSIA: done",
                done=len(mols),
                total=max(1, len(mols)),
                progress_state=self.progress_state,
            )
            self.signals.train_finished.emit(model)
        except ComsiaCancelled:
            _emit_failed(self.signals, "Cancelled.")
        except ComsiaError as exc:
            _emit_failed(self.signals, str(exc))
        except Exception as exc:
            logger.exception("CoMSIA training failed")
            _emit_failed(self.signals, str(exc) or exc.__class__.__name__)


class ComsiaPredictWorker(QRunnable):
    """Apply a fitted CoMSIA model to posed rows."""

    def __init__(
        self,
        params: dict,
        signals: ComsiaSignals,
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
            _emit_failed(self.signals, "Cancelled.")
            return
        try:
            model = self.params["model"]
            if not isinstance(model, ComsiaModel):
                raise ComsiaError("Train a CoMSIA model before adding predictions.")
            oids, mols, skipped = _prediction_poses(self.params["records"])
            report_tool_progress(
                message="CoMSIA: predicting…",
                done=0,
                total=max(1, len(mols)),
                progress_state=self.progress_state,
            )
            predicted = predict_comsia(model, mols)
            rows = [
                (int(oid), float(value))
                for oid, value in zip(oids, predicted, strict=True)
                if value == value
            ]
            if self.cancel_event is not None and self.cancel_event.is_set():
                _emit_failed(self.signals, "Cancelled.")
                return
            report_tool_progress(
                message="CoMSIA: done",
                done=len(rows),
                total=max(1, len(mols)),
                progress_state=self.progress_state,
            )
            self.signals.predict_finished.emit(
                {"rows": rows, "skipped": skipped + (len(mols) - len(rows))}
            )
        except ComsiaError as exc:
            _emit_failed(self.signals, str(exc))
        except Exception as exc:
            logger.exception("CoMSIA prediction failed")
            _emit_failed(self.signals, str(exc) or exc.__class__.__name__)


def _training_poses(
    records: list[tuple[int, bytes, float | None]],
) -> tuple[list, list[float], int]:
    mols: list = []
    activities: list[float] = []
    skipped = 0
    for _oid, blob, activity in records:
        if activity is None:
            skipped += 1
            continue
        pose = _pose(blob)
        if pose is None:
            skipped += 1
            continue
        mols.append(pose)
        activities.append(float(activity))
    return mols, activities, skipped


def _prediction_poses(
    records: list[tuple[int, bytes, float | None]],
) -> tuple[list[int], list, int]:
    oids: list[int] = []
    mols: list = []
    skipped = 0
    for oid, blob, _activity in records:
        pose = _pose(blob)
        if pose is None:
            skipped += 1
            continue
        oids.append(int(oid))
        mols.append(pose)
    return oids, mols, skipped


def _pose(blob: bytes) -> Any:
    try:
        mol = Chem.Mol(blob)
    except (RuntimeError, ValueError):
        return None
    return pose_from_mol(mol)
