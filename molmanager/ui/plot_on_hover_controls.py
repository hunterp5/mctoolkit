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

"""Shared On Hover plot-options group (structure + column pickers + persist)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QCheckBox, QComboBox, QGroupBox, QHBoxLayout, QVBoxLayout, QWidget

from .plot_hover import hover_column_choices


class PlotOnHoverControls(QGroupBox):
    """Plotter-style On Hover settings reused by analysis plot option dialogs."""

    changed = pyqtSignal()
    persist_changed = pyqtSignal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("On Hover", parent)
        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self._hover_combos: list[QComboBox] = []
        for _ in range(3):
            cb = QComboBox()
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            cb.currentIndexChanged.connect(lambda _i: self._emit_changed())
            layout.addWidget(cb)
            self._hover_combos.append(cb)

        option_row = QHBoxLayout()
        option_row.setContentsMargins(0, 0, 0, 0)
        option_row.setSpacing(12)
        self.hover_structure_cb = QCheckBox("Show Structure")
        self.hover_structure_cb.setChecked(True)
        self.hover_structure_cb.setToolTip(
            "Show a small 2D depiction of the molecule next to the hover card."
        )
        self.hover_structure_cb.stateChanged.connect(self._emit_changed)
        option_row.addWidget(self.hover_structure_cb)
        self.hover_persist_cb = QCheckBox("Persistent on Select")
        self.hover_persist_cb.setChecked(False)
        self.hover_persist_cb.setToolTip(
            "Keep the hover card near selected point(s); multiple selections are shown together."
        )
        self.hover_persist_cb.stateChanged.connect(self._emit_persist_changed)
        option_row.addWidget(self.hover_persist_cb)
        option_row.addStretch(1)
        layout.addLayout(option_row)

    def _emit_changed(self, *_args) -> None:
        self.changed.emit()

    def _emit_persist_changed(self, *_args) -> None:
        self.persist_changed.emit()
        self.changed.emit()

    def reload_columns(self, headers: list[str] | None) -> None:
        """Populate column pickers from table headers, preserving prior choices."""
        combos = self._hover_combos
        if not combos:
            return
        choices = hover_column_choices(headers)
        prev = [cb.currentText() for cb in combos]
        for cb in combos:
            cb.blockSignals(True)
        try:
            for cb in combos:
                cb.clear()
                cb.addItem("—", userData=None)
                for h in choices:
                    cb.addItem(h, userData=h)
            for cb, p in zip(combos, prev, strict=False):
                if p and p != "—":
                    j = cb.findText(p)
                    if j >= 0:
                        cb.setCurrentIndex(j)
        finally:
            for cb in combos:
                cb.blockSignals(False)

    def selected_columns(self) -> list[str]:
        cols: list[str] = []
        for cb in self._hover_combos:
            h = cb.currentData()
            if h:
                cols.append(str(h))
        return cols

    def show_structure(self) -> bool:
        return bool(self.hover_structure_cb.isChecked())

    def persist_on_select(self) -> bool:
        return bool(self.hover_persist_cb.isChecked())

    def collect_state(self) -> dict[str, Any]:
        cols: list[str] = []
        for cb in self._hover_combos:
            h = cb.currentData()
            cols.append(str(h) if h else "")
        return {
            "hover_structure": self.show_structure(),
            "hover_persist": self.persist_on_select(),
            "hover_columns": cols,
        }

    def apply_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        if "hover_structure" in state:
            self.hover_structure_cb.setChecked(bool(state.get("hover_structure")))
        if "hover_persist" in state:
            self.hover_persist_cb.setChecked(bool(state.get("hover_persist")))
        hover_cols = state.get("hover_columns")
        if isinstance(hover_cols, list):
            for cb, name in zip(self._hover_combos, hover_cols, strict=False):
                text = str(name or "").strip()
                if not text or text == "—":
                    cb.setCurrentIndex(0)
                    continue
                idx = cb.findText(text)
                if idx >= 0:
                    cb.setCurrentIndex(idx)

    def apply_to_plot_view(self, plot_view: Any) -> None:
        """Push current options into a :class:`PlotlyInteractiveView` (or compatible)."""
        if plot_view is None:
            return
        setter = getattr(plot_view, "set_hover_options", None)
        if not callable(setter):
            return
        setter(
            columns=self.selected_columns(),
            show_structure=self.show_structure(),
            persist=self.persist_on_select(),
        )
