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

"""Dixon-style AutoQSAR: repeated 75/25 splits, a train/test score, and a consensus.

The learning set is every scoped row with a numeric activity and, when
structures are available, a structure. Descriptors are filtered once.
Fingerprints are modeled on their own. Quick keeps 5 models from 10 splits.
Standard keeps 10 models from 50 splits.
"""

from __future__ import annotations

import threading
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .auto_qsar_features import (
    DESCRIPTOR_SET,
    FINGERPRINT_SETS,
    MIN_LEARNING_ROWS,
    AutoQSARCancelled,
    descriptor_matrix,
    fingerprint_matrix,
    select_descriptor_columns,
)
from .auto_qsar_models import (
    conformal_half_width,
    fit_errors,
    fit_split_model,
    population_variance,
    prepare_domain,
    score_predictions,
)
from .qsar_models import TaskKind, _prepare_labels, infer_task_type

ProgressCallback = Callable[[int, int, str], None]

_DESCRIPTOR_METHODS = {
    "regression": ("mlr", "pls", "pcr", "kpls"),
    "classification": ("bayes", "rp"),
}
_FINGERPRINT_METHODS = {
    "regression": ("kpls",),
    "classification": ("bayes",),
}
_METHOD_LABEL = {
    "mlr": "MLR",
    "pls": "PLS",
    "pcr": "PCR",
    "kpls": "KPLS",
    "bayes": "Naive Bayes",
    "rp": "Ensemble trees",
}


def methods_for(task: str, feature_kind: str) -> tuple[str, ...]:
    """Dixon methods for one feature kind. Fingerprints are never mixed with descriptors."""
    key = str(task or "").strip().lower()
    kind = str(feature_kind or "").strip().lower()
    if kind == "descriptors":
        return _DESCRIPTOR_METHODS[key]
    if kind == "fingerprints":
        return _FINGERPRINT_METHODS[key]
    raise ValueError(f"Unknown AutoQSAR feature kind: {feature_kind}")


@dataclass(frozen=True)
class EffortSettings:
    """How many splits to build and how many models to retain."""

    key: str
    splits: int
    retain: int


@dataclass
class FeatureBlock:
    """One learning-set matrix. Rows match :attr:`AutoQSARResult.learning_oids`."""

    name: str
    kind: str
    columns: tuple[str, ...]
    bit_ids: np.ndarray
    fingerprint_kind: str
    values: np.ndarray
    requires_structure: bool


@dataclass
class AutoQSARModel:
    """One retained model. ``train_index`` selects rows of its feature block."""

    method: str
    method_label: str
    feature_set: str
    score: float
    train_accuracy: float
    test_accuracy: float
    split_index: int
    n_features: int
    train_index: np.ndarray
    estimator: Any
    half_width: float


@dataclass
class AutoQSARResult:
    """Retained models, the matrices they read, and the text report."""

    task: TaskKind
    effort: str
    activity_column: str
    n_built: int
    n_attempted: int
    models: tuple[AutoQSARModel, ...]
    blocks: dict[str, FeatureBlock]
    class_labels: tuple[Any, ...] | None
    learning_oids: tuple[int, ...]
    write_columns: tuple[str, ...]
    report_text: str
    notes: tuple[str, ...]


def effort_settings(effort: str) -> EffortSettings:
    """Quick is 10 splits retaining 5 models. Standard is 50 splits retaining 10."""
    key = str(effort or "quick").strip().lower()
    if key == "quick":
        return EffortSettings("quick", 10, 5)
    if key == "standard":
        return EffortSettings("standard", 50, 10)
    raise ValueError(f"Unknown AutoQSAR effort: {effort}")


def output_headers(
    output_column: str,
    task: str,
    write_columns: Sequence[str],
) -> list[str]:
    """Table headers for descriptor write-back, the prediction, and its qualifiers."""
    headers = [str(column) for column in write_columns]
    name = (output_column or "").strip() or "AutoQSAR"
    headers.append(name)
    if task == "regression":
        headers.append(f"{name} interval")
    else:
        headers.append(f"{name} probability")
    headers.append(f"{name} domain")
    return headers


