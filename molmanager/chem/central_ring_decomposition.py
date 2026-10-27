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

"""R-group decomposition around each molecule's most central ring system."""

from __future__ import annotations

from rdkit import Chem

# RDKit's Python wrappers raise ValueError (including MolSanitizeException) or
# RuntimeError. New modules cannot use a bare ``except Exception``.
_RDKIT_ERRORS = (ValueError, RuntimeError)


def most_central_ring_atoms(mol: Chem.Mol) -> tuple[int, ...] | None:
    """Heavy-atom indices of the ring system that contains the most central ring.

    Centrality is the mean bond-path distance from a ring's atoms to every heavy
    atom. The lowest mean wins. Ties prefer the larger ring, then the ring that
    holds the lowest canonical atom rank. Rings that share an atom with the
    winner — fused, bridged, or spiro — stay in the same system. A ring joined
    only by a bond, such as the second ring of biphenyl, does not.
    """
    rings = _sssr_rings(mol)
    if not rings:
        return None
    heavy = _heavy_atom_indices(mol)
    if not heavy:
        return None
    means = _mean_heavy_distances(mol, heavy)
    ranks = list(Chem.CanonicalRankAtoms(mol, breakTies=True, includeChirality=True))
    chosen = min(
        range(len(rings)),
        key=lambda index: (
            sum(means[atom] for atom in rings[index]) / len(rings[index]),
            -len(rings[index]),
            min(ranks[atom] for atom in rings[index]),
        ),
    )
    atoms = {
        atom
        for atom in _ring_system_atoms(rings, chosen)
        if mol.GetAtomWithIdx(atom).GetAtomicNum() > 1
    }
    if len(atoms) < 3:
        return None
    return tuple(sorted(atoms))


def decompose_central_ring(mol: Chem.Mol | None) -> dict[str, str] | None:
    """Split *mol* into its most central ring system and the attached substituents.

    Keys match core-based decomposition: ``Core``, ``R1``, ``R2``, and so on.
    Each attachment is a dummy atom ``[*:1]``, ``[*:2]``, … ordered by the
    core's canonical ranking, so the same scaffold gets the same R numbers.
    Returns None when *mol* has no ring.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    work = _prepared_copy(mol)
    if work is None:
        return None
    core_atoms = most_central_ring_atoms(work)
    if not core_atoms:
        return None
    core_set = set(core_atoms)
    cut_ids = _cut_bonds(work, core_set)
    if cut_ids:
        bond_types = [work.GetBondWithIdx(idx).GetBondType() for idx in cut_ids]
        fragmented = Chem.FragmentOnBonds(work, cut_ids, addDummies=True, bondTypes=bond_types)
        links = _dummy_links(fragmented)
        for idx in links:
            fragmented.GetAtomWithIdx(idx).SetIsotope(0)
        if not _label_attachments(fragmented, core_set, links):
            return None
        split = _split_core_and_substituents(fragmented, core_set)
    else:
        split = _split_core_and_substituents(work, core_set)
    if split is None:
        return None
    core_mol, substituents = split
    if substituents and not any(atom.GetAtomicNum() == 0 for atom in core_mol.GetAtoms()):
        return None
    if any(_has_unlabeled_dummy(frag) for frag in (core_mol, *substituents)):
        return None
    substituents = sorted(substituents, key=_attachment_sort_key)
    core_smiles = _to_smiles(core_mol)
    if not core_smiles:
        return None
    rgroup_smiles = [_to_smiles(frag) for frag in substituents]
    if any(not smiles for smiles in rgroup_smiles):
        return None
    row = {"Core": core_smiles}
    for index, smiles in enumerate(rgroup_smiles, start=1):
        row[f"R{index}"] = smiles
    return row


def _prepared_copy(mol: Chem.Mol) -> Chem.Mol | None:
    """Sanitized heavy-atom copy. The caller's molecule is left unchanged."""
    try:
        work = Chem.Mol(mol)
        Chem.SanitizeMol(work)
    except _RDKIT_ERRORS:
        return None
    try:
        stripped = Chem.RemoveHs(work)
    except _RDKIT_ERRORS:
        return work
    return work if stripped is None else stripped


