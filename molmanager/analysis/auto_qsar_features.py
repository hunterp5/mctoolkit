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

"""RDKit 2D descriptors, unfolded fingerprints, and the descriptor filter.

Drop a column when 90% of the learning set shares one value or its variance is
below ``1e-12 * (sum x^2) / N``, then keep one representative from each
single-linkage cluster whose absolute Pearson correlation is at least 0.8.
Dixon et al. describe this filter in Future Med. Chem. 2016
(10.4155/fmc-2016-0093).
"""

from __future__ import annotations

import threading
from collections.abc import Sequence

import numpy as np

DESCRIPTOR_SET = "Descriptors"
MAX_FINGERPRINT_BITS = 10_000
MIN_LEARNING_ROWS = 8
_CORR_LIMIT = 0.8
_IDENTICAL_FRACTION = 0.90
_VARIANCE_SCALE = 1e-12

# Ipc grows without a useful bound. qed is a drug-likeness model. Morgan
# densities repeat the radial fingerprint. The unspecified-stereocenter count
# changes when a wedge is added to the same structure.
EXCLUDED_RDKIT_DESCRIPTORS = frozenset(
    {
        "Ipc",
        "qed",
        "FpDensityMorgan1",
        "FpDensityMorgan2",
        "FpDensityMorgan3",
        "NumUnspecifiedAtomStereoCenters",
    }
)

FINGERPRINT_SETS: tuple[tuple[str, str], ...] = (
    ("Radial (Morgan r=2)", "morgan"),
    ("Linear (RDKit path)", "rdk"),
    ("Dendritic (atom pair)", "atom_pair"),
    ("MOLPRINT2D (feature-Morgan r=2)", "fcfp"),
)


class AutoQSARCancelled(Exception):
    """Raised when a search sees the job cancel event."""


_CALC_ERRORS = (
    ValueError,
    TypeError,
    RuntimeError,
    ArithmeticError,
    AttributeError,
    KeyError,
    IndexError,
)

_rdkit_names: tuple[str, ...] | None = None
_rdkit_funcs: tuple | None = None
_fp_generators: dict | None = None


def rdkit_descriptor_names() -> tuple[str, ...]:
    """Scalar RDKit descriptors Quick QSAR calculates, in column order.

    Autocorrelation and MQN lengths are appended when a molecule is calculated,
    because those vectors are not in ``Descriptors.descList``.
    """
    global _rdkit_names, _rdkit_funcs
    if _rdkit_names is None:
        from rdkit.Chem import Descriptors

        names: list[str] = []
        funcs = []
        for name, fn in Descriptors.descList:
            if name in EXCLUDED_RDKIT_DESCRIPTORS:
                continue
            names.append(str(name))
            funcs.append(fn)
        _rdkit_names = tuple(names)
        _rdkit_funcs = tuple(funcs)
    return _rdkit_names


def _call_descriptor(fn, mol) -> float:
    try:
        value = float(fn(mol))
    except _CALC_ERRORS:
        return float("nan")
    if not np.isfinite(value):
        return float("nan")
    return value


def _vector_descriptor(fn, mol) -> np.ndarray | None:
    try:
        raw = fn(mol)
    except _CALC_ERRORS:
        return None
    values = np.asarray(list(raw), dtype=float)
    if values.size == 0 or not np.isfinite(values).any():
        return None
    return values


def descriptor_matrix(
    mols: Sequence[object | None],
    *,
    cancel_event: threading.Event | None = None,
    on_row=None,
) -> tuple[tuple[str, ...], np.ndarray]:
    """Calculate the RDKit 2D pool. A missing structure is an all-missing row."""
    from rdkit.Chem import rdMolDescriptors

    scalar_names = rdkit_descriptor_names()
    funcs = _rdkit_funcs or ()
    n_rows = len(mols)
    autocorr_len = 0
    mqn_len = 0
    for mol in mols:
        if mol is None:
            continue
        sample_ac = _vector_descriptor(rdMolDescriptors.CalcAUTOCORR2D, mol)
        sample_mqn = _vector_descriptor(rdMolDescriptors.MQNs_, mol)
        autocorr_len = 0 if sample_ac is None else int(sample_ac.size)
        mqn_len = 0 if sample_mqn is None else int(sample_mqn.size)
        break
    names = list(scalar_names)
    names.extend(f"AUTOCORR2D_{index}" for index in range(1, autocorr_len + 1))
    names.extend(f"MQN_{index}" for index in range(1, mqn_len + 1))
    matrix = np.full((n_rows, len(names)), np.nan, dtype=float)
    scalar_count = len(scalar_names)
    for row, mol in enumerate(mols):
        if cancel_event is not None and cancel_event.is_set():
            raise AutoQSARCancelled()
        if on_row is not None:
            on_row(row + 1, n_rows)
        if mol is None:
            continue
        for index, fn in enumerate(funcs):
            matrix[row, index] = _call_descriptor(fn, mol)
        autocorr = _vector_descriptor(rdMolDescriptors.CalcAUTOCORR2D, mol)
        if autocorr is not None:
            width = min(autocorr_len, int(autocorr.size))
            matrix[row, scalar_count : scalar_count + width] = autocorr[:width]
        mqn = _vector_descriptor(rdMolDescriptors.MQNs_, mol)
        if mqn is not None:
            start = scalar_count + autocorr_len
            width = min(mqn_len, int(mqn.size))
            matrix[row, start : start + width] = mqn[:width]
    return tuple(names), matrix


def _generators() -> dict:
    global _fp_generators
    if _fp_generators is None:
        from rdkit.Chem import rdFingerprintGenerator

        feature_invariants = rdFingerprintGenerator.GetMorganFeatureAtomInvGen()
        _fp_generators = {
            "morgan": rdFingerprintGenerator.GetMorganGenerator(radius=2),
            "fcfp": rdFingerprintGenerator.GetMorganGenerator(
                radius=2,
                atomInvariantsGenerator=feature_invariants,
            ),
            "atom_pair": rdFingerprintGenerator.GetAtomPairGenerator(),
        }
    return _fp_generators


def _on_bit_ids(mol, kind: str) -> np.ndarray:
    from rdkit.Chem import AllChem

    if kind == "rdk":
        unfolded = AllChem.UnfoldedRDKFingerprintCountBased(mol)
        return np.fromiter(unfolded.GetNonzeroElements().keys(), dtype=np.int64)
    fingerprint = _generators()[kind].GetSparseFingerprint(mol)
    return np.fromiter(fingerprint.GetOnBits(), dtype=np.int64)


def fingerprint_matrix(mols: Sequence[object], kind: str) -> tuple[np.ndarray, np.ndarray]:
    """Binary unfolded fingerprint. Columns are the highest-variance on-bits, capped at 10,000."""
    rows: list[np.ndarray] = []
    for mol in mols:
        try:
            rows.append(_on_bit_ids(mol, kind))
        except _CALC_ERRORS:
            rows.append(np.array([], dtype=np.int64))
    n_rows = len(rows)
    counts: dict[int, int] = {}
    for bits in rows:
        for bit in np.unique(bits):
            counts[int(bit)] = counts.get(int(bit), 0) + 1
    ranked: list[tuple[float, int]] = []
    for bit, count in counts.items():
        prevalence = count / n_rows if n_rows else 0.0
        variance = prevalence * (1.0 - prevalence)
        if variance > 0.0:
            ranked.append((variance, bit))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    chosen = [bit for _variance, bit in ranked[:MAX_FINGERPRINT_BITS]]
    bit_ids = np.asarray(chosen, dtype=np.int64)
    column = {int(bit): index for index, bit in enumerate(bit_ids)}
    matrix = np.zeros((n_rows, bit_ids.size), dtype=np.float32)
    for row, bits in enumerate(rows):
        for bit in bits:
            index = column.get(int(bit))
            if index is not None:
                matrix[row, index] = 1.0
    return bit_ids, matrix


def _population_variance(values: np.ndarray) -> float:
    if values.size == 0:
        return 0.0
    centered = values - float(np.mean(values))
    return float(np.mean(centered * centered))


def _descriptor_column_ok(column: np.ndarray, n_rows: int) -> bool:
    finite = column[np.isfinite(column)]
    if n_rows <= 0 or finite.size < _IDENTICAL_FRACTION * n_rows:
        return False
    _unique, counts = np.unique(finite, return_counts=True)
    if int(counts.max()) >= _IDENTICAL_FRACTION * n_rows:
        return False
    variance = _population_variance(finite)
    threshold = _VARIANCE_SCALE * (float(np.dot(finite, finite)) / n_rows)
    return variance >= threshold


def _cluster_representatives(block: np.ndarray) -> list[int]:
    """Indices of one centroid-nearest descriptor from each correlation cluster."""
    n_cols = int(block.shape[1])
    if n_cols <= 1:
        return list(range(n_cols))
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(block, rowvar=False)
    corr = np.asarray(corr, dtype=float)
    if corr.ndim != 2:
        return list(range(n_cols))
    corr = np.nan_to_num(corr, nan=0.0, posinf=0.0, neginf=0.0)
    corr = np.clip(corr, -1.0, 1.0)
    distance = np.clip(1.0 - np.abs(corr), 0.0, 1.0)
    distance = (distance + distance.T) * 0.5
    np.fill_diagonal(distance, 0.0)
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    condensed = squareform(distance, checks=False)
    if condensed.size == 0:
        return list(range(n_cols))
    linked = linkage(condensed, method="single")
    labels = fcluster(linked, t=1.0 - _CORR_LIMIT, criterion="distance")
    scaled = block.astype(float, copy=True)
    center = scaled.mean(axis=0)
    spread = scaled.std(axis=0)
    spread[spread < 1e-12] = 1.0
    scaled = (scaled - center) / spread
    chosen: list[int] = []
    for label in np.unique(labels):
        members = np.flatnonzero(labels == label)
        if members.size == 1:
            chosen.append(int(members[0]))
            continue
        centroid = scaled[:, members].mean(axis=1)
        member_distance = [
            float(np.linalg.norm(scaled[:, int(member)] - centroid)) for member in members
        ]
        chosen.append(int(members[int(np.argmin(member_distance))]))
    chosen.sort()
    return chosen


def select_descriptor_columns(
    values: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, str | None]:
    """Return ``(row_indices, column_indices, note)`` for the descriptor pool.

    Rows still missing a kept column are dropped. When those holes sit on
    different columns, the sparsest remaining column is removed until the
    complete learning set reaches :data:`MIN_LEARNING_ROWS` or no column is
    sparse.
    """
    matrix = np.asarray(values, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] == 0 or matrix.shape[1] == 0:
        return np.array([], dtype=int), np.array([], dtype=int), None
    n_rows = int(matrix.shape[0])
    active = [
        index for index in range(matrix.shape[1]) if _descriptor_column_ok(matrix[:, index], n_rows)
    ]
    note = None
    rows = np.array([], dtype=int)
    target = min(MIN_LEARNING_ROWS, n_rows)
    while active:
        block = matrix[:, active]
        rows = np.flatnonzero(np.isfinite(block).all(axis=1))
        if rows.size >= target:
            break
        missing_rate = (~np.isfinite(block)).mean(axis=0)
        worst = int(np.argmax(missing_rate))
        if float(missing_rate[worst]) <= 0.0:
            break
        active.pop(worst)
        note = (
            "Dropped descriptors that were missing on different rows "
            "so the learning set could stay complete."
        )
    if rows.size < target or not active:
        return rows, np.array([], dtype=int), note
    representatives = _cluster_representatives(matrix[np.ix_(rows, active)])
    columns = np.array(sorted(active[index] for index in representatives), dtype=int)
    return rows, columns, note
