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

"""Resolution-independent 2D depiction scenes.

A scene is a finished drawing of one molecule as primitives in molecule units
(the units of its 2D coordinates). Nothing in it depends on cell size, pixel
ratio or theme: the painter scales it to the cell and resolves colours then.

Colour roles are atomic numbers, so the painter's palette decides what each
element looks like. Role 0 covers dummy atoms and drawing that belongs to no
element; roles above 118 are reserved.

Every primitive names the bond or atom it was drawn for, so highlights and
hit-testing work from the stored scene without rebuilding it.

The packed form is little-endian, starts with a magic and a version byte, and
decodes to ``None`` when it is truncated, corrupt or from another version, so
callers fall back to the RDKit picture in the same way as :func:`unpack_xy`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum

SCENE_VERSION = 1
NO_INDEX = 0xFFFF
MAX_COLOUR_ROLE = 118
# Em size of subscript and superscript pieces relative to normal label text.
SCRIPT_SCALE = 0.66

_MAGIC = b"MS"
_HEADER = struct.Struct("<2sBBHHff4fIII")
_ATOM = struct.Struct("<2f")
_STROKE = struct.Struct("<4fBBH")
_FILL_HEAD = struct.Struct("<BHB")
_POINT = struct.Struct("<2f")
_LABEL_HEAD = struct.Struct("<H2fBB4fB")
_PIECE_HEAD = struct.Struct("<2fBB")


class StrokeStyle(IntEnum):
    """How the painter draws a stroke segment."""

    SOLID = 0
    # Unknown-order or dative-style bonds drawn as a dashed line.
    DASHED = 1
    # Unknown stereo: the painter draws a wave along the segment.
    WAVY = 2
    # One dash of a hashed wedge; dash count and spacing are fixed by the builder.
    HASH = 3


class LabelOrientation(IntEnum):
    """Which side of the atom a label's hydrogens and extras sit on."""

    CENTRE = 0
    NORTH = 1
    EAST = 2
    SOUTH = 3
    WEST = 4


class PieceKind(IntEnum):
    """Text size and baseline of one label piece."""

    NORMAL = 0
    SUBSCRIPT = 1
    SUPERSCRIPT = 2


@dataclass(frozen=True, slots=True)
class Stroke:
    """A straight segment from ``(x1, y1)`` to ``(x2, y2)``.

    Segments sharing an endpoint are drawn with round caps in one path per
    colour role, which gives round joins without separate patches.
    """

    x1: float
    y1: float
    x2: float
    y2: float
    role: int
    style: StrokeStyle = StrokeStyle.SOLID
    bond: int = NO_INDEX


@dataclass(frozen=True, slots=True)
class Fill:
    """A filled polygon, such as a solid wedge already cut to its neighbours."""

    points: tuple[tuple[float, float], ...]
    role: int
    bond: int = NO_INDEX


@dataclass(frozen=True, slots=True)
class LabelPiece:
    """One run of text placed with its baseline origin at ``(x, y)``."""

    x: float
    y: float
    text: str
    kind: PieceKind = PieceKind.NORMAL


@dataclass(frozen=True, slots=True)
class Label:
    """An atom label: placed text pieces plus the box bonds were trimmed to.

    *box* is ``(min_x, min_y, max_x, max_y)``. The builder measured it with the
    same font metrics the painter uses, so bonds end at the drawn text.
    """

    atom: int
    anchor: tuple[float, float]
    orientation: LabelOrientation
    role: int
    box: tuple[float, float, float, float]
    pieces: tuple[LabelPiece, ...]


@dataclass(frozen=True, slots=True)
class DepictionScene:
    """A complete drawing of one molecule in molecule units.

    *atoms* holds one position per atom, for hit-testing and highlights.
    *label_size* is the em size of normal label text, and *bounds* covers every
    primitive including label boxes, so a cell fit needs only the header.
    """

    atoms: tuple[tuple[float, float], ...]
    bond_count: int
    mean_bond_length: float
    label_size: float
    bounds: tuple[float, float, float, float]
    strokes: tuple[Stroke, ...] = ()
    fills: tuple[Fill, ...] = ()
    labels: tuple[Label, ...] = ()
    flags: int = 0


