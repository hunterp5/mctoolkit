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

"""Compact binary ensembles: one topology plus float32 coordinates (zlib)."""

from __future__ import annotations

import base64
import json
import struct
import zlib

import numpy as np
from rdkit import Chem
from rdkit.Geometry import Point3D

MAGIC = b"MMCE"
VERSION = 1
_HEADER = struct.Struct("<4sB3sIII")


def pack_ensemble_mol(mol: Chem.Mol | None) -> bytes | None:
    """zlib-compressed topology mol block plus all conformer coordinates."""
    if mol is None:
        return None
    try:
        n_atoms = int(mol.GetNumAtoms())
        ids = sorted(int(c.GetId()) for c in mol.GetConformers())
    except Exception:
        return None
    if n_atoms < 1 or not ids:
        return None
    try:
        block = Chem.MolToMolBlock(mol, confId=ids[0])
    except Exception:
        return None
    block_b = block.encode("utf-8")
    coords = np.zeros((len(ids), n_atoms, 3), dtype=np.float32)
    for i, cid in enumerate(ids):
        try:
            conf = mol.GetConformer(cid)
        except Exception:
            return None
        for atom in range(n_atoms):
            try:
                pos = conf.GetAtomPosition(atom)
                coords[i, atom, 0] = float(pos.x)
                coords[i, atom, 1] = float(pos.y)
                coords[i, atom, 2] = float(pos.z)
            except Exception:
                return None
    header = _HEADER.pack(MAGIC, VERSION, b"\x00\x00\x00", n_atoms, len(ids), len(block_b))
    return zlib.compress(header + block_b + coords.tobytes(order="C"), 6)


def unpack_ensemble_mol(blob: bytes | None) -> Chem.Mol | None:
    """Rebuild a multi-conformer mol from :func:`pack_ensemble_mol` bytes."""
    if not blob:
        return None
    try:
        raw = zlib.decompress(blob)
    except Exception:
        return None
    if len(raw) < _HEADER.size:
        return None
    magic, version, _pad, n_atoms, n_confs, block_len = _HEADER.unpack(raw[: _HEADER.size])
    if magic != MAGIC or int(version) != VERSION:
        return None
    n_atoms = int(n_atoms)
    n_confs = int(n_confs)
    block_len = int(block_len)
    start = _HEADER.size
    end = start + block_len
    coord_n = n_confs * n_atoms * 12
    if n_atoms < 1 or n_confs < 1 or block_len < 1 or end + coord_n > len(raw):
        return None
    try:
        block = raw[start:end].decode("utf-8")
        mol = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
    except Exception:
        return None
    if mol is None or int(mol.GetNumAtoms()) != n_atoms:
        return None
    coords = np.frombuffer(raw[end : end + coord_n], dtype=np.float32).reshape(n_confs, n_atoms, 3)
    try:
        mol.RemoveAllConformers()
    except Exception:
        pass
    for i in range(n_confs):
        conf = Chem.Conformer(n_atoms)
        for atom in range(n_atoms):
            x, y, z = (
                float(coords[i, atom, 0]),
                float(coords[i, atom, 1]),
                float(coords[i, atom, 2]),
            )
            conf.SetAtomPosition(atom, Point3D(x, y, z))
        try:
            conf.Set3D(True)
        except Exception:
            pass
        mol.AddConformer(conf, assignId=True)
    return mol


def ensemble_blob_to_blocks_b64(blob: bytes | None) -> str | None:
    """Viewer/legacy payload: base64(JSON list of base64 mol blocks)."""
    mol = unpack_ensemble_mol(blob)
    if mol is None:
        return None
    from .conformer_column_codec import conformer_mol_blocks_b64_json

    text = conformer_mol_blocks_b64_json(mol)
    return text or None


def blocks_b64_to_ensemble_blob(blocks_b64: str | None) -> bytes | None:
    """Convert a legacy nested-base64 mol-block payload to a compact blob."""
    if not isinstance(blocks_b64, str) or not blocks_b64.strip():
        return None
    try:
        inner = json.loads(base64.b64decode(blocks_b64.encode("ascii")))
    except Exception:
        return None
    if not isinstance(inner, list) or not inner:
        return None
    mols: list[Chem.Mol] = []
    n_atoms = None
    for enc in inner:
        if not isinstance(enc, str):
            return None
        try:
            block = base64.b64decode(enc.encode("ascii")).decode("utf-8")
            # RDKit writes SDF data tags as ``>  <name>``. Compact blobs keep coordinates only.
            if "\n>" in block:
                return None
            frag = Chem.MolFromMolBlock(block, sanitize=True, removeHs=False)
        except Exception:
            return None
        if frag is None or frag.GetNumConformers() < 1:
            return None
        na = int(frag.GetNumAtoms())
        if n_atoms is None:
            n_atoms = na
        elif na != n_atoms:
            return None
        mols.append(frag)
    if not mols:
        return None
    merged = Chem.Mol(mols[0])
    merged.RemoveAllConformers()
    for frag in mols:
        merged.AddConformer(Chem.Conformer(frag.GetConformer()), assignId=True)
    return pack_ensemble_mol(merged)


def is_ensemble_blob(blob: bytes | None) -> bool:
    """True when *blob* looks like a compact MMCE payload (possibly zlib)."""
    if not blob:
        return False
    if blob.startswith(MAGIC):
        return True
    try:
        raw = zlib.decompress(blob)
    except Exception:
        return False
    return raw.startswith(MAGIC)
