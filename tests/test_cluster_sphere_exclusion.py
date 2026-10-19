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

"""RDKit Leader sphere-exclusion clustering."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.workers.cluster_worker import cluster_sphere_exclusion


def test_sphere_exclusion_assigns_nearest_centroid():
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    labels = cluster_sphere_exclusion(fps, 0.25)
    assert labels is not None
    assert labels.shape[0] == 5
    assert len(set(int(x) for x in labels)) >= 2


def test_sphere_exclusion_high_cutoff_yields_many_clusters():
    smis = ["CCO", "CCC", "CCCC", "CCCCC"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    labels = cluster_sphere_exclusion(fps, 0.05)
    assert labels is not None
    assert len(set(int(x) for x in labels)) == 4


def test_butina_labels_match_rdkit_clusterdata():
    import numpy as np
    from rdkit import DataStructs
    from rdkit.ML.Cluster import Butina

    from molmanager.workers.cluster_worker import cluster_butina

    smis = ["CCO", "CCO", "CCCO", "CCCCO", "c1ccccc1", "Cc1ccccc1", "CC(=O)O", "CC(=O)OC"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    n = len(fps)
    dists: list[float] = []
    for i in range(n):
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        dists.extend(1.0 - float(sim) for sim in sims)
    for cutoff in (0.15, 0.4, 0.7):
        for reordering in (False, True):
            labels = cluster_butina(fps, cutoff, reordering=reordering)
            clusters = Butina.ClusterData(
                dists, nPts=n, distThresh=cutoff, isDistData=True, reordering=reordering
            )
            expected = np.full(n, -1, dtype=np.int32)
            for cid, group in enumerate(clusters):
                for idx in group:
                    expected[int(idx)] = int(cid)
            assert labels is not None
            assert list(labels) == list(expected)


def test_dense_fingerprint_matrix_stays_uint8():
    import numpy as np

    from molmanager.workers.cluster_worker import _dense_fingerprint_matrix

    fps = [
        AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 128)
        for s in ("CCO", "c1ccccc1")
    ]
    matrix = _dense_fingerprint_matrix(fps)
    assert matrix.dtype == np.uint8
    assert matrix.shape == (2, 128)
    assert set(np.unique(matrix)).issubset({0, 1})


def test_butina_and_jarvis_patrick_do_not_need_dense_matrix():
    from molmanager.workers.cluster_worker import (
        _method_needs_dense_matrix,
        cluster_butina,
        cluster_jarvis_patrick,
    )

    assert not _method_needs_dense_matrix("butina")
    assert not _method_needs_dense_matrix("jarvis_patrick")
    assert not _method_needs_dense_matrix("sphere_exclusion")
    assert _method_needs_dense_matrix("kmeans")
    smis = ["CCO", "CCCO", "c1ccccc1", "Cc1ccccc1"]
    fps = [AllChem.GetMorganFingerprintAsBitVect(Chem.MolFromSmiles(s), 2, 2048) for s in smis]
    butina = cluster_butina(fps, 0.4)
    assert butina is not None
    assert butina.shape[0] == 4
    jp = cluster_jarvis_patrick(fps, nn_count=2, common_neighbors=1)
    assert jp is not None
    assert jp.shape[0] == 4


def test_cluster_method_combo_uses_worker_keys(qapp):
    from molmanager.ui.dialogs.cluster import ClusterDialog
    from molmanager.workers.cluster_worker import CLUSTER_METHOD_LABELS

    dlg = ClusterDialog(None)
    try:
        keys = [dlg.method_combo.itemData(i) for i in range(dlg.method_combo.count())]
        assert keys == [k for k, _ in CLUSTER_METHOD_LABELS]
        dlg.method_combo.setCurrentIndex(keys.index("jarvis_patrick"))
        assert dlg.method_combo.currentData() == "jarvis_patrick"
        assert dlg._opt_stack.currentIndex() == dlg._method_pages["jarvis_patrick"]
    finally:
        dlg.close()
