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

"""IUPAC graphical representation constants and helpers for the sketcher.

Maps selected recommendations from IUPAC Recommendations 2008 (GR-*) and
stereochemical configuration 2006 (ST-*) into concrete sketch geometry and paint params.
See ``docs/IUPAC_DRAWING.md``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .constants import SKETCH_MEDIAN_BOND_PX

if TYPE_CHECKING:
    from PyQt5.QtGui import QFont

# Preferred bond angles (radians). IUPAC treats listed degree values as ≈±10°.
ANGLE_LINEAR_DEG = 180.0
ANGLE_TRIGONAL_DEG = 120.0
ANGLE_TETRAHEDRAL_DEG = 109.47
ANGLE_TOLERANCE_DEG = 10.0

ANGLE_LINEAR = math.radians(ANGLE_LINEAR_DEG)
ANGLE_TRIGONAL = math.radians(ANGLE_TRIGONAL_DEG)
ANGLE_TETRAHEDRAL = math.radians(ANGLE_TETRAHEDRAL_DEG)
ANGLE_TOLERANCE = math.radians(ANGLE_TOLERANCE_DEG)

# Snap targets for interactive placement (extension from an existing bond).
# Deviation from collinear (π): 0 → 180°, 60 → 120°, ~70.5 → 109.5°.
SNAP_EXTENSION_DEVIATIONS_DEG = (
    0.0,  # collinear / 180° (alkyne, allene)
    60.0,  # → 120° bond angle
    180.0 - ANGLE_TETRAHEDRAL_DEG,  # → ~109.5°
)

# Bond length outliers relative to median (validation).
# Bridges / congested polycycles may legitimately deviate more (GR-1.1 exceptions).
BOND_LENGTH_MIN_FRAC = 0.55
BOND_LENGTH_MAX_FRAC = 1.55

# Near-collinear bend that looks like one bond (degrees from 180).
NEAR_COLLINEAR_DEG = 12.0

# Atom overlap (px) for validation.
ATOM_OVERLAP_PX = 8.0


@dataclass(frozen=True)
class IupacSketchStyle:
    """Pixel drawing parameters aligned with ACS1996 proportions and IUPAC clarity rules."""

    median_bond_px: float
    bond_width_px: float
    double_bond_offset_px: float
    triple_bond_offset_px: float
    label_font_pt: int
    charge_font_pt: int
    wedge_half_width_px: float
    hash_bar_count: int
    ink: tuple[int, int, int]
    selection_pen_width: float
    hover_pen_width: float
    atom_selection_radius_extra: float
    bond_selection_extra_width: float


def iupac_sketch_style(median_bond_px: float = SKETCH_MEDIAN_BOND_PX) -> IupacSketchStyle:
    """
    Derive canvas style from RDKit ACS1996 metrics scaled to the sketch median bond.

    Multi-bond offset ≈ 1/6 of bond length (within GR-1 preferred range).
    Bond width tracks atom-label stroke thickness (GR-1.2).
    """
    from .acs_style import acs_sketch_style
    from .iupac_rings import hash_bar_count_for_style

    base = acs_sketch_style(median_bond_px)
    med = base.median_bond_px
    # Prefer ~1/6 bond length for double-bond separation when ACS scale is thin.
    dbl = max(base.double_bond_offset_px, med / 6.0)
    # GR-1.2: bond ≈ capital-H stroke of the structure font (not ≪ or ≫ that stroke).
    font = iupac_structure_font(base.label_font_pt)
    stroke = max(1.0, base.label_font_pt * 0.15)
    try:
        from PyQt5.QtGui import QFontMetrics
        from PyQt5.QtWidgets import QApplication

        if QApplication.instance() is not None:
            fm = QFontMetrics(font)
            # Approximate capital-H stroke from em height (Qt has no portable strokeWidth API).
            stroke = max(1.0, float(fm.height()) * 0.12)
    except Exception:
        pass
    # Keep near ACS weight but clamp to [0.25×, 4×] label stroke; prefer ≈ stroke.
    bond_w = max(0.25 * stroke, min(4.0 * stroke, max(base.bond_width_px, stroke * 0.95)))
    return IupacSketchStyle(
        median_bond_px=med,
        bond_width_px=bond_w,
        double_bond_offset_px=dbl,
        triple_bond_offset_px=max(base.triple_bond_offset_px, dbl * 1.55),
        label_font_pt=base.label_font_pt,
        charge_font_pt=base.charge_font_pt,
        wedge_half_width_px=base.wedge_half_width_px,
        hash_bar_count=hash_bar_count_for_style(bond_width_px=bond_w, bond_length_px=med),
        ink=base.ink,
        selection_pen_width=base.selection_pen_width,
        hover_pen_width=base.hover_pen_width,
        atom_selection_radius_extra=base.atom_selection_radius_extra,
        bond_selection_extra_width=base.bond_selection_extra_width,
    )


def snap_extension_angle(
    raw_angle: float,
    neighbor_angles: list[float],
    *,
    prefer_linear: bool = False,
    prefer_trigonal: bool = False,
) -> float:
    """
    Snap a proposed bond direction to an IUPAC-preferred angle relative to neighbors.

    When ``prefer_linear``, use 180° (triple bonds / allenes).
    When ``prefer_trigonal``, prefer 120°.
    """
    if not neighbor_angles:
        return raw_angle
    if len(neighbor_angles) == 1:
        base = neighbor_angles[0]
        if prefer_linear:
            return (base + math.pi) % (2.0 * math.pi)
        cands: list[float] = []
        devs: tuple[float, ...] = SNAP_EXTENSION_DEVIATIONS_DEG
        if prefer_trigonal:
            devs = (60.0, 180.0 - ANGLE_TETRAHEDRAL_DEG, 0.0)
        for dev_deg in devs:
            dev = math.radians(dev_deg)
            for sign in (1.0, -1.0):
                cands.append((base + math.pi - sign * dev) % (2.0 * math.pi))
        best = cands[0]
        best_d = abs(((raw_angle - best + math.pi) % (2.0 * math.pi)) - math.pi)
        for c in cands[1:]:
            d = abs(((raw_angle - c + math.pi) % (2.0 * math.pi)) - math.pi)
            if d < best_d:
                best, best_d = c, d
        return best
    return raw_angle


def angle_near(a: float, b: float, tol: float = ANGLE_TOLERANCE) -> bool:
    d = abs(((a - b + math.pi) % (2.0 * math.pi)) - math.pi)
    return d <= tol


def condensed_heteroatom_label(element: str, implicit_h: int) -> str | None:
    """
    Build a condensed atom label with terminal hydrogens (GR-2), e.g. OH, NH2, SH.

    Returns None when no condensed H should be shown (use bare element symbol).
    """
    el = str(element or "")
    if not el or el in ("C", "H", "D", "T", "*", "R1", "R2"):
        return None
    n = int(implicit_h)
    if n <= 0:
        return None
    # Prefer element-then-H for O/S/Se/Te (OH) and H-count for N/P (NH2).
    if el in ("O", "S", "Se", "Te"):
        if n == 1:
            return f"{el}H"
        return f"{el}H{n}"
    if el in ("N", "P", "As"):
        if n == 1:
            return f"{el}H"
        return f"{el}H{n}"
    if el in ("F", "Cl", "Br", "I"):
        return None
    if n == 1:
        return f"{el}H"
    return f"{el}H{n}"


def explicit_carbon_label(implicit_h: int) -> str:
    """Condensed carbon label for Explicit Carbon (GR-2): C, CH, CH2, CH3, …"""
    n = max(0, int(implicit_h))
    if n <= 0:
        return "C"
    if n == 1:
        return "CH"
    return f"CH{n}"


def iupac_ring_vertex_offset(n_atoms: int) -> float:
    """
    Starting angle (radians) for a regular *n*-gon so ring orientation matches GR-3.4.2.

    - 6-membered: vertical bond on the left (flat-top hexagon).
    - 3–5, 7–8: horizontal bond along the bottom.
    """
    n = max(3, int(n_atoms))
    if n == 6:
        # Edge midpoint at π (left) → vertical left bond.
        return math.pi * (1.0 - 1.0 / n)
    # Edge midpoint at −π/2 (bottom) → horizontal bottom bond.
    return -0.5 * math.pi - math.pi / n


# Preferred structure fonts (IUPAC GR-0): plain roman / sans; Helvetica & Arial cited.
IUPAC_LABEL_FONT_FAMILIES = ("Helvetica", "Arial", "DejaVu Sans", "Sans Serif")


def iupac_structure_font(
    point_size: int,
    *,
    italic: bool = False,
    weight: int | None = None,
) -> QFont:
    """
    Font for atom labels and diagram annotations (GR-0).

    Plain (roman) sans-serif; annotations may use italic. Avoid heavy black weights
    for routine atom labels.
    """
    from PyQt5.QtGui import QFont

    pt = max(5, int(point_size))
    font = QFont(IUPAC_LABEL_FONT_FAMILIES[0], pt)
    if hasattr(font, "setFamilies"):
        font.setFamilies(list(IUPAC_LABEL_FONT_FAMILIES))
    font.setStyleHint(QFont.SansSerif)
    font.setItalic(bool(italic))
    if weight is None:
        font.setWeight(QFont.Normal)
    else:
        font.setWeight(int(weight))
    return font
