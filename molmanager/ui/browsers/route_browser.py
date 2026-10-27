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

"""Browse AiZynthFinder routes as a tree of precursor cards."""

from __future__ import annotations

from urllib.parse import urlencode

from PyQt5.QtCore import QEvent, QPoint, QPointF, QRectF, Qt, QTimer, QUrl
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QCursor,
    QDesktopServices,
    QFont,
    QImage,
    QKeySequence,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
)
from PyQt5.QtWidgets import (
    QAbstractButton,
    QAbstractItemView,
    QApplication,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsItem,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem
from rdkit.Chem import Draw

from ...predictions.aizynthfinder_run import leaf_stock_counts, sort_routes
from ..dialogs.ord_search import OrdSearchDialog
from ...table.structure_image import molecule_pixmap
from ..qt_widget_utils import make_window_minimizable, make_window_resizable
from ..strings import TOOL_RETROSYNTHESIS
from ..structure_copy_menu import add_structure_copy_submenu
from .chrome import style_browser_data_table, style_browser_structure_label

_CARD_W = 160
_CARD_H = 110
_BRANCH_LEN = 120
_STEP_W = 680
_STEP_H = 160
_IN_STOCK = "#2e7d32"
_NOT_IN_STOCK = "#ef6c00"
_CARD_NAME = "route-mol-card"
_STEP_BUTTON_QSS = (
    "QPushButton {"
    " padding: 0px 6px;"
    " border: 1px solid palette(mid);"
    " border-radius: 3px;"
    " background: palette(base);"
    "}"
    "QPushButton:checked { background: palette(midlight); }"
)
_ROUTE_COLUMNS = ("#", "Status", "Score", "Steps", "In stock")
_SCENE_SPAN = 100000
_ZOOM_MIN = 0.25
_ZOOM_MAX = 4.0
_ZOOM_STEP = 1.1
_PAN_SLOP = 4
_RATIO_CAP = 4.0
_BACKING_PIXELS = 16_000_000
_CHEMICAL_FIELDS = frozenset({"reaction", "template", "smiles", "smarts", "inchi", "inchikey"})
_ORD_SEARCH_URL = "https://open-reaction-database.org/search"


def ord_conditions_url(reaction_smiles: str) -> str:
    """Public Open Reaction Database search for conditions of *reaction_smiles*."""
    query = _ord_reaction_query(reaction_smiles)
    if not query:
        return ""
    return f"{_ORD_SEARCH_URL}?{urlencode({'reaction_smarts': query, 'limit': '100'})}"


def open_ord_conditions(reaction_smiles: str) -> bool:
    """Open the Open Reaction Database search for *reaction_smiles* in the browser."""
    url = ord_conditions_url(reaction_smiles)
    if not url:
        return False
    return bool(QDesktopServices.openUrl(QUrl(url)))


def _ord_reaction_query(reaction_smiles: str) -> str:
    """Reaction SMARTS for a condition search, without atom-map numbers."""
    text = reaction_smiles.strip()
    if ">>" not in text:
        return ""
    reaction = _parsed_reaction(text)
    if reaction is None:
        return text
    reactants = _unmapped_side(reaction.GetReactants())
    products = _unmapped_side(reaction.GetProducts())
    if not reactants or not products:
        return text
    return f"{reactants}>>{products}"


def _parsed_reaction(text: str):
    parser = Chem.rdChemReactions.ReactionFromSmarts
    for use_smiles in (True, False):
        try:
            reaction = parser(text, useSmiles=use_smiles)
        except (ValueError, RuntimeError):
            reaction = None
        if reaction is not None and reaction.GetNumProductTemplates():
            return reaction
    return None


def _unmapped_side(mols) -> str:
    pieces: list[str] = []
    for mol in mols:
        copy = Chem.Mol(mol)
        for atom in copy.GetAtoms():
            atom.SetAtomMapNum(0)
        smiles = Chem.MolToSmiles(copy)
        if smiles:
            pieces.append(smiles)
    return ".".join(pieces)


def _device_ratio() -> float:
    """Screen pixels per logical pixel. Drawings use this so they stay sharp."""
    app = QApplication.instance()
    if app is None:
        return 1.0
    return max(1.0, float(app.devicePixelRatio()))


def _backing_ratio(width: int, height: int, ratio: float) -> float:
    """Pixel ratio for a tree of *width* × *height*, capped so the bitmap stays bounded."""
    ratio = min(_RATIO_CAP, max(1.0, ratio))
    pixels = max(1, width) * max(1, height) * ratio * ratio
    if pixels > _BACKING_PIXELS:
        ratio *= (_BACKING_PIXELS / pixels) ** 0.5
    return max(1.0, ratio)


def _render_widget(widget: QWidget, ratio: float) -> QPixmap:
    """Rasterize *widget* at *ratio* physical pixels per logical pixel."""
    width = max(1, int(round(widget.width() * ratio)))
    height = max(1, int(round(widget.height() * ratio)))
    pixmap = QPixmap(width, height)
    pixmap.setDevicePixelRatio(1.0)
    pixmap.fill(widget.palette().color(QPalette.Window))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.TextAntialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
    painter.scale(ratio, ratio)
    widget.render(painter, QPoint())
    painter.end()
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class _SharpProxy(QGraphicsProxyWidget):
    """Draw the embedded tree at screen resolution instead of scaling a 1× bitmap."""

    def __init__(self) -> None:
        super().__init__()
        self.setCacheMode(QGraphicsItem.NoCache)
        self._cache: QPixmap | None = None
        self._key: tuple[int, int, int] | None = None
        self._painting = False
        self._ignore_updates = False

    def invalidate(self) -> None:
        if self._painting or self._ignore_updates or self._cache is None:
            return
        self._cache = None
        self._key = None
        self.update()

    def _accept_updates(self) -> None:
        self._ignore_updates = False

    def paint(self, painter, option, widget=None) -> None:  # noqa: N802
        del option, widget
        hosted = self.widget()
        if hosted is None or hosted.width() < 1 or hosted.height() < 1:
            return
        view = next(
            (item for item in self.scene().views() if isinstance(item, _RouteCanvas)),
            None,
        )
        ratio = view.depict_ratio() if view is not None else 1.0
        key = (hosted.width(), hosted.height(), int(round(ratio * 1000)))
        if self._cache is None or self._key != key:
            self._painting = True
            try:
                self._cache = _render_widget(hosted, ratio)
            finally:
                self._painting = False
                self._ignore_updates = True
                QTimer.singleShot(0, self._accept_updates)
            self._key = key
        if self._cache is not None:
            painter.drawPixmap(QPointF(0, 0), self._cache)


def _is_chemical_field(field: str, value: str) -> bool:
    """Reaction SMILES, templates, and other structure strings can be copied."""
    name = field.strip().lower().replace(" ", "_")
    if name in _CHEMICAL_FIELDS or name.endswith(("_smiles", "_smarts", "_inchi")):
        return bool(value.strip())
    return ">>" in value


class _RouteCanvas(QGraphicsView):
    """Route drawing. Drag with the left button to pan, and scroll to zoom."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        scene = QGraphicsScene(self)
        scene.setSceneRect(QRectF(-_SCENE_SPAN, -_SCENE_SPAN, 2 * _SCENE_SPAN, 2 * _SCENE_SPAN))
        self.setScene(scene)
        self._content: QWidget | None = None
        self._proxy: _SharpProxy | None = None
        self._zoom = 1.0
        self._pending: QPoint | None = None
        self._pan: tuple[QPoint, int, int] | None = None
        self._app_filter = False
        self._pan_cursor = False
        self.on_transform = None
        self.setFrameShape(QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setTransformationAnchor(QGraphicsView.NoAnchor)
        self.setResizeAnchor(QGraphicsView.NoAnchor)
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.TextAntialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setBackgroundBrush(self.palette().brush(QPalette.Base))
        self.setMinimumSize(120, 120)
        self.viewport().installEventFilter(self)
        self.installEventFilter(self)

    def set_content(self, widget: QWidget) -> None:
        self._content = widget
        self._proxy = _SharpProxy()
        self._proxy.setWidget(widget)
        self.scene().addItem(self._proxy)
        self._apply_background()
        self.watch(widget)

    def depict_ratio(self) -> float:
        """Physical pixels per logical pixel for the tree at the current zoom."""
        content = self._content
        width = content.width() if content is not None else 1
        height = content.height() if content is not None else 1
        return _backing_ratio(width, height, _device_ratio() * self._zoom)

    def place_content(self) -> None:
        """Park the drawing with its right side in view. It may extend past every edge."""
        content = self._content
        proxy = self._proxy
        view = self.viewport().size()
        if content is None or proxy is None or view.width() < 2 or view.height() < 2:
            return
        self.resetTransform()
        self._zoom = 1.0
        bounds = proxy.sceneBoundingRect()
        margin = 12
        self.centerOn(bounds.right() - view.width() / 2 + margin, bounds.center().y())
        self._notify_transform()

    def _apply_background(self) -> None:
        """Paint the tree plate with the same base color as the canvas."""
        color = self.palette().color(QPalette.Base)
        brush = QBrush(color)
        self.setBackgroundBrush(brush)
        scene = self.scene()
        if scene is not None:
            scene.setBackgroundBrush(brush)
        content = self._content
        if content is None:
            return
        palette = content.palette()
        palette.setColor(QPalette.Window, color)
        palette.setColor(QPalette.Base, color)
        content.setPalette(palette)
        content.setAutoFillBackground(True)
        content.setObjectName("route-tree")
        content.setAttribute(Qt.WA_StyledBackground, True)
        content.setStyleSheet("QWidget#route-tree { background-color: palette(base); }")
        if self._proxy is not None:
            self._proxy.invalidate()

    def changeEvent(self, event) -> None:  # noqa: N802
        super().changeEvent(event)
        if event.type() == QEvent.PaletteChange:
            self._apply_background()

    def watch(self, root: QWidget) -> None:
        """Listen for drags on *root* and the cards added under it."""
        root.installEventFilter(self)
        for child in root.findChildren(QWidget):
            child.installEventFilter(self)

    def end_pan(self) -> None:
        self._pan = None
        self._pending = None
        if QWidget.mouseGrabber() is self.viewport():
            self.viewport().releaseMouse()
        if self._app_filter:
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
            self._app_filter = False
        if self._pan_cursor:
            QApplication.restoreOverrideCursor()
            self._pan_cursor = False

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind == QEvent.UpdateRequest and self._content_widget(obj):
            if self._proxy is not None:
                self._proxy.invalidate()
            return False
        if kind == QEvent.Wheel and self._on_canvas(obj):
            if event.spontaneous():
                self._zoom_at(self._wheel_steps(event), self._wheel_anchor(obj, event))
            return True
        if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            if self._on_canvas(obj):
                self._pending = self._pointer(event)
                self._install_app_filter()
            return False
        if kind == QEvent.MouseMove and (self._pending is not None or self._pan is not None):
            return self._move_pan(event)
        if kind == QEvent.WindowDeactivate and (self._pan is not None or self._pending is not None):
            self.end_pan()
            return False
        if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
            panning = self._pan is not None
            if panning or self._pending is not None:
                self.end_pan()
            return panning
        return super().eventFilter(obj, event)

    def _move_pan(self, event) -> bool:
        if not event.spontaneous():
            return self._pan is not None
        buttons = event.buttons() or QApplication.mouseButtons()
        if not (buttons & Qt.LeftButton):
            return self._pan is not None
        if self._pan is None:
            origin = self._pending
            if origin is None:
                return False
            if (QCursor.pos() - origin).manhattanLength() < _PAN_SLOP:
                return False
            self._cancel_button_down()
            self._begin_pan(origin)
        origin, horizontal, vertical = self._pan
        delta = QCursor.pos() - origin
        self.horizontalScrollBar().setValue(horizontal - delta.x())
        self.verticalScrollBar().setValue(vertical - delta.y())
        return True

    def _pointer(self, event) -> QPoint:
        if event.spontaneous():
            return QPoint(QCursor.pos())
        return QPoint(event.globalPos())

    def _cancel_button_down(self) -> None:
        content = self._content
        if content is not None:
            for button in content.findChildren(QAbstractButton):
                if button.isDown():
                    button.setDown(False)
        grabber = QWidget.mouseGrabber()
        if grabber is not None and grabber is not self.viewport():
            grabber.releaseMouse()

    def _install_app_filter(self) -> None:
        app = QApplication.instance()
        if app is not None and not self._app_filter:
            app.installEventFilter(self)
            self._app_filter = True

    def _begin_pan(self, origin: QPoint) -> None:
        self._pan = (
            origin,
            self.horizontalScrollBar().value(),
            self.verticalScrollBar().value(),
        )
        self._install_app_filter()
        if not self._pan_cursor:
            QApplication.setOverrideCursor(Qt.ClosedHandCursor)
            self._pan_cursor = True
        QTimer.singleShot(0, self._grab_pan)

    def _notify_transform(self) -> None:
        callback = self.on_transform
        if callback is not None:
            callback()

    def _grab_pan(self) -> None:
        """Take the mouse after the press, so the drag is not dropped."""
        if self._pan is None:
            return
        viewport = self.viewport()
        if QWidget.mouseGrabber() is not viewport:
            viewport.grabMouse()

    def _zoom_at(self, steps: float, anchor: QPoint) -> None:
        if not steps:
            return
        new_zoom = min(_ZOOM_MAX, max(_ZOOM_MIN, self._zoom * (_ZOOM_STEP**steps)))
        applied = new_zoom / self._zoom
        if abs(applied - 1.0) < 1e-4:
            return
        before = self.mapToScene(anchor)
        self._zoom = new_zoom
        self.scale(applied, applied)
        shifted = self.mapFromScene(before)
        self.horizontalScrollBar().setValue(
            self.horizontalScrollBar().value() + shifted.x() - anchor.x()
        )
        self.verticalScrollBar().setValue(
            self.verticalScrollBar().value() + shifted.y() - anchor.y()
        )
        self._notify_transform()

    def _wheel_steps(self, event) -> float:
        angle = event.angleDelta().y()
        if angle:
            return angle / 120.0
        pixel = event.pixelDelta().y()
        if pixel:
            return pixel / 40.0
        return 0.0

    def _wheel_anchor(self, obj, event) -> QPoint:
        point = event.pos()
        local = QPoint(int(point.x()), int(point.y()))
        if obj is self.viewport() or obj is self:
            return local
        if isinstance(obj, QWidget):
            return obj.mapTo(self.viewport(), local)
        return local

    def _on_canvas(self, obj) -> bool:
        if obj is self or obj is self.viewport():
            return True
        return self._content_widget(obj)

    def _content_widget(self, obj) -> bool:
        content = self._content
        if content is None or obj is self or obj is self.viewport():
            return False
        if obj is content:
            return True
        return isinstance(obj, QWidget) and content.isAncestorOf(obj)


def _route_log_view() -> QPlainTextEdit:
    log = QPlainTextEdit()
    log.setReadOnly(True)
    log.setLineWrapMode(QPlainTextEdit.NoWrap)
    log.setMaximumHeight(132)
    log.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
    font = QFont("Consolas")
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(9)
    log.setFont(font)
    log.setStyleSheet(
        "QPlainTextEdit {"
        " background: palette(base);"
        " color: palette(text);"
        " border: 1px solid palette(mid);"
        " border-radius: 4px;"
        "}"
    )
    return log


class RouteBrowserDialog(QDialog):
    """Modeless list of searched targets and the precursor tree of one route."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{TOOL_RETROSYNTHESIS} routes")
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setMinimumSize(920, 560)
        self._targets: list[dict] = []
        self._routes: list[dict] = []
        self._pixmaps: dict[tuple, QPixmap | None] = {}
        self._reaction_pixmaps: dict[tuple, QPixmap | None] = {}
        self._depict_key: int | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        self.target_combo = QComboBox()
        self.target_combo.currentIndexChanged.connect(self._on_target_changed)
        root.addWidget(self.target_combo)

        splitter = QSplitter(Qt.Horizontal)
        self.route_table = _route_table()
        self.route_table.currentCellChanged.connect(self._on_route_cell_changed)
        splitter.addWidget(self.route_table)

        self._steps_host = QWidget()
        self._steps_host.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._steps_host._route_dialog = self
        self._steps_layout = QVBoxLayout(self._steps_host)
        self._steps_layout.setContentsMargins(4, 4, 4, 4)
        self._steps_layout.setSpacing(12)
        self._route_scroll = _RouteCanvas()
        self._route_scroll.on_transform = self._sync_depictions
        self._route_scroll.set_content(self._steps_host)

        canvas_column = QWidget()
        canvas_layout = QVBoxLayout(canvas_column)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(6)
        canvas_layout.addWidget(self._route_scroll, 1)
        self.summary_log = _route_log_view()
        canvas_layout.addWidget(self.summary_log)

        self.step_table = _step_table()
        splitter.addWidget(canvas_column)
        splitter.addWidget(self.step_table)
        splitter.setStretchFactor(1, 1)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        self._empty = QLabel("Run Retrosynthesis → Search to collect routes.")
        self._empty.setWordWrap(True)
        self._steps_layout.insertWidget(0, self._empty)

        make_window_minimizable(self)
        make_window_resizable(self)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._route_scroll._apply_background()
        self._sync_depictions()

    def hideEvent(self, event) -> None:  # noqa: N802
        self._route_scroll.end_pan()
        super().hideEvent(event)

    def set_targets(self, targets: list[dict], *, focus_smiles: str = "") -> None:
        """Replace the target list. *targets* items have ``smiles`` and ``routes``."""
        self._targets = [dict(item) for item in targets if item.get("smiles")]
        self.target_combo.blockSignals(True)
        self.target_combo.clear()
        focus = 0
        for index, target in enumerate(self._targets):
            smiles = str(target.get("smiles") or "")
            n_routes = len(target.get("routes") or [])
            label = smiles if len(smiles) <= 48 else smiles[:45] + "…"
            self.target_combo.addItem(f"{label}  ({n_routes})", smiles)
            if focus_smiles and smiles == focus_smiles:
                focus = index
        self.target_combo.blockSignals(False)
        if self.target_combo.count():
            self.target_combo.setCurrentIndex(focus)
            self._on_target_changed(focus)
        else:
            self._clear_route_table()
            self._routes = []
            self._clear_steps("No routes to show.")

    def molecule_cards(self) -> list[QFrame]:
        """Structure cards currently in the route tree."""
        return self._steps_host.findChildren(QFrame, _CARD_NAME)

    def _on_target_changed(self, index: int) -> None:
        target = self._target_at(index)
        self._routes = sort_routes(list(target.get("routes") or [])) if target else []
        self._fill_route_table(self._routes)
        if not self._routes:
            self._clear_steps("This structure has no extracted routes.")
            return
        self.route_table.blockSignals(True)
        self.route_table.selectRow(0)
        self.route_table.blockSignals(False)
        self._show_route(0)

    def _on_route_cell_changed(
        self, row: int, _column: int, _prev_row: int, _prev_col: int
    ) -> None:
        self._show_route(row)

    def _fill_route_table(self, routes: list[dict]) -> None:
        table = self.route_table
        extras = _extra_score_names(routes)
        headers = list(_ROUTE_COLUMNS) + extras
        table.blockSignals(True)
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(routes))
        for row, route in enumerate(routes):
            solved = bool(route.get("solved"))
            cells = _route_cells(row + 1, route)
            cells.extend(_score_cell(route, name) for name in extras)
            for column, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                if column == 1:
                    color = _IN_STOCK if solved else _NOT_IN_STOCK
                    item.setForeground(QBrush(QColor(color)))
                table.setItem(row, column, item)
        table.resizeColumnsToContents()
        table.blockSignals(False)

    def _clear_route_table(self) -> None:
        self.route_table.blockSignals(True)
        self.route_table.setRowCount(0)
        self.route_table.blockSignals(False)

    def _show_route(self, row: int) -> None:
        if row < 0 or row >= len(self._routes):
            return
        route = self._routes[row]
        self._clear_steps("")
        self.summary_log.setPlainText(_route_log(row + 1, route))
        tree = route.get("tree")
        if isinstance(tree, dict) and str(tree.get("smiles") or "").strip():
            self._empty.hide()
            self._steps_layout.addWidget(
                _MoleculeNode(tree, self._pixmap_for),
                0,
                Qt.AlignRight | Qt.AlignTop,
            )
            self._route_scroll.watch(self._steps_host)
            self._place_tree()
            QTimer.singleShot(0, self._place_tree)
            return
        steps = list(route.get("steps") or [])
        if not steps:
            message = "No reaction steps."
            if route.get("solved"):
                message = "No reaction steps. The target is in stock."
            self._empty.setText(message)
            self._empty.show()
            return
        self._empty.hide()
        for number, step in enumerate(steps, start=1):
            self._steps_layout.addWidget(_StepWidget(number, step, self._reaction_pixmap_for))
        self._route_scroll.watch(self._steps_host)
        self._place_tree()
        QTimer.singleShot(0, self._place_tree)

    def _target_at(self, index: int) -> dict | None:
        if index < 0 or index >= len(self._targets):
            return None
        return self._targets[index]

    def _clear_steps(self, message: str) -> None:
        self._steps_host.setMinimumSize(0, 0)
        layout = self._steps_layout
        for index in range(layout.count() - 1, -1, -1):
            item = layout.itemAt(index)
            widget = item.widget() if item is not None else None
            if widget is None or widget is self._empty:
                continue
            widget.setParent(None)
            widget.deleteLater()
        self.summary_log.setPlainText("" if message else self.summary_log.toPlainText())
        self._clear_step_table()
        self._empty.setText(message)
        self._empty.setVisible(bool(message))

    def _show_step_rows(self, button) -> None:
        for other in self._steps_host.findChildren(QPushButton, "route-step"):
            other.setChecked(other is button)
        rows = list(getattr(button, "step_rows", []) or [])
        table = self.step_table
        table.setRowCount(len(rows))
        for index, (field, value) in enumerate(rows):
            field_item = QTableWidgetItem(field)
            field_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            value_item = QTableWidgetItem(value)
            value_item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
            if _is_chemical_field(field, value):
                value_item.setToolTip(f"{value}\nRight-click to copy")
            else:
                value_item.setToolTip(value)
            table.setItem(index, 0, field_item)
            table.setItem(index, 1, value_item)
        table.resizeColumnsToContents()
        table.resizeRowsToContents()

    def _clear_step_table(self) -> None:
        self.step_table.setRowCount(0)

    def _place_tree(self) -> None:
        host = self._steps_host
        layout = host.layout()
        if layout is None:
            return
        host.setMinimumSize(0, 0)
        size = layout.totalMinimumSize()
        host.resize(max(size.width(), 1), max(size.height(), 1))
        layout.activate()
        self._route_scroll.place_content()

    def _sync_depictions(self) -> None:
        key = int(round(self._route_scroll.depict_ratio() * 1000))
        if key == self._depict_key:
            return
        self._depict_key = key
        self._repaint_structures()

    def _repaint_structures(self) -> None:
        for card in self.molecule_cards():
            label = card.findChild(QLabel)
            pixmap = self._pixmap_for(getattr(card, "_smiles", ""))
            if label is not None and isinstance(pixmap, QPixmap) and not pixmap.isNull():
                label.setPixmap(pixmap)
        for label in self._steps_host.findChildren(QLabel):
            step = getattr(label, "_reaction_step", None)
            if not isinstance(step, dict):
                continue
            pixmap = self._reaction_pixmap_for(step)
            if isinstance(pixmap, QPixmap) and not pixmap.isNull():
                label.setPixmap(pixmap)
        proxy = self._route_scroll._proxy
        if isinstance(proxy, _SharpProxy):
            proxy.invalidate()

    def _pixmap_for(self, smiles: str) -> QPixmap | None:
        ratio = self._route_scroll.depict_ratio()
        key = (smiles, _CARD_W, _CARD_H, int(round(ratio * 1000)))
        if key not in self._pixmaps:
            self._pixmaps[key] = _molecule_pixmap(smiles, _CARD_W, _CARD_H, ratio)
        return self._pixmaps[key]

    def _reaction_pixmap_for(self, step: dict) -> QPixmap | None:
        product = str(step.get("product") or "")
        reactants = [
            str(item.get("smiles") or "")
            for item in step.get("reactants") or []
            if str(item.get("smiles") or "").strip()
        ]
        ratio = self._route_scroll.depict_ratio()
        key = (product, tuple(reactants), _STEP_W, _STEP_H, int(round(ratio * 1000)))
        if key not in self._reaction_pixmaps:
            self._reaction_pixmaps[key] = _reaction_pixmap(
                product, reactants, _STEP_W, _STEP_H, ratio
            )
        return self._reaction_pixmaps[key]


