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

"""Versioned simulation document: system, stages, observables, and run settings."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .selection import SelectionError, parse_selection

DOCUMENT_VERSION = 1
FILE_SUFFIX = ".mmsim.json"

STAGE_MINIMIZE = "minimize"
STAGE_DYNAMICS = "dynamics"
STAGE_CUSTOM = "custom"

SOURCE_BUILD = "build"
SOURCE_PRMTOP = "prmtop"
SOURCE_XML = "xml"
SOURCE_PSF = "psf"
SOURCES = (SOURCE_BUILD, SOURCE_PRMTOP, SOURCE_XML, SOURCE_PSF)

IMPLICIT_SOLVENTS = ("vacuum", "gbn2", "obc2", "gbn", "hct")
WATER_MODELS = ("tip3p", "tip3pfb", "spce", "tip4pew", "opc", "opc3")
SOLVENTS = IMPLICIT_SOLVENTS + WATER_MODELS

PROTEIN_FORCE_FIELDS = ("ff14sb", "ff19sb", "ff99sbildn")
LIGAND_FORCE_FIELDS = ("gaff2", "gaff", "openff", "none")
BOX_SHAPES = ("cubic", "octahedron", "dodecahedron", "cryst1")
NONBONDED_METHODS = (
    "nocutoff",
    "cutoff_nonperiodic",
    "cutoff_periodic",
    "pme",
    "ljpme",
)
CONSTRAINTS = ("none", "hbonds", "allbonds", "hangles")
CRYSTAL_WATER = ("drop", "keep", "within")
ION_MODES = ("neutralize", "concentration")
ENSEMBLES = ("nve", "nvt", "npt")
INTEGRATORS = (
    "langevin_middle",
    "langevin",
    "brownian",
    "verlet",
    "variable_verlet",
    "variable_langevin",
    "nose_hoover",
)
VELOCITY_POLICIES = ("continue", "reassign", "zero")
LENGTH_UNITS = ("steps", "ps", "ns")
BAROSTATS = ("montecarlo", "anisotropic")
RESTRAINT_FORMS = (
    "harmonic",
    "flat_bottom",
    "freeze",
    "distance",
    "angle",
    "dihedral",
    "rmsd",
)
REFERENCES = ("stage_start", "structure", "frame")
OBSERVABLE_KINDS = (
    "rmsd",
    "rmsf",
    "rg",
    "distance",
    "angle",
    "dihedral",
    "contacts",
    "hbond",
    "mmgbsa",
)
RUN_KINDS = ("dynamics", "alchemical")
RESUME_MODES = ("none", "checkpoint", "state")
PLATFORMS = ("auto", "cuda", "opencl", "cpu", "reference")
PRECISIONS = ("single", "mixed", "double")


class SimulationDocumentError(ValueError):
    """The simulation document JSON is missing a required field or has a bad value."""


def new_id(prefix: str) -> str:
    """A short id for a stage or observable."""
    return f"{prefix}{uuid.uuid4().hex[:8]}"


@dataclass
class RestraintGroup:
    """One restraint applied for a single stage."""

    selection: str = "backbone and ligand"
    form: str = "harmonic"
    k_kcal_per_ang2: float = 10.0
    radius_a: float = 0.0
    reference: str = "stage_start"
    atoms: tuple[str, ...] = ()


@dataclass
class ReporterSpec:
    """How often a stage writes scalars, a trajectory, and restart files."""

    energy_ps: float | None = 1.0
    dcd_ps: float | None = 10.0
    checkpoint_ps: float | None = 20.0
    state_xml_ps: float | None = None
    wrap_dcd: bool = True


@dataclass
class MinimizeStage:
    """Energy minimization. Tolerance is kJ/mol/nm, the OpenMM unit."""

    id: str
    name: str = "Minimize"
    enabled: bool = True
    kind: str = STAGE_MINIMIZE
    tolerance_kj: float = 10.0
    max_iterations: int = 500
    restraints: list[RestraintGroup] = field(default_factory=list)
    constraints: str | None = None
    hydrogen_mass_da: float | None = None


@dataclass
class DynamicsStage:
    """One dynamics leg. Temperature and pressure may ramp across the stage."""

    id: str
    name: str = "Dynamics"
    enabled: bool = True
    kind: str = STAGE_DYNAMICS
    ensemble: str = "nvt"
    integrator: str = "langevin_middle"
    friction_per_ps: float = 1.0
    temperature_k: float = 300.0
    temperature_end_k: float | None = None
    pressure_bar: float = 1.0
    pressure_end_bar: float | None = None
    barostat: str = "montecarlo"
    barostat_interval: int = 25
    timestep_fs: float = 2.0
    length_value: float = 100.0
    length_unit: str = "ps"
    velocity_policy: str = "continue"
    seed: int = 1
    restraints: list[RestraintGroup] = field(default_factory=list)
    reporters: ReporterSpec = field(default_factory=ReporterSpec)
    observable_ids: list[str] = field(default_factory=list)
    observable_stride_ps: float = 10.0
    constraints: str | None = None
    hydrogen_mass_da: float | None = None


@dataclass
class CustomStage:
    """A user-written OpenMM CustomIntegrator script plus the shared stage controls."""

    id: str
    name: str = "Custom"
    enabled: bool = True
    kind: str = STAGE_CUSTOM
    script: str = "variable v\ncompute v = v+dt*f/m\ncompute x = x+dt*v\n"
    length_value: float = 1000.0
    length_unit: str = "steps"
    timestep_fs: float = 1.0
    seed: int = 1
    restraints: list[RestraintGroup] = field(default_factory=list)
    reporters: ReporterSpec = field(default_factory=ReporterSpec)
    observable_ids: list[str] = field(default_factory=list)
    observable_stride_ps: float = 10.0
    constraints: str | None = None
    hydrogen_mass_da: float | None = None


Stage = MinimizeStage | DynamicsStage | CustomStage


@dataclass
class Observable:
    """A measurement taken on a stride during selected stages and from the trajectory."""

    id: str
    kind: str
    selection: str = "ligand"
    fit_selection: str = "ca"
    reference: str = "frame0"
    stride_ps: float = 10.0
    stage_ids: list[str] = field(default_factory=list)
    cutoff_a: float = 4.0
    atom_a: str = ""
    atom_b: str = ""
    atom_c: str = ""
    atom_d: str = ""


@dataclass
class SystemSpec:
    """Where the atoms and the force field come from."""

    source: str = SOURCE_BUILD
    solute_selection: str = "protein or ligand or ion"
    protein_ff: str = "ff14sb"
    ligand_ff: str = "gaff2"
    solvent: str = "gbn2"
    salt_m: float = 0.15
    gbsa: bool = True
    box_shape: str = "cubic"
    box_padding_a: float = 10.0
    ion_mode: str = "neutralize"
    cation: str = "Na+"
    anion: str = "Cl-"
    ion_conc_m: float = 0.15
    crystal_water: str = "keep"
    crystal_water_distance_a: float = 5.0
    crystal_water_selection: str = "ligand"
    nonbonded: str = "pme"
    cutoff_nm: float = 1.0
    switch_width_nm: float = 0.0
    dispersion_correction: bool = True
    ewald_tolerance: float = 0.0005
    constraints: str = "hbonds"
    rigid_water: bool = True
    hydrogen_mass_da: float = 1.0
    com_removal: str = "linear"
    com_interval: int = 1
    prmtop_path: str = ""
    inpcrd_path: str = ""
    xml_path: str = ""
    coordinates_path: str = ""
    psf_path: str = ""
    pdb_path: str = ""
    params_path: str = ""
    ligand_smiles: str = ""
    solute_atoms: int = 0


@dataclass
class RunSpec:
    """Platform, replicates, resume, and alchemical settings for one document."""

    kind: str = "dynamics"
    platform: str = "auto"
    precision: str = "mixed"
    device_index: int = 0
    replicates: int = 1
    seeds: list[int] = field(default_factory=lambda: [1])
    resume: str = "none"
    resume_path: str = ""
    output_dir: str = ""
    queue_width: int = 1
    lambda_count: int = 12
    lambda_values: list[float] = field(default_factory=list)
    fep_equilibration_ps: float = 100.0
    fep_production_ps: float = 500.0
    fep_timestep_fs: float = 2.0
    fep_temperature_k: float = 300.0
    fep_pressure_bar: float = 1.0
    fep_hydrogen_mass_da: float = 4.0
    fep_replica_exchange: bool = True
    fep_repeats: int = 1
    fep_solvent_padding_a: float = 10.0
    summary_observable: str = "rmsd"


@dataclass
class SimulationDocument:
    """The saved protocol. Trajectories stay on disk; this object points at them."""

    version: int = DOCUMENT_VERSION
    name: str = "Simulation"
    system: SystemSpec = field(default_factory=SystemSpec)
    stages: list[Stage] = field(default_factory=list)
    observables: list[Observable] = field(default_factory=list)
    run: RunSpec = field(default_factory=RunSpec)

    def content_hash(self) -> str:
        """Stable hash of the document JSON, including paths the user set."""
        raw = json.dumps(document_to_dict(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def document_to_dict(document: SimulationDocument) -> dict[str, Any]:
    """JSON-ready mapping. Tuples become lists."""
    return {
        "version": int(document.version),
        "name": document.name,
        "system": _system_to_dict(document.system),
        "stages": [_stage_to_dict(stage) for stage in document.stages],
        "observables": [_observable_to_dict(item) for item in document.observables],
        "run": _run_to_dict(document.run),
    }


def document_to_json(document: SimulationDocument) -> str:
    """Pretty JSON for ``.mmsim.json`` files and the session."""
    return json.dumps(document_to_dict(document), indent=2) + "\n"


def document_from_dict(data: dict[str, Any]) -> SimulationDocument:
    """Build a document. Unknown version or a bad stage kind is an error."""
    if not isinstance(data, dict):
        raise SimulationDocumentError("Simulation document must be a JSON object.")
    version = int(data.get("version") or 0)
    if version != DOCUMENT_VERSION:
        raise SimulationDocumentError(
            f"Simulation document version {version} is not supported. "
            f"This build reads version {DOCUMENT_VERSION}."
        )
    stages_raw = data.get("stages") or []
    if not isinstance(stages_raw, list):
        raise SimulationDocumentError("stages must be a list.")
    observables_raw = data.get("observables") or []
    if not isinstance(observables_raw, list):
        raise SimulationDocumentError("observables must be a list.")
    return SimulationDocument(
        version=version,
        name=str(data.get("name") or "Simulation"),
        system=_system_from_dict(data.get("system") or {}),
        stages=[_stage_from_dict(item) for item in stages_raw],
        observables=[_observable_from_dict(item) for item in observables_raw],
        run=_run_from_dict(data.get("run") or {}),
    )


def document_from_json(text: str) -> SimulationDocument:
    """Parse a document string."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SimulationDocumentError(f"Simulation document is not valid JSON: {exc}") from exc
    return document_from_dict(data)


