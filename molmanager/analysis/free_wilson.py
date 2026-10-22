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

"""Additive Free-Wilson / Fujita-Ban analysis (no Qt).

One least-squares fit is reported two ways. Fujita-Ban coefficients are the
activity change versus a reference substituent (hydrogen when that position has
it, otherwise the most common). Free-Wilson recenters each position so the
occurrence-weighted coefficients sum to zero. Predicted activities match.
"""

from __future__ import annotations

import heapq
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from itertools import product
from threading import Event

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdRGroupDecomposition

logger = logging.getLogger(__name__)

HYDROGEN_KEY = "H"
REPORT_FUJITA_BAN = "fujita_ban"
REPORT_FREE_WILSON = "free_wilson"
DEFAULT_MIN_COUNT = 2
DEFAULT_MAX_NEW_STRUCTURES = 500
ENUMERATION_PRODUCT_LIMIT = 1_000_000
PREDICTED_COLUMN = "FW_Predicted"
SOURCE_COLUMN = "FW_Source"
SOURCE_VALUE = "Free-Wilson"

SKIP_NO_MATCH = "no core match"
SKIP_RARE = "rare substituent"
SKIP_INCOMPLETE = "incomplete decomposition"
SKIP_ACTIVITY = "no numeric activity"

_RDKIT_ERRORS = (RuntimeError, ValueError, TypeError, OSError)
_RANK_TOL = 1e-8
_PROGRESS_STRIDE = 8192

ProgressCallback = Callable[[str, int, int], None]


class _Cancelled(Exception):
    """Raised when the caller sets the cancel event."""


@dataclass(frozen=True)
class FreeWilsonSettings:
    """Fit and enumeration options. Structure scope stays in the dialog."""

    core_query: str
    activity_column: str = ""
    report: str = REPORT_FUJITA_BAN
    min_count: int = DEFAULT_MIN_COUNT
    max_new_structures: int = DEFAULT_MAX_NEW_STRUCTURES
    prefer_higher: bool = True
    only_match_at_r_groups: bool = True
    matching: str = "greedy"


@dataclass(frozen=True)
class SubstituentCoefficient:
    """One substituent's contribution in the requested report."""

    position: str
    key: str
    label: str
    count: int
    coefficient: float | None
    std_error: float | None
    is_reference: bool
    identifiable: bool


@dataclass(frozen=True)
class ObservedPrediction:
    """Observed activity and the additive prediction for one fitted row."""

    oid: int
    observed: float
    predicted: float
    residual: float
    substituents: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class MissingAnalog:
    """A substituent combination that was not in the fitted series."""

    smiles: str
    predicted: float
    substituents: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SkippedRow:
    """A row left out of the fit, with a short reason."""

    oid: int
    reason: str


@dataclass(frozen=True)
class FreeWilsonResult:
    """Fit, observed predictions, and any enumerated missing analogs."""

    ok: bool
    message: str
    cancelled: bool
    report: str
    activity_column: str
    n: int
    n_parameters: int
    r_squared: float | None
    adjusted_r_squared: float | None
    rmse: float | None
    residual_df: int
    saturated: bool
    intercept: float
    intercept_std_error: float | None
    coefficients: tuple[SubstituentCoefficient, ...]
    observed: tuple[ObservedPrediction, ...]
    missing: tuple[MissingAnalog, ...]
    skipped: tuple[SkippedRow, ...]
    enumeration_refused: bool
    enumeration_message: str
    enumeration_truncated: bool
    n_combinations: int
    n_missing: int
    n_zip_failed: int
    position_counts: tuple[tuple[str, int], ...]
    references: tuple[tuple[str, str], ...]


@dataclass
class _FittedSub:
    position: str
    key: str
    label: str
    count: int
    mol: Chem.Mol
    is_reference: bool
    column: int | None
    fb_coefficient: float
    identifiable: bool


@dataclass(frozen=True)
class _Choice:
    position: str
    key: str
    label: str
    mol: Chem.Mol
    fb_coefficient: float


@dataclass
class _DecompRow:
    oid: int
    mol: Chem.Mol
    activity: float
    subs: dict[str, str]
    labels: dict[str, str]


def report_label(report: str) -> str:
    """User-facing name for a coefficient parameterization."""
    if report == REPORT_FREE_WILSON:
        return "Free-Wilson"
    return "Fujita-Ban"