def table_numeric_feature_columns(
    df: pd.DataFrame,
    activity_column: str,
    *,
    blocked_columns: Sequence[str] | None = None,
) -> list[str]:
    """Numeric columns eligible as user-supplied descriptor features."""
    from .dimensionality_reduction import is_fingerprint_bitcount_column

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


def table_write_rows(
    predictions: Sequence[tuple[int, Mapping[str, str]]],
    headers: Sequence[str],
) -> tuple[list[str], list[tuple[int, dict[str, str]]]]:
    """Shape prediction dicts into a table write. Missing cells become ``N/A``."""
    header_list = [str(header) for header in headers]
    rows = []
    for oid, values in predictions:
        payload = {header: str(values.get(header, "N/A")) for header in header_list}
        rows.append((int(oid), payload))
    return header_list, rows


def search_auto_qsar(
    *,
    df: pd.DataFrame,
    oids: list[int],
    activity_column: str,
    task_mode: str,
    effort: str,
    mol_rows: list[tuple[int, object]] | None = None,
    table_columns: Sequence[str] | None = None,
    blocked_columns: Sequence[str] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressCallback | None = None,
) -> AutoQSARResult:
    """Build, score, and retain the Dixon model pool for one activity column."""
    _check_cancel(cancel_event)
    if activity_column not in df.columns:
        raise ValueError(f"Activity column not found: {activity_column}")
    if len(oids) != len(df):
        raise ValueError("OID list length must match dataframe row count.")
    if table_columns is None:
        table_columns = table_numeric_feature_columns(
            df, activity_column, blocked_columns=blocked_columns
        )
    settings = effort_settings(effort)
    task = _resolve_task(df, activity_column, task_mode)
    notes: list[str] = []
    y_all = pd.to_numeric(df[activity_column], errors="coerce").to_numpy(dtype=float)
    mol_by_oid = _mol_by_oid(mol_rows)
    if mol_by_oid:
        notes.append(
            "RDKit 2D descriptors are used. Ipc, qed, Morgan fingerprint densities, "
            "and the unspecified-stereocenter count are left out."
        )
        notes.append("MOLPRINT2D is represented by unfolded feature-Morgan (FCFP), radius 2.")
    if table_columns:
        joined = ", ".join(str(column) for column in table_columns)
        notes.append(f"Table columns added to the calculated descriptors: {joined}.")
    else:
        notes.append("No table columns were added to the calculated descriptors.")
    candidate = _candidate_rows(oids, y_all, mol_by_oid, notes)
    if candidate.size < MIN_LEARNING_ROWS:
        raise ValueError(
            f"Need at least {MIN_LEARNING_ROWS} labeled rows"
            + (" with structures." if mol_by_oid else ".")
            + f" Found {int(candidate.size)}."
        )
    max_methods = len(_DESCRIPTOR_METHODS[task]) + 4 * len(_FINGERPRINT_METHODS[task])
    progress_total = int(candidate.size) + settings.splits * max_methods
    _emit(on_progress, 0, progress_total, "AutoQSAR: calculating descriptors")
    names, combined, calculated = _learning_matrix(
        df,
        oids,
        candidate,
        mol_by_oid,
        table_columns,
        blocked_columns,
        activity_column,
        cancel_event,
        on_progress,
        progress_total=progress_total,
    )
    row_local, columns, filter_note = select_descriptor_columns(combined)
    if filter_note:
        notes.append(filter_note)
    blocks: dict[str, FeatureBlock] = {}
    if columns.size:
        learning = candidate[row_local]
        desc_names = tuple(names[int(index)] for index in columns)
        blocks[DESCRIPTOR_SET] = FeatureBlock(
            name=DESCRIPTOR_SET,
            kind="descriptors",
            columns=desc_names,
            bit_ids=np.array([], dtype=np.int64),
            fingerprint_kind="",
            values=np.asarray(combined[np.ix_(row_local, columns)], dtype=float),
            requires_structure=any(name in calculated for name in desc_names),
        )
    elif mol_by_oid:
        learning = candidate
        notes.append("No descriptor column survived filtering.")
    else:
        raise ValueError(filter_note or "No descriptor column survived filtering.")
    if learning.size < MIN_LEARNING_ROWS:
        raise ValueError(
            f"Need at least {MIN_LEARNING_ROWS} complete learning rows. Found {int(learning.size)}."
        )
    y_raw = y_all[learning]
    y, class_labels = _prepare_labels(y_raw, task)
    if task == "classification" and (class_labels is None or len(class_labels) < 2):
        raise ValueError("Classification needs at least two activity classes.")
    learning_oids = tuple(int(oids[int(index)]) for index in learning)
    mols = [mol_by_oid.get(oid) for oid in learning_oids]
    if mol_by_oid:
        _note_duplicate_structures(mols, notes)
        _add_fingerprint_blocks(blocks, mols, notes, cancel_event)
    else:
        notes.append("No structures; fingerprints were not calculated.")
    if not blocks:
        raise ValueError("AutoQSAR found no descriptor or fingerprint features.")
    jobs = _jobs_for_blocks(task, blocks)
    if not jobs:
        raise ValueError("AutoQSAR found no model to fit for this task.")
    fit_total = int(candidate.size) + settings.splits * len(jobs)
    built: list[AutoQSARModel] = []
    attempted = 0
    done = 0
    last_error = ""
    learning_variance = population_variance(y) if task == "regression" else 0.0
    classes = tuple(range(len(class_labels))) if class_labels else ()
    for split_index in range(settings.splits):
        try:
            train_index, test_index = _split_indices(y, task, split_index)
        except ValueError:
            continue
        if task == "classification" and len(np.unique(np.asarray(y)[train_index])) < 2:
            continue
        if train_index.size < 4 or test_index.size < 1:
            continue
        for method, feature_name in jobs:
            _check_cancel(cancel_event)
            done += 1
            attempted += 1
            block = blocks[feature_name]
            _emit(
                on_progress,
                int(candidate.size) + done,
                fit_total,
                f"AutoQSAR: {_METHOD_LABEL[method]} / {feature_name} "
                f"(split {split_index + 1}/{settings.splits})",
            )
            model, error = _try_model(
                method,
                feature_name,
                block,
                y,
                train_index,
                test_index,
                task=task,
                split_index=split_index,
                learning_variance=learning_variance,
                classes=classes,
            )
            if model is not None:
                built.append(model)
            elif error:
                last_error = error
    if not built:
        detail = last_error or " ".join(notes)
        raise ValueError(detail or "AutoQSAR could not fit a model on this scope.")
    retained = tuple(sorted(built, key=_rank_key)[: settings.retain])
    for model in retained:
        prepare_domain(model.estimator, blocks[model.feature_set].values[model.train_index])
    write_columns = _write_columns(df, retained, blocks.get(DESCRIPTOR_SET), calculated)
    report = _format_report(
        settings,
        task,
        learning_oids,
        len(built),
        attempted,
        retained,
        notes,
    )
    _emit(on_progress, fit_total, fit_total, "AutoQSAR: done")
    return AutoQSARResult(
        task=task,
        effort=settings.key,
        activity_column=activity_column,
        n_built=len(built),
        n_attempted=attempted,
        models=retained,
        blocks=blocks,
        class_labels=class_labels,
        learning_oids=learning_oids,
        write_columns=write_columns,
        report_text=report,
        notes=tuple(notes),
    )


