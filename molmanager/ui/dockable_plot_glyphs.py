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

"""Rasterized footer glyphs and compact button styling."""

from __future__ import annotations

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PyQt5.QtWidgets import QLineEdit, QPushButton, QSizePolicy

from .dockable_plot_constants import (
    _BROWSER_NAV_BTN_HEIGHT,
    _BROWSER_NAV_BTN_WIDTH,
    _BROWSER_NAV_ICON_SIZE,
    _FOOTER_TEXT_FONT_PX,
    _FOOTER_TEXT_PAD_H,
    _GLYPH_BTN_SIZE,
    _GLYPH_ICON_SIZE,
    _GLYPH_INK,
    _PANE_TITLE_EDIT_WIDTH,
)


def _glyph_pen(width: float) -> QPen:
    pen = QPen(_GLYPH_INK, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _paint_glyph_pixmap(paint_fn, size: int = _GLYPH_ICON_SIZE, *, pad: float = 1.0) -> QPixmap:
    """Rasterize a glyph with stroke inset so ink stays centered and unclipped."""
    dpr = 2.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.fill(Qt.transparent)
    pm.setDevicePixelRatio(dpr)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    # Inset by ~½ stroke so edge strokes are not clipped asymmetrically.
    painter.translate(pad, pad)
    paint_fn(painter, float(size) - 2.0 * pad)
    painter.end()
    return pm


def _paint_glyph_icon(paint_fn, size: int = _GLYPH_ICON_SIZE, *, pad: float = 1.0) -> QIcon:
    return QIcon(_paint_glyph_pixmap(paint_fn, size, pad=pad))


def plot_options_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Compact gear icon for Plot Options."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.5, s * 0.12)))
        p.setBrush(Qt.NoBrush)
        cx = cy = s * 0.5
        r = s * 0.24
        R = s * 0.42
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(8):
            ang = i * 45.0
            from math import cos, radians, sin

            a = radians(ang)
            x0 = cx + r * 1.3 * cos(a)
            y0 = cy + r * 1.3 * sin(a)
            x1 = cx + R * cos(a)
            y1 = cy + R * sin(a)
            p.drawLine(QPointF(x0, y0), QPointF(x1, y1))

    return _paint_glyph_icon(paint, size)


def send_to_window_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Single window with a pop-out arrow for Send to New Window."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.6, s * 0.13)))
        p.setBrush(Qt.NoBrush)
        box = QRectF(s * 0.06, s * 0.34, s * 0.52, s * 0.56)
        p.drawRect(box)
        title_y = box.top() + s * 0.15
        p.drawLine(QPointF(box.left(), title_y), QPointF(box.right(), title_y))
        tip = QPointF(s * 0.92, s * 0.08)
        p.drawLine(QPointF(s * 0.50, s * 0.50), tip)
        head = QPainterPath()
        head.moveTo(tip)
        head.lineTo(QPointF(s * 0.64, s * 0.08))
        head.lineTo(QPointF(s * 0.92, s * 0.36))
        head.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(_GLYPH_INK)
        p.drawPath(head)

    return _paint_glyph_icon(paint, size)


def add_to_main_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Dock-into-main icon for Add to Main Window (inverse of send)."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.5, s * 0.12)))
        p.setBrush(Qt.NoBrush)
        # Main window / dock target on the left
        p.drawRect(QRectF(s * 0.10, s * 0.14, s * 0.44, s * 0.72))
        p.drawLine(QPointF(s * 0.10, s * 0.30), QPointF(s * 0.54, s * 0.30))
        # Arrow pointing into the window
        path = QPainterPath()
        path.moveTo(s * 0.90, s * 0.5)
        path.lineTo(s * 0.60, s * 0.5)
        path.moveTo(s * 0.72, s * 0.34)
        path.lineTo(s * 0.56, s * 0.5)
        path.lineTo(s * 0.72, s * 0.66)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def clear_selection_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Selection marquee corners with a centered X for Clear Selection."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.6, s * 0.13)))
        p.setBrush(Qt.NoBrush)
        x0, y0 = s * 0.08, s * 0.08
        x1, y1 = s * 0.92, s * 0.92
        arm = s * 0.20
        p.drawLine(QPointF(x0, y0), QPointF(x0 + arm, y0))
        p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + arm))
        p.drawLine(QPointF(x1, y0), QPointF(x1 - arm, y0))
        p.drawLine(QPointF(x1, y0), QPointF(x1, y0 + arm))
        p.drawLine(QPointF(x0, y1), QPointF(x0 + arm, y1))
        p.drawLine(QPointF(x0, y1), QPointF(x0, y1 - arm))
        p.drawLine(QPointF(x1, y1), QPointF(x1 - arm, y1))
        p.drawLine(QPointF(x1, y1), QPointF(x1, y1 - arm))
        m = s * 0.34
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))

    return _paint_glyph_icon(paint, size)