def parse_free_wilson_core(query: str) -> Chem.Mol | None:
    """Parse a core as SMARTS, then as SMILES. Returns ``None`` when neither works."""
    text = (query or "").strip()
    if not text:
        return None
    mol = Chem.MolFromSmarts(text)
    if mol is None:
        mol = Chem.MolFromSmiles(text)
    return mol


def rgroup_decomp_failure_message(exc: BaseException) -> str:
    """Turn RDKit core-decomposition failures into short UI text."""
    msg = (str(exc) or "").strip()
    low = msg.lower()
    if "could not prepare" in low and "core" in low:
        return (
            "RDKit could not prepare the core for Free-Wilson decomposition. "
            "Check that dummy atoms ([*], [1*], …) label attachment sites correctly and that "
            "the pattern is valid SMARTS (or try a simpler core)."
        )
    if "invariant violation" in low and "core" in low:
        return (
            "Free-Wilson decomposition failed while processing the core. "
            "Verify the core SMARTS/SMILES and R-group dummy labels match your row structures."
        )
    return msg or "Free-Wilson decomposition failed."


def run_free_wilson(
    records: Sequence[tuple[int, Chem.Mol, float]],
    settings: FreeWilsonSettings,
    *,
    cancel_event: Event | None = None,
    progress: ProgressCallback | None = None,
    enumeration_product_limit: int = ENUMERATION_PRODUCT_LIMIT,
) -> FreeWilsonResult:
    """Decompose *records*, fit the additive model, and list missing combinations.

    *records* are ``(oid, mol, activity)``. Rows that do not match the core, lack a
    finite activity, or contain a substituent below ``settings.min_count`` are
    skipped. When the cartesian product of fitted substituents exceeds
    *enumeration_product_limit*, the fit is still returned and ``missing`` is empty.
    """
    try:
        return _run(
            records,
            settings,
            cancel_event=cancel_event,
            progress=progress,
            enumeration_product_limit=max(1, int(enumeration_product_limit)),
        )
    except _Cancelled:
        return _result(settings, cancelled=True, message="Cancelled.")


def _run(
    records: Sequence[tuple[int, Chem.Mol, float]],
    settings: FreeWilsonSettings,
    *,
    cancel_event: Event | None,
    progress: ProgressCallback | None,
    enumeration_product_limit: int,
) -> FreeWilsonResult:
    _check_cancel(cancel_event)
    core = parse_free_wilson_core(settings.core_query)
    if core is None:
        return _result(settings, message="Core is not valid SMARTS or SMILES.")
    total = max(len(records), 1)
    _report(progress, "Free-Wilson: decomposing", 0, total)
    try:
        decomp_rows, unmatched = _decompose(core, records, settings)
    except _RDKIT_ERRORS as exc:
        return _result(settings, message=rgroup_decomp_failure_message(exc))
    _check_cancel(cancel_event)
    _report(progress, "Free-Wilson: decomposing", total, total)

    skipped: list[SkippedRow] = []
    matched, positions, core_mol = _align_rows(records, decomp_rows, unmatched, skipped)
    if core_mol is None or not matched:
        return _result(
            settings,
            message="No rows matched the core (check labels and attachment-point dummies).",
            skipped=tuple(skipped),
        )
    exemplars: dict[tuple[str, str], Chem.Mol] = {}
    parsed: list[_DecompRow] = []
    for oid, mol, activity, row in matched:
        if not np.isfinite(activity):
            skipped.append(SkippedRow(int(oid), SKIP_ACTIVITY))
            continue
        subs, labels, ok = _substituents_from_row(row, positions, exemplars)
        if not ok:
            skipped.append(SkippedRow(int(oid), SKIP_INCOMPLETE))
            continue
        parsed.append(
            _DecompRow(
                oid=int(oid),
                mol=mol,
                activity=float(activity),
                subs=subs,
                labels=labels,
            )
        )
    fitted, rare_skipped = _drop_rare(parsed, max(1, int(settings.min_count)))
    skipped.extend(rare_skipped)
    if len(fitted) < 2:
        return _result(
            settings,
            message=(
                "Need at least two molecules that match the core, have a numeric activity, "
                "and meet the minimum substituent count."
            ),
            skipped=tuple(skipped),
        )
    model = _build_model(fitted, positions, exemplars)
    if model is None:
        return _result(
            settings,
            message=(
                "Need at least one attachment position with two substituents "
                "at or above the minimum count."
            ),
            skipped=tuple(skipped),
        )
    _report(progress, "Free-Wilson: fitting", 0, 1)
    design = _design_matrix(fitted, model)
    kept = _independent_columns(design)
    if not kept and design.shape[1] > 0:
        return _result(
            settings,
            message="Substituent effects are not identifiable for this series.",
            skipped=tuple(skipped),
        )
    for sub in model:
        if sub.column is not None and sub.column not in kept:
            sub.identifiable = False
            sub.column = None
            sub.fb_coefficient = 0.0
    reduced = design[:, kept] if kept else np.zeros((len(fitted), 0))
    fit = _least_squares(fitted, reduced, kept, model)
    _report(progress, "Free-Wilson: fitting", 1, 1)
    return _with_enumeration(
        settings,
        fitted,
        model,
        fit,
        core_mol,
        skipped,
        positions,
        cancel_event=cancel_event,
        progress=progress,
        enumeration_product_limit=enumeration_product_limit,
    )


