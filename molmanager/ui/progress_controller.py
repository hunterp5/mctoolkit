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

"""Tool-progress owner for the main window.

The polled progress state machine lives here and owns its timer, depth counter, and the
last text it wrote. The window keeps the status-bar chrome it builds (stack overlay, memory
label, status-bar visibility); ``AppProgressMixin`` still supplies that half through the
legacy bridge.
"""

from __future__ import annotations

from contextlib import suppress
from typing import Any, Protocol

from PyQt5.QtCore import QTimer

from ..platform_support.config import load_config
from ..platform_support.tool_progress import format_tool_progress_text
from .app_kernel import bind_mixin_methods
from .main_window.app_progress_mixin import AppProgressMixin
from .recent_paths import remember_successful_export
from .strings import STATUS_READY


class ProgressHost(Protocol):
    """What the progress state machine needs from the window's status chrome."""

    status_label: Any
    background_activity: Any
    _tool_progress_state: Any
    _loading_detail: Any
    _export_busy: bool

    def _workspace_loading_overlay_visible(self) -> bool: ...
    def _session_overlay_owns_loading_detail(self) -> bool: ...
    def _status_work_is_active(self) -> bool: ...


class ProgressController:
    """Owns the polled tool-progress state machine and the text it puts on the status line.

    ``AppProgressMixin`` still supplies the window's status-bar chrome through
    ``bind_mixin_methods``; everything below is a real method reading ``self._app``.
    """

    def __init__(self, app: ProgressHost) -> None:
        self._app = app
        bind_mixin_methods(self, app, AppProgressMixin)
        self._active_label = ""
        self._last_status_text = ""
        self._background_job_ui_depth = 0
        self._partial_results_notice: str | None = None
        self._poll_interval_ms = int(load_config().tool_progress_poll_ms)
        self._poll_timer = QTimer(app)
        self._poll_timer.setInterval(self._poll_interval_ms)
        self._poll_timer.timeout.connect(self._poll_tool_progress_state)

    def current_status_text(self) -> str:
        """Last text written to the status line, for the background-activity hub."""
        return self._last_status_text

    def has_partial_results_notice(self) -> bool:
        return bool(self._partial_results_notice)

    def _progress_any_active(self) -> bool:
        state = self._app._tool_progress_state
        fn = getattr(state, "any_active", None)
        if callable(fn):
            return bool(fn())
        snapshot = getattr(state, "snapshot", None)
        if callable(snapshot):
            return bool(snapshot()[3])
        return False

    def _running_queue_job_id(self) -> str | None:
        pq = getattr(self._app, "process_queue", None)
        snap_fn = getattr(pq, "snapshot", None) if pq is not None else None
        if not callable(snap_fn):
            return None
        running = (snap_fn() or {}).get("running") or {}
        job_id = running.get("job_id")
        return str(job_id) if job_id else None

    def _status_progress_snapshot(self) -> tuple[str, int, int, bool]:
        state = self._app._tool_progress_state
        preferred = getattr(state, "preferred_snapshot", None)
        if callable(preferred):
            return preferred(self._running_queue_job_id())
        return state.snapshot()

    def _begin_tool_progress(self, message: str, total: int, job_id: str | None = None) -> None:
        """Start polled status updates for a long-running queued tool.

        ``total < 0`` is indeterminate: the status line is the message only.
        """
        self._active_label = str(message or "")
        total_i = int(total)
        if total_i < 0:
            self._on_tool_progress(message, 0, -1, job_id=job_id)
        else:
            total_i = max(1, total_i)
            self._app._tool_progress_state.begin(message, total_i, job_id=job_id)
            self._on_tool_progress(message, 0, total_i, job_id=job_id)
        if not self._poll_timer.isActive():
            self._poll_timer.start()

    def _poll_tool_progress_state(self) -> None:
        if not self._progress_any_active():
            self._poll_timer.stop()
            return
        self._refresh_status_from_slots()
        self._notify_activity_hub()

    def _background_job_ui_active(self) -> bool:
        return self._background_job_ui_depth > 0

    def _enter_background_job_ui(self) -> None:
        """Reduce main-thread churn while a queued tool holds the machine busy."""
        self._background_job_ui_depth += 1
        if self._background_job_ui_depth != 1:
            return
        self._poll_timer.setInterval(int(load_config().background_job_poll_ms))

    def _exit_background_job_ui(self) -> None:
        self._background_job_ui_depth = max(0, self._background_job_ui_depth - 1)
        if self._background_job_ui_depth != 0:
            return
        self._poll_timer.setInterval(self._poll_interval_ms)

    def _restore_idle_status(self) -> None:
        """Set the status line to Ready when nothing else is running."""
        if self._app._status_work_is_active():
            return
        label = self._app.status_label
        if label is None:
            return
        try:
            if label.text() != STATUS_READY:
                label.setText(STATUS_READY)
        except RuntimeError:
            pass

    def _finish_tool_progress(
        self,
        message: str | None = None,
        *,
        status_message: str | None = STATUS_READY,
        job_id: str | None = None,
    ) -> None:
        """Show 100% once, then stop polling and optionally reset the status line."""
        key = self._resolve_progress_job_id(job_id, message=message)
        state = self._app._tool_progress_state
        try:
            msg, done, total, active = state.snapshot(job_id=key)
        except TypeError:
            msg, done, total, active = state.snapshot()
        final_msg = message or msg or self._active_label
        if total > 0 and (active or done < total):
            self._on_tool_progress(final_msg, total, total, job_id=key)
        self._end_progress_slot(key, also_message=str(msg or ""))
        leftover = getattr(state, "snapshots", None)
        if key and callable(leftover) and not any(jid for jid in leftover() if jid):
            state.end()
        if not self._progress_any_active():
            self._active_label = ""
            self._poll_timer.stop()
            if status_message is not None:
                self._app.status_label.setText(status_message)
                self._last_status_text = str(status_message or "")
        else:
            self._refresh_status_from_slots()
        self._notify_activity_hub()

    def _resolve_progress_job_id(
        self,
        job_id: str | None,
        *,
        message: str | None = None,
    ) -> str | None:
        """Pick the slot to finish/clear: explicit id, label match, running queue, or sole named."""
        if job_id:
            return str(job_id)
        state = self._app._tool_progress_state
        snaps_fn = getattr(state, "snapshots", None)
        snaps = snaps_fn() if callable(snaps_fn) else {}
        label = str(message or "").strip().rstrip(".…")
        if label:
            matches = [
                jid
                for jid, (msg, _d, _t, _a) in snaps.items()
                if jid and str(msg or "").strip().rstrip(".…").startswith(label)
            ]
            if len(matches) == 1:
                return str(matches[0])
            return None
        running = self._running_queue_job_id()
        if running:
            return running
        named = [jid for jid in snaps if jid]
        if len(named) == 1:
            return str(named[0])
        return None

    def _end_progress_slot(self, job_id: str | None, *, also_message: str = "") -> None:
        """Stop *job_id* and the unnamed copy a worker signal writes beside it.

        Queue workers update a named slot and also emit ``tool_progress``, which
        the status handler stores with no job id. Ending only the named slot
        leaves that copy at 100%, and the poll paints it forever.
        """
        state = self._app._tool_progress_state
        messages = {str(also_message or "")}
        if job_id:
            with suppress(TypeError):
                messages.add(str(state.snapshot(job_id=job_id)[0] or ""))
        state.end(job_id=job_id)
        messages.discard("")
        if not job_id or not messages:
            return
        try:
            default_message, _done, _total, active = state.snapshot(job_id="")
        except TypeError:
            return
        if active and str(default_message or "") in messages:
            state.end(job_id="")

    def _clear_tool_progress(
        self,
        *,
        status_message: str | None = STATUS_READY,
        job_id: str | None = None,
    ) -> None:
        """Stop polled tool progress; reset status line unless ``status_message`` is ``None``."""
        key = self._resolve_progress_job_id(job_id)
        self._end_progress_slot(key)
        if self._progress_any_active():
            self._refresh_status_from_slots()
            self._notify_activity_hub()
            return
        self._active_label = ""
        self._last_status_text = ""
        if self._poll_timer.isActive():
            self._poll_timer.stop()
        if status_message is not None:
            self._app.status_label.setText(status_message)
        self._notify_activity_hub()

    def _on_export_finished_message(self, message: str) -> None:
        self._app._export_busy = False
        self._clear_tool_progress(status_message=None)
        self._app.status_label.setText(message)
        remember_successful_export(message)

    def _refresh_status_from_slots(self) -> None:
        message, done, total, active = self._status_progress_snapshot()
        text = format_tool_progress_text(message, done, total) if active else ""
        if text == self._last_status_text:
            return
        self._last_status_text = text
        if text:
            self._app.status_label.setText(text)

    def _on_tool_progress(
        self,
        message: str,
        done: int,
        total: int,
        job_id: str | None = None,
    ) -> None:
        state = self._app._tool_progress_state
        if message or job_id:
            if total < 0:
                state.update(message, 0, -1, job_id=job_id)
            else:
                state.update(message, done, total, job_id=job_id)
        message, done, total, active = self._status_progress_snapshot()
        text = format_tool_progress_text(message, done, total) if active else ""
        if text != self._last_status_text:
            self._last_status_text = text
            if text:
                self._app.status_label.setText(text)
            if (
                text
                and self._app._workspace_loading_overlay_visible()
                and not self._app._session_overlay_owns_loading_detail()
            ):
                detail = self._app._loading_detail
                if detail is not None:
                    with suppress(RuntimeError):
                        detail.setText(text)
        self._notify_activity_hub()

    def _on_partial_results_notice(self, tool_label: str, done: int, total: int) -> None:
        d = max(0, int(done))
        t = max(1, int(total))
        self._partial_results_notice = (
            f"Cancelled — applied partial results for {tool_label} ({d}/{t})."
        )

    def _consume_partial_results_notice(self) -> str | None:
        note = self._partial_results_notice
        self._partial_results_notice = None
        return note

    def _notify_activity_hub(self) -> None:
        hub = self._app.background_activity
        if hub is not None:
            hub.notify_changed()
