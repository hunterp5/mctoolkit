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

"""Vacuum GAFF/GAFF2 minimization for stochastic ETKDG conformers."""

from __future__ import annotations

import tempfile
import threading
from pathlib import Path

from rdkit import Chem

from .chemistry_worker_common import normalize_force_field
from .protein_prepare_amber import (
    _amber_missing_message,
    _amber_resn,
    _formal_charge,
    _gaff_atom_type,
    _normalize_ligand_ff,
    _parameterize_ligand,
    _proc_tail,
    _require_ambertools,
    amber_program,
    ligand_only_leap_input,
)
from .protein_prepare_ligand import write_ligand_mol2

_TLEAP_TIMEOUT_S = 180.0
_MAX_MAP_DIST_A = 0.75
_OPENMM_MISSING = (
    "GAFF/GAFF2 conformer minimization needs OpenMM.\n  pip install 'openmm>=8.2,<8.3'"
)


def map_coords_by_element(
    src_z: list[int],
    src_xyz: list[tuple[float, float, float]],
    dest_z: list[int],
    dest_xyz: list[tuple[float, float, float]],
    *,
    max_dist_a: float = _MAX_MAP_DIST_A,
) -> list[int]:
    """Map each source atom onto a unique destination atom of the same element.

    Returns ``dest_index`` for each source atom. Raises ``ValueError`` when the
    counts differ or the nearest unused match exceeds *max_dist_a*.
    """
    n = len(src_z)
    if n != len(src_xyz) or n != len(dest_z) or n != len(dest_xyz):
        raise ValueError(
            f"GAFF topology atom count mismatch ({n} vs {len(dest_z)}). "
            "Antechamber may have added or removed atoms."
        )
    used: set[int] = set()
    mapping: list[int] = [-1] * n
    max_d2 = float(max_dist_a) * float(max_dist_a)
    for i, z in enumerate(src_z):
        sx, sy, sz_ = src_xyz[i]
        best_j = -1
        best_d2 = max_d2 + 1.0
        for j, dz in enumerate(dest_z):
            if j in used or int(dz) != int(z):
                continue
            dx = sx - dest_xyz[j][0]
            dy = sy - dest_xyz[j][1]
            dzc = sz_ - dest_xyz[j][2]
            d2 = dx * dx + dy * dy + dzc * dzc
            if d2 < best_d2:
                best_d2 = d2
                best_j = j
        if best_j < 0 or best_d2 > max_d2:
            raise ValueError(
                "Could not match RDKit atoms to the AmberTools topology. "
                "Try regenerating with explicit hydrogens."
            )
        used.add(best_j)
        mapping[i] = best_j
    return mapping


def _mol_single_conf(mol: Chem.Mol, conf_id: int) -> Chem.Mol:
    out = Chem.Mol(mol)
    keep = int(conf_id)
    for cid in sorted((int(c.GetId()) for c in out.GetConformers()), reverse=True):
        if cid != keep:
            out.RemoveConformer(cid)
    return out


def _rdkit_xyz(mol: Chem.Mol, conf_id: int) -> tuple[list[int], list[tuple[float, float, float]]]:
    conf = mol.GetConformer(int(conf_id))
    zs: list[int] = []
    xyz: list[tuple[float, float, float]] = []
    for atom in mol.GetAtoms():
        zs.append(int(atom.GetAtomicNum()))
        p = conf.GetAtomPosition(atom.GetIdx())
        xyz.append((float(p.x), float(p.y), float(p.z)))
    return zs, xyz


def _openmm_xyz(topology, positions) -> tuple[list[int], list[tuple[float, float, float]]]:
    from openmm import unit

    zs: list[int] = []
    xyz: list[tuple[float, float, float]] = []
    for atom in topology.atoms():
        element = getattr(atom, "element", None)
        z = int(getattr(element, "atomic_number", 0) or 0)
        pos = positions[atom.index].value_in_unit(unit.angstrom)
        zs.append(z)
        xyz.append((float(pos[0]), float(pos[1]), float(pos[2])))
    return zs, xyz


def _require_openmm() -> None:
    try:
        import openmm  # noqa: F401
        from openmm.app import AmberPrmtopFile  # noqa: F401
    except ImportError as exc:
        raise RuntimeError(_OPENMM_MISSING) from exc