def save_document(path: str | Path, document: SimulationDocument) -> Path:
    """Write *document* to *path*, adding the ``.mmsim.json`` suffix when missing."""
    dest = Path(path)
    if dest.suffix.lower() != ".json":
        dest = dest.with_suffix(FILE_SUFFIX)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(document_to_json(document), encoding="utf-8", newline="\n")
    return dest


def load_document(path: str | Path) -> SimulationDocument:
    """Read a ``.mmsim.json`` file."""
    src = Path(path)
    if not src.is_file():
        raise SimulationDocumentError(f"Simulation document not found: {src}")
    return document_from_json(src.read_text(encoding="utf-8"))


def validate_document(document: SimulationDocument) -> list[str]:
    """Problems that should stop a run. An empty list means the document can start."""
    issues: list[str] = []
    system = document.system
    if system.source not in SOURCES:
        issues.append(f"Unknown system source {system.source!r}.")
    if system.source == SOURCE_BUILD:
        if system.protein_ff not in PROTEIN_FORCE_FIELDS:
            issues.append(f"Unknown protein force field {system.protein_ff!r}.")
        if system.ligand_ff not in LIGAND_FORCE_FIELDS:
            issues.append(f"Unknown ligand force field {system.ligand_ff!r}.")
        if system.solvent not in SOLVENTS:
            issues.append(f"Unknown solvent {system.solvent!r}.")
        if system.box_shape not in BOX_SHAPES:
            issues.append(f"Unknown box shape {system.box_shape!r}.")
        if (
            system.solvent in WATER_MODELS
            and system.box_shape == "dodecahedron"
            and system.ligand_ff in {"gaff", "gaff2"}
        ):
            issues.append(
                "AmberTools tleap builds a cubic or octahedral box. "
                "Use octahedron or cubic with GAFF, or OpenFF for a dodecahedron."
            )
        _check_selection(issues, "Solute", system.solute_selection)
    elif system.source == SOURCE_PRMTOP:
        if not system.prmtop_path or not system.inpcrd_path:
            issues.append("Amber source needs a prmtop path and an inpcrd path.")
    elif system.source == SOURCE_XML:
        if not system.xml_path or not system.coordinates_path:
            issues.append("OpenMM XML source needs a system XML path and a coordinate file.")
    elif system.source == SOURCE_PSF:
        if not system.psf_path or not system.pdb_path:
            issues.append("CHARMM source needs a PSF path and a PDB path.")
        if not system.params_path:
            issues.append("CHARMM source needs a parameter file so OpenMM can build the system.")
    if system.constraints not in CONSTRAINTS:
        issues.append(f"Unknown constraints {system.constraints!r}.")
    if system.nonbonded not in NONBONDED_METHODS:
        issues.append(f"Unknown nonbonded method {system.nonbonded!r}.")
    if not document.stages:
        issues.append("Add at least one stage.")
    seen: set[str] = set()
    for stage in document.stages:
        if stage.id in seen:
            issues.append(f"Duplicate stage id {stage.id}.")
        seen.add(stage.id)
        issues.extend(_validate_stage(stage))
    obs_ids = {item.id for item in document.observables}
    for item in document.observables:
        if item.kind not in OBSERVABLE_KINDS:
            issues.append(f"Unknown observable {item.kind!r}.")
        _check_selection(issues, item.id, item.selection)
        if item.kind == "rmsd" and item.fit_selection.strip():
            _check_selection(issues, f"{item.id} fit", item.fit_selection)
    for stage in document.stages:
        ids = getattr(stage, "observable_ids", [])
        for obs_id in ids:
            if obs_id not in obs_ids:
                issues.append(f"Stage {stage.name} names unknown observable {obs_id}.")
    run = document.run
    if run.kind not in RUN_KINDS:
        issues.append(f"Unknown run kind {run.kind!r}.")
    if run.platform not in PLATFORMS:
        issues.append(f"Unknown platform {run.platform!r}.")
    if run.precision not in PRECISIONS:
        issues.append(f"Unknown precision {run.precision!r}.")
    if run.resume not in RESUME_MODES:
        issues.append(f"Unknown resume mode {run.resume!r}.")
    if run.replicates < 1:
        issues.append("Replicates must be at least 1.")
    if run.queue_width < 1:
        issues.append("Queue width must be at least 1.")
    if run.kind == "alchemical":
        if run.lambda_values and any(value < 0.0 or value > 1.0 for value in run.lambda_values):
            issues.append("Lambda values must lie between 0 and 1.")
        if not run.lambda_values and run.lambda_count < 2:
            issues.append("An alchemical schedule needs at least two lambda windows.")
    return issues


