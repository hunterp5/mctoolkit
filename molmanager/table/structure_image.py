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

"""Structure pictures for the table and previews: depiction scenes, else RDKit PNGs.

:func:`pixmap_from_structure_image` decodes stored Structure-cell bytes.
:func:`molecule_pixmap` and :func:`molecule_png_bytes` draw a molecule directly for
browsers, dialogs and hover cards, so they look like the table.
"""

from __future__ import annotations

from PyQt5.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PyQt5.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from molmanager.chem.depiction_scene import SceneHighlight, is_scene_blob, unpack_scene
from molmanager.chem.render2d_mp import molecule_image_bytes
from molmanager.table.depiction_painter import light_palette, paint_scene
from molmanager.table.structure_depiction_layout import (
    STRUCTURE_DEPICT_BOND_LINE_WIDTH,
    structure_depict_width,
)

# Longest bond as a fraction of the cell height, so small molecules keep the same
# bond length and label size as their neighbours instead of filling the cell.
MAX_BOND_FRACTION = 0.2


def pixmap_from_structure_image(image: bytes, display_w: int, display_h: int) -> QPixmap:
    """Decode stored Structure-cell bytes for a *display_w* × *display_h* cell.

    Scenes are painted at that size. PNGs are scaled down when larger than the cell.
    Returns a null pixmap for bytes that are neither. GUI thread only.
    """
    return QPixmap.fromImage(image_from_structure_bytes(image, display_w, display_h))


def image_from_structure_bytes(
    image: bytes,
    display_w: int,
    display_h: int,
    *,
    highlight: SceneHighlight | None = None,
) -> QImage:
    """:func:`pixmap_from_structure_image` as a QImage, which is safe off the GUI thread.

    *highlight* is painted under a scene; PNG bytes are returned as they are.
    """
    dw, dh = int(display_w), int(display_h)
    if is_scene_blob(image):
        return _image_from_scene(image, dw, dh, highlight)
    decoded = QImage.fromData(image)
    if not decoded.isNull() and (decoded.width() > dw or decoded.height() > dh):
        decoded = decoded.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return decoded


def molecule_pixmap(
    mol, width: int, height: int, *, highlight: SceneHighlight | None = None
) -> QPixmap:
    """*mol* drawn for a *width* × *height* preview, the same way as the Structure column.

    *highlight* indexes the atoms and bonds of *mol*. Raises what RDKit raises when
    the molecule cannot be drawn at all.
    """
    return QPixmap.fromImage(_molecule_image(mol, width, height, highlight))


def molecule_png_bytes(mol, width: int, height: int) -> bytes:
    """:func:`molecule_pixmap` encoded as PNG, for HTML hover cards and data URLs."""
    image = _molecule_image(mol, width, height, None)
    if image.isNull():
        return b""
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def _molecule_image(mol, width: int, height: int, highlight: SceneHighlight | None) -> QImage:
    raw = molecule_image_bytes(mol, width, height, want_scene=True, highlight=highlight)
    return image_from_structure_bytes(raw, width, height, highlight=highlight)


def _image_from_scene(
    blob: bytes, width: int, height: int, highlight: SceneHighlight | None = None
) -> QImage:
    """Paint a packed scene on white, matching the RDKit PNG cell look."""
    scene = unpack_scene(blob)
    if scene is None or width <= 0 or height <= 0:
        return QImage()
    app = QGuiApplication.instance()
    ratio = app.devicePixelRatio() if app is not None else 1.0
    image = QImage(round(width * ratio), round(height * ratio), QImage.Format_ARGB32_Premultiplied)
    image.setDevicePixelRatio(ratio)
    image.fill(Qt.white)
    zoom = max(1.0, width / max(1.0, float(structure_depict_width())))
    painter = QPainter(image)
    try:
        paint_scene(
            painter,
            scene,
            QRectF(0.0, 0.0, width, height),
            light_palette(),
            line_width_px=STRUCTURE_DEPICT_BOND_LINE_WIDTH * zoom,
            max_bond_px=MAX_BOND_FRACTION * height,
            highlight=highlight,
        )
    finally:
        painter.end()
    return image
