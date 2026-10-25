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

"""Shared ordinary least squares used by Free-Wilson and Hansch."""

from __future__ import annotations

import numpy as np

from molmanager.analysis.linear_fit import (
    design_columns_with_intercept,
    fit_linear,
    independent_column_indices,
)


def test_exact_line_recovers_intercept_and_slope() -> None:
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = 1.0 + 2.0 * x
    fit = fit_linear(y, x.reshape(-1, 1))
    assert abs(fit.intercept - 1.0) < 1e-8
    assert abs(fit.coefficients[0] - 2.0) < 1e-8
    assert abs(fit.r_squared - 1.0) < 1e-8
    assert fit.n_parameters == 2
    assert fit.residual_df == 2
    assert fit.vif[0] == 1.0
    assert fit.q_squared is not None and abs(fit.q_squared - 1.0) < 1e-6


def test_noisy_line_reports_t_and_p() -> None:
    x = np.array([0.0, 1.0, 2.0, 3.0])
    y = np.array([1.0, 2.0, 2.0, 4.0])
    fit = fit_linear(y, x.reshape(-1, 1))
    slope, _residual, _rank, _singular = np.linalg.lstsq(
        np.column_stack([np.ones(4), x]),
        y,
        rcond=None,
    )
    assert abs(fit.intercept - float(slope[0])) < 1e-8
    assert abs(fit.coefficients[0] - float(slope[1])) < 1e-8
    assert fit.coefficient_t[0] is not None
    assert fit.coefficient_p[0] is not None
    assert 0.0 <= fit.coefficient_p[0] <= 1.0
    assert fit.r_squared < 1.0


def test_constant_column_is_not_independent_of_the_intercept() -> None:
    varying = np.array([0.0, 1.0, 2.0])
    constant = np.array([5.0, 5.0, 5.0])
    design = np.column_stack([varying, constant])
    assert design_columns_with_intercept(design) == [0]
    assert independent_column_indices(design) == [0, 1]


def test_duplicate_column_has_infinite_vif() -> None:
    column = np.array([0.0, 1.0, 2.0, 3.0])
    design = np.column_stack([column, 2.0 * column])
    fit = fit_linear(np.array([1.0, 2.0, 3.0, 4.0]), design)
    assert float("inf") in fit.vif
    assert len(design_columns_with_intercept(design)) == 1


def test_orthogonal_columns_have_unit_vif() -> None:
    first = np.array([0.0, 1.0, 0.0, 1.0])
    second = np.array([0.0, 0.0, 1.0, 1.0])
    fit = fit_linear(first + 2.0 * second, np.column_stack([first, second]))
    assert abs(fit.vif[0] - 1.0) < 1e-8
    assert abs(fit.vif[1] - 1.0) < 1e-8
    assert abs(fit.coefficients[0] - 1.0) < 1e-8
    assert abs(fit.coefficients[1] - 2.0) < 1e-8
