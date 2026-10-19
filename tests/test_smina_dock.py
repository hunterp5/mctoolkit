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

"""Gnina CLI dialog: autobox vs manual search box."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.ui.gnina_dock import GninaDockDialog

_CARBONYL_PDBQT = (
    "REMARK SMILES C=O\n"
    "REMARK SMILES IDX 1 1 2 2\n"
    "ROOT\n"
    "ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
    "ATOM      2  O   UNL     1       1.210   0.000   0.000  1.00  0.00     0.000 OA\n"
    "ENDROOT\n"
    "TORSDOF 0\n"
)


def _filled_dialog(qapp):  # noqa: ARG001
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText("rec.pdbqt")
    dlg.edit_ligand.setText("lig.pdbqt")
    dlg.edit_out.setText("out.pdbqt")
    return dlg


def test_smina_argv_manual_box(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(False)
    dlg.spin_cx.setValue(1.5)
    dlg.spin_sx.setValue(22.0)
    argv = dlg._build_argv()
    assert "--autobox_ligand" not in argv
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    assert argv[argv.index("--cnn_scoring") + 1] == "rescore"
    assert argv[argv.index("--pose_sort_order") + 1] == "CNNscore"
    assert "--energy_range" not in argv
    dlg.close()


def test_gnina_argv_gpu_off_adds_no_gpu(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.gpu_cb.setChecked(False)
    argv = dlg._build_argv()
    assert "--no_gpu" in argv
    dlg.close()


def test_gnina_argv_empirical_when_cnn_none(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.combo_cnn_scoring.setCurrentIndex(dlg.combo_cnn_scoring.findData("none"))
    dlg.combo_emp_scoring.setCurrentIndex(dlg.combo_emp_scoring.findData("vinardo"))
    argv = dlg._build_argv()
    assert argv[argv.index("--cnn_scoring") + 1] == "none"
    assert argv[argv.index("--scoring") + 1] == "vinardo"
    assert "--pose_sort_order" not in argv
    dlg.close()


def test_smina_autobox_uses_docking_ligand(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(True)
    dlg.spin_autobox_add.setValue(5.5)
    assert not dlg.spin_cx.isEnabled()
    argv = dlg._build_argv()
    assert "--center_x" not in argv
    assert argv[argv.index("--autobox_ligand") + 1] == "lig.pdbqt"
    assert argv[argv.index("--autobox_add") + 1] == "5.50"
    dlg.close()


def test_smina_autobox_optional_box_ligand(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.autobox_cb.setChecked(True)
    assert dlg.edit_autobox_ligand.isEnabled()
    assert dlg.btn_autobox_ligand.isEnabled()
    dlg.edit_autobox_ligand.setText("crystal.pdb")
    argv = dlg._build_argv()
    assert argv[argv.index("--autobox_ligand") + 1] == "crystal.pdb"
    assert argv[argv.index("--ligand") + 1] == "lig.pdbqt"
    dlg.edit_autobox_ligand.setText("crystal.pdbqt")
    argv = dlg._build_argv()
    assert argv[argv.index("--autobox_ligand") + 1] == "crystal.pdbqt"
    dlg.autobox_cb.setChecked(False)
    assert not dlg.edit_autobox_ligand.isEnabled()
    assert not dlg.btn_autobox_ligand.isEnabled()
    dlg.close()


def test_gnina_flex_off_omits_flex_flags(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    assert dlg.combo_flex_mode.currentData() == "off"
    argv = dlg._build_argv()
    assert "--flexres" not in argv
    assert "--flexdist" not in argv
    assert "--flexdist_ligand" not in argv
    assert "--out_flex" not in argv
    dlg.close()


def test_gnina_flex_distance_argv(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.combo_flex_mode.setCurrentIndex(dlg.combo_flex_mode.findData("dist"))
    dlg.edit_flexdist_ligand.setText("crystal.pdb")
    dlg.spin_flexdist.setValue(3.5)
    dlg.spin_flex_max.setValue(8)
    argv = dlg._build_argv()
    assert argv[argv.index("--flexdist_ligand") + 1] == "crystal.pdb"
    assert argv[argv.index("--flexdist") + 1] == "3.50"
    assert argv[argv.index("--flex_max") + 1] == "8"
    assert argv[argv.index("--out_flex") + 1] == "out_flex.pdb"
    assert "--full_flex_output" not in argv
    dlg.close()


def test_gnina_flex_distance_falls_back_to_autobox_ligand(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.combo_flex_mode.setCurrentIndex(dlg.combo_flex_mode.findData("dist"))
    dlg.edit_autobox_ligand.setText("box_lig.pdb")
    argv = dlg._build_argv()
    assert argv[argv.index("--flexdist_ligand") + 1] == "box_lig.pdb"
    dlg.close()


def test_gnina_flex_named_residues_argv(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.combo_flex_mode.setCurrentIndex(dlg.combo_flex_mode.findData("res"))
    dlg.edit_flexres.setText("A:123, A:145")
    dlg.chk_full_flex.setChecked(True)
    argv = dlg._build_argv()
    assert argv[argv.index("--flexres") + 1] == "A:123,A:145"
    assert "--flex_max" not in argv
    assert "--full_flex_output" in argv
    assert argv[argv.index("--out_flex") + 1] == "out_flex.pdb"
    dlg.close()


def test_gnina_flex_named_residues_rejects_bad_token(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg.combo_flex_mode.setCurrentIndex(dlg.combo_flex_mode.findData("res"))
    dlg.edit_flexres.setText("HIS123")
    with pytest.raises(ValueError, match="CHAIN:RESNUM"):
        dlg._build_argv()
    dlg.close()


def test_normalize_flexres_and_flex_out_path():
    from molmanager.ui.gnina_dock import flex_out_path, normalize_flexres

    assert normalize_flexres(" A:123 ; B:4A ") == "A:123,B:4A"
    assert flex_out_path("C:/tmp/rec_docked.sdf") == str(Path("C:/tmp/rec_docked_flex.pdb"))
    with pytest.raises(ValueError, match="CHAIN:RESNUM"):
        normalize_flexres("")


def test_smina_dialog_defaults_to_resolved_executable(qapp):  # noqa: ARG001
    from molmanager.platform_support.bundled_paths import default_external_executable

    dlg = GninaDockDialog(None)
    assert dlg.edit_exe.text() == default_external_executable("gnina")
    assert not hasattr(dlg, "progress")
    assert dlg.save_sdf_cb.isChecked()
    assert not dlg.minimize_poses_cb.isChecked()
    assert dlg.edit_out.placeholderText() == "out.sdf"
    assert dlg.combo_ligand_source.currentData() == "file"
    assert dlg.combo_confs.findText("Structure") >= 0
    assert dlg.combo_flex_mode.currentData() == "off"
    dlg.close()


def test_smina_argv_uses_sdf_out_when_save_sdf(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    argv = dlg._build_argv()
    assert argv[argv.index("--out") + 1] == "out.sdf"
    dlg.save_sdf_cb.setChecked(False)
    argv = dlg._build_argv()
    assert argv[argv.index("--out") + 1] == "out.pdbqt"
    dlg.close()


def test_smina_writes_sidecar_sdf_on_success(qapp, tmp_path):  # noqa: ARG001
    pdbqt = tmp_path / "out.pdbqt"
    pdbqt.write_text("MODEL 1\n" + _CARBONYL_PDBQT + "ENDMDL\n", encoding="utf-8")
    dlg = GninaDockDialog(None)
    dlg.save_sdf_cb.setChecked(False)
    dlg.edit_out.setText(str(pdbqt))
    dlg.save_sdf_cb.setChecked(True)
    dlg._worker.write_final_sdf(str(pdbqt))
    sdf = tmp_path / "out.sdf"
    assert sdf.is_file()
    dlg.close()


def test_smina_prepares_ligand_batch_from_concatenated_pdbqt(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem

    sample = tmp_path / "ligands.pdbqt"
    sample.write_text(_CARBONYL_PDBQT + _CARBONYL_PDBQT, encoding="utf-8")
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText("rec.pdbqt")
    dlg.edit_ligand.setText(str(sample))
    out = str(tmp_path / "out.sdf")
    dlg.edit_out.setText(out)
    paths = dlg._prepare_smina_ligands(str(sample))
    assert len(paths) == 1
    assert paths[0].suffix.lower() == ".sdf"
    mols = [m for m in Chem.SDMolSupplier(str(paths[0]), removeHs=False) if m is not None]
    assert len(mols) > 1
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mols[0].GetBonds()
    )
    argv = dlg._build_argv(ligand=str(paths[0]), out=out)
    assert argv.count("--ligand") == 1
    assert argv[argv.index("--ligand") + 1] == str(paths[0])
    assert argv[argv.index("--out") + 1] == out
    dlg._clear_batch()
    dlg.close()


def test_smina_sdf_ligand_skips_pdbqt_split(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    from rdkit import Chem

    sample = Path(__file__).resolve().parents[1] / "samples" / "test_ligand.sdf"
    dlg = _filled_dialog(qapp)
    dlg.edit_ligand.setText(str(sample))
    n = dlg._prepare_ligand_batch(str(sample))
    assert n == 1
    assert dlg._batch_ligands == []
    argv = dlg._build_argv(ligand=str(sample), out=str(tmp_path / "out.sdf"))
    assert argv[argv.index("--ligand") + 1] == str(sample)
    tmpl = dlg._ligand_template_mol()
    assert tmpl is not None
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in tmpl.GetBonds()
    )
    dlg.close()


def test_smina_launch_argv_uses_config_for_multi_ligand(qapp, tmp_path):  # noqa: ARG001
    from pathlib import Path

    dlg = _filled_dialog(qapp)
    argv = dlg._build_argv(ligand=["a.pdbqt", "b.pdbqt"], out=str(tmp_path / "out.pdbqt"))
    launch = dlg._launch_argv(argv)
    assert launch[:1] == ["--config"]
    cfg = Path(launch[1])
    assert cfg.is_file()
    assert cfg.read_text(encoding="utf-8").count("ligand = ") == 2
    dlg._clear_batch()
    dlg.close()


def test_smina_ligand_cli_args_repeats_flag():
    from molmanager.ui.smina_dock import _ligand_cli_args

    args, first = _ligand_cli_args(["a.pdbqt", "b.pdbqt"])
    assert args == ["--ligand", "a.pdbqt", "--ligand", "b.pdbqt"]
    assert first == "a.pdbqt"
    one, only = _ligand_cli_args("lig.pdbqt")
    assert one == ["--ligand", "lig.pdbqt"]
    assert only == "lig.pdbqt"


def test_write_smina_config_repeats_ligand(tmp_path):
    from molmanager.ui.smina_dock import _write_smina_config

    dest = tmp_path / "smina.conf"
    _write_smina_config(
        [
            "--receptor",
            "rec.pdbqt",
            "--ligand",
            "a.pdbqt",
            "--ligand",
            "b.pdbqt",
            "--out",
            "out.pdbqt",
            "--minimize",
            "--center_x",
            "-1.5",
        ],
        dest,
    )
    text = dest.read_text(encoding="utf-8")
    assert text.count("ligand = ") == 2
    assert "minimize = true" in text
    assert "center_x = -1.5" in text


def test_smina_skips_sidecar_sdf_when_unchecked(qapp, tmp_path):  # noqa: ARG001
    from PyQt5.QtCore import QProcess

    pdbqt = tmp_path / "out.pdbqt"
    pdbqt.write_text("MODEL 1\n" + _CARBONYL_PDBQT + "ENDMDL\n", encoding="utf-8")
    dlg = GninaDockDialog(None)
    dlg.save_sdf_cb.setChecked(False)
    dlg.edit_out.setText(str(pdbqt))
    dlg._worker.on_proc_finished(0, QProcess.NormalExit)
    assert not (tmp_path / "out.sdf").exists()
    dlg.close()


def test_smina_minimize_argv_omits_search_box(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    argv = dlg._build_minimize_argv("pose.pdbqt", "min.pdbqt")
    assert "--minimize" in argv
    assert "--num_modes" not in argv
    assert "--exhaustiveness" not in argv
    assert argv[argv.index("--ligand") + 1] == "pose.pdbqt"
    assert "--minimize" not in dlg._build_argv()
    multi = dlg._build_minimize_argv(["a.pdbqt", "b.pdbqt"], "min.pdbqt")
    assert multi.count("--ligand") == 2
    assert multi[multi.index("--ligand") + 1] == "a.pdbqt"
    dlg.close()


def test_smina_present_dock_results_opens_table(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    sdf = tmp_path / "docked.sdf"
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("_Name", "lig_1")
    mol.SetProp("minimizedAffinity", "-9.100")
    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    opened: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None, **_kwargs):
            opened.append((list(mols), title, receptor_path))
            return None

    dlg = GninaDockDialog(None)
    dlg._main_window = _Host()
    dlg._stdout_buf = (
        "mode |   affinity | dist from best mode\n"
        "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
        "-----+------------+----------+----------\n"
        "   1         -9.10      0.000      0.000\n"
    )
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.present_dock_results(str(sdf))
    assert opened
    mols, title, receptor_path = opened[0]
    assert "docked.sdf" in title
    assert receptor_path == str(rec)
    assert mols[0].GetProp("minimizedAffinity") == "-9.100"
    assert mols[0].GetProp("mode") == "1"
    assert mols[0].GetProp("rmsd_lb") == "0.000"
    assert mols[0].HasProp("E_MMFF")
    assert mols[0].HasProp("E_UFF")
    dlg.close()


def test_apply_prepare_result_fills_numeric_box(qapp, tmp_path):  # noqa: ARG001
    from molmanager.docking.search_box import DockingBox
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    rec = tmp_path / "rec_receptor.pdbqt"
    lig = tmp_path / "rec_ligand.sdf"
    lig_pdb = tmp_path / "rec_ligand.pdb"
    rec.write_text("ATOM\n", encoding="utf-8")
    lig.write_text("lig\n", encoding="utf-8")
    lig_pdb.write_text("HETATM\n", encoding="utf-8")
    box = DockingBox(1.5, -2.0, 3.25, 22.0, 18.0, 20.0, padding=4.0)
    result = ProteinPrepareResult(
        output_path=str(tmp_path / "rec.cif"),
        receptor_pdbqt=str(rec),
        ligand_sdf=str(lig),
        ligand_pdb=str(lig_pdb),
        box_path=str(tmp_path / "rec_box.txt"),
        box=box,
    )
    dlg = GninaDockDialog(None)
    dlg.edit_ligand.setText("stale.sdf")
    dlg.apply_prepare_result(result)
    assert dlg.edit_receptor.text() == str(rec)
    assert dlg.combo_ligand_source.currentData() == "file"
    assert dlg.edit_ligand.text() == ""
    assert dlg._crystal_ligand_path == str(lig)
    assert dlg._prepare_receptor_path == str(rec)
    assert dlg.edit_autobox_ligand.text() == str(lig_pdb)
    assert dlg.edit_flexdist_ligand.text() == str(lig_pdb)
    assert dlg.autobox_cb.isChecked() is False
    assert dlg.spin_cx.value() == 1.5
    assert dlg.spin_sx.value() == 22.0
    assert dlg.edit_out.text().endswith("rec_receptor_docked.sdf")
    dlg.edit_ligand.setText("lig.sdf")
    argv = dlg._build_argv()
    assert argv[argv.index("--center_x") + 1] == "1.500"
    assert argv[argv.index("--size_x") + 1] == "22.00"
    dlg.close()


def test_apply_prepare_result_loads_output_pdbqt_as_receptor(qapp, tmp_path):  # noqa: ARG001
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    rec = tmp_path / "holo_smina.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    result = ProteinPrepareResult(
        output_path=str(rec),
        receptor_pdbqt=str(rec),
    )
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText("stale.pdb")
    dlg.apply_prepare_result(result)
    assert dlg.edit_receptor.text() == str(rec)
    assert dlg.edit_receptor.text().lower().endswith(".pdbqt")
    dlg.close()


def test_apply_prepare_result_skips_missing_output_pdbqt(qapp, tmp_path):  # noqa: ARG001
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    missing = tmp_path / "holo_smina.pdbqt"
    result = ProteinPrepareResult(output_path=str(missing))
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText("stale.pdb")
    dlg.apply_prepare_result(result)
    assert dlg.edit_receptor.text() == "stale.pdb"
    dlg.close()


def test_ensemble_column_headers_lists_confs_and_sidecar(qapp):  # noqa: ARG001
    from molmanager.ui.gnina_dock import ensemble_column_headers

    class _App:
        headers = [
            "ID_HIDDEN",
            "Structure",
            "SMILES",
            "confs",
            "confs_2",
            "confidence",
            "superpose",
            "poses",
            "extra_ens",
        ]
        _confs_blocks_sidecar = {(1, "extra_ens"): "x"}

    names = ensemble_column_headers(_App())
    assert names == ["confs", "confs_2", "superpose", "poses", "extra_ens"]


def test_ligand_mol_from_ensemble_keeps_one_start(qapp):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from molmanager.ui.gnina_dock import ligand_mol_from_ensemble

    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMultipleConfs(mol, 2, randomSeed=1)
    ligand = ligand_mol_from_ensemble(mol, 9)
    assert ligand is not None
    assert ligand.GetProp("_Name") == "9"
    assert ligand.GetProp("Parent OID") == "9"
    assert ligand.GetNumConformers() == 1


def test_gnina_selected_rows_writes_confs_sdf(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import AllChem

    from molmanager.conformers.conformer_column_codec import pack_confs_cell
    from molmanager.ui.gnina_dock import GninaDockDialog

    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    AllChem.EmbedMultipleConfs(mol, 2, randomSeed=1)
    cell = pack_confs_cell({"n_packed": int(mol.GetNumConformers())}, mol)

    class _Model:
        def row_oid(self, _row):
            return 7

        def backing_value_for_row_header(self, _row, header):
            return cell if header == "confs" else ""

    class _App:
        headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
        _confs_blocks_sidecar = {}
        _table_model = _Model()

        def _selected_logical_rows(self):
            return [0]

    dlg = GninaDockDialog(None)
    dlg._main_window = _App()
    dlg.combo_ligand_source.setCurrentIndex(dlg.combo_ligand_source.findData("rows"))
    dlg._refresh_confs_columns()
    dlg.combo_confs.setCurrentText("confs")
    paths = dlg._prepare_table_row_ligands()
    assert len(paths) == 1
    assert paths[0].suffix.lower() == ".sdf"
    mols = [m for m in Chem.SDMolSupplier(str(paths[0]), removeHs=False) if m is not None]
    assert len(mols) == 1
    assert mols[0].GetProp("_Name") == "7"
    dlg.close()


def test_gnina_selected_rows_requires_selection(qapp):  # noqa: ARG001
    class _App:
        headers = ["ID_HIDDEN", "Structure", "SMILES", "confs"]
        _confs_blocks_sidecar = {}
        _table_model = None

        def _selected_logical_rows(self):
            return []

    dlg = GninaDockDialog(None)
    dlg._main_window = _App()
    dlg.combo_ligand_source.setCurrentIndex(dlg.combo_ligand_source.findData("rows"))
    dlg.combo_confs.setCurrentText("confs")
    try:
        dlg._prepare_table_row_ligands()
        raise AssertionError("expected missing selection")
    except ValueError as exc:
        assert "Select one or more table rows" in str(exc)
    dlg.close()


def test_build_argv_uses_apo_receptor_override(qapp):  # noqa: ARG001
    dlg = _filled_dialog(qapp)
    dlg._apo_receptor_path = "apo_rec.pdbqt"
    argv = dlg._build_argv()
    assert argv[argv.index("--receptor") + 1] == "apo_rec.pdbqt"
    dlg.close()


def test_setup_crystal_validation_strips_holo_pdb(qapp, tmp_path):  # noqa: ARG001
    rec = tmp_path / "holo.pdb"
    rec.write_text(
        "ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N\n"
        "ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C\n"
        "HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O\n"
        "HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C\n"
        "HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O\n"
        "END\n",
        encoding="utf-8",
    )
    outdir = tmp_path / "out"
    outdir.mkdir()
    dlg = GninaDockDialog(None)
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.setup_crystal_validation(str(rec), durable_dir=outdir)
    assert dlg._apo_receptor_path
    apo_text = Path(dlg._apo_receptor_path).read_text(encoding="utf-8")
    assert "AXI" not in apo_text
    assert "ALA" in apo_text
    assert dlg._validation_ligand_path
    lig_text = Path(dlg._validation_ligand_path).read_text(encoding="utf-8")
    assert "AXI" in lig_text or "crystal" in Path(dlg._validation_ligand_path).name.lower()
    assert dlg._crystal_ref_mol is not None
    dlg.close()


def test_internal_validation_checkbox_defaults_on(qapp):  # noqa: ARG001
    dlg = GninaDockDialog(None)
    assert dlg.validate_crystal_cb.isChecked() is True
    dlg.close()


def test_setup_crystal_validation_off_strips_but_skips_redock(qapp, tmp_path):  # noqa: ARG001
    rec = tmp_path / "holo.pdb"
    rec.write_text(
        "ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N\n"
        "ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C\n"
        "HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O\n"
        "HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C\n"
        "END\n",
        encoding="utf-8",
    )
    outdir = tmp_path / "out"
    outdir.mkdir()
    dlg = GninaDockDialog(None)
    dlg.validate_crystal_cb.setChecked(False)
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.setup_crystal_validation(str(rec), durable_dir=outdir, validate=False)
    assert dlg._apo_receptor_path
    assert "AXI" not in Path(dlg._apo_receptor_path).read_text(encoding="utf-8")
    assert dlg._validation_ligand_path == ""
    assert dlg._crystal_ref_mol is None
    dlg.close()


def test_present_dock_results_title_includes_crystal_rmsd(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    sdf = tmp_path / "docked.sdf"
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    opened: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None, **_kwargs):
            opened.append(title)
            return None

    dlg = GninaDockDialog(None)
    dlg._main_window = _Host()
    dlg._crystal_rmsd = 1.25
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.present_dock_results(str(sdf))
    assert opened
    assert "crystal RMSD 1.250 Å" in opened[0]
    dlg.close()


def test_present_dock_results_stamps_crystal_ref(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    from molmanager.docking.redock_validation import CRYSTAL_REF_PROP

    sdf = tmp_path / "docked.sdf"
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    captured: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None, **_kwargs):
            captured.append(list(mols))
            return None

    dlg = GninaDockDialog(None)
    dlg._main_window = _Host()
    crystal = Chem.MolFromSmiles("CCO")
    assert crystal is not None
    crystal.SetProp("_Name", "AXI")
    dlg._crystal_ref_mol = crystal
    dlg._validation_ligand_path = str(tmp_path / "holo_smina_ligand.sdf")
    dlg._stamp_crystal_on_poses = True
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.present_dock_results(str(sdf))
    assert captured
    assert captured[0][0].GetProp(CRYSTAL_REF_PROP) == "AXI"
    dlg.close()


def test_present_dock_results_skips_crystal_ref_on_user_ligands(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    from molmanager.docking.redock_validation import CRYSTAL_REF_PROP

    sdf = tmp_path / "docked.sdf"
    mol = Chem.MolFromSmiles("CCN")
    assert mol is not None
    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    captured: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None, **_kwargs):
            captured.append(list(mols))
            return None

    dlg = GninaDockDialog(None)
    dlg._main_window = _Host()
    crystal = Chem.MolFromSmiles("CCO")
    assert crystal is not None
    crystal.SetProp("_Name", "AXI")
    dlg._crystal_ref_mol = crystal
    dlg._validation_ligand_path = str(tmp_path / "holo_smina_ligand.sdf")
    dlg._stamp_crystal_on_poses = False
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.present_dock_results(str(sdf))
    assert captured
    assert not captured[0][0].HasProp(CRYSTAL_REF_PROP)
    dlg.close()


def test_present_dock_results_keeps_crystal_ref_on_validation_entry_only(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Chem import SDWriter

    from molmanager.docking.redock_validation import CRYSTAL_REF_PROP, stamp_crystal_ref

    user_sdf = tmp_path / "docked.sdf"
    user = Chem.MolFromSmiles("CCN")
    assert user is not None
    writer = SDWriter(str(user_sdf))
    writer.write(user)
    writer.close()
    crystal_pose = Chem.MolFromSmiles("CCO")
    assert crystal_pose is not None
    stamp_crystal_ref([crystal_pose], "AXI A 2000")
    captured: list = []

    class _Host:
        def open_dock_results_window(self, mols, *, title="", receptor_path=None, **_kwargs):
            captured.append(list(mols))
            return None

    dlg = GninaDockDialog(None)
    dlg._main_window = _Host()
    dlg._crystal_ref_mol = Chem.MolFromSmiles("CCO")
    dlg._stamp_crystal_on_poses = False
    dlg._validation_pose_mols = [crystal_pose]
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    dlg.edit_receptor.setText(str(rec))
    dlg._worker.present_dock_results(str(user_sdf))
    assert captured
    mols = captured[0]
    assert len(mols) == 2
    assert mols[0].GetProp(CRYSTAL_REF_PROP) == "AXI A 2000"
    assert not mols[1].HasProp(CRYSTAL_REF_PROP)
    dlg.close()


def test_stop_clears_ui_when_gnina_already_exited(qapp):  # noqa: ARG001
    dlg = GninaDockDialog(None)
    dlg._set_running_ui(True)
    assert dlg.btn_stop.isEnabled()
    dlg._worker.stop()
    assert dlg.btn_run.isEnabled()
    assert not dlg.btn_stop.isEnabled()
    assert not dlg._batch_cancelled
    dlg.close()


def test_gnina_log_goes_to_protein_viewer(qapp):  # noqa: ARG001
    from types import SimpleNamespace

    from PyQt5.QtWidgets import QGroupBox

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    viewer = ProteinViewerDialog()
    host = SimpleNamespace(_live_protein_viewer=lambda: viewer)
    dlg = GninaDockDialog(None)
    dlg._main_window = host
    assert "Log" not in [g.title() for g in dlg.findChildren(QGroupBox)]
    dlg.log.append("[12:00:00][system] Launch: gnina --receptor rec.pdbqt")
    text = viewer.log.toPlainText()
    assert "Launch: gnina --receptor rec.pdbqt" in text
    assert "[system]" not in text
    dlg.close()
    viewer.close()


def test_gnina_session_state_roundtrip(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.gnina_dock import gnina_session_worth_saving

    empty = GninaDockDialog(None)
    assert gnina_session_worth_saving(empty.gnina_session_state()) is False
    empty.close()

    src = GninaDockDialog(None)
    src.edit_receptor.setText("rec.pdbqt")
    src.combo_ligand_source.setCurrentIndex(src.combo_ligand_source.findData("rows"))
    src.combo_confs.addItem("poses")
    src.combo_confs.setCurrentText("poses")
    src.save_sdf_cb.setChecked(False)
    src.edit_out.setText("poses.pdbqt")
    src.autobox_cb.setChecked(True)
    src.edit_autobox_ligand.setText("box.pdb")
    src.spin_autobox_add.setValue(6.0)
    src.combo_flex_mode.setCurrentIndex(src.combo_flex_mode.findData("res"))
    src.edit_flexres.setText("A:123")
    src.chk_full_flex.setChecked(True)
    src.spin_exhaust.setValue(16)
    src.minimize_poses_cb.setChecked(True)
    src.validate_crystal_cb.setChecked(False)
    src.gpu_cb.setChecked(False)
    src.combo_cnn_model.setCurrentIndex(src.combo_cnn_model.findData("fast"))
    src._crystal_ligand_path = "xtal.sdf"
    state = src.gnina_session_state()
    assert gnina_session_worth_saving(state) is True
    dst = GninaDockDialog(None)
    dst.apply_gnina_session(state)
    again = dst.gnina_session_state()
    for key in (
        "receptor",
        "ligand_source",
        "confs_column",
        "output",
        "save_sdf",
        "autobox",
        "autobox_ligand",
        "autobox_add",
        "flex_mode",
        "flexres",
        "full_flex",
        "exhaustiveness",
        "minimize_poses",
        "validate_crystal",
        "gpu",
        "cnn_model",
        "crystal_ligand",
    ):
        assert again[key] == state[key], key
    src.close()
    dst.close()


def test_gnina_start_hides_dialog(qapp, monkeypatch):  # noqa: ARG001
    dlg = GninaDockDialog(None)
    dlg.show()
    assert dlg.isVisible()
    dlg._resolved_exe = "gnina"
    monkeypatch.setattr("molmanager.workers.gnina_dock_worker.gnina_uses_wsl", lambda: False)
    monkeypatch.setattr("molmanager.workers.gnina_dock_worker.gnina_launch_env", lambda _exe: {})
    monkeypatch.setattr(dlg._proc, "start", lambda *_args, **_kwargs: None)
    dlg._worker.start_process(["--receptor", "rec.pdbqt"])
    assert dlg.isHidden()
    dlg.close()
