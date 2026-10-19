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

"""Geometric hydrogen-bond detection for Protein Viewer overlays."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from .structure_components import (
    AMINO_ACIDS,
    POLAR_HEAVY_ELEMENTS,
    StructureAtom,
    parse_structure_atoms,
    _dist_sq,
    _is_hydrogen,
    _residue_kinds_from_atoms,
)

HBOND_KIND_PROTEIN = "protein"
HBOND_KIND_LIGAND = "ligand"
HBOND_KIND_COMPLEX = "complex"
HBOND_KINDS = (HBOND_KIND_PROTEIN, HBOND_KIND_LIGAND, HBOND_KIND_COMPLEX)

HBOND_COLORS = {
    HBOND_KIND_PROTEIN: "#E6C229",
    HBOND_KIND_LIGAND: "#00B4D8",
    HBOND_KIND_COMPLEX: "#2ECC71",
}

# Baker–Hubbard-like cutoffs. A residue that already has explicit hydrogens
# donates only from atoms that carry one. Residues with no hydrogens fall back
# to heavy-atom distances, except sulfonyl and N-oxide oxygens, which are not donors.
HBOND_DA_MAX = 3.5
HBOND_DA_MIN = 2.3
HBOND_HA_MAX = 2.5
HBOND_DHA_MIN_DEG = 120.0
HBOND_PARENT_DA_MIN_DEG = 90.0

_DONOR_ELEMENTS = frozenset({"N", "O", "S"})
_ACCEPTOR_ELEMENTS = frozenset({"N", "O", "S", "F"})
_BOND_TOLERANCE = 0.45
_COVALENT_RADII = {
    "H": 0.31,
    "D": 0.31,
    "C": 0.76,
    "N": 0.71,
    "O": 0.66,
    "F": 0.57,
    "P": 1.07,
    "S": 1.05,
    "SE": 1.20,
    "CL": 1.02,
    "BR": 1.20,
    "I": 1.39,
    "B": 0.84,
    "SI": 1.11,
}

_BACKBONE_DONOR = frozenset({"N"})
_BACKBONE_ACCEPTOR = frozenset({"O", "OXT", "OT1", "OT2", "OC1", "OC2"})

_SIDECHAIN_DONOR = {
    "ARG": frozenset({"NE", "NH1", "NH2"}),
    "ASN": frozenset({"ND2"}),
    "GLN": frozenset({"NE2"}),
    "HIS": frozenset({"ND1", "NE2"}),
    "HID": frozenset({"ND1"}),
    "HIE": frozenset({"NE2"}),
    "HIP": frozenset({"ND1", "NE2"}),
    "LYS": frozenset({"NZ"}),
    "LYN": frozenset({"NZ"}),
    "SER": frozenset({"OG"}),
    "THR": frozenset({"OG1"}),
    "TRP": frozenset({"NE1"}),
    "TYR": frozenset({"OH"}),
    "CYS": frozenset({"SG"}),
    "ASH": frozenset({"OD2"}),
    "GLH": frozenset({"OE2"}),
    "HYP": frozenset({"OD1"}),
    "SEP": frozenset({"OG"}),
    "TPO": frozenset({"OG1"}),
    "PTR": frozenset({"OH"}),
    "MLY": frozenset({"NZ"}),
}

_SIDECHAIN_ACCEPTOR = {
    "ASN": frozenset({"OD1"}),
    "ASP": frozenset({"OD1", "OD2"}),
    "GLN": frozenset({"OE1"}),
    "GLU": frozenset({"OE1", "OE2"}),
    "HIS": frozenset({"ND1", "NE2"}),
    "HID": frozenset({"NE2"}),
    "HIE": frozenset({"ND1"}),
    "SER": frozenset({"OG"}),
    "THR": frozenset({"OG1"}),
    "TYR": frozenset({"OH"}),
    "CYS": frozenset({"SG"}),
    "MET": frozenset({"SD"}),
    "MSE": frozenset({"SE"}),
    "ASH": frozenset({"OD1"}),
    "GLH": frozenset({"OE1"}),
    "HYP": frozenset({"OD1"}),
    "SEP": frozenset({"OG", "O1P", "O2P", "O3P", "OP1", "OP2", "OP3"}),
    "TPO": frozenset({"OG1", "O1P", "O2P", "O3P", "OP1", "OP2", "OP3"}),
    "PTR": frozenset({"OH", "O1P", "O2P", "O3P", "OP1", "OP2", "OP3"}),
}


@dataclass(frozen=True)
class HydrogenBond:
    """One donor–acceptor contact with coordinates for a 3Dmol dashed cylinder."""

    kind: str
    start: tuple[float, float, float]
    end: tuple[float, float, float]
    distance: float
    angle: float | None
    has_hydrogen: bool
    donor_chain: str
    donor_resn: str
    donor_resi: str
    donor_icode: str
    donor_name: str
    donor_kind: str
    acceptor_chain: str
    acceptor_resn: str
    acceptor_resi: str
    acceptor_icode: str
    acceptor_name: str
    acceptor_kind: str
    model: int | None = None

    def to_payload(self, color: str | None = None) -> dict:
        """JSON object consumed by the Protein Viewer hydrogen-bond overlay."""
        payload = {
            "kind": self.kind,
            "color": color or HBOND_COLORS.get(self.kind, "#E6C229"),
            "start": {"x": self.start[0], "y": self.start[1], "z": self.start[2]},
            "end": {"x": self.end[0], "y": self.end[1], "z": self.end[2]},
            "distance": round(self.distance, 3),
            "angle": None if self.angle is None else round(self.angle, 1),
            "hasHydrogen": self.has_hydrogen,
            "donor": _atom_ref(
                self.donor_chain,
                self.donor_resn,
                self.donor_resi,
                self.donor_icode,
                self.donor_name,
                self.donor_kind,
            ),
            "acceptor": _atom_ref(
                self.acceptor_chain,
                self.acceptor_resn,
                self.acceptor_resi,
                self.acceptor_icode,
                self.acceptor_name,
                self.acceptor_kind,
            ),
        }
        if self.kind == HBOND_KIND_COMPLEX:
            residue = _polymer_partner_residue(self)
            if residue:
                payload["showResidues"] = [residue]
        return payload


def detect_hydrogen_bonds(
    text: str,
    fmt: str,
    *,
    model: int | None = None,
) -> tuple[HydrogenBond, ...]:
    """Return protein, ligand, and protein–ligand hydrogen bonds in *text*."""
    atoms = parse_structure_atoms(text, fmt)
    return detect_hydrogen_bonds_from_atoms(atoms, model=model)


def detect_hydrogen_bonds_from_atoms(
    atoms: Iterable[StructureAtom],
    *,
    model: int | None = None,
) -> tuple[HydrogenBond, ...]:
    """Detect hydrogen bonds from already-parsed coordinate atoms."""
    atom_list = list(atoms)
    if len(atom_list) < 2:
        return ()
    kinds = _residue_kinds_from_atoms(atom_list)
    neighbors = _covalent_neighbors(atom_list)
    forbidden = _forbidden_pairs(neighbors)
    donors = _donor_sites(atom_list, kinds, neighbors)
    acceptors = _acceptor_indices(atom_list, kinds, neighbors)
    if not donors or not acceptors:
        return ()
    acc_grid = _spatial_grid([atom_list[i] for i in acceptors], HBOND_DA_MAX)
    acc_lookup = {id(atom_list[i]): i for i in acceptors}
    best: dict[frozenset[int], HydrogenBond] = {}
    for heavy_i, hydrogen_i in donors:
        donor = atom_list[heavy_i]
        probe = atom_list[hydrogen_i] if hydrogen_i is not None else donor
        for acc_atom in _grid_neighbors(acc_grid, probe, HBOND_DA_MAX):
            acc_i = acc_lookup.get(id(acc_atom))
            if acc_i is None or acc_i == heavy_i:
                continue
            if (heavy_i, acc_i) in forbidden or (acc_i, heavy_i) in forbidden:
                continue
            bond = _try_bond(
                atom_list,
                kinds,
                neighbors,
                heavy_i,
                hydrogen_i,
                acc_i,
                model=model,
            )
            if bond is None:
                continue
            key = frozenset({heavy_i, acc_i})
            prev = best.get(key)
            if prev is None or _bond_better(bond, prev):
                best[key] = bond
    return tuple(
        sorted(
            best.values(),
            key=lambda b: (b.kind, b.donor_chain, b.donor_resi, b.acceptor_chain, b.acceptor_resi),
        )
    )


def _atom_ref(chain: str, resn: str, resi: str, icode: str, name: str, kind: str) -> dict[str, str]:
    return {
        "chain": chain,
        "resn": resn,
        "resi": resi,
        "icode": icode,
        "name": name,
        "kind": kind,
    }


def _residue_key(atom: StructureAtom) -> tuple[str, str, str, str]:
    return (atom.chain, atom.resn, atom.resi, atom.icode)


def _covalent_cutoff(elem_a: str, elem_b: str) -> float:
    ra = _COVALENT_RADII.get(elem_a, 0.8)
    rb = _COVALENT_RADII.get(elem_b, 0.8)
    return ra + rb + _BOND_TOLERANCE


def _covalent_neighbors(atoms: list[StructureAtom]) -> list[list[int]]:
    neighbors: list[list[int]] = [[] for _ in atoms]
    if not atoms:
        return neighbors
    cell = 2.0
    grid: dict[tuple[int, int, int], list[int]] = {}
    for i, atom in enumerate(atoms):
        key = (
            math.floor(atom.x / cell),
            math.floor(atom.y / cell),
            math.floor(atom.z / cell),
        )
        grid.setdefault(key, []).append(i)
    for i, atom in enumerate(atoms):
        ix, iy, iz = (
            math.floor(atom.x / cell),
            math.floor(atom.y / cell),
            math.floor(atom.z / cell),
        )
        for jx in (ix - 1, ix, ix + 1):
            for jy in (iy - 1, iy, iy + 1):
                for jz in (iz - 1, iz, iz + 1):
                    for j in grid.get((jx, jy, jz), ()):
                        if j <= i:
                            continue
                        other = atoms[j]
                        cutoff = _covalent_cutoff(atom.elem, other.elem)
                        if _dist_sq(atom, other) <= cutoff * cutoff:
                            neighbors[i].append(j)
                            neighbors[j].append(i)
    return neighbors


def _forbidden_pairs(neighbors: list[list[int]]) -> set[tuple[int, int]]:
    """1–2 and 1–3 covalently bonded pairs (not hydrogen bonds)."""
    out: set[tuple[int, int]] = set()
    for i, bonded in enumerate(neighbors):
        for j in bonded:
            out.add((i, j))
            for k in neighbors[j]:
                if k != i:
                    out.add((i, k))
    return out


def _spatial_grid(
    atoms: list[StructureAtom], cell: float
) -> dict[tuple[int, int, int], list[StructureAtom]]:
    grid: dict[tuple[int, int, int], list[StructureAtom]] = {}
    for atom in atoms:
        key = (
            math.floor(atom.x / cell),
            math.floor(atom.y / cell),
            math.floor(atom.z / cell),
        )
        grid.setdefault(key, []).append(atom)
    return grid


def _grid_neighbors(
    grid: dict[tuple[int, int, int], list[StructureAtom]],
    atom: StructureAtom,
    radius: float,
) -> list[StructureAtom]:
    ix = math.floor(atom.x / radius)
    iy = math.floor(atom.y / radius)
    iz = math.floor(atom.z / radius)
    out: list[StructureAtom] = []
    for jx in (ix - 1, ix, ix + 1):
        for jy in (iy - 1, iy, iy + 1):
            for jz in (iz - 1, iz, iz + 1):
                out.extend(grid.get((jx, jy, jz), ()))
    return out


def _polar_hydrogen_neighbors(
    atoms: list[StructureAtom], neighbors: list[list[int]], i: int
) -> list[int]:
    return [
        j for j in neighbors[i] if _is_hydrogen(atoms[j]) and atoms[i].elem in POLAR_HEAVY_ELEMENTS
    ]


def _heavy_neighbors(atoms: list[StructureAtom], neighbors: list[list[int]], i: int) -> list[int]:
    return [j for j in neighbors[i] if not _is_hydrogen(atoms[j])]


def _protein_donor_names(resn: str) -> frozenset[str]:
    names = set(_SIDECHAIN_DONOR.get(resn, ()))
    if resn != "PRO":
        names |= _BACKBONE_DONOR
    return frozenset(names)


def _protein_acceptor_names(resn: str) -> frozenset[str]:
    return frozenset(_BACKBONE_ACCEPTOR | _SIDECHAIN_ACCEPTOR.get(resn, frozenset()))


def _donor_sites(
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    neighbors: list[list[int]],
) -> list[tuple[int, int | None]]:
    protonated = _protonated_residue_keys(atoms)
    sites: list[tuple[int, int | None]] = []
    for i, atom in enumerate(atoms):
        if _is_hydrogen(atom) or atom.elem not in _DONOR_ELEMENTS:
            continue
        kind = kinds.get(_residue_key(atom), "")
        if kind in {"water", "metal"}:
            continue
        hydrogens = _polar_hydrogen_neighbors(atoms, neighbors, i)
        n_heavy = len(_heavy_neighbors(atoms, neighbors, i))
        if kind == "polymer" and atom.resn in AMINO_ACIDS:
            if atom.name not in _protein_donor_names(atom.resn) and not hydrogens:
                continue
        elif not _ligand_is_donor(atom, n_heavy, hydrogens):
            continue
        if hydrogens:
            sites.extend((i, h) for h in hydrogens)
            continue
        if kind != "polymer" and _residue_key(atom) in protonated:
            continue
        if kind != "polymer" and not _implicit_heavy_donor(atoms, neighbors, i):
            continue
        sites.append((i, None))
    return sites


def _acceptor_indices(
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    neighbors: list[list[int]],
) -> list[int]:
    out: list[int] = []
    for i, atom in enumerate(atoms):
        if _is_hydrogen(atom) or atom.elem not in _ACCEPTOR_ELEMENTS:
            continue
        kind = kinds.get(_residue_key(atom), "")
        if kind in {"water", "metal"}:
            continue
        hydrogens = _polar_hydrogen_neighbors(atoms, neighbors, i)
        n_heavy = len(_heavy_neighbors(atoms, neighbors, i))
        if kind == "polymer" and atom.resn in AMINO_ACIDS:
            if atom.name not in _protein_acceptor_names(atom.resn):
                continue
        elif not _ligand_is_acceptor(atom, n_heavy, len(hydrogens)):
            continue
        out.append(i)
    return out


def _ligand_is_donor(atom: StructureAtom, n_heavy: int, hydrogens: list[int]) -> bool:
    if hydrogens:
        return atom.elem in _DONOR_ELEMENTS
    if atom.elem == "N":
        return n_heavy <= 2
    if atom.elem == "O":
        return n_heavy <= 1
    if atom.elem == "S":
        return n_heavy <= 1
    return False


def _protonated_residue_keys(atoms: list[StructureAtom]) -> set[tuple[str, str, str, str]]:
    """Residues that already carry explicit hydrogens."""
    return {_residue_key(atom) for atom in atoms if _is_hydrogen(atom)}


def _implicit_heavy_donor(
    atoms: list[StructureAtom],
    neighbors: list[list[int]],
    index: int,
) -> bool:
    """Whether a hydrogen-free ligand atom may still donate.

    Sulfonyl, sulfoxide, sulfate, and nitrogen-bound oxygens donate only when a
    hydrogen is actually present. A hydroxyl oxygen on carbon stays eligible so
    crystal structures without hydrogens can still match.
    """
    atom = atoms[index]
    if atom.elem != "O":
        return True
    return all(atoms[j].elem not in {"S", "N"} for j in _heavy_neighbors(atoms, neighbors, index))


def _polymer_partner_residue(bond: HydrogenBond) -> dict[str, str | int] | None:
    """Protein residue to draw when a geometric protein–ligand bond is shown."""
    if bond.donor_kind == "polymer":
        chain, resn, resi, icode = (
            bond.donor_chain,
            bond.donor_resn,
            bond.donor_resi,
            bond.donor_icode,
        )
    elif bond.acceptor_kind == "polymer":
        chain, resn, resi, icode = (
            bond.acceptor_chain,
            bond.acceptor_resn,
            bond.acceptor_resi,
            bond.acceptor_icode,
        )
    else:
        return None
    if not str(resi).strip() and not (chain or resn):
        return None
    record: dict[str, str | int] = {
        "chain": chain,
        "resn": resn,
        "resi": str(resi),
        "icode": icode or "",
    }
    if bond.model is not None:
        record["model"] = bond.model
    return record


def _ligand_is_acceptor(atom: StructureAtom, n_heavy: int, n_h: int) -> bool:
    if atom.elem == "O":
        return n_heavy <= 2
    if atom.elem == "N":
        return n_heavy <= 2 and n_h == 0
    if atom.elem == "S":
        return n_heavy <= 2
    if atom.elem == "F":
        return True
    return False


def _kind_for_pair(donor_kind: str, acceptor_kind: str) -> str | None:
    pair = {donor_kind, acceptor_kind}
    if pair == {"polymer"}:
        return HBOND_KIND_PROTEIN
    if pair == {"ligand"}:
        return HBOND_KIND_LIGAND
    if pair == {"polymer", "ligand"}:
        return HBOND_KIND_COMPLEX
    return None


def _is_backbone_hbond_atom(atom: StructureAtom) -> bool:
    return atom.name in (_BACKBONE_DONOR | _BACKBONE_ACCEPTOR)


def _adjacent_backbone(donor: StructureAtom, acceptor: StructureAtom) -> bool:
    if donor.chain != acceptor.chain:
        return False
    if not (_is_backbone_hbond_atom(donor) and _is_backbone_hbond_atom(acceptor)):
        return False
    try:
        gap = abs(int(donor.resi) - int(acceptor.resi))
    except ValueError:
        return donor.resi == acceptor.resi and donor.icode == acceptor.icode
    return gap <= 1


def _angle_at(vertex: StructureAtom, a: StructureAtom, c: StructureAtom) -> float | None:
    vax = a.x - vertex.x
    vay = a.y - vertex.y
    vaz = a.z - vertex.z
    vcx = c.x - vertex.x
    vcy = c.y - vertex.y
    vcz = c.z - vertex.z
    na = math.sqrt(vax * vax + vay * vay + vaz * vaz)
    nc = math.sqrt(vcx * vcx + vcy * vcy + vcz * vcz)
    if na < 1e-6 or nc < 1e-6:
        return None
    cosang = (vax * vcx + vay * vcy + vaz * vcz) / (na * nc)
    cosang = max(-1.0, min(1.0, cosang))
    return math.degrees(math.acos(cosang))


def _try_bond(
    atoms: list[StructureAtom],
    kinds: dict[tuple[str, str, str, str], str],
    neighbors: list[list[int]],
    donor_i: int,
    hydrogen_i: int | None,
    acceptor_i: int,
    *,
    model: int | None,
) -> HydrogenBond | None:
    donor = atoms[donor_i]
    acceptor = atoms[acceptor_i]
    donor_kind = kinds.get(_residue_key(donor), "")
    acceptor_kind = kinds.get(_residue_key(acceptor), "")
    kind = _kind_for_pair(donor_kind, acceptor_kind)
    if kind is None:
        return None
    if _adjacent_backbone(donor, acceptor):
        return None
    da = math.sqrt(_dist_sq(donor, acceptor))
    if da > HBOND_DA_MAX:
        return None
    angle: float | None = None
    if hydrogen_i is not None:
        hydrogen = atoms[hydrogen_i]
        ha = math.sqrt(_dist_sq(hydrogen, acceptor))
        if ha > HBOND_HA_MAX:
            return None
        angle = _angle_at(hydrogen, donor, acceptor)
        if angle is None or angle < HBOND_DHA_MIN_DEG:
            return None
        start = (hydrogen.x, hydrogen.y, hydrogen.z)
        distance = ha
        has_hydrogen = True
    else:
        if da < HBOND_DA_MIN:
            return None
        parents = _heavy_neighbors(atoms, neighbors, donor_i)
        parent_angles: list[float] = []
        for parent_i in parents:
            if parent_i == acceptor_i:
                continue
            parent_ang = _angle_at(donor, atoms[parent_i], acceptor)
            if parent_ang is not None:
                parent_angles.append(parent_ang)
        if parent_angles:
            angle = max(parent_angles)
            if angle < HBOND_PARENT_DA_MIN_DEG:
                return None
        start = (donor.x, donor.y, donor.z)
        distance = da
        has_hydrogen = False
    return HydrogenBond(
        kind=kind,
        start=start,
        end=(acceptor.x, acceptor.y, acceptor.z),
        distance=distance,
        angle=angle,
        has_hydrogen=has_hydrogen,
        donor_chain=donor.chain,
        donor_resn=donor.resn,
        donor_resi=donor.resi,
        donor_icode=donor.icode,
        donor_name=donor.name,
        donor_kind=donor_kind,
        acceptor_chain=acceptor.chain,
        acceptor_resn=acceptor.resn,
        acceptor_resi=acceptor.resi,
        acceptor_icode=acceptor.icode,
        acceptor_name=acceptor.name,
        acceptor_kind=acceptor_kind,
        model=model,
    )


def _bond_better(candidate: HydrogenBond, previous: HydrogenBond) -> bool:
    if candidate.has_hydrogen != previous.has_hydrogen:
        return candidate.has_hydrogen
    return candidate.distance < previous.distance
