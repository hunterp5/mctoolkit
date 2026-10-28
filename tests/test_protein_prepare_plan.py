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

"""Fast Prepare start checks, without a dialog."""

from __future__ import annotations

from molmanager.workers.protein_prepare_plan import (
    EMPTY_OUTPUT,
    GAFF_NEEDS_LIGAND_TEMPLATE,
    NO_BOX_LIGAND_FILE,
    NO_SELECTED_WATERS,
    NO_STEP,
    PROTONATION_NEEDS_LIGAND_TEMPLATE,
    UNSUPPORTED_FORMAT,
    build_protein_prepare_request,
    normalized_prepare_output_path,
    plan_protein_prepare_start,
    source_has_ligand,
)

_FMTS = frozenset({"pdb", "pqr", "cif"})
_ALA = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
END
"""
_HOLO = _ALA + "HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O\n"


def _start(**overrides):
    fields = {
        "source_text": _ALA,
        "source_fmt": "pdb",
        "supported_formats": _FMTS,
        "output_path": "out.cif",
        "output_format": "cif",
        "repair": True,
        "protonate": False,
        "minimize": False,
        "write_smina": False,
        "keep_selected_waters": False,
        "keep_water_keys": (),
        "include_ligand": False,
        "ligand_ff": "none",
        "ligand_smiles": "",
        "ligand_ref": "",
        "protonate_ligand": False,
        "box_from_file": False,
        "box_ligand_path": "",
        "ligand_present": lambda: False,
        "cif_ligand_bonds": lambda: False,
        "empty_source_message": "Choose a Manager structure or a PDB/mmCIF file.",
    }
    fields.update(overrides)
    return plan_protein_prepare_start(**fields)


def test_empty_source_blocks_before_parsing_a_ligand():
    called = {"n": 0}

    def _present() -> bool:
        called["n"] += 1
        return True

    start = _start(source_text="  ", ligand_present=_present)
    assert start.message == "Choose a Manager structure or a PDB/mmCIF file."
    assert start.output_path == ""
    assert called["n"] == 0


def test_unsupported_format_is_a_warning():
    start = _start(source_fmt="mol2")
    assert start.warning
    assert start.message == UNSUPPORTED_FORMAT


def test_missing_output_and_missing_step():
    assert _start(output_path="").message == EMPTY_OUTPUT
    start = _start(repair=False, output_path="receptor")
    assert start.message == NO_STEP
    assert start.output_path == "receptor.cif"


def test_output_suffix_follows_format():
    assert normalized_prepare_output_path("a.pdb", "cif") == "a.cif"
    assert normalized_prepare_output_path("a.cif", "pdb") == "a.pdb"
    assert normalized_prepare_output_path("a.mmcif", "cif") == "a.mmcif"


def test_selected_waters_must_name_a_residue():
    start = _start(keep_selected_waters=True, keep_water_keys=())
    assert start.message == NO_SELECTED_WATERS


def test_gaff_and_protonation_need_a_ligand_template_only_when_a_ligand_is_present():
    start = _start(
        include_ligand=True,
        minimize=True,
        ligand_ff="gaff2",
        ligand_present=lambda: True,
    )
    assert start.message == GAFF_NEEDS_LIGAND_TEMPLATE
    skipped = _start(
        include_ligand=True,
        minimize=True,
        ligand_ff="gaff2",
        ligand_present=lambda: False,
    )
    assert skipped.message == ""
    protonation = _start(
        include_ligand=True,
        protonate=True,
        protonate_ligand=True,
        ligand_present=lambda: True,
        cif_ligand_bonds=lambda: False,
    )
    assert protonation.message == PROTONATION_NEEDS_LIGAND_TEMPLATE
    covered = _start(
        include_ligand=True,
        protonate=True,
        protonate_ligand=True,
        ligand_present=lambda: True,
        cif_ligand_bonds=lambda: True,
    )
    assert covered.message == ""


def test_box_ligand_file_must_be_chosen_and_exist(tmp_path):
    missing = _start(write_smina=True, box_from_file=True, box_ligand_path="")
    assert missing.message == NO_BOX_LIGAND_FILE
    absent = _start(
        write_smina=True,
        box_from_file=True,
        box_ligand_path=str(tmp_path / "missing.sdf"),
    )
    assert absent.warning
    assert absent.message.startswith("Ligand file not found:")
    present = tmp_path / "lig.sdf"
    present.write_text("lig", encoding="utf-8")
    ok = _start(write_smina=True, box_from_file=True, box_ligand_path=str(present))
    assert ok.message == ""


def test_protein_only_request_drops_the_ligand_force_field():
    req = build_protein_prepare_request(
        input_path="in.pdb",
        output_path="out.cif",
        output_format="cif",
        ph=7.4,
        rebuild_missing_loops=True,
        include_ligand=False,
        keep_ligand=True,
        keep_water_keys=(),
        keep_bridging_waters=False,
        repair=False,
        protonate=True,
        minimize=False,
        ligand_smiles="",
        ligand_ref_path="",
        protonate_ligand=True,
        pocket_ligand=True,
        restraint_k_kcal_per_ang2=1.0,
        max_minimize_iterations=10,
        protein_ff="amber14",
        ligand_ff="gaff",
        solvent="gbn2",
        openmm_platform="auto",
        salt_m=0.15,
        restraint_set="backbone",
        skip_pocket_loops=True,
        write_smina=False,
        box_padding=4.0,
        box_ligand_keys=(),
        box_ligand_path="",
        box_source_text="",
        box_source_fmt="",
        extra={"keep_highest_occupancy_altlocs": True, "keep_chain_ids": ()},
    )
    assert req.ligand_ff == "none"
    assert req.protonate_ligand is True
    assert req.pocket_ligand_protonation is True
    assert req.keep_highest_occupancy_altlocs is False


def test_source_has_ligand_reads_a_hetatm():
    assert source_has_ligand(_ALA, "pdb") is False
    assert source_has_ligand(_HOLO, "pdb") is True
