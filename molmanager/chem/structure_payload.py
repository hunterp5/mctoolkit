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

"""Qt-free structure snapshots for chemistry-tool workers.

The GUI thread copies ``(oid, blob, smiles)`` only. RDKit hydrate happens on the
process-queue / thread-pool factory thread, where workers already run.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .molecule_conversion import mol_to_canonical_smiles, parse_molecule_from_cell_text


@dataclass(frozen=True)
class StructurePayload:
    """One scoped structure: stored pickle and/or parseable text. No live ``Mol``."""

    oid: int | None
    blob: bytes | None = None
    smiles: str = ""

    def has_structure(self) -> bool:
        return bool(self.blob) or bool((self.smiles or "").strip())


def mol_from_payload(payload: StructurePayload):
    """Hydrate one RDKit mol from a stored blob, else from SMILES/InChI/molblock text."""
    blob = payload.blob
    if blob:
        from rdkit import Chem

        try:
            mol = Chem.Mol(blob)
        except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
            mol = None
        if mol is not None:
            return mol
    smi = (payload.smiles or "").strip()
    if not smi:
        return None
    return parse_molecule_from_cell_text(smi)


def smiles_text_for_payload(payload: StructurePayload) -> str:
    """SMILES for a tool that cannot read a stored mol blob.

    SDF and session rows often keep a valid connection table with no SMILES
    string. Hydrate the payload and canonicalize so callers are not limited to
    datasets that already have a SMILES column.
    """
    mol = mol_from_payload(payload)
    if mol is None:
        return ""
    try:
        return mol_to_canonical_smiles(mol).strip()
    except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
        return ""


def smiles_rows_from_payloads(
    payloads: Iterable[StructurePayload],
) -> list[tuple[int, str]]:
    """``(oid, SMILES)`` for payloads that canonicalize. Drops empty and unparsed rows."""
    rows: list[tuple[int, str]] = []
    for payload in payloads:
        if payload.oid is None:
            continue
        smi = smiles_text_for_payload(payload)
        if smi:
            rows.append((int(payload.oid), smi))
    return rows


def mols_from_payloads(
    payloads: Iterable[StructurePayload],
) -> list[tuple[int | None, object]]:
    """Hydrate payloads; drop rows that do not parse."""
    out: list[tuple[int | None, object]] = []
    for payload in payloads:
        mol = mol_from_payload(payload)
        if mol is None:
            continue
        out.append((payload.oid, mol))
    return out


def oid_mol_rows_from_payloads(
    payloads: Sequence[StructurePayload],
) -> list[tuple[int, object]]:
    """Like :func:`mols_from_payloads` but only rows with a table OID."""
    rows: list[tuple[int, object]] = []
    for oid, mol in mols_from_payloads(payloads):
        if oid is None:
            continue
        rows.append((int(oid), mol))
    return rows


def mol_rows_from_job_params(params: dict) -> list[tuple[int | None, object]] | None:
    """Resolve ``mol_payloads`` (preferred) or legacy ``mol_rows`` on a worker thread."""
    payloads = params.get("mol_payloads")
    if payloads:
        return mols_from_payloads(payloads)
    rows = params.get("mol_rows")
    if not rows:
        return None
    return list(rows)
