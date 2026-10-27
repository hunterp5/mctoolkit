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

"""Staged AutoQSAR search over table columns, catalog descriptors, and fingerprint blocks.

Model choice uses cross-validation on the training split only. The hold-out score is
computed once, by :func:`molmanager.analysis.qsar_models.fit_qsar_model`, on the winner.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from ..chem.rdkit_fingerprints import DEFAULT_FINGERPRINT_LABEL
from ..descriptors.catalog import DESCRIPTOR_TAB_ORDER, descriptor_tab_items
from ..descriptors.descriptor_cache_reuse import column_complete_for_oids
from ..descriptors.descriptors_3d import DESCRIPTOR_3D_KEYS
from .dimensionality_reduction import is_fingerprint_bitcount_column
from .qsar_models import (
    TaskKind,
    QSARFitResult,
    _merge_model_params,
    _model_label,
    _prepare_labels,
    _prepare_model_for_x,
    _scale_fit,
    default_model_params,
    fit_qsar_model,
    infer_task_type,
    models_for_task,
)

MIN_ROWS = 8
TRAIN_FRACTION = 0.8
MISSING_FRACTION = 0.20
CORR_THRESHOLD = 0.95
_3D_MIN_FRACTION = 0.80
_QUICK_SKIP_MODELS = frozenset({"svr"})
_IONIZATION_KEYS = frozenset({"LOGD74", "LOGS74", "AB_MPS", "BBB_SCORE", "CNS_MPO"})
_SKIP_TABS = frozenset({"Name", "Fingerprints"})

FP_MORGAN = DEFAULT_FINGERPRINT_LABEL
FP_MACCS = "MACCS (166)"
FP_RDK = "RDK path (1024)"

_SCORE_ERRORS = (ValueError, ArithmeticError, np.linalg.LinAlgError, IndexError, KeyError)
_DESCRIPTOR_ERRORS = (
    ValueError,
    TypeError,
    RuntimeError,
    ArithmeticError,
    AttributeError,
    KeyError,
    IndexError,
)

ProgressCallback = Callable[[int, int, str], None]


class AutoQSARCancelled(Exception):
    """Raised when a search sees the job cancel event between trials."""


@dataclass(frozen=True)
class AutoQSARTrial:
    """One scored candidate. ``model_params`` is the merged hyperparameter set."""

    model_key: str
    model_label: str
    feature_set: str
    n_features: int
    cv_mean: float
    cv_std: float
    stage: int
    feature_columns: tuple[str, ...]
    fp_choice: str | None
    model_params: tuple[tuple[str, Any], ...]


@dataclass(frozen=True)
class AutoQSARResult:
    """Winner, leaderboard, and the columns a later write should add to the table."""

    task: TaskKind
    effort: str
    activity_column: str
    selection_metric: str
    trials: tuple[AutoQSARTrial, ...]
    winner: AutoQSARTrial
    fit: QSARFitResult
    report_text: str
    computed_columns_used: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class DescriptorAttachResult:
    """Working table after catalog descriptors were reused or calculated."""

    dataframe: pd.DataFrame
    pool_columns: tuple[str, ...]
    computed_columns: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass
class _PreparedSet:
    name: str
    X: np.ndarray
    y: np.ndarray
    train_idx: np.ndarray
    n_numeric: int
    feature_columns: tuple[str, ...]
    fp_choice: str | None
    fit_df: pd.DataFrame
    fit_oids: list[int]


def auto_qsar_descriptor_specs(*, include_3d: bool = False) -> tuple[tuple[str, str], ...]:
    """Catalog ``(display name, internal key)`` pairs AutoQSAR may use.

    Ionization-backed scores and name/fingerprint-count columns are omitted. 3D
    descriptors are included only when *include_3d* is true.
    """
    specs: list[tuple[str, str]] = []
    for tab in DESCRIPTOR_TAB_ORDER:
        if tab in _SKIP_TABS:
            continue
        if tab == "3D" and not include_3d:
            continue
        for display, key in descriptor_tab_items(tab):
            if key in _IONIZATION_KEYS:
                continue
            specs.append((display, key))
    return tuple(specs)


def table_numeric_feature_columns(
    df: pd.DataFrame,
    activity_column: str,
    *,
    blocked_columns: Sequence[str] | None = None,
) -> list[str]:
    """Numeric columns eligible as existing-table features."""
    blocked = set(blocked_columns or ())
    blocked.add(activity_column)
    blocked.update(("ID_HIDDEN", "Structure"))
    blocked.update(_fingerprint_onbit_headers())
    kept: list[str] = []
    for column in df.columns:
        name = str(column)
        if name in blocked or is_fingerprint_bitcount_column(name):
            continue
        numeric = pd.to_numeric(df[column], errors="coerce")
        if numeric.notna().any():
            kept.append(name)
    return kept


def filter_training_features(
    frame: pd.DataFrame,
    y: np.ndarray,
    train_positions: np.ndarray,
    *,
    missing_fraction: float = MISSING_FRACTION,
    corr_threshold: float = CORR_THRESHOLD,
) -> list[str]:
    """Drop sparse, constant, or redundant columns using training rows only.

    A pair with absolute correlation above *corr_threshold* keeps the column
    more associated with *y* on the training rows. Ties keep the earlier column.
    """
    if frame.empty or len(frame.columns) == 0:
        return []
    positions = np.asarray(train_positions, dtype=int)
    if positions.size == 0:
        return []
    y_train = np.asarray(y, dtype=float)[positions]
    values = frame.apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
    train = values[positions]
    candidates: list[int] = []
    associations: list[float] = []
    min_present = 1.0 - float(missing_fraction)
    for index, _name in enumerate(frame.columns):
        column = train[:, index]
        finite = np.isfinite(column)
        if float(np.mean(finite)) < min_present:
            continue
        present = column[finite]
        if present.size == 0 or float(np.std(present)) <= 1e-8 or np.unique(present).size <= 1:
            continue
        candidates.append(index)
        associations.append(_association(column, y_train))
    ranked = sorted(range(len(candidates)), key=lambda i: (-associations[i], candidates[i]))
    chosen: list[int] = []
    for rank in ranked:
        index = candidates[rank]
        column = train[:, index]
        if any(
            abs(_pairwise_corr(column, train[:, other])) > float(corr_threshold) for other in chosen
        ):
            continue
        chosen.append(index)
    chosen_set = set(chosen)
    return [str(frame.columns[i]) for i in range(len(frame.columns)) if i in chosen_set]


def modeling_split_indices(
    y: np.ndarray,
    task: TaskKind,
    train_fraction: float = TRAIN_FRACTION,
) -> tuple[np.ndarray, np.ndarray]:
    """Row indices of the same hold-out split :func:`fit_qsar_model` uses."""
    from sklearn.model_selection import train_test_split

    test_size = max(0.1, min(0.4, 1.0 - float(train_fraction)))
    idx = np.arange(len(y))
    stratify = y if task == "classification" and len(np.unique(y)) > 1 else None
    train_idx, test_idx = train_test_split(
        idx,
        test_size=test_size,
        random_state=42,
        stratify=stratify,
    )
    return np.asarray(train_idx, dtype=int), np.asarray(test_idx, dtype=int)


def score_training_matrix(
    X: np.ndarray,
    y: np.ndarray,
    train_idx: np.ndarray,
    *,
    task: TaskKind,
    model_key: str,
    model_params: Mapping[str, Any] | None,
    cv_folds: int,
    n_numeric: int,
) -> tuple[float, float]:
    """Cross-validated selection score on training rows. The hold-out is not passed in."""
    from sklearn.model_selection import cross_val_score

    X_train = np.asarray(X)[np.asarray(train_idx, dtype=int)]
    y_train = np.asarray(y)[np.asarray(train_idx, dtype=int)]
    Xs, _scaler = _scale_fit(
        X_train,
        standardize_numeric=n_numeric > 0,
        n_numeric=n_numeric,
    )
    model = _prepare_model_for_x(_make_model(task, model_key, model_params), Xs)
    folds = _cv_folds(y_train, task, cv_folds)
    scoring = "r2" if task == "regression" else "balanced_accuracy"
    scores = cross_val_score(model, Xs, y_train, cv=folds, scoring=scoring, n_jobs=1)
    return float(np.mean(scores)), float(np.std(scores))


def cv_folds_for_effort(effort: str) -> int:
    """Quick uses 3-fold CV. Standard uses 5-fold CV."""
    return 3 if _normalize_effort(effort) == "quick" else 5


def model_keys_for_search(task: TaskKind, effort: str) -> list[str]:
    """Algorithms scored for *task*. Quick omits SVR."""
    keys = [key for key, _label in models_for_task(task)]
    if _normalize_effort(effort) == "quick":
        keys = [key for key in keys if key not in _QUICK_SKIP_MODELS]
    return keys


def stage2_param_grid(model_key: str) -> tuple[dict[str, Any], ...]:
    """Short second-stage grids. Points that match the stage-1 defaults are skipped later."""
    grids: dict[str, tuple[dict[str, Any], ...]] = {
        "ridge": ({"alpha": 0.1}, {"alpha": 1.0}, {"alpha": 10.0}),
        "lasso": ({"alpha": 0.01}, {"alpha": 0.1}, {"alpha": 1.0}),
        "mlr": ({"fit_intercept": True}, {"fit_intercept": False}),
        "pls": ({"n_components": 2}, {"n_components": 5}),
        "knn": ({"n_neighbors": 3}, {"n_neighbors": 5}, {"n_neighbors": 9}),
        "random_forest": (
            {"n_estimators": 100, "max_depth": 0},
            {"n_estimators": 100, "max_depth": 8},
        ),
        "gradient_boosting": (
            {"learning_rate": 0.05, "max_depth": 2},
            {"learning_rate": 0.1, "max_depth": 3},
            {"learning_rate": 0.05, "max_depth": 3},
        ),
        "logistic": ({"C": 0.1}, {"C": 1.0}, {"C": 10.0}),
        "svm": (
            {"C": 0.1, "kernel": "linear"},
            {"C": 1.0, "kernel": "linear"},
            {"C": 1.0, "kernel": "rbf"},
        ),
        "svr": (
            {"C": 0.1, "kernel": "rbf"},
            {"C": 1.0, "kernel": "rbf"},
            {"C": 10.0, "kernel": "rbf"},
        ),
    }
    return grids.get(str(model_key), ())


def attach_catalog_descriptors(
    df: pd.DataFrame,
    oids: list[int],
    mol_rows: list[tuple[int, object]] | None,
    *,
    specs: Sequence[tuple[str, str]] | None = None,
    include_3d: bool | None = None,
    cancel_event: threading.Event | None = None,
    on_row: Callable[[int, int], None] | None = None,
) -> DescriptorAttachResult:
    """Reuse complete descriptor columns and calculate the rest from structures.

    3D descriptors are calculated only when a 3D pose exists for at least 80% of
    the structures. The returned frame is a copy.
    """
    if len(oids) != len(df):
        raise ValueError("OID list length must match dataframe row count.")
    _check_cancel(cancel_event)
    out = df.copy()
    notes: list[str] = []
    mol_by_oid, three_d_by_oid, fraction = _structure_maps(mol_rows)
    use_3d = fraction >= _3D_MIN_FRACTION if include_3d is None else bool(include_3d)
    if include_3d and fraction < _3D_MIN_FRACTION:
        use_3d = False
    chosen, three_d_note = _specs_for_attach(specs, use_3d=use_3d, have_structures=bool(mol_by_oid))
    if three_d_note and mol_by_oid:
        notes.append(_three_d_note(fraction, included=use_3d and three_d_note == "included"))
    pool: list[str] = []
    computed: list[str] = []
    to_compute: list[tuple[str, str]] = []
    for display, key in chosen:
        if _column_complete(out, display, oids) and _has_numeric(out, display):
            pool.append(display)
            continue
        if mol_by_oid:
            to_compute.append((display, key))
    if to_compute:
        _calculate_descriptor_columns(
            out,
            oids,
            to_compute,
            mol_by_oid,
            three_d_by_oid,
            cancel_event=cancel_event,
            on_row=on_row,
        )
        for display, _key in to_compute:
            if _has_numeric(out, display):
                pool.append(display)
                computed.append(display)
    if not mol_by_oid and not pool:
        notes.append("No structures; descriptors were not calculated.")
    return DescriptorAttachResult(
        dataframe=out,
        pool_columns=tuple(pool),
        computed_columns=tuple(computed),
        notes=tuple(notes),
    )


def search_auto_qsar(
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    task_mode: str,
    effort: str,
    mol_rows: list[tuple[int, object]] | None = None,
    table_columns: Sequence[str] | None = None,
    descriptor_columns: Sequence[str] | None = None,
    computed_columns: Sequence[str] | None = None,
    blocked_columns: Sequence[str] | None = None,
    initial_notes: Sequence[str] | None = None,
    train_fraction: float = TRAIN_FRACTION,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> AutoQSARResult:
    """Score feature sets and models, then refit the winner on its frozen rows.

    *table_columns* should be the numeric columns that existed before descriptor
    calculation. *computed_columns* are catalog columns this job calculated; the
    winner's overlap is what a later write should add to the table.
    """
    _check_cancel(cancel_event)
    if activity_column not in df.columns:
        raise ValueError(f"Activity column not found: {activity_column}")
    effort_key = _normalize_effort(effort)
    folds = cv_folds_for_effort(effort_key)
    task = _resolve_task(df, activity_column, task_mode)
    blocked = set(blocked_columns or ())
    blocked.add(activity_column)
    notes = [note for note in (initial_notes or ()) if note]
    table_cols = [
        column
        for column in (
            list(table_columns)
            if table_columns is not None
            else table_numeric_feature_columns(df, activity_column)
        )
        if column not in blocked and column in df.columns
    ]
    desc_cols = [
        column
        for column in (descriptor_columns or ())
        if column not in blocked and column in df.columns
    ]
    computed = [column for column in (computed_columns or ()) if column in df.columns]
    model_keys = model_keys_for_search(task, effort_key)
    prepared = _prepare_sets(
        df=df,
        oids=oids,
        activity_column=activity_column,
        task=task,
        train_fraction=train_fraction,
        table_columns=table_cols,
        descriptor_columns=desc_cols,
        mol_rows=mol_rows,
        effort=effort_key,
        notes=notes,
    )
    can_combo = bool(mol_rows) and any(item.fp_choice is None for item in prepared)
    stage2_budget = 0 if effort_key == "quick" else 12
    combo_slots = len(model_keys) if can_combo else 0
    total = max(1, len(prepared) * len(model_keys) + combo_slots + stage2_budget + 1)
    done = 0
    trials: list[AutoQSARTrial] = []

    def _score_many(
        items: Sequence[_PreparedSet],
        stage: int,
        params_for_key: Callable[[str], Mapping[str, Any]],
        keys: Sequence[str],
    ) -> None:
        nonlocal done
        for item in items:
            for model_key in keys:
                _check_cancel(cancel_event)
                done += 1
                params = dict(params_for_key(model_key))
                _emit_progress(
                    on_progress,
                    done,
                    total,
                    f"AutoQSAR: {_model_label(task, model_key)} / {item.name}",
                )
                trial = _try_trial(item, task, model_key, params, stage, folds)
                if trial is not None:
                    trials.append(trial)

    _score_many(prepared, 1, default_model_params, model_keys)
    if can_combo:
        combo = _prepare_morgan_combo(
            prepared,
            trials,
            df=df,
            oids=oids,
            activity_column=activity_column,
            task=task,
            train_fraction=train_fraction,
            mol_rows=mol_rows,
            notes=notes,
        )
        if combo is not None:
            prepared.append(combo)
            _score_many([combo], 1, default_model_params, model_keys)
    if effort_key == "standard" and trials:
        done = _score_stage2(
            prepared,
            trials,
            task,
            folds,
            total,
            on_progress,
            cancel_event,
            done,
        )
    if not trials:
        detail = " ".join(notes)
        raise ValueError(detail or "AutoQSAR could not score any model on this scope.")
    _check_cancel(cancel_event)
    ranked = tuple(sorted(trials, key=_trial_key))
    winner = ranked[0]
    winner_set = next(item for item in prepared if item.name == winner.feature_set)
    _emit_progress(on_progress, total, total, "AutoQSAR: refitting winner")
    fit = fit_qsar_model(
        df=winner_set.fit_df,
        oids=winner_set.fit_oids,
        activity_column=activity_column,
        feature_columns=list(winner.feature_columns) or None,
        fp_choice=winner.fp_choice,
        mol_rows=mol_rows,
        model_key=winner.model_key,
        task_mode=task,
        train_fraction=train_fraction,
        cv_folds=folds,
        standardize=True,
        model_params=dict(winner.model_params),
    )
    used = tuple(column for column in computed if column in set(winner.feature_columns))
    metric = "R²" if task == "regression" else "balanced accuracy"
    report = _format_report(effort_key, task, metric, winner, fit, notes)
    return AutoQSARResult(
        task=task,
        effort=effort_key,
        activity_column=activity_column,
        selection_metric=metric,
        trials=ranked,
        winner=winner,
        fit=fit,
        report_text=report,
        computed_columns_used=used,
        notes=tuple(notes),
    )


def table_write_rows(
    df: pd.DataFrame,
    oids: list[int],
    descriptor_columns: Sequence[str],
    predictions: Sequence[tuple[int, Mapping[str, str]]],
    prediction_column: str,
) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Merge calculated descriptor cells with prediction cells for one table write."""
    columns = [column for column in descriptor_columns if column in df.columns]
    pred_col = (prediction_column or "").strip()
    by_oid: dict[int, dict[str, str]] = {}
    if columns:
        for pos, oid in enumerate(oids):
            payload: dict[str, str] = {}
            for column in columns:
                raw = df.iloc[pos][column]
                payload[column] = "N/A" if _missing_cell(raw) else str(raw)
            by_oid[int(oid)] = payload
    for oid, values in predictions:
        slot = by_oid.setdefault(int(oid), {})
        slot.update({str(key): str(value) for key, value in values.items()})
    headers = list(columns)
    if pred_col:
        headers.append(pred_col)
    rows = [(oid, by_oid[oid]) for oid in by_oid]
    return headers, rows


