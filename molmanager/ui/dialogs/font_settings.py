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

"""Settings dialog to change application-wide and table font sizes (live, theme-safe)."""

from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import (
    QButtonGroup,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import boxed_form, make_window_minimizable
from ..theme import (
    DEFAULT_TABLE_ALIGN_H,
    DEFAULT_TABLE_ALIGN_V,
    MAX_FONT_PT,
    MIN_FONT_PT,
    default_app_font_pt,
    default_table_font_pt,
    table_text_alignment_label,
)

_ALIGN_CELLS: tuple[tuple[str, str, str], ...] = (
    ("left", "top", "Top left"),
    ("center", "top", "Top center"),
    ("right", "top", "Top right"),
    ("left", "center", "Center left"),
    ("center", "center", "Center"),
    ("right", "center", "Center right"),
    ("left", "bottom", "Bottom left"),
    ("center", "bottom", "Bottom center"),
    ("right", "bottom", "Bottom right"),
)


class _TableAlignButton(QToolButton):
    """Checkable cell showing an A at the chosen horizontal/vertical alignment."""

    def __init__(self, horizontal: str, vertical: str, label: str, parent=None) -> None:
        super().__init__(parent)
        self._h = horizontal
        self._v = vertical
        self.setCheckable(True)
        self.setToolTip(label)
        self.setFixedSize(34, 28)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAutoRaise(False)

    def paintEvent(self, event) -> None:  # noqa: N802
        super().paintEvent(event)
        painter = QPainter(self)
        r = self.rect().adjusted(5, 3, -5, -3)
        hflag = {"left": Qt.AlignLeft, "center": Qt.AlignHCenter, "right": Qt.AlignRight}[self._h]
        vflag = {"top": Qt.AlignTop, "center": Qt.AlignVCenter, "bottom": Qt.AlignBottom}[self._v]
        painter.setPen(self.palette().buttonText().color())
        painter.drawText(r, int(hflag | vflag), "A")
        painter.end()


class FontSettingsDialog(QDialog):
    """Pick application-wide and table font sizes; emits preview signals while adjusting."""

    app_font_size_previewed = pyqtSignal(int)
    table_font_size_previewed = pyqtSignal(int)
    table_align_previewed = pyqtSignal(str, str)

    def __init__(
        self,
        current_app_pt: int,
        current_table_pt: int,
        parent=None,
        *,
        current_align_h: str = DEFAULT_TABLE_ALIGN_H,
        current_align_v: str = DEFAULT_TABLE_ALIGN_V,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Font")
        self.setMinimumWidth(360)
        self._default_app_pt = default_app_font_pt()
        self._default_table_pt = default_table_font_pt()
        self._align_h = current_align_h
        self._align_v = current_align_v

        root = QVBoxLayout(self)
        application, app_form = boxed_form("Application")

        self._app_spin = self._make_spin(current_app_pt, self._default_app_pt)
        self._app_spin.valueChanged.connect(lambda pt: self.app_font_size_previewed.emit(int(pt)))
        app_form.addRow("Font size:", self._app_spin)
        root.addWidget(application)

        table, form = boxed_form("Table")
        self._table_spin = self._make_spin(current_table_pt, self._default_table_pt)
        self._table_spin.valueChanged.connect(
            lambda pt: self.table_font_size_previewed.emit(int(pt))
        )
        form.addRow("Font size:", self._table_spin)

        align_host = QWidget()
        grid = QGridLayout(align_host)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setSpacing(4)
        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)
        self._align_buttons: dict[tuple[str, str], _TableAlignButton] = {}
        for i, (h, v, label) in enumerate(_ALIGN_CELLS):
            btn = _TableAlignButton(h, v, label, align_host)
            self._align_group.addButton(btn)
            self._align_buttons[(h, v)] = btn
            btn.toggled.connect(lambda checked, hh=h, vv=v: self._on_align_toggled(checked, hh, vv))
            grid.addWidget(btn, i // 3, i % 3)
        form.addRow("Text alignment:", align_host)
        self._sync_align_buttons()
        root.addWidget(table)

        actions = QHBoxLayout()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        actions.addWidget(bb)
        actions.addStretch(1)
        reset_btn = QPushButton("Reset to Default")
        reset_btn.setToolTip("Reset to default font sizes and table alignment")
        reset_btn.clicked.connect(self._reset_default)
        actions.addWidget(reset_btn)
        root.addLayout(actions)

        make_window_minimizable(self)

    @staticmethod
    def _make_spin(current_pt: int, default_pt: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(MIN_FONT_PT, MAX_FONT_PT)
        spin.setSuffix(" pt")
        spin.setValue(max(MIN_FONT_PT, min(MAX_FONT_PT, int(current_pt or default_pt))))
        return spin

    def _sync_align_buttons(self) -> None:
        btn = self._align_buttons.get((self._align_h, self._align_v))
        if btn is not None:
            btn.setChecked(True)

    def _on_align_toggled(self, checked: bool, horizontal: str, vertical: str) -> None:
        if not checked:
            return
        self._align_h = horizontal
        self._align_v = vertical
        self.table_align_previewed.emit(horizontal, vertical)

    def _reset_default(self) -> None:
        self._app_spin.setValue(self._default_app_pt)
        self._table_spin.setValue(self._default_table_pt)
        self._align_h = DEFAULT_TABLE_ALIGN_H
        self._align_v = DEFAULT_TABLE_ALIGN_V
        self._sync_align_buttons()
        self.table_align_previewed.emit(self._align_h, self._align_v)

    def selected_app_point_size(self) -> int:
        return int(self._app_spin.value())

    def selected_table_point_size(self) -> int:
        return int(self._table_spin.value())

    def selected_table_alignment(self) -> tuple[str, str]:
        return self._align_h, self._align_v

    def selected_table_alignment_label(self) -> str:
        return table_text_alignment_label(self._align_h, self._align_v)
