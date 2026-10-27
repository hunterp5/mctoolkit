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

"""Stage schedules, rebuild rules, and a short real OpenMM run when it is installed."""

from pathlib import Path

import pytest

from molmanager.sim.document import DynamicsStage, ReporterSpec
from molmanager.sim.presets import explicit_npt
from molmanager.sim.protocol import (
    SimulationRunError,
    length_to_steps,
    parse_custom_script,
    pressure_bar,
    read_manifest,
    temperature_kelvin,
    walk_stages,
    write_manifest,
)
from molmanager.sim.protocol import Manifest


class _Fake:
    def __init__(self, pause_at: str = "") -> None:
        self.rebuilt: list[str] = []
        self.ran: list[str] = []
        self.pause_at = pause_at

    def rebuild(self, stage) -> None:
        self.rebuilt.append(stage.id)

    def run_stage(self, stage, *, start_step: int = 0) -> str:
        self.ran.append(stage.id)
        if stage.id == self.pause_at:
            return "pause"
        return "ok"


def test_temperature_and_pressure_ramps():
    stage = DynamicsStage(
        id="heat",
        temperature_k=0.0,
        temperature_end_k=300.0,
        pressure_bar=1.0,
        pressure_end_bar=5.0,
        timestep_fs=2.0,
        length_value=100.0,
        length_unit="ps",
    )
    steps = length_to_steps(100.0, "ps", 2.0)
    assert steps == 50_000
    assert temperature_kelvin(stage, 0, steps) == pytest.approx(0.0)
    assert temperature_kelvin(stage, steps - 1, steps) == pytest.approx(300.0)
    assert temperature_kelvin(stage, (steps - 1) // 2, steps) == pytest.approx(150.0, abs=0.01)
    assert pressure_bar(stage, 0, steps) == pytest.approx(1.0)
    assert pressure_bar(stage, steps - 1, steps) == pytest.approx(5.0)


def test_walk_rebuilds_when_restraints_change_and_pause_keeps_the_stage_open():
    document = explicit_npt()
    engine = _Fake(pause_at="npt")
    result = walk_stages(document, engine)
    assert result.status == "paused"
    assert result.paused_stage == "npt"
    assert "npt" not in result.completed
    assert "heat" in result.completed
    assert engine.rebuilt[0] == "min"
    assert "heat" in engine.rebuilt
    assert "nvt" in engine.rebuilt
    assert "npt" in engine.rebuilt


def test_resume_skips_completed_stages_and_rebuilds_the_edited_one():
    document = explicit_npt()
    document.stages[-1].temperature_k = 310.0
    engine = _Fake()
    result = walk_stages(document, engine, completed={"min", "heat", "nvt", "npt"})
    assert result.status == "finished"
    assert engine.ran == ["prod"]
    assert engine.rebuilt == ["prod"]


def test_custom_script_names_a_bad_line():
    with pytest.raises(SimulationRunError, match="opcode"):
        parse_custom_script("variable v\nnope x = 1\n")
    steps = parse_custom_script("variable v\ncompute v = v+dt*f/m\n")
    assert steps[0] == ("variable", "v")
    assert steps[1][0] == "compute"


def test_manifest_roundtrip(tmp_path: Path):
    path = tmp_path / "manifest.json"
    manifest = Manifest(document_hash="abc", status="paused", completed=["min"], ns_per_day=12.5)
    write_manifest(path, manifest)
    again = read_manifest(path)
    assert again.document_hash == "abc"
    assert again.completed == ["min"]
    assert again.ns_per_day == pytest.approx(12.5)


def test_openmm_checkpoint_resume_and_dcd(tmp_path: Path):
    openmm = pytest.importorskip("openmm")
    from openmm import unit
    from openmm.app import Element, Topology

    from molmanager.sim.document import MinimizeStage, SimulationDocument, SystemSpec
    from molmanager.sim.protocol import run_document
    from molmanager.sim.selection import AtomRecord
    from molmanager.sim.trajectory import read_dcd_xyz

    topology = Topology()
    chain = topology.addChain()
    residue = topology.addResidue("UNK", chain)
    topology.addAtom("C1", Element.getBySymbol("C"), residue)
    topology.addAtom("C2", Element.getBySymbol("C"), residue)
    system = openmm.System()
    system.addParticle(12.0)
    system.addParticle(12.0)
    bond = openmm.HarmonicBondForce()
    bond.addBond(0, 1, 0.15, 1000.0)
    system.addForce(bond)
    positions = [
        openmm.Vec3(0.0, 0.0, 0.0) * unit.nanometer,
        openmm.Vec3(0.2, 0.0, 0.0) * unit.nanometer,
    ]
    document = SimulationDocument(
        name="tiny",
        system=SystemSpec(solvent="vacuum", com_removal="none", hydrogen_mass_da=1.0),
        stages=[
            MinimizeStage(id="min", name="Minimize", max_iterations=5, restraints=[]),
            DynamicsStage(
                id="dyn",
                name="Dynamics",
                ensemble="nve",
                integrator="verlet",
                timestep_fs=1.0,
                length_value=20,
                length_unit="steps",
                velocity_policy="reassign",
                restraints=[],
                reporters=ReporterSpec(energy_ps=0.002, dcd_ps=0.002, checkpoint_ps=0.002),
            ),
        ],
    )
    atoms = [
        AtomRecord(0, "C1", "UNK", "A", 1, element="C", kind="ligand", x=0, y=0, z=0),
        AtomRecord(1, "C2", "UNK", "A", 1, element="C", kind="ligand", x=2, y=0, z=0),
    ]
    out = tmp_path / "run"
    manifest = run_document(
        document,
        topology=topology,
        system=system,
        positions=positions,
        output_dir=out,
        atoms=atoms,
        platform="CPU",
        seed=1,
    )
    assert manifest.status == "finished"
    assert (out / "simulation.chk").is_file()
    assert (out / "state.xml").is_file()
    xyz = read_dcd_xyz(out / "trajectory.dcd")
    assert xyz.shape[1] == 2
    assert xyz.shape[0] >= 1
    resumed = run_document(
        document,
        topology=topology,
        system=system,
        positions=positions,
        output_dir=tmp_path / "resume",
        atoms=atoms,
        platform="CPU",
        resume_checkpoint=str(out / "simulation.chk"),
        completed={"min"},
    )
    assert "dyn" in resumed.completed