def _make_model(task: TaskKind, model_key: str, params: Mapping[str, Any] | None) -> Any:
    from .qsar_models import _make_model as build_model

    return build_model(task, model_key, dict(params) if params else None)


def _normalize_effort(effort: str) -> str:
    key = str(effort or "quick").strip().lower()
    if key not in {"quick", "standard"}:
        raise ValueError(f"Unknown AutoQSAR effort: {effort}")
    return key


def _resolve_task(df: pd.DataFrame, activity_column: str, task_mode: str) -> TaskKind:
    mode = str(task_mode or "auto").strip().lower()
    if mode == "regression":
        return "regression"
    if mode == "classification":
        return "classification"
    if mode != "auto":
        raise ValueError(f"Unknown AutoQSAR task: {task_mode}")
    y = pd.to_numeric(df[activity_column], errors="coerce").to_numpy(dtype=float)
    return infer_task_type(y[np.isfinite(y)])


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AutoQSARCancelled()


def _emit_progress(
    on_progress: ProgressCallback | None,
    done: int,
    total: int,
    message: str,
) -> None:
    if on_progress is not None:
        on_progress(int(done), int(total), message)


def _fingerprint_onbit_headers() -> frozenset[str]:
    from ..chem.rdkit_fingerprints import FINGERPRINT_SPECS, descriptor_onbits_column_aliases

    names: set[str] = set()
    for spec in FINGERPRINT_SPECS:
        names.update(descriptor_onbits_column_aliases(spec.label))
    return frozenset(names)


