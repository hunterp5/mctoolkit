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

"""Pairwise relative binding free energy. Equal net charge is required."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .document import RunSpec


class FepUnavailable(RuntimeError):
    """OpenFE is not installed, or this pair cannot start."""


class ChargeMismatch(FepUnavailable):
    """The two ligands do not have the same net formal charge."""


@dataclass(frozen=True)
class FepEdge:
    """One reference-to-analog transformation."""

    reference_id: str
    other_id: str
    charge: int


def formal_charge(mol) -> int:
    """Sum of RDKit formal charges. ``mol`` is an RDKit molecule."""
    return int(sum(atom.GetFormalCharge() for atom in mol.GetAtoms()))


def refuse_charge_change(reference_charge: int, other_charge: int) -> str | None:
    """A message when the charges differ, otherwise ``None``."""
    if int(reference_charge) == int(other_charge):
        return None
    return (
        "Relative binding free energy needs equal net charge. "
        f"Reference is {int(reference_charge):+d} and the other ligand is {int(other_charge):+d}."
    )


def star_edges(reference_id: str, ligand_ids: list[str]) -> list[tuple[str, str]]:
    """Edges from *reference_id* to every other id. The reference is not paired with itself."""
    return [(reference_id, other) for other in ligand_ids if other != reference_id]


def lambda_schedule(count: int, explicit: list[float] | None = None) -> list[float]:
    """Evenly spaced windows, or the caller's list when that list is non-empty."""
    if explicit:
        return [float(value) for value in explicit]
    windows = int(count)
    if windows < 2:
        raise FepUnavailable("An alchemical schedule needs at least two lambda windows.")
    return [index / (windows - 1) for index in range(windows)]


def edges_from_charges(reference_id: str, charges: dict[str, int]) -> list[FepEdge]:
    """Star edges that share *reference_id*'s charge. The first mismatch raises."""
    if reference_id not in charges:
        raise FepUnavailable(f"Reference ligand {reference_id!r} has no formal charge.")
    reference = int(charges[reference_id])
    edges: list[FepEdge] = []
    for other, charge in charges.items():
        if other == reference_id:
            continue
        message = refuse_charge_change(reference, int(charge))
        if message:
            raise ChargeMismatch(message)
        edges.append(FepEdge(reference_id, other, reference))
    return edges


def apply_openfe_settings(settings, spec: RunSpec) -> list[str]:
    """Copy the document's alchemical fields onto an OpenFE settings object.

    Only attributes that exist are changed, so a newer OpenFE build keeps
    defaults we do not recognize. The returned names are the fields that were set.
    """
    applied: list[str] = []
    simulation = getattr(settings, "simulation_settings", None)
    if simulation is not None:
        applied.extend(_set_length(simulation, "equilibration_length", spec.fep_equilibration_ps))
        applied.extend(_set_length(simulation, "production_length", spec.fep_production_ps))
        applied.extend(_set_time(simulation, "timestep", spec.fep_timestep_fs, "femtoseconds"))
        if hasattr(simulation, "temperature"):
            simulation.temperature = _quantity(spec.fep_temperature_k, "kelvin")
            applied.append("temperature")
        if hasattr(simulation, "pressure"):
            simulation.pressure = _quantity(spec.fep_pressure_bar, "bar")
            applied.append("pressure")
        if hasattr(simulation, "hydrogen_mass"):
            simulation.hydrogen_mass = _quantity(spec.fep_hydrogen_mass_da, "dalton")
            applied.append("hydrogen_mass")
    alchemical = getattr(settings, "alchemical_settings", None)
    if alchemical is not None and spec.lambda_values:
        if hasattr(alchemical, "lambda_values"):
            alchemical.lambda_values = list(spec.lambda_values)
            applied.append("lambda_values")
    sampler = getattr(settings, "sampler_settings", None)
    if sampler is not None and hasattr(sampler, "sampler_method"):
        sampler.sampler_method = "repex" if spec.fep_replica_exchange else "independent"
        applied.append("sampler_method")
    if hasattr(settings, "protocol_repeats"):
        settings.protocol_repeats = int(spec.fep_repeats)
        applied.append("protocol_repeats")
    solvent = getattr(settings, "solvent_settings", None)
    if solvent is not None and hasattr(solvent, "solvent_padding"):
        solvent.solvent_padding = _quantity(spec.fep_solvent_padding_a, "angstrom")
        applied.append("solvent_padding")
    return applied


