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

"""Gnina dock job policy without Qt."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmanager.docking.gnina_job import (
    GninaJobSettings,
    build_cnn_argv,
    build_flex_argv,
    build_gnina_argv,
    build_minimize_argv,
    effective_out_path,
    flex_out_path,
    ligand_cli_args,
    gnina_output_problem,
    gnina_receptor_problem,
    ligand_mol_from_ensemble,
    ligands_from_row_mols,
    no_table_ligands_message,
    normalize_flexres,
    plan_gnina_run,
    table_row_dock_problem,
)


def test_ligand_cli_args_repeats_flag():
    args, first = ligand_cli_args(["a.pdbqt", "b.pdbqt"])
    assert args == ["--ligand", "a.pdbqt", "--ligand", "b.pdbqt"]
    assert first == "a.pdbqt"
    one, only = ligand_cli_args("lig.pdbqt")
    assert one == ["--ligand", "lig.pdbqt"]
    assert only == "lig.pdbqt"


def test_normalize_flexres_and_flex_out_path():
    assert normalize_flexres(" A:123 ; B:4A ") == "A:123,B:4A"
    assert flex_out_path("C:/tmp/rec_docked.sdf") == str(Path("C:/tmp/rec_docked_flex.pdb"))
    with pytest.raises(ValueError, match="CHAIN:RESNUM"):
        normalize_flexres("")


def test_build_gnina_argv_manual_box():
    settings = GninaJobSettings(
        receptor="rec.pdbqt",
        size_x=22.0,
        center_x=1.5,
        cnn_scoring="rescore",
        pose_sort="CNNscore",
        no_gpu=True,
    )
    argv = build_gnina_argv(settings, ligand="lig.sdf", out="out.sdf")
    assert "--autobox_ligand" not in argv
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    assert argv[argv.index("--cnn_scoring") + 1] == "rescore"
    assert argv[argv.index("--pose_sort_order") + 1] == "CNNscore"
    assert "--no_gpu" in argv
    assert "--energy_range" not in argv


def test_build_cnn_argv_empirical_when_none():
    settings = GninaJobSettings(cnn_scoring="none", emp_scoring="vinardo")
    argv = build_cnn_argv(settings)
    assert argv[argv.index("--cnn_scoring") + 1] == "none"
    assert argv[argv.index("--scoring") + 1] == "vinardo"
    assert "--pose_sort_order" not in argv


def test_build_flex_argv_named_residues():
    settings = GninaJobSettings(flex_mode="res", flexres="A:123,A:145")
    argv = build_flex_argv(settings, dock_ligand="lig.sdf", out_path="out.sdf")
    assert argv[argv.index("--flexres") + 1] == "A:123,A:145"
    assert argv[argv.index("--out_flex") + 1] == flex_out_path("out.sdf")


def test_build_minimize_argv_omits_search_box():
    settings = GninaJobSettings(receptor="rec.pdbqt", no_gpu=True)
    argv = build_minimize_argv(settings, "pose.pdbqt", "min.pdbqt")
    assert "--minimize" in argv
    assert "--num_modes" not in argv
    assert "--exhaustiveness" not in argv
    assert argv[argv.index("--ligand") + 1] == "pose.pdbqt"


def test_effective_out_path_sdf_sibling():
    assert effective_out_path("out.pdbqt", save_sdf=True).endswith("out.sdf")
    assert effective_out_path("out.pdbqt", save_sdf=False).endswith("out.pdbqt")


def test_ligand_mol_from_ensemble_keeps_one_start():
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMultipleConfs(mol, 2, randomSeed=1)
    ligand = ligand_mol_from_ensemble(mol, 9)
    assert ligand is not None
    assert ligand.GetProp("_Name") == "9"
    assert ligand.GetProp("Parent OID") == "9"
    assert ligand.GetNumConformers() == 1


def test_table_row_dock_problem_and_ligand_list():
    from rdkit import Chem
    from rdkit.Chem import AllChem

    assert table_row_dock_problem(has_window=False, selected_rows=1, column="Structure")
    assert table_row_dock_problem(has_window=True, selected_rows=0, column="Structure")
    assert table_row_dock_problem(has_window=True, selected_rows=1, column="")
    assert table_row_dock_problem(has_window=True, selected_rows=2, column="Structure") is None
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMolecule(mol, randomSeed=1)
    ligands = ligands_from_row_mols([(3, mol), (4, None)])
    assert len(ligands) == 1
    assert ligands[0].GetProp("_Name") == "3"
    assert "chosen column" in no_table_ligands_message("")


def test_plan_gnina_run_checks_files_then_crystal(tmp_path: Path):
    missing = tmp_path / "missing.pdb"
    present = tmp_path / "rec.pdb"
    present.write_text("ATOM\n", encoding="utf-8")
    assert gnina_receptor_problem("", present) == "Choose a receptor PDB or PDBQT file."
    assert "not found" in (gnina_receptor_problem("rec.pdb", missing) or "")
    assert gnina_receptor_problem("rec.pdb", present) is None
    assert gnina_output_problem("") == "Set an output path."
    assert gnina_output_problem("out.sdf") is None
    empty = plan_gnina_run(ligand_paths=[], crystal_ligand="", same_crystal_ligand=False)
    assert empty.message == "Choose a ligand file (PDBQT or SDF)."
    crystal = plan_gnina_run(ligand_paths=[], crystal_ligand="xtal.sdf", same_crystal_ligand=False)
    assert crystal.ligand_paths_are_crystal
    assert crystal.stamp_crystal_on_poses
    other = plan_gnina_run(
        ligand_paths=[tmp_path / "lig.sdf"],
        crystal_ligand="xtal.sdf",
        same_crystal_ligand=False,
    )
    assert other.extra_validation
    assert other.message is None
