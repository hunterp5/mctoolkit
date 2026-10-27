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

"""Most central ring decomposition: fused systems stay whole, side chains become R groups."""

from __future__ import annotations

import random

from rdkit import Chem

from molmanager.analysis.design_studio import assemble_rgroup_product
from molmanager.chem.central_ring_decomposition import decompose_central_ring
from molmanager.workers.rgroup_decomposition import _assemble_table_rows, _collect_rg_columns


def _mol(smiles: str) -> Chem.Mol:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def _canonical(smiles: str) -> str:
    return Chem.MolToSmiles(Chem.RemoveHs(_mol(smiles)), canonical=True)


def _heavy(smiles: str) -> int:
    return sum(1 for atom in _mol(smiles).GetAtoms() if atom.GetAtomicNum() > 0)


def _ring_heavy_atoms(smiles: str) -> int:
    mol = _mol(smiles)
    Chem.GetSymmSSSR(mol)
    atoms: set[int] = set()
    for ring in mol.GetRingInfo().AtomRings():
        atoms.update(int(index) for index in ring)
    return len(atoms)


def _r_keys(result: dict[str, str]) -> list[str]:
    return [key for key in result if key.startswith("R")]


def _rebuild(result: dict[str, str]) -> str:
    combined = Chem.MolFromSmiles(result["Core"])
    assert combined is not None
    for key in _r_keys(result):
        piece = Chem.MolFromSmiles(result[key])
        assert piece is not None
        combined = Chem.CombineMols(combined, piece)
    zipped = Chem.molzip(combined)
    assert zipped is not None
    Chem.SanitizeMol(zipped)
    return Chem.MolToSmiles(Chem.RemoveHs(zipped), canonical=True)


def _require(smiles: str) -> dict[str, str]:
    result = decompose_central_ring(_mol(smiles))
    assert result is not None
    assert _rebuild(result) == _canonical(smiles)
    return result


def test_toluene_core_zips_back_to_the_same_molecule():
    result = _require("Cc1ccccc1")
    assert _heavy(result["Core"]) == 6
    assert _r_keys(result) == ["R1"]
    assert "*" in result["Core"] and "*" in result["R1"]
    assert assemble_rgroup_product(result["Core"], [("R1", result["R1"])]) == _canonical(
        "Cc1ccccc1"
    )


def test_fused_ring_stays_in_the_core():
    smiles = "Cc1ccc2ccccc2c1"
    result = _require(smiles)
    assert _heavy(result["Core"]) == _ring_heavy_atoms(smiles) == 10
    assert _r_keys(result) == ["R1"]


def test_pendant_ring_is_a_substituent_of_the_fused_system():
    smiles = "c1ccc(-c2ccc3ccccc3c2)cc1"
    result = _require(smiles)
    assert _heavy(result["Core"]) == 10
    assert _r_keys(result) == ["R1"]


def test_biaryl_bond_does_not_fuse_the_central_ring():
    smiles = "c1ccccc1c2ccc(CCCCCCCC)cc2"
    result = _require(smiles)
    assert _heavy(result["Core"]) == 6
    assert _r_keys(result) == ["R1", "R2"]


def test_bridged_and_spiro_systems_stay_whole():
    for smiles in ("CC1CC2CCC1C2", "CC1CCC2(C1)CCCCC2"):
        result = _require(smiles)
        assert _heavy(result["Core"]) == _ring_heavy_atoms(smiles)
        assert _r_keys(result) == ["R1"]


def test_two_substituents_on_one_ring_atom_are_separate_r_groups():
    result = _require("CC1(C)CCCCC1")
    assert _r_keys(result) == ["R1", "R2"]
    assert _heavy(result["R1"]) == 1
    assert _heavy(result["R2"]) == 1


def test_a_side_chain_stays_one_r_group():
    result = _require("CC(C)c1ccccc1")
    assert _r_keys(result) == ["R1"]
    assert _heavy(result["R1"]) == 3


def test_exocyclic_double_bond_is_preserved():
    result = _require("O=C1CCCCC1")
    assert _r_keys(result) == ["R1"]
    assert "=" in result["R1"] or "=" in result["Core"]


