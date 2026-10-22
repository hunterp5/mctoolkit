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

"""Convert legacy MolManager sessions (versions 1-3 and session CSV) to version 4.

The application only opens version-4 sessions. This script keeps frozen copies of the
old readers so existing files can still be brought forward::

    python scripts/convert_session.py old.cms            # replaces old.cms, keeps old.cms.bak
    python scripts/convert_session.py old.cms -o new.cms
    python scripts/convert_session.py table_session.csv  # writes table_session.cms

Structures are written as saved: RDKit binaries when the session had them, otherwise
SMILES, which the application parses when a row is first drawn. Depictions are not
converted; the application renders them after the first open and saves them with the
next session save.
"""

from __future__ import annotations

import argparse
import base64
import csv
import gzip
import io
import json
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from molmanager.chem.structure_source_headers import (  # noqa: E402
    is_tool_generated_structure_header,
)
from molmanager.table.session_v4 import (  # noqa: E402
    SessionSaveSnapshot,
    is_session_v4,
    remove_sqlite_file,
    split_manifest,
    write_session_v4,
)
from molmanager.ui.column_store import ColumnStore  # noqa: E402

_GZIP_MAGIC = b"\x1f\x8b"
_ZIP_MAGIC = b"PK"
_V3_MANIFEST = "manifest.json"
_CMS_MEMBER = "session.cms"
_ENSEMBLES_MEMBER = "ensembles.sqlite"
_FORMAT_ALIASES = frozenset({"molmanager_session", "MOLMANAGER_session", "chemmanager_session"})
# Keys that describe rows in legacy documents; version 4 stores rows outside the manifest.
_ROW_KEYS = frozenset(
    {
        "format",
        "version",
        "rows",
        "ids",
        "values",
        "data_headers",
        "structure_smiles",
        "structure_mols",
        "structure_field_override",
        "row_count",
        "chunk_rows",
    }
)


class LegacySession:
    """A decoded legacy session: workspace metadata plus row and structure lists."""

    def __init__(self, doc: dict[str, Any]) -> None:
        self.doc = doc
        self.oids: list[int] = []
        self.cells: list[dict[str, str]] = []
        self.smiles: list[str] = []
        self.mol_blobs: list[bytes | None] = []
        self.ensembles: bytes | None = None

    def add_row(self, oid: int, cells: dict[str, str], smiles: str, blob: bytes | None) -> None:
        self.oids.append(int(oid))
        self.cells.append(cells)
        self.smiles.append(smiles)
        self.mol_blobs.append(blob)


def _loads_json(raw: bytes) -> Any:
    try:
        import orjson

        return orjson.loads(raw)
    except (ImportError, ValueError):
        return json.loads(raw.decode("utf-8"))


def _decode_mol_b64(raw: object) -> bytes | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return base64.b64decode(raw.encode("ascii"), validate=False) or None
    except ValueError:
        return None


def _row_smiles(cells: dict[str, str], saved: str) -> str:
    """Saved structure identity first, then the SMILES cell (never a tool column)."""
    smi = str(saved or "").strip()
    return smi or str(cells.get("SMILES") or "").strip()


def _structure_field(doc: dict[str, Any], headers: list[str]) -> str | None:
    """Data column that older sessions named as the Structure source, if still valid."""
    field = doc.get("structure_field_override")
    if not isinstance(field, str) or not field.strip():
        return None
    field = field.strip()
    if field not in headers or is_tool_generated_structure_header(field):
        return None
    return field


def _columnar_rows(
    chunk: dict[str, Any], data_headers: list[str]
) -> Iterator[tuple[int, dict[str, str], str, bytes | None]]:
    """Rows of a version-2 document or a version-3 chunk."""
    ids = list(chunk.get("ids") or [])
    values = list(chunk.get("values") or [])
    saved_smiles = chunk.get("structure_smiles")
    saved_smiles = saved_smiles if isinstance(saved_smiles, list) else []
    saved_mols = chunk.get("structure_mols")
    saved_mols = saved_mols if isinstance(saved_mols, list) else []
    for i in range(min(len(ids), len(values))):
        try:
            oid = int(ids[i])
        except (TypeError, ValueError):
            continue
        row_vals = values[i]
        if not isinstance(row_vals, (list, tuple)):
            continue
        cells = {
            str(h): ("" if j >= len(row_vals) or row_vals[j] is None else str(row_vals[j]))
            for j, h in enumerate(data_headers)
        }
        saved = str(saved_smiles[i] or "") if i < len(saved_smiles) else ""
        blob = _decode_mol_b64(saved_mols[i]) if i < len(saved_mols) else None
        yield oid, cells, _row_smiles(cells, saved), blob


