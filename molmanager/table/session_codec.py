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

"""JSON-safe encodings for values stored in the session manifest.

The file format itself lives in :mod:`molmanager.table.session_v4`.
"""

from __future__ import annotations

import base64
import math


def encode_mol_blob_b64(blob: bytes | None) -> str:
    """Base64 for one structure mol blob (empty string when missing)."""
    if not blob:
        return ""
    return base64.b64encode(blob).decode("ascii")


def decode_mol_blob_b64(raw: object) -> bytes | None:
    """Decode one base64 mol blob; ``None`` when missing or invalid."""
    if not isinstance(raw, str) or not raw:
        return None
    try:
        blob = base64.b64decode(raw.encode("ascii"), validate=False)
    except ValueError:
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
