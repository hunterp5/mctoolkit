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

"""Ordinary least squares shared by Free-Wilson and Hansch.

The design matrix does not include an intercept column. :func:`fit_linear`
adds one. Rank uses the same column-pivoted QR cutoff Free-Wilson used before
this module existed, so moving the fit here does not change those coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import t as student_t

RANK_TOL = 1e-8


@dataclass(frozen=True)
class LinearFit:
    """One intercept-plus-design fit and its classical diagnostics."""

    intercept: float
    coefficients: tuple[float, ...]
    intercept_std_error: float | None
    coefficient_std_errors: tuple[float | None, ...]
    intercept_t: float | None
    coefficient_t: tuple[float | None, ...]
    intercept_p: float | None
    coefficient_p: tuple[float | None, ...]
    r_squared: float
    adjusted_r_squared: float | None
    q_squared: float | None
    rmse: float | None
    residual_df: int
    saturated: bool
    n: int
    n_parameters: int
    covariance: np.ndarray | None
    predictions: tuple[float, ...]
    residuals: tuple[float, ...]
    vif: tuple[float | None, ...]


def independent_column_indices(design: np.ndarray) -> list[int]:
    """Column-pivoted QR indices that span *design*.

    An empty matrix has no columns. The rank cutoff is ``RANK_TOL`` times the
    leading diagonal entry, matching the Free-Wilson substituent matrix.
    """
    if design.size == 0 or design.shape[1] == 0:
        return []
    from scipy.linalg import qr

    _q, r_matrix, pivots = qr(design, mode="economic", pivoting=True)
    diagonal = np.abs(np.diag(r_matrix))
    if diagonal.size == 0 or diagonal[0] <= 0.0:
        return []
    rank = int(np.sum(diagonal > (RANK_TOL * float(diagonal[0]))))
    return sorted(int(index) for index in pivots[:rank])


def design_columns_with_intercept(design: np.ndarray) -> list[int]:
    """Indices of *design* columns that stay independent beside an intercept.

    Columns are centered first, so a constant column has no remaining rank and
    is left out. The intercept itself is always kept by :func:`fit_linear`.
    """
    matrix = np.asarray(design, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        return []
    centered = matrix - matrix.mean(axis=0, keepdims=True)
    return independent_column_indices(centered)


def linear_standard_error(weights: np.ndarray, covariance: np.ndarray) -> float:
    """Standard error of a linear combination of the fitted coefficients.

    *weights* is aligned with the covariance, whose first entry is the intercept.
    """
    variance = float(weights @ covariance @ weights)
    return float(np.sqrt(max(variance, 0.0)))


def fit_linear(y: np.ndarray, design: np.ndarray) -> LinearFit:
    """Fit *y* on an intercept plus *design*.

    *design* has one row per observation and one column per regressor. Leave-one-out
    q² uses the hat-matrix form of the prediction error. Variance-inflation factors
    are per design column, not the intercept. A column that does not vary, or that
    is an exact linear combination of the others, has no finite VIF.
    """
    activity = np.asarray(y, dtype=float).reshape(-1)
    matrix = np.asarray(design, dtype=float)
    if matrix.ndim == 1:
        matrix = matrix.reshape(-1, 1)
    if matrix.ndim != 2:
        raise ValueError("Design matrix must be two-dimensional.")
    if matrix.shape[0] != activity.shape[0]:
        raise ValueError("Activity and the design matrix have different lengths.")
    if activity.size == 0:
        raise ValueError("Need at least one observation.")
    if not np.all(np.isfinite(activity)):
        raise ValueError("Activity contains a non-finite value.")
    if matrix.size and not np.all(np.isfinite(matrix)):
        raise ValueError("Design matrix contains a non-finite value.")

    n = int(activity.shape[0])
    n_columns = int(matrix.shape[1])
    ones = np.ones((n, 1), dtype=float)
    predictors = ones if n_columns == 0 else np.column_stack([ones, matrix])
    beta, residual, sse, sst, r_squared = _fit_predictors(activity, predictors)
    n_parameters = int(predictors.shape[1])
    dof = n - n_parameters
    adjusted = None
    if dof > 0 and n > 1:
        adjusted = 1.0 - (1.0 - r_squared) * (n - 1) / dof
    rmse = float(np.sqrt(sse / n)) if n else None
    covariance = None
    intercept_se = None
    coefficient_se: list[float | None] = [None] * n_columns
    if dof > 0:
        covariance = _covariance(predictors, sse / dof)
        stderr = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        intercept_se = float(stderr[0])
        for offset in range(n_columns):
            coefficient_se[offset] = float(stderr[offset + 1])
    intercept_t, intercept_p = _t_and_p(float(beta[0]), intercept_se, dof)
    coefficient_t: list[float | None] = []
    coefficient_p: list[float | None] = []
    for offset, value in enumerate(beta[1:]):
        stat, probability = _t_and_p(float(value), coefficient_se[offset], dof)
        coefficient_t.append(stat)
        coefficient_p.append(probability)
    return LinearFit(
        intercept=float(beta[0]),
        coefficients=tuple(float(value) for value in beta[1:]),
        intercept_std_error=intercept_se,
        coefficient_std_errors=tuple(coefficient_se),
        intercept_t=intercept_t,
        coefficient_t=tuple(coefficient_t),
        intercept_p=intercept_p,
        coefficient_p=tuple(coefficient_p),
        r_squared=float(r_squared),
        adjusted_r_squared=None if adjusted is None else float(adjusted),
        q_squared=_loo_q_squared(predictors, residual, sst),
        rmse=rmse,
        residual_df=int(dof),
        saturated=dof <= 0,
        n=n,
        n_parameters=n_parameters,
        covariance=covariance,
        predictions=tuple(float(value) for value in (predictors @ beta)),
        residuals=tuple(float(value) for value in residual),
        vif=_variance_inflation(matrix),
    )


def _fit_predictors(
    y: np.ndarray,
    predictors: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, float, float, float]:
    beta, _residuals, _rank, _singular = np.linalg.lstsq(predictors, y, rcond=None)
    predicted = predictors @ beta
    residual = y - predicted
    sse = float(residual @ residual)
    centered = y - float(np.mean(y))
    sst = float(centered @ centered)
    r_squared = 1.0 if sst <= RANK_TOL else 1.0 - (sse / sst)
    return beta, residual, sse, sst, float(r_squared)


def _covariance(predictors: np.ndarray, sigma2: float) -> np.ndarray:
    gram = predictors.T @ predictors
    try:
        inverse = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        inverse = np.linalg.pinv(gram)
    return sigma2 * inverse


def _t_and_p(
    coefficient: float, std_error: float | None, dof: int
) -> tuple[float | None, float | None]:
    """Two-sided t statistic and p-value. A zero standard error has neither."""
    if std_error is None or std_error <= 0.0 or dof <= 0 or not np.isfinite(std_error):
        return None, None
    stat = float(coefficient / std_error)
    if not np.isfinite(stat):
        return None, None
    probability = float(2.0 * student_t.sf(abs(stat), dof))
    return stat, min(probability, 1.0)


def _loo_q_squared(predictors: np.ndarray, residual: np.ndarray, sst: float) -> float | None:
    """Leave-one-out q² from leverage. ``None`` when a point cannot be left out."""
    if sst <= RANK_TOL:
        return None
    n, n_parameters = predictors.shape
    if n <= n_parameters:
        return None
    gram = predictors.T @ predictors
    try:
        inverse = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        inverse = np.linalg.pinv(gram)
    leverage = np.sum((predictors @ inverse) * predictors, axis=1)
    denom = 1.0 - leverage
    if np.any(denom <= RANK_TOL):
        return None
    press = float(np.sum((residual / denom) ** 2))
    return 1.0 - (press / sst)


def _variance_inflation(design: np.ndarray) -> tuple[float | None, ...]:
    """VIF of each design column against the intercept and the other columns."""
    if design.ndim != 2 or design.shape[1] == 0:
        return ()
    n, n_columns = design.shape
    vifs: list[float | None] = []
    for index in range(n_columns):
        column = design[:, index]
        if float(np.std(column)) <= RANK_TOL:
            vifs.append(None)
            continue
        others = np.delete(design, index, axis=1)
        ones = np.ones((n, 1), dtype=float)
        predictors = ones if others.shape[1] == 0 else np.column_stack([ones, others])
        _beta, _residual, _sse, _sst, r_squared = _fit_predictors(column, predictors)
        if r_squared >= 1.0 - RANK_TOL:
            vifs.append(float("inf"))
        else:
            vifs.append(1.0 / (1.0 - r_squared))
    return tuple(vifs)
