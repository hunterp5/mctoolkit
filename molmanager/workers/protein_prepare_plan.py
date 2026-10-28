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

"""Fast Prepare start checks and request assembly. No Qt.

The dialog reads widgets and viewer payloads, then calls these functions and
shows ``ProteinPrepareStart.message``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

_CIF_OUTPUT_SUFFIXES = {".cif", ".mmcif", ".mcif"}
_CIF_SOURCE_FMTS = {"cif", "mmcif"}
_GAFF_FORCE_FIELDS = {"gaff", "gaff2"}
_PARSE_ERRORS = (TypeError, ValueError, KeyError, IndexError, AttributeError)

EMPTY_OUTPUT = "Set an output path."
UNSUPPORTED_FORMAT = "Fast Prepare supports PDB and mmCIF. Convert or reload as PDB first."
NO_STEP = (
    "Check Clean up, Protonate, Restrained minimization, or Write Gnina "
    "files so there is a step to run."
)
NO_SELECTED_WATERS = (
    "Select water groups in the Manager (a Chain row or its Water row), "
    "then try again — or uncheck Keep Manager-selected waters."
)
GAFF_NEEDS_LIGAND_TEMPLATE = (
    "GAFF/GAFF2 minimization needs SMILES, an SDF/MOL2, or mmCIF "
    "_chem_comp_bond so AmberTools can assign ligand atom types. Add one, "
    "or set Ligand force field to Protein only."
)
PROTONATION_NEEDS_LIGAND_TEMPLATE = (
    "Ligand protonation needs SMILES, an SDF/MOL2, or mmCIF _chem_comp_bond "
    "so Uni-pKa can pick the protomer at this pH. Add one, or uncheck "
    "Protonate ligand (Uni-pKa)."
)
NO_BOX_LIGAND_FILE = (
    "Choose a ligand file for the docking box, or switch Box from to Loaded structure."
)


@dataclass(frozen=True)
class ProteinPrepareStart:
    """Normalized output path, or a message that blocks Fast Prepare.

    ``warning`` selects a warning box; otherwise the dialog shows information.
    """

    output_path: str = ""
    message: str = ""
    warning: bool = False

    @property
    def is_ready(self) -> bool:
        return not self.message


def _structure_components(text: str, fmt: str):
    """Inventory rows, or ``None`` when the text cannot be read as a structure."""
    from ..protein.structure_components import parse_structure_components

    try:
        return parse_structure_components(text or "", fmt or "pdb")
    except _PARSE_ERRORS:
        return None


def source_has_ligand(text: str, fmt: str) -> bool:
    """True when the structure text contains a ligand component.

    Unreadable text is treated as having no ligand, so Fast Prepare can still
    explain a missing template instead of raising out of the dialog.
    """
    comps = _structure_components(text, fmt)
    if not comps:
        return False
    return any(c.kind == "ligand" for c in comps)


def source_has_cif_ligand_bonds(text: str, fmt: str) -> bool:
    """True when an mmCIF ligand has ``_chem_comp_bond`` records."""
    if (fmt or "").lower() not in _CIF_SOURCE_FMTS:
        return False
    from ..protein.structure_components import cif_has_component_bonds

    comps = _structure_components(text, fmt)
    if not comps:
        return False
    resns = {c.resn for c in comps if c.kind == "ligand"}
    try:
        return bool(cif_has_component_bonds(text or "", resns))
    except _PARSE_ERRORS:
        return False


def normalized_prepare_output_path(path: str, output_format: str) -> str:
    """Apply the ``.pdb`` or ``.cif`` suffix the output format requires."""
    rec = Path(path)
    if output_format == "pdb":
        if rec.suffix.lower() != ".pdb":
            rec = rec.with_suffix(".pdb")
    elif rec.suffix.lower() not in _CIF_OUTPUT_SUFFIXES:
        rec = rec.with_suffix(".cif")
    return str(rec)


def plan_protein_prepare_start(
    *,
    source_text: str,
    source_fmt: str,
    supported_formats: frozenset[str],
    output_path: str,
    output_format: str,
    repair: bool,
    protonate: bool,
    minimize: bool,
    write_smina: bool,
    keep_selected_waters: bool,
    keep_water_keys: tuple,
    include_ligand: bool,
    ligand_ff: str,
    ligand_smiles: str,
    ligand_ref: str,
    protonate_ligand: bool,
    box_from_file: bool,
    box_ligand_path: str,
    ligand_present: Callable[[], bool],
    cif_ligand_bonds: Callable[[], bool],
    empty_source_message: str,
) -> ProteinPrepareStart:
    """Decide whether Fast Prepare can start, and normalize the output path.

    ``ligand_present`` and ``cif_ligand_bonds`` run only when a ligand template
    is required, so a protein-only run does not parse the structure.
    """
    if not (source_text or "").strip():
        return ProteinPrepareStart(message=empty_source_message)
    fmt = source_fmt or "pdb"
    if fmt not in supported_formats:
        return ProteinPrepareStart(message=UNSUPPORTED_FORMAT, warning=True)
    path = (output_path or "").strip()
    if not path:
        return ProteinPrepareStart(message=EMPTY_OUTPUT)
    normalized = normalized_prepare_output_path(path, output_format or "cif")
    if not repair and not protonate and not minimize and not write_smina:
        return ProteinPrepareStart(output_path=normalized, message=NO_STEP)
    if keep_selected_waters and not keep_water_keys:
        return ProteinPrepareStart(output_path=normalized, message=NO_SELECTED_WATERS)
    needs_template = (
        include_ligand and not (ligand_smiles or "").strip() and not (ligand_ref or "").strip()
    )
    if (
        needs_template
        and minimize
        and (ligand_ff or "none") in _GAFF_FORCE_FIELDS
        and ligand_present()
        and not cif_ligand_bonds()
    ):
        return ProteinPrepareStart(output_path=normalized, message=GAFF_NEEDS_LIGAND_TEMPLATE)
    if (
        needs_template
        and protonate
        and protonate_ligand
        and ligand_present()
        and not cif_ligand_bonds()
    ):
        return ProteinPrepareStart(
            output_path=normalized, message=PROTONATION_NEEDS_LIGAND_TEMPLATE
        )
    if write_smina and box_from_file:
        lig_file = (box_ligand_path or "").strip()
        if not lig_file:
            return ProteinPrepareStart(output_path=normalized, message=NO_BOX_LIGAND_FILE)
        if not Path(lig_file).expanduser().is_file():
            return ProteinPrepareStart(
                output_path=normalized,
                message=f"Ligand file not found:\n{lig_file}",
                warning=True,
            )
    return ProteinPrepareStart(output_path=normalized)


def build_protein_prepare_request(
    *,
    input_path: str,
    output_path: str,
    output_format: str,
    ph: float,
    rebuild_missing_loops: bool,
    include_ligand: bool,
    keep_ligand: bool,
    keep_water_keys: tuple,
    keep_bridging_waters: bool,
    repair: bool,
    protonate: bool,
    minimize: bool,
    ligand_smiles: str,
    ligand_ref_path: str,
    protonate_ligand: bool,
    pocket_ligand: bool,
    restraint_k_kcal_per_ang2: float,
    max_minimize_iterations: int,
    protein_ff: str,
    ligand_ff: str,
    solvent: str,
    openmm_platform: str,
    salt_m: float,
    restraint_set: str,
    skip_pocket_loops: bool,
    write_smina: bool,
    box_padding: float,
    box_ligand_keys: tuple,
    box_ligand_path: str,
    box_source_text: str,
    box_source_fmt: str,
    extra: Mapping[str, object],
):
    """Build the worker request from values the dialog already read off the form."""
    from .protein_prepare_runtime import ProteinPrepareRequest

    fields = dict(extra)
    if not repair:
        fields["keep_highest_occupancy_altlocs"] = False
    return ProteinPrepareRequest(
        input_path=input_path,
        output_pdb_path=output_path,
        ph=float(ph),
        rebuild_missing_loops=rebuild_missing_loops,
        include_ligand=include_ligand,
        keep_ligand=keep_ligand,
        keep_water_keys=keep_water_keys,
        keep_bridging_waters=keep_bridging_waters,
        repair=repair,
        protonate=protonate,
        minimize=minimize,
        ligand_smiles=(ligand_smiles or "").strip(),
        ligand_ref_path=(ligand_ref_path or "").strip(),
        protonate_ligand=bool(protonate and protonate_ligand),
        pocket_ligand_protonation=bool(protonate and pocket_ligand),
        restraint_k_kcal_per_ang2=float(restraint_k_kcal_per_ang2),
        max_minimize_iterations=int(max_minimize_iterations),
        protein_ff=protein_ff or "amber14",
        ligand_ff=(ligand_ff or "none") if include_ligand else "none",
        solvent=solvent or "gbn2",
        openmm_platform=openmm_platform or "auto",
        salt_m=float(salt_m),
        restraint_set=restraint_set or "backbone",
        skip_pocket_loops=skip_pocket_loops,
        output_format=output_format or "cif",
        write_smina=write_smina,
        box_padding=float(box_padding),
        box_ligand_keys=box_ligand_keys,
        box_ligand_path=box_ligand_path,
        box_source_text=box_source_text,
        box_source_fmt=box_source_fmt,
        **fields,
    )
