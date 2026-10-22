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

from __future__ import annotations

from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...chem.rdkit_fingerprints import select_default_fingerprint
from ...chem.structure_payload import oid_mol_rows_from_payloads
from ...workers import (
    BulkSimilaritySignals,
    BulkSimilarityWorker,
    SIMILARITY_FP_TYPE_LABELS,
    SIMILARITY_METRIC_LABELS,
)
from ..qt_widget_utils import make_window_minimizable
from ..analysis_job_support import enqueue_process_queue_job


class BulkSimilarityDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Bulk Similarity")
        self.setMinimumWidth(560)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        self._sel_lbl = QLabel("")
        self._sel_lbl.setStyleSheet("color: palette(mid);")
        root.addWidget(self._sel_lbl)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        root.addLayout(form)

        self.src_combo = QComboBox()
        self._refresh_structure_sources()
        form.addRow("Structure source:", self.src_combo)

        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        select_default_fingerprint(self.fp_combo)
        form.addRow("Fingerprint:", self.fp_combo)

        self.metric_combo = QComboBox()
        self.metric_combo.addItems(SIMILARITY_METRIC_LABELS)
        form.addRow("Similarity metric:", self.metric_combo)

        self.top_k_spin = QSpinBox()
        self.top_k_spin.setRange(10, 2000)
        self.top_k_spin.setValue(200)
        form.addRow("Pairs to keep (K):", self.top_k_spin)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Compute")
        self.run_btn.clicked.connect(self._on_run)
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.summary_lbl = QLabel("")
        self.summary_lbl.setWordWrap(True)
        root.addWidget(self.summary_lbl)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Type", "OID A", "OID B", "Similarity"])
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        root.addWidget(self.table, 1)

        self._sig = BulkSimilaritySignals(self)
        self._sig.finished.connect(self._on_finished)
        self._sig.failed.connect(self._on_failed)

        make_window_minimizable(self)
        self._sync_selection_label()

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _sync_selection_label(self) -> None:
        if self.parent_app is None:
            self._sel_lbl.setText("")
            return
        n = len(self.parent_app._selected_logical_rows())
        self._sel_lbl.setText(f"Selected rows: {n:,}")

    def _selected_payloads_or_warn(self):
        app = self.parent_app
        if app is None:
            return []
        allowed = app._selected_oids_set()
        if not allowed:
            QMessageBox.information(self, "Bulk Similarity", "Select rows in the table first.")
            return []
        src = self.src_combo.currentText()
        payloads = app.collect_scoped_table_structure_payloads(src, only_selected=True)
        if len(payloads) < 2:
            QMessageBox.information(
                self,
                "Bulk Similarity",
                "Need at least two selected rows with valid structures in this source.",
            )
            return []
        return payloads

    def _on_run(self) -> None:
        app = self.parent_app
        if app is None or not app.headers:
            return
        rows = self._selected_payloads_or_warn()
        if not rows:
            return
        from ...platform_support.memory_guards import check_cluster_workload

        guard = check_cluster_workload(len(rows))
        if not guard.ok:
            QMessageBox.warning(self, "Bulk Similarity", guard.message)
            return
        fp_choice = self.fp_combo.currentText()
        metric = self.metric_combo.currentText().strip() or "Tanimoto"
        top_k = int(self.top_k_spin.value())

        self.run_btn.setEnabled(False)
        self.summary_lbl.setText("")
        self.table.setRowCount(0)

        enqueue_process_queue_job(
            app,
            "Bulk similarity",
            max(1, len(rows)),
            lambda ev, ps, r=rows, fp=fp_choice, m=metric, k=top_k, sig=self._sig: (
                BulkSimilarityWorker(
                    oid_mol_rows_from_payloads(r),
                    fp,
                    m,
                    top_k_pairs=k,
                    signals=sig,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"Bulk similarity ({len(rows)} rows)",
        )

    def _on_finished(self, res) -> None:
        app = self.parent_app
        if app is not None:
            app._finish_tool_progress("Bulk similarity")
        self.run_btn.setEnabled(True)

        mean = "N/A" if res.mean_similarity is None else f"{res.mean_similarity:.4f}"
        mn = "N/A" if res.min_similarity is None else f"{res.min_similarity:.4f}"
        mx = "N/A" if res.max_similarity is None else f"{res.max_similarity:.4f}"
        self.summary_lbl.setText(
            f"Rows: {res.n_rows:,}  Pairs: {res.n_pairs:,}  Mean: {mean}  Min: {mn}  Max: {mx}"
        )

        rows = [("Most similar", a, b, s) for a, b, s in res.most_similar_pairs] + [
            ("Least similar", a, b, s) for a, b, s in res.least_similar_pairs
        ]
        self.table.setRowCount(0)
        for r, (typ, a, b, s) in enumerate(rows):
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(str(typ)))
            self.table.setItem(r, 1, QTableWidgetItem(str(int(a))))
            self.table.setItem(r, 2, QTableWidgetItem(str(int(b))))
            self.table.setItem(r, 3, QTableWidgetItem(f"{float(s):.4f}"))
        self.table.resizeColumnsToContents()

    def _on_failed(self, msg: str) -> None:
        app = self.parent_app
        if app is not None:
            app._finish_tool_progress("Bulk similarity")
        self.run_btn.setEnabled(True)
        self.summary_lbl.setText(
            "Cancelled." if msg == "Cancelled." else (msg or "Bulk similarity failed.")
        )
