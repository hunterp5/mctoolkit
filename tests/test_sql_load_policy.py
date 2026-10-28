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

from __future__ import annotations

import pytest

from molmanager.chem.molecule_conversion import redact_sqlalchemy_url
from molmanager.services.sql_load_policy import (
    SqlWriteBlocked,
    assert_read_only_statement,
    dialect_family,
    engine_kwargs_for_sql_load,
    install_read_only_guards,
    make_sqlite_read_only_creator,
    read_only_session_statements,
    read_only_transaction_statement,
    sql_looks_destructive,
    sqlite_database_path_from_url,
)
from molmanager.services.table_scope import collect_scoped_pairs, resolve_structure_row_for_oid


@pytest.mark.parametrize(
    "sql,expect",
    [
        ("SELECT * FROM compounds", False),
        ("  select id, smiles from t where mw > 100", False),
        ("INSERT INTO t VALUES (1)", True),
        ("DELETE FROM t", True),
        ("DROP TABLE t", True),
        ("UPDATE t SET x=1", True),
        ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", True),
        ("SELECT a INTO b FROM c", True),
        ("SELECT 1; DELETE FROM t", True),
        ("-- comment\nSELECT * FROM t", False),
        ("/* block */\nTRUNCATE TABLE t", True),
    ],
)
def test_sql_looks_destructive(sql: str, expect: bool) -> None:
    assert sql_looks_destructive(sql) is expect


def test_sqlite_database_path_from_url() -> None:
    assert sqlite_database_path_from_url("sqlite:///C:/data/mols.db") == "C:/data/mols.db"
    assert sqlite_database_path_from_url("sqlite:///:memory:") is None


def test_engine_kwargs_read_only_sqlite(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "x.db"
    sqlite3.connect(str(db)).close()
    url = "sqlite:///" + str(db).replace("\\", "/")
    out_url, eng_kw = engine_kwargs_for_sql_load(
        url,
        read_only=True,
        sqlite_timeout_s=30.0,
        pg_connect_timeout=10,
    )
    assert out_url == "sqlite://"
    assert callable(eng_kw.get("creator"))
    # Creator must open the file.
    con = eng_kw["creator"]()
    con.close()


def test_redact_sqlalchemy_url_hides_a_password_inside_an_error() -> None:
    raw = (
        "OperationalError: (psycopg.OperationalError) postgresql://chem:s3cret@db.internal:5432/lab"
    )
    assert "s3cret" not in redact_sqlalchemy_url(raw)
    assert "postgresql://chem:***@db.internal:5432/lab" in redact_sqlalchemy_url(raw)


def test_read_only_session_sql_by_engine() -> None:
    assert dialect_family("postgresql+psycopg://u:p@h/db") == "postgresql"
    assert read_only_session_statements("postgresql://h/db") == (
        "SET default_transaction_read_only = on",
    )
    assert read_only_transaction_statement("postgres://h/db") == "SET TRANSACTION READ ONLY"
    assert read_only_session_statements("mysql+pymysql://u:p@h/db") == (
        "SET SESSION TRANSACTION READ ONLY",
    )
    assert read_only_transaction_statement("mysql://h/db") is None
    assert (
        read_only_session_statements("mssql+pyodbc://u:p@h/db?driver=ODBC+Driver+17+for+SQL+Server")
        == ()
    )
    assert dialect_family("mssql+pyodbc://h/db") == "mssql"


def test_read_only_statement_guard() -> None:
    assert_read_only_statement("SELECT id, smiles FROM compounds")
    assert_read_only_statement("SET TRANSACTION READ ONLY")
    with pytest.raises(SqlWriteBlocked):
        assert_read_only_statement("UPDATE compounds SET smiles = 'C'")
    with pytest.raises(SqlWriteBlocked):
        assert_read_only_statement("SET default_transaction_read_only = off")
    with pytest.raises(SqlWriteBlocked):
        assert_read_only_statement("EXPLAIN ANALYZE DELETE FROM compounds")
    with pytest.raises(SqlWriteBlocked):
        assert_read_only_statement("SELECT * FROM compounds FOR UPDATE")
    with pytest.raises(SqlWriteBlocked):
        assert_read_only_statement("SELECT 1; DELETE FROM compounds")


def test_read_only_engine_blocks_a_statement_the_keyword_scan_might_miss(tmp_path) -> None:
    import sqlite3

    from sqlalchemy import create_engine, text

    db = tmp_path / "lab.db"
    raw = sqlite3.connect(str(db))
    raw.execute("CREATE TABLE compounds (smiles TEXT)")
    raw.execute("INSERT INTO compounds VALUES ('CCO')")
    raw.commit()
    raw.close()

    url = "sqlite:///" + str(db).replace("\\", "/")
    out_url, eng_kw = engine_kwargs_for_sql_load(
        url,
        read_only=True,
        sqlite_timeout_s=5.0,
        pg_connect_timeout=5,
    )
    engine = create_engine(out_url, **eng_kw)
    install_read_only_guards(engine, url)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT smiles FROM compounds")).scalar() == "CCO"
        with pytest.raises(SqlWriteBlocked):
            conn.execute(text("UPDATE compounds SET smiles = 'CC'"))
    engine.dispose()


def test_make_sqlite_read_only_creator_blocks_writes(tmp_path) -> None:
    import sqlite3

    db = tmp_path / "ro.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE t (x INTEGER)")
    con.commit()
    con.close()

    creator = make_sqlite_read_only_creator(str(db), timeout_s=5.0)
    ro = creator()
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO t VALUES (1)")
    ro.close()


def test_collect_scoped_pairs_filters() -> None:
    oids = [10, 20, 30]
    values = {0: "a", 1: None, 2: "c"}

    got = collect_scoped_pairs(
        3,
        row_oid=lambda r: oids[r],
        resolve=lambda r, oid: values[r],
        allowed_oids={10, 30},
    )
    assert got == [(10, "a"), (30, "c")]


def test_resolve_structure_row_for_oid_prefers_valid_batch_map() -> None:
    row = resolve_structure_row_for_oid(
        7,
        row_count=3,
        cell_text_col0=lambda r: "7" if r == 1 else "0",
        logical_row_for_oid=lambda oid: 99,
        render2d_row_by_oid={7: 1},
    )
    assert row == 1


def test_resolve_structure_row_for_oid_falls_back() -> None:
    row = resolve_structure_row_for_oid(
        7,
        row_count=3,
        cell_text_col0=lambda r: "0",
        logical_row_for_oid=lambda oid: 2,
        render2d_row_by_oid={7: 1},
    )
    assert row == 2
