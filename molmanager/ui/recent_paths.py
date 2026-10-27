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

"""Recently opened files and sessions for File → Open Recent.

Paths are stored newest-first in QSettings. Duplicate Session writes under the
temp ``MolManagerSessions`` folder are omitted so that scratch copy never
appears in the menu.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass

from PyQt5.QtCore import QSettings

KIND_FILE = "file"
KIND_SESSION = "session"
MAX_RECENT_PER_KIND = 10

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY = "gui/recent_paths"
_KINDS = frozenset({KIND_FILE, KIND_SESSION})
# ExportWorker emits this prefix with the destination path on success.
_EXPORT_SUCCESS_PREFIX = "Exported successfully to "


@dataclass(frozen=True)
class RecentEntry:
    """One path the user opened or saved, tagged as a data file or a session."""

    kind: str
    path: str


def ephemeral_session_dir() -> str:
    """Temp folder used for Duplicate Session bundles."""
    from ..platform_support.session_runtime import current_runtime

    return str(current_runtime().sessions_dir())


def remember_recent(kind: str, path: str) -> None:
    """Move *path* to the front of the recent list for *kind*.

    Missing paths and Duplicate Session temp files are ignored. Opening the
    same path again updates its kind and recency. Each kind keeps at most
    ``MAX_RECENT_PER_KIND`` entries.
    """
    if kind not in _KINDS:
        return
    text = str(path or "").strip()
    if not text or _is_ephemeral_session_path(text) or not os.path.isfile(text):
        return
    stored = os.path.abspath(text)
    key = _path_key(stored)
    entries = [entry for entry in load_recent() if _path_key(entry.path) != key]
    entries.insert(0, RecentEntry(kind, stored))
    _save(entries)


def remember_successful_export(message: str) -> None:
    """Record an exported file when *message* is ExportWorker's success text."""
    text = str(message or "")
    if not text.startswith(_EXPORT_SUCCESS_PREFIX):
        return
    remember_recent(KIND_FILE, text[len(_EXPORT_SUCCESS_PREFIX) :])


def load_recent() -> list[RecentEntry]:
    """Return saved paths, newest first, capped per kind."""
    settings = _settings()
    raw = settings.value(_SETTINGS_KEY, "")
    entries = _parse_stored(raw)
    entries = [entry for entry in entries if not _is_ephemeral_session_path(entry.path)]
    return _trim(_dedupe(entries))


def forget_recent(path: str) -> None:
    """Drop one path from the recent list (for example after it goes missing)."""
    text = str(path or "").strip()
    if not text:
        return
    key = _path_key(text)
    _save([entry for entry in load_recent() if _path_key(entry.path) != key])


def clear_recent() -> None:
    """Remove every recent file and session."""
    settings = _settings()
    settings.remove(_SETTINGS_KEY)
    settings.sync()


def recent_display_name(path: str, peers: Sequence[str]) -> str:
    """Basename, or ``parent/basename`` when several paths in *peers* share a name."""
    base = os.path.basename(path) or path
    bases = [os.path.basename(peer) or peer for peer in peers]
    if bases.count(base) <= 1:
        return base
    parent = os.path.basename(os.path.dirname(path))
    if parent:
        return os.path.join(parent, base)
    return path


def _settings() -> QSettings:
    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _save(entries: Sequence[RecentEntry]) -> None:
    payload = [{"kind": entry.kind, "path": entry.path} for entry in _trim(_dedupe(entries))]
    settings = _settings()
    settings.setValue(_SETTINGS_KEY, json.dumps(payload))
    settings.sync()


def _parse_stored(raw: object) -> list[RecentEntry]:
    if raw is None or raw == "":
        return []
    try:
        if isinstance(raw, bytes):
            data = json.loads(raw.decode("utf-8"))
        elif isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            data = json.loads(text)
        elif isinstance(raw, list):
            data = raw
        else:
            return []
    except (json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    entries: list[RecentEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        path = item.get("path")
        if kind not in _KINDS or not isinstance(path, str) or not path.strip():
            continue
        entries.append(RecentEntry(str(kind), path))
    return entries


def _dedupe(entries: Sequence[RecentEntry]) -> list[RecentEntry]:
    seen: set[str] = set()
    kept: list[RecentEntry] = []
    for entry in entries:
        key = _path_key(entry.path)
        if key in seen:
            continue
        seen.add(key)
        kept.append(entry)
    return kept


def _trim(entries: Sequence[RecentEntry]) -> list[RecentEntry]:
    counts = {KIND_FILE: 0, KIND_SESSION: 0}
    kept: list[RecentEntry] = []
    for entry in entries:
        counts[entry.kind] = counts.get(entry.kind, 0) + 1
        if counts[entry.kind] <= MAX_RECENT_PER_KIND:
            kept.append(entry)
    return kept


def _path_key(path: str) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(path)))


def _is_ephemeral_session_path(path: str) -> bool:
    folder = os.path.normcase(os.path.abspath(os.path.dirname(str(path))))
    root = os.path.normcase(os.path.abspath(ephemeral_session_dir()))
    return folder == root
