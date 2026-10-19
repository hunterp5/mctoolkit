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

"""Host pane for one or more docked plot widgets."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QStackedLayout,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..dockable_plot import (
    PLOT_PANEL_BASE_MINIMUM_WIDTH,
    _FOOTER_TEXT_FONT_PX,
    _GLYPH_BTN_SIZE,
    adopt_dock_header_buttons,
    embed_in_plot_pane,
    plot_widget_display_title,
    restore_dock_header_buttons,
    style_plot_pane_close_button,
    style_plot_pane_nav_arrow,
    style_plot_pane_title_edit,
    unembed_from_plot_pane,
)
from ..layout_perf import perf_span

_WEB_ENGINE_VIEW_UNSET = object()
_WEB_ENGINE_VIEW_CLS = _WEB_ENGINE_VIEW_UNSET


def _web_engine_view_type():
    """``QWebEngineView`` when importable; import stays local to avoid Chromium init."""
    global _WEB_ENGINE_VIEW_CLS
    if _WEB_ENGINE_VIEW_CLS is not _WEB_ENGINE_VIEW_UNSET:
        return _WEB_ENGINE_VIEW_CLS
    try:
        from PyQt5.QtWebEngineWidgets import QWebEngineView
    except ImportError:
        _WEB_ENGINE_VIEW_CLS = None
    else:
        _WEB_ENGINE_VIEW_CLS = QWebEngineView
    return _WEB_ENGINE_VIEW_CLS


class _StackPresizeFilter(QObject):
    """Keep non-current stack pages at the stack size so WebEngine/Plotly do not cold-resize."""

    def __init__(self, pane: "PlotPane"):
        super().__init__(pane)
        self._pane = pane

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.Resize and obj is self._pane._stack:
            with perf_span("presize_stack_pages"):
                self._pane._presize_stack_pages(live_only=True)
        return False


class PlotPane(QFrame):
    """Host for one or more docked plot widgets, with pager chrome when stacked."""

    activated = pyqtSignal(object)  # PlotPane
    close_requested = pyqtSignal(object)  # PlotPane

    def __init__(self, pane_id: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.pane_id = pane_id
        self._pages: list[QWidget] = []
        self._page_web_views: dict[int, list] = {}
        self._stale_pages: set[int] = set()
        self._settle_presize_timer = QTimer(self)
        self._settle_presize_timer.setSingleShot(True)
        self._settle_presize_timer.setInterval(150)
        self._settle_presize_timer.timeout.connect(self._presize_stale_pages)
        self.setObjectName("PlotPane")
        # Border width is owned by the stylesheet; avoid QFrame chrome fighting it.
        self.setFrameShape(QFrame.NoFrame)
        self.setMinimumWidth(PLOT_PANEL_BASE_MINIMUM_WIDTH // 2)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(1, 0, 1, 1)
        self._root.setSpacing(0)

        self._nav_host = QWidget()
        self._nav_host.setObjectName("PlotPaneNav")
        nav_ly = QHBoxLayout(self._nav_host)
        nav_ly.setContentsMargins(0, 0, 0, 0)
        nav_ly.setSpacing(2)
        self._prev_btn = QPushButton()
        self._next_btn = QPushButton()
        self._move_earlier_btn = QPushButton()
        self._move_later_btn = QPushButton()
        self._style_nav_arrow(self._prev_btn, "left")
        self._style_nav_arrow(self._next_btn, "right")
        self._style_nav_arrow(self._move_earlier_btn, "up")
        self._style_nav_arrow(self._move_later_btn, "down")
        self._prev_btn.setToolTip("Previous plot in this pane")
        self._next_btn.setToolTip("Next plot in this pane")
        self._move_earlier_btn.setToolTip("Move this plot earlier in the pane")
        self._move_later_btn.setToolTip("Move this plot later in the pane")
        self._prev_btn.clicked.connect(self.show_previous_page)
        self._next_btn.clicked.connect(self.show_next_page)
        self._move_earlier_btn.clicked.connect(self.move_current_page_earlier)
        self._move_later_btn.clicked.connect(self.move_current_page_later)
        self._title_edit = QLineEdit()
        self._title_edit.setObjectName("PlotPaneTitle")
        self._title_edit.setReadOnly(True)
        self._title_edit.setFocusPolicy(Qt.ClickFocus)
        self._title_edit.setToolTip("Double-click to rename this plot")
        style_plot_pane_title_edit(self._title_edit)
        self._title_edit.installEventFilter(self)
        self._title_edit.editingFinished.connect(self._commit_title_edit)
        # Compatibility alias for older tests/callers.
        self._title_label = self._title_edit
        self._page_label = QLabel("")
        self._page_label.setObjectName("PlotPanePage")
        self._page_label.setAlignment(Qt.AlignCenter)
        self._page_label.setFixedWidth(38)
        self._page_label.setFixedHeight(_GLYPH_BTN_SIZE)
        self._page_label.setStyleSheet(
            f"QLabel {{ font-size: {_FOOTER_TEXT_FONT_PX}px; padding: 0px 1px; }}"
        )
        nav_ly.addWidget(self._prev_btn)
        nav_ly.addWidget(self._next_btn)
        nav_ly.addWidget(self._title_edit)
        nav_ly.addWidget(self._page_label)
        nav_ly.addWidget(self._move_earlier_btn)
        nav_ly.addWidget(self._move_later_btn)
        # Compatibility alias used by older tests.
        self._pager = self._nav_host

        # Header: equal side strips keep the pager geometrically centered in the pane.
        self._header = QWidget()
        self._header.setObjectName("PlotPaneHeader")
        self._header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._header.setFixedHeight(_GLYPH_BTN_SIZE)
        header_ly = QHBoxLayout(self._header)
        header_ly.setContentsMargins(2, 0, 2, 0)
        header_ly.setSpacing(2)

        self._header_left = QWidget()
        self._header_left.setObjectName("PlotPaneHeaderLeft")
        left_ly = QHBoxLayout(self._header_left)
        left_ly.setContentsMargins(0, 0, 0, 0)
        left_ly.setSpacing(2)
        self._leading_opts_host = QWidget()
        self._leading_opts_host.setObjectName("PlotPaneLeadingOpts")
        self._leading_opts_ly = QHBoxLayout(self._leading_opts_host)
        self._leading_opts_ly.setContentsMargins(0, 0, 0, 0)
        self._leading_opts_ly.setSpacing(2)
        left_ly.addWidget(self._leading_opts_host, 0)
        self._chrome_host = QWidget()
        self._chrome_host.setObjectName("PlotPaneChrome")
        self._chrome_ly = QHBoxLayout(self._chrome_host)
        self._chrome_ly.setContentsMargins(0, 0, 0, 0)
        self._chrome_ly.setSpacing(2)
        left_ly.addWidget(self._chrome_host, 0)
        left_ly.addStretch(1)

        self._header_right = QWidget()
        self._header_right.setObjectName("PlotPaneHeaderRight")
        right_ly = QHBoxLayout(self._header_right)
        right_ly.setContentsMargins(0, 0, 0, 0)
        right_ly.setSpacing(2)
        right_ly.addStretch(1)
        self._send_host = QWidget()
        self._send_host.setObjectName("PlotPaneSend")
        self._send_ly = QHBoxLayout(self._send_host)
        self._send_ly.setContentsMargins(0, 0, 0, 0)
        self._send_ly.setSpacing(2)
        right_ly.addWidget(self._send_host, 0)
        self._trailing_close_host = QWidget()
        self._trailing_close_host.setObjectName("PlotPaneTrailingClose")
        self._trailing_close_ly = QHBoxLayout(self._trailing_close_host)
        self._trailing_close_ly.setContentsMargins(0, 0, 0, 0)
        self._trailing_close_ly.setSpacing(2)
        right_ly.addWidget(self._trailing_close_host, 0)
        self._close_btn = QPushButton()
        self._close_btn.setObjectName("PlotPaneClose")
        style_plot_pane_close_button(self._close_btn, "Close this plot pane")
        self._close_btn.clicked.connect(lambda *_a: self.close_requested.emit(self))
        right_ly.addWidget(self._close_btn, 0)

        header_ly.addWidget(self._header_left, 1)
        header_ly.addWidget(self._nav_host, 0)
        header_ly.addWidget(self._header_right, 1)
        # Alias so callers/tests that still look at ``_footer`` find the chrome bar.
        self._footer = self._header
        self._root.addWidget(self._header)

        self._stack = QStackedWidget()
        self._stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        stack_ly = self._stack.layout()
        if stack_ly is not None and hasattr(stack_ly, "setSizeAdjustPolicy"):
            stack_ly.setSizeAdjustPolicy(QStackedLayout.AdjustIgnored)
        self._stack.currentChanged.connect(self._on_stack_current_changed)
        self._stack_presize_filter = _StackPresizeFilter(self)
        self._stack.installEventFilter(self._stack_presize_filter)
        self._stack.hide()

        self._placeholder = QLabel("Plot pane\n(Add to Main Window…)")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setWordWrap(True)
        self._placeholder.setStyleSheet("color: palette(mid); padding: 12px;")
        self._root.addWidget(self._stack, 1)
        self._root.addWidget(self._placeholder, 1)
        self._header_button_owner = None
        self._title_edit_base = ""

        self._active = False
        self._set_active_style(False)
        self._refresh_pager()

    @staticmethod
    def _style_nav_arrow(btn: QPushButton, direction: str) -> None:
        style_plot_pane_nav_arrow(btn, direction)

    def refresh_theme(self) -> None:
        """Re-apply palette-backed chrome after a GUI theme or application font change."""
        self._set_active_style(self._active)
        self._placeholder.setStyleSheet("color: palette(mid); padding: 12px;")
        app = QApplication.instance()
        if app is not None:
            font = app.font()
            pal = app.palette()
            self.setPalette(pal)
            for widget in (
                self._header,
                self._footer,
                self._header_left,
                self._header_right,
                self._leading_opts_host,
                self._chrome_host,
                self._send_host,
                self._trailing_close_host,
                self._nav_host,
                self._close_btn,
                self._prev_btn,
                self._next_btn,
                self._move_earlier_btn,
                self._move_later_btn,
                self._title_edit,
                self._page_label,
                self._placeholder,
            ):
                widget.setPalette(pal)
                widget.setFont(font)
                style = widget.style()
                if style is not None:
                    style.unpolish(widget)
                    style.polish(widget)
                widget.update()
        self._style_nav_arrow(self._prev_btn, "left")
        self._style_nav_arrow(self._next_btn, "right")
        self._style_nav_arrow(self._move_earlier_btn, "up")
        self._style_nav_arrow(self._move_later_btn, "down")
        style_plot_pane_close_button(self._close_btn, "Close this plot pane")
        style_plot_pane_title_edit(self._title_edit)
        self.update()

    def plot_widget(self) -> QWidget | None:
        """Currently visible plot in this pane."""
        if not self._pages:
            return None
        current = self._stack.currentWidget()
        if current in self._pages:
            return current
        return self._pages[-1]

    def plot_widgets(self) -> list[QWidget]:
        """All plots hosted in this pane (visible first is not required)."""
        return list(self._pages)

    def page_count(self) -> int:
        return len(self._pages)

    def page_index(self) -> int:
        if not self._pages:
            return -1
        idx = int(self._stack.currentIndex())
        if 0 <= idx < len(self._pages):
            return idx
        return len(self._pages) - 1

    def is_empty(self) -> bool:
        return not self._pages

    def take_plot_widgets(self) -> list[QWidget]:
        """Detach pages for a layout rebuild.

        Restores pane-adopted header buttons onto each plot first so a following
        ``deleteLater`` of this pane cannot destroy Plot Options / Close chrome.
        """
        widgets = list(self._pages)
        owner = getattr(self, "_header_button_owner", None)
        if owner is not None:
            restore_dock_header_buttons(owner)
            self._header_button_owner = None
        for widget in widgets:
            if widget is not owner:
                restore_dock_header_buttons(widget)
        self._stack.blockSignals(True)
        try:
            for widget in widgets:
                self._forget_page_web_cache(widget)
                self._stack.removeWidget(widget)
                try:
                    # Hide first so Qt does not flash a top-level window.
                    widget.hide()
                    widget.setParent(None)
                except RuntimeError:
                    pass
            self._pages = []
            self._page_web_views.clear()
            self._stale_pages.clear()
        finally:
            self._stack.blockSignals(False)
        self._refresh_pager()
        return widgets

    def display_title(self) -> str:
        return plot_widget_display_title(self.plot_widget())

    @staticmethod
    def _title_for_widget(w: QWidget | None) -> str:
        return plot_widget_display_title(w)

    def eventFilter(self, obj, event):  # noqa: N802 — Qt API name
        if obj is self._title_edit and event.type() == QEvent.MouseButtonDblClick:
            if event.button() == Qt.LeftButton and self.plot_widget() is not None:
                self._begin_title_edit()
                return True
        if obj is self._title_edit and event.type() == QEvent.KeyPress:
            if event.key() == Qt.Key_Escape and not self._title_edit.isReadOnly():
                self._cancel_title_edit()
                return True
        return super().eventFilter(obj, event)

    def _begin_title_edit(self) -> None:
        self._title_edit_base = self._title_for_widget(self.plot_widget())
        self._title_edit.blockSignals(True)
        self._title_edit.setText(self._title_edit_base)
        self._title_edit.blockSignals(False)
        self._title_edit.setReadOnly(False)
        self._title_edit.setFocus(Qt.MouseFocusReason)
        self._title_edit.selectAll()

    def _cancel_title_edit(self) -> None:
        self._title_edit.blockSignals(True)
        self._title_edit.setText(self._title_edit_base)
        self._title_edit.blockSignals(False)
        self._title_edit.setReadOnly(True)
        self._title_edit.clearFocus()
        self._refresh_pager()

    def _commit_title_edit(self) -> None:
        if self._title_edit.isReadOnly():
            return
        widget = self.plot_widget()
        text = self._title_edit.text().strip()
        self._title_edit.setReadOnly(True)
        if widget is not None:
            if text:
                widget._pane_display_title = text
            elif hasattr(widget, "_pane_display_title"):
                try:
                    delattr(widget, "_pane_display_title")
                except Exception:
                    widget._pane_display_title = ""
        self._refresh_pager()

    def set_plot_widget(self, widget: QWidget | None) -> QWidget | None:
        """Replace this pane's stack with ``widget`` (or clear when ``None``)."""
        previous = self.plot_widget()
        if widget is None:
            self.set_plot_widgets([])
            return previous
        self.set_plot_widgets([widget])
        return previous if previous is not widget else None

    def set_plot_widgets(self, widgets: list[QWidget], *, current: int | None = None) -> None:
        """Replace the page stack. Detaches previous pages without deleting them."""
        current_id = None
        if current is None and self._pages:
            cur = self.plot_widget()
            current_id = id(cur) if cur is not None else None
        self._stack.blockSignals(True)
        try:
            owner = getattr(self, "_header_button_owner", None)
            if owner is not None:
                restore_dock_header_buttons(owner)
                self._header_button_owner = None
            for old in list(self._pages):
                self._stack.removeWidget(old)
                old.setParent(None)
                self._forget_page_web_cache(old)
                unembed_from_plot_pane(old)
            self._pages = []
            self._stale_pages.clear()
            for widget in widgets:
                if widget is None:
                    continue
                embed_in_plot_pane(widget)
                self._pages.append(widget)
                self._stack.addWidget(widget)
                self._remember_page_web_views(widget)
            if self._pages:
                idx = 0
                if current is not None:
                    idx = max(0, min(int(current), len(self._pages) - 1))
                elif current_id is not None:
                    for i, w in enumerate(self._pages):
                        if id(w) == current_id:
                            idx = i
                            break
                self._stack.setCurrentIndex(idx)
        finally:
            self._stack.blockSignals(False)
        self._refresh_pager()
        self._sync_visible_footer()

    def add_plot_widget(self, widget: QWidget) -> None:
        """Append ``widget`` and show it. If it is already here, just show it."""
        embed_in_plot_pane(widget)
        if widget not in self._pages:
            self._pages.append(widget)
            self._stack.addWidget(widget)
            self._remember_page_web_views(widget)
        self._display_page(self._pages.index(widget))
        self._refresh_pager()
        self._sync_visible_footer()

    def remove_plot_widget(self, widget: QWidget, *, discard: bool = False) -> bool:
        """Detach ``widget`` from this pane. Returns True if it was present."""
        if widget not in self._pages:
            return False
        if getattr(self, "_header_button_owner", None) is widget:
            if not discard:
                # Stay hidden until the widget is off this stack. Showing the footer
                # here shrinks the figure while it is still the visible page.
                restore_dock_header_buttons(widget, docked=True)
            self._header_button_owner = None
        idx = self._pages.index(widget)
        self._pages.remove(widget)
        self._forget_page_web_cache(widget)
        self._stack.removeWidget(widget)
        try:
            widget.setParent(None)
        except RuntimeError:
            pass
        if not discard:
            unembed_from_plot_pane(widget)
        if self._pages:
            self._display_page(min(idx, len(self._pages) - 1))
        self._refresh_pager()
        self._sync_visible_footer()
        return True

    def show_previous_page(self) -> None:
        n = len(self._pages)
        if n < 2:
            return
        self._ensure_stale_pages_presized()
        self._display_page((self.page_index() - 1) % n)
        self.activated.emit(self)

    def show_next_page(self) -> None:
        n = len(self._pages)
        if n < 2:
            return
        self._ensure_stale_pages_presized()
        self._display_page((self.page_index() + 1) % n)
        self.activated.emit(self)

    def move_current_page_earlier(self) -> None:
        """Shift the visible plot one slot toward the start of this pane."""
        self._move_current_page(-1)

    def move_current_page_later(self) -> None:
        """Shift the visible plot one slot toward the end of this pane."""
        self._move_current_page(1)

    def _move_current_page(self, delta: int) -> None:
        n = len(self._pages)
        if n < 2 or delta == 0:
            return
        idx = self.page_index()
        new_idx = idx + int(delta)
        if new_idx < 0 or new_idx >= n:
            return
        widget = self._pages.pop(idx)
        self._pages.insert(new_idx, widget)
        self._stack.blockSignals(True)
        try:
            self._stack.insertWidget(new_idx, widget)
            self._stack.setCurrentWidget(widget)
        finally:
            self._stack.blockSignals(False)
        self._refresh_pager()
        self._sync_visible_footer()
        self.activated.emit(self)

    def set_page(self, index: int) -> None:
        if not self._pages:
            return
        self._ensure_stale_pages_presized()
        self._display_page(index)

    def _on_stack_current_changed(self, _index: int) -> None:
        self._ensure_stale_pages_presized()
        self._presize_stack_pages()
        self._refresh_pager()
        self._sync_visible_footer()

    def _remember_page_web_views(self, page: QWidget) -> None:
        web_cls = _web_engine_view_type()
        views: list = []
        if web_cls is not None:
            try:
                views = page.findChildren(web_cls)
            except RuntimeError:
                views = []
        self._page_web_views[id(page)] = views

    def _forget_page_web_cache(self, page: QWidget) -> None:
        self._page_web_views.pop(id(page), None)
        self._stale_pages.discard(id(page))

    def _stack_content_size(self) -> tuple[int, int] | None:
        stack = getattr(self, "_stack", None)
        if stack is None:
            return None
        try:
            sw, sh = int(stack.width()), int(stack.height())
        except RuntimeError:
            return None
        if sw < 20 or sh < 20:
            return None
        return sw, sh

    def _apply_page_geometry(self, page: QWidget, sw: int, sh: int) -> None:
        """Size a stack page to the pane, then let its layout place the figure.

        The web view sits inside the plot layout (body margins, and the footer when
        that bar is up). Pinning the view to the stack rectangle makes it a few
        pixels too big; the layout then corrects it and Plotly lays the figure out
        again. Activating the page layout assigns the content rect directly.
        """
        try:
            if page.width() != sw or page.height() != sh:
                page.resize(sw, sh)
            layout = page.layout()
        except RuntimeError:
            return
        if layout is None:
            return
        try:
            layout.invalidate()
            layout.activate()
        except RuntimeError:
            return

    def _schedule_stale_presize(self) -> None:
        if self._stale_pages:
            self._settle_presize_timer.start()

    def _presize_stale_pages(self) -> None:
        size = self._stack_content_size()
        if size is None:
            return
        sw, sh = size
        for key in list(self._stale_pages):
            page = next((p for p in self._pages if id(p) == key), None)
            if page is None:
                self._stale_pages.discard(key)
                continue
            self._apply_page_geometry(page, sw, sh)
            self._stale_pages.discard(key)

    def _ensure_stale_pages_presized(self) -> None:
        if not self._stale_pages:
            return
        self._settle_presize_timer.stop()
        self._presize_stale_pages()

    def _presize_stack_pages(self, *, live_only: bool = False) -> None:
        """Match stack pages to the pane content area.

        During splitter drags only the visible page is resized live; hidden pages are
        updated on a short settle timer or before a page switch.
        """
        size = self._stack_content_size()
        if size is None:
            return
        sw, sh = size
        stack = self._stack
        current = stack.currentWidget() if stack is not None else None
        if live_only:
            if current is not None:
                self._apply_page_geometry(current, sw, sh)
            for page in self._pages:
                if page is not current:
                    self._stale_pages.add(id(page))
            self._schedule_stale_presize()
            return
        for page in list(self._pages):
            try:
                self._apply_page_geometry(page, sw, sh)
                self._stale_pages.discard(id(page))
            except RuntimeError:
                continue

    def _install_page_chrome(self, page: QWidget | None) -> None:
        """Adopt ``page`` header buttons before that page is shown.

        Doing this after ``setCurrentIndex`` paints the footer, then hides it, and
        the figure grows by that band. Background pages keep the footer hidden so
        the next visit does not resize the figure either.
        """
        if page is None:
            return
        owner = getattr(self, "_header_button_owner", None)
        if owner is not None and owner is not page:
            restore_dock_header_buttons(owner, docked=owner in self._pages)
            self._header_button_owner = None
            owner = None
        if owner is page:
            sync = getattr(page, "_sync_footer_chrome", None)
            if callable(sync):
                try:
                    sync()
                except RuntimeError:
                    pass
            return
        sync = getattr(page, "_sync_footer_chrome", None)
        if callable(sync):
            try:
                sync()
            except RuntimeError:
                pass
        adopt_dock_header_buttons(
            self._chrome_ly,
            page,
            leading_opts_layout=self._leading_opts_ly,
            send_window_layout=self._send_ly,
            trailing_close_layout=self._trailing_close_ly,
        )
        self._header_button_owner = page

    def _sync_visible_footer(self) -> None:
        self._install_page_chrome(self.plot_widget())

    def _display_page(self, index: int) -> None:
        """Show ``index`` with its chrome and figure box already final."""
        n = len(self._pages)
        if n == 0:
            return
        index = max(0, min(int(index), n - 1))
        page = self._pages[index]
        self._stack.setUpdatesEnabled(False)
        try:
            self._install_page_chrome(page)
            self._presize_stack_pages()
            if self.page_index() != index:
                self._stack.setCurrentIndex(index)
        finally:
            self._stack.setUpdatesEnabled(True)

    def _refresh_pager(self) -> None:
        n = len(self._pages)
        self._header.show()
        if n == 0:
            owner = getattr(self, "_header_button_owner", None)
            if owner is not None:
                restore_dock_header_buttons(owner)
                self._header_button_owner = None
            self._nav_host.hide()
            self._stack.hide()
            self._placeholder.show()
            return
        self._placeholder.hide()
        self._stack.show()
        self._nav_host.show()
        multi = n > 1
        idx = self.page_index()
        self._prev_btn.setVisible(multi)
        self._next_btn.setVisible(multi)
        self._prev_btn.setEnabled(multi)
        self._next_btn.setEnabled(multi)
        self._move_earlier_btn.setVisible(multi)
        self._move_later_btn.setVisible(multi)
        self._move_earlier_btn.setEnabled(multi and idx > 0)
        self._move_later_btn.setEnabled(multi and 0 <= idx < n - 1)
        title = self._title_for_widget(self.plot_widget())
        editing = not self._title_edit.isReadOnly() and self._title_edit.hasFocus()
        if not editing:
            self._title_edit.blockSignals(True)
            self._title_edit.setText(title)
            self._title_edit.blockSignals(False)
        if multi:
            tip = f"Plot {idx + 1} of {n}"
            self._page_label.setText(f"({idx + 1}/{n})")
            self._page_label.setVisible(True)
            self._prev_btn.setToolTip(f"Previous plot ({tip})")
            self._next_btn.setToolTip(f"Next plot ({tip})")
            self._move_earlier_btn.setToolTip(f"Move this plot earlier ({tip})")
            self._move_later_btn.setToolTip(f"Move this plot later ({tip})")
        else:
            self._page_label.clear()
            self._page_label.setVisible(False)
            self._prev_btn.setToolTip("Previous plot in this pane")
            self._next_btn.setToolTip("Next plot in this pane")
            self._move_earlier_btn.setToolTip("Move this plot earlier in the pane")
            self._move_later_btn.setToolTip("Move this plot later in the pane")
        self._title_edit.setToolTip(f"{title}\nDouble-click to rename")

    def clear_plot_widget(self) -> QWidget | None:
        """Remove the currently visible plot; other pages stay."""
        current = self.plot_widget()
        if current is None:
            return None
        self.remove_plot_widget(current)
        return current

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._set_active_style(self._active)

    def _set_active_style(self, active: bool) -> None:
        # Keep border width identical so activating a pane does not resize Plotly.
        color = "palette(highlight)" if active else "palette(mid)"
        self.setStyleSheet(f"QFrame#PlotPane {{ border: 2px solid {color}; border-radius: 2px; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802 — Qt API
        self.activated.emit(self)
        super().mousePressEvent(event)
