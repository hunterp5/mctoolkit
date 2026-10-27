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

"""Options for an Open Reaction Database conditions search."""

from __future__ import annotations

from PyQt5.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...sources.ord_search import (
    OrdSearchError,
    OrdSearchOptions,
    build_ord_query,
    reaction_record_url,
    search_reactions,
)
from ..qt_widget_utils import make_window_resizable

_ROLES = (
    ("", "Any"),
    ("REACTANT", "Reactant"),
    ("REAGENT", "Reagent"),
    ("SOLVENT", "Solvent"),
    ("CATALYST", "Catalyst"),
)
_MATCHES = (
    ("substructure", "Substructure"),
    ("same_compound", "Same compound"),
    ("same_parent", "Same parent"),
    ("similarity", "Similar"),
)
_ORDERS = (
    ("", "Unsorted"),
    ("temperature_desc", "Highest temperature"),
    ("temperature_asc", "Lowest temperature"),
    ("yield_desc", "Highest yield"),
)


class _OrdSearchJob(QObject):
    """Carries a background search result back to the dialog."""

    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)


class _OrdSearchRunnable(QRunnable):
    """One search. *generation* drops a result that belongs to an older click."""

    def __init__(self, query: dict, job: _OrdSearchJob, generation: int, search_fn) -> None:
        super().__init__()
        self._query = query
        self._job = job
        self._generation = generation
        self._search_fn = search_fn

    def run(self) -> None:
        try:
            result = self._search_fn(self._query)
        except OrdSearchError as exc:
            self._job.failed.emit(self._generation, str(exc))
            return
        except (OSError, TypeError, ValueError, RuntimeError) as exc:
            self._job.failed.emit(self._generation, str(exc))
            return
        self._job.finished.emit(self._generation, result)


