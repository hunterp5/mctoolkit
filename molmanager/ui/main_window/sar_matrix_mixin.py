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

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QMessageBox

from ...analysis.design_studio import series_core_from_labels, suggest_core_column
from ...analysis.sar_matrix import SarMatrixLimit, SarObservation, build_sar_matrix
from ...services.activity_records import parse_activity_float
from ..analysis_job_support import ensure_activity_analysis_ready, show_activity_tool_dialog
from ..qt_widget_utils import qobject_is_deleted
from ..strings import TOOL_SAR_MATRIX
from ..table_dataframe import iter_scoped_table_analysis_rows, scoped_table_column_names

_BLANK_LABEL = frozenset({"", "n/a", "na", "none", "null", "nan"})


def _label_kept(row_label: str, col_label: str, page_label: str, page_column: str) -> bool:
    """True when this row would land on the SAR grid."""
    if (row_label or "").strip().casefold() in _BLANK_LABEL:
        return False
    if (col_label or "").strip().casefold() in _BLANK_LABEL:
        return False
    if page_column and (page_label or "").strip().casefold() in _BLANK_LABEL:
        return False
    return True


class SarMatrixMixin:
    """Open the SAR matrix dialog, then show the colored grid in its own window."""

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
                "Chemistry → Structure Decomposition → Core-Based Decomposition.",
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
        all_cols, _numeric = scoped_table_column_names(self, visible_only=True)
        core_column = suggest_core_column(all_cols, params.row_column)
        observations: list[SarObservation] = []
        cores: list[str] = []
        for row_index, row in iter_scoped_table_analysis_rows(
            self,
            visible_only=True,
            only_selected=params.only_selected,
        ):
            row_label = row.get(params.row_column, "")
            col_label = row.get(params.column_column, "")
            page_label = row.get(params.page_column, "") if params.page_column else ""
            observations.append(
                SarObservation(
                    oid=int(self._table_model.row_oid(row_index)),
                    row_label=row_label,
                    col_label=col_label,
                    page_label=page_label,
                    activity=parse_activity_float(row.get(params.activity_column, "")),
                )
            )
            if core_column and _label_kept(row_label, col_label, page_label, params.page_column):
                cores.append(str(row.get(core_column, "")))
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
        except (TypeError, ValueError, RuntimeError, MemoryError, OverflowError) as exc:
            QMessageBox.warning(
                self, TOOL_SAR_MATRIX, str(exc) or "Could not build the SAR matrix."
            )
            return
        higher = params.higher_is_better
        core_smiles, core_state = (
            series_core_from_labels(cores) if core_column else (None, "missing")
        )
        # The grid used to open inside this slot, which is still inside the
        # settings dialog's click. Showing that window and closing it again
        # fail-fasts in CoreMessaging.dll on Windows 10. Open it on the next turn.

        def _open() -> None:
            self._open_built_sar_matrix(
                matrix,
                higher_is_better=higher,
                series_core=core_smiles,
                series_core_state=core_state,
            )

        QTimer.singleShot(0, _open)

    def _open_built_sar_matrix(
        self,
        matrix,
        *,
        higher_is_better: bool,
        series_core: str | None = None,
        series_core_state: str = "missing",
    ) -> None:
        try:
            self._show_sar_matrix(
                matrix,
                higher_is_better=higher_is_better,
                series_core=series_core,
                series_core_state=series_core_state,
            )
        except (RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, TOOL_SAR_MATRIX, str(exc) or "Could not open the SAR matrix.")

    def _show_sar_matrix(
        self,
        matrix,
        *,
        higher_is_better: bool,
        series_core: str | None = None,
        series_core_state: str = "missing",
    ) -> None:
        from ..sar_matrix_panel import SarMatrixPanel, SarMatrixWindow

        for widget in self.iter_docked_plot_widgets():
            if isinstance(widget, SarMatrixPanel):
                widget.set_matrix(
                    matrix,
                    higher_is_better=higher_is_better,
                    series_core=series_core,
                    series_core_state=series_core_state,
                )
                self.show_docked_plot_panel()
                widget.raise_()
                self.status_label.setText("SAR matrix: updated in the workspace pane.")
                return
        existing = getattr(self, "_sar_matrix_dialog", None)
        if existing is not None and not qobject_is_deleted(existing):
            panel = getattr(existing, "_panel", None)
            if isinstance(panel, SarMatrixPanel):
                panel.set_matrix(
                    matrix,
                    higher_is_better=higher_is_better,
                    series_core=series_core,
                    series_core_state=series_core_state,
                )
                existing.show()
                existing.raise_()
                existing.activateWindow()
                return
        panel = SarMatrixPanel(self, self)
        panel.set_matrix(
            matrix,
            higher_is_better=higher_is_better,
            series_core=series_core,
            series_core_state=series_core_state,
        )
        dialog = SarMatrixWindow(self, panel=panel)
        self._sar_matrix_dialog = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        self.status_label.setText("SAR matrix: opened.")
