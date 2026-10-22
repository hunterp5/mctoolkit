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

"""MMP Pair Network tool entry points."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from ..analysis_job_support import (
    ensure_activity_analysis_ready,
    finish_analysis_pairs,
    report_analysis_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_MMP_PAIR_NETWORK
from ... import workers
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class MmpNeighborhoodMixin:
    def open_mmp_neighborhood_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_MMP_PAIR_NETWORK,
            missing_activity_message=(
                "Pair Network requires at least one numeric activity/property column."
            ),
        )
        if not activity_cols:
            return
        from ..dialogs.mmp_neighborhood import MmpNeighborhoodDialog

        d = MmpNeighborhoodDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, d, on_accepted=self._on_mmp_neighborhood_dialog_accepted)

    def _on_mmp_neighborhood_dialog_accepted(self, d) -> None:
        p = d.params()

        def _make_worker(rec, *, cancel_event, signals, progress_state):
            return workers.MmpAnalysisWorker(
                rec,
                activity_column=p.activity_column,
                max_cuts=p.max_cuts,
                max_variable_heavy_atoms=p.max_variable_heavy_atoms,
                min_activity_difference=p.min_activity_difference,
                max_activity_difference=p.max_activity_difference,
                purpose="mmp_neighborhood",
                signals=signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_MMP_PAIR_NETWORK,
            structure_source=p.structure_source,
            activity_column=p.activity_column,
            only_selected=d.only_selected_rows(),
            make_worker=_make_worker,
        )

    def on_mmp_neighborhood_finished(self, pairs, activity_column: str) -> None:
        pairs = finish_analysis_pairs(
            self,
            TOOL_MMP_PAIR_NETWORK,
            pairs,
            empty_message="No matched molecular pairs were found for the current settings.",
        )
        if pairs is None:
            return
        self._open_mmp_neighborhood_map(pairs, activity_column=activity_column)
        self.status_label.setText(f"MMP Pair Network: {len(pairs)} pair(s).")

    def on_mmp_neighborhood_failed(self, message: str) -> None:
        report_analysis_failure(
            self,
            TOOL_MMP_PAIR_NETWORK,
            message,
            fallback="MMP Pair Network failed.",
        )

    def _open_mmp_neighborhood_map(self, pairs, *, activity_column: str) -> None:
        from ..mmp_neighborhood_map import MmpNeighborhoodMapDialog

        def _factory():
            dlg = MmpNeighborhoodMapDialog(self, pairs, activity_column=activity_column)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column)

        reuse_or_show_modeless_singleton(
            self,
            "_mmp_neighborhood_map_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )
