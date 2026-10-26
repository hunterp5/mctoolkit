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

"""Choose one bioisostere product for the atoms selected on the sketch."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from ...chem.bioisosteres import CATEGORY_LABELS, Bioisostere


class BioisostereReplacementDialog(QDialog):
    """Lists transforms that touch the selection, then the product of the chosen one."""

    def __init__(
        self,
        options: tuple[tuple[Bioisostere, tuple[str, ...]], ...],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Bioisosteric Replacement")
        self.setModal(True)
        self._options = options

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Replacement"))
        self._transforms = QListWidget(self)
        self._transforms.currentRowChanged.connect(self._show_products)
        root.addWidget(self._transforms, 1)

        root.addWidget(QLabel("Product"))
        self._products = QListWidget(self)
        self._products.itemDoubleClicked.connect(lambda *_args: self.accept())
        root.addWidget(self._products, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        buttons.button(QDialogButtonBox.Ok).setText("Replace")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        for row, products in options:
            category = CATEGORY_LABELS.get(row.category, row.category)
            item = QListWidgetItem(f"{category} — {row.name}")
            item.setToolTip(row.summary)
            item.setData(Qt.UserRole, products)
            self._transforms.addItem(item)
        if self._transforms.count():
            self._transforms.setCurrentRow(0)
        self.resize(520, 420)

    def _show_products(self, row: int) -> None:
        self._products.clear()
        item = self._transforms.item(row)
        products = () if item is None else item.data(Qt.UserRole) or ()
        for smiles in products:
            self._products.addItem(QListWidgetItem(str(smiles)))
        if self._products.count():
            self._products.setCurrentRow(0)

    def chosen_smiles(self) -> str:
        item = self._products.currentItem()
        if item is None:
            return ""
        return item.text().strip()
