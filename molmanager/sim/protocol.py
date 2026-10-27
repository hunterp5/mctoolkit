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

"""Walk a stage list. Each stage can rebuild the system and carry coordinates forward."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .document import (
    STAGE_MINIMIZE,
    CustomStage,
    DynamicsStage,
    MinimizeStage,
    SimulationDocument,
    Stage,
    SystemSpec,
)
from .selection import AtomRecord, SelectionError, select_atom_indices
from .trajectory import TrajectoryError

_FREEZE_K = 1.0e6


class SimulationRunError(RuntimeError):
    """A stage could not be started or a restart file could not be read."""


class StageController(Protocol):
    """What the walker asks the engine to do. Tests supply a fake."""

    def rebuild(self, stage: Stage) -> None:
        """Create a new OpenMM system for *stage* and keep the current coordinates."""

    def run_stage(self, stage: Stage, *, start_step: int = 0) -> str:
        """Run *stage*. Return ``ok``, ``pause``, or ``cancel``."""


@dataclass
class WalkResult:
    """Where a walk stopped. A paused stage is not listed in ``completed``."""

    status: str
    completed: tuple[str, ...]
    paused_stage: str = ""
    rebuilt: tuple[str, ...] = ()


@dataclass
class RunPaths:
    """Files one run writes next to the trajectory."""

    output_dir: Path
    manifest: Path
    scalars: Path
    checkpoint: Path
    state_xml: Path
    dcd: Path

    @classmethod
    def create(cls, output_dir: str | Path) -> RunPaths:
        root = Path(output_dir)
        root.mkdir(parents=True, exist_ok=True)
        return cls(
            output_dir=root,
            manifest=root / "manifest.json",
            scalars=root / "scalars.csv",
            checkpoint=root / "simulation.chk",
            state_xml=root / "state.xml",
            dcd=root / "trajectory.dcd",
        )


@dataclass
class Manifest:
    """Reproducibility record updated as stages finish."""

    document_hash: str
    status: str = "running"
    completed: list[str] = field(default_factory=list)
    paused_stage: str = ""
    stage_step: int = 0
    platform: str = ""
    precision: str = ""
    seed: int = 1
    ns_per_day: float | None = None
    solute_atoms: int = 0
    files: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "document_hash": self.document_hash,
            "status": self.status,
            "completed": list(self.completed),
            "paused_stage": self.paused_stage,
            "stage_step": self.stage_step,
            "platform": self.platform,
            "precision": self.precision,
            "seed": self.seed,
            "ns_per_day": self.ns_per_day,
            "solute_atoms": self.solute_atoms,
            "files": dict(self.files),
        }


def length_to_steps(value: float, unit: str, timestep_fs: float) -> int:
    """Convert a stage length to integrator steps."""
    if unit == "steps":
        return max(0, int(round(value)))
    if timestep_fs <= 0:
        raise SimulationRunError("Timestep must be positive.")
    picoseconds = float(value)
    if unit == "ns":
        picoseconds *= 1000.0
    elif unit != "ps":
        raise SimulationRunError(f"Unknown length unit {unit!r}.")
    return max(0, int(round(picoseconds * 1000.0 / timestep_fs)))


def stage_steps(stage: Stage) -> int:
    """Step count for a dynamics or custom stage. Minimize returns 0."""
    if isinstance(stage, MinimizeStage):
        return 0
    return length_to_steps(stage.length_value, stage.length_unit, stage.timestep_fs)


def temperature_kelvin(stage: DynamicsStage, step: int, n_steps: int) -> float:
    """Temperature at *step*. A ramp runs from the start value to ``temperature_end_k``."""
    start = float(stage.temperature_k)
    end = stage.temperature_end_k
    if end is None or n_steps <= 1:
        return float(end if end is not None and n_steps <= 1 else start)
    fraction = min(1.0, max(0.0, step / (n_steps - 1)))
    return start + (float(end) - start) * fraction


def pressure_bar(stage: DynamicsStage, step: int, n_steps: int) -> float:
    """Pressure at *step*, constant unless ``pressure_end_bar`` is set."""
    start = float(stage.pressure_bar)
    end = stage.pressure_end_bar
    if end is None or n_steps <= 1:
        return float(end if end is not None and n_steps <= 1 else start)
    fraction = min(1.0, max(0.0, step / (n_steps - 1)))
    return start + (float(end) - start) * fraction


def stage_signature(stage: Stage, system: SystemSpec) -> tuple:
    """Fields that force a new OpenMM system before the stage runs."""
    restraints = tuple(
        (
            group.selection,
            group.form,
            group.k_kcal_per_ang2,
            group.radius_a,
            group.reference,
            group.atoms,
        )
        for group in stage.restraints
    )
    constraints = stage.constraints or system.constraints
    hydrogen_mass = stage.hydrogen_mass_da
    if hydrogen_mass is None:
        hydrogen_mass = system.hydrogen_mass_da
    ensemble = getattr(stage, "ensemble", STAGE_MINIMIZE)
    barostat = getattr(stage, "barostat", "") if ensemble == "npt" else ""
    return (restraints, constraints, float(hydrogen_mass), ensemble, barostat)


def needs_rebuild(previous: tuple | None, current: tuple) -> bool:
    """True when *current* is the first stage or differs from *previous*."""
    return previous != current


def restraint_expression(form: str) -> str:
    """OpenMM custom-force expression for a positional restraint form."""
    harmonic = "0.5*k*((x-x0)^2+(y-y0)^2+(z-z0)^2)"
    if form in {"harmonic", "freeze"}:
        return harmonic
    if form == "flat_bottom":
        return "0.5*k*max(0, sqrt((x-x0)^2+(y-y0)^2+(z-z0)^2)-r0)^2"
    if form == "distance":
        return "0.5*k*(r-r0)^2"
    if form == "angle":
        return "0.5*k*(theta-theta0)^2"
    if form == "dihedral":
        return "0.5*k*min(dtheta, 2*pi-dtheta)^2; dtheta=abs(theta-theta0)"
    if form == "rmsd":
        return "0.5*k*(rmsd-rmsd0)^2"
    raise SimulationRunError(f"Unknown restraint form {form!r}.")


def parse_custom_script(script: str) -> list[tuple[str, str]]:
    """Parse a custom-integrator script into ``(opcode, argument)`` lines.

    Opcodes are ``variable``, ``global``, ``compute``, ``compute_global``,
    ``update_context``, and ``constrain_positions``. A bad line raises
    :class:`SimulationRunError` naming that line.
    """
    steps: list[tuple[str, str]] = []
    for raw in (script or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        opcode, _, argument = line.partition(" ")
        opcode = opcode.strip().lower()
        argument = argument.strip()
        if opcode in {"update_context", "constrain_positions"}:
            steps.append((opcode, ""))
            continue
        if opcode in {"variable", "global"}:
            if not argument:
                raise SimulationRunError(f"Custom integrator line needs a name: {raw!r}.")
            steps.append((opcode, argument))
            continue
        if opcode in {"compute", "compute_global"}:
            if "=" not in argument:
                raise SimulationRunError(f"Custom integrator line needs '=': {raw!r}.")
            steps.append((opcode, argument))
            continue
        raise SimulationRunError(f"Unknown custom integrator opcode in {raw!r}.")
    if not steps:
        raise SimulationRunError("Custom integrator script is empty.")
    return steps


def walk_stages(
    document: SimulationDocument,
    controller: StageController,
    *,
    completed: set[str] | None = None,
) -> WalkResult:
    """Run enabled stages that are not already in *completed*.

    The first remaining stage always rebuilds. Later stages rebuild when their
    restraint, constraint, hydrogen-mass, ensemble, or barostat signature changes.
    """
    done = set(completed or ())
    previous: tuple | None = None
    rebuilt: list[str] = []
    for stage in document.stages:
        if not stage.enabled or stage.id in done:
            continue
        signature = stage_signature(stage, document.system)
        if needs_rebuild(previous, signature):
            controller.rebuild(stage)
            rebuilt.append(stage.id)
        previous = signature
        status = controller.run_stage(stage, start_step=0)
        if status == "pause":
            return WalkResult("paused", tuple(done), paused_stage=stage.id, rebuilt=tuple(rebuilt))
        if status == "cancel":
            return WalkResult(
                "cancelled", tuple(done), paused_stage=stage.id, rebuilt=tuple(rebuilt)
            )
        if status != "ok":
            raise SimulationRunError(f"Stage {stage.name} returned {status!r}.")
        done.add(stage.id)
    return WalkResult("finished", tuple(done), rebuilt=tuple(rebuilt))


def write_manifest(path: str | Path, manifest: Manifest) -> None:
    """Replace the manifest file."""
    Path(path).write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")


def read_manifest(path: str | Path) -> Manifest:
    """Load a manifest written by :func:`write_manifest`."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SimulationRunError(f"Could not read the run manifest: {exc}") from exc
    manifest = Manifest(document_hash=str(data.get("document_hash") or ""))
    manifest.status = str(data.get("status") or "")
    manifest.completed = [str(item) for item in data.get("completed") or []]
    manifest.paused_stage = str(data.get("paused_stage") or "")
    manifest.stage_step = int(data.get("stage_step") or 0)
    manifest.platform = str(data.get("platform") or "")
    manifest.precision = str(data.get("precision") or "")
    manifest.seed = int(data.get("seed") or 1)
    ns_per_day = data.get("ns_per_day")
    manifest.ns_per_day = None if ns_per_day is None else float(ns_per_day)
    manifest.solute_atoms = int(data.get("solute_atoms") or 0)
    manifest.files = {str(key): str(value) for key, value in (data.get("files") or {}).items()}
    return manifest


