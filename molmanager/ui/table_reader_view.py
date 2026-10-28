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

"""Live :class:`~molmanager.services.table_reader.TableReader` over the open window.

This is a view. It does not copy rows. Cell text, backing text, and oid lookup
delegate to the methods the tools already use.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


class WindowTableReader:
    """Read the window's current table without copying it."""

    def __init__(self, app: Any) -> None:
        self._app = app

    @property
    def headers(self) -> Sequence[str]:
        return self._app.headers

    def row_count(self) -> int:
        return int(self._app._table_model.rowCount())

    def cell_text(self, row: int, column: int) -> str:
        return (self._app._table_cell_text(row, column) or "").strip()

    def backing_text(self, row: int, header: str) -> str:
        return (self._app._table_model.backing_value_for_row_header(row, header) or "").strip()

    def row_for_oid(self, oid: int) -> int:
        return int(self._app.logical_row_for_oid(int(oid)))

    def oid_at(self, row: int) -> int:
        return int(self._app._table_model.row_oid(row))

    def is_pixmap_column(self, header: str) -> bool:
        query = getattr(self._app._table_model, "is_pixmap_data_column", None)
        if not callable(query):
            return False
        return bool(query(header))

    def structure_text(self, oid: int) -> str:
        mols = getattr(self._app, "mols", None)
        text_for = getattr(mols, "structure_text_for", None)
        if not callable(text_for):
            return ""
        return (text_for(int(oid)) or "").strip()

    def structure_blob(self, oid: int) -> bytes | None:
        mols = getattr(self._app, "mols", None)
        blob_for = getattr(mols, "blob_for", None)
        if not callable(blob_for):
            return None
        blob = blob_for(int(oid))
        if not blob:
            return None
        return bytes(blob)

    def structure_rows(self, oids: set[int] | None) -> dict[int, tuple[bytes | None, str]]:
        """One molecule-store query for the selected ids, or a full scan when unscoped."""
        mols = getattr(self._app, "mols", None)
        if mols is None:
            return {}
        if oids is not None:
            scoped = getattr(mols, "structure_payloads_for", None)
            if callable(scoped):
                rows: Iterable[tuple[int, bytes | None, str]] = scoped(oids)
            else:
                rows = _mapping_structure_rows(mols, oids)
        else:
            scan = getattr(mols, "iter_structure_payloads", None)
            if callable(scan):
                rows = scan()
            else:
                rows = _mapping_structure_rows(mols, None)
        out: dict[int, tuple[bytes | None, str]] = {}
        for oid, blob, smiles in rows:
            out[int(oid)] = (bytes(blob) if blob else None, (smiles or "").strip())
        return out


def _mapping_structure_rows(
    mols: Any, oids: set[int] | None
) -> list[tuple[int, bytes | None, str]]:
    """Pickles from a dict-like molecule store that has no batch query."""
    keys = list(mols) if oids is None else [oid for oid in oids if oid in mols]
    rows: list[tuple[int, bytes | None, str]] = []
    for oid in keys:
        mol = mols.get(oid)
        if mol is None:
            continue
        try:
            blob = mol.ToBinary()
        except (AttributeError, RuntimeError):
            continue
        rows.append((int(oid), bytes(blob) if blob else None, ""))
    return rows
