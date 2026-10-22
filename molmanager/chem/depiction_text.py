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

"""Qt-free measurement of atom-label text in the bundled label font.

Sizes are em sizes in whatever unit the caller works in (molecule units in the
depiction builder). Kerning is ignored: labels are short, and the painter draws
each piece at its stored origin, so a pair kern only shifts glyphs within one
piece. Results use y up from the baseline, like the font itself.
"""

from __future__ import annotations

from molmanager.chem import depiction_font_metrics as _metrics


def _glyph(ch: str) -> tuple[int, int, int, int, int]:
    metrics = _metrics.GLYPHS.get(ch)
    if metrics is not None:
        return metrics
    return (_metrics.FALLBACK_ADVANCE, 0, 0, _metrics.FALLBACK_ADVANCE, _metrics.CAP_HEIGHT)


def text_advance(text: str, size: float) -> float:
    """Pen advance of *text* at em *size*: where the next piece would start."""
    total = sum(_glyph(ch)[0] for ch in text)
    return total * size / _metrics.UNITS_PER_EM


def text_ink_bounds(text: str, size: float) -> tuple[float, float, float, float]:
    """Inked box ``(min_x, min_y, max_x, max_y)`` of *text* from its baseline origin.

    Blank text, such as spaces only, returns ``(0, 0, 0, 0)``.
    """
    pen = 0
    min_x = min_y = max_x = max_y = None
    for ch in text:
        advance, x0, y0, x1, y1 = _glyph(ch)
        if x1 > x0 and y1 > y0:
            min_x = pen + x0 if min_x is None else min(min_x, pen + x0)
            max_x = pen + x1 if max_x is None else max(max_x, pen + x1)
            min_y = y0 if min_y is None else min(min_y, y0)
            max_y = y1 if max_y is None else max(max_y, y1)
        pen += advance
    if min_x is None:
        return (0.0, 0.0, 0.0, 0.0)
    scale = size / _metrics.UNITS_PER_EM
    return (min_x * scale, min_y * scale, max_x * scale, max_y * scale)


def cap_height(size: float) -> float:
    """Height of capital letters at em *size*, for centring labels on atoms."""
    return _metrics.CAP_HEIGHT * size / _metrics.UNITS_PER_EM
