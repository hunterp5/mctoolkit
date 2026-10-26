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

"""2D structure depiction layout defaults (shared by UI and background render workers)."""

from __future__ import annotations

from PyQt5.QtCore import QSettings

# Default RDKit draw → QPixmap size for 2D structure images.
DEFAULT_STRUCTURE_DEPICT_WIDTH = 210
DEFAULT_STRUCTURE_DEPICT_HEIGHT = 170
DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT = 180
STRUCTURE_ROW_HEIGHT_PADDING = (
    DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT - DEFAULT_STRUCTURE_DEPICT_HEIGHT
)

MIN_STRUCTURE_DEPICT_WIDTH = 80
MAX_STRUCTURE_DEPICT_WIDTH = 640
MIN_STRUCTURE_DEPICT_HEIGHT = 60
MAX_STRUCTURE_DEPICT_HEIGHT = 540

# Back-compat aliases for tests and scripts (factory defaults).
STRUCTURE_DEPICT_WIDTH = DEFAULT_STRUCTURE_DEPICT_WIDTH
STRUCTURE_DEPICT_HEIGHT = DEFAULT_STRUCTURE_DEPICT_HEIGHT
STRUCTURE_ROW_DEFAULT_HEIGHT = DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT

# Bond stroke at 1× table resolution (default RDKit is 2.0; thinner lines without supersampling).
STRUCTURE_DEPICT_BOND_LINE_WIDTH = 1.0
# RDKit MolDraw2D padding fraction (fraction of the canvas on each side).
STRUCTURE_DEPICT_PADDING = 0.05
# Extra horizontal space in the table column beyond the pixmap (margins / scrollbar slop).
STRUCTURE_COLUMN_HORIZONTAL_PADDING = 28
# Reaction schemes (A + B → C) need a wider canvas than a single molecule at the same height.
REACTION_DEPICT_WIDTH_MULTIPLIER = 3
# Same inset as molecules so the reaction arrow is not clipped.
REACTION_DEPICT_PADDING = 0.05

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY_STRUCTURE_WIDTH = "structure/depict_width"
_SETTINGS_KEY_STRUCTURE_HEIGHT = "structure/depict_height"

_RUNTIME_WIDTH = DEFAULT_STRUCTURE_DEPICT_WIDTH
_RUNTIME_HEIGHT = DEFAULT_STRUCTURE_DEPICT_HEIGHT


def _clamp_structure_width(width: int) -> int:
    return max(MIN_STRUCTURE_DEPICT_WIDTH, min(MAX_STRUCTURE_DEPICT_WIDTH, int(width)))


def _clamp_structure_height(height: int) -> int:
    return max(MIN_STRUCTURE_DEPICT_HEIGHT, min(MAX_STRUCTURE_DEPICT_HEIGHT, int(height)))


def structure_depict_width() -> int:
    """Current 2D structure depiction width in pixels."""
    return _RUNTIME_WIDTH


def structure_depict_height() -> int:
    """Current 2D structure depiction height in pixels."""
    return _RUNTIME_HEIGHT


def structure_row_default_height() -> int:
    """Default table row height for the Structure column."""
    return structure_depict_height() + STRUCTURE_ROW_HEIGHT_PADDING


def structure_column_minimum_width(*, zoomed: bool = False) -> int:
    """Minimum Structure column width so the depiction is never clipped horizontally."""
    depict_w = structure_depict_width() * (2 if zoomed else 1)
    return int(depict_w) + int(STRUCTURE_COLUMN_HORIZONTAL_PADDING)


def reaction_depict_size(*, zoomed: bool = False) -> tuple[int, int]:
    """PNG size for a reaction scheme: same height as molecules, wider canvas."""
    scale = 2 if zoomed else 1
    width = int(structure_depict_width()) * int(REACTION_DEPICT_WIDTH_MULTIPLIER) * scale
    height = int(structure_depict_height()) * scale
    return max(1, width), max(1, height)


def load_saved_structure_depict_size() -> tuple[int, int]:
    """Return saved depiction size, or defaults when unset."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    try:
        w = int(settings.value(_SETTINGS_KEY_STRUCTURE_WIDTH, 0))
    except (TypeError, ValueError):
        w = 0
    try:
        h = int(settings.value(_SETTINGS_KEY_STRUCTURE_HEIGHT, 0))
    except (TypeError, ValueError):
        h = 0
    if w <= 0 or h <= 0:
        return DEFAULT_STRUCTURE_DEPICT_WIDTH, DEFAULT_STRUCTURE_DEPICT_HEIGHT
    return _clamp_structure_width(w), _clamp_structure_height(h)


def set_structure_depict_size(width: int, height: int, *, persist: bool = True) -> tuple[int, int]:
    """Apply depiction size for new renders and optionally persist to QSettings."""
    global _RUNTIME_WIDTH, _RUNTIME_HEIGHT
    w = _clamp_structure_width(width)
    h = _clamp_structure_height(height)
    _RUNTIME_WIDTH = w
    _RUNTIME_HEIGHT = h
    if persist:
        settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
        settings.setValue(_SETTINGS_KEY_STRUCTURE_WIDTH, w)
        settings.setValue(_SETTINGS_KEY_STRUCTURE_HEIGHT, h)
    return w, h


def _load_runtime_structure_size_from_settings() -> None:
    w, h = load_saved_structure_depict_size()
    set_structure_depict_size(w, h, persist=False)


_load_runtime_structure_size_from_settings()


def browser_structure_preview_width() -> int:
    """Browser / preview pane width: 2× the current 2D render size."""
    return max(1, int(structure_depict_width()) * 2)


def browser_structure_preview_height() -> int:
    """Browser / preview pane height: 2× the current 2D render size."""
    return max(1, int(structure_depict_height()) * 2)


def browser_structure_preview_size() -> tuple[int, int]:
    return browser_structure_preview_width(), browser_structure_preview_height()


# Data → Browser structure preview (tracks Settings → GUI → 2D Render; 2× table size).
BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH = DEFAULT_STRUCTURE_DEPICT_WIDTH * 2
BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT = DEFAULT_STRUCTURE_DEPICT_HEIGHT * 2

# Back-compat aliases for the historical misspelling.
structure_depiict_width = structure_depict_width
structure_depiict_height = structure_depict_height
load_saved_structure_depiict_size = load_saved_structure_depict_size
set_structure_depiict_size = set_structure_depict_size
