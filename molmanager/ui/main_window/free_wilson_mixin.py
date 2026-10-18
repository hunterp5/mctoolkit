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

"""Free-Wilson tool window (Data menu)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ...analysis.free_wilson import parse_free_wilson_core
from ...platform_support.memory_guards import check_product_enumeration
from ...workers.free_wilson_worker import FreeWilsonWorker
from ..analysis_job_support import (
    ensure_activity_analysis_ready,
    report_cancellable_job_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_FREE_WILSON


class FreeWilsonMixin:
    """Open Free-Wilson, enqueue the fit, and show the results window."""

    def open_free_wilson_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_FREE_WILSON,
            missing_activity_message=("Free-Wilson requires at least one numeric activity column."),
        )
        if not activity_cols:
            return
        from ..dialogs.free_wilson import FreeWilsonDialog

        dialog = FreeWilsonDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, dialog, on_accepted=self._on_free_wilson_dialog_accepted)

    def _on_free_wilson_dialog_accepted(self, dialog) -> None:
        params = dialog.params()
        settings = params.settings
        guard = check_product_enumeration(settings.max_new_structures)
        if not guard.ok:
            QMessageBox.warning(self, TOOL_FREE_WILSON, guard.message)
            return
        if parse_free_wilson_core(settings.core_query) is None:
            QMessageBox.warning(
                self,
                TOOL_FREE_WILSON,
                "Core is not valid SMARTS or SMILES.",
            )
            return

        def _make_worker(records, *, cancel_event, signals, progress_state):
            return FreeWilsonWorker(
                records,
                settings,
                signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_FREE_WILSON,
            structure_source=params.structure_source,
            activity_column=settings.activity_column,
            only_selected=dialog.only_selected_rows(),
            make_worker=_make_worker,
        )

    def on_free_wilson_finished(self, result) -> None:
        self._finish_tool_progress(TOOL_FREE_WILSON)
        if not getattr(result, "ok", False):
            self.status_label.setText("Ready.")
            QMessageBox.information(
                self,
                TOOL_FREE_WILSON,
                getattr(result, "message", "") or "Free-Wilson analysis failed.",
            )
            return
        from ..dialogs.free_wilson_results import FreeWilsonResultsDialog

        dialog = FreeWilsonResultsDialog(result, parent=self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()
        if result.enumeration_refused:
            detail = "missing analogs were not listed"
        else:
            detail = f"{len(result.missing):,} missing analog(s)"
        self.status_label.setText(f"{TOOL_FREE_WILSON}: fitted {result.n:,} molecule(s), {detail}.")

    def on_free_wilson_failed(self, message: str) -> None:
        report_cancellable_job_failure(
            self,
            TOOL_FREE_WILSON,
            message,
            progress_label=TOOL_FREE_WILSON,
            failure_fallback="Free-Wilson analysis failed.",
        )
