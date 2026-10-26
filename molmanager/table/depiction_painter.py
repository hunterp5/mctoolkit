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

"""Paint a :class:`DepictionScene` with QPainter.

The scene is in molecule units with y up; the painter fits it to a rectangle,
flips y, and resolves colour roles through a palette, so one stored scene draws
at any size, pixel ratio and theme.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from functools import lru_cache

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF

from molmanager.chem.depiction_scene import (
    SCRIPT_SCALE,
    DepictionScene,
    PieceKind,
    SceneHighlight,
    StrokeStyle,
)
from molmanager.table.depiction_font import depiction_label_font

# Label text is drawn at this pixel size and scaled, so unhinted metrics stay exact.
_REFERENCE_FONT_PX = 128
# Fraction of the mean bond length.
_WAVE_LENGTH = 0.12
_WAVE_AMPLITUDE = 0.05
_DASH_PATTERN = [3.0, 2.0]
# Width of a highlighted bond's band, as a fraction of the mean bond length.
_HIGHLIGHT_BAND_WIDTH = 0.3
# Default structure cell (210px) with the painter's 5% padding, about six bonds
# across. The table stroke is 1px, so this is that stroke divided by a normal bond.
TABLE_REFERENCE_BOND_PX = (210.0 * 0.9) / 6.0
TABLE_STROKE_PER_BOND = 1.0 / TABLE_REFERENCE_BOND_PX

# RDKit's default element colours, so the first vector pictures compare like for like.
_LIGHT_ELEMENT_RGB: dict[int, tuple[int, int, int]] = {
    7: (0, 0, 255),
    8: (255, 0, 0),
    9: (51, 204, 204),
    15: (255, 128, 0),
    16: (204, 204, 0),
    17: (0, 204, 0),
    35: (153, 76, 26),
    53: (160, 32, 240),
}


@dataclass(frozen=True)
class ScenePalette:
    """Colour for each role: element colours over a foreground for the rest."""

    foreground: QColor
    elements: dict[int, QColor] = field(default_factory=dict)

    def colour(self, role: int) -> QColor:
        return self.elements.get(int(role), self.foreground)


def light_palette() -> ScenePalette:
    """Palette for a light background."""
    return ScenePalette(
        foreground=QColor(0, 0, 0),
        elements={role: QColor(*rgb) for role, rgb in _LIGHT_ELEMENT_RGB.items()},
    )


@dataclass(frozen=True)
class SceneFit:
    """Mapping from scene units to device pixels: ``x * scale + dx``, ``-y * scale + dy``."""

    scale: float
    dx: float
    dy: float

    def map(self, x: float, y: float) -> QPointF:
        return QPointF(x * self.scale + self.dx, -y * self.scale + self.dy)


def fit_scene(
    scene: DepictionScene,
    rect: QRectF,
    *,
    padding: float = 0.05,
    max_bond_px: float | None = None,
) -> SceneFit:
    """Centre *scene* in *rect*, leaving *padding* of the rectangle on each side.

    *max_bond_px* caps the scale so small molecules are not blown up to fill a cell.
    """
    min_x, min_y, max_x, max_y = scene.bounds
    width = max(max_x - min_x, 1e-6)
    height = max(max_y - min_y, 1e-6)
    room_w = rect.width() * (1 - 2 * padding)
    room_h = rect.height() * (1 - 2 * padding)
    scale = min(room_w / width, room_h / height)
    if max_bond_px is not None and scene.mean_bond_length > 0:
        scale = min(scale, max_bond_px / scene.mean_bond_length)
    centre_x = (min_x + max_x) / 2
    centre_y = (min_y + max_y) / 2
    return SceneFit(
        scale=scale,
        dx=rect.center().x() - centre_x * scale,
        dy=rect.center().y() + centre_y * scale,
    )


@lru_cache(maxsize=1)
def _label_font():
    return depiction_label_font(_REFERENCE_FONT_PX)


def _wave_path(path: QPainterPath, start: QPointF, end: QPointF, wave: float, amp: float) -> None:
    dx = end.x() - start.x()
    dy = end.y() - start.y()
    size = math.hypot(dx, dy)
    if size < 1e-6:
        return
    ux, uy = dx / size, dy / size
    nx, ny = -uy, ux
    halves = max(2, round(size / (wave / 2)))
    step = size / halves
    path.moveTo(start)
    for index in range(halves):
        sign = 1 if index % 2 == 0 else -1
        mid = (index + 0.5) * step
        control = QPointF(
            start.x() + ux * mid + nx * amp * 2 * sign,
            start.y() + uy * mid + ny * amp * 2 * sign,
        )
        stop = QPointF(start.x() + ux * (index + 1) * step, start.y() + uy * (index + 1) * step)
        path.quadTo(control, stop)


def _paint_highlight(
    painter: QPainter, scene: DepictionScene, fit: SceneFit, highlight: SceneHighlight
) -> None:
    """Bands along highlighted bonds, then discs on highlighted atoms, under the drawing.

    Indices outside the scene are skipped, so a highlight made for a molecule with
    fewer or more atoms than the scene cannot fail the paint.
    """
    bond_px = scene.mean_bond_length * fit.scale
    n_atoms = len(scene.atoms)
    painter.setBrush(Qt.NoBrush)
    for (begin, end), rgb in highlight.bonds.items():
        if not (0 <= begin < n_atoms and 0 <= end < n_atoms):
            continue
        pen = QPen(QColor.fromRgbF(*rgb), _HIGHLIGHT_BAND_WIDTH * bond_px)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        painter.drawLine(fit.map(*scene.atoms[begin]), fit.map(*scene.atoms[end]))
    painter.setPen(Qt.NoPen)
    for atom, rgb in highlight.atoms.items():
        if not 0 <= atom < n_atoms:
            continue
        radius = highlight.radius(atom) * bond_px
        painter.setBrush(QColor.fromRgbF(*rgb))
        painter.drawEllipse(fit.map(*scene.atoms[atom]), radius, radius)
    painter.setBrush(Qt.NoBrush)


def paint_scene_fit(
    painter: QPainter,
    scene: DepictionScene,
    fit: SceneFit,
    palette: ScenePalette,
    *,
    line_width_px: float = 1.0,
    highlight: SceneHighlight | None = None,
) -> None:
    """Draw *scene* through an explicit *fit*. The table centres a cell; the sketcher locks atoms."""
    bond_px = scene.mean_bond_length * fit.scale
    painter.save()
    try:
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        if highlight is not None:
            _paint_highlight(painter, scene, fit, highlight)
        painter.setPen(Qt.NoPen)
        for fill in scene.fills:
            painter.setBrush(palette.colour(fill.role))
            painter.drawPolygon(QPolygonF([fit.map(x, y) for x, y in fill.points]))
        painter.setBrush(Qt.NoBrush)

        paths: dict[tuple[int, StrokeStyle], QPainterPath] = {}
        for stroke in scene.strokes:
            path = paths.setdefault((stroke.role, stroke.style), QPainterPath())
            start = fit.map(stroke.x1, stroke.y1)
            end = fit.map(stroke.x2, stroke.y2)
            if stroke.style == StrokeStyle.WAVY:
                _wave_path(path, start, end, _WAVE_LENGTH * bond_px, _WAVE_AMPLITUDE * bond_px)
            else:
                path.moveTo(start)
                path.lineTo(end)
        for (role, style), path in paths.items():
            pen = QPen(palette.colour(role), line_width_px)
            pen.setJoinStyle(Qt.RoundJoin)
            pen.setCapStyle(Qt.FlatCap if style == StrokeStyle.HASH else Qt.RoundCap)
            if style == StrokeStyle.DASHED:
                pen.setDashPattern(_DASH_PATTERN)
            painter.strokePath(path, pen)

        font = _label_font()
        painter.setFont(font)
        em_px = scene.label_size * fit.scale
        for label in scene.labels:
            painter.setPen(palette.colour(label.role))
            for piece in label.pieces:
                size_px = em_px * (1.0 if piece.kind == PieceKind.NORMAL else SCRIPT_SCALE)
                origin = fit.map(piece.x, piece.y)
                painter.save()
                painter.translate(origin)
                factor = size_px / _REFERENCE_FONT_PX
                painter.scale(factor, factor)
                painter.drawText(QPointF(0, 0), piece.text)
                painter.restore()
    finally:
        painter.restore()


def paint_scene(
    painter: QPainter,
    scene: DepictionScene,
    rect: QRectF,
    palette: ScenePalette,
    *,
    line_width_px: float = 1.0,
    max_bond_px: float | None = None,
    highlight: SceneHighlight | None = None,
) -> SceneFit:
    """Draw *scene* centred in *rect*, over *highlight* if given. Returns the fit used."""
    fit = fit_scene(scene, rect, max_bond_px=max_bond_px)
    paint_scene_fit(
        painter,
        scene,
        fit,
        palette,
        line_width_px=line_width_px,
        highlight=highlight,
    )
    return fit
