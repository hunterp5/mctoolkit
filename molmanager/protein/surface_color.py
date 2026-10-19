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

"""Pocket-surface colors for hydrophobicity and qualitative charge."""

from __future__ import annotations

# Kyte & Doolittle, J. Mol. Biol. 157:105 (1982). Positive is hydrophobic.
KYTE_DOOLITTLE: dict[str, float] = {
    "ILE": 4.5,
    "VAL": 4.2,
    "LEU": 3.8,
    "PHE": 2.8,
    "CYS": 2.5,
    "MET": 1.9,
    "ALA": 1.8,
    "GLY": -0.4,
    "THR": -0.7,
    "SER": -0.8,
    "TRP": -0.9,
    "TYR": -1.3,
    "PRO": -1.6,
    "HIS": -3.2,
    "GLU": -3.5,
    "GLN": -3.5,
    "ASP": -3.5,
    "ASN": -3.5,
    "LYS": -3.9,
    "ARG": -4.5,
}

_RESN_ALIASES = {
    "HID": "HIS",
    "HIE": "HIS",
    "HIP": "HIS",
    "HSD": "HIS",
    "HSE": "HIS",
    "HSP": "HIS",
    "ASH": "ASP",
    "GLH": "GLU",
    "CYX": "CYS",
    "CYM": "CYS",
    "MSE": "MET",
    "SEP": "SER",
    "TPO": "THR",
    "PTR": "TYR",
    "LYN": "LYS",
    "HYP": "PRO",
}

HYDROPHILIC_COLOR = "#2c7bb6"
NEUTRAL_COLOR = "#f7f7f7"
HYDROPHOBIC_COLOR = "#d95f0e"
HYDROPHILIC_MIN = -4.5
HYDROPHOBIC_MAX = 4.5


def hydrophobicity_value(resn: str) -> float | None:
    """Kyte–Doolittle score for a residue name, or None when the name is unknown."""
    key = (resn or "").strip().upper()
    key = _RESN_ALIASES.get(key, key)
    if key not in KYTE_DOOLITTLE:
        return None
    return KYTE_DOOLITTLE[key]


def hydrophobicity_color(resn: str) -> str:
    """Blue (hydrophilic) through white to orange (hydrophobic). Unknown names stay white."""
    value = hydrophobicity_value(resn)
    if value is None:
        return NEUTRAL_COLOR
    span = HYDROPHOBIC_MAX - HYDROPHILIC_MIN
    if span <= 0:
        return NEUTRAL_COLOR
    placed = (float(value) - HYDROPHILIC_MIN) / span
    if placed <= 0.5:
        return _lerp_hex(HYDROPHILIC_COLOR, NEUTRAL_COLOR, placed / 0.5)
    return _lerp_hex(NEUTRAL_COLOR, HYDROPHOBIC_COLOR, (placed - 0.5) / 0.5)


def hydrophobicity_residue_colors() -> dict[str, str]:
    """Hex color for every residue name the hydrophobicity surface knows."""
    names = set(KYTE_DOOLITTLE) | set(_RESN_ALIASES)
    return {name: hydrophobicity_color(name) for name in sorted(names)}


def _lerp_hex(start: str, end: str, fraction: float) -> str:
    placed = min(1.0, max(0.0, float(fraction)))
    channels = []
    for index in range(3):
        left = int(start[1 + index * 2 : 3 + index * 2], 16)
        right = int(end[1 + index * 2 : 3 + index * 2], 16)
        channels.append(int(round(left + (right - left) * placed)))
    return "#" + "".join(f"{channel:02x}" for channel in channels)