class _MoleculeNode(QWidget):
    """One molecule, with its precursors to the left and the parent to the right."""

    def __init__(
        self,
        node: dict,
        pixmap_for,
        *,
        joined: bool = False,
        counter: list[int] | None = None,
    ) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)
        steps = counter if counter is not None else [0]
        for reaction in node.get("reactions") or []:
            if not isinstance(reaction, dict):
                continue
            reactants = [item for item in reaction.get("reactants") or [] if isinstance(item, dict)]
            if not reactants:
                continue
            _add_reaction(layout, reaction, reactants, pixmap_for, steps)
        smiles = str(node.get("smiles") or "")
        layout.addWidget(_MoleculeCard(node, pixmap_for(smiles)), 0, Qt.AlignVCenter)
        if joined:
            layout.addWidget(_HStem(), 0, Qt.AlignVCenter)


class _MoleculeCard(QFrame):
    """White depiction well. Green when the molecule is in stock, amber otherwise."""

    def __init__(self, node: dict, pixmap: QPixmap | None) -> None:
        super().__init__()
        self._smiles = str(node.get("smiles") or "")
        self.setObjectName(_CARD_NAME)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        color = _IN_STOCK if node.get("in_stock") else _NOT_IN_STOCK
        self.setStyleSheet(
            f"QFrame#{_CARD_NAME} {{ background-color: #ffffff; "
            f"border: 2px solid {color}; border-radius: 4px; }}"
        )
        self.setToolTip(_card_tooltip(node))
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)
        image = QLabel()
        image.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        style_browser_structure_label(image)
        image.setFixedSize(_CARD_W, _CARD_H)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            image.setPixmap(pixmap)
        root.addWidget(image)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        mol = Chem.MolFromSmiles(self._smiles) if self._smiles else None
        menu = QMenu(self)
        by_act = add_structure_copy_submenu(menu, mol)
        chosen = menu.exec_(event.globalPos())
        if chosen in by_act:
            text, _status = by_act[chosen]
            clipboard = QApplication.clipboard()
            if clipboard is not None and text:
                clipboard.setText(text)
        event.accept()


