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

"""Hansch results: the equation, coefficients, and observed versus predicted."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...analysis.hansch import PREDICTED_COLUMN, HanschResult
from ..qt_widget_utils import make_window_resizable, qobject_is_deleted
from ..strings import TOOL_HANSCH


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    if value == float("inf"):
        return "inf"
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
    table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setStretchLastSection(True)
    return table


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    return item


class HanschResultsDialog(QDialog):
    """Modeless summary of one Hansch fit. Nothing is written until a button is used."""

    def __init__(self, result: HanschResult, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._result = result
        column = (result.activity_column or "").strip()
        title = f"{TOOL_HANSCH} — {column}" if column else TOOL_HANSCH
        self.setWindowTitle(title)
        self.resize(860, 560)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(), "Summary")
        tabs.addTab(self._coefficient_tab(), "Coefficients")
        tabs.addTab(self._observed_tab(), "Observed")
        tabs.addTab(self._skipped_tab(), "Skipped")
        root.addWidget(tabs, 1)

        buttons = QDialogButtonBox()
        self._write_btn = QPushButton("Write predictions")
        self._write_btn.setEnabled(bool(result.observed))
        self._write_btn.clicked.connect(self._write_predictions)
        buttons.addButton(self._write_btn, QDialogButtonBox.ActionRole)
        close = buttons.addButton(QDialogButtonBox.Close)
        close.clicked.connect(self.close)
        root.addWidget(buttons)
        make_window_resizable(self)

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
            result.equation or "(no equation)",
            "",
            f"Fitted molecules: {result.n}",
            f"Parameters (including intercept): {result.n_parameters}",
            f"r²: {_fmt(result.r_squared)}",
            f"Adjusted r²: {_fmt(result.adjusted_r_squared)}",
            f"q² (leave-one-out): {_fmt(result.q_squared)}",
            f"RMSE: {_fmt(result.rmse)}",
            f"Residual degrees of freedom: {result.residual_df}",
            f"Intercept: {_fmt(result.intercept)}",
            f"Intercept std. error: {_fmt(result.intercept_std_error)}",
            f"Intercept t: {_fmt(result.intercept_t)}",
            f"Intercept p: {_fmt(result.intercept_p)}",
        ]
        if result.saturated:
            lines.append("The fit is saturated, so standard errors are not reported.")
        high_vif = [
            item.name
            for item in result.coefficients
            if item.identifiable and item.vif is not None and item.vif > 10.0
        ]
        if high_vif:
            lines.append("High VIF (> 10): " + ", ".join(high_vif) + ".")
        dropped = [item.name for item in result.coefficients if not item.identifiable]
        if dropped:
            lines.append("Not identifiable: " + ", ".join(dropped) + ".")
        if result.unmatched:
            listed = ", ".join(f"{position}={key}" for position, key in result.unmatched)
            lines.append("Substituents missing from the constants file: " + listed + ".")
        if result.message:
            lines.extend(["", result.message])
        return "\n".join(lines)

    def _coefficient_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(["Term", "Coefficient", "Std. error", "t", "p", "VIF"])
        for row, item in enumerate(self._result.coefficients):
            table.insertRow(row)
            values = [
                item.name,
                _fmt(item.coefficient),
                _fmt(item.std_error),
                _fmt(item.t_value),
                _fmt(item.p_value),
                _fmt(item.vif),
            ]
            for column, text in enumerate(values):
                table.setItem(row, column, _text_item(text))
        layout.addWidget(table)
        return page

    def _observed_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(["Row", "Observed", "Predicted", "Residual", "Substituents"])
        for row, item in enumerate(self._result.observed):
            table.insertRow(row)
            values = [
                str(item.oid),
                _fmt(item.observed),
                _fmt(item.predicted),
                _fmt(item.residual),
                _substituent_text(item.substituents),
            ]
            for column, text in enumerate(values):
                table.setItem(row, column, _text_item(text))
        layout.addWidget(table)
        return page

    def _skipped_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(["Row", "Reason"])
        for row, item in enumerate(self._result.skipped):
            table.insertRow(row)
            table.setItem(row, 0, _text_item(str(item.oid)))
            table.setItem(row, 1, _text_item(item.reason))
        layout.addWidget(table)
        return page

    def _write_predictions(self) -> None:
        app = self.parent_app
        if app is None or not hasattr(app, "on_calc_finished"):
            QMessageBox.warning(self, TOOL_HANSCH, "The table is not available.")
            return
        rows = [(row.oid, {PREDICTED_COLUMN: _fmt(row.predicted)}) for row in self._result.observed]

        def _written(_headers: list[str]) -> None:
            mark = getattr(app, "_mark_session_dirty", None)
            if callable(mark):
                mark()
            status = getattr(app, "status_label", None)
            if status is not None:
                status.setText(f"{TOOL_HANSCH}: wrote {PREDICTED_COLUMN} for {len(rows):,} row(s).")
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
