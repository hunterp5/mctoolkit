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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Docking I/O helpers (PDBQT parse, setup file, pose merge)."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.docking.pose_file_io import (
    affinity_from_pdbqt,
    combine_placement_and_minimized,
    combine_pose_mols,
    combine_sdf_placement_and_minimized,
    dock_result_headers,
    gnina_executable_ok,
    is_autobox_ligand_path,
    load_sdf_mols,
    merge_pdbqt_files,
    mol_from_pdbqt_block,
    mols_from_dock_output,
    pose_metadata_from_pdbqt,
    pose_stage_from_pdbqt,
    restore_sdf_bond_orders,
    sdf_path_for_pdbqt,
    smina_executable_ok,
    smina_log_pose_rows,
    split_ligand_pdbqt_records,
    split_pdbqt_models,
    stamp_pose_ff_energies,
    write_ligand_pdbqt_as_sdf,
    write_pdbqt_poses_sdf,
    write_protein_setup,
)


def test_write_protein_setup(tmp_path):
    path = write_protein_setup(
        tmp_path / "grid.txt",
        center_x=1.5,
        center_y=-2.0,
        center_z=3.25,
        size_x=20,
        size_y=18,
        size_z=22,
    )
    text = path.read_text(encoding="utf-8")
    assert "center_x = 1.5" in text
    assert "size_z = 22.0" in text


def test_split_pdbqt_models_and_affinity():
    raw = (
        "MODEL 1\n"
        "REMARK VINA RESULT:      -8.50      0.000      0.000\n"
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C\n"
        "ENDMDL\n"
        "MODEL 2\n"
        "REMARK minimizedAffinity -6.25\n"
        "ATOM      1  C   LIG     1       1.000   0.000   0.000  0.00  0.00     0.000 C\n"
        "ENDMDL\n"
    )
    models = split_pdbqt_models(raw)
    assert len(models) == 2
    assert affinity_from_pdbqt(models[0]) == -8.5
    assert affinity_from_pdbqt(models[1]) == -6.25


_TWO_MEEKO_LIGANDS = """\
ROOT
ATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C
ENDROOT
TORSDOF 0
ROOT
ATOM      1  C   UNL     1       1.000   0.000   0.000  1.00  0.00     0.000 C
ENDROOT
TORSDOF 0
"""


def test_split_ligand_pdbqt_records_concatenated_meeko():
    records = split_ligand_pdbqt_records(_TWO_MEEKO_LIGANDS)
    assert len(records) == 2
    assert records[0].strip().startswith("ROOT")
    assert "TORSDOF" in records[0]
    assert sum(1 for ln in records[1].splitlines() if ln.startswith("ROOT")) == 1
    assert "ROOT" not in records[0].split("TORSDOF")[1]


def test_split_ligand_pdbqt_records_strips_model_tags():
    raw = (
        "MODEL 1\nROOT\nATOM      1  C   UNL     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
        "ENDROOT\nTORSDOF 0\nENDMDL\n"
        "MODEL 2\nROOT\nATOM      1  C   UNL     1       1.000   0.000   0.000  1.00  0.00     0.000 C\n"
        "ENDROOT\nTORSDOF 0\nENDMDL\n"
    )
    records = split_ligand_pdbqt_records(raw)
    assert len(records) == 2
    assert not any(ln.startswith("MODEL") for rec in records for ln in rec.splitlines())
    assert all("TORSDOF" in rec for rec in records)


def test_split_ligand_pdbqt_axitinib_conformers():
    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.pdbqt"
    if not sample.is_file():
        pytest.skip("axitininb_conformers.pdbqt sample missing")
    records = split_ligand_pdbqt_records(sample.read_text(encoding="utf-8"))
    assert len(records) > 1
    assert all(
        rec.lstrip().startswith("REMARK") or rec.lstrip().startswith("ROOT") for rec in records
    )
    assert all("TORSDOF" in rec for rec in records)
    # Smina ligand parser rejects a second ROOT after TORSDOF.
    assert all(rec.rstrip().splitlines()[-1].startswith("TORSDOF") for rec in records)


def test_merge_pdbqt_files(tmp_path):
    a = tmp_path / "a.pdbqt"
    b = tmp_path / "b.pdbqt"
    a.write_text("MODEL 1\nATOM a\nENDMDL\n", encoding="utf-8")
    b.write_text("MODEL 1\nATOM b\nENDMDL\n", encoding="utf-8")
    dest = tmp_path / "merged.pdbqt"
    merge_pdbqt_files([a, b], dest)
    text = dest.read_text(encoding="utf-8")
    assert "ATOM a" in text and "ATOM b" in text