def predict_auto_qsar(
    result: AutoQSARResult,
    *,
    df: pd.DataFrame,
    oids: list[int],
    mol_rows: list[tuple[int, object]] | None,
    output_column: str,
    model_index: int | None = None,
    cancel_event: threading.Event | None = None,
) -> list[tuple[int, dict[str, str]]]:
    """Score rows with the consensus, or with one retained model when *model_index* is set."""
    _check_cancel(cancel_event)
    if len(oids) != len(df):
        raise ValueError("OID list length must match dataframe row count.")
    if not result.models:
        return []
    if model_index is None:
        chosen = result.models
    else:
        if model_index < 0 or model_index >= len(result.models):
            raise ValueError("Selected AutoQSAR model is no longer available.")
        chosen = (result.models[model_index],)
    headers = output_headers(output_column, result.task, result.write_columns)
    pred_name, qualifier_name, domain_name = headers[-3:]
    mol_by_oid = _mol_by_oid(mol_rows)
    mols = [mol_by_oid.get(int(oid)) for oid in oids]
    query_blocks = _query_blocks(result, df, oids, mols, cancel_event)
    rows: list[tuple[int, dict[str, str]]] = []
    write_block = result.blocks.get(DESCRIPTOR_SET)
    for row_index, oid in enumerate(oids):
        _check_cancel(cancel_event)
        if not all(_row_is_ready(model, query_blocks, row_index) for model in chosen):
            continue
        predictions = []
        domains = []
        probabilities = []
        for model in chosen:
            block = result.blocks[model.feature_set]
            query = query_blocks[model.feature_set]
            train = block.values[model.train_index]
            row = query.values[row_index : row_index + 1]
            predictions.append(np.asarray(model.estimator.predict(row, train)).ravel()[0])
            domains.append(bool(np.asarray(model.estimator.domain_mask(row, train)).ravel()[0]))
            probabilities.append(_probability_map(model.estimator, row))
        payload: dict[str, str] = {}
        _fill_descriptor_cells(payload, result.write_columns, write_block, query_blocks, row_index)
        if result.task == "regression":
            value = float(np.mean(predictions))
            half = float(np.mean([model.half_width for model in chosen]))
            payload[pred_name] = f"{value:.6g}"
            payload[qualifier_name] = f"{half:.4g}"
        else:
            code, probability = _consensus_class(
                [int(value) for value in predictions],
                probabilities,
            )
            label = _class_label(result.class_labels, code)
            payload[pred_name] = label
            payload[qualifier_name] = f"{probability:.3f}"
        in_domain = sum(domains) * 2 >= len(domains)
        payload[domain_name] = "in" if in_domain else "out"
        rows.append((int(oid), payload))
    return rows


