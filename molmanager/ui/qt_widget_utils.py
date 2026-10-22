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

"""Small Qt widget helpers shared across dialogs (keep dependency-free beyond PyQt5)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import QEvent, QObject, Qt
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import (
    QAbstractScrollArea,
    QAbstractSpinBox,
    QApplication,
    QColorDialog,
    QComboBox,
    QDial,
    QDialog,
    QErrorMessage,
    QFileDialog,
    QFontDialog,
    QGroupBox,
    QInputDialog,
    QMessageBox,
    QProgressDialog,
    QSlider,
    QTextEdit,
    QWidget,
)


def qobject_is_deleted(obj: Any) -> bool:
    """Return True when *obj* is missing or its C++ QObject has already been destroyed."""
    if obj is None:
        return True
    try:
        from PyQt5 import sip

        if isinstance(obj, QObject) and sip.isdeleted(obj):
            return True
    except Exception:
        return True
    return False


def monospace_text_font() -> QFont:
    f = QFont("Consolas")
    if not f.exactMatch():
        f = QFont("Courier New")
    f.setStyleHint(QFont.Monospace)
    return f


def apply_monospace_to_text_edit(w: QTextEdit) -> None:
    w.setFont(monospace_text_font())


def append_viewer_log(viewer, text: str) -> None:
    """Forward a progress line to Protein Viewer ``append_log`` when present."""
    append = getattr(viewer, "append_log", None)
    if callable(append):
        append(text)


# Viewers set this so the dialog resize policy leaves their frame alone.
_ALLOW_RESIZE_ATTR = "_mm_allow_user_resize"
_RESIZE_POLICY_ATTR = "_mm_dialog_resize_policy"
_RESIZE_FILTER_NAME = "molmanager_dialog_resize_policy"

# Qt's own pickers stay on the platform's resize behavior.
_SYSTEM_DIALOGS = (
    QFileDialog,
    QColorDialog,
    QFontDialog,
    QMessageBox,
    QInputDialog,
    QProgressDialog,
    QErrorMessage,
)


def _disable_size_grip(widget: QWidget) -> None:
    grip = getattr(widget, "setSizeGripEnabled", None)
    if callable(grip):
        grip(False)


def make_dialog_non_resizable(widget: QWidget) -> None:
    """Remove the resize border and maximize button from a dialog.

    ``MSWindowsFixedSizeDialogHint`` drops the thick frame on Windows. The
    widget's size is not frozen, so later ``resize()`` calls still apply.
    """
    setattr(widget, _ALLOW_RESIZE_ATTR, False)
    setattr(widget, _RESIZE_POLICY_ATTR, True)
    flags = widget.windowFlags()
    flags |= Qt.MSWindowsFixedSizeDialogHint
    flags &= ~Qt.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)
    _disable_size_grip(widget)


def make_window_minimizable(widget: QWidget) -> None:
    """Add a minimize button and keep a dialog from being resized."""
    setattr(widget, _ALLOW_RESIZE_ATTR, False)
    setattr(widget, _RESIZE_POLICY_ATTR, True)
    flags = widget.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.MSWindowsFixedSizeDialogHint
    flags &= ~Qt.WindowMaximizeButtonHint
    widget.setWindowFlags(flags)
    _disable_size_grip(widget)


def make_window_resizable(widget: QWidget) -> None:
    """Add minimize and maximize buttons on a window the user can resize.

    Plots, the protein viewer, the sketcher, and structure browsers use this.
    Tool dialogs use :func:`make_window_minimizable`.
    """
    setattr(widget, _ALLOW_RESIZE_ATTR, True)
    setattr(widget, _RESIZE_POLICY_ATTR, True)
    flags = widget.windowFlags()
    flags |= Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint
    flags &= ~Qt.MSWindowsFixedSizeDialogHint
    widget.setWindowFlags(flags)


class _DialogResizePolicyFilter(QObject):
    """Make top-level dialogs fixed-size unless a caller opted into resizing."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Polish or not isinstance(obj, QDialog):
            return False
        if not obj.isWindow() or isinstance(obj, _SYSTEM_DIALOGS):
            return False
        if getattr(obj, _ALLOW_RESIZE_ATTR, False) or getattr(obj, _RESIZE_POLICY_ATTR, False):
            return False
        # Polish runs before the window is shown, so replacing flags does not hide it.
        make_dialog_non_resizable(obj)
        return False


def install_dialog_resize_policy(app: QApplication | None = None) -> QObject | None:
    """Keep tool dialogs from being resized. Viewers opt out with ``make_window_resizable``."""
    if app is None:
        app = QApplication.instance()
    if app is None:
        return None
    existing = app.findChild(_DialogResizePolicyFilter, _RESIZE_FILTER_NAME)
    if existing is not None and not qobject_is_deleted(existing):
        return existing
    filt = _DialogResizePolicyFilter(app)
    filt.setObjectName(_RESIZE_FILTER_NAME)
    app.installEventFilter(filt)
    return filt


_WHEEL_STEALERS = (QAbstractSpinBox, QComboBox, QSlider, QDial)
_WHEEL_FILTER_NAME = "molmanager_unfocused_wheel_passthrough"


def _is_wheel_stealing_control(obj: object) -> bool:
    return isinstance(obj, _WHEEL_STEALERS)


def _control_should_accept_wheel(widget: QWidget) -> bool:
    if widget.hasFocus():
        return True
    if isinstance(widget, QComboBox):
        view = widget.view()
        if view is not None and view.isVisible():
            return True
    return False


def _nearest_scroll_area(widget: QWidget) -> QAbstractScrollArea | None:
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, QAbstractScrollArea):
            return parent
        parent = parent.parentWidget()
    return None


