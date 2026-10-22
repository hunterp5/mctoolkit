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

"""Convert structure render PNG bytes to table-sized QPixmaps."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap


def pixmap_from_structure_render_png(
    png_bytes: bytes,
    display_w: int,
    display_h: int,
) -> QPixmap:
    """Decode a render PNG and scale down to the display size when larger than target."""
    pm = QPixmap.fromImage(QImage.fromData(png_bytes))
    if pm.isNull():
        return pm
    dw, dh = int(display_w), int(display_h)
    if pm.width() > dw or pm.height() > dh:
        pm = pm.scaled(dw, dh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return pm
