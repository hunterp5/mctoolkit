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

"""Numeric matrix preparation and sklearn PCA / t-SNE / UMAP plus NumPy Kohonen SOM (no Qt)."""

from __future__ import annotations

import inspect
from dataclasses import asdict, dataclass, replace
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class DimensionReductionResult:
    method: str
    x: list[float]
    y: list[float]
    oids: list[int]
    hover: list[str]
    title: str
    summary: str
    color_values: list[Any] | None = None
    color_label: str | None = None
    z: list[float] | None = None


def result_to_dict(result: DimensionReductionResult) -> dict:
    """Serialize a reduction result for session / UI state (no Qt)."""
    return asdict(result)


def subset_dimension_reduction_result(
    result: DimensionReductionResult,
    keep: frozenset[int] | None,
) -> DimensionReductionResult:
    """Keep coordinates for OIDs that are still visible in the table."""
    if keep is None:
        return result
    xs: list[float] = []
    ys: list[float] = []
    oids: list[int] = []
    hover: list[str] = []
    has_color = result.color_values is not None
    colors: list[Any] = []
    n_x = len(result.x)
    n_y = len(result.y)
    n_h = len(result.hover)
    n_c = len(result.color_values) if has_color else 0
    has_z = result.z is not None
    n_z = len(result.z) if has_z else 0
    zs: list[float] = []
    for i, oid in enumerate(result.oids):
        if int(oid) not in keep:
            continue
        oids.append(int(oid))
        xs.append(result.x[i] if i < n_x else 0.0)
        ys.append(result.y[i] if i < n_y else 0.0)
        hover.append(result.hover[i] if i < n_h else f"OID {oid}")
        if has_color:
            colors.append(result.color_values[i] if i < n_c else None)
        if has_z:
            zs.append(result.z[i] if i < n_z else 0.0)
    return replace(
        result,
        x=xs,
        y=ys,
        z=zs if has_z else None,
        oids=oids,
        hover=hover,
        color_values=colors if has_color else None,
    )


