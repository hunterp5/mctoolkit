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

"""Qt-free view of table rows for workflows and services.

A :class:`TableReader` answers headers, row count, cell text, and structure by
oid. It does not know about widgets, selection, or dialogs. ``StoreTableReader``
reads a :class:`~molmanager.table.column_store.ColumnStore` plus the molecule
store. The live window adapts itself in ``ui/table_reader_view.py``.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from typing import Protocol

from ..chem.structure_payload import StructurePayload
from ..table.column_store import ColumnStore
from .activity_records import parse_activity_float


class StructureLookup(Protocol):
    """The molecule-store methods a table reader needs."""

    def structure_text_for(self, oid: int) -> str: ...

    def blob_for(self, oid: int) -> bytes | None: ...

    def structure_payloads_for(
        self, oids: Iterable[int]
    ) -> Iterator[tuple[int, bytes | None, str]]: ...

    def iter_structure_payloads(self) -> Iterator[tuple[int, bytes | None, str]]: ...


class TableReader(Protocol):
    """Row data a tool can read without the main window."""

    @property
    def headers(self) -> Sequence[str]: ...

    def row_count(self) -> int: ...

    def cell_text(self, row: int, column: int) -> str: ...

    def backing_text(self, row: int, header: str) -> str: ...

    def row_for_oid(self, oid: int) -> int: ...

    def oid_at(self, row: int) -> int: ...

    def is_pixmap_column(self, header: str) -> bool: ...

    def structure_text(self, oid: int) -> str: ...

    def structure_blob(self, oid: int) -> bytes | None: ...

    def structure_rows(self, oids: set[int] | None) -> dict[int, tuple[bytes | None, str]]: ...


class StoreTableReader:
    """Read-only view of a column store and an optional molecule store.

    Column 0 is the row oid, matching the hidden id column. Column 1 is the
    depiction and has no export text, matching ``_table_cell_text``. The row
    order is whatever the column store has when this reader is built.
    """

    def __init__(
        self,
        headers: Sequence[str],
        rows: ColumnStore,
        structures: StructureLookup | None = None,
    ) -> None:
        self._headers = tuple(headers)
        self._rows = rows
        self._structures = structures
        self._row_for_oid = {int(rows.oid_at(i)): i for i in range(rows.n)}

    @property
    def headers(self) -> Sequence[str]:
        return self._headers

    def row_count(self) -> int:
        return int(self._rows.n)

    def cell_text(self, row: int, column: int) -> str:
        if row < 0 or row >= self._rows.n or column < 0 or column >= len(self._headers):
            return ""
        if column == 1:
            return ""
        if column == 0:
            return str(self._rows.oid_at(row))
        return (self._rows.get_text(row, self._headers[column]) or "").strip()

    def backing_text(self, row: int, header: str) -> str:
        if row < 0 or row >= self._rows.n:
            return ""
        return (self._rows.get_text(row, header) or "").strip()

    def row_for_oid(self, oid: int) -> int:
        return self._row_for_oid.get(int(oid), -1)

    def oid_at(self, row: int) -> int:
        if row < 0 or row >= self._rows.n:
            return -1
        return int(self._rows.oid_at(row))

    def is_pixmap_column(self, header: str) -> bool:
        del header
        return False

    def structure_text(self, oid: int) -> str:
        if self._structures is None:
            return ""
        return (self._structures.structure_text_for(int(oid)) or "").strip()

    def structure_blob(self, oid: int) -> bytes | None:
        if self._structures is None:
            return None
        blob = self._structures.blob_for(int(oid))
        if not blob:
            return None
        return bytes(blob)

    def structure_rows(self, oids: set[int] | None) -> dict[int, tuple[bytes | None, str]]:
        """One molecule-store read for *oids*, or every stored row when *oids* is ``None``."""
        structures = self._structures
        if structures is None:
            return {}
        if oids is not None:
            rows = structures.structure_payloads_for(oids)
        else:
            rows = structures.iter_structure_payloads()
        return _structure_map(rows)


def activity_for_oid(
    reader: TableReader,
    oid: int,
    *,
    activity_column: str,
    activity_col_index: int | None = None,
) -> float | None:
    """Numeric activity for *oid*, from display text, then stored text."""
    row = reader.row_for_oid(int(oid))
    if row < 0:
        return None
    if activity_col_index is None:
        if activity_column not in reader.headers:
            return None
        column = reader.headers.index(activity_column)
    else:
        column = int(activity_col_index)
    raw = (reader.cell_text(row, column) or "").strip()
    if not raw:
        raw = (reader.backing_text(row, activity_column) or "").strip()
    return parse_activity_float(raw)


def cell_then_backing(reader: TableReader, row: int, header: str) -> str:
    """Display text for *header*, or the stored text when the display is blank."""
    if header not in reader.headers or row < 0:
        return ""
    text = (reader.cell_text(row, reader.headers.index(header)) or "").strip()
    if text:
        return text
    return (reader.backing_text(row, header) or "").strip()


def backing_then_cell(reader: TableReader, row: int, header: str) -> str:
    """Stored text for *header*, or the display text when nothing is stored."""
    if header not in reader.headers or row < 0:
        return ""
    text = (reader.backing_text(row, header) or "").strip()
    if text:
        return text
    return (reader.cell_text(row, reader.headers.index(header)) or "").strip()


def collect_structure_payloads(
    reader: TableReader,
    source: str,
    *,
    allowed_oids: set[int] | None = None,
    visible_rows: set[int] | None = None,
) -> list[StructurePayload]:
    """Structure snapshots in table order.

    ``source`` is ``"Structure"`` for the molecule store, or a data-column
    header. ``allowed_oids`` limits the rows. ``visible_rows`` limits them by
    source-row index. A ``"Structure"`` source loads the molecule store once
    via :meth:`TableReader.structure_rows`, then walks the table so the result
    stays in row order.
    """
    store_map = reader.structure_rows(allowed_oids) if source == "Structure" else None
    payloads: list[StructurePayload] = []
    for row in range(reader.row_count()):
        if visible_rows is not None and row not in visible_rows:
            continue
        oid = reader.oid_at(row)
        if oid < 0:
            continue
        if allowed_oids is not None and oid not in allowed_oids:
            continue
        payload = _payload_at(reader, row, oid, source, store_map)
        if payload is not None:
            payloads.append(payload)
    return payloads


def _structure_map(
    rows: Iterable[tuple[int, bytes | None, str]],
) -> dict[int, tuple[bytes | None, str]]:
    out: dict[int, tuple[bytes | None, str]] = {}
    for oid, blob, smiles in rows:
        out[int(oid)] = (bytes(blob) if blob else None, (smiles or "").strip())
    return out


def _payload_at(
    reader: TableReader,
    row: int,
    oid: int,
    source: str,
    store_map: dict[int, tuple[bytes | None, str]] | None,
) -> StructurePayload | None:
    if store_map is not None:
        blob, smiles = store_map.get(oid, (None, ""))
        if blob or smiles:
            return StructurePayload(oid, blob, smiles)
        return None
    raw = reader.backing_text(row, source)
    if raw or reader.is_pixmap_column(source):
        text = raw
    elif source in reader.headers:
        text = reader.cell_text(row, reader.headers.index(source))
    else:
        text = ""
    if not text:
        return None
    return StructurePayload(oid, None, text)
