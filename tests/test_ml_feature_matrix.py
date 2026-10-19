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

"""Tests for combined numeric + fingerprint feature matrices."""

from __future__ import annotations

import numpy as np
import pandas as pd
from rdkit import Chem

from molmanager.descriptors.ml_feature_matrix import (
    build_combined_feature_matrix,
    standardize_feature_matrix,
)


def _mol(smiles: str = "CCO") -> Chem.Mol:
    return Chem.MolFromSmiles(smiles)


def test_combined_numeric_and_fingerprint():
    n = 12
    df = pd.DataFrame(
        {
            "MW": np.linspace(100, 200, n),
            "LogP": np.linspace(0, 3, n),
        }
    )
    oids = list(range(n))
    mol_rows = [(i, _mol("CCO" if i % 2 == 0 else "c1ccccc1")) for i in oids]
    built = build_combined_feature_matrix(
        df=df,
        oids=oids,
        feature_columns=["MW", "LogP"],
        mol_rows=mol_rows,
        fp_choice="MACCS (166)",
        min_rows=2,
    )
    assert built.X.shape[0] == n
    assert built.n_numeric_features == 2
    assert built.X.shape[1] > built.n_numeric_features
    assert built.X.dtype == np.float32


def test_fingerprint_only_matrix_is_uint8():
    mol_rows = [(0, _mol("CCO")), (1, _mol("c1ccccc1"))]
    built = build_combined_feature_matrix(
        df=pd.DataFrame({"x": [1.0, 2.0]}),
        oids=[0, 1],
        feature_columns=[],
        mol_rows=mol_rows,
        fp_choice="MACCS (166)",
        min_rows=2,
    )
    assert built.X.dtype == np.uint8
    assert set(np.unique(built.X)).issubset({0, 1})


def test_standardize_numeric_block_only():
    X = np.array([[1.0, 0.0, 0.0], [3.0, 1.0, 0.0], [5.0, 0.0, 1.0]])
    Xs, scaler = standardize_feature_matrix(X, 1, enabled=True, fit=True)
    assert scaler is not None
    assert np.isclose(np.mean(Xs[:, 0]), 0.0, atol=1e-10)
    assert Xs[0, 1] == 0.0
    assert Xs[0, 2] == 0.0
