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

"""File → Open Recent path list and menu."""

from __future__ import annotations

import json
import os
from pathlib import Path

from PyQt5.QtWidgets import QMenu

from molmanager.ui.main_window.app_menu_mixin import AppMenuMixin
from molmanager.ui.recent_paths import (
    KIND_FILE,
    KIND_SESSION,
    MAX_RECENT_PER_KIND,
    RecentEntry,
    clear_recent,
    ephemeral_session_dir,
    load_recent,
    remember_recent,
    remember_successful_export,
)


def _touch(path: Path, text: str = "x") -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def _menu_labels(menu: QMenu) -> list[str]:
    labels: list[str] = []
    for act in menu.actions():
        labels.append("" if act.isSeparator() else act.text())
    return labels


class _Host(AppMenuMixin):
    def __init__(self) -> None:
        self._recent_menu = QMenu()
        self.opened_files: list[str] = []
        self.opened_sessions: list[str] = []
        self.warnings: list[tuple[str, str]] = []

    def load_file(self, path: str) -> None:
        self.opened_files.append(path)

    def apply_saved_session_from_file(self, path: str) -> bool:
        self.opened_sessions.append(path)
        return True

    def _warn_could_not_open(self, title: str, message: str) -> None:
        self.warnings.append((title, message))


def test_remember_orders_dedupes_and_caps(tmp_path: Path) -> None:
    first = _touch(tmp_path / "a.sdf")
    second = _touch(tmp_path / "b.sdf")
    remember_recent(KIND_FILE, first)
    remember_recent(KIND_FILE, second)
    remember_recent(KIND_FILE, first)
    newest = [entry.path for entry in load_recent()]
    assert newest == [os.path.abspath(first), os.path.abspath(second)]

    session = _touch(tmp_path / "work.cms")
    remember_recent(KIND_FILE, session)
    remember_recent(KIND_SESSION, session)
    kinds = [(entry.kind, os.path.basename(entry.path)) for entry in load_recent()]
    assert (KIND_SESSION, "work.cms") in kinds
    assert (KIND_FILE, "work.cms") not in kinds

    for index in range(MAX_RECENT_PER_KIND + 2):
        remember_recent(KIND_FILE, _touch(tmp_path / f"extra_{index}.smi"))
    files = [entry for entry in load_recent() if entry.kind == KIND_FILE]
    sessions = [entry for entry in load_recent() if entry.kind == KIND_SESSION]
    assert len(files) == MAX_RECENT_PER_KIND
    assert os.path.basename(files[0].path) == f"extra_{MAX_RECENT_PER_KIND + 1}.smi"
    assert [os.path.basename(entry.path) for entry in sessions] == ["work.cms"]


def test_remember_skips_missing_unknown_and_duplicate_temp(tmp_path: Path) -> None:
    remember_recent(KIND_FILE, str(tmp_path / "missing.sdf"))
    remember_recent("plot", _touch(tmp_path / "kept.sdf"))
    assert load_recent() == []

    folder = Path(ephemeral_session_dir())
    folder.mkdir(parents=True, exist_ok=True)
    scratch = folder / f"session_recent_test_{os.getpid()}.cms"
    scratch.write_text("x", encoding="utf-8")
    try:
        remember_recent(KIND_SESSION, str(scratch))
        assert load_recent() == []
    finally:
        scratch.unlink(missing_ok=True)


def test_load_recent_drops_corrupt_and_unknown_rows(tmp_path: Path) -> None:
    from molmanager.ui import recent_paths

    kept = _touch(tmp_path / "kept.sdf")
    settings = recent_paths.QSettings("MolManager", "MolManager")
    settings.setValue(
        recent_paths._SETTINGS_KEY,
        json.dumps(
            [
                {"kind": KIND_FILE, "path": kept},
                {"kind": "plot", "path": kept},
                {"path": kept},
                "bad",
            ]
        ),
    )
    settings.sync()
    assert load_recent() == [RecentEntry(KIND_FILE, kept)]

    settings.setValue(recent_paths._SETTINGS_KEY, "{")
    settings.sync()
    assert load_recent() == []


def test_clear_and_successful_export(tmp_path: Path) -> None:
    path = _touch(tmp_path / "out.sdf")
    remember_recent(KIND_FILE, path)
    clear_recent()
    assert load_recent() == []

    remember_successful_export(f"Exported successfully to {path}")
    assert load_recent() == [RecentEntry(KIND_FILE, os.path.abspath(path))]
    remember_successful_export("Export Error: disk full")
    remember_successful_export("Export cancelled (partial file may exist).")
    assert len(load_recent()) == 1


def test_open_recent_menu_lists_files_and_sessions(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    _touch(tmp_path / "lib_a" / "compounds.sdf")
    _touch(tmp_path / "lib_b" / "compounds.sdf")
    _touch(tmp_path / "notes & data.sdf", "C")
    session = _touch(tmp_path / "project.cms")
    remember_recent(KIND_FILE, str(tmp_path / "lib_a" / "compounds.sdf"))
    remember_recent(KIND_FILE, str(tmp_path / "lib_b" / "compounds.sdf"))
    remember_recent(KIND_FILE, str(tmp_path / "notes & data.sdf"))
    remember_recent(KIND_SESSION, session)

    host = _Host()
    host._populate_recent_menu()
    labels = _menu_labels(host._recent_menu)
    assert labels[0] == "Files"
    assert "lib_b\\compounds.sdf" in labels or "lib_b/compounds.sdf" in labels
    assert "lib_a\\compounds.sdf" in labels or "lib_a/compounds.sdf" in labels
    assert "notes && data.sdf" in labels
    assert "Sessions" in labels
    assert "project.cms" in labels
    assert labels[-1] == "Clear Recent"
    assert host._recent_menu.actions()[0].isEnabled() is False

    file_act = next(act for act in host._recent_menu.actions() if act.text() == "project.cms")
    assert file_act.toolTip() == os.path.abspath(session)
    file_act.trigger()
    assert host.opened_sessions == [os.path.abspath(session)]

    host._recent_menu.actions()[-1].trigger()
    assert load_recent() == []
    host._populate_recent_menu()
    assert _menu_labels(host._recent_menu) == ["No Recent Items"]
    assert host._recent_menu.actions()[0].isEnabled() is False


def test_open_recent_routes_by_kind_and_drops_missing(qapp, tmp_path: Path) -> None:  # noqa: ARG001
    data = _touch(tmp_path / "set.sdf")
    legacy = _touch(tmp_path / "legacy.csv", "SMILES\nC\n")
    host = _Host()
    host._open_recent_entry(KIND_FILE, data)
    host._open_recent_entry(KIND_SESSION, legacy)
    assert host.opened_files == [data]
    assert host.opened_sessions == [legacy]

    remember_recent(KIND_SESSION, legacy)
    Path(legacy).unlink()
    host._open_recent_entry(KIND_SESSION, legacy)
    assert host.warnings and host.warnings[-1][0] == "Open Session"
    assert "does not exist" in host.warnings[-1][1]
    assert load_recent() == []
