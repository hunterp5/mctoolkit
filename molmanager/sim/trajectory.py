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

"""DCD read and write, plus solute PDB frames for the Protein Viewer."""

from __future__ import annotations

import struct
from pathlib import Path

import numpy as np

from .selection import AtomRecord


class TrajectoryError(ValueError):
    """A DCD could not be read or written."""


def write_dcd(path: str | Path, xyz: np.ndarray) -> None:
    """Write coordinates in Å as a little-endian CORD DCD without a unit cell."""
    coords = np.asarray(xyz, dtype=float)
    if coords.ndim != 3 or coords.shape[2] != 3:
        raise TrajectoryError("DCD coordinates must have shape (frames, atoms, 3).")
    n_frames, n_atoms, _ = coords.shape
    header = bytearray(84)
    header[0:4] = b"CORD"
    struct.pack_into("<i", header, 4, int(n_frames))
    records = [_record(bytes(header)), _record(struct.pack("<i", int(n_atoms)))]
    for frame in coords:
        for axis in range(3):
            column = np.asarray(frame[:, axis], dtype="<f4").tobytes()
            records.append(_record(column))
    Path(path).write_bytes(b"".join(records))


def read_dcd_xyz(path: str | Path) -> np.ndarray:
    """Read a little-endian CORD DCD into Å with shape (frames, atoms, 3).

    Unit-cell records are skipped. Both this module's writer and an OpenMM
    DCD whose header is a Fortran record starting with ``CORD`` are accepted.
    """
    data = Path(path).read_bytes()
    if len(data) < 8:
        raise TrajectoryError(f"DCD header is truncated: {path}")
    endian = "<" if struct.unpack_from("<i", data, 0)[0] > 0 else ">"
    records = list(_iter_records(data, endian))
    if not records or records[0][:4] != b"CORD":
        raise TrajectoryError(f"Not a CORD DCD: {path}")
    header = records[0]
    box_flag = 0
    if len(header) >= 48:
        box_flag = struct.unpack_from(endian + "i", header, 44)[0]
    natom, start = _atom_count(records, endian)
    if natom <= 0:
        raise TrajectoryError(f"DCD atom count is invalid: {path}")
    frames: list[np.ndarray] = []
    index = start
    while index < len(records):
        if box_flag:
            index += 1
        if index + 2 >= len(records):
            break
        columns = []
        for axis in range(3):
            payload = records[index + axis]
            count = len(payload) // 4
            column = np.frombuffer(payload, dtype=np.dtype(endian + "f4"), count=count)
            columns.append(np.array(column, dtype=float, copy=True))
        index += 3
        if any(col.shape[0] != natom for col in columns):
            continue
        frames.append(np.column_stack(columns))
    if not frames:
        raise TrajectoryError(f"DCD has no frames: {path}")
    return np.stack(frames, axis=0)


def stride_indices(n_frames: int, stride: int, cap: int) -> list[int]:
    """Frame numbers kept for playback. The last frame is always included."""
    if n_frames <= 0:
        return []
    step = max(1, int(stride))
    chosen = list(range(0, n_frames, step))
    if chosen[-1] != n_frames - 1:
        chosen.append(n_frames - 1)
    if cap > 0 and len(chosen) > cap:
        keep = np.linspace(0, len(chosen) - 1, cap, dtype=int)
        chosen = [chosen[int(i)] for i in keep]
        if chosen[-1] != n_frames - 1:
            chosen[-1] = n_frames - 1
    return chosen


def solute_multimodel_pdb(
    atoms: list[AtomRecord],
    xyz: np.ndarray,
    *,
    solute_atoms: int,
    stride: int = 1,
    cap: int = 200,
) -> str:
    """Multi-model PDB of solute frames. Water past *solute_atoms* is left out."""
    coords = np.asarray(xyz, dtype=float)
    n_solute = len(atoms) if solute_atoms <= 0 else min(solute_atoms, len(atoms))
    solute = atoms[:n_solute]
    frames = stride_indices(coords.shape[0], stride, cap)
    blocks: list[str] = []
    for model, frame_index in enumerate(frames, start=1):
        blocks.append(f"MODEL     {model:4d}")
        frame = coords[frame_index]
        for atom in solute:
            x, y, z = frame[atom.index]
            blocks.append(_pdb_atom_line(atom, x, y, z))
        blocks.append("ENDMDL")
    blocks.append("END")
    return "\n".join(blocks) + "\n"


def _pdb_atom_line(atom: AtomRecord, x: float, y: float, z: float) -> str:
    name = (atom.name or "X").strip()[:4]
    if len(name) < 4:
        name = f" {name:<3}"
    resn = (atom.resname or "UNK")[:3]
    chain = (atom.chain or "A")[:1] or "A"
    element = (atom.element or name.strip()[:1] or "C")[:2]
    return (
        f"ATOM  {atom.index + 1:5d} {name:>4} {resn:>3} {chain}{atom.resi:4d}    "
        f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00          {element:>2}"
    )


def _record(payload: bytes) -> bytes:
    size = struct.pack("<i", len(payload))
    return size + payload + size


def _iter_records(data: bytes, endian: str):
    offset = 0
    limit = len(data)
    while offset + 8 <= limit:
        (size,) = struct.unpack_from(endian + "i", data, offset)
        if size < 0 or offset + 8 + size > limit:
            break
        yield data[offset + 4 : offset + 4 + size]
        offset += 8 + size


def _atom_count(records: list[bytes], endian: str) -> tuple[int, int]:
    """Return ``(n_atoms, index of the first frame record)``."""
    if len(records) >= 2 and len(records[1]) == 4:
        return struct.unpack(endian + "i", records[1])[0], 2
    if len(records) >= 3 and len(records[2]) == 4:
        return struct.unpack(endian + "i", records[2])[0], 3
    raise TrajectoryError("DCD is missing its atom-count record.")
