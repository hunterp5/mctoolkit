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

"""OpenMM restrained protein minimization for Protein Prepare."""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from pathlib import Path

from .protein_prepare_amber import (
    _ligand_ff_is_gaff,
    _normalize_ligand_ff,
)
from .protein_prepare_constants import (
    _GB_SALT_M,
    _GB_SOLVENT_DIELECTRIC,
    _GB_TEMPERATURE_K,
    _LIGAND_FF_NONE,
    _OPENMM_PLATFORM_AUTO,
    _PROTEIN_FF_AMBER14,
    _PROTEIN_FF_AMBER99,
    _RESTRAINT_BACKBONE,
    _RESTRAINT_BACKBONE_LIGAND,
    _RESTRAINT_CA,
    _SOLVENT_GBN2,
    _SOLVENT_OBC2,
    _SOLVENT_VACUUM,
    ResidueKey,
)
from .protein_prepare_io import (
    _ca_residue_keys,
    _is_cif_fmt,
    _ligand_residue_names,
    _residue_key,
    _write_openmm_structure,
    log_prepare,
)


def _gb_kappa_per_nm(
    *,
    salt_m: float = _GB_SALT_M,
    temperature_k: float = _GB_TEMPERATURE_K,
    solvent_dielectric: float = _GB_SOLVENT_DIELECTRIC,
) -> float:
    """Debye κ (nm⁻¹) from 1:1 salt molarity. OpenMM's 50.33355 conversion at *temperature_k*."""
    if salt_m <= 0:
        return 0.0
    return 50.33355 * math.sqrt(float(salt_m) / float(solvent_dielectric) / float(temperature_k))


def _normalize_protein_ff(name: str) -> str:
    raw = (name or _PROTEIN_FF_AMBER14).strip().lower()
    if raw in {_PROTEIN_FF_AMBER99, "amber99", "ff99sbildn"}:
        return _PROTEIN_FF_AMBER99
    return _PROTEIN_FF_AMBER14


def _normalize_solvent(name: str) -> str:
    raw = (name or _SOLVENT_GBN2).strip().lower()
    if raw in {_SOLVENT_VACUUM, "none", "vac"}:
        return _SOLVENT_VACUUM
    if raw in {_SOLVENT_OBC2, "obc", "gbsa-obc"}:
        return _SOLVENT_OBC2
    return _SOLVENT_GBN2


def _normalize_openmm_platform(name: str) -> str:
    raw = (name or _OPENMM_PLATFORM_AUTO).strip()
    env = (os.environ.get("MOLMANAGER_OPENMM_PLATFORM") or "").strip()
    if not raw or raw.lower() == _OPENMM_PLATFORM_AUTO:
        raw = env or _OPENMM_PLATFORM_AUTO
    key = raw.lower()
    if key in {_OPENMM_PLATFORM_AUTO, "gpu"}:
        return _OPENMM_PLATFORM_AUTO
    if key in {"cuda"}:
        return "CUDA"
    if key in {"opencl"}:
        return "OpenCL"
    if key in {"cpu"}:
        return "CPU"
    if key in {"reference"}:
        return "Reference"
    return raw


def _openmm_platform_names() -> list[str]:
    import openmm

    return [
        openmm.Platform.getPlatform(i).getName() for i in range(openmm.Platform.getNumPlatforms())
    ]


def _cpu_thread_count() -> int:
    n = os.cpu_count() or 1
    return max(1, n - 1) if n > 1 else 1


def _openmm_platform_properties(name: str) -> dict[str, str]:
    if name == "CUDA":
        return {"CudaPrecision": "single"}
    if name == "OpenCL":
        return {"OpenCLPrecision": "single"}
    if name == "CPU":
        return {"Threads": str(_cpu_thread_count())}
    return {}


def _iter_openmm_platform_candidates(preferred: str = _OPENMM_PLATFORM_AUTO) -> list[str]:
    """Preference order: requested GPU, other GPU plugins, then CPU."""
    preferred = _normalize_openmm_platform(preferred)
    available = set(_openmm_platform_names())
    ordered: list[str] = []

    def _add(name: str) -> None:
        if name in available and name not in ordered:
            ordered.append(name)

    if preferred == "CPU":
        _add("CPU")
        return ordered
    if preferred == "Reference":
        _add("Reference")
        _add("CPU")
        return ordered
    if preferred in {"CUDA", "OpenCL"}:
        _add(preferred)
        if preferred not in available:
            log_prepare(f"OpenMM: {preferred} plugin not installed; trying another platform")
    for name in ("CUDA", "OpenCL", "CPU"):
        _add(name)
    return ordered


def _platform_context_label(simulation) -> str:
    platform = simulation.context.getPlatform()
    name = platform.getName()
    bits = [name]
    for key in ("DeviceName", "Threads", "Precision", "CudaPrecision", "OpenCLPrecision"):
        try:
            value = platform.getPropertyValue(simulation.context, key)
        except Exception:
            continue
        if value:
            bits.append(f"{key}={value}")
    return " ".join(bits)


def _create_openmm_simulation(
    topology, system, integrator, *, preferred: str = _OPENMM_PLATFORM_AUTO
):
    import openmm
    from openmm.app import Simulation

    last_err: BaseException | None = None
    for name in _iter_openmm_platform_candidates(preferred):
        try:
            platform = openmm.Platform.getPlatformByName(name)
            simulation = Simulation(
                topology,
                system,
                integrator,
                platform,
                _openmm_platform_properties(name),
            )
            log_prepare(f"OpenMM: using {_platform_context_label(simulation)}")
            return simulation
        except Exception as exc:
            last_err = exc
            log_prepare(f"OpenMM: {name} unavailable ({exc}); trying next platform")
    detail = str(last_err) if last_err else "no platforms"
    raise RuntimeError(f"Could not create an OpenMM Simulation ({detail})")


def _normalize_restraint_set(name: str) -> str:
    raw = (name or _RESTRAINT_BACKBONE).strip().lower()
    if raw in {_RESTRAINT_CA, "c-alpha", "calpha"}:
        return _RESTRAINT_CA
    if raw in {_RESTRAINT_BACKBONE_LIGAND, "backbone+ligand", "all_heavy"}:
        return _RESTRAINT_BACKBONE_LIGAND
    return _RESTRAINT_BACKBONE


def _protein_ff_xmls(
    *,
    keep_water: bool,
    solvent: str = _SOLVENT_GBN2,
    protein_ff: str = _PROTEIN_FF_AMBER14,
    gbsa: bool | None = None,
) -> tuple[tuple[str, ...], ...]:
    """Force-field XML combinations, preferred first."""
    ff = _normalize_protein_ff(protein_ff)
    if gbsa is False:
        sol = _SOLVENT_VACUUM
    elif gbsa is True and not solvent:
        sol = _SOLVENT_GBN2
    else:
        sol = _normalize_solvent(solvent)
    if ff == _PROTEIN_FF_AMBER99:
        protein_xml = "amber99sbildn.xml"
        water_xml = "tip3p.xml"
        gb_fallback = "implicit/obc2.xml"
    else:
        protein_xml = "amber14-all.xml"
        water_xml = "amber14/tip3pfb.xml"
        gb_fallback = "implicit/gbn2.xml"
    gb_xml = None
    if sol == _SOLVENT_GBN2:
        gb_xml = "implicit/gbn2.xml"
    elif sol == _SOLVENT_OBC2:
        gb_xml = "implicit/obc2.xml"
    primary: list[str] = [protein_xml]
    if keep_water:
        primary.append(water_xml)
    if gb_xml:
        primary.append(gb_xml)
    out: list[tuple[str, ...]] = [tuple(primary)]
    if gb_xml and gb_xml != gb_fallback:
        alt = [protein_xml]
        if keep_water:
            alt.append(water_xml)
        alt.append(gb_fallback)
        out.append(tuple(alt))
    return tuple(out)


def _solvent_label(
    xmls: tuple[str, ...],
    *,
    used_gb: bool,
    used_salt: bool,
    salt_m: float = _GB_SALT_M,
) -> str:
    if not used_gb:
        return "VACUUM"
    model = "GBN2" if any("gbn2" in x for x in xmls) else "OBC2"
    if used_salt:
        return f"{model} I={float(salt_m):.2f}M"
    return model


