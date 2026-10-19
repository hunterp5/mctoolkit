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

"""Cluster table rows by fingerprint, numeric columns, or both.

Fingerprint-only clustering keeps Tanimoto methods (Butina, sphere exclusion,
Jarvis–Patrick) and scikit-learn methods on the bit matrix. Numeric columns,
alone or concatenated with a fingerprint, use K-Means, agglomerative clustering,
and DBSCAN.
"""

from __future__ import annotations

import logging
import multiprocessing
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import (
    FIRST_COMPLETED,
    ProcessPoolExecutor,
    TimeoutError as FuturesTimeout,
    wait,
)

import numpy as np
from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit import DataStructs
from rdkit.SimDivFilters.rdSimDivPickers import LeaderPicker

from ..chem.fingerprint_cache import get as cache_get
from ..chem.fingerprint_cache import store as cache_store
from ..chem.rdkit_fingerprints import (
    fingerprint_bitvect_for_row,
    fingerprint_is_gil_heavy,
    spec_for_label,
)
from ..platform_support.config import load_config
from .fingerprint_similarity import fingerprint_bitvect_for_ui_choice
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import emit_partial_results_if_cancelled

logger = logging.getLogger(__name__)


_SKLEARN_CLUSTER_METHODS = frozenset({"kmeans", "agglomerative", "dbscan"})
TANIMOTO_CLUSTER_METHODS = frozenset({"butina", "sphere_exclusion", "jarvis_patrick"})
_FP_NONE_LABELS = frozenset({"", "none"})

# Euclidean DBSCAN radii for standardized descriptor space. Cosine radii below
# stay tuned to fingerprint bit vectors.
_DBSCAN_EUCLIDEAN_EPS = (0.6, 1.0, 1.5, 2.0, 2.8, 3.6)

# Fingerprints for exploratory trials, installed once in the child process.
_CHILD_FPS: list | None = None
_CHILD_X: np.ndarray | None = None

# Combo labels (and explore-table short names) for each worker method key.
CLUSTER_METHOD_LABELS: tuple[tuple[str, str], ...] = (
    ("kmeans", "K-Means"),
    ("agglomerative", "Agglomerative"),
    ("dbscan", "DBSCAN (cosine)"),
    ("butina", "Butina (Tanimoto distance)"),
    ("sphere_exclusion", "Sphere exclusion (RDKit Leader)"),
    ("jarvis_patrick", "Jarvis-Patrick"),
)
CLUSTER_METHOD_SHORT_LABELS: dict[str, str] = {
    "kmeans": "K-Means",
    "agglomerative": "Agglomerative",
    "dbscan": "DBSCAN",
    "butina": "Butina",
    "sphere_exclusion": "Sphere exclusion",
    "jarvis_patrick": "Jarvis-Patrick",
}


def _bitvect_to_numpy(fp) -> np.ndarray:
    """0/1 bytes. sklearn call sites upcast; the retained matrix stays uint8."""
    from ..chem.rdkit_fingerprints import bitvect_to_uint8

    return bitvect_to_uint8(fp)


def _dense_fingerprint_matrix(fps: Sequence) -> np.ndarray:
    if not fps:
        return np.zeros((0, 0), dtype=np.uint8)
    return np.vstack([_bitvect_to_numpy(fp) for fp in fps])


def _as_sklearn_features(X: np.ndarray) -> np.ndarray:
    """Float64 view for sklearn. No copy when the matrix is already float64."""
    if X.dtype == np.float64:
        return X
    return np.asarray(X, dtype=np.float64)


def _method_needs_dense_matrix(method: str) -> bool:
    return str(method) in _SKLEARN_CLUSTER_METHODS


def fingerprint_requested(fp_choice: str | None) -> bool:
    """False when the dialog chose numeric columns without a fingerprint."""
    return (fp_choice or "").strip().lower() not in _FP_NONE_LABELS


def _align_numeric_rows(
    oids: Sequence[int],
    fps: Sequence | None,
    numeric_by_oid: dict[int, np.ndarray],
) -> tuple[list[int], list | None, np.ndarray | None]:
    """Keep rows that have a finite numeric vector, in ``oids`` order."""
    kept_oids: list[int] = []
    kept_fps: list = []
    vectors: list[np.ndarray] = []
    if fps is None:
        pairs: Sequence[tuple[int, object | None]] = [(int(oid), None) for oid in oids]
    else:
        pairs = [(int(oid), fp) for oid, fp in zip(oids, fps)]
    for oid, fp in pairs:
        raw = numeric_by_oid.get(int(oid))
        if raw is None:
            continue
        vector = np.asarray(raw, dtype=np.float64)
        if vector.ndim != 1 or vector.size == 0 or not np.isfinite(vector).all():
            continue
        kept_oids.append(int(oid))
        if fps is not None:
            kept_fps.append(fp)
        vectors.append(vector)
    if not vectors:
        return [], ([] if fps is not None else None), None
    numeric = np.vstack(vectors)
    return kept_oids, (kept_fps if fps is not None else None), numeric


def _combine_feature_matrix(
    fps: Sequence | None,
    numeric: np.ndarray,
    *,
    standardize: bool,
) -> np.ndarray:
    """Euclidean feature matrix for scikit-learn methods.

    Numeric columns are standardized when requested. When a fingerprint is
    concatenated, the bit block is rescaled so its total variance matches the
    numeric block. Otherwise the bits dominate the distance.
    """
    numeric_block = np.array(numeric, dtype=np.float64, copy=True)
    n_numeric = int(numeric_block.shape[1])
    if standardize and n_numeric > 0:
        from ..descriptors.ml_feature_matrix import standardize_feature_matrix

        numeric_block, _scaler = standardize_feature_matrix(numeric_block, n_numeric, enabled=True)
    if not fps:
        return numeric_block
    bits = np.asarray(_dense_fingerprint_matrix(fps), dtype=np.float64)
    num_var = float(numeric_block.var(axis=0).sum())
    bit_var = float(bits.var(axis=0).sum())
    if num_var > 0.0 and bit_var > 0.0:
        bits *= np.sqrt(num_var / bit_var)
    return np.hstack([numeric_block, bits])