def duplicate_stage(stage: Stage) -> Stage:
    """A copy with a new id, inserted by the stage list."""
    data = _stage_to_dict(stage)
    data["id"] = new_id("s")
    data["name"] = f"{stage.name} copy"
    return _stage_from_dict(data)


def _validate_stage(stage: Stage) -> list[str]:
    issues: list[str] = []
    for group in stage.restraints:
        if group.form not in RESTRAINT_FORMS:
            issues.append(f"Stage {stage.name} has unknown restraint form {group.form!r}.")
        if group.reference not in REFERENCES:
            issues.append(
                f"Stage {stage.name} has unknown restraint reference {group.reference!r}."
            )
        _check_selection(issues, stage.name, group.selection)
        for extra in group.atoms:
            _check_selection(issues, stage.name, extra)
    if isinstance(stage, DynamicsStage):
        if stage.ensemble not in ENSEMBLES:
            issues.append(f"Stage {stage.name} has unknown ensemble {stage.ensemble!r}.")
        if stage.integrator not in INTEGRATORS:
            issues.append(f"Stage {stage.name} has unknown integrator {stage.integrator!r}.")
        if stage.length_unit not in LENGTH_UNITS:
            issues.append(f"Stage {stage.name} has unknown length unit {stage.length_unit!r}.")
        if stage.velocity_policy not in VELOCITY_POLICIES:
            issues.append(
                f"Stage {stage.name} has unknown velocity policy {stage.velocity_policy!r}."
            )
        if stage.barostat not in BAROSTATS:
            issues.append(f"Stage {stage.name} has unknown barostat {stage.barostat!r}.")
        if stage.timestep_fs <= 0:
            issues.append(f"Stage {stage.name} needs a positive timestep.")
        if stage.length_value < 0:
            issues.append(f"Stage {stage.name} has a negative length.")
    if isinstance(stage, CustomStage):
        if not stage.script.strip():
            issues.append(f"Stage {stage.name} needs a custom integrator script.")
        if stage.timestep_fs <= 0:
            issues.append(f"Stage {stage.name} needs a positive timestep.")
    if stage.constraints is not None and stage.constraints not in CONSTRAINTS:
        issues.append(f"Stage {stage.name} has unknown constraints {stage.constraints!r}.")
    return issues


