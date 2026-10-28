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

"""QTableView stack for CompoundTableModel (delegate, header, view)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
from typing import TYPE_CHECKING

from PyQt5.QtCore import QEvent, QItemSelectionModel, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLineEdit,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTableView,
    QWIDGETSIZE_MAX,
)

from ..table.structure_depiction_layout import (
    set_structure_depict_size,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_size_for_cell_resize,
    structure_depict_width,
    structure_row_default_height,
)

# Zoomed rows are twice the depiction height; normal rows add only a few pixels of padding.
_ZOOMED_ROW_HEIGHT_NUMERATOR = 3
_ZOOMED_ROW_HEIGHT_DENOMINATOR = 2

if TYPE_CHECKING:
    from .table_row_selection import TableRowSelectionController

# Must match CompoundTableModel.STRUCTURE_COL
_STRUCTURE_COL = 1
_ROW_HEADER_HIGHLIGHT_ALPHA = 110
_USER_SELECTION_EVENTS = frozenset(
    {QEvent.MouseButtonPress, QEvent.MouseButtonRelease, QEvent.MouseMove, QEvent.KeyPress}
)

# Palette roles so Fusion headers follow light/dark/custom GUI colors.
# Any QHeaderView stylesheet without these roles freezes the section fill.
TABLE_HEADER_SECTION_QSS = """
QHeaderView {
    background-color: palette(button);
    color: palette(button-text);
}
QHeaderView::section {
    padding-top: 1px;
    padding-bottom: 1px;
    background-color: palette(button);
    color: palette(button-text);
    border: none;
    border-right: 1px solid palette(mid);
    border-bottom: 1px solid palette(mid);
}
"""

# Compact QSS padding (1px × 2) plus the section border.
_HEADER_FONT_PAD_PX = 3
# Fast edge-scroll while dragging a column header off the visible area.
_HEADER_DRAG_SCROLL_INTERVAL_MS = 16
_HEADER_DRAG_SCROLL_MIN_STEP_PX = 32
_HEADER_DRAG_SCROLL_MAX_STEP_PX = 180


def header_bar_extent_for_font(header: QHeaderView, font: QFont) -> int:
    """Thickness of the header bar for *font* (height if horizontal, width if vertical)."""
    fm = QFontMetrics(font)
    extra = _HEADER_FONT_PAD_PX
    if header.orientation() == Qt.Horizontal:
        return max(fm.height(), fm.lineSpacing()) + extra
    model = header.model()
    n = int(model.rowCount()) if model is not None else 1
    sample = str(max(99, n))
    return max(fm.horizontalAdvance(sample) + extra + 6, 1)


def apply_header_font(header: QHeaderView | None, font: QFont) -> None:
    """Apply *font* and resize the header bar so labels are not clipped."""
    if header is None:
        return
    header.setMinimumSize(0, 0)
    header.setMaximumSize(QWIDGETSIZE_MAX, QWIDGETSIZE_MAX)
    header.setFont(font)
    vp = header.viewport()
    if vp is not None:
        vp.setFont(font)
    qss = header.styleSheet()
    if qss:
        header.setStyleSheet(qss)
    extent = header_bar_extent_for_font(header, font)
    if header.orientation() == Qt.Horizontal:
        header.setFixedHeight(extent)
    else:
        header.setFixedWidth(extent)
    header.updateGeometry()
    header.update()
    if vp is not None:
        vp.update()


def apply_table_header_theme(header: QHeaderView | None, pal: QPalette) -> None:
    """Push *pal* onto a header and re-resolve its palette() stylesheet colors."""
    if header is None:
        return
    header.setPalette(pal)
    vp = header.viewport()
    if vp is not None:
        vp.setPalette(pal)
    qss = header.styleSheet()
    if qss:
        header.setStyleSheet(qss)
    style = header.style()
    if style is not None:
        style.unpolish(header)
        style.polish(header)
        if vp is not None:
            style.unpolish(vp)
            style.polish(vp)
    header.update()
    if vp is not None:
        vp.update()


def scaled_structure_pixmap(
    pix: QPixmap,
    origin_width: int,
    origin_height: int,
    width: int,
    height: int,
) -> QPixmap:
    """Scale a cached depiction from the origin cell size to *width* × *height*.

    A reaction or a zoomed row is already wider or taller than one molecule. Scaling
    by the ratio of the shared depiction size keeps that relative size.
    """
    if pix.isNull():
        return pix
    origin_w = max(1, int(origin_width))
    origin_h = max(1, int(origin_height))
    new_w = max(1, int(width))
    new_h = max(1, int(height))
    if new_w == origin_w and new_h == origin_h:
        return pix
    target_w = max(1, int(round(pix.width() * new_w / origin_w)))
    target_h = max(1, int(round(pix.height() * new_h / origin_h)))
    if target_w == pix.width() and target_h == pix.height():
        return pix
    return pix.scaled(target_w, target_h, Qt.IgnoreAspectRatio, Qt.FastTransformation)


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap or a neutral placeholder."""

    def __init__(self, parent=None, compound_model=None):
        super().__init__(parent)
        self._cell_background: QColor | None = QColor(255, 255, 255)
        self._compound_model = compound_model
        self._preview_active = False
        self._preview_origin_w = 0
        self._preview_origin_h = 0

    def set_depiction_preview(
        self, active: bool, origin_width: int = 0, origin_height: int = 0
    ) -> None:
        """While a border drag is active, draw cached pictures at the live depiction size."""
        self._preview_active = bool(active)
        self._preview_origin_w = int(origin_width)
        self._preview_origin_h = int(origin_height)

    def _pixmap_column_source_size(self, index) -> tuple[int, int] | None:
        """Depiction size a rendered data column was drawn at, or None for Structure."""
        if index is None or self._compound_model is None:
            return None
        col = int(index.column())
        headers = getattr(self._compound_model, "_headers", ())
        if col < 0 or col >= len(headers):
            return None
        lookup = getattr(self._compound_model, "pixmap_column_source_size", None)
        if not callable(lookup):
            return None
        return lookup(str(headers[col]))

    def _pixmap_for_cell(self, pix: QPixmap, index=None) -> QPixmap:
        """Draw *pix* at the current depiction size.

        A picture already painted at that height, such as a depiction scene, is
        left as it is. Scaling it would blur the drawing. A raster from another
        size is scaled for the live drag, then replaced when the drag ends.
        """
        current_w = structure_depict_width()
        current_h = structure_depict_height()
        if not pix.isNull() and pix.height() == current_h:
            return pix
        source = self._pixmap_column_source_size(index)
        if source is not None:
            return scaled_structure_pixmap(pix, source[0], source[1], current_w, current_h)
        if not self._preview_active:
            return pix
        return scaled_structure_pixmap(
            pix,
            self._preview_origin_w,
            self._preview_origin_h,
            current_w,
            current_h,
        )

    def _pixmap_inside_cell(self, pix: QPixmap, rect: QRect) -> QPixmap:
        """Shrink *pix* so it stays inside *rect* without changing its shape."""
        avail_w = max(1, int(rect.width()) - 4)
        avail_h = max(1, int(rect.height()) - 4)
        if pix.width() <= avail_w and pix.height() <= avail_h:
            return pix
        return pix.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.FastTransformation)

    def set_compound_model(self, compound_model) -> None:
        self._compound_model = compound_model

    def set_cell_background(self, color: QColor | None) -> None:
        """Cell fill color; ``None`` falls back to white for legacy callers."""
        self._cell_background = color

    def _cell_has_structure_pixmap(self, index) -> bool:
        pix = index.data(Qt.DecorationRole)
        return isinstance(pix, QPixmap) and not pix.isNull()

    def _cell_is_selected(self, opt: QStyleOptionViewItem, index) -> bool:
        if opt.state & QStyle.State_Selected:
            return True
        from .table_selection_delegate import source_row_for_view_index

        if self._compound_model is None:
            return False
        row = source_row_for_view_index(index, self._compound_model)
        return row >= 0 and self._compound_model.is_row_highlighted(row)

    def _fill_cell_background(
        self,
        painter,
        opt: QStyleOptionViewItem,
        index,
        *,
        has_rendered_structure: bool = False,
    ) -> None:
        if self._cell_is_selected(opt, index):
            pal = QApplication.palette() if QApplication.instance() else opt.palette
            painter.fillRect(opt.rect, pal.color(QPalette.Highlight))
            return
        if has_rendered_structure:
            painter.fillRect(opt.rect, QColor(255, 255, 255))
            return
        bg = self._cell_background if self._cell_background is not None else QColor(255, 255, 255)
        painter.fillRect(opt.rect, bg)

    def paint(self, painter, option, index):  # noqa: N802
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        has_pix = self._cell_has_structure_pixmap(index)
        self._fill_cell_background(painter, opt, index, has_rendered_structure=has_pix)
        pix = index.data(Qt.DecorationRole) if has_pix else None
        if has_pix:
            pix = self._pixmap_inside_cell(self._pixmap_for_cell(pix, index), opt.rect)
            r = opt.rect
            x = r.x() + (r.width() - pix.width()) // 2
            y = r.y() + (r.height() - pix.height()) // 2
            painter.drawPixmap(x, y, pix)
        else:
            hint = index.data(Qt.DisplayRole)
            text = hint if isinstance(hint, str) and hint.strip() else "—"
            painter.save()
            painter.setFont(opt.font)
            if self._cell_is_selected(opt, index):
                pal = QApplication.palette() if QApplication.instance() else opt.palette
                painter.setPen(pal.color(QPalette.HighlightedText))
            else:
                painter.setPen(opt.palette.text().color())
            margin = 6
            r = QRect(
                opt.rect.x() + margin,
                opt.rect.y() + margin,
                max(1, opt.rect.width() - 2 * margin),
                max(1, opt.rect.height() - 2 * margin),
            )
            align = index.data(Qt.TextAlignmentRole)
            if not isinstance(align, int):
                align = int(Qt.AlignLeft | Qt.AlignVCenter)
            painter.drawText(r, int(align) | int(Qt.TextWordWrap), text)
            painter.restore()

    def createEditor(self, parent, option, index):  # noqa: N802
        editor = super().createEditor(parent, option, index)
        if isinstance(editor, QLineEdit):
            editor.setPlaceholderText("SMILES or InChI")
        return editor

    def updateEditorGeometry(self, editor, option, index) -> None:  # noqa: N802
        rect = option.rect
        if rect.width() < 8 or rect.height() < 8:
            editor.setGeometry(rect)
            return
        height = min(rect.height() - 4, max(editor.sizeHint().height(), 24))
        editor.setGeometry(
            rect.x() + 4,
            rect.bottom() - height - 2,
            max(1, rect.width() - 8),
            height,
        )

    def sizeHint(self, option, index):  # noqa: N802
        sh = super().sizeHint(option, index)
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            pix = self._pixmap_for_cell(pix, index)
            return QSize(max(sh.width(), pix.width()), max(sh.height(), pix.height()))
        return QSize(structure_depict_width(), max(sh.height(), structure_depict_height()))


def _header_grip_margin(header: QHeaderView) -> int:
    """Qt's own section-border hit width, in pixels."""
    style = header.style()
    if style is None:
        return 4
    raw = int(style.pixelMetric(QStyle.PM_HeaderGripMargin, None, header))
    return raw if raw > 0 else 4


def _header_grip_px(header: QHeaderView) -> int:
    """Pixel slop for a column resize grip, floored so the viewport edge stays hittable."""
    return max(12, _header_grip_margin(header))


class CompoundTableHeaderView(QHeaderView):
    """Horizontal header that can still resize a column flush with the viewport edge.

    Qt's native grip sits on the section's true right border. When that border is at or
    past the visible edge, the handle is clipped and ScrollPerItem jumps the column away.
    Clicks on the last few pixels of the viewport resize the section under that edge.
    """

    def __init__(self, orientation=Qt.Horizontal, parent=None):
        super().__init__(orientation, parent)
        self.setSectionsMovable(True)
        self.setFirstSectionMovable(False)
        self.setSectionsClickable(True)
        self.setSectionResizeMode(QHeaderView.Interactive)
        self.setStretchLastSection(False)
        self.setMouseTracking(True)
        self._edge_resize_logical = -1
        self._edge_resize_origin_x = 0
        self._edge_resize_origin_size = 0
        self._native_section_resize = False
        self._section_drag_press_x = -1
        self._section_drag_active = False
        self._section_drag_x = 0
        self._section_drag_timer = QTimer(self)
        self._section_drag_timer.setInterval(_HEADER_DRAG_SCROLL_INTERVAL_MS)
        self._section_drag_timer.timeout.connect(self._on_header_drag_scroll_tick)
        self.setStyleSheet(TABLE_HEADER_SECTION_QSS)
        vp = self.viewport()
        if vp is not None:
            vp.setMouseTracking(True)

    def _header_hscroll_bar(self):
        parent = self.parentWidget()
        if parent is not None:
            bar = getattr(parent, "horizontalScrollBar", None)
            if callable(bar):
                found = bar()
                if found is not None:
                    return found
        return self.horizontalScrollBar()

    def _header_drag_scroll_step(self, x: int) -> int:
        """Pixels to scroll this tick; negative is left. Zero if not in the edge zone."""
        vp = self.viewport()
        if vp is None:
            return 0
        width = int(vp.width())
        if width <= 0:
            parent = self.parentWidget()
            pvp = parent.viewport() if parent is not None else None
            width = int(pvp.width()) if pvp is not None else 0
        if width <= 0:
            return 0
        if x >= width:
            overshoot = int(x) - width + 1
            sign = 1
        elif x < 0:
            overshoot = -int(x)
            sign = -1
        else:
            return 0
        step = _HEADER_DRAG_SCROLL_MIN_STEP_PX + max(0, overshoot)
        return sign * max(
            _HEADER_DRAG_SCROLL_MIN_STEP_PX,
            min(_HEADER_DRAG_SCROLL_MAX_STEP_PX, step),
        )

    def _apply_header_drag_scroll(self, step: int) -> None:
        if step == 0:
            return
        bar = self._header_hscroll_bar()
        if bar is None:
            return
        bar.setValue(int(bar.value()) + int(step))

    def _update_section_drag_scroll(self, x: int) -> None:
        self._section_drag_x = int(x)
        step = self._header_drag_scroll_step(x)
        if step == 0:
            self._section_drag_timer.stop()
            return
        self._apply_header_drag_scroll(step)
        if not self._section_drag_timer.isActive():
            self._section_drag_timer.start()

    def _on_header_drag_scroll_tick(self) -> None:
        if not self._section_drag_active:
            self._stop_section_drag_scroll()
            return
        step = self._header_drag_scroll_step(int(self._section_drag_x))
        if step == 0:
            self._section_drag_timer.stop()
            return
        self._apply_header_drag_scroll(step)

    def _stop_section_drag_scroll(self) -> None:
        self._section_drag_active = False
        self._section_drag_press_x = -1
        self._section_drag_timer.stop()

    def _pointer_on_section_resize_handle(self, x: int) -> bool:
        """True when *x* is on a section border that Qt resizes."""
        if self.section_for_viewport_right_grip(int(x)) >= 0:
            return True
        logical = int(self.logicalIndexAt(int(x)))
        if logical < 0 or self.isSectionHidden(logical):
            return False
        if self.sectionResizeMode(logical) != QHeaderView.Interactive:
            return False
        grip = _header_grip_margin(self)
        pos = int(self.sectionViewportPosition(logical))
        size = int(self.sectionSize(logical))
        return int(x) - pos < grip or pos + size - int(x) < grip

    def section_for_viewport_right_grip(self, x: int) -> int:
        """Logical section resized by a click at ``x`` on the viewport's right edge, or -1."""
        vp = self.viewport()
        if vp is None:
            return -1
        vp_w = int(vp.width())
        grip = _header_grip_px(self)
        if vp_w <= 0 or int(x) < vp_w - grip:
            return -1
        logical = int(self.logicalIndexAt(max(0, vp_w - 1)))
        if logical < 0 or self.isSectionHidden(logical):
            return -1
        if self.sectionResizeMode(logical) != QHeaderView.Interactive:
            return -1
        right = int(self.sectionViewportPosition(logical)) + int(self.sectionSize(logical))
        if right < vp_w - grip:
            return -1
        return logical

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            logical = self.section_for_viewport_right_grip(event.pos().x())
            if logical >= 0:
                self._stop_section_drag_scroll()
                self._native_section_resize = False
                self._edge_resize_logical = logical
                self._edge_resize_origin_x = int(event.pos().x())
                self._edge_resize_origin_size = int(self.sectionSize(logical))
                self.setCursor(Qt.SplitHCursor)
                self._note_parent_structure_resize()
                event.accept()
                return
            # A resize that leaves the header clears the split cursor. Remember the
            # gesture here so that departure is not treated as a column move.
            split = self.cursor().shape() == Qt.SplitHCursor
            header_vp = self.viewport()
            if header_vp is not None and header_vp.cursor().shape() == Qt.SplitHCursor:
                split = True
            self._native_section_resize = split or self._pointer_on_section_resize_handle(
                event.pos().x()
            )
            if self._native_section_resize:
                self._note_parent_structure_resize()
            self._section_drag_press_x = int(event.pos().x())
            self._section_drag_active = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical >= 0:
            dx = int(event.pos().x()) - self._edge_resize_origin_x
            new_size = max(int(self.minimumSectionSize()), self._edge_resize_origin_size + dx)
            self.resizeSection(self._edge_resize_logical, new_size)
            self.setCursor(Qt.SplitHCursor)
            event.accept()
            return
        super().mouseMoveEvent(event)
        if self._native_section_resize:
            return
        if (
            event.buttons() & Qt.LeftButton
            and self.sectionsMovable()
            and self.cursor().shape() != Qt.SplitHCursor
        ):
            x = int(event.pos().x())
            if not self._section_drag_active:
                origin = self._section_drag_press_x
                dist = abs(x - origin) if origin >= 0 else 0
                if dist >= int(QApplication.startDragDistance()):
                    self._section_drag_active = True
            if self._section_drag_active:
                self._update_section_drag_scroll(x)
                return
        else:
            self._section_drag_timer.stop()
        hovering_edge = (
            event.buttons() == Qt.NoButton
            and self.section_for_viewport_right_grip(event.pos().x()) >= 0
        )
        if hovering_edge:
            self.setCursor(Qt.SplitHCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_resize = self._native_section_resize or self._edge_resize_logical >= 0
        self._native_section_resize = False
        self._stop_section_drag_scroll()
        if self._edge_resize_logical >= 0:
            self._edge_resize_logical = -1
            self.unsetCursor()
            event.accept()
        else:
            super().mouseReleaseEvent(event)
        if was_resize:
            self._finish_parent_structure_resize()

    def _note_parent_structure_resize(self) -> None:
        parent = self.parentWidget()
        note = getattr(parent, "note_structure_resize_anchor", None)
        if callable(note):
            note()

    def _finish_parent_structure_resize(self) -> None:
        parent = self.parentWidget()
        finish = getattr(parent, "finish_user_structure_resize", None)
        if callable(finish):
            finish()

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical < 0 and not self._native_section_resize:
            self.unsetCursor()
        super().leaveEvent(event)


class CompoundTableRowHeaderView(QHeaderView):
    """Vertical header that highlights rows selected in the entry-selection store.

    Entry selection is not held by Qt's selection model, so Qt's own section highlight
    never fires for it; ``is_row_selected`` (view row -> bool) supplies the state instead.
    """

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        # QTableView only configures its default header; a replacement must opt in.
        self.setSectionsClickable(True)
        self.setHighlightSections(True)
        self.is_row_selected: Callable[[int], bool] | None = None
        self._row_resize = False

    def _pointer_on_row_resize_handle(self, y: int) -> bool:
        """True when *y* is on a row border that Qt resizes."""
        logical = int(self.logicalIndexAt(int(y)))
        if logical < 0 or self.isSectionHidden(logical):
            return False
        grip = _header_grip_margin(self)
        pos = int(self.sectionViewportPosition(logical))
        size = int(self.sectionSize(logical))
        if int(y) - pos < grip:
            return int(self.visualIndex(logical)) > 0
        return pos + size - int(y) < grip

    def mousePressEvent(self, event) -> None:  # noqa: N802
        split = self.cursor().shape() == Qt.SplitVCursor
        header_vp = self.viewport()
        if header_vp is not None and header_vp.cursor().shape() == Qt.SplitVCursor:
            split = True
        self._row_resize = bool(
            event.button() == Qt.LeftButton
            and (split or self._pointer_on_row_resize_handle(event.pos().y()))
        )
        if self._row_resize:
            parent = self.parentWidget()
            note = getattr(parent, "note_structure_resize_anchor", None)
            if callable(note):
                note()
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        was_resize = self._row_resize
        self._row_resize = False
        super().mouseReleaseEvent(event)
        if was_resize:
            parent = self.parentWidget()
            finish = getattr(parent, "finish_user_structure_resize", None)
            if callable(finish):
                finish()

    def paintSection(self, painter, rect, logical_index) -> None:  # noqa: N802
        super().paintSection(painter, rect, logical_index)
        is_selected = self.is_row_selected
        if is_selected is None or not is_selected(int(logical_index)):
            return
        fill = QColor(self.palette().color(QPalette.Highlight))
        fill.setAlpha(_ROW_HEADER_HIGHLIGHT_ALPHA)
        painter.save()
        painter.fillRect(rect, fill)
        painter.restore()


class CompoundTableView(QTableView):
    """
    QTableView pre-wired for ``CompoundTableModel`` + structure delegate.
    Call ``set_compound_model`` after construction.

    With a :class:`~molmanager.ui.table_row_selection.TableRowSelectionController`
    installed (``set_row_selection_controller``), row-header clicks, select-all, and
    selection-clearing cell input drive entry selection instead of Qt's selection model.
    """

    structure_depict_resized = pyqtSignal(int, int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_selection: TableRowSelectionController | None = None
        self._row_number_width_model = None
        self._compound_model = None
        self._structure_column_min_width = structure_column_minimum_width()
        self._axis_resize: dict | None = None
        self._pending_resize_anchor: dict[str, int] | None = None
        self._applying_structure_scale = False
        self.setVerticalHeader(CompoundTableRowHeaderView(self))
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectItems)
        self.setSelectionMode(QTableView.ExtendedSelection)
        # F2 or typing edits a Structure cell. Double-click does not.
        self.setEditTriggers(QAbstractItemView.EditKeyPressed | QAbstractItemView.AnyKeyPressed)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.verticalHeader().setDefaultSectionSize(structure_row_default_height())
        self.verticalHeader().setSectionsMovable(True)
        self.verticalHeader().setDefaultAlignment(Qt.AlignCenter)
        self.verticalHeader().setStyleSheet(TABLE_HEADER_SECTION_QSS)
        hh = CompoundTableHeaderView(Qt.Horizontal, self)
        self.setHorizontalHeader(hh)
        # QTableView connects sectionPressed → _q_selectColumn, which selects the
        # column from row 0 and scrolls there before our click handler runs.
        with suppress(TypeError):
            hh.sectionPressed.disconnect()
        self.setSortingEnabled(False)
        hh.sectionResized.connect(self._on_horizontal_section_resized)
        self.verticalHeader().sectionResized.connect(self._on_vertical_section_resized)

    def set_row_selection_controller(self, controller: TableRowSelectionController) -> None:
        """Route row-header, select-all, and cell-clear input to *controller*."""
        self._row_selection = controller
        vh = self.verticalHeader()
        # QTableView wires row-header press/drag to _q_selectRow (Qt row selection).
        with suppress(TypeError):
            vh.sectionPressed.disconnect()
        with suppress(TypeError):
            vh.sectionEntered.disconnect()
        vh.sectionPressed.connect(self._on_row_header_pressed)
        if isinstance(vh, CompoundTableRowHeaderView):
            vh.is_row_selected = controller.is_view_row_selected

    def row_selection_controller(self) -> TableRowSelectionController | None:
        return self._row_selection

    def _on_row_header_pressed(self, logical_row: int) -> None:
        if self._row_selection is not None and logical_row >= 0:
            self._row_selection.press_row(logical_row, QApplication.keyboardModifiers())

    def selectAll(self) -> None:  # noqa: N802
        if self._row_selection is None:
            super().selectAll()
            return
        self._row_selection.select_all()

    def selectionCommand(self, index, event=None):  # noqa: N802
        """Keep entry selection in step with Qt's cell-selection decisions for user input.

        A right-click inside a selected entry keeps everything (context menu on the
        selection); any user input for which Qt clears its selection clears entries too.
        """
        controller = self._row_selection
        if controller is None or event is None or event.type() not in _USER_SELECTION_EVENTS:
            return super().selectionCommand(index, event)
        if (
            event.type() == QEvent.MouseButtonPress
            and event.button() == Qt.RightButton
            and index.isValid()
            and controller.is_view_row_selected(index.row())
        ):
            return QItemSelectionModel.NoUpdate
        flags = super().selectionCommand(index, event)
        if flags & QItemSelectionModel.Clear:
            controller.clear_for_cell_input()
        return flags

    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Type into a Structure cell, but let Delete and Backspace stay table shortcuts."""
        if event.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            triggers = self.editTriggers()
            self.setEditTriggers(triggers & ~QAbstractItemView.AnyKeyPressed)
            try:
                super().keyPressEvent(event)
            finally:
                self.setEditTriggers(triggers)
            return
        super().keyPressEvent(event)

    def apply_table_font(self, font: QFont) -> None:
        """Set the table font and grow or shrink header bars to match."""
        self.setFont(font)
        apply_header_font(self.horizontalHeader(), font)
        apply_header_font(self.verticalHeader(), font)
        hh = self.horizontalHeader()
        corner = self.findChild(QAbstractButton)
        if corner is not None:
            corner.setFont(font)
            if hh is not None:
                corner.setFixedHeight(int(hh.height()))
            corner.update()
        self.updateGeometries()
        vp = self.viewport()
        if vp is not None:
            vp.update()

    def refresh_theme(self) -> None:
        """Keep header chrome on the current application palette."""
        app = QApplication.instance()
        pal = app.palette() if app is not None else self.palette()
        self.setPalette(pal)
        apply_table_header_theme(self.horizontalHeader(), pal)
        apply_table_header_theme(self.verticalHeader(), pal)
        corner = self.findChild(QAbstractButton)
        if corner is not None:
            corner.setPalette(pal)
            corner.update()
        vp = self.viewport()
        if vp is not None:
            vp.setPalette(pal)
            vp.update()

    def updateGeometries(self) -> None:  # noqa: N802
        super().updateGeometries()
        self._extend_horizontal_scroll_for_resize_grip()

    def _extend_horizontal_scroll_for_resize_grip(self) -> None:
        """Keep a few pixels of scroll past the last section so its right grip stays on-screen."""
        hh = self.horizontalHeader()
        bar = self.horizontalScrollBar()
        vp = self.viewport()
        if hh is None or bar is None or vp is None:
            return
        width = int(vp.width())
        length = int(hh.length())
        if width <= 0 or length <= 0:
            return
        grip = _header_grip_px(hh)
        needed_max = max(int(bar.maximum()), length - width + grip)
        if needed_max != int(bar.maximum()):
            bar.setRange(int(bar.minimum()), needed_max)

    def structure_column_minimum_width(self) -> int:
        return self._structure_column_min_width

    def _column_is_structure_sized(self, logical_index: int) -> bool:
        """True for Structure and 2D pixmap columns that share its depiction size."""
        if logical_index == _STRUCTURE_COL:
            return True
        model = self._compound_model
        if model is None:
            return False
        headers = getattr(model, "_headers", ())
        if logical_index < 0 or logical_index >= len(headers):
            return False
        return bool(model.is_pixmap_data_column(headers[logical_index]))

    def set_structure_column_minimum_width(self, width: int) -> None:
        """Keep Structure and 2D pixmap columns at least wide enough for depictions."""
        w = max(1, int(width))
        if w == self._structure_column_min_width:
            return
        self._structure_column_min_width = w
        hh = self.horizontalHeader()
        hh.blockSignals(True)
        try:
            model = self._compound_model
            n = model.columnCount() if model is not None else 0
            if n <= 0:
                n = 2
            for col in range(n):
                if not self._column_is_structure_sized(col):
                    continue
                if self.columnWidth(col) < w:
                    self.setColumnWidth(col, w)
        finally:
            hh.blockSignals(False)

    def note_structure_resize_anchor(self) -> None:
        """Remember the viewport before a column or row border drag moves it."""
        self._pending_resize_anchor = self._viewport_scroll_anchor()

    def finish_user_structure_resize(self) -> None:
        """Save a depiction size chosen by dragging a column or row border."""
        drag = self._axis_resize
        self._axis_resize = None
        self._pending_resize_anchor = None
        self._set_depiction_preview(False, 0, 0)
        if not drag:
            viewport = self.viewport()
            if viewport is not None:
                viewport.update()
            return
        width = structure_depict_width()
        height = structure_depict_height()
        anchor = drag["anchor"]
        if width != int(drag["origin_w"]) or height != int(drag["origin_h"]):
            self.structure_depict_resized.emit(int(width), int(height))
            self._restore_viewport_scroll_anchor(anchor)
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def _on_horizontal_section_resized(
        self, logical_index: int, old_size: int, new_size: int
    ) -> None:
        if self._applying_structure_scale:
            return
        header = self.horizontalHeader()
        user_drag = isinstance(header, CompoundTableHeaderView) and (
            header._native_section_resize or header._edge_resize_logical >= 0
        )
        if user_drag and self._column_is_structure_sized(int(logical_index)):
            self._resize_structures_from_axis("x", int(logical_index), int(old_size), int(new_size))
            return
        if not self._column_is_structure_sized(logical_index):
            return
        min_w = self._structure_column_min_width
        if new_size >= min_w:
            return
        hh = self.horizontalHeader()
        hh.blockSignals(True)
        try:
            self.setColumnWidth(logical_index, min_w)
        finally:
            hh.blockSignals(False)

    def _on_vertical_section_resized(
        self, logical_index: int, old_size: int, new_size: int
    ) -> None:
        if self._applying_structure_scale:
            return
        header = self.verticalHeader()
        if not isinstance(header, CompoundTableRowHeaderView) or not header._row_resize:
            return
        self._resize_structures_from_axis("y", int(logical_index), int(old_size), int(new_size))

    def _resize_structures_from_axis(
        self, axis: str, logical: int, old_size: int, new_size: int
    ) -> None:
        """Scale every structure depiction from a column-width or row-height drag."""
        drag = self._axis_resize
        if drag is None or drag.get("axis") != axis or int(drag.get("logical", -1)) != int(logical):
            self._begin_axis_resize(axis, logical, old_size)
            drag = self._axis_resize
        if drag is None:
            return
        delta = int(new_size) - int(drag["origin_span"])
        dx, dy = (delta, 0) if axis == "x" else (0, delta)
        width, height = structure_depict_size_for_cell_resize(
            int(drag["origin_w"]),
            int(drag["origin_h"]),
            int(drag["cell_w"]),
            int(drag["cell_h"]),
            dx,
            dy,
        )
        if width == structure_depict_width() and height == structure_depict_height():
            return
        self._apply_live_structure_size(
            width,
            height,
            origin_w=int(drag["origin_w"]),
            columns=drag["columns"],
            zoomed=bool(drag["zoomed_layout"]),
            anchor=drag["anchor"],
            row_state=drag,
            skip_column=int(logical) if axis == "x" else None,
            skip_row=int(logical) if axis == "y" else None,
        )

    def _begin_axis_resize(self, axis: str, logical: int, origin_span: int) -> None:
        columns = {col: int(self.columnWidth(col)) for col in self._structure_logical_columns()}
        if axis == "x" and int(logical) not in columns:
            return
        origin_w = structure_depict_width()
        origin_h = structure_depict_height()
        if axis == "x":
            cell_w = int(origin_span)
            row = self.rowAt(0)
            cell_h = int(self.rowHeight(row)) if row >= 0 else structure_row_default_height()
        else:
            cell_h = int(origin_span)
            cell_w = int(columns.get(_STRUCTURE_COL, self.columnWidth(_STRUCTURE_COL)))
        anchor = self._pending_resize_anchor or self._viewport_scroll_anchor()
        self._pending_resize_anchor = None
        self._remember_pixmap_column_source_size(origin_w, origin_h)
        zoomed_floor = structure_column_minimum_width(zoomed=True)
        self._axis_resize = {
            "axis": axis,
            "logical": int(logical),
            "origin_span": int(origin_span),
            "origin_w": origin_w,
            "origin_h": origin_h,
            "cell_w": cell_w,
            "cell_h": cell_h,
            "columns": columns,
            "zoomed_layout": int(self._structure_column_min_width) >= int(zoomed_floor),
            "zoomed_rows": set(),
            "origin_row_heights": {},
            "anchor": anchor,
        }
        self._set_depiction_preview(True, origin_w, origin_h)

    def _apply_live_structure_size(
        self,
        width: int,
        height: int,
        *,
        origin_w: int,
        columns: dict[int, int],
        zoomed: bool,
        anchor: dict[str, int],
        row_state: dict,
        skip_column: int | None = None,
        skip_row: int | None = None,
    ) -> None:
        """Apply one shared depiction scale to structure columns and row heights."""
        self._applying_structure_scale = True
        try:
            set_structure_depict_size(int(width), int(height), persist=False)
            min_w = structure_column_minimum_width(zoomed=bool(zoomed))
            self.set_structure_column_minimum_width(min_w)
            scale = int(width) / max(1, int(origin_w))
            hh = self.horizontalHeader()
            if hh is not None:
                hh.blockSignals(True)
            try:
                for logical, origin in columns.items():
                    if skip_column is not None and int(logical) == int(skip_column):
                        continue
                    target = max(int(min_w), int(round(int(origin) * scale)))
                    if int(self.columnWidth(int(logical))) != target:
                        self.setColumnWidth(int(logical), target)
            finally:
                if hh is not None:
                    hh.blockSignals(False)
            self._apply_depict_row_heights(visible_only=True, state=row_state, skip_row=skip_row)
        finally:
            self._applying_structure_scale = False
        self._restore_viewport_scroll_anchor(anchor)
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def setModel(self, model) -> None:  # noqa: N802
        """Keep the row-number column width tied to whichever model the view shows."""
        super().setModel(model)
        # Connect after the view so this runs once the row count has already landed.
        self._bind_row_number_column_width(model)
        self.sync_row_number_column_width()

    def _bind_row_number_column_width(self, model) -> None:
        previous = self._row_number_width_model
        if previous is model:
            return
        if previous is not None:
            for signal in (previous.modelReset, previous.rowsInserted, previous.rowsRemoved):
                with suppress(TypeError, RuntimeError):
                    signal.disconnect(self.sync_row_number_column_width)
        self._row_number_width_model = model
        if model is None:
            return
        model.modelReset.connect(self.sync_row_number_column_width)
        model.rowsInserted.connect(self.sync_row_number_column_width)
        model.rowsRemoved.connect(self.sync_row_number_column_width)

    def sync_row_number_column_width(self, *_args) -> None:
        """Size the row-number column for the current row count.

        The width is fixed from the font while the table is still empty (wide enough
        for two digits). A file load then inserts every row at once. Updating here,
        in the same turn as that insert, means the first paint already has the final
        width instead of snapping wider after the table is shown.
        """
        vh = self.verticalHeader()
        if vh is None:
            return
        extent = header_bar_extent_for_font(vh, vh.font())
        if int(vh.minimumWidth()) == extent and int(vh.maximumWidth()) == extent:
            return
        vh.setFixedWidth(extent)
        self.updateGeometries()

    def set_compound_model(self, model) -> None:
        self._compound_model = model
        self.setModel(model)
        self.setItemDelegateForColumn(_STRUCTURE_COL, StructureDelegate(self))
        if model.columnCount() > 0:
            self.setColumnHidden(0, True)

    def compound_model(self):
        return self._compound_model

    def _viewport_scroll_anchor(self) -> dict[str, int]:
        """First visible row and column, and where each sits in the viewport.

        Depiction resize changes every row height and every structure column width.
        A pixel scroll offset then points at different cells, so the table jumps.
        Putting these sections back at the same viewport position keeps the view still.
        """
        anchor: dict[str, int] = {}
        vh = self.verticalHeader()
        row = self.rowAt(0)
        if vh is not None and row >= 0:
            anchor["row"] = int(row)
            anchor["row_y"] = int(vh.sectionViewportPosition(row))
        hh = self.horizontalHeader()
        if hh is None:
            return anchor
        for visual in range(int(hh.count())):
            logical = int(hh.logicalIndex(visual))
            if logical < 0 or hh.isSectionHidden(logical):
                continue
            left = int(hh.sectionViewportPosition(logical))
            if left + int(hh.sectionSize(logical)) > 0:
                anchor["col"] = logical
                anchor["col_x"] = left
                break
        return anchor

    def _restore_viewport_scroll_anchor(self, anchor: dict[str, int]) -> None:
        """Scroll so the sections in *anchor* sit where they did when the drag started."""
        row = anchor.get("row")
        vh = self.verticalHeader()
        if row is not None and vh is not None and int(row) >= 0:
            delta = int(vh.sectionViewportPosition(int(row))) - int(anchor["row_y"])
            if delta:
                bar = self.verticalScrollBar()
                bar.setValue(int(bar.value()) + delta)
        col = anchor.get("col")
        hh = self.horizontalHeader()
        if col is not None and hh is not None and not hh.isSectionHidden(int(col)):
            delta = int(hh.sectionViewportPosition(int(col))) - int(anchor["col_x"])
            if delta:
                bar = self.horizontalScrollBar()
                bar.setValue(int(bar.value()) + delta)

    def _remember_pixmap_column_source_size(self, width: int, height: int) -> None:
        """Record the depiction size at the start of a drag when a column has none.

        A later drag keeps that record so the preview scales from the last sharp
        drawing. Committing the size replaces it with the size just drawn.
        """
        model = self._compound_model
        note = getattr(model, "note_pixmap_column_source_size", None)
        headers = getattr(model, "pixmap_data_column_headers", None)
        if not callable(note) or not callable(headers):
            return
        for header in headers():
            note(str(header), int(width), int(height), replace=False)

    def _structure_logical_columns(self) -> list[int]:
        model = getattr(self, "_compound_model", None)
        if model is not None:
            count = int(model.columnCount())
        elif self.model() is not None:
            count = int(self.model().columnCount())
        else:
            count = 0
        return [col for col in range(count) if self._column_is_structure_sized(col)]

    def _apply_depict_row_heights(
        self, *, visible_only: bool, state: dict, skip_row: int | None = None
    ) -> None:
        model = self.model()
        header = self.verticalHeader()
        if model is None or header is None:
            return
        count = int(model.rowCount())
        if count <= 0:
            return
        if visible_only:
            top = self.rowAt(0)
            if top < 0:
                return
            viewport = self.viewport()
            view_h = int(viewport.height()) if viewport is not None else 0
            bottom = self.rowAt(max(0, view_h - 1))
            if bottom < 0:
                bottom = count - 1
            rows = range(max(0, int(top)), min(count - 1, int(bottom)) + 1)
        else:
            rows = range(count)
        base = structure_row_default_height()
        zoom_h = int(structure_depict_height()) * 2
        threshold = (
            int(state["origin_h"]) * _ZOOMED_ROW_HEIGHT_NUMERATOR // _ZOOMED_ROW_HEIGHT_DENOMINATOR
        )
        heights: dict[int, int] = state["origin_row_heights"]
        zoomed: set[int] = state["zoomed_rows"]
        # Read heights before changing the default. Qt applies a new default to every
        # row that has not been resized on its own, which would hide the original.
        pending: list[int] = []
        for row in rows:
            if row not in heights:
                current = int(header.sectionSize(row))
                heights[row] = current
                if current >= threshold:
                    zoomed.add(row)
            pending.append(row)
        header.blockSignals(True)
        try:
            header.setDefaultSectionSize(base)
            for row in pending:
                if skip_row is not None and int(row) == int(skip_row):
                    continue
                target = zoom_h if row in zoomed else base
                if int(header.sectionSize(row)) != target:
                    header.resizeSection(row, target)
        finally:
            header.blockSignals(False)

    def _set_depiction_preview(self, active: bool, origin_w: int, origin_h: int) -> None:
        delegates: list = []
        column_delegate = self.itemDelegateForColumn(_STRUCTURE_COL)
        if isinstance(column_delegate, StructureDelegate):
            delegates.append(column_delegate)
        base = self.itemDelegate()
        extra = getattr(base, "depiction_delegates", None)
        if callable(extra):
            delegates.extend(extra())
        for delegate in delegates:
            setter = getattr(delegate, "set_depiction_preview", None)
            if callable(setter):
                setter(bool(active), int(origin_w), int(origin_h))
