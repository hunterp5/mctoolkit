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

"""Dock-pane width, header-button adoption, and size-constraint embed."""

from __future__ import annotations

from contextlib import contextmanager, suppress

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget

from .dockable_plot_chrome import apply_plot_chrome_glyphs
from .dockable_plot_constants import (
    PLOT_PANEL_BASE_MINIMUM_WIDTH,
    PLOT_PANEL_DEFAULT_WIDTH,
    _DOCK_HEADER_BUTTON_ATTRS,
    _DOCK_HEADER_HOME_ATTR,
    _DOCK_LEADING_OPTS_ATTRS,
    _DOCK_SEND_WINDOW_ATTRS,
    _DOCK_TRAILING_CLOSE_BUTTON_ATTRS,
    _PANE_EMBED_ATTR,
)
from .dockable_plot_title import sync_floating_title_chrome

_PARENT_CHANGE_CHROME_DEPTH = 0


@contextmanager
def suspend_parent_change_chrome():
    """Skip footer chrome work while workspace layout reparents widgets."""
    global _PARENT_CHANGE_CHROME_DEPTH
    _PARENT_CHANGE_CHROME_DEPTH += 1
    try:
        yield
    finally:
        _PARENT_CHANGE_CHROME_DEPTH -= 1


def parent_change_chrome_suspended() -> bool:
    return _PARENT_CHANGE_CHROME_DEPTH > 0


def sync_footer_on_parent_change(widget: QWidget) -> None:
    """Run ``_sync_footer_chrome`` unless a layout apply is in progress."""
    if _PARENT_CHANGE_CHROME_DEPTH:
        return
    sync = getattr(widget, "_sync_footer_chrome", None)
    if not callable(sync):
        return
    with suppress(RuntimeError):
        sync()


def iter_plot_selection_views(root: QWidget | None) -> list:
    """Return widgets that implement ``sync_from_table_selection`` (plot ↔ table)."""
    if root is None:
        return []
    views: list = []
    seen: set[int] = set()

    def add(candidate) -> None:
        if candidate is None:
            return
        key = id(candidate)
        if key in seen:
            return
        if not callable(getattr(candidate, "sync_from_table_selection", None)):
            return
        seen.add(key)
        views.append(candidate)

    add(root)
    add(getattr(root, "_plot_view", None))
    add(getattr(root, "_plot_widget", None))
    return views


def is_dockable_plot_widget(widget) -> bool:
    """True when the widget can be placed in the main-window plot panel."""
    return getattr(widget, "only_selected_cb", None) is not None and bool(
        iter_plot_selection_views(widget)
    )


def is_dockable_workspace_widget(widget) -> bool:
    """True for plot panels or other workspace-dockable widgets (e.g. 2D/3D viewers)."""
    if is_dockable_plot_widget(widget):
        return True
    return bool(getattr(widget, "dockable_in_workspace", False))


def plot_embedded_minimum_width(widget: QWidget | None) -> int:
    """Minimum panel width so docked plot controls do not overlap or clip."""
    if widget is None:
        return PLOT_PANEL_BASE_MINIMUM_WIDTH
    custom = getattr(widget, "embedded_minimum_width", None)
    if callable(custom):
        try:
            return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.minimumSizeHint().width())
    except Exception:
        hint = 0
    return max(PLOT_PANEL_BASE_MINIMUM_WIDTH, hint)


def plot_embedded_preferred_width(widget: QWidget | None) -> int:
    """Preferred dock width (at least the minimum needed for controls)."""
    min_w = plot_embedded_minimum_width(widget)
    if widget is None:
        return max(min_w, PLOT_PANEL_DEFAULT_WIDTH)
    custom = getattr(widget, "embedded_preferred_width", None)
    if callable(custom):
        try:
            return max(min_w, int(custom()))
        except Exception:
            pass
    try:
        hint = int(widget.sizeHint().width())
    except Exception:
        hint = 0
    return max(min_w, hint, PLOT_PANEL_DEFAULT_WIDTH)


def _layout_containing(widget: QWidget) -> QLayout | None:
    parent = widget.parentWidget()
    if parent is None:
        return None
    ly = parent.layout()
    if ly is not None:
        try:
            if ly.indexOf(widget) >= 0:
                return ly
        except RuntimeError:
            pass
    try:
        for child_ly in parent.findChildren(QLayout):
            try:
                if child_ly.indexOf(widget) >= 0:
                    return child_ly
            except RuntimeError:
                continue
    except RuntimeError:
        pass
    return None


