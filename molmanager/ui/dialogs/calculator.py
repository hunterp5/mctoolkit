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

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...workflows.tool_requests import CalculatorColumnRequest, row_scope_from_only_selected
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_CALCULATOR
from .scope import selection_scope_checked

# (button label, token inserted; empty token with label C / ⌫ uses special handlers)
_KEYPAD_ROWS: tuple[tuple[str, str], ...] = (
    ("C", ""),
    ("⌫", ""),
    ("(", "("),
    (")", ")"),
    ("7", "7"),
    ("8", "8"),
    ("9", "9"),
    ("÷", "/"),
    ("4", "4"),
    ("5", "5"),
    ("6", "6"),
    ("×", "*"),
    ("1", "1"),
    ("2", "2"),
    ("3", "3"),
    ("−", "-"),
    ("0", "0"),
    (".", "."),
    ("^", "**"),
    ("+", "+"),
    ("√", "sqrt("),
    ("log", "log10("),
    ("exp", "exp("),
    ("π", "pi"),
)

_KEYPAD_COLS = 4


class CalculatorDialog(QDialog):
    """Build a numeric table column with a keypad-style expression editor."""

    apply_requested = pyqtSignal()

    def __init__(self, numeric_columns, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_CALCULATOR)
        self.resize(440, 620)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setSpacing(10)

        self.expr_input = QLineEdit()
        self.expr_input.setPlaceholderText("Enter expression or tap keys…")
        disp_font = QFont("Consolas")
        disp_font.setPointSize(13)
        self.expr_input.setFont(disp_font)
        self.expr_input.setAlignment(Qt.AlignRight)
        self.expr_input.setMinimumHeight(42)
        self.expr_input.setClearButtonEnabled(True)
        root.addWidget(self.expr_input)

        pad_box = QGroupBox("Keypad")
        pad_grid = QGridLayout(pad_box)
        pad_grid.setSpacing(6)
        btn_font = QFont()
        btn_font.setPointSize(11)
        row = col = 0
        for label, token in _KEYPAD_ROWS:
            btn = QPushButton(label)
            btn.setFont(btn_font)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            btn.setMinimumHeight(36)
            if label == "C":
                btn.clicked.connect(self._clear_expression)
            elif label == "⌫":
                btn.clicked.connect(self._backspace_expression)
            else:
                btn.clicked.connect(lambda _checked=False, t=token: self._append_token(t))
            pad_grid.addWidget(btn, row, col)
            col += 1
            if col >= _KEYPAD_COLS:
                col = 0
                row += 1
        root.addWidget(pad_box)

        var_box = QGroupBox("Column variables")
        var_outer = QVBoxLayout(var_box)
        var_hint = QLabel("Tap a column to insert [ColumnName] into the expression.")
        var_hint.setWordWrap(True)
        var_outer.addWidget(var_hint)

        var_scroll = QScrollArea()
        var_scroll.setWidgetResizable(True)
        var_scroll.setMaximumHeight(140)
        var_host = QWidget()
        var_grid = QGridLayout(var_host)
        var_grid.setSpacing(4)
        self._column_buttons: list[QPushButton] = []
        if numeric_columns:
            for i, name in enumerate(numeric_columns):
                vb = QPushButton(name)
                vb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                vb.clicked.connect(lambda _c=False, n=name: self._insert_column(n))
                var_grid.addWidget(vb, i // 3, i % 3)
                self._column_buttons.append(vb)
        else:
            var_grid.addWidget(QLabel("No numeric columns in the table yet."), 0, 0)
        var_scroll.setWidget(var_host)
        var_outer.addWidget(var_scroll)
        root.addWidget(var_box)

        out_box = QGroupBox("Output")
        out_lyt = QFormLayout(out_box)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("New column name")
        out_lyt.addRow("Column name:", self.name_input)
        root.addWidget(out_box)

        scope_box = QGroupBox("Scope")
        scope_lyt = QVBoxLayout(scope_box)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        scope_lyt.addWidget(self.only_selected_cb)
        root.addWidget(scope_box)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        apply_btn = bb.button(QDialogButtonBox.Ok)
        apply_btn.setText("Apply to Table")
        apply_btn.clicked.connect(self._on_apply_clicked)
        bb.rejected.connect(self.reject)
        root.addWidget(bb)
        make_window_minimizable(self)

    def _append_token(self, token: str) -> None:
        self.expr_input.setFocus(Qt.OtherFocusReason)
        self.expr_input.insert(token)

    def _insert_column(self, name: str) -> None:
        self._append_token(f"[{name}]")

    def _clear_expression(self) -> None:
        self.expr_input.clear()
        self.expr_input.setFocus(Qt.OtherFocusReason)

    def _backspace_expression(self) -> None:
        text = self.expr_input.text()
        pos = self.expr_input.cursorPosition()
        if pos > 0:
            self.expr_input.setText(text[: pos - 1] + text[pos:])
            self.expr_input.setCursorPosition(pos - 1)
        self.expr_input.setFocus(Qt.OtherFocusReason)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def request(self) -> CalculatorColumnRequest:
        """The column and expression, without a row snapshot."""
        return CalculatorColumnRequest(
            column=self.name_input.text().strip(),
            expression=self.expr_input.text().strip(),
            row_scope=row_scope_from_only_selected(self.only_selected_rows()),
        )

    def _on_apply_clicked(self) -> None:
        if not self.expr_input.text().strip():
            if self._column_buttons:
                self._insert_column(self._column_buttons[0].text())
            else:
                QMessageBox.warning(
                    self,
                    TOOL_CALCULATOR,
                    "Enter an expression, or add numeric columns to the table first.",
                )
                return
        if not self.name_input.text().strip():
            QMessageBox.warning(
                self,
                TOOL_CALCULATOR,
                "Enter a name for the new column.",
            )
            self.name_input.setFocus(Qt.OtherFocusReason)
            return
        self.apply_requested.emit()
