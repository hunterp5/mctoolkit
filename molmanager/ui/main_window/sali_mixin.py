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

"""Structure–Activity Landscape (SALI) tool entry points."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..analysis_job_support import (
    activity_value_for_table_oid,
    ensure_activity_analysis_ready,
    finish_analysis_pairs,
    report_analysis_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_SALI_MAP
from ...workers import SaliAnalysisWorker
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class SaliMixin:
    def open_sali_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_SALI_MAP,
            missing_activity_message="SALI requires at least one numeric activity/property column.",
        )
        if not activity_cols:
            return
        from ..dialogs.sali import SaliDialog

        d = SaliDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, d, on_accepted=self._on_sali_dialog_accepted)

    def _snapshot_off_target(self, column: str) -> dict[int, float] | None:
        """Read numeric off-target values on the GUI thread before the worker starts."""
        if column not in self.headers:
            QMessageBox.information(
                self,
                TOOL_SALI_MAP,
                f"Off-target column “{column}” is not in the table.",
            )
            return None
        col = self.headers.index(column)
        values: dict[int, float] = {}
        for oid in self._table_model.all_oids_in_order():
            off = activity_value_for_table_oid(
                self,
                int(oid),
                activity_column=column,
                activity_col_index=col,
            )
            if off is not None:
                values[int(oid)] = float(off)
        return values

    def _on_sali_dialog_accepted(self, d) -> None:
        p = d.params()
        off_by_oid = None
        if p.off_target_column:
            if p.off_target_column == p.activity_column:
                QMessageBox.information(
                    self,
                    TOOL_SALI_MAP,
                    "Choose a different off-target column.",
                )
                return
            off_by_oid = self._snapshot_off_target(p.off_target_column)
            if off_by_oid is None:
                return

        def _make_worker(rec, *, cancel_event, signals, progress_state):
            return SaliAnalysisWorker(
                rec,
                activity_column=p.activity_column,
                fp_choice=p.fp_choice,
                metric=p.metric,
                min_similarity=p.min_similarity,
                min_activity_difference=p.min_activity_difference,
                max_pairs=p.max_pairs,
                off_by_oid=off_by_oid,
                off_target_column=p.off_target_column,
                signals=signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_SALI_MAP,
            structure_source=p.structure_source,
            activity_column=p.activity_column,
            only_selected=d.only_selected_rows(),
            make_worker=_make_worker,
        )

    def on_sali_finished(
        self,
        points,
        activity_column: str,
        fp_choice: str,
        metric: str,
        off_target_column: str = "",
    ) -> None:
        empty = (
            "No pairs met the current similarity / selectivity-difference filters."
            if off_target_column
            else "No pairs met the current similarity / activity-difference filters."
        )
        points = finish_analysis_pairs(
            self,
            TOOL_SALI_MAP,
            points,
            empty_message=empty,
        )
        if points is None:
            return
        self._open_sali_map(
            points,
            activity_column=activity_column,
            fp_choice=fp_choice,
            metric=metric,
            off_target_column=off_target_column,
        )
        label = "SALI selectivity" if off_target_column else "SALI"
        self.status_label.setText(f"{label}: {len(points)} pair(s).")

    def on_sali_failed(self, message: str) -> None:
        report_analysis_failure(self, TOOL_SALI_MAP, message, fallback="SALI analysis failed.")

    def _open_sali_map(
        self,
        points,
        *,
        activity_column: str,
        fp_choice: str = "",
        metric: str = "Tanimoto",
        off_target_column: str = "",
    ) -> None:
        from ..sali_map import SaliMapDialog

        def _factory():
            dlg = SaliMapDialog(
                self,
                points,
                activity_column=activity_column,
                fp_choice=fp_choice,
                metric=metric,
                off_target_column=off_target_column,
            )
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_points(
                points,
                activity_column=activity_column,
                fp_choice=fp_choice,
                metric=metric,
                off_target_column=off_target_column,
            )

        reuse_or_show_modeless_singleton(
            self,
            "_sali_map_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def _open_sali_browser(
        self,
        points,
        *,
        activity_column: str,
        fp_choice: str = "",
        metric: str = "Tanimoto",
        start_index: int = 0,
        off_target_column: str = "",
    ) -> None:
        from ..sali_browser import SaliBrowserDialog

        def _factory():
            dlg = SaliBrowserDialog(
                self,
                points,
                activity_column=activity_column,
                fp_choice=fp_choice,
                metric=metric,
                start_index=start_index,
                off_target_column=off_target_column,
            )
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_points(
                points,
                activity_column=activity_column,
                fp_choice=fp_choice,
                metric=metric,
                start_index=start_index,
                off_target_column=off_target_column,
            )

        reuse_or_show_modeless_singleton(
            self,
            "_sali_browser_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )
