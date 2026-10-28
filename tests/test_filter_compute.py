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

"""Tests for filter_compute SQL pushdown helpers."""

from __future__ import annotations

from pathlib import Path

from molmanager.table.filter_compute import build_sqlite_where, fetch_matching_oids
from molmanager.storage.sqlite_table_store import SqliteTableStore


def _store_with_rows(tmp_path: Path) -> SqliteTableStore:
    store = SqliteTableStore(tmp_path / "filter_test.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW", "Phase"]
    rows = [
        (0, {"SMILES": "C", "MW": "16", "Phase": "prep"}),
        (1, {"SMILES": "CC", "MW": "30", "Phase": "ship"}),
        (2, {"SMILES": "CCC", "MW": "44", "Phase": "prep"}),
    ]
    store.rebuild(headers, rows)
    return store


def test_build_sqlite_where_numeric_range(tmp_path):
    store = _store_with_rows(tmp_path)
    where = build_sqlite_where(
        [
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 20.0,
                "max": 40.0,
                "inverted": False,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    oids = fetch_matching_oids(store.db_path, where_sql, args)
    assert oids == frozenset({1})


def test_disabled_substructure_card_does_not_block_sqlite(tmp_path):
    store = _store_with_rows(tmp_path)
    where = build_sqlite_where(
        [
            {"kind": "substructure", "enabled": False},
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 0.0,
                "max": 20.0,
                "inverted": False,
            },
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    oids = fetch_matching_oids(store.db_path, where_sql, args)
    assert oids == frozenset({0})


def test_enabled_substructure_blocks_sqlite_pushdown(tmp_path):
    store = _store_with_rows(tmp_path)
    where = build_sqlite_where(
        [
            {"kind": "substructure", "enabled": True},
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 0.0,
                "max": 100.0,
                "inverted": False,
            },
        ],
        headers=store.headers,
    )
    assert where is None


def test_category_filter_in_clause(tmp_path):
    store = _store_with_rows(tmp_path)
    where = build_sqlite_where(
        [
            {
                "kind": "category",
                "enabled": True,
                "column": "Phase",
                "values": ["prep"],
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    oids = fetch_matching_oids(store.db_path, where_sql, args)
    assert oids == frozenset({0, 2})


def test_numeric_filter_hides_blank_and_non_numeric_cells(tmp_path):
    store = SqliteTableStore(tmp_path / "blank_numeric.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW", "Phase"]
    store.rebuild(
        headers,
        [
            (0, {"SMILES": "C", "MW": "0", "Phase": "prep"}),
            (1, {"SMILES": "CC", "MW": "10", "Phase": "ship"}),
            (2, {"SMILES": "CCC", "MW": "", "Phase": "prep"}),
            (3, {"SMILES": "CCCC", "MW": "n/a", "Phase": ""}),
        ],
    )
    where = build_sqlite_where(
        [
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 0.0,
                "max": 10.0,
                "inverted": False,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    assert fetch_matching_oids(store.db_path, where_sql, args) == frozenset({0, 1})


def test_inverted_numeric_filter_hides_blank_cells(tmp_path):
    store = SqliteTableStore(tmp_path / "inv_numeric.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    store.rebuild(
        headers,
        [
            (0, {"SMILES": "C", "MW": "10"}),
            (1, {"SMILES": "CC", "MW": "30"}),
            (2, {"SMILES": "CCC", "MW": ""}),
        ],
    )
    where = build_sqlite_where(
        [
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 10.0,
                "max": 20.0,
                "inverted": True,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    assert fetch_matching_oids(store.db_path, where_sql, args) == frozenset({1})


def test_inverted_text_filter_hides_blank_cells(tmp_path):
    store = _store_with_rows(tmp_path)
    store.rebuild(
        store.headers,
        [
            (0, {"SMILES": "C", "MW": "16", "Phase": "prep"}),
            (1, {"SMILES": "CC", "MW": "30", "Phase": ""}),
            (2, {"SMILES": "CCC", "MW": "44", "Phase": "ship"}),
        ],
    )
    where = build_sqlite_where(
        [
            {
                "kind": "text",
                "enabled": True,
                "column": "Phase",
                "text": "prep",
                "partial_match": True,
                "case_sensitive": False,
                "inverted": True,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    assert fetch_matching_oids(store.db_path, where_sql, args) == frozenset({2})


def test_category_filter_hides_blank_cells(tmp_path):
    store = SqliteTableStore(tmp_path / "blank_category.sqlite3")
    headers = ["ID_HIDDEN", "Structure", "SMILES", "Phase"]
    store.rebuild(
        headers,
        [
            (0, {"SMILES": "C", "Phase": "prep"}),
            (1, {"SMILES": "CC", "Phase": ""}),
            (2, {"SMILES": "CCC", "Phase": "ship"}),
        ],
    )
    where = build_sqlite_where(
        [
            {
                "kind": "category",
                "enabled": True,
                "column": "Phase",
                "values": ["prep", "ship", ""],
                "inverted": False,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    assert fetch_matching_oids(store.db_path, where_sql, args) == frozenset({0, 2})


def test_fetch_matching_oids_keyset_pages(tmp_path):
    store = _store_with_rows(tmp_path)
    where = build_sqlite_where(
        [
            {
                "kind": "numeric",
                "enabled": True,
                "column": "MW",
                "min": 0.0,
                "max": 100.0,
                "inverted": False,
            }
        ],
        headers=store.headers,
    )
    assert where is not None
    where_sql, args = where
    oids = fetch_matching_oids(store.db_path, where_sql, args, page_size=1)
    assert oids == frozenset({0, 1, 2})
