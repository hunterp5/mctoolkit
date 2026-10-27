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

"""Process temp directory and the offline / SQL-write policy."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmanager.platform_support.session_runtime import (
    NetworkDisabled,
    ToolDenied,
    current_runtime,
    network_allowed,
    require_network,
    require_tool,
    sql_writes_allowed,
)
from molmanager.storage.sqlite_table_store import SqliteTableStore


@pytest.fixture(autouse=True)
def _audit_in_tmp(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("MOLMANAGER_LOG_DIR", str(tmp_path / "logs"))


def test_offline_refuses_network(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_OFFLINE", "1")
    assert network_allowed() is False
    with pytest.raises(NetworkDisabled, match="PubChem"):
        require_network("PubChem")


def test_network_is_allowed_by_default(monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_OFFLINE", raising=False)
    assert network_allowed() is True
    require_network("PubChem")


def test_sql_writes_can_be_disabled(monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_SQL_WRITES", raising=False)
    assert sql_writes_allowed() is True
    monkeypatch.setenv("MOLMANAGER_SQL_WRITES", "0")
    assert sql_writes_allowed() is False


def test_table_cache_is_private_and_removed_on_close() -> None:
    first = SqliteTableStore()
    second = SqliteTableStore()
    try:
        assert first.db_path != second.db_path
        assert current_runtime().contains(first.db_path)
        assert "MOLMANAGER_table_cache.sqlite3" not in first.db_path.name
        assert first.db_path.is_file()
    finally:
        first_path = first.db_path
        second_path = second.db_path
        first.close()
        second.close()
    assert not first_path.exists()
    assert not second_path.exists()


def test_explicit_sqlite_path_is_kept(tmp_path: Path) -> None:
    path = tmp_path / "kept.sqlite3"
    store = SqliteTableStore(path)
    store.close()
    assert path.exists()


def test_foreign_scratch_session_is_copied(tmp_path: Path) -> None:
    foreign = tmp_path / "molmanager-rt-1-abc" / "sessions"
    foreign.mkdir(parents=True)
    src = foreign / "session_old.cms"
    src.write_bytes(b"session")
    runtime = current_runtime()
    copied = runtime.retain_foreign_session(str(src))
    assert copied != str(src)
    assert Path(copied).read_bytes() == b"session"
    assert runtime.contains(copied)
    assert runtime.retain_foreign_session(copied) == copied


def test_machine_policy_overrides_the_environment(tmp_path: Path, monkeypatch) -> None:
    policy = tmp_path / "policy.txt"
    policy.write_text(
        "\n".join(
            [
                "# deployed by IT",
                "MOLMANAGER_OFFLINE=1",
                "MOLMANAGER_SQL_WRITES=0",
                "NOT_A_MOLMANAGER_KEY=1",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "molmanager.platform_support.session_runtime.machine_policy_path", lambda: policy
    )
    monkeypatch.setenv("MOLMANAGER_OFFLINE", "0")
    monkeypatch.setenv("MOLMANAGER_SQL_WRITES", "1")
    assert network_allowed() is False
    assert sql_writes_allowed() is False


def test_missing_policy_file_leaves_the_environment_in_effect(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.platform_support.session_runtime.machine_policy_path",
        lambda: tmp_path / "missing.txt",
    )
    monkeypatch.delenv("MOLMANAGER_OFFLINE", raising=False)
    assert network_allowed() is True


def test_allowlist_limits_which_program_can_start(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("MOLMANAGER_TOOL_DIGESTS", raising=False)
    program = tmp_path / "gnina.exe"
    program.write_bytes(b"tool")
    monkeypatch.delenv("MOLMANAGER_TOOL_ALLOWLIST", raising=False)
    require_tool(str(program), "Gnina")
    monkeypatch.setenv("MOLMANAGER_TOOL_ALLOWLIST", "obabel")
    with pytest.raises(ToolDenied, match="gnina.exe"):
        require_tool(str(program), "Gnina")
    monkeypatch.setenv("MOLMANAGER_TOOL_ALLOWLIST", "gnina.exe")
    require_tool(str(program), "Gnina")


def test_digest_pin_rejects_a_changed_program(tmp_path: Path, monkeypatch) -> None:
    import hashlib

    monkeypatch.delenv("MOLMANAGER_TOOL_ALLOWLIST", raising=False)
    program = tmp_path / "obabel.exe"
    program.write_bytes(b"openbabel")
    pins = tmp_path / "digests.txt"
    pins.write_text(hashlib.sha256(b"openbabel").hexdigest() + " obabel.exe\n", encoding="utf-8")
    monkeypatch.setenv("MOLMANAGER_TOOL_DIGESTS", str(pins))
    require_tool(str(program), "Open Babel")
    program.write_bytes(b"changed")
    with pytest.raises(ToolDenied, match="does not match"):
        require_tool(str(program), "Open Babel")
