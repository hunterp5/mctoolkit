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

"""Help → Citations: papers and licenses for tools used in MolManager."""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont, QPalette
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QTextBrowser,
)

from ..reference.citations_catalog import (
    CITATION_SECTIONS,
    iter_tool_citations,
    tool_citation,
    tool_citation_html_fragment,
)
from .qt_widget_utils import make_window_resizable
from .user_guides import _guide_style_sheet

if TYPE_CHECKING:
    from PyQt5.QtWidgets import QWidget


def _first_tool_id() -> str:
    tools = iter_tool_citations()
    return tools[0].tool_id if tools else "molmanager"


def citation_html(tool_id: str, palette: QPalette | None = None) -> str:
    """Return a full HTML document for one catalog entry."""
    tool = tool_citation(tool_id)
    if tool is None:
        body = f"<h1>Unknown citation</h1><p>No catalog entry for <code>{tool_id}</code>.</p>"
    else:
        body = tool_citation_html_fragment(tool)
    style = _guide_style_sheet(palette)
    return f"<html><head><style>{style}</style></head><body>{body}</body></html>"


def _populate_citation_list(lst: QListWidget, *, select_tool_id: str | None = None) -> None:
    lst.clear()
    select_row = 0
    row = 0
    header_font = QFont(lst.font())
    header_font.setBold(True)

    for section in CITATION_SECTIONS:
        header = QListWidgetItem(section.title)
        header.setFlags(Qt.NoItemFlags)
        header.setFont(header_font)
        header.setForeground(lst.palette().mid())
        lst.addItem(header)
        row += 1

        for tool in section.tools:
            it = QListWidgetItem(tool.name)
            it.setData(Qt.UserRole, tool.tool_id)
            it.setToolTip(tool.used_in)
            lst.addItem(it)
            if select_tool_id and tool.tool_id == select_tool_id:
                select_row = row
            row += 1

    lst.setCurrentRow(select_row)


def open_citations_dialog(parent: QWidget | None, tool_id: str | None = None) -> None:
    """Open the citations browser (modeless). Reuses an existing window when possible."""
    topic = (tool_id or "").strip() or _first_tool_id()
    if tool_citation(topic) is None:
        topic = _first_tool_id()
    host = parent
    dlg = getattr(host, "_citations_dialog", None) if host is not None else None
    if dlg is not None:
        try:
            _show_citations_dialog(dlg, topic)
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            return
        except RuntimeError:
            if host is not None:
                host._citations_dialog = None

    dlg = QDialog(parent)
    dlg.setWindowTitle("MolManager — Citations")
    dlg.resize(900, 620)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)

    content = QHBoxLayout(dlg)
    lst = QListWidget()
    lst.setMinimumWidth(280)
    _populate_citation_list(lst, select_tool_id=topic)

    browser = QTextBrowser()
    browser.setOpenExternalLinks(True)
    content.addWidget(lst)
    content.addWidget(browser, 1)

    dlg._citation_list = lst  # type: ignore[attr-defined]
    dlg._citation_browser = browser  # type: ignore[attr-defined]

    def on_pick(current: QListWidgetItem | None, _previous: QListWidgetItem | None = None) -> None:
        if current is None:
            return
        tid = current.data(Qt.UserRole)
        if isinstance(tid, str):
            _show_citations_dialog(dlg, tid)

    lst.currentItemChanged.connect(on_pick)
    make_window_resizable(dlg)

    if host is not None:
        host._citations_dialog = dlg
        # Hold the host weakly: a strong capture here makes host and dialog a reference
        # cycle, and the cyclic collector frees them in an order that can delete the Qt
        # parent before the child wrapper, crashing the interpreter.
        host_ref = weakref.ref(host)

        def forget_dialog(*_args: object) -> None:
            owner = host_ref()
            if owner is not None:
                owner._citations_dialog = None

        dlg.destroyed.connect(forget_dialog)

    _show_citations_dialog(dlg, topic)
    dlg.show()
    dlg.raise_()
    dlg.activateWindow()


def _show_citations_dialog(dlg: QDialog, tool_id: str) -> None:
    lst = getattr(dlg, "_citation_list", None)
    browser = getattr(dlg, "_citation_browser", None)
    tool = tool_citation(tool_id)
    if browser is not None:
        pal = dlg.palette() if QApplication.instance() is not None else None
        browser.setHtml(citation_html(tool_id, pal))
    if tool is not None:
        dlg.setWindowTitle(f"MolManager — Citations: {tool.name}")
    else:
        dlg.setWindowTitle("MolManager — Citations")
    if lst is not None:
        for i in range(lst.count()):
            it = lst.item(i)
            if it is not None and it.data(Qt.UserRole) == tool_id:
                lst.setCurrentRow(i)
                break
