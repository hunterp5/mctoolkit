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

"""Leaf ProcessPool entry for batch 2D structure rendering (no Qt).

Lives under ``chem`` (not ``workers``) so spawned children on Windows ``spawn``
do not import the Qt-heavy ``workers`` package.
"""

from __future__ import annotations

from rdkit import Chem

from .depiction_builder import build_scene
from .depiction_coords import apply_depiction_coords
from .depiction_scene import SceneHighlight, pack_scene
from .molecule_conversion import parse_molecule_from_cell_text
from .structure_2d_depiction import render_molecule_png, render_reaction_png

# Tags for serialized Render 2D payloads. Keeping structures in these forms lets the GUI
# thread hand rows straight to the child processes without building RDKit mols first.
REACTION_PAYLOAD_TAG = "rxn"
STRUCTURE_PAYLOAD_TAG = "mol"


def _as_text(raw) -> str:
    return raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw or "")


def _mol_from_render_payload(blob, text: str):
    """Rebuild a structure from its stored pickle, falling back to its cell text.

    The text is SMILES, InChI, or a mol block. The fallback also covers sessions written by a
    newer RDKit, whose pickles this build cannot read; without it those rows would render blank.
    """
    if blob:
        try:
            mol = Chem.Mol(bytes(blob))
        except Exception:  # noqa: BLE001 — RDKit raises varied C++ wrap errors
            mol = None
        if mol is not None:
            return mol
    if not text:
        return None
    return parse_molecule_from_cell_text(text)


def _coord_blob(payload) -> bytes:
    """Optional packed xy on a structure payload. Empty means the usual layout."""
    if (
        isinstance(payload, tuple)
        and len(payload) > 3
        and isinstance(payload[3], (bytes, bytearray))
    ):
        return bytes(payload[3])
    return b""


def mol_from_render_payload(payload):
    """Molecule a Render 2D task payload describes (tagged tuple, pickle bytes, or live mol)."""
    if isinstance(payload, tuple) and payload and payload[0] == STRUCTURE_PAYLOAD_TAG:
        return _mol_from_render_payload(payload[1], _as_text(payload[2]))
    if isinstance(payload, (bytes, bytearray)):
        return _mol_from_render_payload(payload, "")
    return payload


def _scene_blob(mol) -> bytes:
    """Packed depiction scene for *mol*, or empty when the row needs the RDKit picture."""
    scene, _reason = build_scene(mol)
    if scene is None:
        return b""
    try:
        return pack_scene(scene)
    except ValueError:
        return b""


def molecule_image_bytes(
    mol,
    width: int,
    height: int,
    *,
    want_scene: bool,
    highlight: SceneHighlight | None = None,
) -> bytes:
    """Stored image bytes for *mol*: its packed scene when wanted and drawable, else a PNG.

    Scenes never contain *highlight*, since the painter adds it at draw time; only the
    PNG fallback has it drawn in.
    """
    scene = _scene_blob(mol) if want_scene else b""
    return scene or render_molecule_png(mol, int(width), int(height), highlight=highlight)


def mp_render_structure_batch(args: tuple) -> list[tuple]:
    """Render many structures per child-process task.

    One task per molecule left the parent process submitting futures and unpickling results faster
    than it could keep up, capping throughput regardless of how many workers were running. Batching
    moves that ceiling so extra cores actually help. Batch renders never read mol properties, so
    rows are ``(oid, png, ok, w, h)``.

    *args* is ``(items, w, h)`` or ``(items, w, h, want_scenes)``. Each item is
    ``(oid, mol_bytes)``, ``(oid, (REACTION_PAYLOAD_TAG, smarts_bytes))``, or
    ``(oid, (STRUCTURE_PAYLOAD_TAG, mol_bytes, smiles_bytes, coord_bytes))``.
    ``coord_bytes`` is optional; empty bytes keep the usual layout.

    With *want_scenes* a molecule's image bytes are its packed depiction scene, which
    :func:`~molmanager.chem.depiction_scene.is_scene_blob` tells apart from PNG bytes.
    Reactions and molecules the scene builder hands back still carry a PNG.
    """
    items, w, h = args[:3]
    want_scenes = bool(args[3]) if len(args) > 3 else False
    width, height = int(w), int(h)
    out: list[tuple] = []

    def emit(oid: int, image: bytes, ok: bool) -> None:
        out.append((oid, image, ok, width, height))

    for item in items:
        oid = int(item[0])
        payload = item[1]
        if not payload:
            emit(oid, b"", False)
            continue
        try:
            if isinstance(payload, tuple) and payload[0] == REACTION_PAYLOAD_TAG:
                text = _as_text(payload[1])
                try:
                    png = render_reaction_png(text, width, height)
                except Exception:  # noqa: BLE001 — text that only looked like a reaction
                    mol = parse_molecule_from_cell_text(text)
                    if mol is None:
                        raise
                    png = render_molecule_png(mol, width, height)
                emit(oid, png, True)
                continue
            if isinstance(payload, tuple) and payload[0] == STRUCTURE_PAYLOAD_TAG:
                mol = _mol_from_render_payload(payload[1], _as_text(payload[2]))
                if mol is None:
                    emit(oid, b"", False)
                    continue
                mol = apply_depiction_coords(mol, _coord_blob(payload))
            else:
                mol = Chem.Mol(payload)
            emit(oid, molecule_image_bytes(mol, width, height, want_scene=want_scenes), True)
        except Exception:  # noqa: BLE001 — per-row draw failures must not abort the batch
            emit(oid, b"", False)
    return out


# Back-compat alias used by older call sites / tests.
_mp_render_structure_batch = mp_render_structure_batch