def _decompose(
    core: Chem.Mol,
    records: Sequence[tuple[int, Chem.Mol, float]],
    settings: FreeWilsonSettings,
) -> tuple[list[dict], list[int]]:
    mols = [mol for _oid, mol, _activity in records]
    if not mols:
        return [], []
    options = rdRGroupDecomposition.RGroupDecompositionParameters()
    options.onlyMatchAtRGroups = bool(settings.only_match_at_r_groups)
    options.removeHydrogensPostMatch = True
    if (settings.matching or "").strip().lower() == "exhaustive":
        options.matchingStrategy = rdRGroupDecomposition.RGroupMatching.Exhaustive
    else:
        options.matchingStrategy = rdRGroupDecomposition.RGroupMatching.Greedy
    rows, unmatched = rdRGroupDecomposition.RGroupDecompose(
        [core],
        mols,
        asSmiles=False,
        asRows=True,
        options=options,
    )
    return list(rows or []), [int(i) for i in (unmatched or [])]


def _align_rows(
    records: Sequence[tuple[int, Chem.Mol, float]],
    decomp_rows: list[dict],
    unmatched: list[int],
    skipped: list[SkippedRow],
) -> tuple[list[tuple[int, Chem.Mol, float, dict]], list[str], Chem.Mol | None]:
    unmatched_set = set(unmatched)
    aligned: list[tuple[int, Chem.Mol, float, dict]] = []
    row_index = 0
    for index, (oid, mol, activity) in enumerate(records):
        if index in unmatched_set:
            skipped.append(SkippedRow(int(oid), SKIP_NO_MATCH))
            continue
        if row_index >= len(decomp_rows):
            skipped.append(SkippedRow(int(oid), SKIP_INCOMPLETE))
            continue
        aligned.append((int(oid), mol, float(activity), decomp_rows[row_index]))
        row_index += 1
    positions: list[str] = []
    core_mol: Chem.Mol | None = None
    if aligned:
        positions = _position_names(aligned[0][3])
        core_value = aligned[0][3].get("Core")
        if core_value is not None:
            core_mol = Chem.Mol(core_value)
    return aligned, positions, core_mol


def _position_names(row: dict) -> list[str]:
    names = [str(key) for key in row if _is_r_position(str(key))]
    return sorted(names, key=lambda name: int(name[1:]))


def _is_r_position(name: str) -> bool:
    return name.startswith("R") and len(name) > 1 and name[1:].isdigit()


def _substituents_from_row(
    row: dict,
    positions: list[str],
    exemplars: dict[tuple[str, str], Chem.Mol],
) -> tuple[dict[str, str], dict[str, str], bool]:
    subs: dict[str, str] = {}
    labels: dict[str, str] = {}
    for position in positions:
        rg = row.get(position)
        if rg is None:
            return {}, {}, False
        try:
            key, label, zip_mol = _substituent_identity(rg)
        except _RDKIT_ERRORS:
            return {}, {}, False
        subs[position] = key
        labels[position] = label
        exemplars.setdefault((position, key), zip_mol)
    return subs, labels, True


def _substituent_identity(mol: Chem.Mol) -> tuple[str, str, Chem.Mol]:
    """Return ``(key, label, mol)``. Hydrogen has no heavy atom; the mol keeps map numbers."""
    copied = Chem.Mol(mol)
    if copied.GetNumHeavyAtoms() == 0:
        return HYDROGEN_KEY, HYDROGEN_KEY, copied
    keyed = Chem.Mol(copied)
    for atom in keyed.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
    key = Chem.MolToSmiles(keyed, canonical=True)
    return key, key, copied


