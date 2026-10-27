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

"""Batched 2D render: child-process task shape, worker sizing, and the batched GUI handler."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.platform_support.config import load_config
from molmanager.workers.load_render import (
    Render2DBatchProcessWorker,
    _mp_render_structure_batch,
    render2d_process_worker_count,
)

SMILES = ["CCO", "c1ccccc1", "CC(=O)Oc1ccccc1C(=O)O"]


def test_batch_render_returns_png_per_row() -> None:
    items = [(i, Chem.MolFromSmiles(s).ToBinary()) for i, s in enumerate(SMILES)]
    rows = _mp_render_structure_batch((items, 242, 202))
    assert len(rows) == len(items)
    for (oid, png, ok, w, h), (exp_oid, _blob) in zip(rows, items):
        assert oid == exp_oid
        assert ok is True
        assert png.startswith(b"\x89PNG")
        assert (w, h) == (242, 202)


def test_batch_render_marks_bad_rows_without_dropping_them() -> None:
    items = [(1, b""), (2, Chem.MolFromSmiles("CCO").ToBinary()), (3, b"not a mol")]
    rows = _mp_render_structure_batch((items, 100, 80))
    # Row order and count must be preserved so progress accounting stays correct.
    assert [r[0] for r in rows] == [1, 2, 3]
    assert [r[2] for r in rows] == [False, True, False]
    assert all(r[3:] == (100, 80) for r in rows)


def test_batch_render_honors_requested_size() -> None:
    items = [(0, Chem.MolFromSmiles("CCO").ToBinary())]
    small = _mp_render_structure_batch((items, 120, 100))[0]
    large = _mp_render_structure_batch((items, 484, 404))[0]
    assert small[3:] == (120, 100)
    assert large[3:] == (484, 404)
    assert len(large[1]) > len(small[1])


def test_scene_mode_returns_scenes_and_png_only_for_fallbacks() -> None:
    from molmanager.chem.depiction_scene import is_scene_blob, unpack_scene
    from molmanager.chem.render2d_mp import REACTION_PAYLOAD_TAG

    items = [
        (1, Chem.MolFromSmiles("CCO").ToBinary()),
        (2, Chem.MolFromSmiles("[CH3]").ToBinary()),
        (3, (REACTION_PAYLOAD_TAG, b"CC>>CO")),
        (4, b""),
    ]
    rows = _mp_render_structure_batch((items, 210, 170, True))
    assert [len(r) for r in rows] == [5, 5, 5, 5]
    scene_row, radical_row, reaction_row, empty_row = rows
    assert scene_row[2] is True and is_scene_blob(scene_row[1])
    assert unpack_scene(scene_row[1]) is not None
    for row in (radical_row, reaction_row):
        assert row[1].startswith(b"\x89PNG") and not is_scene_blob(row[1])
    assert empty_row[2] is False


def test_scene_mode_off_draws_pngs() -> None:
    items = [(0, Chem.MolFromSmiles("CCO").ToBinary())]
    (row,) = _mp_render_structure_batch((items, 210, 170, False))
    assert row[1].startswith(b"\x89PNG")


def test_worker_count_respects_env_override(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_PROCESS_WORKERS", "3")
    assert render2d_process_worker_count() == 3
    monkeypatch.delenv("MOLMANAGER_RENDER2D_PROCESS_WORKERS")
    assert render2d_process_worker_count() >= 2


def test_batch_size_default_is_greater_than_one() -> None:
    # One molecule per task made the parent process the throughput ceiling.
    assert load_config().render2d_batch_size > 1


def _worker(items):
    return Render2DBatchProcessWorker(items, signals=None, cancel_event=None, batch_session=1)


def test_build_tasks_batches_rows_and_covers_every_oid(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_BATCH_SIZE", "4")
    mol = Chem.MolFromSmiles("CCO")
    items = [(oid, mol, 242, 202) for oid in range(10)]
    tasks = _worker(items).build_tasks()
    assert [len(rows) for rows, _w, _h, _scenes in tasks] == [4, 4, 2]
    assert sorted(oid for rows, _w, _h, _scenes in tasks for oid, _b in rows) == list(range(10))
    assert all((w, h) == (242, 202) for _rows, w, h, _scenes in tasks)


def test_build_tasks_keeps_zoomed_rows_in_their_own_size_group(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_RENDER2D_BATCH_SIZE", "64")
    mol = Chem.MolFromSmiles("CCO")
    items = [(1, mol, 242, 202), (2, mol, 484, 404), (3, mol, 242, 202)]
    tasks = _worker(items).build_tasks()
    sizes = {(w, h): [oid for oid, _b in rows] for rows, w, h, _scenes in tasks}
    assert sizes == {(242, 202): [1, 3], (484, 404): [2]}


def test_build_tasks_emits_empty_blob_for_missing_mol() -> None:
    tasks = _worker([(1, None, 242, 202)]).build_tasks()
    assert tasks == [([(1, b"")], 242, 202, False)]


def test_build_tasks_pass_the_scene_request() -> None:
    worker = Render2DBatchProcessWorker(
        [(1, None, 242, 202)], signals=None, cancel_event=None, batch_session=1, want_scenes=True
    )
    assert worker.build_tasks() == [([(1, b"")], 242, 202, True)]


def test_build_tasks_tags_reaction_smarts() -> None:
    from molmanager.chem.structure_2d_depiction import ReactionDrawSpec

    spec = ReactionDrawSpec("[C:1]>>[C:1]")
    tasks = _worker([(7, spec, 630, 170)]).build_tasks()
    assert len(tasks) == 1
    rows, w, h, _scenes = tasks[0]
    assert (w, h) == (630, 170)
    assert rows == [(7, ("rxn", b"[C:1]>>[C:1]"))]


def test_batch_render_reaction_smarts() -> None:
    items = [(1, ("rxn", b"[C:1](=[O:2])-[OH].[N]>>[C:1](=[O:2])-[N]"))]
    rows = _mp_render_structure_batch((items, 630, 170))
    assert len(rows) == 1
    oid, png, ok, w, h = rows[0]
    assert oid == 1
    assert ok is True
    assert png.startswith(b"\x89PNG")
    assert (w, h) == (630, 170)
    assert int.from_bytes(png[16:20], "big") == 630
    assert int.from_bytes(png[20:24], "big") == 170


def test_build_tasks_stops_when_cancelled() -> None:
    import threading

    ev = threading.Event()
    ev.set()
    worker = Render2DBatchProcessWorker(
        [(1, Chem.MolFromSmiles("CCO"), 242, 202)],
        signals=None,
        cancel_event=ev,
        batch_session=1,
    )
    assert worker.build_tasks() == []


class _App:
    """Minimal stand-in exposing only what the batched render handler touches."""

    def __init__(self, rows_in_table: set[int], goal: int):
        from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

        self._rows = rows_in_table
        self._render2d_pending: dict = {}
        self._render2d_accept_session = 7
        self._render2d_batch_active = True
        self._import_progress_active = True
        self._import_render_goal = goal
        self._import_render_done = 0
        self.progress: list[tuple[str, int, int]] = []
        self.flushed = False
        self.restored = False
        self.status_label = type("L", (), {"setText": lambda _s, _t: None})()
        self._cls = Render2DResultsMixin

    # Bound mixin methods under test.
    def _render2d_batch_session_accepted(self, s):
        return self._cls._render2d_batch_session_accepted(self, s)

    def on_render2d_rows_ready(self, rows, s):
        return self._cls.on_render2d_rows_ready(self, rows, s)

    def _advance_render2d_batch_progress(self, n):
        return self._cls._advance_render2d_batch_progress(self, n)

    def _resolve_structure_row_for_oid(self, oid):
        return 0 if oid in self._rows else -1

    def _on_tool_progress(self, msg, done, total):
        self.progress.append((msg, done, total))

    def _clear_tool_progress(self):
        pass

    def _flush_render2d_batch_results(self):
        self.flushed = True

    def _restore_render2d_batch_environment(self):
        self.restored = True


def _png_rows(oids):
    blob = Chem.MolFromSmiles("CCO").ToBinary()
    return _mp_render_structure_batch(([(o, blob) for o in oids], 242, 202))


def test_batched_handler_streams_scenes_and_drops_png_fallbacks() -> None:
    from molmanager.chem.depiction_scene import is_scene_blob
    from molmanager.storage.structure_render_store import StructureRenderStore
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    items = [
        (1, Chem.MolFromSmiles("CCO").ToBinary()),
        (2, Chem.MolFromSmiles("[CH3]").ToBinary()),
    ]
    rows = _mp_render_structure_batch((items, 210, 170, True))
    app = _App(rows_in_table={1, 2}, goal=4)
    store = StructureRenderStore(max_decoded_pixmaps=4, max_png_entries=0)
    try:
        app._render2d_stream_store = store
        app._render2d_pixmap_target = None
        app._render2d_flush_max_width = 0
        app._render2d_write_png_rows = lambda ready: Render2DResultsMixin._render2d_write_png_rows(
            app, ready
        )
        app.on_render2d_rows_ready(rows, 7)
        assert app._render2d_pending == {}
        assert is_scene_blob(store.png_bytes(1))
        assert store.png_bytes(2) is None
        assert app._import_render_done == 2
        assert not app.flushed
    finally:
        store.close()


def test_worker_count_caps_by_available_ram(monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_RENDER2D_PROCESS_WORKERS", raising=False)
    monkeypatch.setattr(
        "molmanager.platform_support.memory_usage.available_physical_bytes",
        lambda: 96 * 1024 * 1024,
    )
    assert render2d_process_worker_count() == 2


def test_batched_handler_stores_results_and_finishes_batch() -> None:
    app = _App(rows_in_table={1, 2, 3, 4}, goal=4)
    app.on_render2d_rows_ready(_png_rows([1, 2]), 7)
    assert set(app._render2d_pending) == {1, 2}
    assert app._render2d_pending[1][1] is True
    assert not app.flushed

    app.on_render2d_rows_ready(_png_rows([3, 4]), 7)
    assert app._import_render_done == 4
    assert app.flushed and app.restored
    assert app.progress[-1] == ("Render 2D", 4, 4)


def test_batched_handler_ignores_superseded_session() -> None:
    app = _App(rows_in_table={1}, goal=1)
    app.on_render2d_rows_ready(_png_rows([1]), 999)
    assert app._render2d_pending == {}
    assert app._import_render_done == 0
    assert not app.flushed


def test_batched_handler_marks_rows_missing_from_table_as_failed() -> None:
    app = _App(rows_in_table=set(), goal=2)
    app.on_render2d_rows_ready(_png_rows([1, 2]), 7)
    assert app._render2d_pending[1] == (b"", False, 242, 202)
    assert app._import_render_done == 2


def test_batched_handler_does_not_steal_progress_when_sharing_queue_job() -> None:
    app = _App(rows_in_table={1}, goal=1)
    app._render2d_shares_ui_with_queue_job = lambda: True
    app.cleared = False
    app._clear_tool_progress = lambda: setattr(app, "cleared", True)
    texts: list[str] = []
    app.status_label = type("L", (), {"setText": lambda _s, t: texts.append(t)})()
    app.on_render2d_rows_ready(_png_rows([1]), 7)
    assert app.flushed and app.restored
    assert app.progress == []
    assert app.cleared is False
    assert texts == []


@pytest.mark.parametrize("rows", [[], None])
def test_batched_handler_tolerates_empty_payload(rows) -> None:
    app = _App(rows_in_table={1}, goal=1)
    app.on_render2d_rows_ready(rows, 7)
    assert app._render2d_pending == {}
    assert app._import_render_done == 0


def test_lazy_scroll_trims_cache_without_data_changed() -> None:
    from molmanager.storage.structure_render_store import StructureRenderStore
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    for oid in range(1, 6):
        model.append_row(oid, {"SMILES": "C"})
    store = StructureRenderStore(max_decoded_pixmaps=8)
    store.ingest_batch([(oid, b"png") for oid in range(1, 6)])
    model.set_structure_png_store(store)
    for oid in range(1, 6):
        store._lru[oid] = object()  # type: ignore[assignment]

    class _Viewport:
        def height(self) -> int:
            return 40

    class _View:
        def rowAt(self, y: int) -> int:
            return 0 if y == 0 else 1

        def viewport(self) -> _Viewport:
            return _Viewport()

        def model(self):
            return model

    class _Host(Render2DResultsMixin):
        def __init__(self) -> None:
            self._table_model = model
            self.table = _View()
            self._structure_lazy_scroll_hooked = True

    host = _Host()
    changes: list[object] = []
    model.dataChanged.connect(lambda *_a: changes.append(1))
    host._on_structure_lazy_scroll()
    assert changes == []
    assert set(store._lru) == {1, 2}


def test_refresh_visible_structure_cells_notifies_once() -> None:
    from molmanager.storage.structure_render_store import StructureRenderStore
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "C"})
    store = StructureRenderStore(max_decoded_pixmaps=8)
    store.ingest_png(1, b"png")
    model.set_structure_png_store(store)

    class _Viewport:
        def height(self) -> int:
            return 40

    class _View:
        def rowAt(self, _y: int) -> int:
            return 0

        def viewport(self) -> _Viewport:
            return _Viewport()

        def model(self):
            return model

    class _Host(Render2DResultsMixin):
        def __init__(self) -> None:
            self._table_model = model
            self.table = _View()

    host = _Host()
    changes: list[object] = []
    model.dataChanged.connect(lambda *_a: changes.append(1))
    host._refresh_visible_structure_cells()
    assert changes == [1]


class _WidthTable:
    def __init__(self) -> None:
        self._width = 40
        self.widths: list[tuple[int, int]] = []

    def columnWidth(self, _col: int) -> int:
        return self._width

    def setColumnWidth(self, col: int, width: int) -> None:
        self._width = int(width)
        self.widths.append((int(col), int(width)))


def _column_app(rows_in_table: set[int], goal: int):
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    app = _App(rows_in_table, goal)
    app.table = _WidthTable()
    app._render2d_pixmap_target = None
    app._render2d_flush_max_width = 0
    app._render2d_column_widened_to = 0
    app._pending_session_table_layout = None
    app._render2d_keeps_session_layout = False
    app._widen_render2d_column_for_first_structure = lambda: (
        Render2DResultsMixin._widen_render2d_column_for_first_structure(app)
    )
    app._apply_render2d_column_width = lambda target, hint: (
        Render2DResultsMixin._apply_render2d_column_width(app, target, hint)
    )
    return app


def test_column_widens_when_the_first_structure_is_stored() -> None:
    from molmanager.storage.structure_render_store import StructureRenderStore
    from molmanager.table.structure_depiction_layout import (
        STRUCTURE_COLUMN_HORIZONTAL_PADDING,
        structure_depict_width,
    )
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    items = [
        (1, Chem.MolFromSmiles("CCO").ToBinary()),
        (2, Chem.MolFromSmiles("CCC").ToBinary()),
    ]
    rows = _mp_render_structure_batch((items, 210, 170, True))
    app = _column_app({1, 2}, goal=2)
    store = StructureRenderStore(max_decoded_pixmaps=4, max_png_entries=0)
    try:
        app._render2d_stream_store = store
        app._render2d_write_png_rows = lambda ready: Render2DResultsMixin._render2d_write_png_rows(
            app, ready
        )
        app.on_render2d_rows_ready(rows[:1], 7)
        expected = max(structure_depict_width(), 210) + STRUCTURE_COLUMN_HORIZONTAL_PADDING
        assert app.table.widths == [(1, expected)]
        assert not app.flushed
        app.on_render2d_rows_ready(rows[1:], 7)
        assert app.table.widths == [(1, expected)]
    finally:
        store.close()


def test_column_stays_put_while_a_session_layout_is_pending() -> None:
    from molmanager.storage.structure_render_store import StructureRenderStore
    from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

    rows = _mp_render_structure_batch(([(1, Chem.MolFromSmiles("CCO").ToBinary())], 210, 170, True))
    app = _column_app({1}, goal=2)
    app._render2d_keeps_session_layout = True
    store = StructureRenderStore(max_decoded_pixmaps=4, max_png_entries=0)
    try:
        app._render2d_stream_store = store
        app._render2d_write_png_rows = lambda ready: Render2DResultsMixin._render2d_write_png_rows(
            app, ready
        )
        app.on_render2d_rows_ready(rows, 7)
        assert app.table.widths == []
        assert app.table.columnWidth(1) == 40
    finally:
        store.close()
