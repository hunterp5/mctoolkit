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

"""SI unit dictionary: prefixes, base units, and compound-unit conversion.

``parse_unit`` is strict. ``nm`` is a nanometer and ``nM`` is nanomolar.
``parse_measured_unit`` is the assay reading of the same dictionary: short
forms such as ``nm``, ``uM``, and ``mm`` are molar concentrations, which is
how potency tables label them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (symbol or word, scale applied to the base unit, label used in output)
_PREFIXES: tuple[tuple[str, float, str], ...] = (
    ("yotta", 1e24, "Y"),
    ("zetta", 1e21, "Z"),
    ("exa", 1e18, "E"),
    ("peta", 1e15, "P"),
    ("tera", 1e12, "T"),
    ("giga", 1e9, "G"),
    ("mega", 1e6, "M"),
    ("kilo", 1e3, "k"),
    ("hecto", 1e2, "h"),
    ("deka", 1e1, "da"),
    ("deca", 1e1, "da"),
    ("deci", 1e-1, "d"),
    ("centi", 1e-2, "c"),
    ("milli", 1e-3, "m"),
    ("micro", 1e-6, "µ"),
    ("nano", 1e-9, "n"),
    ("pico", 1e-12, "p"),
    ("femto", 1e-15, "f"),
    ("atto", 1e-18, "a"),
    ("zepto", 1e-21, "z"),
    ("yocto", 1e-24, "y"),
    ("da", 1e1, "da"),
    ("Y", 1e24, "Y"),
    ("Z", 1e21, "Z"),
    ("E", 1e18, "E"),
    ("P", 1e15, "P"),
    ("T", 1e12, "T"),
    ("G", 1e9, "G"),
    ("M", 1e6, "M"),
    ("k", 1e3, "k"),
    ("h", 1e2, "h"),
    ("d", 1e-1, "d"),
    ("c", 1e-2, "c"),
    ("m", 1e-3, "m"),
    ("u", 1e-6, "µ"),
    ("n", 1e-9, "n"),
    ("p", 1e-12, "p"),
    ("f", 1e-15, "f"),
    ("a", 1e-18, "a"),
    ("z", 1e-21, "z"),
    ("y", 1e-24, "y"),
)

# Display symbol, dimension (mass / length / amount), scale to SI (kg, m, mol), match names.
_BASES: tuple[tuple[str, tuple[tuple[str, int], ...], float, tuple[str, ...]], ...] = (
    ("mol", (("amount", 1),), 1.0, ("mol", "mole", "moles")),
    ("g", (("mass", 1),), 1e-3, ("gram", "grams", "g")),
    ("L", (("length", 3),), 1e-3, ("liter", "litre", "liters", "litres", "L", "l")),
    ("m", (("length", 1),), 1.0, ("meter", "metre", "meters", "metres", "m")),
    ("M", (("amount", 1), ("length", -3)), 1e3, ("molar", "M")),
)

# Whole-string assay readings. Keys are casefolded after micro signs fold to ``u``.
_MEASURED_ALIASES: dict[str, str] = {
    "m": "M",
    "nm": "nM",
    "um": "uM",
    "mm": "mM",
    "pm": "pM",
    "fm": "fM",
}

_AMOUNT = "amount"
_LENGTH = "length"
_MASS = "mass"
_FACTOR_RE = re.compile(r"^([A-Za-z]+)(?:\^(-?\d+)|(-?\d+))?$")
_NAME_MATCHES: tuple[tuple[str, str, tuple[tuple[str, int], ...], float], ...] = tuple(
    sorted(
        (
            (name, symbol, dimension, to_si)
            for symbol, dimension, to_si, names in _BASES
            for name in names
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
)


@dataclass(frozen=True)
class ParsedUnit:
    """One compound unit. ``to_si`` converts a value into kg, m, and mol."""

    dimension: tuple[tuple[str, int], ...]
    to_si: float
    label: str


class _Builder:
    def __init__(self) -> None:
        self.dimension: dict[str, int] = {}
        self.components: dict[str, int] = {}
        self.to_si: float = 1.0

    def freeze(self) -> ParsedUnit:
        return ParsedUnit(
            dimension=_dimension_key(self.dimension),
            to_si=self.to_si,
            label=_format_label(self.components),
        )


def parse_unit(text: str) -> ParsedUnit | None:
    """Parse a strict SI unit. ``None`` when the text is blank or not a unit.

    The prefix binds to the unit it precedes, and an exponent applies to that
    prefixed unit, so ``cm^3`` is a milliliter and not a hundredth of a cubic meter.
    """
    raw = _normalize(text)
    if not raw or "/" not in raw and not re.search(r"[A-Za-z]", raw):
        return None
    parts = [part.strip() for part in raw.split("/")]
    if any(not part for part in parts):
        return None
    built = _parse_product(parts[0])
    if built is None:
        return None
    for part in parts[1:]:
        denominator = _parse_product(part)
        if denominator is None:
            return None
        _invert(denominator)
        _multiply(built, denominator)
    if not built.dimension:
        return None
    return built.freeze()


def parse_measured_unit(text: str) -> ParsedUnit | None:
    """Parse a unit as it appears in an assay table.

    Short molar forms (``nm``, ``uM``, ``mm``) win over the length reading
    (nanometer, millimeter). Other text uses :func:`parse_unit`, then a
    case-insensitive retry so ``MG/ML`` still parses as a mass concentration.
    """
    raw = _normalize(text)
    if not raw:
        return None
    alias = _MEASURED_ALIASES.get(raw.replace(" ", "").casefold())
    if alias is not None:
        return parse_unit(alias)
    parsed = parse_unit(raw)
    if parsed is not None:
        return parsed
    folded = raw.casefold()
    if folded == raw:
        return None
    parsed = parse_unit(folded)
    if parsed is not None and (is_mass_concentration(parsed) or is_amount_concentration(parsed)):
        return parsed
    return None


def convert(value: float, source: str, target: str) -> float:
    """Convert ``value`` between two units of the same dimension."""
    src = parse_unit(source)
    dst = parse_unit(target)
    if src is None or dst is None or src.dimension != dst.dimension:
        raise ValueError(f"Cannot convert {source!r} to {target!r}.")
    return float(value) * src.to_si / dst.to_si


def is_amount_concentration(unit: ParsedUnit) -> bool:
    """True for mol/volume, including molar shorthand such as nM."""
    return unit.dimension == ((_AMOUNT, 1), (_LENGTH, -3))


def is_mass_concentration(unit: ParsedUnit) -> bool:
    """True for mass/volume, such as g/mL, mg/L, or kg/m^3."""
    return unit.dimension == ((_LENGTH, -3), (_MASS, 1))


def is_molar_mass(unit: ParsedUnit) -> bool:
    """True for mass/amount, such as g/mol."""
    return unit.dimension == ((_AMOUNT, -1), (_MASS, 1))


def _normalize(text: str) -> str:
    raw = (text or "").strip()
    if len(raw) >= 2 and raw[0] == "(" and raw[-1] == ")":
        raw = raw[1:-1].strip()
    raw = (
        raw.replace("μ", "u")
        .replace("µ", "u")
        .replace("·", " ")
        .replace("×", " ")
        .replace("*", " ")
        .replace("−", "-")
        .replace("–", "-")
        .replace("⁻", "-")
        .replace("²", "^2")
        .replace("³", "^3")
        .replace("¹", "^1")
    )
    raw = re.sub(r"\s+per\s+", "/", raw, flags=re.IGNORECASE)
    return " ".join(raw.split())


def _parse_product(text: str) -> _Builder | None:
    tokens = [token for token in re.split(r"[.\s]+", text.strip()) if token]
    if not tokens:
        return None
    built = _Builder()
    for token in tokens:
        factor = _parse_factor(token)
        if factor is None:
            return None
        _multiply(built, factor)
    return built


def _parse_factor(token: str) -> _Builder | None:
    match = _FACTOR_RE.fullmatch(token)
    if match is None:
        return None
    word = match.group(1)
    exponent_text = match.group(2) if match.group(2) is not None else match.group(3)
    exponent = int(exponent_text) if exponent_text is not None else 1
    if exponent == 0 or abs(exponent) > 9:
        return None
    built = _lookup_prefixed(word)
    if built is None:
        return None
    _power(built, exponent)
    return built


def _lookup_prefixed(word: str) -> _Builder | None:
    for name, symbol, dimension, to_si in _NAME_MATCHES:
        if len(name) == 1:
            if not word.endswith(name):
                continue
            rest = word[:-1]
        elif not word.casefold().endswith(name.casefold()):
            continue
        else:
            rest = word[: -len(name)]
        prefix = _match_prefix(rest)
        if prefix is None:
            continue
        scale, prefix_label = prefix
        built = _Builder()
        for axis, exponent in dimension:
            built.dimension[axis] = exponent
        built.to_si = to_si * scale
        built.components[f"{prefix_label}{symbol}"] = 1
        return built
    return None


def _match_prefix(rest: str) -> tuple[float, str] | None:
    if not rest:
        return 1.0, ""
    if len(rest) <= 2:
        for key, scale, label in _PREFIXES:
            if key == rest:
                return scale, label
        return None
    folded = rest.casefold()
    for key, scale, label in _PREFIXES:
        if len(key) > 2 and key.casefold() == folded:
            return scale, label
    return None


def _power(built: _Builder, exponent: int) -> None:
    if exponent == 1:
        return
    built.dimension = {axis: power * exponent for axis, power in built.dimension.items()}
    built.components = {label: power * exponent for label, power in built.components.items()}
    built.to_si = built.to_si**exponent


def _invert(built: _Builder) -> None:
    _power(built, -1)


def _multiply(total: _Builder, factor: _Builder) -> None:
    for axis, exponent in factor.dimension.items():
        total.dimension[axis] = total.dimension.get(axis, 0) + exponent
        if total.dimension[axis] == 0:
            del total.dimension[axis]
    for label, exponent in factor.components.items():
        total.components[label] = total.components.get(label, 0) + exponent
        if total.components[label] == 0:
            del total.components[label]
    total.to_si *= factor.to_si


def _dimension_key(dimension: dict[str, int]) -> tuple[tuple[str, int], ...]:
    return tuple(sorted((axis, exponent) for axis, exponent in dimension.items() if exponent))


def _format_label(components: dict[str, int]) -> str:
    numerator: list[str] = []
    denominator: list[str] = []
    for label, exponent in components.items():
        if exponent > 1:
            numerator.append(f"{label}^{exponent}")
        elif exponent == 1:
            numerator.append(label)
        elif exponent == -1:
            denominator.append(label)
        elif exponent < -1:
            denominator.append(f"{label}^{-exponent}")
    left = "·".join(numerator) if numerator else "1"
    if not denominator:
        return left
    return f"{left}/{'·'.join(denominator)}"


def _required(text: str) -> ParsedUnit:
    parsed = parse_unit(text)
    if parsed is None:
        raise RuntimeError(f"Built-in unit {text!r} did not parse.")
    return parsed


MOL_PER_LITER = _required("mol/L")
GRAMS_PER_LITER = _required("g/L")
