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

"""Shared Markers plot-options group (Color by and Size by)."""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..plotting.plot_marker_color import PLOT_COLORSCALE_CHOICES
from .plot_color_range_controls import PlotColorRangeControls
from .plot_size_controls import PlotSizeRangeControls


class PlotMarkersControls(QGroupBox):
    """Color by and Size by, in the same box on every plot options dialog."""

    color_changed = pyqtSignal()
    size_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        color_tooltip: str = "",
        size_tooltip: str = "",
        combo_min_width: int = 120,
    ) -> None:
        super().__init__("Markers", parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(2)

        color_row = QHBoxLayout()
        color_row.setContentsMargins(0, 0, 0, 0)
        color_row.setSpacing(6)
        self._color_by_label = QLabel("Color by:")
        color_row.addWidget(self._color_by_label)
        self.color_combo = QComboBox()
        self.color_combo.setMinimumWidth(int(combo_min_width))
        self.color_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if color_tooltip:
            self.color_combo.setToolTip(color_tooltip)
        self.color_combo.currentIndexChanged.connect(lambda *_args: self.color_changed.emit())
        color_row.addWidget(self.color_combo, 1)
        self._spectrum_label = QLabel("Spectrum:")
        color_row.addWidget(self._spectrum_label)
        self.colorscale_combo = QComboBox()
        self.colorscale_combo.setMinimumWidth(100)
        self.colorscale_combo.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.colorscale_combo.addItems(PLOT_COLORSCALE_CHOICES)
        self.colorscale_combo.setToolTip("Continuous colorscale for numeric Color by columns.")
        self.colorscale_combo.currentIndexChanged.connect(lambda *_args: self.color_changed.emit())
        color_row.addWidget(self.colorscale_combo)
        self.color_range = PlotColorRangeControls()
        self.color_range.connect_changed(lambda *_args: self.color_changed.emit())
        color_row.addWidget(self.color_range)
        root.addLayout(color_row)

        size_row = QHBoxLayout()
        size_row.setContentsMargins(0, 0, 0, 0)
        size_row.setSpacing(6)
        self._size_by_label = QLabel("Size by:")
        size_row.addWidget(self._size_by_label)
        self.size_combo = QComboBox()
        self.size_combo.setMinimumWidth(int(combo_min_width))
        self.size_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        if size_tooltip:
            self.size_combo.setToolTip(size_tooltip)
        self.size_combo.currentIndexChanged.connect(lambda *_args: self.size_changed.emit())
        size_row.addWidget(self.size_combo, 1)
        self.size_range = PlotSizeRangeControls()
        self.size_range.connect_changed(lambda *_args: self.size_changed.emit())
        size_row.addWidget(self.size_range)
        root.addLayout(size_row)
