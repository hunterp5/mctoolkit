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

"""Bemis–Murcko scaffold columns and the Scaffolds descriptor tab."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.murcko import (
    apply_murcko_scaffold_counts,
    murcko_framework_smiles,
    murcko_ring_systems_smiles,
    murcko_scaffold_smiles,
)
from molmanager.ui.dialogs.properties import PropertyDialog
from molmanager.workers.chemistry_descriptors import CalcDescriptorsRequest, CalcWorker
from molmanager.workers.signals import WorkerSignals


def _mol(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_toluene_shares_benzene_scaffold_and_framework() -> None:
    benzene = _mol("c1ccccc1")
    toluene = _mol("Cc1ccccc1")
    pyridine = _mol("n1ccccc1")
    assert murcko_scaffold_smiles(toluene) == murcko_scaffold_smiles(benzene) == "c1ccccc1"
    assert murcko_scaffold_smiles(pyridine) == "c1ccncc1"
    assert murcko_framework_smiles(benzene) == murcko_framework_smiles(pyridine) == "C1CCCCC1"
    assert murcko_ring_systems_smiles(toluene) == "c1ccccc1"


def test_acyclic_scaffold_is_blank() -> None:
    ethanol = _mol("CCO")
    assert murcko_scaffold_smiles(ethanol) == ""
    assert murcko_framework_smiles(ethanol) == ""
    assert murcko_ring_systems_smiles(ethanol) == ""


def test_biphenyl_ring_systems_drop_the_biaryl_bond() -> None:
    biphenyl = _mol("c1ccc(-c2ccccc2)cc1")
    assert murcko_scaffold_smiles(biphenyl) == "c1ccc(-c2ccccc2)cc1"
    assert murcko_ring_systems_smiles(biphenyl) == "c1ccccc1.c1ccccc1"


def test_scaffold_count_groups_the_run_and_skips_missing_structures() -> None:
    prepared = [
        (1, _mol("c1ccccc1")),
        (2, _mol("Cc1ccccc1")),
        (3, _mol("CCO")),
        (4, None),
    ]
    results = [
        (1, {"Murcko scaffold": "c1ccccc1", "Scaffold count": ""}),
        (2, {"Murcko scaffold": "c1ccccc1", "Scaffold count": ""}),
        (3, {"Murcko scaffold": "", "Scaffold count": ""}),
        (4, {"Murcko scaffold": "N/A", "Scaffold count": "N/A"}),
    ]
    filled = apply_murcko_scaffold_counts(
        results,
        prepared,
        ["Murcko scaffold", "Scaffold count"],
        ["MURCKO_SCAFFOLD", "MURCKO_COUNT"],
    )
    by_oid = {oid: row for oid, row in filled}
    assert by_oid[1]["Scaffold count"] == "2"
    assert by_oid[2]["Scaffold count"] == "2"
    assert by_oid[3]["Scaffold count"] == "0"
    assert by_oid[4]["Scaffold count"] == "N/A"
    assert by_oid[1]["Murcko scaffold"] == "c1ccccc1"


def test_descriptor_worker_writes_scaffold_and_count(qapp) -> None:  # noqa: ARG001
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))
    worker = CalcWorker(
        CalcDescriptorsRequest(
            data=[(1, "c1ccccc1"), (2, "Cc1ccccc1"), (3, "CCO")],
            disp_headers=["Murcko scaffold", "Scaffold count"],
            int_fns=["MURCKO_SCAFFOLD", "MURCKO_COUNT"],
            is_smiles=True,
        ),
        sigs,
    )
    worker.run()
    rows = {oid: row for oid, row in out["rows"]}  # type: ignore[index]
    assert rows[1]["Murcko scaffold"] == rows[2]["Murcko scaffold"] == "c1ccccc1"
    assert rows[1]["Scaffold count"] == rows[2]["Scaffold count"] == "2"
    assert rows[3]["Murcko scaffold"] == ""
    assert rows[3]["Scaffold count"] == "0"
    assert out["headers"] == ["Murcko scaffold", "Scaffold count"]


def test_scaffolds_tab_follows_structural_alerts(qapp) -> None:  # noqa: ARG001
    dlg = PropertyDialog(["Structure"], selected_row_count=0)
    labels = [dlg.tabs.tabText(i) for i in range(dlg.tabs.count())]
    assert labels[labels.index("Structural Alerts") + 1] == "Scaffolds"
    assert dlg.get_selected() == ([], [])
    dlg._scaffold_checks["Murcko scaffold"].setChecked(True)
    dlg._scaffold_checks["Scaffold count"].setChecked(True)
    disp, fns = dlg.get_selected()
    assert disp == ["Murcko scaffold", "Scaffold count"]
    assert fns == ["MURCKO_SCAFFOLD", "MURCKO_COUNT"]
    dlg.close()
