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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager.  If not, see <https://www.gnu.org/licenses/>.

from __future__ import annotations

from rdkit import Chem

from molmanager.chem.depiction_scene import is_scene_blob, pack_scene
from molmanager.chem.structure_2d_depiction import render_molecule_png


def _scene_blob(smiles: str) -> bytes:
    from molmanager.chem.depiction_builder import build_scene

    scene, reason = build_scene(Chem.MolFromSmiles(smiles))
    assert reason is None
    return pack_scene(scene)


def _ink_columns(image) -> list[int]:
    """Columns of *image* holding any non-white pixel."""
    white = 0xFFFFFFFF
    return [
        x
        for x in range(image.width())
        if any(image.pixel(x, y) != white for y in range(image.height()))
    ]


def test_scene_magic_tells_scenes_from_pngs() -> None:
    assert is_scene_blob(_scene_blob("CCO"))
    assert not is_scene_blob(render_molecule_png(Chem.MolFromSmiles("CCO"), 120, 100))
    assert not is_scene_blob(b"")
    assert not is_scene_blob(None)


def test_scene_paints_at_the_cell_size_on_white(qapp) -> None:
    from molmanager.table.structure_image import pixmap_from_structure_image

    pm = pixmap_from_structure_image(_scene_blob("c1ccccc1O"), 210, 170)
    image = pm.toImage()
    assert (pm.width(), pm.height()) == (210, 170)
    assert image.pixel(0, 0) == 0xFFFFFFFF
    assert _ink_columns(image)


def test_png_is_scaled_down_to_the_cell(qapp) -> None:
    from molmanager.table.structure_image import pixmap_from_structure_image

    png = render_molecule_png(Chem.MolFromSmiles("CCO"), 420, 340)
    pm = pixmap_from_structure_image(png, 210, 170)
    assert pm.width() <= 210 and pm.height() <= 170 and not pm.isNull()


def test_bond_cap_keeps_small_molecules_small(qapp) -> None:
    from molmanager.table.structure_image import MAX_BOND_FRACTION, pixmap_from_structure_image

    height = 170
    cols = _ink_columns(pixmap_from_structure_image(_scene_blob("CC"), 210, height).toImage())
    assert cols and cols[-1] - cols[0] <= MAX_BOND_FRACTION * height + 4


def test_garbage_bytes_give_a_null_pixmap(qapp) -> None:
    from molmanager.table.structure_image import pixmap_from_structure_image

    assert pixmap_from_structure_image(b"MS\xff", 210, 170).isNull()
    assert pixmap_from_structure_image(b"not an image", 210, 170).isNull()


_HIGHLIGHT_RGB = (0.0, 0.8, 0.0)


def _has_highlight_colour(image) -> bool:
    for x in range(image.width()):
        for y in range(image.height()):
            colour = image.pixelColor(x, y)
            if colour.green() > 150 and colour.red() < 80 and colour.blue() < 80:
                return True
    return False


def test_highlight_is_painted_under_a_scene(qapp) -> None:
    from molmanager.chem.depiction_scene import atom_set_highlight
    from molmanager.table.structure_image import molecule_pixmap

    mol = Chem.MolFromSmiles("c1ccccc1CC")
    plain = molecule_pixmap(mol, 210, 170).toImage()
    highlight = atom_set_highlight(mol, [6, 7], _HIGHLIGHT_RGB)
    assert set(highlight.bonds) == {(6, 7)}
    marked = molecule_pixmap(mol, 210, 170, highlight=highlight).toImage()
    assert not _has_highlight_colour(plain)
    assert _has_highlight_colour(marked)


def test_highlight_reaches_the_rdkit_fallback() -> None:
    from PyQt5.QtGui import QImage

    from molmanager.chem.depiction_scene import atom_set_highlight

    mol = Chem.MolFromSmiles("c1ccccc1CC")
    highlight = atom_set_highlight(mol, [6, 7], _HIGHLIGHT_RGB)
    png = render_molecule_png(mol, 210, 170, highlight=highlight)
    assert _has_highlight_colour(QImage.fromData(png))


def test_highlight_ignores_atoms_outside_the_scene(qapp) -> None:
    from molmanager.chem.depiction_scene import SceneHighlight
    from molmanager.table.structure_image import molecule_pixmap

    highlight = SceneHighlight(atoms={99: _HIGHLIGHT_RGB}, bonds={(0, 99): _HIGHLIGHT_RGB})
    assert not molecule_pixmap(Chem.MolFromSmiles("CCO"), 210, 170, highlight=highlight).isNull()


def test_render_store_decodes_scenes(qapp) -> None:
    from molmanager.storage.structure_render_store import StructureRenderStore

    store = StructureRenderStore(max_decoded_pixmaps=4)
    store.ingest_batch([(1, _scene_blob("CCO"))])
    pm = store.pixmap(1)
    assert pm is not None and not pm.isNull()
