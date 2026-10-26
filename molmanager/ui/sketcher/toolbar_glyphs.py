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

"""Painted toolbar glyphs for the chemical sketcher (bonds, rings, modes, charge)."""

from __future__ import annotations

import math
from typing import Any

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QFont,
    QIcon,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
)


_INK = QColor(40, 40, 40)
_ICON_SIZE = 28


def _paint_icon(paint_fn, size: int = _ICON_SIZE) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    paint_fn(p, float(size))
    p.end()
    return QIcon(pm)


def _ink_pen(width: float = 1.8) -> QPen:
    pen = QPen(_INK)
    pen.setWidthF(width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _stereo_bond_axis(s: float) -> tuple[float, float, float, float, float, float]:
    """Shared hash/wedge axis: apex (narrow) → wide end, plus unit perpendicular."""
    m = s * 0.2
    x0, y0 = m, s - m
    x1, y1 = s - m, m + s * 0.1
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    px, py = -dy / length, dx / length
    return x0, y0, x1, y1, px, py


def _stereo_wedge_half(s: float, t: float) -> float:
    return s * 0.04 + t * s * 0.14


def bond_plain_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        p.setPen(_ink_pen(2.2))
        m = s * 0.22
        p.drawLine(QPointF(m, s - m), QPointF(s - m, m))

    return _paint_icon(paint, size)


def bond_wedge_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Same triangle outline as the hash glyph, filled solid.
        x0, y0, x1, y1, px, py = _stereo_bond_axis(s)
        half = _stereo_wedge_half(s, 1.0)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(_INK))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x0, y0),
                    QPointF(x1 + px * half, y1 + py * half),
                    QPointF(x1 - px * half, y1 - py * half),
                ]
            )
        )

    return _paint_icon(paint, size)


def bond_hash_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Hashed wedge (IUPAC/ACS): parallel bars widening from the tip.
        x0, y0, x1, y1, px, py = _stereo_bond_axis(s)
        dx, dy = x1 - x0, y1 - y0
        pen = _ink_pen(1.6)
        p.setPen(pen)
        n_marks = 6
        for i in range(n_marks):
            t = (i + 0.55) / (n_marks + 0.2)
            cx = x0 + dx * t
            cy = y0 + dy * t
            half = _stereo_wedge_half(s, t)
            p.drawLine(
                QPointF(cx - px * half, cy - py * half),
                QPointF(cx + px * half, cy + py * half),
            )

    return _paint_icon(paint, size)


def _draw_parallel_bond_strokes(p: QPainter, s: float, n_lines: int) -> None:
    """Diagonal multi-bond strokes with true perpendicular offsets (toolbar-readable)."""
    m = s * 0.18
    x0, y0 = m, s - m
    x1, y1 = s - m, m
    dx, dy = x1 - x0, y1 - y0
    length = math.hypot(dx, dy) or 1.0
    px, py = -dy / length, dx / length
    spacing = s * (0.13 if n_lines == 2 else 0.11)
    if n_lines == 2:
        offs = (-0.5 * spacing, 0.5 * spacing)
    else:
        offs = (-spacing, 0.0, spacing)
    p.setPen(_ink_pen(2.0 if n_lines == 2 else 1.7))
    for off in offs:
        p.drawLine(
            QPointF(x0 + px * off, y0 + py * off),
            QPointF(x1 + px * off, y1 + py * off),
        )


def bond_double_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        _draw_parallel_bond_strokes(p, s, 2)

    return _paint_icon(paint, size)


def bond_triple_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        _draw_parallel_bond_strokes(p, s, 3)

    return _paint_icon(paint, size)


def bond_wavy_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        p.setPen(_ink_pen(1.8))
        m = s * 0.18
        x0, y0 = m, s - m
        x1, y1 = s - m, m
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        path = QPainterPath()
        n = 16
        amp = s * 0.08
        for i in range(n + 1):
            t = i / n
            wave = math.sin(t * math.pi * 3.0) * amp
            x = x0 + dx * t + px * wave
            y = y0 + dy * t + py * wave
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.drawPath(path)

    return _paint_icon(paint, size)


