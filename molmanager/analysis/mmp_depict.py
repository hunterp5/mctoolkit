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

"""Atom highlights for pair drawings (MMP and SALI): atoms outside the MCS."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import rdFMCS


def highlight_atoms_for_pair(
    mol_a: Chem.Mol,
    mol_b: Chem.Mol,
) -> tuple[list[int], list[int]]:
    """
    Return atom indices to highlight on each molecule (variable / non-MCS atoms).

    Falls back to empty lists when MCS cannot be found.
    """
    if mol_a is None or mol_b is None:
        return [], []
    try:
        res = rdFMCS.FindMCS(
            [mol_a, mol_b],
            timeout=1,
            matchValences=True,
            ringMatchesRingOnly=True,
            completeRingsOnly=False,
        )
    except (RuntimeError, ValueError, TypeError):
        return [], []
    if res is None or res.canceled or res.numAtoms < 1 or not res.smartsString:
        return [], []
    try:
        query = Chem.MolFromSmarts(res.smartsString)
    except (RuntimeError, ValueError, TypeError):
        return [], []
    if query is None:
        return [], []

    def _variable_atoms(mol: Chem.Mol) -> list[int]:
        matches = mol.GetSubstructMatches(query)
        if not matches:
            return []
        common = set(matches[0])
        return [int(a.GetIdx()) for a in mol.GetAtoms() if int(a.GetIdx()) not in common]

    return _variable_atoms(mol_a), _variable_atoms(mol_b)