def _tanimoto_with_numeric_message() -> str:
    return (
        "Butina, sphere exclusion, and Jarvis-Patrick use fingerprint Tanimoto "
        "distance. Clear the numeric columns, or choose K-Means, Agglomerative, or DBSCAN."
    )


def _butina_neighbor_lists(
    fps: Sequence,
    dist_cutoff: float,
    cancel_event: threading.Event | None = None,
) -> list[list[int]] | None:
    """Indexes within ``dist_cutoff`` (1 - Tanimoto), including self.

    RDKit ``ClusterData`` turns a condensed distance list into an n×n float64 matrix
    before it builds these same lists. Keeping only the neighbors avoids both.
    """
    n = len(fps)
    cutoff = float(dist_cutoff)
    # Diagonal distance is 0, so self is a neighbor only when the cutoff is non-negative.
    neighbors: list[list[int]] = [([i] if cutoff >= 0.0 else []) for i in range(n)]
    for i in range(1, n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps[:i])
        for j, sim in enumerate(sims):
            dist = 1.0 - float(sim)
            if dist < 0.0:
                dist = 0.0
            elif dist > 1.0:
                dist = 1.0
            if dist <= cutoff:
                neighbors[i].append(j)
                neighbors[j].append(i)
    for group in neighbors:
        group.sort()
    return neighbors


def _clusters_from_neighbor_lists(
    neighbor_lists: list[list[int]],
    *,
    reordering: bool,
) -> tuple[tuple[int, ...], ...]:
    """Same selection order as ``rdkit.ML.Cluster.Butina.ClusterData``."""
    n_pts = len(neighbor_lists)
    sorted_indices = [(len(group), idx) for idx, group in enumerate(neighbor_lists)]
    sorted_indices.sort(reverse=True)
    clusters: list[tuple[int, ...]] = []
    seen = np.zeros(n_pts, dtype=bool)
    while sorted_indices and sorted_indices[0][0] > 1:
        _, idx = sorted_indices.pop(0)
        if seen[idx]:
            continue
        cluster = [idx]
        seen[idx] = True
        for neighbor in neighbor_lists[idx]:
            if not seen[neighbor]:
                cluster.append(neighbor)
                seen[neighbor] = True
        clusters.append(tuple(cluster))
        if not reordering:
            continue
        affected = {
            neighbor
            for point in cluster
            for neighbor in neighbor_lists[point]
            if not seen[neighbor]
        }
        for ii, element in enumerate(sorted_indices):
            affected_point = element[1]
            if affected_point in affected:
                new_neighbors = [nbr for nbr in neighbor_lists[affected_point] if not seen[nbr]]
                neighbor_lists[affected_point] = new_neighbors
                sorted_indices[ii] = (len(new_neighbors), affected_point)
        sorted_indices.sort(reverse=True)
    while sorted_indices:
        _, idx = sorted_indices.pop(0)
        if seen[idx]:
            continue
        clusters.append((idx,))
    return tuple(clusters)


def _labels_from_butina_clusters(clusters: tuple[tuple[int, ...], ...], n: int) -> np.ndarray:
    lab = np.full((n,), -1, dtype=np.int32)
    for cid, group in enumerate(clusters):
        for idx in group:
            lab[int(idx)] = int(cid)
    return lab


def cluster_butina(
    fps: Sequence,
    dist_cutoff: float,
    *,
    reordering: bool = False,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """Butina sphere-exclusion on Tanimoto distance (1 - similarity)."""
    n = len(fps)
    if n < 2:
        return None
    if cancel_event is not None and cancel_event.is_set():
        return None
    neighbors = _butina_neighbor_lists(fps, dist_cutoff, cancel_event=cancel_event)
    if neighbors is None:
        return None
    clusters = _clusters_from_neighbor_lists(neighbors, reordering=bool(reordering))
    return _labels_from_butina_clusters(clusters, n)


def _leader_sphere_centroids(
    fps: Sequence,
    threshold: float,
    *,
    cancel_event: threading.Event | None = None,
) -> list[int] | None:
    """RDKit :class:`LeaderPicker` centroids (minimum Tanimoto distance ``threshold`` between leaders)."""
    n = len(fps)
    if n < 1:
        return []
    if cancel_event is not None and cancel_event.is_set():
        return None
    lp = LeaderPicker()
    try:
        return [int(i) for i in lp.LazyBitVectorPick(fps, n, float(threshold))]
    except Exception:
        logger.debug("LazyBitVectorPick failed; falling back to LazyPick", exc_info=True)

    def dist(i: int, j: int) -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise _ClusterCancelled()
        if i == j:
            return 0.0
        return _tanimoto_distance(fps[i], fps[j])

    try:
        return [int(i) for i in lp.LazyPick(distFunc=dist, poolSize=n, threshold=float(threshold))]
    except _ClusterCancelled:
        return None


class _ClusterCancelled(Exception):
    pass


def _tanimoto_distance(fp_i, fp_j) -> float:
    s = float(DataStructs.TanimotoSimilarity(fp_i, fp_j))
    d = 1.0 - s
    if d < 0.0:
        return 0.0
    if d > 1.0:
        return 1.0
    return d


def cluster_sphere_exclusion(
    fps: Sequence,
    dist_cutoff: float,
    *,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """
    Sphere exclusion clustering (RDKit Leader / Sayle): pick cluster centroids with
    :meth:`LeaderPicker.LazyBitVectorPick`, then assign each compound to its nearest centroid.
    """
    n = len(fps)
    if n < 2:
        return None
    if cancel_event is not None and cancel_event.is_set():
        return None
    try:
        centroid_idxs = _leader_sphere_centroids(fps, float(dist_cutoff), cancel_event=cancel_event)
    except _ClusterCancelled:
        return None
    if centroid_idxs is None:
        return None
    if not centroid_idxs:
        return np.zeros((n,), dtype=np.int32)

    cid_map = {int(idx): int(cid) for cid, idx in enumerate(centroid_idxs)}
    cent_fps = [fps[int(i)] for i in centroid_idxs]
    labels = np.zeros((n,), dtype=np.int32)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        if i in cid_map:
            labels[i] = cid_map[i]
            continue
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], cent_fps)
        labels[i] = int(np.argmax(sims))
    return labels


