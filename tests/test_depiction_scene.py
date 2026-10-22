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

import pytest

from molmanager.chem.depiction_scene import (
    NO_INDEX,
    DepictionScene,
    Fill,
    Label,
    LabelOrientation,
    LabelPiece,
    PieceKind,
    Stroke,
    StrokeStyle,
    pack_scene,
    scene_bounds,
    unpack_scene,
)


def _acetic_acid_scene() -> DepictionScene:
    """Hand-built scene with every record type. Values are exact in float32."""
    atoms = ((0.0, 0.0), (1.5, 0.0), (2.25, 1.25), (2.25, -1.25))
    strokes = (
        Stroke(0.0, 0.0, 1.5, 0.0, 6, bond=0),
        Stroke(1.5, 0.0, 1.875, 0.625, 6, bond=1),
        Stroke(1.875, 0.625, 2.0, 1.0, 8, bond=1),
        Stroke(1.75, 0.25, 2.0, 0.75, 8, StrokeStyle.DASHED, bond=1),
        Stroke(1.5, 0.0, 2.0, -0.75, 6, StrokeStyle.WAVY, bond=2),
        Stroke(1.0, 0.25, 1.0, -0.25, 6, StrokeStyle.HASH, bond=NO_INDEX),
    )
    fills = (Fill(((0.0, 0.0), (1.5, 0.25), (1.5, -0.25)), 6, bond=0),)
    labels = (
        Label(
            atom=2,
            anchor=(2.25, 1.25),
            orientation=LabelOrientation.CENTRE,
            role=8,
            box=(2.0, 1.0, 2.5, 1.5),
            pieces=(LabelPiece(2.0, 1.5, "O"),),
        ),
        Label(
            atom=3,
            anchor=(2.25, -1.25),
            orientation=LabelOrientation.EAST,
            role=8,
            box=(2.0, -1.5, 3.25, -1.0),
            pieces=(
                LabelPiece(2.0, -1.0, "OH"),
                LabelPiece(3.0, -1.25, "−", PieceKind.SUPERSCRIPT),
                LabelPiece(3.0, -0.875, "2", PieceKind.SUBSCRIPT),
            ),
        ),
    )
    return DepictionScene(
        atoms=atoms,
        bond_count=3,
        mean_bond_length=1.5,
        label_size=0.5,
        bounds=scene_bounds(atoms, strokes, fills, labels),
        strokes=strokes,
        fills=fills,
        labels=labels,
        flags=1,
    )


def test_round_trip_keeps_every_record():
    scene = _acetic_acid_scene()
    assert unpack_scene(pack_scene(scene)) == scene


def test_empty_scene_round_trips():
    scene = DepictionScene(
        atoms=(), bond_count=0, mean_bond_length=0.0, label_size=0.0, bounds=(0, 0, 0, 0)
    )
    assert unpack_scene(pack_scene(scene)) == scene


def test_scene_bounds_include_label_boxes():
    scene = _acetic_acid_scene()
    assert scene.bounds == (0.0, -1.5, 3.25, 1.5)
    assert scene_bounds(()) == (0.0, 0.0, 0.0, 0.0)


@pytest.mark.parametrize("blob", [None, b"", b"MS", b"XX" + bytes(40)])
def test_missing_or_foreign_blob_is_none(blob):
    assert unpack_scene(blob) is None


def test_every_truncation_is_rejected():
    blob = pack_scene(_acetic_acid_scene())
    for size in range(len(blob)):
        assert unpack_scene(blob[:size]) is None


def test_trailing_bytes_are_rejected():
    assert unpack_scene(pack_scene(_acetic_acid_scene()) + b"\0") is None


def test_other_version_is_rejected():
    blob = bytearray(pack_scene(_acetic_acid_scene()))
    blob[2] = 99
    assert unpack_scene(bytes(blob)) is None


def test_corrupt_enum_or_index_is_rejected():
    scene = _acetic_acid_scene()
    blob = pack_scene(scene)
    header_and_atoms = 44 + 8 * len(scene.atoms)
    stroke_style = header_and_atoms + 17
    stroke_bond = header_and_atoms + 18
    for offset, value in ((stroke_style, b"\x09"), (stroke_bond, b"\x07\x00")):
        corrupt = bytearray(blob)
        corrupt[offset : offset + len(value)] = value
        assert unpack_scene(bytes(corrupt)) is None


def test_invalid_utf8_label_is_rejected():
    blob = pack_scene(_acetic_acid_scene())
    index = blob.rindex(b"2")
    corrupt = blob[:index] + b"\xff" + blob[index + 1 :]
    assert unpack_scene(corrupt) is None


@pytest.mark.parametrize(
    "change",
    [
        {"strokes": (Stroke(0, 0, 1, 1, 119),)},
        {"strokes": (Stroke(0, 0, 1, 1, 6, bond=3),)},
        {"fills": (Fill(((0, 0), (1, 1)), 6),)},
        {
            "labels": (
                Label(
                    9, (0, 0), LabelOrientation.CENTRE, 7, (0, 0, 1, 1), (LabelPiece(0, 0, "N"),)
                ),
            )
        },
        {"labels": (Label(0, (0, 0), LabelOrientation.CENTRE, 7, (0, 0, 1, 1), ()),)},
        {
            "labels": (
                Label(0, (0, 0), LabelOrientation.CENTRE, 7, (0, 0, 1, 1), (LabelPiece(0, 0, ""),)),
            )
        },
    ],
)
def test_pack_rejects_out_of_range_content(change):
    base = _acetic_acid_scene()
    fields = {
        "atoms": base.atoms,
        "bond_count": base.bond_count,
        "mean_bond_length": base.mean_bond_length,
        "label_size": base.label_size,
        "bounds": base.bounds,
    }
    with pytest.raises(ValueError):
        pack_scene(DepictionScene(**fields, **change))


def test_pack_rejects_too_many_atoms():
    scene = DepictionScene(
        atoms=((0.0, 0.0),) * NO_INDEX,
        bond_count=0,
        mean_bond_length=1.0,
        label_size=0.5,
        bounds=(0, 0, 0, 0),
    )
    with pytest.raises(ValueError):
        pack_scene(scene)