def iter_dock_header_buttons(widget: QWidget | None) -> list[QWidget]:
    """Mid-header chrome buttons (e.g. Egg / Yolk / Triangle) when docked."""
    return _iter_named_buttons(widget, _DOCK_HEADER_BUTTON_ATTRS)


def iter_dock_leading_opts_buttons(widget: QWidget | None) -> list[QWidget]:
    """Plot Options + Clear Selection glyphs on the far left of the pane header."""
    return _iter_named_buttons(widget, _DOCK_LEADING_OPTS_ATTRS)


def iter_dock_send_window_buttons(widget: QWidget | None) -> list[QWidget]:
    """Add-to-main / send-window glyph shown left of Close / pane ×."""
    return _iter_named_buttons(widget, _DOCK_SEND_WINDOW_ATTRS)


def iter_dock_trailing_close_buttons(widget: QWidget | None) -> list[QWidget]:
    """Close-this-plot/viewer buttons shown immediately left of the pane ×."""
    return _iter_named_buttons(widget, _DOCK_TRAILING_CLOSE_BUTTON_ATTRS)


def _iter_named_buttons(widget: QWidget | None, names: tuple[str, ...]) -> list[QWidget]:
    if widget is None:
        return []
    buttons: list[QWidget] = []
    seen: set[int] = set()
    for name in names:
        btn = getattr(widget, name, None)
        if btn is None:
            continue
        key = id(btn)
        if key in seen:
            continue
        seen.add(key)
        buttons.append(btn)
    return buttons


def restore_dock_header_buttons(widget: QWidget | None, *, docked: bool = False) -> None:
    """Put pane-adopted buttons back on the plot/viewer footer.

    ``docked=True`` leaves the footer hidden. Page changes use that so a plot that
    stays in the stack does not give the footer band back to the figure and then
    take it away again on the next visit.
    """
    if widget is None:
        return
    homes = getattr(widget, _DOCK_HEADER_HOME_ATTR, None)
    if not homes:
        return
    try:
        delattr(widget, _DOCK_HEADER_HOME_ATTR)
    except Exception:
        setattr(widget, _DOCK_HEADER_HOME_ATTR, None)
    for btn, layout, index in sorted(homes, key=lambda item: int(item[2])):
        if btn is None or layout is None:
            continue
        try:
            idx = max(0, min(int(index), layout.count()))
            layout.insertWidget(idx, btn)
        except RuntimeError:
            continue
    sync_docked_footer_bar(widget, docked=docked)


def _adopt_buttons_into_layout(
    host_layout: QHBoxLayout, widget: QWidget, buttons: list[QWidget]
) -> list[tuple[QWidget, QLayout | None, int]]:
    homes: list[tuple[QWidget, QLayout | None, int]] = []
    for btn in buttons:
        try:
            # ``isVisible()`` is false until the pane is shown; use ``isHidden()``
            # so intentionally suppressed chrome (e.g. Add to Main while docked) is skipped.
            if btn.isHidden():
                continue
        except RuntimeError:
            continue
        layout = _layout_containing(btn)
        index = -1
        if layout is not None:
            try:
                index = int(layout.indexOf(btn))
            except RuntimeError:
                index = -1
        homes.append((btn, layout, index))
        try:
            host_layout.addWidget(btn)
            btn.setAutoDefault(False)
            btn.setDefault(False)
            btn.setFocusPolicy(Qt.NoFocus)
        except RuntimeError:
            continue
    return homes


