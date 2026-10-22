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

"""Activity Cliff Map tool entry points."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from ..analysis_job_support import (
    ensure_activity_analysis_ready,
    finish_analysis_pairs,
    report_analysis_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_ACTIVITY_CLIFF_MAP
from ... import workers
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class ActivityCliffMixin:
    def open_activity_cliff_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_ACTIVITY_CLIFF_MAP,
            missing_activity_message=(
                "Activity Cliff Map requires at least one numeric activity/property column."
            ),
        )
        if not activity_cols:
            return
        from ..dialogs.activity_cliff import ActivityCliffDialog

        d = ActivityCliffDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, d, on_accepted=self._on_activity_cliff_dialog_accepted)

    def _on_activity_cliff_dialog_accepted(self, d) -> None:
        p = d.params()

        def _make_worker(rec, *, cancel_event, signals, progress_state):
            return workers.MmpAnalysisWorker(
                rec,
                activity_column=p.activity_column,
                max_cuts=p.max_cuts,
                max_variable_heavy_atoms=p.max_variable_heavy_atoms,
                min_activity_difference=p.min_activity_difference,
                purpose="activity_cliff",
                x_mode=p.x_mode,
                signals=signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_ACTIVITY_CLIFF_MAP,
            structure_source=p.structure_source,
            activity_column=p.activity_column,
            only_selected=d.only_selected_rows(),
            make_worker=_make_worker,
        )

    def on_activity_cliff_finished(self, pairs, activity_column: str, x_mode: str) -> None:
        pairs = finish_analysis_pairs(
            self,
            TOOL_ACTIVITY_CLIFF_MAP,
            pairs,
            empty_message="No matched molecular pairs were found for the current settings.",
        )
        if pairs is None:
            return
        self._open_activity_cliff_map(pairs, activity_column=activity_column, x_mode=x_mode)
        self.status_label.setText(f"Activity Cliff Map: {len(pairs)} pair(s).")

    def on_activity_cliff_failed(self, message: str) -> None:
        report_analysis_failure(
            self,
            TOOL_ACTIVITY_CLIFF_MAP,
            message,
            fallback="Activity Cliff Map failed.",
        )

    def _open_activity_cliff_map(self, pairs, *, activity_column: str, x_mode: str) -> None:
        from ..activity_cliff_map import ActivityCliffMapDialog

        def _factory():
            dlg = ActivityCliffMapDialog(
                self, pairs, activity_column=activity_column, x_mode=x_mode
            )
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column, x_mode=x_mode)

        reuse_or_show_modeless_singleton(
            self,
            "_activity_cliff_map_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )
