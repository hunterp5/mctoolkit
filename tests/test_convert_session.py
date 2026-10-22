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

"""``scripts/convert_session.py`` brings version 1-3 and CSV sessions to version 4."""

from __future__ import annotations

import base64
import gzip
import importlib.util
import io
import json
import sqlite3
import zipfile
from pathlib import Path

import pytest
from rdkit import Chem

from molmanager.storage import EnsembleStore
from molmanager.table.session_v4 import is_legacy_session, is_session_v4, read_session_v4

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "convert_session.py"
_spec = importlib.util.spec_from_file_location("convert_session", _SCRIPT)
convert_session = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(convert_session)

HEADERS = ["ID_HIDDEN", "Structure", "SMILES", "Protonated", "MW"]


def _mols(opened) -> dict[int, tuple[bytes | None, str | None]]:
    if opened.mol_db is None:
        return {}
    conn = sqlite3.connect(str(opened.mol_db))
    try:
        return {int(o): (b, s) for o, b, s in conn.execute("SELECT oid, blob, smiles FROM mols")}
    finally:
        conn.close()


def _convert(tmp_path: Path, name: str, data: bytes) -> object:
    src = tmp_path / name
    src.write_bytes(data)
    assert is_legacy_session(src)
    dest = convert_session.convert_path(src, tmp_path / "out.cms")
    assert is_session_v4(dest)
    return read_session_v4(dest)


def _v2_doc() -> dict:
    blob = Chem.MolFromSmiles("CCN").ToBinary()
    return {
        "format": "molmanager_session",
        "version": 2,
        "headers": HEADERS,
        "data_headers": ["SMILES", "Protonated", "MW"],
        "ids": [4, 7],
        "values": [["CCO", "CC[OH2+]", "46.07"], ["", "", "45.08"]],
        "structure_smiles": ["CCO", ""],
        "structure_mols": ["", base64.b64encode(blob).decode("ascii")],
        "next_oid": 8,
        "global_bounds": {"MW": {"min": 45.08, "max": 46.07, "is_int": False}},
        "ionization_sidecar": {"v": 1, "entries": {}},
        "notepad": {"text": "hello"},
    }


def test_v1_keeps_structure_identity_not_protonated(tmp_path) -> None:
    doc = {
        "format": "molmanager_session",
        "version": 1,
        "headers": HEADERS,
        "rows": [
            {"id": 0, "cells": {"SMILES": "", "Protonated": "CC[NH3+]", "MW": "45"}},
            {"id": 1, "cells": {"SMILES": "c1ccccc1", "Protonated": "", "MW": "78"}},
        ],
        "structure_smiles": ["CCN", ""],
        "next_oid": 2,
    }
    opened = _convert(tmp_path, "v1.json", json.dumps(doc).encode())
    try:
        assert list(opened.rows.oids) == [0, 1]
        assert opened.rows.get_text(0, "Protonated") == "CC[NH3+]"
        mols = _mols(opened)
        assert mols[0][1] == "CCN"
        assert mols[1][1] == "c1ccccc1"
    finally:
        opened.discard_temp_files()


def test_v2_gzip_keeps_cells_mol_binaries_bounds_and_sidecars(tmp_path) -> None:
    opened = _convert(tmp_path, "v2.cms", gzip.compress(json.dumps(_v2_doc()).encode()))
    try:
        assert list(opened.rows.oids) == [4, 7]
        assert opened.rows.column_kind("MW") == "float"
        assert opened.rows.get_text(1, "MW") == "45.08"
        assert opened.manifest["next_oid"] == 8
        assert opened.manifest["global_bounds"]["MW"]["max"] == pytest.approx(46.07)
        assert opened.manifest["notepad"] == {"text": "hello"}
        assert "ids" not in opened.manifest and "format" not in opened.manifest
        mols = _mols(opened)
        assert mols[4] == (None, "CCO")
        assert Chem.MolToSmiles(Chem.Mol(mols[7][0])) == "CCN"
    finally:
        opened.discard_temp_files()


def test_v2_zip_bundle_keeps_ensembles(tmp_path) -> None:
    store = EnsembleStore()
    try:
        store[(4, "Confs")] = "AAAA"
        ensembles = store.export_sqlite_bytes(None)
    finally:
        store.close()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("session.cms", gzip.compress(json.dumps(_v2_doc()).encode()))
        zf.writestr("ensembles.sqlite", ensembles)
    opened = _convert(tmp_path, "bundle.cms", buf.getvalue())
    try:
        restored = EnsembleStore(opened.ensembles_db)
        try:
            assert restored[(4, "Confs")] == "AAAA"
        finally:
            restored.close()
    finally:
        opened.discard_temp_files()


def test_v3_chunks_are_joined_in_order(tmp_path) -> None:
    manifest = {
        "format": "molmanager_session",
        "version": 3,
        "headers": ["ID_HIDDEN", "Structure", "SMILES"],
        "data_headers": ["SMILES"],
        "row_count": 3,
        "chunk_rows": 2,
        "next_oid": 3,
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("manifest.json", json.dumps(manifest))
        zf.writestr("rows/00001.json", json.dumps({"ids": [2], "values": [["CC"]]}))
        zf.writestr(
            "rows/00000.json",
            json.dumps({"ids": [0, 1], "values": [["C"], ["CCO"]], "structure_smiles": ["C", ""]}),
        )
    opened = _convert(tmp_path, "v3.cms", buf.getvalue())
    try:
        assert list(opened.rows.oids) == [0, 1, 2]
        assert "chunk_rows" not in opened.manifest
        assert {oid: smi for oid, (_b, smi) in _mols(opened).items()} == {
            0: "C",
            1: "CCO",
            2: "CC",
        }
    finally:
        opened.discard_temp_files()


def test_structure_field_override_moves_that_column_into_structures(tmp_path) -> None:
    doc = _v2_doc()
    doc["headers"] = ["ID_HIDDEN", "Structure", "SMILES", "Alt", "MW"]
    doc["data_headers"] = ["SMILES", "Alt", "MW"]
    doc["values"] = [["CCO", "CCCl", "1"], ["CCN", "CCBr", "2"]]
    doc["structure_field_override"] = "Alt"
    opened = _convert(tmp_path, "override.cms", gzip.compress(json.dumps(doc).encode()))
    try:
        assert "structure_field_override" not in opened.manifest
        assert {oid: smi for oid, (_b, smi) in _mols(opened).items()} == {4: "CCCl", 7: "CCBr"}
    finally:
        opened.discard_temp_files()


def test_session_csv_becomes_rows_with_smiles_structures(tmp_path) -> None:
    src = tmp_path / "table.csv"
    src.write_text("SMILES,Name\nCCO,ethanol\n,blank\n", encoding="utf-8")
    dest = convert_session.convert_path(src)
    assert dest == tmp_path / "table.cms"
    opened = read_session_v4(dest)
    try:
        assert opened.manifest["headers"] == ["ID_HIDDEN", "Structure", "SMILES", "Name"]
        assert [opened.rows.get_text(i, "Name") for i in range(2)] == ["ethanol", "blank"]
        assert opened.manifest["next_oid"] == 2
        assert {oid: smi for oid, (_b, smi) in _mols(opened).items()} == {0: "CCO"}
    finally:
        opened.discard_temp_files()


def test_in_place_conversion_keeps_a_backup_and_refuses_v4(tmp_path) -> None:
    src = tmp_path / "s.cms"
    raw = gzip.compress(json.dumps(_v2_doc()).encode())
    src.write_bytes(raw)
    assert convert_session.main([str(src)]) == 0
    assert is_session_v4(src)
    assert (tmp_path / "s.cms.bak").read_bytes() == raw
    assert convert_session.main([str(src)]) == 1