def _ff_attempts(
    *, keep_water: bool, solvent: str, protein_ff: str
) -> list[tuple[tuple[str, ...], bool, bool]]:
    sol = _normalize_solvent(solvent)
    attempts: list[tuple[tuple[str, ...], bool, bool]] = []
    if sol != _SOLVENT_VACUUM:
        for xmls in _protein_ff_xmls(keep_water=keep_water, solvent=sol, protein_ff=protein_ff):
            attempts.append((xmls, True, True))
            attempts.append((xmls, True, False))
    for xmls in _protein_ff_xmls(
        keep_water=keep_water, solvent=_SOLVENT_VACUUM, protein_ff=protein_ff
    ):
        attempts.append((xmls, False, False))
    return attempts


def _protein_only_system(
    pdb,
    *,
    keep_water: bool,
    protein_ff: str = _PROTEIN_FF_AMBER14,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
) -> tuple[object, str]:
    from openmm.app import ForceField, HBonds, NoCutoff

    last_exc: Exception | None = None
    for xmls, gbsa, with_salt in _ff_attempts(
        keep_water=keep_water, solvent=solvent, protein_ff=protein_ff
    ):
        try:
            forcefield = ForceField(*xmls)
        except Exception as exc:
            last_exc = exc
            continue
        kwargs = {"constraints": HBonds, "nonbondedMethod": NoCutoff}
        if gbsa and with_salt:
            kwargs["implicitSolventKappa"] = _gb_kappa_per_nm(salt_m=salt_m)
        try:
            system = forcefield.createSystem(pdb.topology, **kwargs)
            return system, _solvent_label(xmls, used_gb=gbsa, used_salt=with_salt, salt_m=salt_m)
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        "OpenMM could not parameterize the protonated structure. "
        f"{last_exc} Uncheck restrained minimization to keep the pdb2pqr hydrogens."
    ) from last_exc


def _amber_holo_system(
    prmtop_path: Path,
    inpcrd_path: Path,
    *,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
):
    """OpenMM system from an AmberTools prmtop (protein AMBER + GAFF ligand)."""
    from openmm.app import AmberInpcrdFile, AmberPrmtopFile, GBn2, HBonds, NoCutoff, OBC2

    prmtop = AmberPrmtopFile(str(prmtop_path))
    inpcrd = AmberInpcrdFile(str(inpcrd_path))
    sol = _normalize_solvent(solvent)
    last_exc: Exception | None = None
    attempts: list[tuple[object | None, bool]] = []
    if sol == _SOLVENT_GBN2:
        attempts.extend([(GBn2, True), (GBn2, False)])
    elif sol == _SOLVENT_OBC2:
        attempts.extend([(OBC2, True), (OBC2, False)])
    attempts.append((None, False))
    for gb, with_salt in attempts:
        kwargs = {"constraints": HBonds, "nonbondedMethod": NoCutoff}
        xmls: tuple[str, ...] = ()
        if gb == GBn2:
            kwargs["implicitSolvent"] = GBn2
            xmls = ("implicit/gbn2.xml",)
        elif gb == OBC2:
            kwargs["implicitSolvent"] = OBC2
            xmls = ("implicit/obc2.xml",)
        if gb is not None and with_salt:
            kwargs["implicitSolventKappa"] = _gb_kappa_per_nm(salt_m=salt_m)
        try:
            system = prmtop.createSystem(**kwargs)
            return (
                system,
                prmtop.topology,
                inpcrd.positions,
                _solvent_label(xmls, used_gb=gb is not None, used_salt=with_salt, salt_m=salt_m),
            )
        except Exception as exc:
            last_exc = exc
    raise RuntimeError(
        "OpenMM could not build a system from the AmberTools prmtop. "
        f"{last_exc} Uncheck restrained minimization, or use Protein only."
    ) from last_exc


def _rmsd_angstrom(ref_positions, new_positions, indices: list[int]) -> float | None:
    if not indices:
        return None
    from openmm import unit

    acc = 0.0
    for i in indices:
        a = ref_positions[i].value_in_unit(unit.angstrom)
        b = new_positions[i].value_in_unit(unit.angstrom)
        dx = float(a[0] - b[0])
        dy = float(a[1] - b[1])
        dz = float(a[2] - b[2])
        acc += dx * dx + dy * dy + dz * dz
    return (acc / len(indices)) ** 0.5