def _check_selection(issues: list[str], label: str, expression: str) -> None:
    if not str(expression or "").strip():
        return
    try:
        parse_selection(expression)
    except SelectionError as exc:
        issues.append(f"{label}: {exc}")


def _system_to_dict(spec: SystemSpec) -> dict[str, Any]:
    return {
        "source": spec.source,
        "solute_selection": spec.solute_selection,
        "protein_ff": spec.protein_ff,
        "ligand_ff": spec.ligand_ff,
        "solvent": spec.solvent,
        "salt_m": spec.salt_m,
        "gbsa": spec.gbsa,
        "box_shape": spec.box_shape,
        "box_padding_a": spec.box_padding_a,
        "ion_mode": spec.ion_mode,
        "cation": spec.cation,
        "anion": spec.anion,
        "ion_conc_m": spec.ion_conc_m,
        "crystal_water": spec.crystal_water,
        "crystal_water_distance_a": spec.crystal_water_distance_a,
        "crystal_water_selection": spec.crystal_water_selection,
        "nonbonded": spec.nonbonded,
        "cutoff_nm": spec.cutoff_nm,
        "switch_width_nm": spec.switch_width_nm,
        "dispersion_correction": spec.dispersion_correction,
        "ewald_tolerance": spec.ewald_tolerance,
        "constraints": spec.constraints,
        "rigid_water": spec.rigid_water,
        "hydrogen_mass_da": spec.hydrogen_mass_da,
        "com_removal": spec.com_removal,
        "com_interval": spec.com_interval,
        "prmtop_path": spec.prmtop_path,
        "inpcrd_path": spec.inpcrd_path,
        "xml_path": spec.xml_path,
        "coordinates_path": spec.coordinates_path,
        "psf_path": spec.psf_path,
        "pdb_path": spec.pdb_path,
        "params_path": spec.params_path,
        "ligand_smiles": spec.ligand_smiles,
        "solute_atoms": spec.solute_atoms,
    }