def test_combine_placement_and_minimized():
    placement = (
        "MODEL 1\nREMARK minimizedAffinity -8.5\n"
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  1.00  0.00     0.000 C\n"
        "ENDMDL\n"
    )
    minimized = (
        "MODEL 1\nREMARK minimizedAffinity -9.1\n"
        "ATOM      1  C   LIG     1       0.100   0.000   0.000  1.00  0.00     0.000 C\n"
        "ENDMDL\n"
    )
    combined = combine_placement_and_minimized(placement, [minimized])
    models = split_pdbqt_models(combined)
    assert len(models) == 2
    assert pose_stage_from_pdbqt(models[0]) == "placement"
    assert pose_stage_from_pdbqt(models[1]) == "minimized"


def test_write_pdbqt_poses_sdf_includes_pose_stage(tmp_path):
    src = tmp_path / "docked.pdbqt"
    atom = "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
    src.write_text(
        "MODEL 1\nREMARK poseStage placement\nREMARK minimizedAffinity -8.5\n" + atom + "ENDMDL\n"
        "MODEL 2\nREMARK poseStage minimized\nREMARK minimizedAffinity -9.1\n"
        + atom.replace("  0.000   0.000   0.000", "  0.200   0.000   0.000")
        + "ENDMDL\n",
        encoding="utf-8",
    )
    dest, n_written = write_pdbqt_poses_sdf(src)
    assert n_written == 2
    suppl = Chem.SDMolSupplier(str(dest), removeHs=False)
    mols = [m for m in suppl if m is not None]
    assert mols[0].GetProp("poseStage") == "placement"
    assert mols[1].GetProp("poseStage") == "minimized"


def test_sdf_path_for_pdbqt():
    assert sdf_path_for_pdbqt("out.pdbqt") == Path("out.sdf")
    assert sdf_path_for_pdbqt(Path("docked") / "lig.PDBQT") == Path("docked") / "lig.sdf"


def test_write_pdbqt_poses_sdf(tmp_path):
    src = tmp_path / "docked.pdbqt"
    atom = "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
    src.write_text(
        "MODEL 1\nREMARK VINA RESULT:      -8.50      0.000      0.000\n" + atom + "ENDMDL\n"
        "MODEL 2\nREMARK minimizedAffinity -6.25\n"
        + atom.replace("  0.000   0.000   0.000", "  1.000   0.000   0.000")
        + "ENDMDL\n",
        encoding="utf-8",
    )
    dest, n_written = write_pdbqt_poses_sdf(src)
    assert dest == tmp_path / "docked.sdf"
    assert n_written == 2
    suppl = Chem.SDMolSupplier(str(dest), removeHs=False)
    mols = [m for m in suppl if m is not None]
    assert len(mols) == 2
    assert mols[0].GetProp("minimizedAffinity") == "-8.500"
    assert mols[0].GetProp("rmsd_lb") == "0.000"
    assert mols[0].GetProp("rmsd_ub") == "0.000"
    assert mols[1].GetProp("minimizedAffinity") == "-6.250"


