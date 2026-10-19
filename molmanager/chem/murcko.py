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

"""Bemis–Murcko scaffold columns for Chemistry → Substructure → Bemis–Murcko.

The scaffold keeps rings and the linker atoms between them. The framework is
that skeleton drawn as carbon with single bonds. Ring systems drop the linker
atoms. Scaffold count is how many rows in the same run share the scaffold.
"""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem.Scaffolds import MurckoScaffold

# Display header, worker key, checkbox tooltip.
SCAFFOLD_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "Murcko scaffold",
        "MURCKO_SCAFFOLD",
        "Bemis–Murcko scaffold: rings and the linkers between them, with atom types kept. "
        "Blank when the structure has no rings.",
    ),
    (
        "Murcko framework",
        "MURCKO_FRAMEWORK",
        "Murcko scaffold drawn with every atom as carbon and every bond as a single bond. "
        "Blank when the structure has no rings.",
    ),
    (
        "Murcko ring systems",
        "MURCKO_RINGS",
        "Ring systems from the Murcko scaffold, without linker atoms. "
        "Separate systems are joined with a dot. Blank when the structure has no rings.",
    ),
    (
        "Scaffold count",
        "MURCKO_COUNT",
        "How many rows in this run share the Murcko scaffold. 0 when the structure has no rings.",
    ),
)

_SCAFFOLD_VALUE_FNS = {
    "MURCKO_SCAFFOLD": "scaffold",
    "MURCKO_FRAMEWORK": "framework",
    "MURCKO_RINGS": "rings",
}


def murcko_callable_for_key(internal: str):
    """``callable(mol)`` for one scaffold column. Count is filled after the run."""
    kind = _SCAFFOLD_VALUE_FNS.get(internal)
    if kind is None:
        return lambda _mol: ""

    def _value(mol, which=kind):
        if mol is None:
            return ""
        if which == "scaffold":
            return murcko_scaffold_smiles(mol)
        if which == "framework":
            return murcko_framework_smiles(mol)
        return murcko_ring_systems_smiles(mol)

    return _value


def murcko_scaffold_smiles(mol) -> str:
    """Canonical SMILES of the Bemis–Murcko scaffold, or blank when there are no rings."""
    scaffold = _scaffold_mol(mol)
    if scaffold is None:
        return ""
    return _canonical_smiles(scaffold)


def murcko_framework_smiles(mol) -> str:
    """Generic Murcko framework: the scaffold as carbon with single bonds."""
    scaffold = _scaffold_mol(mol)
    if scaffold is None:
        return ""
    try:
        generic = MurckoScaffold.MakeScaffoldGeneric(scaffold)
    except (ValueError, RuntimeError):
        return ""
    return _canonical_smiles(generic)


def murcko_ring_systems_smiles(mol) -> str:
    """Canonical SMILES of each ring system in the scaffold, joined with ``.``."""
    scaffold = _scaffold_mol(mol)
    if scaffold is None:
        return ""
    parts: list[str] = []
    for atoms in _ring_system_atom_sets(scaffold):
        smiles = _fragment_smiles(scaffold, atoms)
        if smiles:
            parts.append(smiles)
    parts.sort()
    return ".".join(parts)


def apply_murcko_scaffold_counts(results, prepared, disp_headers, int_fns):
    """Fill scaffold-count cells from the Murcko scaffold shared by rows in this run.

    Rows whose count cell is already ``N/A`` (no structure) are left alone and
    are not part of the tally. A structure with no rings gets ``0``.
    """
    count_headers = [str(disp) for disp, fn in zip(disp_headers, int_fns) if fn == "MURCKO_COUNT"]
    if not count_headers:
        return results
    smiles_by_oid = {int(oid): murcko_scaffold_smiles(mol) for oid, mol in prepared}
    pending: list[tuple[int, dict, str | None]] = []
    tally: dict[str, int] = {}
    for oid, row in results:
        copied = dict(row or {})
        oid_i = int(oid)
        if copied.get(count_headers[0]) == "N/A":
            pending.append((oid_i, copied, None))
            continue
        smiles = smiles_by_oid.get(oid_i, "")
        if smiles:
            tally[smiles] = tally.get(smiles, 0) + 1
        pending.append((oid_i, copied, smiles))
    out: list[tuple[int, dict]] = []
    for oid, row, smiles in pending:
        if smiles is not None:
            value = str(tally[smiles]) if smiles else "0"
            for header in count_headers:
                row[header] = value
        out.append((oid, row))
    return out


def _scaffold_mol(mol):
    if mol is None:
        return None
    try:
        scaffold = MurckoScaffold.GetScaffoldForMol(mol)
    except (ValueError, RuntimeError):
        return None
    if scaffold is None or scaffold.GetNumAtoms() == 0:
        return None
    return scaffold


def _canonical_smiles(mol) -> str:
    try:
        return Chem.MolToSmiles(mol, canonical=True) or ""
    except (ValueError, RuntimeError):
        return ""


def _ring_system_atom_sets(mol) -> list[set[int]]:
    """Fused and spiro rings that share an atom stay in one system."""
    systems = [set(ring) for ring in mol.GetRingInfo().AtomRings()]
    changed = True
    while changed and len(systems) > 1:
        changed = False
        merged: list[set[int]] = []
        for atoms in systems:
            placed = False
            for system in merged:
                if system & atoms:
                    system |= atoms
                    placed = True
                    changed = True
                    break
            if not placed:
                merged.append(set(atoms))
        systems = merged
    return systems


def _fragment_smiles(mol, atom_ids: set[int]) -> str:
    bonds = [
        bond.GetIdx()
        for bond in mol.GetBonds()
        if bond.GetBeginAtomIdx() in atom_ids and bond.GetEndAtomIdx() in atom_ids
    ]
    try:
        return (
            Chem.MolFragmentToSmiles(
                mol,
                atomsToUse=sorted(atom_ids),
                bondsToUse=bonds,
                canonical=True,
            )
            or ""
        )
    except (ValueError, RuntimeError):
        return ""
