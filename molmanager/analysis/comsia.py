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

"""CoMSIA fields and PLS (no Qt).

Steric, electrostatic, hydrophobic, and hydrogen-bond fields are Gaussian
similarity indices (Klebe, Abraham, Mietzner, J. Med. Chem. 1994). The series
must already share one coordinate frame (a superpose column or docked poses).
This module uses the first 3D conformer and does not embed or align.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

import numpy as np
from rdkit import Chem
from rdkit.Chem import AllChem, rdMolDescriptors

from ..conformers.conformer_column_codec import conformer_is_3d

# Klebe attenuation, in 1/Å². Similarity falls to about 0.05 by 3 Å.
ALPHA = 0.3
# Distance from the heteroatom to a hydrogen-bond probe, in Å.
PROBE_DISTANCE_ANGSTROM = 1.9
# Leave-one-out needs a spare row beyond the largest component count.
MIN_TRAINING_ROWS = 5
# One field on a 0.5 Å lattice around a large ligand is already tens of thousands of points.
MAX_GRID_POINTS = 64_000
# Smallest component count whose q² is within this of the best leave-one-out score.
COMPONENT_Q2_MARGIN = 0.05

# RDKit BaseFeatures donor / acceptor definitions. Explicit hydrogens count toward H1.
_DONOR_SMARTS = "[$([N;!H0;v3,v4&+1]),$([O,S;H1;+0])]"
_ACCEPTOR_SMARTS = (
    "[$([O,S;H1;v2;!$(*-*=[O,N,P,S])]),$([O,S;H0;v2]),$([O,S;v1;-]),"
    "$([N;v3;!$(N-*=[O,N,P,S])]),$([nH0,o,s;+0])]"
)
_DONOR_QUERY = Chem.MolFromSmarts(_DONOR_SMARTS)
_ACCEPTOR_QUERY = Chem.MolFromSmarts(_ACCEPTOR_SMARTS)

FIELD_ORDER: tuple[str, ...] = (
    "steric",
    "electrostatic",
    "hydrophobic",
    "hbond_donor",
    "hbond_acceptor",
)
FIELD_LABELS: dict[str, str] = {
    "steric": "Steric",
    "electrostatic": "Electrostatic",
    "hydrophobic": "Hydrophobic",
    "hbond_donor": "H-bond donor",
    "hbond_acceptor": "H-bond acceptor",
}


class ComsiaError(ValueError):
    """The series or the grid cannot support a CoMSIA model."""


class ComsiaCancelled(Exception):
    """Leave-one-out or field calculation was cancelled."""


@dataclass
class ComsiaGrid:
    """Regular lattice in the common pose frame."""

    origin: tuple[float, float, float]
    spacing: float
    shape: tuple[int, int, int]
    points: np.ndarray


@dataclass
class ComsiaModel:
    """Fitted CoMSIA PLS model and the grid it was trained on."""

    fields: tuple[str, ...]
    grid: ComsiaGrid
    kept_indices: dict[str, np.ndarray]
    block_scales: dict[str, float]
    n_components: int
    q2_by_components: tuple[float, ...]
    q2: float
    sdep: float
    r2: float
    n_train: int
    pls: Any
    coefficient_grids: dict[str, np.ndarray]
    metrics_text: str


def select_n_components(
    q2_by_components: Sequence[float], *, margin: float = COMPONENT_Q2_MARGIN
) -> int:
    """Smallest component count whose q² is within *margin* of the best score.

    ``q2_by_components[0]`` is the one-component model. Returns a count starting at 1.
    """
    scores = [float(score) for score in q2_by_components]
    if not scores:
        raise ComsiaError("Leave-one-out did not produce a q².")
    best = max(scores)
    for count, score in enumerate(scores, start=1):
        if score >= best - float(margin):
            return count
    return len(scores)


def pose_from_mol(mol: Chem.Mol | None) -> Chem.Mol | None:
    """Copy *mol* down to its first 3D conformer.

    Superpose and docking write the aligned coordinates as that conformer.
    A raw ``confs`` ensemble therefore contributes only its first 3D conformer.
    """
    if mol is None:
        return None
    chosen: Chem.Conformer | None = None
    try:
        conformers = sorted(mol.GetConformers(), key=lambda conf: int(conf.GetId()))
    except (RuntimeError, TypeError, ValueError):
        return None
    for conf in conformers:
        try:
            if conformer_is_3d(conf):
                chosen = conf
                break
        except (RuntimeError, TypeError, ValueError):
            continue
    if chosen is None:
        return None
    try:
        work = Chem.Mol(mol)
        kept = Chem.Conformer(chosen)
        work.RemoveAllConformers()
        work.AddConformer(kept, assignId=True)
    except (RuntimeError, ValueError):
        return None
    with suppress(RuntimeError, ValueError):
        Chem.SanitizeMol(work)
    return work


def probe_positions(mol: Chem.Mol) -> tuple[np.ndarray, np.ndarray]:
    """Donor and acceptor probe coordinates, each ``(n, 3)``.

    Donors sit along explicit hydrogens, or opposite the heavy-atom neighbors when
    the pose has none. Acceptors sit along lone-pair directions derived from the
    bonded geometry, so the probes rotate with the molecule.
    """
    conf = mol.GetConformer()
    donors = _probe_sites(mol, conf, _DONOR_QUERY, _donor_directions)
    acceptors = _probe_sites(mol, conf, _ACCEPTOR_QUERY, _acceptor_directions)
    return donors, acceptors


def fit_comsia(
    mols: Sequence[Chem.Mol],
    activities: Sequence[float],
    *,
    fields: Sequence[str] | None = None,
    spacing: float = 2.0,
    padding: float = 4.0,
    max_components: int = 5,
    sd_fraction: float = 0.01,
    progress: Callable[[str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> ComsiaModel:
    """Fit a CoMSIA PLS model. *mols* must already share one coordinate frame.

    Grid limits, the flat-point filter, and block scaling are fit on the training
    rows only. Leave-one-out refits that filter inside each fold. q² uses the
    mean of all training activities as the total sum of squares. The component
    count is the smallest whose q² is within 0.05 of the best score. The returned
    model is refit on every training row.
    """
    requested = _normalize_fields(fields)
    poses = [pose_from_mol(mol) for mol in mols]
    if any(pose is None for pose in poses):
        raise ComsiaError("Every training row needs a 3D conformer in the shared frame.")
    y = np.asarray(list(activities), dtype=float)
    if y.shape[0] != len(poses):
        raise ComsiaError("Activity values and poses do not match.")
    if y.shape[0] < MIN_TRAINING_ROWS:
        raise ComsiaError(
            f"Need at least {MIN_TRAINING_ROWS} aligned rows with activity ({y.shape[0]} usable)."
        )
    if not np.all(np.isfinite(y)):
        raise ComsiaError("Activity values must be finite numbers.")
    if float(np.std(y)) < 1e-12:
        raise ComsiaError("Activity values are constant.")
    _check_cancelled(cancelled)
    _report(progress, "CoMSIA: building the grid")
    grid = grid_around_mols([pose for pose in poses if pose is not None], spacing, padding)
    _report(progress, "CoMSIA: calculating fields")
    blocks = _field_blocks([pose for pose in poses if pose is not None], grid, requested)
    _check_cancelled(cancelled)

    n_train = int(y.shape[0])
    component_limit = min(int(max_components), n_train - 2)
    if component_limit < 1:
        raise ComsiaError("Need more training rows for leave-one-out.")
    q2_scores: list[float] = []
    loo_predictions: list[np.ndarray] = []
    for n_components in range(1, component_limit + 1):
        _check_cancelled(cancelled)
        _report(progress, f"CoMSIA: leave-one-out, {n_components} component(s)")
        predicted = _loo_predictions(
            blocks,
            y,
            requested,
            n_components,
            sd_fraction,
            cancelled,
        )
        loo_predictions.append(predicted)
        q2_scores.append(_q2(y, predicted))

    chosen = select_n_components(q2_scores)
    chosen_pred = loo_predictions[chosen - 1]
    q2 = float(q2_scores[chosen - 1])
    sdep = float(np.sqrt(np.mean((y - chosen_pred) ** 2)))

    _report(progress, "CoMSIA: fitting the final model")
    row_mask = np.ones(n_train, dtype=bool)
    kept, scales = _column_filter(blocks, row_mask, sd_fraction)
    names = tuple(name for name in requested if name in kept)
    if not names:
        raise ComsiaError("No grid points vary across the training set. Try a finer spacing.")
    design = _design_matrix(blocks, row_mask, names, kept, scales)
    n_fit = min(chosen, design.shape[0] - 1, design.shape[1])
    if n_fit < 1:
        raise ComsiaError("Not enough varying grid points to fit PLS.")
    pls = _new_pls(n_fit)
    pls.fit(design, y)
    fitted = np.asarray(pls.predict(design), dtype=float).ravel()
    r2 = _r2(y, fitted)
    coefficient_grids = _coefficient_grids(pls, names, kept, grid.shape)
    text = _metrics_text(
        fields=names,
        grid=grid,
        n_train=n_train,
        n_components=n_fit,
        q2_scores=q2_scores,
        q2=q2,
        sdep=sdep,
        r2=r2,
        kept=kept,
    )
    return ComsiaModel(
        fields=names,
        grid=grid,
        kept_indices={name: np.asarray(kept[name], dtype=int) for name in names},
        block_scales={name: float(scales[name]) for name in names},
        n_components=n_fit,
        q2_by_components=tuple(float(score) for score in q2_scores),
        q2=q2,
        sdep=sdep,
        r2=r2,
        n_train=n_train,
        pls=pls,
        coefficient_grids=coefficient_grids,
        metrics_text=text,
    )


def predict_comsia(model: ComsiaModel, mols: Sequence[Chem.Mol]) -> np.ndarray:
    """Predict activity for poses in the training frame. Missing 3D yields NaN."""
    out = np.full(len(mols), np.nan, dtype=float)
    usable: list[tuple[int, Chem.Mol]] = []
    for index, mol in enumerate(mols):
        pose = pose_from_mol(mol)
        if pose is not None:
            usable.append((index, pose))
    if not usable:
        return out
    blocks = _field_blocks([pose for _index, pose in usable], model.grid, model.fields)
    design = _design_matrix(
        blocks,
        np.ones(len(usable), dtype=bool),
        model.fields,
        model.kept_indices,
        model.block_scales,
    )
    predicted = np.asarray(model.pls.predict(design), dtype=float).ravel()
    for row, (index, _pose) in enumerate(usable):
        out[index] = float(predicted[row])
    return out


def grid_around_mols(mols: Sequence[Chem.Mol], spacing: float, padding: float) -> ComsiaGrid:
    """Lattice that covers *mols* with *padding* (Å) and a fixed *spacing*."""
    step = float(spacing)
    pad = float(padding)
    if step <= 0.0 or not np.isfinite(step):
        raise ComsiaError("Grid spacing must be a positive number of angstroms.")
    if pad < 0.0 or not np.isfinite(pad):
        raise ComsiaError("Grid padding must be zero or positive.")
    coords = _all_coordinates(mols)
    if coords.size == 0:
        raise ComsiaError("The poses have no coordinates.")
    lows = np.min(coords, axis=0) - pad
    highs = np.max(coords, axis=0) + pad
    origin = np.floor(lows / step) * step
    counts = np.floor((highs - origin) / step).astype(int) + 1
    counts = np.maximum(counts, 1)
    shape = (int(counts[0]), int(counts[1]), int(counts[2]))
    n_points = int(np.prod(shape))
    if n_points > MAX_GRID_POINTS:
        raise ComsiaError(
            f"The grid has {n_points:,} points (limit {MAX_GRID_POINTS:,}). "
            "Increase the spacing or reduce the padding."
        )
    axes = [float(origin[axis]) + np.arange(shape[axis]) * step for axis in range(3)]
    points = np.stack(np.meshgrid(*axes, indexing="ij"), axis=-1).reshape(-1, 3)
    return ComsiaGrid(
        origin=(float(origin[0]), float(origin[1]), float(origin[2])),
        spacing=step,
        shape=shape,
        points=np.ascontiguousarray(points, dtype=float),
    )


def _normalize_fields(fields: Sequence[str] | None) -> tuple[str, ...]:
    requested = tuple(fields) if fields else FIELD_ORDER
    unknown = [name for name in requested if name not in FIELD_LABELS]
    if unknown:
        raise ComsiaError(f"Unknown CoMSIA field(s): {', '.join(unknown)}.")
    if not requested:
        raise ComsiaError("Select at least one CoMSIA field.")
    return requested


def _loo_predictions(
    blocks: Mapping[str, np.ndarray],
    y: np.ndarray,
    field_names: Sequence[str],
    n_components: int,
    sd_fraction: float,
    cancelled: Callable[[], bool] | None,
) -> np.ndarray:
    predicted = np.zeros(y.shape[0], dtype=float)
    for left_out in range(y.shape[0]):
        _check_cancelled(cancelled)
        mask = np.ones(y.shape[0], dtype=bool)
        mask[left_out] = False
        kept, scales = _column_filter(blocks, mask, sd_fraction)
        names = tuple(name for name in field_names if name in kept)
        if not names:
            predicted[left_out] = float(np.mean(y[mask]))
            continue
        design = _design_matrix(blocks, mask, names, kept, scales)
        limit = min(int(n_components), design.shape[0] - 1, design.shape[1])
        if limit < 1:
            predicted[left_out] = float(np.mean(y[mask]))
            continue
        pls = _new_pls(limit)
        pls.fit(design, y[mask])
        held_out = _design_matrix(
            blocks,
            np.asarray([left_out]),
            names,
            kept,
            scales,
        )
        predicted[left_out] = float(np.asarray(pls.predict(held_out), dtype=float).ravel()[0])
    return predicted


def _column_filter(
    blocks: Mapping[str, np.ndarray],
    row_mask: np.ndarray,
    sd_fraction: float,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Drop flat grid points and record one scale per remaining field.

    A point is flat when its standard deviation is below *sd_fraction* of that
    field's standard deviation on *row_mask*. The scale is the standard deviation
    of the kept points, so each field enters PLS with unit pooled variance.
    """
    kept: dict[str, np.ndarray] = {}
    scales: dict[str, float] = {}
    fraction = max(0.0, float(sd_fraction))
    for name, full in blocks.items():
        sample = full[row_mask]
        field_std = float(sample.std())
        if field_std < 1e-12:
            continue
        point_std = sample.std(axis=0)
        idx = np.flatnonzero(point_std > fraction * field_std)
        if idx.size == 0:
            continue
        scale = float(sample[:, idx].std())
        if scale < 1e-12:
            continue
        kept[name] = idx
        scales[name] = scale
    return kept, scales