def test_write_pdbqt_poses_sdf_sample_ligand(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "samples" / "4AGC_liigand.pdbqt"
    if not sample.is_file():
        pytest.skip("sample ligand missing")
    src = tmp_path / "out.pdbqt"
    src.write_bytes(sample.read_bytes())
    dest, n_written = write_pdbqt_poses_sdf(src)
    assert dest == tmp_path / "out.sdf"
    assert n_written >= 1
    suppl = Chem.SDMolSupplier(str(dest), removeHs=False)
    assert any(m is not None for m in suppl)


def test_mol_from_pdbqt_restores_axitinib_bond_orders():
    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.pdbqt"
    if not sample.is_file():
        pytest.skip("axitininb_conformers.pdbqt sample missing")
    records = split_ligand_pdbqt_records(sample.read_text(encoding="utf-8"))
    mol = mol_from_pdbqt_block(records[0])
    assert mol is not None
    assert mol.GetNumAtoms() == 28
    orders = {b.GetBondType() for b in mol.GetBonds()}
    assert Chem.BondType.DOUBLE in orders or any(b.GetIsAromatic() for b in mol.GetBonds())
    smiles = Chem.MolToSmiles(mol)
    assert "c" in smiles or "=" in smiles


def test_write_pdbqt_poses_sdf_axitinib_keeps_double_bonds(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.pdbqt"
    if not sample.is_file():
        pytest.skip("axitininb_conformers.pdbqt sample missing")
    src = tmp_path / "out.pdbqt"
    src.write_bytes(sample.read_bytes())
    dest, n_written = write_pdbqt_poses_sdf(src)
    assert n_written >= 1
    mols = [m for m in Chem.SDMolSupplier(str(dest), removeHs=False) if m is not None]
    assert mols
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mols[0].GetBonds()
    )


def test_write_ligand_pdbqt_as_sdf_axitinib(tmp_path):
    sample = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.pdbqt"
    if not sample.is_file():
        pytest.skip("axitininb_conformers.pdbqt sample missing")
    dest, n_written = write_ligand_pdbqt_as_sdf(sample, tmp_path / "lig.sdf")
    assert n_written > 1
    mols = load_sdf_mols(dest)
    assert len(mols) == n_written
    assert any(
        b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mols[0].GetBonds()
    )


def test_restore_sdf_bond_orders_from_template(tmp_path):
    sdf = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.sdf"
    if not sdf.is_file():
        pytest.skip("axitininb_conformers.sdf sample missing")
    template = next(m for m in Chem.SDMolSupplier(str(sdf), removeHs=False) if m is not None)
    pose = Chem.Mol(template)
    for bond in pose.GetBonds():
        bond.SetBondType(Chem.BondType.SINGLE)
        bond.SetIsAromatic(False)
    dest = tmp_path / "flat.sdf"
    writer = Chem.SDWriter(str(dest))
    writer.SetKekulize(False)
    writer.write(pose)
    writer.close()
    n_restored = restore_sdf_bond_orders(dest, template)
    assert n_restored == 1
    mol = load_sdf_mols(dest)[0]
    assert any(b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mol.GetBonds())


def test_combine_sdf_placement_and_minimized(tmp_path):
    sdf = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.sdf"
    if not sdf.is_file():
        pytest.skip("axitininb_conformers.sdf sample missing")
    mols = load_sdf_mols(sdf)
    place = tmp_path / "place.sdf"
    minimized = tmp_path / "min.sdf"
    writer = Chem.SDWriter(str(place))
    writer.write(mols[0])
    writer.close()
    writer = Chem.SDWriter(str(minimized))
    writer.write(mols[0] if len(mols) == 1 else mols[1])
    writer.close()
    dest, n_written = combine_sdf_placement_and_minimized(place, minimized)
    assert n_written == 2
    combined = load_sdf_mols(dest)
    assert combined[0].GetProp("poseStage") == "placement"
    assert combined[1].GetProp("poseStage") == "minimized"


def test_mol_from_pdbqt_template_restores_sdf_bond_orders():
    sdf = Path(__file__).resolve().parents[1] / "samples" / "axitininb_conformers.sdf"
    if not sdf.is_file():
        pytest.skip("axitininb_conformers.sdf sample missing")
    template = next(m for m in Chem.SDMolSupplier(str(sdf), removeHs=False) if m is not None)
    conf = template.GetConformer()
    lines = ["ROOT\n"]
    for i, atom in enumerate(template.GetAtoms(), start=1):
        pos = conf.GetAtomPosition(atom.GetIdx())
        sym = atom.GetSymbol().ljust(3)
        lines.append(
            f"ATOM  {i:5d}  {sym}UNL     1    "
            f"{pos.x:8.3f}{pos.y:8.3f}{pos.z:8.3f}  1.00  0.00     0.000 {sym.strip()}\n"
        )
    lines.append("ENDROOT\nTORSDOF 0\n")
    mol = mol_from_pdbqt_block("".join(lines), template=template)
    assert mol is not None
    assert any(b.GetBondType() == Chem.BondType.DOUBLE or b.GetIsAromatic() for b in mol.GetBonds())
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol = Chem.AddHs(mol)
    assert AllChem.EmbedMolecule(mol, AllChem.ETKDG()) == 0
    a = Chem.Mol(mol)
    b = Chem.Mol(mol)
    conf = b.GetConformer()
    p = conf.GetAtomPosition(0)
    conf.SetAtomPosition(0, (p.x + 0.4, p.y, p.z))
    combined = combine_pose_mols([a, b])
    assert combined is not None
    assert combined.GetNumConformers() == 2


def test_smina_executable_ok(tmp_path):
    exe = tmp_path / "smina.exe"
    exe.write_bytes(b"")
    assert smina_executable_ok(str(exe))
    assert not smina_executable_ok("")
    assert not smina_executable_ok(str(tmp_path / "missing.bin"))


def test_gnina_executable_ok_accepts_wsl_name(monkeypatch, tmp_path):
    exe = tmp_path / "gnina"
    exe.write_bytes(b"")
    assert gnina_executable_ok(str(exe))
    monkeypatch.setattr("molmanager.docking.gnina_launch.gnina_uses_wsl", lambda: True)
    monkeypatch.setattr("molmanager.docking.gnina_launch.resolve_user_executable", lambda _p: None)
    assert gnina_executable_ok("gnina")
    assert not gnina_executable_ok("")


def test_is_autobox_ligand_path():
    assert is_autobox_ligand_path("crystal.pdb")
    assert is_autobox_ligand_path("crystal.PDB")
    assert is_autobox_ligand_path("lig.pdbqt")
    assert not is_autobox_ligand_path("lig.sdf")
    assert not is_autobox_ligand_path("rec.mol2")


def test_pose_metadata_from_pdbqt_extracts_smina_and_vina_fields():
    block = (
        "MODEL 1\n"
        "REMARK  Name = oid7_conf1\n"
        "REMARK minimizedAffinity -10.3347759\n"
        "REMARK minimizedRMSD 0.05945\n"
        "REMARK poseStage minimized\n"
        "REMARK SMILES CCO\n"
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
        "ENDMDL\n"
    )
    meta = pose_metadata_from_pdbqt(block)
    assert meta["minimizedAffinity"] == "-10.335"
    assert meta["minimizedRMSD"] == "0.05945"
    assert meta["poseStage"] == "minimized"
    assert meta["Name"] == "oid7_conf1"
    assert meta["SMILES"] == "CCO"
    vina = pose_metadata_from_pdbqt(
        "REMARK VINA RESULT:      -8.50      0.000      1.250\n"
        "ATOM      1  C   LIG     1       0.000   0.000   0.000  0.00  0.00     0.000 C \n"
    )
    assert vina["minimizedAffinity"] == "-8.500"
    assert vina["rmsd_lb"] == "0.000"
    assert vina["rmsd_ub"] == "1.250"
    skipped = pose_metadata_from_pdbqt("REMARK minimizedRMSD -1\nREMARK minimizedAffinity -3.1\n")
    assert "minimizedRMSD" not in skipped
    cnn = pose_metadata_from_pdbqt(
        "REMARK CNNscore 0.9123\nREMARK CNNaffinity 6.45\nREMARK CNN_VS 5.2\n"
        "REMARK minimizedAffinity -8.1\n"
    )
    assert cnn["CNNscore"] == "0.912"
    assert cnn["CNNaffinity"] == "6.450"
    assert cnn["CNN_VS"] == "5.200"
    assert cnn["minimizedAffinity"] == "-8.100"
    assert skipped["minimizedAffinity"] == "-3.100"


def test_smina_log_pose_rows_parses_mode_table():
    log = (
        "mode |   affinity | dist from best mode\n"
        "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
        "-----+------------+----------+----------\n"
        "   1       -12.339      0.000      0.000\n"
        "   2       -11.204      1.234      2.456\n"
        "Writing output ... done.\n"
    )
    rows = smina_log_pose_rows(log)
    assert len(rows) == 2
    assert rows[0]["mode"] == "1"
    assert rows[0]["minimizedAffinity"] == "-12.339"
    assert rows[1]["rmsd_lb"] == "1.234"
    assert rows[1]["rmsd_ub"] == "2.456"


def test_mols_from_dock_output_merges_log(tmp_path):
    sdf = tmp_path / "out.sdf"
    mol = Chem.MolFromSmiles("CCO")
    mol.SetProp("minimizedAffinity", "-7.250")
    mol.SetProp("CNNscore", "0.910")
    mol.SetProp("CNNaffinity", "6.200")
    from rdkit.Chem import SDWriter

    writer = SDWriter(str(sdf))
    writer.write(mol)
    writer.close()
    log = (
        "mode |   affinity | dist from best mode\n"
        "     | (kcal/mol) | rmsd l.b.| rmsd u.b.\n"
        "-----+------------+----------+----------\n"
        "   1         -7.25      0.000      0.000\n"
    )
    mols = mols_from_dock_output(sdf, log_text=log)
    assert len(mols) == 1
    assert mols[0].GetProp("minimizedAffinity") == "-7.250"
    assert mols[0].GetProp("mode") == "1"
    assert mols[0].GetProp("rmsd_lb") == "0.000"
    headers = dock_result_headers(mols)
    assert headers[:2] == ["ID_HIDDEN", "Structure"]
    assert "minimizedAffinity" in headers
    assert "CNNscore" in headers
    assert "CNNaffinity" in headers
    assert headers.index("CNNscore") < headers.index("CNNaffinity")
    assert headers.index("CNNaffinity") < headers.index("minimizedAffinity")
    assert "mode" in headers
    assert "rmsd_lb" in headers
    assert "confs" in headers
    assert "poses" not in headers


def test_group_dock_poses_by_parent_oid():
    from molmanager.docking.pose_file_io import (
        dock_poses_pack_meta,
        group_dock_poses,
        stamp_pose_parent_oids,
    )
    from molmanager.services.column_labels import COLUMN_PARENT_OID

    parent = Chem.MolFromSmiles("CCO")
    orphan = Chem.MolFromSmiles("CCN")
    assert parent is not None and orphan is not None
    parent.SetProp("_Name", "7")
    parent.SetProp("minimizedAffinity", "-8.1")
    orphan.SetProp("_Name", "filelig")
    orphan.SetProp("CNNaffinity", "-5.0")
    stamp_pose_parent_oids([parent, orphan], {7})
    assert parent.GetProp(COLUMN_PARENT_OID) == "7"
    assert not orphan.HasProp(COLUMN_PARENT_OID)
    by_oid, orphans = group_dock_poses([parent, orphan], {7})
    assert list(by_oid.keys()) == [7]
    assert len(by_oid[7]) == 1
    assert len(orphans) == 1
    assert len(orphans[0]) == 1
    meta = dock_poses_pack_meta(by_oid[7])
    assert meta["op"] == "gnina"
    assert meta["n_packed"] == 1
    assert meta["e_min_kcal"] == -8.1


def test_ordered_dock_pose_groups_first_seen():
    from molmanager.docking.pose_file_io import ordered_dock_pose_groups
    from molmanager.services.column_labels import COLUMN_PARENT_OID

    a = Chem.MolFromSmiles("CCO")
    b = Chem.MolFromSmiles("CCO")
    c = Chem.MolFromSmiles("CCN")
    assert a is not None and b is not None and c is not None
    a.SetProp(COLUMN_PARENT_OID, "1")
    b.SetProp(COLUMN_PARENT_OID, "1")
    c.SetProp("_Name", "filelig")
    groups = ordered_dock_pose_groups([a, c, b], {1})
    assert len(groups) == 2
    assert groups[0] == [a, b]
    assert groups[1] == [c]


def test_dock_result_headers_skip_packed_poses():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("minimizedAffinity", "-7.250")
    mol.SetProp("poses", "blob")
    headers = dock_result_headers([mol])
    assert "poses" not in headers
    assert "minimizedAffinity" in headers


def test_dock_result_headers_include_crystal_ref():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("crystalRMSD", "1.250")
    mol.SetProp("crystalRef", "AXI A 2000")
    mol.SetProp("minimizedAffinity", "-7.250")
    headers = dock_result_headers([mol])
    assert "crystalRMSD" in headers
    assert "crystalRef" in headers
    assert headers.index("minimizedAffinity") < headers.index("crystalRMSD")
    assert headers.index("crystalRMSD") < headers.index("crystalRef")


def test_stamp_pose_ff_energies_writes_mmff_and_uff():
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    assert AllChem.EmbedMolecule(mol, randomSeed=7) == 0
    stamp_pose_ff_energies([mol])
    mmff = float(mol.GetProp("E_MMFF"))
    uff = float(mol.GetProp("E_UFF"))
    assert math.isfinite(mmff)
    assert math.isfinite(uff)


def _sulfonamide_with_extra_hydrogen() -> Chem.Mol:
    """Neutral sulfonamide whose nitrogen has two explicit H (Gnina/OpenBabel)."""
    mol = Chem.AddHs(Chem.MolFromSmiles("CS(=O)(=O)NC"))
    assert mol is not None
    assert AllChem.EmbedMolecule(mol, randomSeed=1) == 0
    edited = Chem.RWMol(mol)
    nitrogen = next(atom.GetIdx() for atom in edited.GetAtoms() if atom.GetSymbol() == "N")
    hydrogen = edited.AddAtom(Chem.Atom(1))
    edited.AddBond(nitrogen, hydrogen, Chem.BondType.SINGLE)
    conf = edited.GetConformer()
    pos = conf.GetAtomPosition(nitrogen)
    conf.SetAtomPosition(hydrogen, (pos.x + 1.0, pos.y, pos.z))
    return edited.GetMol()


def test_load_sdf_mols_drops_extra_sulfonamide_hydrogen(tmp_path):
    bad = _sulfonamide_with_extra_hydrogen()
    dest = tmp_path / "pose.sdf"
    block = Chem.MolToMolBlock(bad, kekulize=False)
    dest.write_text(block + "> <minimizedAffinity>\n-7.100\n\n$$$$\n", encoding="utf-8")
    mols = load_sdf_mols(dest)
    assert len(mols) == 1
    mol = mols[0]
    Chem.SanitizeMol(mol)
    nitrogen = next(atom for atom in mol.GetAtoms() if atom.GetSymbol() == "N")
    heavy_neighbors = [nbr for nbr in nitrogen.GetNeighbors() if nbr.GetAtomicNum() > 1]
    hydrogen_neighbors = [nbr for nbr in nitrogen.GetNeighbors() if nbr.GetAtomicNum() == 1]
    assert len(heavy_neighbors) == 2
    assert len(hydrogen_neighbors) + int(nitrogen.GetTotalNumHs()) == 1
    assert mol.GetProp("minimizedAffinity") == "-7.100"
    stamp_pose_ff_energies([mol])
    assert math.isfinite(float(mol.GetProp("E_UFF")))


def test_dock_result_headers_include_ff_energies():
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    mol.SetProp("minimizedAffinity", "-7.250")
    mol.SetProp("E_MMFF", "12.500")
    mol.SetProp("E_UFF", "8.250")
    headers = dock_result_headers([mol])
    assert headers.index("minimizedAffinity") < headers.index("E_MMFF")
    assert headers.index("E_MMFF") < headers.index("E_UFF")


def test_is_poses_header():
    from molmanager.docking.pose_file_io import is_poses_header

    assert is_poses_header("poses") is True
    assert is_poses_header("poses (1)") is True
    assert is_poses_header("poses_2") is True
    assert is_poses_header("confs") is False
    assert is_poses_header("superpose") is False


def test_dock_results_session_payload_roundtrip():
    from rdkit.Geometry import Point3D

    from molmanager.docking.pose_file_io import (
        deserialize_dock_results_payload,
        serialize_dock_results_payload,
    )
    from molmanager.services.column_labels import COLUMN_PARENT_OID

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(1.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(2.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(3.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    mol.SetProp("minimizedAffinity", "-8.100")
    mol.SetProp(COLUMN_PARENT_OID, "0")
    other = Chem.Mol(mol)
    other.SetProp(COLUMN_PARENT_OID, "1")
    other.SetProp("minimizedAffinity", "-6.400")
    snap = {
        "mols": [mol, other],
        "title": "Pose browser — out.sdf",
        "receptor_path": "/tmp/rec.pdbqt",
        "crystal_path": "/tmp/xtal.sdf",
    }
    payload = serialize_dock_results_payload(snap)
    assert payload is not None
    assert payload["title"] == "Pose browser — out.sdf"
    assert payload["receptor_path"] == "/tmp/rec.pdbqt"
    assert len(payload["poses"]) == 2
    restored = deserialize_dock_results_payload(payload)
    assert restored is not None
    assert restored["crystal_path"] == "/tmp/xtal.sdf"
    assert len(restored["mols"]) == 2
    assert restored["mols"][0].GetProp("minimizedAffinity") == "-8.100"
    assert restored["mols"][0].GetNumConformers() == 1
    filtered = serialize_dock_results_payload(snap, oids={1})
    assert filtered is not None
    assert len(filtered["poses"]) == 1
    kept = deserialize_dock_results_payload(filtered)
    assert kept is not None
    assert kept["mols"][0].GetProp("minimizedAffinity") == "-6.400"
    assert serialize_dock_results_payload(None) is None
    assert deserialize_dock_results_payload(None) is None