def pane_close_glyph_icon(size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Centered X for the plot-pane close control (red, matching prior × chrome)."""
    ink = QColor(192, 57, 43)  # #c0392b
    hover = QColor(231, 76, 60)  # #e74c3c
    pressed = QColor(146, 43, 33)  # #922b21

    def paint_for(color: QColor):
        def paint(p: QPainter, s: float) -> None:
            pen = QPen(color, max(1.8, s * 0.16))
            pen.setCapStyle(Qt.RoundCap)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            m = s * 0.22
            p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
            p.drawLine(QPointF(s - m, m), QPointF(m, s - m))

        return paint

    icon = QIcon()
    icon.addPixmap(_paint_glyph_pixmap(paint_for(ink), size), QIcon.Normal, QIcon.Off)
    icon.addPixmap(_paint_glyph_pixmap(paint_for(hover), size), QIcon.Active, QIcon.Off)
    icon.addPixmap(_paint_glyph_pixmap(paint_for(pressed), size), QIcon.Selected, QIcon.Off)
    return icon


def pane_nav_arrow_glyph_icon(direction: str, size: int = _GLYPH_ICON_SIZE) -> QIcon:
    """Filled triangle for plot-pane previous / next / reorder arrows."""
    d = str(direction or "").strip().lower()

    def paint(p: QPainter, s: float) -> None:
        tip = s * 0.16
        back = s * 0.84
        mid = s * 0.50
        spread = s * 0.32
        if d == "left":
            pts = (QPointF(tip, mid), QPointF(back, mid - spread), QPointF(back, mid + spread))
        elif d == "right":
            pts = (QPointF(back, mid), QPointF(tip, mid - spread), QPointF(tip, mid + spread))
        elif d == "up":
            pts = (QPointF(mid, tip), QPointF(mid - spread, back), QPointF(mid + spread, back))
        else:
            pts = (QPointF(mid, back), QPointF(mid - spread, tip), QPointF(mid + spread, tip))
        path = QPainterPath()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        path.lineTo(pts[2])
        path.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(_GLYPH_INK)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def browser_nav_glyph_icon(kind: str, size: int = _BROWSER_NAV_ICON_SIZE) -> QIcon:
    """Filled skip / step arrow for browser first / previous / next / last."""
    k = str(kind or "").strip().lower()
    if k in {"left", "prev", "back"}:
        return pane_nav_arrow_glyph_icon("left", size)
    if k in {"right", "next", "fwd"}:
        return pane_nav_arrow_glyph_icon("right", size)

    def paint(p: QPainter, s: float) -> None:
        p.setPen(Qt.NoPen)
        p.setBrush(_GLYPH_INK)
        radius = max(0.8, s * 0.07)
        bar_w = s * 0.12
        bar_h = s * 0.64
        bar_y = (s - bar_h) * 0.5
        mid = s * 0.50
        spread = s * 0.32
        if k == "first":
            p.drawRoundedRect(QRectF(s * 0.08, bar_y, bar_w, bar_h), radius, radius)
            tip = s * 0.28
            back = s * 0.92
            pts = (QPointF(tip, mid), QPointF(back, mid - spread), QPointF(back, mid + spread))
        else:
            p.drawRoundedRect(QRectF(s * 0.80, bar_y, bar_w, bar_h), radius, radius)
            tip = s * 0.72
            back = s * 0.08
            pts = (QPointF(tip, mid), QPointF(back, mid - spread), QPointF(back, mid + spread))
        path = QPainterPath()
        path.moveTo(pts[0])
        path.lineTo(pts[1])
        path.lineTo(pts[2])
        path.closeSubpath()
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def select_row_glyph_icon(size: int = _BROWSER_NAV_ICON_SIZE) -> QIcon:
    """Checkmark for Select this row / pair in the compound table."""

    def paint(p: QPainter, s: float) -> None:
        p.setPen(_glyph_pen(max(1.8, s * 0.16)))
        p.setBrush(Qt.NoBrush)
        path = QPainterPath()
        path.moveTo(s * 0.16, s * 0.52)
        path.lineTo(s * 0.40, s * 0.78)
        path.lineTo(s * 0.86, s * 0.20)
        p.drawPath(path)

    return _paint_glyph_icon(paint, size)


def _style_browser_glyph_button(btn: QPushButton, icon: QIcon, tooltip: str = "") -> None:
    """Glyph control that stretches horizontally in the browser nav row."""
    btn.setText("")
    btn.setIcon(icon)
    btn.setIconSize(QSize(_BROWSER_NAV_ICON_SIZE, _BROWSER_NAV_ICON_SIZE))
    btn.setMinimumWidth(_BROWSER_NAV_BTN_WIDTH)
    btn.setFixedHeight(_BROWSER_NAV_BTN_HEIGHT)
    btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFlat(False)
    btn.setStyleSheet("QPushButton { padding: 0px; margin: 0px; }")


def style_browser_nav_arrow(btn: QPushButton, kind: str, tooltip: str = "") -> None:
    """Skip/step control for browser first / previous / next / last."""
    _style_browser_glyph_button(btn, browser_nav_glyph_icon(kind), tooltip)


def style_browser_select_button(btn: QPushButton, *, checkable: bool = False) -> None:
    """Select-row glyph; *checkable* for Data → Browser toggle select/deselect."""
    _style_browser_glyph_button(btn, select_row_glyph_icon(), btn.toolTip())
    btn.setCheckable(bool(checkable))


def style_browser_nav_buttons(
    first: QPushButton,
    back: QPushButton,
    fwd: QPushButton,
    last: QPushButton,
    select: QPushButton | None = None,
    *,
    select_checkable: bool = False,
) -> None:
    """Replace unicode nav / Select labels with glyphs; keep existing tooltips."""
    style_browser_nav_arrow(first, "first")
    style_browser_nav_arrow(back, "left")
    style_browser_nav_arrow(fwd, "right")
    style_browser_nav_arrow(last, "last")
    if select is not None:
        style_browser_select_button(select, checkable=select_checkable)


def _add_compact_nav_widgets(layout, widgets) -> None:
    """Pin index fields and checkboxes to their size while nav buttons share the row."""
    if widgets is None:
        return
    if not isinstance(widgets, (list, tuple)):
        widgets = (widgets,)
    for widget in widgets:
        policy = QSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        policy.setHorizontalStretch(0)
        widget.setSizePolicy(policy)
        layout.addWidget(widget, 0)


def add_centered_browser_nav(
    layout,
    buttons: list,
    *,
    leading=None,
    trailing=None,
) -> None:
    """Share leftover row width across nav buttons; side chrome stays compact."""
    _add_compact_nav_widgets(layout, leading)
    for btn in buttons:
        policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        policy.setHorizontalStretch(1)
        btn.setSizePolicy(policy)
        layout.addWidget(btn, 1)
    _add_compact_nav_widgets(layout, trailing)


# Notepad format marks are larger than plot-chrome glyphs so the letters stay readable.
FORMAT_GLYPH_ICON_SIZE = 20
FORMAT_GLYPH_BTN_SIZE = 26
_FORMAT_GLYPH_PAD = 0.35


def _paint_format_letter(
    painter: QPainter,
    box: QRectF,
    letter: str,
    *,
    weight: int = QFont.Black,
    italic: bool = False,
) -> None:
    font = QFont("Segoe UI")
    font.setWeight(weight)
    font.setItalic(italic)
    font.setPixelSize(max(8, int(box.height() * 0.92)))
    painter.setFont(font)
    painter.setPen(_GLYPH_INK)
    painter.drawText(box, int(Qt.AlignCenter), letter)


def _format_glyph_icon(paint_fn, size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    return _paint_glyph_icon(paint_fn, size, pad=_FORMAT_GLYPH_PAD)


def bold_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Heavy bold mark for notepad text."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, 0, span, span), "B")

    return _format_glyph_icon(paint, size)


def italic_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Heavy italic mark for notepad text."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, 0, span, span), "I", weight=QFont.Bold, italic=True)

    return _format_glyph_icon(paint, size)


def underline_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Heavy underline mark for notepad text."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, 0, span, span * 0.72), "U")
        painter.setPen(_glyph_pen(max(2.2, span * 0.14)))
        y = span * 0.88
        painter.drawLine(QPointF(span * 0.06, y), QPointF(span * 0.94, y))

    return _format_glyph_icon(paint, size)


def text_color_glyph_icon(color: QColor, size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Heavy letter with a thick bar in *color* for notepad text color."""
    ink = QColor(color) if color.isValid() else QColor(_GLYPH_INK)

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, 0, span, span * 0.68), "A")
        bar_h = max(3.0, span * 0.22)
        painter.setPen(Qt.NoPen)
        painter.setBrush(ink)
        painter.drawRoundedRect(
            QRectF(span * 0.06, span - bar_h, span * 0.88, bar_h * 0.82), 1.2, 1.2
        )

    return _format_glyph_icon(paint, size)