def test_chiral_side_chain_round_trips():
    _require("C[C@H](O)c1ccccc1")


def test_other_ring_across_a_linker_is_an_r_group():
    result = _require("c1ccccc1CCc2ccccc2")
    assert _heavy(result["Core"]) == 6
    assert _r_keys(result) == ["R1"]
    substituent = Chem.MolFromSmiles(result["R1"])
    assert substituent is not None
    Chem.GetSymmSSSR(substituent)
    assert substituent.GetRingInfo().NumRings() >= 1


def test_benzene_has_a_core_and_no_r_groups():
    result = _require("c1ccccc1")
    assert result == {"Core": "c1ccccc1"}


def test_acyclic_molecules_have_no_core():
    assert decompose_central_ring(_mol("CCO")) is None


def test_disconnected_fragment_is_not_an_r_group():
    result = decompose_central_ring(_mol("c1ccccc1.Cl"))
    assert result == {"Core": "c1ccccc1"}


def test_explicit_hydrogens_match_the_implicit_molecule():
    bare = _mol("Cc1cc2ccccc2n1C")
    explicit = Chem.AddHs(bare)
    assert decompose_central_ring(explicit) == decompose_central_ring(bare)


def test_labels_do_not_depend_on_input_atom_order():
    mol = _mol("Cc1cc2ccccc2n1C")
    original = decompose_central_ring(mol)
    assert original is not None
    assert _heavy(original["Core"]) == _ring_heavy_atoms("Cc1cc2ccccc2n1C")
    for seed in range(8):
        order = list(range(mol.GetNumAtoms()))
        random.Random(seed).shuffle(order)
        assert decompose_central_ring(Chem.RenumberAtoms(mol, order)) == original


def test_acyclic_rows_are_marked_na_beside_a_matched_core():
    toluene = decompose_central_ring(_mol("Cc1ccccc1"))
    assert toluene is not None
    columns = _collect_rg_columns([toluene])
    rows = _assemble_table_rows([10, 11], [toluene], [1], columns, "MCR")
    assert rows[0][1]["MCR_Core"] == toluene["Core"]
    assert rows[0][1]["MCR_R1"] == toluene["R1"]
    assert rows[1] == (11, {"MCR_Core": "N/A", "MCR_R1": "N/A"})


def test_central_ring_dialog_defaults(qapp):  # noqa: ARG001
    from molmanager.ui.dialogs.fragment_decomposition import CentralRingDecompositionDialog

    dialog = CentralRingDecompositionDialog(["Structure"], 0)
    params = dialog.params()
    assert params.structure_source == "Structure"
    assert params.column_prefix == "MCR"
    assert dialog.only_selected_rows() is False
    assert dialog.windowTitle() == "Most Central Ring Decomposition"


def test_worker_writes_prefixed_columns(qapp):  # noqa: ARG001
    from molmanager.workers.central_ring_decomposition import CentralRingDecompositionWorker

    class _Emit:
        def __init__(self) -> None:
            self.calls: list[tuple] = []

        def emit(self, *args) -> None:
            self.calls.append(args)

    class _Signals:
        def __init__(self) -> None:
            self.fragment_decomp_finished = _Emit()
            self.fragment_decomp_failed = _Emit()
            self.tool_progress = _Emit()

    signals = _Signals()
    worker = CentralRingDecompositionWorker(
        [(7, _mol("Cc1ccccc1")), (8, _mol("CCO"))],
        "MCR",
        "Most Central Ring Decomposition",
        signals,  # type: ignore[arg-type]
    )
    worker.run()
    assert signals.fragment_decomp_failed.calls == []
    rows, headers, title = signals.fragment_decomp_finished.calls[0]
    assert title == "Most Central Ring Decomposition"
    assert headers[:2] == ["MCR_Core", "MCR_R1"]
    by_oid = {oid: row for oid, row in rows}
    assert by_oid[7]["MCR_Core"] != "N/A"
    assert by_oid[8] == {"MCR_Core": "N/A", "MCR_R1": "N/A"}
