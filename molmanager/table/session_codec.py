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

"""Encode/decode MolManager ``.cms`` session documents (compact v2 + gzip)."""

from __future__ import annotations

import base64
import gzip
import io
import json
import logging
import math
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

SESSION_FORMAT = "molmanager_session"
SESSION_FORMAT_ALIASES = frozenset(
    {"molmanager_session", "MOLMANAGER_session", "chemmanager_session"}
)
SESSION_VERSION_CURRENT = 2
SESSION_VERSIONS_SUPPORTED = frozenset({1, 2, 3})
SESSION_V3_MANIFEST = "manifest.json"
SESSION_V3_CHUNK_ROWS = 10_000

_GZIP_MAGIC = b"\x1f\x8b"
_ZIP_MAGIC = b"PK"
SESSION_CMS_MEMBER = "session.cms"
SESSION_ENSEMBLES_MEMBER = "ensembles.sqlite"
# In-memory only: compact JSON must not serialize this bytes payload.
SESSION_ENSEMBLES_KEY = "__ensembles_sqlite__"

# Top-level keys that may be dropped when empty to shrink saved documents.
_OMIT_IF_EMPTY = frozenset(
    {
        "zoomed_ids",
        "workspace_layout",
        "docked_plots",
        "floating_plots",
        "table_layout",
        "filters",
        "column_logical_order",
        "sort_column",
        "sort_mode",
        "column_colors",
        "logarithmic_columns",
        "confs_sidecar",
        "som_browse",
        "ionization_sidecar",
        "mmp_ledger",
        "dock_results",
        "pose_column_contexts",
        "structure_smiles",
        "structure_mols",
        "global_bounds",
        "depiction_2d",
        "table_search",
        "protein_viewer",
        "gnina_dock",
        "row_lists",
        "notepad",
    }
)


def session_format_ok(fmt: object) -> bool:
    return isinstance(fmt, str) and fmt in SESSION_FORMAT_ALIASES


def session_version_ok(version: object) -> bool:
    try:
        return int(version) in SESSION_VERSIONS_SUPPORTED
    except (TypeError, ValueError):
        return False


def _dumps_json_bytes(obj: Any) -> bytes:
    try:
        import orjson

        return orjson.dumps(obj)
    except Exception:
        return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _loads_json_bytes(raw: bytes) -> Any:
    try:
        import orjson

        return orjson.loads(raw)
    except Exception:
        return json.loads(raw.decode("utf-8"))


def dumps_session_document(doc: dict[str, Any], *, gzip_compress: bool = True) -> bytes:
    """Serialize a session document to bytes (gzip JSON, or zip with ensembles)."""
    extra = None
    payload_doc = doc
    if isinstance(doc, dict) and SESSION_ENSEMBLES_KEY in doc:
        extra = doc.get(SESSION_ENSEMBLES_KEY)
        if not isinstance(extra, (bytes, bytearray)) or not extra:
            extra = None
        payload_doc = {k: v for k, v in doc.items() if k != SESSION_ENSEMBLES_KEY}
    payload = _dumps_json_bytes(payload_doc)
    if gzip_compress:
        payload = gzip.compress(payload, compresslevel=6)
    if not extra:
        return payload
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(SESSION_CMS_MEMBER, payload)
        zf.writestr(SESSION_ENSEMBLES_MEMBER, bytes(extra))
    return buf.getvalue()


def _session_zip_payload(data: bytes) -> tuple[bytes, bytes | None]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        cms_name = None
        if SESSION_CMS_MEMBER in names:
            cms_name = SESSION_CMS_MEMBER
        else:
            cms_name = next(
                (n for n in names if n.endswith(".cms") or n.endswith(".json")),
                None,
            )
        if cms_name is None:
            raise ValueError("Session zip is missing session.cms.")
        cms = zf.read(cms_name)
        ensembles = zf.read(SESSION_ENSEMBLES_MEMBER) if SESSION_ENSEMBLES_MEMBER in names else None
    return cms, ensembles


def session_path_is_v3(path: str) -> bool:
    """True when *path* is a chunked version-3 session zip."""
    try:
        if not zipfile.is_zipfile(path):
            return False
        with zipfile.ZipFile(path) as zf:
            return SESSION_V3_MANIFEST in zf.namelist()
    except (OSError, zipfile.BadZipFile):
        return False


