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

"""Zoom, resize and session reopen paint stored scenes without starting workers."""

from __future__ import annotations

from pathlib import Path

import pytest
from rdkit import Chem

from molmanager.chem.depiction_builder import build_scene
from molmanager.chem.depiction_scene import pack_scene
from molmanager.storage.session_structure_cache import write_structure_cache
from molmanager.storage.structure_render_store import StructureRenderStore
from molmanager.table import structure_depiction_layout as layout
from molmanager.ui.main_window import ChemistryWorkspaceWindow

SMILES = ["CCO", "c1ccccc1"]


def _scene(smiles: str) -> bytes:
    scene, _reason = build_scene(Chem.MolFromSmiles(smiles))
    return pack_scene(scene)


def _no_workers(window, monkeypatch) -> None:
    def fail(*_args, **_kwargs):
        raise AssertionError("a render worker was started")

    monkeypatch.setattr(window, "start_render_worker", fail)
    monkeypatch.setattr(window, "_start_render_2d_batch", fail)


@pytest.fixture
def window(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    store = StructureRenderStore()
    for oid, smiles in enumerate(SMILES):
        w._table_model.append_row(oid, {"SMILES": smiles})
        w.mols[oid] = Chem.MolFromSmiles(smiles)
        store.ingest_png(oid, _scene(smiles))
    w.next_oid = len(SMILES)
    w._table_model.set_structure_png_store(store)
    size = (layout.structure_depict_width(), layout.structure_depict_height())
    yield w
    layout.set_structure_depict_size(*size, persist=False)
    w.close()


def test_zoom_paints_the_scene_at_twice_the_size(window, monkeypatch) -> None:
    _no_workers(window, monkeypatch)
    w, h = layout.structure_depict_width(), layout.structure_depict_height()
    window.on_cell_double_click(0, 1)
    zoomed = window._table_model.structure_pixmap_for_oid(0)
    assert 0 in window.zoomed_ids
    assert (zoomed.width(), zoomed.height()) == (2 * w, 2 * h)
    window.on_cell_double_click(0, 1)
    restored = window._table_model.structure_pixmap_for_oid(0)
    assert 0 not in window.zoomed_ids
    assert (restored.width(), restored.height()) == (w, h)


def test_resize_repaints_scenes_without_rendering(window, monkeypatch) -> None:
    _no_workers(window, monkeypatch)
    window._table_model.structure_pixmap_for_oid(1)
    w, h = layout.structure_depict_width() + 40, layout.structure_depict_height() + 30
    layout.set_structure_depict_size(w, h, persist=False)
    window.rerender_structure_column_for_new_size()
    pm = window._table_model.structure_pixmap_for_oid(1)
    assert (pm.width(), pm.height()) == (w, h)


def test_resize_with_a_png_row_still_renders(window, monkeypatch) -> None:
    started = []
    monkeypatch.setattr(window, "_start_render_2d_batch", lambda *a, **k: started.append(a))
    window._table_model._structure_png_store.ingest_png(1, b"\x89PNG-not-a-scene")
    window.rerender_structure_column_for_new_size()
    assert started


def test_reopen_keeps_scenes_from_a_cache_at_another_size(
    window, monkeypatch, tmp_path: Path
) -> None:
    _no_workers(window, monkeypatch)
    session = tmp_path / "demo.cms"
    session.write_bytes(b"{}")
    store = window._table_model._structure_png_store
    store.ingest_png(2, b"\x89PNG-drawn-at-the-old-size")
    write_structure_cache(
        session,
        store.export_sqlite_bytes(),
        depict_width=10,
        depict_height=10,
        zoomed_ids=[1],
        oid_count=len(store),
    )
    window._table_model.clear_structure_png_store()
    window._session_source_path = str(session)
    window.zoomed_ids = {1}

    assert window._try_load_session_structure_cache()
    loaded = window._table_model._structure_png_store
    assert sorted(loaded.png_oids()) == [0, 1]
    zoomed = window._table_model.structure_pixmap_for_oid(1)
    assert zoomed.width() == 2 * layout.structure_depict_width()