def _heavy_atom_indices(mol: Chem.Mol) -> list[int]:
    return [idx for idx in range(mol.GetNumAtoms()) if mol.GetAtomWithIdx(idx).GetAtomicNum() > 1]


def _sssr_rings(mol: Chem.Mol) -> list[tuple[int, ...]]:
    try:
        raw = Chem.GetSymmSSSR(mol)
    except _RDKIT_ERRORS:
        return []
    rings: list[tuple[int, ...]] = []
    for ring in raw:
        idxs = tuple(int(atom) for atom in ring)
        if len(idxs) >= 3:
            rings.append(idxs)
    return rings


def _mean_heavy_distances(mol: Chem.Mol, heavy: list[int]) -> list[float]:
    """Mean topological distance from each atom to every heavy atom."""
    matrix = Chem.GetDistanceMatrix(mol)
    means = [float("inf")] * mol.GetNumAtoms()
    for atom in range(mol.GetNumAtoms()):
        row = matrix[atom]
        total = 0.0
        counted = 0
        for target in heavy:
            value = float(row[target])
            if value < 0:
                continue
            total += value
            counted += 1
        if counted:
            means[atom] = total / counted
    return means


def _ring_system_atoms(rings: list[tuple[int, ...]], chosen: int) -> set[int]:
    """Atoms in every ring that shares an atom, directly or through other rings, with *chosen*."""
    parent = list(range(len(rings)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parent[right_root] = left_root

    atom_sets = [set(ring) for ring in rings]
    for left in range(len(rings)):
        for right in range(left + 1, len(rings)):
            if atom_sets[left] & atom_sets[right]:
                union(left, right)
    root = find(chosen)
    atoms: set[int] = set()
    for index, ring_atoms in enumerate(atom_sets):
        if find(index) == root:
            atoms.update(ring_atoms)
    return atoms


def _cut_bonds(mol: Chem.Mol, core_atoms: set[int]) -> list[int]:
    """Bonds that leave the core for a heavy atom. Hydrogens stay implicit."""
    cuts: list[int] = []
    for bond in mol.GetBonds():
        begin = bond.GetBeginAtomIdx()
        end = bond.GetEndAtomIdx()
        begin_in = begin in core_atoms
        end_in = end in core_atoms
        if begin_in == end_in:
            continue
        outside = end if begin_in else begin
        if mol.GetAtomWithIdx(outside).GetAtomicNum() <= 1:
            continue
        cuts.append(bond.GetIdx())
    return cuts


def _dummy_links(mol: Chem.Mol) -> dict[int, tuple[int, int]]:
    """Map each dummy atom to ``(neighbor index, isotope)``.

    FragmentOnBonds labels a dummy with the atom index on the far side of the
    cut, so the two dummies from one bond point at each other.
    """
    links: dict[int, tuple[int, int]] = {}
    for atom in mol.GetAtoms():
        if atom.GetAtomicNum() != 0:
            continue
        neighbors = atom.GetNeighbors()
        if len(neighbors) != 1:
            continue
        links[atom.GetIdx()] = (neighbors[0].GetIdx(), int(atom.GetIsotope()))
    return links


def _partner(links: dict[int, tuple[int, int]], idx: int) -> int | None:
    neighbor, other = links[idx]
    for candidate, (cand_neighbor, cand_other) in links.items():
        if candidate != idx and cand_neighbor == other and cand_other == neighbor:
            return candidate
    return None


def _label_attachments(
    mol: Chem.Mol,
    core_atoms: set[int],
    links: dict[int, tuple[int, int]],
) -> bool:
    """Write ``[*:1]``, ``[*:2]``, … onto both ends of each cut, in core rank order."""
    core_dummies = [idx for idx, (neighbor, _other) in links.items() if neighbor in core_atoms]
    if not links or len(core_dummies) != len(links) // 2:
        return False
    rank_ids = sorted(core_atoms) + sorted(core_dummies)
    rank_mol, old_to_new = _copy_subset(mol, rank_ids)
    _prepare_for_ranking(rank_mol)
    ranks = list(Chem.CanonicalRankAtoms(rank_mol, breakTies=True, includeChirality=True))
    ordered = sorted(core_dummies, key=lambda idx: ranks[old_to_new[idx]])
    used: set[int] = set()
    for number, idx in enumerate(ordered, start=1):
        partner = _partner(links, idx)
        if partner is None or idx in used or partner in used:
            return False
        used.add(idx)
        used.add(partner)
        mol.GetAtomWithIdx(idx).SetAtomMapNum(number)
        mol.GetAtomWithIdx(partner).SetAtomMapNum(number)
    return len(used) == len(links)


def _copy_subset(mol: Chem.Mol, atom_ids: list[int]) -> tuple[Chem.Mol, dict[int, int]]:
    """Induced subgraph. Dummy isotopes are cleared so they do not affect rank."""
    rw = Chem.RWMol()
    old_to_new: dict[int, int] = {}
    keep = set(atom_ids)
    for old in atom_ids:
        src = mol.GetAtomWithIdx(old)
        atom = Chem.Atom(src)
        atom.SetAtomMapNum(0)
        if atom.GetAtomicNum() == 0:
            atom.SetIsotope(0)
        old_to_new[old] = rw.AddAtom(atom)
    for bond in mol.GetBonds():
        begin = bond.GetBeginAtomIdx()
        end = bond.GetEndAtomIdx()
        if begin not in keep or end not in keep:
            continue
        rw.AddBond(old_to_new[begin], old_to_new[end], bond.GetBondType())
        created = rw.GetBondBetweenAtoms(old_to_new[begin], old_to_new[end])
        if created is not None:
            created.SetIsAromatic(bond.GetIsAromatic())
    return rw.GetMol(), old_to_new


def _prepare_for_ranking(mol: Chem.Mol) -> None:
    try:
        Chem.SanitizeMol(mol)
    except _RDKIT_ERRORS:
        mol.UpdatePropertyCache(strict=False)


def _split_core_and_substituents(
    mol: Chem.Mol,
    core_atoms: set[int],
) -> tuple[Chem.Mol, list[Chem.Mol]] | None:
    """Core fragment plus substituent fragments that carry a dummy atom.

    A fragment that still contains both a core atom and some other heavy atom
    means a substituent was not cut. That decomposition is rejected.
    """
    index_groups = Chem.GetMolFrags(mol)
    frag_mols = Chem.GetMolFrags(mol, asMols=True, sanitizeFrags=False)
    core_mol: Chem.Mol | None = None
    substituents: list[Chem.Mol] = []
    for indices, frag in zip(index_groups, frag_mols, strict=True):
        heavy = [idx for idx in indices if mol.GetAtomWithIdx(idx).GetAtomicNum() > 1]
        if any(idx in core_atoms for idx in heavy):
            if any(idx not in core_atoms for idx in heavy):
                return None
            core_mol = frag
            continue
        if any(mol.GetAtomWithIdx(idx).GetAtomicNum() == 0 for idx in indices):
            substituents.append(frag)
    if core_mol is None:
        return None
    return core_mol, substituents


def _has_unlabeled_dummy(mol: Chem.Mol) -> bool:
    return any(atom.GetAtomicNum() == 0 and atom.GetAtomMapNum() <= 0 for atom in mol.GetAtoms())


def _attachment_sort_key(frag: Chem.Mol) -> tuple[int, int]:
    maps = [
        atom.GetAtomMapNum()
        for atom in frag.GetAtoms()
        if atom.GetAtomicNum() == 0 and atom.GetAtomMapNum() > 0
    ]
    if not maps:
        return (10**9, frag.GetNumAtoms())
    return (min(maps), len(maps))


def _to_smiles(mol: Chem.Mol) -> str:
    copy = Chem.Mol(mol)
    try:
        Chem.SanitizeMol(copy)
    except _RDKIT_ERRORS:
        try:
            Chem.SanitizeMol(
                copy,
                sanitizeOps=Chem.SanitizeFlags.SANITIZE_ALL ^ Chem.SanitizeFlags.SANITIZE_KEKULIZE,
            )
        except _RDKIT_ERRORS:
            copy.UpdatePropertyCache(strict=False)
    try:
        return Chem.MolToSmiles(copy, canonical=True, isomericSmiles=True) or ""
    except _RDKIT_ERRORS:
        return ""