def read_session_v3_manifest(path: str) -> dict[str, Any]:
    """Read the small manifest. Row chunks stay on disk."""
    with zipfile.ZipFile(path) as zf:
        manifest = _loads_json_bytes(zf.read(SESSION_V3_MANIFEST))
    if not isinstance(manifest, dict):
        raise ValueError("Session manifest must be a JSON object.")
    return manifest


def session_v3_chunk_names(path: str) -> list[str]:
    with zipfile.ZipFile(path) as zf:
        return sorted(
            name for name in zf.namelist() if name.startswith("rows/") and name.endswith(".json")
        )


def read_session_v3_chunk(path: str, name: str) -> dict[str, Any]:
    with zipfile.ZipFile(path) as zf:
        chunk = _loads_json_bytes(zf.read(name))
    if not isinstance(chunk, dict):
        raise ValueError(f"Session chunk {name} must be a JSON object.")
    return chunk


def read_session_v3_ensembles(path: str) -> bytes | None:
    with zipfile.ZipFile(path) as zf:
        if SESSION_ENSEMBLES_MEMBER not in zf.namelist():
            return None
        return zf.read(SESSION_ENSEMBLES_MEMBER)


def session_v3_chunk_rows(
    chunk: dict[str, Any], data_headers: list[str]
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """One version-3 chunk as restore rows plus parallel structure lists."""
    ids = list(chunk.get("ids") or [])
    values = list(chunk.get("values") or [])
    saved_structure = chunk.get("structure_smiles")
    if not isinstance(saved_structure, list):
        saved_structure = []
    saved_mols = chunk.get("structure_mols")
    keep_mols = isinstance(saved_mols, list)
    if not keep_mols:
        saved_mols = []
    rows: list[dict[str, Any]] = []
    structure_smiles: list[str] = []
    structure_mols: list[str] = []
    n = min(len(ids), len(values))
    for i in range(n):
        try:
            oid = int(ids[i])
        except (TypeError, ValueError):
            continue
        row_vals = values[i]
        if not isinstance(row_vals, (list, tuple)):
            continue
        cells: dict[str, str] = {}
        for j, header in enumerate(data_headers):
            if j < len(row_vals) and row_vals[j] is not None:
                cells[str(header)] = str(row_vals[j])
            else:
                cells[str(header)] = ""
        rows.append({"id": oid, "cells": cells})
        saved_smi = str(saved_structure[i] or "") if i < len(saved_structure) else ""
        structure_smiles.append(row_structure_smiles(cells, saved_smi))
        if keep_mols:
            structure_mols.append(str(saved_mols[i] or "") if i < len(saved_mols) else "")
    return rows, structure_smiles, structure_mols


def _load_v3_zip(data: bytes) -> dict[str, Any]:
    """Reassemble a version-3 zip into one document. Streaming open does not use this."""
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        manifest = _loads_json_bytes(zf.read(SESSION_V3_MANIFEST))
        if not isinstance(manifest, dict):
            raise ValueError("Session manifest must be a JSON object.")
        ids: list[Any] = []
        values: list[Any] = []
        smiles: list[Any] = []
        mols: list[Any] = []
        names = sorted(
            name for name in zf.namelist() if name.startswith("rows/") and name.endswith(".json")
        )
        for name in names:
            chunk = _loads_json_bytes(zf.read(name))
            if not isinstance(chunk, dict):
                raise ValueError(f"Session chunk {name} must be a JSON object.")
            ids.extend(chunk.get("ids") or [])
            values.extend(chunk.get("values") or [])
            smiles.extend(chunk.get("structure_smiles") or [])
            mols.extend(chunk.get("structure_mols") or [])
        manifest["ids"] = ids
        manifest["values"] = values
        if smiles:
            manifest["structure_smiles"] = smiles
        if any(mols):
            manifest["structure_mols"] = mols
        if SESSION_ENSEMBLES_MEMBER in zf.namelist():
            manifest[SESSION_ENSEMBLES_KEY] = zf.read(SESSION_ENSEMBLES_MEMBER)
    return manifest


def loads_session_bytes(raw: bytes | str) -> dict[str, Any]:
    """Parse session file bytes (gzip JSON, zip bundle, or plain JSON) into a dict."""
    if isinstance(raw, str):
        data = raw.encode("utf-8")
    else:
        data = raw
    ensembles = None
    if data.startswith(_ZIP_MAGIC):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                v3 = SESSION_V3_MANIFEST in zf.namelist()
        except zipfile.BadZipFile:
            v3 = False
        if v3:
            return _load_v3_zip(data)
        data, ensembles = _session_zip_payload(data)
    if data.startswith(_GZIP_MAGIC):
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            raise ValueError(f"Could not decompress session file: {exc}") from exc
    doc = _loads_json_bytes(data)
    if not isinstance(doc, dict):
        raise ValueError("Session root must be a JSON object.")
    if ensembles:
        doc[SESSION_ENSEMBLES_KEY] = ensembles
    return doc


def _is_empty_optional(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, dict, str)) and len(value) == 0:
        return True
    return False


