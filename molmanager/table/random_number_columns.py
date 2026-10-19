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

"""Generate random numbers for table columns (Tools → Random → Number)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

DistributionName = Literal["uniform", "integer", "normal"]
RANDOM_NUMBER_DISTRIBUTION_LABELS: tuple[tuple[DistributionName, str], ...] = (
    ("uniform", "Uniform (continuous)"),
    ("integer", "Uniform (integer)"),
    ("normal", "Normal (Gaussian)"),
)


@dataclass(frozen=True)
class RandomNumberParams:
    """Settings for filling a column with random values."""

    distribution: DistributionName
    low: float
    high: float
    mean: float = 0.0
    std: float = 1.0
    seed: int | None = None
    decimals: int = 4
    clip_normal: bool = False


def generate_random_values(n: int, params: RandomNumberParams) -> list[str]:
    """
    Return *n* formatted numeric strings drawn from *params*.

    Raises ``ValueError`` for invalid settings (empty range, non-positive std, etc.).
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return []

    dist = params.distribution
    rng = np.random.default_rng(params.seed)

    if dist == "uniform":
        low, high = float(params.low), float(params.high)
        if not (high > low):
            raise ValueError("Maximum must be greater than minimum for a uniform distribution.")
        values = rng.uniform(low, high, size=n)
        return [_format_float(float(v), params.decimals) for v in values]

    if dist == "integer":
        low_i = int(round(params.low))
        high_i = int(round(params.high))
        if high_i < low_i:
            raise ValueError("Maximum must be greater than or equal to minimum for integers.")
        # NumPy Generator.integers high is exclusive; use high_i + 1 for inclusive.
        values = rng.integers(low_i, high_i + 1, size=n)
        return [str(int(v)) for v in values]

    if dist == "normal":
        std = float(params.std)
        if std <= 0:
            raise ValueError("Standard deviation must be positive for a normal distribution.")
        values = rng.normal(float(params.mean), std, size=n)
        if params.clip_normal:
            low, high = float(params.low), float(params.high)
            if not (high > low):
                raise ValueError(
                    "Maximum must be greater than minimum when clipping a normal draw."
                )
            values = np.clip(values, low, high)
        return [_format_float(float(v), params.decimals) for v in values]

    raise ValueError(f"Unknown distribution: {dist!r}")


def _format_float(value: float, decimals: int) -> str:
    decimals = max(0, min(int(decimals), 12))
    if decimals == 0:
        return str(int(round(value)))
    return f"{value:.{decimals}f}"
