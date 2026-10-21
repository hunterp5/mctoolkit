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

"""Background GNN-MTL permeability / efflux prediction (Chemprop)."""

from __future__ import annotations

import logging
import threading
import time

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from ..chem.structure_payload import StructurePayload, smiles_text_for_payload
from ..predictions.permeability_prediction import (
    format_permeability_row,
    permeability_model_available,
    permeability_stack_import_error,
    predict_permeability_batch,
)

logger = logging.getLogger(__name__)


def _safe_emit(obj, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


class PermeabilityPredictorSignals(QObject):
    """Emits from :class:`PermeabilityPredictorWorker` (owned on the GUI thread)."""

    finished = pyqtSignal(list)  # list[tuple[int, dict[str, str]]]
    failed = pyqtSignal(str)


class PermeabilityPredictorWorker(QRunnable):
    """Predict GNN-MTL endpoints per table row; writes via ``finished`` on the GUI thread."""

    def __init__(
        self,
        rows: list[StructurePayload],
        worker_signals,
        permeability_signals: PermeabilityPredictorSignals,
        cancel_event: threading.Event | None = None,
        *,
        output_columns: tuple[str, ...],
        batch_size: int = 64,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.worker_signals = worker_signals
        self.permeability_signals = permeability_signals
        self.cancel_event = cancel_event
        self.output_columns = output_columns
        self.batch_size = batch_size
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        tot = max(len(self.rows), 1)
        done = 0
        prog_last = 0.0
        throttle = [0, 0.0]

        def _emit_progress(message: str, *, force: bool = False) -> None:
            nonlocal prog_last
            now = time.monotonic()
            if force or done >= tot or (now - prog_last) >= 0.12:
                prog_last = now
                report_tool_progress(
                    message=message,
                    done=min(done, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=force,
                )

        _emit_progress("Predict Permeability…", force=True)

        err = permeability_stack_import_error()
        if err:
            _safe_emit(self.permeability_signals, "failed", err)
            return
        if not permeability_model_available():
            _safe_emit(
                self.permeability_signals,
                "failed",
                "GNN-MTL model file (model.pt) is missing.\n"
                "Run: python scripts/bootstrap_gnn_mtl_model.py\n"
                "See molmanager/resources/models/gnn_mtl/README.md",
            )
            return

        oids: list[int] = []
        smiles: list[str] = []
        for payload in self.rows:
            if cancel_ev is not None and cancel_ev.is_set():
                _safe_emit(self.permeability_signals, "failed", "Cancelled.")
                return
            done += 1
            _emit_progress("Predict Permeability…")
            if payload.oid is None:
                continue
            text = smiles_text_for_payload(payload)
            if text:
                oids.append(int(payload.oid))
                smiles.append(text)

        if not smiles:
            _safe_emit(
                self.permeability_signals,
                "failed",
                "No valid structures were found for this scope and source.",
            )
            return

        _emit_progress("Running GNN-MTL model…", force=True)
        try:

            def _predict_progress(batch_done: int, batch_total: int) -> None:
                if cancel_ev is not None and cancel_ev.is_set():
                    return
                report_tool_progress(
                    message="Predict Permeability…",
                    done=batch_done,
                    total=max(batch_total, 1),
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=batch_done >= batch_total,
                )

            preds = predict_permeability_batch(
                smiles,
                batch_size=self.batch_size,
                progress_callback=_predict_progress,
            )
        except Exception as e:
            logger.exception("Permeability prediction failed")
            _safe_emit(self.permeability_signals, "failed", f"Prediction failed: {e}")
            return

        if cancel_ev is not None and cancel_ev.is_set():
            _safe_emit(self.permeability_signals, "failed", "Cancelled.")
            return

        results: list[tuple[int, dict[str, str]]] = []
        for oid, pred in zip(oids, preds):
            row = format_permeability_row(pred, self.output_columns)
            results.append((oid, row))

        done = tot
        _emit_progress("Predict Permeability", force=True)
        _safe_emit(self.permeability_signals, "finished", results)