def _association(column: np.ndarray, y: np.ndarray) -> float:
    mask = np.isfinite(column) & np.isfinite(y)
    if int(mask.sum()) < 3:
        return 0.0
    return abs(_pairwise_corr(column[mask], y[mask]))


def _pairwise_corr(left: np.ndarray, right: np.ndarray) -> float:
    mask = np.isfinite(left) & np.isfinite(right)
    if int(mask.sum()) < 3:
        return 0.0
    a = left[mask]
    b = right[mask]
    if float(np.std(a)) <= 1e-12 or float(np.std(b)) <= 1e-12:
        return 0.0
    corr = float(np.corrcoef(a, b)[0, 1])
    if not np.isfinite(corr):
        return 0.0
    return corr


def _cv_folds(y_train: np.ndarray, task: TaskKind, cv_folds: int) -> int:
    folds = max(2, min(int(cv_folds), len(y_train) - 1))
    if task == "classification":
        _labels, counts = np.unique(y_train, return_counts=True)
        folds = min(folds, int(counts.min()) if counts.size else 0)
    if folds < 2 or len(y_train) < folds + 1:
        raise ValueError("Too few training rows for cross-validation.")
    return folds


def _column_complete(df: pd.DataFrame, column: str, oids: Sequence[int]) -> bool:
    headers = [str(name) for name in df.columns]
    oid_to_row = {int(oid): pos for pos, oid in enumerate(oids)}

    def cell_text(row: int, col: int) -> str:
        if row < 0:
            return ""
        return str(df.iat[row, col])

    def row_for_oid(oid: int) -> int:
        return oid_to_row.get(int(oid), -1)

    return column_complete_for_oids(
        column,
        oids,
        headers=headers,
        cell_text=cell_text,
        row_for_oid=row_for_oid,
    )