def describe_fep(spec: RunSpec) -> dict:
    """JSON-ready description of the schedule, with OpenFE not yet imported."""
    values = lambda_schedule(spec.lambda_count, spec.lambda_values or None)
    return {
        "lambdas": values,
        "n_windows": len(values),
        "equilibration_ps": spec.fep_equilibration_ps,
        "production_ps": spec.fep_production_ps,
        "timestep_fs": spec.fep_timestep_fs,
        "temperature_k": spec.fep_temperature_k,
        "pressure_bar": spec.fep_pressure_bar,
        "hydrogen_mass_da": spec.fep_hydrogen_mass_da,
        "replica_exchange": spec.fep_replica_exchange,
        "repeats": spec.fep_repeats,
        "solvent_padding_a": spec.fep_solvent_padding_a,
    }


def execute_star(
    spec: RunSpec,
    *,
    receptor_path: str,
    ligand_paths: dict[str, str],
    reference_id: str,
    charges: dict[str, int],
    output_dir: str,
) -> list[dict]:
    """Run each star edge. Missing OpenFE raises :class:`FepUnavailable` before any window."""
    edges = edges_from_charges(reference_id, charges)
    try:
        from openfe.protocols.openmm_rfe import RelativeHybridTopologyProtocol
    except ImportError as exc:
        raise FepUnavailable(
            "Relative binding free energy needs the fep extra: pip install 'molmanager[fep]'"
        ) from exc
    settings = RelativeHybridTopologyProtocol.default_settings()
    apply_openfe_settings(settings, spec)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    for edge in edges:
        edge_dir = root / f"{edge.reference_id}__{edge.other_id}"
        edge_dir.mkdir(parents=True, exist_ok=True)
        results.append(
            _execute_one(
                RelativeHybridTopologyProtocol,
                settings,
                receptor_path=receptor_path,
                reference_path=ligand_paths[edge.reference_id],
                other_path=ligand_paths[edge.other_id],
                edge=edge,
                edge_dir=edge_dir,
            )
        )
    return results


def _execute_one(
    protocol_cls, settings, *, receptor_path, reference_path, other_path, edge, edge_dir
):
    """Build an OpenFE protocol object and record its directory.

    The heavy network setup (ChemicalSystem, atom mapping) is delegated to
    OpenFE. A failure here is returned as a row so the rest of the star continues.
    """
    try:
        protocol = protocol_cls(settings=settings)
    except (TypeError, ValueError, AttributeError) as exc:
        return {
            "reference": edge.reference_id,
            "other": edge.other_id,
            "status": "failed",
            "message": str(exc),
            "directory": str(edge_dir),
        }
    note = edge_dir / "edge.txt"
    note.write_text(
        "\n".join(
            [
                f"reference {edge.reference_id} {reference_path}",
                f"other {edge.other_id} {other_path}",
                f"receptor {receptor_path}",
                f"charge {edge.charge:+d}",
                f"protocol {type(protocol).__name__}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "reference": edge.reference_id,
        "other": edge.other_id,
        "status": "prepared",
        "dG": None,
        "uncertainty": None,
        "message": "OpenFE protocol settings were written. Run the protocol directory to sample.",
        "directory": str(edge_dir),
    }


def _set_length(settings, name: str, picoseconds: float) -> list[str]:
    if not hasattr(settings, name):
        return []
    setattr(settings, name, _quantity(picoseconds, "picoseconds"))
    return [name]


def _set_time(settings, name: str, femtoseconds: float, unit_name: str) -> list[str]:
    if not hasattr(settings, name):
        return []
    setattr(settings, name, _quantity(femtoseconds, unit_name))
    return [name]


def _quantity(value: float, unit_name: str):
    try:
        from openmm import unit
    except ImportError:
        return float(value)
    units = {
        "picoseconds": unit.picoseconds,
        "femtoseconds": unit.femtoseconds,
        "kelvin": unit.kelvin,
        "bar": unit.bar,
        "dalton": unit.dalton,
        "angstrom": unit.angstrom,
    }
    return float(value) * units[unit_name]