def bond_dative_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        p.setPen(_ink_pen(1.8))
        m = s * 0.2
        x0, y0 = m, s - m
        x1, y1 = s - m * 1.15, m * 1.15
        dx, dy = x1 - x0, y1 - y0
        length = math.hypot(dx, dy) or 1.0
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        # Shaft stops short of the arrowhead tip.
        tip_back = s * 0.16
        p.drawLine(QPointF(x0, y0), QPointF(x1 - ux * tip_back, y1 - uy * tip_back))
        p.setBrush(QBrush(_INK))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x1, y1),
                    QPointF(x1 - ux * tip_back + px * s * 0.1, y1 - uy * tip_back + py * s * 0.1),
                    QPointF(x1 - ux * tip_back - px * s * 0.1, y1 - uy * tip_back - py * s * 0.1),
                ]
            )
        )

    return _paint_icon(paint, size)


def reaction_arrow_icon(size: int = _ICON_SIZE) -> QIcon:
    """Horizontal reaction arrow (plus on the left, arrow to the right)."""

    def paint(p: QPainter, s: float) -> None:
        ink = _INK
        p.setPen(_ink_pen(2.0))
        plus_x = s * 0.22
        plus_y = s * 0.50
        arm = s * 0.10
        p.drawLine(QPointF(plus_x - arm, plus_y), QPointF(plus_x + arm, plus_y))
        p.drawLine(QPointF(plus_x, plus_y - arm), QPointF(plus_x, plus_y + arm))
        y = s * 0.50
        x0 = s * 0.38
        x1 = s * 0.86
        head = s * 0.16
        p.drawLine(QPointF(x0, y), QPointF(x1 - head, y))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ink))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x1, y),
                    QPointF(x1 - head, y - s * 0.12),
                    QPointF(x1 - head, y + s * 0.12),
                ]
            )
        )

    return _paint_icon(paint, size)


def _regular_polygon(
    cx: float, cy: float, r: float, n: int, rot: float = -math.pi / 2
) -> list[QPointF]:
    return [
        QPointF(
            cx + r * math.cos(rot + 2 * math.pi * i / n),
            cy + r * math.sin(rot + 2 * math.pi * i / n),
        )
        for i in range(n)
    ]