def _has_numeric(df: pd.DataFrame, column: str) -> bool:
    if column not in df.columns:
        return False
    return bool(pd.to_numeric(df[column], errors="coerce").notna().any())


def _missing_cell(raw: Any) -> bool:
    if raw is None:
        return True
    try:
        if pd.isna(raw):
            return True
    except (TypeError, ValueError):
        return False
    return False


def _format_descriptor_value(value: Any) -> str:
    if isinstance(value, str):
        text = value.strip()
        lowered = text.lower()
        if lowered == "yes":
            return "1"
        if lowered == "no":
            return "0"
        return text or "N/A"
    if isinstance(value, (bool, np.bool_)):
        return "1" if value else "0"
    if isinstance(value, (int, np.integer)):
        return str(int(value))
    if isinstance(value, (float, np.floating)):
        number = float(value)
        if not np.isfinite(number):
            return "N/A"
        return f"{number:.3f}"
    return str(value)


def _structure_maps(
    mol_rows: list[tuple[int, object]] | None,
) -> tuple[dict[int, object], dict[int, object], float]:
    from ..descriptors.descriptors_3d import mol_for_3d_descriptors

    mol_by_oid: dict[int, object] = {}
    three_d_by_oid: dict[int, object] = {}
    if not mol_rows:
        return mol_by_oid, three_d_by_oid, 0.0
    n_3d = 0
    for oid, mol in mol_rows:
        if oid is None:
            continue
        mol_by_oid[int(oid)] = mol
        posed = mol_for_3d_descriptors(mol)
        three_d_by_oid[int(oid)] = posed
        if posed is not None:
            n_3d += 1
    fraction = n_3d / len(mol_by_oid) if mol_by_oid else 0.0
    return mol_by_oid, three_d_by_oid, fraction


