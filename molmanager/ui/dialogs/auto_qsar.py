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

"""AutoQSAR — search features and models for an activity column (Data menu)."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
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

from ...analysis.auto_qsar import table_write_rows
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

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


class AutoQSARDialog(QDialog):
    """Pick an activity column and task. AutoQSAR chooses the features and model."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_state(parent)
        self._build_ui()
        self._wire_ui()
        self._reload_columns()

    def _init_state(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.setWindowTitle("AutoQSAR")
        self.setMinimumSize(760, 560)
        self.resize(960, 680)
        make_window_minimizable(self)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._job: AutoQSARJobResult | None = None
        self._mol_payloads: list | None = None
        self._job_running = False
        self._active_progress_label = "AutoQSAR"
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
        self.effort_combo = QComboBox()
        self.effort_combo.addItem("Quick", "quick")
        self.effort_combo.addItem("Standard", "standard")
        self.effort_combo.setToolTip(
            "Quick scores default hyperparameters with 3-fold CV. "
            "Standard adds a short second-stage grid and 5-fold CV."
        )
        search_form.addRow("Effort:", self.effort_combo)
        self.struct_src_combo = QComboBox()
        search_form.addRow("Structure:", self.struct_src_combo)
        hint = QLabel(
            "AutoQSAR tries table columns, calculated 2D descriptors, and a few fingerprint "
            "blocks, then keeps the model with the best training-set score."
        )
        hint.setWordWrap(True)
        search_form.addRow(hint)
        left_lyt.addWidget(search_grp)

        out_grp = QGroupBox("Output")
        out_form = QFormLayout(out_grp)
        self.pred_column_edit = QLineEdit()
        self.pred_column_edit.setPlaceholderText("AutoQSAR_<activity column>")
        out_form.addRow("Prediction column:", self.pred_column_edit)
        left_lyt.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run AutoQSAR")
        btn_row.addWidget(self.run_btn)
        self.predict_btn = QPushButton("Add predictions to table")
        self.predict_btn.setEnabled(False)
        self.predict_btn.setToolTip(
            "Write the winning predictions. Calculated descriptors the winner uses are written too."
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
        right_lyt.addWidget(QLabel("Leaderboard"))
        self.leaderboard = QTableWidget(0, 5)
        self.leaderboard.setHorizontalHeaderLabels(
            ["Model", "Feature set", "Features", "CV mean", "CV std"]
        )
        self.leaderboard.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.leaderboard.setSelectionMode(QAbstractItemView.SingleSelection)
        self.leaderboard.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.leaderboard.verticalHeader().setVisible(False)
        self.leaderboard.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.leaderboard.setMinimumHeight(160)
        right_lyt.addWidget(self.leaderboard)
        right_lyt.addWidget(QLabel("Results"))
        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        apply_monospace_to_text_edit(self.results_text)
        self.results_text.setPlaceholderText(
            "Choose an activity column and task, then click Run AutoQSAR.\n\n"
            "Structures are used to calculate descriptors and fingerprints when they improve "
            "the training-set score. The hold-out score is reported only for the winner."
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
        prev = self.activity_combo.currentText().strip()
        self.activity_combo.blockSignals(True)
        self.activity_combo.clear()
        if self.parent_app is not None:
            self.struct_src_combo.clear()
            self.struct_src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())
            df, _oids = self._scoped_dataframe_and_oids()
            for column in numeric_subset(df, exclude_id=True).columns:
                self.activity_combo.addItem(str(column))
        if self.activity_combo.count():
            if prev:
                idx = self.activity_combo.findText(prev)
                self.activity_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                select_preferred_activity_column(self.activity_combo)
        self.activity_combo.blockSignals(False)
        self._on_activity_changed()

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
        suggested = f"AutoQSAR_{activity}"
        current = self.pred_column_edit.text().strip()
        if not current or current == self._auto_pred_name:
            self.pred_column_edit.setText(suggested)
        self._auto_pred_name = suggested

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.run_btn.setEnabled(not running)
        self.predict_btn.setEnabled(not running and self._job is not None)

    def _on_run(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        activity = self.activity_combo.currentText().strip()
        if not activity:
            QMessageBox.warning(self, "AutoQSAR", "Select an activity column (Y).")
            return
        df, oids = self._scoped_dataframe_and_oids()
        if len(oids) < 8:
            QMessageBox.information(
                self,
                "AutoQSAR",
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
        pred_col = self.pred_column_edit.text().strip() or f"AutoQSAR_{activity}"
        self.pred_column_edit.setText(pred_col)
        params = {
            "dataframe": df,
            "oids": oids,
            "activity_column": activity,
            "task_mode": self._task_mode_key(),
            "effort": str(self.effort_combo.currentData() or "quick"),
            "mol_payloads": payloads,
            "prediction_column": pred_col,
        }
        self._mol_payloads = payloads
        self._job = None
        self.leaderboard.setRowCount(0)
        self.results_text.setPlainText("Searching…")
        self._active_progress_label = "AutoQSAR"
        self._set_job_running(True)
        self._disconnect_thread_finished()
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            "AutoQSAR",
            len(oids),
            lambda ev, ps, p=params, sigs=self._signals: AutoQSARSearchWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"AutoQSAR ({len(oids)} rows)",
        )
        self.parent_app.process_queue.thread_finished.connect(self._on_thread_finished)

    def _on_predict(self) -> None:
        if self._job_running or self._job is None or self.parent_app is None:
            return
        bundle = self._job.search.fit.bundle
        out_col = (
            self.pred_column_edit.text().strip() or f"AutoQSAR_{self._job.search.activity_column}"
        )
        df = self._job.dataframe
        oids = list(self._job.oids)
        payloads = self._mol_payloads if bundle.fp_choice else None
        if payloads is None or len(payloads) == len(oids):
            kept = self.parent_app._filter_rows_for_resume([(int(oid),) for oid in oids], [out_col])
            if len(kept) != len(oids):
                keep = {int(row[0]) for row in kept}
                mask = [i for i, oid in enumerate(oids) if int(oid) in keep]
                df = df.iloc[mask].reset_index(drop=True)
                oids = [oids[i] for i in mask]
                if payloads is not None:
                    payloads = [payloads[i] for i in mask]
        params = {
            "bundle": bundle,
            "dataframe": df,
            "oids": oids,
            "mol_payloads": payloads,
            "output_column": out_col,
        }
        self._active_progress_label = "AutoQSAR predictions"
        self._set_job_running(True)
        self._disconnect_thread_finished()
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            "AutoQSAR predictions",
            len(oids),
            lambda ev, ps, p=params, sigs=self._signals: AutoQSARPredictWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"AutoQSAR predict ({len(oids)} rows)",
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
            QMessageBox.warning(self, "AutoQSAR", message)

    def _on_search_finished(self, result: object) -> None:
        self._active_job_id = None
        self._disconnect_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("AutoQSAR", status_message=None)
        if not isinstance(result, AutoQSARJobResult):
            self._set_job_running(False)
            return
        self._job = result
        self._fill_leaderboard(result)
        self.results_text.setPlainText(result.search.report_text)
        self._set_job_running(False)
        winner = result.search.winner
        if self.parent_app is not None:
            self.parent_app.status_label.setText(
                f"AutoQSAR: {winner.model_label} on {winner.feature_set} "
                f"({winner.n_features} features, CV {winner.cv_mean:.3f})."
            )

    def _fill_leaderboard(self, result: AutoQSARJobResult) -> None:
        trials = result.search.trials
        self.leaderboard.setRowCount(len(trials))
        for row, trial in enumerate(trials):
            values = (
                trial.model_label,
                trial.feature_set,
                str(trial.n_features),
                f"{trial.cv_mean:.4f}",
                f"{trial.cv_std:.4f}",
            )
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col >= 2:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.leaderboard.setItem(row, col, item)
        if trials:
            self.leaderboard.selectRow(0)
        self.leaderboard.resizeColumnsToContents()
        self.leaderboard.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

    def _on_predict_finished(self, rows: list) -> None:
        self._active_job_id = None
        self._disconnect_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("AutoQSAR predictions", status_message=None)
        self._set_job_running(False)
        job = self._job
        if job is None or self.parent_app is None:
            return
        pred_col = self.pred_column_edit.text().strip() or f"AutoQSAR_{job.search.activity_column}"
        headers, merged = table_write_rows(
            job.dataframe,
            list(job.oids),
            job.search.computed_columns_used,
            rows or [],
            pred_col,
        )
        if not merged:
            QMessageBox.information(
                self,
                "AutoQSAR",
                "No rows received predictions (missing features or structures).",
            )
            return
        self.parent_app.on_calc_finished(merged, headers, progress_label="AutoQSAR")
        n_pred = len(rows or [])
        extra = ""
        if job.search.computed_columns_used:
            written = ", ".join(job.search.computed_columns_used)
            extra = f" Wrote descriptors: {written}."
        QMessageBox.information(
            self,
            "AutoQSAR",
            f"Added predictions for {n_pred:,} row(s) in “{pred_col}”.{extra}",
        )

    def _on_failed(self, message: str) -> None:
        self._active_job_id = None
        self._reset_after_failure(message or "AutoQSAR failed.")