def _drop_rare(
    rows: list[_DecompRow],
    min_count: int,
) -> tuple[list[_DecompRow], list[SkippedRow]]:
    """Drop molecules that contain a substituent seen fewer than *min_count* times.

    Counts are recomputed after each drop so a substituent cannot stay in the fit
    once its companions fall below the minimum.
    """
    kept = list(rows)
    skipped: list[SkippedRow] = []
    while kept:
        counts: Counter[tuple[str, str]] = Counter()
        for row in kept:
            for position, key in row.subs.items():
                counts[(position, key)] += 1
        rare = {pair for pair, count in counts.items() if count < min_count}
        if not rare:
            break
        next_kept: list[_DecompRow] = []
        for row in kept:
            if any((position, key) in rare for position, key in row.subs.items()):
                skipped.append(SkippedRow(row.oid, SKIP_RARE))
            else:
                next_kept.append(row)
        if len(next_kept) == len(kept):
            break
        kept = next_kept
    return kept, skipped


def _build_model(
    rows: list[_DecompRow],
    positions: list[str],
    exemplars: dict[tuple[str, str], Chem.Mol],
) -> list[_FittedSub] | None:
    counts: dict[str, Counter[str]] = {position: Counter() for position in positions}
    labels: dict[tuple[str, str], str] = {}
    for row in rows:
        for position, key in row.subs.items():
            counts[position][key] += 1
            labels[(position, key)] = row.labels[position]
    varying = [position for position in positions if len(counts[position]) >= 2]
    if not varying:
        return None
    model: list[_FittedSub] = []
    column = 0
    for position in positions:
        position_counts = counts[position]
        if not position_counts:
            continue
        reference = _reference_key(position_counts)
        for key in _sorted_keys(position_counts, reference):
            is_reference = key == reference
            use_column = None
            if not is_reference and len(position_counts) >= 2:
                use_column = column
                column += 1
            model.append(
                _FittedSub(
                    position=position,
                    key=key,
                    label=labels.get((position, key), key),
                    count=int(position_counts[key]),
                    mol=exemplars[(position, key)],
                    is_reference=is_reference,
                    column=use_column,
                    fb_coefficient=0.0,
                    identifiable=True,
                )
            )
    return model


def _reference_key(counts: Counter[str]) -> str:
    if HYDROGEN_KEY in counts:
        return HYDROGEN_KEY
    return min(counts, key=lambda key: (-counts[key], key))


def _sorted_keys(counts: Counter[str], reference: str) -> list[str]:
    others = sorted(key for key in counts if key != reference)
    return [reference, *others]


def _design_matrix(rows: list[_DecompRow], model: list[_FittedSub]) -> np.ndarray:
    columns = [sub for sub in model if sub.column is not None]
    matrix = np.zeros((len(rows), len(columns)), dtype=float)
    index_of = {sub.column: offset for offset, sub in enumerate(columns)}
    lookup = {(sub.position, sub.key): sub for sub in columns}
    for row_index, row in enumerate(rows):
        for position, key in row.subs.items():
            sub = lookup.get((position, key))
            if sub is None or sub.column is None:
                continue
            matrix[row_index, index_of[sub.column]] = 1.0
    return matrix


def _independent_columns(design: np.ndarray) -> list[int]:
    """Column-pivoted QR indices that span the substituent design matrix."""
    if design.size == 0 or design.shape[1] == 0:
        return []
    from scipy.linalg import qr

    _q, r_matrix, pivots = qr(design, mode="economic", pivoting=True)
    diagonal = np.abs(np.diag(r_matrix))
    if diagonal.size == 0 or diagonal[0] <= 0.0:
        return []
    rank = int(np.sum(diagonal > (_RANK_TOL * float(diagonal[0]))))
    return sorted(int(index) for index in pivots[:rank])


@dataclass
class _FitStats:
    intercept: float
    intercept_se: float | None
    column_se: dict[int, float]
    r_squared: float | None
    adjusted_r_squared: float | None
    rmse: float | None
    residual_df: int
    saturated: bool
    n_parameters: int
    covariance: np.ndarray | None


