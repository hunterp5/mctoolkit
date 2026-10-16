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
    'Match this column: e.g. >10, "eth*", NOT blank. Quote string text ("like this") so '
    "&, |, and comma are not treated as operators. Press Enter to search."
)
_PLACEHOLDER_SUBSTRUCTURE = (
    "Substructure (SMILES/SMARTS), e.g. c1ccccc1, [F,Cl], [!C;R], or [M]. "
    "Daylight logic inside [] / bonds (! & , ;) is kept. "
    "Search OR = | or comma between patterns; AND = &. Prefix NOT, !, or - to exclude. Press Enter."
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
            "Combine this criterion with the rows above. "
            "AND keeps rows in both, OR keeps either, NOT drops rows that match this criterion."
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

        self.partial_cb = QCheckBox("Partial match", self)
        self.partial_cb.setChecked(True)
        self.partial_cb.setToolTip(
            "Substring match (and * ? wildcards). Off = whole cell must match."
        )
        lay.addWidget(self.partial_cb)

        self.case_cb = QCheckBox("Case Sensitive", self)
        self.case_cb.setToolTip("When on, letter case must match.")
        lay.addWidget(self.case_cb)

        self.substructure_cb = QCheckBox("Substructure", self)
        self.substructure_cb.setToolTip(
            "Match structures with SMARTS/SMILES instead of column text."
        )
        self.substructure_cb.toggled.connect(self._on_substructure_toggled)
        lay.addWidget(self.substructure_cb)

    def _on_substructure_toggled(self, on: bool) -> None:
        self.partial_cb.setEnabled(not on)
        self.case_cb.setEnabled(not on)
        self.query_edit.setPlaceholderText(_PLACEHOLDER_SUBSTRUCTURE if on else _PLACEHOLDER_TEXT)

    def copy_options_from(self, other: SearchCriterionRow) -> None:
        """Mirror checkbox state when adding another row."""
        self.partial_cb.setChecked(other.partial_cb.isChecked())
        self.case_cb.setChecked(other.case_cb.isChecked())
        self.substructure_cb.setChecked(other.substructure_cb.isChecked())

    def glue(self) -> str:
        """``and``, ``or``, or ``not`` (only meaningful when the glue control is visible)."""
        data = self.glue_combo.currentData()
        return data if data in ("and", "or", "not") else "and"
