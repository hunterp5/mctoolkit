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

"""Tests for multi-pane workspace layout presets and docking into panes."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from PyQt5.QtWidgets import QApplication, QLabel, QWidget

from molmanager.ui.main_window.workspace_layout import (
    DEFAULT_LAYOUT_ID,
    LAYOUT_QUADRANTS,
    LAYOUT_TABLE_GRID,
    LAYOUT_TABLE_ONLY,
    LAYOUT_TABLE_SIDE,
    LAYOUT_TABLE_SINGLE,
    LAYOUT_TABLE_STACK,
    PlotPane,
    WorkspaceLayoutManager,
)


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


def _manager(qapp) -> WorkspaceLayoutManager:
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    return mgr


def test_default_layout_is_table_only(qapp):
    del qapp
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    assert mgr.layout_id == DEFAULT_LAYOUT_ID == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert mgr._workspace_root is not None
    assert mgr.isAncestorOf(table)


def test_apply_layout_pane_counts(qapp):
    mgr = _manager(qapp)
    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
    assert len(mgr.plot_panes()) == 0
    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 1
    mgr.apply_layout(LAYOUT_TABLE_SIDE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 2
    mgr.apply_layout(LAYOUT_QUADRANTS, preserve_plots=False)
    assert len(mgr.plot_panes()) == 3
    mgr.apply_layout(LAYOUT_TABLE_GRID, preserve_plots=False)
    assert len(mgr.plot_panes()) == 5
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    assert len(mgr.plot_panes()) == 2


def test_apply_layout_same_id_is_noop(qapp):
    mgr = _manager(qapp)
    panes = mgr.plot_panes()
    widget = QLabel("keep")
    mgr.dock_into_pane(panes[0], widget)
    extras = mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=True)
    assert extras == []
    assert mgr.plot_panes() == panes
    assert panes[0].plot_widget() is widget


def _assert_equal_splitter_pair(splitter) -> None:
    sizes = [int(s) for s in splitter.sizes()]
    assert len(sizes) == 2
    assert sizes[0] > 40
    assert sizes[1] > 40
    assert abs(sizes[0] - sizes[1]) <= max(2, int(splitter.handleWidth()))


def test_quadrants_are_equal_sized(qapp):
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    mgr.apply_layout(LAYOUT_QUADRANTS, preserve_plots=False)
    mgr.resize(900, 700)
    mgr.show()
    qapp.processEvents()
    assert len(mgr.plot_panes()) == 3
    assert len(mgr._splitters) == 3
    for splitter in mgr._splitters:
        _assert_equal_splitter_pair(splitter)


def test_quadrants_restore_keeps_saved_splitter_ratios(qapp):
    table = QWidget()
    mgr = WorkspaceLayoutManager(table)
    mgr.apply_layout(LAYOUT_QUADRANTS, preserve_plots=False)
    mgr.resize(900, 700)
    mgr.show()
    qapp.processEvents()
    top = mgr._splitters[1]
    top.setSizes([620, 280])
    qapp.processEvents()
    payload = mgr.collect_splitter_sizes()
    mgr.apply_layout(LAYOUT_QUADRANTS, preserve_plots=False)
    mgr.restore_splitter_sizes(payload)
    mgr.resize(900, 700)
    qapp.processEvents()
    sizes = [int(s) for s in mgr._splitters[1].sizes()]
    assert sizes[0] > sizes[1] + 80


def test_table_only_releases_all_plots(qapp):
    mgr = _manager(qapp)
    w0 = QLabel("a")
    w1 = QLabel("b")
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    extras = mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=True)
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert set(extras) == {w0, w1}
    assert mgr.preferred_pane() is None


def test_dock_into_pane_and_release(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    widget = QLabel("plot")
    prev = mgr.dock_into_pane(pane, widget)
    assert prev is None
    assert pane.plot_widget() is widget
    assert not pane.is_empty()
    assert mgr.pane_for_widget(widget) is pane
    assert list(mgr.iter_docked_widgets()) == [widget]
    assert mgr.release_widget(widget) is True
    assert pane.is_empty()


def test_apply_layout_preserves_plots_and_returns_extras(qapp):
    mgr = _manager(qapp)
    w0 = QLabel("a")
    w1 = QLabel("b")
    w2 = QLabel("c")
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    # Stack has 2 panes; add a third logically by switching to single after 3 docks on stack
    # First expand to side (2), then we only have 2. Use stack with 2, switch to single → 1 extra.
    extras = mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=True)
    assert len(mgr.plot_panes()) == 1
    assert mgr.plot_panes()[0].plot_widget() is w0
    assert extras == [w1]
    # Re-dock leftover and another, then go to single again from stack with 2
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=True)
    assert len(mgr.plot_panes()) == 2
    mgr.dock_into_pane(mgr.plot_panes()[0], w0)
    mgr.dock_into_pane(mgr.plot_panes()[1], w1)
    # Can't fit w2 on stack; simulate three kept by manually calling with three
    # via temporary side layout then adding third through apply from a custom keep list:
    mgr.dock_into_pane(mgr.plot_panes()[0], w2)
    # Now panes hold w2 and w1; apply single keeps first only
    extras2 = mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=True)
    assert mgr.plot_panes()[0].plot_widget() is w2
    assert w1 in extras2


def test_splitter_size_roundtrip(qapp):
    mgr = _manager(qapp)
    payload = mgr.collect_splitter_sizes()
    assert payload["layout_id"] == LAYOUT_TABLE_STACK
    assert "sizes" in payload
    assert "ratios" in payload
    assert "preferred_pane_id" in payload
    mgr.apply_layout(LAYOUT_TABLE_SIDE, preserve_plots=False)
    mgr.restore_splitter_sizes(payload)  # different layout; sizes keys may not match count
    payload2 = mgr.collect_splitter_sizes()
    mgr.restore_splitter_sizes(payload2)
    assert mgr.collect_splitter_sizes()["layout_id"] == LAYOUT_TABLE_SIDE


def test_preferred_pane_tracks_activation(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    mgr.set_preferred_pane(p1)
    assert mgr.preferred_pane() is p1
    mgr.dock_into_pane(p0, QLabel("x"))
    assert mgr.preferred_pane() is p0


def test_dock_appends_and_paginates_in_same_pane(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w0 = QLabel("first")
    w0._window_title = "Alpha"
    w1 = QLabel("second")
    w1._window_title = "Beta"
    mgr.dock_into_pane(pane, w0)
    mgr.dock_into_pane(pane, w1)
    assert pane.plot_widgets() == [w0, w1]
    assert pane.plot_widget() is w1
    assert pane.page_count() == 2
    assert pane.page_index() == 1
    assert not pane._pager.isHidden()
    assert not pane._header.isHidden()
    assert pane._pager.parentWidget() is pane._header
    nav_ly = pane._nav_host.layout()
    assert nav_ly.indexOf(pane._prev_btn) == 0
    assert nav_ly.indexOf(pane._next_btn) == 1
    assert nav_ly.indexOf(pane._title_edit) == 2
    assert pane._title_edit.text() == "Beta"
    assert "2/2" in pane._page_label.text()
    assert pane.display_title() == "Beta"
    pane.show_previous_page()
    assert pane.plot_widget() is w0
    assert pane.page_index() == 0
    pane.show_next_page()
    assert pane.plot_widget() is w1
    assert mgr.pane_for_widget(w0) is pane
    assert list(mgr.iter_docked_widgets()) == [w0, w1]


def test_reorder_arrows_move_current_plot_in_pane(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w0 = QLabel("first")
    w0._window_title = "Alpha"
    w1 = QLabel("second")
    w1._window_title = "Beta"
    w2 = QLabel("third")
    w2._window_title = "Gamma"
    mgr.dock_into_pane(pane, w0)
    mgr.dock_into_pane(pane, w1)
    mgr.dock_into_pane(pane, w2)
    assert pane.plot_widgets() == [w0, w1, w2]
    assert pane.page_index() == 2
    assert "3/3" in pane._page_label.text()
    assert pane._move_earlier_btn.isEnabled()
    assert not pane._move_later_btn.isEnabled()

    pane.move_current_page_later()
    assert pane.plot_widgets() == [w0, w1, w2]
    assert pane.plot_widget() is w2

    pane.move_current_page_earlier()
    assert pane.plot_widgets() == [w0, w2, w1]
    assert pane.plot_widget() is w2
    assert pane.page_index() == 1
    assert "2/3" in pane._page_label.text()
    assert pane._title_edit.text() == "Gamma"
    assert pane._move_earlier_btn.isEnabled()
    assert pane._move_later_btn.isEnabled()

    pane.move_current_page_earlier()
    assert pane.plot_widgets() == [w2, w0, w1]
    assert pane.plot_widget() is w2
    assert pane.page_index() == 0
    assert "1/3" in pane._page_label.text()
    assert not pane._move_earlier_btn.isEnabled()
    assert pane._move_later_btn.isEnabled()
    assert [pane._stack.widget(i) for i in range(pane._stack.count())] == [w2, w0, w1]

    pane.move_current_page_earlier()
    assert pane.plot_widgets() == [w2, w0, w1]
    assert pane.page_index() == 0


def test_release_one_page_keeps_the_other(qapp):
    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w0 = QLabel("a")
    w1 = QLabel("b")
    mgr.dock_into_pane(pane, w0)
    mgr.dock_into_pane(pane, w1)
    assert mgr.release_widget(w1) is True
    assert pane.plot_widget() is w0
    assert pane.page_count() == 1
    assert pane.plot_widgets() == [w0]
    assert not pane.is_empty()
    assert pane._prev_btn.isHidden()
    assert pane._next_btn.isHidden()
    assert pane._move_earlier_btn.isHidden()
    assert pane._move_later_btn.isHidden()
    assert pane._title_edit.text() == pane.display_title()


def test_plot_pane_header_adopts_dock_chrome_buttons(qapp):
    from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    host = QWidget()
    root = QVBoxLayout(host)
    footer = QWidget(host)
    host._footer_bar = footer
    foot = QHBoxLayout(footer)
    host._opts_btn = QPushButton("Plot Options")
    host._send_window_btn = QPushButton("Send to New Window")
    host._close_plot_btn = QPushButton("Close")
    host._clear_sel_btn = QPushButton("Clear Selection")
    for btn in (
        host._opts_btn,
        host._send_window_btn,
        host._close_plot_btn,
        host._clear_sel_btn,
    ):
        foot.addWidget(btn)
    root.addWidget(footer)

    def _sync_footer_chrome() -> None:
        host._send_window_btn.setVisible(True)
        host._close_plot_btn.setVisible(True)

    host._sync_footer_chrome = _sync_footer_chrome
    mgr.dock_into_pane(pane, host)
    assert host._opts_btn.parentWidget() is pane._leading_opts_host
    assert host._clear_sel_btn.parentWidget() is pane._leading_opts_host
    assert host._send_window_btn.parentWidget() is pane._send_host
    assert host._close_plot_btn.parentWidget() is pane._trailing_close_host
    assert pane._close_btn.parentWidget() is pane._header_right
    assert footer.isHidden()
    assert pane._prev_btn.isHidden()

    # Header order: left strip | pager | right strip (pager stays pane-centered)
    header_ly = pane._header.layout()
    left_idx = header_ly.indexOf(pane._header_left)
    nav_idx = header_ly.indexOf(pane._nav_host)
    right_idx = header_ly.indexOf(pane._header_right)
    assert left_idx >= 0 and nav_idx == left_idx + 1 and right_idx == nav_idx + 1
    left_ly = pane._header_left.layout()
    assert left_ly.indexOf(pane._leading_opts_host) == 0
    assert left_ly.indexOf(pane._chrome_host) == 1
    leading_ly = pane._leading_opts_ly
    assert leading_ly.indexOf(host._opts_btn) == 0
    assert leading_ly.indexOf(host._clear_sel_btn) == 1
    right_ly = pane._header_right.layout()
    send_idx = right_ly.indexOf(pane._send_host)
    trailing_idx = right_ly.indexOf(pane._trailing_close_host)
    close_idx = right_ly.indexOf(pane._close_btn)
    assert send_idx >= 0 and trailing_idx == send_idx + 1 and close_idx == trailing_idx + 1

    mgr.release_widget(host)
    assert host._opts_btn.parentWidget() is footer
    assert host._send_window_btn.parentWidget() is footer
    assert host._close_plot_btn.parentWidget() is footer
    assert not footer.isHidden()


def test_plot_pane_title_double_click_renames(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent

    mgr = _manager(qapp)
    pane = mgr.plot_panes()[0]
    w = QLabel("plot")
    w._window_title = "Original"
    mgr.dock_into_pane(pane, w)
    assert pane._title_edit.text() == "Original"
    assert pane._title_edit.isReadOnly()

    pos = QPoint(4, 4)
    dbl = QMouseEvent(
        QEvent.MouseButtonDblClick,
        pos,
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    pane.eventFilter(pane._title_edit, dbl)
    assert not pane._title_edit.isReadOnly()
    pane._title_edit.setText("Custom Name")
    pane._commit_title_edit()
    assert pane._title_edit.isReadOnly()
    assert pane.display_title() == "Custom Name"
    assert w._window_title == "Original"
    assert getattr(w, "_pane_display_title") == "Custom Name"


def test_move_widget_between_panes_keeps_other_pages(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    a = QLabel("a")
    b = QLabel("b")
    c = QLabel("c")
    mgr.dock_into_pane(p0, a)
    mgr.dock_into_pane(p0, b)
    mgr.dock_into_pane(p1, c)
    mgr.dock_into_pane(p1, b)
    assert p0.plot_widgets() == [a]
    assert p1.plot_widgets() == [c, b]
    assert p1.plot_widget() is b


def test_plot_pane_has_close_button(qapp):
    del qapp
    pane = PlotPane("pane_test")
    assert pane._close_btn.text() == ""
    assert not pane._close_btn.icon().isNull()
    assert pane._prev_btn.text() == ""
    assert not pane._prev_btn.icon().isNull()
    assert not pane._next_btn.icon().isNull()


def test_activate_filter_skips_webengine_descendants(qapp, monkeypatch):
    from molmanager.ui.main_window import plot_pane as plot_pane_mod

    class FakeWeb(QWidget):
        pass

    monkeypatch.setattr(plot_pane_mod, "_web_engine_view_type", lambda: FakeWeb)
    root = QWidget()
    chrome = QLabel("chrome", root)
    web = FakeWeb(root)
    inner = QLabel("chromium", web)
    targets = list(plot_pane_mod._iter_activate_filter_widgets(root))
    assert root in targets
    assert chrome in targets
    assert web in targets
    assert inner not in targets


def test_remove_pane_reduces_pane_count(qapp):
    mgr = _manager(qapp)
    assert len(mgr.plot_panes()) == 2
    p0, p1 = mgr.plot_panes()
    surviving = QLabel("keep")
    mgr.dock_into_pane(p0, surviving)
    assert mgr.remove_pane(p1) is True
    assert mgr.plot_panes() == [p0]
    assert p1 not in mgr.plot_panes()
    assert mgr.layout_id == LAYOUT_TABLE_SINGLE
    assert mgr.session_layout_id() == LAYOUT_TABLE_SINGLE
    assert p0.plot_widget() is surviving
    assert surviving.parentWidget() is not None


def test_session_layout_id_canonicalizes_leftover_single_pane(qapp):
    mgr = _manager(qapp)
    assert mgr.layout_id == LAYOUT_TABLE_STACK
    mgr._panes.pop()
    assert len(mgr.plot_panes()) == 1
    assert mgr.session_layout_id() == LAYOUT_TABLE_SINGLE
    payload = mgr.collect_splitter_sizes()
    assert payload["layout_id"] == LAYOUT_TABLE_SINGLE


def test_remove_last_pane_switches_to_table_only(qapp):
    mgr = _manager(qapp)
    table = mgr._table_area
    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 1
    p0 = mgr.plot_panes()[0]
    assert mgr.remove_pane(p0) is True
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert table.parentWidget() is not None
    assert table.parentWidget() is not table
    # Table must stay nested under a host; promoting it to workspace root breaks layouts.
    assert mgr._workspace_root is not table
    assert mgr.isAncestorOf(table)


def test_layout_roundtrip_clears_plot_panes(qapp):
    mgr = _manager(qapp)
    table = mgr._table_area
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    mgr.dock_into_pane(mgr.plot_panes()[0], QLabel("a"))
    mgr.dock_into_pane(mgr.plot_panes()[1], QLabel("b"))
    extras = mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=True)
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert len(extras) == 2
    assert mgr._workspace_root is not table
    assert mgr.isAncestorOf(table)
    # Collapse via pane close, then picker-style layout changes must stay robust.
    mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=False)
    assert mgr.remove_pane(mgr.plot_panes()[1]) is True
    assert mgr.remove_pane(mgr.plot_panes()[0]) is True
    assert mgr._workspace_root is not table
    mgr.apply_layout(LAYOUT_TABLE_SIDE, preserve_plots=False)
    assert len(mgr.plot_panes()) == 2
    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=True)
    assert mgr.plot_panes() == []
    assert mgr._workspace_root is not table


def test_table_only_after_split_reclaims_full_width(qapp):
    """table_only → split → table_only must drop splitters and give the table full span."""
    from PyQt5.QtWidgets import QSplitter

    mgr = _manager(qapp)
    mgr.resize(1000, 700)
    mgr.show()
    qapp.processEvents()
    table = mgr._table_area

    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
    qapp.processEvents()
    assert table.width() == mgr.width()

    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    qapp.processEvents()
    assert len(mgr.plot_panes()) == 1
    assert isinstance(mgr._workspace_root, QSplitter)
    assert table.width() < mgr.width() - 50

    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=True)
    qapp.processEvents()
    assert mgr.layout_id == LAYOUT_TABLE_ONLY
    assert mgr.plot_panes() == []
    assert mgr._splitters == []
    assert not isinstance(mgr._workspace_root, QSplitter)
    assert mgr.findChildren(QSplitter) == []
    assert table.width() == mgr.width()
    assert mgr._layout_tree_matches(LAYOUT_TABLE_ONLY)


def test_table_only_early_out_requires_non_splitter_root(qapp):
    """Stale splitter trees labeled table_only must still rebuild."""
    from PyQt5.QtWidgets import QSplitter

    mgr = _manager(qapp)
    mgr.apply_layout(LAYOUT_TABLE_SINGLE, preserve_plots=False)
    # Poisoned state: id says table_only but the splitter tree remains.
    mgr._layout_id = LAYOUT_TABLE_ONLY
    mgr._panes.clear()
    assert isinstance(mgr._workspace_root, QSplitter)
    assert not mgr._layout_tree_matches(LAYOUT_TABLE_ONLY)

    mgr.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)
    assert mgr.plot_panes() == []
    assert mgr._splitters == []
    assert not isinstance(mgr._workspace_root, QSplitter)


def test_take_plot_widgets_restores_adopted_header_buttons(qapp):
    """Layout rebuild must not delete Plot Options chrome with the old pane."""
    from PyQt5 import sip
    from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    from molmanager.ui.dockable_plot_chrome import apply_plot_chrome_glyphs
    from molmanager.ui.dockable_plot_embed import adopt_dock_header_buttons

    plot = QWidget()
    foot_host = QWidget(plot)
    foot = QHBoxLayout(foot_host)
    opts = QPushButton("opts", foot_host)
    opts.setToolTip("Plot Options")
    plot._opts_btn = opts
    foot.addWidget(opts)
    root = QVBoxLayout(plot)
    root.addWidget(foot_host)
    plot._footer_bar = foot_host
    plot.show()
    opts.show()
    qapp.processEvents()

    pane = PlotPane("pane_chrome")
    pane.show()
    qapp.processEvents()
    pane.add_plot_widget(plot)
    adopt_dock_header_buttons(
        pane._chrome_ly,
        plot,
        leading_opts_layout=pane._leading_opts_ly,
        send_window_layout=pane._send_ly,
        trailing_close_layout=pane._trailing_close_ly,
    )
    pane._header_button_owner = plot
    qapp.processEvents()
    assert opts.parentWidget() is not foot_host

    old_pane = pane
    taken = pane.take_plot_widgets()
    assert taken == [plot]
    old_pane.deleteLater()
    qapp.processEvents()
    assert not sip.isdeleted(opts)
    assert opts.toolTip() == "Plot Options"
    apply_plot_chrome_glyphs(plot)
    assert not sip.isdeleted(opts)



def test_plot_pane_refresh_theme_reapplies_selection_outline(qapp):
    del qapp
    pane = PlotPane("pane_test")
    pane.set_active(True)
    assert "palette(highlight)" in pane.styleSheet()
    pane.set_active(False)
    assert "palette(mid)" in pane.styleSheet()
    pane.set_active(True)
    pane.refresh_theme()
    assert pane._active is True
    assert "palette(highlight)" in pane.styleSheet()


def test_workspace_layout_refresh_theme_preserves_preferred_pane(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    mgr.set_preferred_pane(p1)
    mgr.refresh_theme()
    assert p1._active is True
    assert p0._active is False


def test_apply_layout_preserves_pane_stacks(qapp):
    mgr = _manager(qapp)
    p0, p1 = mgr.plot_panes()
    a = QLabel("a")
    b = QLabel("b")
    c = QLabel("c")
    mgr.dock_into_pane(p0, a)
    mgr.dock_into_pane(p0, b)
    mgr.dock_into_pane(p1, c)
    extras = mgr.apply_layout(LAYOUT_TABLE_STACK, preserve_plots=True)
    assert extras == []
    panes = mgr.plot_panes()
    assert panes[0].plot_widgets() == [a, b]
    assert panes[0].plot_widget() is b
    assert panes[1].plot_widgets() == [c]


def test_dock_fits_wide_widget_to_existing_splitter_sizes(qapp):
    from PyQt5.QtWidgets import QLayout, QVBoxLayout

    from molmanager.ui.dockable_plot import embed_in_plot_pane, unembed_from_plot_pane

    host = QWidget()
    ly = QVBoxLayout(host)
    ly.setSizeConstraint(QLayout.SetMinimumSize)
    ly.addWidget(QLabel("wide"))
    host.setMinimumWidth(900)
    embed_in_plot_pane(host)
    assert host.minimumWidth() == 0
    assert ly.sizeConstraint() == QLayout.SetDefaultConstraint
    unembed_from_plot_pane(host)
    assert host.minimumWidth() == 900
    assert ly.sizeConstraint() == QLayout.SetMinimumSize

    mgr = _manager(qapp)
    outer = mgr._splitters[0]
    outer.setSizes([900, 320])
    before = [int(s) for s in outer.sizes()]
    widget = QLabel("wide")
    widget.setMinimumWidth(1800)
    widget.setMinimumHeight(900)
    mgr.dock_into_pane(mgr.plot_panes()[0], widget)
    assert [int(s) for s in outer.sizes()] == before
    assert widget.minimumWidth() == 0
    assert mgr.release_widget(widget) is True
    assert widget.minimumWidth() == 1800


def test_plot_pane_header_is_vertically_compact(qapp):
    from molmanager.ui.dockable_plot import PLOT_BODY_MARGINS, _GLYPH_BTN_SIZE

    pane = PlotPane("pane_compact")
    assert pane._header.minimumHeight() == _GLYPH_BTN_SIZE
    assert pane._header.maximumHeight() == _GLYPH_BTN_SIZE
    header_m = pane._header.layout().contentsMargins()
    assert (header_m.top(), header_m.bottom()) == (0, 0)
    root_m = pane._root.contentsMargins()
    assert root_m.top() == 0
    assert pane._close_btn.height() == _GLYPH_BTN_SIZE
    assert PLOT_BODY_MARGINS[1] == 0
    pane.deleteLater()