def _design_matrix(
    blocks: Mapping[str, np.ndarray],
    row_index: np.ndarray,
    names: Sequence[str],
    kept: Mapping[str, np.ndarray],
    scales: Mapping[str, float],
) -> np.ndarray:
    parts = [blocks[name][row_index][:, kept[name]] / float(scales[name]) for name in names]
    return np.hstack(parts)


def _field_blocks(
    mols: Sequence[Chem.Mol],
    grid: ComsiaGrid,
    field_names: Sequence[str],
) -> dict[str, np.ndarray]:
    rows = {name: [] for name in field_names}
    for mol in mols:
        values = _molecule_fields(mol, grid.points, field_names)
        for name in field_names:
            rows[name].append(values[name])
    return {name: np.vstack(chunks) for name, chunks in rows.items()}


def _molecule_fields(
    mol: Chem.Mol,
    points: np.ndarray,
    field_names: Sequence[str],
) -> dict[str, np.ndarray]:
    n_points = int(points.shape[0])
    fields = {name: np.zeros(n_points, dtype=float) for name in field_names}
    conf = mol.GetConformer()
    n_atoms = int(mol.GetNumAtoms())
    coords = np.array([_position(conf, index) for index in range(n_atoms)], dtype=float)
    table = Chem.GetPeriodicTable()
    radii = np.array(
        [
            float(table.GetRvdw(mol.GetAtomWithIdx(index).GetAtomicNum()))
            for index in range(n_atoms)
        ],
        dtype=float,
    )
    charges = _gasteiger_charges(mol, n_atoms)
    hydrophobicity = _crippen_logp(mol, n_atoms)
    if "steric" in fields:
        _accumulate(points, coords, radii**3, fields["steric"])
    if "electrostatic" in fields:
        _accumulate(points, coords, charges, fields["electrostatic"])
    if "hydrophobic" in fields:
        _accumulate(points, coords, hydrophobicity, fields["hydrophobic"])
    donors, acceptors = probe_positions(mol)
    if "hbond_donor" in fields and donors.size:
        _accumulate(points, donors, np.ones(donors.shape[0]), fields["hbond_donor"])
    if "hbond_acceptor" in fields and acceptors.size:
        _accumulate(points, acceptors, np.ones(acceptors.shape[0]), fields["hbond_acceptor"])
    return fields


