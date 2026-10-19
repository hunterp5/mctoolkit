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

"""Convert assay concentrations to nM or uM and pActivity, with optional Cheng–Prusoff Ki."""

from __future__ import annotations

import math
from collections.abc import Sequence

from .si_units import (
    GRAMS_PER_LITER,
    MOL_PER_LITER,
    is_amount_concentration,
    is_mass_concentration,
    parse_measured_unit,
)

# Assay unit dropdown. Scales are mol/L per named unit; parsing lives in si_units.
CONCENTRATION_UNITS: tuple[tuple[str, float], ...] = (
    ("M", 1.0),
    ("mM", 1e-3),
    ("µM", 1e-6),
    ("nM", 1e-9),
    ("pM", 1e-12),
)

# Written columns use these labels. Source cells may use any concentration the SI parser accepts.
DESIRED_UNITS: tuple[str, ...] = ("nM", "uM")

_NAMED_MOLAR: tuple[tuple[float, str], ...] = (
    (1.0, "M"),
    (1e-3, "mM"),
    (1e-6, "µM"),
    (1e-9, "nM"),
    (1e-12, "pM"),
    (1e-15, "fM"),
)

MEASURES: tuple[str, ...] = ("IC50", "EC50", "Ki", "Kd")
PKI_HEADER = "pKi"
_CENSOR_PREFIXES = ("<", ">", "~", "≤", "≥")


def canonical_concentration_unit(text: str) -> str | None:
    """Map unit text to a concentration label, or ``None`` when it is not one.

    Amount concentrations use a short molar name when the scale matches
    (``nmol/L`` is ``nM``). Mass/volume units keep a normalized label such as
    ``mg/mL``. ``g/mol`` is a molar mass, not a concentration.
    """
    parsed = parse_measured_unit(text)
    if parsed is None:
        return None
    if is_amount_concentration(parsed):
        return _named_molar_label(parsed) or parsed.label
    if is_mass_concentration(parsed):
        return parsed.label
    return None


def needs_molecular_weight(unit: str | None) -> bool:
    """True when ``unit`` is mass/volume and conversion needs a g/mol value."""
    if not unit or not str(unit).strip():
        return False
    parsed = parse_measured_unit(unit)
    return parsed is not None and is_mass_concentration(parsed)


def _named_molar_label(parsed) -> str | None:
    factor = parsed.to_si / MOL_PER_LITER.to_si
    for scale, label in _NAMED_MOLAR:
        if math.isclose(factor, scale, rel_tol=1e-9, abs_tol=0.0):
            return label
    return None


def activity_header(measure: str, unit: str) -> str:
    """Column name for the activity expressed in ``unit``."""
    return f"{measure} ({unit})"


def p_header(measure: str) -> str:
    """Column name for −log10 of the molar activity."""
    return f"p{measure}"


def output_headers(
    measure: str,
    *,
    desired_unit: str,
    write_p: bool,
    write_ki: bool,
) -> list[str]:
    """Headers written for one standardization pass, in column order."""
    headers = [activity_header(measure, desired_unit)]
    if write_p:
        headers.append(p_header(measure))
    if write_ki:
        ki_header = activity_header("Ki", desired_unit)
        if ki_header not in headers:
            headers.append(ki_header)
        if write_p and PKI_HEADER not in headers:
            headers.append(PKI_HEADER)
    return headers


def parse_concentration(text: str, *, allow_zero: bool = False) -> float | None:
    """Positive concentration, or ``None`` when blank, censored, or not a number.

    A leading ``<``, ``>``, or ``~`` is left blank so a censored assay value is
    not treated as an exact potency. ``allow_zero`` accepts 0, which is a valid
    substrate concentration.
    """
    raw = (text or "").strip().replace(",", "")
    if not raw or raw[0] in _CENSOR_PREFIXES:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    if value < 0 or (value == 0 and not allow_zero):
        return None
    return value


