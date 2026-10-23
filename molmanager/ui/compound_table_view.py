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

from PyQt5.QtCore import QEvent, QItemSelectionModel, QRect, QSize, Qt, QTimer
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
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_width,
    structure_row_default_height,
)

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


class StructureDelegate(QStyledItemDelegate):
    """Paints cached structure pixmap or a neutral placeholder."""

    def __init__(self, parent=None, compound_model=None):
        super().__init__(parent)
        self._cell_background: QColor | None = QColor(255, 255, 255)
        self._compound_model = compound_model

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

    def __init__(self, parent=None):
        super().__init__(parent)
        self._row_selection: TableRowSelectionController | None = None
        self._row_number_width_model = None
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
        self._compound_model = None
        self._structure_column_min_width = structure_column_minimum_width()
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

    def _on_horizontal_section_resized(
        self, logical_index: int, _old_size: int, new_size: int
    ) -> None:
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