def _accumulate(
    points: np.ndarray,
    origins: np.ndarray,
    weights: np.ndarray,
    out: np.ndarray,
) -> None:
    for origin, weight in zip(origins, weights, strict=True):
        value = float(weight)
        if value == 0.0 or not np.isfinite(value):
            continue
        distance_sq = np.sum((points - origin) ** 2, axis=1)
        out += value * np.exp(-ALPHA * distance_sq)


def _gasteiger_charges(mol: Chem.Mol, n_atoms: int) -> np.ndarray:
    charges = np.zeros(n_atoms, dtype=float)
    try:
        AllChem.ComputeGasteigerCharges(mol)
    except (RuntimeError, ValueError):
        return charges
    for index, atom in enumerate(mol.GetAtoms()):
        try:
            value = float(atom.GetDoubleProp("_GasteigerCharge"))
        except (KeyError, RuntimeError, ValueError):
            value = 0.0
        if not np.isfinite(value):
            value = 0.0
        charges[index] = value
    return charges


def _crippen_logp(mol: Chem.Mol, n_atoms: int) -> np.ndarray:
    try:
        contribs = rdMolDescriptors._CalcCrippenContribs(mol)
    except (AttributeError, RuntimeError, ValueError):
        return np.zeros(n_atoms, dtype=float)
    if len(contribs) != n_atoms:
        return np.zeros(n_atoms, dtype=float)
    values = np.array([float(contrib[0]) for contrib in contribs], dtype=float)
    return np.nan_to_num(values, nan=0.0, posinf=0.0, neginf=0.0)


