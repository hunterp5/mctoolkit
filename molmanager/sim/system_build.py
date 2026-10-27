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

"""Build an OpenMM system from a simulation document or from an external topology."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .document import (
    SOURCE_BUILD,
    SOURCE_PRMTOP,
    SOURCE_PSF,
    SOURCE_XML,
    WATER_MODELS,
    SimulationDocument,
    SystemSpec,
)

_WATER_LEAP = {
    "tip3p": ("leaprc.water.tip3p", "TIP3PBOX"),
    "tip3pfb": ("leaprc.water.tip3pfb", "TIP3PFBOX"),
    "spce": ("leaprc.water.spce", "SPCBOX"),
    "tip4pew": ("leaprc.water.tip4pew", "TIP4PEWBOX"),
    "opc": ("leaprc.water.opc", "OPCBOX"),
    "opc3": ("leaprc.water.opc3", "OPC3BOX"),
}
_OPENMM_WATER = {
    "tip3p": "tip3p",
    "tip3pfb": "tip3pfb",
    "spce": "spce",
    "tip4pew": "tip4pew",
    "opc": "opc",
    "opc3": "opc3",
}
_BOX_SHAPE = {
    "cubic": "cube",
    "octahedron": "octahedron",
    "dodecahedron": "dodecahedron",
}


class SystemBuildError(RuntimeError):
    """The document's system could not be turned into an OpenMM System."""


@dataclass
class BuiltSystem:
    """Topology, system, and coordinates handed to the stage runner."""

    topology: object
    system: object
    positions: object
    label: str
    velocities: object = None
    box: object = None
    solute_atoms: int = 0
    dry_prmtop: str = ""
    receptor_prmtop: str = ""
    ligand_prmtop: str = ""


@dataclass
class LegacyMinimization:
    """The system Prepare → Minimize asks the shared builder to create."""

    system: object
    structure: object
    label: str
    min_tag: str
    charge_tag: str = ""
    ligand_tag: str = ""


def leap_script(
    *,
    protein_pdb: str,
    ligands: Sequence[tuple[str, str, str]],
    protein_ff: str,
    ligand_ff: str,
    solvent: str,
    box_shape: str = "cubic",
    padding_a: float = 10.0,
    cation: str = "Na+",
    anion: str = "Cl-",
    ion_mode: str = "neutralize",
    ion_conc_m: float = 0.15,
    prmtop: str = "complex.prmtop",
    inpcrd: str = "complex.inpcrd",
    receptor_prmtop: str = "receptor.prmtop",
    receptor_inpcrd: str = "receptor.inpcrd",
    ligand_prmtop: str = "ligand.prmtop",
    ligand_inpcrd: str = "ligand.inpcrd",
    dry_prmtop: str = "complex_dry.prmtop",
    dry_inpcrd: str = "complex_dry.inpcrd",
) -> str:
    """tleap script: split receptor and ligand, optional explicit solvent and ions.

    A dodecahedron with GAFF is refused. tleap can build a cube or an octahedron.
    """
    from ..workers.protein_prepare_amber import _leaprc_gaff, _leaprc_protein, _pbradii

    if solvent in WATER_MODELS and box_shape == "dodecahedron":
        raise SystemBuildError(
            "AmberTools tleap builds a cubic or octahedral box. "
            "Use octahedron or cubic with GAFF, or OpenFF for a dodecahedron."
        )
    lines = [
        f"source {_leaprc_protein(protein_ff)}",
        f"source {_leaprc_gaff(ligand_ff)}",
    ]
    radii = _pbradii(solvent if solvent not in WATER_MODELS else "gbn2")
    if radii and solvent not in WATER_MODELS:
        lines.append(f"set default PBradii {radii}")
    for index, (mol2, frcmod, _resn) in enumerate(ligands):
        lines.append(f"loadamberparams {frcmod}")
        lines.append(f"LIG{index} = loadMol2 {mol2}")
    lines.append(f"PROT = loadPdb {protein_pdb}")
    lines.append(f"saveAmberParm PROT {receptor_prmtop} {receptor_inpcrd}")
    if ligands:
        lines.append(f"saveAmberParm LIG0 {ligand_prmtop} {ligand_inpcrd}")
    combo = " ".join(["PROT", *[f"LIG{index}" for index in range(len(ligands))]])
    lines.append(f"COMP = combine {{ {combo} }}")
    if solvent in WATER_MODELS:
        lines.append(f"saveAmberParm COMP {dry_prmtop} {dry_inpcrd}")
        leaprc, box = _WATER_LEAP[solvent]
        lines.append(f"source {leaprc}")
        if box_shape == "octahedron":
            lines.append(f"solvateOct COMP {box} {float(padding_a):.3f}")
        else:
            lines.append(f"solvateBox COMP {box} {float(padding_a):.3f}")
        if ion_mode == "concentration":
            lines.append(f"addIonsRand COMP {cation} 0 {anion} 0 {float(ion_conc_m):.4f}")
        else:
            lines.append(f"addIons COMP {cation} 0")
    lines.append(f"saveAmberParm COMP {prmtop} {inpcrd}")
    lines.append("quit")
    return "\n".join(lines) + "\n"


