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

"""Clustering on numeric columns and on fingerprints concatenated with them."""

from __future__ import annotations

import numpy as np
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidgetItem
from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.workers.cluster_worker import (
    ClusterExploreWorker,
    ClusterWorker,
    _combine_feature_matrix,
    _fit_matrix_off_gil,
    generate_explore_trials,
)
from molmanager.workers.signals import WorkerSignals


def _labels_by_oid(rows: list) -> dict[int, str]:
    return {int(oid): str(cols["Cluster"]) for oid, cols in rows}


def _run_worker(worker: ClusterWorker) -> dict[str, object]:
    out: dict[str, object] = {}
    worker.signals.calculated.connect(
        lambda rows, headers: out.update({"rows": rows, "headers": headers})
    )
    worker.signals.cluster_failed.connect(lambda msg: out.update({"failed": msg}))
    worker.run()
    return out


def test_numeric_kmeans_separates_two_property_groups():
    rows = [(oid, None) for oid in (1, 2, 3, 4)]
    numeric = {
        1: np.array([0.0, 0.0]),
        2: np.array([0.1, -0.05]),
        3: np.array([8.0, 8.0]),
        4: np.array([8.2, 7.9]),
    }
    out = _run_worker(
        ClusterWorker(
            rows,
            "",
            "kmeans",
            {"n_clusters": 2},
            "Cluster",
            WorkerSignals(),
            numeric_by_oid=numeric,
        )
    )
    assert "failed" not in out
    labels = _labels_by_oid(out["rows"])
    assert labels[1] == labels[2]
    assert labels[3] == labels[4]
    assert labels[1] != labels[3]


def test_mixed_features_drop_rows_without_numeric_values():
    smiles = {1: "CCO", 2: "CCN", 3: "c1ccccc1", 4: "CC(=O)O"}
    rows = []
    for oid, smi in smiles.items():
        mol = Chem.MolFromSmiles(smi)
        assert mol is not None
        rows.append((oid, mol))
    numeric = {
        1: np.array([0.0, 1.0]),
        2: np.array([0.2, 1.1]),
        3: np.array([5.0, 5.0]),
    }
    out = _run_worker(
        ClusterWorker(
            rows,
            "Morgan (r=2, n=1024)",
            "kmeans",
            {"n_clusters": 2},
            "Cluster",
            WorkerSignals(),
            numeric_by_oid=numeric,
        )
    )
    assert "failed" not in out
    labels = _labels_by_oid(out["rows"])
    assert set(labels) == {1, 2, 3}


def test_tanimoto_methods_reject_numeric_columns():
    out = _run_worker(
        ClusterWorker(
            [(1, None), (2, None)],
            "Morgan (r=2, n=1024)",
            "butina",
            {"cutoff": 0.4, "reordering": False},
            "Cluster",
            WorkerSignals(),
            numeric_by_oid={1: np.array([0.0]), 2: np.array([1.0])},
        )
    )
    assert "rows" not in out
    assert "Tanimoto" in str(out.get("failed"))


def test_combine_feature_matrix_balances_bit_variance():
    smiles = ["CCO", "c1ccccc1", "CC(=O)O", "CCN(CC)CC"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(smi), 2, 128) for smi in smiles]
    numeric = np.array([[0.0], [0.0], [10.0], [10.0]])
    matrix = _combine_feature_matrix(fps, numeric, standardize=True)
    assert matrix.shape == (4, 129)
    num_var = float(matrix[:, :1].var(axis=0).sum())
    bit_var = float(matrix[:, 1:].var(axis=0).sum())
    assert num_var > 0.0
    assert abs(num_var - bit_var) / num_var < 1e-6


def test_explore_trials_skip_tanimoto_methods_for_numeric_space():
    include = {
        "kmeans": True,
        "agglomerative": False,
        "dbscan": True,
        "butina": True,
        "sphere_exclusion": True,
        "jarvis_patrick": True,
    }
    trials = generate_explore_trials(30, 80, include, feature_space="numeric")
    methods = {method for method, _params in trials}
    assert methods == {"kmeans", "dbscan"}
    assert all(
        params.get("metric") == "euclidean" for method, params in trials if method == "dbscan"
    )
    fingerprint = generate_explore_trials(30, 80, include, feature_space="fingerprint")
    assert any(method == "butina" for method, _params in fingerprint)
    assert all("metric" not in params for method, params in fingerprint if method == "dbscan")