def _probe_sites(
    mol: Chem.Mol,
    conf: Chem.Conformer,
    query: Chem.Mol | None,
    directions_for: Callable[[Chem.Mol, Chem.Atom, Chem.Conformer], list[np.ndarray]],
) -> np.ndarray:
    if query is None:
        return np.zeros((0, 3), dtype=float)
    try:
        matches = mol.GetSubstructMatches(query, uniquify=True)
    except (RuntimeError, ValueError):
        return np.zeros((0, 3), dtype=float)
    sites: list[np.ndarray] = []
    for match in matches:
        atom = mol.GetAtomWithIdx(int(match[0]))
        origin = _position(conf, atom.GetIdx())
        for direction in directions_for(mol, atom, conf):
            sites.append(origin + PROBE_DISTANCE_ANGSTROM * direction)
    if not sites:
        return np.zeros((0, 3), dtype=float)
    return np.vstack(sites)


def _donor_directions(mol: Chem.Mol, atom: Chem.Atom, conf: Chem.Conformer) -> list[np.ndarray]:
    del mol
    origin = _position(conf, atom.GetIdx())
    hydrogens: list[np.ndarray] = []
    heavies: list[np.ndarray] = []
    for neighbor in atom.GetNeighbors():
        direction = _unit(_position(conf, neighbor.GetIdx()) - origin)
        if direction is None:
            continue
        if neighbor.GetAtomicNum() == 1:
            hydrogens.append(direction)
        else:
            heavies.append(direction)
    if hydrogens:
        return hydrogens
    if not heavies:
        return []
    inferred = _unit(-np.sum(heavies, axis=0))
    return [inferred] if inferred is not None else []