def _data_headers(doc: dict[str, Any]) -> list[str]:
    saved = doc.get("data_headers")
    if isinstance(saved, list) and saved:
        return [str(h) for h in saved]
    return [str(h) for h in (doc.get("headers") or []) if h and h not in ("ID_HIDDEN", "Structure")]


def _read_v1_rows(doc: dict[str, Any], session: LegacySession) -> None:
    saved = doc.get("structure_smiles")
    saved = saved if isinstance(saved, list) else []
    for i, entry in enumerate(doc.get("rows") or []):
        if not isinstance(entry, dict):
            continue
        try:
            oid = int(entry["id"])
        except (KeyError, TypeError, ValueError):
            continue
        cells = entry.get("cells") if isinstance(entry.get("cells"), dict) else {}
        cells = {str(k): "" if v is None else str(v) for k, v in cells.items()}
        smi = _row_smiles(cells, str(saved[i] or "") if i < len(saved) else "")
        session.add_row(oid, cells, smi, None)


def _read_v3(data: bytes) -> LegacySession:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = _loads_json(zf.read(_V3_MANIFEST))
        if not isinstance(manifest, dict):
            raise ValueError("Session manifest must be a JSON object.")
        session = LegacySession(manifest)
        headers = _data_headers(manifest)
        names = sorted(n for n in zf.namelist() if n.startswith("rows/") and n.endswith(".json"))
        for name in names:
            chunk = _loads_json(zf.read(name))
            if not isinstance(chunk, dict):
                raise ValueError(f"Session chunk {name} must be a JSON object.")
            for row in _columnar_rows(chunk, headers):
                session.add_row(*row)
        if _ENSEMBLES_MEMBER in zf.namelist():
            session.ensembles = zf.read(_ENSEMBLES_MEMBER) or None
    return session


def read_legacy_cms(path: Path) -> LegacySession:
    """Decode a version 1, 2 or 3 ``.cms`` / ``.json`` session."""
    data = path.read_bytes()
    ensembles = None
    if data.startswith(_ZIP_MAGIC):
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = zf.namelist()
            if _V3_MANIFEST in names:
                return _read_v3(data)
            cms_name = _CMS_MEMBER if _CMS_MEMBER in names else None
            if cms_name is None:
                cms_name = next((n for n in names if n.endswith((".cms", ".json"))), None)
            if cms_name is None:
                raise ValueError("Session zip is missing session.cms.")
            data = zf.read(cms_name)
            if _ENSEMBLES_MEMBER in names:
                ensembles = zf.read(_ENSEMBLES_MEMBER) or None
    if data.startswith(_GZIP_MAGIC):
        data = gzip.decompress(data)
    doc = _loads_json(data)
    if not isinstance(doc, dict):
        raise ValueError("Session root must be a JSON object.")
    session = LegacySession(doc)
    session.ensembles = ensembles
    version = int(doc.get("version", 0) or 0)
    if version == 1 or ("rows" in doc and "ids" not in doc):
        _read_v1_rows(doc, session)
    elif version == 2 or "ids" in doc:
        for row in _columnar_rows(doc, _data_headers(doc)):
            session.add_row(*row)
    else:
        raise ValueError(f"Unsupported session version: {version}")
    return session


def read_session_csv(path: Path) -> LegacySession:
    """Decode a legacy session CSV: a SMILES column plus property columns."""
    with path.open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.DictReader(handle)
        cols = list(reader.fieldnames or [])
        if "SMILES" not in cols:
            cols = ["SMILES", *cols]
        session = LegacySession({"headers": ["ID_HIDDEN", "Structure", *cols]})
        for oid, row in enumerate(reader):
            cells = {c: str(row.get(c, "") or "") for c in cols}
            session.add_row(oid, cells, cells["SMILES"].strip(), None)
    session.doc["next_oid"] = len(session.oids)
    return session


