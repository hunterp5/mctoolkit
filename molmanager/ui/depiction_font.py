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

"""The bundled atom-label font for painting depiction scenes.

Scenes are laid out with :mod:`molmanager.chem.depiction_font_metrics`, so the
painter must draw with the same font file, unhinted, for text to fill the label
boxes the builder trimmed bonds to.
"""

from __future__ import annotations

from PyQt5.QtGui import QFont, QFontDatabase

from molmanager.chem import depiction_font_metrics
from molmanager.platform_support.bundled_paths import resources_dir

_family: str | None = None


def label_font_path():
    """Path of the bundled label font file."""
    return resources_dir() / "fonts" / depiction_font_metrics.FONT_FILE


def label_font_family() -> str:
    """Family name of the bundled label font, registering it on first use.

    Needs a ``QGuiApplication``. When the file cannot be loaded the metrics
    family name is still returned, so Qt substitutes a similar installed font.
    """
    global _family
    if _family is None:
        font_id = QFontDatabase.addApplicationFont(str(label_font_path()))
        families = QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
        _family = families[0] if families else depiction_font_metrics.FONT_FAMILY
    return _family


def depiction_label_font(pixel_size: int) -> QFont:
    """Unhinted regular label font at *pixel_size*."""
    font = QFont(label_font_family())
    font.setPixelSize(max(1, int(pixel_size)))
    font.setWeight(QFont.Normal)
    font.setItalic(False)
    font.setKerning(False)
    font.setHintingPreference(QFont.PreferNoHinting)
    font.setStyleStrategy(QFont.PreferAntialias)
    return font