class _HStem(QWidget):
    """Horizontal connector between a molecule and the route toward its parent."""

    def __init__(self, length: int = 22) -> None:
        super().__init__()
        self.setFixedSize(length, 12)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(QPalette.Mid), 2))
        mid = self.height() // 2
        painter.drawLine(0, mid, self.width(), mid)


class _VBranch(QWidget):
    """Vertical connector beside a column of precursors."""

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(12)
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setPen(QPen(self.palette().color(QPalette.Mid), 2))
        top, bottom = _branch_span(self)
        mid = self.height() // 2
        painter.drawLine(0, top, 0, bottom)
        painter.drawLine(0, mid, self.width(), mid)


class _StepTable(QTableWidget):
    """Reaction details. Chemical values copy with Ctrl+C or the context menu."""

    def copy_selected_chemical(self) -> bool:
        row = self.currentRow()
        if row < 0:
            return False
        field_item = self.item(row, 0)
        value_item = self.item(row, 1)
        if field_item is None or value_item is None:
            return False
        value = value_item.text()
        if not _is_chemical_field(field_item.text(), value):
            return False
        clipboard = QApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(value)
        return True

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.matches(QKeySequence.Copy) and self.copy_selected_chemical():
            event.accept()
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        row = self.rowAt(event.pos().y())
        if row < 0:
            return
        field_item = self.item(row, 0)
        value_item = self.item(row, 1)
        if field_item is None or value_item is None:
            return
        if not _is_chemical_field(field_item.text(), value_item.text()):
            return
        menu = QMenu(self)
        action = menu.addAction("Copy")
        if menu.exec_(event.globalPos()) is action:
            self.setCurrentCell(row, 1)
            self.copy_selected_chemical()
        event.accept()