def _least_squares(
    rows: list[_DecompRow],
    design: np.ndarray,
    kept_original_columns: list[int],
    model: list[_FittedSub],
) -> _FitStats:
    y = np.array([row.activity for row in rows], dtype=float)
    n = int(y.shape[0])
    ones = np.ones((n, 1), dtype=float)
    predictors = np.column_stack([ones, design]) if design.shape[1] else ones
    beta, _residuals, _rank, _singular = np.linalg.lstsq(predictors, y, rcond=None)
    predicted = predictors @ beta
    residual = y - predicted
    sse = float(residual @ residual)
    n_parameters = int(predictors.shape[1])
    dof = n - n_parameters
    centered = y - float(np.mean(y))
    sst = float(centered @ centered)
    r_squared = 1.0 if sst <= _RANK_TOL else 1.0 - (sse / sst)
    adjusted = None
    if dof > 0 and n > 1:
        adjusted = 1.0 - (1.0 - r_squared) * (n - 1) / dof
    rmse = float(np.sqrt(sse / n)) if n else None
    covariance = None
    intercept_se = None
    column_se: dict[int, float] = {}
    if dof > 0:
        sigma2 = sse / dof
        covariance = _covariance(predictors, sigma2)
        stderr = np.sqrt(np.maximum(np.diag(covariance), 0.0))
        intercept_se = float(stderr[0])
        for offset, original in enumerate(kept_original_columns):
            column_se[original] = float(stderr[offset + 1])
    by_column = {sub.column: sub for sub in model if sub.column is not None}
    for offset, original in enumerate(kept_original_columns):
        sub = by_column.get(original)
        if sub is not None:
            sub.fb_coefficient = float(beta[offset + 1])
            sub.identifiable = True
    return _FitStats(
        intercept=float(beta[0]),
        intercept_se=intercept_se,
        column_se=column_se,
        r_squared=float(r_squared),
        adjusted_r_squared=None if adjusted is None else float(adjusted),
        rmse=rmse,
        residual_df=int(dof),
        saturated=dof <= 0,
        n_parameters=n_parameters,
        covariance=covariance,
    )


def _covariance(predictors: np.ndarray, sigma2: float) -> np.ndarray:
    gram = predictors.T @ predictors
    try:
        inverse = np.linalg.inv(gram)
    except np.linalg.LinAlgError:
        inverse = np.linalg.pinv(gram)
    return sigma2 * inverse


def _with_enumeration(
    settings: FreeWilsonSettings,
    rows: list[_DecompRow],
    model: list[_FittedSub],
    fit: _FitStats,
    core_mol: Chem.Mol,
    skipped: list[SkippedRow],
    positions: list[str],
    *,
    cancel_event: Event | None,
    progress: ProgressCallback | None,
    enumeration_product_limit: int,
) -> FreeWilsonResult:
    coefficients = _report_coefficients(settings.report, model, rows, fit)
    observed = _observed_predictions(rows, model, fit.intercept, positions)
    pools = _enumeration_pools(model, positions)
    counts = tuple((position, len(pool)) for position, pool in pools)
    n_combinations = _product_size(pools)
    observed_keys = {tuple(row.subs[position] for position, _pool in pools) for row in rows}
    n_missing = max(0, n_combinations - len(observed_keys))
    references = tuple((sub.position, sub.label) for sub in model if sub.is_reference)
    base_kwargs = dict(
        ok=True,
        report=settings.report if settings.report == REPORT_FREE_WILSON else REPORT_FUJITA_BAN,
        n=len(rows),
        n_parameters=fit.n_parameters,
        r_squared=fit.r_squared,
        adjusted_r_squared=fit.adjusted_r_squared,
        rmse=fit.rmse,
        residual_df=fit.residual_df,
        saturated=fit.saturated,
        intercept=_reported_intercept(settings.report, fit.intercept, model, rows),
        intercept_std_error=_reported_intercept_se(settings.report, fit, model, rows),
        coefficients=coefficients,
        observed=observed,
        skipped=tuple(skipped),
        n_combinations=n_combinations,
        n_missing=n_missing,
        position_counts=counts,
        references=references,
    )
    if n_combinations > enumeration_product_limit:
        message = _refusal_message(counts, n_combinations, enumeration_product_limit)
        return _result(
            settings,
            enumeration_refused=True,
            enumeration_message=message,
            message=message,
            **base_kwargs,
        )
    _check_cancel(cancel_event)
    missing, truncated, zip_failed = _enumerate_missing(
        pools,
        observed_keys,
        core_mol,
        fit.intercept,
        max_keep=max(1, int(settings.max_new_structures)),
        prefer_higher=bool(settings.prefer_higher),
        n_missing=n_missing,
        observed_smiles=_observed_smiles(rows),
        cancel_event=cancel_event,
        progress=progress,
    )
    enum_message = ""
    if truncated:
        direction = "highest" if settings.prefer_higher else "lowest"
        enum_message = (
            f"Showing {len(missing):,} of {n_missing:,} missing combinations "
            f"({direction} predicted activity)."
        )
    elif zip_failed:
        enum_message = f"{zip_failed:,} combination(s) could not be rebuilt into a molecule."
    return _result(
        settings,
        enumeration_truncated=truncated,
        enumeration_message=enum_message,
        missing=tuple(missing),
        n_zip_failed=zip_failed,
        **base_kwargs,
    )


