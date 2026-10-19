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

"""Bemis–Murcko scaffold columns and the Substructure menu dialog."""

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.murcko import (
    apply_murcko_scaffold_counts,
    murcko_framework_smiles,
    murcko_ring_systems_smiles,
    murcko_scaffold_smiles,
)
from molmanager.ui.dialogs.substructure import BemisMurckoDialog
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


def test_bemis_murcko_dialog_defaults_to_every_column(qapp) -> None:  # noqa: ARG001
    dlg = BemisMurckoDialog(["Structure"], selected_row_count=0)
    disp, fns = dlg.get_selected()
    assert disp == [
        "Murcko scaffold",
        "Murcko framework",
        "Murcko ring systems",
        "Scaffold count",
    ]
    assert fns == ["MURCKO_SCAFFOLD", "MURCKO_FRAMEWORK", "MURCKO_RINGS", "MURCKO_COUNT"]
    dlg._checks["Murcko framework"][0].setChecked(False)
    dlg._checks["Murcko ring systems"][0].setChecked(False)
    disp, fns = dlg.get_selected()
    assert disp == ["Murcko scaffold", "Scaffold count"]
    assert fns == ["MURCKO_SCAFFOLD", "MURCKO_COUNT"]
    dlg.close()


def _window_with_one_row():
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(1, {})
    return window


def test_murcko_columns_queue_render_2d(qapp) -> None:  # noqa: ARG001
    window = _window_with_one_row()
    queued: list[str] = []

    def _record(title, _factory, **_kwargs):
        queued.append(title)
        return "test-job"

    window.process_queue.enqueue = _record
    try:
        window._on_calculated_results(
            [
                (
                    1,
                    {
                        "Murcko scaffold": "c1ccccc1",
                        "Murcko framework": "C1CCCCC1",
                        "Murcko ring systems": "c1ccccc1",
                        "Scaffold count": "1",
                    },
                )
            ],
            [
                "Murcko scaffold",
                "Murcko framework",
                "Murcko ring systems",
                "Scaffold count",
            ],
        )
        assert queued == [
            "Render 2D: Murcko scaffold (1 rows)",
            "Render 2D: Murcko framework (1 rows)",
            "Render 2D: Murcko ring systems (1 rows)",
        ]
        assert window._table_model.value_for_header(0, "Scaffold count") == "1"
    finally:
        window.close()


def test_blank_and_placeholder_murcko_cells_skip_render(qapp) -> None:  # noqa: ARG001
    window = _window_with_one_row()
    queued: list[str] = []
    window.process_queue.enqueue = lambda title, _factory, **_kwargs: queued.append(title)
    try:
        window._on_calculated_results(
            [(1, {"Murcko scaffold": "", "Murcko framework": "N/A"})],
            ["Murcko scaffold", "Murcko framework"],
        )
        assert queued == []
    finally:
        window.close()
