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

"""RDKit helpers for sketch export and atom parsing."""

from __future__ import annotations

from typing import Any

from rdkit import Chem

from .constants import DEFAULT_WILDCARD_ELEMENTS, ELEMENT_UPPER_MAP, WILDCARD_ELEMENT
from .rgroups import RGROUP_MAX, rgroup_element, rgroup_label_from_element
from .wildcards import (
    _is_wildcard_node,
    _normalize_wildcard_elements,
    _wildcard_query_smarts,
)


def _sanitize_mol_for_smiles(mol: Chem.Mol) -> bool:
    """Try full sanitization; fall back to looser steps so charged / sketch edge cases can export."""
    try:
        Chem.SanitizeMol(mol)
        return True
    except Exception:
        pass
    try:
        mol.UpdatePropertyCache(strict=False)
        Chem.SanitizeMol(mol, sanitizeOps=Chem.SanitizeFlags.SANITIZE_PROPERTIES)
        return True
    except Exception:
        pass
    try:
        mol.UpdatePropertyCache(strict=False)
        return True
    except Exception:
        return False


def _rdkit_atom_from_sketch_node(node: dict[str, Any], formal_charge: int = 0) -> Chem.Atom:
    """
    Build an RDKit atom for SMILES/SMARTS export from a sketcher node.

    Handles wildcards (element-list SMARTS + charge), R1/R2 attachment points,
    deuterium/tritium isotopes, and normal elements with formal charge.
    """
    fc = int(formal_charge)
    if _is_wildcard_node(node):
        sm = _wildcard_query_smarts(_normalize_wildcard_elements(node), formal_charge=fc)
        try:
            a = Chem.AtomFromSmarts(sm)
        except Exception:
            a = Chem.AtomFromSmarts(
                _wildcard_query_smarts(list(DEFAULT_WILDCARD_ELEMENTS), formal_charge=fc)
            )
        if a is None:
            a = Chem.Atom(0)
            if fc:
                a.SetFormalCharge(fc)
        return a

    el = str(node.get("element") or "C")
    r_label = rgroup_label_from_element(el)
    if r_label is not None:
        atom = Chem.Atom(0)
        atom.SetAtomMapNum(r_label)
        atom.SetNoImplicit(True)
        if fc:
            atom.SetFormalCharge(fc)
        return atom
    if el == "D":
        a = Chem.Atom(1)
        a.SetIsotope(2)
    elif el == "T":
        a = Chem.Atom(1)
        a.SetIsotope(3)
    else:
        a = Chem.Atom(el)
    if fc:
        a.SetFormalCharge(fc)
    return a


def _sketch_element_from_rdkit_atom(atom: Chem.Atom) -> str:
    """Map an RDKit atom back to a sketcher element symbol (D/T for hydrogen isotopes)."""
    if atom.GetAtomicNum() == 0:
        label = int(atom.GetAtomMapNum() or 0) or int(atom.GetIsotope() or 0)
        mapped = rgroup_element(label) if 1 <= label <= RGROUP_MAX else None
        if mapped:
            return mapped
        return atom.GetSymbol() or "*"
    if atom.GetAtomicNum() == 1:
        iso = int(atom.GetIsotope())
        if iso == 2:
            return "D"
        if iso == 3:
            return "T"
        return "H"
    return atom.GetSymbol()