def ring_icon(n_atoms: int, *, aromatic: bool = False, size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        cx = cy = s * 0.5
        r = s * 0.34
        # Vertex-up triangle bbox sits high in its circumcircle; nudge down to center in the button.
        if n_atoms == 3:
            cy = s * 0.5 + r * 0.22
            r = s * 0.36
        pts = _regular_polygon(cx, cy, r, n_atoms)
        p.setPen(_ink_pen(1.7))
        p.setBrush(Qt.NoBrush)
        for i in range(n_atoms):
            p.drawLine(pts[i], pts[(i + 1) % n_atoms])
        if aromatic and n_atoms == 6:
            # Alternating double-bond offsets (Kekulé) for benzene glyph.
            for i in range(0, 6, 2):
                a, b = pts[i], pts[(i + 1) % 6]
                mx, my = (a.x() + b.x()) * 0.5, (a.y() + b.y()) * 0.5
                ox, oy = (cx - mx) * 0.28, (cy - my) * 0.28
                p.drawLine(
                    QPointF(a.x() + ox, a.y() + oy),
                    QPointF(b.x() + ox, b.y() + oy),
                )

    return _paint_icon(paint, size)


_HETERO_INK = {
    "N": QColor(20, 70, 180),
    "O": QColor(180, 30, 30),
    "S": QColor(170, 140, 20),
    "P": QColor(190, 100, 20),
    "F": QColor(40, 140, 40),
    "Cl": QColor(20, 140, 40),
    "Br": QColor(140, 40, 20),
    "I": QColor(120, 40, 160),
}


def _paint_image(paint_fn, size: int) -> QImage:
    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(Qt.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    paint_fn(painter, float(size))
    painter.end()
    return image


def template_structure_image(
    points: list[tuple[float, float]],
    bonds: list[tuple[int, int, int]],
    elements: list[str],
    *,
    size: int = _ICON_SIZE,
) -> QImage:
    """Raster of the heavy-atom graph a ring template places."""

    def paint(p: QPainter, s: float) -> None:
        if not points:
            return
        xs = [pt[0] for pt in points]
        ys = [pt[1] for pt in points]
        span = max(max(xs) - min(xs), max(ys) - min(ys), 1e-6)
        pad = s * 0.16
        scale = (s - 2.0 * pad) / span
        cx = (min(xs) + max(xs)) * 0.5
        cy = (min(ys) + max(ys)) * 0.5
        origin = s * 0.5

        def mapped(index: int) -> QPointF:
            x, y = points[index]
            return QPointF(origin + (x - cx) * scale, origin + (y - cy) * scale)

        verts = [mapped(i) for i in range(len(points))]
        centroid = QPointF(
            sum(pt.x() for pt in verts) / len(verts),
            sum(pt.y() for pt in verts) / len(verts),
        )
        labeled = [str(el) not in {"", "C"} for el in elements]
        trim = s * 0.12
        p.setBrush(Qt.NoBrush)
        for i, j, order in bonds:
            if i >= len(verts) or j >= len(verts):
                continue
            a, b = _trimmed_segment(
                verts[i],
                verts[j],
                trim if labeled[i] else 0.0,
                trim if labeled[j] else 0.0,
            )
            p.setPen(_ink_pen(1.45))
            p.drawLine(a, b)
            if int(order) < 2:
                continue
            mx = (a.x() + b.x()) * 0.5
            my = (a.y() + b.y()) * 0.5
            ox, oy = centroid.x() - mx, centroid.y() - my
            olen = math.hypot(ox, oy) or 1.0
            shift = s * 0.055
            ox, oy = ox / olen * shift, oy / olen * shift
            p.drawLine(QPointF(a.x() + ox, a.y() + oy), QPointF(b.x() + ox, b.y() + oy))

        font = QFont("Helvetica", max(7, int(s * 0.26)))
        font.setBold(True)
        font.setStyleHint(QFont.SansSerif)
        p.setFont(font)
        metrics = p.fontMetrics()
        for index, element in enumerate(elements):
            if index >= len(verts) or not labeled[index]:
                continue
            symbol = str(element)
            p.setPen(QPen(_HETERO_INK.get(symbol, _INK)))
            width = (
                metrics.horizontalAdvance(symbol)
                if hasattr(metrics, "horizontalAdvance")
                else metrics.width(symbol)
            )
            pt = verts[index]
            p.drawText(
                QRectF(
                    pt.x() - width * 0.5 - 1,
                    pt.y() - metrics.height() * 0.5,
                    width + 2,
                    metrics.height(),
                ),
                int(Qt.AlignCenter),
                symbol,
            )

    return _paint_image(paint, size)


def template_structure_icon(
    points: list[tuple[float, float]],
    bonds: list[tuple[int, int, int]],
    elements: list[str],
    *,
    size: int = _ICON_SIZE,
) -> QIcon:
    """Toolbar picture of the heavy-atom graph a ring template places."""
    return QIcon(QPixmap.fromImage(template_structure_image(points, bonds, elements, size=size)))


def _trimmed_segment(
    start: QPointF, end: QPointF, trim_start: float, trim_end: float
) -> tuple[QPointF, QPointF]:
    dx, dy = end.x() - start.x(), end.y() - start.y()
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    if trim_start:
        start = QPointF(start.x() + ux * trim_start, start.y() + uy * trim_start)
    if trim_end:
        end = QPointF(end.x() - ux * trim_end, end.y() - uy * trim_end)
    return start, end


def ring_template_image(
    elements: list[str],
    orders: list[int],
    *,
    size: int = _ICON_SIZE,
) -> QImage:
    """Raster for a monocycle, using the same vertex layout the canvas places."""
    from .iupac_rings import ring_vertex_offsets_y_up, rotate_offsets_to_inward_heteroatoms

    count = len(elements)
    offsets = ring_vertex_offsets_y_up(count, bond_length=60.0)
    if count >= 9:
        offsets = rotate_offsets_to_inward_heteroatoms(offsets, elements)
    points = [(x, -y) for x, y in offsets]
    bonds = [(i, (i + 1) % count, int(orders[i]) if i < len(orders) else 1) for i in range(count)]
    return template_structure_image(points, bonds, elements, size=size)


def ring_template_icon(
    elements: list[str],
    orders: list[int],
    *,
    size: int = _ICON_SIZE,
) -> QIcon:
    """Icon for a monocycle, using the same vertex layout the canvas places."""
    return QIcon(QPixmap.fromImage(ring_template_image(elements, orders, size=size)))


def fused_ring_image(template: Any, *, size: int = _ICON_SIZE) -> QImage:
    """Raster for a fused template, using its heavy-atom coordinates and symbols."""
    points = [(float(x), -float(y)) for x, y in template.coords]
    return template_structure_image(
        points,
        [(int(i), int(j), int(order)) for i, j, order in template.bonds],
        [str(el) for el in template.elements],
        size=size,
    )


def fused_ring_icon(template: Any, *, size: int = _ICON_SIZE) -> QIcon:
    """Icon for a fused template, using its heavy-atom coordinates and symbols."""
    return QIcon(QPixmap.fromImage(fused_ring_image(template, size=size)))


def mode_select_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Marquee rectangle + simple pointer tip.
        pen = _ink_pen(1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        m = s * 0.18
        p.drawRect(QRectF(m, m, s * 0.48, s * 0.42))
        p.setPen(_ink_pen(1.6))
        p.setBrush(QBrush(_INK))
        tip = QPointF(s * 0.52, s * 0.48)
        p.drawPolygon(
            QPolygonF(
                [
                    tip,
                    QPointF(s * 0.78, s * 0.62),
                    QPointF(s * 0.64, s * 0.66),
                    QPointF(s * 0.72, s * 0.86),
                    QPointF(s * 0.62, s * 0.90),
                    QPointF(s * 0.54, s * 0.70),
                    QPointF(s * 0.42, s * 0.74),
                ]
            )
        )

    return _paint_icon(paint, size)


def mode_lasso_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Freeform lasso loop + pointer tip.
        pen = _ink_pen(1.5)
        pen.setStyle(Qt.DashLine)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.22, s * 0.38)
        path.cubicTo(s * 0.12, s * 0.18, s * 0.42, s * 0.08, s * 0.52, s * 0.22)
        path.cubicTo(s * 0.66, s * 0.12, s * 0.78, s * 0.34, s * 0.62, s * 0.48)
        path.cubicTo(s * 0.72, s * 0.62, s * 0.48, s * 0.72, s * 0.34, s * 0.58)
        path.cubicTo(s * 0.20, s * 0.66, s * 0.28, s * 0.48, s * 0.22, s * 0.38)
        p.drawPath(path)
        p.setPen(_ink_pen(1.6))
        p.setBrush(QBrush(_INK))
        tip = QPointF(s * 0.58, s * 0.52)
        p.drawPolygon(
            QPolygonF(
                [
                    tip,
                    QPointF(s * 0.82, s * 0.66),
                    QPointF(s * 0.68, s * 0.70),
                    QPointF(s * 0.76, s * 0.90),
                    QPointF(s * 0.66, s * 0.94),
                    QPointF(s * 0.58, s * 0.74),
                    QPointF(s * 0.46, s * 0.78),
                ]
            )
        )

    return _paint_icon(paint, size)


def mode_text_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Capital "A" with underline — text / label edit tool.
        from PyQt5.QtGui import QFont, QFontMetrics

        font = QFont("Helvetica", max(10, int(s * 0.55)))
        font.setBold(True)
        font.setStyleHint(QFont.SansSerif)
        fm = QFontMetrics(font)
        text = "A"
        tw = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
        x = (s - tw) * 0.5
        y = s * 0.62
        path = QPainterPath()
        path.addText(x, y, font, text)
        p.fillPath(path, QBrush(_INK))
        p.setPen(_ink_pen(1.8))
        uy = s * 0.78
        p.drawLine(QPointF(s * 0.22, uy), QPointF(s * 0.78, uy))

    return _paint_icon(paint, size)


def mode_draw_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Pencil centered on the icon mid-point (tip SW, eraser NE).
        # Nudge the construction origin toward the tip so the wide eraser end
        # does not pull the ink bbox off-center.
        ux, uy = 0.7071, -0.7071
        px, py = 0.7071, 0.7071
        half_len = s * 0.32
        half_w = s * 0.09
        tip_len = s * 0.13
        nudge = half_w * 0.55
        cx = s * 0.5 - ux * nudge
        cy = s * 0.5 - uy * nudge
        back_x = cx + ux * half_len
        back_y = cy + uy * half_len
        front_x = cx - ux * (half_len - tip_len)
        front_y = cy - uy * (half_len - tip_len)
        body = QPolygonF(
            [
                QPointF(front_x + px * half_w, front_y + py * half_w),
                QPointF(back_x + px * half_w, back_y + py * half_w),
                QPointF(back_x - px * half_w, back_y - py * half_w),
                QPointF(front_x - px * half_w, front_y - py * half_w),
            ]
        )
        p.setPen(_ink_pen(1.4))
        p.setBrush(QBrush(QColor(220, 220, 220)))
        p.drawPolygon(body)
        tip_pt = QPointF(cx - ux * half_len, cy - uy * half_len)
        tip = QPolygonF(
            [
                tip_pt,
                QPointF(front_x + px * half_w, front_y + py * half_w),
                QPointF(front_x - px * half_w, front_y - py * half_w),
            ]
        )
        p.setBrush(QBrush(_INK))
        p.drawPolygon(tip)
        # Eraser ferrule band inset from the back end (keeps the glyph centered).
        band0, band1 = half_len - s * 0.02, half_len - s * 0.10
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(90, 90, 100)))
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx + ux * band0 + px * half_w, cy + uy * band0 + py * half_w),
                    QPointF(cx + ux * band1 + px * half_w, cy + uy * band1 + py * half_w),
                    QPointF(cx + ux * band1 - px * half_w, cy + uy * band1 - py * half_w),
                    QPointF(cx + ux * band0 - px * half_w, cy + uy * band0 - py * half_w),
                ]
            )
        )

    return _paint_icon(paint, size)