def subscript_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Letter with a lowered numeral for subscript."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, 0, span * 0.64, span * 0.70), "A")
        _paint_format_letter(
            painter,
            QRectF(span * 0.48, span * 0.50, span * 0.52, span * 0.50),
            "2",
        )

    return _format_glyph_icon(paint, size)


def superscript_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Letter with a raised numeral for superscript."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, span * 0.30, span * 0.64, span * 0.70), "A")
        _paint_format_letter(painter, QRectF(span * 0.48, 0, span * 0.52, span * 0.50), "2")

    return _format_glyph_icon(paint, size)


def bullet_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Three heavy bullets with rules for a bulleted list."""

    def paint(painter: QPainter, span: float) -> None:
        line_pen = _glyph_pen(max(2.0, span * 0.12))
        radius = span * 0.12
        for frac in (0.24, 0.50, 0.76):
            cy = span * frac
            painter.setPen(Qt.NoPen)
            painter.setBrush(_GLYPH_INK)
            painter.drawEllipse(QPointF(span * 0.16, cy), radius, radius)
            painter.setPen(line_pen)
            painter.drawLine(QPointF(span * 0.40, cy), QPointF(span * 0.94, cy))

    return _format_glyph_icon(paint, size)


def numbering_glyph_icon(size: int = FORMAT_GLYPH_ICON_SIZE) -> QIcon:
    """Heavy numeral beside rules for a numbered list."""

    def paint(painter: QPainter, span: float) -> None:
        _paint_format_letter(painter, QRectF(0, span * 0.06, span * 0.42, span * 0.88), "1")
        painter.setPen(_glyph_pen(max(2.0, span * 0.12)))
        for frac in (0.28, 0.50, 0.72):
            y = span * frac
            painter.drawLine(QPointF(span * 0.50, y), QPointF(span * 0.96, y))

    return _format_glyph_icon(paint, size)


def style_plot_pane_nav_arrow(btn: QPushButton, direction: str, tooltip: str = "") -> None:
    """Square antialiased triangle control for plot-pane pager / reorder."""
    style_plot_chrome_glyph_button(
        btn, pane_nav_arrow_glyph_icon(direction), tooltip or btn.toolTip()
    )


def style_plot_pane_close_button(btn: QPushButton, tooltip: str = "") -> None:
    """Square antialiased X control for closing a plot pane."""
    style_plot_chrome_glyph_button(
        btn,
        pane_close_glyph_icon(),
        tooltip or btn.toolTip() or "Close this plot pane",
    )


def style_plot_chrome_glyph_button(btn: QPushButton, icon: QIcon, tooltip: str) -> None:
    """Turn a footer chrome button into a compact square glyph control."""
    btn.setText("")
    btn.setIcon(icon)
    btn.setIconSize(QSize(_GLYPH_ICON_SIZE, _GLYPH_ICON_SIZE))
    btn.setFixedSize(_GLYPH_BTN_SIZE, _GLYPH_BTN_SIZE)
    btn.setToolTip(tooltip)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFlat(False)
    # Zero padding so the icon is optically centered in the square button.
    btn.setStyleSheet("QPushButton { padding: 0px; margin: 0px; }")


def style_format_glyph_button(
    btn: QPushButton,
    icon: QIcon,
    tooltip: str,
    *,
    checkable: bool = False,
) -> None:
    """Square notepad format control, larger than plot chrome so the glyph reads clearly."""
    btn.setText("")
    btn.setIcon(icon)
    btn.setIconSize(QSize(FORMAT_GLYPH_ICON_SIZE, FORMAT_GLYPH_ICON_SIZE))
    btn.setFixedSize(FORMAT_GLYPH_BTN_SIZE, FORMAT_GLYPH_BTN_SIZE)
    btn.setToolTip(tooltip)
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFlat(False)
    btn.setCheckable(checkable)
    sheet = "QPushButton { padding: 0px; margin: 0px; }"
    if checkable:
        sheet += "QPushButton:checked { background-color: palette(midlight); }"
    btn.setStyleSheet(sheet)


def style_plot_footer_text_button(btn: QPushButton) -> None:
    """Compact height/padding for text chrome (Close Plot, region select, …)."""
    btn.setAutoDefault(False)
    btn.setDefault(False)
    btn.setFocusPolicy(Qt.NoFocus)
    btn.setFixedHeight(_GLYPH_BTN_SIZE)
    btn.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
    btn.setStyleSheet(
        "QPushButton {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " min-height: 0px;"
        " }"
    )


def style_plot_pane_title_edit(edit: QLineEdit) -> None:
    """Compact transparent title field between pager arrows."""
    edit.setFixedHeight(_GLYPH_BTN_SIZE)
    edit.setFixedWidth(_PANE_TITLE_EDIT_WIDTH)
    edit.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    edit.setAlignment(Qt.AlignCenter)
    edit.setFrame(False)
    edit.setAutoFillBackground(False)
    pal = edit.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    edit.setPalette(pal)
    edit.setStyleSheet(
        "QLineEdit {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " min-height: 0px;"
        " }"
        "QLineEdit:focus {"
        " border: 1px solid palette(highlight);"
        " background: transparent;"
        " background-color: transparent;"
        " }"
        "QLineEdit:read-only {"
        " selection-background-color: transparent;"
        " }"
    )


def style_floating_plot_title_edit(edit: QLineEdit) -> None:
    """Window-centered floating title: no chrome background, text only."""
    edit.setFixedHeight(_GLYPH_BTN_SIZE)
    edit.setMinimumWidth(80)
    edit.setMaximumWidth(360)
    edit.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    edit.setAlignment(Qt.AlignCenter)
    edit.setFrame(False)
    edit.setAutoFillBackground(False)
    edit.setAttribute(Qt.WA_TranslucentBackground, True)
    pal = edit.palette()
    pal.setColor(QPalette.Base, Qt.transparent)
    pal.setColor(QPalette.Window, Qt.transparent)
    edit.setPalette(pal)
    edit.setStyleSheet(
        "QLineEdit {"
        f" padding: 0px {_FOOTER_TEXT_PAD_H}px;"
        f" font-size: {_FOOTER_TEXT_FONT_PX}px;"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " min-height: 0px;"
        " }"
        "QLineEdit:focus {"
        " border: none;"
        " background: transparent;"
        " background-color: transparent;"
        " }"
        "QLineEdit:read-only {"
        " border: none;"
        " selection-background-color: transparent;"
        " }"
    )
