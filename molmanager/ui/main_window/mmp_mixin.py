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

"""Matched molecular pair (MMP) analysis entry points.

Leftover window MRO adapter over ``analysis_job_support``. New tools should go on
``WorkspaceTools`` instead of adding another window base.
"""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..analysis_job_support import (
    ensure_activity_analysis_ready,
    finish_analysis_pairs,
    report_analysis_failure,
    show_activity_tool_dialog,
    start_scoped_activity_job,
)
from ..strings import TOOL_MMP
from ...workers import MmpAnalysisWorker
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class MmpMixin:
    def open_mmp_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_MMP,
            missing_activity_message="MMP requires at least one numeric activity/property column.",
        )
        if not activity_cols:
            return
        from ..dialogs import MmpDialog

        d = MmpDialog(
            structure_sources=self.chemistry_tool_structure_sources(),
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, d, on_accepted=self._on_mmp_dialog_accepted)

    def _on_mmp_dialog_accepted(self, d) -> None:
        p = d.params()
        only_selected = d.only_selected_rows()
        if p.core_smarts:
            from ...analysis.mmp_analysis import parse_mmp_core_query

            if parse_mmp_core_query(p.core_smarts) is None:
                QMessageBox.information(
                    self,
                    TOOL_MMP,
                    "Core / MCS could not be parsed as SMARTS or SMILES.",
                )
                return

        def _make_worker(rec, *, cancel_event, signals, progress_state):
            return MmpAnalysisWorker(
                rec,
                activity_column=p.activity_column,
                max_cuts=p.max_cuts,
                max_variable_heavy_atoms=p.max_variable_heavy_atoms,
                min_activity_difference=p.min_activity_difference,
                max_activity_difference=p.max_activity_difference,
                core_smarts=p.core_smarts,
                signals=signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        start_scoped_activity_job(
            self,
            tool_label=TOOL_MMP,
            structure_source=p.structure_source,
            activity_column=p.activity_column,
            only_selected=only_selected,
            make_worker=_make_worker,
        )

    def on_mmp_finished(self, pairs, activity_column: str) -> None:
        pairs = finish_analysis_pairs(
            self,
            TOOL_MMP,
            pairs,
            empty_message="No matched molecular pairs were found for the current settings.",
        )
        if pairs is None:
            return

        from ...analysis.mmp_table import assemble_mmp_table_annotations

        rows, headers = assemble_mmp_table_annotations(pairs, activity_column=activity_column)
        if rows:
            self.on_calc_finished(rows, headers, finish_progress=False)

        self._mmp_last_pairs = pairs
        self._mmp_last_activity_column = str(activity_column or "")
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self._open_mmp_ledger(pairs, activity_column=activity_column)
        self.status_label.setText(f"MMP: {len(pairs)} pair(s).")

    def on_mmp_failed(self, message: str) -> None:
        report_analysis_failure(self, TOOL_MMP, message, fallback="MMP analysis failed.")

    def open_mmp_transform_ledger_for_last_run(self) -> None:
        """Re-open the Transform Ledger for the most recent MMP analysis."""
        pairs = list(getattr(self, "_mmp_last_pairs", None) or [])
        activity_column = str(getattr(self, "_mmp_last_activity_column", "") or "")
        if not pairs:
            QMessageBox.information(
                self,
                TOOL_MMP,
                "No MMP results are available in this session. Run Data → MMP first.",
            )
            return
        self._open_mmp_ledger(pairs, activity_column=activity_column)

    def _open_mmp_ledger(self, pairs, *, activity_column: str) -> None:
        from ..mmp_transform_ledger import MmpTransformLedgerDialog

        def _factory():
            dlg = MmpTransformLedgerDialog(self, pairs, activity_column=activity_column)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column)

        reuse_or_show_modeless_singleton(
            self,
            "_mmp_ledger_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def _open_mmp_browser(self, pairs, *, activity_column: str) -> None:
        from ..mmp_browser import MmpBrowserDialog

        self.reveal_first_selected_row(focus=False)

        def _factory():
            dlg = MmpBrowserDialog(self, pairs, activity_column=activity_column)
            dlg.setModal(False)
            dlg.setWindowModality(Qt.NonModal)
            return dlg

        def _on_reused(dlg):
            dlg.set_pairs(pairs, activity_column=activity_column)

        reuse_or_show_modeless_singleton(
            self,
            "_mmp_browser_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )
