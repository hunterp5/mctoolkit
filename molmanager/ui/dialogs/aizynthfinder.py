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

"""Chemistry → Retrosynthesis → Search."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...predictions.aizynthfinder_run import (
    OUTPUT_COLUMNS,
    ready_message,
    resolve_config,
    resolve_python,
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
        self.setMinimumWidth(460)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_lyt = QVBoxLayout(structures)
        struct_lyt.setContentsMargins(8, 6, 8, 6)
        attach_structure_input(self, struct_lyt, selected_row_count=n_sel)
        root.addWidget(structures)

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
                "Choose the AiZynthFinder config.yml from download_public_data.",
            )
            return
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
            )

        enqueue_process_queue_job(
            app,
            TOOL_RETROSYNTHESIS,
            n,
            _make_worker,
            queue_label=f"{TOOL_RETROSYNTHESIS} ({n} molecules)",
        )
        self.close()