def _specs_for_attach(
    specs: Sequence[tuple[str, str]] | None,
    *,
    use_3d: bool,
    have_structures: bool,
) -> tuple[list[tuple[str, str]], str | None]:
    """Return the specs to consider and whether a 3D note should be recorded."""
    del have_structures
    if specs is None:
        chosen = list(auto_qsar_descriptor_specs(include_3d=use_3d))
        return chosen, "included" if use_3d else "skipped"
    chosen = [(display, key) for display, key in specs if use_3d or key not in DESCRIPTOR_3D_KEYS]
    mentions_3d = any(key in DESCRIPTOR_3D_KEYS for _display, key in specs)
    if not mentions_3d:
        return chosen, None
    return chosen, "included" if use_3d else "skipped"


def _three_d_note(fraction: float, *, included: bool) -> str:
    pct = f"{fraction:.0%}"
    if included:
        return f"3D descriptors included (poses on {pct} of rows)."
    return f"3D descriptors skipped (poses on {pct} of rows; need at least 80%)."


def _calculate_descriptor_columns(
    df: pd.DataFrame,
    oids: list[int],
    specs: Sequence[tuple[str, str]],
    mol_by_oid: Mapping[int, object],
    three_d_by_oid: Mapping[int, object],
    *,
    cancel_event: threading.Event | None,
    on_row: Callable[[int, int], None] | None,
) -> None:
    from ..workers.chemistry_descriptors import descriptor_callable_for_int_fn

    smarts_cache: dict[str, Any] = {}
    for display, _key in specs:
        if display not in df.columns:
            df[display] = pd.Series(["N/A"] * len(df), index=df.index, dtype=object)
        else:
            df[display] = df[display].astype(object)
    locations = {display: int(df.columns.get_loc(display)) for display, _key in specs}
    total = len(oids)
    for pos, oid in enumerate(oids):
        _check_cancel(cancel_event)
        row_oid = int(oid)
        mol = mol_by_oid.get(row_oid)
        row_ctx = {"oid": row_oid, "mol_3d": three_d_by_oid.get(row_oid)}
        for display, key in specs:
            text = "N/A"
            if mol is not None or row_ctx.get("mol_3d") is not None:
                fn = descriptor_callable_for_int_fn(key, smarts_cache, row_ctx)
                text = _call_descriptor(fn, mol)
            df.iat[pos, locations[display]] = text
        if on_row is not None:
            on_row(pos + 1, total)


