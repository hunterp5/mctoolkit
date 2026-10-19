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

"""SAR matrix tool window (Data menu)."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

from ...analysis.sar_matrix import SarMatrixLimit, SarObservation, build_sar_matrix
from ...services.activity_records import parse_activity_float
from ..analysis_job_support import ensure_activity_analysis_ready, show_activity_tool_dialog
from ..qt_widget_utils import qobject_is_deleted
from ..strings import TOOL_SAR_MATRIX
from ..table_dataframe import iter_scoped_table_analysis_rows, scoped_table_column_names


class SarMatrixMixin:
    """Open the SAR matrix dialog and dock the colored grid beside the table."""

    def open_sar_matrix_dialog(self) -> None:
        activity_cols = ensure_activity_analysis_ready(
            self,
            TOOL_SAR_MATRIX,
            missing_activity_message="SAR matrix requires a numeric activity column.",
        )
        if not activity_cols:
            return
        _all_cols, numeric_cols = scoped_table_column_names(self, visible_only=True)
        numeric = set(numeric_cols)
        substituents = [
            name
            for name in _all_cols
            if name not in numeric and name not in {"ID_HIDDEN", "Structure"}
        ]
        if len(substituents) < 2:
            QMessageBox.warning(
                self,
                TOOL_SAR_MATRIX,
                "SAR matrix needs two substituent columns, usually R1 and R2 from "
                "Chemistry → Reaction → R-Group Decomposition.",
            )
            return
        from ..dialogs.sar_matrix import SarMatrixDialog

        dialog = SarMatrixDialog(
            substituent_columns=substituents,
            activity_columns=activity_cols,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(self, dialog, on_accepted=self._on_sar_matrix_dialog_accepted)

    def _on_sar_matrix_dialog_accepted(self, dialog) -> None:
        params = dialog.params()
        observations: list[SarObservation] = []
        for row_index, row in iter_scoped_table_analysis_rows(
            self,
            visible_only=True,
            only_selected=params.only_selected,
        ):
            observations.append(
                SarObservation(
                    oid=int(self._table_model.row_oid(row_index)),
                    row_label=row.get(params.row_column, ""),
                    col_label=row.get(params.column_column, ""),
                    page_label=row.get(params.page_column, "") if params.page_column else "",
                    activity=parse_activity_float(row.get(params.activity_column, "")),
                )
            )
        try:
            matrix = build_sar_matrix(
                observations,
                row_axis=params.row_column,
                col_axis=params.column_column,
                page_axis=params.page_column,
                activity_axis=params.activity_column,
            )
        except SarMatrixLimit as exc:
            QMessageBox.warning(self, TOOL_SAR_MATRIX, str(exc))
            return
        self._show_sar_matrix(matrix, higher_is_better=params.higher_is_better)

    def _show_sar_matrix(self, matrix, *, higher_is_better: bool) -> None:
        from ..sar_matrix_panel import SarMatrixPanel, SarMatrixWindow

        for widget in self.iter_docked_plot_widgets():
            if isinstance(widget, SarMatrixPanel):
                widget.set_matrix(matrix, higher_is_better=higher_is_better)
                self.show_docked_plot_panel()
                widget.raise_()
                self.status_label.setText("SAR matrix: updated in the workspace pane.")
                return
        existing = getattr(self, "_sar_matrix_dialog", None)
        if existing is not None and not qobject_is_deleted(existing):
            panel = getattr(existing, "_panel", None)
            if isinstance(panel, SarMatrixPanel):
                panel.set_matrix(matrix, higher_is_better=higher_is_better)
                existing.show()
                existing.raise_()
                return
        dialog = SarMatrixWindow(self)
        dialog._panel.set_matrix(matrix, higher_is_better=higher_is_better)
        self._sar_matrix_dialog = dialog
        dialog.show()
        dock = getattr(self, "dock_plot_widget", None)
        if callable(dock) and dock(dialog._panel):
            from ..dockable_plot import discard_host_dialog_after_dock

            discard_host_dialog_after_dock(dialog, self, "_sar_matrix_dialog")
            return
        self.status_label.setText("SAR matrix: opened.")
