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
    apply_murcko_scaffold_ids,
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


def test_ring_systems_replace_cut_bonds_and_keep_exocyclic_carbonyls() -> None:
    nelarabine = _mol("COc1nc(N)nc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@@H]1O")
    clofarabine = _mol("Nc1nc(Cl)nc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@@H]1F")
    nucleoside_rings = "C1CCOC1.c1ncc2nc[nH]c2n1"
    assert murcko_ring_systems_smiles(nelarabine) == nucleoside_rings
    assert murcko_ring_systems_smiles(clofarabine) == nucleoside_rings

    topotecan = _mol("CC[C@@]1(O)C(=O)OCc2c1cc1n(c2=O)Cc2cc3c(CN(C)C)c(O)ccc3nc2-1")
    topotecan_rings = murcko_ring_systems_smiles(topotecan)
    assert topotecan_rings == "O=C1Cc2cc3n(c(=O)c2CO1)Cc1cc2ccccc2nc1-3"
    assert "." not in topotecan_rings

    indomethacin = _mol("COc1ccc2c(c1)c(CC(=O)O)c(C)n2C(=O)c1ccc(Cl)cc1")
    assert murcko_ring_systems_smiles(indomethacin) == "c1ccc2[nH]ccc2c1.c1ccccc1"


def test_ring_system_fragments_can_be_drawn() -> None:
    from molmanager.chem.depiction_builder import build_scene

    smiles = {
        "nelarabine": "COc1nc(N)nc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@@H]1O",
        "clofarabine": "Nc1nc(Cl)nc2c1ncn2[C@@H]1O[C@H](CO)[C@@H](O)[C@@H]1F",
        "topotecan": "CC[C@@]1(O)C(=O)OCc2c1cc1n(c2=O)Cc2cc3c(CN(C)C)c(O)ccc3nc2-1",
        "caffeine": "Cn1cnc2c1c(=O)n(C)c(=O)n2C",
    }
    for name, text in smiles.items():
        rings = murcko_ring_systems_smiles(_mol(text))
        parsed = Chem.MolFromSmiles(rings)
        assert parsed is not None, name
        scene, reason = build_scene(parsed)
        assert scene is not None, (name, reason)
        assert len(scene.atoms) == parsed.GetNumAtoms()


def test_scaffold_id_is_shared_and_follows_first_appearance() -> None:
    prepared = [
        (1, _mol("c1ccccc1")),
        (2, _mol("Cc1ccccc1")),
        (3, _mol("CCO")),
        (4, None),
        (5, _mol("n1ccccc1")),
        (6, _mol("Cc1ccncc1")),
    ]
    results = [
        (5, {"Murcko scaffold": "c1ccncc1", "Scaffold ID": ""}),
        (1, {"Murcko scaffold": "c1ccccc1", "Scaffold ID": ""}),
        (6, {"Murcko scaffold": "c1ccncc1", "Scaffold ID": ""}),
        (2, {"Murcko scaffold": "c1ccccc1", "Scaffold ID": ""}),
        (3, {"Murcko scaffold": "", "Scaffold ID": ""}),
        (4, {"Murcko scaffold": "N/A", "Scaffold ID": "N/A"}),
    ]
    filled = apply_murcko_scaffold_ids(
        results,
        prepared,
        ["Murcko scaffold", "Scaffold ID"],
        ["MURCKO_SCAFFOLD", "MURCKO_ID"],
    )
    by_oid = {oid: row for oid, row in filled}
    assert by_oid[1]["Scaffold ID"] == by_oid[2]["Scaffold ID"] == "1"
    assert by_oid[5]["Scaffold ID"] == by_oid[6]["Scaffold ID"] == "2"
    assert by_oid[3]["Scaffold ID"] == "0"
    assert by_oid[4]["Scaffold ID"] == "N/A"
    assert by_oid[1]["Murcko scaffold"] == "c1ccccc1"