def selected_indices(expression: str, atoms: list[AtomRecord]) -> list[int]:
    """Selection indices, or a run error that names the bad token."""
    try:
        return select_atom_indices(expression, atoms)
    except SelectionError as exc:
        raise SimulationRunError(str(exc)) from exc


def restraint_k(group_form: str, k_kcal: float) -> float:
    """Force constant actually applied. Freeze uses a very large harmonic k."""
    if group_form == "freeze":
        return _FREEZE_K
    return float(k_kcal)


def ns_per_day(elapsed_s: float, timestep_fs: float, steps: int) -> float | None:
    """Nanoseconds per day from a measured stretch of dynamics."""
    if elapsed_s <= 0 or steps <= 0 or timestep_fs <= 0:
        return None
    nanoseconds = steps * timestep_fs * 1.0e-6
    return nanoseconds * (86400.0 / elapsed_s)


def run_document(
    document: SimulationDocument,
    *,
    topology,
    system,
    positions,
    output_dir: str | Path,
    atoms: list[AtomRecord] | None = None,
    velocities=None,
    box=None,
    platform: str = "auto",
    precision: str = "mixed",
    device_index: int = 0,
    seed: int = 1,
    resume_state: str = "",
    resume_checkpoint: str = "",
    completed: set[str] | None = None,
    should_pause=None,
    should_cancel=None,
    on_scalar=None,
    solute_atoms: int = 0,
) -> Manifest:
    """Run *document* on an OpenMM system. Pause writes ``state.xml`` and stops."""
    paths = RunPaths.create(output_dir)
    manifest = Manifest(
        document_hash=document.content_hash(),
        platform=platform,
        precision=precision,
        seed=seed,
        solute_atoms=solute_atoms,
        files={
            "scalars": str(paths.scalars),
            "checkpoint": str(paths.checkpoint),
            "state_xml": str(paths.state_xml),
            "dcd": str(paths.dcd),
        },
    )
    if completed:
        manifest.completed = sorted(completed)
    engine = OpenMMEngine(
        document=document,
        topology=topology,
        system=system,
        positions=positions,
        velocities=velocities,
        box=box,
        paths=paths,
        atoms=atoms or [],
        platform=platform,
        precision=precision,
        device_index=device_index,
        seed=seed,
        resume_state=resume_state,
        resume_checkpoint=resume_checkpoint,
        should_pause=should_pause,
        should_cancel=should_cancel,
        on_scalar=on_scalar,
        manifest=manifest,
    )
    result = walk_stages(document, engine, completed=completed)
    manifest.status = result.status
    manifest.completed = list(result.completed)
    manifest.paused_stage = result.paused_stage
    manifest.ns_per_day = engine.ns_per_day
    write_manifest(paths.manifest, manifest)
    return manifest


