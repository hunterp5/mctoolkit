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

"""Serial queue for long-running tool jobs (conformers, descriptors, export, load, …)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from PyQt5.QtCore import QMetaObject, QObject, QRunnable, Qt, QThreadPool, pyqtSignal, pyqtSlot

logger = logging.getLogger(__name__)


@dataclass
class _QueuedJob:
    job_id: str
    title: str
    factory: Callable[[threading.Event], QRunnable]
    enqueued_at: float


class ProcessQueueManager(QObject):
    """
    Runs at most one queued tool job at a time on a **dedicated** single-thread pool (not
    ``app.threadpool``), so substructure filters, renders, and other pool users cannot interleave
    with the queue runner or reorder completion relative to cancellation.

    Jobs are built with ``factory(cancel_event)`` so cooperative cancellation can be wired per task.
    """

    snapshot_changed = pyqtSignal()
    thread_finished = pyqtSignal(str)
    fast_thread_finished = pyqtSignal(str)

    def __init__(self, app: Any) -> None:
        super().__init__(app)
        self._app = app
        self._queue: deque[_QueuedJob] = deque()
        self._busy = False
        self._current_job_id: str | None = None
        self._current_title: str | None = None
        self._current_started_at: float | None = None
        self._running_cancel: threading.Event | None = None
        self.thread_finished.connect(self._on_job_thread_finished, Qt.QueuedConnection)
        self.fast_thread_finished.connect(self._on_fast_job_thread_finished, Qt.QueuedConnection)
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._fast_pool = QThreadPool(self)
        self._fast_pool.setMaxThreadCount(2)
        self._fast_running: dict[str, dict[str, Any]] = {}

    def _threadpool(self) -> QThreadPool:
        return self._pool

    def _fast_threadpool(self) -> QThreadPool:
        return self._fast_pool

    def has_running_job(self) -> bool:
        return bool(self._busy)

    def has_pending_jobs(self) -> bool:
        return bool(self._queue)

    def has_outstanding_work(self) -> bool:
        """True when a queued tool is running, waiting, or on the fast lane."""
        return self.has_running_job() or self.has_pending_jobs() or bool(self._fast_running)

    def is_blocked_by_external_activity(self) -> bool:
        """True when Render 2D is running outside the current queue job (legacy parallel path)."""
        fn = getattr(self._app, "render2d_batch_active", None)
        if callable(fn) and fn():
            return not self._busy
        return False

    def schedule_resume(self) -> None:
        """Try to start the next queued job after external activity completes."""
        self._maybe_start_next()

    def enqueue(
        self,
        title: str,
        factory: Callable[[threading.Event], QRunnable],
        *,
        job_id: str | None = None,
    ) -> str:
        """Queue a job; returns job id. ``factory`` receives a fresh cancel event for this run.

        Pass *job_id* when tool progress was already begun for that id so the Log row
        and progress slot stay aligned from the first tick.
        """
        jid = str(job_id) if job_id else str(uuid.uuid4())[:8]
        self._queue.append(
            _QueuedJob(
                job_id=jid,
                title=title.strip() or "Job",
                factory=factory,
                enqueued_at=time.monotonic(),
            )
        )
        self.snapshot_changed.emit()
        self._maybe_start_next()
        return jid

    def enqueue_fast(
        self,
        title: str,
        factory: Callable[[threading.Event], QRunnable],
        *,
        job_id: str | None = None,
    ) -> str:
        """Start an interactive job on a separate small pool (does not block heavy queue)."""
        if (
            self.has_running_job()
            or self.has_pending_jobs()
            or self.is_blocked_by_external_activity()
        ):
            return self.enqueue(title, factory, job_id=job_id)
        jid = str(job_id) if job_id else str(uuid.uuid4())[:8]
        cancel_ev = threading.Event()
        try:
            inner = factory(cancel_ev)
        except Exception:
            logger.exception("Fast job factory failed (job_id=%s)", jid)
            return jid
        self._fast_running[jid] = {
            "title": title.strip() or "Interactive job",
            "cancel": cancel_ev,
            "started_at": time.monotonic(),
        }
        self.snapshot_changed.emit()
        self._fast_threadpool().start(_FastQueueJobRunner(self, jid, inner))
        return jid

    def cancel_fast_job(self, job_id: str) -> bool:
        info = self._fast_running.get(job_id)
        if not info:
            return False
        ev = info.get("cancel")
        if not isinstance(ev, threading.Event) or ev.is_set():
            return False
        ev.set()
        self.snapshot_changed.emit()
        return True

    def cancel_running(self) -> bool:
        """Cooperatively cancel the currently running job, if any. Returns True if a cancel was signaled.

        Does **not** remove jobs still waiting in ``_queue``; only ``clear_queued`` does that.
        """
        ev = self._running_cancel
        if ev is None or ev.is_set():
            return False
        ev.set()
        self.snapshot_changed.emit()
        return True

    def queued_job_count(self) -> int:
        """Number of jobs waiting to start (excludes the job currently running, if any)."""
        return len(self._queue)

    def wait_for_all_jobs(self, msec: int = 60000) -> bool:
        """Wait until no queued-tool runner is active on the internal pool (mainly for tests)."""
        ok_heavy = self._pool.waitForDone(msec)
        ok_fast = self._fast_pool.waitForDone(msec)
        return bool(ok_heavy and ok_fast)

    def shutdown_for_exit(self) -> None:
        """Cancel queued/running jobs and kill any active process-pool children (window close)."""
        from molmanager.workers.process_pool_utils import (
            shutdown_all_process_pools,
            signal_application_shutdown,
        )

        signal_application_shutdown()
        self.clear_queued()
        for info in list(self._fast_running.values()):
            ev = info.get("cancel")
            if isinstance(ev, threading.Event):
                ev.set()
        ev = self._running_cancel
        if ev is not None and not ev.is_set():
            ev.set()
        shutdown_all_process_pools(kill_workers=True)
        self._pool.clear()
        self._fast_pool.clear()
        self._pool.waitForDone(500)
        self._fast_pool.waitForDone(500)

    def clear_queued(self) -> int:
        """Remove all jobs waiting in the queue (not the running job). Returns number removed."""
        n = len(self._queue)
        self._queue.clear()
        if n:
            self.snapshot_changed.emit()
        return n

    def remove_queued_job(self, job_id: str) -> bool:
        """Remove a single waiting job by id. Returns True if a job was removed."""
        for i, job in enumerate(self._queue):
            if job.job_id == job_id:
                del self._queue[i]
                self.snapshot_changed.emit()
                return True
        return False

    def snapshot(self) -> dict[str, Any]:
        """Serializable view for the Processes dialog."""
        queued = [
            {
                "job_id": j.job_id,
                "title": j.title,
                "status": "Queued",
                "enqueued_at": j.enqueued_at,
            }
            for j in self._queue
        ]
        running = None
        if self._busy and self._current_job_id:
            running = {
                "job_id": self._current_job_id,
                "title": self._current_title or "",
                "status": "Running",
                "cancellable": self._running_cancel is not None
                and not self._running_cancel.is_set(),
                "started_at": self._current_started_at,
            }
        fast_running = []
        for jid, info in self._fast_running.items():
            ev = info.get("cancel")
            if isinstance(ev, threading.Event) and not ev.is_set():
                fast_running.append(
                    {
                        "job_id": jid,
                        "title": str(info.get("title") or "Interactive job"),
                        "status": "Running",
                        "cancellable": True,
                        "started_at": info.get("started_at"),
                    }
                )
        return {"running": running, "queued": queued, "fast_running": fast_running}

    @pyqtSlot()
    def _enter_app_background_ui(self) -> None:
        """GUI-thread: slow the progress poll while a queued job holds a pool thread."""
        fn = getattr(self._app, "_enter_background_job_ui", None)
        if callable(fn):
            fn()

    @pyqtSlot()
    def _exit_app_background_ui(self) -> None:
        """GUI-thread: restore the progress poll interval after the queued job returns."""
        fn = getattr(self._app, "_exit_background_job_ui", None)
        if callable(fn):
            fn()

    @pyqtSlot(str)
    def _on_job_thread_finished(self, job_id: str) -> None:
        if self._current_job_id != job_id:
            return
        self._busy = False
        self._current_job_id = None
        self._current_title = None
        self._current_started_at = None
        self._running_cancel = None
        self.snapshot_changed.emit()
        self._maybe_start_next()

    def _maybe_start_next(self) -> None:
        if self._busy or not self._queue:
            return
        if self.is_blocked_by_external_activity():
            return
        job = self._queue.popleft()
        cancel_ev = threading.Event()
        self._busy = True
        self._current_job_id = job.job_id
        self._current_title = job.title
        self._current_started_at = time.monotonic()
        self._running_cancel = cancel_ev
        try:
            inner = job.factory(cancel_ev)
        except Exception:
            logger.exception("Job factory failed (job_id=%s)", job.job_id)
            self._busy = False
            self._current_job_id = None
            self._current_title = None
            self._current_started_at = None
            self._running_cancel = None
            self.snapshot_changed.emit()
            self._maybe_start_next()
            return
        self.snapshot_changed.emit()
        self._threadpool().start(_QueueJobRunner(self, job.job_id, inner))

    @pyqtSlot(str)
    def _on_fast_job_thread_finished(self, job_id: str) -> None:
        self._fast_running.pop(job_id, None)
        self.snapshot_changed.emit()


class _QueueJobRunner(QRunnable):
    """Runs one inner QRunnable on the pool thread, then notifies the manager on the GUI thread."""

    def __init__(self, manager: ProcessQueueManager, job_id: str, inner: QRunnable):
        super().__init__()
        self._manager = manager
        self._job_id = job_id
        self._inner = inner

    def run(self) -> None:
        QMetaObject.invokeMethod(self._manager, "_enter_app_background_ui", Qt.QueuedConnection)
        try:
            self._inner.run()
        except Exception:
            logger.exception("Queued job crashed (job_id=%s)", self._job_id)
        finally:
            QMetaObject.invokeMethod(self._manager, "_exit_app_background_ui", Qt.QueuedConnection)
            self._manager.thread_finished.emit(self._job_id)


class _FastQueueJobRunner(QRunnable):
    """Runs one interactive job on the fast lane pool."""

    def __init__(self, manager: ProcessQueueManager, job_id: str, inner: QRunnable):
        super().__init__()
        self._manager = manager
        self._job_id = job_id
        self._inner = inner

    def run(self) -> None:
        try:
            self._inner.run()
        except Exception:
            logger.exception("Fast queued job crashed (job_id=%s)", self._job_id)
        finally:
            self._manager.fast_thread_finished.emit(self._job_id)
