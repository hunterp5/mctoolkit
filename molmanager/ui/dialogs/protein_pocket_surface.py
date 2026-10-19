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

"""Protein Viewer dialog for pocket-surface color, opacity, and wireframe."""

from __future__ import annotations

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import make_window_minimizable

POCKET_SURFACE_TYPES = (
    ("ms", "Molecular"),
    ("vdw", "van der Waals"),
    ("sas", "Solvent accessible"),
)

POCKET_SURFACE_COLORS = (
    ("lightgray", "Light gray"),
    ("white", "White"),
    ("gray", "Gray"),
    ("green", "Green"),
    ("cyan", "Cyan"),
    ("magenta", "Magenta"),
    ("yellow", "Yellow"),
    ("orange", "Orange"),
    ("purple", "Purple"),
    ("blue", "Blue"),
    ("element", "Element (CPK)"),
    ("hydrophobicity", "Hydrophobicity"),
    ("charge", "Charge"),
    ("custom", "Custom…"),
)

DEFAULT_POCKET_SURFACE_SETTINGS = {
    "color": "lightgray",
    "opacity": 0.7,
    "wireframe": False,
    "linewidth": 1.5,
    "surfaceType": "ms",
    "colorScheme": "solid",
}

_PROPERTY_COLOR_SCHEMES = frozenset({"element", "hydrophobicity", "charge"})
_NAMED_COLORS = {
    key for key, _label in POCKET_SURFACE_COLORS if key not in _PROPERTY_COLOR_SCHEMES | {"custom"}
}
_SCHEME_SWATCHES = {
    "hydrophobicity": (
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        "stop:0 #2c7bb6, stop:0.5 #f7f7f7, stop:1 #d95f0e);"
    ),
    "charge": (
        "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
        "stop:0 #d7191c, stop:0.5 #f7f7f7, stop:1 #2c7bb6);"
    ),
}


def normalize_pocket_surface_settings(raw: dict | None) -> dict:
    """Return a complete pocket-surface style dict from a session or UI payload."""
    src = raw if isinstance(raw, dict) else {}
    out = dict(DEFAULT_POCKET_SURFACE_SETTINGS)
    color = str(src.get("color") or out["color"]).strip() or out["color"]
    scheme = str(src.get("colorScheme") or "").strip() or "solid"
    if scheme in _PROPERTY_COLOR_SCHEMES or color in _PROPERTY_COLOR_SCHEMES:
        out["colorScheme"] = scheme if scheme in _PROPERTY_COLOR_SCHEMES else color
        out["color"] = "lightgray"
    elif color.startswith("#") and len(color) >= 4:
        out["colorScheme"] = "solid"
        out["color"] = color
    elif color in _NAMED_COLORS:
        out["colorScheme"] = "solid"
        out["color"] = color
    else:
        out["colorScheme"] = "solid"
        out["color"] = "lightgray"
    try:
        opacity = float(src.get("opacity", out["opacity"]))
    except (TypeError, ValueError):
        opacity = float(out["opacity"])
    out["opacity"] = min(1.0, max(0.05, opacity))
    out["wireframe"] = bool(src.get("wireframe", out["wireframe"]))
    try:
        width = float(src.get("linewidth", out["linewidth"]))
    except (TypeError, ValueError):
        width = float(out["linewidth"])
    out["linewidth"] = min(4.0, max(0.5, width))
    surface_type = str(src.get("surfaceType") or out["surfaceType"]).strip().lower()
    if surface_type not in {key for key, _label in POCKET_SURFACE_TYPES}:
        surface_type = "ms"
    out["surfaceType"] = surface_type
    return out