def mode_chain_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        pen = _ink_pen(1.7)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        points = [
            QPointF(s * 0.16, s * 0.62),
            QPointF(s * 0.38, s * 0.34),
            QPointF(s * 0.60, s * 0.62),
            QPointF(s * 0.82, s * 0.34),
        ]
        path = QPainterPath(points[0])
        for point in points[1:]:
            path.lineTo(point)
        p.drawPath(path)
        p.setBrush(QBrush(_INK))
        p.setPen(Qt.NoPen)
        for point in points:
            p.drawEllipse(point, s * 0.045, s * 0.045)

    return _paint_icon(paint, size)


def mode_erase_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Classic angled eraser, centered in the button (no floor line).
        cx = cy = s * 0.5
        ux, uy = 0.7071, -0.7071
        px, py = 0.7071, 0.7071
        half_len = s * 0.30
        half_w = s * 0.16
        body = QPolygonF(
            [
                QPointF(cx - ux * half_len + px * half_w, cy - uy * half_len + py * half_w),
                QPointF(cx + ux * half_len + px * half_w, cy + uy * half_len + py * half_w),
                QPointF(cx + ux * half_len - px * half_w, cy + uy * half_len - py * half_w),
                QPointF(cx - ux * half_len - px * half_w, cy - uy * half_len - py * half_w),
            ]
        )
        p.setPen(_ink_pen(1.4))
        p.setBrush(QBrush(QColor(235, 150, 160)))
        p.drawPolygon(body)
        # Ferrule / metal band across the midsection.
        band_half = s * 0.07
        p.setBrush(QBrush(QColor(90, 90, 100)))
        p.setPen(Qt.NoPen)
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(cx - ux * band_half + px * half_w, cy - uy * band_half + py * half_w),
                    QPointF(cx + ux * band_half + px * half_w, cy + uy * band_half + py * half_w),
                    QPointF(cx + ux * band_half - px * half_w, cy + uy * band_half - py * half_w),
                    QPointF(cx - ux * band_half - px * half_w, cy - uy * band_half - py * half_w),
                ]
            )
        )

    return _paint_icon(paint, size)