def _step_table() -> QTableWidget:
    table = _StepTable(0, 2)
    table.setHorizontalHeaderLabels(["Field", "Value"])
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setWordWrap(True)
    table.setMinimumWidth(220)
    table.setFocusPolicy(Qt.StrongFocus)
    table.verticalHeader().setVisible(False)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
    style_browser_data_table(table)
    return table


def _route_table() -> QTableWidget:
    table = QTableWidget(0, len(_ROUTE_COLUMNS))
    table.setHorizontalHeaderLabels(list(_ROUTE_COLUMNS))
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setFocusPolicy(Qt.StrongFocus)
    table.setMinimumWidth(340)
    table.setWordWrap(False)
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(28)
    header = table.horizontalHeader()
    header.setStretchLastSection(True)
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setDefaultAlignment(Qt.AlignCenter)
    style_browser_data_table(table)
    return table


def _route_cells(number: int, route: dict) -> list[str]:
    solved = "Solved" if route.get("solved") else "Unsolved"
    score = str(route.get("score") or "").strip() or "—"
    in_stock, total = leaf_stock_counts(route)
    return [str(number), solved, score, str(len(route.get("steps") or [])), f"{in_stock}/{total}"]


def _extra_score_names(routes: list[dict]) -> list[str]:
    """Score names other than the state score, in first-seen order."""
    names: list[str] = []
    seen: set[str] = set()
    for route in routes:
        scores = route.get("scores")
        if not isinstance(scores, dict):
            continue
        for key in scores:
            label = str(key)
            if label.lower() == "state score" or label in seen:
                continue
            seen.add(label)
            names.append(label)
    return names