class ProteinPocketSurfaceDialog(QDialog):
    """Options for Protein Viewer → Render → Pocket Surface."""

    settings_changed = pyqtSignal(dict)
    show_toggled = pyqtSignal(bool)
    generate_requested = pyqtSignal()

    def __init__(self, viewer, parent=None) -> None:
        super().__init__(parent or viewer)
        self._updating = False
        self._custom_color = "#d3d3d3"
        self.setWindowTitle("Pocket Surface")
        self.setMinimumWidth(360)
        self.resize(380, 280)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(6)

        self.chk_show = QCheckBox("Show pocket surface")
        self.chk_show.setToolTip("Draw a surface on protein residues within 4.5 Å of the ligand.")
        form.addRow(self.chk_show)

        self.combo_type = QComboBox()
        for key, label in POCKET_SURFACE_TYPES:
            self.combo_type.addItem(label, key)
        self.combo_type.setToolTip(
            "Molecular is the solvent-excluded surface of the pocket residues. "
            "van der Waals is the union of atom spheres. Solvent accessible is expanded "
            "by a water probe."
        )
        form.addRow("Type:", self.combo_type)

        self.combo_color = QComboBox()
        for key, label in POCKET_SURFACE_COLORS:
            self.combo_color.addItem(label, key)
        self.combo_color.setToolTip(
            "Solid color, element CPK, Kyte–Doolittle hydrophobicity "
            "(blue hydrophilic, orange hydrophobic), amino-acid partial charge "
            "(red negative, blue positive), or a custom color."
        )
        self.btn_color = QPushButton()
        self.btn_color.setFixedWidth(36)
        self.btn_color.setToolTip("Choose a custom surface color.")
        color_row = QWidget()
        color_l = QHBoxLayout(color_row)
        color_l.setContentsMargins(0, 0, 0, 0)
        color_l.setSpacing(6)
        color_l.addWidget(self.combo_color, 1)
        color_l.addWidget(self.btn_color)
        form.addRow("Color:", color_row)

        self.spin_opacity = QDoubleSpinBox()
        self.spin_opacity.setRange(5.0, 100.0)
        self.spin_opacity.setDecimals(0)
        self.spin_opacity.setSingleStep(5.0)
        self.spin_opacity.setSuffix(" %")
        self.spin_opacity.setValue(70.0)
        self.spin_opacity.setToolTip("How see-through the surface is (100% is solid).")
        form.addRow("Opacity:", self.spin_opacity)

        self.chk_wireframe = QCheckBox("Wireframe")
        self.chk_wireframe.setToolTip("Draw the surface as a mesh instead of a solid.")
        form.addRow(self.chk_wireframe)

        self.spin_linewidth = QDoubleSpinBox()
        self.spin_linewidth.setRange(0.5, 4.0)
        self.spin_linewidth.setDecimals(1)
        self.spin_linewidth.setSingleStep(0.5)
        self.spin_linewidth.setValue(1.5)
        self.spin_linewidth.setToolTip("Mesh line thickness when Wireframe is on.")
        form.addRow("Line width:", self.spin_linewidth)
        root.addLayout(form)
        root.addStretch()

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_ok = QPushButton("OK")
        self.btn_ok.setDefault(True)
        self.btn_ok.setToolTip("Draw the pocket surface with these options.")
        self.btn_ok.clicked.connect(self._on_ok_clicked)
        btn_row.addWidget(self.btn_ok)
        root.addLayout(btn_row)

        self.chk_show.toggled.connect(self._on_show_toggled)
        self.combo_type.currentIndexChanged.connect(self._on_options_changed)
        self.combo_color.currentIndexChanged.connect(self._on_color_chosen)
        self.btn_color.clicked.connect(self._pick_custom_color)
        self.spin_opacity.valueChanged.connect(self._on_options_changed)
        self.chk_wireframe.toggled.connect(self._on_wireframe_toggled)
        self.spin_linewidth.valueChanged.connect(self._on_options_changed)
        self._sync_enabled()
        self._refresh_color_button()
        make_window_minimizable(self)

    def settings(self) -> dict:
        """Current type, color, opacity, and wireframe options."""
        color_key = self.combo_color.currentData() or "lightgray"
        if color_key in _PROPERTY_COLOR_SCHEMES:
            color = "lightgray"
            scheme = str(color_key)
        elif color_key == "custom":
            color = self._custom_color
            scheme = "solid"
        else:
            color = str(color_key)
            scheme = "solid"
        return {
            "color": color,
            "opacity": float(self.spin_opacity.value()) / 100.0,
            "wireframe": self.chk_wireframe.isChecked(),
            "linewidth": float(self.spin_linewidth.value()),
            "surfaceType": self.combo_type.currentData() or "ms",
            "colorScheme": scheme,
        }

    def set_settings(self, raw: dict | None) -> None:
        """Load saved options without emitting live updates."""
        settings = normalize_pocket_surface_settings(raw)
        self._updating = True
        try:
            type_idx = self.combo_type.findData(settings["surfaceType"])
            if type_idx >= 0:
                self.combo_type.setCurrentIndex(type_idx)
            color = settings["color"]
            if settings["colorScheme"] in _PROPERTY_COLOR_SCHEMES:
                idx = self.combo_color.findData(settings["colorScheme"])
            elif str(color).startswith("#"):
                self._custom_color = str(color)
                idx = self.combo_color.findData("custom")
            else:
                idx = self.combo_color.findData(color)
            if idx < 0:
                idx = self.combo_color.findData("lightgray")
            if idx >= 0:
                self.combo_color.setCurrentIndex(idx)
            self.spin_opacity.setValue(round(float(settings["opacity"]) * 100.0))
            self.chk_wireframe.setChecked(bool(settings["wireframe"]))
            self.spin_linewidth.setValue(float(settings["linewidth"]))
            self._sync_enabled()
            self._refresh_color_button()
        finally:
            self._updating = False

    def set_showing(self, showing: bool) -> None:
        """Update the Show checkbox without emitting ``show_toggled``."""
        self._updating = True
        try:
            self.chk_show.setChecked(bool(showing))
        finally:
            self._updating = False

    def is_showing(self) -> bool:
        return self.chk_show.isChecked()

    def _sync_enabled(self) -> None:
        property_scheme = self.combo_color.currentData() in _PROPERTY_COLOR_SCHEMES
        self.btn_color.setEnabled(not property_scheme)
        self.spin_linewidth.setEnabled(self.chk_wireframe.isChecked())

    def _refresh_color_button(self) -> None:
        key = self.combo_color.currentData() or "lightgray"
        swatch = _SCHEME_SWATCHES.get(str(key))
        if swatch:
            self.btn_color.setStyleSheet(swatch)
            return
        if key == "element":
            fill = "#888888"
        elif key == "custom":
            fill = self._custom_color
        else:
            named = QColor(str(key))
            fill = named.name() if named.isValid() else "#d3d3d3"
        self.btn_color.setStyleSheet(f"background-color: {fill};")

    def _on_ok_clicked(self) -> None:
        """Ask the viewer to build the pocket surface from the current options."""
        self.generate_requested.emit()

    def _on_show_toggled(self, checked: bool) -> None:
        if self._updating:
            return
        self.show_toggled.emit(bool(checked))

    def _on_wireframe_toggled(self, _checked: bool) -> None:
        self._sync_enabled()
        self._on_options_changed()

    def _on_color_chosen(self, _index: int = 0) -> None:
        if self._updating:
            return
        if self.combo_color.currentData() == "custom":
            if not self._pick_custom_color():
                self._updating = True
                try:
                    fallback = self.combo_color.findData("lightgray")
                    if fallback >= 0:
                        self.combo_color.setCurrentIndex(fallback)
                finally:
                    self._updating = False
                self._sync_enabled()
                self._refresh_color_button()
            return
        self._sync_enabled()
        self._refresh_color_button()
        self._on_options_changed()

    def _pick_custom_color(self) -> bool:
        start = QColor(self._custom_color)
        if not start.isValid():
            start = QColor("#d3d3d3")
        chosen = QColorDialog.getColor(start, self, "Pocket surface color")
        if not chosen.isValid():
            return False
        self._custom_color = chosen.name()
        self._updating = True
        try:
            idx = self.combo_color.findData("custom")
            if idx >= 0:
                self.combo_color.setCurrentIndex(idx)
        finally:
            self._updating = False
        self._sync_enabled()
        self._refresh_color_button()
        self._on_options_changed()
        return True

    def _on_options_changed(self, *_args) -> None:
        if self._updating:
            return
        self.settings_changed.emit(self.settings())
