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

"""GFN2-xTB HOMO/LUMO descriptor parsing, wiring, and the optional engine."""

from __future__ import annotations

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.conformers.conformer_column_codec import mol_has_3d_coordinates
from molmanager.descriptors.catalog import descriptor_tab_items
from molmanager.descriptors.descriptors_3d import mol_for_3d_descriptors
from molmanager.descriptors.orbitals import (
    _HARTREE_EV,
    clear_orbital_cache,
    gfn2_available,
    int_fns_need_orbitals,
    mol_for_orbital_single_point,
    orbital_energies_ev,
    parse_xtb_orbital_output,
)
from molmanager.workers.chemistry_descriptors import _calc_descriptor_row_values

_XTB_STDOUT = """
          #    Occupation            Energy/Eh            Energy/eV
       -------------------------------------------------------------
          1        2.0000           -19.0000000000         -516.9999
          2        2.0000            -0.3800000000          -10.3403 (HOMO)
          3        0.0000             0.0500000000            1.3606 (LUMO)
       -------------------------------------------------------------
                HL-Gap            0.4300000000 Eh            11.7009 eV
"""


def _water_3d():
    mol = Chem.AddHs(Chem.MolFromSmiles("O"))
    assert AllChem.EmbedMolecule(mol, randomSeed=1) == 0
    AllChem.UFFOptimizeMolecule(mol)
    work = mol_for_3d_descriptors(mol)
    assert work is not None
    return work


def test_parse_xtb_stdout_homo_lumo_and_gap():
    parsed = parse_xtb_orbital_output(_XTB_STDOUT)
    assert parsed is not None
    assert parsed["HOMO"] == pytest.approx(-10.3403)
    assert parsed["LUMO"] == pytest.approx(1.3606)
    assert parsed["HOMO_LUMO_GAP"] == pytest.approx(parsed["LUMO"] - parsed["HOMO"])


def test_parse_xtb_json_hartree_orbitals():
    payload = {
        "orbital energies / Eh": [-0.5, -0.2, 0.1],
        "fractional occupation": [2.0, 2.0, 0.0],
    }
    parsed = parse_xtb_orbital_output("no markers", payload)
    assert parsed is not None
    assert parsed["HOMO"] == pytest.approx(-0.2 * _HARTREE_EV)
    assert parsed["LUMO"] == pytest.approx(0.1 * _HARTREE_EV)
    assert parsed["HOMO_LUMO_GAP"] == pytest.approx(parsed["LUMO"] - parsed["HOMO"])


def test_parse_xtb_output_without_orbitals_is_none():
    assert parse_xtb_orbital_output("SCF failed\n") is None
    assert parse_xtb_orbital_output("", {"total energy": -1.0}) is None


def test_orbital_keys_are_on_the_electronic_tab():
    keys = {key for _disp, key in descriptor_tab_items("Electronic")}
    assert {"HOMO", "LUMO", "HOMO_LUMO_GAP"} <= keys
    assert int_fns_need_orbitals(("MolWt", "HOMO"))
    assert not int_fns_need_orbitals(("MolLogP",))


def test_orbital_row_embeds_a_2d_structure(monkeypatch):
    seen: dict[str, object] = {}

    def _energies(mol):
        seen["atoms"] = mol.GetNumAtoms()
        seen["is_3d"] = mol_has_3d_coordinates(mol)
        return {"HOMO": -9.0, "LUMO": -0.5, "HOMO_LUMO_GAP": 8.5}

    monkeypatch.setattr(
        "molmanager.workers.chemistry_descriptors.orbital_energies_ev",
        _energies,
    )
    _idx, row = _calc_descriptor_row_values(
        1,
        Chem.MolFromSmiles("CCO"),
        ["HOMO (eV)", "LUMO (eV)", "HOMO-LUMO gap (eV)", "Mol Weight"],
        ("HOMO", "LUMO", "HOMO_LUMO_GAP", "MolWt"),
        {},
        pka_states=None,
        pka_cache_used=False,
    )
    assert seen["is_3d"] is True
    assert int(seen["atoms"]) > 3
    assert row["HOMO (eV)"] == "-9.000"
    assert row["LUMO (eV)"] == "-0.500"
    assert row["HOMO-LUMO gap (eV)"] == "8.500"
    assert float(row["Mol Weight"]) > 0.0


def test_orbital_row_is_na_when_embedding_fails(monkeypatch):
    monkeypatch.setattr(
        "molmanager.descriptors.orbitals.embed_conformer_for_orbitals",
        lambda _mol: None,
    )
    _idx, row = _calc_descriptor_row_values(
        2,
        Chem.MolFromSmiles("CCO"),
        ["HOMO (eV)", "Mol Weight"],
        ("HOMO", "MolWt"),
        {},
        pka_states=None,
        pka_cache_used=False,
    )
    assert row["HOMO (eV)"] == "N/A"
    assert float(row["Mol Weight"]) > 0.0