def scene_bounds(
    atoms: tuple[tuple[float, float], ...] | list[tuple[float, float]],
    strokes: tuple[Stroke, ...] | list[Stroke] = (),
    fills: tuple[Fill, ...] | list[Fill] = (),
    labels: tuple[Label, ...] | list[Label] = (),
) -> tuple[float, float, float, float]:
    """Union box of atom positions, strokes, fills and label boxes.

    Returns ``(0, 0, 0, 0)`` when there is nothing to bound.
    """
    xs: list[float] = []
    ys: list[float] = []
    for x, y in atoms:
        xs.append(x)
        ys.append(y)
    for stroke in strokes:
        xs.extend((stroke.x1, stroke.x2))
        ys.extend((stroke.y1, stroke.y2))
    for fill in fills:
        for x, y in fill.points:
            xs.append(x)
            ys.append(y)
    for label in labels:
        xs.extend((label.box[0], label.box[2]))
        ys.extend((label.box[1], label.box[3]))
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _check_role(role: int) -> int:
    if not 0 <= int(role) <= MAX_COLOUR_ROLE:
        raise ValueError(f"colour role {role} is outside 0..{MAX_COLOUR_ROLE}")
    return int(role)


def _check_index(index: int, count: int, what: str) -> int:
    if int(index) != NO_INDEX and not 0 <= int(index) < count:
        raise ValueError(f"{what} index {index} is outside 0..{count - 1}")
    return int(index)


def pack_scene(scene: DepictionScene) -> bytes:
    """Encode *scene*. Raises ``ValueError`` when it does not fit the format.

    Atom and bond counts must stay below :data:`NO_INDEX`, and every index and
    colour role must be in range, so a packed scene always decodes.
    """
    n_atoms = len(scene.atoms)
    if n_atoms >= NO_INDEX or not 0 <= scene.bond_count < NO_INDEX:
        raise ValueError("too many atoms or bonds for a depiction scene")
    out = bytearray()
    try:
        out += _HEADER.pack(
            _MAGIC,
            SCENE_VERSION,
            scene.flags,
            n_atoms,
            scene.bond_count,
            scene.mean_bond_length,
            scene.label_size,
            *scene.bounds,
            len(scene.strokes),
            len(scene.fills),
            len(scene.labels),
        )
        for x, y in scene.atoms:
            out += _ATOM.pack(x, y)
        for stroke in scene.strokes:
            out += _STROKE.pack(
                stroke.x1,
                stroke.y1,
                stroke.x2,
                stroke.y2,
                _check_role(stroke.role),
                StrokeStyle(stroke.style),
                _check_index(stroke.bond, scene.bond_count, "bond"),
            )
        for fill in scene.fills:
            if not 3 <= len(fill.points) <= 255:
                raise ValueError("a fill polygon needs 3 to 255 points")
            out += _FILL_HEAD.pack(
                _check_role(fill.role),
                _check_index(fill.bond, scene.bond_count, "bond"),
                len(fill.points),
            )
            for x, y in fill.points:
                out += _POINT.pack(x, y)
        for label in scene.labels:
            if not label.pieces or len(label.pieces) > 255:
                raise ValueError("a label needs 1 to 255 pieces")
            out += _LABEL_HEAD.pack(
                _check_index(label.atom, n_atoms, "atom"),
                *label.anchor,
                LabelOrientation(label.orientation),
                _check_role(label.role),
                *label.box,
                len(label.pieces),
            )
            for piece in label.pieces:
                text = piece.text.encode("utf-8")
                if not 0 < len(text) <= 255:
                    raise ValueError("label text must be 1 to 255 bytes")
                out += _PIECE_HEAD.pack(piece.x, piece.y, PieceKind(piece.kind), len(text))
                out += text
    except struct.error as exc:
        raise ValueError(f"cannot pack depiction scene: {exc}") from exc
    return bytes(out)