def _acceptor_directions(mol: Chem.Mol, atom: Chem.Atom, conf: Chem.Conformer) -> list[np.ndarray]:
    origin = _position(conf, atom.GetIdx())
    dirs: list[np.ndarray] = []
    neighbor_ids: list[int] = []
    for neighbor in atom.GetNeighbors():
        if neighbor.GetAtomicNum() == 1:
            continue
        direction = _unit(_position(conf, neighbor.GetIdx()) - origin)
        if direction is None:
            continue
        dirs.append(direction)
        neighbor_ids.append(int(neighbor.GetIdx()))
    if not dirs:
        return []
    if len(dirs) == 1 and (_is_sp(atom) or _bond_is_triple(mol, atom.GetIdx(), neighbor_ids[0])):
        return [-dirs[0]]
    if len(dirs) == 1:
        return _sp2_lone_pairs(mol, atom.GetIdx(), neighbor_ids[0], dirs[0], conf)
    if len(dirs) == 2 and _is_sp2(atom):
        outward = _unit(-(dirs[0] + dirs[1]))
        return [outward] if outward is not None else []
    if len(dirs) == 2:
        return _tetrahedral_lone_pairs(dirs[0], dirs[1])
    outward = _unit(-(dirs[0] + dirs[1] + dirs[2]))
    return [outward] if outward is not None else []


