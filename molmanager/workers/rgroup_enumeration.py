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

"""R-group enumeration worker (Chemistry → R-Group Enumeration)."""

from __future__ import annotations

import logging
import threading

from PyQt5.QtCore import QRunnable

from ..chem.rgroup_enumeration import (
    RGroupEnumerationJobResult,
    RGroupEnumerationRequest,
    enumerate_rgroups,
    load_rgroup_pools,
    write_rgroup_products_to_sdf,
)
from .signals import WorkerSignals, emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)

_JOB_ERRORS = (ValueError, RuntimeError, OSError, TypeError)


class RGroupEnumerationWorker(QRunnable):
    """Attach building-block lists to a core and emit the product rows."""

    def __init__(
        self,
        request: RGroupEnumerationRequest,
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
            self._finish_cancelled(())
            return
        from ..platform_support.tool_progress import report_tool_progress

        req = self.request
        label = self.tool_title
        target = max(1, int(req.max_products))
        throttle = [0, 0.0]

        def on_progress(accepted: int, cap: int, examined: int) -> None:
            report_tool_progress(
                message=f"{label} ({examined:,} combinations examined)",
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
            self._finish_cancelled(())
            return
        try:
            pools = load_rgroup_pools(req)
            products, skipped, cancelled = enumerate_rgroups(
                req.core_smiles,
                pools,
                core_id=req.core_id,
                max_products=req.max_products,
                output_filters=req.output_filters,
                cancel_event=ev,
                progress_callback=on_progress,
            )
        except _JOB_ERRORS as exc:
            if ev is not None and ev.is_set():
                self._finish_cancelled(())
                return
            self._emit_failed(str(exc) or exc.__class__.__name__)
            return
        if cancelled or (ev is not None and ev.is_set()):
            self._finish_cancelled(tuple(products), skipped)
            return
        try:
            written = self._write_products(tuple(products))
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
        self._emit_finished(self._result(tuple(products), skipped, written))

    def _write_products(self, products) -> int:
        req = self.request
        if not (req.save_to_file and req.save_path and products):
            return 0
        return write_rgroup_products_to_sdf(req.save_path, products)

    def _result(self, products, skipped: int, written: int) -> RGroupEnumerationJobResult:
        req = self.request
        return RGroupEnumerationJobResult(
            products=tuple(products),
            skipped=int(skipped),
            add_to_table=req.add_to_table,
            save_to_file=req.save_to_file,
            save_path=req.save_path,
            written_count=int(written),
        )

    def _emit_failed(self, message: str) -> None:
        try:
            self.signals.rgroup_enum_failed.emit(message, self.tool_title)
        except (RuntimeError, TypeError):
            logger.warning("rgroup_enum_failed emit failed", exc_info=True)

    def _emit_finished(self, result: RGroupEnumerationJobResult) -> None:
        try:
            self.signals.rgroup_enum_finished.emit(result)
        except (RuntimeError, TypeError):
            logger.warning("rgroup_enum_finished emit failed", exc_info=True)

    def _finish_cancelled(self, products, skipped: int = 0) -> None:
        kept = tuple(product for product in products if (product.smiles or "").strip())
        written = 0
        try:
            written = self._write_products(kept)
        except _JOB_ERRORS:
            logger.warning("R-group enumeration could not write a partial SDF", exc_info=True)
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
