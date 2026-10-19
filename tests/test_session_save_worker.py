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

"""SessionSaveWorker and Qt-free session document assembly."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QThreadPool
from rdkit import Chem

from molmanager.chem.molecule_conversion import mol_graph_binary
from molmanager.table.session_codec import (
    decode_mol_blob_b64,
    expand_session_document,
    loads_session_bytes,
)
from molmanager.table.session_document_build import assemble_session_document
from molmanager.workers import SessionSaveSignals, SessionSaveWorker


def _metadata() -> dict:
    return {
        "format": "molmanager_session",
        "version": 2,
        "next_oid": 2,
        "filter_panel_visible": False,
        "plot_panel_visible": True,
        "sort_ascending": True,
    }


def test_assemble_session_document_uses_store_payload_without_reserialize():
    mol = Chem.MolFromSmiles("CCO")
    blob = mol_graph_binary(mol)
    assert blob
    doc = assemble_session_document(
        {
            "headers": ["ID_HIDDEN", "Structure", "SMILES", "Note"],
            "entries": [(1, {"SMILES": "CCO", "Note": "ethanol"})],
            "payloads": {1: (blob, "CCO")},
            "metadata": _metadata(),
            "ensembles": None,
        }
    )
    assert doc["ids"] == [1]
    assert doc["data_headers"] == ["SMILES", "Note"]
    restored = decode_mol_blob_b64(doc["structure_mols"][0])
    assert restored == blob
    assert doc["structure_smiles"] == ["CCO"]


def test_assemble_session_document_fills_blob_from_smiles_cell():
    doc = assemble_session_document(
        {
            "headers": ["ID_HIDDEN", "Structure", "SMILES"],
            "entries": [(7, {"SMILES": "CC"})],
            "payloads": {},
            "metadata": _metadata(),
            "ensembles": None,
        }
    )
    blob = decode_mol_blob_b64(doc["structure_mols"][0])
    assert blob
    roundtrip = Chem.Mol(blob)
    assert Chem.MolToSmiles(roundtrip) == "CC"


def test_session_save_worker_writes_chunked_cms(qapp, tmp_path):  # noqa: ARG001
    sig = SessionSaveSignals()
    results: list[tuple[int, str]] = []
    sig.finished.connect(lambda gen, path: results.append((gen, path)))
    out = tmp_path / "saved.cms"
    mol = Chem.MolFromSmiles("CCO")
    blob = mol_graph_binary(mol)
    snapshot = {
        "headers": ["ID_HIDDEN", "Structure", "SMILES"],
        "entries": [(1, {"SMILES": "CCO"})],
        "payloads": {1: (blob, "CCO")},
        "metadata": _metadata(),
        "ensembles": None,
    }
    pool = QThreadPool()
    pool.start(SessionSaveWorker(4, str(out), snapshot, sig))
    assert pool.waitForDone(60_000)
    qapp.processEvents()
    assert results and results[0] == (4, str(out))
    raw = Path(out).read_bytes()
    assert raw.startswith(b"PK")
    doc = expand_session_document(loads_session_bytes(raw))
    assert [row["id"] for row in doc["rows"]] == [1]
    assert "CCO" in (doc["rows"][0]["cells"].get("SMILES") or "")


def test_version3_chunks_round_trip_display_text(tmp_path):
    from molmanager.table.session_codec import (
        read_session_v3_ensembles,
        read_session_v3_manifest,
        session_path_is_v3,
        session_v3_chunk_names,
    )
    from molmanager.table.session_document_build import write_session_v3

    out = tmp_path / "chunked.cms"
    write_session_v3(
        str(out),
        {
            "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
            "entries": [
                (1, {"SMILES": "CCO", "MW": "1.50"}),
                (2, {"SMILES": "CC", "MW": "2.00"}),
            ],
            "payloads": {},
            "metadata": _metadata(),
            "ensembles": b"ensemble-bytes",
        },
        chunk_rows=1,
    )
    assert session_path_is_v3(str(out))
    assert session_v3_chunk_names(str(out)) == ["rows/00000.json", "rows/00001.json"]
    manifest = read_session_v3_manifest(str(out))
    assert manifest["version"] == 3
    assert "values" not in manifest
    assert read_session_v3_ensembles(str(out)) == b"ensemble-bytes"
    doc = expand_session_document(loads_session_bytes(out.read_bytes()))
    assert [row["cells"]["MW"] for row in doc["rows"]] == ["1.50", "2.00"]


def test_open_version3_session_applies_chunks(qapp, tmp_path):  # noqa: ARG001
    from molmanager.table.session_document_build import write_session_v3
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    out = tmp_path / "open.cms"
    meta = _metadata()
    meta["next_oid"] = 3
    write_session_v3(
        str(out),
        {
            "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
            "entries": [
                (1, {"SMILES": "CCO", "MW": "1.50"}),
                (2, {"SMILES": "CC", "MW": "2.00"}),
            ],
            "payloads": {},
            "metadata": meta,
            "ensembles": None,
        },
        chunk_rows=1,
    )
    window = ChemistryWorkspaceWindow()
    assert window.apply_saved_session_from_file(str(out)) is True
    model = window._table_model
    assert model.rowCount() == 2
    assert model.cell_text(0, 3) == "1.50"
    assert model.cell_text(1, 3) == "2.00"
    assert model._rows.column_kind("MW") == "float"