class OpenMMEngine:
    """OpenMM implementation of :class:`StageController`."""

    def __init__(
        self,
        *,
        document: SimulationDocument,
        topology,
        system,
        positions,
        velocities,
        box,
        paths: RunPaths,
        atoms: list[AtomRecord],
        platform: str,
        precision: str,
        device_index: int,
        seed: int,
        resume_state: str,
        resume_checkpoint: str,
        should_pause,
        should_cancel,
        on_scalar,
        manifest: Manifest,
    ) -> None:
        self.document = document
        self.topology = topology
        self.system = system
        self.positions = positions
        self.velocities = velocities
        self.box = box
        self.paths = paths
        self.atoms = atoms
        self.platform = platform
        self.precision = precision
        self.device_index = device_index
        self.seed = seed
        self.resume_state = resume_state
        self.resume_checkpoint = resume_checkpoint
        self.should_pause = should_pause or (lambda: False)
        self.should_cancel = should_cancel or (lambda: False)
        self.on_scalar = on_scalar
        self.manifest = manifest
        self.ns_per_day: float | None = None
        self._used_resume = False

    def rebuild(self, stage: Stage) -> None:
        """Update masses, the barostat, and COM removal before the stage's integrator."""
        self._apply_hydrogen_mass(stage)
        self._install_barostat(stage)
        self._ensure_com_remover()

    def run_stage(self, stage: Stage, *, start_step: int = 0) -> str:
        if isinstance(stage, MinimizeStage):
            return self._minimize(stage)
        return self._dynamics(stage, start_step=start_step)

    def _minimize(self, stage: MinimizeStage) -> str:
        simulation = self._simulation(stage, temperature_k=300.0)
        self._load_resume(simulation)
        tolerance = float(stage.tolerance_kj)
        simulation.minimizeEnergy(maxIterations=int(stage.max_iterations), tolerance=tolerance)
        self._capture(simulation)
        self._save_state(simulation)
        return self._stop_status()

    def _dynamics(self, stage: DynamicsStage | CustomStage, *, start_step: int) -> str:
        import time

        n_steps = stage_steps(stage)
        simulation = self._simulation(stage, temperature_k=_initial_temperature(stage))
        self._load_resume(simulation)
        self._velocities(simulation, stage)
        chunk = _chunk_steps(stage)
        begun = time.perf_counter()
        step = max(0, start_step)
        while step < n_steps:
            if self.should_cancel():
                self._save_checkpoint(simulation)
                self.manifest.stage_step = step
                return "cancel"
            if self.should_pause():
                self._save_state(simulation)
                self.manifest.stage_step = step
                return "pause"
            take = min(chunk, n_steps - step)
            if isinstance(stage, DynamicsStage):
                self._set_schedule(simulation, stage, step, n_steps)
            simulation.step(take)
            step += take
            self._report(simulation, stage, step, n_steps)
            self._save_checkpoint(simulation)
        elapsed = time.perf_counter() - begun
        timestep = stage.timestep_fs
        measured = ns_per_day(elapsed, timestep, n_steps)
        if measured is not None:
            self.ns_per_day = measured
        self._capture(simulation)
        self._save_state(simulation)
        return "ok"

    def _simulation(self, stage: Stage, *, temperature_k: float):
        try:
            import openmm
            from openmm import unit
            from openmm.app import Simulation
        except ImportError as exc:
            raise SimulationRunError(
                "OpenMM is required to run a simulation. Install the docking extra: "
                "pip install 'openmm>=8.2,<8.3'"
            ) from exc
        self._install_restraints(stage)
        integrator = _integrator(stage, temperature_k)
        platform, properties = _platform(self.platform, self.precision, self.device_index)
        if platform is None:
            simulation = Simulation(self.topology, self.system, integrator)
        else:
            simulation = Simulation(self.topology, self.system, integrator, platform, properties)
        simulation.context.setPositions(self.positions)
        if self.box is not None:
            simulation.context.setPeriodicBoxVectors(*self.box)
        if self.velocities is not None:
            simulation.context.setVelocities(self.velocities)
        self.manifest.platform = simulation.context.getPlatform().getName()
        _ = (openmm, unit)
        return simulation

    def _install_restraints(self, stage: Stage) -> None:
        try:
            import openmm
            from openmm import unit
        except ImportError as exc:
            raise SimulationRunError("OpenMM is required to add restraints.") from exc
        _drop_named_forces(self.system, "molmanager-restraint")
        positional = [
            group
            for group in stage.restraints
            if group.form in {"harmonic", "flat_bottom", "freeze"}
        ]
        if not positional or not self.atoms:
            return
        k_unit = unit.kilocalories_per_mole / unit.angstrom**2
        for form in ("harmonic", "flat_bottom", "freeze"):
            groups = [group for group in positional if group.form == form]
            if not groups:
                continue
            force = openmm.CustomExternalForce(restraint_expression(form))
            force.setName("molmanager-restraint")
            force.addGlobalParameter(
                "k",
                restraint_k(form, groups[0].k_kcal_per_ang2) * k_unit,
            )
            force.addPerParticleParameter("x0")
            force.addPerParticleParameter("y0")
            force.addPerParticleParameter("z0")
            if form == "flat_bottom":
                force.addGlobalParameter("r0", float(groups[0].radius_a) * unit.angstrom)
            for group in groups:
                for index in selected_indices(group.selection, self.atoms):
                    if index >= len(self.positions):
                        continue
                    xyz = self.positions[index].value_in_unit(unit.nanometer)
                    force.addParticle(index, [float(xyz[0]), float(xyz[1]), float(xyz[2])])
            if force.getNumParticles():
                self.system.addForce(force)

    def _apply_hydrogen_mass(self, stage: Stage) -> None:
        mass = stage.hydrogen_mass_da
        if mass is None:
            mass = self.document.system.hydrogen_mass_da
        if mass is None or float(mass) <= 1.01 or not self.atoms:
            return
        try:
            from openmm import unit
        except ImportError as exc:
            raise SimulationRunError(
                "OpenMM is required for hydrogen mass repartitioning."
            ) from exc
        target = float(mass) * unit.dalton
        heavy_of: dict[int, int] = {}
        for atom in self.atoms:
            if _is_hydrogen_name(atom) and atom.index > 0:
                heavy_of.setdefault(atom.index, atom.index - 1)
        for hydrogen, heavy in heavy_of.items():
            if hydrogen >= self.system.getNumParticles() or heavy >= self.system.getNumParticles():
                continue
            current = self.system.getParticleMass(hydrogen)
            delta = target - current
            if delta.value_in_unit(unit.dalton) <= 0:
                continue
            self.system.setParticleMass(hydrogen, target)
            self.system.setParticleMass(heavy, self.system.getParticleMass(heavy) - delta)

    def _install_barostat(self, stage: Stage) -> None:
        try:
            import openmm
            from openmm import unit
        except ImportError as exc:
            raise SimulationRunError("OpenMM is required to add a barostat.") from exc
        for index in range(self.system.getNumForces() - 1, -1, -1):
            if type(self.system.getForce(index)).__name__.endswith("Barostat"):
                self.system.removeForce(index)
        if not isinstance(stage, DynamicsStage) or stage.ensemble != "npt":
            return
        pressure = float(stage.pressure_bar) * unit.bar
        temperature = float(stage.temperature_k) * unit.kelvin
        interval = int(stage.barostat_interval)
        if stage.barostat == "anisotropic":
            force = openmm.MonteCarloAnisotropicBarostat(
                pressure, pressure, pressure, temperature, interval
            )
        else:
            force = openmm.MonteCarloBarostat(pressure, temperature, interval)
        self.system.addForce(force)

    def _ensure_com_remover(self) -> None:
        if self.document.system.com_removal == "none":
            return
        for index in range(self.system.getNumForces()):
            if type(self.system.getForce(index)).__name__ == "CMMotionRemover":
                return
        try:
            import openmm
        except ImportError as exc:
            raise SimulationRunError("OpenMM is required to remove center-of-mass motion.") from exc
        self.system.addForce(openmm.CMMotionRemover(int(self.document.system.com_interval)))

    def _velocities(self, simulation, stage: Stage) -> None:
        policy = getattr(stage, "velocity_policy", "continue")
        if policy == "continue" and self.velocities is not None:
            return
        try:
            from openmm import unit
        except ImportError as exc:
            raise SimulationRunError("OpenMM is required to assign velocities.") from exc
        if policy == "zero":
            simulation.context.setVelocitiesToTemperature(0.0 * unit.kelvin)
            return
        temperature = _initial_temperature(stage)
        simulation.context.setVelocitiesToTemperature(temperature * unit.kelvin, self.seed)

    def _set_schedule(self, simulation, stage: DynamicsStage, step: int, n_steps: int) -> None:
        try:
            from openmm import unit
        except ImportError as exc:
            raise SimulationRunError("OpenMM is required to update the thermostat.") from exc
        temperature = temperature_kelvin(stage, step, n_steps)
        integrator = simulation.integrator
        setter = getattr(integrator, "setTemperature", None)
        if callable(setter):
            setter(temperature * unit.kelvin)
        if stage.ensemble == "npt":
            pressure = pressure_bar(stage, step, n_steps)
            for index in range(self.system.getNumForces()):
                force = self.system.getForce(index)
                if force.getName() == "MonteCarloBarostat" or type(force).__name__.endswith(
                    "Barostat"
                ):
                    parameter = getattr(type(force), "Pressure", None)
                    if callable(parameter):
                        simulation.context.setParameter(parameter(), pressure)

    def _report(self, simulation, stage: Stage, step: int, n_steps: int) -> None:
        state = simulation.context.getState(getEnergy=True, getPositions=True)
        potential = state.getPotentialEnergy()
        try:
            from openmm import unit

            kcal = float(potential.value_in_unit(unit.kilocalories_per_mole))
        except (AttributeError, TypeError):
            kcal = float(potential)
        time_ps = step * float(getattr(stage, "timestep_fs", 2.0)) / 1000.0
        row = {"time_ps": time_ps, "E_pot_kcal": kcal, "step": step, "stage": stage.id}
        self._append_scalar(row)
        if self.on_scalar is not None:
            self.on_scalar(row)
        reporters = getattr(stage, "reporters", None)
        if reporters is not None and reporters.dcd_ps:
            self._append_dcd_frame(state)
        _ = n_steps

    def _append_scalar(self, row: dict) -> None:
        path = self.paths.scalars
        new_file = not path.is_file()
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            if new_file:
                handle.write("stage,step,time_ps,E_pot_kcal\n")
            handle.write(
                f"{row['stage']},{int(row['step'])},{row['time_ps']:.4f},{row['E_pot_kcal']:.6g}\n"
            )

    def _append_dcd_frame(self, state) -> None:
        positions = state.getPositions(asNumpy=True)
        try:
            from openmm import unit

            angstrom = positions.value_in_unit(unit.angstrom)
        except (AttributeError, TypeError):
            return
        import numpy as np

        frame = np.asarray(angstrom, dtype=float).reshape(1, -1, 3)
        from .trajectory import read_dcd_xyz, write_dcd

        if self.paths.dcd.is_file():
            try:
                previous = read_dcd_xyz(self.paths.dcd)
            except TrajectoryError:
                previous = frame[:0]
            if previous.shape[0]:
                frame = np.concatenate([previous, frame], axis=0)
        write_dcd(self.paths.dcd, frame)

    def _save_checkpoint(self, simulation) -> None:
        simulation.saveCheckpoint(str(self.paths.checkpoint))

    def _save_state(self, simulation) -> None:
        simulation.saveState(str(self.paths.state_xml))

    def _capture(self, simulation) -> None:
        state = simulation.context.getState(getPositions=True, getVelocities=True)
        self.positions = state.getPositions()
        self.velocities = state.getVelocities()

    def _load_resume(self, simulation) -> None:
        if self._used_resume:
            return
        self._used_resume = True
        if self.resume_state and Path(self.resume_state).is_file():
            simulation.loadState(self.resume_state)
            self._capture(simulation)
            return
        if self.resume_checkpoint and Path(self.resume_checkpoint).is_file():
            simulation.loadCheckpoint(self.resume_checkpoint)
            self._capture(simulation)

    def _stop_status(self) -> str:
        if self.should_cancel():
            return "cancel"
        if self.should_pause():
            return "pause"
        return "ok"