def view_3d_icon(size: int = _ICON_SIZE) -> QIcon:
    """Bold “3D” label for the sketcher live 3D preview toggle."""

    def paint(p: QPainter, s: float) -> None:
        f = QFont("Arial")
        f.setBold(True)
        f.setPixelSize(max(10, int(round(s * 0.48))))
        p.setFont(f)
        p.setPen(_INK)
        p.drawText(QRectF(0.0, 0.0, s, s), int(Qt.AlignCenter), "3D")

    return _paint_icon(paint, size)


def clear_sketch_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        # Trash-can glyph for clear sketch.
        p.setPen(_ink_pen(1.6))
        p.setBrush(Qt.NoBrush)
        lid_y = s * 0.28
        p.drawLine(QPointF(s * 0.22, lid_y), QPointF(s * 0.78, lid_y))
        p.drawLine(QPointF(s * 0.38, s * 0.18), QPointF(s * 0.62, s * 0.18))
        p.drawLine(QPointF(s * 0.50, s * 0.18), QPointF(s * 0.50, lid_y))
        body = QPainterPath()
        body.moveTo(s * 0.28, lid_y + 1.0)
        body.lineTo(s * 0.34, s * 0.82)
        body.lineTo(s * 0.66, s * 0.82)
        body.lineTo(s * 0.72, lid_y + 1.0)
        p.drawPath(body)
        for x in (0.42, 0.50, 0.58):
            p.drawLine(QPointF(s * x, s * 0.38), QPointF(s * x, s * 0.72))

    return _paint_icon(paint, size)


