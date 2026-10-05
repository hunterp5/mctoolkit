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

"""Footer chrome buttons, Plot Options dialog, and close helpers."""

from __future__ import annotations

from contextlib import suppress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QPushButton, QVBoxLayout, QWidget

from .dockable_plot_constants import _DOCK_TEXT_CHROME_ATTRS
from .dockable_plot_glyphs import (
    add_to_main_glyph_icon,
    clear_selection_glyph_icon,
    plot_options_glyph_icon,
    send_to_window_glyph_icon,
    style_plot_chrome_glyph_button,
    style_plot_footer_text_button,
)


def make_plot_options_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Plot Options",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, plot_options_glyph_icon(), tooltip)
    return btn


def make_send_window_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Send to New Window",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, send_to_window_glyph_icon(), tooltip)
    return btn


def make_add_to_main_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Add to Main Window",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, add_to_main_glyph_icon(), tooltip)
    return btn


def make_close_plot_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Close this plot.",
) -> QPushButton:
    btn = QPushButton("Close Plot", parent)
    btn.setToolTip(tooltip)
    style_plot_footer_text_button(btn)
    return btn


def make_clear_selection_button(
    parent: QWidget | None = None,
    *,
    tooltip: str = "Clear the current table and plot selection.",
) -> QPushButton:
    btn = QPushButton(parent)
    style_plot_chrome_glyph_button(btn, clear_selection_glyph_icon(), tooltip)
    return btn


def apply_plot_chrome_glyphs(widget: QWidget | None) -> None:
    """Ensure Plot Options / Clear / Add / Send glyphs and compact text chrome when present."""
    if widget is None:
        return
    opts = getattr(widget, "_opts_btn", None)
    if isinstance(opts, QPushButton):
        with suppress(RuntimeError):
            tip = opts.toolTip() or "Plot Options"
            style_plot_chrome_glyph_button(opts, plot_options_glyph_icon(), tip)
    clear = getattr(widget, "_clear_sel_btn", None)
    if isinstance(clear, QPushButton):
        with suppress(RuntimeError):
            tip = clear.toolTip() or "Clear the current table and plot selection."
            style_plot_chrome_glyph_button(clear, clear_selection_glyph_icon(), tip)
    add = getattr(widget, "_add_to_main_btn", None)
    if isinstance(add, QPushButton):
        with suppress(RuntimeError):
            tip = add.toolTip() or "Add to Main Window"
            style_plot_chrome_glyph_button(add, add_to_main_glyph_icon(), tip)
    send = getattr(widget, "_send_window_btn", None)
    if isinstance(send, QPushButton):
        with suppress(RuntimeError):
            tip = send.toolTip() or "Send to New Window"
            style_plot_chrome_glyph_button(send, send_to_window_glyph_icon(), tip)
    for name in _DOCK_TEXT_CHROME_ATTRS:
        btn = getattr(widget, name, None)
        if isinstance(btn, QPushButton):
            with suppress(RuntimeError):
                if (btn.text() or "").strip():
                    style_plot_footer_text_button(btn)


def confirm_close_plot(
    parent: QWidget | None,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> bool:
    """Deprecated no-op: plot close is no longer confirmed. Always returns True."""
    _ = parent, title, message
    return True


def _widget_is_docked_in_main(widget: QWidget) -> bool:
    app = getattr(widget, "parent_app", None)
    if app is None:
        return False
    check = getattr(app, "is_plot_docked", None)
    if callable(check):
        return bool(check(widget))
    return getattr(app, "_docked_plot_widget", None) is widget


def _widget_is_docked_in_viewer(widget: QWidget) -> bool:
    app = getattr(widget, "parent_app", None)
    if app is None:
        return False
    finder = getattr(app, "_live_protein_viewer", None)
    protein = finder() if callable(finder) else None
    check = getattr(protein, "is_side_docked", None) if protein is not None else None
    return callable(check) and bool(check(widget))


def request_close_plot_widget(
    widget: QWidget,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> None:
    """Close a docked plot or its floating host dialog without confirmation."""
    _ = title, message
    if _widget_is_docked_in_viewer(widget):
        app = getattr(widget, "parent_app", None)
        finder = getattr(app, "_live_protein_viewer", None) if app is not None else None
        protein = finder() if callable(finder) else None
        close = getattr(protein, "close_side_dock_widget", None) if protein is not None else None
        if callable(close):
            close(widget)
        return
    if _widget_is_docked_in_main(widget):
        app = getattr(widget, "parent_app", None)
        close = getattr(app, "close_docked_plot", None) if app is not None else None
        if callable(close):
            close(widget, confirm=False)
        return
    dlg = widget.window()
    if dlg is not None and dlg is not widget:
        dlg._force_close = True
        dlg.close()


def handle_floating_plot_close_event(
    dialog: QWidget,
    event,
    *,
    title: str = "Close Plot",
    message: str = "Close this plot?",
) -> None:
    """Shared closeEvent for floating plot / viewer / browser dialogs (no confirm)."""
    _ = title, message
    if getattr(dialog, "_force_close", False):
        dialog._force_close = False
    event.accept()


def discard_host_dialog_after_dock(dlg, host, attr_name: str) -> None:
    """Destroy the empty floating husk after its panel was reparented into the workspace."""
    if dlg is None:
        return
    if hasattr(dlg, "_panel"):
        dlg._panel = None
    dlg._force_close = True
    if host is not None and getattr(host, attr_name, None) is dlg:
        setattr(host, attr_name, None)
    try:
        dlg.close()
        dlg.deleteLater()
    except RuntimeError:
        pass


def make_plot_options_dialog(
    parent: QWidget,
    content: QWidget,
    *,
    title: str = "Plot Options",
    min_width: int = 520,
    min_height: int = 360,
) -> QDialog:
    """Build a modeless dialog that hosts a plot's options panel."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(title)
    dlg.setModal(False)
    dlg.setWindowModality(Qt.NonModal)
    dlg.setAttribute(Qt.WA_DeleteOnClose, False)
    dlg.setMinimumWidth(min_width)
    dlg.setMinimumHeight(min_height)
    root = QVBoxLayout(dlg)
    root.setContentsMargins(8, 8, 8, 8)
    root.addWidget(content, 1)
    return dlg


def show_plot_options_dialog(dialog: QDialog | None) -> None:
    """Show and raise an existing plot-options dialog."""
    if dialog is None:
        return
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()


def hide_plot_options_dialog(dialog: QDialog | None) -> None:
    """Hide a plot-options dialog if it is open."""
    if dialog is None:
        return
    with suppress(RuntimeError):
        dialog.hide()
