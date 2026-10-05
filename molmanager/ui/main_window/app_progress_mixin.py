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

"""Status-bar chrome for ChemistryWorkspaceWindow.

The polled tool-progress state machine lives in ``ui/progress_controller.py``; what is left
here is the chrome the window itself builds — loading overlay, status-bar visibility, and the
memory label.
"""

from __future__ import annotations

import logging

from PyQt5.QtCore import QTimer

from ...platform_support.memory_usage import format_process_memory_status

logger = logging.getLogger(__name__)


class AppProgressMixin:
    def _workspace_loading_overlay_visible(self) -> bool:
        """True while the loading/idle page covers the table and plot panes."""
        if bool(getattr(self, "_ingest_loading", False)):
            return True
        stack = getattr(self, "_table_stack", None)
        try:
            return stack is not None and int(stack.currentIndex()) == 0
        except RuntimeError:
            return False

    def _show_idle_workspace(self) -> None:
        """Cover the empty table with the same full-page chrome used during loads."""
        from ..strings import LOADING_DETAIL_IDLE

        detail = getattr(self, "_loading_detail", None)
        if detail is not None:
            try:
                detail.setText(LOADING_DETAIL_IDLE)
            except RuntimeError:
                pass
        self._set_workspace_stack_index(0)

    def _reveal_workspace_ready(self) -> None:
        """Show the table/plot workspace after data is present."""
        self._set_workspace_stack_index(1)

    def _session_overlay_owns_loading_detail(self) -> bool:
        """True while session restore is writing the loading page (not tool progress)."""
        if getattr(self, "_session_waiting_for_render", False):
            return False
        if getattr(self, "_session_awaiting_ready", False):
            return True
        if getattr(self, "_session_finalize_ctx", None) is not None:
            return True
        if getattr(self, "_session_restore_ctx", None) is not None:
            return True
        if getattr(self, "_csv_session_ctx", None) is not None:
            return True
        return False

    def _sync_status_chrome_for_workspace(self) -> None:
        """Hide status/memory on the loading page; restore the user's status-bar setting after."""
        apply_bar = getattr(self, "_apply_status_bar_visible", None)
        if not callable(apply_bar):
            return
        act = getattr(self, "_act_status_bar", None)
        if act is not None:
            want = bool(act.isChecked())
        else:
            from ..theme import load_status_bar_visible

            want = bool(load_status_bar_visible())
        apply_bar(want, persist=False)

    def _set_workspace_stack_index(self, index: int) -> None:
        stack = getattr(self, "_table_stack", None)
        if stack is None:
            return
        stack.setCurrentIndex(int(index))
        self._sync_status_chrome_for_workspace()

    def _status_memory_should_poll(self) -> bool:
        """True unless the status-bar host was explicitly hidden.

        ``isVisible()`` is False until the top-level window is shown, so it
        cannot be used during ``__init__`` to decide whether polling starts.
        Idle (no file) still polls; only an active ingest/session load pauses it.
        """
        if bool(getattr(self, "_ingest_loading", False)):
            return False
        host = getattr(self, "_status_host", None)
        return host is None or not host.isHidden()

    def _init_status_memory_tracker(self, cfg) -> None:
        self._memory_status_timer = QTimer(self)
        self._memory_status_timer.timeout.connect(self._refresh_status_memory_label)
        label = getattr(self, "_memory_status_label", None)
        if cfg.status_memory_enabled:
            if label is not None:
                label.show()
            self._memory_status_timer.setInterval(int(cfg.status_memory_poll_ms))
            if self._status_memory_should_poll():
                self._memory_status_timer.start()
            self._refresh_status_memory_label()
        elif label is not None:
            label.hide()

    def _refresh_status_memory_label(self) -> None:
        label = getattr(self, "_memory_status_label", None)
        if label is None or label.isHidden():
            return
        text = format_process_memory_status()
        if text is None:
            label.setText("")
            label.setToolTip("Process memory unavailable on this platform.")
            return
        label.setText(text)

    def _status_work_is_active(self) -> bool:
        """True when the status line should keep showing in-progress work."""
        if bool(getattr(self, "_ingest_loading", False)):
            return True
        if bool(getattr(self, "_export_busy", False)):
            return True
        render2d_active = getattr(self, "render2d_batch_active", None)
        if callable(render2d_active) and render2d_active():
            return True
        if self._background_job_ui_active():
            return True
        state = getattr(self, "_tool_progress_state", None)
        if state is not None:
            _msg, _done, _total, active = state.snapshot()
            if active:
                return True
        jobs = getattr(self, "_background_jobs", None)
        return bool(jobs)