def _system_from_dict(data: dict[str, Any]) -> SystemSpec:
    if not isinstance(data, dict):
        raise SimulationDocumentError("system must be a JSON object.")
    spec = SystemSpec()
    for key in _system_to_dict(spec):
        if key in data:
            setattr(spec, key, data[key])
    spec.salt_m = float(spec.salt_m)
    spec.box_padding_a = float(spec.box_padding_a)
    spec.ion_conc_m = float(spec.ion_conc_m)
    spec.cutoff_nm = float(spec.cutoff_nm)
    spec.switch_width_nm = float(spec.switch_width_nm)
    spec.ewald_tolerance = float(spec.ewald_tolerance)
    spec.hydrogen_mass_da = float(spec.hydrogen_mass_da)
    spec.crystal_water_distance_a = float(spec.crystal_water_distance_a)
    spec.com_interval = int(spec.com_interval)
    spec.solute_atoms = int(spec.solute_atoms)
    spec.gbsa = bool(spec.gbsa)
    spec.rigid_water = bool(spec.rigid_water)
    spec.dispersion_correction = bool(spec.dispersion_correction)
    return spec


def _run_to_dict(spec: RunSpec) -> dict[str, Any]:
    return {
        "kind": spec.kind,
        "platform": spec.platform,
        "precision": spec.precision,
        "device_index": spec.device_index,
        "replicates": spec.replicates,
        "seeds": list(spec.seeds),
        "resume": spec.resume,
        "resume_path": spec.resume_path,
        "output_dir": spec.output_dir,
        "queue_width": spec.queue_width,
        "lambda_count": spec.lambda_count,
        "lambda_values": list(spec.lambda_values),
        "fep_equilibration_ps": spec.fep_equilibration_ps,
        "fep_production_ps": spec.fep_production_ps,
        "fep_timestep_fs": spec.fep_timestep_fs,
        "fep_temperature_k": spec.fep_temperature_k,
        "fep_pressure_bar": spec.fep_pressure_bar,
        "fep_hydrogen_mass_da": spec.fep_hydrogen_mass_da,
        "fep_replica_exchange": spec.fep_replica_exchange,
        "fep_repeats": spec.fep_repeats,
        "fep_solvent_padding_a": spec.fep_solvent_padding_a,
        "summary_observable": spec.summary_observable,
    }


