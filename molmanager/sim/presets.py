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

"""Editable starting documents. Saving over a preset stores the user's copy."""

from __future__ import annotations

from .document import (
    DynamicsStage,
    MinimizeStage,
    Observable,
    ReporterSpec,
    RestraintGroup,
    SimulationDocument,
    SystemSpec,
)

_BACKBONE_LIGAND = "backbone or (ligand and heavy)"


def _hold(selection: str, k: float) -> list[RestraintGroup]:
    return [RestraintGroup(selection=selection, form="harmonic", k_kcal_per_ang2=k)]


def gb_relax() -> SimulationDocument:
    """Minimize, a short restrained NVT leg, then a short free NVT leg."""
    return SimulationDocument(
        name="GB relax",
        system=SystemSpec(solvent="gbn2", nonbonded="nocutoff", salt_m=0.15, gbsa=True),
        stages=[
            MinimizeStage(
                id="min",
                name="Minimize",
                max_iterations=400,
                restraints=_hold(_BACKBONE_LIGAND, 10.0),
            ),
            DynamicsStage(
                id="eq",
                name="Restrained NVT",
                ensemble="nvt",
                temperature_k=300.0,
                timestep_fs=2.0,
                length_value=10.0,
                length_unit="ps",
                velocity_policy="reassign",
                restraints=_hold(_BACKBONE_LIGAND, 10.0),
                reporters=ReporterSpec(energy_ps=1.0, dcd_ps=None, checkpoint_ps=10.0),
            ),
            DynamicsStage(
                id="prod",
                name="Free NVT",
                ensemble="nvt",
                temperature_k=300.0,
                timestep_fs=2.0,
                length_value=20.0,
                length_unit="ps",
                velocity_policy="continue",
                restraints=[],
                reporters=ReporterSpec(energy_ps=1.0, dcd_ps=1.0, checkpoint_ps=10.0),
                observable_ids=["rmsd"],
            ),
        ],
        observables=[
            Observable(id="rmsd", kind="rmsd", selection="ligand and heavy", fit_selection="ca"),
        ],
    )


def explicit_npt() -> SimulationDocument:
    """Minimize, heat, restrained NVT, restrained NPT, then free NPT production."""
    return SimulationDocument(
        name="Explicit NPT",
        system=SystemSpec(
            solvent="tip3p",
            nonbonded="pme",
            box_shape="cubic",
            box_padding_a=10.0,
            ion_mode="concentration",
            ion_conc_m=0.15,
            hydrogen_mass_da=1.0,
        ),
        stages=[
            MinimizeStage(
                id="min",
                name="Minimize",
                max_iterations=500,
                restraints=_hold(_BACKBONE_LIGAND, 10.0),
            ),
            DynamicsStage(
                id="heat",
                name="Heat",
                ensemble="nvt",
                temperature_k=0.0,
                temperature_end_k=300.0,
                timestep_fs=1.0,
                length_value=100.0,
                length_unit="ps",
                velocity_policy="reassign",
                seed=1,
                restraints=_hold(_BACKBONE_LIGAND, 10.0),
                reporters=ReporterSpec(energy_ps=1.0, dcd_ps=None, checkpoint_ps=20.0),
            ),
            DynamicsStage(
                id="nvt",
                name="Equilibrate NVT",
                ensemble="nvt",
                temperature_k=300.0,
                timestep_fs=2.0,
                length_value=200.0,
                length_unit="ps",
                velocity_policy="continue",
                restraints=_hold(_BACKBONE_LIGAND, 5.0),
            ),
            DynamicsStage(
                id="npt",
                name="Equilibrate NPT",
                ensemble="npt",
                temperature_k=300.0,
                pressure_bar=1.0,
                timestep_fs=2.0,
                length_value=500.0,
                length_unit="ps",
                velocity_policy="continue",
                restraints=_hold("backbone", 2.0),
            ),
            DynamicsStage(
                id="prod",
                name="Production",
                ensemble="npt",
                temperature_k=300.0,
                pressure_bar=1.0,
                timestep_fs=2.0,
                length_value=10.0,
                length_unit="ns",
                velocity_policy="continue",
                hydrogen_mass_da=4.0,
                restraints=[],
                reporters=ReporterSpec(
                    energy_ps=1.0,
                    dcd_ps=10.0,
                    checkpoint_ps=100.0,
                    state_xml_ps=1000.0,
                    wrap_dcd=True,
                ),
                observable_ids=["rmsd", "contacts", "mmgbsa"],
                observable_stride_ps=10.0,
            ),
        ],
        observables=[
            Observable(id="rmsd", kind="rmsd", selection="ligand and heavy", fit_selection="ca"),
            Observable(id="contacts", kind="contacts", selection="ligand", cutoff_a=4.0),
            Observable(id="mmgbsa", kind="mmgbsa", selection="ligand", stride_ps=100.0),
        ],
    )


def blank() -> SimulationDocument:
    """One minimize stage and one dynamics stage with the fields filled in."""
    return SimulationDocument(
        name="Blank",
        system=SystemSpec(),
        stages=[
            MinimizeStage(id="min", name="Minimize", restraints=_hold("backbone", 10.0)),
            DynamicsStage(
                id="dyn",
                name="Dynamics",
                ensemble="nvt",
                temperature_k=300.0,
                length_value=100.0,
                length_unit="ps",
                velocity_policy="reassign",
                restraints=[],
            ),
        ],
        observables=[
            Observable(id="rmsd", kind="rmsd", selection="ligand and heavy", fit_selection="ca"),
        ],
    )


PRESETS = {
    "gb_relax": gb_relax,
    "explicit_npt": explicit_npt,
    "blank": blank,
}