def _charge_circle_and_mark(p: QPainter, s: float, *, plus: bool) -> None:
    """Centered charge badge: circle + geometric +/− (avoids font metrics drift)."""
    cx = cy = s * 0.5
    r = s * 0.34
    p.setPen(_ink_pen(1.6))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QPointF(cx, cy), r, r)
    mark = QColor(170, 30, 30)
    arm = s * 0.15
    thick = max(2.0, s * 0.09)
    pen = QPen(mark)
    pen.setWidthF(thick)
    pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    p.drawLine(QPointF(cx - arm, cy), QPointF(cx + arm, cy))
    if plus:
        p.drawLine(QPointF(cx, cy - arm), QPointF(cx, cy + arm))


def charge_plus_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        _charge_circle_and_mark(p, s, plus=True)

    return _paint_icon(paint, size)


def charge_minus_icon(size: int = _ICON_SIZE) -> QIcon:
    def paint(p: QPainter, s: float) -> None:
        _charge_circle_and_mark(p, s, plus=False)

    return _paint_icon(paint, size)


def status_ok_icon(size: int = _ICON_SIZE) -> QIcon:
    """Green checkmark for a clean sketch."""

    def paint(p: QPainter, s: float) -> None:
        green = QColor(34, 140, 64)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(green))
        p.drawEllipse(QRectF(s * 0.08, s * 0.08, s * 0.84, s * 0.84))
        pen = QPen(QColor(255, 255, 255))
        pen.setWidthF(max(2.2, s * 0.11))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.28, s * 0.52)
        path.lineTo(s * 0.44, s * 0.68)
        path.lineTo(s * 0.74, s * 0.34)
        p.drawPath(path)

    return _paint_icon(paint, size)


def status_caution_icon(size: int = _ICON_SIZE) -> QIcon:
    """Yellow caution triangle for unspecified stereo / soft IUPAC notes."""

    def paint(p: QPainter, s: float) -> None:
        amber = QColor(220, 170, 20)
        ink = QColor(50, 40, 0)
        tri = QPolygonF(
            [
                QPointF(s * 0.50, s * 0.10),
                QPointF(s * 0.90, s * 0.88),
                QPointF(s * 0.10, s * 0.88),
            ]
        )
        p.setPen(QPen(ink, max(1.0, s * 0.04)))
        p.setBrush(QBrush(amber))
        p.drawPolygon(tri)
        pen = QPen(ink)
        pen.setWidthF(max(2.0, s * 0.09))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(s * 0.50, s * 0.34), QPointF(s * 0.50, s * 0.58))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ink))
        p.drawEllipse(QPointF(s * 0.50, s * 0.72), s * 0.045, s * 0.045)

    return _paint_icon(paint, size)


def status_error_icon(size: int = _ICON_SIZE) -> QIcon:
    """Red X for invalid valence or hard structural errors."""

    def paint(p: QPainter, s: float) -> None:
        red = QColor(200, 40, 40)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(red))
        p.drawEllipse(QRectF(s * 0.08, s * 0.08, s * 0.84, s * 0.84))
        pen = QPen(QColor(255, 255, 255))
        pen.setWidthF(max(2.2, s * 0.11))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        m = s * 0.30
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))

    return _paint_icon(paint, size)


# Carbocycle toolbar order: (template key, atom count, aromatic, tooltip)
TOOLBAR_RING_TEMPLATES: tuple[tuple[str, int, bool, str], ...] = (
    ("Benzene", 6, True, "Benzene ring template"),
    ("Pyridine", 6, True, "Pyridine ring template"),
    ("Cyclohexyl", 6, False, "Cyclohexyl ring template"),
    ("Cyclopentyl", 5, False, "Cyclopentyl ring template"),
    ("Cyclobutane", 4, False, "Cyclobutyl ring template"),
    ("Cyclopropane", 3, False, "Cyclopropyl ring template"),
)