def _fingerprint_onbit_headers() -> frozenset[str]:
    from ..chem.rdkit_fingerprints import FINGERPRINT_SPECS, descriptor_onbits_column_aliases

    names: set[str] = set()
    for spec in FINGERPRINT_SPECS:
        names.update(descriptor_onbits_column_aliases(spec.label))
    return frozenset(names)


def _check_cancel(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise AutoQSARCancelled()


def _emit(on_progress: ProgressCallback | None, done: int, total: int, message: str) -> None:
    if on_progress is not None:
        on_progress(int(done), int(total), message)


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


def _mol_by_oid(mol_rows: list[tuple[int, object]] | None) -> dict[int, object]:
    found: dict[int, object] = {}
    for oid, mol in mol_rows or []:
        if oid is None or mol is None:
            continue
        found[int(oid)] = mol
    return found


def _candidate_rows(
    oids: Sequence[int],
    y_all: np.ndarray,
    mol_by_oid: Mapping[int, object],
    notes: list[str],
) -> np.ndarray:
    labeled = np.flatnonzero(np.isfinite(y_all))
    if not mol_by_oid:
        return labeled
    kept = [int(index) for index in labeled if mol_by_oid.get(int(oids[int(index)])) is not None]
    skipped = int(labeled.size - len(kept))
    if skipped:
        notes.append(
            f"{skipped} labeled rows had no structure and were left out of the learning set."
        )
    return np.asarray(kept, dtype=int)


def _learning_matrix(
    df: pd.DataFrame,
    oids: Sequence[int],
    candidate: np.ndarray,
    mol_by_oid: Mapping[int, object],
    table_columns: Sequence[str] | None,
    blocked_columns: Sequence[str] | None,
    activity_column: str,
    cancel_event: threading.Event | None,
    on_progress: ProgressCallback | None,
    progress_total: int = 0,
) -> tuple[list[str], np.ndarray, set[str]]:
    mols = [mol_by_oid.get(int(oids[int(index)])) for index in candidate]
    names: list[str] = []
    parts: list[np.ndarray] = []
    calculated: set[str] = set()
    if any(mol is not None for mol in mols):

        def on_row(done: int, total: int) -> None:
            overall = progress_total if progress_total else total
            _emit(on_progress, done, max(1, overall), "AutoQSAR: calculating descriptors")

        rdkit_names, rdkit_values = descriptor_matrix(
            mols, cancel_event=cancel_event, on_row=on_row
        )
        names.extend(rdkit_names)
        parts.append(rdkit_values)
        calculated.update(rdkit_names)
    blocked = set(blocked_columns or ())
    blocked.add(activity_column)
    for column in table_columns or ():
        if column in names or column in blocked or column not in df.columns:
            continue
        values = pd.to_numeric(df.iloc[candidate][column], errors="coerce").to_numpy(dtype=float)
        names.append(str(column))
        parts.append(values.reshape(-1, 1))
    if not parts:
        raise ValueError(
            "AutoQSAR needs structures to calculate descriptors, or at least one selected table column."
        )
    combined = parts[0] if len(parts) == 1 else np.column_stack(parts)
    return names, np.asarray(combined, dtype=float), calculated


def _add_fingerprint_blocks(
    blocks: dict[str, FeatureBlock],
    mols: Sequence[object | None],
    notes: list[str],
    cancel_event: threading.Event | None,
) -> None:
    ready = [mol for mol in mols if mol is not None]
    if len(ready) != len(mols):
        notes.append("Fingerprints were skipped because a learning row has no structure.")
        return
    for label, kind in FINGERPRINT_SETS:
        _check_cancel(cancel_event)
        bit_ids, values = fingerprint_matrix(ready, kind)
        if bit_ids.size == 0:
            notes.append(f"{label}: no varying fingerprint bits.")
            continue
        blocks[label] = FeatureBlock(
            name=label,
            kind="fingerprints",
            columns=(),
            bit_ids=bit_ids,
            fingerprint_kind=kind,
            values=values,
            requires_structure=True,
        )


def _note_duplicate_structures(mols: Sequence[object | None], notes: list[str]) -> None:
    from rdkit import Chem

    smiles: list[str] = []
    for mol in mols:
        if mol is None:
            continue
        try:
            smiles.append(Chem.MolToSmiles(mol))
        except (ValueError, RuntimeError):
            continue
    extra = len(smiles) - len(set(smiles))
    if extra:
        notes.append(f"{extra} duplicate structures were kept in the learning set.")


def _split_indices(
    y: np.ndarray, task: TaskKind, split_index: int
) -> tuple[np.ndarray, np.ndarray]:
    from sklearn.model_selection import train_test_split

    index = np.arange(len(y))
    stratify = y if task == "classification" and len(np.unique(y)) > 1 else None
    try:
        train, test = train_test_split(
            index, test_size=0.25, random_state=int(split_index), stratify=stratify
        )
    except ValueError:
        if stratify is None:
            raise
        train, test = train_test_split(index, test_size=0.25, random_state=int(split_index))
    return np.asarray(train, dtype=int), np.asarray(test, dtype=int)


def _try_model(
    method: str,
    feature_name: str,
    block: FeatureBlock,
    y: np.ndarray,
    train_index: np.ndarray,
    test_index: np.ndarray,
    *,
    task: str,
    split_index: int,
    learning_variance: float,
    classes: Sequence,
) -> tuple[AutoQSARModel | None, str]:
    if block.values.shape[1] == 0:
        return None, f"{feature_name} has no columns."
    try:
        estimator, train_pred, test_pred, n_features = fit_split_model(
            method,
            block.values,
            y,
            train_index,
            test_index,
            task=task,
            split_index=split_index,
        )
        score, train_accuracy, test_accuracy = score_predictions(
            y,
            train_index,
            test_index,
            train_pred,
            test_pred,
            task=task,
            learning_variance=learning_variance,
            classes=classes,
        )
    except fit_errors() as exc:
        return None, str(exc) or exc.__class__.__name__
    if not np.isfinite(score):
        return None, f"{feature_name} produced a non-finite score."
    half_width = 0.0
    if task == "regression":
        half_width = conformal_half_width(np.asarray(y)[test_index] - np.asarray(test_pred))
    return AutoQSARModel(
        method=method,
        method_label=_METHOD_LABEL.get(method, method),
        feature_set=feature_name,
        score=float(score),
        train_accuracy=float(train_accuracy),
        test_accuracy=float(test_accuracy),
        split_index=int(split_index),
        n_features=int(n_features),
        train_index=np.asarray(train_index, dtype=int),
        estimator=estimator,
        half_width=float(half_width),
    ), ""


def _rank_key(model: AutoQSARModel) -> tuple:
    return (
        -float(model.score),
        -float(model.test_accuracy),
        -float(model.train_accuracy),
        model.method,
        model.feature_set,
        int(model.split_index),
    )


def _write_columns(
    df: pd.DataFrame,
    models: Sequence[AutoQSARModel],
    block: FeatureBlock | None,
    calculated: set[str],
) -> tuple[str, ...]:
    if block is None:
        return ()
    from .auto_qsar_models import MLREnsemble

    used: set[str] = set()
    for model in models:
        if model.feature_set != block.name:
            continue
        if isinstance(model.estimator, MLREnsemble):
            for subset in model.estimator.subsets:
                used.update(block.columns[int(index)] for index in subset)
        else:
            used.update(block.columns)
    ordered = []
    for name in block.columns:
        if name not in used or name not in calculated:
            continue
        if name not in df.columns:
            ordered.append(name)
            continue
        numeric = pd.to_numeric(df[name], errors="coerce")
        if not bool(numeric.notna().all()):
            ordered.append(name)
    return tuple(ordered)


def _jobs_for_blocks(task: TaskKind, blocks: Mapping[str, FeatureBlock]) -> list[tuple[str, str]]:
    jobs: list[tuple[str, str]] = []
    if DESCRIPTOR_SET in blocks:
        jobs.extend((method, DESCRIPTOR_SET) for method in _DESCRIPTOR_METHODS[task])
    for name, block in blocks.items():
        if block.kind != "fingerprints":
            continue
        jobs.extend((method, name) for method in _FINGERPRINT_METHODS[task])
    return jobs


def _format_report(
    settings: EffortSettings,
    task: TaskKind,
    learning_oids: Sequence[int],
    n_built: int,
    attempted: int,
    models: Sequence[AutoQSARModel],
    notes: Sequence[str],
) -> str:
    if n_built == attempted:
        built_line = f"Built {n_built} models and retained {len(models)}."
    else:
        built_line = f"Built {n_built} of {attempted} models and retained {len(models)}."
    lines = [
        "AutoQSAR",
        f"Task: {task}",
        f"Learning rows: {len(learning_oids)}",
        f"Split: random 75/25, repeated {settings.splits} times.",
        built_line,
        "Score = test accuracy × (1 − |train accuracy − test accuracy|).",
        "A negative test accuracy is used as the score.",
        "Continuous test accuracy divides by the variance of the learning-set activity.",
        "Categorical accuracy is the unweighted mean of per-class recall.",
        "",
        "Retained models, best score first:",
    ]
    for model in models:
        lines.append(
            f"  {model.score:.4f}  test {model.test_accuracy:.4f}  "
            f"train {model.train_accuracy:.4f}  {model.method_label}  {model.feature_set}"
        )
    lines.extend(
        [
            "",
            "Default predictions are the unweighted consensus of the retained models.",
            "Regression consensus is the mean. Classification consensus is a majority vote,",
            "with ties broken by the average class probability.",
            "Learning-set rows were used to train some of the retained models.",
            "Rows outside this scope are the external set.",
            "A row is out of domain when its distance to a model's training rows exceeds",
            "the 95th percentile of distances inside that training set. The regression",
            "interval is a 90% split-conformal half-width from each model's own test residuals.",
        ]
    )
    if notes:
        lines.append("")
        lines.append("Notes:")
        for note in notes:
            lines.append(f"  {note}")
    return "\n".join(lines)


@dataclass
class _QueryBlock:
    values: np.ndarray
    valid: np.ndarray


def _query_blocks(
    result: AutoQSARResult,
    df: pd.DataFrame,
    oids: Sequence[int],
    mols: Sequence[object | None],
    cancel_event: threading.Event | None,
) -> dict[str, _QueryBlock]:
    from .auto_qsar_features import _on_bit_ids

    found: dict[str, _QueryBlock] = {}
    descriptor_block = result.blocks.get(DESCRIPTOR_SET)
    full_names: tuple[str, ...] = ()
    full_values = None
    if any(block.kind == "descriptors" for block in result.blocks.values()):
        _check_cancel(cancel_event)
        try:
            full_names, full_values, _calculated = _learning_matrix(
                df,
                oids,
                np.arange(len(oids)),
                _mol_by_oid([(int(oid), mol) for oid, mol in zip(oids, mols, strict=True)]),
                [column for column in df.columns if column in _needed_table_columns(result)],
                None,
                result.activity_column,
                cancel_event,
                None,
            )
        except ValueError:
            full_names = ()
            full_values = None
    for name, block in result.blocks.items():
        if block.kind == "descriptors" and descriptor_block is not None:
            if full_values is None:
                found[name] = _QueryBlock(
                    values=np.full((len(oids), len(block.columns)), np.nan),
                    valid=np.zeros(len(oids), dtype=bool),
                )
                continue
            position = {column: index for index, column in enumerate(full_names)}
            selected = [position[column] for column in block.columns if column in position]
            if len(selected) != len(block.columns):
                values = np.full((len(oids), len(block.columns)), np.nan)
                valid = np.zeros(len(oids), dtype=bool)
            else:
                values = full_values[:, selected]
                valid = np.isfinite(values).all(axis=1)
                if block.requires_structure:
                    valid &= np.array([mol is not None for mol in mols], dtype=bool)
            found[name] = _QueryBlock(values=values, valid=valid)
            continue
        if block.kind != "fingerprints":
            continue
        values = np.zeros((len(mols), int(block.bit_ids.size)), dtype=np.float32)
        valid = np.array([mol is not None for mol in mols], dtype=bool)
        column = {int(bit): index for index, bit in enumerate(block.bit_ids)}
        for row, mol in enumerate(mols):
            if mol is None:
                continue
            try:
                bits = _on_bit_ids(mol, block.fingerprint_kind)
            except (
                ValueError,
                TypeError,
                RuntimeError,
                ArithmeticError,
                AttributeError,
                KeyError,
                IndexError,
            ):
                valid[row] = False
                continue
            for bit in bits:
                index = column.get(int(bit))
                if index is not None:
                    values[row, index] = 1.0
        found[name] = _QueryBlock(values=values, valid=valid)
    return found


def _needed_table_columns(result: AutoQSARResult) -> set[str]:
    block = result.blocks.get(DESCRIPTOR_SET)
    if block is None:
        return set()
    calculated_prefixes = ("AUTOCORR2D_", "MQN_")
    return {
        column
        for column in block.columns
        if not column.startswith(calculated_prefixes) and column not in _known_rdkit_names()
    }


def _known_rdkit_names() -> set[str]:
    from .auto_qsar_features import rdkit_descriptor_names

    return set(rdkit_descriptor_names())


def _row_is_ready(model: AutoQSARModel, blocks: Mapping[str, _QueryBlock], row: int) -> bool:
    query = blocks.get(model.feature_set)
    return query is not None and bool(query.valid[row])


def _probability_map(estimator: Any, row: np.ndarray) -> dict[Any, float]:
    if not hasattr(estimator, "probabilities"):
        return {}
    packed = estimator.probabilities(row)
    if packed is None:
        return {}
    classes, proba = packed
    mapped: dict[Any, float] = {}
    for index, label in enumerate(classes):
        try:
            key: Any = int(label)
        except (TypeError, ValueError):
            key = label
        mapped[key] = float(proba[0, index])
    return mapped


def _consensus_class(
    predictions: Sequence[Any],
    probabilities: Sequence[Mapping[Any, float]],
) -> tuple[Any, float]:
    votes = Counter(predictions)
    top = max(votes.values())
    tied = [label for label, count in votes.items() if count == top]
    if len(tied) == 1:
        winner = tied[0]
        return winner, votes[winner] / len(predictions)
    best = tied[0]
    best_probability = -1.0
    for label in tied:
        average = float(np.mean([row.get(label, 0.0) for row in probabilities]))
        if average > best_probability:
            best = label
            best_probability = average
    return best, best_probability


def _class_label(labels: tuple[Any, ...] | None, code: Any) -> str:
    if labels is None:
        return str(code)
    try:
        return str(labels[int(code)])
    except (TypeError, ValueError, IndexError):
        return str(code)


def _fill_descriptor_cells(
    payload: dict[str, str],
    columns: Sequence[str],
    block: FeatureBlock | None,
    queries: Mapping[str, _QueryBlock],
    row: int,
) -> None:
    if block is None or not columns:
        return
    query = queries.get(block.name)
    if query is None:
        return
    position = {name: index for index, name in enumerate(block.columns)}
    for name in columns:
        index = position.get(name)
        if index is None or not np.isfinite(query.values[row, index]):
            payload[name] = "N/A"
            continue
        payload[name] = f"{float(query.values[row, index]):.6g}"
