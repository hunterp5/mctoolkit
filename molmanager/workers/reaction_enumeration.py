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

"""Reaction-based enumeration worker (Chemistry → Structure Enumeration)."""

from __future__ import annotations

import threading
from contextlib import suppress

from PyQt5.QtCore import QRunnable

from ..chem.reaction_enumeration import (
    ReactionEnumerationJobResult,
    ReactionEnumerationRequest,
    enumerate_reaction,
    load_reactant_pools,
    write_product_smiles_to_sdf,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled

_JOB_ERRORS = (ValueError, RuntimeError, OSError, TypeError)


class ReactionEnumerationWorker(QRunnable):
    """Enumerate reaction products from two reactant pools (files or SMILES text)."""

    def __init__(
        self,
        request: ReactionEnumerationRequest,
        tool_title: str,
        signals: WorkerSignals,
        *,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.request = request
        self.tool_title = tool_title
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def run(self) -> None:
        ev = self.cancel_event
        if ev is not None and ev.is_set():
            self._finish_cancelled([], 0)
            return
        from ..platform_support.tool_progress import report_tool_progress

        req = self.request
        label = self.tool_title
        target = max(1, int(req.max_products))
        throttle = [0, 0.0]

        def on_progress(accepted: int, cap: int, examined: int) -> None:
            report_tool_progress(
                message=f"{label} ({examined:,} pairs examined)",
                done=min(max(0, int(accepted)), cap),
                total=cap,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )

        report_tool_progress(
            message=label,
            done=0,
            total=target,
            progress_state=self.progress_state,
            signals=self.signals,
            throttle=throttle,
            force_signal=True,
        )
        if ev is not None and ev.is_set():
            self._finish_cancelled([], 0)
            return
        try:
            pool_a, pool_b = load_reactant_pools(req)
            products, skipped, cancelled = enumerate_reaction(
                req.rxn_smarts,
                [pool_a, pool_b],
                max_products=req.max_products,
                output_filters=req.output_filters,
                cancel_event=ev,
                progress_callback=on_progress,
            )
        except _JOB_ERRORS as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled([], 0)
                return
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        if cancelled or (ev is not None and ev.is_set()):
            self._finish_cancelled(products, skipped)
            return
        try:
            written = self._write_products(products)
        except _JOB_ERRORS as exc:
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        report_tool_progress(
            message=label,
            done=target,
            total=target,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self._emit_finished(self._result(products, skipped, written))

    def _write_products(self, products: list[str]) -> int:
        req = self.request
        if not (req.save_to_file and req.save_path and products):
            return 0
        return write_product_smiles_to_sdf(req.save_path, products, req.reaction_name)

    def _result(
        self, products: list[str], skipped: int, written: int
    ) -> ReactionEnumerationJobResult:
        req = self.request
        return ReactionEnumerationJobResult(
            products=list(products),
            reaction_name=req.reaction_name,
            skipped=int(skipped),
            add_to_table=req.add_to_table,
            save_to_file=req.save_to_file,
            save_path=req.save_path,
            written_count=int(written),
        )

    def _emit_failed(self, message: str) -> None:
        with suppress(RuntimeError, TypeError):
            self.signals.reaction_enum_failed.emit(message, self.tool_title)

    def _emit_finished(self, result: ReactionEnumerationJobResult) -> None:
        with suppress(RuntimeError, TypeError):
            self.signals.reaction_enum_finished.emit(result)

    def _finish_cancelled(self, products: list[str], skipped: int) -> None:
        kept = [str(smi) for smi in products if (smi or "").strip()]
        written = 0
        with suppress(*_JOB_ERRORS):
            written = self._write_products(kept)
        if kept:
            emit_partial_results_if_cancelled(
                self.signals,
                self.tool_title,
                len(kept),
                self.request.max_products,
                True,
            )
            self._emit_finished(self._result(kept, skipped, written))
        self._emit_failed("Cancelled.")