def _run_from_dict(data: dict[str, Any]) -> RunSpec:
    if not isinstance(data, dict):
        raise SimulationDocumentError("run must be a JSON object.")
    spec = RunSpec()
    for key in _run_to_dict(spec):
        if key in data:
            setattr(spec, key, data[key])
    spec.device_index = int(spec.device_index)
    spec.replicates = int(spec.replicates)
    spec.queue_width = int(spec.queue_width)
    spec.lambda_count = int(spec.lambda_count)
    spec.seeds = [int(item) for item in spec.seeds]
    spec.lambda_values = [float(item) for item in spec.lambda_values]
    spec.fep_equilibration_ps = float(spec.fep_equilibration_ps)
    spec.fep_production_ps = float(spec.fep_production_ps)
    spec.fep_timestep_fs = float(spec.fep_timestep_fs)
    spec.fep_temperature_k = float(spec.fep_temperature_k)
    spec.fep_pressure_bar = float(spec.fep_pressure_bar)
    spec.fep_hydrogen_mass_da = float(spec.fep_hydrogen_mass_da)
    spec.fep_repeats = int(spec.fep_repeats)
    spec.fep_solvent_padding_a = float(spec.fep_solvent_padding_a)
    spec.fep_replica_exchange = bool(spec.fep_replica_exchange)
    return spec