class _DSU:
    __slots__ = ("p", "r")

    def __init__(self, n: int) -> None:
        self.p = list(range(n))
        self.r = [0] * n

    def find(self, x: int) -> int:
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a: int, b: int) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return
        if self.r[ra] < self.r[rb]:
            self.p[ra] = rb
        elif self.r[ra] > self.r[rb]:
            self.p[rb] = ra
        else:
            self.p[rb] = ra
            self.r[ra] += 1


def cluster_jarvis_patrick(
    fps: Sequence,
    nn_count: int,
    common_neighbors: int,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    """
    Jarvis–Patrick: link i,j if they share at least ``common_neighbors`` of their
    ``nn_count`` nearest neighbors (by Tanimoto similarity).
    """
    n = len(fps)
    if n < 2:
        return None
    j_nn = int(nn_count)
    p_req = int(common_neighbors)
    j_nn = max(1, min(j_nn, n - 1))
    p_req = max(1, min(p_req, j_nn))

    neighbors: list[set[int]] = []
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        sims = DataStructs.BulkTanimotoSimilarity(fps[i], fps)
        sim_arr = np.asarray(sims, dtype=np.float64)
        order = np.argsort(-sim_arr)
        neigh: list[int] = []
        for idx in order:
            ii = int(idx)
            if ii == i:
                continue
            neigh.append(ii)
            if len(neigh) >= j_nn:
                break
        neighbors.append(set(neigh))

    dsu = _DSU(n)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            return None
        for j in range(i + 1, n):
            if len(neighbors[i] & neighbors[j]) >= p_req:
                dsu.union(i, j)

    root_to_label: dict[int, int] = {}
    labels = np.zeros((n,), dtype=np.int32)
    next_lab = 0
    for i in range(n):
        r = dsu.find(i)
        if r not in root_to_label:
            root_to_label[r] = next_lab
            next_lab += 1
        labels[i] = root_to_label[r]
    return labels


def _fit_sklearn_labels(X: np.ndarray, method: str, params: dict) -> np.ndarray:
    from sklearn.cluster import AgglomerativeClustering, DBSCAN, KMeans

    n_samples = X.shape[0]
    if method == "kmeans":
        k = int(params.get("n_clusters", 5))
        k = max(2, min(k, n_samples))
        model = KMeans(n_clusters=k, random_state=42, n_init=10)
        return model.fit_predict(_as_sklearn_features(X))
    if method == "agglomerative":
        k = int(params.get("n_clusters", 5))
        k = max(2, min(k, n_samples))
        linkage = str(params.get("linkage", "average"))
        model = AgglomerativeClustering(n_clusters=k, linkage=linkage)
        return model.fit_predict(_as_sklearn_features(X))
    eps = float(params.get("eps", 0.35))
    ms = int(params.get("min_samples", 5))
    ms = max(2, min(ms, n_samples))
    metric = str(params.get("metric") or "cosine")
    model = DBSCAN(eps=eps, min_samples=ms, metric=metric)
    return model.fit_predict(_as_sklearn_features(X))


def _run_clustering(
    method: str,
    params: dict,
    *,
    X: np.ndarray | None,
    fps: Sequence,
    cancel_event: threading.Event | None = None,
) -> np.ndarray | None:
    if method == "butina":
        return cluster_butina(
            fps,
            float(params.get("cutoff", 0.25)),
            reordering=bool(params.get("reordering", False)),
            cancel_event=cancel_event,
        )
    if method == "sphere_exclusion":
        return cluster_sphere_exclusion(
            fps,
            float(params.get("cutoff", 0.35)),
            cancel_event=cancel_event,
        )
    if method == "jarvis_patrick":
        return cluster_jarvis_patrick(
            fps,
            int(params.get("nn_count", 16)),
            int(params.get("common_neighbors", 8)),
            cancel_event=cancel_event,
        )
    if X is None:
        raise ValueError(f"{method} clustering requires a feature matrix.")
    return _fit_sklearn_labels(X, method, params)


def _summarize_partition(labels: np.ndarray, X: np.ndarray | None) -> dict[str, float | int | None]:
    n = int(labels.shape[0])
    noise_ct = int(np.sum(labels == -1))
    non_noise_mask = labels >= 0
    n_eff = int(np.sum(non_noise_mask))
    if noise_ct:
        if n_eff == 0:
            n_clusters = 0
            largest_pct: float | None = None
        else:
            n_clusters = int(len(np.unique(labels[non_noise_mask])))
            uids, cnts = np.unique(labels[non_noise_mask], return_counts=True)
            largest_pct = float(np.max(cnts)) / float(max(n_eff, 1)) * 100.0
    else:
        uniq, counts = np.unique(labels, return_counts=True)
        n_clusters = int(len(uniq))
        largest_pct = float(np.max(counts)) / float(max(n, 1)) * 100.0

    sil: float | None = None
    if X is not None and n >= 3 and n_clusters >= 2:
        try:
            from sklearn.metrics import silhouette_score

            features = _as_sklearn_features(X)
            if noise_ct:
                if n_eff >= 3:
                    xm = non_noise_mask
                    lab_sub = labels[xm]
                    sil = float(silhouette_score(features[xm], lab_sub, metric="euclidean"))
            else:
                sil = float(silhouette_score(features, labels, metric="euclidean"))
        except Exception:
            sil = None

    return {
        "n_clusters": n_clusters,
        "noise_pct": float(noise_ct) / float(max(n, 1)) * 100.0,
        "largest_pct": largest_pct,
        "silhouette": sil,
    }


def _spread_integers(lo: int, hi: int, count: int) -> list[int]:
    if hi < lo:
        return []
    if lo == hi:
        return [lo]
    count = max(1, count)
    xs = np.linspace(lo, hi, num=min(count, hi - lo + 1))
    out: list[int] = []
    seen: set[int] = set()
    for v in xs:
        k = int(round(float(v)))
        k = max(lo, min(hi, k))
        if k not in seen:
            seen.add(k)
            out.append(k)
    return sorted(out)


def generate_explore_trials(
    n: int,
    max_runs: int,
    include: dict[str, bool],
    *,
    feature_space: str = "fingerprint",
) -> list[tuple[str, dict]]:
    """Build a bounded list of (method, params) trials for exploratory mode.

    ``feature_space`` is ``fingerprint`` (Tanimoto methods allowed, cosine DBSCAN),
    or ``numeric`` / ``mixed`` (scikit-learn methods only, Euclidean DBSCAN).
    """
    trials: list[tuple[str, dict]] = []
    cap_k = max(2, min(n - 1, 80))
    fingerprint_space = feature_space == "fingerprint"

    if include.get("kmeans", True):
        for k in _spread_integers(2, min(cap_k, 40), 8):
            trials.append(("kmeans", {"n_clusters": k}))

    if include.get("agglomerative", True):
        for linkage in ("average", "complete"):
            for k in _spread_integers(2, min(cap_k, 40), 5):
                trials.append(("agglomerative", {"n_clusters": k, "linkage": linkage}))

    if include.get("dbscan", True):
        if fingerprint_space:
            eps_values = (0.12, 0.18, 0.25, 0.32, 0.4, 0.5)
        else:
            eps_values = _DBSCAN_EUCLIDEAN_EPS
        for eps in eps_values:
            for ms in (3, 5, 8):
                params: dict = {"eps": float(eps), "min_samples": int(ms)}
                if not fingerprint_space:
                    params["metric"] = "euclidean"
                trials.append(("dbscan", params))

    if fingerprint_space and include.get("butina", True):
        for c in np.linspace(0.08, 0.45, num=8):
            trials.append(("butina", {"cutoff": float(c), "reordering": False}))
        trials.append(("butina", {"cutoff": 0.25, "reordering": True}))

    if fingerprint_space and include.get("sphere_exclusion", True):
        for c in np.linspace(0.15, 0.65, num=8):
            trials.append(("sphere_exclusion", {"cutoff": float(c)}))

    if fingerprint_space and include.get("jarvis_patrick", True):
        for j_nn, p_common in ((10, 4), (12, 5), (14, 6), (16, 8), (20, 10), (24, 12)):
            if p_common < j_nn < n:
                trials.append(("jarvis_patrick", {"nn_count": j_nn, "common_neighbors": p_common}))

    out: list[tuple[str, dict]] = []
    seen: set[tuple[str, str]] = set()
    for m, p in trials:
        key = (m, repr(sorted(p.items())) if p else "")
        if key in seen:
            continue
        seen.add(key)
        out.append((m, dict(p)))

    return out[: max(1, max_runs)]


def _format_params(method: str, params: dict) -> str:
    if method == "kmeans":
        return f"k={int(params['n_clusters'])}"
    if method == "agglomerative":
        return f"k={int(params['n_clusters'])}, {params.get('linkage', 'average')}"
    if method == "dbscan":
        metric = str(params.get("metric") or "")
        suffix = f", {metric}" if metric and metric != "cosine" else ""
        return f"eps={float(params['eps']):.3f}, min_samples={int(params['min_samples'])}{suffix}"
    if method == "butina":
        r = ", reorder" if params.get("reordering") else ""
        return f"cutoff={float(params.get('cutoff', 0.2)):.3f}{r}"
    if method == "sphere_exclusion":
        return f"cutoff={float(params.get('cutoff', 0.35)):.3f}"
    if method == "jarvis_patrick":
        return f"NN={int(params['nn_count'])}, common≥{int(params['common_neighbors'])}"
    return repr(params)


class _PoolCancelled(Exception):
    """Parent stopped waiting because the job was cancelled."""


def _cluster_process_min_rows() -> int:
    """Row count at which fingerprint and fit work move to child processes."""
    return int(load_config().descriptor_fp_process_pool_min_rows)


def _use_fp_process_pool(n_rows: int, fp_choice: str) -> bool:
    """True when fingerprint generation should leave the GUI process.

    RDKit fingerprint code holds the GIL. Gobbi pharmacophore fingerprints do so
    for a long time per molecule; other types do once the table is large.
    """
    n = int(n_rows)
    if n < 2:
        return False
    if fingerprint_is_gil_heavy(fp_choice):
        return True
    return n >= _cluster_process_min_rows()


def _use_fit_process_pool(n_fps: int) -> bool:
    """True when clustering itself should leave the GUI process.

    Butina, LeaderPicker, Jarvis–Patrick, and scikit-learn fits hold the GIL for
    the whole call. A child process lets the Qt thread keep running. The threshold
    is capped so a high descriptor-fingerprint setting cannot leave a large fit
    on the GUI interpreter.
    """
    threshold = min(_cluster_process_min_rows(), 64)
    return int(n_fps) >= max(2, threshold)


def _spawn_context() -> multiprocessing.context.BaseContext:
    # Spawn (not fork) so the child does not inherit the Qt GUI state.
    return multiprocessing.get_context("spawn")


def _process_workers(n_tasks: int) -> int:
    cpu = max(2, (os.cpu_count() or 4) - 1)
    return max(1, min(cpu, 8, int(n_tasks)))


def _wait_future(
    fut,
    cancel_event: threading.Event | None,
    pulse: Callable[[], None] | None = None,
):
    """Block on *fut* without holding the GIL between timeout slices."""
    while True:
        if should_terminate_process_pool(cancel_event):
            raise _PoolCancelled()
        try:
            return fut.result(timeout=0.25)
        except FuturesTimeout:
            if pulse is not None:
                pulse()


def _explore_record(
    method: str,
    params: dict,
    *,
    stats: dict | None = None,
    notes: str = "",
) -> dict:
    sil = None if stats is None else stats.get("silhouette")
    largest = None if stats is None else stats.get("largest_pct")
    noise = None if stats is None else stats.get("noise_pct")
    return {
        "method": method,
        "params": dict(params),
        "settings": _format_params(method, params),
        "n_clusters": None if stats is None else stats.get("n_clusters"),
        "silhouette": None if sil is None else round(float(sil), 4),
        "largest_pct": None if largest is None else round(float(largest), 2),
        "noise_pct": None if noise is None else round(float(noise), 2),
        "notes": notes,
    }


def _fingerprints_from_index(
    rows: Sequence[tuple[int, Chem.Mol]],
    fp_by_index: Sequence,
    *,
    cancelled: bool,
) -> tuple[list[int], list, bool]:
    oids: list[int] = []
    fps: list = []
    for (oid, _mol), fp in zip(rows, fp_by_index):
        if fp is None:
            continue
        oids.append(int(oid))
        fps.append(fp)
    return oids, fps, cancelled


def _collect_fingerprints_inline(
    rows: Sequence[tuple[int, Chem.Mol]],
    fp_choice: str,
    *,
    cancel_event: threading.Event | None,
    on_progress: Callable[[int, int], None] | None,
) -> tuple[list[int], list, bool]:
    """In-process fingerprints. One cancel check per row, before that row is computed."""
    oids: list[int] = []
    fps: list = []
    tot = max(len(rows), 1)
    cancelled = False
    for i, (oid, mol) in enumerate(rows, start=1):
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
            break
        if on_progress is not None:
            on_progress(i, tot)
        try:
            fp = fingerprint_bitvect_for_row(int(oid), mol, fp_choice)
            if fp is None:
                fp = fingerprint_bitvect_for_ui_choice(mol, fp_choice)
        except Exception:
            fp = None
        if fp is None:
            continue
        try:
            fps.append(fp)
            oids.append(int(oid))
        except Exception:
            logger.debug("Fingerprint conversion failed for oid=%s", oid, exc_info=True)
    return oids, fps, cancelled


def _mp_cluster_fp_batch(args: tuple) -> list[tuple[int, object | None]]:
    """Fingerprints for one batch of ``(row_index, mol_bytes)`` in a child process."""
    items, fp_choice = args
    out: list[tuple[int, object | None]] = []
    for idx, mol_bytes in items:
        if not mol_bytes:
            out.append((int(idx), None))
            continue
        try:
            mol = Chem.Mol(mol_bytes)
            fp = fingerprint_bitvect_for_ui_choice(mol, str(fp_choice)) if mol is not None else None
        except Exception:
            fp = None
        out.append((int(idx), fp))
    return out


def _collect_fingerprints_pooled(
    rows: Sequence[tuple[int, Chem.Mol]],
    fp_choice: str,
    *,
    cancel_event: threading.Event | None,
    on_progress: Callable[[int, int], None] | None,
) -> tuple[list[int], list, bool]:
    """Compute missing fingerprints in child processes. The parent only waits."""
    n = len(rows)
    spec = spec_for_label(fp_choice)
    internal_key = spec.internal_key if spec is not None else ""
    fp_by_index: list = [None] * n
    missing: list[tuple[int, bytes]] = []
    done = 0
    for i, (oid, mol) in enumerate(rows):
        if cancel_event is not None and cancel_event.is_set():
            return _fingerprints_from_index(rows, fp_by_index, cancelled=True)
        cached = cache_get(int(oid), internal_key) if internal_key else None
        if cached is not None:
            fp_by_index[i] = cached
            done += 1
            if on_progress is not None:
                on_progress(done, n)
            continue
        blob = b""
        if mol is not None:
            try:
                blob = mol.ToBinary()
            except Exception:
                blob = b""
        missing.append((i, blob))

    if not missing:
        return _fingerprints_from_index(rows, fp_by_index, cancelled=False)

    batch_size = max(1, int(load_config().descriptor_process_pool_batch_size))
    batches = [missing[s : s + batch_size] for s in range(0, len(missing), batch_size)]
    ex = register_process_pool(
        ProcessPoolExecutor(
            max_workers=_process_workers(len(batches)),
            mp_context=_spawn_context(),
        )
    )
    cancelled = False
    try:
        pending = {ex.submit(_mp_cluster_fp_batch, (batch, fp_choice)): batch for batch in batches}
        while pending:
            if should_terminate_process_pool(cancel_event):
                cancelled = True
                break
            completed, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
            if not completed:
                if on_progress is not None:
                    on_progress(done, max(n, 1))
                continue
            for fut in completed:
                if fut.cancelled():
                    continue
                for idx, fp in fut.result():
                    done += 1
                    if fp is None:
                        continue
                    fp_by_index[int(idx)] = fp
                    if internal_key:
                        cache_store(int(rows[int(idx)][0]), internal_key, fp)
                if on_progress is not None:
                    on_progress(min(done, n), max(n, 1))
    finally:
        shutdown_process_pool_executor(
            ex,
            kill_workers=cancelled or should_terminate_process_pool(cancel_event),
        )
    return _fingerprints_from_index(rows, fp_by_index, cancelled=cancelled)


def _collect_fingerprints(
    rows: Sequence[tuple[int, Chem.Mol]],
    fp_choice: str,
    *,
    cancel_event: threading.Event | None,
    on_progress: Callable[[int, int], None] | None,
) -> tuple[list[int], list, bool]:
    if _use_fp_process_pool(len(rows), fp_choice):
        return _collect_fingerprints_pooled(
            rows,
            fp_choice,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
    return _collect_fingerprints_inline(
        rows,
        fp_choice,
        cancel_event=cancel_event,
        on_progress=on_progress,
    )


def _mp_fit_labels(args: tuple) -> np.ndarray:
    """Cluster in a child process. Returns labels aligned with *fps*."""
    method, params, fps = args
    x = _dense_fingerprint_matrix(fps) if _method_needs_dense_matrix(method) else None
    labels = _run_clustering(method, params, X=x, fps=fps, cancel_event=None)
    if labels is None:
        raise RuntimeError("Clustering produced no labels.")
    return labels


def _fit_labels_off_gil(
    method: str,
    params: dict,
    fps: Sequence,
    cancel_event: threading.Event | None,
    *,
    on_wait: Callable[[], None] | None = None,
) -> np.ndarray:
    ex = register_process_pool(ProcessPoolExecutor(max_workers=1, mp_context=_spawn_context()))
    try:
        fut = ex.submit(_mp_fit_labels, (method, dict(params), list(fps)))
        return _wait_future(fut, cancel_event, on_wait)
    finally:
        shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(cancel_event))


def _mp_fit_matrix(args: tuple) -> np.ndarray:
    """Cluster a prepared feature matrix in a child process."""
    method, params, matrix = args
    labels = _run_clustering(method, params, X=matrix, fps=[], cancel_event=None)
    if labels is None:
        raise RuntimeError("Clustering produced no labels.")
    return labels


def _fit_matrix_off_gil(
    method: str,
    params: dict,
    matrix: np.ndarray,
    cancel_event: threading.Event | None,
    *,
    on_wait: Callable[[], None] | None = None,
) -> np.ndarray:
    ex = register_process_pool(ProcessPoolExecutor(max_workers=1, mp_context=_spawn_context()))
    try:
        fut = ex.submit(_mp_fit_matrix, (method, dict(params), matrix))
        return _wait_future(fut, cancel_event, on_wait)
    finally:
        shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(cancel_event))


