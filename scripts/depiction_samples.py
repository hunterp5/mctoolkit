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

"""Molecule inputs and summary statistics shared by the depiction scripts."""

from __future__ import annotations

import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from rdkit import Chem  # noqa: E402

#: First RDKit release the project supports; older builds draw differently.
MIN_RDKIT_RELEASE = (2025, 9)


@dataclass(frozen=True)
class DepictionSample:
    name: str
    category: str
    mol: Chem.Mol


def load_depiction_samples(path: str | Path, limit: int = 0) -> list[DepictionSample]:
    """Molecules from an SDF / SD / molfile, or from a ``smiles, name, category`` TSV.

    SDF files go through the app's own reader, so hydrogens and coordinates match what
    the table would draw. A *limit* of 0 reads everything.
    """
    source = Path(path)
    samples: list[DepictionSample] = []
    if source.suffix.lower() == ".tsv":
        with source.open(encoding="utf-8", newline="") as fh:
            for row in csv.DictReader(fh, delimiter="\t"):
                mol = Chem.MolFromSmiles(row["smiles"])
                if mol is not None:
                    samples.append(DepictionSample(row["name"], row.get("category", ""), mol))
                if limit and len(samples) >= limit:
                    break
        return samples

    from molmanager.chem.molecule_conversion import safe_mol_prop_string
    from molmanager.table.table_file_formats import iter_sdf_mols

    for index, mol in enumerate(iter_sdf_mols(source)):
        name = safe_mol_prop_string(mol, "_Name").strip()
        samples.append(DepictionSample(name or f"row_{index}", "", mol))
        if limit and len(samples) >= limit:
            break
    return samples


def rdkit_release_ok() -> bool:
    """True when the running RDKit is at least :data:`MIN_RDKIT_RELEASE`."""
    from rdkit import __version__

    parts = __version__.split(".")
    try:
        return (int(parts[0]), int(parts[1])) >= MIN_RDKIT_RELEASE
    except (IndexError, ValueError):
        return False


def summarize(values: list[float], digits: int = 3) -> dict[str, float]:
    """Mean, median, 95th percentile, and maximum of *values* (zeros when empty)."""
    if not values:
        return {"mean": 0.0, "median": 0.0, "p95": 0.0, "max": 0.0}
    ordered = sorted(values)
    n = len(ordered)
    return {
        "mean": round(sum(ordered) / n, digits),
        "median": round(ordered[n // 2], digits),
        "p95": round(ordered[min(n - 1, int(n * 0.95))], digits),
        "max": round(ordered[-1], digits),
    }
