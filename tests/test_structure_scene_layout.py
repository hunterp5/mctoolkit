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

import pytest
from rdkit import Chem

from molmanager.chem.depiction_builder import build_scene
from molmanager.chem.depiction_scene import pack_scene
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


def test_resize_renders_only_rows_without_a_scene(window, monkeypatch) -> None:
    started = []
    monkeypatch.setattr(window, "_start_render_2d_batch", lambda *a, **k: started.append((a, k)))
    window._table_model._structure_png_store.remove_oid(1)
    window.rerender_structure_column_for_new_size()
    assert started
    renders, _row_by_oid, src = started[0][0][:3]
    assert src == "Structure"
    assert [item[0] for item in renders] == [1]
    assert started[0][1]["merge_structure_store"] is True
    assert window._table_model._structure_png_store.scene_oids() == {0}


def test_reopen_paints_saved_scenes_at_another_size(window, monkeypatch) -> None:
    from session_roundtrip import save_session_file

    window._table_model._structure_png_store.ingest_png(2, b"\x89PNG-drawn-at-the-old-size")
    window.zoomed_ids = {1}
    layout.set_structure_depict_size(10, 10, persist=False)
    session = save_session_file(window)
    layout.set_structure_depict_size(
        layout.structure_depict_width() + 90, layout.structure_depict_height() + 90, persist=False
    )
    reopened = ChemistryWorkspaceWindow()
    _no_workers(reopened, monkeypatch)
    try:
        assert reopened.apply_saved_session_from_file(str(session))
        loaded = reopened._table_model._structure_png_store
        assert sorted(loaded.png_oids()) == [0, 1]
        zoomed = reopened._table_model.structure_pixmap_for_oid(1)
        assert zoomed.width() == 2 * layout.structure_depict_width()
    finally:
        reopened.close()