def _assign_cluster_labels(
    method: str,
    params: dict,
    fps: Sequence,
    *,
    cancel_event: threading.Event | None,
    on_wait: Callable[[], None] | None = None,
    features: np.ndarray | None = None,
) -> np.ndarray | None:
    # A large partial set (fingerprint collection already cancelled) still has to run
    # off the GIL. Pass cancel_event=None in that case so the fit is not killed immediately.
    if features is not None:
        if _use_fit_process_pool(int(features.shape[0])):
            return _fit_matrix_off_gil(method, params, features, cancel_event, on_wait=on_wait)
        return _run_clustering(method, params, X=features, fps=fps, cancel_event=cancel_event)
    if _use_fit_process_pool(len(fps)):
        return _fit_labels_off_gil(method, params, fps, cancel_event, on_wait=on_wait)
    x = _dense_fingerprint_matrix(fps) if _method_needs_dense_matrix(method) else None
    return _run_clustering(method, params, X=x, fps=fps, cancel_event=cancel_event)


def _mp_init_cluster_fps(fps: list) -> None:
    global _CHILD_FPS, _CHILD_X
    _CHILD_FPS = fps
    _CHILD_X = None


def _mp_explore_trial(args: tuple) -> dict:
    """One exploratory trial inside the fingerprint child process."""
    global _CHILD_X
    method, params, build_matrix = args
    fps = _CHILD_FPS or []
    try:
        if build_matrix and _CHILD_X is None:
            _CHILD_X = _dense_fingerprint_matrix(fps)
        x_stats = _CHILD_X if build_matrix else None
        x_fit = x_stats if method in _SKLEARN_CLUSTER_METHODS else None
        labels = _run_clustering(method, params, X=x_fit, fps=fps, cancel_event=None)
    except Exception as exc:
        return _explore_record(method, params, notes=str(exc)[:120])
    if labels is None:
        return _explore_record(method, params, notes="Clustering produced no labels.")
    return _explore_record(method, params, stats=_summarize_partition(labels, x_stats))


