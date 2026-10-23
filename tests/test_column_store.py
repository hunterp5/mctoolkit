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

"""Columnar table cells keep exact display text and pack uniform numbers."""

from __future__ import annotations

from molmanager.ui.column_store import ColumnStore
from molmanager.ui.compound_table_model import CompoundTableModel, _Row


def _row(oid: int, **cells: str) -> _Row:
    return _Row(oid=oid, values=dict(cells))


def test_uniform_decimals_stay_float_and_round_trip() -> None:
    store = ColumnStore()
    store.append(_row(1, MW="1.50"))
    store.append(_row(2, MW="10.00"))
    assert store.column_kind("MW") == "float"
    assert store.get_text(0, "MW") == "1.50"
    assert store.get_text(1, "MW") == "10.00"
    assert store.get_text(0, "missing") == ""


def test_mixed_decimal_widths_stay_text() -> None:
    store = ColumnStore()
    store.append(_row(1, MW="1.50"))
    store.append(_row(2, MW="1.5"))
    assert store.column_kind("MW") == "text"
    assert store.get_text(0, "MW") == "1.50"
    assert store.get_text(1, "MW") == "1.5"


def test_leading_zeros_and_smiles_stay_text() -> None:
    store = ColumnStore()
    store.append(_row(1, ID="00123", SMILES="CCO"))
    assert store.column_kind("ID") == "text"
    assert store.column_kind("SMILES") == "text"
    assert store.get_text(0, "ID") == "00123"
    assert store.get_text(0, "SMILES") == "CCO"


def test_blank_then_number_promotes() -> None:
    store = ColumnStore()
    store.append(_row(1, MW=""))
    store.append(_row(2, MW="2.50"))
    assert store.column_kind("MW") == "float"
    assert store.get_text(0, "MW") == ""
    assert store.get_text(1, "MW") == "2.50"


def test_delete_sort_and_rename_keep_text() -> None:
    store = ColumnStore()
    store.append(_row(1, MW="1.00", Name="a"))
    store.append(_row(2, MW="3.00", Name="c"))
    store.append(_row(3, MW="2.00", Name="b"))
    store.delete_oids({2})
    assert [store.oid_at(i) for i in range(len(store))] == [1, 3]
    store.sort(key=lambda row: row.values.get("Name", ""), reverse=True)
    assert [store.oid_at(i) for i in range(len(store))] == [3, 1]
    assert store.get_text(0, "MW") == "2.00"
    assert store.get_text(1, "Name") == "a"
    store.rename_column("MW", "Mass")
    assert store.column_kind("Mass") == "float"
    assert store.get_text(0, "Mass") == "2.00"
    assert store.get_text(1, "Mass") == "1.00"
    assert store.column_kind("MW") is None


def test_model_displays_packed_numbers_exactly(qapp) -> None:  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "MW", "Name"])
    model.append_rows_batch(
        [(7, {"MW": "1.50", "Name": "ethanol"}), (8, {"MW": "2.00", "Name": "x"})]
    )
    assert model._rows.column_kind("MW") == "float"
    assert model._rows.column_kind("Name") == "text"
    assert model.cell_text(0, 2) == "1.50"
    assert model.data(model.index(1, 2)) == "2.00"
    assert model.value_for_header(0, "Name") == "ethanol"
    model.set_cell_text(7, "MW", "3.00")
    assert model.cell_text(0, 2) == "3.00"
    assert model._rows.column_kind("MW") == "float"
    model.set_cell_text(7, "MW", "see note")
    assert model._rows.column_kind("MW") == "text"
    assert model.cell_text(0, 2) == "see note"
    assert model.cell_text(1, 2) == "2.00"


def test_analysis_reads_packed_numbers_as_floats(qapp) -> None:  # noqa: ARG001
    import numpy as np
    import pandas as pd

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "MW", "Name"])
    model.append_rows_batch([(1, {"MW": "1.50", "Name": "ethanol"}), (2, {"MW": "", "Name": ""})])
    headers = ["ID_HIDDEN", "Structure", "MW", "Name"]
    columns = model.analysis_column_texts(headers, None)
    assert isinstance(columns["MW"], np.ndarray)
    assert columns["MW"][0] == 1.5
    assert np.isnan(columns["MW"][1])
    assert columns["Name"] == ["ethanol", ""]
    assert model.cell_text(0, 2) == "1.50"
    frame = pd.DataFrame(columns, copy=False)
    numeric = frame[["MW"]].apply(pd.to_numeric, errors="coerce")
    assert numeric["MW"].dtype.kind == "f"
    assert list(model.analysis_column_texts(headers, [])) == ["ID_HIDDEN", "MW", "Name"]


