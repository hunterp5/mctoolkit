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

"""Session save/open helpers for tests: real version-4 files, written synchronously."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from molmanager.chem.depiction_scene import SCENE_MAGIC
from molmanager.table.session_v4 import split_manifest, write_session_v4


def saved_document(win, *, oids: set[int] | None = None) -> dict[str, Any]:
    """Workspace metadata as a save writes it (manifest plus sidecars, deferred ones run)."""
    doc = win._session_document_metadata(oids=oids)
    return {key: value() if callable(value) else value for key, value in doc.items()}


def save_session_file(
    win, *, doc: dict[str, Any] | None = None, oids: set[int] | None = None
) -> Path:
    """Write *win* to a new temp ``.cms``; *doc* replaces the workspace metadata."""
    snapshot = win._snapshot_session_save_inputs(oids=oids)
    if doc is not None:
        snapshot.manifest, snapshot.sidecars = split_manifest(doc)
    path = Path(tempfile.mkdtemp(prefix="molmanager_session_test_")) / "session.cms"
    write_session_v4(path, snapshot, scene_magic=SCENE_MAGIC)
    return path


def open_saved(
    source, target, doc: dict[str, Any] | None = None, *, oids: set[int] | None = None
) -> Path:
    """Save *source* (rows, stores and *doc*) and open the file in *target*."""
    path = save_session_file(source, doc=doc, oids=oids)
    assert target.apply_saved_session_from_file(str(path))
    return path