def _explore_trials_inline(
    fps: Sequence,
    trials: Sequence[tuple[str, dict]],
    *,
    cancel_event: threading.Event | None,
    on_trial: Callable[[int, int], None] | None,
    features: np.ndarray | None = None,
) -> tuple[list[dict], bool]:
    needs_x = any(method in _SKLEARN_CLUSTER_METHODS for method, _params in trials)
    if features is not None:
        x = features
    else:
        x = _dense_fingerprint_matrix(fps) if needs_x else None
    n_trials = max(len(trials), 1)
    results: list[dict] = []
    for method, params in trials:
        if cancel_event is not None and cancel_event.is_set():
            return results, True
        if on_trial is not None:
            on_trial(len(results) + 1, n_trials)
        try:
            labels = _run_clustering(method, params, X=x, fps=fps, cancel_event=cancel_event)
        except Exception as exc:
            logger.debug("Explore trial failed: %s %s", method, params, exc_info=True)
            results.append(_explore_record(method, params, notes=str(exc)[:120]))
            continue
        if labels is None:
            return results, True
        results.append(_explore_record(method, params, stats=_summarize_partition(labels, x)))
    return results, False


def _explore_trials_off_gil(
    fps: Sequence,
    trials: Sequence[tuple[str, dict]],
    *,
    cancel_event: threading.Event | None,
    on_trial: Callable[[int, int], None] | None,
) -> tuple[list[dict], bool]:
    """Run exploratory trials in one child so each fit does not hold the GUI GIL."""
    n_trials = max(len(trials), 1)
    build_matrix = any(method in _SKLEARN_CLUSTER_METHODS for method, _params in trials)
    ex = register_process_pool(
        ProcessPoolExecutor(
            max_workers=1,
            mp_context=_spawn_context(),
            initializer=_mp_init_cluster_fps,
            initargs=(list(fps),),
        )
    )
    results: list[dict] = []
    cancelled = False

    def _pulse() -> None:
        if on_trial is not None:
            on_trial(len(results), n_trials)

    try:
        for method, params in trials:
            if should_terminate_process_pool(cancel_event):
                cancelled = True
                break
            fut = ex.submit(
                _mp_explore_trial,
                (method, dict(params), build_matrix),
            )
            try:
                results.append(_wait_future(fut, cancel_event, _pulse))
            except _PoolCancelled:
                cancelled = True
                break
            if on_trial is not None:
                on_trial(len(results), n_trials)
        return results, cancelled
    finally:
        shutdown_process_pool_executor(
            ex,
            kill_workers=cancelled or should_terminate_process_pool(cancel_event),
        )


