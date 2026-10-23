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

from molmanager.workers.load_render import Render2DBatchProcessWorker
from molmanager.workers.render2d_plan import PriorityRenderPlan

_BASE = (242, 202)
_ZOOM = (484, 404)


def _plan(rows, *, batch_size=4, priority_batch_size=2) -> PriorityRenderPlan:
    return PriorityRenderPlan(
        [(oid, b"", *size) for oid, size in rows],
        batch_size=batch_size,
        priority_batch_size=priority_batch_size,
        want_scenes=True,
    )


def _drain(plan: PriorityRenderPlan) -> list[tuple[list[int], tuple[int, int]]]:
    return [([oid for oid, _b in rows], (w, h)) for rows, w, h, _s in iter(plan.next_task, None)]


def test_rows_go_out_in_table_order_without_a_priority() -> None:
    plan = _plan([(oid, _BASE) for oid in range(6)])
    assert _drain(plan) == [([0, 1, 2, 3], _BASE), ([4, 5], _BASE)]
    assert len(plan) == 0


def test_prioritized_rows_go_first_in_small_tasks() -> None:
    plan = _plan([(oid, _BASE) for oid in range(10)])
    plan.prioritize([7, 8, 9])
    assert _drain(plan) == [
        ([7, 8], _BASE),
        ([9], _BASE),
        ([0, 1, 2, 3], _BASE),
        ([4, 5, 6], _BASE),
    ]


def test_a_new_priority_replaces_the_old_one_and_skips_drawn_rows() -> None:
    plan = _plan([(oid, _BASE) for oid in range(8)])
    plan.prioritize([5, 6])
    assert plan.next_task()[0] == [(5, b""), (6, b"")]
    plan.prioritize([6, 2, 3])
    assert _drain(plan) == [([2, 3], _BASE), ([0, 1, 4, 7], _BASE)]


def test_sizes_stay_separate_and_follow_table_order() -> None:
    plan = _plan([(1, _BASE), (2, _ZOOM), (3, _BASE), (4, _ZOOM)], batch_size=64)
    plan.prioritize([2, 3, 4])
    assert _drain(plan) == [([2, 4], _ZOOM), ([3], _BASE), ([1], _BASE)]


def test_worker_applies_a_priority_set_before_it_starts() -> None:
    items = [(oid, None, *_BASE) for oid in range(5)]
    worker = Render2DBatchProcessWorker(items, signals=None, cancel_event=None, batch_session=1)
    worker.prioritize([4])
    plan = worker.build_plan()
    plan.prioritize(worker._priority_request)
    assert plan.next_task()[0] == [(4, b"")]


class _SessionApp:
    """Stand-in for a window whose session is waiting on the Structure render."""

    def __init__(self, visible_oids: list[int], batch_oids: set[int]) -> None:
        from types import SimpleNamespace

        from molmanager.ui.main_window.render2d_results_mixin import Render2DResultsMixin

        self._release = Render2DResultsMixin._release_session_wait_when_viewport_drawn.__get__(self)
        self._session_waiting_for_render = True
        self._render2d_row_by_oid = {oid: oid for oid in batch_oids}
        self._render2d_landed_oids = set()
        self._table_model = SimpleNamespace(row_oid=lambda row: visible_oids[row])
        self._visible = list(range(len(visible_oids)))
        self.released = 0

    def _visible_structure_source_rows(self):
        return self._visible, set()

    def _session_on_render2d_batch_finished(self) -> None:
        self.released += 1
        self._session_waiting_for_render = False


def test_session_reveals_once_on_screen_rows_have_landed() -> None:
    app = _SessionApp(visible_oids=[1, 2, 3], batch_oids={1, 2, 3, 4, 5})
    app._release([(1, b"", True, 1, 1), (4, b"", True, 1, 1)])
    assert app.released == 0
    app._release([(2, b"", False, 1, 1), (3, b"", True, 1, 1)])
    assert app.released == 1


def test_rows_outside_the_batch_do_not_hold_the_session() -> None:
    app = _SessionApp(visible_oids=[1, 9], batch_oids={1, 2})
    app._release([(1, b"", True, 1, 1)])
    assert app.released == 1