def _pocket_heavy_indices(topology, positions, ligand_keys: set[ResidueKey], cutoff: float = 5.0):
    from openmm import unit

    from ..protein.structure_components import AMINO_ACIDS, NUCLEIC_ACIDS

    lig_xyz = []
    polymer_idx: list[int] = []
    cutoff_sq = float(cutoff) ** 2
    for atom in topology.atoms():
        key = _residue_key(atom.residue)
        name = (atom.name or "").strip()
        elem = ""
        element = getattr(atom, "element", None)
        if element is not None:
            elem = (getattr(element, "symbol", "") or "").upper()
        is_h = elem in {"H", "D"} or name.startswith("H")
        pos = positions[atom.index].value_in_unit(unit.angstrom)
        xyz = (float(pos[0]), float(pos[1]), float(pos[2]))
        if key in ligand_keys and not is_h:
            lig_xyz.append(xyz)
        resn = (getattr(atom.residue, "name", "") or "").strip().upper()
        if not is_h and (resn in AMINO_ACIDS or resn in NUCLEIC_ACIDS):
            polymer_idx.append((atom.index, xyz))
    if not lig_xyz:
        return []
    out: list[int] = []
    for idx, xyz in polymer_idx:
        x, y, z = xyz
        if any(
            (x - lx) ** 2 + (y - ly) ** 2 + (z - lz) ** 2 <= cutoff_sq for lx, ly, lz in lig_xyz
        ):
            out.append(idx)
    return out


def _restrained_minimize_pdb(
    input_pdb: Path,
    output_pdb: Path,
    *,
    restrained_ca_keys: set[ResidueKey],
    k_kcal_per_ang2: float,
    max_iterations: int,
    keep_water: bool,
    remarks: list[str],
    chem_source: str = "",
    protein_ff: str = _PROTEIN_FF_AMBER14,
    solvent: str = _SOLVENT_GBN2,
    salt_m: float = _GB_SALT_M,
    restraint_set: str = _RESTRAINT_BACKBONE,
    ligand_keys: set[ResidueKey] | None = None,
    ligand_ff: str = _LIGAND_FF_NONE,
    ligand_mols: Sequence | None = None,
    work_dir: Path | None = None,
    openmm_platform: str = _OPENMM_PLATFORM_AUTO,
) -> None:
    from openmm import CustomExternalForce, LangevinMiddleIntegrator, unit

    from .protein_prepare_qc import restrain_atom

    protein_ff = _normalize_protein_ff(protein_ff)
    restraint_set = _normalize_restraint_set(restraint_set)
    ligand_keys = ligand_keys or set()
    ligand_ff = _normalize_ligand_ff(ligand_ff)
    use_gaff = _ligand_ff_is_gaff(ligand_ff) and bool(ligand_mols) and bool(ligand_keys)
    from ..sim.system_build import build_for_legacy_minimize

    built = build_for_legacy_minimize(
        input_pdb=input_pdb,
        use_gaff=use_gaff,
        ligand_mols=ligand_mols,
        ligand_keys=ligand_keys,
        keep_water=keep_water,
        protein_ff=protein_ff,
        ligand_ff=ligand_ff,
        solvent=solvent,
        salt_m=salt_m,
        work_dir=work_dir,
    )
    system = built.system
    pdb = built.structure
    min_tag = built.min_tag
    if built.ligand_tag:
        remarks.append(f"4B AMBERTOOLS {built.ligand_tag} {built.charge_tag}")
    scheme_tag = {
        _RESTRAINT_CA: "CA-RESTRAINED",
        _RESTRAINT_BACKBONE_LIGAND: "BACKBONE+LIGAND-RESTRAINED",
        _RESTRAINT_BACKBONE: "BACKBONE-RESTRAINED",
    }.get(restraint_set, "BACKBONE-RESTRAINED")
    for i, line in enumerate(remarks):
        if str(line).startswith("4 OPENMM "):
            remarks[i] = (
                f"4 OPENMM {scheme_tag} MIN {min_tag} K={float(k_kcal_per_ang2):.1f} KCAL/MOL/A**2"
            )
            break

    restraint = CustomExternalForce("0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)")
    restraint.addGlobalParameter(
        "k", float(k_kcal_per_ang2) * unit.kilocalories_per_mole / unit.angstroms**2
    )
    restraint.addPerParticleParameter("x0")
    restraint.addPerParticleParameter("y0")
    restraint.addPerParticleParameter("z0")

    original_keys = restrained_ca_keys or _ca_residue_keys(pdb.topology)
    n_restrained = 0
    for atom in pdb.topology.atoms():
        if not restrain_atom(
            atom, scheme=restraint_set, original_keys=original_keys, ligand_keys=ligand_keys
        ):
            continue
        pos = pdb.positions[atom.index]
        xyz = pos.value_in_unit(unit.nanometer)
        restraint.addParticle(atom.index, [float(xyz[0]), float(xyz[1]), float(xyz[2])])
        n_restrained += 1
    if n_restrained == 0:
        for atom in pdb.topology.atoms():
            if atom.name != "CA":
                continue
            pos = pdb.positions[atom.index]
            xyz = pos.value_in_unit(unit.nanometer)
            restraint.addParticle(atom.index, [float(xyz[0]), float(xyz[1]), float(xyz[2])])
            n_restrained += 1
    if n_restrained:
        system.addForce(restraint)

    integrator = LangevinMiddleIntegrator(
        300 * unit.kelvin, 1.0 / unit.picosecond, 0.002 * unit.picoseconds
    )
    simulation = _create_openmm_simulation(
        pdb.topology,
        system,
        integrator,
        preferred=openmm_platform,
    )
    simulation.context.setPositions(pdb.positions)
    log_prepare(f"OpenMM: running minimizer ({int(max_iterations)} iterations)…")
    simulation.minimizeEnergy(maxIterations=int(max_iterations))
    positions = simulation.context.getState(getPositions=True).getPositions()
    ca_idx = [atom.index for atom in pdb.topology.atoms() if atom.name == "CA"]
    pocket_idx = _pocket_heavy_indices(pdb.topology, pdb.positions, ligand_keys)
    ca_rmsd = _rmsd_angstrom(pdb.positions, positions, ca_idx)
    pocket_rmsd = _rmsd_angstrom(pdb.positions, positions, pocket_idx)
    rmsd_bits = []
    if ca_rmsd is not None:
        rmsd_bits.append(f"CA={ca_rmsd:.2f}A")
    if pocket_rmsd is not None:
        rmsd_bits.append(f"POCKET={pocket_rmsd:.2f}A")
    if rmsd_bits:
        remarks.append("5 RMSD " + " ".join(rmsd_bits))
        log_prepare("OpenMM: " + " ".join(rmsd_bits))
    else:
        log_prepare("OpenMM: minimization finished")
    _write_openmm_structure(
        pdb.topology,
        positions,
        output_pdb,
        remarks=remarks,
        chem_source=chem_source,
    )