def _mp_init_cluster_matrix(matrix: np.ndarray) -> None:
    global _CHILD_FPS, _CHILD_X
    _CHILD_FPS = []
    _CHILD_X = matrix


def _mp_explore_matrix_trial(args: tuple) -> dict:
    """One exploratory trial against the prepared feature matrix."""
    method, params = args
    matrix = _CHILD_X
    try:
        labels = _run_clustering(method, params, X=matrix, fps=[], cancel_event=None)
    except Exception as exc:
        return _explore_record(method, params, notes=str(exc)[:120])
    if labels is None:
        return _explore_record(method, params, notes="Clustering produced no labels.")
    return _explore_record(method, params, stats=_summarize_partition(labels, matrix))


def _explore_matrix_off_gil(
    matrix: np.ndarray,
    trials: Sequence[tuple[str, dict]],
    *,
    cancel_event: threading.Event | None,
    on_trial: Callable[[int, int], None] | None,
) -> tuple[list[dict], bool]:
    """Run exploratory trials on a prepared matrix in one child process."""
    n_trials = max(len(trials), 1)
    ex = register_process_pool(
        ProcessPoolExecutor(
            max_workers=1,
            mp_context=_spawn_context(),
            initializer=_mp_init_cluster_matrix,
            initargs=(matrix,),
        )
    )
    results: list[dict] = []
    cancelled = False

    def _pulse() -> None:
        if on_trial is not None:
            on_trial(len(results), n_trials)

    try:
        for method, params in trials:
            if should_terminate_process_pool(cancel_event):
                cancelled = True
                break
            fut = ex.submit(_mp_explore_matrix_trial, (method, dict(params)))
            try:
                results.append(_wait_future(fut, cancel_event, _pulse))
            except _PoolCancelled:
                cancelled = True
                break
            if on_trial is not None:
                on_trial(len(results), n_trials)
        return results, cancelled
    finally:
        shutdown_process_pool_executor(
            ex,
            kill_workers=cancelled or should_terminate_process_pool(cancel_event),
        )


