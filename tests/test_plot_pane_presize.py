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

from PyQt5.QtWidgets import QApplication, QStackedWidget, QVBoxLayout, QWidget

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
