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

"""RDKit conformers for Uni-pKa, without importing PyTorch.

The record layout matches ``unipkainfer.pka_predictor.free_energy`` (11 coordinates:
10 MMFF conformers plus one 2D fallback). Keeping it here lets preprocess workers
stay small while one other process loads the model.
"""

from __future__ import annotations

import os
from collections.abc import Sequence

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem
from rdkit.Chem.rdchem import Mol

# unipkainfer.pka_predictor.free_energy.UNIPKA_CONF_SIZE
_CONF_SIZE = 11
_GEN_MODE = "mmff"
_PREPROCESS_CHILD_ENV = "MOLMANAGER_UNIPKA_PREPROCESS_CHILD"


def unmapped_smiles(mol: Mol) -> str:
    """Same SMILES key Uni-pKa uses to dedupe a scoring batch."""
    mol_copy = Chem.Mol(mol)
    for atom in mol_copy.GetAtoms():
        atom.SetAtomMapNum(0)
    mol_copy = Chem.RemoveHs(mol_copy)
    smiles = Chem.MolToSmiles(mol_copy, isomericSmiles=True)
    if not smiles:
        raise ValueError("Could not convert RDKit molecule to SMILES.")
    return smiles


def _scaffold(smi: str) -> str:
    from rdkit.Chem.Scaffolds import MurckoScaffold

    try:
        return MurckoScaffold.MurckoScaffoldSmiles(smiles=smi, includeChirality=True)
    except (ValueError, RuntimeError):
        return smi


def _coords_2d(smi: str) -> np.ndarray:
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smi}")
    mol = AllChem.AddHs(mol)
    AllChem.Compute2DCoords(mol)
    return mol.GetConformer().GetPositions().astype(np.float32)


def _coords_3d(smi: str, conformer_count: int, num_threads: int) -> list[np.ndarray]:
    if conformer_count == 0:
        return []
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smi}")
    mol = AllChem.AddHs(mol)
    try:
        conf_ids = list(
            AllChem.EmbedMultipleConfs(
                mol,
                numConfs=conformer_count,
                randomSeed=0,
                numThreads=num_threads,
            )
        )
        AllChem.MMFFOptimizeMoleculeConfs(mol, numThreads=num_threads)
    except (ValueError, RuntimeError):
        conf_ids = []
    coordinates = [
        mol.GetConformer(int(conf_id)).GetPositions().astype(np.float32) for conf_id in conf_ids
    ]
    fallback = _coords_2d(smi)
    coordinates.extend(fallback.copy() for _ in range(conformer_count - len(coordinates)))
    return coordinates


def record_for_smiles(smi: str, *, nthreads: int = 1) -> dict[str, object]:
    """One LMDB row: atoms, charges, coordinates, and the hydrogen-added mol."""
    conformer_count = _CONF_SIZE - 1
    scaffold = _scaffold(smi)
    mol = Chem.MolFromSmiles(smi)
    if mol is None:
        raise ValueError(f"Could not parse SMILES: {smi}")
    if len(mol.GetAtoms()) > 400:
        coordinates = [_coords_2d(smi)] * (conformer_count + 1)
    else:
        coordinates = _coords_3d(smi, conformer_count, max(1, int(nthreads)))
        coordinates.append(_coords_2d(smi))
    mol_h = AllChem.AddHs(mol)
    return {
        "atoms": [atom.GetSymbol() for atom in mol_h.GetAtoms()],
        "charges": [atom.GetFormalCharge() for atom in mol_h.GetAtoms()],
        "coordinates": coordinates,
        "mol": mol_h,
        "smi": smi,
        "scaffold": scaffold,
        "target": -1.0,
    }


def _preprocess_one(smi: str) -> dict[str, object]:
    """Process-pool entry. One MMFF thread; the pool supplies the parallelism."""
    os.environ[_PREPROCESS_CHILD_ENV] = "1"
    return record_for_smiles(smi, nthreads=1)


def records_for_mols(
    mols: Sequence[Mol],
    *,
    nthreads: int = 1,
    parallel_workers: int = 1,
    on_record=None,
) -> dict[str, dict[str, object]]:
    """Map each distinct Uni-pKa SMILES to a conformer record.

    *parallel_workers* above 1 uses child processes that do not import PyTorch.
    """
    smiles: list[str] = []
    seen: set[str] = set()
    for mol in mols:
        smi = unmapped_smiles(mol)
        if smi not in seen:
            seen.add(smi)
            smiles.append(smi)
    workers = max(1, int(parallel_workers))
    child = os.environ.get(_PREPROCESS_CHILD_ENV) == "1"
    if workers <= 1 or len(smiles) < 4 or child:
        out = {smi: record_for_smiles(smi, nthreads=nthreads) for smi in smiles}
        if on_record is not None:
            for _smi in smiles:
                on_record()
        return out

    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    ctx = multiprocessing.get_context("spawn")
    out: dict[str, dict[str, object]] = {}
    with ProcessPoolExecutor(max_workers=min(workers, len(smiles)), mp_context=ctx) as ex:
        for smi, rec in zip(smiles, ex.map(_preprocess_one, smiles)):
            out[smi] = rec
            if on_record is not None:
                on_record()
    return out