def _reported_intercept(
    report: str,
    fb_intercept: float,
    model: list[_FittedSub],
    rows: list[_DecompRow],
) -> float:
    if report != REPORT_FREE_WILSON:
        return fb_intercept
    return fb_intercept + sum(
        _position_mean(sub_list, rows) for _pos, sub_list in _by_position(model)
    )


def _reported_intercept_se(
    report: str,
    fit: _FitStats,
    model: list[_FittedSub],
    rows: list[_DecompRow],
) -> float | None:
    if fit.covariance is None:
        return None
    if report != REPORT_FREE_WILSON:
        return fit.intercept_se
    weights = _fw_intercept_weights(model, rows, fit.covariance.shape[0])
    return _linear_se(weights, fit.covariance)


def _report_coefficients(
    report: str,
    model: list[_FittedSub],
    rows: list[_DecompRow],
    fit: _FitStats,
) -> tuple[SubstituentCoefficient, ...]:
    grouped = _by_position(model)
    means = {position: _position_mean(subs, rows) for position, subs in grouped}
    out: list[SubstituentCoefficient] = []
    for position, subs in grouped:
        mean = means[position]
        for sub in subs:
            coefficient, stderr, identifiable = _one_coefficient(
                report, sub, mean, fit, model, rows
            )
            out.append(
                SubstituentCoefficient(
                    position=sub.position,
                    key=sub.key,
                    label=sub.label,
                    count=sub.count,
                    coefficient=coefficient,
                    std_error=stderr,
                    is_reference=sub.is_reference,
                    identifiable=identifiable,
                )
            )
    return tuple(out)


def _one_coefficient(
    report: str,
    sub: _FittedSub,
    mean: float,
    fit: _FitStats,
    model: list[_FittedSub],
    rows: list[_DecompRow],
) -> tuple[float | None, float | None, bool]:
    if not sub.identifiable:
        return None, None, False
    if report != REPORT_FREE_WILSON:
        if sub.is_reference:
            return 0.0, None, True
        stderr = fit.column_se.get(sub.column) if sub.column is not None else None
        return sub.fb_coefficient, stderr, True
    coefficient = sub.fb_coefficient - mean
    if fit.covariance is None or (sub.column is None and not sub.is_reference):
        return coefficient, None, True
    weights = _fw_coefficient_weights(sub, model, rows, fit.covariance.shape[0])
    return coefficient, _linear_se(weights, fit.covariance), True


def _by_position(model: list[_FittedSub]) -> list[tuple[str, list[_FittedSub]]]:
    order: list[str] = []
    grouped: dict[str, list[_FittedSub]] = {}
    for sub in model:
        if sub.position not in grouped:
            order.append(sub.position)
            grouped[sub.position] = []
        grouped[sub.position].append(sub)
    return [(position, grouped[position]) for position in order]


def _position_mean(subs: list[_FittedSub], rows: list[_DecompRow]) -> float:
    """Occurrence-weighted Fujita-Ban mean. Non-identifiable substituents contribute 0."""
    del rows
    total = sum(sub.count for sub in subs if sub.identifiable)
    if total <= 0:
        return 0.0
    weighted = sum(sub.count * sub.fb_coefficient for sub in subs if sub.identifiable)
    return weighted / total


