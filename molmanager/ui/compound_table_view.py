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

from PyQt5.QtCore import QEvent, QItemSelectionModel, QPoint, QRect, QSize, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPalette, QPen, QPixmap
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
    QWidget,
    QWIDGETSIZE_MAX,
)

from ..table.structure_depiction_layout import (
    STRUCTURE_COLUMN_HORIZONTAL_PADDING,
    set_structure_depict_size,
    structure_column_minimum_width,
    structure_column_width_for_depict_scale,
    structure_depict_height,
    structure_depict_size_for_corner_drag,
    structure_depict_width,
    structure_row_default_height,
)

# Hit target at the bottom-right of a structure column. Ticks are drawn inside it.
_STRUCTURE_CORNER_GRIP_PX = 16
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


class StructureColumnCornerGrip(QWidget):
    """Transparent drag handle at the bottom-right of one structure column."""

    def __init__(self, view: "CompoundTableView", logical_column: int) -> None:
        super().__init__(view.viewport())
        self._view = view
        self._logical = int(logical_column)
        self._hovered = False
        self.setFixedSize(_STRUCTURE_CORNER_GRIP_PX, _STRUCTURE_CORNER_GRIP_PX)
        self.setCursor(Qt.SizeFDiagCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoFillBackground(False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background: transparent;")
        self.setToolTip("Drag to resize structure depictions")
        self.hide()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        right = self.width() - 2
        bottom = self.height() - 2
        dark = QColor(40, 40, 40) if self._hovered else QColor(70, 70, 70)
        for pen in (QPen(QColor(255, 255, 255), 3), QPen(dark, 1.4)):
            painter.setPen(pen)
            for inset in (4, 8, 12):
                painter.drawLine(right - inset, bottom, right, bottom - inset)
        painter.end()

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton:
            self.grabMouse()
            self._view.begin_structure_depict_resize(self._logical, event.globalPos())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._view.structure_depict_resize_active():
            self._view.update_structure_depict_resize(event.globalPos())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._view.structure_depict_resize_active():
            if QWidget.mouseGrabber() is self:
                self.releaseMouse()
            self._view.finish_structure_depict_resize()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key_Escape and self._view.structure_depict_resize_active():
            self._view.cancel_structure_depict_resize()
            event.accept()
            return
        super().keyPressEvent(event)


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
        """While a corner drag is active, draw cached pictures at the live depiction size."""
        self._preview_active = bool(active)
        self._preview_origin_w = int(origin_width)
        self._preview_origin_h = int(origin_height)

    def _pixmap_for_cell(self, pix: QPixmap) -> QPixmap:
        if not self._preview_active:
            return pix
        return scaled_structure_pixmap(
            pix,
            self._preview_origin_w,
            self._preview_origin_h,
            structure_depict_width(),
            structure_depict_height(),
        )

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
            pix = self._pixmap_for_cell(pix)
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
            pix = self._pixmap_for_cell(pix)
            return QSize(max(sh.width(), pix.width()), max(sh.height(), pix.height()))
        return QSize(structure_depict_width(), max(sh.height(), structure_depict_height()))


def _header_grip_px(header: QHeaderView) -> int:
    """Pixel slop for a column resize grip, floored so the viewport edge stays hittable."""
    style = header.style()
    pm = 4
    if style is not None:
        raw = int(style.pixelMetric(QStyle.PM_HeaderGripMargin, None, header))
        if raw > 0:
            pm = raw
    return max(12, pm)


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
                self._edge_resize_logical = logical
                self._edge_resize_origin_x = int(event.pos().x())
                self._edge_resize_origin_size = int(self.sectionSize(logical))
                self.setCursor(Qt.SplitHCursor)
                event.accept()
                return
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
        self._stop_section_drag_scroll()
        if self._edge_resize_logical >= 0:
            self._edge_resize_logical = -1
            self.unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._edge_resize_logical < 0:
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
        self._corner_grips: dict[int, StructureColumnCornerGrip] = {}
        self._corner_grip_model = None
        self._positioning_corner_grips = False
        self._depict_resize: dict | None = None
        self.setVerticalHeader(CompoundTableRowHeaderView(self))
        self.setAlternatingRowColors(True)
        self.setSelectionBehavior(QTableView.SelectItems)
        self.setSelectionMode(QTableView.ExtendedSelection)
        # F2 or typing edits a Structure cell. Double-click stays a depiction zoom.
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
        if event.key() == Qt.Key_Escape and self._depict_resize is not None:
            self.cancel_structure_depict_resize()
            event.accept()
            return
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
        # QTableView construction calls this before the grip state exists.
        if getattr(self, "_corner_grips", None) is not None:
            self._position_structure_corner_grips()

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

    def _on_horizontal_section_resized(
        self, logical_index: int, _old_size: int, new_size: int
    ) -> None:
        if getattr(self, "_corner_grips", None) is None:
            return
        if not self._column_is_structure_sized(logical_index):
            self._position_structure_corner_grips()
            return
        min_w = self._structure_column_min_width
        if new_size >= min_w:
            self._position_structure_corner_grips()
            return
        hh = self.horizontalHeader()
        hh.blockSignals(True)
        try:
            self.setColumnWidth(logical_index, min_w)
        finally:
            hh.blockSignals(False)
        self._position_structure_corner_grips()

    def setModel(self, model) -> None:  # noqa: N802
        """Keep the row-number column width tied to whichever model the view shows."""
        super().setModel(model)
        # Connect after the view so this runs once the row count has already landed.
        self._bind_row_number_column_width(model)
        self.sync_row_number_column_width()
        self._bind_structure_corner_grips(model)

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

    def structure_depict_resize_active(self) -> bool:
        """True while the user is dragging a structure-column corner grip."""
        return self._depict_resize is not None

    def structure_corner_grip(self, logical_column: int) -> StructureColumnCornerGrip | None:
        """The corner grip for *logical_column*, once the view has positioned it."""
        return self._corner_grips.get(int(logical_column))

    def structure_column_corner_grip_rect(self, logical_column: int) -> QRect | None:
        """Viewport rectangle of the bottom-right grip, or ``None`` when it is off-screen.

        The grip sits on the column's right edge and on the bottom of the visible rows
        (the last row, or the bottom of the viewport when more rows continue below).
        """
        logical = int(logical_column)
        if not self._column_is_structure_sized(logical):
            return None
        header = self.horizontalHeader()
        viewport = self.viewport()
        model = self.model()
        if header is None or viewport is None or model is None or header.isSectionHidden(logical):
            return None
        if int(model.rowCount()) <= 0:
            return None
        left = int(header.sectionViewportPosition(logical))
        width = int(header.sectionSize(logical))
        right = left + width
        view_w = int(viewport.width())
        view_h = int(viewport.height())
        if right > view_w or right < _STRUCTURE_CORNER_GRIP_PX or left >= view_w:
            return None
        last = int(model.rowCount()) - 1
        content_bottom = int(self.rowViewportPosition(last)) + int(self.rowHeight(last))
        if content_bottom <= 0:
            return None
        bottom = min(content_bottom, view_h)
        if bottom < _STRUCTURE_CORNER_GRIP_PX:
            return None
        return QRect(
            right - _STRUCTURE_CORNER_GRIP_PX,
            bottom - _STRUCTURE_CORNER_GRIP_PX,
            _STRUCTURE_CORNER_GRIP_PX,
            _STRUCTURE_CORNER_GRIP_PX,
        )

    def begin_structure_depict_resize(self, logical_column: int, global_pos: QPoint) -> None:
        """Start a corner drag that resizes every structure depiction."""
        if self._depict_resize is not None:
            return
        logical = int(logical_column)
        if not self._column_is_structure_sized(logical):
            return
        columns: dict[int, dict[str, int]] = {}
        for col in self._structure_logical_columns():
            content = self._structure_column_content_width(col)
            actual = int(self.columnWidth(col))
            fitted = max(actual, content + STRUCTURE_COLUMN_HORIZONTAL_PADDING)
            columns[col] = {"actual": actual, "fitted": fitted, "content": content}
        if logical not in columns:
            return
        origin_w = structure_depict_width()
        origin_h = structure_depict_height()
        zoomed_floor = structure_column_minimum_width(zoomed=True)
        self._depict_resize = {
            "logical": logical,
            "origin": QPoint(global_pos),
            "origin_w": origin_w,
            "origin_h": origin_h,
            "origin_min": int(self._structure_column_min_width),
            "zoomed_layout": int(self._structure_column_min_width) >= int(zoomed_floor),
            "columns": columns,
            "content": columns[logical]["content"],
            "zoomed_rows": set(),
            "origin_row_heights": {},
        }
        self._set_depiction_preview(True, origin_w, origin_h)

    def update_structure_depict_resize(self, global_pos: QPoint) -> None:
        """Move the live depiction size with the pointer."""
        state = self._depict_resize
        if state is None:
            return
        delta = QPoint(global_pos) - state["origin"]
        width, height = structure_depict_size_for_corner_drag(
            state["origin_w"],
            state["origin_h"],
            state["content"],
            int(delta.x()),
            int(delta.y()),
        )
        if width == structure_depict_width() and height == structure_depict_height():
            return
        set_structure_depict_size(width, height, persist=False)
        min_w = structure_column_minimum_width(zoomed=bool(state["zoomed_layout"]))
        self.set_structure_column_minimum_width(min_w)
        for logical, col in state["columns"].items():
            target = structure_column_width_for_depict_scale(
                col["fitted"],
                col["content"],
                state["origin_w"],
                width,
            )
            target = max(int(target), int(min_w))
            if int(self.columnWidth(logical)) != target:
                self.setColumnWidth(logical, target)
        self._apply_depict_row_heights(visible_only=True)
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def finish_structure_depict_resize(self) -> None:
        """Keep the dragged size and ask the window to save and redraw it."""
        state = self._depict_resize
        if state is None:
            return
        width = structure_depict_width()
        height = structure_depict_height()
        changed = width != int(state["origin_w"]) or height != int(state["origin_h"])
        if changed:
            # Rows that still use the default pick up the new height here. Rows already
            # resized (a zoomed row, or one under the pointer) are set from the drag.
            self._apply_depict_row_heights(visible_only=True)
        self._depict_resize = None
        self._release_corner_grip_mouse()
        self._set_depiction_preview(False, 0, 0)
        self._position_structure_corner_grips()
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()
        if changed:
            self.structure_depict_resized.emit(int(width), int(height))

    def cancel_structure_depict_resize(self) -> None:
        """Restore the depiction size from before this corner drag."""
        state = self._depict_resize
        if state is None:
            return
        self._depict_resize = None
        self._release_corner_grip_mouse()
        set_structure_depict_size(int(state["origin_w"]), int(state["origin_h"]), persist=False)
        self._set_depiction_preview(False, 0, 0)
        self.set_structure_column_minimum_width(int(state["origin_min"]))
        header = self.horizontalHeader()
        if header is not None:
            header.blockSignals(True)
        try:
            for logical, col in state["columns"].items():
                self.setColumnWidth(int(logical), int(col["actual"]))
        finally:
            if header is not None:
                header.blockSignals(False)
        self._restore_depict_row_heights(state)
        self._position_structure_corner_grips()
        viewport = self.viewport()
        if viewport is not None:
            viewport.update()

    def _structure_logical_columns(self) -> list[int]:
        model = getattr(self, "_compound_model", None)
        if model is not None:
            count = int(model.columnCount())
        elif self.model() is not None:
            count = int(self.model().columnCount())
        else:
            count = 0
        return [col for col in range(count) if self._column_is_structure_sized(col)]

    def _structure_column_content_width(self, logical: int) -> int:
        """Picture width that a corner drag of this column should track."""
        depict_w = int(structure_depict_width())
        sampled = self._sampled_pixmap_width(logical)
        zoomed = int(self._structure_column_min_width) >= int(
            structure_column_minimum_width(zoomed=True)
        )
        if int(logical) == _STRUCTURE_COL and zoomed:
            return max(depict_w * 2, sampled)
        if sampled > 0:
            return sampled
        return depict_w

    def _sampled_pixmap_width(self, logical: int) -> int:
        model = self.model()
        if model is None:
            return 0
        count = int(model.rowCount())
        if count <= 0:
            return 0
        top = self.rowAt(0)
        if top < 0:
            top = 0
        viewport = self.viewport()
        view_h = int(viewport.height()) if viewport is not None else 0
        bottom = self.rowAt(max(0, view_h - 1))
        if bottom < 0:
            bottom = min(count - 1, top + 40)
        bottom = min(count - 1, max(top, bottom))
        best = 0
        for row in range(top, bottom + 1):
            pix = model.index(row, int(logical)).data(Qt.DecorationRole)
            if isinstance(pix, QPixmap) and not pix.isNull():
                best = max(best, int(pix.width()))
        return best

    def _apply_depict_row_heights(self, *, visible_only: bool) -> None:
        state = self._depict_resize
        model = self.model()
        header = self.verticalHeader()
        if state is None or model is None or header is None:
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
                target = zoom_h if row in zoomed else base
                if int(header.sectionSize(row)) != target:
                    header.resizeSection(row, target)
        finally:
            header.blockSignals(False)

    def _restore_depict_row_heights(self, state: dict) -> None:
        header = self.verticalHeader()
        if header is None:
            return
        header.blockSignals(True)
        try:
            header.setDefaultSectionSize(structure_row_default_height())
            for row, height in state["origin_row_heights"].items():
                if int(header.sectionSize(int(row))) != int(height):
                    header.resizeSection(int(row), int(height))
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

    def _release_corner_grip_mouse(self) -> None:
        grabber = QWidget.mouseGrabber()
        if grabber is not None and grabber in self._corner_grips.values():
            grabber.releaseMouse()

    def _bind_structure_corner_grips(self, model) -> None:
        previous = self._corner_grip_model
        if previous is model:
            return
        if previous is not None:
            for signal in (
                previous.modelReset,
                previous.rowsInserted,
                previous.rowsRemoved,
                previous.columnsInserted,
                previous.layoutChanged,
            ):
                with suppress(TypeError, RuntimeError):
                    signal.disconnect(self._position_structure_corner_grips)
        self._corner_grip_model = model
        if model is None:
            return
        model.modelReset.connect(self._position_structure_corner_grips)
        model.rowsInserted.connect(self._position_structure_corner_grips)
        model.rowsRemoved.connect(self._position_structure_corner_grips)
        model.columnsInserted.connect(self._position_structure_corner_grips)
        model.layoutChanged.connect(self._position_structure_corner_grips)
        self._position_structure_corner_grips()

    def _position_structure_corner_grips(self, *_args) -> None:
        if self._positioning_corner_grips:
            return
        self._positioning_corner_grips = True
        try:
            wanted = set(self._structure_logical_columns())
            for logical in list(self._corner_grips):
                if logical not in wanted:
                    grip = self._corner_grips.pop(logical)
                    grip.hide()
                    grip.deleteLater()
            viewport = self.viewport()
            if viewport is None:
                return
            for logical in wanted:
                grip = self._corner_grips.get(logical)
                if grip is None:
                    grip = StructureColumnCornerGrip(self, logical)
                    self._corner_grips[logical] = grip
                rect = self.structure_column_corner_grip_rect(logical)
                if rect is None:
                    grip.hide()
                    continue
                grip.setGeometry(rect)
                grip.show()
                grip.raise_()
        finally:
            self._positioning_corner_grips = False