def _score_cell(route: dict, name: str) -> str:
    scores = route.get("scores")
    if not isinstance(scores, dict) or name not in scores:
        return "—"
    return _format_route_value(scores.get(name))


def _route_log(number: int, route: dict) -> str:
    solved = "Solved" if route.get("solved") else "Unsolved"
    score = str(route.get("score") or "").strip() or "no score"
    n_steps = len(route.get("steps") or [])
    in_stock, total = leaf_stock_counts(route)
    lines = [
        f"route {number}",
        f"status    {solved}",
        f"score     {score}",
        f"steps     {n_steps}",
        f"in stock  {in_stock}/{total}",
    ]
    lines.extend(_route_detail_lines(route))
    return "\n".join(lines)


def _route_detail_lines(route: dict) -> list[str]:
    lines: list[str] = []
    scores = route.get("scores")
    if isinstance(scores, dict):
        for key, value in scores.items():
            if str(key).lower() == "state score":
                continue
            lines.append(f"{key}  {_format_route_value(value)}")
    metadata = route.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value not in (None, ""):
                lines.append(f"{key}  {value}")
    return lines


def _add_reaction(
    layout: QHBoxLayout,
    reaction: dict,
    reactants: list[dict],
    pixmap_for,
    counter: list[int],
) -> None:
    if len(reactants) == 1:
        layout.addWidget(
            _MoleculeNode(reactants[0], pixmap_for, joined=True, counter=counter),
            0,
            Qt.AlignVCenter,
        )
    else:
        column = QWidget()
        column.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        col = QVBoxLayout(column)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(8)
        for reactant in reactants:
            col.addWidget(
                _MoleculeNode(reactant, pixmap_for, joined=True, counter=counter),
                0,
                Qt.AlignRight | Qt.AlignVCenter,
            )
        pair = QWidget()
        pair.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        pair_layout = QHBoxLayout(pair)
        pair_layout.setContentsMargins(0, 0, 0, 0)
        pair_layout.setSpacing(0)
        pair_layout.addWidget(column)
        pair_layout.addWidget(_VBranch())
        layout.addWidget(pair, 0, Qt.AlignVCenter)
    counter[0] += 1
    layout.addWidget(_StepBranch(counter[0], reaction), 0, Qt.AlignVCenter)


