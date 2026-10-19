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

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QApplication, QSizePolicy, QVBoxLayout, QWidget

from molmanager.ui.main_window.plot_pane import PlotPane


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def test_live_presize_marks_hidden_pages_stale(qapp):
    del qapp
    pane = PlotPane("test_pane")
    pane.resize(400, 300)
    pages = [QWidget() for _ in range(3)]
    for page in pages:
        pane.add_plot_widget(page)
    pane._stack.setCurrentWidget(pages[1])
    pane._presize_stack_pages(live_only=True)
    assert id(pages[0]) in pane._stale_pages
    assert id(pages[2]) in pane._stale_pages
    assert id(pages[1]) not in pane._stale_pages


def test_presize_keeps_figure_inside_layout_margins(qapp):
    """The figure keeps the layout content box, not the stack rectangle.

    Pinning the web view to the stack size and letting the layout pull it back
    is the small resize on dock, undock, and paging.
    """
    pane = PlotPane("margins")
    pane.resize(480, 360)
    pane.show()
    qapp.processEvents()
    page = QWidget()
    layout = QVBoxLayout(page)
    layout.setContentsMargins(2, 0, 2, 2)
    layout.setSpacing(0)
    surface = QWidget()
    surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    layout.addWidget(surface, 1)
    pane.add_plot_widget(page)
    qapp.processEvents()
    assert surface.width() == page.width() - 4
    assert surface.height() == page.height() - 2

    other = QWidget()
    other_layout = QVBoxLayout(other)
    other_layout.setContentsMargins(2, 0, 2, 2)
    other_layout.setSpacing(0)
    other_surface = QWidget()
    other_surface.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    other_layout.addWidget(other_surface, 1)
    pane.add_plot_widget(other)
    held = (surface.width(), surface.height())
    pane.show_previous_page()
    qapp.processEvents()
    assert (surface.width(), surface.height()) == held


def test_stale_presize_before_page_switch(qapp):
    del qapp
    pane = PlotPane("test_pane2")
    pane.resize(400, 300)
    a, b = QWidget(), QWidget()
    pane.add_plot_widget(a)
    pane.add_plot_widget(b)
    pane._stale_pages.add(id(b))
    pane.show_next_page()
    assert id(b) not in pane._stale_pages
