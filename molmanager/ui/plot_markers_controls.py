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

"""Shared Markers plot-options group (color, size, shape, and opacity)."""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..plotting.plot_marker_color import (
    DEFAULT_MARKER_OPACITY,
    PLOT_COLORSCALE_CHOICES,
    PLOT_MARKER_SHAPES,
    clamp_marker_opacity,
    resolve_marker_symbol,
)
from .plot_color_range_controls import PlotColorRangeControls
from .plot_size_controls import PlotSizeRangeControls

_SHAPE_TOOLTIP = (
    "Marker shape. 3D scatter draws circle, square, diamond, cross, and x; "
    "other shapes are shown as a circle."
)
_OPACITY_TOOLTIP = "How solid each marker is. 100% is fully opaque."


class PlotMarkersControls(QGroupBox):
    """Color, size, shape, and opacity for scatter markers on every plot options dialog."""

    color_changed = pyqtSignal()
    size_changed = pyqtSignal()
    style_changed = pyqtSignal()

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        color_tooltip: str = "",
        size_tooltip: str = "",
        combo_min_width: int = 120,
        default_opacity: float = DEFAULT_MARKER_OPACITY,
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
        self.invert_spectrum_cb = QCheckBox("Invert")
        self.invert_spectrum_cb.setToolTip("Reverse the continuous color spectrum.")
        self.invert_spectrum_cb.toggled.connect(lambda *_args: self.color_changed.emit())
        color_row.addWidget(self.invert_spectrum_cb)
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

        style_row = QHBoxLayout()
        style_row.setContentsMargins(0, 0, 0, 0)
        style_row.setSpacing(6)
        self._shape_label = QLabel("Shape:")
        style_row.addWidget(self._shape_label)
        self.shape_combo = QComboBox()
        self.shape_combo.setMinimumWidth(int(combo_min_width))
        self.shape_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        for label, symbol in PLOT_MARKER_SHAPES:
            self.shape_combo.addItem(label, symbol)
        self.shape_combo.setToolTip(_SHAPE_TOOLTIP)
        self.shape_combo.currentIndexChanged.connect(lambda *_args: self.style_changed.emit())
        style_row.addWidget(self.shape_combo, 1)
        self._opacity_label = QLabel("Opacity:")
        style_row.addWidget(self._opacity_label)
        self.opacity_spin = QDoubleSpinBox()
        self.opacity_spin.setDecimals(0)
        self.opacity_spin.setRange(0.0, 100.0)
        self.opacity_spin.setSingleStep(5.0)
        self.opacity_spin.setSuffix(" %")
        self.opacity_spin.setValue(round(clamp_marker_opacity(default_opacity) * 100.0))
        self.opacity_spin.setFixedWidth(72)
        self.opacity_spin.setToolTip(_OPACITY_TOOLTIP)
        self.opacity_spin.valueChanged.connect(lambda *_args: self.style_changed.emit())
        style_row.addWidget(self.opacity_spin)
        root.addLayout(style_row)

    def marker_opacity(self) -> float:
        """Current marker opacity in the Plotly range ``[0, 1]``."""
        return clamp_marker_opacity(float(self.opacity_spin.value()) / 100.0)

    def marker_symbol(self) -> str:
        """Current Plotly marker symbol."""
        data = self.shape_combo.currentData()
        return resolve_marker_symbol(None if data is None else str(data))

    def apply_style(self, *, opacity: object = None, symbol: str | None = None) -> None:
        """Restore shape and opacity from session state. Unknown values are ignored."""
        if isinstance(symbol, str) and symbol.strip():
            idx = self.shape_combo.findData(symbol.strip())
            if idx >= 0:
                self.shape_combo.setCurrentIndex(idx)
        if opacity is None:
            return
        try:
            percent = round(clamp_marker_opacity(float(opacity)) * 100.0)
        except (TypeError, ValueError):
            return
        self.opacity_spin.setValue(percent)

    def set_style_enabled(self, enabled: bool) -> None:
        """Enable shape and opacity when the current plot draws point markers."""
        for widget in (
            self._shape_label,
            self.shape_combo,
            self._opacity_label,
            self.opacity_spin,
        ):
            widget.setEnabled(enabled)
