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

"""Turn stored structure image bytes (an RDKit PNG or a depiction scene) into a QPixmap."""

from __future__ import annotations

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QGuiApplication, QImage, QPainter, QPixmap

from molmanager.chem.depiction_scene import is_scene_blob, unpack_scene
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
    Returns a null pixmap for bytes that are neither.
    """
    dw, dh = int(display_w), int(display_h)
    if is_scene_blob(image):
        return _pixmap_from_scene(image, dw, dh)
    pm = QPixmap.fromImage(QImage.fromData(image))
    if pm.isNull():
        return pm
    if pm.width() > dw or pm.height() > dh:
        pm = pm.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm


def _pixmap_from_scene(blob: bytes, width: int, height: int) -> QPixmap:
    """Paint a packed scene on white, matching the RDKit PNG cell look."""
    scene = unpack_scene(blob)
    if scene is None or width <= 0 or height <= 0:
        return QPixmap()
    ratio = QGuiApplication.instance().devicePixelRatio() if QGuiApplication.instance() else 1.0
    pm = QPixmap(round(width * ratio), round(height * ratio))
    pm.setDevicePixelRatio(ratio)
    pm.fill(Qt.white)
    zoom = max(1.0, width / max(1.0, float(structure_depict_width())))
    painter = QPainter(pm)
    try:
        paint_scene(
            painter,
            scene,
            QRectF(0.0, 0.0, width, height),
            light_palette(),
            line_width_px=STRUCTURE_DEPICT_BOND_LINE_WIDTH * zoom,
            max_bond_px=MAX_BOND_FRACTION * height,
        )
    finally:
        painter.end()
    return pm