def test_descriptor_worker_writes_scaffold_and_id(qapp) -> None:  # noqa: ARG001
    sigs = WorkerSignals()
    out: dict[str, object] = {}
    sigs.calculated.connect(lambda rows, headers: out.update({"rows": rows, "headers": headers}))
    worker = CalcWorker(
        CalcDescriptorsRequest(
            data=[(1, "c1ccccc1"), (2, "Cc1ccccc1"), (3, "CCO"), (4, "n1ccccc1")],
            disp_headers=["Murcko scaffold", "Scaffold ID"],
            int_fns=["MURCKO_SCAFFOLD", "MURCKO_ID"],
            is_smiles=True,
        ),
        sigs,
    )
    worker.run()
    rows = {oid: row for oid, row in out["rows"]}  # type: ignore[index]
    assert rows[1]["Murcko scaffold"] == rows[2]["Murcko scaffold"] == "c1ccccc1"
    assert rows[1]["Scaffold ID"] == rows[2]["Scaffold ID"] == "1"
    assert rows[3]["Murcko scaffold"] == ""
    assert rows[3]["Scaffold ID"] == "0"
    assert rows[4]["Scaffold ID"] == "2"
    assert out["headers"] == ["Murcko scaffold", "Scaffold ID"]


def test_bemis_murcko_dialog_defaults_to_every_column(qapp) -> None:  # noqa: ARG001
    dlg = BemisMurckoDialog(["Structure"], selected_row_count=0)
    disp, fns = dlg.get_selected()
    assert disp == [
        "Murcko scaffold",
        "Murcko framework",
        "Murcko ring systems",
        "Scaffold ID",
    ]
    assert fns == ["MURCKO_SCAFFOLD", "MURCKO_FRAMEWORK", "MURCKO_RINGS", "MURCKO_ID"]
    dlg._checks["Murcko framework"][0].setChecked(False)
    dlg._checks["Murcko ring systems"][0].setChecked(False)
    disp, fns = dlg.get_selected()
    assert disp == ["Murcko scaffold", "Scaffold ID"]
    assert fns == ["MURCKO_SCAFFOLD", "MURCKO_ID"]
    dlg.close()


def _window_with_one_row():
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    window = ChemistryWorkspaceWindow()
    window.headers = ["ID_HIDDEN", "Structure"]
    window._table_model.set_headers(list(window.headers))
    window._table_model.append_row(1, {})
    return window


def test_murcko_columns_queue_render_2d(qapp) -> None:  # noqa: ARG001
    import threading

    window = _window_with_one_row()
    queued: list[str] = []
    jobs = []

    def _record(title, factory, **_kwargs):
        queued.append(title)
        jobs.append(factory(threading.Event()))
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
                        "Scaffold ID": "1",
                    },
                )
            ],
            [
                "Murcko scaffold",
                "Murcko framework",
                "Murcko ring systems",
                "Scaffold ID",
            ],
        )
        assert queued == [
            "Render 2D: Murcko scaffold (1 rows)",
            "Render 2D: Murcko framework (1 rows)",
            "Render 2D: Murcko ring systems (1 rows)",
        ]
        assert window._table_model.value_for_header(0, "Scaffold ID") == "1"
        scaffold = jobs[0]
        assert scaffold._bridge is window._render2d_queue_bridge
        assert scaffold._payload[2] == "Murcko scaffold"
        assert scaffold._payload[3] is True
        assert scaffold._payload[4] is False
    finally:
        window.close()


def test_tool_structure_columns_queue_render_2d(qapp) -> None:  # noqa: ARG001
    window = _window_with_one_row()
    queued: list[str] = []
    window.process_queue.enqueue = lambda title, _factory, **_kwargs: queued.append(title)
    try:
        window.on_calc_finished(
            [
                (
                    1,
                    {
                        "BRICS_1": "[16*]c1ccccc1",
                        "BRICS_2": "N/A",
                        "Common core": "[#6]-[#6]",
                        "Core match": "yes",
                        "Product 1": "CCO>>CC",
                        "Scaffold ID": "1",
                    },
                )
            ],
            ["BRICS_1", "BRICS_2", "Common core", "Core match", "Product 1", "Scaffold ID"],
            finish_progress=False,
        )
        assert queued == [
            "Render 2D: BRICS_1 (1 rows)",
            "Render 2D: Common core (1 rows)",
            "Render 2D: Product 1 (1 rows)",
        ]
        window.process_queue.enqueue = lambda title, _factory, **_kwargs: queued.append(title)
        queued.clear()
        window.on_calc_finished(
            [(1, {"Protonated": "c1ccccc1"})],
            ["Protonated"],
            finish_progress=False,
            depict_structures=False,
        )
        assert queued == []
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