class _StepBranch(QWidget):
    """Branch line with a Step button. Details open in the table beside the canvas."""

    def __init__(self, number: int, reaction: dict) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Minimum)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        row.addWidget(_HStem(_BRANCH_LEN), 0, Qt.AlignVCenter)
        self._button = QPushButton(f"Step {number}")
        self._button.setObjectName("route-step")
        self._button.setCheckable(True)
        self._button.setCursor(Qt.PointingHandCursor)
        self._button.setFixedHeight(22)
        self._button.setStyleSheet(_STEP_BUTTON_QSS)
        self._button.step_number = number
        self._button.step_rows = _step_rows(reaction)
        self._button.reaction_smiles = str(reaction.get("smiles") or "").strip()
        self._button.clicked.connect(self._select)
        self._button.installEventFilter(self)
        row.addWidget(self._button, 0, Qt.AlignVCenter)
        row.addWidget(_HStem(_BRANCH_LEN), 0, Qt.AlignVCenter)
        root.addLayout(row)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if obj is self._button and event.type() == QEvent.ContextMenu:
            self._open_reaction_menu(event.globalPos())
            return True
        return super().eventFilter(obj, event)

    def _open_reaction_menu(self, global_pos) -> None:
        menu = QMenu(self._button)
        search = menu.addAction("Search Open Reaction Database")
        smiles = str(getattr(self._button, "reaction_smiles", "") or "")
        search.setEnabled(bool(ord_conditions_url(smiles)))
        if menu.exec_(global_pos) is search:
            self._open_ord_search(smiles)

    def _open_ord_search(self, smiles: str) -> None:
        query = _ord_reaction_query(smiles)
        if not query:
            return
        dialog = OrdSearchDialog(query, parent=self._route_owner())
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _route_owner(self):
        parent = self.parentWidget()
        while parent is not None:
            owner = getattr(parent, "_route_dialog", None)
            if owner is not None:
                return owner
            parent = parent.parentWidget()
        return self.window()

    def _select(self) -> None:
        parent = self.parentWidget()
        while parent is not None:
            show = getattr(parent, "_show_step_rows", None)
            if callable(show):
                show(self._button)
                return
            owner = getattr(parent, "_route_dialog", None)
            show = getattr(owner, "_show_step_rows", None)
            if callable(show):
                show(self._button)
                return
            parent = parent.parentWidget()