def _build_ligand_prmtop(
    mol: Chem.Mol,
    *,
    ligand_ff: str,
    work_dir: Path,
) -> tuple[Path, Path]:
    """Write MOL2, run antechamber/parmchk2/tleap, return prmtop and inpcrd."""
    from ..platform_support.wsl_launcher import run_linux_tool

    ff = _normalize_ligand_ff(ligand_ff)
    atom_type = _gaff_atom_type(ff)
    resn = _amber_resn("LIG")
    stem = "lig0"
    cids = [int(c.GetId()) for c in mol.GetConformers()]
    if not cids:
        raise RuntimeError("GAFF minimization needs a 3D conformer.")
    write_ligand_mol2(
        _mol_single_conf(mol, cids[0]),
        work_dir / f"{stem}.mol2",
        resn=resn,
        resi="1",
    )
    _parameterize_ligand(
        stem,
        charge=_formal_charge(mol),
        atom_type=atom_type,
        resn=resn,
        work_dir=work_dir,
    )
    prmtop = work_dir / "lig.prmtop"
    inpcrd = work_dir / "lig.inpcrd"
    leap_in = work_dir / "leap.in"
    leap_in.write_text(
        ligand_only_leap_input(
            mol2=f"{stem}_gaff.mol2",
            frcmod=f"{stem}.frcmod",
            ligand_ff=ff,
            prmtop=prmtop.name,
            inpcrd=inpcrd.name,
        ),
        encoding="utf-8",
        newline="\n",
    )
    try:
        proc = run_linux_tool(
            [amber_program("tleap"), "-f", leap_in.name],
            work_dir=work_dir,
            timeout=_TLEAP_TIMEOUT_S,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(_amber_missing_message()) from exc
    leap_log = ""
    log_path = work_dir / "leap.log"
    if log_path.is_file():
        leap_log = log_path.read_text(encoding="utf-8", errors="replace")
    if proc.returncode != 0 or not prmtop.is_file() or not inpcrd.is_file():
        raise RuntimeError(
            "AmberTools tleap failed to build a ligand topology. " + _proc_tail(proc, leap_log)
        )
    return prmtop, inpcrd


def _rdkit_conf_to_openmm(conf: Chem.Conformer, rdkit_to_omm: list[int]):
    from openmm import Vec3, unit

    xyz = [Vec3(0.0, 0.0, 0.0) for _ in rdkit_to_omm]
    for r_i, omm_i in enumerate(rdkit_to_omm):
        p = conf.GetAtomPosition(r_i)
        xyz[omm_i] = Vec3(float(p.x), float(p.y), float(p.z))
    return xyz * unit.angstrom


def _apply_openmm_positions(conf: Chem.Conformer, positions, rdkit_to_omm: list[int]) -> None:
    from openmm import unit

    for r_i, omm_i in enumerate(rdkit_to_omm):
        xyz = positions[omm_i].value_in_unit(unit.angstrom)
        conf.SetAtomPosition(r_i, (float(xyz[0]), float(xyz[1]), float(xyz[2])))


def optimize_conformer_energies_gaff(
    mol: Chem.Mol,
    force_field: str,
    max_iterations: int,
    cancel_event: threading.Event | None = None,
) -> tuple[list[float], str]:
    """Minimize every conformer in vacuum with GAFF or GAFF2; energies in kcal/mol."""
    ff_tag = normalize_force_field(force_field)
    if ff_tag not in {"GAFF", "GAFF2"}:
        raise ValueError(f"Not a GAFF force field: {force_field}")
    _require_ambertools()
    _require_openmm()
    from openmm import LangevinMiddleIntegrator, unit
    from openmm.app import AmberInpcrdFile, AmberPrmtopFile, NoCutoff

    from .protein_prepare_minimize import _create_openmm_simulation

    cids = [int(c.GetId()) for c in mol.GetConformers()]
    if not cids:
        raise RuntimeError("GAFF minimization needs a 3D conformer.")
    max_it = max(1, int(max_iterations))
    with tempfile.TemporaryDirectory(prefix="mm_gaff_conf_") as tmp:
        work = Path(tmp)
        prmtop_path, inpcrd_path = _build_ligand_prmtop(mol, ligand_ff=ff_tag, work_dir=work)
        prmtop = AmberPrmtopFile(str(prmtop_path))
        inpcrd = AmberInpcrdFile(str(inpcrd_path))
        system = prmtop.createSystem(nonbondedMethod=NoCutoff, constraints=None)
        src_z, src_xyz = _rdkit_xyz(mol, cids[0])
        dest_z, dest_xyz = _openmm_xyz(prmtop.topology, inpcrd.positions)
        rdkit_to_omm = map_coords_by_element(src_z, src_xyz, dest_z, dest_xyz)
        integrator = LangevinMiddleIntegrator(
            300 * unit.kelvin, 1.0 / unit.picosecond, 0.002 * unit.picoseconds
        )
        try:
            simulation = _create_openmm_simulation(
                prmtop.topology, system, integrator, preferred="CPU"
            )
        except RuntimeError:
            simulation = _create_openmm_simulation(
                prmtop.topology, system, integrator, preferred="Reference"
            )
        energies: list[float] = []
        for cid in cids:
            if cancel_event is not None and cancel_event.is_set():
                raise RuntimeError("cancelled")
            conf = mol.GetConformer(int(cid))
            simulation.context.setPositions(_rdkit_conf_to_openmm(conf, rdkit_to_omm))
            simulation.minimizeEnergy(maxIterations=max_it)
            state = simulation.context.getState(getEnergy=True, getPositions=True)
            energy = float(state.getPotentialEnergy().value_in_unit(unit.kilocalories_per_mole))
            energies.append(energy)
            _apply_openmm_positions(conf, state.getPositions(), rdkit_to_omm)
        return energies, ff_tag
