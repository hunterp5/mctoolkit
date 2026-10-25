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

"""Local substituent-constant table for Hansch analysis.

The numbers themselves stay in a file the user keeps. This module only reads
that CSV and canonicalizes attachment-point SMILES the same way Free-Wilson
names an R-group. Es is stored as the file gives it: Taft's scale is zero at
methyl, and the later Hansch scale is zero at hydrogen. Nothing here converts
between those zeros.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from rdkit import Chem

HYDROGEN_ATTACHMENT = "H"
SMILES_COLUMN = "smiles"
CONSTANT_FIELDS = (
    "pi",
    "sigma_m",
    "sigma_p",
    "f",
    "r",
    "es",
    "mr",
    "upsilon",
    "sigma_star",
)
SCHEMA_HEADER = ",".join((SMILES_COLUMN, *CONSTANT_FIELDS))

_PARSE_ERRORS = (RuntimeError, ValueError, TypeError, OSError)


@dataclass(frozen=True)
class SubstituentRecord:
    """One substituent. A blank CSV cell is ``None``, not zero."""

    key: str
    pi: float | None = None
    sigma_m: float | None = None
    sigma_p: float | None = None
    f: float | None = None
    r: float | None = None
    es: float | None = None
    mr: float | None = None
    upsilon: float | None = None
    sigma_star: float | None = None


class SubstituentTable:
    """Constants keyed by :func:`attachment_key`."""

    def __init__(self, records: tuple[SubstituentRecord, ...]):
        self.records = records
        self.by_key = {record.key: record for record in records}

    def get(self, key: str) -> SubstituentRecord | None:
        return self.by_key.get(key)


def attachment_key(mol: Chem.Mol) -> str:
    """Canonical lookup key for an R-group, including the attachment dummy.

    Hydrogen, with no heavy atom, is ``H``. Other groups are canonical SMILES
    with atom-map numbers cleared on dummy atoms.
    """
    if mol.GetNumHeavyAtoms() == 0:
        return HYDROGEN_ATTACHMENT
    keyed = Chem.Mol(mol)
    for atom in keyed.GetAtoms():
        if atom.GetAtomicNum() == 0:
            atom.SetAtomMapNum(0)
    try:
        smiles = Chem.MolToSmiles(keyed, canonical=True)
    except _PARSE_ERRORS:
        smiles = ""
    return smiles or HYDROGEN_ATTACHMENT


def canonical_table_key(text: str) -> str:
    """Turn one CSV substituent cell into an :func:`attachment_key`."""
    raw = (text or "").strip()
    if not raw or raw.upper() == HYDROGEN_ATTACHMENT:
        return HYDROGEN_ATTACHMENT
    try:
        mol = Chem.MolFromSmiles(raw)
    except _PARSE_ERRORS:
        mol = None
    if mol is None:
        raise ValueError(f"Substituent SMILES is not valid: {raw}")
    return attachment_key(mol)


def load_substituent_constants(path: str | Path) -> SubstituentTable:
    """Read a constants CSV. The header is :data:`SCHEMA_HEADER`.

    ``smiles`` is required. The other columns are optional; a missing column is
    the same as a blank cell. Duplicate keys after canonicalization are an error.
    """
    file_path = Path(path)
    if not file_path.is_file():
        raise ValueError(f"Constants file was not found: {file_path}")
    try:
        text = file_path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise ValueError(f"Could not read the constants file: {exc}") from exc
    reader = csv.DictReader(text.splitlines())
    fieldnames = _normalized_fields(reader.fieldnames)
    if SMILES_COLUMN not in fieldnames:
        raise ValueError(f"Constants file needs a {SMILES_COLUMN} column.")
    present = [name for name in CONSTANT_FIELDS if name in fieldnames]
    records: list[SubstituentRecord] = []
    seen: dict[str, int] = {}
    for line_number, row in enumerate(reader, start=2):
        if row is None or not any(
            (value or "").strip() for value in row.values() if value is not None
        ):
            continue
        normalized = {(key or "").strip().lower(): (value or "") for key, value in row.items()}
        smiles = normalized.get(SMILES_COLUMN, "").strip()
        if not smiles:
            raise ValueError(f"Line {line_number}: missing {SMILES_COLUMN}.")
        try:
            key = canonical_table_key(smiles)
        except ValueError as exc:
            raise ValueError(f"Line {line_number}: {exc}") from exc
        previous = seen.get(key)
        if previous is not None:
            raise ValueError(
                f"Line {line_number}: {smiles} matches the substituent already on line {previous}."
            )
        seen[key] = line_number
        values = {
            name: _optional_float(normalized.get(name, ""), line_number, name) for name in present
        }
        records.append(SubstituentRecord(key=key, **values))
    if not records:
        raise ValueError("Constants file has no substituent rows.")
    return SubstituentTable(tuple(records))


def _normalized_fields(fieldnames: list[str] | None) -> set[str]:
    return {(name or "").strip().lower() for name in (fieldnames or []) if (name or "").strip()}


def _optional_float(text: str, line_number: int, column: str) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"Line {line_number}: {column} is not a number ({raw}).") from exc
    return value