def _step_rows(reaction: dict) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    smiles = str(reaction.get("smiles") or "").strip()
    if smiles:
        rows.append(("reaction", smiles))
    metadata = reaction.get("metadata")
    if isinstance(metadata, dict):
        for key, value in metadata.items():
            if value in (None, ""):
                continue
            rows.append((str(key), str(value)))
    return rows


def _branch_span(branch: QWidget) -> tuple[int, int]:
    """Vertical line from the first precursor's connector to the last."""
    parent = branch.parentWidget()
    layout = parent.layout() if parent is not None else None
    column = layout.itemAt(0).widget() if layout is not None and layout.count() else None
    col_layout = column.layout() if column is not None else None
    if col_layout is None or col_layout.count() < 1 or column is None:
        return 0, max(0, branch.height())
    first = col_layout.itemAt(0).widget()
    last = col_layout.itemAt(col_layout.count() - 1).widget()
    if first is None or last is None or first.height() <= 0 or last.height() <= 0:
        return 0, max(0, branch.height())
    top = column.y() + first.y() + first.height() // 2 - branch.y()
    bottom = column.y() + last.y() + last.height() // 2 - branch.y()
    if bottom < top:
        top, bottom = bottom, top
    return top, bottom


def _card_tooltip(node: dict) -> str:
    stock = node.get("stock")
    names = [str(item).strip() for item in stock] if isinstance(stock, list) else []
    names = [name for name in names if name]
    if names:
        return f"In stock: {', '.join(names)}. Right-click to copy"
    return "Right-click to copy"


