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

"""Tests for docked-plot panel width helpers."""

from molmanager.ui.dockable_plot import (
    PLOT_PANEL_BASE_MINIMUM_WIDTH,
    PLOT_PANEL_DEFAULT_WIDTH,
    is_dockable_plot_widget,
    is_dockable_workspace_widget,
    plot_embedded_minimum_width,
    plot_embedded_preferred_width,
)


class _WidePlot:
    def embedded_minimum_width(self) -> int:
        return 700

    def embedded_preferred_width(self) -> int:
        return 900


class _ViewerLike:
    dockable_in_workspace = True


def test_plot_embedded_widths_use_custom_hooks():
    w = _WidePlot()
    assert plot_embedded_minimum_width(w) == 700
    assert plot_embedded_preferred_width(w) == 900


def test_plot_embedded_widths_fallback_without_widget():
    assert plot_embedded_minimum_width(None) == PLOT_PANEL_BASE_MINIMUM_WIDTH
    assert plot_embedded_preferred_width(None) == max(
        PLOT_PANEL_BASE_MINIMUM_WIDTH, PLOT_PANEL_DEFAULT_WIDTH
    )


def test_plot_widget_dock_width_is_figure_sized():
    """Options live in a dialog, so docked width no longer needs axes+stats side-by-side."""
    import inspect

    from molmanager.ui.plot import PlotWidget

    stub = type(
        "W",
        (),
        {
            "embedded_minimum_width": lambda self: 420,
            "embedded_preferred_width": lambda self: 640,
        },
    )()
    assert plot_embedded_minimum_width(stub) == 420
    assert plot_embedded_preferred_width(stub) == 640
    min_src = inspect.getsource(PlotWidget.embedded_minimum_width)
    pref_src = inspect.getsource(PlotWidget.embedded_preferred_width)
    assert "420" in min_src
    assert "640" in pref_src
    assert "_AXES_CONTROLS_MIN_WIDTH" not in min_src


def test_is_dockable_workspace_widget_accepts_viewer_marker():
    viewer = _ViewerLike()
    assert is_dockable_workspace_widget(viewer)
    assert not is_dockable_plot_widget(viewer)