def _initial_temperature(stage: Stage) -> float:
    if isinstance(stage, DynamicsStage):
        return float(stage.temperature_k)
    return 300.0


def _chunk_steps(stage: Stage) -> int:
    reporters = getattr(stage, "reporters", None)
    timestep = float(getattr(stage, "timestep_fs", 2.0) or 2.0)
    if reporters is None or not reporters.energy_ps:
        return max(1, length_to_steps(1.0, "ps", timestep))
    return max(1, length_to_steps(float(reporters.energy_ps), "ps", timestep))


def _integrator(stage: Stage, temperature_k: float):
    from openmm import LangevinIntegrator, LangevinMiddleIntegrator, VerletIntegrator, unit

    timestep = float(getattr(stage, "timestep_fs", 1.0)) * unit.femtoseconds
    temperature = float(temperature_k) * unit.kelvin
    if isinstance(stage, CustomStage):
        from openmm import CustomIntegrator

        integrator = CustomIntegrator(timestep)
        _apply_custom_script(integrator, stage.script)
        return integrator
    if not isinstance(stage, DynamicsStage):
        return LangevinMiddleIntegrator(temperature, 1.0 / unit.picosecond, timestep)
    friction = float(stage.friction_per_ps) / unit.picosecond
    name = stage.integrator
    if name == "langevin":
        return LangevinIntegrator(temperature, friction, timestep)
    if name == "verlet":
        return VerletIntegrator(timestep)
    if name == "brownian":
        from openmm import BrownianIntegrator

        return BrownianIntegrator(temperature, friction, timestep)
    if name == "variable_verlet":
        from openmm import VariableVerletIntegrator

        return VariableVerletIntegrator(0.001)
    if name == "variable_langevin":
        from openmm import VariableLangevinIntegrator

        return VariableLangevinIntegrator(temperature, friction, 0.001)
    if name == "nose_hoover":
        from openmm import NoseHooverIntegrator

        return NoseHooverIntegrator(temperature, friction, timestep)
    return LangevinMiddleIntegrator(temperature, friction, timestep)


