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

"""Decide which scoped structure and activity records a tool may run on.

The result is either the record list or a blocker. ``ui/analysis_job_support.py``
maps the blocker to a dialog. This module does not import Qt.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..chem.structure_payload import StructurePayload
from ..services.activity_records import build_oid_mol_activity_records
from ..services.table_reader import TableReader, activity_for_oid, collect_structure_payloads


class ScopeBlocker(Enum):
    """Why a scoped structure or activity job cannot start."""

    NO_STRUCTURES = "no_structures"
    TOO_FEW_STRUCTURES = "too_few_structures"
    NO_ACTIVITY_CHOSEN = "no_activity_chosen"
    MISSING_ACTIVITY_COLUMN = "missing_activity_column"
    TOO_FEW_ACTIVITY = "too_few_activity"


@dataclass(frozen=True)
class ScopedStructureRecords:
    """Structure payloads for one job, or why the job should not start."""

    payloads: tuple[StructurePayload, ...] = ()
    blocked_by: ScopeBlocker | None = None
    min_count: int = 1

    @property
    def is_ready(self) -> bool:
        return self.blocked_by is None


@dataclass(frozen=True)
class ScopedActivityRecords:
    """``(oid, payload, activity)`` rows for one job, or why it should not start."""

    records: tuple[tuple[int, StructurePayload, float], ...] = ()
    blocked_by: ScopeBlocker | None = None
    activity_column: str = ""

    @property
    def is_ready(self) -> bool:
        return self.blocked_by is None


def plan_scoped_structure_records(
    reader: TableReader,
    source: str,
    *,
    allowed_oids: set[int] | None = None,
    min_count: int = 1,
) -> ScopedStructureRecords:
    """Collect structure snapshots, and refuse a job that does not have enough."""
    need = max(0, int(min_count))
    payloads = tuple(collect_structure_payloads(reader, source, allowed_oids=allowed_oids))
    if not payloads:
        return ScopedStructureRecords(blocked_by=ScopeBlocker.NO_STRUCTURES, min_count=need)
    if len(payloads) < need:
        return ScopedStructureRecords(
            payloads=payloads,
            blocked_by=ScopeBlocker.TOO_FEW_STRUCTURES,
            min_count=need,
        )
    return ScopedStructureRecords(payloads=payloads, min_count=need)


def plan_scoped_activity_records(
    reader: TableReader,
    source: str,
    *,
    activity_column: str,
    allowed_oids: set[int] | None = None,
    min_records: int = 2,
) -> ScopedActivityRecords:
    """Collect structures that have a numeric activity, or report why that failed.

    A column name that is blank or starts with ``(`` is the dialog placeholder
    for "no column chosen".
    """
    column = str(activity_column or "")
    if not column or column.startswith("("):
        return ScopedActivityRecords(
            blocked_by=ScopeBlocker.NO_ACTIVITY_CHOSEN,
            activity_column=column,
        )
    if column not in reader.headers:
        return ScopedActivityRecords(
            blocked_by=ScopeBlocker.MISSING_ACTIVITY_COLUMN,
            activity_column=column,
        )
    payloads = collect_structure_payloads(reader, source, allowed_oids=allowed_oids)
    paired = [(int(payload.oid), payload) for payload in payloads if payload.oid is not None]
    if not paired:
        return ScopedActivityRecords(
            blocked_by=ScopeBlocker.NO_STRUCTURES,
            activity_column=column,
        )
    column_index = reader.headers.index(column)
    records = build_oid_mol_activity_records(
        paired,
        activity_for_oid=lambda oid: activity_for_oid(
            reader,
            oid,
            activity_column=column,
            activity_col_index=column_index,
        ),
    )
    need = max(0, int(min_records))
    if len(records) < need:
        return ScopedActivityRecords(
            blocked_by=ScopeBlocker.TOO_FEW_ACTIVITY,
            activity_column=column,
        )
    return ScopedActivityRecords(records=tuple(records), activity_column=column)
