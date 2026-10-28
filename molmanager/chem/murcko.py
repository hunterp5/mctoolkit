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
atoms and keep exocyclic double bonds. Scaffold ID gives every distinct scaffold
in the run one integer, so
rows that share a scaffold share that ID.
"""

from __future__ import annotations

from rdkit import Chem, rdBase
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
        "Ring systems from the Murcko scaffold, without the atoms that link them. "
        "Exocyclic double bonds stay on the ring. Separate systems are joined with a dot. "
        "Blank when the structure has no rings.",
    ),
    (
        "Scaffold ID",
        "MURCKO_ID",
        "Integer shared by every row in this run with the same Murcko scaffold. "
        "IDs start at 1 in the order scaffolds first appear. 0 when the structure has no rings.",
    ),
)

_SCAFFOLD_VALUE_FNS = {
    "MURCKO_SCAFFOLD": "scaffold",
    "MURCKO_FRAMEWORK": "framework",
    "MURCKO_RINGS": "rings",
}


def murcko_callable_for_key(internal: str):
    """``callable(mol)`` for one scaffold column. Scaffold ID is filled after the run."""
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
    """Canonical SMILES of each ring system in the scaffold, joined with ``.``.

    Linker atoms are left out. Exocyclic multiple bonds, such as carbonyls, stay
    on the ring. A bond cut by that split is replaced by hydrogen, so a
    substituted aromatic nitrogen is written as ``[nH]`` and the fragment can
    be drawn.
    """
    scaffold = _scaffold_mol(mol)
    if scaffold is None:
        return ""
    parts: list[str] = []
    for atoms in _ring_system_fragments(scaffold):
        smiles = _fragment_smiles(scaffold, atoms)
        if smiles:
            parts.append(smiles)
    parts.sort()
    return ".".join(parts)


def apply_murcko_scaffold_ids(results, prepared, disp_headers, int_fns):
    """Fill scaffold-ID cells so rows that share a Murcko scaffold share an ID.

    IDs start at 1 and follow the order scaffolds first appear in *prepared*
    (the run order), not the order worker results happen to finish. Rows whose
    ID cell is already ``N/A`` (no structure) are left alone. A structure with
    no rings gets ``0``, and every such row shares that ID.
    """
    id_headers = [str(disp) for disp, fn in zip(disp_headers, int_fns) if fn == "MURCKO_ID"]
    if not id_headers:
        return results
    smiles_by_oid = {int(oid): murcko_scaffold_smiles(mol) for oid, mol in prepared}
    scaffold_ids: dict[str, int] = {}
    for oid, _mol in prepared:
        smiles = smiles_by_oid.get(int(oid), "")
        if smiles and smiles not in scaffold_ids:
            scaffold_ids[smiles] = len(scaffold_ids) + 1
    out: list[tuple[int, dict]] = []
    for oid, row in results:
        copied = dict(row or {})
        oid_i = int(oid)
        if copied.get(id_headers[0]) != "N/A":
            smiles = smiles_by_oid.get(oid_i, "")
            value = str(scaffold_ids[smiles]) if smiles else "0"
            for header in id_headers:
                copied[header] = value
        out.append((oid_i, copied))
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


# Bond order a cut bond contributes when it is replaced by hydrogen. Aromatic
# bonds count as one: ``GetBondTypeAsDouble`` reports 1.5, which would add two.
_CUT_BOND_HYDROGENS = {
    Chem.BondType.SINGLE: 1,
    Chem.BondType.DOUBLE: 2,
    Chem.BondType.TRIPLE: 3,
    Chem.BondType.QUADRUPLE: 4,
    Chem.BondType.AROMATIC: 1,
    Chem.BondType.DATIVE: 0,
}


def _ring_system_fragments(mol) -> list[set[int]]:
    """Ring-system atoms plus exocyclic atoms that are not linkers.

    Carbonyl oxygens and other dead-end substituents are peeled off the scaffold
    and given back to the ring they touch. An oxygen on a linker carbonyl stays
    out, because it does not touch a ring.
    """
    systems = _ring_system_atom_sets(mol)
    if not systems:
        return []
    ring_of: dict[int, int] = {}
    for index, atoms in enumerate(systems):
        for atom_id in atoms:
            ring_of[atom_id] = index
    pendants = _pendant_atoms(mol, ring_of)
    extras = [set() for _ in systems]
    owner: dict[int, int] = {}
    for atom_id in reversed(pendants):
        system = _pendant_system(mol, atom_id, ring_of, owner)
        if system is None:
            continue
        owner[atom_id] = system
        extras[system].add(atom_id)
    return [set(atoms) | extras[index] for index, atoms in enumerate(systems)]


def _pendant_atoms(mol, ring_of: dict[int, int]) -> list[int]:
    """Non-ring atoms peeled from the outside in. What remains are linkers."""
    remaining = {atom.GetIdx() for atom in mol.GetAtoms() if atom.GetIdx() not in ring_of}
    pendants: list[int] = []
    changed = True
    while changed:
        changed = False
        for atom_id in list(remaining):
            degree = sum(
                1
                for neighbor in mol.GetAtomWithIdx(atom_id).GetNeighbors()
                if neighbor.GetIdx() in remaining or neighbor.GetIdx() in ring_of
            )
            if degree <= 1:
                remaining.remove(atom_id)
                pendants.append(atom_id)
                changed = True
    return pendants


def _pendant_system(
    mol, atom_id: int, ring_of: dict[int, int], owner: dict[int, int]
) -> int | None:
    """Ring system a peeled atom belongs to, or ``None`` when it hangs off a linker."""
    for neighbor in mol.GetAtomWithIdx(atom_id).GetNeighbors():
        idx = neighbor.GetIdx()
        if idx in ring_of:
            return ring_of[idx]
        if idx in owner:
            return owner[idx]
    return None


def _hydrogens_for_cut_bond(bond) -> int:
    mapped = _CUT_BOND_HYDROGENS.get(bond.GetBondType())
    if mapped is not None:
        return mapped
    order = bond.GetBondTypeAsDouble()
    if order <= 0:
        return 0
    return int(round(order))


def _fragment_smiles(mol, atom_ids: set[int]) -> str:
    """Canonical SMILES of one ring system.

    Hydrogens replace bonds to atoms outside *atom_ids*. ``MolFragmentToSmiles``
    otherwise keeps the parent's hydrogen count, so a glycosidic nitrogen is
    written as ``n`` and the purine cannot be kekulized.
    """
    if not atom_ids:
        return ""
    copied = Chem.RWMol(mol)
    try:
        for atom_id in atom_ids:
            atom = copied.GetAtomWithIdx(atom_id)
            missing = 0
            for bond in atom.GetBonds():
                if bond.GetOtherAtomIdx(atom_id) not in atom_ids:
                    missing += _hydrogens_for_cut_bond(bond)
            if missing:
                atom.SetNumExplicitHs(atom.GetTotalNumHs() + missing)
                atom.SetNoImplicit(True)
        bonds = [
            bond.GetIdx()
            for bond in copied.GetBonds()
            if bond.GetBeginAtomIdx() in atom_ids and bond.GetEndAtomIdx() in atom_ids
        ]
        smiles = (
            Chem.MolFragmentToSmiles(
                copied,
                atomsToUse=sorted(atom_ids),
                bondsToUse=bonds,
                canonical=True,
            )
            or ""
        )
    except (ValueError, RuntimeError):
        return ""
    if not smiles or not _smiles_parses(smiles):
        return ""
    return smiles


def _smiles_parses(smiles: str) -> bool:
    """True when *smiles* is a molecule the 2D renderer can read back."""
    blocker = rdBase.BlockLogs()
    try:
        return Chem.MolFromSmiles(smiles) is not None
    finally:
        del blocker