def _run_explore_trials(
    fps: Sequence,
    trials: Sequence[tuple[str, dict]],
    *,
    cancel_event: threading.Event | None,
    on_trial: Callable[[int, int], None] | None,
    features: np.ndarray | None = None,
) -> tuple[list[dict], bool]:
    if features is not None:
        n_rows = int(features.shape[0])
        if _use_fit_process_pool(n_rows):
            return _explore_matrix_off_gil(
                features,
                trials,
                cancel_event=cancel_event,
                on_trial=on_trial,
            )
        return _explore_trials_inline(
            fps,
            trials,
            cancel_event=cancel_event,
            on_trial=on_trial,
            features=features,
        )
    if _use_fit_process_pool(len(fps)):
        return _explore_trials_off_gil(
            fps,
            trials,
            cancel_event=cancel_event,
            on_trial=on_trial,
        )
    return _explore_trials_inline(
        fps,
        trials,
        cancel_event=cancel_event,
        on_trial=on_trial,
    )


def _feature_space_name(*, use_fp: bool, numeric: bool) -> str:
    if numeric and use_fp:
        return "mixed"
    if numeric:
        return "numeric"
    return "fingerprint"


def _not_enough_rows_message(*, use_fp: bool, numeric: bool, explore: bool) -> str:
    verb = "explore" if explore else "cluster"
    if numeric and use_fp:
        need = "both a fingerprint and complete numeric values"
    elif numeric:
        need = "complete values in the selected columns"
    else:
        need = "valid fingerprints"
    return f"Need at least two rows with {need} in this scope to {verb}."


