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

"""Strain energy of conformers relative to a reference."""

from __future__ import annotations

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.workers import (
    ConformerGenParams,
    StrainEnergyParams,
    run_conformer_generation,
    run_strain_energy,
    strain_overlay_for_mol,
    strain_overlay_for_mols,
)
from molmanager.workers.strain_energy import single_point_energy_kcal


def test_single_point_energy_kcal_mmff_and_uff():
    mol = Chem.AddHs(Chem.MolFromSmiles("CCO"))
    assert mol is not None
    assert AllChem.EmbedMolecule(mol, randomSeed=7) == 0
    mmff = single_point_energy_kcal(mol, "MMFF")
    uff = single_point_energy_kcal(mol, "UFF")
    assert mmff is not None and uff is not None
    assert mmff != uff


def test_single_point_energy_kcal_invalid_valence_returns_none():
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
    bad = edited.GetMol()
    assert single_point_energy_kcal(bad, "UFF") is None
    assert single_point_energy_kcal(bad, "MMFF") is None


def test_run_strain_energy_relative_to_reference():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=5,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=21,
            prune_rms_threshold=-1.0,
            max_iterations=80,
        ),
    )
    assert out is not None and meta.get("ok") is True
    assert out.GetNumConformers() >= 2

    row, smeta = run_strain_energy(out, StrainEnergyParams(reference_conformer_index=0))
    assert row is not None and smeta.get("ok") is True
    assert smeta.get("ff") in ("MMFF", "UFF")
    strains = [float(x) for x in row["Strain_energies"].split(";")]
    assert len(strains) == out.GetNumConformers()
    assert abs(strains[0]) < 1e-6
    assert float(row["Strain_max"]) == max(strains)
    assert float(row["E_ref"]) == float(smeta["e_ref_kcal"])
    assert len(smeta.get("energies") or []) == len(strains)
    assert len(smeta.get("strains") or []) == len(strains)
    assert abs(float(smeta["energies"][0]) - float(smeta["e_ref_kcal"])) < 1e-6

    row2, smeta2 = run_strain_energy(out, StrainEnergyParams(reference_conformer_index=1))
    assert row2 is not None and smeta2.get("ok") is True
    strains2 = [float(x) for x in row2["Strain_energies"].split(";")]
    assert abs(strains2[1]) < 1e-6


def test_run_strain_energy_clamps_reference_index():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="UFF",
            random_seed=7,
            prune_rms_threshold=-1.0,
            max_iterations=60,
        ),
    )
    assert out is not None and meta.get("ok") is True
    row, smeta = run_strain_energy(
        out, StrainEnergyParams(reference_conformer_index=999, force_field="UFF")
    )
    assert row is not None and smeta.get("ok") is True
    assert smeta.get("ref_clamped") is True
    strains = [float(x) for x in row["Strain_energies"].split(";")]
    assert abs(strains[-1]) < 1e-6


def test_run_strain_energy_reports_min_delta_population_and_other_ffs():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=21,
            prune_rms_threshold=-1.0,
            max_iterations=80,
        ),
    )
    assert out is not None and meta.get("ok") is True
    row, smeta = run_strain_energy(out, StrainEnergyParams(reference_conformer_index=0))
    assert row is not None and smeta.get("ok") is True
    energies = [float(x) for x in smeta["energies"]]
    deltas_min = [float(x) for x in smeta["deltas_min"]]
    pops = [float(x) for x in smeta["pop_fracs"]]
    assert abs(min(deltas_min)) < 1e-6
    assert abs(float(smeta["e_min_kcal"]) - min(energies)) < 1e-6
    assert abs(sum(pops) - 1.0) < 1e-5
    by_ff = smeta.get("energies_by_ff") or {}
    assert smeta["ff"] in by_ff
    assert len(by_ff[smeta["ff"]]) == len(energies)
    assert "UFF" in by_ff or smeta["ff"] == "UFF"


def test_run_strain_energy_mmff94s():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=3,
            prune_rms_threshold=-1.0,
            max_iterations=60,
        ),
    )
    assert out is not None and meta.get("ok") is True
    _row, smeta = run_strain_energy(out, StrainEnergyParams(force_field="MMFF94s"))
    assert smeta.get("ok") is True
    assert smeta.get("ff") in ("MMFF94s", "UFF")


def test_strain_overlay_for_mol_includes_rmsd():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=4,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=11,
            prune_rms_threshold=-1.0,
            max_iterations=60,
        ),
    )
    assert out is not None and meta.get("ok") is True
    overlay = strain_overlay_for_mol(out, StrainEnergyParams(reference_conformer_index=0))
    assert overlay is not None
    n = out.GetNumConformers()
    assert len(overlay["energies"]) == n
    assert len(overlay["deltas"]) == n
    assert overlay.get("rmsds") is not None
    assert len(overlay["rmsds"]) == n
    assert overlay["rmsds"][0] == 0.0


def test_strain_overlay_for_mols_matches_single_mol():
    m = Chem.MolFromSmiles("CCO")
    out, meta = run_conformer_generation(
        m,
        ConformerGenParams(
            num_confs=3,
            energy_window_kcal=100.0,
            force_field="MMFF",
            random_seed=12,
            prune_rms_threshold=-1.0,
            max_iterations=60,
        ),
    )
    assert out is not None and meta.get("ok") is True
    a = strain_overlay_for_mol(out)
    b = strain_overlay_for_mols([out])
    assert a is not None and b is not None
    assert a["energies"] == b["energies"]
