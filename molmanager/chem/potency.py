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

"""Convert assay concentrations to molar and pActivity, with optional Cheng–Prusoff Ki."""

from __future__ import annotations

import math

# Factor converts a value in that unit into mol/L.
CONCENTRATION_UNITS: tuple[tuple[str, float], ...] = (
    ("M", 1.0),
    ("mM", 1e-3),
    ("µM", 1e-6),
    ("nM", 1e-9),
    ("pM", 1e-12),
)
_UNIT_FACTORS: dict[str, float] = {name: factor for name, factor in CONCENTRATION_UNITS}
_UNIT_FACTORS["uM"] = 1e-6

MEASURES: tuple[str, ...] = ("IC50", "EC50", "Ki", "Kd")
KI_MOLAR_HEADER = "Ki (M)"
PKI_HEADER = "pKi"
_CENSOR_PREFIXES = ("<", ">", "~", "≤", "≥")


def molar_header(measure: str) -> str:
    """Column name for the activity expressed in mol/L."""
    return f"{measure} (M)"


def p_header(measure: str) -> str:
    """Column name for −log10 of the molar activity."""
    return f"p{measure}"


def output_headers(
    measure: str,
    *,
    write_molar: bool,
    write_p: bool,
    write_ki: bool,
) -> list[str]:
    """Headers written for one standardization pass, in column order."""
    headers: list[str] = []
    if write_molar:
        headers.append(molar_header(measure))
    if write_p:
        headers.append(p_header(measure))
    if write_ki:
        headers.append(KI_MOLAR_HEADER)
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


def to_molar(value: float, unit: str) -> float:
    """Convert ``value`` in ``unit`` to mol/L."""
    try:
        factor = _UNIT_FACTORS[unit]
    except KeyError as exc:
        raise ValueError(f"Unknown concentration unit {unit!r}.") from exc
    return float(value) * factor


def p_activity(molar: float) -> float | None:
    """−log10(molar). ``None`` when the concentration is not positive."""
    if not math.isfinite(molar) or molar <= 0:
        return None
    return -math.log10(molar)


def cheng_prusoff_ki(ic50_molar: float, substrate_molar: float, km_molar: float) -> float | None:
    """Ki = IC50 / (1 + [S]/Km) for competitive inhibition.

    ``None`` when Km is not positive or any input is not finite. A substrate
    concentration of 0 returns the IC50 unchanged.
    """
    if not all(math.isfinite(x) for x in (ic50_molar, substrate_molar, km_molar)):
        return None
    if ic50_molar <= 0 or km_molar <= 0 or substrate_molar < 0:
        return None
    return ic50_molar / (1.0 + substrate_molar / km_molar)


def format_molar(molar: float) -> str:
    """Compact mol/L text."""
    return f"{molar:.6g}"


def format_p(value: float) -> str:
    """pActivity to three decimal places."""
    return f"{value:.3f}"


def standardize_activity(
    activity_text: str,
    *,
    unit: str,
    measure: str,
    write_molar: bool,
    write_p: bool,
    write_ki: bool = False,
    substrate_molar: float | None = None,
    km_molar: float | None = None,
) -> dict[str, str]:
    """Cell text for one row. Missing or censored input writes blank cells."""
    out: dict[str, str] = {}
    activity = parse_concentration(activity_text)
    molar = to_molar(activity, unit) if activity is not None else None
    if write_molar:
        out[molar_header(measure)] = "" if molar is None else format_molar(molar)
    if write_p:
        p_value = p_activity(molar) if molar is not None else None
        out[p_header(measure)] = "" if p_value is None else format_p(p_value)
    if write_ki:
        ki = None
        if molar is not None and substrate_molar is not None and km_molar is not None:
            ki = cheng_prusoff_ki(molar, substrate_molar, km_molar)
        p_ki = p_activity(ki) if ki is not None else None
        out[KI_MOLAR_HEADER] = "" if ki is None else format_molar(ki)
        out[PKI_HEADER] = "" if p_ki is None else format_p(p_ki)
    return out