def _ligand_chem_tables(
    text: str,
    *,
    fmt: str,
    keep_ligand: bool,
    ligand_keys: set[ResidueKey],
    input_text: str,
    input_fmt: str,
) -> tuple[dict, dict]:
    """Copy original mmCIF ``_chem_comp_*`` tables for ligands still in the file."""
    if not keep_ligand or not ligand_keys:
        return {}, {}
    remaining = _ligand_residue_names(text, fmt, ligand_keys)
    if not remaining:
        remaining = _ligand_residue_names(input_text, input_fmt, ligand_keys)
    if not remaining:
        return {}, {}
    from ..protein.structure_components import parse_cif_chem_comp_atoms, parse_cif_chem_comp_bonds

    atoms: dict = {}
    bonds: dict = {}

    def _take(src: str, src_fmt: str, *, overwrite: bool) -> None:
        if not _is_cif_fmt(src_fmt):
            return
        parsed_atoms = parse_cif_chem_comp_atoms(src)
        parsed_bonds = parse_cif_chem_comp_bonds(src)
        for key, val in parsed_atoms.items():
            if key not in remaining:
                continue
            if overwrite or key not in atoms:
                atoms[key] = val
        for key, val in parsed_bonds.items():
            if key not in remaining:
                continue
            if overwrite or key not in bonds:
                bonds[key] = val

    _take(text, fmt, overwrite=True)
    _take(input_text, input_fmt, overwrite=True)
    if bonds:
        from ..protein.structure_atoms import parse_structure_atoms
        from ..protein.structure_cif import rebuild_hydrogen_chem_tables

        atoms, bonds = rebuild_hydrogen_chem_tables(parse_structure_atoms(text, fmt), atoms, bonds)
    return atoms, bonds