class _UnfocusedWheelPassthroughFilter(QObject):
    """Let page scroll win over spin boxes / combos that the cursor happens to cover."""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._forwarding = False

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if self._forwarding or event.type() != QEvent.Wheel:
            return False
        if not _is_wheel_stealing_control(obj):
            return False
        widget = obj
        if not isinstance(widget, QWidget) or _control_should_accept_wheel(widget):
            return False
        scroll = _nearest_scroll_area(widget)
        target = scroll.viewport() if scroll is not None else widget.parentWidget()
        if target is None:
            event.ignore()
            return True
        self._forwarding = True
        try:
            QApplication.sendEvent(target, event)
        finally:
            self._forwarding = False
        return True


def _mix_color(base: QColor, other: QColor, toward_other: float) -> QColor:
    amount = min(1.0, max(0.0, toward_other))
    return QColor(
        int(base.red() * (1.0 - amount) + other.red() * amount),
        int(base.green() * (1.0 - amount) + other.green() * amount),
        int(base.blue() * (1.0 - amount) + other.blue() * amount),
    )


def group_box_stylesheet(palette: QPalette, *, titled: bool = True) -> str:
    """Frame whose title breaks the border, with a light tint instead of a solid panel.

    The title stays the opaque window color so it covers the line. The fill and
    border are a softened mix of the window and mid tones. Untitled boxes keep a
    continuous border.
    """
    window = palette.color(QPalette.Window)
    mid = palette.color(QPalette.Mid)
    fill = _mix_color(window, mid, 0.14)
    fill.setAlpha(150)
    border = _mix_color(window, mid, 0.42)
    border.setAlpha(160)
    margin = "8px" if titled else "0px"
    sheet = (
        "QGroupBox {"
        f" border: 1px solid {border.name(QColor.HexArgb)};"
        " border-radius: 3px;"
        f" margin-top: {margin};"
        f" background-color: {fill.name(QColor.HexArgb)};"
        "}"
    )
    if not titled:
        return sheet
    return (
        sheet + "QGroupBox::title {"
        " subcontrol-origin: margin;"
        " subcontrol-position: top left;"
        " left: 8px;"
        " padding: 0 4px;"
        f" background-color: {window.name()};"
        "}"
    )


def group_box_stylesheet_for(box: QGroupBox) -> str:
    """Stylesheet for *box* from the application palette and whether it has a title.

    A stylesheet changes the palette ``QWidget.palette()`` reports, so the colors
    come from the application palette that themes set.
    """
    app = QApplication.instance()
    palette = app.palette() if app is not None else box.palette()
    titled = bool((box.title() or "").strip())
    return group_box_stylesheet(palette, titled=titled)


_GROUP_BOX_APPLYING = "_mm_group_qss_applying"
_GROUP_BOX_FILTER_NAME = "molmanager_group_box_style"


def apply_group_box_style(box: QGroupBox) -> None:
    """Paint *box* with the shared group-box frame. No-op when it already matches."""
    if qobject_is_deleted(box):
        return
    sheet = group_box_stylesheet_for(box)
    if box.styleSheet() == sheet:
        return
    setattr(box, _GROUP_BOX_APPLYING, True)
    try:
        box.setStyleSheet(sheet)
    finally:
        setattr(box, _GROUP_BOX_APPLYING, False)


class _GroupBoxStyleFilter(QObject):
    """Apply the shared group-box frame as each box is polished."""

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:  # noqa: N802
        if event.type() != QEvent.Polish or not isinstance(obj, QGroupBox):
            return False
        if getattr(obj, _GROUP_BOX_APPLYING, False):
            return False
        apply_group_box_style(obj)
        return False


def install_group_box_style(app: QApplication | None = None) -> QObject | None:
    """Style every QGroupBox, including ones created after startup.

    Colors are baked from the palette, so a theme change must call
    ``restyle_application_group_boxes``. This does not set an application stylesheet.
    """
    if app is None:
        app = QApplication.instance()
    if app is None:
        return None
    existing = app.findChild(_GroupBoxStyleFilter, _GROUP_BOX_FILTER_NAME)
    if existing is not None and not qobject_is_deleted(existing):
        return existing
    filt = _GroupBoxStyleFilter(app)
    filt.setObjectName(_GROUP_BOX_FILTER_NAME)
    app.installEventFilter(filt)
    return filt


def restyle_application_group_boxes(app: QApplication | None = None) -> None:
    """Rewrite group-box stylesheets from the palette now on each box."""
    if app is None:
        app = QApplication.instance()
    if app is None:
        return
    for widget in app.allWidgets():
        if not isinstance(widget, QGroupBox):
            continue
        try:
            apply_group_box_style(widget)
        except RuntimeError:
            continue


def install_unfocused_wheel_passthrough(app: QApplication | None = None) -> QObject | None:
    """Stop hover-wheel from editing spin boxes and combo boxes; keep scrolling the page.

    Qt's ``QAbstractSpinBox`` and ``QComboBox`` accept wheel events on hover (even without
    focus), which traps scrolling in Prepare and other tall forms. After a click, wheel
    still changes the focused control.
    """
    if app is None:
        app = QApplication.instance()
    if app is None:
        return None
    existing = app.findChild(_UnfocusedWheelPassthroughFilter, _WHEEL_FILTER_NAME)
    if existing is not None and not qobject_is_deleted(existing):
        return existing
    filt = _UnfocusedWheelPassthroughFilter(app)
    filt.setObjectName(_WHEEL_FILTER_NAME)
    app.installEventFilter(filt)
    return filt