def _reaction_caption(reaction: dict) -> str:
    meta = reaction.get("metadata")
    if not isinstance(meta, dict) or not meta:
        return ""
    parts: list[str] = []
    name = str(meta.get("policy_name") or "").strip()
    if name:
        parts.append(name)
    if meta.get("policy_probability") not in (None, ""):
        parts.append(_probability_text(meta.get("policy_probability")))
    if meta.get("policy_probability_rank") not in (None, ""):
        parts.append(f"rank {meta.get('policy_probability_rank')}")
    classification = str(meta.get("classification") or "").strip()
    if classification:
        parts.append(classification)
    occurrence = meta.get("library_occurrence", meta.get("library_occurence"))
    if occurrence not in (None, ""):
        parts.append(f"occurs {occurrence}")
    return " · ".join(parts)


def _metadata_tooltip(metadata: object) -> str:
    if not isinstance(metadata, dict) or not metadata:
        return ""
    return "\n".join(f"{key}: {value}" for key, value in metadata.items())


def _format_route_value(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    if value is None or value == "":
        return "—"
    return str(value)


def _probability_text(value: object) -> str:
    try:
        return f"{float(value):.4f}"  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return str(value)


def _molecule_pixmap(smiles: str, width: int, height: int, ratio: float) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles) if smiles else None
    if mol is None:
        return None
    app_ratio = _device_ratio()
    scale = ratio / app_ratio if app_ratio else ratio
    try:
        pixmap = molecule_pixmap(
            mol,
            max(1, int(round(width * scale))),
            max(1, int(round(height * scale))),
        )
    except (ValueError, RuntimeError):
        return None
    if pixmap.isNull():
        return None
    pixmap.setDevicePixelRatio(ratio)
    return pixmap


class _StepWidget(QWidget):
    """Linear fallback when a route has reaction steps and no nested tree."""

    def __init__(self, number: int, step: dict, pixmap_for) -> None:
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(4)
        title = QLabel(f"Step {number}")
        title.setStyleSheet("font-weight: 600;")
        root.addWidget(title)
        image = QLabel()
        image.setAlignment(Qt.AlignCenter)
        image._reaction_step = step
        pixmap = pixmap_for(step)
        if isinstance(pixmap, QPixmap) and not pixmap.isNull():
            image.setPixmap(pixmap)
        root.addWidget(image)
        caption = _reaction_caption({"metadata": step.get("metadata")})
        if caption:
            detail = QLabel(caption)
            detail.setAlignment(Qt.AlignCenter)
            detail.setWordWrap(True)
            detail.setTextInteractionFlags(Qt.TextSelectableByMouse)
            detail.setToolTip(_metadata_tooltip(step.get("metadata")))
            root.addWidget(detail)


def _reaction_pixmap(
    product: str, reactants: list[str], width: int, height: int, ratio: float
) -> QPixmap | None:
    if not product or not reactants:
        return _molecule_pixmap(product, width, height, ratio)
    smiles = ".".join(reactants) + ">>" + product
    try:
        reaction = Chem.rdChemReactions.ReactionFromSmarts(smiles, useSmiles=True)
        if reaction is None:
            return _molecule_pixmap(product, width, height, ratio)
        drawer = Draw.MolDraw2DCairo(
            max(1, int(round(width * ratio))),
            max(1, int(round(height * ratio))),
        )
        drawer.DrawReaction(reaction)
        drawer.FinishDrawing()
        image = QImage.fromData(bytes(drawer.GetDrawingText()))
    except (ValueError, RuntimeError):
        return _molecule_pixmap(product, width, height, ratio)
    if image.isNull():
        return None
    pixmap = QPixmap.fromImage(image)
    if pixmap.isNull():
        return None
    pixmap.setDevicePixelRatio(ratio)
    return pixmap
