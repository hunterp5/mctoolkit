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

"""Residue-contact fingerprints for a stored ligand pose against one receptor.

Each contact is ``chain:resname:resid:family``. The residue list drops the
family so a later contact map can count residues without parsing bits.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .protein_interactions import (
    FAMILY_HALOGEN,
    FAMILY_HBOND,
    FAMILY_HYDROPHOBIC,
    FAMILY_IONIC,
    FAMILY_PI_CATION,
    FAMILY_PI_STACKING,
    ProteinInteraction,
    _prolif_role,
    detect_prolif_interactions_from_pose,
    prolif_available,
)
from .structure_atoms import StructureAtom, _residue_kinds_from_atoms, parse_structure_atoms

IFP_FAMILIES: tuple[str, ...] = (
    FAMILY_HBOND,
    FAMILY_HYDROPHOBIC,
    FAMILY_IONIC,
    FAMILY_PI_STACKING,
    FAMILY_PI_CATION,
    FAMILY_HALOGEN,
)
_FAMILY_SET = frozenset(IFP_FAMILIES)
_CIF_SUFFIXES = {".cif", ".mmcif", ".mcif"}


class InteractionFingerprintError(ValueError):
    """The receptor or ProLIF cannot produce a fingerprint."""


@dataclass(frozen=True)
class InteractionFingerprintRow:
    """One table row's fingerprint and residue list."""

    oid: int
    fingerprint: str
    residues: str


@dataclass(frozen=True)
class InteractionFingerprintJobResult:
    """Columns to write after a fingerprint job."""

    rows: tuple[InteractionFingerprintRow, ...]
    fingerprint_header: str
    residues_header: str
    n_missing_pose: int
    cancelled: bool


def fingerprint_headers(prefix: str) -> tuple[str, str]:
    """Return ``(fingerprint column, residue-list column)`` for *prefix*."""
    base = (prefix or "").strip() or "IFP"
    return base, f"{base} Residues"


def residue_label(chain: str, resn: str, resi: str, icode: str = "") -> str:
    """Stable residue id ``chain:resn:resi`` or ``chain:resn:resi:icode``."""
    chain_text = (chain or "").strip() or "?"
    resn_text = (resn or "").strip() or "UNK"
    resi_text = (resi or "").strip() or "?"
    label = f"{chain_text}:{resn_text}:{resi_text}"
    insertion = (icode or "").strip()
    if insertion:
        return f"{label}:{insertion}"
    return label


def contact_token(contact: ProteinInteraction) -> str | None:
    """``residue:family`` for a typed contact, or ``None`` when the family is unused."""
    family = (contact.family or "").strip()
    if family not in _FAMILY_SET:
        return None
    residue = residue_label(
        contact.protein_chain,
        contact.protein_resn,
        contact.protein_resi,
        contact.protein_icode,
    )
    return f"{residue}:{family}"


def fingerprint_from_contacts(
    contacts: tuple[ProteinInteraction, ...] | list[ProteinInteraction],
) -> tuple[str, str]:
    """Return ``(fingerprint, residue list)``. Duplicate contacts collapse."""
    tokens: set[str] = set()
    residues: set[str] = set()
    for contact in contacts:
        token = contact_token(contact)
        if token is None:
            continue
        tokens.add(token)
        residues.add(token.rsplit(":", 1)[0])
    return ";".join(sorted(tokens)), ";".join(sorted(residues))


def structure_format_for_path(path: str) -> str:
    """``mmcif`` for CIF suffixes, otherwise the PDB parser."""
    suffix = Path(path).suffix.lower()
    if suffix in _CIF_SUFFIXES:
        return "mmcif"
    return "pdb"


def load_receptor_polymer_atoms(path: str) -> list[StructureAtom]:
    """Polymer atoms from a receptor file. Crystal ligands and waters are left out."""
    file_path = Path(path)
    try:
        text = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise InteractionFingerprintError(f"Could not read the receptor file: {exc}") from exc
    atoms = parse_structure_atoms(text, structure_format_for_path(str(file_path)))
    kinds = _residue_kinds_from_atoms(atoms)
    polymer = [atom for atom in atoms if _prolif_role(atom, kinds) == "polymer"]
    if len(polymer) < 3:
        raise InteractionFingerprintError(
            "The receptor file has no polymer chain to type contacts against."
        )
    return polymer


def fingerprint_pose(
    protein_atoms: list[StructureAtom],
    ligand_mol,
) -> tuple[str, str]:
    """ProLIF fingerprint for one pose. Empty strings mean the pose makes no contacts."""
    if not prolif_available():
        raise InteractionFingerprintError(
            "Interaction fingerprints need ProLIF. Install it with: pip install prolif"
        )
    contacts = detect_prolif_interactions_from_pose(protein_atoms, ligand_mol)
    return fingerprint_from_contacts(contacts)