def test_orbital_row_uses_one_single_point(monkeypatch):
    calls = {"n": 0}

    def _energies(_mol):
        calls["n"] += 1
        return {"HOMO": -9.5, "LUMO": -0.25, "HOMO_LUMO_GAP": 9.25}

    monkeypatch.setattr(
        "molmanager.workers.chemistry_descriptors.orbital_energies_ev",
        _energies,
    )
    _idx, row = _calc_descriptor_row_values(
        4,
        Chem.MolFromSmiles("CCO"),
        ["HOMO (eV)", "LUMO (eV)", "HOMO-LUMO gap (eV)"],
        ("HOMO", "LUMO", "HOMO_LUMO_GAP"),
        {},
        pka_states=None,
        pka_cache_used=False,
        mol_3d=_water_3d(),
    )
    assert calls["n"] == 1
    assert row["HOMO (eV)"] == "-9.500"
    assert row["LUMO (eV)"] == "-0.250"
    assert row["HOMO-LUMO gap (eV)"] == "9.250"


def test_odd_electron_and_implicit_hydrogen_skip_the_engine(monkeypatch):
    def _boom(*_args, **_kwargs):
        raise AssertionError("xtb should not run")

    monkeypatch.setattr("molmanager.descriptors.orbitals._run_xtb", _boom)
    monkeypatch.setattr(
        "molmanager.descriptors.orbitals.resolve_xtb_executable", lambda *_a, **_k: "xtb"
    )
    clear_orbital_cache()
    radical = Chem.AddHs(Chem.MolFromSmiles("[CH3]"))
    assert AllChem.EmbedMolecule(radical, randomSeed=1) == 0
    assert orbital_energies_ev(radical) is None
    implicit = Chem.MolFromSmiles("O")
    assert AllChem.EmbedMolecule(implicit, randomSeed=1) == 0
    assert orbital_energies_ev(implicit) is None


def test_xtb_cli_parses_stdout_and_caches(monkeypatch):
    calls = {"n": 0}

    class _Proc:
        returncode = 0
        stdout = _XTB_STDOUT
        stderr = ""

    def _run(argv, *, cwd, timeout):
        calls["n"] += 1
        assert argv[1:] == ["mol.xyz", "--gfn", "2", "--chrg", "0", "--uhf", "0", "--norestart"]
        assert timeout > 0
        assert cwd
        return _Proc()

    monkeypatch.setattr(
        "molmanager.descriptors.orbitals.resolve_xtb_executable", lambda *_a, **_k: "xtb"
    )
    monkeypatch.setattr("molmanager.descriptors.orbitals._run_xtb", _run)
    clear_orbital_cache()
    mol = _water_3d()
    first = orbital_energies_ev(mol)
    second = orbital_energies_ev(mol)
    assert calls["n"] == 1
    assert first == second
    assert first is not None
    assert first["HOMO"] == pytest.approx(-10.3403)


def test_missing_engine_returns_none(monkeypatch):
    monkeypatch.setattr(
        "molmanager.descriptors.orbitals.resolve_xtb_executable", lambda *_a, **_k: None
    )
    monkeypatch.setattr("molmanager.descriptors.orbitals.tblite_available", lambda: False)
    clear_orbital_cache()
    assert orbital_energies_ev(_water_3d()) is None
    assert gfn2_available() is False


def _use_installed_xtb_in_this_test() -> None:
    """Point the isolated test settings at a local xtb.exe when one is installed."""
    import os
    from pathlib import Path

    from molmanager.platform_support.tool_paths import TOOL_XTB, save_tool_path

    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        installed = Path(local) / "MolManager" / "xtb" / "xtb-6.7.1" / "bin" / "xtb.exe"
        if installed.is_file():
            save_tool_path(TOOL_XTB, str(installed))
            return
    if not gfn2_available():
        pytest.skip("xtb or tblite is not installed")


def test_water_gfn2_frontier_orbitals_are_finite():
    _use_installed_xtb_in_this_test()
    clear_orbital_cache()
    parsed = orbital_energies_ev(_water_3d())
    assert parsed is not None
    assert parsed["HOMO"] < -5.0
    assert parsed["LUMO"] > parsed["HOMO"]
    assert parsed["HOMO_LUMO_GAP"] == pytest.approx(parsed["LUMO"] - parsed["HOMO"])
    assert 2.0 < parsed["HOMO_LUMO_GAP"] < 30.0


def test_dummy_congeneric_sdf_embeds_without_stored_conformers():
    """The sample series is a 2D drawing. Orbital jobs must still build a pose."""
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "samples" / "dummy_congeneric.sdf"
    mols = [mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol is not None]
    assert len(mols) >= 10
    for mol in mols:
        assert mol_for_3d_descriptors(mol) is None
        posed = mol_for_orbital_single_point(mol)
        assert posed is not None
        assert mol_has_3d_coordinates(posed)
        assert all(atom.GetNumImplicitHs() == 0 for atom in posed.GetAtoms())


def test_dummy_congeneric_sdf_orbitals_are_finite():
    _use_installed_xtb_in_this_test()
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "samples" / "dummy_congeneric.sdf"
    clear_orbital_cache()
    failures: list[str] = []
    for mol in Chem.SDMolSupplier(str(path), removeHs=False):
        if mol is None:
            failures.append("unparsed record")
            continue
        name = mol.GetProp("ID") if mol.HasProp("ID") else "?"
        energies = orbital_energies_ev(mol_for_orbital_single_point(mol))
        if energies is None or not (energies["HOMO"] < energies["LUMO"]):
            failures.append(name)
    assert failures == []
