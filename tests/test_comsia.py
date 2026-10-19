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

"""CoMSIA fields, probe geometry, and PLS (no protein viewer)."""

from __future__ import annotations

from contextlib import suppress

import numpy as np
import pytest
from rdkit import Chem

from molmanager.analysis.comsia import (
    ComsiaError,
    fit_comsia,
    grid_around_mols,
    pose_from_mol,
    predict_comsia,
    probe_positions,
    select_n_components,
)
from molmanager.reference.help_markdown import load_help_markdown
from molmanager.ui.main_window.menu_spec import MAIN_WINDOW_MENUS, find_submenu


def test_component_count_prefers_the_smallest_near_best_score():
    assert select_n_components([0.20, 0.50, 0.52, 0.53]) == 2
    assert select_n_components([0.10]) == 1
    assert select_n_components([-0.40, -0.05, -0.02]) == 2


def test_carbonyl_acceptor_probes_follow_the_molecule():
    mol = _acetone()
    _assert_carbonyl_angles(mol)
    rotated = _rotate_z(mol, 90.0)
    _assert_carbonyl_angles(rotated)


def test_hydroxyl_donor_probe_follows_the_hydrogen():
    mol = _methanol()
    donors, _acceptors = probe_positions(mol)
    assert donors.shape == (1, 3)
    oxygen = _coord(mol, 0)
    hydrogen = _coord(mol, 2)
    probe_dir = donors[0] - oxygen
    hydrogen_dir = hydrogen - oxygen
    assert _angle_deg(probe_dir, hydrogen_dir) < 1.0


def test_ether_lone_pairs_leave_the_bond_plane():
    mol = _dimethyl_ether()
    _donors, acceptors = probe_positions(mol)
    assert acceptors.shape[0] == 2
    assert acceptors[0, 2] * acceptors[1, 2] < 0.0


def test_shifted_atom_activity_is_recovered():
    mols = [_carbon_at(float(index)) for index in range(8)]
    activities = [float(index) for index in range(8)]
    model = fit_comsia(
        mols,
        activities,
        fields=("steric",),
        spacing=1.0,
        padding=2.0,
        max_components=3,
        sd_fraction=0.0,
    )
    assert model.n_train == 8
    assert model.q2 > 0.5
    assert model.r2 > 0.9
    assert model.coefficient_grids["steric"].shape == model.grid.shape
    coef = np.array(model.pls.coef_, copy=True)
    far = _carbon_at(40.0)
    predicted = predict_comsia(model, [far, mols[3]])
    assert np.isfinite(predicted).all()
    assert abs(float(predicted[1]) - 3.0) < 1.0
    assert np.allclose(model.pls.coef_, coef)


def test_prediction_set_does_not_move_the_training_grid():
    mols = [_carbon_at(float(index)) for index in range(6)]
    activities = [float(index) for index in range(6)]
    trained = grid_around_mols(mols, 2.0, 2.0)
    with_outlier = grid_around_mols([*mols, _carbon_at(80.0)], 2.0, 2.0)
    assert trained.shape != with_outlier.shape
    model = fit_comsia(
        mols,
        activities,
        fields=("steric",),
        spacing=2.0,
        padding=2.0,
        max_components=2,
        sd_fraction=0.0,
    )
    assert model.grid.shape == trained.shape


def test_grid_point_cap():
    mols = [_carbon_at(0.0), _carbon_at(80.0)]
    with pytest.raises(ComsiaError, match="grid"):
        grid_around_mols(mols, 0.5, 8.0)


def test_pose_keeps_the_first_3d_conformer():
    mol = Chem.Mol(_carbon_at(0.0))
    flat = Chem.Conformer(1)
    flat.SetAtomPosition(0, (5.0, 0.0, 0.0))
    mol.AddConformer(flat, assignId=True)
    pose = pose_from_mol(mol)
    assert pose is not None
    assert pose.GetNumConformers() == 1
    assert abs(float(pose.GetConformer().GetAtomPosition(0).x)) < 1e-6


def test_menu_help_and_pose_preference():
    from molmanager.ui.dialogs.comsia import _preferred_pose_column

    data = find_submenu(MAIN_WINDOW_MENUS, "Data")
    qsar = find_submenu(data.items, "QSAR")
    assert qsar.items[2].slot == "open_comsia_dialog"
    text = load_help_markdown("data_comsia")
    assert text is not None
    assert "leave-one-out" in text.lower()
    assert _preferred_pose_column(["confs", "poses", "superpose (1)"]) == "superpose (1)"
    assert _preferred_pose_column(["confs", "poses"]) == "poses"


