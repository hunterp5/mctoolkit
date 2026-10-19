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

"""Maximum common substructure over a set of molecules (RDKit FindMCS)."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import rdFMCS

COMMON_CORE_HEADER = "Common core"
CORE_ATOM_MAP_HEADER = "Core atom map"
CORE_MATCH_HEADER = "Core match"
COMMON_CORE_HEADERS: tuple[str, ...] = (
    COMMON_CORE_HEADER,
    CORE_ATOM_MAP_HEADER,
    CORE_MATCH_HEADER,
)

_NA = "N/A"


def build_common_core_rows(
    pairs: list[tuple[int, Chem.Mol | None]],
    *,
    outliers: int,
    complete_rings: bool,
    timeout: int,
) -> list[tuple[int, dict[str, str]]]:
    """Return one result row per input pair.

    ``outliers`` is how many structures may lack the core. The search still
    requires the core in at least two molecules. Rows that do not contain the
    core keep the core SMARTS and are marked ``no``. Invalid structures are
    ``N/A`` and are left out of the search.

    Raises:
        ValueError: fewer than two usable structures, no core, or the search timed out.
    """
    usable: list[tuple[int, Chem.Mol]] = []
    for oid, mol in pairs:
        if mol is not None and mol.GetNumAtoms() > 0:
            usable.append((int(oid), mol))
    if len(usable) < 2:
        raise ValueError("Common core needs at least two structures.")

    ignored = max(0, min(int(outliers), len(usable) - 2))
    threshold = (len(usable) - ignored) / float(len(usable))
    try:
        result = rdFMCS.FindMCS(
            [mol for _oid, mol in usable],
            threshold=threshold,
            timeout=max(1, int(timeout)),
            matchValences=True,
            ringMatchesRingOnly=False,
            completeRingsOnly=bool(complete_rings),
            atomCompare=rdFMCS.AtomCompare.CompareElements,
            bondCompare=rdFMCS.BondCompare.CompareOrder,
        )
    except (ValueError, RuntimeError) as exc:
        raise ValueError("Common core search failed.") from exc
    if result is None or bool(getattr(result, "canceled", False)):
        raise ValueError(
            "The common-core search timed out. Increase the time limit or search fewer rows."
        )
    smarts = str(getattr(result, "smartsString", "") or "").strip()
    if int(getattr(result, "numAtoms", 0) or 0) < 1 or not smarts:
        raise ValueError(
            "No common core was found. Ignore more outliers, or turn off complete rings."
        )
    query = getattr(result, "queryMol", None)
    if query is None:
        try:
            query = Chem.MolFromSmarts(smarts)
        except (ValueError, RuntimeError):
            query = None
    if query is None:
        raise ValueError("Common core search failed.")

    matched_oids: dict[int, tuple[int, ...]] = {}
    for oid, mol in usable:
        try:
            match = mol.GetSubstructMatch(query)
        except (ValueError, RuntimeError):
            match = ()
        if match:
            matched_oids[int(oid)] = tuple(int(index) for index in match)
    if len(matched_oids) < 2:
        raise ValueError(
            "No common core was found. Ignore more outliers, or turn off complete rings."
        )

    rows: list[tuple[int, dict[str, str]]] = []
    for oid, mol in pairs:
        if mol is None or mol.GetNumAtoms() == 0:
            rows.append(
                (
                    int(oid),
                    {
                        COMMON_CORE_HEADER: _NA,
                        CORE_ATOM_MAP_HEADER: _NA,
                        CORE_MATCH_HEADER: _NA,
                    },
                )
            )
            continue
        match = matched_oids.get(int(oid))
        rows.append(
            (
                int(oid),
                {
                    COMMON_CORE_HEADER: smarts,
                    CORE_ATOM_MAP_HEADER: "" if not match else ", ".join(str(i) for i in match),
                    CORE_MATCH_HEADER: "yes" if match else "no",
                },
            )
        )
    return rows
