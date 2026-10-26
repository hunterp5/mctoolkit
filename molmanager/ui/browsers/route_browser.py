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

"""Browse AiZynthFinder routes: one target, then each reaction step."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem
from rdkit.Chem import Draw

from ..qt_widget_utils import make_window_minimizable, make_window_resizable
from ..strings import TOOL_RETROSYNTHESIS

_STEP_W = 680
_STEP_H = 160


class RouteBrowserDialog(QDialog):
    """Modeless list of searched targets and the reaction steps of one route."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{TOOL_RETROSYNTHESIS} routes")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumSize(760, 520)
        self._targets: list[dict] = []
        self._pixmaps: dict[tuple, QPixmap | None] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        root.addWidget(self.target_combo)

        splitter = QSplitter(Qt.Horizontal)
        self.route_list = QListWidget()
        self.route_list.setMinimumWidth(220)
        self.route_list.currentRowChanged.connect(self._show_route)
        splitter.addWidget(self.route_list)

        self._steps_host = QWidget()
        self._steps_layout = QVBoxLayout(self._steps_host)
        self._steps_layout.setContentsMargins(4, 4, 4, 4)
        self._steps_layout.setSpacing(12)
        self._steps_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._steps_host)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._empty = QLabel("Run Retrosynthesis → Search to collect routes.")
        self._empty.setWordWrap(True)
        self._steps_layout.insertWidget(0, self._empty)

        make_window_minimizable(self)
        make_window_resizable(self)

    def set_targets(self, targets: list[dict], *, focus_smiles: str = "") -> None:
        """Replace the target list. *targets* items have ``smiles`` and ``routes``."""
        self._targets = [dict(item) for item in targets if item.get("smiles")]
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        focus = 0
        for index, target in enumerate(self._targets):
            smiles = str(target.get("smiles") or "")
            n_routes = len(target.get("routes") or [])
            label = smiles if len(smiles) <= 48 else smiles[:45] + "…"
            self.target_combo.addItem(f"{label}  ({n_routes})", smiles)
            if focus_smiles and smiles == focus_smiles:
                focus = index
        self.target_combo.blockSignals(False)
        if self.target_combo.count():
            self.target_combo.setCurrentIndex(focus)
            self._on_target_changed(focus)
        else:
            self.route_list.clear()
            self._clear_steps("No routes to show.")

    def _on_target_changed(self, index: int) -> None:
        self.route_list.clear()
        target = self._target_at(index)
        routes = list(target.get("routes") or []) if target else []
        if not routes:
            self._clear_steps("This structure has no extracted routes.")
            return
        for number, route in enumerate(routes, start=1):
            solved = "solved" if route.get("solved") else "unsolved"
            score = str(route.get("score") or "").strip() or "no score"
            n_steps = len(route.get("steps") or [])
            noun = "step" if n_steps == 1 else "steps"
            item = QListWidgetItem(f"{number}. {solved}   {score}   {n_steps} {noun}")
            self.route_list.addItem(item)
        self.route_list.setCurrentRow(0)

    def _show_route(self, row: int) -> None:
        target = self._target_at(self.target_combo.currentIndex())
        routes = list(target.get("routes") or []) if target else []
        if row < 0 or row >= len(routes):
            return
        self._clear_steps("")
        steps = list(routes[row].get("steps") or [])
        if not steps:
            message = "No reaction steps."
            if routes[row].get("solved"):
                message = "No reaction steps. The target is in stock."
            self._empty.setText(message)
            self._empty.show()
            return
        self._empty.hide()
        for number, step in enumerate(steps, start=1):
            self._steps_layout.insertWidget(
                self._steps_layout.count() - 1, _StepWidget(number, step, self._pixmap_for)
            )

    def _target_at(self, index: int) -> dict | None:
        if index < 0 or index >= len(self._targets):
            return None
        return self._targets[index]

    def _clear_steps(self, message: str) -> None:
        layout = self._steps_layout
        for index in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or widget is self._empty:
                continue
            widget.setParent(None)
            widget.deleteLater()
        self._empty.setText(message)
        self._empty.setVisible(bool(message))

    def _pixmap_for(self, step: dict) -> QPixmap | None:
        product = str(step.get("product") or "")
        reactants = [
            str(item.get("smiles") or "")
            for item in step.get("reactants") or []
            if str(item.get("smiles") or "").strip()
        ]
        key = (product, tuple(reactants), _STEP_W, _STEP_H)
        if key not in self._pixmaps:
            self._pixmaps[key] = _reaction_pixmap(product, reactants, _STEP_W, _STEP_H)
        return self._pixmaps[key]


class _StepWidget(QWidget):
    """One retrosynthetic step: reaction drawing plus precursor stock labels."""

    def __init__(self, number: int, step: dict, pixmap_for) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel(f"Step {number}")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)
        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        pixmap = pixmap_for(step)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            image.setPixmap(pixmap)
        else:
            image.setText(str(step.get("product") or ""))
        root.addWidget(image)
        caption = QLabel(_precursor_text(step))
        caption.setWordWrap(True)
        caption.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(caption)


def _precursor_text(step: dict) -> str:
    parts = []
    for reactant in step.get("reactants") or []:
        smiles = str(reactant.get("smiles") or "").strip()
        if not smiles:
            continue
        state = "in stock" if reactant.get("in_stock") else "not in stock"
        parts.append(f"{smiles} ({state})")
    if not parts:
        return str(step.get("product") or "")
    return "Precursors: " + "; ".join(parts)


def _reaction_pixmap(product: str, reactants: list[str], width: int, height: int) -> QPixmap | None:
    if not product or not reactants:
        return _molecule_pixmap(product, width, height)
    smiles = ".".join(reactants) + ">>" + product
    try:
        reaction = Chem.rdChemReactions.ReactionFromSmarts(smiles, useSmiles=True)
        if reaction is None:
            return _molecule_pixmap(product, width, height)
        drawer = Draw.MolDraw2DCairo(int(width), int(height))
        drawer.DrawReaction(reaction)
        drawer.FinishDrawing()
        image = QImage.fromData(bytes(drawer.GetDrawingText()))
    except (ValueError, RuntimeError):
        return _molecule_pixmap(product, width, height)
    if image.isNull():
        return None
    return QPixmap.fromImage(image)


def _molecule_pixmap(smiles: str, width: int, height: int) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    try:
        drawer = Draw.MolDraw2DCairo(int(width), int(height))
        drawer.DrawMolecule(mol)
        drawer.FinishDrawing()
        image = QImage.fromData(bytes(drawer.GetDrawingText()))
    except (ValueError, RuntimeError):
        return None
    if image.isNull():
        return None
    return QPixmap.fromImage(image)
