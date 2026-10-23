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

"""Version-4 SQLite sessions round-trip rows, structures, depictions and sidecars."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import numpy as np
import pytest

from molmanager.storage import EnsembleStore, MolStore
from molmanager.table.session_v4 import (
    SessionSaveSnapshot,
    is_session_v4,
    keep_mask,
    read_session_v4,
    split_manifest,
    write_session_v4,
)
from molmanager.ui.column_store import ColumnStore


def _render_db(path: Path, rows: list[tuple[int, bytes]]) -> Path:
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE pngs (oid INTEGER PRIMARY KEY, blob BLOB NOT NULL, seq INTEGER NOT NULL)"
    )
    conn.executemany(
        "INSERT INTO pngs (oid, blob, seq) VALUES (?, ?, ?)",
        [(oid, blob, i) for i, (oid, blob) in enumerate(rows)],
    )
    conn.commit()
    conn.close()
    return path


@pytest.fixture
def stores(tmp_path):
    rows = ColumnStore()
    rows.append_columns(
        [1, 2, 3], {"SMILES": ["CCO", "c1ccccc1", "CC"], "MW": ["46.07", "78.11", ""]}
    )
    mols = MolStore()
    mols.ingest_jobs([(1, None, "CCO"), (2, None, "c1ccccc1"), (3, None, "CC")])
    ensembles = EnsembleStore()
    ensembles[(2, "Confs")] = "AAAA"
    render = _render_db(
        tmp_path / "render.sqlite", [(1, b"MS-scene-1"), (2, b"\x89PNG"), (3, b"MS-3")]
    )
    yield rows, mols, ensembles, render
    mols.close()
    ensembles.close()


def _snapshot(rows, mols, ensembles, render, keep=None, sidecars=None) -> SessionSaveSnapshot:
    mask = keep_mask(rows.oids[: rows.n], keep)
    mols.flush()
    ensembles.flush()
    return SessionSaveSnapshot(
        manifest={"headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"], "next_oid": 4},
        oids=rows.oids_blob(mask),
        columns=rows.to_blobs(["SMILES", "MW"], mask),
        sidecars=sidecars or {},
        mol_db=mols.db_path,
        render_db=render,
        ensembles_db=ensembles.db_path,
        scene_revision=33,
        keep_oids=None if keep is None else frozenset(keep),
        row_count=rows.n,
    )


def test_round_trip_full_session(tmp_path, stores) -> None:
    rows, mols, ensembles, render = stores
    path = tmp_path / "s.cms"
    manifest, sidecars = split_manifest(
        {
            "headers": ["ID_HIDDEN"],
            "ionization_sidecar": {"k": [1, 2]},
            "som_browse": [],
            "notepad": lambda: {"text": "deferred"},
        }
    )
    assert "ionization_sidecar" not in manifest and "som_browse" not in sidecars
    write_session_v4(
        path, _snapshot(rows, mols, ensembles, render, sidecars=sidecars), scene_magic=b"MS"
    )
    assert is_session_v4(path)
    assert not Path(str(path) + ".tmp").exists()

    opened = read_session_v4(path, want_scene_revision=33)
    try:
        assert opened.manifest["next_oid"] == 4
        assert opened.manifest["ionization_sidecar"] == {"k": [1, 2]}
        assert opened.manifest["notepad"] == {"text": "deferred"}
        assert opened.max_oid == 3
        assert [opened.rows.get_text(i, "MW") for i in range(3)] == ["46.07", "78.11", ""]
        assert opened.rows.column_kind("MW") == "float"
        assert opened.render_count == 2
        adopted = MolStore(opened.mol_db)
        try:
            assert adopted.structure_text_for(2) == "c1ccccc1"
        finally:
            adopted.close()
        ens = EnsembleStore(opened.ensembles_db)
        try:
            assert ens[(2, "Confs")] == "AAAA"
        finally:
            ens.close()
    finally:
        opened.discard_temp_files()
    assert all(not p.exists() for p in [opened.mol_db, opened.render_db, opened.ensembles_db])


def test_subset_save_and_stale_scenes(tmp_path, stores) -> None:
    rows, mols, ensembles, render = stores
    path = tmp_path / "subset.cms"
    write_session_v4(path, _snapshot(rows, mols, ensembles, render, keep={1, 3}))
    opened = read_session_v4(path, want_scene_revision=99)
    try:
        assert list(opened.rows.oids) == [1, 3]
        assert [opened.rows.get_text(i, "SMILES") for i in range(2)] == ["CCO", "CC"]
        assert opened.render_db is None
        assert opened.ensembles_db is None
        conn = sqlite3.connect(str(opened.mol_db))
        assert [r[0] for r in conn.execute("SELECT oid FROM mols ORDER BY oid")] == [1, 3]
        conn.close()
    finally:
        opened.discard_temp_files()


def test_rejects_non_session_sqlite(tmp_path) -> None:
    path = tmp_path / "other.sqlite"
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value BLOB)")
    conn.execute("INSERT INTO meta VALUES ('format', ?)", (b"other",))
    conn.commit()
    conn.close()
    with pytest.raises(ValueError):
        read_session_v4(path)
    assert not is_session_v4(tmp_path / "missing.cms")


def test_keep_mask() -> None:
    assert keep_mask(np.array([1, 2, 3]), None) is None
    assert list(keep_mask(np.array([1, 2, 3]), {3, 1})) == [True, False, True]