def build_for_legacy_minimize(
    *,
    input_pdb: Path,
    use_gaff: bool,
    ligand_mols,
    ligand_keys,
    keep_water: bool,
    protein_ff: str,
    ligand_ff: str,
    solvent: str,
    salt_m: float,
    work_dir: Path | None,
) -> LegacyMinimization:
    """System for Prepare → Minimize. Implicit solvent uses the existing helpers."""
    from ..workers.protein_prepare_amber import _ligand_ff_tag, build_gaff_prmtop
    from ..workers.protein_prepare_io import log_prepare
    from ..workers.protein_prepare_minimize import (
        _amber_holo_system,
        _open_openmm_structure,
        _protein_only_system,
    )

    if use_gaff:
        scratch = Path(work_dir) if work_dir is not None else input_pdb.parent
        log_prepare("AmberTools: parameterizing ligand for OpenMM…")
        prmtop, inpcrd, charge_tag = build_gaff_prmtop(
            input_pdb,
            ligand_mols=list(ligand_mols or []),
            ligand_keys=ligand_keys,
            keep_water=keep_water,
            protein_ff=protein_ff,
            ligand_ff=ligand_ff,
            solvent=solvent,
            work_dir=scratch,
        )
        system, topology, positions, solvent_label = _amber_holo_system(
            prmtop, inpcrd, solvent=solvent, salt_m=salt_m
        )
        structure = _Structure(topology, positions)
        ligand_tag = _ligand_ff_tag(ligand_ff)
        return LegacyMinimization(
            system=system,
            structure=structure,
            label=solvent_label,
            min_tag=f"{protein_ff.upper()} {ligand_tag} {charge_tag} {solvent_label}",
            charge_tag=charge_tag,
            ligand_tag=ligand_tag,
        )
    structure = _open_openmm_structure(input_pdb)
    log_prepare("OpenMM: assigning protein force field…")
    system, solvent_label = _protein_only_system(
        structure,
        keep_water=keep_water,
        protein_ff=protein_ff,
        solvent=solvent,
        salt_m=salt_m,
    )
    return LegacyMinimization(
        system=system,
        structure=structure,
        label=solvent_label,
        min_tag=f"{protein_ff.upper()} {solvent_label}",
    )


def build_system(
    document: SimulationDocument,
    *,
    structure_path: str | Path,
    work_dir: str | Path,
    ligand_mols=None,
    ligand_keys=None,
) -> BuiltSystem:
    """Create the system described by *document*."""
    spec = document.system
    if spec.source == SOURCE_PRMTOP:
        return _load_amber(spec)
    if spec.source == SOURCE_XML:
        return _load_xml(spec)
    if spec.source == SOURCE_PSF:
        return _load_psf(spec)
    if spec.source != SOURCE_BUILD:
        raise SystemBuildError(f"Unknown system source {spec.source!r}.")
    if spec.ligand_ff in {"gaff", "gaff2"} and ligand_mols:
        return _build_gaff(document, Path(structure_path), Path(work_dir), ligand_mols, ligand_keys)
    if spec.ligand_ff == "openff" and ligand_mols:
        return _build_openff(document, Path(structure_path), ligand_mols)
    return _build_protein(document, Path(structure_path))


def _build_protein(document: SimulationDocument, structure_path: Path) -> BuiltSystem:
    spec = document.system
    from ..workers.protein_prepare_io import _open_openmm_structure

    pdb = _open_openmm_structure(structure_path)
    if spec.solvent in WATER_MODELS:
        return _solvate_protein(pdb, spec)
    from ..workers.protein_prepare_minimize import _protein_only_system

    system, label = _protein_only_system(
        pdb,
        keep_water=spec.crystal_water != "drop",
        protein_ff=_protein_ff_name(spec.protein_ff),
        solvent=spec.solvent,
        salt_m=spec.salt_m,
    )
    return BuiltSystem(
        topology=pdb.topology,
        system=system,
        positions=pdb.positions,
        label=label,
        solute_atoms=pdb.topology.getNumAtoms(),
    )


