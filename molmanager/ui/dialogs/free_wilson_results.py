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

"""Free-Wilson results: coefficients, predictions, and missing analogs."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...analysis.free_wilson import (
    PREDICTED_COLUMN,
    SOURCE_COLUMN,
    SOURCE_VALUE,
    FreeWilsonResult,
    MissingAnalog,
    report_label,
)
from ...chem.structure_2d_depiction import render_molecule_png
from ..qt_widget_utils import make_window_minimizable, qobject_is_deleted
from ..strings import TOOL_FREE_WILSON

_DRAW_ERRORS = (RuntimeError, ValueError, TypeError, OSError)


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return format(float(value), ".6g")


def _substituent_text(pairs: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f"{position}={label}" for position, label in pairs)


def _readonly_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    return table


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    return item


class FreeWilsonResultsDialog(QDialog):
    """Modeless summary of one Free-Wilson fit. Nothing is written until a button is used."""

    def __init__(self, result: FreeWilsonResult, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._result = result
        self._added_smiles: set[str] = set()
        self.setWindowTitle(self._title())
        self.resize(860, 560)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(), "Summary")
        tabs.addTab(self._contribution_tab(), "Contributions")
        tabs.addTab(self._observed_tab(), "Observed")
        tabs.addTab(self._missing_tab(), "Missing")
        root.addWidget(tabs, 1)
        make_window_minimizable(self)

    def _title(self) -> str:
        column = (self._result.activity_column or "").strip()
        if column:
            return f"{TOOL_FREE_WILSON} — {column}"
        return TOOL_FREE_WILSON

    def _summary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._summary_text())
        layout.addWidget(text)
        return page

    def _summary_text(self) -> str:
        result = self._result
        lines = [
            f"Report: {report_label(result.report)}",
            f"Fitted molecules: {result.n}",
            f"Parameters (including intercept): {result.n_parameters}",
            f"Intercept: {_fmt(result.intercept)}",
        ]
        if result.intercept_std_error is not None:
            lines.append(f"Intercept std. error: {_fmt(result.intercept_std_error)}")
        lines.append(f"R²: {_fmt(result.r_squared)}")
        lines.append(f"Adjusted R²: {_fmt(result.adjusted_r_squared) or '—'}")
        lines.append(f"RMSE: {_fmt(result.rmse)}")
        lines.append(f"Residual degrees of freedom: {result.residual_df}")
        if result.saturated:
            lines.append("The fit is saturated (no residual degrees of freedom).")
        if result.references:
            refs = ", ".join(f"{position}={label}" for position, label in result.references)
            lines.append(f"Reference substituents: {refs}")
        if result.skipped:
            counts: dict[str, int] = {}
            for row in result.skipped:
                counts[row.reason] = counts.get(row.reason, 0) + 1
            detail = ", ".join(f"{reason}: {count}" for reason, count in sorted(counts.items()))
            lines.append(f"Skipped rows: {len(result.skipped)} ({detail})")
        if result.position_counts:
            counts_text = ", ".join(
                f"{position}: {count}" for position, count in result.position_counts
            )
            lines.append(f"Substituents per position: {counts_text}")
        lines.append(f"Combinations: {result.n_combinations:,}")
        lines.append(f"Missing combinations: {result.n_missing:,}")
        lines.append(f"Listed missing analogs: {len(result.missing):,}")
        if result.enumeration_message:
            lines.append(result.enumeration_message)
        if result.n_zip_failed:
            lines.append(f"Combinations that could not be rebuilt: {result.n_zip_failed:,}")
        lines.append(
            "Predicted activities and missing structures are written to the table only "
            "from the Observed and Missing tabs."
        )
        return "\n".join(lines)

    def _contribution_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(
            ["Position", "Substituent", "Count", "Coefficient", "Std. error", "Note"]
        )
        table.setRowCount(len(self._result.coefficients))
        for row_index, coef in enumerate(self._result.coefficients):
            if not coef.identifiable:
                note = "not identifiable"
            elif coef.is_reference:
                note = "reference"
            else:
                note = ""
            values = [
                coef.position,
                coef.label,
                str(coef.count),
                _fmt(coef.coefficient),
                _fmt(coef.std_error),
                note,
            ]
            for column, value in enumerate(values):
                table.setItem(row_index, column, _text_item(value))
        layout.addWidget(table)
        return page

    def _observed_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(["OID", "Observed", "Predicted", "Residual", "Substituents"])
        table.setRowCount(len(self._result.observed))
        for row_index, row in enumerate(self._result.observed):
            values = [
                str(row.oid),
                _fmt(row.observed),
                _fmt(row.predicted),
                _fmt(row.residual),
                _substituent_text(row.substituents),
            ]
            for column, value in enumerate(values):
                table.setItem(row_index, column, _text_item(value))
        layout.addWidget(table, 1)
        button_row = QHBoxLayout()
        self._write_btn = QPushButton("Write predictions")
        self._write_btn.setToolTip(
            f"Write {PREDICTED_COLUMN} for each fitted row. Does not add new rows."
        )
        self._write_btn.setEnabled(bool(self._result.observed))
        self._write_btn.clicked.connect(self._write_predictions)
        button_row.addWidget(self._write_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return page

    def _missing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        self._preview = QLabel("Select a row to preview the structure.")
        self._preview.setAlignment(Qt.AlignCenter)
        self._preview.setMinimumHeight(160)
        layout.addWidget(self._preview)
        if self._result.enumeration_message:
            note = QLabel(self._result.enumeration_message)
            note.setWordWrap(True)
            layout.addWidget(note)
        self._missing_table = _readonly_table(["Substituents", "Predicted", "SMILES"])
        self._missing_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._missing_table.setRowCount(len(self._result.missing))
        for row_index, analog in enumerate(self._result.missing):
            values = [
                _substituent_text(analog.substituents),
                _fmt(analog.predicted),
                analog.smiles,
            ]
            for column, value in enumerate(values):
                self._missing_table.setItem(row_index, column, _text_item(value))
        self._missing_table.itemSelectionChanged.connect(self._preview_selection)
        layout.addWidget(self._missing_table, 1)
        button_row = QHBoxLayout()
        self._add_selected_btn = QPushButton("Add selected to table")
        self._add_selected_btn.setToolTip(
            "Append the selected missing analogs as new rows with SMILES, "
            f"{PREDICTED_COLUMN}, R-group labels, and a source field."
        )
        self._add_all_btn = QPushButton("Add all shown")
        self._add_all_btn.setToolTip("Append every listed missing analog.")
        enabled = bool(self._result.missing)
        self._add_selected_btn.setEnabled(enabled)
        self._add_all_btn.setEnabled(enabled)
        self._add_selected_btn.clicked.connect(self._add_selected)
        self._add_all_btn.clicked.connect(self._add_all)
        button_row.addWidget(self._add_selected_btn)
        button_row.addWidget(self._add_all_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return page

    def _preview_selection(self) -> None:
        analogs = self._selected_analogs()
        if not analogs:
            self._preview.setText("Select a row to preview the structure.")
            self._preview.setPixmap(QPixmap())
            return
        self._show_smiles(analogs[0].smiles)

    def _show_smiles(self, smiles: str) -> None:
        mol = Chem.MolFromSmiles(smiles or "")
        if mol is None:
            self._preview.setText(smiles)
            self._preview.setPixmap(QPixmap())
            return
        try:
            png = render_molecule_png(mol, 240, 160)
        except _DRAW_ERRORS:
            self._preview.setText(smiles)
            self._preview.setPixmap(QPixmap())
            return
        self._preview.setText("")
        self._preview.setPixmap(QPixmap.fromImage(QImage.fromData(png)))

    def _selected_analogs(self) -> list[MissingAnalog]:
        rows = sorted({item.row() for item in self._missing_table.selectedItems()})
        missing = self._result.missing
        return [missing[row] for row in rows if 0 <= row < len(missing)]

    def _write_predictions(self) -> None:
        app = self.parent_app
        if app is None or not hasattr(app, "on_calc_finished"):
            QMessageBox.warning(self, TOOL_FREE_WILSON, "The table is not available.")
            return
        rows = [(row.oid, {PREDICTED_COLUMN: _fmt(row.predicted)}) for row in self._result.observed]

        def _written(_headers: list[str]) -> None:
            self._mark_dirty(app)
            status = getattr(app, "status_label", None)
            if status is not None:
                status.setText(
                    f"{TOOL_FREE_WILSON}: wrote {PREDICTED_COLUMN} for {len(rows):,} row(s)."
                )
            if qobject_is_deleted(self):
                return
            self._write_btn.setEnabled(False)
            self._write_btn.setText("Predictions written")

        app.on_calc_finished(
            rows,
            [PREDICTED_COLUMN],
            finish_progress=False,
            on_complete=_written,
        )

    def _add_selected(self) -> None:
        analogs = [row for row in self._selected_analogs() if row.smiles not in self._added_smiles]
        if not analogs:
            QMessageBox.information(
                self,
                TOOL_FREE_WILSON,
                "Select one or more missing analogs that are not already added.",
            )
            return
        self._add_analogs(analogs)

    def _add_all(self) -> None:
        analogs = [row for row in self._result.missing if row.smiles not in self._added_smiles]
        if not analogs:
            return
        self._add_analogs(analogs)

    def _add_analogs(self, analogs: list[MissingAnalog]) -> None:
        app = self.parent_app
        if app is None or not hasattr(app, "add_rows_from_external_records_batch"):
            QMessageBox.warning(self, TOOL_FREE_WILSON, "The table is not available.")
            return
        records: list[tuple[str, dict[str, str]]] = []
        for analog in analogs:
            fields = {
                PREDICTED_COLUMN: _fmt(analog.predicted),
                SOURCE_COLUMN: SOURCE_VALUE,
            }
            for position, label in analog.substituents:
                fields[f"FW_{position}"] = label
            records.append((analog.smiles, fields))
        added = int(app.add_rows_from_external_records_batch(records, render_structures=True))
        for analog in analogs:
            self._added_smiles.add(analog.smiles)
        if len(self._added_smiles) >= len(self._result.missing):
            self._add_all_btn.setEnabled(False)
            self._add_all_btn.setText("All shown added")
        self._mark_dirty(app)
        status = getattr(app, "status_label", None)
        if status is not None:
            status.setText(f"{TOOL_FREE_WILSON}: added {added:,} missing analog(s).")

    def _mark_dirty(self, app: object) -> None:
        mark = getattr(app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
