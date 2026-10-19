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

"""Structure-edit tools send stored blobs to workers and write results back in bulk."""

from __future__ import annotations

from rdkit import Chem

from molmanager.storage.mol_store import MolStore
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.workers import DisconnectFragmentsWorker, NeutralizeWorker

SALTS = [
    "CC(=O)[O-].[Na+]",
    "C[NH+](C)C.[Cl-]",
    "c1ccccc1",
]
CHARGED = ["CC(=O)[O-]", "C[NH+](C)C", "c1ccccc1"]


class _Sig:
    def __init__(self, sink):
        self._sink = sink

    def emit(self, *args):
        self._sink(*args)


def _recorder(result_signal: str, captured: list):
    attrs = {
        result_signal: _Sig(captured.append),
        "tool_progress": _Sig(lambda *_a: None),
        "partial_results": _Sig(lambda *_a: None),
    }
    return type("_Recorder", (), attrs)()


def _seeded_window(smiles_rows: list[str]) -> ChemistryWorkspaceWindow:
    win = ChemistryWorkspaceWindow()
    win.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    win._table_model.set_headers(list(win.headers))
    for smiles in smiles_rows:
        oid = win.next_oid
        win.next_oid += 1
        cells = win._ingest_store_mol(oid, Chem.MolFromSmiles(smiles))
        cells["SMILES"] = smiles
        win._table_model.append_row(oid, cells)
    win.mols._lru.clear()
    return win


def _forbid_per_row_store_access(monkeypatch) -> None:
    def _forbidden(self, key, *_args):
        raise AssertionError(f"GUI thread touched mol {key} one row at a time")

    monkeypatch.setattr(MolStore, "__getitem__", _forbidden)
    monkeypatch.setattr(MolStore, "__setitem__", _forbidden)


def _stored_smiles(win: ChemistryWorkspaceWindow) -> list[str]:
    return [smi for _oid, _blob, smi in win.mols.iter_structure_payloads()]


def test_neutralize_round_trip_skips_per_row_store_access(qapp, monkeypatch):  # noqa: ARG001
    win = _seeded_window(CHARGED)
    try:
        _forbid_per_row_store_access(monkeypatch)
        monkeypatch.setattr(win, "_start_render_2d_batch", lambda *_a, **_k: None)
        data = win._structure_tool_inputs("Structure", None)
        assert all(isinstance(item, bytes) for _oid, item in data)
        captured: list = []
        NeutralizeWorker(data, _recorder("neutralized", captured)).run()
        win._neutralize_source = "Structure"
        win.on_neutralize_finished(captured[0])
        assert _stored_smiles(win) == ["CC(=O)O", "CN(C)C", "c1ccccc1"]
    finally:
        monkeypatch.undo()
        win.close()


def test_disconnect_writes_parent_and_fragments_in_bulk(qapp, monkeypatch):  # noqa: ARG001
    win = _seeded_window(SALTS)
    try:
        _forbid_per_row_store_access(monkeypatch)
        monkeypatch.setattr(win, "_start_render_2d_batch", lambda *_a, **_k: None)
        data = win._structure_tool_inputs("Structure", None, with_source_text=True)
        captured: list = []
        DisconnectFragmentsWorker(data, _recorder("disconnect_fragments_finished", captured)).run()
        win._disconnect_source = "Structure"
        win._disconnect_fragments_col = "Fragments"
        win.on_disconnect_fragments_finished(captured[0])
        stored = _stored_smiles(win)
        assert all("." not in smi for smi in stored)
        assert "Fragments" in win.headers
        fragments = [
            win._table_model.backing_value_for_row_header(r, "Fragments") or ""
            for r in range(len(SALTS))
        ]
        assert "[Na+]" in fragments[0]
        assert "[Cl-]" in fragments[1]
    finally:
        monkeypatch.undo()
        win.close()