def row_structure_smiles(cells: dict[str, Any] | None, saved_smiles: str = "") -> str:
    """Structure-column SMILES for one row: saved identity first, then a SMILES cell.

    Tool-generated columns such as Protonated are never used as a fallback.
    """
    smi = str(saved_smiles or "").strip()
    if smi:
        return smi
    if not isinstance(cells, dict):
        return ""
    return str(cells.get("SMILES") or "").strip()


def encode_mol_blob_b64(blob: bytes | None) -> str:
    """Base64 for one structure mol blob (empty string when missing)."""
    if not blob:
        return ""
    return base64.b64encode(blob).decode("ascii")


def decode_mol_blob_b64(raw: object) -> bytes | None:
    """Decode one ``structure_mols`` entry; ``None`` when missing or invalid."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        blob = base64.b64decode(raw.encode("ascii"), validate=False)
    except Exception:
        return None
    return blob or None


def compact_global_bounds(raw: object) -> dict[str, dict[str, float | bool]] | None:
    """JSON-safe numeric bounds dict, or ``None`` when empty/invalid."""
    if not isinstance(raw, dict) or not raw:
        return None
    out: dict[str, dict[str, float | bool]] = {}
    for key, meta in raw.items():
        name = str(key or "").strip()
        if not name or not isinstance(meta, dict):
            continue
        try:
            lo = float(meta["min"])
            hi = float(meta["max"])
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(lo) or not math.isfinite(hi):
            continue
        out[name] = {"min": lo, "max": hi, "is_int": bool(meta.get("is_int", False))}
    return out or None


parse_session_global_bounds = compact_global_bounds


def _structure_smiles_from_v1_rows(rows: Any, saved: Any) -> list[str]:
    out: list[str] = []
    saved_list = saved if isinstance(saved, list) else None
    if not isinstance(rows, list):
        return [str(s or "") for s in saved_list] if saved_list is not None else []
    for i, entry in enumerate(rows):
        cells = entry.get("cells") if isinstance(entry, dict) else None
        saved_smi = ""
        if saved_list is not None and i < len(saved_list):
            saved_smi = str(saved_list[i] or "")
        out.append(row_structure_smiles(cells if isinstance(cells, dict) else None, saved_smi))
    return out


def compact_session_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Convert an internal (v1-shaped) document to compact session version 2."""
    headers = list(doc.get("headers") or [])
    data_headers = [h for h in headers if h and h not in ("ID_HIDDEN", "Structure")]
    rows = doc.get("rows") or []
    ids: list[int] = []
    values: list[list[str]] = []
    structure_smiles: list[str] = []
    structure_mols: list[str] = []
    saved_structure = doc.get("structure_smiles")
    if not isinstance(saved_structure, list):
        saved_structure = None
    saved_mols = doc.get("structure_mols")
    if not isinstance(saved_mols, list):
        saved_mols = None
    if isinstance(rows, list):
        for row_i, entry in enumerate(rows):
            if not isinstance(entry, dict):
                continue
            try:
                oid = int(entry["id"])
            except (KeyError, TypeError, ValueError):
                continue
            cells = entry.get("cells") or {}
            if not isinstance(cells, dict):
                cells = {}
            ids.append(oid)
            values.append([str(cells.get(h, "") or "") for h in data_headers])
            saved_smi = ""
            if saved_structure is not None and row_i < len(saved_structure):
                saved_smi = str(saved_structure[row_i] or "")
            structure_smiles.append(row_structure_smiles(cells, saved_smi))
            if saved_mols is not None and row_i < len(saved_mols):
                structure_mols.append(str(saved_mols[row_i] or ""))
            else:
                structure_mols.append("")

    out: dict[str, Any] = {
        "format": doc.get("format") or SESSION_FORMAT,
        "version": SESSION_VERSION_CURRENT,
        "headers": headers,
        "data_headers": data_headers,
        "ids": ids,
        "values": values,
        "structure_smiles": structure_smiles,
        "next_oid": int(doc.get("next_oid", 0) or 0),
        "filter_panel_visible": bool(doc.get("filter_panel_visible", False)),
        "plot_panel_visible": bool(doc.get("plot_panel_visible", True)),
        "plot_panel_width": doc.get("plot_panel_width"),
        "sort_ascending": bool(doc.get("sort_ascending", True)),
    }
    for key, value in doc.items():
        if key in out or key in (
            "rows",
            "version",
            "data_headers",
            "ids",
            "values",
            "structure_smiles",
            "structure_mols",
        ):
            continue
        if key == SESSION_ENSEMBLES_KEY:
            continue
        if key == "global_bounds":
            bounds = compact_global_bounds(value)
            if bounds:
                out[key] = bounds
            continue
        if key in _OMIT_IF_EMPTY and _is_empty_optional(value):
            continue
        out[key] = value
    if any(structure_mols):
        out["structure_mols"] = structure_mols
    # Drop empties that we always copy above when unused.
    for key in list(out.keys()):
        if key in _OMIT_IF_EMPTY and _is_empty_optional(out[key]):
            del out[key]
    if out.get("plot_panel_width") is None:
        out.pop("plot_panel_width", None)
    return out