def _sp2_lone_pairs(
    mol: Chem.Mol,
    atom_idx: int,
    neighbor_idx: int,
    bond_direction: np.ndarray,
    conf: Chem.Conformer,
) -> list[np.ndarray]:
    """Two probes in the local plane, 120° apart, bisected by the bond axis."""
    outward = -bond_direction
    tangent = _plane_tangent(mol, atom_idx, neighbor_idx, bond_direction, outward, conf)
    if tangent is None:
        return [outward]
    cosine = 0.5
    sine = float(np.sqrt(3.0) / 2.0)
    return [cosine * outward + sine * tangent, cosine * outward - sine * tangent]


def _plane_tangent(
    mol: Chem.Mol,
    atom_idx: int,
    neighbor_idx: int,
    bond_direction: np.ndarray,
    outward: np.ndarray,
    conf: Chem.Conformer,
) -> np.ndarray | None:
    neighbor = mol.GetAtomWithIdx(neighbor_idx)
    neighbor_pos = _position(conf, neighbor_idx)
    substituent: np.ndarray | None = None
    for other in neighbor.GetNeighbors():
        if other.GetIdx() == atom_idx or other.GetAtomicNum() == 1:
            continue
        substituent = _position(conf, other.GetIdx()) - neighbor_pos
        break
    normal: np.ndarray | None = None
    if substituent is not None:
        normal = np.cross(bond_direction, substituent)
    if normal is None or float(np.linalg.norm(normal)) < 1e-8:
        return _perpendicular(outward)
    return _unit(np.cross(normal, outward))


def _tetrahedral_lone_pairs(first: np.ndarray, second: np.ndarray) -> list[np.ndarray]:
    """Complete a tetrahedron from two unit vectors toward the bonded neighbors."""
    base = -0.5 * (first + second)
    perpendicular = np.cross(first, second)
    hat = _unit(perpendicular)
    length_sq = float(np.dot(base, base))
    if hat is None or length_sq >= 1.0 - 1e-8:
        outward = _unit(-(first + second))
        return [outward] if outward is not None else []
    offset = float(np.sqrt(1.0 - length_sq))
    first_pair = _unit(base + offset * hat)
    second_pair = _unit(base - offset * hat)
    if first_pair is None or second_pair is None:
        outward = _unit(-(first + second))
        return [outward] if outward is not None else []
    return [first_pair, second_pair]


def _is_sp(atom: Chem.Atom) -> bool:
    return atom.GetHybridization() == Chem.HybridizationType.SP


def _is_sp2(atom: Chem.Atom) -> bool:
    return atom.GetHybridization() == Chem.HybridizationType.SP2


def _bond_is_triple(mol: Chem.Mol, atom_idx: int, neighbor_idx: int) -> bool:
    bond = mol.GetBondBetweenAtoms(int(atom_idx), int(neighbor_idx))
    return bond is not None and bond.GetBondType() == Chem.BondType.TRIPLE