def _restraint_to_dict(group: RestraintGroup) -> dict[str, Any]:
    return {
        "selection": group.selection,
        "form": group.form,
        "k_kcal_per_ang2": group.k_kcal_per_ang2,
        "radius_a": group.radius_a,
        "reference": group.reference,
        "atoms": list(group.atoms),
    }


def _restraint_from_dict(data: dict[str, Any]) -> RestraintGroup:
    return RestraintGroup(
        selection=str(data.get("selection") or ""),
        form=str(data.get("form") or "harmonic"),
        k_kcal_per_ang2=_num(data, "k_kcal_per_ang2", 0.0),
        radius_a=_num(data, "radius_a", 0.0),
        reference=str(data.get("reference") or "stage_start"),
        atoms=tuple(str(item) for item in data.get("atoms") or []),
    )


def _reporters_to_dict(spec: ReporterSpec) -> dict[str, Any]:
    return {
        "energy_ps": spec.energy_ps,
        "dcd_ps": spec.dcd_ps,
        "checkpoint_ps": spec.checkpoint_ps,
        "state_xml_ps": spec.state_xml_ps,
        "wrap_dcd": spec.wrap_dcd,
    }


def _reporters_from_dict(data: dict[str, Any] | None) -> ReporterSpec:
    raw = data or {}
    return ReporterSpec(
        energy_ps=_optional_float(raw.get("energy_ps", 1.0)),
        dcd_ps=_optional_float(raw.get("dcd_ps", 10.0)),
        checkpoint_ps=_optional_float(raw.get("checkpoint_ps", 20.0)),
        state_xml_ps=_optional_float(raw.get("state_xml_ps")),
        wrap_dcd=bool(raw.get("wrap_dcd", True)),
    )


def _num(data: dict[str, Any], key: str, default: float, cast=float):
    """*default* when *key* is missing or null. Zero is a real value."""
    if key not in data or data[key] is None:
        return cast(default)
    return cast(data[key])


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _stage_to_dict(stage: Stage) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": stage.id,
        "name": stage.name,
        "enabled": stage.enabled,
        "kind": stage.kind,
        "restraints": [_restraint_to_dict(group) for group in stage.restraints],
        "constraints": stage.constraints,
        "hydrogen_mass_da": stage.hydrogen_mass_da,
    }
    if isinstance(stage, MinimizeStage):
        base["tolerance_kj"] = stage.tolerance_kj
        base["max_iterations"] = stage.max_iterations
        return base
    reporters = _reporters_to_dict(stage.reporters)
    base.update(
        {
            "reporters": reporters,
            "observable_ids": list(stage.observable_ids),
            "observable_stride_ps": stage.observable_stride_ps,
        }
    )
    if isinstance(stage, CustomStage):
        base.update(
            {
                "script": stage.script,
                "length_value": stage.length_value,
                "length_unit": stage.length_unit,
                "timestep_fs": stage.timestep_fs,
                "seed": stage.seed,
            }
        )
        return base
    base.update(
        {
            "ensemble": stage.ensemble,
            "integrator": stage.integrator,
            "friction_per_ps": stage.friction_per_ps,
            "temperature_k": stage.temperature_k,
            "temperature_end_k": stage.temperature_end_k,
            "pressure_bar": stage.pressure_bar,
            "pressure_end_bar": stage.pressure_end_bar,
            "barostat": stage.barostat,
            "barostat_interval": stage.barostat_interval,
            "timestep_fs": stage.timestep_fs,
            "length_value": stage.length_value,
            "length_unit": stage.length_unit,
            "velocity_policy": stage.velocity_policy,
            "seed": stage.seed,
        }
    )
    return base


