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

"""Session save/restore for :class:`PlotWidget`."""

from __future__ import annotations

from typing import TypeVar

from PyQt5.QtWidgets import QComboBox

from ..plotting.plot_axes import PLOT_SESSION_KIND
from ..plotting.plot_radar import SPOKE_NONE

_T = TypeVar("_T", bound="PlotSessionMixin")


class PlotSessionMixin:
    """Persist and restore Plotter control state in ``.cms`` sessions."""

    def collect_session_state(self) -> dict:
        """JSON-safe Plotter settings for ``.cms`` session files."""
        spokes = [c.currentText() for c in getattr(self, "spoke_combos", None) or []]
        entries = [e.text() for e in getattr(self, "entry_edits", None) or []]
        fit_key = self.fit_combo.currentData()
        return {
            "kind": PLOT_SESSION_KIND,
            "plot_type": self._current_plot_type(),
            "x": self.x_combo.currentText(),
            "y": self.y_combo.currentText(),
            "z": self.z_combo.currentText(),
            "xmin": self.xmin.text(),
            "xmax": self.xmax.text(),
            "ymin": self.ymin.text(),
            "ymax": self.ymax.text(),
            "zmin": self.zmin.text(),
            "zmax": self.zmax.text(),
            "hist_bin_width": self.hist_bin_width.text(),
            "heatmap_y_bin_width": self.heatmap_y_bin_width.text(),
            "color": self.color_combo.currentText(),
            "colorscale": self.colorscale_combo.currentText(),
            "invert_spectrum": bool(self.invert_spectrum_cb.isChecked()),
            "color_min": self.color_range.color_min.text(),
            "color_max": self.color_range.color_max.text(),
            "size": self.size_combo.currentText(),
            "size_min": float(self.size_range.size_min.value()),
            "size_max": float(self.size_range.size_max.value()),
            "marker_opacity": self._markers_group.marker_opacity(),
            "marker_symbol": self._markers_group.marker_symbol(),
            "fit": fit_key if isinstance(fit_key, str) else "",
            "show_fit_formula": bool(self.show_fit_formula_cb.isChecked()),
            "fit_trunc_lower": self.fit_trunc_lower.text(),
            "fit_trunc_upper": self.fit_trunc_upper.text(),
            "plot_title": self.plot_title_edit.text(),
            "xaxis_title": self.xaxis_title_edit.text(),
            "yaxis_title": self.yaxis_title_edit.text(),
            "zaxis_title": self.zaxis_title_edit.text(),
            "only_selected": bool(self.only_selected_cb.isChecked()),
            **self._hover_controls.collect_state(),
            "radar_spokes": spokes,
            "radar_entries": entries,
        }

    @staticmethod
    def _set_combo_text(combo: QComboBox, text: str | None) -> None:
        if not text:
            return
        idx = combo.findText(str(text))
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def apply_session_state(self, state: dict | None) -> None:
        """Restore Plotter controls from ``collect_session_state``."""
        if not isinstance(state, dict):
            return
        ptype = state.get("plot_type")
        self.plot_type_combo.blockSignals(True)
        self.x_combo.blockSignals(True)
        self.y_combo.blockSignals(True)
        self.z_combo.blockSignals(True)
        try:
            if isinstance(ptype, str):
                idx = self.plot_type_combo.findData(ptype)
                if idx >= 0:
                    self.plot_type_combo.setCurrentIndex(idx)
            self._set_combo_text(self.x_combo, state.get("x"))
            self._set_combo_text(self.y_combo, state.get("y"))
            self._set_combo_text(self.z_combo, state.get("z"))
        finally:
            self.plot_type_combo.blockSignals(False)
            self.x_combo.blockSignals(False)
            self.y_combo.blockSignals(False)
            self.z_combo.blockSignals(False)
        self._prev_range_axis = {
            "x": self.x_combo.currentText(),
            "y": self._combo_axis_name(self.y_combo) or "",
            "z": self._combo_axis_name(self.z_combo) or "",
        }
        for edit, key in (
            (self.xmin, "xmin"),
            (self.xmax, "xmax"),
            (self.ymin, "ymin"),
            (self.ymax, "ymax"),
            (self.zmin, "zmin"),
            (self.zmax, "zmax"),
            (self.hist_bin_width, "hist_bin_width"),
            (self.heatmap_y_bin_width, "heatmap_y_bin_width"),
            (self.plot_title_edit, "plot_title"),
            (self.xaxis_title_edit, "xaxis_title"),
            (self.yaxis_title_edit, "yaxis_title"),
            (self.zaxis_title_edit, "zaxis_title"),
            (self.fit_trunc_lower, "fit_trunc_lower"),
            (self.fit_trunc_upper, "fit_trunc_upper"),
        ):
            val = state.get(key)
            if isinstance(val, str):
                edit.setText(val)
        self._on_plot_type_change()
        self._set_combo_text(self.color_combo, state.get("color"))
        self._set_combo_text(self.colorscale_combo, state.get("colorscale"))
        self._set_combo_text(self.size_combo, state.get("size"))
        if "invert_spectrum" in state:
            self.invert_spectrum_cb.blockSignals(True)
            self.invert_spectrum_cb.setChecked(bool(state.get("invert_spectrum")))
            self.invert_spectrum_cb.blockSignals(False)
        cmin, cmax = state.get("color_min"), state.get("color_max")
        if isinstance(cmin, str):
            self.color_range.color_min.setText(cmin)
        if isinstance(cmax, str):
            self.color_range.color_max.setText(cmax)
        try:
            if state.get("size_min") is not None:
                self.size_range.size_min.setValue(float(state["size_min"]))
            if state.get("size_max") is not None:
                self.size_range.size_max.setValue(float(state["size_max"]))
        except (TypeError, ValueError):
            pass
        self._markers_group.apply_style(
            opacity=state.get("marker_opacity"),
            symbol=state.get("marker_symbol")
            if isinstance(state.get("marker_symbol"), str)
            else None,
        )
        fit_key = state.get("fit")
        if isinstance(fit_key, str) and fit_key:
            fidx = self.fit_combo.findData(fit_key)
            if fidx >= 0:
                self.fit_combo.setCurrentIndex(fidx)
        if "show_fit_formula" in state:
            self.show_fit_formula_cb.setChecked(bool(state.get("show_fit_formula")))
        if "only_selected" in state:
            self.only_selected_cb.setChecked(bool(state.get("only_selected")))
        self._hover_controls.apply_state(state)
        spokes = state.get("radar_spokes")
        if isinstance(spokes, list):
            for combo, name in zip(self.spoke_combos, spokes, strict=False):
                self._set_combo_text(combo, str(name) if name else SPOKE_NONE)
        entries = state.get("radar_entries")
        if isinstance(entries, list):
            for edit, text in zip(self.entry_edits, entries, strict=False):
                edit.setText(str(text) if text is not None else "")
        self._update_color_controls()
        self._plot_shown = True
        self._schedule_plot()

    @classmethod
    def from_session_state(cls: type[_T], parent_app, state: dict | None) -> _T:
        widget = cls(parent_app)
        widget.apply_session_state(state)
        return widget
