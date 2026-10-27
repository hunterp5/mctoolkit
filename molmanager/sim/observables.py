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

"""Measurements on a trajectory. MM/GBSA here is a ranking score and omits -TΔS."""

from __future__ import annotations

import csv
import math
from pathlib import Path

import numpy as np

from .document import Observable
from .selection import AtomRecord, select_atom_indices

_HYDROGEN = frozenset({"H", "D"})
_POLAR = frozenset({"N", "O"})


def kabsch_rotation(
    mobile: np.ndarray, target: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Return ``(R, mobile_com, target_com)`` so ``(mobile - mc) @ R + tc`` matches *target*."""
    points = np.asarray(mobile, dtype=float)
    reference = np.asarray(target, dtype=float)
    if (
        points.shape != reference.shape
        or points.ndim != 2
        or points.shape[1] != 3
        or points.shape[0] == 0
    ):
        raise ValueError("Kabsch needs matching Nx3 coordinates.")
    mobile_com = points.mean(axis=0)
    target_com = reference.mean(axis=0)
    if points.shape[0] == 1:
        return np.eye(3), mobile_com, target_com
    centered_mobile = points - mobile_com
    centered_target = reference - target_com
    left, _values, right = np.linalg.svd(centered_mobile.T @ centered_target)
    rotation = right.T @ left.T
    if np.linalg.det(rotation) < 0.0:
        right = right.copy()
        right[-1, :] *= -1.0
        rotation = right.T @ left.T
    return rotation, mobile_com, target_com


def apply_kabsch(
    xyz: np.ndarray,
    rotation: np.ndarray,
    mobile_com: np.ndarray,
    target_com: np.ndarray,
) -> np.ndarray:
    """Apply a Kabsch fit to every atom of one frame."""
    return (np.asarray(xyz, dtype=float) - mobile_com) @ rotation + target_com


def rmsd(left: np.ndarray, right: np.ndarray) -> float:
    """Root-mean-square distance in the same units as the coordinates."""
    diff = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    count = diff.shape[0]
    if count <= 0:
        return float("nan")
    return float(math.sqrt(float((diff * diff).sum()) / count))


def radius_of_gyration(xyz: np.ndarray) -> float:
    """Rg about the center of mass, unweighted."""
    points = np.asarray(xyz, dtype=float)
    if points.shape[0] == 0:
        return float("nan")
    center = points.mean(axis=0)
    delta = points - center
    return float(math.sqrt(float((delta * delta).sum()) / points.shape[0]))


def mmgbsa_delta(
    e_complex: float,
    e_receptor: float,
    e_ligand: float,
    *,
    vdw: float = 0.0,
    eel: float = 0.0,
    egb: float = 0.0,
    esurf: float = 0.0,
    bonded: float = 0.0,
) -> dict[str, float]:
    """1-trajectory Δ = E(complex) − E(receptor) − E(ligand). Entropy is not included."""
    total = float(e_complex) - float(e_receptor) - float(e_ligand)
    return {
        "dG": total,
        "vdw": float(vdw),
        "eel": float(eel),
        "egb": float(egb),
        "esurf": float(esurf),
        "bonded": float(bonded),
        "ggas": float(vdw) + float(eel) + float(bonded),
        "gsolv": float(egb) + float(esurf),
        "E_complex": float(e_complex),
        "E_receptor": float(e_receptor),
        "E_ligand": float(e_ligand),
    }


def count_contacts(
    atoms: list[AtomRecord],
    xyz: np.ndarray,
    selection: list[int],
    *,
    cutoff_a: float,
) -> int:
    """Heavy-atom pairs between *selection* and the rest of the solute within *cutoff_a*."""
    selected = set(selection)
    others = [
        atom.index
        for atom in atoms
        if atom.index not in selected and _element(atom) not in _HYDROGEN
    ]
    chosen = [index for index in selection if _element(atoms[index]) not in _HYDROGEN]
    return _pair_count(xyz, chosen, others, cutoff_a, minimum=0.0)


def count_hydrogen_bonds(
    atoms: list[AtomRecord],
    xyz: np.ndarray,
    selection: list[int],
    *,
    cutoff_a: float = 3.5,
) -> int:
    """Polar N/O pairs between *selection* and the rest of the structure.

    Pairs closer than 2 Å are treated as bonds and are not counted. This is a
    geometric ranking count, recorded separately from a ProLIF interaction fingerprint.
    """
    selected = set(selection)
    donors = [index for index in selection if _element(atoms[index]) in _POLAR]
    acceptors = [
        atom.index for atom in atoms if atom.index not in selected and _element(atom) in _POLAR
    ]
    return _pair_count(xyz, donors, acceptors, cutoff_a, minimum=2.0)


def evaluate_observable(
    observable: Observable,
    atoms: list[AtomRecord],
    xyz: np.ndarray,
) -> list[float]:
    """One value per frame. ``nan`` is written when a pick matches no atoms."""
    coords = np.asarray(xyz, dtype=float)
    values: list[float] = []
    for frame_index in range(coords.shape[0]):
        values.append(_frame_value(observable, atoms, coords, frame_index))
    return values


def rmsf_per_residue(
    atoms: list[AtomRecord],
    xyz: np.ndarray,
    selection: str,
) -> list[tuple[str, int, float]]:
    """Cα (or the selection) RMSF after a Kabsch fit of that selection to frame 0."""
    coords = np.asarray(xyz, dtype=float)
    indices = select_atom_indices(selection, atoms)
    if len(indices) < 1 or coords.shape[0] < 2:
        return []
    fitted = _fit_frames(coords, indices)
    grouped: dict[tuple[str, int, str], list[int]] = {}
    for index in indices:
        atom = atoms[index]
        grouped.setdefault((atom.chain, atom.resi, atom.resname), []).append(index)
    rows: list[tuple[str, int, float]] = []
    for (chain, resi, _resname), members in grouped.items():
        stack = fitted[:, members, :]
        mean = stack.mean(axis=0)
        delta = stack - mean
        value = float(math.sqrt(float((delta * delta).sum()) / stack.shape[0] / len(members)))
        rows.append((chain, resi, value))
    return rows


def write_series_csv(
    path: str | Path, times_ps: list[float], columns: dict[str, list[float]]
) -> None:
    """Write ``time_ps`` plus one column per observable."""
    dest = Path(path)
    headers = ["time_ps", *columns.keys()]
    with dest.open("w", encoding="utf-8", newline="\n") as handle:
        writer = csv.writer(handle)
        writer.writerow(headers)
        width = len(times_ps)
        for row_index in range(width):
            writer.writerow(
                [f"{times_ps[row_index]:.4f}"]
                + [_csv_num(columns[name][row_index]) for name in columns]
            )


def _frame_value(
    observable: Observable, atoms: list[AtomRecord], coords: np.ndarray, frame: int
) -> float:
    kind = observable.kind
    if kind == "rmsd":
        return _rmsd_frame(observable, atoms, coords, frame)
    if kind == "rg":
        indices = select_atom_indices(observable.selection, atoms)
        if not indices:
            return float("nan")
        return radius_of_gyration(coords[frame, indices, :])
    if kind == "distance":
        return _angle_like(atoms, coords[frame], (observable.atom_a, observable.atom_b), kind)
    if kind in {"angle", "dihedral"}:
        picks = (observable.atom_a, observable.atom_b, observable.atom_c)
        if kind == "dihedral":
            picks = (*picks, observable.atom_d)
        return _angle_like(atoms, coords[frame], picks, kind)
    if kind == "contacts":
        indices = select_atom_indices(observable.selection, atoms)
        return float(count_contacts(atoms, coords[frame], indices, cutoff_a=observable.cutoff_a))
    if kind == "hbond":
        indices = select_atom_indices(observable.selection, atoms)
        return float(count_hydrogen_bonds(atoms, coords[frame], indices))
    if kind in {"rmsf", "mmgbsa"}:
        return float("nan")
    return float("nan")


def _rmsd_frame(
    observable: Observable, atoms: list[AtomRecord], coords: np.ndarray, frame: int
) -> float:
    indices = select_atom_indices(observable.selection, atoms)
    if not indices:
        return float("nan")
    if frame == 0:
        return 0.0
    mobile = coords[frame]
    reference = coords[0]
    fit = (
        select_atom_indices(observable.fit_selection, atoms)
        if observable.fit_selection.strip()
        else []
    )
    if len(fit) >= 1:
        rotation, mobile_com, target_com = kabsch_rotation(mobile[fit], reference[fit])
        mobile = apply_kabsch(mobile, rotation, mobile_com, target_com)
    return rmsd(mobile[indices], reference[indices])


def _fit_frames(coords: np.ndarray, indices: list[int]) -> np.ndarray:
    fitted = np.array(coords, copy=True)
    reference = coords[0, indices, :]
    for frame in range(1, coords.shape[0]):
        rotation, mobile_com, target_com = kabsch_rotation(coords[frame, indices, :], reference)
        fitted[frame] = apply_kabsch(coords[frame], rotation, mobile_com, target_com)
    return fitted


def _angle_like(atoms, frame, picks: tuple[str, ...], kind: str) -> float:
    points = []
    for expression in picks:
        if not expression.strip():
            return float("nan")
        indices = select_atom_indices(expression, atoms)
        if len(indices) != 1:
            return float("nan")
        points.append(frame[indices[0]])
    if kind == "distance":
        delta = points[0] - points[1]
        return float(math.sqrt(float((delta * delta).sum())))
    if kind == "angle":
        return _angle_degrees(points[0], points[1], points[2])
    return _dihedral_degrees(points[0], points[1], points[2], points[3])


def _angle_degrees(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    left = a - b
    right = c - b
    denom = float(np.linalg.norm(left) * np.linalg.norm(right))
    if denom == 0.0:
        return float("nan")
    cosine = float(np.dot(left, right) / denom)
    cosine = min(1.0, max(-1.0, cosine))
    return float(math.degrees(math.acos(cosine)))


def _dihedral_degrees(a, b, c, d) -> float:
    b0 = a - b
    b1 = c - b
    b2 = d - c
    normal_1 = np.cross(b0, b1)
    normal_2 = np.cross(b1, b2)
    denom = float(np.linalg.norm(normal_1) * np.linalg.norm(normal_2))
    if denom == 0.0:
        return float("nan")
    cosine = min(1.0, max(-1.0, float(np.dot(normal_1, normal_2) / denom)))
    sign = float(np.dot(b0, normal_2))
    angle = math.degrees(math.acos(cosine))
    return angle if sign >= 0.0 else -angle


def _pair_count(xyz, left: list[int], right: list[int], cutoff: float, minimum: float) -> int:
    if not left or not right:
        return 0
    limit = cutoff * cutoff
    floor = minimum * minimum
    count = 0
    for i in left:
        xi, yi, zi = xyz[i]
        for j in right:
            dx = xi - float(xyz[j][0])
            dy = yi - float(xyz[j][1])
            dz = zi - float(xyz[j][2])
            dist = dx * dx + dy * dy + dz * dz
            if floor < dist <= limit:
                count += 1
    return count


def _element(atom: AtomRecord) -> str:
    if atom.element:
        return atom.element.strip().upper()
    name = atom.name.strip().upper()
    return "H" if name.startswith("H") else name[:1]


def _csv_num(value: float) -> str:
    if value != value:
        return ""
    return f"{value:.6g}"