def _call_descriptor(fn: Callable[..., Any], mol: object) -> str:
    try:
        value = fn(mol)
    except _DESCRIPTOR_ERRORS:
        return "N/A"
    return _format_descriptor_value(value)


def _prepare_sets(
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    task: TaskKind,
    train_fraction: float,
    table_columns: Sequence[str],
    descriptor_columns: Sequence[str],
    mol_rows: list[tuple[int, object]] | None,
    effort: str,
    notes: list[str],
) -> list[_PreparedSet]:
    prepared: list[_PreparedSet] = []
    numeric_groups: list[tuple[str, Sequence[str]]] = []
    if table_columns:
        numeric_groups.append(("Table columns", table_columns))
    if descriptor_columns:
        numeric_groups.append(("Computed descriptors", descriptor_columns))
    for name, columns in numeric_groups:
        item, reason = _prepare_feature_set(
            name=name,
            df=df,
            oids=oids,
            activity_column=activity_column,
            task=task,
            train_fraction=train_fraction,
            numeric_columns=list(columns),
            fp_choice=None,
            mol_rows=None,
        )
        if item is not None:
            prepared.append(item)
        elif reason:
            notes.append(f"{name}: {reason}")
    if mol_rows:
        fp_groups = [(FP_MORGAN, "Morgan"), (FP_MACCS, "MACCS")]
        if effort == "standard":
            fp_groups.append((FP_RDK, "RDK"))
        for fp_choice, name in fp_groups:
            item, reason = _prepare_feature_set(
                name=name,
                df=df,
                oids=oids,
                activity_column=activity_column,
                task=task,
                train_fraction=train_fraction,
                numeric_columns=None,
                fp_choice=fp_choice,
                mol_rows=mol_rows,
            )
            if item is not None:
                prepared.append(item)
            elif reason:
                notes.append(f"{name}: {reason}")
    return prepared


