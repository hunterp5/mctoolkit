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

"""Trajectory frames and observable arithmetic."""

from pathlib import Path

import numpy as np
import pytest

from molmanager.sim.document import Observable
from molmanager.sim.observables import evaluate_observable, mmgbsa_delta, rmsf_per_residue
from molmanager.sim.selection import AtomRecord
from molmanager.sim.trajectory import read_dcd_xyz, solute_multimodel_pdb, write_dcd


def _atoms():
    return [
        AtomRecord(0, "CA", "ALA", "A", 1, element="C", kind="protein", x=0, y=0, z=0),
        AtomRecord(1, "CA", "ALA", "A", 2, element="C", kind="protein", x=3, y=0, z=0),
        AtomRecord(2, "C1", "LIG", "B", 1, element="C", kind="ligand", x=1, y=2, z=0),
    ]


def test_dcd_roundtrip_and_solute_pdb(tmp_path: Path):
    frame0 = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1.0, 2.0, 0.0]])
    frame1 = frame0.copy()
    frame1[2, 0] += 2.0
    xyz = np.stack([frame0, frame1], axis=0)
    path = tmp_path / "traj.dcd"
    write_dcd(path, xyz)
    again = read_dcd_xyz(path)
    assert again.shape == (2, 3, 3)
    assert again[1, 2, 0] == pytest.approx(3.0)
    pdb = solute_multimodel_pdb(_atoms(), xyz, solute_atoms=2, stride=1, cap=10)
    assert pdb.count("MODEL") == 2
    assert "LIG" not in pdb


def test_rmsd_uses_ca_fit_and_mmgbsa_omits_entropy():
    atoms = _atoms()
    frame0 = np.array([[0.0, 0.0, 0.0], [3.0, 0.0, 0.0], [1.0, 2.0, 0.0]], dtype=float)
    frame1 = frame0.copy()
    frame1[2, 0] += 2.0
    xyz = np.stack([frame0, frame1])
    values = evaluate_observable(
        Observable(id="rmsd", kind="rmsd", selection="ligand", fit_selection="ca"),
        atoms,
        xyz,
    )
    assert values[0] == pytest.approx(0.0)
    assert values[1] == pytest.approx(2.0)
    delta = mmgbsa_delta(-10.0, -3.0, -4.0, vdw=-2.0, eel=-1.0, egb=0.5, esurf=0.1, bonded=0.0)
    assert delta["dG"] == pytest.approx(-3.0)
    assert "entropy" not in delta
    rows = rmsf_per_residue(atoms, np.stack([frame0, frame0]), "ca")
    assert rows
    assert all(row[2] == pytest.approx(0.0) for row in rows)
