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

"""Allowed bond-order sums for sketch atoms. No widget state."""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from .contracted_labels import contracted_max_bonds
from .rgroups import is_rgroup_node, rgroup_label_from_element
from .wildcards import _is_wildcard_node, _normalize_wildcard_elements

_RDKIT_VALENCE_ERRORS = (ValueError, RuntimeError)


def valence_list_for_element(element: str) -> list[int]:
    """RDKit allowed valences for *element* (ascending), or empty if unknown."""
    if rgroup_label_from_element(element) is not None:
        return []
    if element in ("H", "D", "T"):
        return [1]
    try:
        pt = Chem.GetPeriodicTable()
        an = pt.GetAtomicNumber(element)
        if an <= 0:
            return []
        return sorted({int(v) for v in pt.GetValenceList(an) if int(v) > 0})
    except _RDKIT_VALENCE_ERRORS:
        return []


def default_valence(element: str) -> int:
    """Common / lowest preferred valence (e.g. S=2), not the hypervalent maximum."""
    if rgroup_label_from_element(element) is not None:
        return 0
    if element in ("H", "D", "T"):
        return 1
    try:
        pt = Chem.GetPeriodicTable()
        an = pt.GetAtomicNumber(element)
        if an > 0:
            dv = pt.GetDefaultValence(an)
            if dv > 0:
                return int(dv)
    except _RDKIT_VALENCE_ERRORS:
        pass
    vlist = valence_list_for_element(element)
    if vlist:
        return min(vlist)
    if element in ("Na", "K", "Rb", "Cs", "Li"):
        return 1
    if element in ("Mg", "Ca", "Sr", "Ba"):
        return 2
    if element in ("Zn", "Cd", "Hg", "Cu", "Ag", "Au", "Ni", "Pd", "Pt", "Co"):
        return 4
    return 4


def max_valence(element: str) -> int:
    """Maximum allowed sum of incident bond orders.

    Uses RDKit's valence-list high end so sulfonamides / sulfones (S=6) and
    phosphates (P=5/7) are legal. Do not use this for implicit-H counts.
    """
    if rgroup_label_from_element(element) is not None:
        return 1
    if element in ("H", "D", "T"):
        return 1
    vlist = valence_list_for_element(element)
    if vlist:
        return max(vlist)
    try:
        pt = Chem.GetPeriodicTable()
        an = pt.GetAtomicNumber(element)
        if an > 0:
            dv = pt.GetDefaultValence(an)
            if dv > 0:
                return int(dv)
    except _RDKIT_VALENCE_ERRORS:
        pass
    if element in ("Na", "K", "Rb", "Cs", "Li"):
        return 1
    if element in ("Mg", "Ca", "Sr", "Ba"):
        return 2
    if element in ("Zn", "Cd", "Hg", "Cu", "Ag", "Au", "Ni", "Pd", "Pt", "Co"):
        return 4
    if element in ("P", "As"):
        return 5
    if element in ("S", "Se", "Te"):
        return 6
    return 8


def max_bond_order_sum(element: str, fc: int) -> int:
    """Allowed sum of bond orders before implicit H.

    Charge-aware so N+, O-, and quaternary ammonium do not trip validation.
    """
    if fc == 1:
        if element == "N":
            return 4
        if element == "O":
            return 3
        if element in ("S", "P"):
            return 5
    if fc == -1:
        if element == "O":
            return 1
        if element == "N":
            return 2
    base = max_valence(element)
    if fc > 0:
        return max(1, base - fc)
    if fc < 0:
        return max(1, base + fc)
    return base


def max_bond_order_sum_for_node(node: dict[str, Any], fc: int) -> int:
    ab_cap = contracted_max_bonds(node.get("abbrev"))
    if ab_cap is not None:
        return int(ab_cap)
    if is_rgroup_node(node):
        return 1
    if _is_wildcard_node(node):
        els = _normalize_wildcard_elements(node)
        return max(max_bond_order_sum(el, fc) for el in els)
    return max_bond_order_sum(node["element"], fc)


def target_valence_for_implicit_h(element: str, bond_sum: int, fc: int) -> int:
    """Valence used to estimate implicit H, condensed labels, and lone pairs.

    Chooses the smallest allowed valence at or above the current bond-order sum
    so divalent sulfur stays at 2, while sulfur with two S=O doubles targets 6.
    """
    need = max(0, int(bond_sum))
    if fc != 0 and element in ("N", "O", "S", "P"):
        if fc == 1 and element in ("N", "O", "S", "P"):
            return max(need, max_bond_order_sum(element, fc))
        if fc == -1 and element in ("O", "N"):
            return max(need, max_bond_order_sum(element, fc))
    vlist = valence_list_for_element(element)
    if not vlist:
        base = default_valence(element)
        if fc > 0:
            return max(need, base - fc)
        if fc < 0:
            return max(need, base - fc)
        return max(need, base)
    candidates = [v for v in vlist if v >= need]
    target = min(candidates) if candidates else max(vlist)
    if fc > 0:
        return max(need, target - fc)
    if fc < 0:
        return max(need, target - fc)
    return target
