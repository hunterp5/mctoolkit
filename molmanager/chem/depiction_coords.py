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

"""Stored 2D depiction coordinates for structure columns.

The molecule store keeps connection tables only. These coordinates are applied
when a picture is drawn, and ignored when the atom count no longer matches.
Align to Substructure writes them, and so does opening an SDF or molfile that
already has a flat conformer.
"""

from __future__ import annotations

import base64
import struct
from typing import Any

_SIDECAR_VERSION = 1
# Match conformer 3D detection: a molfile with numerical noise in z is still flat.
_FLAT_Z_EPS = 1e-3
# A conformer with no spread is not an orientation; drawing should use the usual layout.
_MIN_XY_SPAN = 1e-4


def pack_xy(points: list[tuple[float, float]]) -> bytes:
    """Little-endian float32 x,y pairs. Empty when *points* is empty."""
    if not points:
        return b""
    flat: list[float] = []
    for x, y in points:
        flat.append(float(x))
        flat.append(float(y))
    return struct.pack(f"<{len(flat)}f", *flat)


def unpack_xy(blob: bytes | None) -> list[tuple[float, float]] | None:
    """Decode :func:`pack_xy`. ``None`` when the blob is missing or truncated."""
    if not blob:
        return None
    raw = bytes(blob)
    if len(raw) < 8 or len(raw) % 8 != 0:
        return None
    count = len(raw) // 4
    try:
        vals = struct.unpack(f"<{count}f", raw)
    except struct.error:
        return None
    return [(float(vals[i]), float(vals[i + 1])) for i in range(0, len(vals), 2)]


def apply_depiction_coords(mol, blob: bytes | None):
    """Copy *mol* with a 2D conformer when *blob* has one point per atom.

    Returns *mol* unchanged when there are no coordinates or the length does not
    match, so a later chemistry edit falls back to the usual layout.
    """
    if mol is None or not blob:
        return mol
    pts = unpack_xy(blob)
    if not pts or len(pts) != int(mol.GetNumAtoms()):
        return mol
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    out = Chem.Mol(mol)
    out.RemoveAllConformers()
    conf = Chem.Conformer(out.GetNumAtoms())
    for i, (x, y) in enumerate(pts):
        conf.SetAtomPosition(i, Point3D(float(x), float(y), 0.0))
    out.AddConformer(conf, assignId=True)
    return out


def depiction_blob_from_mol(mol) -> bytes:
    """Packed xy of a flat conformer, or empty when *mol* has none.

    3D coordinates are not a drawing orientation: a conformer whose z range
    is larger than a flat molfile is skipped. The molfile's own 2D/3D flag is
    not consulted, so a flat drawing tagged as 3D still counts. Collapsed
    coordinates are skipped so the usual layout can still place the atoms.
    """
    if mol is None:
        return b""
    try:
        n_atoms = int(mol.GetNumAtoms())
        n_conf = int(mol.GetNumConformers())
    except (AttributeError, TypeError, ValueError):
        return b""
    if n_atoms < 2 or n_conf < 1:
        return b""
    try:
        conformers = list(mol.GetConformers())
    except (TypeError, ValueError, RuntimeError):
        return b""
    if not conformers:
        return b""
    for conf in conformers:
        zs = [float(conf.GetAtomPosition(i).z) for i in range(n_atoms)]
        if max(zs) - min(zs) > _FLAT_Z_EPS:
            return b""
    conf = conformers[0]
    points: list[tuple[float, float]] = []
    for i in range(n_atoms):
        pos = conf.GetAtomPosition(i)
        points.append((float(pos.x), float(pos.y)))
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    if max(xs) - min(xs) < _MIN_XY_SPAN and max(ys) - min(ys) < _MIN_XY_SPAN:
        return b""
    return pack_xy(points)


def mol_for_app_depiction(app, mol, oid: int, column: str = "Structure"):
    """Table molecule with stored orientation for *column*, when one exists."""
    if mol is None or app is None:
        return mol
    store = getattr(app, "_depiction_coords", None)
    if store is None:
        return mol
    return apply_depiction_coords(mol, store.get(str(column), int(oid)))