_APPEND_CASES = [
    ["1.50", "", "10.00"],
    ["1.50", "1.5"],
    ["", "", ""],
    ["", "7", "8"],
    ["7", "x"],
    ["00123", "4"],
    ["abc", "1"],
    ["1", "2.0"],
]


def _per_cell(chunks: list[list[str]]) -> ColumnStore:
    store = ColumnStore()
    oid = 0
    for chunk in chunks:
        for text in chunk:
            oid += 1
            store.append(_row(oid, A=text))
    return store


def _columnar(chunks: list[list[str]]) -> ColumnStore:
    store = ColumnStore()
    oid = 0
    for chunk in chunks:
        oids = list(range(oid + 1, oid + 1 + len(chunk)))
        oid += len(chunk)
        store.append_columns(oids, {"A": chunk})
    return store


def test_append_columns_matches_per_cell_appends() -> None:
    for first in _APPEND_CASES:
        for second in _APPEND_CASES:
            chunks = [first, second]
            expected, actual = _per_cell(chunks), _columnar(chunks)
            assert actual.column_kind("A") == expected.column_kind("A"), chunks
            assert [actual.get_text(i, "A") for i in range(actual.n)] == [
                expected.get_text(i, "A") for i in range(expected.n)
            ], chunks
            assert list(actual.oids[: actual.n]) == list(expected.oids[: expected.n])


def test_append_columns_blanks_missing_and_new_columns() -> None:
    store = ColumnStore()
    store.append_columns([1, 2], {"A": ["x", "y"]})
    store.append_columns([3], {"B": ["2.5"]})
    assert [store.get_text(i, "A") for i in range(3)] == ["x", "y", ""]
    assert [store.get_text(i, "B") for i in range(3)] == ["", "", "2.5"]
    assert store.column_kind("B") == "float"


def test_blob_round_trip_keeps_text_kinds_and_subset() -> None:
    import numpy as np

    store = ColumnStore()
    store.append_columns(
        [10, 20, 30],
        {"MW": ["1.50", "", "3.25"], "Name": ["a", "b", ""], "Empty": ["", "", ""]},
    )
    blobs = store.to_blobs(["MW", "Name", "Empty", "Missing"])
    back = ColumnStore.from_blobs(store.oids_blob(), blobs)
    assert list(back.oids) == [10, 20, 30]
    assert back.column_kind("MW") == "float"
    assert [back.get_text(i, "MW") for i in range(3)] == ["1.50", "", "3.25"]
    assert [back.get_text(i, "Name") for i in range(3)] == ["a", "b", ""]
    assert back.columns["Empty"].blank_only
    assert [back.get_text(i, "Missing") for i in range(3)] == ["", "", ""]

    keep = np.array([True, False, True])
    subset = ColumnStore.from_blobs(store.oids_blob(keep), store.to_blobs(["MW", "Name"], keep))
    assert list(subset.oids) == [10, 30]
    assert [subset.get_text(i, "MW") for i in range(2)] == ["1.50", "3.25"]
    assert [subset.get_text(i, "Name") for i in range(2)] == ["a", ""]


def test_float_range_matches_per_cell_bounds(qapp) -> None:  # noqa: ARG001
    from molmanager.services.numeric_bounds import merge_numeric_bounds_rows

    model = CompoundTableModel([])
    model.set_headers(["ID_HIDDEN", "Structure", "pIC50", "Count", "Note"])
    cells = [
        {"pIC50": "5.25", "Count": "3", "Note": "1.5"},
        {"pIC50": "", "Count": "-7", "Note": "n/a"},
        {"pIC50": "8.75", "Count": "12", "Note": "2"},
        {"pIC50": "6.00", "Count": "", "Note": ""},
    ]
    model.append_rows_batch(list(enumerate(cells)))
    rows = model._rows
    assert rows.column_kind("pIC50") == "float" and rows.column_kind("Note") == "text"
    for header in ("pIC50", "Count", "Note"):
        for start, end in ((0, 4), (1, 3), (1, 2)):
            slow = merge_numeric_bounds_rows(
                [_Row(oid=i, values=c) for i, c in enumerate(cells)], header, start, end, None
            )
            assert model.merge_numeric_bounds_chunk(header, start, end, None) == slow
    acc = model.merge_numeric_bounds_chunk("Count", 0, 2, None)
    assert model.merge_numeric_bounds_chunk("Count", 2, 4, acc) == {
        "min": -7.0,
        "max": 12.0,
        "is_int": True,
    }
