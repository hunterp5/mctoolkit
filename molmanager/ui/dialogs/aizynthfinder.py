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

"""Chemistry → Reaction → Retrosynthesis → Search."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...predictions.aizynthfinder_run import (
    OUTPUT_COLUMNS,
    _ALGORITHMS,
    SearchOptions,
    config_catalog,
    load_search_options,
    ready_message,
    resolve_config,
    resolve_python,
    save_search_options,
)
from ...workers.aizynthfinder_worker import AizynthFinderWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_RETROSYNTHESIS
from .structure_input import attach_structure_input


class AizynthFinderDialog(QDialog):
    """Queue a local AiZynthFinder search for table rows or one SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_RETROSYNTHESIS)
        self.setMinimumWidth(520)
        self.setMinimumHeight(560)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_lyt = QVBoxLayout(structures)
        struct_lyt.setContentsMargins(8, 6, 8, 6)
        attach_structure_input(self, struct_lyt, selected_row_count=n_sel)
        root.addWidget(structures)

        saved = load_search_options()
        catalog = _read_catalog()
        self._policy_boxes = _checkboxes(catalog["expansion"], saved.policies)
        self._filter_boxes = _checkboxes(catalog["filter"], saved.filters)
        self._stock_boxes = _checkboxes(catalog["stock"], saved.stocks)

        options = QWidget()
        options_layout = QVBoxLayout(options)
        options_layout.setContentsMargins(0, 0, 0, 0)
        options_layout.setSpacing(8)
        options_layout.addWidget(self._model_box())
        options_layout.addWidget(self._search_box(saved))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(options)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        search = QPushButton("Search")
        search.setDefault(True)
        search.clicked.connect(self._on_search)
        buttons.addWidget(search)
        root.addLayout(buttons)

        self._structure_input.refresh_sources(parent)
        self.adjustSize()
        make_window_minimizable(self)

    def _on_search(self) -> None:
        problem = ready_message()
        if problem:
            QMessageBox.warning(self, TOOL_RETROSYNTHESIS, problem)
            return
        if self.parent_app is None:
            return
        payloads = self._structure_input.collect_payloads(self, TOOL_RETROSYNTHESIS)
        if payloads is None:
            return
        payloads = self.parent_app._filter_rows_for_resume(payloads, OUTPUT_COLUMNS)
        if not payloads:
            QMessageBox.information(
                self,
                TOOL_RETROSYNTHESIS,
                "No valid structures were found for this scope and source.",
            )
            return
        python = resolve_python()
        config = resolve_config()
        if config is None:
            QMessageBox.warning(
                self,
                TOOL_RETROSYNTHESIS,
                "Choose the AiZynthFinder config.yml. Settings → Configure → AiZynthFinder "
                "→ Download… writes one next to the model files.",
            )
            return
        options = self._search_options()
        if not options.policies:
            QMessageBox.warning(self, TOOL_RETROSYNTHESIS, "Select at least one expansion policy.")
            return
        save_search_options(options)
        signals = self.parent_app._ensure_aizynthfinder_signals()
        n = len(payloads)
        config_text = str(config)
        app = self.parent_app

        def _make_worker(cancel_event, progress_state):
            return AizynthFinderWorker(
                payloads,
                python,
                config_text,
                app.signals,
                signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
                options=options,
            )

        enqueue_process_queue_job(
            app,
            TOOL_RETROSYNTHESIS,
            n,
            _make_worker,
            queue_label=f"{TOOL_RETROSYNTHESIS} ({n} molecules)",
        )
        self.close()

    def _model_box(self) -> QGroupBox:
        box = QGroupBox("Models")
        box.setObjectName("aizynth-models")
        box.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        form = QFormLayout(box)
        form.setContentsMargins(8, 4, 8, 4)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(2)
        form.setLabelAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        policies = (
            _checkbox_row(self._policy_boxes)
            if self._policy_boxes
            else QLabel("No expansion policies in config.yml.")
        )
        form.addRow("Policies", policies)
        if self._filter_boxes:
            form.addRow("Filters", _checkbox_row(self._filter_boxes))
        if self._stock_boxes:
            form.addRow("Stocks", _checkbox_row(self._stock_boxes))
        return box

    def _search_box(self, saved: SearchOptions) -> QGroupBox:
        box = QGroupBox("Search")
        form = QFormLayout(box)
        form.setContentsMargins(8, 6, 8, 6)
        self.time_minutes = QSpinBox()
        self.time_minutes.setRange(1, 120)
        self.time_minutes.setValue(max(1, int(saved.time_limit) // 60))
        self.time_minutes.setSuffix(" min")
        form.addRow("Time limit", self.time_minutes)
        self.iteration_limit = QSpinBox()
        self.iteration_limit.setRange(1, 5000)
        self.iteration_limit.setValue(saved.iteration_limit)
        form.addRow("Iterations", self.iteration_limit)
        self.max_transforms = QSpinBox()
        self.max_transforms.setRange(1, 20)
        self.max_transforms.setValue(saved.max_transforms)
        form.addRow("Maximum reactions", self.max_transforms)
        self.max_routes = QSpinBox()
        self.max_routes.setRange(1, 100)
        self.max_routes.setValue(saved.max_routes)
        form.addRow("Routes to keep", self.max_routes)
        self.exploration = QDoubleSpinBox()
        self.exploration.setRange(0.1, 5.0)
        self.exploration.setSingleStep(0.1)
        self.exploration.setDecimals(1)
        self.exploration.setValue(saved.exploration)
        form.addRow("Exploration (C)", self.exploration)
        self.algorithm = QComboBox()
        for label, value in _ALGORITHMS:
            self.algorithm.addItem(label, value)
        index = self.algorithm.findData(saved.algorithm)
        if index >= 0:
            self.algorithm.setCurrentIndex(index)
        form.addRow("Algorithm", self.algorithm)
        self.try_all = QCheckBox("Try all algorithms")
        self.try_all.setToolTip(
            "Run Monte Carlo, Retro*, breadth-first, and proof number in one search, "
            "then keep the distinct routes. Each algorithm uses the full time limit."
        )
        self.try_all.setChecked(saved.all_algorithms)
        self.try_all.toggled.connect(self._on_try_all)
        form.addRow(self.try_all)
        self.return_first = QCheckBox("Stop at the first solved route")
        self.return_first.setChecked(saved.return_first)
        form.addRow(self.return_first)
        self.exclude_target = QCheckBox("Do not count the target as a stock hit")
        self.exclude_target.setChecked(saved.exclude_target_from_stock)
        form.addRow(self.exclude_target)
        self.cluster = QCheckBox("Cluster similar routes")
        self.cluster.setChecked(saved.cluster)
        form.addRow(self.cluster)
        self._on_try_all(self.try_all.isChecked())
        return box

    def _on_try_all(self, checked: bool) -> None:
        self.algorithm.setEnabled(not checked)
        self.cluster.setEnabled(not checked)

    def _search_options(self) -> SearchOptions:
        return SearchOptions(
            policies=_checked(self._policy_boxes),
            filters=_checked(self._filter_boxes),
            stocks=_checked(self._stock_boxes),
            algorithm=str(self.algorithm.currentData() or "mcts"),
            exploration=float(self.exploration.value()),
            max_transforms=int(self.max_transforms.value()),
            iteration_limit=int(self.iteration_limit.value()),
            time_limit=int(self.time_minutes.value()) * 60,
            return_first=self.return_first.isChecked(),
            exclude_target_from_stock=self.exclude_target.isChecked(),
            max_routes=int(self.max_routes.value()),
            cluster=self.cluster.isChecked(),
            all_algorithms=self.try_all.isChecked(),
        )


def _read_catalog() -> dict[str, list[str]]:
    config = resolve_config()
    if config is None:
        return {"expansion": [], "filter": [], "stock": []}
    try:
        text = config.read_text(encoding="utf-8")
    except OSError:
        return {"expansion": [], "filter": [], "stock": []}
    return config_catalog(text)


def _checkbox_row(boxes: list[QCheckBox]) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(16)
    for box in boxes:
        layout.addWidget(box)
    layout.addStretch(1)
    return row


def _checkboxes(names: list[str], saved: tuple[str, ...]) -> list[QCheckBox]:
    chosen = set(saved)
    use_saved = bool(chosen & set(names))
    boxes: list[QCheckBox] = []
    for name in names:
        box = QCheckBox(name)
        box.setChecked(name in chosen if use_saved else True)
        boxes.append(box)
    return boxes


def _checked(boxes: list[QCheckBox]) -> tuple[str, ...]:
    return tuple(box.text() for box in boxes if box.isChecked())
