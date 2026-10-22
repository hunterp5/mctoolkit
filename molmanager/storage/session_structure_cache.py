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

"""Sidecar cache (``.mctcache``) of session Structure depictions.

The cache holds the structure store's SQLite file: depiction scenes only. Scenes
do not depend on the cell size, so a cache written at another size still applies.
Version 1 caches held PNGs only and are ignored. A version 2 cache may still
contain PNG rows from before the table stopped storing them; those rows are
dropped when the cache is loaded.
"""

from __future__ import annotations

import json
import logging
import os
import zipfile
from pathlib import Path

from ..chem.depiction_builder import scene_revision

logger = logging.getLogger(__name__)

CACHE_FORMAT = "molmanager_structure_cache"
CACHE_VERSION = 2
CACHE_EXTENSION = ".mctcache"
_HEADER_MEMBER = "header.json"
_PNG_MEMBER = "pngs.sqlite"


def session_cache_path(session_path: str | Path) -> Path:
    """Return ``<session>.mctcache`` next to the session file."""
    path = Path(session_path)
    return (
        path.with_suffix(path.suffix + CACHE_EXTENSION)
        if path.suffix
        else Path(str(path) + CACHE_EXTENSION)
    )


def _session_identity(session_path: str | Path) -> dict[str, int | float | str]:
    path = Path(session_path)
    try:
        st = path.stat()
        return {
            "session_path": str(path.resolve()),
            "session_size": int(st.st_size),
            "session_mtime_ns": int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
        }
    except OSError:
        return {
            "session_path": str(path),
            "session_size": 0,
            "session_mtime_ns": 0,
        }


def build_cache_header(
    session_path: str | Path,
    *,
    depict_width: int,
    depict_height: int,
    zoomed_ids: list[int] | None = None,
    oid_count: int = 0,
) -> dict:
    """Metadata written into the sidecar zip so stale contents are rejected."""
    header = {
        "format": CACHE_FORMAT,
        "version": int(CACHE_VERSION),
        "scene_revision": scene_revision(),
        "depict_width": int(depict_width),
        "depict_height": int(depict_height),
        "zoomed_ids": sorted(int(x) for x in (zoomed_ids or [])),
        "oid_count": int(oid_count),
    }
    header.update(_session_identity(session_path))
    return header


def header_matches_session(header: dict | None, session_path: str | Path) -> bool:
    """True when *header* is a current-version cache written for this session file."""
    if not isinstance(header, dict):
        return False
    if header.get("format") != CACHE_FORMAT:
        return False
    identity = _session_identity(session_path)
    try:
        if int(header.get("version", -1)) != CACHE_VERSION:
            return False
        if int(header.get("session_size", -1)) != int(identity["session_size"]):
            return False
        if int(header.get("session_mtime_ns", -1)) != int(identity["session_mtime_ns"]):
            return False
    except (TypeError, ValueError):
        return False
    return True


def cached_scenes_current(header: dict) -> bool:
    """True when the cache's scenes came from the current builder and layout options."""
    try:
        return int(header.get("scene_revision", -1)) == scene_revision()
    except (TypeError, ValueError):
        return False


def write_structure_cache(
    session_path: str | Path,
    png_sqlite_bytes: bytes,
    *,
    depict_width: int,
    depict_height: int,
    zoomed_ids: list[int] | None = None,
    oid_count: int = 0,
) -> Path | None:
    """Write ``<session>.mctcache``; return the path, or ``None`` when skipped."""
    if not png_sqlite_bytes:
        return None
    path = session_cache_path(session_path)
    header = build_cache_header(
        session_path,
        depict_width=depict_width,
        depict_height=depict_height,
        zoomed_ids=zoomed_ids,
        oid_count=oid_count,
    )
    try:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED) as zf:
            zf.writestr(_HEADER_MEMBER, json.dumps(header, separators=(",", ":")).encode("utf-8"))
            zf.writestr(_PNG_MEMBER, bytes(png_sqlite_bytes))
        os.replace(tmp, path)
        return path
    except OSError:
        logger.warning("Could not write structure cache %s", path, exc_info=True)
        from contextlib import suppress

        with suppress(OSError):
            Path(str(path) + ".tmp").unlink(missing_ok=True)
        return None


def read_structure_cache(session_path: str | Path) -> tuple[dict, bytes] | None:
    """Load the sidecar written for *session_path*, or ``None`` when missing / stale.

    Callers drop non-scene rows and reject the rest when :func:`cached_scenes_current`
    is false. Depiction width and height in the header are recorded and not used.
    """
    path = session_cache_path(session_path)
    if not path.is_file():
        return None
    try:
        with zipfile.ZipFile(path, "r") as zf:
            raw_header = zf.read(_HEADER_MEMBER)
            png_bytes = zf.read(_PNG_MEMBER)
        header = json.loads(raw_header.decode("utf-8"))
    except (OSError, KeyError, json.JSONDecodeError, UnicodeDecodeError, zipfile.BadZipFile):
        logger.debug("Ignoring unreadable structure cache %s", path, exc_info=True)
        return None
    if not header_matches_session(header, session_path):
        logger.debug("Structure cache stale for %s", path)
        return None
    if not png_bytes:
        return None
    return header, bytes(png_bytes)


def remove_structure_cache(session_path: str | Path) -> None:
    """Delete the sidecar next to *session_path* if present."""
    path = session_cache_path(session_path)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.debug("Could not remove structure cache %s", path, exc_info=True)