def adopt_dock_header_buttons(
    host_layout: QHBoxLayout,
    widget: QWidget | None,
    *,
    leading_opts_layout: QHBoxLayout | None = None,
    send_window_layout: QHBoxLayout | None = None,
    trailing_close_layout: QHBoxLayout | None = None,
) -> None:
    """Move dock chrome buttons into pane header strips."""
    if widget is None:
        return
    apply_plot_chrome_glyphs(widget)
    restore_dock_header_buttons(widget)
    homes: list[tuple[QWidget, QLayout | None, int]] = []
    if leading_opts_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                leading_opts_layout, widget, iter_dock_leading_opts_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(host_layout, widget, iter_dock_leading_opts_buttons(widget))
        )
    homes.extend(_adopt_buttons_into_layout(host_layout, widget, iter_dock_header_buttons(widget)))
    if send_window_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                send_window_layout, widget, iter_dock_send_window_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(host_layout, widget, iter_dock_send_window_buttons(widget))
        )
    if trailing_close_layout is not None:
        homes.extend(
            _adopt_buttons_into_layout(
                trailing_close_layout, widget, iter_dock_trailing_close_buttons(widget)
            )
        )
    else:
        homes.extend(
            _adopt_buttons_into_layout(
                host_layout, widget, iter_dock_trailing_close_buttons(widget)
            )
        )
    setattr(widget, _DOCK_HEADER_HOME_ATTR, homes)
    sync_docked_footer_bar(widget, docked=True)


def sync_docked_footer_bar(widget: QWidget | None, *, docked: bool) -> None:
    """Hide an empty plot footer once its chrome buttons live in the pane header."""
    if widget is None:
        return
    sync_floating_title_chrome(widget, floating=not docked)
    bar = getattr(widget, "_footer_bar", None)
    if bar is None:
        return
    if not docked:
        try:
            bar.show()
        except RuntimeError:
            pass
        return
    ly = bar.layout()
    if ly is None:
        try:
            bar.hide()
        except RuntimeError:
            pass
        return
    try:
        for i in range(ly.count()):
            item = ly.itemAt(i)
            child = item.widget() if item is not None else None
            if child is None:
                continue
            try:
                if not child.isHidden():
                    bar.show()
                    return
            except RuntimeError:
                continue
        bar.hide()
    except RuntimeError:
        pass


def _iter_widget_layouts(widget: QWidget):
    seen: set[int] = set()
    layout = widget.layout()
    layouts = []
    if layout is not None:
        layouts.append(layout)
    try:
        layouts.extend(widget.findChildren(QLayout))
    except RuntimeError:
        pass
    for item in layouts:
        key = id(item)
        if key in seen:
            continue
        seen.add(key)
        yield item


def embed_in_plot_pane(widget: QWidget | None) -> None:
    """Let ``widget`` shrink to the current plot pane instead of growing the splitter.

    Floating windows keep large minimum sizes and ``QLayout.SetMinimumSize`` constraints.
    Those must not drive QSplitter after the widget is reparented into an existing pane.
    """
    if widget is None:
        return
    state = getattr(widget, _PANE_EMBED_ATTR, None)
    if state is None:
        layout_constraints: list[tuple[QLayout, int]] = []
        for layout in _iter_widget_layouts(widget):
            try:
                constraint = int(layout.sizeConstraint())
            except RuntimeError:
                continue
            if constraint == int(QLayout.SetMinimumSize):
                layout_constraints.append((layout, constraint))
        state = {
            "min": QSize(widget.minimumSize()),
            "max": QSize(widget.maximumSize()),
            "policy": QSizePolicy(widget.sizePolicy()),
            "layouts": layout_constraints,
        }
        setattr(widget, _PANE_EMBED_ATTR, state)
    _apply_plot_pane_fit(widget, state)


def _apply_plot_pane_fit(widget: QWidget, state: dict) -> None:
    for layout, _constraint in state.get("layouts") or ():
        try:
            layout.setSizeConstraint(QLayout.SetDefaultConstraint)
        except RuntimeError:
            pass
    widget.setMinimumSize(0, 0)
    widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)


def unembed_from_plot_pane(widget: QWidget | None) -> None:
    """Restore size constraints saved by :func:`embed_in_plot_pane`."""
    if widget is None:
        return
    restore_dock_header_buttons(widget)
    state = getattr(widget, _PANE_EMBED_ATTR, None)
    if not isinstance(state, dict):
        return
    try:
        delattr(widget, _PANE_EMBED_ATTR)
    except Exception:
        setattr(widget, _PANE_EMBED_ATTR, None)
    for layout, constraint in state.get("layouts") or ():
        try:
            layout.setSizeConstraint(constraint)
        except RuntimeError:
            pass
    try:
        widget.setMinimumSize(state["min"])
        widget.setMaximumSize(state["max"])
        widget.setSizePolicy(state["policy"])
    except RuntimeError:
        pass