def _stage_from_dict(data: dict[str, Any]) -> Stage:
    if not isinstance(data, dict):
        raise SimulationDocumentError("Each stage must be a JSON object.")
    kind = str(data.get("kind") or "")
    restraints = [_restraint_from_dict(item) for item in data.get("restraints") or []]
    common = {
        "id": str(data.get("id") or new_id("s")),
        "name": str(data.get("name") or kind or "Stage"),
        "enabled": bool(data.get("enabled", True)),
        "restraints": restraints,
        "constraints": data.get("constraints"),
        "hydrogen_mass_da": _optional_float(data.get("hydrogen_mass_da")),
    }
    if kind == STAGE_MINIMIZE:
        return MinimizeStage(
            **common,
            tolerance_kj=_num(data, "tolerance_kj", 10.0),
            max_iterations=int(data.get("max_iterations") or 0),
        )
    reporters = _reporters_from_dict(data.get("reporters"))
    observable_ids = [str(item) for item in data.get("observable_ids") or []]
    stride = _num(data, "observable_stride_ps", 10.0)
    if kind == STAGE_CUSTOM:
        return CustomStage(
            **common,
            script=str(data.get("script") or ""),
            length_value=_num(data, "length_value", 0.0),
            length_unit=str(data.get("length_unit") or "steps"),
            timestep_fs=_num(data, "timestep_fs", 1.0),
            seed=_num(data, "seed", 1, int),
            reporters=reporters,
            observable_ids=observable_ids,
            observable_stride_ps=stride,
        )
    if kind != STAGE_DYNAMICS:
        raise SimulationDocumentError(f"Unknown stage kind {kind!r}.")
    return DynamicsStage(
        **common,
        ensemble=str(data.get("ensemble") or "nvt"),
        integrator=str(data.get("integrator") or "langevin_middle"),
        friction_per_ps=_num(data, "friction_per_ps", 1.0),
        temperature_k=_num(data, "temperature_k", 300.0),
        temperature_end_k=_optional_float(data.get("temperature_end_k")),
        pressure_bar=_num(data, "pressure_bar", 1.0),
        pressure_end_bar=_optional_float(data.get("pressure_end_bar")),
        barostat=str(data.get("barostat") or "montecarlo"),
        barostat_interval=_num(data, "barostat_interval", 25, int),
        timestep_fs=_num(data, "timestep_fs", 2.0),
        length_value=_num(data, "length_value", 0.0),
        length_unit=str(data.get("length_unit") or "ps"),
        velocity_policy=str(data.get("velocity_policy") or "continue"),
        seed=_num(data, "seed", 1, int),
        reporters=reporters,
        observable_ids=observable_ids,
        observable_stride_ps=stride,
    )


def _observable_to_dict(item: Observable) -> dict[str, Any]:
    return {
        "id": item.id,
        "kind": item.kind,
        "selection": item.selection,
        "fit_selection": item.fit_selection,
        "reference": item.reference,
        "stride_ps": item.stride_ps,
        "stage_ids": list(item.stage_ids),
        "cutoff_a": item.cutoff_a,
        "atom_a": item.atom_a,
        "atom_b": item.atom_b,
        "atom_c": item.atom_c,
        "atom_d": item.atom_d,
    }


def _observable_from_dict(data: dict[str, Any]) -> Observable:
    if not isinstance(data, dict):
        raise SimulationDocumentError("Each observable must be a JSON object.")
    return Observable(
        id=str(data.get("id") or new_id("o")),
        kind=str(data.get("kind") or ""),
        selection=str(data.get("selection") or ""),
        fit_selection=str(data.get("fit_selection") or ""),
        reference=str(data.get("reference") or "frame0"),
        stride_ps=_num(data, "stride_ps", 10.0),
        stage_ids=[str(item) for item in data.get("stage_ids") or []],
        cutoff_a=float(data.get("cutoff_a") or 4.0),
        atom_a=str(data.get("atom_a") or ""),
        atom_b=str(data.get("atom_b") or ""),
        atom_c=str(data.get("atom_c") or ""),
        atom_d=str(data.get("atom_d") or ""),
    )
