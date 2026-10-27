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

"""Choose bioisostere products to add to the Design Studio list."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from ...chem.bioisosteres import CATEGORY_LABELS, Bioisostere


class BioisostereReplacementDialog(QDialog):
    """Classes collapse to their replacements. Selecting a class lists every product."""

    def __init__(
        self,
        options: tuple[tuple[Bioisostere, tuple[str, ...]], ...],
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Bioisosteric Replacement")
        self.setModal(True)
        self._only_current = False

        root = QVBoxLayout(self)
        root.addWidget(QLabel("Replacement"))
        self._transforms = QTreeWidget(self)
        self._transforms.setHeaderHidden(True)
        self._transforms.setRootIsDecorated(True)
        self._transforms.currentItemChanged.connect(self._show_products)
        root.addWidget(self._transforms, 1)

        root.addWidget(QLabel("Product"))
        self._products = QListWidget(self)
        self._products.itemDoubleClicked.connect(self._accept_current)
        root.addWidget(self._products, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, self)
        add_button = buttons.button(QDialogButtonBox.Ok)
        add_button.setText("Add to design list")
        add_button.setToolTip(
            "Add every product listed for the selected class or replacement. "
            "Double-click one product to add only that product."
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self._fill_classes(options)
        if self._transforms.topLevelItemCount():
            self._transforms.setCurrentItem(self._transforms.topLevelItem(0))
        self.resize(520, 480)

    def _fill_classes(
        self,
        options: tuple[tuple[Bioisostere, tuple[str, ...]], ...],
    ) -> None:
        grouped: dict[str, list[tuple[Bioisostere, tuple[str, ...]]]] = {
            key: [] for key in CATEGORY_LABELS
        }
        for row, products in options:
            grouped.setdefault(row.category, []).append((row, products))
        order = list(CATEGORY_LABELS)
        for key in grouped:
            if key not in order:
                order.append(key)
        for key in order:
            rows = grouped.get(key) or []
            if not rows:
                continue
            label = CATEGORY_LABELS.get(key, key)
            noun = "replacement" if len(rows) == 1 else "replacements"
            parent = QTreeWidgetItem([f"{label} ({len(rows)} {noun})"])
            parent.setToolTip(0, "Every replacement in this class that matches the selection.")
            parent.setFlags(parent.flags() | Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            for row, products in rows:
                child = QTreeWidgetItem([row.name])
                child.setToolTip(0, row.summary)
                child.setData(0, Qt.UserRole, products)
                parent.addChild(child)
            parent.setExpanded(False)
            self._transforms.addTopLevelItem(parent)

    def _show_products(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        self._products.clear()
        if current is None:
            return
        if current.parent() is None:
            sources = [current.child(index) for index in range(current.childCount())]
            show_name = True
        else:
            sources = [current]
            show_name = False
        seen: dict[str, list[str]] = {}
        order: list[str] = []
        for source in sources:
            name = source.text(0)
            for smiles in _stored_smiles(source):
                if smiles in seen:
                    if name not in seen[smiles]:
                        seen[smiles].append(name)
                    continue
                seen[smiles] = [name]
                order.append(smiles)
        for smiles in order:
            names = seen[smiles]
            text = f"{', '.join(names)} — {smiles}" if show_name else smiles
            item = QListWidgetItem(text)
            item.setData(Qt.UserRole, smiles)
            item.setData(Qt.UserRole + 1, ", ".join(names))
            item.setToolTip(smiles)
            self._products.addItem(item)
        if self._products.count():
            self._products.setCurrentRow(0)

    def _accept_current(self, *_args) -> None:
        self._only_current = True
        self.accept()

    def designs_to_add(self) -> list[tuple[str, str]]:
        """``(replacement name, SMILES)`` for the products this dialog should add."""
        if self._only_current:
            pair = _product_pair(self._products.currentItem())
            return [pair] if pair is not None else []
        found: list[tuple[str, str]] = []
        seen: set[str] = set()
        for index in range(self._products.count()):
            pair = _product_pair(self._products.item(index))
            if pair is None or pair[1] in seen:
                continue
            seen.add(pair[1])
            found.append(pair)
        return found

    def chosen_smiles(self) -> str:
        item = self._products.currentItem()
        if item is None:
            return ""
        stored = item.data(Qt.UserRole)
        if isinstance(stored, str) and stored.strip():
            return stored.strip()
        return ""


def _product_pair(item: QListWidgetItem | None) -> tuple[str, str] | None:
    if item is None:
        return None
    smiles = item.data(Qt.UserRole)
    name = item.data(Qt.UserRole + 1)
    if not isinstance(smiles, str) or not smiles.strip():
        return None
    title = name.strip() if isinstance(name, str) and name.strip() else smiles.strip()
    return title, smiles.strip()


def _stored_smiles(item: QTreeWidgetItem) -> tuple[str, ...]:
    raw = item.data(0, Qt.UserRole)
    if not raw:
        return ()
    return tuple(str(smiles) for smiles in raw if str(smiles).strip())
