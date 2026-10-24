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

"""CoMSIA on an aligned pose column (Data → QSAR)."""

from __future__ import annotations

from contextlib import suppress
from typing import TYPE_CHECKING, Any

import pandas as pd
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...analysis.comsia import FIELD_LABELS, FIELD_ORDER, ComsiaModel
from ...conformers.conformer_column_codec import is_packed_ensemble_header
from ...workers.comsia_worker import ComsiaPredictWorker, ComsiaSignals, ComsiaTrainWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..table_dataframe import numeric_subset, table_to_dataframe
from .mmp import select_preferred_activity_column
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow


class ComsiaDialog(QDialog):
    """Train a CoMSIA model on aligned poses and write predictions to the table."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("CoMSIA")
        make_window_minimizable(self)
        self.setMinimumWidth(520)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._only_selected_scope_prefix = "Selected Rows Only"
        self._model: ComsiaModel | None = None
        self._job_running = False
        self._active_progress_label = "CoMSIA"
        self._active_job_id: str | None = None
        self._auto_pred_name = ""
        self._signals = ComsiaSignals(self)
        self._field_checks: dict[str, QCheckBox] = {}
        self._build_ui(n_sel)
        self._wire_ui()
        self._reload_columns()

    def _build_ui(self, n_selected: int) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(8)

        data_grp = QGroupBox("Data")
        form = QFormLayout(data_grp)
        self.activity_combo = QComboBox()
        self.activity_combo.setMinimumWidth(220)
        form.addRow("Activity (Y):", self.activity_combo)
        self.pose_combo = QComboBox()
        self.pose_combo.setToolTip(
            "Aligned poses in one coordinate frame. The first 3D conformer of each cell is used. "
            "Superpose a series, or use docked poses, before training."
        )
        form.addRow("Poses:", self.pose_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({n_selected} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        self.only_selected_cb.setToolTip(
            "Train and predict on the current selection. Otherwise every table row is used."
        )
        form.addRow("", self.only_selected_cb)
        root.addWidget(data_grp)

        field_grp = QGroupBox("Fields")
        field_lyt = QVBoxLayout(field_grp)
        for key in FIELD_ORDER:
            box = QCheckBox(FIELD_LABELS[key])
            box.setChecked(True)
            self._field_checks[key] = box
            field_lyt.addWidget(box)
        root.addWidget(field_grp)

        grid_grp = QGroupBox("Grid and PLS")
        grid_form = QFormLayout(grid_grp)
        self.spacing_spin = QDoubleSpinBox()
        self.spacing_spin.setRange(0.5, 2.0)
        self.spacing_spin.setSingleStep(0.5)
        self.spacing_spin.setDecimals(1)
        self.spacing_spin.setValue(2.0)
        self.spacing_spin.setSuffix(" Å")
        self.spacing_spin.setToolTip(
            "Distance between grid points. 2 Å is the usual CoMSIA spacing."
        )
        grid_form.addRow("Spacing:", self.spacing_spin)
        self.padding_spin = QDoubleSpinBox()
        self.padding_spin.setRange(1.0, 8.0)
        self.padding_spin.setSingleStep(0.5)
        self.padding_spin.setDecimals(1)
        self.padding_spin.setValue(4.0)
        self.padding_spin.setSuffix(" Å")
        self.padding_spin.setToolTip(
            "Extra space around the training poses. The lattice is fixed from those poses."
        )
        grid_form.addRow("Padding:", self.padding_spin)
        self.components_spin = QSpinBox()
        self.components_spin.setRange(1, 8)
        self.components_spin.setValue(5)
        self.components_spin.setToolTip(
            "Largest PLS component count to test. The fit keeps the smallest count whose "
            "leave-one-out q² is within 0.05 of the best score."
        )
        grid_form.addRow("Max components:", self.components_spin)
        self.sd_spin = QDoubleSpinBox()
        self.sd_spin.setRange(0.0, 0.5)
        self.sd_spin.setSingleStep(0.01)
        self.sd_spin.setDecimals(2)
        self.sd_spin.setValue(0.01)
        self.sd_spin.setToolTip(
            "Drop a grid point when its standard deviation is below this fraction of the "
            "field's standard deviation. The cutoff is refit inside each leave-one-out fold."
        )
        grid_form.addRow("Flat-point cutoff:", self.sd_spin)
        root.addWidget(grid_grp)

        out_grp = QGroupBox("Output")
        out_form = QFormLayout(out_grp)
        self.pred_column_edit = QLineEdit()
        self.pred_column_edit.setPlaceholderText("CoMSIA_<activity column>")
        out_form.addRow("Prediction column:", self.pred_column_edit)
        root.addWidget(out_grp)

        btn_row = QHBoxLayout()
        self.train_btn = QPushButton("Train/Evaluate")
        self.predict_btn = QPushButton("Add predictions to table")
        self.predict_btn.setEnabled(False)
        self.refresh_btn = QPushButton("Refresh columns")
        btn_row.addWidget(self.train_btn)
        btn_row.addWidget(self.predict_btn)
        btn_row.addWidget(self.refresh_btn)
        root.addLayout(btn_row)

        self.results_text = QTextEdit()
        self.results_text.setReadOnly(True)
        self.results_text.setMinimumHeight(180)
        apply_monospace_to_text_edit(self.results_text)
        self.results_text.setPlaceholderText(
            "Superpose the series, or choose a poses column from docking, then train.\n\n"
            "q² is leave-one-out. The model written to the table is fit on every training row."
        )
        root.addWidget(self.results_text, 1)

    def _wire_ui(self) -> None:
        self._signals.train_finished.connect(self._on_train_finished, Qt.QueuedConnection)
        self._signals.predict_finished.connect(self._on_predict_finished, Qt.QueuedConnection)
        self._signals.failed.connect(self._on_failed, Qt.QueuedConnection)
        self.activity_combo.currentIndexChanged.connect(self._on_activity_changed)
        self.only_selected_cb.stateChanged.connect(self._reload_columns)
        self.train_btn.clicked.connect(self._on_train)
        self.predict_btn.clicked.connect(self._on_predict)
        self.refresh_btn.clicked.connect(self._reload_columns)

    def _scoped_dataframe_and_oids(self) -> tuple[pd.DataFrame, list[int]]:
        app = self.parent_app
        assert app is not None
        df, source_rows = table_to_dataframe(
            app,
            visible_only=False,
            only_selected=selection_scope_checked(self),
        )
        model = app._table_model
        oids = [int(model.row_oid(row)) for row in source_rows]
        return df, oids

    def _reload_columns(self) -> None:
        prev_activity = self.activity_combo.currentText().strip()
        prev_pose = self.pose_combo.currentText().strip()
        self.activity_combo.blockSignals(True)
        self.activity_combo.clear()
        self.pose_combo.clear()
        if self.parent_app is not None:
            df, _oids = self._scoped_dataframe_and_oids()
            for column in numeric_subset(df, exclude_id=True).columns:
                self.activity_combo.addItem(str(column))
            for header in _pose_column_headers(self.parent_app):
                self.pose_combo.addItem(header)
        if self.activity_combo.count():
            if prev_activity:
                idx = self.activity_combo.findText(prev_activity)
                self.activity_combo.setCurrentIndex(idx if idx >= 0 else 0)
            else:
                select_preferred_activity_column(self.activity_combo)
        if self.pose_combo.count():
            preferred = _preferred_pose_column(
                [self.pose_combo.itemText(i) for i in range(self.pose_combo.count())]
            )
            target = prev_pose or preferred
            idx = self.pose_combo.findText(target)
            self.pose_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.activity_combo.blockSignals(False)
        self._on_activity_changed()

    def _on_activity_changed(self, *_args: Any) -> None:
        activity = self.activity_combo.currentText().strip()
        if not activity:
            return
        suggested = f"CoMSIA_{activity}"
        current = self.pred_column_edit.text().strip()
        if not current or current == self._auto_pred_name:
            self.pred_column_edit.setText(suggested)
        self._auto_pred_name = suggested

    def _selected_fields(self) -> list[str]:
        return [key for key in FIELD_ORDER if self._field_checks[key].isChecked()]

    def _pose_records(self) -> list[tuple[int, bytes, float | None]]:
        app = self.parent_app
        assert app is not None
        from ..main_window.conformer_writeback import mol_for_ensemble_column

        column = self.pose_combo.currentText().strip()
        df, oids = self._scoped_dataframe_and_oids()
        activity = self.activity_combo.currentText().strip()
        if activity and activity in df.columns:
            values = pd.to_numeric(df[activity], errors="coerce")
        else:
            values = pd.Series(dtype=float)
        records: list[tuple[int, bytes, float | None]] = []
        for index, oid in enumerate(oids):
            mol = mol_for_ensemble_column(app, int(oid), column, min_conformers=1)
            if mol is None:
                continue
            activity_value: float | None = None
            if index < len(values):
                raw = values.iloc[index]
                if pd.notna(raw):
                    activity_value = float(raw)
            records.append((int(oid), mol.ToBinary(), activity_value))
        return records

    def _fit_params(self) -> dict[str, Any]:
        return {
            "fields": self._selected_fields(),
            "spacing": float(self.spacing_spin.value()),
            "padding": float(self.padding_spin.value()),
            "max_components": int(self.components_spin.value()),
            "sd_fraction": float(self.sd_spin.value()),
        }

    def _on_train(self) -> None:
        if self._job_running or self.parent_app is None:
            return
        if not self.activity_combo.currentText().strip():
            QMessageBox.warning(self, "CoMSIA", "Select an activity column (Y).")
            return
        if not self.pose_combo.currentText().strip():
            QMessageBox.information(
                self,
                "CoMSIA",
                "Choose a pose column. Superpose the series, or dock it, so the rows share one frame.",
            )
            return
        if not self._selected_fields():
            QMessageBox.warning(self, "CoMSIA", "Select at least one field.")
            return
        records = self._pose_records()
        labeled = sum(1 for _oid, _blob, activity in records if activity is not None)
        if labeled < 5:
            QMessageBox.information(
                self,
                "CoMSIA",
                f"Need at least 5 posed rows with activity ({labeled} usable).",
            )
            return
        params = {"records": records, **self._fit_params()}
        self._model = None
        self.predict_btn.setEnabled(False)
        self.results_text.setPlainText("Training…")
        self._start_job(
            "CoMSIA",
            labeled,
            lambda ev, ps, p=params, sigs=self._signals: ComsiaTrainWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"CoMSIA train ({labeled} rows)",
        )

    def _on_predict(self) -> None:
        if self._job_running or self._model is None or self.parent_app is None:
            return
        if not self.pose_combo.currentText().strip():
            QMessageBox.information(self, "CoMSIA", "Choose a pose column.")
            return
        records = self._pose_records()
        if not records:
            QMessageBox.information(self, "CoMSIA", "No posed rows in the current scope.")
            return
        column = self.pred_column_edit.text().strip() or self._auto_pred_name or "CoMSIA"
        records = self.parent_app._filter_rows_for_resume(records, [column])
        self.pred_column_edit.setText(column)
        params = {"records": records, "model": self._model, "output_column": column}
        self._start_job(
            "CoMSIA predictions",
            len(records),
            lambda ev, ps, p=params, sigs=self._signals: ComsiaPredictWorker(
                p, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"CoMSIA predict ({len(records)} rows)",
        )

    def _start_job(self, label: str, total: int, factory, queue_label: str) -> None:
        assert self.parent_app is not None
        self._active_progress_label = label
        self._set_job_running(True)
        self._disconnect_process_queue_thread_finished()
        self._active_job_id = enqueue_process_queue_job(
            self.parent_app,
            label,
            total,
            factory,
            queue_label=queue_label,
        )
        self.parent_app.process_queue.thread_finished.connect(
            self._on_process_queue_thread_finished
        )

    def _set_job_running(self, running: bool) -> None:
        self._job_running = running
        self.train_btn.setEnabled(not running)
        self.predict_btn.setEnabled(not running and self._model is not None)
        self.refresh_btn.setEnabled(not running)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_process_queue_thread_finished()
        super().closeEvent(event)

    def _disconnect_process_queue_thread_finished(self) -> None:
        app = self.parent_app
        if app is None:
            return
        with suppress(TypeError):
            app.process_queue.thread_finished.disconnect(self._on_process_queue_thread_finished)

    def _on_process_queue_thread_finished(self, job_id: str) -> None:
        if job_id != self._active_job_id or not self._job_running:
            return
        self._active_job_id = None
        self._reset_after_failure("Cancelled.")

    def _reset_after_failure(self, message: str) -> None:
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress(self._active_progress_label)
        self._set_job_running(False)
        self._disconnect_process_queue_thread_finished()
        if message and message != "Cancelled.":
            self.results_text.append(f"\n\nError: {message}")
        if message:
            QMessageBox.warning(self, "CoMSIA", message)

    def _on_train_finished(self, result: object) -> None:
        self._active_job_id = None
        self._disconnect_process_queue_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("CoMSIA", status_message=None)
        if not isinstance(result, ComsiaModel):
            self._set_job_running(False)
            return
        self._model = result
        self._set_job_running(False)
        self.results_text.setPlainText(result.metrics_text)
        if self.parent_app is not None:
            self.parent_app.status_label.setText(
                f"CoMSIA: q² = {result.q2:.3f} on {result.n_train} rows "
                f"({result.n_components} component(s))."
            )

    def _on_predict_finished(self, payload: object) -> None:
        self._active_job_id = None
        self._disconnect_process_queue_thread_finished()
        if self.parent_app is not None:
            self.parent_app._finish_tool_progress("CoMSIA predictions", status_message=None)
        self._set_job_running(False)
        rows: list = []
        skipped = 0
        if isinstance(payload, dict):
            rows = list(payload.get("rows") or [])
            skipped = int(payload.get("skipped") or 0)
        if not rows or self.parent_app is None:
            QMessageBox.information(self, "CoMSIA", "No rows received predictions.")
            return
        column = self.pred_column_edit.text().strip() or self._auto_pred_name or "CoMSIA"
        written = [(int(oid), {column: f"{float(value):.4f}"}) for oid, value in rows]
        self.parent_app.on_calc_finished(written, [column], progress_label="CoMSIA")
        extra = f" Skipped {skipped} row(s) without a 3D pose." if skipped else ""
        QMessageBox.information(
            self,
            "CoMSIA",
            f"Added column “{column}” with predictions for {len(written):,} row(s).{extra}",
        )

    def _on_failed(self, message: str) -> None:
        self._active_job_id = None
        self._reset_after_failure(message or "CoMSIA failed.")


def _pose_column_headers(app) -> list[str]:
    headers = [str(header).strip() for header in (getattr(app, "headers", None) or [])]
    return [header for header in headers if is_packed_ensemble_header(header)]


def _preferred_pose_column(headers: list[str]) -> str:
    """Prefer a superpose column, then docked poses, then any ensemble column."""
    for prefix in ("superpose", "poses", "confs"):
        for header in headers:
            if header.lower().startswith(prefix):
                return header
    return headers[0] if headers else ""
