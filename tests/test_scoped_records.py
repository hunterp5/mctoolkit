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

"""Scoped structure and activity record plans, with no Qt."""

from __future__ import annotations

from rdkit import Chem

from molmanager.services.table_reader import StoreTableReader
from molmanager.storage.mol_store import MolStore
from molmanager.table.column_store import ColumnStore
from molmanager.workflows.scoped_records import (
    ScopeBlocker,
    plan_scoped_activity_records,
    plan_scoped_structure_records,
)

_HEADERS = ("ID_HIDDEN", "Structure", "SMILES", "IC50")


def _reader(mols: MolStore) -> StoreTableReader:
    rows = ColumnStore()
    rows.append_columns(
        [10, 20],
        {"SMILES": ["CCO", "c1ccccc1"], "IC50": ["1.50", "nope"]},
    )
    blob = Chem.MolFromSmiles("CCO").ToBinary()
    mols.ingest_jobs([(10, bytes(blob), "CCO")])
    return StoreTableReader(_HEADERS, rows, mols)


def test_structure_plan_keeps_table_order_and_refuses_a_short_list() -> None:
    mols = MolStore()
    try:
        reader = _reader(mols)
        ready = plan_scoped_structure_records(reader, "SMILES", min_count=2)
        assert ready.is_ready
        assert [payload.smiles for payload in ready.payloads] == ["CCO", "c1ccccc1"]
        short = plan_scoped_structure_records(reader, "SMILES", allowed_oids={10}, min_count=2)
        assert short.blocked_by is ScopeBlocker.TOO_FEW_STRUCTURES
        assert short.min_count == 2
        empty = plan_scoped_structure_records(reader, "Missing")
        assert empty.blocked_by is ScopeBlocker.NO_STRUCTURES
    finally:
        mols.close()


def test_activity_plan_pairs_numeric_values_and_names_the_blocker() -> None:
    mols = MolStore()
    try:
        reader = _reader(mols)
        ready = plan_scoped_activity_records(
            reader, "Structure", activity_column="IC50", min_records=1
        )
        assert ready.is_ready
        assert [(oid, payload.smiles, activity) for oid, payload, activity in ready.records] == [
            (10, "CCO", 1.5)
        ]
        assert (
            plan_scoped_activity_records(reader, "SMILES", activity_column="(none)").blocked_by
            is ScopeBlocker.NO_ACTIVITY_CHOSEN
        )
        missing = plan_scoped_activity_records(reader, "SMILES", activity_column="LogP")
        assert missing.blocked_by is ScopeBlocker.MISSING_ACTIVITY_COLUMN
        assert missing.activity_column == "LogP"
        too_few = plan_scoped_activity_records(reader, "SMILES", activity_column="IC50")
        assert too_few.blocked_by is ScopeBlocker.TOO_FEW_ACTIVITY
    finally:
        mols.close()
