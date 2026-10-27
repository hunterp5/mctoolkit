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

"""Background job registry for Processes dialog."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager.platform_support.tool_progress import ToolProgressState
from molmanager.ui.background_jobs import register_background_job, unregister_background_job


def test_background_job_register_unregister() -> None:
    app = SimpleNamespace(_background_jobs={}, background_activity=SimpleNamespace(notify_calls=0))

    def notify() -> None:
        app.background_activity.notify_calls += 1

    app.background_activity.notify_changed = notify

    register_background_job(app, "job-a", "Test job")
    assert app._background_jobs == {"job-a": "Test job"}
    assert app.background_activity.notify_calls == 1

    unregister_background_job(app, "job-a")
    assert app._background_jobs == {}
    assert app.background_activity.notify_calls == 2


def test_unregister_background_job_ends_progress_slot() -> None:
    state = ToolProgressState()
    state.begin("Applying filters", 10, job_id="filter-1")
    app = SimpleNamespace(
        _background_jobs={"filter-1": "Applying filters"},
        _tool_progress_state=state,
        background_activity=None,
    )
    unregister_background_job(app, "filter-1")
    assert state.snapshot(job_id="filter-1")[3] is False
    assert app._background_jobs == {}
