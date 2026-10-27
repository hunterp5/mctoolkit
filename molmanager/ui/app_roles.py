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

"""Kernel roles: the slices of the window a collaborator is allowed to need.

``AppKernel`` is the union of every role here, so the window still satisfies all of
them at once. The point of the split is the *annotation*: a collaborator that takes
``ProgressChrome`` cannot quietly start reading the SQLite store, and the roles it
does take show up in its constructor signature instead of being buried in method
bodies.

Attribute names match the historical window ``self`` so mixin bodies can run
against a role without copying ``MolStore`` / table rows. See
``docs/ARCHITECTURE.md`` for how roles relate to the collaborator layer.
"""

from __future__ import annotations

from typing import Any, Protocol

from PyQt5.QtCore import QThreadPool, QTimer
from PyQt5.QtWidgets import QTableView, QUndoStack

from .selection_store import SelectionStore


class ProgressChrome(Protocol):
    """The status line and the queued-tool progress state behind it."""

    status_label: Any
    _tool_progress_state: Any

    def _begin_tool_progress(self, message: str, total: int, job_id: str | None = None) -> None: ...
    def _finish_tool_progress(self, message: str | None = None, **kwargs: Any) -> None: ...
    def _clear_tool_progress(self, **kwargs: Any) -> None: ...


class TableData(Protocol):
    """Row data plus the models that present it."""

    mols: Any
    headers: list
    _table_model: Any
    _filter_proxy_model: Any


class TableSelection(Protocol):
    """The view and the caches that answer "what is selected" without a row scan."""

    table: QTableView
    selection_store: SelectionStore
    _visible_source_rows_cache: Any

    def _selected_oids_set(self) -> set[int]: ...


class SessionState(Protocol):
    """Dirty flag, oid allocation, and the filter/zoom state a session round-trips."""

    filters: list
    global_bounds: dict
    next_oid: int
    zoomed_ids: set

    def _mark_session_dirty(self) -> None: ...
    def schedule_calculate_global_bounds(self) -> None: ...


class JobScheduler(Protocol):
    """Pools, the external-process queue, and the hub background work reports to."""

    threadpool: QThreadPool
    _render_threadpool: QThreadPool
    process_queue: Any
    background_activity: Any
    signals: Any


class StoreAccess(Protocol):
    """Persistent sidecars and the undo stack."""

    session_runtime: Any
    _sqlite_store: Any
    _confs_blocks_sidecar: Any
    _undo_stack: QUndoStack

    def _schedule_sqlite_rebuild(self, *args: Any, **kwargs: Any) -> None: ...


class CoalescedRefresh(Protocol):
    """Debounce timers that collapse bursts of edits into one recompute."""

    _apply_filters_timer: QTimer
    _plot_table_sync_timer: QTimer
    _plot_replot_timer: QTimer

    def _schedule_active_plots_replot(self, *args: Any, **kwargs: Any) -> None: ...
