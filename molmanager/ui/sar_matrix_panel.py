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

"""Docked R1 × R2 activity grid."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QBrush, QColor
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..analysis.sar_matrix import SarCell, SarMatrix, sar_page_csv
from .browsers.chrome import BrowserHostDialog, apply_browser_body_layout, style_browser_data_table
from .dockable_plot import (
    apply_plot_chrome_glyphs,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_close_plot_button,
    make_send_window_button,
    request_close_plot_widget,
    style_plot_footer_text_button,
    sync_docked_footer_bar,
    sync_footer_on_parent_change,
)
from .strings import TOOL_SAR_MATRIX

_HEADER_LIMIT = 22
_WORSE = QColor(252, 220, 220)
_BETTER = QColor(170, 214, 186)


def _short_label(label: str) -> str:
    text = label.strip()
    if len(text) <= _HEADER_LIMIT:
        return text
    return text[: _HEADER_LIMIT - 1] + "…"


def _mix(worse: QColor, better: QColor, amount: float) -> QColor:
    span = min(1.0, max(0.0, amount))
    return QColor(
        int(worse.red() * (1.0 - span) + better.red() * span),
        int(worse.green() * (1.0 - span) + better.green() * span),
        int(worse.blue() * (1.0 - span) + better.blue() * span),
    )


def _activity_color(value: float, low: float, high: float, *, higher_is_better: bool) -> QColor:
    if high <= low:
        amount = 1.0
    else:
        amount = (value - low) / (high - low)
    if not higher_is_better:
        amount = 1.0 - amount
    return _mix(_WORSE, _BETTER, amount)


class SarMatrixPanel(QWidget):
    """Colored substituent grid. A click selects the compounds in that cell."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = TOOL_SAR_MATRIX
        self._matrix: SarMatrix | None = None
        self._higher_is_better = True

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        page_row = QHBoxLayout()
        self._page_label = QLabel("Page:")
        self._page_combo = QComboBox()
        self._page_combo.setMinimumWidth(160)
        self._page_combo.currentIndexChanged.connect(self._show_current_page)
        page_row.addWidget(self._page_label)
        page_row.addWidget(self._page_combo, 1)
        root.addLayout(page_row)

        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        root.addWidget(self._summary)

        self._table = QTableWidget(0, 0, self)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectItems)
        self._table.setWordWrap(False)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self._table.verticalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        style_browser_data_table(self._table)
        self._table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self._table, 1)

        footer = QHBoxLayout()
        self._export_btn = QPushButton("Export…", self)
        self._export_btn.setToolTip(
            "Save the current page as a CSV table. Blank cells were not made."
        )
        style_plot_footer_text_button(self._export_btn)
        self._export_btn.clicked.connect(self._export_current_page)
        self._add_to_main_btn = make_add_to_main_button(self, tooltip="Dock beside the table")
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        self._send_window_btn = make_send_window_button(self, tooltip="Open in a separate window")
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        self._close_btn = make_close_plot_button(self, tooltip="Close this SAR matrix.")
        self._close_btn.clicked.connect(self._close_docked)
        footer.addWidget(self._export_btn)
        footer.addStretch(1)
        footer.addWidget(self._add_to_main_btn)
        footer.addWidget(self._send_window_btn)
        footer.addWidget(self._close_btn)
        root.addLayout(footer)
        self._sync_footer_chrome()
        self.setMinimumWidth(420)

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self.parent_app = parent_app
        self._app = parent_app

    def embedded_minimum_width(self) -> int:
        return 420

    def embedded_preferred_width(self) -> int:
        return 640

    def create_floating_dialog(self, parent_app) -> SarMatrixWindow:
        self.show()
        return SarMatrixWindow(parent_app, panel=self)

    def set_matrix(self, matrix: SarMatrix, *, higher_is_better: bool) -> None:
        """Replace the grid. The current page index is kept when the page count allows."""
        previous = self._page_combo.currentIndex()
        self._matrix = matrix
        self._higher_is_better = bool(higher_is_better)
        self._page_combo.blockSignals(True)
        self._page_combo.clear()
        for page in matrix.pages:
            label = page.label or "(all)"
            if matrix.page_axis and page.label:
                label = f"{matrix.page_axis} = {page.label}"
            self._page_combo.addItem(label)
        show_pages = len(matrix.pages) > 1
        self._page_combo.setVisible(show_pages)
        self._page_label.setVisible(show_pages)
        if 0 <= previous < self._page_combo.count():
            self._page_combo.setCurrentIndex(previous)
        self._page_combo.blockSignals(False)
        self._show_current_page()

    def _current_page(self):
        matrix = self._matrix
        if matrix is None or not matrix.pages:
            return None
        index = self._page_combo.currentIndex()
        if index < 0:
            index = 0
        return matrix.page(index)

    def _show_current_page(self) -> None:
        matrix = self._matrix
        page = self._current_page()
        self._table.clear()
        if matrix is None or page is None:
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._summary.setText("")
            return
        self._table.setRowCount(len(page.row_labels))
        self._table.setColumnCount(len(page.col_labels))
        self._table.setHorizontalHeaderLabels([_short_label(label) for label in page.col_labels])
        self._table.setVerticalHeaderLabels([_short_label(label) for label in page.row_labels])
        for col, label in enumerate(page.col_labels):
            item = self._table.horizontalHeaderItem(col)
            if item is not None:
                item.setToolTip(f"{matrix.col_axis}: {label}")
        for row, label in enumerate(page.row_labels):
            item = self._table.verticalHeaderItem(row)
            if item is not None:
                item.setToolTip(f"{matrix.row_axis}: {label}")
        low = matrix.value_min
        high = matrix.value_max
        for row, row_label in enumerate(page.row_labels):
            for col, col_label in enumerate(page.col_labels):
                cell = page.cells.get((row_label, col_label))
                self._table.setItem(row, col, self._item_for(cell, low, high))
        direction = "higher is darker" if self._higher_is_better else "lower is darker"
        self._summary.setText(
            f"{matrix.activity_axis} · {page.filled_count()} filled, "
            f"{page.empty_count()} not made · {direction}"
        )

    def _item_for(
        self,
        cell: SarCell | None,
        low: float | None,
        high: float | None,
    ) -> QTableWidgetItem:
        if cell is None:
            item = QTableWidgetItem("")
            item.setToolTip("Not made")
            item.setBackground(self.palette().alternateBase())
            return item
        item = QTableWidgetItem(cell.grid_text())
        item.setData(Qt.UserRole, list(cell.oids))
        item.setTextAlignment(Qt.AlignCenter)
        lines = []
        for oid, activity in zip(cell.oids, cell.activities):
            shown = "—" if activity is None else f"{activity:.4g}"
            lines.append(f"Row {oid}: {shown}")
        item.setToolTip("\n".join(lines))
        value = cell.display_value()
        if value is not None and low is not None and high is not None:
            item.setBackground(
                QBrush(_activity_color(value, low, high, higher_is_better=self._higher_is_better))
            )
            item.setForeground(QBrush(QColor(20, 20, 20)))
        return item

    def _on_cell_clicked(self, row: int, col: int) -> None:
        item = self._table.item(row, col)
        app = self._app
        if item is None or app is None:
            return
        oids = item.data(Qt.UserRole)
        if not oids:
            status = getattr(app, "status_label", None)
            if status is not None:
                status.setText("SAR matrix: that combination has not been made.")
            return
        select = getattr(app, "select_table_oids", None)
        if callable(select):
            select(list(oids), extra_status="SAR matrix", reveal=True)

    def _export_current_page(self) -> None:
        matrix = self._matrix
        page = self._current_page()
        if matrix is None or page is None:
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Export SAR matrix",
            "sar_matrix.csv",
            "CSV (*.csv)",
        )
        if not path:
            return
        text = sar_page_csv(page, row_axis=matrix.row_axis)
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def _add_to_main_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        dock = getattr(app, "dock_plot_widget", None)
        if not callable(dock) or not dock(self):
            return
        dlg = self.window()
        if isinstance(dlg, SarMatrixWindow):
            discard_host_dialog_after_dock(dlg, app, "_sar_matrix_dialog")

    def _send_to_new_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        undock = getattr(app, "undock_plot_to_window", None)
        if callable(undock):
            undock(self)

    def _close_docked(self) -> None:
        request_close_plot_widget(self, title="Close SAR Matrix", message="Close this SAR matrix?")

    def _is_docked(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        return bool(callable(check) and check(self))

    def _sync_footer_chrome(self) -> None:
        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), SarMatrixWindow)
        docked = self._is_docked()
        self._add_to_main_btn.setVisible(floating or not docked)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        super().changeEvent(event)


class SarMatrixWindow(BrowserHostDialog):
    """Floating shell for :class:`SarMatrixPanel`."""

    default_title = TOOL_SAR_MATRIX
    close_title = "Close SAR Matrix"
    close_message = "Close this SAR matrix?"
    panel_cls = SarMatrixPanel
    min_size = (640, 420)
    initial_size = (760, 520)