def prepare_numeric_matrix(
    df: pd.DataFrame,
    feature_columns: list[str],
    *,
    drop_incomplete_rows: bool = True,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """
    Return ``(X, row_indices_into_df, valid_positions)`` where row_indices map back to the
    input dataframe index labels (0..n-1 positions in the passed frame).
    """
    if not feature_columns:
        raise ValueError("Select at least one numeric column.")
    missing = [c for c in feature_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Unknown column(s): {', '.join(missing)}")
    num = df[feature_columns].apply(pd.to_numeric, errors="coerce")
    if drop_incomplete_rows:
        mask = num.notna().all(axis=1)
        num = num.loc[mask]
        positions = [int(i) for i in np.where(mask.to_numpy())[0]]
    else:
        num = num.fillna(num.mean(numeric_only=True))
        positions = list(range(len(num)))
    if len(num) < 2:
        raise ValueError("Need at least two complete rows for dimensionality reduction.")
    if num.shape[1] < 1:
        raise ValueError("Need at least one feature column.")
    return num.to_numpy(dtype=float), num.index.to_numpy(), positions


def is_fingerprint_bitcount_column(name: str) -> bool:
    """True for descriptor columns that store on-bit counts, not full bit vectors."""
    n = (name or "").strip()
    if n.startswith("FP_"):
        return True
    lo = n.lower()
    return "morgan" in lo and "bit" in lo and lo.endswith("bits")


def _standardize(X: np.ndarray, standardize: bool) -> np.ndarray:
    if not standardize:
        return X
    from sklearn.preprocessing import StandardScaler

    return StandardScaler().fit_transform(X)


EMBEDDING_PCA_DIM = 50
EMBEDDING_PCA_DIM_MAX = 500


def normalize_target_dimensions(value: Any) -> int:
    """Return 2 or 3, the embedding axes a dimred plot can draw."""
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"3", "3d"}:
            return 3
        return 2
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 2
    return 3 if n >= 3 else 2


def _embed_coords(coords: np.ndarray, n_dims: int) -> np.ndarray:
    """Return ``(n, 2)`` or ``(n, 3)`` coordinates, padding missing axes with zeros."""
    dims = normalize_target_dimensions(n_dims)
    arr = np.asarray(coords, dtype=float)
    if arr.ndim != 2:
        raise ValueError("coordinates must be a 2D array.")
    out = np.zeros((arr.shape[0], dims), dtype=float)
    take = min(dims, arr.shape[1])
    if take:
        out[:, :take] = arr[:, :take]
    return out


def _maybe_pca_preprocess(
    X: np.ndarray,
    *,
    max_dim: int = EMBEDDING_PCA_DIM,
    min_variance: float = 0.0,
    whiten: bool = False,
    random_state: int = 42,
) -> tuple[np.ndarray, str]:
    """Project high-D features (e.g. 2048-bit fingerprints) before t-SNE / UMAP / SOM.

    sklearn's t-SNE docs recommend PCA to ~50 dimensions; it also shrinks UMAP and
    Kohonen maps that would otherwise loop over the full bit vector.
    """
    cap = int(max_dim)
    if cap <= 0:
        return X, ""
    n_samples, n_features = X.shape
    cap = max(2, cap)
    var_target = float(min_variance or 0.0)
    if var_target > 1.0:
        var_target = var_target / 100.0
    var_target = min(max(var_target, 0.0), 0.99)
    if n_features <= cap and var_target <= 0.0 and not whiten:
        return X, ""
    k_fit = min(n_samples, n_features)
    if n_features > cap:
        k_fit = min(k_fit, cap)
    if k_fit < 2:
        return X, ""
    from sklearn.decomposition import PCA

    pca = PCA(n_components=k_fit, whiten=bool(whiten), random_state=int(random_state))
    transformed = pca.fit_transform(X)
    ratios = np.asarray(pca.explained_variance_ratio_, dtype=float)
    cum = np.cumsum(ratios)
    if var_target > 0.0:
        k = int(np.searchsorted(cum, var_target) + 1)
        k = max(2, min(k, k_fit))
    else:
        k = k_fit
    if k >= n_features and not whiten:
        return X, ""
    reduced = np.asarray(transformed[:, :k], dtype=float)
    if var_target <= 0.0 and not whiten:
        note = f"PCA-preprocessed to {k} components (from {n_features} features).\n"
        return reduced, note
    kept = 100.0 * float(cum[k - 1])
    parts = [
        f"PCA-preprocessed to {k} components ({kept:.1f}% variance, from {n_features} features"
    ]
    if var_target > 0.0:
        parts.append(f", target {100.0 * var_target:.0f}%")
    if n_features > cap:
        parts.append(f", cap {cap}")
    if whiten:
        parts.append(", whitened")
    note = "".join(parts) + ").\n"
    return reduced, note


def subsample_row_indices(
    n_rows: int,
    *,
    max_points: int | None,
    random_state: int = 42,
) -> np.ndarray:
    """Sorted row indices after the dimred max-points cap (all rows when under the cap)."""
    from ..platform_support.config import load_config

    n = max(0, int(n_rows))
    idx = np.arange(n)
    if max_points is None or n == 0:
        return idx
    cap = min(int(max_points), int(load_config().memory_guard_dimred_max_points))
    cap = max(1, cap)
    if n <= cap:
        return idx
    rng = np.random.default_rng(int(random_state))
    return np.sort(rng.choice(n, size=cap, replace=False))


def _tsne_init_method(n_features: int, n_components: int = 2) -> str:
    """PCA init needs at least as many features as embedding axes."""
    need = max(2, int(n_components))
    return "pca" if int(n_features) >= need else "random"


def build_fingerprint_matrix(
    mol_rows: list[tuple[int, object]],
    fp_choice: str,
) -> tuple[np.ndarray, list[int]]:
    """Full bit-vector matrix from in-memory structures (same fingerprints as Cluster)."""
    from ..chem.rdkit_fingerprints import bitvect_to_uint8
    from ..platform_support.memory_guards import check_fp_matrix_workload
    from ..workers.fingerprint_similarity import fingerprint_bitvect_for_ui_choice
    from ..chem.rdkit_fingerprints import fingerprint_bitvect_for_row

    n_candidates = sum(1 for _oid, mol in mol_rows if mol is not None)
    guard = check_fp_matrix_workload(n_candidates, n_bits=2048)
    if not guard.ok:
        raise ValueError(guard.message)

    oids: list[int] = []
    rows: list[np.ndarray] = []
    for oid, mol in mol_rows:
        if mol is None:
            continue
        try:
            fp = fingerprint_bitvect_for_row(int(oid), mol, fp_choice)
            if fp is None:
                fp = fingerprint_bitvect_for_ui_choice(mol, fp_choice)
        except Exception:
            fp = None
        if fp is None:
            continue
        oids.append(int(oid))
        rows.append(bitvect_to_uint8(fp))
    if len(rows) < 2:
        raise ValueError(
            "Need at least two rows with valid fingerprints in this scope. "
            "Check the structure source and that rows have parseable structures."
        )
    return np.vstack(rows), oids


def run_pca(
    X: np.ndarray,
    *,
    standardize: bool = True,
    n_components: int = 2,
    plot_dims: int = 2,
) -> tuple[np.ndarray, np.ndarray, str]:
    from sklearn.decomposition import PCA

    dims = normalize_target_dimensions(plot_dims)
    Xs = _standardize(X, standardize)
    n_samples, n_features = Xs.shape
    limit = min(n_samples, n_features)
    n_comp = max(1, min(int(n_components), limit))
    n_comp = max(n_comp, min(dims, limit))
    pca = PCA(n_components=n_comp)
    coords_full = pca.fit_transform(Xs)
    ratios = pca.explained_variance_ratio_
    coords = _embed_coords(coords_full, dims)
    lines = [
        f"Samples: {n_samples}",
        f"Features: {n_features}",
        f"Components computed: {n_comp}",
        "",
        "Explained variance ratio:",
    ]
    for i, r in enumerate(ratios, start=1):
        lines.append(f"  PC{i}: {100.0 * float(r):.2f}%")
    lines.append(f"  Cumulative (PC1–PC{n_comp}): {100.0 * float(np.sum(ratios)):.2f}%")
    if n_features == 1 and dims == 2:
        lines.append("")
        lines.append("Only one feature: plot shows PC1 on X and 0 on Y.")
    elif n_features < dims:
        lines.append("")
        lines.append(f"Only {n_features} feature(s): missing axes are plotted as 0.")
    elif dims == 3:
        lines.append("")
        lines.append("Plot shows PC1, PC2, and PC3.")
    elif n_comp > 2:
        lines.append("")
        lines.append("Plot shows PC1 vs PC2.")
    return coords, ratios, "\n".join(lines)


def run_tsne(
    X: np.ndarray,
    *,
    standardize: bool = True,
    perplexity: float = 30.0,
    learning_rate: float = 200.0,
    max_iter: int = 1000,
    random_state: int = 42,
    max_points: int | None = 2500,
    pca_dim: int | None = None,
    pca_min_variance: float = 0.0,
    pca_whiten: bool = False,
    n_components: int = 2,
) -> tuple[np.ndarray, np.ndarray, str]:
    from sklearn.manifold import TSNE

    n_samples = X.shape[0]
    used_idx = subsample_row_indices(
        n_samples, max_points=max_points, random_state=int(random_state)
    )
    note = ""
    if used_idx.size < n_samples:
        note = (
            f"Subsampled {int(used_idx.size)} of {n_samples} rows (fixed seed {random_state}).\n\n"
        )

    Xs = _standardize(X[used_idx], standardize)
    cap = EMBEDDING_PCA_DIM if pca_dim is None else int(pca_dim)
    Xs, pca_note = _maybe_pca_preprocess(
        Xs,
        max_dim=cap,
        min_variance=float(pca_min_variance or 0.0),
        whiten=bool(pca_whiten),
        random_state=int(random_state),
    )
    n_used = Xs.shape[0]
    dims = normalize_target_dimensions(n_components)
    perp = float(perplexity)
    perp = max(5.0, min(perp, float(n_used - 1)))
    n_comp = min(dims, max(1, n_used - 1))
    init = _tsne_init_method(Xs.shape[1], n_comp)
    tsne_kwargs: dict[str, Any] = {
        "n_components": n_comp,
        "perplexity": perp,
        "learning_rate": float(learning_rate),
        "max_iter": int(max_iter),
        "init": init,
        "random_state": int(random_state),
    }
    # Barnes–Hut only embeds two axes; three axes need the exact method.
    if n_comp >= 3:
        tsne_kwargs["method"] = "exact"
    if "n_jobs" in inspect.signature(TSNE).parameters:
        tsne_kwargs["n_jobs"] = -1
    tsne = TSNE(**tsne_kwargs)
    coords = _embed_coords(tsne.fit_transform(Xs), dims)
    summary = (
        f"{note}{pca_note}"
        f"Samples used: {n_used}\n"
        f"Features: {Xs.shape[1]}\n"
        f"Dimensions: {dims}\n"
        f"t-SNE init: {init}\n"
        f"Perplexity: {perp:.1f}\n"
        f"Learning rate: {learning_rate}\n"
        f"Iterations: {max_iter}\n"
        f"Random state: {random_state}"
    )
    return coords, used_idx, summary


def run_umap(
    X: np.ndarray,
    *,
    standardize: bool = True,
    n_neighbors: int = 15,
    min_dist: float = 0.1,
    random_state: int = 42,
    max_points: int | None = 2500,
    pca_dim: int | None = None,
    pca_min_variance: float = 0.0,
    pca_whiten: bool = False,
    n_components: int = 2,
) -> tuple[np.ndarray, np.ndarray, str]:
    try:
        import umap
    except ImportError as exc:
        raise ImportError(
            "UMAP requires the umap-learn package. Install with: pip install umap-learn"
        ) from exc

    n_samples = X.shape[0]
    used_idx = subsample_row_indices(
        n_samples, max_points=max_points, random_state=int(random_state)
    )
    note = ""
    if used_idx.size < n_samples:
        note = (
            f"Subsampled {int(used_idx.size)} of {n_samples} rows (fixed seed {random_state}).\n\n"
        )

    Xs = _standardize(X[used_idx], standardize)
    cap = EMBEDDING_PCA_DIM if pca_dim is None else int(pca_dim)
    Xs, pca_note = _maybe_pca_preprocess(
        Xs,
        max_dim=cap,
        min_variance=float(pca_min_variance or 0.0),
        whiten=bool(pca_whiten),
        random_state=int(random_state),
    )
    n_used = Xs.shape[0]
    dims = normalize_target_dimensions(n_components)
    n_neigh = max(2, min(int(n_neighbors), n_used - 1))
    reducer = umap.UMAP(
        n_components=dims,
        n_neighbors=n_neigh,
        min_dist=float(min_dist),
        random_state=int(random_state),
        n_jobs=1,
    )
    coords = _embed_coords(reducer.fit_transform(Xs), dims)
    summary = (
        f"{note}{pca_note}"
        f"Samples used: {n_used}\n"
        f"Features: {Xs.shape[1]}\n"
        f"Dimensions: {dims}\n"
        f"n_neighbors: {n_neigh}\n"
        f"min_dist: {min_dist}\n"
        f"Random state: {random_state}"
    )
    return coords, used_idx, summary


def _fit_som_3d(
    Xs: np.ndarray,
    *,
    gw: int,
    gh: int,
    gd: int,
    epochs: int,
    lr0: float,
    sigma0: float,
    rng: np.random.Generator,
    jitter: float,
) -> tuple[np.ndarray, int, int]:
    """Train a width × height × depth Kohonen map. Returns coords, occupied nodes, max count."""
    n_used, n_features = Xs.shape
    n_nodes = gw * gh * gd
    init_n = min(n_used, max(n_nodes, 8))
    init_pick = rng.choice(n_used, size=init_n, replace=False)
    weights = (
        Xs[init_pick][rng.integers(0, init_n, size=n_nodes)].reshape(gd, gh, gw, n_features).copy()
    )
    zz, yy, xx = np.indices((gd, gh, gw))
    order = np.arange(n_used)
    for epoch in range(epochs):
        frac = epoch / max(1, epochs - 1) if epochs > 1 else 1.0
        lr = lr0 * (1.0 - frac)
        sig = max(0.35, sigma0 * (1.0 - frac))
        rng.shuffle(order)
        inv_2sig2 = 1.0 / (2.0 * sig * sig)
        for i in order:
            sample = Xs[int(i)]
            diff = weights - sample
            dist2 = np.einsum("ijkl,ijkl->ijk", diff, diff)
            bz, by, bx = np.unravel_index(int(np.argmin(dist2)), (gd, gh, gw))
            d2 = (zz - bz) ** 2 + (yy - by) ** 2 + (xx - bx) ** 2
            neigh = np.exp(-d2 * inv_2sig2)[..., None]
            weights += lr * neigh * (sample - weights)

    flat_w = weights.reshape(n_nodes, n_features)
    x_sq = np.einsum("ij,ij->i", Xs, Xs)[:, None]
    w_sq = np.einsum("ij,ij->i", flat_w, flat_w)[None, :]
    bmu_flat = np.argmin(x_sq + w_sq - 2.0 * (Xs @ flat_w.T), axis=1)
    plane = gh * gw
    bmu_z = bmu_flat // plane
    rem = bmu_flat % plane
    bmu_y = rem // gw
    bmu_x = rem % gw
    if jitter and float(jitter) > 0:
        j = float(jitter)
        coords = np.column_stack(
            [
                bmu_x.astype(float) + rng.uniform(-j, j, size=n_used),
                bmu_y.astype(float) + rng.uniform(-j, j, size=n_used),
                bmu_z.astype(float) + rng.uniform(-j, j, size=n_used),
            ]
        )
    else:
        coords = np.column_stack([bmu_x.astype(float), bmu_y.astype(float), bmu_z.astype(float)])
    occupied = int(np.unique(bmu_flat).size)
    max_count = int(np.bincount(bmu_flat, minlength=n_nodes).max())
    return coords, occupied, max_count


def run_som(
    X: np.ndarray,
    *,
    standardize: bool = True,
    grid_width: int = 10,
    grid_height: int = 10,
    n_epochs: int = 50,
    learning_rate: float = 0.5,
    sigma: float | None = None,
    random_state: int = 42,
    max_points: int | None = 2500,
    jitter: float = 0.35,
    pca_dim: int | None = None,
    pca_min_variance: float = 0.0,
    pca_whiten: bool = False,
    grid_depth: int = 1,
) -> tuple[np.ndarray, np.ndarray, str]:
    """
    Train a rectangular Kohonen self-organizing map and return BMU grid coordinates.

    Plot coordinates are BMU column (X) and row (Y). ``grid_depth`` above 1 adds a
    layer axis (Z). Optional jitter separates points that share a node.
    No extra package dependency (NumPy only).
    """
    n_samples = X.shape[0]
    used_idx = subsample_row_indices(
        n_samples, max_points=max_points, random_state=int(random_state)
    )
    note = ""
    if used_idx.size < n_samples:
        note = (
            f"Subsampled {int(used_idx.size)} of {n_samples} rows (fixed seed {random_state}).\n\n"
        )

    Xs = _standardize(X[used_idx], standardize).astype(np.float64, copy=False)
    cap = EMBEDDING_PCA_DIM if pca_dim is None else int(pca_dim)
    Xs, pca_note = _maybe_pca_preprocess(
        Xs,
        max_dim=cap,
        min_variance=float(pca_min_variance or 0.0),
        whiten=bool(pca_whiten),
        random_state=int(random_state),
    )
    Xs = np.asarray(Xs, dtype=np.float64)
    n_used, n_features = Xs.shape
    gw = max(2, int(grid_width))
    gh = max(2, int(grid_height))
    gd = max(2, int(grid_depth)) if int(grid_depth) > 1 else 1
    use_3d = gd > 1
    n_nodes = gw * gh * gd
    if n_nodes > 2_500:
        shape = f"{gw}×{gh}×{gd}" if use_3d else f"{gw}×{gh}"
        hint = "Reduce map width, height, or depth." if use_3d else "Reduce map width/height."
        raise ValueError(f"SOM grid {shape} ({n_nodes:,} nodes) exceeds 2,500. {hint}")
    epochs = max(1, int(n_epochs))
    lr0 = max(1e-6, float(learning_rate))
    longest = max(gw, gh, gd) if use_3d else max(gw, gh)
    sigma0 = float(sigma) if sigma is not None and float(sigma) > 0 else longest / 2.0
    sigma0 = max(0.5, sigma0)

    rng = np.random.default_rng(int(random_state))
    if use_3d:
        coords, occupied, max_count = _fit_som_3d(
            Xs,
            gw=gw,
            gh=gh,
            gd=gd,
            epochs=epochs,
            lr0=lr0,
            sigma0=sigma0,
            rng=rng,
            jitter=float(jitter),
        )
        grid_text = f"{gw} × {gh} × {gd}"
        plot_text = "Plot: BMU column (X), row (Y), and layer (Z)"
    else:
        # Sample subspace for weight init so maps start near the data cloud.
        init_n = min(n_used, max(n_nodes, 8))
        init_pick = rng.choice(n_used, size=init_n, replace=False)
        weights = (
            Xs[init_pick][rng.integers(0, init_n, size=n_nodes)].reshape(gh, gw, n_features).copy()
        )

        yy, xx = np.indices((gh, gw))
        order = np.arange(n_used)
        for epoch in range(epochs):
            frac = epoch / max(1, epochs - 1) if epochs > 1 else 1.0
            lr = lr0 * (1.0 - frac)
            sig = max(0.35, sigma0 * (1.0 - frac))
            rng.shuffle(order)
            inv_2sig2 = 1.0 / (2.0 * sig * sig)
            for i in order:
                sample = Xs[i]
                diff = weights - sample
                dist2 = np.einsum("ijk,ijk->ij", diff, diff)
                by, bx = np.unravel_index(int(np.argmin(dist2)), (gh, gw))
                d2 = (yy - by) ** 2 + (xx - bx) ** 2
                neigh = np.exp(-d2 * inv_2sig2)[..., None]
                weights += lr * neigh * (sample - weights)

        flat_w = weights.reshape(n_nodes, n_features)
        # Batched BMU assignment
        # ||x - w||^2 = ||x||^2 + ||w||^2 - 2 x·w
        x_sq = np.einsum("ij,ij->i", Xs, Xs)[:, None]
        w_sq = np.einsum("ij,ij->i", flat_w, flat_w)[None, :]
        dots = Xs @ flat_w.T
        bmu_flat = np.argmin(x_sq + w_sq - 2.0 * dots, axis=1)
        bmu_y = bmu_flat // gw
        bmu_x = bmu_flat % gw
        if jitter and float(jitter) > 0:
            j = float(jitter)
            coords = np.column_stack(
                [
                    bmu_x.astype(float) + rng.uniform(-j, j, size=n_used),
                    bmu_y.astype(float) + rng.uniform(-j, j, size=n_used),
                ]
            )
        else:
            coords = np.column_stack([bmu_x.astype(float), bmu_y.astype(float)])

        occupied = int(np.unique(bmu_flat).size)
        max_count = int(np.bincount(bmu_flat, minlength=n_nodes).max())
        grid_text = f"{gw} × {gh}"
        plot_text = "Plot: BMU column (X) vs row (Y)"
    if jitter and float(jitter) > 0:
        plot_text += " with jitter"
    summary = (
        f"{note}{pca_note}"
        f"Samples used: {n_used}\n"
        f"Features: {n_features}\n"
        f"Grid: {grid_text} ({n_nodes} nodes)\n"
        f"Occupied nodes: {occupied} ({100.0 * occupied / n_nodes:.1f}%)\n"
        f"Max node occupancy: {max_count}\n"
        f"Epochs: {epochs}\n"
        f"Initial learning rate: {lr0}\n"
        f"Initial sigma: {sigma0:.2f}\n"
        f"Random state: {random_state}\n"
        f"{plot_text}"
    )
    return coords, used_idx, summary


def build_reduction_result(
    method: str,
    coords: np.ndarray,
    df: pd.DataFrame,
    oids: list[int],
    row_indices: np.ndarray,
    *,
    title: str,
    summary: str,
    color_column: str | None = None,
) -> DimensionReductionResult:
    """Map coordinates back to table oids and optional color column."""
    if len(oids) != len(df):
        raise ValueError("oids must align with dataframe rows.")
    pos_arr = np.asarray(row_indices, dtype=int)
    if coords.shape[0] != len(pos_arr):
        raise ValueError("coordinate count must match row index count.")
    if len(pos_arr) and (int(pos_arr.min()) < 0 or int(pos_arr.max()) >= len(oids)):
        raise ValueError("row index out of range for oid list.")
    xs = coords[:, 0].tolist()
    ys = coords[:, 1].tolist() if coords.shape[1] > 1 else [0.0] * coords.shape[0]
    zs = coords[:, 2].tolist() if coords.shape[1] >= 3 else None
    out_oids: list[int] = []
    hover: list[str] = []
    color_values: list[Any] | None = [] if color_column else None

    for j in range(coords.shape[0]):
        p = int(pos_arr[j])
        oid = int(oids[p])
        out_oids.append(oid)
        parts = [f"OID {oid}"]
        if color_column and color_column in df.columns:
            cv = df.iloc[p][color_column]
            parts.append(f"{color_column}: {cv}")
            if color_values is not None:
                color_values.append(cv)
        hover.append("<br>".join(parts))

    return DimensionReductionResult(
        method=method,
        x=xs,
        y=ys,
        z=zs,
        oids=out_oids,
        hover=hover,
        title=title,
        summary=summary,
        color_values=color_values,
        color_label=color_column,
    )
