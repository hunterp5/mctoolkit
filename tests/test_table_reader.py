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

"""Qt-free table reader over a column store and a molecule store."""

from __future__ import annotations

from rdkit import Chem

from molmanager.services.table_reader import (
    StoreTableReader,
    activity_for_oid,
    backing_then_cell,
    cell_then_backing,
    collect_structure_payloads,
)
from molmanager.ui.table_reader_view import WindowTableReader
from molmanager.storage.mol_store import MolStore
from molmanager.table.column_store import ColumnStore

_HEADERS = ("ID_HIDDEN", "Structure", "SMILES", "IC50")


def _reader(mols: MolStore) -> StoreTableReader:
    rows = ColumnStore()
    rows.append_columns(
        [10, 20],
        {"SMILES": ["CCO", "c1ccccc1"], "IC50": ["1.50", ""]},
    )
    blob = Chem.MolFromSmiles("CCO").ToBinary()
    mols.ingest_jobs([(10, bytes(blob), "CCO"), (20, None, "c1ccccc1")])
    return StoreTableReader(_HEADERS, rows, mols)


def test_reader_reports_cells_oids_and_activity() -> None:
    mols = MolStore()
    try:
        reader = _reader(mols)
        assert reader.row_count() == 2
        assert reader.headers == _HEADERS
        assert reader.cell_text(0, 0) == "10"
        assert reader.cell_text(0, 1) == ""
        assert reader.cell_text(0, 3) == "1.50"
        assert reader.oid_at(1) == 20
        assert reader.row_for_oid(20) == 1
        assert reader.row_for_oid(99) == -1
        assert activity_for_oid(reader, 10, activity_column="IC50") == 1.5
        assert activity_for_oid(reader, 20, activity_column="IC50") is None
        assert activity_for_oid(reader, 99, activity_column="IC50") is None
    finally:
        mols.close()


def test_activity_falls_back_to_backing_text() -> None:
    rows = ColumnStore()
    rows.append_columns([7], {"IC50": ["2.25"]})
    reader = StoreTableReader(("ID_HIDDEN", "Structure", "IC50"), rows)

    class _DisplayHidesValue:
        """Display text is blank; the stored cell still has the number."""

        headers = reader.headers

        def row_for_oid(self, oid: int) -> int:
            return reader.row_for_oid(oid)

        def cell_text(self, row: int, column: int) -> str:
            del row, column
            return ""

        def backing_text(self, row: int, header: str) -> str:
            return reader.backing_text(row, header)

    assert (
        activity_for_oid(_DisplayHidesValue(), 7, activity_column="IC50", activity_col_index=2)
        == 2.25
    )


def test_structure_source_reads_the_molecule_store_once() -> None:
    class _Store(MolStore):
        def __init__(self) -> None:
            super().__init__()
            self.batch_calls = 0
            self.blob_calls = 0

        def structure_payloads_for(self, oids):
            self.batch_calls += 1
            return super().structure_payloads_for(oids)

        def blob_for(self, oid: int) -> bytes | None:
            self.blob_calls += 1
            return super().blob_for(oid)

    mols = _Store()
    try:
        reader = _reader(mols)
        selected = collect_structure_payloads(reader, "Structure", allowed_oids={20})
        assert [payload.oid for payload in selected] == [20]
        assert mols.batch_calls == 1
        assert mols.blob_calls == 0
    finally:
        mols.close()


def test_plain_molecule_map_is_pickled_without_a_batch_query() -> None:
    class _Mol:
        def ToBinary(self) -> bytes:
            return b"pickle"

    class _App:
        mols = {4: _Mol(), 5: None}

    rows = WindowTableReader(_App()).structure_rows(None)
    assert rows[4] == (b"pickle", "")
    assert 5 not in rows


def test_cell_text_falls_through_to_stored_text() -> None:
    rows = ColumnStore()
    rows.append_columns([1], {"SMILES": ["CCO"]})
    reader = StoreTableReader(("ID_HIDDEN", "Structure", "SMILES"), rows)
    assert cell_then_backing(reader, 0, "SMILES") == "CCO"
    assert backing_then_cell(reader, 0, "SMILES") == "CCO"
    assert cell_then_backing(reader, 0, "Missing") == ""


def test_collect_structure_payloads_from_store_and_column() -> None:
    mols = MolStore()
    try:
        reader = _reader(mols)
        structures = collect_structure_payloads(reader, "Structure", allowed_oids={10})
        assert [payload.oid for payload in structures] == [10]
        assert structures[0].smiles == "CCO"
        assert structures[0].blob
        smiles = collect_structure_payloads(reader, "SMILES")
        assert [(payload.oid, payload.smiles) for payload in smiles] == [
            (10, "CCO"),
            (20, "c1ccccc1"),
        ]
        assert collect_structure_payloads(reader, "Missing") == []
        visible = collect_structure_payloads(reader, "SMILES", visible_rows={1})
        assert [payload.oid for payload in visible] == [20]
    finally:
        mols.close()