def depiction_revision(app) -> int:
    """Cache token. Changes when any stored orientation is written or cleared."""
    store = getattr(app, "_depiction_coords", None)
    if store is None:
        return 0
    return int(getattr(store, "revision", 0) or 0)


class DepictionCoordStore:
    """``(column, oid) -> packed xy`` for one workspace."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, int], bytes] = {}
        self.revision = 0

    def __len__(self) -> int:
        return len(self._rows)

    def _touch(self) -> None:
        self.revision += 1

    def get(self, column: str, oid: int) -> bytes | None:
        blob = self._rows.get((str(column), int(oid)))
        return blob if blob else None

    def set(self, column: str, oid: int, blob: bytes) -> None:
        raw = bytes(blob or b"")
        if not raw:
            self.discard_column_oids(column, [int(oid)])
            return
        self._rows[(str(column), int(oid))] = raw
        self._touch()

    def set_many(self, column: str, rows: list[tuple[int, bytes]]) -> None:
        name = str(column)
        changed = False
        for oid, blob in rows:
            raw = bytes(blob or b"")
            if not raw:
                continue
            self._rows[(name, int(oid))] = raw
            changed = True
        if changed:
            self._touch()

    def discard_column_oids(self, column: str, oids) -> list[int]:
        """Drop coordinates for *oids* in *column*. Return the oids that had some."""
        name = str(column)
        removed: list[int] = []
        for oid in oids:
            key = (name, int(oid))
            if key in self._rows:
                del self._rows[key]
                removed.append(int(oid))
        if removed:
            self._touch()
        return removed

    def discard_oids(self, oids) -> None:
        """Drop every column's coordinates for these row ids."""
        kill = {int(oid) for oid in oids}
        if not kill:
            return
        keys = [key for key in self._rows if key[1] in kill]
        if not keys:
            return
        for key in keys:
            del self._rows[key]
        self._touch()

    def coords_for_oid(self, oid: int) -> dict[str, bytes]:
        """Column → packed coordinates currently stored for *oid*."""
        want = int(oid)
        return {column: blob for (column, row_id), blob in self._rows.items() if row_id == want}

    def restore_oid(self, oid: int, columns: dict[str, bytes] | None) -> None:
        """Replace *oid* entries with *columns* (used by paste undo)."""
        want = int(oid)
        keys = [key for key in self._rows if key[1] == want]
        for key in keys:
            del self._rows[key]
        for column, blob in (columns or {}).items():
            raw = bytes(blob or b"")
            if raw and column:
                self._rows[(str(column), want)] = raw
        self._touch()

    def column_items(self, column: str, oids: set[int] | None = None) -> dict[int, bytes]:
        """``oid -> bytes`` for one column, optionally limited to *oids*."""
        name = str(column)
        out: dict[int, bytes] = {}
        for (col, oid), blob in self._rows.items():
            if col != name or not blob:
                continue
            if oids is not None and int(oid) not in oids:
                continue
            out[int(oid)] = blob
        return out

    def clear(self) -> None:
        if not self._rows:
            return
        self._rows.clear()
        self._touch()

    def to_session(self, oids: set[int] | None = None) -> dict[str, Any] | None:
        """JSON-ready payload, or ``None`` when nothing would be saved."""
        rows: list[list[Any]] = []
        for (column, oid), blob in sorted(
            self._rows.items(), key=lambda item: (item[0][0], item[0][1])
        ):
            if oids is not None and int(oid) not in oids:
                continue
            if not blob:
                continue
            rows.append([column, int(oid), base64.b64encode(blob).decode("ascii")])
        if not rows:
            return None
        return {"v": _SIDECAR_VERSION, "rows": rows}

    def load_session(self, raw: Any) -> None:
        """Replace the store from a session payload. Unknown data clears it."""
        self._rows.clear()
        if isinstance(raw, dict):
            for item in raw.get("rows") or []:
                if not isinstance(item, (list, tuple)) or len(item) < 3:
                    continue
                column = str(item[0] or "").strip()
                if not column:
                    continue
                try:
                    oid = int(item[1])
                except (TypeError, ValueError):
                    continue
                try:
                    blob = base64.b64decode(str(item[2] or ""), validate=True)
                except ValueError:
                    continue
                if unpack_xy(blob):
                    self._rows[(column, oid)] = bytes(blob)
        self._touch()
