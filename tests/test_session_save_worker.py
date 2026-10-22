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

"""SessionSaveWorker and SessionOpenWorker on a thread pool."""

from __future__ import annotations

from PyQt5.QtCore import QThreadPool
from rdkit import Chem

from molmanager.storage import MolStore
from molmanager.table.session_v4 import SessionOpenResult, SessionSaveSnapshot, is_session_v4
from molmanager.ui.column_store import ColumnStore
from molmanager.workers import (
    SessionOpenSignals,
    SessionOpenWorker,
    SessionSaveSignals,
    SessionSaveWorker,
)


def _snapshot(mols: MolStore) -> SessionSaveSnapshot:
    rows = ColumnStore()
    rows.append_columns([1, 2], {"SMILES": ["CCO", "CC"], "MW": ["1.50", "2.00"]})
    return SessionSaveSnapshot(
        manifest={"headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"], "next_oid": 3},
        oids=rows.oids_blob(),
        columns=rows.to_blobs(["SMILES", "MW"]),
        sidecars={"notepad": lambda: {"text": "written on the worker"}},
        mol_db=mols.db_path,
        row_count=rows.n,
    )


def test_save_then_open_workers_round_trip(qapp, tmp_path):  # noqa: ARG001
    mols = MolStore()
    mols[1] = Chem.MolFromSmiles("CCO")
    mols.flush()
    out = tmp_path / "saved.cms"
    saved: list[tuple[int, str]] = []
    save_signals = SessionSaveSignals()
    save_signals.finished.connect(lambda gen, path: saved.append((gen, path)))
    pool = QThreadPool()
    pool.start(SessionSaveWorker(4, str(out), _snapshot(mols), save_signals))
    assert pool.waitForDone(60_000)
    qapp.processEvents()
    mols.close()
    assert saved == [(4, str(out))]
    assert is_session_v4(out)

    opened: list[tuple[int, object]] = []
    open_signals = SessionOpenSignals()
    open_signals.finished.connect(lambda gen, result: opened.append((gen, result)))
    pool.start(SessionOpenWorker(9, str(out), open_signals, want_scene_revision=None))
    assert pool.waitForDone(60_000)
    qapp.processEvents()
    assert len(opened) == 1 and opened[0][0] == 9
    result = opened[0][1]
    assert isinstance(result, SessionOpenResult)
    try:
        assert result.manifest["notepad"] == {"text": "written on the worker"}
        assert [result.rows.get_text(i, "MW") for i in range(2)] == ["1.50", "2.00"]
        restored = MolStore(result.mol_db)
        try:
            assert Chem.MolToSmiles(restored[1]) == "CCO"
        finally:
            restored.close()
    finally:
        result.discard_temp_files()


def test_open_worker_reports_damaged_file(qapp, tmp_path):  # noqa: ARG001
    bad = tmp_path / "bad.cms"
    bad.write_bytes(b"SQLite format 3\x00" + b"\x00" * 64)
    failures: list[tuple[int, str]] = []
    signals = SessionOpenSignals()
    signals.failed.connect(lambda gen, msg: failures.append((gen, msg)))
    SessionOpenWorker(2, str(bad), signals, want_scene_revision=None).run()
    qapp.processEvents()
    assert failures and failures[0][0] == 2


def test_open_session_keeps_float_column_display_text(qapp, tmp_path):  # noqa: ARG001
    from session_roundtrip import open_saved

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    source = ChemistryWorkspaceWindow()
    source.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    source._table_model.set_headers(list(source.headers))
    source._table_model.append_row(1, {"SMILES": "CCO", "MW": "1.50"})
    source._table_model.append_row(2, {"SMILES": "CC", "MW": "2.00"})
    source.next_oid = 3
    window = ChemistryWorkspaceWindow()
    open_saved(source, window)
    model = window._table_model
    assert model.rowCount() == 2
    assert model.cell_text(0, 3) == "1.50"
    assert model.cell_text(1, 3) == "2.00"
    assert model._rows.column_kind("MW") == "float"
    assert window.next_oid == 3
