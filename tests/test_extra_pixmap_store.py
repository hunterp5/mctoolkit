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

from __future__ import annotations

from PyQt5.QtGui import QPixmap

from molmanager.storage.extra_pixmap_store import ExtraPixmapStore
from molmanager.ui.compound_table_model import CompoundTableModel


def test_extra_pixmap_store_lru_keeps_png_bytes(qapp):  # noqa: ARG001
    store = ExtraPixmapStore(max_decoded_pixmaps=2)
    pm = QPixmap(8, 8)
    pm.fill()
    store.set_pixmap(1, "Frag", pm)
    store.set_pixmap(2, "Frag", pm)
    store.set_pixmap(3, "Frag", pm)
    assert len(store) == 3
    assert store.pixmap(1, "Frag") is not None
    assert len(store._lru) <= 2
    store.copy_png((1, "Frag"), (1, "Copy"))
    assert store.pixmap(1, "Copy") is not None
    store.remove_header("Frag")
    assert store.pixmap(1, "Frag") is None
    assert store.pixmap(1, "Copy") is not None


def test_extra_pixmap_store_misses_skip_sqlite(qapp):  # noqa: ARG001
    store = ExtraPixmapStore()
    pm = QPixmap(8, 8)
    pm.fill()
    store.set_pixmap(1, "Frag", pm)
    store.set_pixmap(2, "Other", pm)
    statements: list[str] = []
    store._conn.set_trace_callback(statements.append)
    assert store.get((5, "Frag")) is None
    assert (5, "Frag") not in store
    assert statements == []
    store._conn.set_trace_callback(None)

    store.rename_header("Frag", "Renamed")
    assert (1, "Renamed") in store and (1, "Frag") not in store
    store.remove_oid(2)
    assert len(store) == 1
    store.pop((1, "Renamed"))
    assert len(store) == 0


def test_compound_table_extra_pixmap_roundtrip(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "Protonated"])
    model.append_row(1, {"Protonated": "CCO"})
    model.register_pixmap_column("Protonated")
    pix = QPixmap(12, 10)
    pix.fill()
    model.set_column_pixmap(1, "Protonated", pix)
    got = model.column_pixmap_copy(1, "Protonated")
    assert got is not None and not got.isNull()
    model.remove_column_at(2)
    assert model.column_pixmap_copy(1, "Protonated") is None
