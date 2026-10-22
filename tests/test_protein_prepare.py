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

"""Protein Viewer Prepare pipeline (PDBFixer, pdb2pqr, OpenMM)."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from molmanager.protein.structure_components import pdb_to_mmcif
from molmanager.workers.protein_prepare_runtime import (
    ProteinPrepareRequest,
    _gb_kappa_per_nm,
    _protein_ff_xmls,
    finalize_prepared_pdb,
    finalize_prepared_structure,
    mp_prepare_protein_structure,
    pdb2pqr_argv,
    prepare_protein_structure,
    remap_kind_map,
    remap_residue_keys,
    residue_names_by_key,
    residues_to_drop,
)

_ALA_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
END
"""

_HOLO_PDB = """\
ATOM      1  N   ALA A   1      11.104   6.134  10.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      12.260   6.859  10.000  1.00  0.00           C
ATOM      3  C   ALA A   1      13.498   6.000  10.000  1.00  0.00           C
ATOM      4  O   ALA A   1      13.400   4.780  10.000  1.00  0.00           O
ATOM      5  CB  ALA A   1      12.250   7.800   8.800  1.00  0.00           C
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O
END
"""

_ALA_CIF = pdb_to_mmcif(_ALA_PDB, data_name="ala")
_HOLO_CIF = pdb_to_mmcif(_HOLO_PDB, data_name="holo")


def _request(tmp_path, **kwargs) -> ProteinPrepareRequest:
    in_path = tmp_path / "in.pdb"
    out_path = tmp_path / "out.cif"
    if not in_path.exists():
        in_path.write_text(_ALA_PDB, encoding="utf-8")
    defaults = dict(
        input_path=str(in_path),
        output_pdb_path=str(out_path),
        ph=7.4,
        rebuild_missing_loops=True,
        include_ligand=True,
        keep_ligand=False,
        keep_water_keys=(),
        remove_other_heterogens=True,
        minimize=True,
        protonate_ligand=False,
        pocket_ligand_protonation=False,
    )
    defaults.update(kwargs)
    return ProteinPrepareRequest(**defaults)


def test_pdb2pqr_argv_includes_propka_and_ph():
    argv = pdb2pqr_argv(
        Path("in.pdb"),
        Path("out.pqr"),
        Path("out.pdb"),
        ph=7.4,
        drop_water=True,
    )
    assert "--ff=AMBER" in argv
    assert "--keep-chain" in argv
    assert "--drop-water" in argv
    assert "--titration-state-method=propka" in argv
    assert "--with-ph=7.4" in argv
    assert "--pdb-output" in argv
    dry = pdb2pqr_argv(Path("in.pdb"), Path("out.pqr"), Path("out.pdb"), ph=7.0, drop_water=False)
    assert "--drop-water" not in dry
    lig = pdb2pqr_argv(
        Path("in.pdb"),
        Path("out.pqr"),
        Path("out.pdb"),
        ph=7.4,
        ligand_mol2=Path("lig.mol2"),
    )
    assert "--ligand" in lig
    assert "lig.mol2" in lig


def test_openmm_platform_candidates_prefer_gpu(monkeypatch):
    from molmanager.workers.protein_prepare_minimize import (
        _iter_openmm_platform_candidates,
        _openmm_platform_properties,
    )

    monkeypatch.delenv("MOLMANAGER_OPENMM_PLATFORM", raising=False)
    monkeypatch.setattr(
        "molmanager.workers.protein_prepare_minimize._openmm_platform_names",
        lambda: ["Reference", "CPU", "OpenCL"],
    )
    assert _iter_openmm_platform_candidates("auto") == ["OpenCL", "CPU"]
    monkeypatch.setattr(
        "molmanager.workers.protein_prepare_minimize._openmm_platform_names",
        lambda: ["CPU", "CUDA", "OpenCL"],
    )
    assert _iter_openmm_platform_candidates("auto") == ["CUDA", "OpenCL", "CPU"]
    assert _iter_openmm_platform_candidates("CPU") == ["CPU"]
    monkeypatch.setattr(
        "molmanager.workers.protein_prepare_minimize._openmm_platform_names",
        lambda: ["CPU", "OpenCL"],
    )
    assert _iter_openmm_platform_candidates("CUDA") == ["OpenCL", "CPU"]
    assert _iter_openmm_platform_candidates("OpenCL") == ["OpenCL", "CPU"]
    props = _openmm_platform_properties("CPU")
    assert int(props["Threads"]) >= 1


def test_drop_uncappable_polymer_residues_n_only_gln():
    from molmanager.workers.protein_prepare_pdb2pqr import drop_uncappable_polymer_residues

    stub = _ALA_PDB.replace(
        "END\n",
        "ATOM      6  N   GLN A1169     -15.761  23.268   9.328  1.00 72.96           N\n"
        "TER       7      GLN A1169\n"
        "END\n",
    )
    cleaned, dropped = drop_uncappable_polymer_residues(stub, "pdb")
    assert ("A", "1169", "") in dropped
    assert ("A", "1", "") not in dropped
    assert "1169" not in cleaned
    assert "ALA" in cleaned


def test_run_pdb2pqr_reports_chained_value_error(tmp_path, monkeypatch):
    pytest.importorskip("pdb2pqr")
    from molmanager.workers.protein_prepare_pdb2pqr import _run_pdb2pqr

    inner = ValueError(
        "Too few atoms present to reconstruct or cap residue GLN A 1169 in structure!"
    )
    outer = RuntimeError()
    outer.__cause__ = inner

    def _boom(_argv):
        raise outer

    monkeypatch.setattr("pdb2pqr.main.run_pdb2pqr", _boom)
    inp = tmp_path / "in.pdb"
    inp.write_text(_ALA_PDB, encoding="utf-8")
    with pytest.raises(RuntimeError, match="GLN A 1169"):
        _run_pdb2pqr(inp, tmp_path / "out.pqr", tmp_path / "out.pdb", ph=7.4)


def test_run_pdb2pqr_drops_uncappable_terminal_stub(tmp_path):
    pytest.importorskip("pdb2pqr")
    from molmanager.workers.protein_prepare_pdb2pqr import _run_pdb2pqr

    inp = tmp_path / "in.pdb"
    inp.write_text(
        _ALA_PDB.replace(
            "END\n",
            "ATOM      6  N   GLN A1169     -15.761  23.268   9.328  1.00 72.96           N\n"
            "TER       7      GLN A1169\n"
            "END\n",
        ),
        encoding="utf-8",
    )
    _run_pdb2pqr(inp, tmp_path / "out.pqr", tmp_path / "out.pdb", ph=7.4)
    text = (tmp_path / "out.pdb").read_text(encoding="utf-8")
    assert "ALA" in text
    assert "1169" not in text


