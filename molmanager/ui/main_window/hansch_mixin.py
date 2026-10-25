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

"""Hansch tool window (Data menu)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ...analysis.hansch import settings_error
from ... import workers
from ..analysis_job_support import (
    ensure_activity_analysis_ready,
    report_cancellable_job_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_HANSCH


class HanschMixin:
    """Open Hansch analysis, enqueue the fit, and show the results window."""

    def open_hansch_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_HANSCH,
            missing_activity_message="Hansch analysis requires at least one numeric activity column.",
        )
        if not activity_cols:
            return
        from ..dialogs.hansch import HanschDialog

        dialog = HanschDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, dialog, on_accepted=self._on_hansch_dialog_accepted)

    def _on_hansch_dialog_accepted(self, dialog) -> None:
        params = dialog.params()
        problem = settings_error(params.settings)
        if problem:
            QMessageBox.warning(self, TOOL_HANSCH, problem)
            return

        def _make_worker(records, *, cancel_event, signals, progress_state):
            return workers.HanschWorker(
                records,
                params.settings,
                signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_HANSCH,
            structure_source=params.structure_source,
            activity_column=params.settings.activity_column,
            only_selected=dialog.only_selected_rows(),
            make_worker=_make_worker,
        )

    def on_hansch_finished(self, result) -> None:
        self._finish_tool_progress(TOOL_HANSCH)
        if not getattr(result, "ok", False):
            self.status_label.setText("Ready.")
            QMessageBox.information(
                self,
                TOOL_HANSCH,
                getattr(result, "message", "") or "Hansch analysis failed.",
            )
            return
        from ..dialogs.hansch_results import HanschResultsDialog

        dialog = HanschResultsDialog(result, parent=self)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.show()
        self.status_label.setText(f"{TOOL_HANSCH}: fitted {result.n:,} molecule(s).")

    def on_hansch_failed(self, message: str) -> None:
        report_cancellable_job_failure(
            self,
            TOOL_HANSCH,
            message,
            progress_label=TOOL_HANSCH,
            failure_fallback="Hansch analysis failed.",
        )