class OrdSearchDialog(QDialog):
    """Change the reaction, temperature, yield, and component filters, then search."""

    def __init__(self, reaction_smarts: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Open Reaction Database")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setObjectName("ord-search")
        self.setMinimumSize(480, 560)
        self.resize(520, 680)
        make_window_resizable(self)
        self._generation = 0
        self._pool = QThreadPool.globalInstance()
        self._search_fn = search_reactions
        self._job = _OrdSearchJob(self)
        self._job.finished.connect(self._show_result)
        self._job.failed.connect(self._show_failure)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        root.addWidget(self._reaction_group(reaction_smarts))
        root.addWidget(self._filter_group())

        buttons = QHBoxLayout()
        self.search_button = QPushButton("Search")
        self.search_button.setDefault(True)
        self.search_button.clicked.connect(self._on_search)
        self.open_button = QPushButton("Open")
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_selected)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(self.search_button)
        buttons.addWidget(self.open_button)
        buttons.addStretch(1)
        buttons.addWidget(close)
        root.addLayout(buttons)

        self.status = QLabel("Change the filters, then search.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        self.results = QTableWidget(0, 1)
        self.results.setHorizontalHeaderLabels(["Reaction"])
        self.results.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.results.setSelectionMode(QAbstractItemView.SingleSelection)
        self.results.verticalHeader().setVisible(False)
        self.results.horizontalHeader().setStretchLastSection(True)
        self.results.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.results.itemSelectionChanged.connect(self._sync_open)
        self.results.cellDoubleClicked.connect(lambda *_args: self._open_selected())
        root.addWidget(self.results, 1)

    def options(self) -> OrdSearchOptions:
        """Read the form. Raises ``ValueError`` when a number is not a number."""
        return OrdSearchOptions(
            reaction_smarts=self.reaction.toPlainText(),
            chirality=self.chirality.isChecked(),
            limit=int(self.limit.value()),
            recorded_temperature=self.recorded_temperature.isChecked(),
            min_celsius=self._optional_float(self.min_temperature, "Minimum temperature"),
            max_celsius=self._optional_float(self.max_temperature, "Maximum temperature"),
            min_yield_percent=self._optional_float(self.min_yield, "Minimum yield"),
            component_role=str(self.role.currentData() or ""),
            component_structure=self.structure.text(),
            component_match=str(self.match.currentData() or "substructure"),
            similarity=float(self.similarity.value()),
            order=str(self.order.currentData() or ""),
        )

    def query(self) -> dict:
        """The search body for the current form."""
        return build_ord_query(self.options())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._generation += 1
        super().closeEvent(event)

    def _reaction_group(self, reaction_smarts: str) -> QGroupBox:
        group = QGroupBox("Reaction")
        form = QFormLayout(group)
        form.setContentsMargins(8, 6, 8, 6)
        self.reaction = QPlainTextEdit(reaction_smarts)
        self.reaction.setTabChangesFocus(True)
        self.reaction.setFixedHeight(64)
        self.reaction.setToolTip("The reaction to look up. Atom maps are ignored.")
        form.addRow("Reaction SMARTS", self.reaction)
        self.sketch_button = QPushButton("Sketcher…")
        self.sketch_button.setToolTip(
            "Draw the reaction. Reactants go on the tail of the arrow and products on the head."
        )
        self.sketch_button.clicked.connect(self._edit_in_sketcher)
        form.addRow("", self.sketch_button)
        self.chirality = QCheckBox("Match stereochemistry")
        self.chirality.setChecked(False)
        self.chirality.setToolTip(
            "Require the stereochemistry drawn in the reaction and in a component pattern."
        )
        form.addRow("", self.chirality)
        self.limit = QSpinBox()
        self.limit.setRange(1, 1000)
        self.limit.setValue(100)
        self.limit.setToolTip(
            "How many matching reactions to list. The service caps the list at 1000."
        )
        form.addRow("Keep", self.limit)
        self.order = QComboBox()
        for value, label in _ORDERS:
            self.order.addItem(label, value)
        self.order.setToolTip("Highest yield uses the largest yield measurement on each reaction.")
        form.addRow("Sort", self.order)
        return group

    def _filter_group(self) -> QGroupBox:
        group = QGroupBox("Filters")
        form = QFormLayout(group)
        form.setContentsMargins(8, 6, 8, 6)
        self.recorded_temperature = QCheckBox("Only reactions with a recorded temperature")
        form.addRow("", self.recorded_temperature)
        self.min_temperature = QLineEdit()
        self.min_temperature.setPlaceholderText("any")
        form.addRow("Minimum temperature (°C)", self.min_temperature)
        self.max_temperature = QLineEdit()
        self.max_temperature.setPlaceholderText("any")
        form.addRow("Maximum temperature (°C)", self.max_temperature)
        self.min_yield = QLineEdit()
        self.min_yield.setPlaceholderText("any")
        form.addRow("Minimum yield (%)", self.min_yield)
        self.role = QComboBox()
        for value, label in _ROLES:
            self.role.addItem(label, value)
        form.addRow("Component role", self.role)
        self.structure = QLineEdit()
        self.structure.setPlaceholderText("SMILES or SMARTS")
        self.structure.setToolTip("Keep reactions that contain this structure in the chosen role.")
        form.addRow("Component structure", self.structure)
        self.match = QComboBox()
        for value, label in _MATCHES:
            self.match.addItem(label, value)
        self.match.setToolTip(
            "Substructure, the same compound, the same compound ignoring its salt, or a similar structure."
        )
        self.match.currentIndexChanged.connect(self._sync_similarity)
        form.addRow("Match", self.match)
        self.similarity = QDoubleSpinBox()
        self.similarity.setRange(0.05, 1.0)
        self.similarity.setSingleStep(0.05)
        self.similarity.setDecimals(2)
        self.similarity.setValue(0.70)
        form.addRow("Similarity", self.similarity)
        self._sync_similarity()
        return group

    def _edit_in_sketcher(self) -> None:
        """Open the sketcher on this reaction and keep a complete drawing."""
        from PyQt5.QtCore import QTimer
        from PyQt5.QtWidgets import QMessageBox

        try:
            from ..sketcher.dialog import SketcherDialog
        except ImportError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        sketch = SketcherDialog(self)
        sketch.setModal(True)
        sketch.setWindowModality(Qt.ApplicationModal)
        sketch.setAttribute(Qt.WA_DeleteOnClose, False)
        text = self.reaction.toPlainText().strip()
        if text:
            QTimer.singleShot(0, lambda: self._load_sketch_reaction(sketch, text))
        sketch.exec_()
        try:
            smarts = (sketch.canvas.to_reaction_smarts() or "").strip()
            drawn = bool(sketch.canvas.nodes or sketch.canvas.reaction_arrow is not None)
        except (AttributeError, RuntimeError):
            smarts = ""
            drawn = False
        sketch.deleteLater()
        if smarts:
            self.reaction.setPlainText(smarts)
            return
        if drawn:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "Draw reactants on the tail of the arrow and products on the head.",
            )

    def _load_sketch_reaction(self, sketch, text: str) -> None:
        if sketch.canvas.load_reaction_smarts(text):
            return
        sketch.show_sketch_status("The reaction SMARTS could not be drawn.")

    def _sync_similarity(self) -> None:
        self.similarity.setEnabled(self.match.currentData() == "similarity")

    def _optional_float(self, edit: QLineEdit, label: str) -> float | None:
        text = edit.text().strip()
        if not text:
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number.") from exc

    def _on_search(self) -> None:
        try:
            query = self.query()
        except ValueError as exc:
            self.status.setText(str(exc))
            return
        self._generation += 1
        generation = self._generation
        self.results.setRowCount(0)
        self.open_button.setEnabled(False)
        self.search_button.setEnabled(False)
        self.status.setText("Searching…")
        self._pool.start(_OrdSearchRunnable(query, self._job, generation, self._search_fn))

    def _show_result(self, generation: int, result) -> None:
        if generation != self._generation:
            return
        self.search_button.setEnabled(True)
        ids = list(result.reaction_ids)
        self.results.setRowCount(len(ids))
        for row, reaction_id in enumerate(ids):
            item = QTableWidgetItem(reaction_id)
            item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            item.setToolTip(reaction_record_url(reaction_id))
            self.results.setItem(row, 0, item)
        if not ids:
            self.status.setText("No reactions matched.")
            return
        message = f"{len(ids)} reactions."
        if result.truncated:
            message = f"{len(ids)} reactions. The list is capped."
        self.status.setText(message)

    def _show_failure(self, generation: int, message: str) -> None:
        if generation != self._generation:
            return
        self.search_button.setEnabled(True)
        self.status.setText(message)

    def _sync_open(self) -> None:
        self.open_button.setEnabled(self.results.currentRow() >= 0)

    def _open_selected(self) -> None:
        row = self.results.currentRow()
        item = self.results.item(row, 0) if row >= 0 else None
        if item is None or not item.text().strip():
            return
        QDesktopServices.openUrl(QUrl(reaction_record_url(item.text().strip())))
