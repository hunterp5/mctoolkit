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

"""Quick QSAR estimators, ranking score, and prediction geometry.

Continuous models are MLR, PLS, PCR, and kernel PLS. Categorical models are
naive Bayes and an ensemble of trees. Latent-factor models stop before the
training R² exceeds 0.9. The ranking score is the one described by Dixon et
al., Future Med. Chem. 2016 (10.4155/fmc-2016-0093).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

R2_CAP = 0.9
MAX_LATENT_FACTORS = 10
ANNEAL_STEPS = 1000
TREE_COUNT = 100
TREE_SAMPLE = 0.8
CONFORMAL_ALPHA = 0.1
DOMAIN_QUANTILE = 0.95

_FIT_ERRORS = (
    ValueError,
    TypeError,
    RuntimeError,
    ArithmeticError,
    AttributeError,
    KeyError,
    IndexError,
    np.linalg.LinAlgError,
)


def population_variance(values: np.ndarray) -> float:
    array = np.asarray(values, dtype=float)
    array = array[np.isfinite(array)]
    if array.size == 0:
        return 0.0
    centered = array - float(np.mean(array))
    return float(np.mean(centered * centered))


def continuous_accuracy(y_true: np.ndarray, y_pred: np.ndarray, y_variance: float) -> float:
    """``1 - var(residual) / y_variance``. The denominator is chosen by the caller."""
    if y_variance <= 1e-18:
        return 0.0
    return 1.0 - population_variance(np.asarray(y_true) - np.asarray(y_pred)) / y_variance


def categorical_accuracy(y_true: np.ndarray, y_pred: np.ndarray, classes: Sequence) -> float:
    """Unweighted mean of per-class recall. Classes absent from *y_true* are skipped."""
    actual = np.asarray(y_true)
    predicted = np.asarray(y_pred)
    recalls: list[float] = []
    for label in classes:
        mask = actual == label
        if not np.any(mask):
            continue
        recalls.append(float(np.mean(predicted[mask] == label)))
    if not recalls:
        return 0.0
    return float(np.mean(recalls))


def split_score(train_accuracy: float, test_accuracy: float) -> float:
    """Reward accuracy on both splits and penalize a gap between them.

    A negative test accuracy is returned unchanged so the product cannot turn
    a very poor test into a large positive score. Dixon et al. describe this
    ranking in Future Med. Chem. 2016 (10.4155/fmc-2016-0093).
    """
    if test_accuracy < 0.0:
        return float(test_accuracy)
    gap = abs(float(train_accuracy) - float(test_accuracy))
    return float(test_accuracy * (1.0 - gap))


def latent_factors_before_r2_cap(train_r2: Sequence[float]) -> int:
    """How many latent factors to keep. The next factor is refused once R² would pass 0.9."""
    if not train_r2:
        return 0
    kept = 1
    for index, r2 in enumerate(train_r2):
        if index == 0:
            if float(r2) > R2_CAP:
                return 1
            continue
        if float(r2) > R2_CAP:
            return kept
        kept = index + 1
    return kept


def subset_size_limit(n_train: int) -> int:
    """Maximum variables in one MLR subset.

    ``N / 10`` when N is at most 100, otherwise ``10 + 10·log10(N)``. A split
    smaller than 10 rows still gets a one-variable model.
    """
    n_rows = int(n_train)
    if n_rows <= 100:
        cap = n_rows // 10
    else:
        cap = int(math.floor(10 + 10 * math.log10(n_rows)))
    return max(1, cap)


def conformal_half_width(residuals: np.ndarray, alpha: float = CONFORMAL_ALPHA) -> float:
    """Split-conformal absolute-residual quantile, with the finite-sample rank."""
    absolute = np.sort(np.abs(np.asarray(residuals, dtype=float)))
    absolute = absolute[np.isfinite(absolute)]
    n_residuals = int(absolute.size)
    if n_residuals == 0:
        return 0.0
    rank = int(math.ceil((n_residuals + 1) * (1.0 - alpha)))
    rank = min(max(rank, 1), n_residuals)
    return float(absolute[rank - 1])


def _scale_fit(values: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    matrix = np.asarray(values, dtype=float)
    mean = matrix.mean(axis=0)
    scale = matrix.std(axis=0)
    scale = np.where(scale < 1e-8, 1.0, scale)
    return mean, scale, (matrix - mean) / scale


def _scale_apply(values: np.ndarray, mean: np.ndarray, scale: np.ndarray) -> np.ndarray:
    return (np.asarray(values, dtype=float) - mean) / scale


def _min_euclidean(query: np.ndarray, reference: np.ndarray) -> np.ndarray:
    query64 = np.asarray(query, dtype=float)
    reference64 = np.asarray(reference, dtype=float)
    query_sq = np.sum(query64 * query64, axis=1, keepdims=True)
    reference_sq = np.sum(reference64 * reference64, axis=1, keepdims=True).T
    distance_sq = np.maximum(query_sq + reference_sq - 2.0 * query64 @ reference64.T, 0.0)
    return np.sqrt(distance_sq.min(axis=1))


def euclidean_cutoff(values: np.ndarray) -> float:
    """95th percentile of nearest-neighbor distances inside *values*."""
    matrix = np.asarray(values, dtype=float)
    if matrix.shape[0] < 2:
        return 0.0
    query_sq = np.sum(matrix * matrix, axis=1, keepdims=True)
    distance_sq = np.maximum(query_sq + query_sq.T - 2.0 * matrix @ matrix.T, 0.0)
    np.fill_diagonal(distance_sq, np.inf)
    nearest = np.sqrt(distance_sq.min(axis=1))
    nearest = nearest[np.isfinite(nearest)]
    if nearest.size == 0:
        return 0.0
    return float(np.quantile(nearest, DOMAIN_QUANTILE))


def _tanimoto(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    left64 = np.asarray(left, dtype=float)
    right64 = np.asarray(right, dtype=float)
    gram = left64 @ right64.T
    left_sum = left64.sum(axis=1, keepdims=True)
    right_sum = right64.sum(axis=1, keepdims=True).T
    return gram / np.maximum(left_sum + right_sum - gram, 1e-12)


def tanimoto_cutoff(values: np.ndarray) -> float:
    """95th percentile of ``1 - max Tanimoto`` inside the training bits."""
    matrix = np.asarray(values, dtype=float)
    if matrix.shape[0] < 2:
        return 0.0
    similarity = _tanimoto(matrix, matrix)
    np.fill_diagonal(similarity, -1.0)
    distance = 1.0 - similarity.max(axis=1)
    return float(np.quantile(distance, DOMAIN_QUANTILE))


def _rbf_gamma(values: np.ndarray) -> float:
    matrix = np.asarray(values, dtype=float)
    n_rows = matrix.shape[0]
    if n_rows < 2:
        return 1.0
    take = min(n_rows, 200)
    sample = matrix[:take]
    squared = np.sum(sample * sample, axis=1, keepdims=True)
    distance_sq = np.maximum(squared + squared.T - 2.0 * sample @ sample.T, 0.0)
    upper = distance_sq[np.triu_indices(take, k=1)]
    median = float(np.median(upper)) if upper.size else 0.0
    if median <= 1e-12:
        return 1.0
    return 1.0 / median


def _rbf(left: np.ndarray, right: np.ndarray, gamma: float) -> np.ndarray:
    left64 = np.asarray(left, dtype=float)
    right64 = np.asarray(right, dtype=float)
    left_sq = np.sum(left64 * left64, axis=1, keepdims=True)
    right_sq = np.sum(right64 * right64, axis=1, keepdims=True).T
    distance_sq = np.maximum(left_sq + right_sq - 2.0 * left64 @ right64.T, 0.0)
    return np.exp(-gamma * distance_sq)


def _center_kernel(kernel: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    column_mean = kernel.mean(axis=0)
    row_mean = kernel.mean(axis=1, keepdims=True)
    grand = float(kernel.mean())
    return kernel - row_mean - column_mean + grand, column_mean, grand


def _center_kernel_test(kernel: np.ndarray, column_mean: np.ndarray, grand: float) -> np.ndarray:
    return kernel - column_mean - kernel.mean(axis=1, keepdims=True) + grand


def _ols(features: np.ndarray, target: np.ndarray) -> tuple[np.ndarray, float, float]:
    design = np.column_stack([features, np.ones(features.shape[0])])
    coef, residuals, _rank, _singular = np.linalg.lstsq(design, target, rcond=None)
    if residuals.size:
        sse = float(residuals[0])
    else:
        sse = float(np.sum((target - design @ coef) ** 2))
    return coef[:-1], float(coef[-1]), sse


@dataclass
class MLREnsemble:
    """Average of the best variable subsets found by simulated annealing."""

    mean: np.ndarray
    scale: np.ndarray
    subsets: tuple[np.ndarray, ...]
    coefs: tuple[np.ndarray, ...]
    intercepts: tuple[float, ...]
    domain_cutoff: float = 0.0

    def predict(self, values: np.ndarray, _train: np.ndarray | None = None) -> np.ndarray:
        scaled = _scale_apply(values, self.mean, self.scale)
        parts = [
            scaled[:, subset] @ coef + intercept
            for subset, coef, intercept in zip(
                self.subsets, self.coefs, self.intercepts, strict=True
            )
        ]
        return np.mean(parts, axis=0)

    def domain_mask(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        query = _scale_apply(values, self.mean, self.scale)
        reference = _scale_apply(train, self.mean, self.scale)
        return _min_euclidean(query, reference) <= self.domain_cutoff


@dataclass
class ScaledEstimator:
    """A scikit-learn model fit on z-scored descriptors."""

    model: object
    mean: np.ndarray
    scale: np.ndarray
    domain_cutoff: float = 0.0

    def predict(self, values: np.ndarray, _train: np.ndarray | None = None) -> np.ndarray:
        scaled = _scale_apply(values, self.mean, self.scale)
        return np.asarray(self.model.predict(scaled)).ravel()

    def probabilities(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        if not hasattr(self.model, "predict_proba"):
            return None
        scaled = _scale_apply(values, self.mean, self.scale)
        proba = np.asarray(self.model.predict_proba(scaled), dtype=float)
        return np.asarray(self.model.classes_), proba

    def domain_mask(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        query = _scale_apply(values, self.mean, self.scale)
        reference = _scale_apply(train, self.mean, self.scale)
        return _min_euclidean(query, reference) <= self.domain_cutoff


@dataclass
class BitEstimator:
    """Naive Bayes on unfolded fingerprint bits."""

    model: object
    domain_cutoff: float = 0.0

    def predict(self, values: np.ndarray, _train: np.ndarray | None = None) -> np.ndarray:
        return np.asarray(self.model.predict(np.asarray(values, dtype=float))).ravel()

    def probabilities(self, values: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
        proba = np.asarray(self.model.predict_proba(np.asarray(values, dtype=float)), dtype=float)
        return np.asarray(self.model.classes_), proba

    def domain_mask(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        similarity = _tanimoto(values, train)
        distance = 1.0 - similarity.max(axis=1)
        return distance <= self.domain_cutoff


@dataclass
class KernelPLS:
    """PLS on a centered Tanimoto or RBF kernel. Training rows are the support set."""

    model: object
    kernel: str
    gamma: float
    mean: np.ndarray | None
    scale: np.ndarray | None
    column_mean: np.ndarray
    grand_mean: float
    domain_cutoff: float = 0.0

    def _prepare(self, values: np.ndarray) -> np.ndarray:
        matrix = np.asarray(values, dtype=float)
        if self.mean is None or self.scale is None:
            return matrix
        return _scale_apply(matrix, self.mean, self.scale)

    def _kernel(self, left: np.ndarray, right: np.ndarray) -> np.ndarray:
        if self.kernel == "tanimoto":
            return _tanimoto(left, right)
        return _rbf(left, right, self.gamma)

    def predict(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        prepared = self._prepare(values)
        support = self._prepare(train)
        kernel = _center_kernel_test(
            self._kernel(prepared, support), self.column_mean, self.grand_mean
        )
        return np.asarray(self.model.predict(kernel)).ravel()

    def domain_mask(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        if self.kernel == "tanimoto":
            distance = 1.0 - _tanimoto(values, train).max(axis=1)
            return distance <= self.domain_cutoff
        query = self._prepare(values)
        reference = self._prepare(train)
        return _min_euclidean(query, reference) <= self.domain_cutoff


@dataclass
class FactorModel:
    """PLS or PCR on z-scored descriptors."""

    kind: str
    model: object
    mean: np.ndarray
    scale: np.ndarray
    domain_cutoff: float = 0.0

    def predict(self, values: np.ndarray, _train: np.ndarray | None = None) -> np.ndarray:
        scaled = _scale_apply(values, self.mean, self.scale)
        if self.kind == "pcr":
            pca, linear = self.model
            return np.asarray(linear.predict(pca.transform(scaled))).ravel()
        return np.asarray(self.model.predict(scaled)).ravel()

    def domain_mask(self, values: np.ndarray, train: np.ndarray) -> np.ndarray:
        query = _scale_apply(values, self.mean, self.scale)
        reference = _scale_apply(train, self.mean, self.scale)
        return _min_euclidean(query, reference) <= self.domain_cutoff


def prepare_domain(estimator: object, train: np.ndarray) -> None:
    """Set the training nearest-neighbor cutoff used as the applicability domain."""
    if isinstance(estimator, (MLREnsemble, ScaledEstimator, FactorModel)):
        reference = train
        if isinstance(estimator, MLREnsemble):
            reference = _scale_apply(train, estimator.mean, estimator.scale)
        elif isinstance(estimator, (ScaledEstimator, FactorModel)):
            reference = _scale_apply(train, estimator.mean, estimator.scale)
        estimator.domain_cutoff = euclidean_cutoff(reference)
        return
    if isinstance(estimator, BitEstimator):
        estimator.domain_cutoff = tanimoto_cutoff(train)
        return
    if isinstance(estimator, KernelPLS):
        if estimator.kernel == "tanimoto":
            estimator.domain_cutoff = tanimoto_cutoff(train)
        else:
            estimator.domain_cutoff = euclidean_cutoff(estimator._prepare(train))


def _latent_fit(
    y_train: np.ndarray,
    y_variance: float,
    max_factors: int,
    build: Callable[[int], tuple[object, np.ndarray]],
) -> tuple[object, np.ndarray, list[float]]:
    """Fit 1..k factors. Keep the last model whose training R² has not been passed by a later one."""
    chosen_model = None
    chosen_pred = None
    r2_values: list[float] = []
    for factors in range(1, max(1, max_factors) + 1):
        model, pred = build(factors)
        r2 = continuous_accuracy(y_train, pred, y_variance)
        if chosen_model is not None and r2 > R2_CAP:
            break
        chosen_model = model
        chosen_pred = pred
        r2_values.append(r2)
        if r2 > R2_CAP:
            break
    if chosen_model is None or chosen_pred is None:
        raise ValueError("No latent-factor model was fit.")
    return chosen_model, chosen_pred, r2_values


def _anneal_subsets(features: np.ndarray, target: np.ndarray, *, seed: int) -> MLREnsemble:
    _mean, _scale, scaled = _scale_fit(features)
    n_rows, n_cols = scaled.shape
    width = min(n_cols, subset_size_limit(n_rows))
    rng = np.random.default_rng(seed)
    if n_cols == width:
        subsets = [np.arange(n_cols, dtype=int)]
        steps = 0
    else:
        subsets = [np.sort(rng.choice(n_cols, size=width, replace=False))]
        steps = ANNEAL_STEPS
    current = subsets[0]
    _coef, _intercept, current_sse = _ols(scaled[:, current], target)
    found: list[tuple[float, tuple[int, ...]]] = [(current_sse, tuple(int(i) for i in current))]
    temperature = max(current_sse, 1.0)
    outside = [index for index in range(n_cols) if index not in set(current.tolist())]
    for _step in range(steps):
        if not outside:
            break
        trial = current.copy()
        out_pos = int(rng.integers(0, width))
        in_pos = int(rng.integers(0, len(outside)))
        removed = int(trial[out_pos])
        trial[out_pos] = outside[in_pos]
        trial.sort()
        _coef, _intercept, sse = _ols(scaled[:, trial], target)
        delta = sse - current_sse
        if delta <= 0.0 or rng.random() < math.exp(-delta / max(temperature, 1e-12)):
            outside[in_pos] = removed
            current = trial
            current_sse = sse
            found.append((current_sse, tuple(int(i) for i in trial)))
        temperature *= 0.995
    found.sort(key=lambda item: item[0])
    chosen: list[tuple[int, ...]] = []
    seen: set[tuple[int, ...]] = set()
    for _sse, columns in found:
        if columns in seen:
            continue
        seen.add(columns)
        chosen.append(columns)
        if len(chosen) == 5:
            break
    coefs = []
    intercepts = []
    subset_arrays = []
    for columns in chosen:
        index = np.asarray(columns, dtype=int)
        coef, intercept, _sse = _ols(scaled[:, index], target)
        subset_arrays.append(index)
        coefs.append(coef)
        intercepts.append(intercept)
    return MLREnsemble(
        mean=_mean,
        scale=_scale,
        subsets=tuple(subset_arrays),
        coefs=tuple(coefs),
        intercepts=tuple(intercepts),
    )


def _fit_factors_pls(train: np.ndarray, test: np.ndarray, y_train: np.ndarray, y_variance: float):
    from sklearn.cross_decomposition import PLSRegression

    max_factors = min(MAX_LATENT_FACTORS, train.shape[0] - 1, train.shape[1])

    def build(factors: int):
        model = PLSRegression(n_components=factors, scale=False)
        model.fit(train, y_train)
        return model, np.asarray(model.predict(train)).ravel()

    model, _train_pred, _r2 = _latent_fit(y_train, y_variance, max_factors, build)
    test_pred = np.asarray(model.predict(test)).ravel()
    return model, test_pred


def _fit_factors_pcr(train: np.ndarray, test: np.ndarray, y_train: np.ndarray, y_variance: float):
    from sklearn.decomposition import PCA
    from sklearn.linear_model import LinearRegression

    max_factors = min(MAX_LATENT_FACTORS, train.shape[0] - 1, train.shape[1])

    def build(factors: int):
        pca = PCA(n_components=factors, svd_solver="full")
        latent_train = pca.fit_transform(train)
        linear = LinearRegression()
        linear.fit(latent_train, y_train)
        return (pca, linear), np.asarray(linear.predict(latent_train)).ravel()

    model, train_pred, _r2 = _latent_fit(y_train, y_variance, max_factors, build)
    pca, linear = model
    test_pred = np.asarray(linear.predict(pca.transform(test))).ravel()
    del train_pred
    return model, test_pred


def _fit_kernel_pls(
    train: np.ndarray,
    y_train: np.ndarray,
    y_variance: float,
    *,
    kernel: str,
) -> KernelPLS:
    from sklearn.cross_decomposition import PLSRegression

    mean = None
    scale = None
    support = train
    gamma = 0.0
    if kernel == "rbf":
        mean, scale, support = _scale_fit(train)
        gamma = _rbf_gamma(support)

    def kernel_matrix(left: np.ndarray, right: np.ndarray) -> np.ndarray:
        if kernel == "tanimoto":
            return _tanimoto(left, right)
        return _rbf(left, right, gamma)

    train_kernel, column_mean, grand = _center_kernel(kernel_matrix(support, support))
    max_factors = min(MAX_LATENT_FACTORS, train.shape[0] - 1)

    def build(factors: int):
        model = PLSRegression(n_components=factors, scale=False)
        model.fit(train_kernel, y_train)
        return model, np.asarray(model.predict(train_kernel)).ravel()

    model, _train_pred, _r2 = _latent_fit(y_train, y_variance, max_factors, build)
    return KernelPLS(
        model=model,
        kernel=kernel,
        gamma=gamma,
        mean=mean,
        scale=scale,
        column_mean=column_mean,
        grand_mean=grand,
    )


def fit_split_model(
    method: str,
    values: np.ndarray,
    y: np.ndarray,
    train_index: np.ndarray,
    test_index: np.ndarray,
    *,
    task: str,
    split_index: int,
):
    """Fit one model. Returns ``(estimator, train_pred, test_pred, n_features)``."""
    train = np.asarray(values[train_index], dtype=float)
    test = np.asarray(values[test_index], dtype=float)
    y_train = np.asarray(y)[train_index]
    train_variance = population_variance(y_train)
    if method == "mlr":
        estimator = _anneal_subsets(train, y_train, seed=10_000 + split_index)
        train_pred = estimator.predict(train)
        test_pred = estimator.predict(test)
        n_features = int(estimator.subsets[0].size) if estimator.subsets else 0
        return estimator, train_pred, test_pred, n_features
    if method in {"pls", "pcr", "kpls"} and task == "regression":
        if method == "kpls":
            kernel = "tanimoto" if _looks_binary(train) else "rbf"
            estimator = _fit_kernel_pls(train, y_train, train_variance, kernel=kernel)
            train_pred = estimator.predict(train, train)
            test_pred = estimator.predict(test, train)
            return estimator, train_pred, test_pred, int(train.shape[1])
        mean, scale, scaled_train = _scale_fit(train)
        scaled_test = _scale_apply(test, mean, scale)
        if method == "pls":
            model, test_pred = _fit_factors_pls(scaled_train, scaled_test, y_train, train_variance)
            estimator = FactorModel(kind="pls", model=model, mean=mean, scale=scale)
        else:
            model, test_pred = _fit_factors_pcr(scaled_train, scaled_test, y_train, train_variance)
            estimator = FactorModel(kind="pcr", model=model, mean=mean, scale=scale)
        train_pred = estimator.predict(train)
        return estimator, train_pred, test_pred, int(train.shape[1])
    if method == "bayes":
        if _looks_binary(train):
            from sklearn.naive_bayes import BernoulliNB

            model = BernoulliNB(alpha=1.0)
            model.fit(train, y_train)
            estimator = BitEstimator(model=model)
        else:
            from sklearn.naive_bayes import GaussianNB

            mean, scale, scaled_train = _scale_fit(train)
            model = GaussianNB()
            model.fit(scaled_train, y_train)
            estimator = ScaledEstimator(model=model, mean=mean, scale=scale)
        train_pred = estimator.predict(train)
        test_pred = estimator.predict(test)
        return estimator, train_pred, test_pred, int(train.shape[1])
    if method == "rp":
        from sklearn.ensemble import BaggingClassifier
        from sklearn.tree import DecisionTreeClassifier

        mean, scale, scaled_train = _scale_fit(train)
        sample_size = max(1, int(TREE_SAMPLE * scaled_train.shape[0]))
        model = BaggingClassifier(
            estimator=DecisionTreeClassifier(random_state=split_index),
            n_estimators=TREE_COUNT,
            max_samples=sample_size,
            bootstrap=False,
            random_state=split_index,
            n_jobs=1,
        )
        model.fit(scaled_train, y_train)
        estimator = ScaledEstimator(model=model, mean=mean, scale=scale)
        train_pred = estimator.predict(train)
        test_pred = estimator.predict(test)
        return estimator, train_pred, test_pred, int(train.shape[1])
    raise ValueError(f"Unknown Quick QSAR method: {method}")


def _looks_binary(values: np.ndarray) -> bool:
    unique = np.unique(np.asarray(values))
    return unique.size > 0 and np.all((unique == 0.0) | (unique == 1.0))


def score_predictions(
    y: np.ndarray,
    train_index: np.ndarray,
    test_index: np.ndarray,
    train_pred: np.ndarray,
    test_pred: np.ndarray,
    *,
    task: str,
    learning_variance: float,
    classes: Sequence,
) -> tuple[float, float, float]:
    """Return ``(score, train_accuracy, test_accuracy)``."""
    y_train = np.asarray(y)[train_index]
    y_test = np.asarray(y)[test_index]
    if task == "regression":
        train_accuracy = continuous_accuracy(y_train, train_pred, population_variance(y_train))
        test_accuracy = continuous_accuracy(y_test, test_pred, learning_variance)
    else:
        train_accuracy = categorical_accuracy(y_train, train_pred, classes)
        test_accuracy = categorical_accuracy(y_test, test_pred, classes)
    return split_score(train_accuracy, test_accuracy), train_accuracy, test_accuracy


def fit_errors() -> tuple[type[BaseException], ...]:
    return _FIT_ERRORS
