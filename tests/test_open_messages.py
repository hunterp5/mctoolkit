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

"""Command-line and menu opens of missing or damaged files."""

from __future__ import annotations

from pathlib import Path

from molmanager.app import _argv_for_qt
from molmanager.table.open_messages import (
    damaged_file_message,
    message_for_session_read_failure,
    no_path_message,
    preflight_open_path,
)
from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.workers.load_render import UniversalLoadWorker
from molmanager.workers.signals import WorkerSignals


def test_preflight_names_the_problem(tmp_path: Path) -> None:
    missing = tmp_path / "binding.sdf"
    assert preflight_open_path(str(missing)) == (
        'Could not open "binding.sdf". That file does not exist.'
    )
    assert preflight_open_path(str(tmp_path)) == (
        f'Could not open "{tmp_path.name}". That path is a folder.'
    )
    assert preflight_open_path("  ") == no_path_message(kind="file")
    assert preflight_open_path(None) == "Could not open a file. No path was given."


def test_damaged_file_message_names_the_format() -> None:
    assert damaged_file_message("binding.sdf") == (
        'Could not open "binding.sdf". That file is not a readable SDF, or it is damaged.'
    )
    assert "not a supported format" in damaged_file_message("notes.xyz")


def test_session_read_failure_distinguishes_shape_from_damage() -> None:
    assert "not a MolManager session" in message_for_session_read_failure(
        "session.cms", ValueError("Unsupported session version: 9")
    )
    assert "damaged" in message_for_session_read_failure(
        "session.cms", ValueError("Could not decompress session file: bad gzip")
    )


def test_argv_records_flags_that_have_no_path() -> None:
    qt, session, path, missing = _argv_for_qt(["molmanager", "--load-session"])
    assert qt == ["molmanager"]
    assert session is None
    assert path is None
    assert missing == ["session"]

    qt, session, path, missing = _argv_for_qt(["molmanager", "--open"])
    assert qt == ["molmanager"]
    assert path is None
    assert missing == ["file"]

    qt, session, path, missing = _argv_for_qt(
        ["molmanager", "--load-session", "demo.cms", "--open"]
    )
    assert session == "demo.cms"
    assert path is None
    assert missing == ["file"]

    qt, session, path, missing = _argv_for_qt(
        ["molmanager", "--load-session", "demo.cms", "--open", "set.sdf"]
    )
    assert qt == ["molmanager"]
    assert session == "demo.cms"
    assert path == "set.sdf"
    assert missing == []


def test_load_file_missing_does_not_clear_the_workspace(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    win = ChemistryWorkspaceWindow()
    cleared: list[bool] = []
    win.clear_all = lambda: cleared.append(True)  # type: ignore[method-assign]
    win.load_file(str(tmp_path / "missing.sdf"))
    assert cleared == []
    assert win._last_open_error == 'Could not open "missing.sdf". That file does not exist.'
    assert win._ingest_loading is False

    win.load_file(str(tmp_path))
    assert cleared == []
    assert "folder" in win._last_open_error


def test_open_session_missing_or_damaged_warns_without_applying(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    win = ChemistryWorkspaceWindow()
    assert win.apply_saved_session_from_file(str(tmp_path / "no.cms")) is False
    assert win._last_open_error == 'Could not open "no.cms". That file does not exist.'

    damaged = tmp_path / "bad.cms"
    damaged.write_bytes(b"this is not a session")
    assert win.apply_saved_session_from_file(str(damaged)) is False
    assert win._last_open_error == 'Could not open "bad.cms". That session file is damaged.'

    other = tmp_path / "other.cms"
    other.write_text('{"hello": 1}', encoding="utf-8")
    assert win.apply_saved_session_from_file(str(other)) is False
    assert "not a MolManager session" in win._last_open_error
    assert win._ingest_loading is False


def test_load_session_csv_missing_does_not_clear(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    win = ChemistryWorkspaceWindow()
    cleared: list[bool] = []
    win.clear_all = lambda: cleared.append(True)  # type: ignore[method-assign]
    win.load_session_csv(str(tmp_path / "legacy.csv"))
    assert cleared == []
    assert "does not exist" in win._last_open_error


def test_universal_load_reports_missing_and_unreadable_files(tmp_path: Path, qapp) -> None:  # noqa: ARG001
    def _fail(path: Path) -> tuple[list, list[tuple[int, str]]]:
        sig = WorkerSignals()
        loaded: list = []
        failed: list[tuple[int, str]] = []
        sig.mols_loaded.connect(lambda *args: loaded.append(args))
        sig.file_load_failed.connect(lambda gen, msg: failed.append((gen, msg)))
        UniversalLoadWorker(str(path), sig, batch_size=10, ingest_generation=3).run()
        return loaded, failed

    loaded, failed = _fail(tmp_path / "missing.sdf")
    assert loaded == []
    assert failed == [(3, 'Could not open "missing.sdf". That file does not exist.')]

    garbage = tmp_path / "bad.sdf"
    garbage.write_text("not an sdf record\n", encoding="utf-8")
    loaded, failed = _fail(garbage)
    assert loaded == []
    assert len(failed) == 1
    assert failed[0][0] == 3
    assert "not a readable SDF" in failed[0][1]

    notes = tmp_path / "notes.xyz"
    notes.write_text("hello\n", encoding="utf-8")
    loaded, failed = _fail(notes)
    assert loaded == []
    assert "not a supported format" in failed[0][1]
