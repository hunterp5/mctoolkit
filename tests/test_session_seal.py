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

"""Encrypted ``.cms`` sessions, and plaintext files saved before encryption."""

from __future__ import annotations

import sys

import pytest

from molmanager.table.column_store import ColumnStore
from molmanager.table.session_seal import (
    SESSION_SEAL_MAGIC,
    SessionSealError,
    load_or_create_session_key,
)
from molmanager.table.session_v4 import (
    SQLITE_HEADER,
    SessionSaveSnapshot,
    is_session_v4,
    read_session_v4,
    write_session_v4,
)


def _snapshot(rows: ColumnStore) -> SessionSaveSnapshot:
    return SessionSaveSnapshot(
        manifest={"headers": ["SMILES"], "next_oid": 2},
        oids=rows.oids_blob(),
        columns=rows.to_blobs(["SMILES"]),
        row_count=rows.n,
    )


def _rows() -> ColumnStore:
    rows = ColumnStore()
    rows.append_columns([1], {"SMILES": ["CCO"]})
    return rows


def test_save_encrypts_and_open_round_trips(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_SESSION_PLAINTEXT", raising=False)
    path = tmp_path / "sealed.cms"
    write_session_v4(path, _snapshot(_rows()))
    assert path.read_bytes()[:4] == SESSION_SEAL_MAGIC
    assert is_session_v4(path)
    opened = read_session_v4(path)
    try:
        assert opened.rows.get_text(0, "SMILES") == "CCO"
    finally:
        opened.discard_temp_files()


def test_plaintext_switch_writes_sqlite_and_still_opens_later(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_SESSION_PLAINTEXT", "1")
    path = tmp_path / "plain.cms"
    write_session_v4(path, _snapshot(_rows()))
    assert path.read_bytes().startswith(SQLITE_HEADER)
    monkeypatch.delenv("MOLMANAGER_SESSION_PLAINTEXT", raising=False)
    opened = read_session_v4(path)
    try:
        assert opened.rows.get_text(0, "SMILES") == "CCO"
    finally:
        opened.discard_temp_files()


def test_a_different_user_key_cannot_read_the_session(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_SESSION_PLAINTEXT", raising=False)
    path = tmp_path / "sealed.cms"
    write_session_v4(path, _snapshot(_rows()))
    monkeypatch.setenv("MOLMANAGER_SESSION_KEY_DIR", str(tmp_path / "other-user"))
    load_or_create_session_key(create=True, scheme=1)
    with pytest.raises(SessionSealError, match="could not decrypt"):
        read_session_v4(path)


def test_raw_key_file_round_trips(tmp_path, monkeypatch) -> None:
    key_dir = tmp_path / "raw-key"
    monkeypatch.setenv("MOLMANAGER_SESSION_KEY_DIR", str(key_dir))
    monkeypatch.delenv("MOLMANAGER_SESSION_PLAINTEXT", raising=False)
    load_or_create_session_key(create=True, scheme=1)
    blob = (key_dir / "session.key").read_bytes()
    assert blob[:4] == b"MMK1"
    assert blob[4] == 1
    if sys.platform != "win32":
        assert (key_dir / "session.key").stat().st_mode & 0o777 == 0o600
    path = tmp_path / "sealed.cms"
    write_session_v4(path, _snapshot(_rows()))
    opened = read_session_v4(path)
    try:
        assert opened.rows.get_text(0, "SMILES") == "CCO"
    finally:
        opened.discard_temp_files()


@pytest.mark.skipif(sys.platform != "win32", reason="DPAPI is the Windows key store")
def test_windows_key_is_dpapi_protected(tmp_path, monkeypatch) -> None:
    key_dir = tmp_path / "dpapi-key"
    monkeypatch.setenv("MOLMANAGER_SESSION_KEY_DIR", str(key_dir))
    monkeypatch.delenv("MOLMANAGER_SESSION_PLAINTEXT", raising=False)
    load_or_create_session_key(create=True)
    blob = (key_dir / "session.key").read_bytes()
    assert blob[4] == 2
    assert blob[5:] != load_or_create_session_key(create=False)
    path = tmp_path / "sealed.cms"
    write_session_v4(path, _snapshot(_rows()))
    opened = read_session_v4(path)
    try:
        assert opened.rows.get_text(0, "SMILES") == "CCO"
    finally:
        opened.discard_temp_files()
