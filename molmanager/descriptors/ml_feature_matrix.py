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

"""Build numeric + fingerprint feature matrices for ML tools (PCA, QSAR, etc.)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CombinedFeatureMatrix:
    """Aligned feature matrix and row metadata."""

    X: np.ndarray
    oids: list[int]
    df_positions: list[int]
    n_numeric_features: int
    feature_names: list[str]
    summary: str


def standardize_feature_matrix(
    X: np.ndarray,
    n_numeric: int,
    *,
    enabled: bool,
    scaler_state: Any | None = None,
    fit: bool = True,
) -> tuple[np.ndarray, Any | None]:
    """
    Scale only the first ``n_numeric`` columns (descriptor columns); leave fingerprint bits as-is.

    ``scaler_state`` is a fitted ``StandardScaler`` when ``fit`` is False.
    """
    if not enabled or n_numeric <= 0 or X.size == 0:
        return X, None
    from sklearn.preprocessing import StandardScaler

    X_out = np.asarray(X, dtype=float).copy()
    if n_numeric >= X_out.shape[1]:
        if fit:
            scaler = StandardScaler()
            X_out = scaler.fit_transform(X_out)
            return X_out, scaler
        if scaler_state is None:
            return X_out, None
        return scaler_state.transform(X_out), scaler_state
    block = X_out[:, :n_numeric]
    if fit:
        scaler = StandardScaler()
        X_out[:, :n_numeric] = scaler.fit_transform(block)
        return X_out, scaler
    if scaler_state is None:
        return X_out, None
    X_out[:, :n_numeric] = scaler_state.transform(block)
    return X_out, scaler_state


def build_combined_feature_matrix(
    *,
    df: pd.DataFrame,
    oids: list[int],
    feature_columns: list[str] | None = None,
    mol_rows: list[tuple[int, object]] | None = None,
    fp_choice: str | None = None,
    min_rows: int = 2,
    activity_column: str | None = None,
) -> CombinedFeatureMatrix:
    """
    Build a feature matrix from numeric columns, fingerprints, or both (inner-joined on OID).

    Rows must have complete numeric values (when columns are selected) and valid fingerprints
    (when fingerprints are requested).
    """
    cols = [c for c in (feature_columns or []) if c in df.columns]
    use_fp = bool((fp_choice or "").strip() and mol_rows)
    if not cols and not use_fp:
        raise ValueError("Select at least one numeric column and/or include 2D fingerprints.")

    if len(oids) != len(df):
        raise ValueError("OID list length must match dataframe row count.")

    numeric_by_oid: dict[int, np.ndarray] = {}
    position_by_oid = {int(oids[pos]): int(pos) for pos in range(len(oids))}

    if cols:
        num = df[cols].apply(pd.to_numeric, errors="coerce")
        y_series = None
        if activity_column and activity_column in df.columns:
            y_series = pd.to_numeric(df[activity_column], errors="coerce")
        for pos in range(len(df)):
            if not num.iloc[pos].notna().all():
                continue
            if y_series is not None and not np.isfinite(float(y_series.iloc[pos])):
                continue
            oid = int(oids[pos])
            numeric_by_oid[oid] = num.iloc[pos].to_numpy(dtype=float)

    fp_by_oid: dict[int, np.ndarray] = {}
    n_fp_bits = 0
    if use_fp:
        from ..analysis.dimensionality_reduction import build_fingerprint_matrix

        X_fp, fp_oids = build_fingerprint_matrix(mol_rows, str(fp_choice))
        n_fp_bits = int(X_fp.shape[1])
        for j, oid in enumerate(fp_oids):
            fp_by_oid[int(oid)] = X_fp[j]

    if cols and use_fp:
        common = sorted(set(numeric_by_oid.keys()) & set(fp_by_oid.keys()))
    elif cols:
        common = sorted(numeric_by_oid.keys())
    else:
        common = sorted(fp_by_oid.keys())

    if len(common) < int(min_rows):
        parts = []
        if cols:
            parts.append("numeric descriptor data")
        if use_fp:
            parts.append("valid fingerprints")
        need = " and ".join(parts) if parts else "features"
        raise ValueError(
            f"Need at least {min_rows} rows with {need} in the current scope (found {len(common)})."
        )

    feat_names: list[str] = list(cols)
    if use_fp:
        feat_names.extend(f"FP_bit_{i}" for i in range(n_fp_bits))

    if cols and use_fp:
        # Numeric columns are few. Bits stay float32 here so the join does not promote to float64.
        numeric = np.vstack([numeric_by_oid[oid] for oid in common]).astype(np.float32, copy=False)
        bits = np.vstack([fp_by_oid[oid] for oid in common]).astype(np.float32, copy=False)
        X = np.hstack([numeric, bits])
    elif use_fp:
        X = np.vstack([fp_by_oid[oid] for oid in common])
    else:
        X = np.vstack([numeric_by_oid[oid] for oid in common])
    df_positions = [position_by_oid[oid] for oid in common]

    summary_parts: list[str] = []
    if cols:
        summary_parts.append(f"Numeric columns ({len(cols)}): {', '.join(cols)}")
    if use_fp:
        summary_parts.append(f"Fingerprint: {fp_choice}\nFingerprint bits: {n_fp_bits}")
    summary_parts.append(f"Total features: {X.shape[1]}  |  Rows: {len(common)}")
    summary = "\n".join(summary_parts)

    return CombinedFeatureMatrix(
        X=X,
        oids=common,
        df_positions=df_positions,
        n_numeric_features=len(cols),
        feature_names=feat_names,
        summary=summary,
    )
