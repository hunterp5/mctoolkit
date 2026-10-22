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

"""Sidecar structure cache for fast session reopen."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from molmanager.storage.session_structure_cache import (
    cached_pngs_fit,
    cached_scenes_current,
    header_matches_session,
    read_structure_cache,
    session_cache_path,
    write_structure_cache,
)
from molmanager.storage.structure_render_store import StructureRenderStore

SCENE = b"MS\x01scene-bytes"
PNG = b"\x89PNG-bytes"


def _write(session: Path, items: list[tuple[int, bytes]], **size) -> None:
    store = StructureRenderStore()
    try:
        store.ingest_batch(items)
        blob = store.export_sqlite_bytes()
    finally:
        store.close()
    write_structure_cache(session, blob, oid_count=len(items), **size)


def _session(tmp_path: Path) -> Path:
    session = tmp_path / "demo.cms"
    session.write_bytes(b'{"format":"molmanager_session","version":2}')
    return session


def test_session_cache_roundtrip(tmp_path: Path) -> None:
    session = _session(tmp_path)
    store = StructureRenderStore()
    try:
        store.ingest_batch([(1, b"png-one"), (2, b"png-two")])
        blob = store.export_sqlite_bytes()
    finally:
        store.close()

    out = write_structure_cache(
        session,
        blob,
        depict_width=180,
        depict_height=140,
        zoomed_ids=[1],
        oid_count=2,
    )
    assert out is not None
    assert out == session_cache_path(session)
    assert out.is_file()

    loaded = read_structure_cache(session)
    assert loaded is not None
    header, png_bytes = loaded
    assert header_matches_session(header, session)
    assert cached_pngs_fit(header, depict_width=180, depict_height=140)
    assert cached_scenes_current(header)
    assert header["oid_count"] == 2
    assert header["zoomed_ids"] == [1]

    restored = StructureRenderStore()
    try:
        assert restored.import_sqlite_bytes(png_bytes) == 2
        assert set(restored.png_oids()) == {1, 2}
    finally:
        restored.close()


def test_session_cache_rejects_a_changed_session(tmp_path: Path) -> None:
    session = tmp_path / "demo.cms"
    session.write_bytes(b"v1")
    write_structure_cache(
        session, b"not-a-real-sqlite", depict_width=10, depict_height=10, oid_count=0
    )
    session.write_bytes(b"v1-changed")
    assert read_structure_cache(session) is None


def test_version_one_caches_are_ignored(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _write(session, [(1, PNG)], depict_width=180, depict_height=140)
    path = session_cache_path(session)
    with zipfile.ZipFile(path) as zf:
        header = json.loads(zf.read("header.json"))
        sqlite = zf.read("pngs.sqlite")
    header["version"] = 1
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("header.json", json.dumps(header))
        zf.writestr("pngs.sqlite", sqlite)
    assert read_structure_cache(session) is None


def test_size_change_keeps_scenes_and_drops_pngs(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _write(session, [(1, SCENE), (2, PNG), (3, SCENE)], depict_width=180, depict_height=140)
    header, blob = read_structure_cache(session)
    assert not cached_pngs_fit(header, depict_width=240, depict_height=200)

    store = StructureRenderStore()
    try:
        store.import_sqlite_bytes(blob)
        assert store.count_pngs() == 1
        assert store.remove_images(scenes=False) == 1
        assert sorted(store.png_oids()) == [1, 3] and len(store) == 2
        assert store.remove_images(scenes=True) == 2
        assert len(store) == 0
    finally:
        store.close()


def test_older_scene_builder_is_not_current(tmp_path: Path) -> None:
    session = _session(tmp_path)
    _write(session, [(1, SCENE)], depict_width=180, depict_height=140)
    header, _blob = read_structure_cache(session)
    header["scene_revision"] = -1
    assert not cached_scenes_current(header)