def test_comsia_dialog_opens(qapp) -> None:  # noqa: ARG001
    from rdkit import Chem

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure", "SMILES", "pIC50", "superpose"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(0, {"SMILES": "CCO", "pIC50": "5.0", "superpose": ""})
    window.mols[0] = Chem.MolFromSmiles("CCO")
    window.next_oid = 1
    window.open_comsia_dialog()
    dialog = window._comsia_dialog
    assert dialog is not None
    assert dialog.pose_combo.findText("superpose") >= 0
    dialog.close()


def _assert_carbonyl_angles(mol: Chem.Mol) -> None:
    _donors, acceptors = probe_positions(mol)
    assert acceptors.shape[0] == 2
    carbon = _coord(mol, 1)
    oxygen = _coord(mol, 0)
    outward = oxygen - carbon
    relative = acceptors - oxygen
    assert np.max(np.abs(relative[:, 2])) < 1e-6
    angles = sorted(_angle_deg(outward, row) for row in relative)
    assert angles[0] == pytest.approx(60.0, abs=1.0)
    assert angles[1] == pytest.approx(60.0, abs=1.0)


def _acetone() -> Chem.Mol:
    # Oxygen, carbonyl carbon, two methyl carbons. The carbonyl lies on x in the xy plane.
    return _mol(
        [
            ("O", (1.22, 0.0, 0.0)),
            ("C", (0.0, 0.0, 0.0)),
            ("C", (-0.75, 1.25, 0.0)),
            ("C", (-0.75, -1.25, 0.0)),
        ],
        [(0, 1, Chem.BondType.DOUBLE), (1, 2, Chem.BondType.SINGLE), (1, 3, Chem.BondType.SINGLE)],
    )


def _methanol() -> Chem.Mol:
    return _mol(
        [("O", (0.0, 0.0, 0.0)), ("C", (-1.43, 0.0, 0.0)), ("H", (0.30, 0.92, 0.0))],
        [(0, 1, Chem.BondType.SINGLE), (0, 2, Chem.BondType.SINGLE)],
    )


def _dimethyl_ether() -> Chem.Mol:
    return _mol(
        [("O", (0.0, 0.0, 0.0)), ("C", (1.16, 0.72, 0.0)), ("C", (-1.16, 0.72, 0.0))],
        [(0, 1, Chem.BondType.SINGLE), (0, 2, Chem.BondType.SINGLE)],
    )


def _carbon_at(x: float) -> Chem.Mol:
    return _mol([("C", (x, 0.0, 0.0))], [])


def _mol(atoms: list[tuple[str, tuple[float, float, float]]], bonds: list[tuple]) -> Chem.Mol:
    rw = Chem.RWMol()
    for symbol, _xyz in atoms:
        rw.AddAtom(Chem.Atom(symbol))
    for begin, end, order in bonds:
        rw.AddBond(int(begin), int(end), order)
    mol = rw.GetMol()
    conf = Chem.Conformer(mol.GetNumAtoms())
    for index, (_symbol, xyz) in enumerate(atoms):
        conf.SetAtomPosition(index, xyz)
    conf.Set3D(True)
    mol.AddConformer(conf, assignId=True)
    with suppress(RuntimeError, ValueError):
        Chem.SanitizeMol(mol)
    return mol


def _rotate_z(mol: Chem.Mol, degrees: float) -> Chem.Mol:
    theta = np.deg2rad(degrees)
    rotation = np.array(
        [[np.cos(theta), -np.sin(theta), 0.0], [np.sin(theta), np.cos(theta), 0.0], [0.0, 0.0, 1.0]]
    )
    atoms: list[tuple[str, tuple[float, float, float]]] = []
    conf = mol.GetConformer()
    for index, atom in enumerate(mol.GetAtoms()):
        point = conf.GetAtomPosition(index)
        rotated = rotation @ np.array([point.x, point.y, point.z], dtype=float)
        atoms.append((atom.GetSymbol(), (float(rotated[0]), float(rotated[1]), float(rotated[2]))))
    bonds = []
    for bond in mol.GetBonds():
        bonds.append((bond.GetBeginAtomIdx(), bond.GetEndAtomIdx(), bond.GetBondType()))
    return _mol(atoms, bonds)


def _coord(mol: Chem.Mol, index: int) -> np.ndarray:
    point = mol.GetConformer().GetAtomPosition(index)
    return np.array([point.x, point.y, point.z], dtype=float)


def _angle_deg(first: np.ndarray, second: np.ndarray) -> float:
    cosine = float(np.dot(first, second) / (np.linalg.norm(first) * np.linalg.norm(second)))
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))
