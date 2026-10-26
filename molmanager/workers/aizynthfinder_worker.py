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

"""Background AiZynthFinder search. The other interpreter does the tree search."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal

from ..chem.structure_payload import smiles_text_for_payload
from ..predictions.aizynthfinder_run import (
    OUTPUT_COLUMNS,
    AizynthRunError,
    run_search,
)
from .signals import emit_partial_results_if_cancelled

_TOOL_LABEL = "Retrosynthesis"


def _safe_emit(obj, emitter_name: str, *args) -> None:
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except RuntimeError:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        return


class AizynthFinderSignals(QObject):
    """Emits from :class:`AizynthFinderWorker` (owned on the GUI thread)."""

    finished = pyqtSignal(list, str, object)
    failed = pyqtSignal(str)


class AizynthFinderWorker(QRunnable):
    """Search each distinct SMILES once and emit summary columns for every row."""

    def __init__(
        self,
        payloads,
        python: str,
        config: str,
        worker_signals,
        aizynth_signals: AizynthFinderSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.payloads = list(payloads)
        self.python = python
        self.config = config
        self.worker_signals = worker_signals
        self.aizynth_signals = aizynth_signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress
        from .process_pool_utils import application_is_shutting_down

        cancel_ev = self.cancel_event
        rows: list[tuple[int | None, str]] = []
        for payload in self.payloads:
            smiles = smiles_text_for_payload(payload)
            if not smiles:
                continue
            oid = None if payload.oid is None else int(payload.oid)
            rows.append((oid, smiles))
        if not rows:
            _safe_emit(
                self.aizynth_signals,
                "failed",
                "No valid structures were found for this scope and source.",
            )
            return

        order: list[str] = []
        seen: set[str] = set()
        for _oid, smiles in rows:
            if smiles not in seen:
                seen.add(smiles)
                order.append(smiles)
        total_rows = max(len(rows), 1)
        throttle = [0, 0.0]

        def _cancelled() -> bool:
            return application_is_shutting_down() or (cancel_ev is not None and cancel_ev.is_set())

        def _emit_progress(done_rows: int, message: str, *, force: bool = False) -> None:
            report_tool_progress(
                message=message,
                done=min(done_rows, total_rows),
                total=total_rows,
                progress_state=self.progress_state,
                signals=self.worker_signals,
                throttle=throttle,
                force_signal=force,
            )

        def _on_progress(done_unique: int, total_unique: int) -> None:
            finished = set(order[: max(0, done_unique)])
            done_rows = sum(1 for _oid, smiles in rows if smiles in finished)
            _emit_progress(
                done_rows,
                f"{_TOOL_LABEL}: {done_unique}/{total_unique} molecules",
            )

        _emit_progress(0, f"{_TOOL_LABEL}: starting…", force=True)
        if _cancelled():
            _safe_emit(self.aizynth_signals, "failed", "Cancelled.")
            return
        try:
            result = run_search(
                python=self.python,
                config=Path(self.config),
                smiles=order,
                cancel=_cancelled,
                on_progress=_on_progress,
            )
        except AizynthRunError as exc:
            _safe_emit(self.aizynth_signals, "failed", str(exc) or "Retrosynthesis failed.")
            return

        blank = {header: "" for header in OUTPUT_COLUMNS}
        emitted: list[tuple[int | None, str, dict[str, str]]] = []
        for oid, smiles in rows:
            columns = result.summaries.get(smiles)
            if columns is None:
                continue
            emitted.append((oid, smiles, columns or blank))
        if result.cancelled:
            emit_partial_results_if_cancelled(
                self.worker_signals,
                _TOOL_LABEL,
                len(emitted),
                total_rows,
                True,
            )
        if not emitted:
            _safe_emit(
                self.aizynth_signals,
                "failed",
                result.warning or "AiZynthFinder returned no route summary.",
            )
            return
        _safe_emit(
            self.aizynth_signals,
            "finished",
            emitted,
            result.warning,
            dict(result.routes),
        )