class ClusterWorker(QRunnable):
    """Cluster rows off the GUI GIL.

    Fingerprints and the fit run in child processes once the table is large enough
    (or the fingerprint type holds the GIL). The parent thread only waits, so Qt
    can keep processing events.

    ``numeric_by_oid`` supplies descriptor rows keyed by table OID. Scikit-learn
    methods cluster those columns, optionally concatenated with a fingerprint.
    Tanimoto methods fail if it is set.
    """

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol | None]],
        fp_choice: str,
        method: str,
        params: dict,
        column_name: str,
        signals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        numeric_by_oid: dict[int, np.ndarray] | None = None,
        standardize_numeric: bool = True,
    ):
        super().__init__()
        self.rows = rows
        self.fp_choice = fp_choice
        self.method = method
        self.params = params
        self.column_name = column_name
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.numeric_by_oid = numeric_by_oid
        self.standardize_numeric = bool(standardize_numeric)

    def run(self) -> None:
        sk_methods = _SKLEARN_CLUSTER_METHODS
        if self.method in sk_methods:
            try:
                from sklearn.cluster import KMeans  # noqa: F401

                _ = KMeans
            except ImportError as e:
                self.signals.cluster_failed.emit(
                    f"scikit-learn is required for {self.method}. Install with: pip install scikit-learn ({e})"
                )
                return

        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        tot = max(len(self.rows), 1)
        throttle = [0, 0.0]

        def _on_fp(done: int, total: int) -> None:
            report_tool_progress(
                message="Clustering",
                done=done,
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=throttle,
            )

        use_fp = fingerprint_requested(self.fp_choice)
        numeric_by_oid = self.numeric_by_oid or None
        if self.method in TANIMOTO_CLUSTER_METHODS and numeric_by_oid:
            self.signals.cluster_failed.emit(_tanimoto_with_numeric_message())
            return
        if not use_fp and not numeric_by_oid:
            self.signals.cluster_failed.emit(
                "Select a fingerprint, one or more numeric columns, or both."
            )
            return

        cancelled = False
        fps: list | None
        if use_fp:
            try:
                oids, fps, cancelled = _collect_fingerprints(
                    self.rows,
                    self.fp_choice,
                    cancel_event=cancel_ev,
                    on_progress=_on_fp,
                )
            except Exception as e:
                logger.exception("Clustering fingerprint collection failed")
                self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
                return
        else:
            oids = [int(oid) for oid, _mol in self.rows]
            fps = None

        numeric = None
        if numeric_by_oid:
            oids, fps, numeric = _align_numeric_rows(oids, fps, numeric_by_oid)

        if len(oids) < 2:
            if cancelled and len(oids) == 1:
                # Keep completed work: one processed row still gets a deterministic cluster label.
                res = [(oids[0], {self.column_name: "0"})]
                emit_partial_results_if_cancelled(self.signals, "Cluster", 1, tot, True)
                self.signals.calculated.emit(res, [self.column_name])
                self.signals.cluster_failed.emit("Cancelled.")
                return
            if cancelled:
                self.signals.cluster_failed.emit("Cancelled.")
                return
            self.signals.cluster_failed.emit(
                _not_enough_rows_message(
                    use_fp=use_fp, numeric=numeric_by_oid is not None, explore=False
                )
            )
            return

        features = None
        fit_params = dict(self.params)
        if numeric is not None:
            try:
                features = _combine_feature_matrix(
                    fps, numeric, standardize=self.standardize_numeric
                )
            except Exception as e:
                logger.exception("Clustering feature matrix failed")
                self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
                return
            if self.method == "dbscan":
                fit_params.setdefault("metric", "euclidean")

        try:
            labels = _assign_cluster_labels(
                self.method,
                fit_params,
                fps or [],
                features=features,
                cancel_event=None if cancelled else cancel_ev,
                on_wait=lambda: report_tool_progress(
                    message="Clustering",
                    done=tot,
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.signals,
                    throttle=throttle,
                ),
            )
        except _PoolCancelled:
            self.signals.cluster_failed.emit("Cancelled.")
            return
        except Exception as e:
            logger.exception("Clustering fit failed")
            self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
            return

        if labels is None:
            self.signals.cluster_failed.emit("Cancelled.")
            return

        def _label_txt(lab: int) -> str:
            if lab == -1:
                return "noise"
            return str(int(lab))

        res = [(oid, {self.column_name: _label_txt(int(lab))}) for oid, lab in zip(oids, labels)]
        report_tool_progress(
            message="Clustering",
            done=tot,
            total=tot,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        emit_partial_results_if_cancelled(self.signals, "Cluster", len(res), tot, cancelled)
        self.signals.calculated.emit(res, [self.column_name])
        if cancelled:
            self.signals.cluster_failed.emit("Cancelled.")


class ClusterExploreWorker(QRunnable):
    """
    Sample several (method, parameter) combinations and emit summary rows for the UI.
    """

    def __init__(
        self,
        rows: list[tuple[int, Chem.Mol | None]],
        fp_choice: str,
        max_runs: int,
        include: dict[str, bool],
        signals,
        cancel_event: threading.Event | None = None,
        progress_state=None,
        numeric_by_oid: dict[int, np.ndarray] | None = None,
        standardize_numeric: bool = True,
    ):
        super().__init__()
        self.rows = rows
        self.fp_choice = fp_choice
        self.max_runs = int(max_runs)
        self.include = dict(include)
        self.signals = signals
        self.cancel_event = cancel_event
        self.progress_state = progress_state
        self.numeric_by_oid = numeric_by_oid
        self.standardize_numeric = bool(standardize_numeric)

    def _emit_explore_cancel(self, results: list, n_trials: int) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        report_tool_progress(
            message="Exploring clusters",
            done=min(len(results), n_trials),
            total=n_trials,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self.signals.cluster_explore_finished.emit(results)
        try:
            self.signals.partial_results.emit("Cluster explore", len(results), n_trials)
        except Exception:
            pass
        self.signals.cluster_failed.emit("Cancelled.")

    def run(self) -> None:
        from ..platform_support.tool_progress import report_tool_progress

        cancel_ev = self.cancel_event
        fp_throttle = [0, 0.0]

        def _on_fp(done: int, total: int) -> None:
            report_tool_progress(
                message="Exploring clusters",
                done=done,
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=fp_throttle,
            )

        use_fp = fingerprint_requested(self.fp_choice)
        numeric_by_oid = self.numeric_by_oid or None
        if not use_fp and not numeric_by_oid:
            self.signals.cluster_failed.emit(
                "Select a fingerprint, one or more numeric columns, or both."
            )
            return

        fps: list | None
        if use_fp:
            try:
                oids, fps, cancelled = _collect_fingerprints(
                    self.rows,
                    self.fp_choice,
                    cancel_event=cancel_ev,
                    on_progress=_on_fp,
                )
            except Exception as e:
                logger.exception("Cluster explore fingerprint collection failed")
                self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
                return
            if cancelled:
                self.signals.cluster_failed.emit("Cancelled.")
                return
        else:
            oids = [int(oid) for oid, _mol in self.rows]
            fps = None

        numeric = None
        if numeric_by_oid:
            oids, fps, numeric = _align_numeric_rows(oids, fps, numeric_by_oid)

        if len(oids) < 2:
            self.signals.cluster_failed.emit(
                _not_enough_rows_message(
                    use_fp=use_fp, numeric=numeric_by_oid is not None, explore=True
                )
            )
            return

        feature_space = _feature_space_name(use_fp=use_fp, numeric=numeric is not None)
        n = len(oids)
        trials = generate_explore_trials(
            n, self.max_runs, self.include, feature_space=feature_space
        )
        if not trials:
            self.signals.cluster_failed.emit(
                "None of the selected methods apply to numeric columns. "
                "Use K-Means, Agglomerative, or DBSCAN."
            )
            return
        features = None
        if numeric is not None:
            try:
                features = _combine_feature_matrix(
                    fps, numeric, standardize=self.standardize_numeric
                )
            except Exception as e:
                logger.exception("Cluster explore feature matrix failed")
                self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
                return
        needs_sk = any(m in _SKLEARN_CLUSTER_METHODS for m, _params in trials)
        if needs_sk:
            try:
                from sklearn.cluster import KMeans  # noqa: F401

                _ = KMeans
            except ImportError as e:
                self.signals.cluster_failed.emit(
                    f"scikit-learn is required for exploratory trials that include K-Means, "
                    f"Agglomerative, or DBSCAN. pip install scikit-learn ({e})"
                )
                return

        n_trials = max(len(trials), 1)
        trial_throttle = [0, 0.0]

        def _on_trial(done: int, total: int) -> None:
            report_tool_progress(
                message="Exploring clusters",
                done=done,
                total=total,
                progress_state=self.progress_state,
                signals=self.signals,
                throttle=trial_throttle,
            )

        try:
            results, trial_cancelled = _run_explore_trials(
                fps or [],
                trials,
                cancel_event=cancel_ev,
                on_trial=_on_trial,
                features=features,
            )
        except _PoolCancelled:
            self._emit_explore_cancel([], n_trials)
            return
        except Exception as e:
            logger.exception("Cluster explore failed")
            self.signals.cluster_failed.emit(str(e) or "Clustering failed.")
            return

        if trial_cancelled:
            self._emit_explore_cancel(results, n_trials)
            return

        report_tool_progress(
            message="Exploring clusters",
            done=n_trials,
            total=n_trials,
            progress_state=self.progress_state,
            signals=self.signals,
            force_signal=True,
        )
        self.signals.cluster_explore_finished.emit(results)