def to_molar(value: float, unit: str, *, molar_mass: float | None = None) -> float:
    """Convert a concentration in ``unit`` to mol/L.

    Amount units (nM, mol/L, M) convert directly. Mass/volume units (mg/mL, g/L,
    kg/m^3) need ``molar_mass`` in g/mol: mol/L = (g/L) / (g/mol).
    """
    parsed = parse_measured_unit(unit)
    if parsed is None:
        raise ValueError(f"Unknown concentration unit {unit!r}.")
    if is_amount_concentration(parsed):
        return float(value) * (parsed.to_si / MOL_PER_LITER.to_si)
    if is_mass_concentration(parsed):
        if molar_mass is None or not math.isfinite(molar_mass) or molar_mass <= 0:
            raise ValueError("Mass/volume units require a molecular weight in g/mol.")
        grams_per_liter = float(value) * (parsed.to_si / GRAMS_PER_LITER.to_si)
        return grams_per_liter / float(molar_mass)
    raise ValueError(f"Unknown concentration unit {unit!r}.")


def from_molar(molar: float, unit: str) -> float:
    """Convert a mol/L value into an amount concentration such as nM or uM."""
    parsed = parse_measured_unit(unit)
    if parsed is None or not is_amount_concentration(parsed):
        raise ValueError(f"Unknown concentration unit {unit!r}.")
    factor = parsed.to_si / MOL_PER_LITER.to_si
    return float(molar) / factor


def p_activity(molar: float) -> float | None:
    """−log10(molar). ``None`` when the concentration is not positive."""
    if not math.isfinite(molar) or molar <= 0:
        return None
    return -math.log10(molar)


def cheng_prusoff_terms(
    ic50_molar: float,
    terms: Sequence[tuple[float, float]],
) -> float | None:
    """Ki = IC50 / (1 + Σ [C]/K) for competitive inhibition.

    Each term is ``(concentration_molar, reference_molar)`` where the reference
    is Km or Kd. An empty list cannot correct an IC50. A concentration of 0
    adds nothing. ``None`` when a reference is not positive or any input is
    not finite.
    """
    if not terms:
        return None
    if not math.isfinite(ic50_molar) or ic50_molar <= 0:
        return None
    correction = 0.0
    for concentration, reference in terms:
        if not math.isfinite(concentration) or not math.isfinite(reference):
            return None
        if concentration < 0 or reference <= 0:
            return None
        correction += concentration / reference
    return ic50_molar / (1.0 + correction)


def cheng_prusoff_ki(ic50_molar: float, substrate_molar: float, km_molar: float) -> float | None:
    """Ki = IC50 / (1 + [S]/Km) for one competitive substrate."""
    return cheng_prusoff_terms(ic50_molar, ((substrate_molar, km_molar),))


def format_concentration(value: float) -> str:
    """Compact concentration text."""
    return f"{value:.6g}"


def format_p(value: float) -> str:
    """pActivity to three decimal places."""
    return f"{value:.3f}"


def standardize_activity(
    activity_text: str,
    *,
    unit: str | None,
    measure: str,
    desired_unit: str,
    write_p: bool,
    write_ki: bool = False,
    assay_terms: Sequence[tuple[float, float]] | None = None,
    molar_mass: float | None = None,
) -> dict[str, str]:
    """Cell text for one row. Missing, censored, or unrecognized input writes blanks.

    ``assay_terms`` are molar ``(concentration, Km or Kd)`` pairs. Cheng–Prusoff
    leaves Ki blank when a pair is missing. pActivity is −log10 of the molar value.
    ``molar_mass`` is g/mol and is used only for mass/volume source units.
    """
    out: dict[str, str] = {}
    activity = parse_concentration(activity_text)
    molar = None
    if activity is not None and unit and str(unit).strip():
        try:
            molar = to_molar(activity, unit, molar_mass=molar_mass)
        except ValueError:
            molar = None
    converted = None if molar is None else from_molar(molar, desired_unit)
    out[activity_header(measure, desired_unit)] = (
        "" if converted is None else format_concentration(converted)
    )
    if write_p:
        p_value = p_activity(molar) if molar is not None else None
        out[p_header(measure)] = "" if p_value is None else format_p(p_value)
    if write_ki:
        ki = None
        if molar is not None and assay_terms:
            ki = cheng_prusoff_terms(molar, assay_terms)
        ki_header = activity_header("Ki", desired_unit)
        if ki_header not in out:
            ki_value = None if ki is None else from_molar(ki, desired_unit)
            out[ki_header] = "" if ki_value is None else format_concentration(ki_value)
        if write_p and PKI_HEADER not in out:
            p_ki = p_activity(ki) if ki is not None else None
            out[PKI_HEADER] = "" if p_ki is None else format_p(p_ki)
    return out