def _apply_custom_script(integrator, script: str) -> None:
    for opcode, argument in parse_custom_script(script):
        if opcode == "variable":
            name, _, value = argument.partition(" ")
            integrator.addPerDofVariable(name, float(value) if value else 0.0)
        elif opcode == "global":
            name, _, value = argument.partition(" ")
            integrator.addGlobalVariable(name, float(value or "0"))
        elif opcode == "compute":
            name, _, expr = argument.partition("=")
            integrator.addComputePerDof(name.strip(), expr.strip())
        elif opcode == "compute_global":
            name, _, expr = argument.partition("=")
            integrator.addComputeGlobal(name.strip(), expr.strip())
        elif opcode == "update_context":
            integrator.addUpdateContextState()
        elif opcode == "constrain_positions":
            integrator.addConstrainPositions()


def _platform(name: str, precision: str, device_index: int):
    try:
        import openmm
    except ImportError:
        return None, {}
    wanted = {"cuda": "CUDA", "opencl": "OpenCL", "cpu": "CPU", "reference": "Reference"}.get(
        (name or "auto").lower()
    )
    available = [
        openmm.Platform.getPlatform(index).getName()
        for index in range(openmm.Platform.getNumPlatforms())
    ]
    if wanted is None:
        for candidate in ("CUDA", "OpenCL", "CPU"):
            if candidate in available:
                wanted = candidate
                break
    if wanted not in available:
        return None, {}
    platform = openmm.Platform.getPlatformByName(wanted)
    properties: dict[str, str] = {}
    if wanted == "CUDA":
        properties["CudaPrecision"] = (
            precision if precision in {"single", "mixed", "double"} else "mixed"
        )
        properties["DeviceIndex"] = str(int(device_index))
    elif wanted == "OpenCL":
        properties["OpenCLPrecision"] = (
            precision if precision in {"single", "mixed", "double"} else "mixed"
        )
        properties["DeviceIndex"] = str(int(device_index))
    elif wanted == "CPU":
        properties["Threads"] = "1"
    return platform, properties


def _drop_named_forces(system, name: str) -> None:
    for index in range(system.getNumForces() - 1, -1, -1):
        force = system.getForce(index)
        if getattr(force, "getName", lambda: "")() == name:
            system.removeForce(index)


def _is_hydrogen_name(atom: AtomRecord) -> bool:
    element = (atom.element or "").upper()
    if element in {"H", "D"}:
        return True
    return atom.name.strip().upper().startswith("H")
