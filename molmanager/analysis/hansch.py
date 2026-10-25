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

"""Hansch analysis on a shared core (no Qt).

Rows are decomposed the same way as Free-Wilson. Each R-group is looked up in
a user-supplied constants file, and the shared least-squares fitter solves

activity = a·π + b·π² + ρ·σ + steric + intercept

with one column per selected parameter per attachment position.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from threading import Event

import numpy as np
from rdkit import Chem

from .free_wilson import (
    _decompose,
    _position_names,
    _substituents_from_row,
    parse_free_wilson_core,
    rgroup_decomp_failure_message,
)
from .linear_fit import design_columns_with_intercept, fit_linear
from .substituent_constants import SubstituentRecord, SubstituentTable, load_substituent_constants

ELECTRONIC_NONE = "none"
ELECTRONIC_SIGMA = "sigma"
ELECTRONIC_FIELD_RESONANCE = "field_resonance"
STERIC_NONE = ""
STERIC_ES = "es"
STERIC_MR = "mr"
STERIC_UPSILON = "upsilon"
SIGMA_META = "meta"
SIGMA_PARA = "para"
PREDICTED_COLUMN = "Hansch_Predicted"

SKIP_NO_MATCH = "no core match"
SKIP_ACTIVITY = "no numeric activity"
SKIP_INCOMPLETE = "incomplete decomposition"
SKIP_UNMATCHED = "substituent not in constants table"

_RDKIT_ERRORS = (RuntimeError, ValueError, TypeError, OSError)
_SIGMA_META_WORDS = {"m", "meta", "σm"}
_SIGMA_PARA_WORDS = {"p", "para", "σp"}

ProgressCallback = Callable[[str, int, int], None]


class _Cancelled(Exception):
    """Raised when the caller sets the cancel event."""


@dataclass(frozen=True)
class HanschSettings:
    """Fit options. Structure scope stays in the dialog."""

    core_query: str
    constants_path: str
    activity_column: str = ""
    include_pi: bool = True
    include_pi_squared: bool = False
    electronic: str = ELECTRONIC_SIGMA
    sigma_default: str = SIGMA_PARA
    sigma_positions: tuple[tuple[str, str], ...] = ()
    steric: str = STERIC_NONE
    only_match_at_r_groups: bool = True
    matching: str = "greedy"


@dataclass(frozen=True)
class HanschCoefficient:
    """One column of the Hansch equation."""

    name: str
    coefficient: float | None
    std_error: float | None
    t_value: float | None
    p_value: float | None
    vif: float | None
    identifiable: bool


@dataclass(frozen=True)
class HanschObservation:
    """Observed activity and the Hansch prediction for one fitted row."""

    oid: int
    observed: float
    predicted: float
    residual: float
    substituents: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class HanschSkipped:
    """A row left out of the fit, with a short reason."""

    oid: int
    reason: str


@dataclass(frozen=True)
class HanschResult:
    """Hansch equation, diagnostics, and the rows that were left out."""

    ok: bool
    message: str
    cancelled: bool
    activity_column: str
    equation: str
    n: int
    n_parameters: int
    r_squared: float | None
    adjusted_r_squared: float | None
    q_squared: float | None
    rmse: float | None
    residual_df: int
    saturated: bool
    intercept: float
    intercept_std_error: float | None
    intercept_t: float | None
    intercept_p: float | None
    coefficients: tuple[HanschCoefficient, ...]
    observed: tuple[HanschObservation, ...]
    skipped: tuple[HanschSkipped, ...]
    unmatched: tuple[tuple[str, str], ...]
    positions: tuple[str, ...]


@dataclass
class _Prepared:
    oid: int
    activity: float
    subs: dict[str, str]
    labels: dict[str, str]
    values: dict[str, float]


def parse_sigma_assignments(text: str) -> dict[str, str]:
    """Parse ``R1=meta, R2=para`` into a position → meta/para map.

    Separators are commas, semicolons, or new lines. ``R1 meta`` is also accepted.
    """
    out: dict[str, str] = {}
    chunks = (text or "").replace(";", "\n").replace(",", "\n").splitlines()
    for raw in chunks:
        line = raw.strip()
        if not line:
            continue
        if "=" in line:
            position, kind = line.split("=", 1)
        else:
            parts = line.split()
            if len(parts) != 2:
                raise ValueError(f"Could not read σ assignment {line!r}. Use R1=meta.")
            position, kind = parts
        position = position.strip()
        if not (position.startswith("R") and position[1:].isdigit()):
            raise ValueError(f"σ assignment {position} is not an R-group label such as R1.")
        parsed = _sigma_word(kind.strip().lower())
        if parsed is None:
            raise ValueError(f"σ for {position} must be meta or para.")
        if position in out:
            raise ValueError(f"σ for {position} is assigned more than once.")
        out[position] = parsed
    return out


def settings_error(settings: HanschSettings) -> str:
    """Empty when *settings* can be sent to :func:`run_hansch`."""
    if not (settings.core_query or "").strip():
        return "Enter a core SMARTS or SMILES."
    if parse_free_wilson_core(settings.core_query) is None:
        return "Core is not valid SMARTS or SMILES."
    if not (settings.constants_path or "").strip():
        return "Choose a substituent constants file."
    if not Path(settings.constants_path).is_file():
        return "Constants file was not found."
    if not _has_term(settings):
        return "Select at least one Hansch term."
    if settings.electronic == ELECTRONIC_SIGMA and settings.sigma_default not in {
        SIGMA_META,
        SIGMA_PARA,
    }:
        return "Default σ must be meta or para."
    if settings.steric not in {STERIC_NONE, STERIC_ES, STERIC_MR, STERIC_UPSILON}:
        return "Steric term must be Es, molar refractivity, υ, or none."
    if settings.electronic not in {
        ELECTRONIC_NONE,
        ELECTRONIC_SIGMA,
        ELECTRONIC_FIELD_RESONANCE,
    }:
        return "Electronic term must be Hammett σ, field and resonance, or none."
    for position, kind in settings.sigma_positions:
        if kind not in {SIGMA_META, SIGMA_PARA}:
            return f"σ for {position} must be meta or para."
    return ""


def format_equation(activity: str, intercept: float, terms: Sequence[tuple[str, float]]) -> str:
    """Plain-text Hansch equation. Only identifiable terms belong in *terms*."""
    left = (activity or "").strip() or "Activity"
    body = f"{intercept:.6g}"
    for name, coefficient in terms:
        sign = "+" if coefficient >= 0.0 else "-"
        body += f" {sign} {abs(coefficient):.6g}*{name}"
    return f"{left} = {body}"


def run_hansch(
    records: Sequence[tuple[int, Chem.Mol, float]],
    settings: HanschSettings,
    *,
    cancel_event: Event | None = None,
    progress: ProgressCallback | None = None,
) -> HanschResult:
    """Decompose *records*, look up substituent constants, and fit the Hansch equation.

    *records* are ``(oid, mol, activity)``. Rows that miss the core, lack a finite
    activity, or contain a substituent the constants file cannot score are skipped.
    """
    try:
        return _run(records, settings, cancel_event=cancel_event, progress=progress)
    except _Cancelled:
        return _result(settings, cancelled=True, message="Cancelled.")


def _run(
    records: Sequence[tuple[int, Chem.Mol, float]],
    settings: HanschSettings,
    *,
    cancel_event: Event | None,
    progress: ProgressCallback | None,
) -> HanschResult:
    problem = settings_error(settings)
    if problem:
        return _result(settings, message=problem)
    _check_cancel(cancel_event)
    try:
        table = load_substituent_constants(settings.constants_path)
    except ValueError as exc:
        return _result(settings, message=str(exc))
    core = parse_free_wilson_core(settings.core_query)
    if core is None:
        return _result(settings, message="Core is not valid SMARTS or SMILES.")
    total = max(len(records), 1)
    _report(progress, "Hansch: decomposing", 0, total)
    try:
        decomp_rows, unmatched = _decompose(
            core,
            records,
            only_match_at_r_groups=bool(settings.only_match_at_r_groups),
            matching=settings.matching,
        )
    except _RDKIT_ERRORS as exc:
        return _result(settings, message=rgroup_decomp_failure_message(exc, tool="Hansch"))
    _check_cancel(cancel_event)
    _report(progress, "Hansch: decomposing", total, total)
    aligned, positions, skipped = _align(records, decomp_rows, unmatched)
    if not aligned or not positions:
        return _result(
            settings,
            message="No rows matched the core (check labels and attachment-point dummies).",
            skipped=tuple(skipped),
        )
    plan = _term_plan(positions, settings)
    if not plan:
        return _result(settings, message="Select at least one Hansch term.", skipped=tuple(skipped))
    prepared, unmatched_pairs = _prepare(aligned, positions, table, plan, skipped)
    if len(prepared) < 2:
        return _result(
            settings,
            message=(
                "Need at least two molecules that match the core, have a numeric activity, "
                "and have constants for every selected term."
            ),
            skipped=tuple(skipped),
            unmatched=tuple(unmatched_pairs),
            positions=tuple(positions),
        )
    _check_cancel(cancel_event)
    _report(progress, "Hansch: fitting", 0, 1)
    names = [name for name, _kind, _position in plan]
    design = np.column_stack([[row.values[name] for row in prepared] for name in names])
    kept = design_columns_with_intercept(design)
    if not kept:
        return _result(
            settings,
            message="The selected constants do not vary across the fitted rows.",
            skipped=tuple(skipped),
            unmatched=tuple(unmatched_pairs),
            positions=tuple(positions),
        )
    reduced = design[:, kept]
    y = np.array([row.activity for row in prepared], dtype=float)
    fit = fit_linear(y, reduced)
    coefficients = _coefficients(names, kept, fit)
    equation_terms = [
        (item.name, item.coefficient)
        for item in coefficients
        if item.identifiable and item.coefficient is not None
    ]
    observed = tuple(
        HanschObservation(
            oid=row.oid,
            observed=row.activity,
            predicted=fit.predictions[index],
            residual=fit.residuals[index],
            substituents=tuple((position, row.labels[position]) for position in positions),
        )
        for index, row in enumerate(prepared)
    )
    dropped = sum(1 for item in coefficients if not item.identifiable)
    message = f"Fitted {len(prepared)} molecule(s)."
    if dropped:
        message += f" Dropped {dropped} collinear term(s)."
    unused = _unused_sigma_positions(settings, positions)
    if unused:
        message += " Ignored σ assignments for " + ", ".join(unused) + "."
    _report(progress, "Hansch: fitting", 1, 1)
    return _result(
        settings,
        ok=True,
        message=message,
        equation=format_equation(settings.activity_column, fit.intercept, equation_terms),
        n=len(prepared),
        n_parameters=fit.n_parameters,
        r_squared=fit.r_squared,
        adjusted_r_squared=fit.adjusted_r_squared,
        q_squared=fit.q_squared,
        rmse=fit.rmse,
        residual_df=fit.residual_df,
        saturated=fit.saturated,
        intercept=fit.intercept,
        intercept_std_error=fit.intercept_std_error,
        intercept_t=fit.intercept_t,
        intercept_p=fit.intercept_p,
        coefficients=coefficients,
        observed=observed,
        skipped=tuple(skipped),
        unmatched=tuple(unmatched_pairs),
        positions=tuple(positions),
    )


def _has_term(settings: HanschSettings) -> bool:
    return bool(
        settings.include_pi
        or settings.include_pi_squared
        or settings.electronic != ELECTRONIC_NONE
        or settings.steric != STERIC_NONE
    )


def _sigma_word(text: str) -> str | None:
    if text in _SIGMA_META_WORDS:
        return SIGMA_META
    if text in _SIGMA_PARA_WORDS:
        return SIGMA_PARA
    return None


def _term_plan(
    positions: list[str],
    settings: HanschSettings,
) -> list[tuple[str, str, str]]:
    """``(column name, record field, position)`` in equation order."""
    chosen = dict(settings.sigma_positions)
    plan: list[tuple[str, str, str]] = []
    for position in positions:
        if settings.include_pi:
            plan.append((f"{position} π", "pi", position))
        if settings.include_pi_squared:
            plan.append((f"{position} π²", "pi2", position))
        if settings.electronic == ELECTRONIC_SIGMA:
            kind = chosen.get(position, settings.sigma_default)
            if kind == SIGMA_META:
                plan.append((f"{position} σm", "sigma_m", position))
            else:
                plan.append((f"{position} σp", "sigma_p", position))
        elif settings.electronic == ELECTRONIC_FIELD_RESONANCE:
            plan.append((f"{position} F", "f", position))
            plan.append((f"{position} R", "r", position))
        if settings.steric == STERIC_ES:
            plan.append((f"{position} Es", "es", position))
        elif settings.steric == STERIC_MR:
            plan.append((f"{position} MR", "mr", position))
        elif settings.steric == STERIC_UPSILON:
            plan.append((f"{position} υ", "upsilon", position))
    return plan


def _align(
    records: Sequence[tuple[int, Chem.Mol, float]],
    decomp_rows: list[dict],
    unmatched: list[int],
) -> tuple[list[tuple[int, Chem.Mol, float, dict]], list[str], list[HanschSkipped]]:
    unmatched_set = set(unmatched)
    aligned: list[tuple[int, Chem.Mol, float, dict]] = []
    skipped: list[HanschSkipped] = []
    row_index = 0
    for index, (oid, mol, activity) in enumerate(records):
        if index in unmatched_set:
            skipped.append(HanschSkipped(int(oid), SKIP_NO_MATCH))
            continue
        if row_index >= len(decomp_rows):
            skipped.append(HanschSkipped(int(oid), SKIP_INCOMPLETE))
            continue
        aligned.append((int(oid), mol, float(activity), decomp_rows[row_index]))
        row_index += 1
    positions = _position_names(aligned[0][3]) if aligned else []
    return aligned, positions, skipped


def _prepare(
    aligned: list[tuple[int, Chem.Mol, float, dict]],
    positions: list[str],
    table: SubstituentTable,
    plan: list[tuple[str, str, str]],
    skipped: list[HanschSkipped],
) -> tuple[list[_Prepared], list[tuple[str, str]]]:
    exemplars: dict[tuple[str, str], Chem.Mol] = {}
    prepared: list[_Prepared] = []
    unmatched: list[tuple[str, str]] = []
    seen_unmatched: set[tuple[str, str]] = set()
    for oid, _mol, activity, row in aligned:
        if not np.isfinite(activity):
            skipped.append(HanschSkipped(int(oid), SKIP_ACTIVITY))
            continue
        subs, labels, ok = _substituents_from_row(row, positions, exemplars)
        if not ok:
            skipped.append(HanschSkipped(int(oid), SKIP_INCOMPLETE))
            continue
        values, reason, missing = _score_row(subs, table, plan, positions)
        for pair in missing:
            if pair not in seen_unmatched:
                seen_unmatched.add(pair)
                unmatched.append(pair)
        if values is None:
            skipped.append(HanschSkipped(int(oid), reason))
            continue
        prepared.append(
            _Prepared(
                oid=int(oid),
                activity=float(activity),
                subs=subs,
                labels=labels,
                values=values,
            )
        )
    return prepared, unmatched


def _score_row(
    subs: dict[str, str],
    table: SubstituentTable,
    plan: list[tuple[str, str, str]],
    positions: list[str],
) -> tuple[dict[str, float] | None, str, list[tuple[str, str]]]:
    records: dict[str, SubstituentRecord | None] = {}
    missing: list[tuple[str, str]] = []
    for position in positions:
        key = subs[position]
        record = table.get(key)
        records[position] = record
        if record is None:
            missing.append((position, key))
    if missing:
        return None, SKIP_UNMATCHED, missing
    values: dict[str, float] = {}
    for name, kind, position in plan:
        record = records[position]
        if record is None:
            return None, SKIP_UNMATCHED, [(position, subs[position])]
        value = _constant_value(record, kind)
        if value is None:
            return None, f"missing substituent constant ({name}, {subs[position]})", []
        values[name] = value
    return values, "", []


def _constant_value(record: SubstituentRecord, kind: str) -> float | None:
    if kind == "pi2":
        pi = record.pi
        if pi is None:
            return None
        return float(pi) * float(pi)
    value = getattr(record, kind)
    if value is None:
        return None
    return float(value)


def _coefficients(names: list[str], kept: list[int], fit) -> tuple[HanschCoefficient, ...]:
    offset_of = {index: offset for offset, index in enumerate(kept)}
    out: list[HanschCoefficient] = []
    for index, name in enumerate(names):
        offset = offset_of.get(index)
        if offset is None:
            out.append(
                HanschCoefficient(
                    name=name,
                    coefficient=None,
                    std_error=None,
                    t_value=None,
                    p_value=None,
                    vif=None,
                    identifiable=False,
                )
            )
            continue
        out.append(
            HanschCoefficient(
                name=name,
                coefficient=fit.coefficients[offset],
                std_error=fit.coefficient_std_errors[offset],
                t_value=fit.coefficient_t[offset],
                p_value=fit.coefficient_p[offset],
                vif=fit.vif[offset] if offset < len(fit.vif) else None,
                identifiable=True,
            )
        )
    return tuple(out)


def _unused_sigma_positions(settings: HanschSettings, positions: list[str]) -> list[str]:
    if settings.electronic != ELECTRONIC_SIGMA:
        return []
    present = set(positions)
    return [position for position, _kind in settings.sigma_positions if position not in present]


def _check_cancel(cancel_event: Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise _Cancelled


def _report(progress: ProgressCallback | None, message: str, done: int, total: int) -> None:
    if progress is not None:
        progress(message, done, total)


def _result(settings: HanschSettings, **kwargs: object) -> HanschResult:
    payload: dict[str, object] = {
        "ok": False,
        "message": "",
        "cancelled": False,
        "activity_column": settings.activity_column,
        "equation": "",
        "n": 0,
        "n_parameters": 0,
        "r_squared": None,
        "adjusted_r_squared": None,
        "q_squared": None,
        "rmse": None,
        "residual_df": 0,
        "saturated": False,
        "intercept": 0.0,
        "intercept_std_error": None,
        "intercept_t": None,
        "intercept_p": None,
        "coefficients": (),
        "observed": (),
        "skipped": (),
        "unmatched": (),
        "positions": (),
    }
    payload.update(kwargs)
    return HanschResult(**payload)  # type: ignore[arg-type]