def test_prepare_protein_structure_missing_input(tmp_path):
    req = ProteinPrepareRequest(
        input_path=str(tmp_path / "missing.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    with pytest.raises(RuntimeError, match="Input structure not found"):
        prepare_protein_structure(req)


def test_mp_prepare_protein_structure_returns_error_message(tmp_path):
    req = ProteinPrepareRequest(
        input_path=str(tmp_path / "missing.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    ok, msg = mp_prepare_protein_structure(req)
    assert ok is False
    assert "Input structure not found" in msg


def test_mp_prepare_forwards_log_lines(tmp_path):
    req = ProteinPrepareRequest(
        input_path=str(tmp_path / "missing.pdb"),
        output_pdb_path=str(tmp_path / "out.pdb"),
    )
    log_path = tmp_path / "prepare.log"
    ok, _msg = mp_prepare_protein_structure(req, str(log_path))
    assert ok is False
    assert not log_path.exists() or log_path.read_text(encoding="utf-8").strip() == ""


def test_drain_prepare_log_file(tmp_path):
    from molmanager.workers.protein_prepare import drain_prepare_log_file
    from molmanager.workers.protein_prepare_io import append_prepare_log_file

    path = tmp_path / "prepare.log"
    append_prepare_log_file(path, "PDBFixer: loading")
    append_prepare_log_file(path, "  ")
    append_prepare_log_file(path, "pdb2pqr/PROPKA: protonating")
    seen = [0]
    got: list[str] = []
    drain_prepare_log_file(path, seen, got.append)
    assert got == ["PDBFixer: loading", "pdb2pqr/PROPKA: protonating"]
    drain_prepare_log_file(path, seen, got.append)
    assert got == ["PDBFixer: loading", "pdb2pqr/PROPKA: protonating"]
    append_prepare_log_file(path, "OpenMM: minimizing")
    drain_prepare_log_file(path, seen, got.append)
    assert got[-1] == "OpenMM: minimizing"


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_on_log_reports_major_steps(
    mock_open_fixer,
    _mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    tmp_path,
):
    req = _request(tmp_path, rebuild_missing_loops=False, minimize=True)
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_ALA_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_ALA_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr

    def _min(_src, dest, **_kwargs):
        dest.write_text(_ALA_PDB, encoding="utf-8")

    mock_min.side_effect = _min
    logs: list[str] = []
    prepare_protein_structure(req, on_log=logs.append)
    text = "\n".join(logs)
    assert "Reading " in text
    assert "PDBFixer:" in text
    assert "pdb2pqr/PROPKA:" in text
    assert "OpenMM:" in text
    assert "Writing prepared" in text
    assert "Prepare finished" in text


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_skips_pdb2pqr_when_protonate_false(
    mock_open_fixer,
    _mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    tmp_path,
):
    req = _request(tmp_path, rebuild_missing_loops=False, minimize=False, protonate=False)
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_ALA_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer
    logs: list[str] = []
    out = prepare_protein_structure(req, on_log=logs.append)
    mock_pqr.assert_not_called()
    mock_min.assert_not_called()
    text = "\n".join(logs)
    assert "Skipping pdb2pqr/PROPKA" in text
    assert "pdb2pqr/PROPKA:" not in text
    assert "OpenMM:" not in text
    written = Path(out.output_path).read_text(encoding="utf-8")
    assert "ALA" in written
    assert (
        "PDB2PQR SKIPPED" in written
        or "pdb2pqr skipped" in written.lower()
        or "3 PDB2PQR SKIPPED" in written
    )


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_skips_pdbfixer_when_repair_false(
    mock_open_fixer,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    tmp_path,
):
    in_path = tmp_path / "in.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    req = _request(
        tmp_path,
        repair=False,
        protonate=True,
        minimize=False,
        keep_waters=True,
        keep_ligand=True,
        protonate_ligand=False,
        pocket_ligand_protonation=False,
        remove_other_heterogens=False,
        strip_additives=False,
    )

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_HOLO_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr
    logs: list[str] = []
    out = prepare_protein_structure(req, on_log=logs.append)
    mock_open_fixer.assert_not_called()
    mock_write_fixer.assert_not_called()
    mock_min.assert_not_called()
    mock_pqr.assert_called_once()
    assert mock_pqr.call_args.kwargs["ph"] == 7.4
    assert mock_pqr.call_args.kwargs["drop_water"] is False
    text = "\n".join(logs)
    assert "Skipping PDBFixer" in text
    assert "pdb2pqr/PROPKA:" in text
    assert "PDBFixer:" not in text
    written = Path(out.output_path).read_text(encoding="utf-8")
    assert "ALA" in written
    assert "AXI" in written
    assert "HOH" in written
    assert "PDBFIXER SKIPPED" in written or "1 PDBFIXER SKIPPED" in written


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._drop_internal_missing_residues")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_rebuilds_internal_loops_by_default(
    mock_open_fixer,
    mock_prune,
    mock_write_fixer,
    mock_drop_internal,
    mock_pqr,
    mock_min,
    tmp_path,
):
    req = _request(tmp_path)
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_ALA_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_ALA_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr

    def _min(_protonated, minimized, **_kwargs):
        minimized.write_text("REMARK   4 MIN\n" + _ALA_PDB, encoding="utf-8")

    mock_min.side_effect = _min

    out = prepare_protein_structure(req)
    assert out.output_path == req.output_pdb_path
    mock_drop_internal.assert_not_called()
    mock_prune.assert_called_once()
    assert mock_prune.call_args.kwargs["include_ligand"] is True
    assert mock_prune.call_args.kwargs["keep_water_keys"] == set()
    assert mock_prune.call_args.kwargs["remove_other_heterogens"] is True
    fixer.removeHeterogens.assert_not_called()
    fixer.findMissingResidues.assert_called_once()
    fixer.findNonstandardResidues.assert_called_once()
    fixer.replaceNonstandardResidues.assert_called_once()
    fixer.findMissingAtoms.assert_called_once()
    fixer.addMissingAtoms.assert_called_once()
    fixer.addMissingHydrogens.assert_not_called()
    mock_pqr.assert_called_once()
    assert mock_pqr.call_args.kwargs["ph"] == 7.4
    assert mock_pqr.call_args.kwargs["drop_water"] is True
    mock_min.assert_called_once()
    written = (tmp_path / "out.cif").read_text(encoding="utf-8")
    assert "ALA" in written


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._drop_internal_missing_residues")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_can_skip_internal_loops_and_min(
    mock_open_fixer,
    _mock_prune,
    mock_write_fixer,
    mock_drop_internal,
    mock_pqr,
    mock_min,
    tmp_path,
):
    req = _request(tmp_path, rebuild_missing_loops=False, minimize=False)
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_ALA_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_ALA_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr
    prepare_protein_structure(req)
    mock_drop_internal.assert_called_once_with(fixer)
    mock_min.assert_not_called()
    text = (tmp_path / "out.cif").read_text(encoding="utf-8")
    assert "MOLMANAGER PROTEIN PREPARE" in text
    assert "OPENMM MINIMIZATION SKIPPED" in text


def test_residues_to_drop_keeps_ligand_and_selected_water():
    kinds = {
        ("A", "1", ""): "polymer",
        ("A", "2000", ""): "ligand",
        ("A", "2001", ""): "metal",
        ("A", "2002", ""): "water",
        ("B", "2003", ""): "water",
    }
    drop = residues_to_drop(
        kinds,
        include_ligand=True,
        keep_water_keys={("A", "2002", "")},
        remove_other_heterogens=True,
    )
    assert ("A", "1", "") not in drop
    assert ("A", "2000", "") not in drop
    assert ("A", "2001", "") in drop
    assert ("A", "2002", "") not in drop
    assert ("B", "2003", "") in drop
    apo = residues_to_drop(
        kinds,
        include_ligand=False,
        keep_water_keys=set(),
        remove_other_heterogens=True,
    )
    assert ("A", "2000", "") in apo
    assert ("A", "2002", "") in apo


def test_residues_to_drop_strips_additives_and_can_keep_metals():
    kinds = {
        ("A", "1", ""): "polymer",
        ("A", "2000", ""): "ligand",
        ("A", "50", ""): "ligand",
        ("A", "2001", ""): "metal",
    }
    names = {
        ("A", "1", ""): "ALA",
        ("A", "2000", ""): "AXI",
        ("A", "50", ""): "EDO",
        ("A", "2001", ""): "ZN",
    }
    drop = residues_to_drop(
        kinds,
        include_ligand=True,
        keep_water_keys=set(),
        remove_other_heterogens=True,
        names_by_key=names,
        strip_additives=True,
        keep_metals=False,
    )
    assert ("A", "2000", "") not in drop
    assert ("A", "50", "") in drop
    assert ("A", "2001", "") in drop
    keep_zn = residues_to_drop(
        kinds,
        include_ligand=True,
        keep_water_keys=set(),
        remove_other_heterogens=True,
        names_by_key=names,
        strip_additives=True,
        keep_metals=True,
    )
    assert ("A", "2001", "") not in keep_zn
    assert ("A", "50", "") in keep_zn
    chain = residues_to_drop(
        kinds,
        include_ligand=True,
        keep_water_keys=set(),
        remove_other_heterogens=True,
        names_by_key=names,
        keep_chain_ids=("B",),
    )
    assert ("A", "1", "") in chain


def test_drop_long_missing_gaps_skips_n_terminal_tag():
    from types import SimpleNamespace

    from molmanager.workers.protein_prepare_qc import drop_long_missing_gaps

    fixer = SimpleNamespace(
        missingResidues={(0, 0): ["GLY"] * 28, (0, 5): ["ALA", "SER"]},
    )
    n = drop_long_missing_gaps(fixer, 8)
    assert n == 28
    assert (0, 0) not in fixer.missingResidues
    assert fixer.missingResidues[(0, 5)] == ["ALA", "SER"]


def test_apply_sequence_missing_residues_n_terminal_tag_is_a_long_gap():
    from types import SimpleNamespace

    from molmanager.workers.protein_prepare_qc import (
        apply_sequence_missing_residues,
        drop_long_missing_gaps,
    )

    names = [
        "GLY",
        "SER",
        "ILE",
        "MET",
        "ARG",
        "ASP",
        "ILE",
        "ASN",
        "LYS",
        "LEU",
        "GLU",
        "GLU",
        "PRO",
        "THR",
    ]
    seqres = " ".join(names)
    remark_lines = [
        "REMARK 465 MISSING",
        "REMARK 465   M RES C SSSEQI",
    ]
    for i, resn in enumerate(names[:-2], start=1):
        remark_lines.append(f"REMARK 465     {resn:3s} A{i:5d}")
    pdb = (
        f"SEQRES   1 A   {len(names):4d}  {seqres}\n" + "\n".join(remark_lines) + "\n"
        "ATOM      1  CA  PRO A  13      0.000   0.000   0.000  1.00  0.00           C\n"
        "ATOM      2  CA  THR A  14      3.800   0.000   0.000  1.00  0.00           C\n"
        "END\n"
    )
    chain = SimpleNamespace(id="A", index=0)
    pro = SimpleNamespace(name="PRO", id="13", insertionCode="")
    thr = SimpleNamespace(name="THR", id="14", insertionCode="")
    chain.residues = lambda: [pro, thr]
    fixer = SimpleNamespace(
        topology=SimpleNamespace(chains=lambda: [chain]),
        missingResidues={},
    )
    n_added = apply_sequence_missing_residues(fixer, pdb, "pdb")
    assert n_added == 12
    assert (0, 0) in fixer.missingResidues
    assert len(fixer.missingResidues[(0, 0)]) == 12
    skipped = drop_long_missing_gaps(fixer, 8)
    assert skipped == 12
    assert fixer.missingResidues == {}


def test_remap_residue_keys_auth_chain_to_mmcif_label_chain():
    source = {("A", "2000", ""): "AXI", ("A", "2001", ""): "HOH", ("A", "801", ""): "TYR"}
    dest = {("B", "2000", ""): "AXI", ("C", "2001", ""): "HOH", ("A", "801", ""): "TYR"}
    assert remap_residue_keys({("A", "2000", "")}, source, dest) == {("B", "2000", "")}
    assert remap_residue_keys({("A", "2001", "")}, source, dest) == {("C", "2001", "")}
    assert remap_residue_keys({("A", "801", "")}, source, dest) == {("A", "801", "")}
    assert remap_residue_keys({("A", "2000", "")}, source, {}) == {("A", "2000", "")}
    kinds = remap_kind_map(
        {("A", "2000", ""): "ligand", ("A", "2001", ""): "water"},
        source,
        dest,
    )
    assert kinds[("B", "2000", "")] == "ligand"
    assert kinds[("C", "2001", "")] == "water"


def test_apply_sequence_missing_residues_inserts_internal_gap():
    from types import SimpleNamespace

    from molmanager.workers.protein_prepare_qc import apply_sequence_missing_residues

    pdb = """\
SEQRES   1 A    3  MET ALA LEU
REMARK 465     ALA A    15
ATOM      1  CA  MET A  10      0.000   0.000   0.000  1.00  0.00           C
ATOM      2  CA  LEU A  20      4.000   0.000   0.000  1.00  0.00           C
END
"""
    chain = SimpleNamespace(id="A", index=0)
    met = SimpleNamespace(name="MET", id="10", insertionCode="")
    leu = SimpleNamespace(name="LEU", id="20", insertionCode="")
    chain.residues = lambda: [met, leu]
    fixer = SimpleNamespace(
        topology=SimpleNamespace(chains=lambda: [chain]),
        missingResidues={},
    )
    n_added = apply_sequence_missing_residues(fixer, pdb, "pdb")
    assert n_added == 1
    assert fixer.missingResidues[(0, 1)] == ["ALA"]


_GAP_CIF = """\
data_gap
loop_
_entity_poly_seq.entity_id
_entity_poly_seq.num
_entity_poly_seq.mon_id
_entity_poly_seq.hetero
1 1 MET n
1 2 ALA n
1 3 LEU n
loop_
_struct_asym.id
_struct_asym.entity_id
A 1
loop_
_pdbx_poly_seq_scheme.asym_id
_pdbx_poly_seq_scheme.mon_id
_pdbx_poly_seq_scheme.pdb_seq_num
_pdbx_poly_seq_scheme.auth_seq_num
_pdbx_poly_seq_scheme.pdb_mon_id
_pdbx_poly_seq_scheme.pdb_strand_id
_pdbx_poly_seq_scheme.pdb_ins_code
_pdbx_poly_seq_scheme.hetero
A MET 10 ? ? A . n
A ALA 15 ? ? A . n
A LEU 20 20 LEU A . n
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . MET A 10 10 MET A . 0.000 0.000 0.000 1.00 0.00 1
ATOM 2 C CA . LEU A 20 20 LEU A . 4.000 0.000 0.000 1.00 0.00 1
"""

_GAP_CIF_ALTLOC = _GAP_CIF.replace(
    "ATOM 1 C CA . MET A 10 10 MET A . 0.000 0.000 0.000 1.00 0.00 1",
    "ATOM 1 C CA . MET A 10 10 MET A . 0.000 0.000 0.000 0.40 0.00 1\n"
    "ATOM 3 C CA A MET A 10 10 MET A . 0.100 0.000 0.000 0.60 0.00 1",
)


def _mock_gap_fixer():
    from types import SimpleNamespace

    chain = SimpleNamespace(id="A", index=0)
    met = SimpleNamespace(name="MET", id="10", insertionCode="")
    leu = SimpleNamespace(name="LEU", id="20", insertionCode="")
    chain.residues = lambda: [met, leu]
    return SimpleNamespace(
        topology=SimpleNamespace(chains=lambda: [chain]),
        missingResidues={},
    )


def test_apply_sequence_missing_residues_from_cif_scheme():
    from molmanager.workers.protein_prepare_qc import apply_sequence_missing_residues

    fixer = _mock_gap_fixer()
    n_added = apply_sequence_missing_residues(fixer, _GAP_CIF, "cif")
    assert n_added == 1
    assert fixer.missingResidues[(0, 1)] == ["ALA"]


def test_ligand_chem_tables_keep_input_cif_doubles():
    from molmanager.workers.protein_prepare_runtime import _ligand_chem_tables

    _atoms, bonds = _ligand_chem_tables(
        _CIF_CARBONYL,
        fmt="cif",
        keep_ligand=True,
        ligand_keys={("A", "1", "")},
        input_text=_CIF_CARBONYL,
        input_fmt="cif",
    )
    assert any({b.atom_id_1, b.atom_id_2} == {"C80", "O81"} and b.order == 2 for b in bonds["LIG"])


def test_ligand_chem_tables_prefer_input_cif_over_rewritten():
    from molmanager.workers.protein_prepare_runtime import _ligand_chem_tables

    rewritten = _CIF_CARBONYL.replace("doub", "sing")
    _atoms, bonds = _ligand_chem_tables(
        rewritten,
        fmt="cif",
        keep_ligand=True,
        ligand_keys={("A", "1", "")},
        input_text=_CIF_CARBONYL,
        input_fmt="cif",
    )
    assert any({b.atom_id_1, b.atom_id_2} == {"C80", "O81"} and b.order == 2 for b in bonds["LIG"])


def test_residue_names_by_key_reads_cif_auth_ids():
    names = residue_names_by_key(_HOLO_CIF, "cif")
    assert names[("A", "2000", "")] == "AXI"
    assert names[("A", "2002", "")] == "HOH"


@patch("molmanager.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_remaps_mmcif_ligand_chain_after_fixer(
    mock_open_fixer,
    mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    mock_ligands,
    tmp_path,
):
    """OpenMM writes AXI on label chain B; Prepare must look it up there, not auth A."""
    from molmanager.protein.structure_components import atoms_to_mmcif, parse_structure_atoms

    in_path = tmp_path / "in.cif"
    in_path.write_text(_HOLO_CIF, encoding="utf-8")
    repaired_atoms = [
        replace(atom, chain="B") if atom.resn == "AXI" else atom
        for atom in parse_structure_atoms(_HOLO_CIF, "cif")
    ]
    repaired_cif = atoms_to_mmcif(repaired_atoms, data_name="repaired")

    req = _request(
        tmp_path,
        input_path=str(in_path),
        include_ligand=True,
        keep_ligand=True,
        minimize=True,
        protonate_ligand=False,
    )
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    fixer.topology.residues.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(repaired_cif, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(repaired_cif, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr
    captured: list[set] = []

    def _gaff(text, keys, **kwargs):
        captured.append(set(keys))
        return [object()], text

    mock_ligands.side_effect = _gaff

    def _min(src, dest, **_kwargs):
        dest.write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

    mock_min.side_effect = _min
    prepare_protein_structure(req)
    assert captured
    assert captured[0] == {("B", "2000", "")}


def test_finalize_prepared_pdb_ligand_and_water():
    ligand_keys = {("A", "2000", "")}
    water_keys = {("A", "2002", "")}
    stripped = finalize_prepared_pdb(
        _HOLO_PDB,
        _HOLO_PDB,
        ligand_keys=ligand_keys,
        keep_ligand=False,
        keep_water_keys=water_keys,
    )
    assert "AXI" not in stripped
    assert "HOH" in stripped
    assert "ALA" in stripped
    kept = finalize_prepared_pdb(
        _ALA_PDB,
        _HOLO_PDB,
        ligand_keys=ligand_keys,
        keep_ligand=True,
        keep_water_keys=water_keys,
    )
    assert "AXI" in kept
    assert "HOH" in kept


def test_finalize_prepared_structure_cif_ligand_and_water():
    ligand_keys = {("A", "2000", "")}
    water_keys = {("A", "2002", "")}
    stripped = finalize_prepared_structure(
        _HOLO_CIF,
        _HOLO_CIF,
        ligand_keys=ligand_keys,
        keep_ligand=False,
        keep_water_keys=water_keys,
        fmt="cif",
    )
    assert "AXI" not in stripped
    assert "HOH" in stripped
    assert "ALA" in stripped
    kept = finalize_prepared_structure(
        _ALA_CIF,
        _HOLO_CIF,
        ligand_keys=ligand_keys,
        keep_ligand=True,
        keep_water_keys=water_keys,
        fmt="cif",
    )
    assert "AXI" in kept
    assert "HOH" in kept


def test_delete_cif_residues_drops_ligand():
    from molmanager.protein.structure_components import delete_cif_residues, parse_structure_atoms

    text = delete_cif_residues(_HOLO_CIF, {("A", "2000", "")})
    resns = {atom.resn for atom in parse_structure_atoms(text, "cif")}
    assert "AXI" not in resns
    assert "ALA" in resns
    assert "HOH" in resns


def test_ligand_bond_orders_from_smiles():
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import (
        mol_from_ligand_pdb,
        prepare_ligands_for_gaff,
    )

    block = """\
HETATM    1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM    2  O   LIG A   1       1.210   0.000   0.000  1.00  0.00           O
END
"""
    template = Chem.MolFromSmiles("C=O")
    mol = mol_from_ligand_pdb(block, template=template)
    orders = {b.GetBondType() for b in mol.GetBonds()}
    assert Chem.BondType.DOUBLE in orders
    pdb = _ALA_PDB.replace(
        "END\n",
        "HETATM  100  C   LIG A2000       0.000   0.000   0.000  1.00  0.00           C\n"
        "HETATM  101  O   LIG A2000       1.210   0.000   0.000  1.00  0.00           O\n"
        "END\n",
    )
    mols, rewritten = prepare_ligands_for_gaff(
        pdb,
        {("A", "2000", "")},
        smiles="C=O",
    )
    assert len(mols) == 1
    assert mols[0].GetNumAtoms() > 2
    assert "LIG" in rewritten
    lig_line = next(line for line in rewritten.splitlines() if line.startswith("HETATM"))
    padded = lig_line.ljust(80)
    assert padded[17:20] == "LIG"
    assert padded[21] == "A"
    assert padded[22:26].strip() == "2000"
    assert padded[16] == " "
    assert any(
        line[12:16].strip().startswith("H")
        for line in rewritten.splitlines()
        if line.startswith("HETATM")
    )


def test_prepare_ligands_for_gaff_cif_keeps_chem_comp_bond():
    from molmanager.workers.protein_prepare_ligand import prepare_ligands_for_gaff

    mols, rewritten = prepare_ligands_for_gaff(
        _CIF_CARBONYL,
        {("A", "1", "")},
        smiles="C=O",
        fmt="cif",
    )
    assert len(mols) == 1
    assert mols[0].GetNumAtoms() > 2
    assert rewritten.lstrip().startswith("data_")
    assert "_atom_site." in rewritten
    assert "_chem_comp_bond.value_order" in rewritten
    assert "LIG" in rewritten
    from molmanager.protein.structure_components import parse_cif_chem_comp_bonds

    bonds = parse_cif_chem_comp_bonds(rewritten).get("LIG") or ()
    assert any({b.atom_id_1, b.atom_id_2} == {"C80", "O81"} and b.order == 2 for b in bonds)


def test_hetatm_line_keeps_pdb_resname_columns():
    from molmanager.workers.protein_prepare_ligand import _hetatm_line

    line = _hetatm_line(2444, "O81", "AXI", "A", "2000", "", -26.050, -1.540, -9.129, "O")
    padded = line.ljust(80)
    assert padded[12:16] == " O81"
    assert padded[16] == " "
    assert padded[17:20] == "AXI"
    assert padded[21] == "A"
    assert padded[22:26] == "2000"


def test_ligand_blocks_drop_alternate_locations():
    from molmanager.workers.protein_prepare_ligand import ligand_residue_blocks

    pdb = """\
HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM    2  C1 ALIG A   1       0.100   0.000   0.000  0.50  0.00           C
HETATM    3  O1  LIG A   1       1.210   0.000   0.000  1.00  0.00           O
HETATM    4  O1 BLIG A   1       1.310   0.000   0.000  0.50  0.00           O
END
"""
    blocks = ligand_residue_blocks(pdb, {("A", "1", "")})
    assert len(blocks) == 1
    body = blocks[0][2]
    assert " C1 A" not in body
    assert " O1 B" not in body
    assert body.count("HETATM") == 2


def test_ligand_smiles_atom_count_mismatch():
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import mol_from_ligand_pdb

    block = """\
HETATM    1  C   LIG A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM    2  O   LIG A   1       1.210   0.000   0.000  1.00  0.00           O
END
"""
    try:
        mol_from_ligand_pdb(block, template=Chem.MolFromSmiles("c1ccccc1"))
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "atom count" in str(exc).lower()


@patch("molmanager.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_strips_ligand_after_propka_unless_kept(
    mock_open_fixer,
    mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    mock_ligands,
    tmp_path,
):
    in_path = tmp_path / "in.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    req = _request(
        tmp_path,
        include_ligand=True,
        keep_ligand=False,
        keep_water_keys=(("A", "2002", ""),),
        minimize=False,
    )

    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_HOLO_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_ALA_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr
    mock_ligands.side_effect = lambda text, _keys, **_k: ([object()], text)

    def _min(src, dest, **_kwargs):
        dest.write_text(Path(src).read_text(encoding="utf-8"), encoding="utf-8")

    mock_min.side_effect = _min
    prepare_protein_structure(req)
    assert mock_pqr.call_args.kwargs["drop_water"] is False
    mock_prune.assert_called_once()
    assert mock_prune.call_args.kwargs["include_ligand"] is True
    assert ("A", "2002", "") in mock_prune.call_args.kwargs["keep_water_keys"]
    text = (tmp_path / "out.cif").read_text(encoding="utf-8")
    assert "AXI" not in text
    assert "HOH" in text
    assert "KEEP LIGAND FOR PROPKA" in text
    assert "STRIP LIGAND FROM OUTPUT" in text
    mock_min.assert_not_called()
    mock_ligands.assert_not_called()

    out_keep = tmp_path / "kept.cif"
    req_keep = replace(
        req,
        output_pdb_path=str(out_keep),
        keep_ligand=True,
        keep_water_keys=(),
        minimize=True,
    )
    prepare_protein_structure(req_keep)
    mock_min.assert_called_once()
    assert not mock_min.call_args.kwargs.get("ligand_mols")
    assert mock_min.call_args.kwargs["ligand_keys"] == set()
    assert (mock_min.call_args.kwargs.get("ligand_ff") or "none") == "none"
    mock_ligands.assert_called_once()
    kept = out_keep.read_text(encoding="utf-8")
    assert "AXI" in kept
    assert not any("GAFF2" in line for line in mock_min.call_args.kwargs["remarks"])

    out_apo = tmp_path / "apo.cif"
    req_apo = replace(
        req,
        output_pdb_path=str(out_apo),
        keep_ligand=False,
        keep_water_keys=(),
        minimize=True,
    )
    prepare_protein_structure(req_apo)
    apo = out_apo.read_text(encoding="utf-8")
    assert "AXI" not in apo
    assert mock_min.call_count == 2


@patch("molmanager.workers.protein_prepare_ligand.prepare_ligands_for_gaff")
@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_gaff2_keeps_ligand_in_openmm(
    mock_open_fixer,
    _mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    mock_ligands,
    tmp_path,
):
    in_path = tmp_path / "holo.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    out = tmp_path / "gaff.cif"
    req = _request(
        tmp_path,
        input_path=str(in_path),
        output_pdb_path=str(out),
        include_ligand=True,
        keep_ligand=True,
        minimize=True,
        ligand_ff="gaff2",
        ligand_smiles="C",
    )
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        path.write_text(_HOLO_PDB, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(_repaired, _pqr, protonated, **_kwargs):
        protonated.write_text(_HOLO_PDB, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr
    mock_ligands.side_effect = lambda text, _keys, **_k: ([object()], text)
    seen: dict = {}

    def _min(src, dest, **kwargs):
        seen["text"] = Path(src).read_text(encoding="utf-8")
        seen["kwargs"] = kwargs
        dest.write_text(seen["text"], encoding="utf-8")

    mock_min.side_effect = _min
    prepare_protein_structure(req)
    mock_min.assert_called_once()
    assert "AXI" in seen["text"]
    assert seen["kwargs"]["ligand_ff"] == "gaff2"
    assert seen["kwargs"]["ligand_keys"]
    assert seen["kwargs"]["ligand_mols"]
    assert seen["kwargs"]["work_dir"] is not None
    assert "AXI" in out.read_text(encoding="utf-8")


@patch("molmanager.workers.protein_prepare_runtime._restrained_minimize_pdb")
@patch("molmanager.workers.protein_prepare_runtime._run_pdb2pqr")
@patch("molmanager.workers.protein_prepare_runtime._write_fixer_pdb")
@patch("molmanager.workers.protein_prepare_runtime._prune_fixer_residues")
@patch("molmanager.workers.protein_prepare_runtime._open_fixer")
def test_prepare_cif_input_keeps_cif_work_files(
    mock_open_fixer,
    _mock_prune,
    mock_write_fixer,
    mock_pqr,
    mock_min,
    tmp_path,
):
    in_path = tmp_path / "in.cif"
    in_path.write_text(_ALA_CIF, encoding="utf-8")
    req = _request(tmp_path, input_path=str(in_path), minimize=True)
    fixer = MagicMock()
    fixer.topology.atoms.return_value = []
    mock_open_fixer.return_value = fixer

    def _write_fixer(_fixer, path):
        assert path.suffix == ".cif"
        path.write_text(_ALA_CIF, encoding="utf-8")

    mock_write_fixer.side_effect = _write_fixer

    def _write_pqr(repaired, _pqr, protonated, **_kwargs):
        assert repaired.suffix == ".cif"
        assert protonated.suffix == ".cif"
        protonated.write_text(_ALA_CIF, encoding="utf-8")

    mock_pqr.side_effect = _write_pqr

    def _min(src, dest, **_kwargs):
        assert Path(src).suffix == ".cif"
        assert dest.suffix == ".cif"
        dest.write_text(_ALA_CIF, encoding="utf-8")

    mock_min.side_effect = _min
    out = prepare_protein_structure(req)
    text = Path(out.output_path).read_text(encoding="utf-8")
    assert out.output_path.endswith(".cif")
    assert text.lstrip().startswith("data_")
    assert "_atom_site." in text
    assert "REMARK   4" not in text
    assert "MOLMANAGER PROTEIN PREPARE" in text
    mock_pqr.assert_called_once()
    mock_min.assert_called_once()


@patch("pdb2pqr.main.run_pdb2pqr")
def test_run_pdb2pqr_cif_output_wraps_pdb_dump(mock_run, tmp_path):
    pytest.importorskip("pdb2pqr")
    from molmanager.workers.protein_prepare_runtime import _run_pdb2pqr

    inp = tmp_path / "repaired.cif"
    inp.write_text(_ALA_CIF, encoding="utf-8")
    pqr = tmp_path / "out.pqr"
    out = tmp_path / "protonated.cif"

    def _fake_run(argv):
        pdb_out = Path(argv[argv.index("--pdb-output") + 1])
        assert pdb_out.suffix == ".pdb"
        assert Path(argv[-2]).suffix == ".pdb"
        pdb_out.write_text(_ALA_PDB, encoding="utf-8")
        Path(argv[-1]).write_text("PQR\n", encoding="utf-8")

    mock_run.side_effect = _fake_run
    _run_pdb2pqr(inp, pqr, out, ph=7.4)
    text = out.read_text(encoding="utf-8")
    assert text.lstrip().startswith("data_")
    assert "ALA" in text
    assert not list(tmp_path.glob("*.pdb2pqr.pdb"))
    assert not list(tmp_path.glob("*pdb2pqr_in.pdb"))
    assert inp.is_file()


def test_open_fixer_does_not_lock_source_cif(tmp_path):
    pytest.importorskip("pdbfixer")
    pytest.importorskip("openmm")
    from molmanager.workers.protein_prepare_runtime import _open_fixer

    path = tmp_path / "in.cif"
    path.write_text(_ALA_CIF, encoding="utf-8")
    _open_fixer(path)
    path.write_text(_ALA_CIF, encoding="utf-8")
    path.unlink()
    assert not path.exists()


def test_prepare_water_keys_from_manager_selection(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert dlg.prepare_water_keys() == ()
    for row in dlg._rows:
        if row.spec.kind == "water":
            row.selected = True
    keys = dlg.prepare_water_keys()
    assert keys == (("A", "2002", ""),)
    dlg.close()


def test_prepare_dialog_defaults_and_menu(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QGroupBox, QMenuBar, QMessageBox, QTextEdit

    from molmanager.ui.protein_prepare_dialog import ProteinPrepareDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    mb = dlg.findChild(QMenuBar)
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert "Tools" in labels
    tools_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    prepare_menu = next(
        a.menu() for a in tools_menu.actions() if a.text().replace("&", "") == "Prepare"
    )
    prepare_labels = [a.text().replace("&", "") for a in prepare_menu.actions()]
    assert any(label.startswith("Fast Prepare") for label in prepare_labels)
    assert any(label.startswith("PDBFixer") for label in prepare_labels)
    assert any("pdb2pqr" in label for label in prepare_labels)
    assert any(label.startswith("Minimize") for label in prepare_labels)
    assert any(label.startswith("Dock File") for label in prepare_labels)
    render_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Render")
    render_labels = [a.text().replace("&", "") for a in render_menu.actions()]
    assert "Docking Box" in render_labels

    shown: list[str] = []

    def _info(*_a, **_k):
        shown.append("info")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    dlg.open_prepare_dialog()
    assert not shown
    empty_prep = dlg._prepare_dialog
    assert empty_prep.radio_src_file.isChecked()
    assert empty_prep.combo_src_manager.count() == 0

    path = tmp_path / "mini.pdb"
    path.write_text(_ALA_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_prepare_dialog()
    prep = dlg._prepare_dialog
    assert isinstance(prep, ProteinPrepareDialog)
    assert dlg.log.isReadOnly()
    assert not prep.findChildren(QTextEdit)
    prep._append_log("Starting Fast Prepare")
    assert "Starting Fast Prepare" in dlg.log.toPlainText()
    titles = [gb.title() for gb in prep.findChildren(QGroupBox)]
    assert "PDBFixer" in titles
    assert "pdb2pqr" in titles
    assert "Minimization" in titles
    assert titles.index("PDBFixer") < titles.index("pdb2pqr") < titles.index("Minimization")
    assert prep.chk_repair.isChecked()
    assert prep.chk_repair.text() == "Clean up"
    assert prep.chk_protonate.isChecked()
    assert prep.chk_protonate.text() == "Protonate"
    assert prep.chk_rebuild_loops.isChecked()
    assert prep.chk_include_ligand.isChecked()
    assert prep.chk_protonate_ligand.isChecked()
    assert prep.chk_pocket_ligand.isChecked()
    assert prep.chk_keep_ligand.isChecked()
    assert not prep.chk_keep_selected_waters.isChecked()
    assert prep.chk_strip_additives.isChecked()
    assert not prep.chk_keep_metals.isChecked()
    assert prep.chk_skip_long_gaps.isChecked()
    assert prep.spin_max_gap.value() == 8
    assert prep.chk_add_missing_atoms.isChecked()
    assert prep.chk_highest_altloc.isChecked()
    assert prep.chk_minimize.isChecked()
    assert prep.combo_protein_ff.isEnabled()
    assert prep.combo_out_fmt.currentData() == "cif"
    assert prep.combo_protein_ff.currentData() == "amber14"
    assert prep.combo_ligand_ff.currentData() == "none"
    assert prep.combo_ligand_ff.isEnabled()
    assert prep.combo_solvent.currentData() == "gbn2"
    assert prep.combo_openmm_platform.currentData() == "auto"
    assert prep.radio_src_manager.isChecked()
    assert prep.combo_src_manager.count() == 1
    assert "mini.pdb" in prep.combo_src_manager.currentText()
    assert prep.combo_restraint.currentData() == "backbone"
    assert prep.chk_skip_pocket_loops.isChecked()
    assert prep.chk_write_smina.isChecked()
    assert prep.radio_box_loaded.isChecked()
    assert prep.spin_box_padding.value() == 4.0
    prep.radio_box_file.setChecked(True)
    assert prep.box_ligand_file_row.isEnabled()
    assert not prep.combo_box_ligand.isEnabled()
    prep.radio_box_loaded.setChecked(True)
    assert prep.btn_open_smina.text() == "Open Gnina…"
    assert "Write Gnina files" in prep.chk_write_smina.text()
    assert not prep.btn_open_smina.isEnabled()
    assert not prep.chk_keep_bridging_waters.isChecked()
    assert prep.spin_salt.value() == 0.15
    assert prep.spin_ph.value() == 7.4
    assert prep.edit_out.text().endswith("mini_prepared.cif")
    assert prep.chk_minimize.isChecked()
    prep.chk_minimize.setChecked(False)
    assert not prep.combo_protein_ff.isEnabled()
    assert not prep.combo_ligand_ff.isEnabled()
    prep.chk_minimize.setChecked(True)
    assert prep.chk_minimize.isEnabled()
    assert prep.combo_protein_ff.isEnabled()
    assert prep.combo_ligand_ff.isEnabled()
    assert prep.edit_ligand_smiles.isEnabled()
    prep.chk_include_ligand.setChecked(False)
    assert prep.chk_keep_ligand.isChecked()
    assert not prep.chk_keep_ligand.isEnabled()
    assert not prep.combo_ligand_ff.isEnabled()
    assert not prep.edit_ligand_smiles.isEnabled()
    assert not prep.chk_protonate_ligand.isEnabled()
    assert not prep.chk_pocket_ligand.isChecked()
    prep.chk_include_ligand.setChecked(True)
    assert prep.chk_keep_ligand.isChecked()
    assert prep.chk_keep_ligand.isEnabled()
    assert prep.combo_ligand_ff.isEnabled()
    assert prep.chk_protonate_ligand.isEnabled()
    assert prep.chk_pocket_ligand.isChecked()
    prep.chk_repair.setChecked(False)
    assert not prep.chk_rebuild_loops.isEnabled()
    assert not prep.chk_skip_pocket_loops.isEnabled()
    assert not prep.chk_strip_additives.isEnabled()
    assert not prep.chk_highest_altloc.isEnabled()
    assert prep.chk_keep_ligand.isEnabled()
    assert prep.chk_protonate.isChecked()
    prep.chk_repair.setChecked(True)
    assert prep.chk_rebuild_loops.isEnabled()
    assert prep.chk_skip_pocket_loops.isEnabled()
    prep.chk_protonate.setChecked(False)
    assert not prep.spin_ph.isEnabled()
    assert not prep.chk_protonate_ligand.isEnabled()
    assert not prep.chk_pocket_ligand.isChecked()
    assert prep.chk_include_ligand.isEnabled()
    prep.chk_protonate.setChecked(True)
    assert prep.spin_ph.isEnabled()
    assert prep.chk_protonate_ligand.isEnabled()
    assert prep.chk_pocket_ligand.isChecked()
    prep.chk_repair.setChecked(False)
    prep.chk_protonate.setChecked(False)
    prep.chk_minimize.setChecked(False)
    prep.chk_write_smina.setChecked(False)
    shown.clear()
    prep._on_run()
    assert shown
    prep.close()

    dlg.open_pdbfixer_dialog()
    fixer = dlg._pdbfixer_dialog
    from molmanager.ui.dialogs.protein_pdbfixer import ProteinPdbFixerDialog

    assert isinstance(fixer, ProteinPdbFixerDialog)
    assert fixer.windowTitle() == "PDBFixer"
    assert not fixer.findChildren(QTextEdit)
    fixer._append_log("Starting PDBFixer")
    assert "Starting PDBFixer" in dlg.log.toPlainText()
    assert fixer.chk_rebuild_loops.isChecked()
    assert fixer.chk_replace_nonstandard.isChecked()
    assert fixer.chk_include_ligand.isChecked()
    assert fixer.chk_keep_ligand.isChecked()
    assert not fixer.chk_keep_selected_waters.isChecked()
    assert fixer.chk_strip_additives.isChecked()
    assert not fixer.chk_keep_metals.isChecked()
    assert fixer.chk_skip_long_gaps.isChecked()
    assert fixer.spin_max_gap.value() == 8
    assert fixer.combo_out_fmt.currentData() == "cif"
    assert fixer.radio_src_manager.isChecked()
    assert fixer.edit_out.text().endswith("mini_fixed.cif")
    fixer.chk_include_ligand.setChecked(False)
    assert fixer.chk_keep_ligand.isChecked()
    assert not fixer.chk_keep_ligand.isEnabled()
    fixer.chk_include_ligand.setChecked(True)
    assert fixer.chk_keep_ligand.isEnabled()
    fixer.close()

    dlg.open_pdb2pqr_dialog()
    pqr = dlg._pdb2pqr_dialog
    from molmanager.ui.dialogs.protein_pdb2pqr import ProteinPdb2pqrDialog

    assert isinstance(pqr, ProteinPdb2pqrDialog)
    assert pqr.windowTitle() == "pdb2pqr"
    assert not pqr.findChildren(QTextEdit)
    pqr._append_log("Starting pdb2pqr")
    assert "Starting pdb2pqr" in dlg.log.toPlainText()
    assert pqr.chk_include_ligand.isChecked()
    assert pqr.chk_keep_ligand.isChecked()
    assert pqr.chk_protonate_ligand.isChecked()
    assert pqr.chk_pocket_ligand.isChecked()
    assert pqr.chk_keep_water.isChecked()
    assert pqr.spin_ph.value() == 7.4
    assert pqr.combo_out_fmt.currentData() == "cif"
    assert pqr.radio_src_manager.isChecked()
    assert pqr.edit_out.text().endswith("mini_protonated.cif")
    pqr.chk_include_ligand.setChecked(False)
    assert pqr.chk_keep_ligand.isChecked()
    assert not pqr.chk_keep_ligand.isEnabled()
    assert not pqr.chk_protonate_ligand.isEnabled()
    assert not pqr.chk_pocket_ligand.isChecked()
    pqr.chk_include_ligand.setChecked(True)
    assert pqr.chk_keep_ligand.isEnabled()
    assert pqr.chk_protonate_ligand.isEnabled()
    assert pqr.chk_pocket_ligand.isChecked()
    pqr.close()
    dlg.close()


def test_prepare_dialogs_use_manager_or_file_source(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    manager_path = tmp_path / "manager.pdb"
    manager_path.write_text(_ALA_PDB, encoding="utf-8")
    file_path = tmp_path / "from_disk.pdb"
    file_path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(manager_path)
    dlg.open_prepare_dialog()
    prep = dlg._prepare_dialog
    assert prep.radio_src_manager.isChecked()
    _name, text, fmt, path = prep.chosen_structure_source()
    assert path == manager_path
    assert "ALA" in text
    prep.edit_src_file.setText(str(file_path))
    prep.radio_src_file.setChecked(True)
    name, text, fmt, path = prep.chosen_structure_source()
    assert path == file_path
    assert "AXI" in text
    snap = prep._write_input_snapshot()
    assert "AXI" in snap.read_text(encoding="utf-8")
    assert prep.edit_out.text().endswith("from_disk_prepared.cif")
    dlg.open_pdbfixer_dialog()
    fixer = dlg._pdbfixer_dialog
    fixer.edit_src_file.setText(str(file_path))
    fixer.radio_src_file.setChecked(True)
    _n, text, _f, path = fixer.chosen_structure_source()
    assert path == file_path
    assert "AXI" in text
    dlg.open_dock_file_dialog()
    dock = dlg._dock_file_dialog
    dock.edit_src_file.setText(str(file_path))
    dock.radio_src_file.setChecked(True)
    _n, text, _f, path = dock.chosen_structure_source()
    assert path == file_path
    assert "AXI" in text
    assert dock.edit_out.text().endswith("from_disk_smina.pdbqt")
    dlg.close()


@pytest.mark.slow
def test_prepare_protein_structure_ala_optional_extras(tmp_path):
    pytest.importorskip("pdbfixer")
    pytest.importorskip("openmm")
    pytest.importorskip("pdb2pqr")
    req = _request(tmp_path, rebuild_missing_loops=False, minimize=False, ph=7.4)
    out = prepare_protein_structure(req)
    text = Path(out.output_path).read_text(encoding="utf-8")
    assert "data_" in text
    assert "ALA" in text
    from molmanager.protein.structure_components import parse_structure_atoms

    atoms = parse_structure_atoms(text, "cif")
    assert any(a.elem == "H" for a in atoms), "expected pdb2pqr to place hydrogens"


def test_pdb_to_mmcif_keeps_ligand_chem_comp_bonds():
    from molmanager.protein.structure_components import (
        CifChemAtom,
        CifChemBond,
        parse_cif_chem_comp_bonds,
        parse_structure_atoms,
        pdb_to_mmcif,
    )

    atoms = {
        "AXI": (
            CifChemAtom(atom_id="C80", symbol="C"),
            CifChemAtom(atom_id="O81", symbol="O"),
        )
    }
    bonds = {"AXI": (CifChemBond(atom_id_1="C80", atom_id_2="O81", order=2, order_token="doub"),)}
    cif = pdb_to_mmcif(
        _HOLO_PDB,
        data_name="prepared",
        remarks=["KEEP LIGAND"],
        chem_atoms=atoms,
        chem_bonds=bonds,
    )
    assert cif.startswith("data_prepared")
    assert "# KEEP LIGAND" in cif
    assert "_chem_comp_bond.value_order" in cif
    parsed = parse_cif_chem_comp_bonds(cif)
    assert any(b.order == 2 and {b.atom_id_1, b.atom_id_2} == {"C80", "O81"} for b in parsed["AXI"])
    site = parse_structure_atoms(cif, "cif")
    assert any(a.resn == "AXI" for a in site)
    assert any(a.resn == "ALA" for a in site)


_ACETIC_PDB = """\
HETATM    1  C1  ACE A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM    2  C2  ACE A   1       1.520   0.000   0.000  1.00  0.00           C
HETATM    3  O1  ACE A   1       2.160   1.080   0.000  1.00  0.00           O
HETATM    4  O2  ACE A   1       2.160  -1.080   0.000  1.00  0.00           O
END
"""


def _acetic_ensemble_near_ph_7_4():
    from rdkit import Chem

    from molmanager.ionization.unipka_ensembles import LN10, build_ensemble_from_scored

    ha = Chem.MolFromSmiles("CC(=O)O")
    a = Chem.MolFromSmiles("CC(=O)[O-]")
    assert ha is not None and a is not None
    # Equal aqueous weight at pH 7.4: G_HA = G_A − ln(10)·7.4
    return build_ensemble_from_scored(
        [
            (0, "CC(=O)O", ha, 0.0),
            (-1, "CC(=O)[O-]", a, LN10 * 7.4),
        ]
    )


def test_choose_ligand_protomer_aqueous_acetic_acid():
    from rdkit import Chem
    from rdkit.Chem import rdmolops

    from molmanager.workers.protein_prepare_ligand import choose_ligand_protomer

    parent = Chem.MolFromSmiles("CC(=O)O")
    choice = choose_ligand_protomer(parent, ph=7.4, ensemble=_acetic_ensemble_near_ph_7_4())
    assert not choice.used_pocket
    assert rdmolops.GetFormalCharge(choice.mol) in (-1, 0)
    assert "UNIPKA" in choice.remark_line()


def test_pocket_coulomb_prefers_neutral_near_anion():
    from rdkit import Chem
    from rdkit.Chem import rdmolops

    from molmanager.workers.protein_prepare_ligand import choose_ligand_protomer

    parent = Chem.MolFromSmiles("CC(=O)O")
    # Nearby negative charge at the carboxylate should penalize acetate.
    pqr = (
        "ATOM      1  N   ASP A   2       2.160  -1.080   3.000 -1.0000 1.50\n"
        "HETATM    2  C2  ACE A   1       1.520   0.000   0.000  0.0000 1.70\n"
    )
    choice = choose_ligand_protomer(
        parent,
        ph=7.4,
        pdb_block=_ACETIC_PDB,
        pqr_text=pqr,
        ligand_keys={("A", "1", "")},
        ensemble=_acetic_ensemble_near_ph_7_4(),
    )
    assert choice.used_pocket
    assert rdmolops.GetFormalCharge(Chem.MolFromSmiles(choice.smiles)) == 0
    assert choice.pocket_pct is not None and choice.pocket_pct > 50.0


def test_pocket_coulomb_prefers_anion_near_cation():
    from rdkit import Chem
    from rdkit.Chem import rdmolops

    from molmanager.workers.protein_prepare_ligand import choose_ligand_protomer

    parent = Chem.MolFromSmiles("CC(=O)O")
    pqr = "ATOM      1  NH1 ARG A   2       2.160  -1.080   3.000  1.0000 1.50\n"
    choice = choose_ligand_protomer(
        parent,
        ph=7.4,
        pdb_block=_ACETIC_PDB,
        pqr_text=pqr,
        ligand_keys={("A", "1", "")},
        ensemble=_acetic_ensemble_near_ph_7_4(),
    )
    assert choice.used_pocket
    assert rdmolops.GetFormalCharge(Chem.MolFromSmiles(choice.smiles)) == -1


def test_parse_pqr_atoms_and_mol2_roundtrip(tmp_path):
    from molmanager.workers.protein_prepare_ligand import (
        parse_pqr_atoms,
        prepare_ligands_for_gaff,
        write_ligand_mol2,
    )

    atoms = parse_pqr_atoms(
        "ATOM      1  N   MET A   1      27.340  24.430   2.614 -0.3000 1.8500\n"
    )
    assert len(atoms) == 1
    key, name, _x, _y, _z, charge = atoms[0]
    assert key == ("A", "1", "")
    assert name == "N"
    assert charge == pytest.approx(-0.3)

    mols, text = prepare_ligands_for_gaff(_ACETIC_PDB, {("A", "1", "")}, smiles="CC(=O)O")
    assert mols
    path = tmp_path / "lig.mol2"
    write_ligand_mol2(mols[0], path, resn="ACE", resi="1")
    body = path.read_text(encoding="utf-8")
    assert "@<TRIPOS>ATOM" in body
    assert "ACE" in body
    assert "HETATM" in text


def test_prepare_requires_smiles_when_protonating_ligand(tmp_path):
    in_path = tmp_path / "holo.pdb"
    in_path.write_text(_HOLO_PDB, encoding="utf-8")
    req = ProteinPrepareRequest(
        input_path=str(in_path),
        output_pdb_path=str(tmp_path / "out.pdb"),
        include_ligand=True,
        protonate_ligand=True,
        pocket_ligand_protonation=False,
        minimize=False,
    )
    with pytest.raises(RuntimeError, match="SMILES"):
        prepare_protein_structure(req)


_CIF_CARBONYL = """\
data_lig
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_model_num
HETATM 1 C C80 LIG 1 LIG A 0.000 0.000 0.000 1
HETATM 2 O O81 LIG 1 LIG A 1.210 0.000 0.000 1
loop_
_chem_comp_atom.comp_id
_chem_comp_atom.atom_id
_chem_comp_atom.type_symbol
LIG C80 C
LIG O81 O
loop_
_chem_comp_bond.comp_id
_chem_comp_bond.atom_id_1
_chem_comp_bond.atom_id_2
_chem_comp_bond.value_order
LIG C80 O81 doub
"""


def test_prepare_dialog_cif_bonds_count_as_ligand_template(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_prepare_dialog import ProteinPrepareDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "lig.cif"
    path.write_text(_CIF_CARBONYL, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg.open_prepare_dialog()
    prep = dlg._prepare_dialog
    assert isinstance(prep, ProteinPrepareDialog)
    text, fmt = dlg.prepare_source()[1], dlg.prepare_source()[2]
    assert prep._source_has_ligand(text, fmt)
    assert prep._source_has_cif_ligand_bonds(text, fmt)
    prep.close()
    dlg.close()


def test_prepare_dialog_requires_smiles_for_holo_protonation(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.protein_prepare_dialog import ProteinPrepareDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    shown: list[str] = []

    def _info(*_a, **_k):
        shown.append("info")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    dlg.open_prepare_dialog()
    prep = dlg._prepare_dialog
    assert isinstance(prep, ProteinPrepareDialog)
    prep.btn_run.click()
    assert shown
    prep.close()
    dlg.close()


def test_gb_kappa_and_ff_xmls_prefer_gbn2():
    kappa = _gb_kappa_per_nm(salt_m=0.15)
    assert 0.10 < kappa < 0.16
    assert _gb_kappa_per_nm(salt_m=0.0) == 0.0
    xmls = _protein_ff_xmls(keep_water=False, gbsa=True)
    assert xmls[0][-1] == "implicit/gbn2.xml"
    assert "implicit/gbn2.xml" not in _protein_ff_xmls(keep_water=False, gbsa=False)[0]
    ildn = _protein_ff_xmls(keep_water=False, protein_ff="amber99sbildn", solvent="obc2")
    assert ildn[0][0] == "amber99sbildn.xml"
    assert ildn[0][-1] == "implicit/obc2.xml"
    vac = _protein_ff_xmls(keep_water=True, solvent="vacuum")
    assert vac[0] == ("amber14-all.xml", "amber14/tip3pfb.xml")


def test_solvent_label_and_minimize_remark_include_gbsa():
    from molmanager.workers.protein_prepare_runtime import _solvent_label

    assert (
        _solvent_label(("amber14-all.xml", "implicit/gbn2.xml"), used_gb=True, used_salt=True)
        == "GBN2 I=0.15M"
    )
    assert _solvent_label(("amber14-all.xml",), used_gb=False, used_salt=False) == "VACUUM"
    assert (
        _solvent_label(
            ("amber99sbildn.xml", "implicit/obc2.xml"), used_gb=True, used_salt=True, salt_m=0.15
        )
        == "OBC2 I=0.15M"
    )


def test_protein_only_system_tries_gbn2_first(monkeypatch):
    pytest.importorskip("openmm")
    seen: list[tuple[str, ...]] = []

    class _FakeFF:
        def __init__(self, *xmls):
            seen.append(xmls)
            raise ValueError("skip")

    monkeypatch.setattr("openmm.app.ForceField", _FakeFF)
    pdb = MagicMock()
    pdb.topology = MagicMock()
    from molmanager.workers.protein_prepare_runtime import _protein_only_system

    with pytest.raises(RuntimeError, match="could not parameterize"):
        _protein_only_system(pdb, keep_water=False)
    assert seen
    assert "implicit/gbn2.xml" in seen[0]


def test_chem_comp_tables_from_mols_keeps_carbonyl_double():
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import chem_comp_tables_from_mols

    mol = Chem.MolFromSmiles("CC(=O)O")
    assert mol is not None
    mol.SetProp("_Name", "ACE")
    _atoms, bonds = chem_comp_tables_from_mols([mol])
    assert any(bond.order == 2 for bond in bonds["ACE"])


def test_highest_occupancy_altloc_keeps_major_copy():
    from molmanager.workers.protein_prepare_qc import apply_highest_occupancy_altlocs

    pdb = """\
ATOM      1  CA  SER A  10       1.000   0.000   0.000  0.40 20.00           C
ATOM      2  CA ASER A  10       1.100   0.000   0.000  0.60 20.00           C
ATOM      3  CB  SER A  10       2.000   0.000   0.000  1.00 20.00           C
END
"""
    text, notes = apply_highest_occupancy_altlocs(pdb, "pdb")
    assert "CA A" in text
    assert " 0.40 " not in text
    assert any("altlocs" in n for n in notes)


def test_highest_occupancy_altloc_preserves_cif_poly_seq():
    from molmanager.protein.structure_inventory import polymer_sequence_entries
    from molmanager.workers.protein_prepare_qc import (
        apply_highest_occupancy_altlocs,
        apply_sequence_missing_residues,
    )

    kept, notes = apply_highest_occupancy_altlocs(_GAP_CIF, "cif")
    assert notes == ()
    assert "_pdbx_poly_seq_scheme." in kept
    assert polymer_sequence_entries(kept, "cif")["A"][1] == ("ALA", "15", "", False)

    rewritten, alt_notes = apply_highest_occupancy_altlocs(_GAP_CIF_ALTLOC, "cif")
    assert any("altlocs" in note for note in alt_notes)
    assert "0.40" not in rewritten
    assert "_pdbx_poly_seq_scheme." in rewritten
    fixer = _mock_gap_fixer()
    assert apply_sequence_missing_residues(fixer, rewritten, "cif") == 1
    assert fixer.missingResidues[(0, 1)] == ["ALA"]


@pytest.mark.slow
def test_4agc_cif_sequence_gaps_survive_altloc_pass():
    from pathlib import Path

    from molmanager.workers.protein_prepare_qc import (
        apply_highest_occupancy_altlocs,
        apply_sequence_missing_residues,
    )

    path = Path("samples/4AGC.cif")
    if not path.is_file():
        pytest.skip("samples/4AGC.cif is not present")
    pytest.importorskip("pdbfixer")
    pytest.importorskip("openmm")
    from molmanager.workers.protein_prepare_io import _open_fixer_from_text

    raw = path.read_text(encoding="utf-8")
    rewritten, _notes = apply_highest_occupancy_altlocs(raw, "cif")
    fixer = _open_fixer_from_text(rewritten, "cif")
    fixer.findMissingResidues()
    n_added = apply_sequence_missing_residues(fixer, rewritten, "cif")
    assert n_added == 48
    assert fixer.missingResidues[(0, 0)][0] == "MET"
    assert len(fixer.missingResidues[(0, 0)]) == 32


def test_bridging_water_keys_near_ligand():
    from molmanager.workers.protein_prepare_qc import bridging_water_keys

    pdb = """\
HETATM    1  C1  LIG A   1       0.000   0.000   0.000  1.00 10.00           C
HETATM    2  O   HOH A   2       2.000   0.000   0.000  0.90 15.00           O
HETATM    3  O   HOH A   3      20.000   0.000   0.000  1.00 15.00           O
END
"""
    keys = bridging_water_keys(pdb, "pdb", {("A", "1", "")})
    assert ("A", "2", "") in keys
    assert ("A", "3", "") not in keys


def test_pocket_titration_remarks_lists_nearby_his():
    from molmanager.workers.protein_prepare_qc import pocket_titration_remarks

    pdb = """\
ATOM      1  CA  HID A  10       1.000   0.000   0.000  1.00 20.00           C
ATOM      2  CA  ALA A  50      40.000   0.000   0.000  1.00 20.00           C
HETATM  100  C1  LIG A  99       1.200   0.200   0.000  1.00 20.00           C
END
"""
    rows = pocket_titration_remarks(pdb, "pdb", pdb, "pdb", {("A", "99", "")})
    assert any("HID10" in row for row in rows)
    assert not any("ALA50" in row for row in rows)


def test_restrain_atom_backbone_and_ligand():
    from types import SimpleNamespace

    from molmanager.workers.protein_prepare_qc import restrain_atom

    chain = SimpleNamespace(id="A")
    ala = SimpleNamespace(name="ALA", id="10", insertionCode="", chain=chain)
    lig = SimpleNamespace(name="LIG", id="99", insertionCode="", chain=chain)
    ca = SimpleNamespace(name="CA", residue=ala, element=SimpleNamespace(symbol="C"))
    cb = SimpleNamespace(name="CB", residue=ala, element=SimpleNamespace(symbol="C"))
    lig_c = SimpleNamespace(name="C1", residue=lig, element=SimpleNamespace(symbol="C"))
    orig = {("A", "10", "")}
    lig_keys = {("A", "99", "")}
    assert restrain_atom(ca, scheme="backbone", original_keys=orig, ligand_keys=lig_keys)
    assert not restrain_atom(cb, scheme="backbone", original_keys=orig, ligand_keys=lig_keys)
    assert restrain_atom(lig_c, scheme="backbone_ligand", original_keys=orig, ligand_keys=lig_keys)
    assert not restrain_atom(lig_c, scheme="backbone", original_keys=orig, ligand_keys=lig_keys)
    assert restrain_atom(ca, scheme="ca", original_keys=orig, ligand_keys=lig_keys)
    assert not restrain_atom(cb, scheme="ca", original_keys=orig, ligand_keys=lig_keys)


def test_prepare_dialog_enables_open_smina_without_receptor(qapp):  # noqa: ARG001
    from molmanager.docking.search_box import DockingBox
    from molmanager.ui.dialogs.protein_prepare import ProteinPrepareDialog
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    dlg = ProteinPrepareDialog(None)
    dlg.show()
    assert not dlg.btn_open_smina.isEnabled()
    result = ProteinPrepareResult(
        output_path="out.cif",
        ligand_pdb="lig.pdb",
        box=DockingBox(0.0, 0.0, 0.0, 10.0, 10.0, 10.0, padding=4.0),
        warning="No module named 'gemmi'",
    )
    dlg._on_finished(result)
    assert dlg.btn_open_smina.isEnabled()
    assert dlg._smina_result is result
    assert dlg.isVisible() is False
    dlg.close()


def test_prepare_tool_dialogs_close_after_finished(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    monkeypatch.setattr(ProteinViewerDialog, "_overlay_prepared_path", lambda *a, **k: None)
    monkeypatch.setattr(ProteinViewerDialog, "_on_structure_minimized", lambda *a, **k: None)
    monkeypatch.setattr(ProteinViewerDialog, "_on_smina_prepared", lambda *a, **k: None)

    out = tmp_path / "done.pdb"
    out.write_text("ATOM\n", encoding="utf-8")
    viewer = ProteinViewerDialog()
    viewer.open_prepare_dialog()
    prep = viewer._prepare_dialog
    assert prep.isVisible()
    prep._on_finished(str(out))
    assert prep.isVisible() is False

    viewer.open_pdbfixer_dialog()
    fixer = viewer._pdbfixer_dialog
    assert fixer.isVisible()
    fixer._on_finished(str(out))
    assert fixer.isVisible() is False

    viewer.open_pdb2pqr_dialog()
    pqr = viewer._pdb2pqr_dialog
    assert pqr.isVisible()
    pqr._on_finished(str(out))
    assert pqr.isVisible() is False

    viewer.open_minimize_dialog()
    mini = viewer._minimize_dialog
    assert mini.isVisible()
    mini._on_finished(str(out))
    assert mini.isVisible() is False
    viewer.close()


def test_dock_file_dialog_defaults_and_auto_open_smina(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from types import SimpleNamespace

    from PyQt5.QtWidgets import QMessageBox

    from molmanager.docking.search_box import DockingBox
    from molmanager.ui.dialogs.protein_dock_file import ProteinDockFileDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog
    from molmanager.workers.protein_prepare_smina import ProteinPrepareResult

    dlg = ProteinViewerDialog()
    shown: list[str] = []

    def _info(*_a, **_k):
        shown.append("info")
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    dlg.open_dock_file_dialog()
    assert not shown
    empty = dlg._dock_file_dialog
    assert empty.radio_src_file.isChecked()

    path = tmp_path / "holo.pdb"
    path.write_text(_HOLO_PDB, encoding="utf-8")
    dlg.load_structure_path(path)
    dlg.open_dock_file_dialog()
    dock = dlg._dock_file_dialog
    assert isinstance(dock, ProteinDockFileDialog)
    assert dock.radio_src_manager.isChecked()
    assert dock.edit_out.text().endswith("holo_smina.pdbqt")
    dock.edit_out.setText(str(tmp_path / "holo_smina.cif"))
    assert dock._receptor_output_path().endswith("holo_smina.pdbqt")
    dock.edit_out.setText(str(tmp_path / "holo_smina.pdbqt"))
    assert dock.spin_box_padding.value() == 4.0
    assert dock.combo_box_ligand.count() >= 1
    assert dock.btn_open_smina.text() == "Open Gnina…"
    assert not dock.btn_open_smina.isEnabled()
    dock._append_log("Starting Dock File: Gnina files")
    assert "Starting Dock File" in dlg.log.toPlainText()

    applied: list[object] = []
    filled: list[str] = []

    class _Edit:
        def setText(self, text):
            filled.append(str(text))

        def text(self):
            return filled[-1] if filled else ""

    fake = SimpleNamespace(
        apply_prepare_result=lambda r: applied.append(r),
        edit_receptor=_Edit(),
    )
    dock._process_host = lambda: SimpleNamespace(open_gnina_dock=lambda: fake)
    rec = tmp_path / "rec.pdbqt"
    rec.write_text("ATOM\n", encoding="utf-8")
    ghost = ProteinPrepareResult(
        output_path=str(tmp_path / "missing_smina.pdbqt"),
        ligand_pdb="lig.pdb",
        box=DockingBox(1.0, 2.0, 3.0, 10.0, 11.0, 12.0, padding=4.0),
        warning="unable to build rdkit mol for residue GLU corresponding to key A:913",
    )
    dock._on_finished(ghost)
    assert applied == []
    assert filled == []
    assert not dock.btn_open_smina.isEnabled()
    assert "Receptor PDBQT was not written" in dlg.log.toPlainText()
    assert dock.isVisible()

    result = ProteinPrepareResult(
        output_path=str(tmp_path / "holo_smina.pdbqt"),
        receptor_pdbqt=str(rec),
        ligand_sdf="lig.sdf",
        ligand_pdb="lig.pdb",
        box=DockingBox(1.0, 2.0, 3.0, 10.0, 11.0, 12.0, padding=4.0),
    )
    dock._on_finished(result)
    assert applied == [result]
    assert filled == [str(rec)]
    assert dock.btn_open_smina.isEnabled()
    assert "Receptor PDBQT" in dlg.log.toPlainText()
    assert dock.isVisible() is False
    dock.close()
    dlg.close()
