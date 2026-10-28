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

"""Split reaction SMARTS / SMIRKS cells into reactant and product columns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from rdkit import Chem

from .reaction_file_io import is_reaction_smarts_header, parse_reaction_smarts
from .molecule_conversion import mol_to_canonical_smiles

ExtractMode = Literal["reactants", "products", "both"]

EXTRACT_MODES: tuple[tuple[str, ExtractMode], ...] = (
    ("Reactants", "reactants"),
    ("Products", "products"),
    ("Both", "both"),
)

MAX_EXTRACT_COMPONENTS = 64
DEFAULT_REACTANT_PREFIX = "Reactant"
DEFAULT_PRODUCT_PREFIX = "Product"


@dataclass(frozen=True)
class ReactionExtractParams:
    """Settings for Chemistry → Reaction → Extract Reaction Info."""

    source_column: str
    mode: ExtractMode
    reactant_prefix: str = DEFAULT_REACTANT_PREFIX
    product_prefix: str = DEFAULT_PRODUCT_PREFIX


def preferred_reaction_source_column(headers: list[str]) -> str | None:
    """First table header that looks like a reaction SMARTS / SMIRKS column."""
    for h in headers:
        if is_reaction_smarts_header(h):
            return h
    return None


def split_side_components(side: str) -> list[str]:
    """Split one reaction side on ``.`` outside square brackets."""
    parts: list[str] = []
    buf: list[str] = []
    depth = 0
    for ch in side or "":
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth = max(0, depth - 1)
        elif ch == "." and depth == 0:
            token = "".join(buf).strip()
            if token:
                parts.append(token)
            buf = []
            continue
        buf.append(ch)
    token = "".join(buf).strip()
    if token:
        parts.append(token)
    return parts


def _mol_has_query(mol: Chem.Mol) -> bool:
    try:
        if any(atom.HasQuery() for atom in mol.GetAtoms()):
            return True
        return any(bond.HasQuery() for bond in mol.GetBonds())
    except Exception:
        return False


def _mol_component_text(mol: Chem.Mol | None) -> str:
    """SMILES for concrete molecules; SMARTS when query features are present."""
    if mol is None:
        return ""
    if not _mol_has_query(mol):
        try:
            copy = Chem.Mol(mol)
            for atom in copy.GetAtoms():
                atom.SetAtomMapNum(0)
            smi = mol_to_canonical_smiles(copy)
        except Exception:
            smi = ""
        if smi:
            return smi
    try:
        return (Chem.MolToSmarts(mol) or "").strip()
    except Exception:
        return ""


def _components_from_rxn(rxn, getter) -> list[str]:
    out: list[str] = []
    try:
        mols = getter() or []
    except Exception:
        return out
    for mol in mols:
        text = _mol_component_text(mol)
        if text:
            out.append(text)
    return out


def _sides_from_text(text: str) -> tuple[str, str]:
    raw = (text or "").strip()
    if ">>" in raw:
        left, right = raw.split(">>", 1)
        return left.strip(), right.strip()
    if raw.count(">") >= 2:
        parts = raw.split(">")
        return parts[0].strip(), parts[-1].strip()
    return "", ""


def extract_reaction_sides(text: str) -> tuple[list[str], list[str]]:
    """Return ``(reactants, products)`` as SMILES or SMARTS strings."""
    rxn = parse_reaction_smarts(text)
    reactants: list[str] = []
    products: list[str] = []
    if rxn is not None:
        reactants = _components_from_rxn(rxn, rxn.GetReactants)
        products = _components_from_rxn(rxn, rxn.GetProducts)
        if reactants or products:
            return reactants, products
    left, right = _sides_from_text(text)
    return split_side_components(left), split_side_components(right)


def _prefixed_headers(prefix: str, n: int) -> list[str]:
    base = (prefix or "").strip() or "Component"
    count = max(0, min(int(n), MAX_EXTRACT_COMPONENTS))
    return [f"{base} {i}" for i in range(1, count + 1)]


def extract_reaction_column_values(
    texts: list[str],
    mode: ExtractMode,
    *,
    reactant_prefix: str = DEFAULT_REACTANT_PREFIX,
    product_prefix: str = DEFAULT_PRODUCT_PREFIX,
) -> tuple[list[str], list[dict[str, str]]]:
    """Parse each cell and build per-row dicts keyed by ``Reactant 1``, ``Product 1``, …"""
    if mode not in ("reactants", "products", "both"):
        raise ValueError(f"Unknown extract mode: {mode!r}")
    parsed = [extract_reaction_sides(t) for t in texts]
    n_r = 0
    n_p = 0
    if mode in ("reactants", "both"):
        n_r = max((len(r) for r, _p in parsed), default=0)
    if mode in ("products", "both"):
        n_p = max((len(p) for _r, p in parsed), default=0)
    r_headers = _prefixed_headers(reactant_prefix, n_r)
    p_headers = _prefixed_headers(product_prefix, n_p)
    headers = r_headers + p_headers
    rows: list[dict[str, str]] = []
    for reactants, products in parsed:
        cells: dict[str, str] = {}
        for i, h in enumerate(r_headers):
            cells[h] = reactants[i] if i < len(reactants) else ""
        for i, h in enumerate(p_headers):
            cells[h] = products[i] if i < len(products) else ""
        rows.append(cells)
    return headers, rows
