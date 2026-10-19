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

"""Multi-row in-table search bar widgets."""

from __future__ import annotations

from collections.abc import Callable

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

_PLACEHOLDER_TEXT = (
    'Quote column text ("eth*", NOT "blank") or compare (>10, empty). '
    "Unquoted SMILES/SMARTS searches structures (c1ccccc1, [F,Cl], [!C;R]). "
    "& AND, | or comma OR. NOT, !, or - excludes a pattern. Press Enter."
)


class SearchCriterionRow(QWidget):
    """One column + query line; Add, −, optional glue, and per-row search options."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        show_glue: bool = False,
        show_add: bool = False,
        on_add: Callable[[], None] | None = None,
        on_remove: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self.remove_btn = QPushButton("−", self)
        self.remove_btn.setFixedWidth(28)
        self.remove_btn.setToolTip("Delete this search and close Search.")
        if on_remove is not None:
            self.remove_btn.clicked.connect(on_remove)
        lay.addWidget(self.remove_btn)

        self.glue_combo = QComboBox(self)
        self.glue_combo.addItem("AND", "and")
        self.glue_combo.addItem("OR", "or")
        self.glue_combo.addItem("NOT", "not")
        self.glue_combo.setFixedWidth(58)
        self.glue_combo.setToolTip(
            "On the first row, NOT selects every row that does not match; "
            "AND and OR both start from the matching rows. "
            "On later rows, AND keeps rows in both, OR keeps either, "
            "and NOT drops rows that match this criterion."
        )
        lay.addWidget(self.glue_combo)
        self.glue_combo.setVisible(show_glue)

        self.add_btn = QPushButton("Add", self)
        self.add_btn.setToolTip("Add another column query below.")
        if on_add is not None:
            self.add_btn.clicked.connect(on_add)
        lay.addWidget(self.add_btn)
        self.add_btn.setVisible(show_add)

        lay.addWidget(QLabel("Column:", self))
        self.col_combo = QComboBox(self)
        self.col_combo.setMinimumWidth(140)
        lay.addWidget(self.col_combo)

        self.query_edit = QLineEdit(self)
        self.query_edit.setPlaceholderText(_PLACEHOLDER_TEXT)
        self.query_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay.addWidget(self.query_edit, 1)

        self.partial_cb = QCheckBox("Partial Match", self)
        self.partial_cb.setChecked(True)
        self.partial_cb.setToolTip(
            "Quoted column text: substring match (and * ? wildcards). "
            "Off = the whole cell must match. Unquoted SMILES/SMARTS ignores this."
        )
        lay.addWidget(self.partial_cb)

        self.case_cb = QCheckBox("Case Sensitive", self)
        self.case_cb.setToolTip(
            "Quoted column text: letter case must match. Unquoted SMILES/SMARTS ignores this."
        )
        lay.addWidget(self.case_cb)

    def copy_options_from(self, other: SearchCriterionRow) -> None:
        """Mirror checkbox state when adding another row."""
        self.partial_cb.setChecked(other.partial_cb.isChecked())
        self.case_cb.setChecked(other.case_cb.isChecked())

    def glue(self) -> str:
        """``and``, ``or``, or ``not`` (only meaningful when the glue control is visible)."""
        data = self.glue_combo.currentData()
        return data if data in ("and", "or", "not") else "and"
