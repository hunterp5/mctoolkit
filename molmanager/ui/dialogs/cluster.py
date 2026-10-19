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

"""Fingerprint clustering dialog (Chemistry → Fingerprints → Cluster)."""

from __future__ import annotations

from contextlib import suppress

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...chem.structure_payload import oid_mol_rows_from_payloads
from ...workers import ClusterExploreWorker, ClusterWorker, SIMILARITY_FP_TYPE_LABELS
from ...workers.cluster_worker import CLUSTER_METHOD_LABELS, CLUSTER_METHOD_SHORT_LABELS
from ..analysis_job_support import enqueue_process_queue_job, prepare_scoped_structure_payloads
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class ClusterDialog(QDialog):
    """Cluster compounds by fingerprint (multiple algorithms + optional exploratory sweep)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_cluster_state(parent)
        self._build_cluster_ui()
        self._wire_cluster_ui()
        self._on_method_changed(self.method_combo.currentIndex())
        self._refresh_structure_sources()
        self.adjustSize()

    def _init_cluster_state(self, parent) -> None:
        self.setWindowTitle("Cluster")
        self.setMinimumWidth(520)
        self.resize(560, 640)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._active_cluster_job_id: str | None = None

    def _build_cluster_ui(self) -> None:
        n_sel = self._initial_selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        src_row = QHBoxLayout()
        src_row.setSpacing(6)
        src_row.addWidget(QLabel("Source:"))
        self.src_combo = QComboBox()
        self.src_combo.setMinimumWidth(180)
        src_row.addWidget(self.src_combo, 1)
        root.addLayout(src_row)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        fp_row = QHBoxLayout()
        fp_row.setSpacing(6)
        fp_row.addWidget(QLabel("Fingerprint:"))
        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        fp_row.addWidget(self.fp_combo, 1)
        root.addLayout(fp_row)

        self.exploratory_cb = QCheckBox("Exploratory mode (sample many parameter sets)")
        self.exploratory_cb.setToolTip(
            "Runs a bounded grid of methods and settings; review metrics, then apply a trial to add a cluster column."
        )
        root.addWidget(self.exploratory_cb)

        self._explore_panel = QWidget()
        ex_outer = QVBoxLayout(self._explore_panel)
        ex_outer.setContentsMargins(0, 0, 0, 0)
        ex_outer.setSpacing(4)
        mr = QHBoxLayout()
        mr.addWidget(QLabel("Max trials:"))
        self.explore_max_runs = QSpinBox()
        self.explore_max_runs.setRange(12, 250)
        self.explore_max_runs.setValue(80)
        self.explore_max_runs.setToolTip(
            "Upper bound on (method, parameter) combinations to evaluate."
        )
        mr.addWidget(self.explore_max_runs)
        mr.addStretch()
        ex_outer.addLayout(mr)

        grp = QGroupBox("Methods to sample")
        gg = QGridLayout(grp)
        self._ex_kmeans = QCheckBox("K-Means")
        self._ex_kmeans.setChecked(True)
        self._ex_agglomerative = QCheckBox("Agglomerative")
        self._ex_agglomerative.setChecked(True)
        self._ex_dbscan = QCheckBox("DBSCAN")
        self._ex_dbscan.setChecked(True)
        self._ex_butina = QCheckBox("Butina (Tanimoto)")
        self._ex_butina.setChecked(True)
        self._ex_sphere = QCheckBox("Sphere exclusion (Leader)")
        self._ex_sphere.setChecked(True)
        self._ex_jp = QCheckBox("Jarvis-Patrick")
        self._ex_jp.setChecked(True)
        gg.addWidget(self._ex_kmeans, 0, 0)
        gg.addWidget(self._ex_agglomerative, 0, 1)
        gg.addWidget(self._ex_dbscan, 1, 0)
        gg.addWidget(self._ex_butina, 1, 1)
        gg.addWidget(self._ex_sphere, 2, 0)
        gg.addWidget(self._ex_jp, 2, 1)
        ex_outer.addWidget(grp)
        root.addWidget(self._explore_panel)
        self._explore_panel.setVisible(False)

        self._single_method_widget = QWidget()
        sm_lyt = QVBoxLayout(self._single_method_widget)
        sm_lyt.setContentsMargins(0, 0, 0, 0)
        sm_lyt.setSpacing(4)

        alg_row = QHBoxLayout()
        alg_row.setSpacing(6)
        alg_row.addWidget(QLabel("Method:"))
        self.method_combo = QComboBox()
        for key, label in CLUSTER_METHOD_LABELS:
            self.method_combo.addItem(label, key)
        alg_row.addWidget(self.method_combo, 1)
        sm_lyt.addLayout(alg_row)

        self._opt_stack = QStackedWidget()
        self._method_pages: dict[str, int] = {}
        km = QWidget()
        km_lyt = QFormLayout(km)
        self.kmeans_k = QSpinBox()
        self.kmeans_k.setRange(2, 500)
        self.kmeans_k.setValue(8)
        self.kmeans_k.setToolTip("Number of clusters (K-Means).")
        km_lyt.addRow("Clusters (k):", self.kmeans_k)
        self._method_pages["kmeans"] = self._opt_stack.addWidget(km)

        ag = QWidget()
        ag_lyt = QFormLayout(ag)
        self.agglom_k = QSpinBox()
        self.agglom_k.setRange(2, 500)
        self.agglom_k.setValue(8)
        self.agglom_k.setToolTip("Number of clusters (cut tree).")
        ag_lyt.addRow("Clusters (k):", self.agglom_k)
        self.linkage_combo = QComboBox()
        self.linkage_combo.addItems(["average", "complete", "single"])
        self.linkage_combo.setToolTip(
            "Linkage for hierarchical clustering (Euclidean on bit vectors)."
        )
        ag_lyt.addRow("Linkage:", self.linkage_combo)
        self._method_pages["agglomerative"] = self._opt_stack.addWidget(ag)

        db = QWidget()
        db_lyt = QFormLayout(db)
        self.dbscan_eps = QDoubleSpinBox()
        self.dbscan_eps.setRange(0.05, 2.0)
        self.dbscan_eps.setDecimals(3)
        self.dbscan_eps.setSingleStep(0.05)
        self.dbscan_eps.setValue(0.35)
        self.dbscan_eps.setToolTip(
            "Neighborhood radius (cosine distance). Smaller → more clusters / noise."
        )
        db_lyt.addRow("eps:", self.dbscan_eps)
        self.dbscan_min_samples = QSpinBox()
        self.dbscan_min_samples.setRange(2, 200)
        self.dbscan_min_samples.setValue(5)
        self.dbscan_min_samples.setToolTip("Minimum neighbors to form a dense region.")
        db_lyt.addRow("min_samples:", self.dbscan_min_samples)
        self._method_pages["dbscan"] = self._opt_stack.addWidget(db)

        bu = QWidget()
        bu_lyt = QFormLayout(bu)
        self.butina_cutoff = QDoubleSpinBox()
        self.butina_cutoff.setRange(0.01, 0.95)
        self.butina_cutoff.setDecimals(3)
        self.butina_cutoff.setSingleStep(0.02)
        self.butina_cutoff.setValue(0.25)
        self.butina_cutoff.setToolTip(
            "Maximum Tanimoto distance (1 − similarity) for two compounds to be treated as neighbors in Butina."
        )
        bu_lyt.addRow("Distance cutoff:", self.butina_cutoff)
        self.butina_reorder_cb = QCheckBox("Reordering (slower, often fewer clusters)")
        bu_lyt.addRow(self.butina_reorder_cb)
        self._method_pages["butina"] = self._opt_stack.addWidget(bu)

        se = QWidget()
        se_lyt = QFormLayout(se)
        self.sphere_cutoff = QDoubleSpinBox()
        self.sphere_cutoff.setRange(0.01, 0.95)
        self.sphere_cutoff.setDecimals(3)
        self.sphere_cutoff.setSingleStep(0.02)
        self.sphere_cutoff.setValue(0.35)
        self.sphere_cutoff.setToolTip(
            "Minimum Tanimoto distance between cluster centroids (RDKit LeaderPicker). "
            "Each compound is assigned to its nearest centroid."
        )
        se_lyt.addRow("Distance cutoff:", self.sphere_cutoff)
        self._method_pages["sphere_exclusion"] = self._opt_stack.addWidget(se)

        jp = QWidget()
        jp_lyt = QFormLayout(jp)
        self.jp_nn = QSpinBox()
        self.jp_nn.setRange(2, 128)
        self.jp_nn.setValue(16)
        self.jp_nn.setToolTip(
            "Number of nearest neighbors (by Tanimoto) considered for each compound."
        )
        jp_lyt.addRow("Nearest neighbors (J):", self.jp_nn)
        self.jp_common = QSpinBox()
        self.jp_common.setRange(1, 127)
        self.jp_common.setValue(8)
        self.jp_common.setToolTip(
            "Minimum shared neighbors required to link two compounds (Jarvis–Patrick). Must be < J."
        )
        jp_lyt.addRow("Shared neighbors (P):", self.jp_common)
        self._method_pages["jarvis_patrick"] = self._opt_stack.addWidget(jp)

        sm_lyt.addWidget(self._opt_stack)
        root.addWidget(self._single_method_widget)

        self.explore_table = QTableWidget(0, 7)
        self.explore_table.setHorizontalHeaderLabels(
            ["Method", "Settings", "Clusters", "Silhouette", "Noise %", "Largest %", "Notes"]
        )
        self.explore_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.explore_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.explore_table.setMaximumHeight(220)
        self.explore_table.setVisible(False)
        root.addWidget(self.explore_table)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Run clustering")
        btn_row.addWidget(self.run_btn)
        self.apply_explore_btn = QPushButton("Apply selected trial")
        self.apply_explore_btn.setToolTip(
            "Add a column using the method/settings from the selected results row."
        )
        self.apply_explore_btn.setEnabled(False)
        self.apply_explore_btn.setVisible(False)
        btn_row.addWidget(self.apply_explore_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def _wire_cluster_ui(self) -> None:
        self.exploratory_cb.stateChanged.connect(self._on_exploratory_toggled)
        self.method_combo.currentIndexChanged.connect(self._on_method_changed)
        self.explore_table.itemDoubleClicked.connect(self._on_explore_item_double_clicked)
        self.run_btn.clicked.connect(self._on_run)
        self.apply_explore_btn.clicked.connect(self._on_apply_explore_trial)
        self.explore_table.itemSelectionChanged.connect(self._sync_apply_explore_enabled)
        make_window_minimizable(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        self._disconnect_process_queue_thread_finished()
        super().closeEvent(event)

    def _disconnect_process_queue_thread_finished(self) -> None:
        pa = self.parent_app
        if pa is None:
            return
        with suppress(TypeError):
            pa.process_queue.thread_finished.disconnect(self._on_process_queue_thread_finished)

    def _on_process_queue_thread_finished(self, job_id: str) -> None:
        if job_id != self._active_cluster_job_id:
            return
        self._active_cluster_job_id = None
        self.enable_run_after_job()

    def _on_method_changed(self, _idx: int = 0) -> None:
        key = str(self.method_combo.currentData() or "")
        self._opt_stack.setCurrentIndex(self._method_pages.get(key, 0))

    def _on_exploratory_toggled(self, state: int) -> None:
        ex = state == int(Qt.Checked)
        self._explore_panel.setVisible(ex)
        self._single_method_widget.setVisible(not ex)
        self.explore_table.setVisible(ex and self.explore_table.rowCount() > 0)
        self.apply_explore_btn.setVisible(ex)
        self._sync_apply_explore_enabled()
        if not ex:
            self.explore_table.setRowCount(0)
            self.apply_explore_btn.setEnabled(False)

    def fill_explore_results(self, rows: list) -> None:
        self.explore_table.setRowCount(0)
        if not rows:
            self.explore_table.setVisible(self.exploratory_cb.isChecked())
            self._sync_apply_explore_enabled()
            return
        self.explore_table.setVisible(True)
        for r, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            self.explore_table.insertRow(r)
            method = row.get("method") or ""
            params = row.get("params") if isinstance(row.get("params"), dict) else {}
            method_label = CLUSTER_METHOD_SHORT_LABELS.get(str(method), str(method))
            key_item = QTableWidgetItem(method_label)
            key_item.setData(Qt.UserRole, {"method": method, "params": params})
            self.explore_table.setItem(r, 0, key_item)
            self.explore_table.setItem(r, 1, QTableWidgetItem(str(row.get("settings", ""))))
            nc = row.get("n_clusters")
            self.explore_table.setItem(r, 2, QTableWidgetItem("" if nc is None else str(nc)))
            sil = row.get("silhouette")
            self.explore_table.setItem(r, 3, QTableWidgetItem("" if sil is None else str(sil)))
            nz = row.get("noise_pct")
            self.explore_table.setItem(r, 4, QTableWidgetItem("" if nz is None else str(nz)))
            lp = row.get("largest_pct")
            self.explore_table.setItem(r, 5, QTableWidgetItem("" if lp is None else str(lp)))
            self.explore_table.setItem(r, 6, QTableWidgetItem(str(row.get("notes", ""))))
        self.explore_table.resizeColumnsToContents()
        self._sync_apply_explore_enabled()

    def _sync_apply_explore_enabled(self) -> None:
        if not self.exploratory_cb.isChecked():
            self.apply_explore_btn.setEnabled(False)
            return
        self.apply_explore_btn.setEnabled(
            self.explore_table.currentRow() >= 0 and self.explore_table.rowCount() > 0
        )

    def _on_explore_item_double_clicked(self, item: QTableWidgetItem) -> None:
        self.explore_table.selectRow(item.row())
        self._on_apply_explore_trial()

    def _on_apply_explore_trial(self) -> None:
        if self.parent_app is None:
            return
        r = self.explore_table.currentRow()
        if r < 0:
            QMessageBox.information(self, "Cluster", "Select a row in the results table first.")
            return
        it = self.explore_table.item(r, 0)
        if it is None:
            return
        payload = it.data(Qt.UserRole)
        if not isinstance(payload, dict):
            QMessageBox.warning(self, "Cluster", "Could not read trial parameters for this row.")
            return
        method = payload.get("method")
        params = payload.get("params")
        if not method or not isinstance(params, dict):
            QMessageBox.warning(self, "Cluster", "Could not read trial parameters for this row.")
            return

        only_selected = selection_scope_checked(self)
        src = self.src_combo.currentText()
        rows = self._prepare_cluster_payloads(src, only_selected)
        if not rows:
            return

        col_name = self._unique_cluster_column()
        fp_choice = self.fp_combo.currentText()
        self._enqueue_cluster_worker(rows, fp_choice, method, dict(params), col_name)

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _prepare_cluster_payloads(self, src: str, only_selected: bool):
        need = "Need at least two rows with valid structures in this scope."
        return prepare_scoped_structure_payloads(
            self.parent_app,
            tool_label="Cluster",
            structure_source=src,
            only_selected=only_selected,
            min_mols=2,
            empty_message=need,
            too_few_message=need,
        )

    def _enqueue_cluster_worker(self, rows, fp_choice, method, params, col_name) -> None:
        self.run_btn.setEnabled(False)
        self._disconnect_process_queue_thread_finished()
        self._active_cluster_job_id = enqueue_process_queue_job(
            self.parent_app,
            "Clustering",
            len(rows),
            lambda ev, ps, r=rows, fc=fp_choice, m=method, p=params, c=col_name, ws=self.parent_app.signals: (
                ClusterWorker(
                    oid_mol_rows_from_payloads(r),
                    fc,
                    m,
                    p,
                    c,
                    ws,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"Cluster ({len(rows)} rows, {method})",
        )
        self.parent_app.process_queue.thread_finished.connect(
            self._on_process_queue_thread_finished
        )
        self.close()

    def _unique_cluster_column(self) -> str:
        base = "Cluster"
        name = base
        i = 1
        while name in self.parent_app.headers:
            i += 1
            name = f"{base} ({i})"
        return name

    def _on_run(self) -> None:
        if self.parent_app is None:
            return
        only_selected = selection_scope_checked(self)
        src = self.src_combo.currentText()
        rows = self._prepare_cluster_payloads(src, only_selected)
        if not rows:
            return

        fp_choice = self.fp_combo.currentText()

        from ...platform_support.memory_guards import check_cluster_workload

        guard = check_cluster_workload(len(rows))
        if not guard.ok:
            QMessageBox.warning(self, "Cluster", guard.message)
            return

        if self.exploratory_cb.isChecked():
            include = {
                "kmeans": self._ex_kmeans.isChecked(),
                "agglomerative": self._ex_agglomerative.isChecked(),
                "dbscan": self._ex_dbscan.isChecked(),
                "butina": self._ex_butina.isChecked(),
                "sphere_exclusion": self._ex_sphere.isChecked(),
                "jarvis_patrick": self._ex_jp.isChecked(),
            }
            if not any(include.values()):
                QMessageBox.warning(
                    self, "Cluster", "Select at least one method to sample in exploratory mode."
                )
                return
            self.explore_table.setRowCount(0)
            self.explore_table.setVisible(True)
            self.run_btn.setEnabled(False)
            self._disconnect_process_queue_thread_finished()
            max_runs = int(self.explore_max_runs.value())
            self._active_cluster_job_id = enqueue_process_queue_job(
                self.parent_app,
                "Exploring clusters",
                len(rows),
                lambda ev, ps, r=rows, fc=fp_choice, mr=max_runs, inc=include, ws=self.parent_app.signals: (
                    ClusterExploreWorker(
                        oid_mol_rows_from_payloads(r),
                        fc,
                        mr,
                        inc,
                        ws,
                        cancel_event=ev,
                        progress_state=ps,
                    )
                ),
                queue_label=f"Cluster explore ({len(rows)} rows, ≤{max_runs} trials)",
            )
            self.parent_app.process_queue.thread_finished.connect(
                self._on_process_queue_thread_finished
            )
            return

        method = str(self.method_combo.currentData() or "")
        if method == "kmeans":
            params = {"n_clusters": int(self.kmeans_k.value())}
        elif method == "agglomerative":
            params = {
                "n_clusters": int(self.agglom_k.value()),
                "linkage": self.linkage_combo.currentText().strip().lower(),
            }
        elif method == "dbscan":
            params = {
                "eps": float(self.dbscan_eps.value()),
                "min_samples": int(self.dbscan_min_samples.value()),
            }
        elif method == "butina":
            params = {
                "cutoff": float(self.butina_cutoff.value()),
                "reordering": bool(self.butina_reorder_cb.isChecked()),
            }
        elif method == "sphere_exclusion":
            params = {"cutoff": float(self.sphere_cutoff.value())}
        elif method == "jarvis_patrick":
            j_nn = int(self.jp_nn.value())
            p_c = int(self.jp_common.value())
            if p_c >= j_nn:
                QMessageBox.warning(
                    self,
                    "Cluster",
                    "Jarvis-Patrick requires shared neighbors (P) strictly less than nearest neighbors (J).",
                )
                return
            params = {"nn_count": j_nn, "common_neighbors": p_c}
        else:
            QMessageBox.warning(self, "Cluster", "Select a clustering method.")
            return

        col_name = self._unique_cluster_column()
        self._enqueue_cluster_worker(rows, fp_choice, method, params, col_name)

    def enable_run_after_job(self) -> None:
        """Call when the process queue finishes so the dialog can run again."""
        self.run_btn.setEnabled(True)
        self._sync_apply_explore_enabled()