def test_molecule_3d_viewer_widget_is_workspace_dockable():
    from molmanager.ui.mol_viewer_3d import Molecule3DViewerWidget

    assert getattr(Molecule3DViewerWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(Molecule3DViewerWidget)


def test_selection_browser_widget_is_workspace_dockable():
    from molmanager.ui.selection_browser import SelectionBrowserWidget

    assert getattr(SelectionBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(SelectionBrowserWidget)
    assert not is_dockable_plot_widget(SelectionBrowserWidget)
    assert hasattr(SelectionBrowserWidget, "create_floating_dialog")
    assert getattr(SelectionBrowserWidget, "supports_floating_title", True) is False
    assert hasattr(SelectionBrowserWidget, "_toggle_options_visible")
    assert hasattr(SelectionBrowserWidget, "_sync_options_chrome")
    assert hasattr(SelectionBrowserWidget, "_open_browser_options")


def test_clear_selection_button_is_glyph(qapp):  # noqa: ARG001
    from molmanager.ui.dockable_plot import (
        _DOCK_LEADING_OPTS_ATTRS,
        _GLYPH_BTN_SIZE,
        _GLYPH_ICON_SIZE,
        make_clear_selection_button,
        make_plot_options_button,
        make_send_window_button,
    )

    btn = make_clear_selection_button()
    assert btn.text() == ""
    assert not btn.icon().isNull()
    assert btn.width() == _GLYPH_BTN_SIZE
    assert btn.height() == _GLYPH_BTN_SIZE
    assert btn.iconSize().width() == _GLYPH_ICON_SIZE
    assert "padding: 0px" in (btn.styleSheet() or "")
    opts = make_plot_options_button()
    assert opts.width() == opts.height() == _GLYPH_BTN_SIZE
    send = make_send_window_button()
    assert send.text() == ""
    assert not send.icon().isNull()
    assert send.toolTip() == "Send to New Window"
    assert _DOCK_LEADING_OPTS_ATTRS == ("_opts_btn", "_clear_sel_btn")


def test_pane_title_chrome_is_readable(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QLineEdit, QPushButton

    from molmanager.ui.dockable_plot import (
        _FOOTER_TEXT_FONT_PX,
        _GLYPH_BTN_SIZE,
        style_plot_footer_text_button,
        style_plot_pane_title_edit,
    )
    from molmanager.ui.main_window.plot_pane import PlotPane

    assert _FOOTER_TEXT_FONT_PX >= 12
    edit = QLineEdit("Histogram")
    style_plot_pane_title_edit(edit)
    assert f"font-size: {_FOOTER_TEXT_FONT_PX}px" in (edit.styleSheet() or "")
    assert edit.height() == _GLYPH_BTN_SIZE
    close = PlotPane("p1")._close_btn
    assert close.text() == ""
    assert not close.icon().isNull()
    assert close.width() == close.height() == _GLYPH_BTN_SIZE
    assert "padding: 0px" in (close.styleSheet() or "")
    btn = QPushButton("Close")
    style_plot_footer_text_button(btn)
    assert f"font-size: {_FOOTER_TEXT_FONT_PX}px" in (btn.styleSheet() or "")


def test_browser_nav_buttons_use_skip_glyphs(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QCheckBox, QHBoxLayout, QLayout, QPushButton, QSizePolicy, QWidget

    from molmanager.ui.dockable_plot import add_centered_browser_nav, style_browser_nav_buttons
    from molmanager.ui.dockable_plot_constants import (
        _BROWSER_NAV_BTN_HEIGHT,
        _BROWSER_NAV_BTN_WIDTH,
    )

    first, back, fwd, last, select = (QPushButton("x") for _ in range(5))
    first.setToolTip("First")
    select.setToolTip("Select this row")
    style_browser_nav_buttons(first, back, fwd, last, select)
    for btn in (first, back, fwd, last, select):
        assert btn.text() == ""
        assert not btn.icon().isNull()
        assert btn.minimumWidth() == _BROWSER_NAV_BTN_WIDTH
        assert btn.height() == _BROWSER_NAV_BTN_HEIGHT
        assert btn.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
    assert first.toolTip() == "First"
    assert select.toolTip() == "Select this row"
    assert not select.isCheckable()

    toggle = QPushButton("Select")
    style_browser_nav_buttons(first, back, fwd, last, toggle, select_checkable=True)
    assert toggle.isCheckable()
    assert toggle.text() == ""
    assert not toggle.icon().isNull()

    host = QWidget()
    layout = QHBoxLayout(host)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    trailing = QCheckBox("Browse Selected")
    add_centered_browser_nav(layout, [first, back, fwd, last, select], trailing=trailing)
    layout.setSizeConstraint(QLayout.SetNoConstraint)
    assert layout.count() == 6
    for i in range(5):
        assert layout.stretch(i) == 1
        assert layout.itemAt(i).widget() is (first, back, fwd, last, select)[i]
    assert layout.stretch(5) == 0
    assert layout.itemAt(5).widget() is trailing
    trailing.setFixedWidth(100)
    host.setFixedWidth(520)
    host.show()
    qapp.processEvents()
    widths = {first.width(), back.width(), fwd.width(), last.width(), select.width()}
    assert min(widths) > _BROWSER_NAV_BTN_WIDTH
    assert max(widths) - min(widths) <= 1
    leftover = 520 - trailing.width() - layout.spacing() * 5
    assert abs(first.width() * 5 - leftover) <= 5
    host.close()


def test_pane_nav_arrow_glyph_is_vector(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QPushButton

    from molmanager.ui.dockable_plot import (
        _GLYPH_BTN_SIZE,
        pane_nav_arrow_glyph_icon,
        style_plot_pane_nav_arrow,
    )

    icon = pane_nav_arrow_glyph_icon("left")
    assert not icon.isNull()
    btn = QPushButton("◀")
    style_plot_pane_nav_arrow(btn, "left", "Previous plot in this pane")
    assert btn.text() == ""
    assert not btn.icon().isNull()
    assert btn.width() == btn.height() == _GLYPH_BTN_SIZE
    assert btn.toolTip() == "Previous plot in this pane"


def test_pane_close_glyph_is_centered_icon(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QPushButton

    from molmanager.ui.dockable_plot import (
        _GLYPH_BTN_SIZE,
        _GLYPH_ICON_SIZE,
        pane_close_glyph_icon,
        style_plot_pane_close_button,
    )

    icon = pane_close_glyph_icon()
    assert not icon.isNull()
    btn = QPushButton("×")
    style_plot_pane_close_button(btn, "Close this plot pane")
    assert btn.text() == ""
    assert not btn.icon().isNull()
    assert btn.iconSize().width() == btn.iconSize().height() == _GLYPH_ICON_SIZE
    assert btn.width() == btn.height() == _GLYPH_BTN_SIZE
    assert btn.toolTip() == "Close this plot pane"
    assert "padding: 0px" in (btn.styleSheet() or "")


def test_floating_title_edit_installed_when_undocked(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    from molmanager.ui.dockable_plot import position_floating_title_edit, sync_docked_footer_bar

    host = QWidget()
    root = QVBoxLayout(host)
    footer = QWidget(host)
    host._footer_bar = footer
    foot = QHBoxLayout(footer)
    host._opts_btn = QPushButton(host)
    foot.addWidget(host._opts_btn)
    foot.addStretch(1)
    root.addWidget(footer)
    host.resize(400, 80)
    footer.resize(400, 24)

    sync_docked_footer_bar(host, docked=False)
    edit = host._float_title_edit
    assert edit is not None
    assert not edit.isHidden()
    host._pane_display_title = "My Plot"
    sync_docked_footer_bar(host, docked=False)
    assert edit.text() == "My Plot"
    position_floating_title_edit(host)
    center = edit.x() + edit.width() // 2
    assert abs(center - footer.width() // 2) <= 1
    assert "transparent" in (edit.styleSheet() or "")
    sync_docked_footer_bar(host, docked=True)
    assert edit.isHidden()


def test_browser_skips_floating_title_edit(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

    from molmanager.ui.dockable_plot import sync_docked_footer_bar

    host = QWidget()
    host.supports_floating_title = False
    host._window_title = "Browser"
    root = QVBoxLayout(host)
    footer = QWidget(host)
    host._footer_bar = footer
    foot = QHBoxLayout(footer)
    host._opts_btn = QPushButton(host)
    foot.addWidget(host._opts_btn)
    foot.addStretch(1)
    root.addWidget(footer)

    sync_docked_footer_bar(host, docked=False)
    assert getattr(host, "_float_title_edit", None) is None