def _solvate_protein(pdb, spec: SystemSpec) -> BuiltSystem:
    try:
        from openmm.app import ForceField, HBonds, Modeller, PME
        from openmm import unit
    except ImportError as exc:
        raise SystemBuildError("OpenMM is required to solvate a protein.") from exc
    from ..workers.protein_prepare_minimize import _protein_ff_xmls

    xmls = _protein_ff_xmls(
        keep_water=True,
        solvent="vacuum",
        protein_ff=_protein_ff_name(spec.protein_ff),
    )[0]
    water_xml = (
        "amber/tip3p_standard.xml" if spec.solvent == "tip3p" else "amber/tip3p_standard.xml"
    )
    forcefield = ForceField(*xmls, water_xml)
    modeller = Modeller(pdb.topology, pdb.positions)
    shape = _BOX_SHAPE.get(spec.box_shape, "cube")
    ionic = (
        float(spec.ion_conc_m) * unit.molar
        if spec.ion_mode == "concentration"
        else 0.0 * unit.molar
    )
    modeller.addSolvent(
        forcefield,
        model=_OPENMM_WATER[spec.solvent],
        padding=float(spec.box_padding_a) * unit.angstrom,
        boxShape=shape,
        ionicStrength=ionic,
    )
    system = forcefield.createSystem(
        modeller.topology,
        nonbondedMethod=PME,
        nonbondedCutoff=float(spec.cutoff_nm) * unit.nanometer,
        constraints=HBonds,
        rigidWater=bool(spec.rigid_water),
    )
    solute = pdb.topology.getNumAtoms()
    return BuiltSystem(
        topology=modeller.topology,
        system=system,
        positions=modeller.positions,
        label=spec.solvent.upper(),
        solute_atoms=solute,
    )


def _build_gaff(
    document, structure_path: Path, work_dir: Path, ligand_mols, ligand_keys
) -> BuiltSystem:
    from ..workers.protein_prepare_amber import build_gaff_prmtop
    from ..workers.protein_prepare_minimize import _amber_holo_system

    spec = document.system
    explicit = spec.solvent in WATER_MODELS
    prmtop, inpcrd, _tag = build_gaff_prmtop(
        structure_path,
        ligand_mols=list(ligand_mols),
        ligand_keys=set(ligand_keys or ()),
        keep_water=spec.crystal_water != "drop",
        protein_ff=_protein_ff_name(spec.protein_ff),
        ligand_ff=spec.ligand_ff,
        solvent="gbn2" if explicit else spec.solvent,
        work_dir=work_dir,
        box_shape=spec.box_shape if explicit else "",
        box_padding_a=spec.box_padding_a if explicit else 0.0,
        ion_mode=spec.ion_mode if explicit else "",
        cation=spec.cation,
        anion=spec.anion,
        ion_conc_m=spec.ion_conc_m,
        write_split=True,
        explicit_solvent=spec.solvent if explicit else "",
    )
    if explicit:
        return _load_prmtop_files(prmtop, inpcrd, spec, work_dir)
    system, topology, positions, label = _amber_holo_system(
        prmtop, inpcrd, solvent=spec.solvent, salt_m=spec.salt_m
    )
    return BuiltSystem(
        topology=topology,
        system=system,
        positions=positions,
        label=label,
        solute_atoms=topology.getNumAtoms(),
        dry_prmtop=str(work_dir / "complex_dry.prmtop"),
        receptor_prmtop=str(work_dir / "receptor.prmtop"),
        ligand_prmtop=str(work_dir / "ligand.prmtop"),
    )


def _build_openff(document, structure_path: Path, ligand_mols) -> BuiltSystem:
    try:
        from openff.toolkit import Molecule
        from openmm.app import ForceField, HBonds, NoCutoff, PME
        from openmm import unit
        from openmmforcefields.generators import SMIRNOFFTemplateGenerator
    except ImportError as exc:
        raise SystemBuildError(
            "OpenFF Sage needs openff-toolkit and openmmforcefields. "
            "Install the fep extra: pip install 'molmanager[fep]'"
        ) from exc
    from ..workers.protein_prepare_io import _open_openmm_structure
    from ..workers.protein_prepare_minimize import _protein_ff_xmls

    spec = document.system
    pdb = _open_openmm_structure(structure_path)
    molecules = []
    for mol in ligand_mols:
        molecules.append(Molecule.from_rdkit(mol, allow_undefined_stereo=True))
    xmls = _protein_ff_xmls(
        keep_water=True,
        solvent="vacuum",
        protein_ff=_protein_ff_name(spec.protein_ff),
    )[0]
    forcefield = ForceField(*xmls)
    generator = SMIRNOFFTemplateGenerator(molecules=molecules)
    forcefield.registerTemplateGenerator(generator.generator)
    method = PME if spec.solvent in WATER_MODELS else NoCutoff
    system = forcefield.createSystem(
        pdb.topology,
        nonbondedMethod=method,
        constraints=HBonds,
        nonbondedCutoff=float(spec.cutoff_nm) * unit.nanometer,
    )
    return BuiltSystem(
        topology=pdb.topology,
        system=system,
        positions=pdb.positions,
        label="OPENFF",
        solute_atoms=pdb.topology.getNumAtoms(),
    )