def _all_coordinates(mols: Sequence[Chem.Mol]) -> np.ndarray:
    chunks: list[np.ndarray] = []
    for mol in mols:
        conf = mol.GetConformer()
        n_atoms = int(mol.GetNumAtoms())
        if n_atoms == 0:
            continue
        chunks.append(np.array([_position(conf, index) for index in range(n_atoms)], dtype=float))
    if not chunks:
        return np.zeros((0, 3), dtype=float)
    return np.vstack(chunks)


def _coefficient_grids(
    pls: Any,
    names: Sequence[str],
    kept: Mapping[str, np.ndarray],
    shape: tuple[int, int, int],
) -> dict[str, np.ndarray]:
    coef = np.asarray(pls.coef_, dtype=float).ravel()
    n_points = int(np.prod(shape))
    offset = 0
    grids: dict[str, np.ndarray] = {}
    for name in names:
        volume = np.zeros(n_points, dtype=float)
        idx = np.asarray(kept[name], dtype=int)
        width = int(idx.size)
        if offset + width > coef.size:
            break
        volume[idx] = coef[offset : offset + width]
        offset += width
        grids[name] = volume.reshape(shape)
    return grids


def _metrics_text(
    *,
    fields: Sequence[str],
    grid: ComsiaGrid,
    n_train: int,
    n_components: int,
    q2_scores: Sequence[float],
    q2: float,
    sdep: float,
    r2: float,
    kept: Mapping[str, np.ndarray],
) -> str:
    labels = ", ".join(FIELD_LABELS[name] for name in fields)
    nx, ny, nz = grid.shape
    n_points = int(nx * ny * nz)
    score_lines = "\n".join(
        f"  {count} component(s): q² = {score:.4f}"
        for count, score in enumerate(q2_scores, start=1)
    )
    kept_lines = "\n".join(
        f"  {FIELD_LABELS[name]}: {int(np.asarray(kept[name]).size):,} point(s)" for name in fields
    )
    return (
        "CoMSIA\n"
        f"Fields: {labels}\n"
        f"Grid: {grid.spacing:.2f} Å, {nx}×{ny}×{nz} ({n_points:,} points)\n"
        f"Training rows: {n_train}\n"
        f"Components: {n_components} "
        f"(smallest q² within {COMPONENT_Q2_MARGIN:.2f} of the best leave-one-out score)\n"
        f"q² (LOO) = {q2:.4f}\n"
        f"SDEP = {sdep:.4f}\n"
        f"R² (fit) = {r2:.4f}\n"
        "Leave-one-out q² by component count:\n"
        f"{score_lines}\n"
        "Grid points kept:\n"
        f"{kept_lines}"
    )


def _q2(y: np.ndarray, predicted: np.ndarray) -> float:
    press = float(np.sum((y - predicted) ** 2))
    tss = float(np.sum((y - np.mean(y)) ** 2))
    if tss < 1e-12:
        return 0.0
    return 1.0 - press / tss


def _r2(y: np.ndarray, predicted: np.ndarray) -> float:
    return _q2(y, predicted)


def _new_pls(n_components: int) -> Any:
    from sklearn.cross_decomposition import PLSRegression

    return PLSRegression(n_components=int(n_components), scale=False)


def _position(conf: Chem.Conformer, index: int) -> np.ndarray:
    point = conf.GetAtomPosition(int(index))
    return np.array([float(point.x), float(point.y), float(point.z)], dtype=float)


def _unit(vector: np.ndarray) -> np.ndarray | None:
    length = float(np.linalg.norm(vector))
    if length < 1e-8:
        return None
    return np.asarray(vector, dtype=float) / length


def _perpendicular(vector: np.ndarray) -> np.ndarray | None:
    axis = int(np.argmin(np.abs(vector)))
    helper = np.zeros(3, dtype=float)
    helper[axis] = 1.0
    return _unit(np.cross(vector, helper))


def _report(progress: Callable[[str], None] | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled is not None and cancelled():
        raise ComsiaCancelled