def expand_session_document(doc: dict[str, Any]) -> dict[str, Any]:
    """Normalize v1/v2 documents to the internal shape used by session restore."""
    if not isinstance(doc, dict):
        raise ValueError("Session root must be a JSON object.")
    version = int(doc.get("version", 0) or 0)
    if version == 1 or ("rows" in doc and "ids" not in doc):
        out = dict(doc)
        out.setdefault("version", 1)
        out["structure_smiles"] = _structure_smiles_from_v1_rows(
            out.get("rows"), out.get("structure_smiles")
        )
        return out
    if version != 2 and "ids" not in doc:
        raise ValueError(f"Unsupported session version: {version}")

    headers = list(doc.get("headers") or [])
    data_headers = list(doc.get("data_headers") or [])
    if not data_headers:
        data_headers = [h for h in headers if h and h not in ("ID_HIDDEN", "Structure")]
    ids = list(doc.get("ids") or [])
    values = list(doc.get("values") or [])
    saved_structure = doc.get("structure_smiles")
    if not isinstance(saved_structure, list):
        saved_structure = []
    saved_mols = doc.get("structure_mols")
    keep_mols = isinstance(saved_mols, list)
    if not keep_mols:
        saved_mols = []
    rows: list[dict[str, Any]] = []
    structure_smiles: list[str] = []
    structure_mols: list[str] = []
    n = min(len(ids), len(values))
    for i in range(n):
        try:
            oid = int(ids[i])
        except (TypeError, ValueError):
            continue
        row_vals = values[i]
        if not isinstance(row_vals, (list, tuple)):
            continue
        cells: dict[str, str] = {}
        for j, h in enumerate(data_headers):
            if j < len(row_vals):
                cells[str(h)] = str(row_vals[j] if row_vals[j] is not None else "")
            else:
                cells[str(h)] = ""
        rows.append({"id": oid, "cells": cells})
        saved_smi = str(saved_structure[i] or "") if i < len(saved_structure) else ""
        structure_smiles.append(row_structure_smiles(cells, saved_smi))
        if keep_mols:
            structure_mols.append(str(saved_mols[i] or "") if i < len(saved_mols) else "")

    out = dict(doc)
    out["version"] = 2
    out["rows"] = rows
    out["structure_smiles"] = structure_smiles
    if keep_mols:
        out["structure_mols"] = structure_mols
    # Keep columnar keys out of restore workers that only need rows.
    out.pop("ids", None)
    out.pop("values", None)
    out.pop("data_headers", None)
    return out