def _prepare_morgan_combo(
    prepared: Sequence[_PreparedSet],
    trials: Sequence[AutoQSARTrial],
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    task: TaskKind,
    train_fraction: float,
    mol_rows: list[tuple[int, object]] | None,
    notes: list[str],
) -> _PreparedSet | None:
    numeric = [item for item in prepared if item.fp_choice is None]
    numeric_names = {item.name for item in numeric}
    ranked = sorted(
        (trial for trial in trials if trial.feature_set in numeric_names), key=_trial_key
    )
    if not ranked:
        return None
    best = next(item for item in numeric if item.name == ranked[0].feature_set)
    name = f"{best.name} + Morgan"
    item, reason = _prepare_feature_set(
        name=name,
        df=df,
        oids=oids,
        activity_column=activity_column,
        task=task,
        train_fraction=train_fraction,
        numeric_columns=list(best.feature_columns),
        fp_choice=FP_MORGAN,
        mol_rows=mol_rows,
    )
    if item is None and reason:
        notes.append(f"{name}: {reason}")
    return item


def _prepare_feature_set(
    *,
    name: str,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    task: TaskKind,
    train_fraction: float,
    numeric_columns: list[str] | None,
    fp_choice: str | None,
    mol_rows: list[tuple[int, object]] | None,
) -> tuple[_PreparedSet | None, str | None]:
    from ..descriptors.ml_feature_matrix import build_combined_feature_matrix

    columns = _columns_with_enough_values(df, numeric_columns or [], activity_column)
    if not columns and not fp_choice:
        return None, "no columns left after the missing-value filter"
    try:
        built = build_combined_feature_matrix(
            df=df,
            oids=oids,
            feature_columns=columns or None,
            mol_rows=mol_rows,
            fp_choice=fp_choice,
            min_rows=MIN_ROWS,
            activity_column=activity_column,
        )
    except ValueError as exc:
        return None, str(exc)
    fit_df, fit_oids = _frame_for_matrix(df, built)
    y_raw = pd.to_numeric(fit_df[activity_column], errors="coerce").to_numpy(dtype=float)
    y, labels = _prepare_labels(y_raw, task)
    if task == "classification" and (labels is None or len(labels) < 2):
        return None, "classification needs at least two activity classes"
    try:
        train_idx, _test_idx = modeling_split_indices(y, task, train_fraction)
    except ValueError as exc:
        return None, str(exc)
    feature_columns: tuple[str, ...] = ()
    n_numeric = 0
    matrix = built.X
    if columns:
        names = list(built.feature_names[: built.n_numeric_features])
        numeric_frame = pd.DataFrame(
            np.asarray(built.X)[:, : built.n_numeric_features], columns=names
        )
        filtered = filter_training_features(numeric_frame, y, train_idx)
        if not filtered:
            return None, "all columns removed by the training-set filter"
        positions = [names.index(column) for column in filtered]
        numeric_block = np.asarray(built.X)[:, positions]
        n_numeric = len(filtered)
        feature_columns = tuple(filtered)
        if fp_choice and built.n_numeric_features < built.X.shape[1]:
            bits = np.asarray(built.X)[:, built.n_numeric_features :]
            matrix = np.hstack([numeric_block, bits])
        else:
            matrix = numeric_block
    return (
        _PreparedSet(
            name=name,
            X=np.asarray(matrix),
            y=y,
            train_idx=train_idx,
            n_numeric=n_numeric,
            feature_columns=feature_columns,
            fp_choice=fp_choice,
            fit_df=fit_df,
            fit_oids=fit_oids,
        ),
        None,
    )