def _beta_index(sub: _FittedSub, model: list[_FittedSub]) -> int | None:
    """Index of *sub* in the least-squares beta vector (0 is the intercept)."""
    if sub.column is None:
        return None
    identifiable = [item for item in model if item.identifiable and item.column is not None]
    identifiable.sort(key=lambda item: int(item.column or 0))
    for offset, item in enumerate(identifiable):
        if item.position == sub.position and item.key == sub.key:
            return offset + 1
    return None


def _fw_coefficient_weights(
    sub: _FittedSub,
    model: list[_FittedSub],
    rows: list[_DecompRow],
    width: int,
) -> np.ndarray:
    del rows
    weights = np.zeros(width, dtype=float)
    peers = [item for item in model if item.position == sub.position and item.identifiable]
    total = sum(item.count for item in peers)
    if total <= 0:
        return weights
    for item in peers:
        index = _beta_index(item, model)
        if index is None or index >= width:
            continue
        weights[index] -= item.count / total
    own = _beta_index(sub, model)
    if own is not None and own < width:
        weights[own] += 1.0
    return weights


def _fw_intercept_weights(
    model: list[_FittedSub],
    rows: list[_DecompRow],
    width: int,
) -> np.ndarray:
    del rows
    weights = np.zeros(width, dtype=float)
    weights[0] = 1.0
    for position, subs in _by_position(model):
        del position
        peers = [item for item in subs if item.identifiable]
        total = sum(item.count for item in peers)
        if total <= 0:
            continue
        for item in peers:
            index = _beta_index(item, model)
            if index is None or index >= width:
                continue
            weights[index] += item.count / total
    return weights


def _linear_se(weights: np.ndarray, covariance: np.ndarray) -> float:
    variance = float(weights @ covariance @ weights)
    return float(np.sqrt(max(variance, 0.0)))


def _observed_predictions(
    rows: list[_DecompRow],
    model: list[_FittedSub],
    intercept: float,
    positions: list[str],
) -> tuple[ObservedPrediction, ...]:
    lookup = {(sub.position, sub.key): sub for sub in model}
    out: list[ObservedPrediction] = []
    for row in rows:
        predicted = intercept
        labels: list[tuple[str, str]] = []
        for position in positions:
            key = row.subs[position]
            labels.append((position, row.labels[position]))
            sub = lookup.get((position, key))
            if sub is not None and sub.identifiable:
                predicted += sub.fb_coefficient
        out.append(
            ObservedPrediction(
                oid=row.oid,
                observed=row.activity,
                predicted=float(predicted),
                residual=float(row.activity - predicted),
                substituents=tuple(labels),
            )
        )
    return tuple(out)


def _enumeration_pools(
    model: list[_FittedSub],
    positions: list[str],
) -> list[tuple[str, tuple[_Choice, ...]]]:
    pools: list[tuple[str, tuple[_Choice, ...]]] = []
    for position in positions:
        choices = [
            _Choice(
                position=sub.position,
                key=sub.key,
                label=sub.label,
                mol=sub.mol,
                fb_coefficient=sub.fb_coefficient if sub.identifiable else 0.0,
            )
            for sub in model
            if sub.position == position and sub.identifiable
        ]
        if choices:
            pools.append((position, tuple(choices)))
    return pools


def _product_size(pools: list[tuple[str, tuple[_Choice, ...]]]) -> int:
    size = 1
    for _position, choices in pools:
        size *= max(1, len(choices))
    return size if pools else 0


def _refusal_message(
    counts: tuple[tuple[str, int], ...],
    n_combinations: int,
    limit: int,
) -> str:
    detail = ", ".join(f"{position}: {count:,}" for position, count in counts)
    return (
        f"The substituent combination count ({n_combinations:,}) exceeds {limit:,}. "
        f"{detail}. Raise the minimum count or simplify the core. "
        "No partial set of missing analogs was generated."
    )


def _observed_smiles(rows: list[_DecompRow]) -> set[str]:
    found: set[str] = set()
    for row in rows:
        try:
            smiles = Chem.MolToSmiles(row.mol, canonical=True)
        except _RDKIT_ERRORS:
            continue
        if smiles:
            found.add(smiles)
    return found


