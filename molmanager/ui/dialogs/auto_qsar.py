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

"""Quick QSAR — search features and models for an activity column (Data menu)."""

from __future__ import annotations

import pickle
from contextlib import suppress
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...analysis.auto_qsar import (
    format_model_details,
    load_auto_qsar_model,
    output_headers,
    save_auto_qsar_model,
    table_write_rows,
)
from ...workers.auto_qsar_worker import (
    AutoQSARJobResult,
    AutoQSARPredictWorker,
    AutoQSARSearchWorker,
    AutoQSARSignals,
)
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..table_dataframe import numeric_subset, table_to_dataframe
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked

# Enough checked-column rows to scan a typical descriptor set; longer lists scroll inside the box.
_COLUMN_LIST_ROWS = 8
_MODEL_FILE_FILTER = "Quick QSAR model (*.mmqsar)"

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


class AutoQSARDialog(QDialog):
    """Pick an activity column and task. Quick QSAR chooses the features and model."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_state(parent)
        self._build_ui()
        self._wire_ui()
        self._reload_columns()

    def _init_state(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.setWindowTitle("Quick QSAR")
        self.setMinimumSize(760, 560)
        self.resize(960, 680)
        make_window_minimizable(self)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._job: AutoQSARJobResult | None = None
        self._structure_source = ""
        self._job_running = False
        self._active_progress_label = "Quick QSAR"
        self._active_job_id: str | None = None
        self._auto_pred_name = ""
        self._signals = AutoQSARSignals(self)

    def _build_ui(self) -> None:
        n_sel = self._initial_selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_host = QWidget()
        left_lyt = QVBoxLayout(left_host)
        left_lyt.setSpacing(8)

        scope = QHBoxLayout()
        self.chk_visible = QCheckBox("Visible Rows Only")
        self.chk_visible.setChecked(True)
        scope.addWidget(self.chk_visible)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        scope.addWidget(self.only_selected_cb)
        scope.addStretch()
        self.btn_refresh = QPushButton("Refresh columns")
        scope.addWidget(self.btn_refresh)
        left_lyt.addLayout(scope)

        data_grp = QGroupBox("Activity (Y)")
        data_form = QFormLayout(data_grp)
        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(200)
        data_form.addRow("Column:", self.activity_combo)
        self.task_combo = QComboBox()
        self.task_combo.addItems(["Auto", "Regression", "Classification"])
        self.task_combo.setToolTip(
            "Auto picks classification when activity has few discrete values; otherwise regression."
        )
        data_form.addRow("Task:", self.task_combo)
        left_lyt.addWidget(data_grp)

        search_grp = QGroupBox("Search")
        search_form = QFormLayout(search_grp)
        self.struct_src_combo = QComboBox()
        search_form.addRow("Structure:", self.struct_src_combo)
        left_lyt.addWidget(search_grp)

        columns_grp = QGroupBox("Table columns")
        columns_lyt = QVBoxLayout(columns_grp)
        self.column_list = QListWidget()
        self.column_list.setSelectionMode(QListWidget.NoSelection)
        self.column_list.setToolTip(
            "Checked columns are added to the calculated descriptors. "
            "Activity is skipped. Leave a column unchecked to keep it out."
        )
        columns_lyt.addWidget(self.column_list)
        left_lyt.addWidget(columns_grp)

        out_grp = QGroupBox("Output")
        out_form = QFormLayout(out_grp)
        self.pred_column_edit = QLineEdit()
        self.pred_column_edit.setPlaceholderText("Quick QSAR_<activity column>")
        out_form.addRow("Prediction column:", self.pred_column_edit)
        self.chk_consensus = QCheckBox("Consensus of retained models")
        self.chk_consensus.setChecked(True)
        self.chk_consensus.setToolTip(
            "Average the retained models. Uncheck to predict with the selected leaderboard row."
        )
        out_form.addRow(self.chk_consensus)
        left_lyt.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run Quick QSAR")
        btn_row.addWidget(self.run_btn)
        self.predict_btn = QPushButton("Add predictions to table")
        self.predict_btn.setEnabled(False)
        self.predict_btn.setToolTip(
            "Score the visible rows, including rows that were not in the learning set. "
            "Uncheck consensus to use the selected model."
        )
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        left_lyt.addLayout(btn_row)
        left_lyt.addStretch()

        left_scroll.setWidget(left_host)
        splitter.addWidget(left_scroll)

        right = QWidget()
        right_lyt = QVBoxLayout(right)
        right_lyt.setContentsMargins(0, 0, 0, 0)
        board_row = QHBoxLayout()
        board_row.addWidget(QLabel("Leaderboard"))
        board_row.addStretch()
        self.load_btn = QPushButton("Load model…")
        self.load_btn.setToolTip(
            "Load a saved model, then use Add predictions to score this table."
        )
        board_row.addWidget(self.load_btn)
        self.save_btn = QPushButton("Save model…")
        self.save_btn.setEnabled(False)
        self.save_btn.setToolTip(
            "Save the selected leaderboard model to a file that can be applied to a dataset later."
        )
        board_row.addWidget(self.save_btn)
        right_lyt.addLayout(board_row)
        self.leaderboard = QTableWidget(0, 6)
        self.leaderboard.setHorizontalHeaderLabels(
            ["Score", "Test accuracy", "Train accuracy", "Method", "Features", "Split"]
        )
        features_header = self.leaderboard.horizontalHeaderItem(4)
        if features_header is not None:
            features_header.setToolTip("Number of features in the model.")
        self.leaderboard.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.leaderboard.setSelectionMode(QAbstractItemView.SingleSelection)
        self.leaderboard.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.leaderboard.verticalHeader().setVisible(False)
        self.leaderboard.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.leaderboard.setMinimumHeight(160)
        right_lyt.addWidget(self.leaderboard)
        right_lyt.addWidget(QLabel("Results"))
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.results_text)
        self.results_text.setPlaceholderText(
            "Choose an activity column and task, then click Run Quick QSAR.\n\n"
            "Click a leaderboard row to see that model's score and the features it uses. "
            "Save model writes the selected model to a file you can load and apply later.\n\n"
            "Add predictions writes the prediction, a 90% interval or class probability, "
            "and an in/out domain flag. Calculated descriptors stay out of the table."
        )
        right_lyt.addWidget(self.results_text, 1)
        splitter.addWidget(right)
        splitter.setSizes([420, 540])

    def _wire_ui(self) -> None:
        self._signals.search_finished.connect(self._on_search_finished, Qt.QueuedConnection)
        self._signals.predict_finished.connect(self._on_predict_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)
        self.chk_visible.stateChanged.connect(self._reload_columns)
        self.only_selected_cb.stateChanged.connect(self._reload_columns)
        self.btn_refresh.clicked.connect(self._reload_columns)
        self.activity_combo.currentIndexChanged.connect(self._on_activity_changed)
        self.run_btn.clicked.connect(self._on_run)
        self.predict_btn.clicked.connect(self._on_predict)
        self.save_btn.clicked.connect(self._on_save_model)
        self.load_btn.clicked.connect(self._on_load_model)
        self.leaderboard.itemSelectionChanged.connect(self._on_leaderboard_selection)

    def _scoped_dataframe_and_oids(self) -> tuple:
        app = self.parent_app
        assert app is not None
        df, source_rows = table_to_dataframe(
            app,
            visible_only=self.chk_visible.isChecked(),
            only_selected=selection_scope_checked(self),
        )
        oids: list[int] = []
        for row in source_rows:
            text = app._table_model.cell_text(row, 0)
            oids.append(int(text) if text.isdigit() else int(row))
        return df, oids

    def _reload_columns(self) -> None:
        previously_checked = {
            self.column_list.item(index).text()
            for index in range(self.column_list.count())
            if self.column_list.item(index).checkState() == Qt.Checked
        }
        prev = self.activity_combo.currentText().strip()
        self.activity_combo.blockSignals(True)
        self.activity_combo.clear()
        self.column_list.clear()
        if self.parent_app is not None:
            self.struct_src_combo.clear()
            self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())
            df, _oids = self._scoped_dataframe_and_oids()
            for column in numeric_subset(df, exclude_id=True).columns:
                name = str(column)
                self.activity_combo.addItem(name)
                item = QListWidgetItem(name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked if name in previously_checked else Qt.Unchecked)
                self.column_list.addItem(item)
        self._size_column_list()
        if self.activity_combo.count():
            if prev:
                idx = self.activity_combo.findText(prev)
                self.activity_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                select_preferred_activity_column(self.activity_combo)
        self.activity_combo.blockSignals(False)
        self._on_activity_changed()

    def _size_column_list(self) -> None:
        """Show several column rows; extra columns scroll inside the list."""
        row_height = self.column_list.sizeHintForRow(0) if self.column_list.count() else 0
        if row_height <= 0:
            row_height = 22
        self.column_list.setFixedHeight(_COLUMN_LIST_ROWS * row_height + 8)

    def _selected_table_columns(self) -> list[str]:
        activity = self.activity_combo.currentText().strip()
        chosen: list[str] = []
        for index in range(self.column_list.count()):
            item = self.column_list.item(index)
            if item is None or item.text() == activity:
                continue
            if item.checkState() == Qt.Checked:
                chosen.append(item.text())
        return chosen

    def _task_mode_key(self) -> str:
        text = self.task_combo.currentText().strip().lower()
        if text == "regression":
            return "regression"
        if text == "classification":
            return "classification"
        return "auto"

    def _on_activity_changed(self, *_args) -> None:
        activity = self.activity_combo.currentText().strip()
        if not activity:
            return
        suggested = f"Quick QSAR_{activity}"
        current = self.pred_column_edit.text().strip()
        if not current or current == self._auto_pred_name:
            self.pred_column_edit.setText(suggested)
        self._auto_pred_name = suggested
        for index in range(self.column_list.count()):
            item = self.column_list.item(index)
            if item is not None and item.text() == activity:
                item.setCheckState(Qt.Unchecked)

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.run_btn.setEnabled(not running)
        self.load_btn.setEnabled(not running)
        ready = not running and self._job is not None and bool(self._job.search.models)
        self.predict_btn.setEnabled(ready)
        self.save_btn.setEnabled(ready and self.leaderboard.currentRow() >= 0)

    def _on_run(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        activity = self.activity_combo.currentText().strip()
        if not activity:
            QMessageBox.warning(self, "Quick QSAR", "Select an activity column (Y).")
            return
        df, oids = self._scoped_dataframe_and_oids()
        if len(oids) < 8:
            QMessageBox.information(
                self,
                "Quick QSAR",
                "Need at least 8 rows in the current scope.",
            )
            return
        source = self.struct_src_combo.currentText()
        payloads = None
        if source:
            payloads = self.parent_app.collect_scoped_table_structure_payloads(
                source,
                only_selected=selection_scope_checked(self),
                only_visible=self.chk_visible.isChecked(),
            )
        pred_col = self.pred_column_edit.text().strip() or f"Quick QSAR_{activity}"
        self.pred_column_edit.setText(pred_col)
        params = {
            "dataframe": df,
            "oids": oids,
            "activity_column": activity,
            "task_mode": self._task_mode_key(),
            "effort": "standard",
            "mol_payloads": payloads,
            "prediction_column": pred_col,
            "table_columns": self._selected_table_columns(),
        }
        self._structure_source = source
        self._job = None
        self.leaderboard.setRowCount(0)
        self.results_text.setPlainText("Searching…")
        self._active_progress_label = "Quick QSAR"
        self._set_job_running(True)
        self._disconnect_thread_finished()
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            "Quick QSAR",
            len(oids),
            lambda ev, ps, p=params, sigs=self._signals: AutoQSARSearchWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"Quick QSAR ({len(oids)} rows)",
        )
        self.parent_app.process_queue.thread_finished.connect(self._on_thread_finished)

    def _prediction_dataframe_and_oids(self) -> tuple:
        app = self.parent_app
        assert app is not None
        df, source_rows = table_to_dataframe(
            app,
            visible_only=self.chk_visible.isChecked(),
            only_selected=False,
        )
        oids: list[int] = []
        for row in source_rows:
            text = app._table_model.cell_text(row, 0)
            oids.append(int(text) if text.isdigit() else int(row))
        return df, oids

    def _selected_model_index(self) -> int | None:
        if self.chk_consensus.isChecked():
            return None
        row = self.leaderboard.currentRow()
        return 0 if row < 0 else int(row)

    def _on_predict(self) -> None:
        if self._job_running or self._job is None or self.parent_app is None:
            return
        out_col = (
            self.pred_column_edit.text().strip() or f"Quick QSAR_{self._job.search.activity_column}"
        )
        if self._prediction_needs_structure() and not self._structure_source:
            QMessageBox.warning(
                self,
                "Quick QSAR",
                "Choose a structure source. This model uses calculated descriptors or fingerprints.",
            )
            return
        df, oids = self._prediction_dataframe_and_oids()
        headers = output_headers(out_col, self._job.search.task)
        payloads = None
        if self._structure_source:
            payloads = self.parent_app.collect_scoped_table_structure_payloads(
                self._structure_source,
                only_selected=False,
                only_visible=self.chk_visible.isChecked(),
            )
        kept = self.parent_app._filter_rows_for_resume([(int(oid),) for oid in oids], headers)
        if len(kept) != len(oids):
            keep = {int(row[0]) for row in kept}
            mask = [i for i, oid in enumerate(oids) if int(oid) in keep]
            df = df.iloc[mask].reset_index(drop=True)
            oids = [oids[i] for i in mask]
        if not oids:
            QMessageBox.information(self, "Quick QSAR", "No visible rows to score.")
            return
        params = {
            "search": self._job.search,
            "dataframe": df,
            "oids": oids,
            "mol_payloads": payloads,
            "output_column": out_col,
            "model_index": self._selected_model_index(),
        }
        self._active_progress_label = "Quick QSAR predictions"
        self._set_job_running(True)
        self._disconnect_thread_finished()
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            "Quick QSAR predictions",
            len(oids),
            lambda ev, ps, p=params, sigs=self._signals: AutoQSARPredictWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"Quick QSAR predict ({len(oids)} rows)",
        )
        self.parent_app.process_queue.thread_finished.connect(self._on_thread_finished)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_thread_finished()
        super().closeEvent(event)

    def _disconnect_thread_finished(self) -> None:
        app = self.parent_app
        if app is None:
            return
        with suppress(TypeError):
            app.process_queue.thread_finished.disconnect(self._on_thread_finished)

    def _on_thread_finished(self, job_id: str) -> None:
        if job_id != self._active_job_id or not self._job_running:
            return
        self._active_job_id = None
        self._reset_after_failure("Cancelled.")

    def _reset_after_failure(self, message: str) -> None:
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(self._active_progress_label)
        self._set_job_running(False)
        self._disconnect_thread_finished()
        if message and message != "Cancelled.":
            self.results_text.append(f"\n\nError: {message}")
        if message:
            QMessageBox.warning(self, "Quick QSAR", message)

    def _on_search_finished(self, result: object) -> None:
        self._active_job_id = None
        self._disconnect_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("Quick QSAR", status_message=None)
        if not isinstance(result, AutoQSARJobResult):
            self._set_job_running(False)
            return
        self._job = result
        self._fill_leaderboard(result)
        self._set_job_running(False)
        best = result.search.models[0] if result.search.models else None
        if self.parent_app is not None and best is not None:
            count = len(result.search.models)
            self.parent_app.status_label.setText(
                f"Quick QSAR: consensus of {count} models. "
                f"Best score {best.score:.3f} "
                f"({best.method_label}, {best.feature_set}, {best.n_features} features)."
            )

    def _fill_leaderboard(self, result: AutoQSARJobResult) -> None:
        models = result.search.models
        self.leaderboard.setRowCount(len(models))
        for row, model in enumerate(models):
            values = (
                f"{model.score:.4f}",
                f"{model.test_accuracy:.4f}",
                f"{model.train_accuracy:.4f}",
                model.method_label,
                str(len(model.feature_names)),
                str(model.split_index + 1),
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col in {0, 1, 2, 4, 5}:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.leaderboard.setItem(row, col, item)
        if models:
            self.leaderboard.selectRow(0)
        self.leaderboard.resizeColumnsToContents()
        self.leaderboard.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self._show_selected_model()

    def _on_leaderboard_selection(self) -> None:
        self._show_selected_model()
        if not self._job_running:
            ready = self._job is not None and bool(self._job.search.models)
            self.save_btn.setEnabled(ready and self.leaderboard.currentRow() >= 0)

    def _show_selected_model(self) -> None:
        job = self._job
        if job is None or not job.search.models:
            return
        row = self.leaderboard.currentRow()
        if row < 0 or row >= len(job.search.models):
            return
        self.results_text.setPlainText(format_model_details(job.search, row))

    def _prediction_needs_structure(self) -> bool:
        job = self._job
        if job is None or not job.search.models:
            return False
        index = self._selected_model_index()
        if index is None:
            models = job.search.models
        elif 0 <= index < len(job.search.models):
            models = (job.search.models[index],)
        else:
            return False
        for model in models:
            block = job.search.blocks.get(model.feature_set)
            if block is not None and block.requires_structure:
                return True
        return False

    def _on_save_model(self) -> None:
        if self._job_running or self._job is None or not self._job.search.models:
            return
        row = self.leaderboard.currentRow()
        if row < 0:
            QMessageBox.information(self, "Quick QSAR", "Select a leaderboard model to save.")
            return
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Save Quick QSAR model",
            "",
            _MODEL_FILE_FILTER,
        )
        if not path:
            return
        if not path.lower().endswith(".mmqsar"):
            path = f"{path}.mmqsar"
        try:
            save_auto_qsar_model(path, self._job.search, row)
        except (OSError, ValueError, TypeError, pickle.PicklingError) as exc:
            QMessageBox.warning(self, "Quick QSAR", str(exc) or "Could not save the model.")
            return
        if self.parent_app is not None:
            self.parent_app.status_label.setText(f"Quick QSAR: saved model to {path}.")

    def _on_load_model(self) -> None:
        if self._job_running:
            return
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Load Quick QSAR model",
            "",
            _MODEL_FILE_FILTER,
        )
        if not path:
            return
        try:
            loaded = load_auto_qsar_model(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Quick QSAR", str(exc) or "Could not load the model.")
            return
        self._job = AutoQSARJobResult(search=loaded, dataframe=None, oids=[])
        self._structure_source = self.struct_src_combo.currentText()
        self._fill_leaderboard(self._job)
        self._set_job_running(False)
        if self.parent_app is not None and loaded.models:
            model = loaded.models[0]
            self.parent_app.status_label.setText(
                f"Quick QSAR: loaded {model.method_label} ({model.n_features} features)."
            )

    def _on_predict_finished(self, rows: list) -> None:
        self._active_job_id = None
        self._disconnect_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("Quick QSAR predictions", status_message=None)
        self._set_job_running(False)
        job = self._job
        if job is None or self.parent_app is None:
            return
        pred_col = (
            self.pred_column_edit.text().strip() or f"Quick QSAR_{job.search.activity_column}"
        )
        headers = output_headers(pred_col, job.search.task)
        headers, merged = table_write_rows(rows or [], headers)
        if not merged:
            QMessageBox.information(
                self,
                "Quick QSAR",
                "No rows received predictions (missing features or structures).",
            )
            return
        self.parent_app.on_calc_finished(merged, headers, progress_label="Quick QSAR")
        n_pred = len(rows or [])
        how = "consensus" if self.chk_consensus.isChecked() else "selected-model"
        QMessageBox.information(
            self,
            "Quick QSAR",
            f"Added {how} predictions for {n_pred:,} row(s) in “{pred_col}”.",
        )

    def _on_failed(self, message: str) -> None:
        self._active_job_id = None
        self._reset_after_failure(message or "Quick QSAR failed.")