def test_numeric_explore_emits_sklearn_trials():
    rows = [(oid, None) for oid in range(1, 5)]
    numeric = {
        1: np.array([0.0, 0.0]),
        2: np.array([0.1, 0.0]),
        3: np.array([6.0, 6.0]),
        4: np.array([6.1, 5.9]),
    }
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.cluster_explore_finished.connect(lambda rows_: out.update({"rows": rows_}))
    sigs.cluster_failed.connect(lambda msg: out.update({"failed": msg}))
    worker = ClusterExploreWorker(
        rows,
        "",
        12,
        {
            "kmeans": True,
            "agglomerative": False,
            "dbscan": False,
            "butina": True,
            "sphere_exclusion": False,
            "jarvis_patrick": False,
        },
        sigs,
        numeric_by_oid=numeric,
    )
    worker.run()
    assert "failed" not in out
    results = out["rows"]
    assert results
    assert all(row["method"] == "kmeans" for row in results)
    assert all(row["notes"] == "" for row in results)
    assert {row["n_clusters"] for row in results} <= {2, 3}


def test_fit_matrix_off_gil_matches_in_process(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_DESCRIPTOR_FP_PROCESS_POOL_MIN_ROWS", "2")
    matrix = np.array([[0.0, 0.0], [0.1, 0.0], [5.0, 5.0], [5.2, 4.8]], dtype=np.float64)
    from molmanager.workers.cluster_worker import _fit_sklearn_labels

    direct = _fit_sklearn_labels(matrix, "kmeans", {"n_clusters": 2})
    off = _fit_matrix_off_gil("kmeans", {"n_clusters": 2}, matrix, None)
    assert [int(v) for v in off] == [int(v) for v in direct]


def test_cluster_dialog_disables_tanimoto_without_a_fingerprint(qapp):
    del qapp
    from molmanager.ui.dialogs.cluster import ClusterDialog

    dlg = ClusterDialog(None)
    try:
        assert dlg.fp_combo.currentText() == "Morgan (r=2, n=2048)"
        keys = [dlg.method_combo.itemData(i) for i in range(dlg.method_combo.count())]
        dlg.method_combo.setCurrentIndex(keys.index("jarvis_patrick"))
        dlg.fp_combo.setCurrentIndex(0)
        assert dlg.fp_combo.currentText() == "None"
        assert dlg.method_combo.currentData() == "kmeans"
        assert not dlg.method_combo.model().item(keys.index("butina")).isEnabled()
        assert not dlg._ex_butina.isEnabled()
        assert not dlg.src_combo.isEnabled()
        assert abs(dlg.dbscan_eps.value() - 1.5) < 1e-9

        dlg.fp_combo.setCurrentIndex(1)
        assert dlg.method_combo.model().item(keys.index("butina")).isEnabled()
        assert dlg._ex_sphere.isEnabled()
        assert abs(dlg.dbscan_eps.value() - 0.35) < 1e-9

        item = QListWidgetItem("MW")
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(Qt.Checked)
        dlg.column_list.addItem(item)
        dlg._sync_feature_controls()
        assert not dlg.method_combo.model().item(keys.index("jarvis_patrick")).isEnabled()
        assert not dlg._ex_jp.isEnabled()
        assert abs(dlg.dbscan_eps.value() - 1.5) < 1e-9
    finally:
        dlg.close()


def test_method_box_shrinks_to_the_selected_method(qapp):
    from PyQt5.QtGui import QColor, QPalette

    from molmanager.ui.dialogs.cluster import ClusterDialog
    from molmanager.ui.qt_widget_utils import group_box_stylesheet

    palette = QPalette()
    palette.setColor(QPalette.Window, QColor("#f0f0f0"))
    palette.setColor(QPalette.Mid, QColor("#777777"))
    sheet = group_box_stylesheet(palette)
    assert "transparent" not in sheet
    assert "#fff0f0f0" not in sheet.split("QGroupBox::title")[0]
    dlg = ClusterDialog(None)
    dlg.show()
    qapp.processEvents()
    try:
        keys = [dlg.method_combo.itemData(i) for i in range(dlg.method_combo.count())]
        dlg.method_combo.setCurrentIndex(keys.index("kmeans"))
        qapp.processEvents()
        kmeans_page = dlg._opt_stack.sizeHint().height()
        kmeans_window = dlg.height()
        dlg.method_combo.setCurrentIndex(keys.index("jarvis_patrick"))
        qapp.processEvents()
        assert dlg._opt_stack.sizeHint().height() > kmeans_page
        assert dlg.height() > kmeans_window
        dlg.method_combo.setCurrentIndex(keys.index("kmeans"))
        qapp.processEvents()
        assert dlg._opt_stack.sizeHint().height() == kmeans_page
        assert dlg.height() == kmeans_window
    finally:
        dlg.close()