class _Reader:
    """Sequential reader over a scene blob; raises ``ValueError`` on bad data."""

    __slots__ = ("_raw", "_pos")

    def __init__(self, raw: bytes) -> None:
        self._raw = raw
        self._pos = 0

    def take(self, record: struct.Struct) -> tuple:
        end = self._pos + record.size
        if end > len(self._raw):
            raise ValueError("truncated depiction scene")
        values = record.unpack_from(self._raw, self._pos)
        self._pos = end
        return values

    def take_bytes(self, size: int) -> bytes:
        end = self._pos + size
        if end > len(self._raw):
            raise ValueError("truncated depiction scene")
        chunk = self._raw[self._pos : end]
        self._pos = end
        return chunk

    @property
    def at_end(self) -> bool:
        return self._pos == len(self._raw)


def _decode(raw: bytes) -> DepictionScene:
    reader = _Reader(raw)
    (
        magic,
        version,
        flags,
        n_atoms,
        bond_count,
        mean_bond_length,
        label_size,
        min_x,
        min_y,
        max_x,
        max_y,
        n_strokes,
        n_fills,
        n_labels,
    ) = reader.take(_HEADER)
    if magic != _MAGIC or version != SCENE_VERSION:
        raise ValueError("not a depiction scene of this version")
    if n_atoms >= NO_INDEX or bond_count >= NO_INDEX:
        raise ValueError("atom or bond count out of range")
    atoms = tuple(reader.take(_ATOM) for _ in range(n_atoms))
    strokes = []
    for _ in range(n_strokes):
        x1, y1, x2, y2, role, style, bond = reader.take(_STROKE)
        strokes.append(
            Stroke(
                x1,
                y1,
                x2,
                y2,
                _check_role(role),
                StrokeStyle(style),
                _check_index(bond, bond_count, "bond"),
            )
        )
    fills = []
    for _ in range(n_fills):
        role, bond, n_points = reader.take(_FILL_HEAD)
        if n_points < 3:
            raise ValueError("fill polygon with fewer than 3 points")
        points = tuple(reader.take(_POINT) for _ in range(n_points))
        fills.append(Fill(points, _check_role(role), _check_index(bond, bond_count, "bond")))
    labels = []
    for _ in range(n_labels):
        atom, ax, ay, orientation, role, bx0, by0, bx1, by1, n_pieces = reader.take(_LABEL_HEAD)
        if n_pieces < 1:
            raise ValueError("label without pieces")
        pieces = []
        for _ in range(n_pieces):
            px, py, kind, size = reader.take(_PIECE_HEAD)
            if size < 1:
                raise ValueError("empty label piece")
            text = reader.take_bytes(size).decode("utf-8")
            pieces.append(LabelPiece(px, py, text, PieceKind(kind)))
        labels.append(
            Label(
                _check_index(atom, n_atoms, "atom"),
                (ax, ay),
                LabelOrientation(orientation),
                _check_role(role),
                (bx0, by0, bx1, by1),
                tuple(pieces),
            )
        )
    if not reader.at_end:
        raise ValueError("trailing bytes after depiction scene")
    return DepictionScene(
        atoms=atoms,
        bond_count=bond_count,
        mean_bond_length=mean_bond_length,
        label_size=label_size,
        bounds=(min_x, min_y, max_x, max_y),
        strokes=tuple(strokes),
        fills=tuple(fills),
        labels=tuple(labels),
        flags=flags,
    )


def is_scene_blob(blob: bytes | None) -> bool:
    """True when *blob* starts like a packed scene, as opposed to PNG bytes."""
    return bool(blob) and bytes(blob[:2]) == _MAGIC


def unpack_scene(blob: bytes | None) -> DepictionScene | None:
    """Decode :func:`pack_scene`. ``None`` when the blob is missing or unusable."""
    if not blob:
        return None
    try:
        return _decode(bytes(blob))
    except (ValueError, UnicodeDecodeError):
        return None