def _columns_with_enough_values(
    df: pd.DataFrame,
    columns: Sequence[str],
    activity_column: str,
) -> list[str]:
    if not columns or activity_column not in df.columns:
        return []
    labeled = pd.to_numeric(df[activity_column], errors="coerce").notna()
    if not bool(labeled.any()):
        return []
    min_present = 1.0 - MISSING_FRACTION
    kept: list[str] = []
    for column in columns:
        if column not in df.columns or column == activity_column:
            continue
        values = pd.to_numeric(df.loc[labeled, column], errors="coerce")
        if float(values.notna().mean()) >= min_present:
            kept.append(column)
    return kept


def _frame_for_matrix(df: pd.DataFrame, built: Any) -> tuple[pd.DataFrame, list[int]]:
    """Rows of *built*, in matrix order, so a later refit cannot add hold-out rows."""
    subset = df.iloc[list(built.df_positions)].reset_index(drop=True)
    return subset, [int(oid) for oid in built.oids]


def _try_trial(
    item: _PreparedSet,
    task: TaskKind,
    model_key: str,
    params: Mapping[str, Any],
    stage: int,
    cv_folds: int,
) -> AutoQSARTrial | None:
    merged = _merge_model_params(model_key, dict(params))
    try:
        mean, std = score_training_matrix(
            item.X,
            item.y,
            item.train_idx,
            task=task,
            model_key=model_key,
            model_params=merged,
            cv_folds=cv_folds,
            n_numeric=item.n_numeric,
        )
    except _SCORE_ERRORS:
        return None
    if not np.isfinite(mean):
        return None
    return AutoQSARTrial(
        model_key=model_key,
        model_label=_model_label(task, model_key),
        feature_set=item.name,
        n_features=int(item.X.shape[1]),
        cv_mean=mean,
        cv_std=std if np.isfinite(std) else 0.0,
        stage=stage,
        feature_columns=item.feature_columns,
        fp_choice=item.fp_choice,
        model_params=tuple(merged.items()),
    )


def _score_stage2(
    prepared: Sequence[_PreparedSet],
    trials: list[AutoQSARTrial],
    task: TaskKind,
    cv_folds: int,
    total: int,
    on_progress: ProgressCallback | None,
    cancel_event: threading.Event | None,
    done: int,
) -> int:
    by_name = {item.name: item for item in prepared}
    for seed in _top_unique(trials, 3):
        item = by_name.get(seed.feature_set)
        if item is None:
            continue
        baseline = dict(seed.model_params)
        for overrides in stage2_param_grid(seed.model_key):
            merged = _merge_model_params(seed.model_key, overrides)
            if merged == baseline:
                continue
            _check_cancel(cancel_event)
            done += 1
            _emit_progress(
                on_progress,
                done,
                total,
                f"AutoQSAR: {seed.model_label} / {item.name}",
            )
            trial = _try_trial(item, task, seed.model_key, merged, 2, cv_folds)
            if trial is not None:
                trials.append(trial)
    return done


def _top_unique(trials: Sequence[AutoQSARTrial], limit: int) -> list[AutoQSARTrial]:
    seen: set[tuple[str, str]] = set()
    chosen: list[AutoQSARTrial] = []
    for trial in sorted(trials, key=_trial_key):
        key = (trial.feature_set, trial.model_key)
        if key in seen:
            continue
        seen.add(key)
        chosen.append(trial)
        if len(chosen) >= limit:
            break
    return chosen


def _trial_key(trial: AutoQSARTrial) -> tuple[Any, ...]:
    return (
        -float(trial.cv_mean),
        float(trial.cv_std),
        int(trial.n_features),
        trial.model_key,
        trial.feature_set,
        int(trial.stage),
    )


def _format_report(
    effort: str,
    task: TaskKind,
    metric: str,
    winner: AutoQSARTrial,
    fit: QSARFitResult,
    notes: Sequence[str],
) -> str:
    lines = [
        f"AutoQSAR ({effort})",
        f"Task: {task}",
        f"Selection metric: CV {metric} on the training split only.",
        "The hold-out score below was not used to choose the model.",
        "",
        f"Winner: {winner.model_label}  |  {winner.feature_set}",
        f"Selection CV: mean = {winner.cv_mean:.4f}  std = {winner.cv_std:.4f}",
        "",
        fit.metrics_text,
    ]
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append(f"  {note}")
    return "\n".join(lines)