def _enumerate_missing(
    pools: list[tuple[str, tuple[_Choice, ...]]],
    observed_keys: set[tuple[str, ...]],
    core_mol: Chem.Mol,
    intercept: float,
    *,
    max_keep: int,
    prefer_higher: bool,
    n_missing: int,
    observed_smiles: set[str],
    cancel_event: Event | None,
    progress: ProgressCallback | None,
) -> tuple[list[MissingAnalog], bool, int]:
    choices = [pool for _position, pool in pools]
    if not choices:
        return [], False, 0
    truncated = n_missing > max_keep
    heap: list[tuple[float, int, tuple[_Choice, ...]]] = []
    examined = 0
    total = _product_size(pools)
    _report(progress, "Free-Wilson: enumerating", 0, max(total, 1))
    for combo in product(*choices):
        examined += 1
        if examined % _PROGRESS_STRIDE == 0:
            _check_cancel(cancel_event)
            _report(progress, "Free-Wilson: enumerating", examined, max(total, 1))
        key = tuple(choice.key for choice in combo)
        if key in observed_keys:
            continue
        predicted = intercept + sum(choice.fb_coefficient for choice in combo)
        _push_extreme(heap, predicted, examined, combo, max_keep, prefer_higher)
    _check_cancel(cancel_event)
    chosen = _sorted_heap(heap)
    missing: list[MissingAnalog] = []
    zip_failed = 0
    seen: set[str] = set()
    for combo in chosen:
        smiles = _assemble_smiles(core_mol, combo)
        if not smiles or smiles in observed_smiles or smiles in seen:
            zip_failed += 0 if smiles else 1
            continue
        seen.add(smiles)
        predicted = intercept + sum(choice.fb_coefficient for choice in combo)
        missing.append(
            MissingAnalog(
                smiles=smiles,
                predicted=float(predicted),
                substituents=tuple((choice.position, choice.label) for choice in combo),
            )
        )
    _report(progress, "Free-Wilson: enumerating", max(total, 1), max(total, 1))
    return missing, truncated and bool(missing or n_missing), zip_failed


def _push_extreme(
    heap: list[tuple[float, int, tuple[_Choice, ...]]],
    predicted: float,
    sequence: int,
    combo: tuple[_Choice, ...],
    max_keep: int,
    prefer_higher: bool,
) -> None:
    score = predicted if prefer_higher else -predicted
    item = (score, sequence, combo)
    if len(heap) < max_keep:
        heapq.heappush(heap, item)
        return
    if score > heap[0][0]:
        heapq.heapreplace(heap, item)


def _sorted_heap(
    heap: list[tuple[float, int, tuple[_Choice, ...]]],
) -> list[tuple[_Choice, ...]]:
    """Return combinations best-score first. Scores are already oriented by preference."""
    ordered = sorted(heap, key=lambda item: item[0], reverse=True)
    return [item[2] for item in ordered]


def _assemble_smiles(core_mol: Chem.Mol, combo: tuple[_Choice, ...]) -> str | None:
    try:
        combined = Chem.Mol(core_mol)
        for choice in combo:
            combined = Chem.CombineMols(combined, choice.mol)
        zipped = Chem.molzip(combined)
        if zipped is None:
            return None
        Chem.SanitizeMol(zipped)
        return Chem.MolToSmiles(zipped, canonical=True) or None
    except _RDKIT_ERRORS:
        logger.debug("Free-Wilson molzip failed", exc_info=True)
        return None


def _result(settings: FreeWilsonSettings, **kwargs: object) -> FreeWilsonResult:
    report = settings.report if settings.report == REPORT_FREE_WILSON else REPORT_FUJITA_BAN
    payload: dict[str, object] = {
        "ok": False,
        "message": "",
        "cancelled": False,
        "report": report,
        "activity_column": settings.activity_column,
        "n": 0,
        "n_parameters": 0,
        "r_squared": None,
        "adjusted_r_squared": None,
        "rmse": None,
        "residual_df": 0,
        "saturated": False,
        "intercept": 0.0,
        "intercept_std_error": None,
        "coefficients": (),
        "observed": (),
        "missing": (),
        "skipped": (),
        "enumeration_refused": False,
        "enumeration_message": "",
        "enumeration_truncated": False,
        "n_combinations": 0,
        "n_missing": 0,
        "n_zip_failed": 0,
        "position_counts": (),
        "references": (),
    }
    payload.update(kwargs)
    return FreeWilsonResult(**payload)  # type: ignore[arg-type]


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _Cancelled


def _report(progress: ProgressCallback | None, message: str, done: int, total: int) -> None:
    if progress is not None:
        progress(message, int(done), int(total))