def _write_mols_db(session: LegacySession, structure_field: str | None) -> Path | None:
    rows = []
    for oid, cells, smi, blob in zip(
        session.oids, session.cells, session.smiles, session.mol_blobs, strict=True
    ):
        if structure_field:
            smi = str(cells.get(structure_field) or "").strip() or smi
            blob = None
        if blob or smi:
            rows.append((oid, blob, smi or None))
    if not rows:
        return None
    handle = tempfile.NamedTemporaryFile(
        prefix="molmanager_convert_", suffix=".sqlite3", delete=False
    )
    handle.close()
    out = Path(handle.name)
    conn = sqlite3.connect(str(out))
    try:
        conn.execute("CREATE TABLE mols (oid INTEGER PRIMARY KEY, blob BLOB, smiles TEXT)")
        conn.executemany("INSERT OR REPLACE INTO mols (oid, blob, smiles) VALUES (?, ?, ?)", rows)
        conn.commit()
    finally:
        conn.close()
    return out


def _write_ensembles_db(raw: bytes | None) -> Path | None:
    if not raw:
        return None
    handle = tempfile.NamedTemporaryFile(
        prefix="molmanager_convert_", suffix=".sqlite3", delete=False
    )
    handle.write(raw)
    handle.close()
    return Path(handle.name)


def convert(session: LegacySession, dest: Path) -> int:
    """Write *session* as a version-4 file at *dest*. Returns the row count."""
    doc = session.doc
    fmt = doc.get("format")
    if fmt is not None and fmt not in _FORMAT_ALIASES:
        raise ValueError("Not a MolManager session.")
    headers = [str(h) for h in (doc.get("headers") or ["ID_HIDDEN", "Structure", "SMILES"])]
    if len(headers) < 2 or headers[:2] != ["ID_HIDDEN", "Structure"]:
        raise ValueError("Invalid session headers.")
    data_headers = headers[2:]
    rows = ColumnStore()
    rows.append_columns(
        session.oids,
        {h: [cells.get(h, "") for cells in session.cells] for h in data_headers},
    )
    manifest, sidecars = split_manifest({k: v for k, v in doc.items() if k not in _ROW_KEYS})
    manifest["headers"] = headers
    if session.oids:
        manifest["next_oid"] = max(int(doc.get("next_oid") or 0), max(session.oids) + 1)
    mol_db = _write_mols_db(session, _structure_field(doc, headers))
    ensembles_db = _write_ensembles_db(session.ensembles)
    try:
        write_session_v4(
            dest,
            SessionSaveSnapshot(
                manifest=manifest,
                oids=rows.oids_blob(),
                columns=rows.to_blobs(data_headers),
                sidecars=sidecars,
                mol_db=mol_db,
                ensembles_db=ensembles_db,
                row_count=rows.n,
            ),
        )
    finally:
        for temp in (mol_db, ensembles_db):
            if temp is not None:
                remove_sqlite_file(temp)
    return rows.n


def convert_path(source: Path, output: Path | None = None) -> Path:
    """Convert *source*; without *output*, ``.cms`` files are replaced after a ``.bak`` copy."""
    if is_session_v4(source):
        raise ValueError(f"{source} is already a version-4 session.")
    is_csv = source.suffix.lower() == ".csv"
    session = read_session_csv(source) if is_csv else read_legacy_cms(source)
    dest = output or source.with_suffix(".cms")
    if dest.resolve() == source.resolve():
        shutil.copy2(source, source.with_name(source.name + ".bak"))
    convert(session, dest)
    return dest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("sources", nargs="+", type=Path, help="legacy .cms, .json or .csv files")
    parser.add_argument("-o", "--output", type=Path, help="output path (one source only)")
    args = parser.parse_args(argv)
    if args.output is not None and len(args.sources) != 1:
        parser.error("--output takes exactly one source")
    failed = 0
    for source in args.sources:
        try:
            dest = convert_path(source, args.output)
        except (OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as exc:
            print(f"{source}: {exc}", file=sys.stderr)
            failed += 1
            continue
        print(f"{source} -> {dest}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