def _parse_atom_symbol_input(raw: str) -> tuple[str, list[str] | None] | None:
    """
    Parse user text from Edit Atom: element symbol or wildcard.
    Returns (element, wildcard_els_or_None) or None if invalid.
    """
    s = (raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if s == "*" or low in ("wildcard", "wild"):
        return (WILDCARD_ELEMENT, None)
    r_label = rgroup_label_from_element(s)
    if r_label is not None:
        return (rgroup_element(r_label), None)
    sym = _parse_periodic_element_symbol(s)
    if sym is None:
        return None
    return (sym, None)


def _parse_periodic_element_symbol(raw: str) -> str | None:
    """
    Parse a single periodic-table element symbol (not wildcard).
    Accepts any RDKit-valid element (e.g. Au, Ru, Se), not only the toolbar subset.
    """
    s = (raw or "").strip()
    if not s or s in ("*", "?"):
        return None
    u = s.upper().replace(" ", "")
    sym = ELEMENT_UPPER_MAP.get(u)
    if sym is None:
        if len(u) == 1:
            sym = u
        elif len(u) == 2:
            sym = u[0] + u[1].lower()
        else:
            return None
    try:
        if Chem.GetPeriodicTable().GetAtomicNumber(sym) <= 0:
            return None
    except Exception:
        return None
    return sym


def sketch_lone_pair_count(
    element: str,
    *,
    formal_charge: int = 0,
    bond_order_sum: int = 0,
    implicit_h: int = 0,
) -> int:
    """
    Approximate Lewis lone-pair count for sketcher display.

    Uses ``floor((V - charge - effective_bonds) / 2)`` where effective bonds include
    sketched bond-order sum plus estimated implicit hydrogens. Returns 0 for H isotopes,
    wildcards, and metals without a positive default valence.
    """
    el = str(element or "")
    if not el or el == WILDCARD_ELEMENT or el in ("H", "D", "T"):
        return 0
    try:
        pt = Chem.GetPeriodicTable()
        an = int(pt.GetAtomicNumber(el))
        if an <= 0:
            return 0
        valence_e = int(pt.GetNOuterElecs(an))
        default_v = int(pt.GetDefaultValence(an))
    except Exception:
        return 0
    if valence_e <= 0 or default_v <= 0:
        return 0
    effective = max(0, int(bond_order_sum) + max(0, int(implicit_h)))
    unpaired = valence_e - int(formal_charge) - effective
    if unpaired < 2:
        return 0
    return min(4, unpaired // 2)


# Approximate Pauling electronegativities for oxidation-state assignment (GR-style display).
_ELEMENT_EN: dict[str, float] = {
    "H": 2.20,
    "D": 2.20,
    "T": 2.20,
    "B": 2.04,
    "C": 2.55,
    "N": 3.04,
    "O": 3.44,
    "F": 3.98,
    "Si": 1.90,
    "P": 2.19,
    "S": 2.58,
    "Cl": 3.16,
    "Br": 2.96,
    "I": 2.66,
    "Se": 2.55,
    "As": 2.18,
    "Na": 0.93,
    "K": 0.82,
    "Mg": 1.31,
    "Ca": 1.00,
    "Fe": 1.83,
    "Ni": 1.91,
    "Pd": 2.20,
    "Pt": 2.28,
    "Cu": 1.90,
    "Zn": 1.65,
}


def sketch_oxidation_state(
    element: str,
    bond_partners: list[tuple[str, int]],
    *,
    implicit_h: int = 0,
) -> int | None:
    """
    Approximate integer oxidation state for sketcher annotation.

    Assigns bonding electrons to the more electronegative atom (equal EN → split).
    Includes implicit hydrogens as bonds to H. Returns None when undefined.
    """
    el = str(element or "")
    if not el or el == WILDCARD_ELEMENT:
        return None
    try:
        pt = Chem.GetPeriodicTable()
        an = int(pt.GetAtomicNumber(el if el not in ("D", "T") else "H"))
        if an <= 0:
            return None
        valence_e = int(pt.GetNOuterElecs(an if el not in ("D", "T") else 1))
        if el in ("D", "T"):
            valence_e = 1
    except Exception:
        return None
    if valence_e <= 0:
        return None
    partners = list(bond_partners)
    for _ in range(max(0, int(implicit_h))):
        partners.append(("H", 1))
    en_self = _ELEMENT_EN.get(el)
    if en_self is None:
        try:
            # Fallback: use outer-electron count band as a weak EN proxy — skip unknowns.
            return None
        except Exception:
            return None
    assigned = 0
    bond_sum = 0
    for pel, order in partners:
        o = max(0, int(order))
        bond_sum += o
        en_p = _ELEMENT_EN.get(str(pel), _ELEMENT_EN.get("C", 2.55))
        if en_self > en_p + 1e-6:
            assigned += 2 * o
        elif abs(en_self - en_p) <= 1e-6:
            assigned += o
        # else: more electronegative partner keeps both electrons → 0 assigned here
    # Nonbonding electrons from leftover valence after bonding (ignore formal charge for OS).
    nonbonding = max(0, valence_e - bond_sum)
    if nonbonding % 2 == 1:
        nonbonding -= 1
    return int(valence_e - nonbonding - assigned)
