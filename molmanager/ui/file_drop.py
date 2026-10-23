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

"""Drop a single table file or ``.cms`` session onto an empty workspace to open it."""

from __future__ import annotations

import os
from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QWidget

from ..table.table_file_formats import is_openable_table_path
from .strings import LOADING_DETAIL_DROP, LOADING_DETAIL_IDLE

_DROP_HOVER_STYLE = "#idleFileDropPage { border: 2px dashed palette(mid); }"


def file_drop_kind(path: str) -> str | None:
    """``session`` for ``.cms``, ``file`` for an Open-dialog table type, otherwise None."""
    if Path(path).suffix.lower() == ".cms":
        return "session"
    if is_openable_table_path(path):
        return "file"
    return None


def single_local_drop_path(mime) -> str | None:
    """The one local file in a drop, or None when the drop is not a single file."""
    if mime is None or not mime.hasUrls():
        return None
    urls = mime.urls()
    if len(urls) != 1:
        return None
    url = urls[0]
    if not url.isLocalFile():
        return None
    path = url.toLocalFile()
    if not path:
        return None
    # Qt yields ``C:/...``; the file dialog stores a native path.
    path = os.path.abspath(path)
    if os.path.isdir(path):
        return None
    return path


def window_is_empty_for_file_drop(window) -> bool:
    """True on the idle cover, including while a valid file is hovering over it."""
    if bool(getattr(window, "_ingest_loading", False)):
        return False
    if bool(getattr(window, "_session_awaiting_ready", False)):
        return False
    stack = getattr(window, "_table_stack", None)
    detail = getattr(window, "_loading_detail", None)
    if stack is None or detail is None:
        return False
    try:
        on_cover = int(stack.currentIndex()) == 0
        text = detail.text()
    except RuntimeError:
        return False
    return on_cover and text in (LOADING_DETAIL_IDLE, LOADING_DETAIL_DROP)


def set_file_drop_hover(window, on: bool) -> None:
    """Show or clear the idle-page hint while a file is dragged over the window."""
    if bool(getattr(window, "_file_drop_hover", False)) == bool(on):
        return
    window._file_drop_hover = bool(on)
    detail = getattr(window, "_loading_detail", None)
    page = getattr(window, "_loading_page", None)
    if detail is None or page is None:
        return
    try:
        if on:
            if detail.text() == LOADING_DETAIL_IDLE:
                detail.setText(LOADING_DETAIL_DROP)
            page.setStyleSheet(_DROP_HOVER_STYLE)
        else:
            if detail.text() == LOADING_DETAIL_DROP:
                detail.setText(LOADING_DETAIL_IDLE)
            page.setStyleSheet("")
    except RuntimeError:
        return


def _accept_file_drag(window, event) -> bool:
    if window_is_empty_for_file_drop(window):
        path = single_local_drop_path(event.mimeData())
    else:
        path = None
    if path is None or file_drop_kind(path) is None:
        event.ignore()
        return False
    event.setDropAction(Qt.CopyAction)
    event.accept()
    return True


def handle_file_drag_enter(window, event) -> None:
    set_file_drop_hover(window, _accept_file_drag(window, event))


def handle_file_drag_move(window, event) -> None:
    set_file_drop_hover(window, _accept_file_drag(window, event))


def handle_file_drag_leave(window, event) -> None:
    set_file_drop_hover(window, False)
    event.accept()


def handle_file_drop(window, event) -> None:
    """Open the dropped file. DragLeave runs before Drop on Windows, so hover is not the gate."""
    ready = window_is_empty_for_file_drop(window)
    path = single_local_drop_path(event.mimeData()) if ready else None
    kind = file_drop_kind(path) if path else None
    set_file_drop_hover(window, False)
    if path is None or kind is None:
        event.ignore()
        return
    event.setDropAction(Qt.CopyAction)
    event.accept()
    if kind == "session":
        window.apply_saved_session_from_file(path)
        return
    window.load_file(path)


class IdleFileDropPage(QWidget):
    """Idle cover. Qt delivers a drop to the nearest ancestor that accepts drops.

    The label in the middle of this page does not accept drops, so a file released
    on that text lands here. ``ChemistryWorkspaceWindow`` accepts drops too, for the
    menu bar and for an occupied workspace (those are ignored).
    """

    def __init__(self, host: QWidget) -> None:
        super().__init__()
        self._host = host
        self.setObjectName("idleFileDropPage")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_file_drag_enter(self._host, event)

    def dragMoveEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_file_drag_move(self._host, event)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_file_drag_leave(self._host, event)

    def dropEvent(self, event) -> None:  # noqa: N802 — Qt API name
        handle_file_drop(self._host, event)
