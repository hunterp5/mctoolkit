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

"""Shared Qt widget helpers."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QObject, QPoint, QPointF, Qt
from PyQt5.QtGui import QWheelEvent
from PyQt5.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from molmanager.ui.qt_widget_utils import (
    append_viewer_log,
    install_dialog_resize_policy,
    install_unfocused_wheel_passthrough,
    make_window_minimizable,
    make_window_resizable,
)


def _wheel_event(widget: QWidget, *, delta: int = 120) -> QWheelEvent:
    pos = QPointF(widget.rect().center())
    global_pos = QPointF(widget.mapToGlobal(widget.rect().center()))
    return QWheelEvent(
        pos,
        global_pos,
        QPoint(0, 0),
        QPoint(0, delta),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.ScrollUpdate,
        False,
    )


def _scroll_host(qapp: QApplication) -> tuple[QScrollArea, QDoubleSpinBox, QComboBox]:
    install_unfocused_wheel_passthrough(qapp)
    scroll = QScrollArea()
    inner = QWidget()
    inner.setMinimumHeight(2000)
    layout = QVBoxLayout(inner)
    spin = QDoubleSpinBox()
    spin.setRange(0.0, 14.0)
    spin.setSingleStep(1.0)
    spin.setValue(7.4)
    combo = QComboBox()
    combo.addItems(["one", "two", "three"])
    layout.addWidget(spin)
    layout.addWidget(combo)
    scroll.setWidget(inner)
    scroll.resize(360, 240)
    scroll.show()
    qapp.processEvents()
    return scroll, spin, combo


def test_install_unfocused_wheel_passthrough_is_idempotent(qapp):
    first = install_unfocused_wheel_passthrough(qapp)
    second = install_unfocused_wheel_passthrough(qapp)
    assert first is not None
    assert first is second


def test_append_viewer_log_forwards_when_present():
    seen: list[str] = []

    class _Host:
        def append_log(self, text: str) -> None:
            seen.append(text)

    append_viewer_log(_Host(), "line")
    append_viewer_log(object(), "ignored")
    append_viewer_log(None, "ignored")
    assert seen == ["line"]


def test_unfocused_spin_and_combo_do_not_eat_wheel(qapp):
    scroll, spin, combo = _scroll_host(qapp)
    received: list[QObject] = []

    class _Counter(QObject):
        def eventFilter(self, obj, event):  # noqa: N802
            if event.type() == QEvent.Wheel:
                received.append(obj)
            return False

    counter = _Counter(scroll)
    scroll.viewport().installEventFilter(counter)
    spin.clearFocus()
    combo.clearFocus()
    qapp.processEvents()

    QApplication.sendEvent(spin, _wheel_event(spin))
    qapp.processEvents()
    assert spin.value() == 7.4
    assert scroll.viewport() in received

    received.clear()
    QApplication.sendEvent(combo, _wheel_event(combo))
    qapp.processEvents()
    assert combo.currentText() == "one"
    assert scroll.viewport() in received
    scroll.close()


def test_focused_spin_still_accepts_wheel(qapp):
    scroll, spin, _combo = _scroll_host(qapp)
    spin.setFocus(Qt.OtherFocusReason)
    qapp.processEvents()
    assert spin.hasFocus()
    QApplication.sendEvent(spin, _wheel_event(spin))
    qapp.processEvents()
    assert spin.value() == 8.4
    scroll.close()


def test_unipka_cuda_hint_shows_once(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox, QWidget

    from molmanager.ui.pka_gpu_hint import maybe_remind_unipka_cuda_wheel

    shown: list[int] = []

    def _info(*_a, **_k):
        shown.append(1)
        return QMessageBox.Ok

    monkeypatch.setattr("molmanager.ui.pka_gpu_hint.cpu_torch_with_nvidia_gpu", lambda: True)
    monkeypatch.setattr(QMessageBox, "information", _info)
    host = QWidget()
    maybe_remind_unipka_cuda_wheel(host)
    maybe_remind_unipka_cuda_wheel(host)
    assert shown == [1]
    host.close()


def _has_flag(widget: QWidget, flag: Qt.WindowType) -> bool:
    return bool(widget.windowFlags() & flag)


def test_make_window_minimizable_drops_the_resize_border(qapp):
    dialog = QDialog()
    dialog.resize(320, 200)
    make_window_minimizable(dialog)
    assert _has_flag(dialog, Qt.WindowMinimizeButtonHint)
    assert not _has_flag(dialog, Qt.WindowMaximizeButtonHint)
    assert _has_flag(dialog, Qt.MSWindowsFixedSizeDialogHint)
    assert not dialog.isSizeGripEnabled()
    dialog.resize(410, 260)
    qapp.processEvents()
    assert dialog.width() == 410
    assert dialog.height() == 260
    dialog.close()


def test_make_window_resizable_keeps_maximize(qapp):
    dialog = QDialog()
    make_window_resizable(dialog)
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    assert _has_flag(dialog, Qt.WindowMinimizeButtonHint)
    assert _has_flag(dialog, Qt.WindowMaximizeButtonHint)
    assert not _has_flag(dialog, Qt.MSWindowsFixedSizeDialogHint)
    dialog.close()


def test_plain_dialog_is_non_resizable_and_file_dialog_is_left_alone(qapp):
    install_dialog_resize_policy(qapp)
    dialog = QDialog()
    dialog.resize(300, 180)
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    assert _has_flag(dialog, Qt.MSWindowsFixedSizeDialogHint)
    assert not _has_flag(dialog, Qt.WindowMaximizeButtonHint)
    assert not _has_flag(dialog, Qt.WindowMinimizeButtonHint)
    dialog.close()

    picker = QFileDialog()
    before = picker.windowFlags()
    picker.ensurePolished()
    qapp.processEvents()
    assert picker.windowFlags() == before
    picker.close()
