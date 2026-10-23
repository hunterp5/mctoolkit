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

from __future__ import annotations

from molmanager.storage.structure_render_store import StructureRenderStore


def test_structure_render_store_ingest_remove_and_trim():
    store = StructureRenderStore(max_decoded_pixmaps=4)
    store.ingest_batch([(1, b"a"), (2, b"b"), (3, b"c")])
    assert len(store) == 3
    assert store.has_png(2)
    store.remove_oid(2)
    assert not store.has_png(2)
    store.trim_decoded_cache(keep_oids={1})
    assert len(store._lru) == 0


def test_structure_render_store_evicts_oldest_png_when_capped():
    store = StructureRenderStore(max_decoded_pixmaps=8, max_png_entries=3)
    for i in range(1, 5):
        store.ingest_png(i, str(i).encode())
    assert len(store) == 3
    assert list(store._png.keys()) == [2, 3, 4]


def test_structure_render_store_batch_expands_cap_to_fit():
    store = StructureRenderStore(max_decoded_pixmaps=8, max_png_entries=3)
    items = [(i, str(i).encode()) for i in range(1, 6)]
    store.ingest_batch(items)
    assert len(store) == 5
    assert store.has_png(1) and store.has_png(5)


def test_batch_replaces_existing_rows_and_keeps_the_count() -> None:
    store = StructureRenderStore(max_decoded_pixmaps=8)
    store.ingest_batch([(1, b"a"), (2, b"b")])
    store.ingest_batch([(2, b"B"), (3, b"c"), (3, b"C")])
    assert len(store) == 3
    assert store._png == {1: b"a", 2: b"B", 3: b"C"}
