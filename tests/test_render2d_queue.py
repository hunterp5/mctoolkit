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
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

"""Render 2D can start while another serial tool (e.g. CONFORGE) is running."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

from molmanager.ui.main_window.render_2d_mixin import Render2DMixin
from molmanager.workers.load_render import Render2DBatchHeldJob, Render2DQueueBridge


class _QueueHost(Render2DMixin):
    def __init__(self, *, running_title: str | None) -> None:
        self._render2d_batch_active = False
        self.process_queue = MagicMock()
        self._begin_calls: list[tuple] = []
        if running_title:
            self.process_queue.has_running_job.return_value = True
            self.process_queue.snapshot.return_value = {
                "running": {"title": running_title},
                "queued": [],
            }
        else:
            self.process_queue.has_running_job.return_value = False
            self.process_queue.snapshot.return_value = {"running": None, "queued": []}

    def _begin_render2d_batch_impl(self, *args, **kwargs) -> None:
        self._begin_calls.append((args, kwargs))


def test_render2d_shares_ui_with_conforge_job() -> None:
    host = _QueueHost(running_title="CONFORGE conformations (10 structures)")
    assert host._render2d_shares_ui_with_queue_job() is True


def test_render2d_does_not_share_ui_when_queue_idle() -> None:
    host = _QueueHost(running_title=None)
    assert host._render2d_shares_ui_with_queue_job() is False


def test_render2d_does_not_share_ui_when_render_is_the_queue_job() -> None:
    host = _QueueHost(running_title="render 2D (100 rows)")
    assert host._render2d_shares_ui_with_queue_job() is False


def test_start_render2d_runs_off_queue_while_conforge_is_running() -> None:
    host = _QueueHost(running_title="CONFORGE conformations (4 structures)")
    renders = [(1, None, 100, 80)]
    host._start_render_2d_batch(renders, {1: 0}, "Structure")
    assert host._begin_calls
    assert host.process_queue.enqueue.call_count == 0
    args, kwargs = host._begin_calls[0]
    assert args[0] is renders
    assert kwargs.get("column_pixmap_mode") is True


def test_start_render2d_enqueues_when_queue_is_idle() -> None:
    host = _QueueHost(running_title=None)
    host._start_render_2d_batch([(1, None, 100, 80)], {1: 0}, "Structure")
    assert host._begin_calls == []
    host.process_queue.enqueue.assert_called_once()
    title, _factory = host.process_queue.enqueue.call_args.args
    assert title == "render 2D (1 rows)"


def test_run_render_2d_structures_allows_dialog_while_conforge_runs(qapp, monkeypatch) -> None:  # noqa: ARG001
    shown = {"n": 0}

    class _Dlg:
        def __init__(self, *_a, **_k) -> None:
            self.accepted = SimpleNamespace(connect=lambda *_a, **_k: None)

        def setAttribute(self, *_a, **_k) -> None:
            return None

        def show(self) -> None:
            shown["n"] += 1

    host = _QueueHost(running_title="CONFORGE conformations (10 structures)")
    host.headers = ["id", "Structure"]
    host._table_model = SimpleNamespace(rowCount=lambda: 2)
    host._selected_logical_rows = lambda: []
    host._prepare_tool_dialog = lambda *_a, **_k: None
    host.chemistry_tool_structure_sources = lambda: ["Structure"]
    import molmanager.ui.dialogs as dialogs_pkg

    monkeypatch.setattr(dialogs_pkg, "Render2DStructureDialog", _Dlg, raising=False)
    host.run_render_2d_structures()
    assert shown["n"] == 1


def _pump(qapp, predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    return bool(predicate())


def test_queued_render_job_passes_the_batch_record(qapp) -> None:  # noqa: ARG001
    host = _QueueHost(running_title=None)
    host._render2d_batch_done_event = threading.Event()
    host._render2d_queue_bridge = Render2DQueueBridge(lambda *_a: None, lambda: False)
    renders = [(1, None, 100, 80)]
    host._start_render_2d_batch(
        renders, {1: 0}, "Structure", column_pixmap_mode=False, merge_structure_store=True
    )
    _title, factory = host.process_queue.enqueue.call_args.args
    job = factory(threading.Event())
    assert job._payload == (renders, {1: 0}, "Structure", False, True)
    assert job._bridge is host._render2d_queue_bridge
    assert not hasattr(job, "_app")


def test_held_render_job_starts_through_the_bridge(qapp) -> None:
    started: dict = {}
    active = {"v": False}
    done = threading.Event()

    def begin(payload, cancel_event) -> None:
        started["payload"] = payload
        started["cancel"] = cancel_event
        active["v"] = True

    bridge = Render2DQueueBridge(begin, lambda: active["v"])
    payload = ([(1, "CCO")], {1: 0}, "Structure", True, False)
    cancel = threading.Event()
    job = Render2DBatchHeldJob(payload, bridge, cancel, done)
    thread = threading.Thread(target=job.run)
    thread.start()
    try:
        assert _pump(qapp, lambda: "payload" in started)
        assert started["payload"] is payload
        assert started["cancel"] is cancel
        done.set()
        assert _pump(qapp, lambda: not thread.is_alive())
    finally:
        done.set()
        thread.join(2)
    assert not thread.is_alive()


def test_held_render_job_releases_the_queue_when_the_batch_does_not_start(qapp) -> None:
    began = {"n": 0}
    done = threading.Event()

    def begin(*_args) -> None:
        began["n"] += 1

    bridge = Render2DQueueBridge(begin, lambda: False)
    job = Render2DBatchHeldJob(([], {}, "Structure", True, False), bridge, None, done)
    thread = threading.Thread(target=job.run)
    thread.start()
    try:
        assert _pump(qapp, lambda: not thread.is_alive())
    finally:
        done.set()
        thread.join(2)
    assert began["n"] == 1
    assert done.is_set()
    assert not thread.is_alive()


def test_held_render_job_skips_a_cancelled_batch() -> None:
    called = {"n": 0}
    bridge = Render2DQueueBridge(lambda *_a: called.__setitem__("n", 1), lambda: True)
    cancel = threading.Event()
    cancel.set()
    done = threading.Event()
    job = Render2DBatchHeldJob(([], {}, "Structure", True, False), bridge, cancel, done)
    job.run()
    assert called["n"] == 0
    assert not done.is_set()