def _load_amber(spec: SystemSpec) -> BuiltSystem:
    prmtop = Path(spec.prmtop_path)
    inpcrd = Path(spec.inpcrd_path)
    if not prmtop.is_file() or not inpcrd.is_file():
        raise SystemBuildError(f"Amber files were not found: {prmtop} {inpcrd}")
    return _load_prmtop_files(prmtop, inpcrd, spec, prmtop.parent)


def _load_prmtop_files(prmtop: Path, inpcrd: Path, spec: SystemSpec, work_dir: Path) -> BuiltSystem:
    try:
        from openmm import unit
        from openmm.app import AmberInpcrdFile, AmberPrmtopFile, HBonds, PME, NoCutoff
    except ImportError as exc:
        raise SystemBuildError("OpenMM is required to read an Amber prmtop.") from exc
    amber = AmberPrmtopFile(str(prmtop))
    coords = AmberInpcrdFile(str(inpcrd))
    explicit = spec.solvent in WATER_MODELS or coords.boxVectors is not None
    if explicit:
        system = amber.createSystem(
            nonbondedMethod=PME,
            nonbondedCutoff=float(spec.cutoff_nm) * unit.nanometer,
            constraints=HBonds,
            rigidWater=bool(spec.rigid_water),
        )
    else:
        system = amber.createSystem(nonbondedMethod=NoCutoff, constraints=HBonds)
    solute = int(spec.solute_atoms) or _dry_atom_count(work_dir) or amber.topology.getNumAtoms()
    return BuiltSystem(
        topology=amber.topology,
        system=system,
        positions=coords.positions,
        box=coords.boxVectors,
        label=spec.solvent.upper(),
        solute_atoms=solute,
        dry_prmtop=str(work_dir / "complex_dry.prmtop"),
        receptor_prmtop=str(work_dir / "receptor.prmtop"),
        ligand_prmtop=str(work_dir / "ligand.prmtop"),
    )


def _load_xml(spec: SystemSpec) -> BuiltSystem:
    xml_path = Path(spec.xml_path)
    coords_path = Path(spec.coordinates_path)
    if not xml_path.is_file() or not coords_path.is_file():
        raise SystemBuildError(f"OpenMM XML inputs were not found: {xml_path} {coords_path}")
    try:
        from openmm import XmlSerializer
        from openmm.app import PDBFile, PDBxFile
    except ImportError as exc:
        raise SystemBuildError("OpenMM is required to read a System XML.") from exc
    system = XmlSerializer.deserialize(xml_path.read_text(encoding="utf-8"))
    if coords_path.suffix.lower() in {".cif", ".mmcif"}:
        coords = PDBxFile(str(coords_path))
    else:
        coords = PDBFile(str(coords_path))
    return BuiltSystem(
        topology=coords.topology,
        system=system,
        positions=coords.positions,
        label="XML",
        solute_atoms=int(spec.solute_atoms) or coords.topology.getNumAtoms(),
    )


def _load_psf(spec: SystemSpec) -> BuiltSystem:
    psf_path = Path(spec.psf_path)
    pdb_path = Path(spec.pdb_path)
    params = Path(spec.params_path)
    if not psf_path.is_file() or not pdb_path.is_file() or not params.is_file():
        raise SystemBuildError("CHARMM source needs an existing PSF, PDB, and parameter file.")
    try:
        from openmm.app import CharmmParameterSet, CharmmPsfFile, PDBFile
    except ImportError as exc:
        raise SystemBuildError("OpenMM is required to read a CHARMM PSF.") from exc
    psf = CharmmPsfFile(str(psf_path))
    parameter_set = CharmmParameterSet(str(params))
    system = psf.createSystem(parameter_set)
    coords = PDBFile(str(pdb_path))
    return BuiltSystem(
        topology=psf.topology,
        system=system,
        positions=coords.positions,
        label="CHARMM",
        solute_atoms=int(spec.solute_atoms) or psf.topology.getNumAtoms(),
    )


def _protein_ff_name(name: str) -> str:
    if name in {"ff19sb", "amber19", "ff14sb", "amber14"}:
        return "amber14"
    if name in {"ff99sbildn", "amber99"}:
        return "amber99sbildn"
    return "amber14"


def _dry_atom_count(work_dir: Path) -> int:
    dry = work_dir / "complex_dry.prmtop"
    if not dry.is_file():
        return 0
    try:
        from openmm.app import AmberPrmtopFile
    except ImportError:
        return 0
    return int(AmberPrmtopFile(str(dry)).topology.getNumAtoms())


class _Structure:
    def __init__(self, topology, positions) -> None:
        self.topology = topology
        self.positions = positions
