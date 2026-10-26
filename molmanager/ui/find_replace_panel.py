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

"""Find and Replace bar widgets. Matching and writes live on the table mixin."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QWidget,
)

FIND_REPLACE_ALL_COLUMNS = "all"

FIND_REPLACE_SCOPE_ITEMS: tuple[tuple[str, str], ...] = (
    ("Visible rows", "visible"),
    ("Entire table", "table"),
    ("Selected cells", "selection"),
)


class FindReplaceBar(QWidget):
    """Find text, replacement, column, scope, and the action buttons."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.close_btn = QPushButton("−", self)
        self.close_btn.setFixedWidth(28)
        self.close_btn.setToolTip("Close Find and Replace. The text stays until you clear it.")
        lay.addWidget(self.close_btn)

        lay.addWidget(QLabel("Find:", self))
        self.find_edit = QLineEdit(self)
        self.find_edit.setPlaceholderText("Text, eth*, >10, empty")
        self.find_edit.setMinimumWidth(120)
        self.find_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.find_edit.setToolTip(
            "Literal text, wildcards (* and ?), or a comparison such as >10, =ethanol, or empty. "
            "Press Enter to jump to the next match."
        )
        lay.addWidget(self.find_edit, 1)

        lay.addWidget(QLabel("Replace:", self))
        self.replace_edit = QLineEdit(self)
        self.replace_edit.setPlaceholderText("Replacement")
        self.replace_edit.setMinimumWidth(120)
        self.replace_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.replace_edit.setToolTip(
            "Text to insert. Leave this empty to delete the match. "
            "A backslash, *, or ? is written as typed. Press Enter to replace the current match."
        )
        lay.addWidget(self.replace_edit, 1)

        lay.addWidget(QLabel("Column:", self))
        self.column_combo = QComboBox(self)
        self.column_combo.setMinimumWidth(140)
        self.column_combo.setToolTip(
            "All text columns, or one column. ID, Structure, and image columns are skipped."
        )
        lay.addWidget(self.column_combo)

        lay.addWidget(QLabel("Scope:", self))
        self.scope_combo = QComboBox(self)
        self.scope_combo.setMinimumWidth(120)
        for label, value in FIND_REPLACE_SCOPE_ITEMS:
            self.scope_combo.addItem(label, value)
        self.scope_combo.setToolTip(
            "Visible rows follows the current filters. Entire table includes hidden rows. "
            "Selected cells uses the current selection."
        )
        lay.addWidget(self.scope_combo)

        self.case_cb = QCheckBox("Match case", self)
        self.case_cb.setToolTip(
            "Letter case must match. Off still inserts the replacement as typed."
        )
        lay.addWidget(self.case_cb)

        self.whole_cb = QCheckBox("Whole cell", self)
        self.whole_cb.setToolTip(
            "The entire cell must match. Off replaces every matching span. "
            "Comparisons always replace the whole cell."
        )
        lay.addWidget(self.whole_cb)

        self.find_next_btn = QPushButton("Find Next", self)
        self.find_next_btn.setToolTip("Select the next matching cell.")
        lay.addWidget(self.find_next_btn)

        self.replace_btn = QPushButton("Replace", self)
        self.replace_btn.setToolTip(
            "Replace matches in the current cell, then move to the next match."
        )
        lay.addWidget(self.replace_btn)

        self.replace_all_btn = QPushButton("Replace All", self)
        self.replace_all_btn.setToolTip(
            "Replace every match in the chosen column and scope. One undo restores them."
        )
        lay.addWidget(self.replace_all_btn)

        for button in (
            self.close_btn,
            self.find_next_btn,
            self.replace_btn,
            self.replace_all_btn,
        ):
            button.setAutoDefault(False)
            button.setDefault(False)
