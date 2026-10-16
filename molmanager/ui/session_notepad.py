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

"""Floating session notepad that docks like a plot or browser window."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QTextCharFormat, QTextCursor, QTextListFormat
from PyQt5.QtWidgets import (
    QColorDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .browsers.chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    floating_browser_minimum_width,
)
from .dockable_plot import (
    apply_plot_chrome_glyphs,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_send_window_button,
    style_plot_footer_text_button,
    sync_docked_footer_bar,
    sync_footer_on_parent_change,
)
from .dockable_plot_glyphs import (
    FORMAT_GLYPH_BTN_SIZE,
    bold_glyph_icon,
    bullet_glyph_icon,
    italic_glyph_icon,
    numbering_glyph_icon,
    style_format_glyph_button,
    subscript_glyph_icon,
    superscript_glyph_icon,
    text_color_glyph_icon,
    underline_glyph_icon,
)
from .qt_widget_utils import qobject_is_deleted

NOTE_FONT_FAMILY = "Segoe UI"
DEFAULT_NOTE_PT = 12
DEFAULT_NOTE_COLOR = "#202020"
NOTE_PAPER = "#ffffff"
MIN_NOTE_PT = 8
MAX_NOTE_PT = 72


def _clamp_pt(value: object) -> int:
    try:
        pt = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        pt = DEFAULT_NOTE_PT
    return max(MIN_NOTE_PT, min(MAX_NOTE_PT, pt))


def _parse_color(value: object) -> QColor:
    color = QColor(str(value or ""))
    if not color.isValid():
        return QColor(DEFAULT_NOTE_COLOR)
    return color


def _live(widget: Any) -> Any:
    if widget is None or qobject_is_deleted(widget):
        return None
    return widget


def _blocks_touched_by_cursor(editor: QTextEdit, cursor: QTextCursor) -> list:
    """Paragraphs covered by *cursor*, including the caret paragraph when nothing is selected."""
    document = editor.document()
    if document is None:
        return []
    start = min(cursor.position(), cursor.anchor())
    end = max(cursor.position(), cursor.anchor())
    block = document.findBlock(start)
    end_block = document.findBlock(end - 1) if end > start else block
    blocks = []
    while block.isValid():
        blocks.append(block)
        if block == end_block:
            break
        block = block.next()
    return blocks


def _mark_notepad_dirty(app: Any) -> None:
    mark = getattr(app, "_mark_session_dirty", None)
    if callable(mark):
        mark()


class _NoteEditor(QTextEdit):
    """Rich-text editor whose base font ignores the application font."""

    def __init__(self, panel: NotepadWidget) -> None:
        super().__init__(panel)
        self._panel = panel
        self.setObjectName("SessionNotepadEdit")
        self.setAcceptRichText(True)
        self.setLineWrapMode(QTextEdit.WidgetWidth)
        self.setPlaceholderText("Notes for this session")
        self.setUndoRedoEnabled(True)
        self.setStyleSheet(
            "QTextEdit#SessionNotepadEdit {"
            f"background-color: {NOTE_PAPER};"
            "selection-background-color: #cce4ff;"
            "}"
        )

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        kind = event.type()
        guarded = kind in (QEvent.ApplicationFontChange, QEvent.ApplicationPaletteChange)
        if guarded and self._panel.applying_style:
            return
        if not guarded:
            super().changeEvent(event)
            return
        html = self.toHtml()
        super().changeEvent(event)
        self._panel.reapply_base_font(html)


class NotepadWidget(QWidget):
    """Notes panel with plot/browser footer chrome and character formatting."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = "Notepad"
        self.applying_style = False
        self._format_syncing = False
        self._color = QColor(DEFAULT_NOTE_COLOR)

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._footer_bar.setMinimumHeight(FORMAT_GLYPH_BTN_SIZE)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)

        self._header_left = QWidget(self._footer_bar)
        self._header_left.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        left = QHBoxLayout(self._header_left)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(4)
        size_label = QLabel("Size", self._header_left)
        self._size = QSpinBox(self._header_left)
        self._size.setRange(MIN_NOTE_PT, MAX_NOTE_PT)
        self._size.setValue(DEFAULT_NOTE_PT)
        self._size.setSuffix(" pt")
        self._size.setFixedHeight(FORMAT_GLYPH_BTN_SIZE)
        self._size.setToolTip("Text size. Settings → Font does not change the notepad.")
        self._bold = self._format_button(bold_glyph_icon(), "Bold")
        self._italic = self._format_button(italic_glyph_icon(), "Italic")
        self._underline = self._format_button(underline_glyph_icon(), "Underline")
        self._color_btn = QPushButton(self._header_left)
        style_format_glyph_button(self._color_btn, text_color_glyph_icon(self._color), "Text color")
        self._color_btn.clicked.connect(self._pick_color)
        self._subscript = self._format_button(subscript_glyph_icon(), "Subscript")
        self._superscript = self._format_button(superscript_glyph_icon(), "Superscript")
        self._bullet = self._format_button(bullet_glyph_icon(), "Bulleted list")
        self._number = self._format_button(numbering_glyph_icon(), "Numbered list")
        left.addWidget(size_label)
        left.addWidget(self._size)
        left.addWidget(self._bold)
        left.addWidget(self._italic)
        left.addWidget(self._underline)
        left.addWidget(self._color_btn)
        left.addWidget(self._subscript)
        left.addWidget(self._superscript)
        left.addWidget(self._bullet)
        left.addWidget(self._number)
        left.addStretch(1)

        self._meta = QLabel(self._footer_bar)
        self._meta.hide()

        self._header_right = QWidget(self._footer_bar)
        self._header_right.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        right = QHBoxLayout(self._header_right)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(4)
        right.addStretch(1)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this notepad beside the compound table.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked notepad in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this notepad.")
        self._close_btn.clicked.connect(self._close_notepad)
        style_plot_footer_text_button(self._close_btn)
        right.addWidget(self._add_to_main_btn)
        right.addWidget(self._send_window_btn)
        right.addWidget(self._close_btn)

        foot.addWidget(self._header_left, 1)
        foot.addWidget(self._meta, 0)
        foot.addWidget(self._header_right, 1)
        root.addWidget(self._footer_bar)

        self._edit = _NoteEditor(self)
        root.addWidget(self._edit, 1)
        self._apply_base_font()
        self._refresh_color_glyph()
        self._size.valueChanged.connect(self._on_size_changed)
        self._bold.clicked.connect(self._toggle_bold)
        self._italic.clicked.connect(self._toggle_italic)
        self._underline.clicked.connect(self._toggle_underline)
        self._subscript.clicked.connect(self._toggle_subscript)
        self._superscript.clicked.connect(self._toggle_superscript)
        self._bullet.clicked.connect(self._toggle_bullet)
        self._number.clicked.connect(self._toggle_numbering)
        self._edit.textChanged.connect(self._notify_changed)
        self._edit.cursorPositionChanged.connect(self._sync_format_buttons)
        self._edit.selectionChanged.connect(self._sync_format_buttons)
        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())

    def _format_button(self, icon, tooltip: str) -> QPushButton:
        btn = QPushButton(self._header_left)
        style_format_glyph_button(btn, icon, tooltip, checkable=True)
        return btn

    def rebind_parent_app(self, parent_app: Any) -> None:
        self.parent_app = parent_app
        self._app = parent_app

    def embedded_minimum_width(self) -> int:
        return 420

    def embedded_preferred_width(self) -> int:
        return 480

    def floating_content_minimum_width(self) -> int:
        """Width needed for the format bar and dock chrome without clipping."""
        return floating_browser_minimum_width(self, floor=self.embedded_minimum_width())

    def event(self, event) -> bool:  # noqa: N802 — Qt API name
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def text(self) -> str:
        return self._edit.toPlainText()

    def html(self) -> str:
        return self._edit.toHtml()

    def font_pt(self) -> int:
        return int(self._size.value())

    def color_hex(self) -> str:
        return self._color.name()

    def set_text(self, text: str) -> None:
        self._edit.blockSignals(True)
        try:
            self._edit.setPlainText(text)
        finally:
            self._edit.blockSignals(False)

    def set_html(self, html: str) -> None:
        self._edit.blockSignals(True)
        try:
            self._edit.setHtml(html)
        finally:
            self._edit.blockSignals(False)

    def set_font_pt(self, pt: int) -> None:
        self._size.blockSignals(True)
        try:
            self._size.setValue(_clamp_pt(pt))
        finally:
            self._size.blockSignals(False)
        self._apply_base_font()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(self.font_pt())
        self._merge_format(fmt, notify=False)

    def set_color(self, color: QColor) -> None:
        """Color the selection, or the whole note when nothing is selected."""
        if not color.isValid():
            return
        self._color = QColor(color)
        self._refresh_color_glyph()
        fmt = QTextCharFormat()
        fmt.setForeground(QBrush(self._color))
        cursor = self._edit.textCursor()
        position = cursor.position()
        anchor = cursor.anchor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.Document)
        cursor.mergeCharFormat(fmt)
        if anchor == position:
            cursor.setPosition(position)
        else:
            cursor.setPosition(anchor)
            cursor.setPosition(position, QTextCursor.KeepAnchor)
        self._edit.setTextCursor(cursor)
        self._edit.mergeCurrentCharFormat(fmt)
        self._sync_format_buttons()

    def reapply_base_font(self, html: str) -> None:
        """Put the notepad font back after an application font or palette change."""
        if self.applying_style:
            return
        self.applying_style = True
        try:
            self._edit.blockSignals(True)
            self._apply_base_font()
            if html and self._edit.toHtml() != html:
                self._edit.setHtml(html)
                self._apply_base_font()
            self._edit.blockSignals(False)
        finally:
            self.applying_style = False

    def reset_contents(self) -> None:
        self._color = QColor(DEFAULT_NOTE_COLOR)
        self.set_text("")
        self._size.blockSignals(True)
        self._size.setValue(DEFAULT_NOTE_PT)
        self._size.blockSignals(False)
        self._apply_base_font()
        self._apply_uniform_format()
        self._refresh_color_glyph()
        self._sync_format_buttons()

    def session_state(self) -> dict:
        text = self.text()
        state = {
            "text": text,
            "font_pt": self.font_pt(),
            "color": self.color_hex(),
            "visible": self._is_showing(),
            "docked": self._is_docked_in_main_window(),
        }
        if text.strip():
            state["html"] = self.html()
        return state

    def apply_session_state(self, payload: dict) -> None:
        self._edit.blockSignals(True)
        self._size.blockSignals(True)
        try:
            self._color = _parse_color(payload.get("color"))
            self._size.setValue(_clamp_pt(payload.get("font_pt")))
            html = payload.get("html")
            text = str(payload.get("text") or "")
            if isinstance(html, str) and html.strip() and text.strip():
                self._edit.setHtml(html)
                self._apply_base_font()
            else:
                self._edit.setPlainText(text)
                self._apply_base_font()
                self._apply_uniform_format()
            self._refresh_color_glyph()
        finally:
            self._edit.blockSignals(False)
            self._size.blockSignals(False)
        self._sync_format_buttons()

    def create_floating_dialog(self, parent_app: Any) -> NotepadDialog:
        """Re-open this notepad in a floating window after it is undocked."""
        self.show()
        return NotepadDialog(parent_app, panel=self)

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _is_showing(self) -> bool:
        if self._is_docked_in_main_window():
            return not self.isHidden()
        dlg = self.window()
        if isinstance(dlg, NotepadDialog):
            return not dlg.isHidden()
        return not self.isHidden()

    def _sync_footer_chrome(self) -> None:
        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), NotepadDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating and not docked)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)
        if floating:
            ensure = getattr(self.window(), "ensure_fits_chrome", None)
            if callable(ensure):
                ensure()

    def _add_to_main_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        dock = getattr(app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, NotepadDialog):
            discard_host_dialog_after_dock(dlg, getattr(app, "session_notepad", None), "dialog")

    def _send_to_new_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        undock = getattr(app, "undock_plot_to_window", None)
        if callable(undock):
            undock(self)

    def _close_notepad(self) -> None:
        """Hide the notepad and keep its text. Docked close does not delete the notes."""
        if self._is_docked_in_main_window():
            self.hide()
            app = self.parent_app
            release = getattr(app, "_release_plot_widget_from_panel_host", None)
            if callable(release):
                release(self, discard=False, sync_chrome=False)
            self.hide()
            if app is not None:
                self.setParent(app)
            self.hide()
            return
        dlg = self.window()
        if isinstance(dlg, NotepadDialog):
            dlg.hide()

    def _base_font(self) -> QFont:
        font = QFont(NOTE_FONT_FAMILY)
        font.setStyleHint(QFont.SansSerif)
        font.setPointSize(self.font_pt())
        return font

    def _apply_base_font(self) -> None:
        font = self._base_font()
        self._edit.setFont(font)
        document = self._edit.document()
        if document is not None:
            document.setDefaultFont(font)

    def _apply_uniform_format(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFont(self._base_font())
        fmt.setForeground(QBrush(self._color))
        cursor = self._edit.textCursor()
        cursor.select(QTextCursor.Document)
        cursor.setCharFormat(fmt)
        self._edit.mergeCurrentCharFormat(fmt)
        cursor.clearSelection()
        self._edit.setTextCursor(cursor)

    def _merge_format(self, fmt: QTextCharFormat, *, notify: bool = True) -> None:
        cursor = self._edit.textCursor()
        if cursor.hasSelection():
            cursor.mergeCharFormat(fmt)
            self._edit.setTextCursor(cursor)
        self._edit.mergeCurrentCharFormat(fmt)
        self._sync_format_buttons()
        if notify:
            self._notify_changed()

    def _refresh_color_glyph(self) -> None:
        style_format_glyph_button(
            self._color_btn,
            text_color_glyph_icon(self._color),
            "Text color",
        )

    def _on_size_changed(self, pt: int) -> None:
        self._apply_base_font()
        fmt = QTextCharFormat()
        fmt.setFontPointSize(_clamp_pt(pt))
        self._merge_format(fmt)

    def _toggle_bold(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontWeight(QFont.Bold if self._bold.isChecked() else QFont.Normal)
        self._merge_format(fmt)

    def _toggle_italic(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontItalic(self._italic.isChecked())
        self._merge_format(fmt)

    def _toggle_underline(self) -> None:
        fmt = QTextCharFormat()
        fmt.setFontUnderline(self._underline.isChecked())
        self._merge_format(fmt)

    def _toggle_subscript(self) -> None:
        fmt = QTextCharFormat()
        alignment = (
            QTextCharFormat.AlignSubScript
            if self._subscript.isChecked()
            else QTextCharFormat.AlignNormal
        )
        fmt.setVerticalAlignment(alignment)
        self._merge_format(fmt)

    def _toggle_superscript(self) -> None:
        fmt = QTextCharFormat()
        alignment = (
            QTextCharFormat.AlignSuperScript
            if self._superscript.isChecked()
            else QTextCharFormat.AlignNormal
        )
        fmt.setVerticalAlignment(alignment)
        self._merge_format(fmt)

    def _toggle_bullet(self) -> None:
        self._apply_list(QTextListFormat.ListDisc, enable=self._bullet.isChecked())

    def _toggle_numbering(self) -> None:
        self._apply_list(QTextListFormat.ListDecimal, enable=self._number.isChecked())

    def _apply_list(self, style: QTextListFormat.Style, *, enable: bool) -> None:
        """Turn the current paragraphs into a list, or take them back out of one."""
        cursor = self._edit.textCursor()
        if enable:
            fmt = QTextListFormat()
            fmt.setStyle(style)
            current = cursor.currentList()
            if current is not None:
                fmt.setIndent(max(1, int(current.format().indent())))
            cursor.createList(fmt)
        else:
            self._remove_lists(cursor)
        self._sync_format_buttons()
        self._notify_changed()

    def _remove_lists(self, cursor: QTextCursor) -> None:
        blocks = _blocks_touched_by_cursor(self._edit, cursor)
        cursor.beginEditBlock()
        try:
            for block in blocks:
                text_list = block.textList()
                if text_list is not None:
                    text_list.remove(block)
        finally:
            cursor.endEditBlock()

    def _pick_color(self) -> None:
        cursor = self._edit.textCursor()
        chosen = QColorDialog.getColor(self._color, self.window(), "Text color")
        if not chosen.isValid():
            return
        self._edit.setTextCursor(cursor)
        self.set_color(chosen)
        self._notify_changed()

    def _sync_format_buttons(self) -> None:
        if self._format_syncing:
            return
        self._format_syncing = True
        try:
            fmt = self._edit.currentCharFormat()
            align = fmt.verticalAlignment()
            text_list = self._edit.textCursor().currentList()
            list_style = text_list.format().style() if text_list is not None else None
            for btn, checked in (
                (self._bold, fmt.fontWeight() >= QFont.Bold),
                (self._italic, fmt.fontItalic()),
                (self._underline, fmt.fontUnderline()),
                (self._subscript, align == QTextCharFormat.AlignSubScript),
                (self._superscript, align == QTextCharFormat.AlignSuperScript),
                (self._bullet, list_style == QTextListFormat.ListDisc),
                (self._number, list_style == QTextListFormat.ListDecimal),
            ):
                btn.blockSignals(True)
                btn.setChecked(checked)
                btn.blockSignals(False)
            point = fmt.fontPointSize()
            if point > 0:
                self._size.blockSignals(True)
                self._size.setValue(_clamp_pt(round(point)))
                self._size.blockSignals(False)
            brush = fmt.foreground()
            if brush.style() != Qt.NoBrush and brush.color().isValid():
                color = brush.color()
                if color.name() != self._color.name():
                    self._color = QColor(color)
                    self._refresh_color_glyph()
        finally:
            self._format_syncing = False

    def _notify_changed(self) -> None:
        app = self.parent_app
        if app is not None:
            _mark_notepad_dirty(app)


class NotepadDialog(BrowserHostDialog):
    """Floating window that hosts :class:`NotepadWidget`."""

    default_title = "Notepad"
    panel_cls = NotepadWidget
    fit_chrome = True
    close_title = "Close Notepad"
    close_message = "Close this notepad?"
    min_size = (420, 320)
    initial_size = (480, 420)


def _ensure_notepad(host: SessionNotepadHost) -> NotepadWidget:
    panel = _live(host.panel)
    if panel is not None:
        return panel
    dlg = NotepadDialog(host._app)
    host.dialog = dlg
    host.panel = dlg._panel
    prepare = getattr(host._app, "_prepare_tool_dialog", None)
    if callable(prepare):
        prepare(dlg)
    return host.panel


class SessionNotepadHost:
    """One notepad for the main window, saved and restored with the session."""

    def __init__(self, app: Any) -> None:
        self._app = app
        self.dialog: NotepadDialog | None = None
        self.panel: NotepadWidget | None = None

    def open_notepad(self) -> None:
        """Show the notepad in a floating window, or focus it if it is already docked."""
        panel = _ensure_notepad(self)
        label = getattr(self._app, "status_label", None)
        if panel._is_docked_in_main_window():
            show = getattr(self._app, "show_docked_plot_panel", None)
            if callable(show):
                show()
            panel.show()
            panel.raise_()
            if label is not None:
                label.setText("Notepad")
            return
        dlg = panel.window()
        if not isinstance(dlg, NotepadDialog) or getattr(dlg, "_panel", None) is not panel:
            dlg = panel.create_floating_dialog(self._app)
            prepare = getattr(self._app, "_prepare_tool_dialog", None)
            if callable(prepare):
                prepare(dlg)
        self.dialog = dlg
        self.panel = panel
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        if label is not None:
            label.setText("Notepad")

    def clear_notepad(self) -> None:
        panel = _live(self.panel)
        if panel is None:
            self.dialog = None
            self.panel = None
            return
        panel.reset_contents()
        if panel._is_docked_in_main_window():
            panel.hide()
            release = getattr(self._app, "_release_plot_widget_from_panel_host", None)
            if callable(release):
                release(panel, discard=False, sync_chrome=False)
            panel.hide()
            panel.setParent(self._app)
            panel.hide()
        _hide_notepad_panel(panel)

    def collect_notepad_session(self) -> dict | None:
        panel = _live(self.panel)
        if panel is None:
            return None
        payload = panel.session_state()
        untouched = (
            not str(payload.get("text") or "").strip()
            and not payload.get("visible")
            and payload.get("font_pt") == DEFAULT_NOTE_PT
            and payload.get("color") == DEFAULT_NOTE_COLOR
            and not payload.get("docked")
        )
        if untouched:
            return None
        return payload

    def restore_notepad_session(self, payload: object | None) -> None:
        if not isinstance(payload, dict):
            self.clear_notepad()
            return
        panel = _ensure_notepad(self)
        panel.apply_session_state(payload)
        if not payload.get("visible", True):
            _hide_notepad_panel(panel)
            return
        if payload.get("docked"):
            dock = getattr(self._app, "dock_plot_widget", None)
            dlg = panel.window()
            if callable(dock) and dock(panel):
                if isinstance(dlg, NotepadDialog):
                    discard_host_dialog_after_dock(dlg, self, "dialog")
                return
        self.open_notepad()


def _hide_notepad_panel(panel: NotepadWidget) -> None:
    dlg = panel.window()
    if isinstance(dlg, NotepadDialog):
        dlg.hide()
    else:
        panel.hide()
