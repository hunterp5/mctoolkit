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

"""Modeless Activity Cliff Map: scatter of MMP change size vs |Δactivity|."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..analysis.activity_cliff_analysis import ActivityCliffPoint, build_activity_cliff_points
from ..analysis.mmp_analysis import MmpPair
from .activity_cliff_plot import build_activity_cliff_figure
from .dockable_plot import style_plot_footer_text_button
from .plotly_interactive_view import PlotlyInteractiveView
from .plot_table_sync import reindex_retained_point, retained_pair_points
from .qt_widget_utils import make_window_resizable
from .result_plot_panel import DockableResultPlotPanel

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except Exception:
    _HAS_WEB = False


class ActivityCliffMapPanel(DockableResultPlotPanel):
    """Interactive cliff scatter; click a point to select the pair and browse evidence."""

    SESSION_KIND = "activity_cliff_map"

    def __init__(
        self,
        parent_app: Any,
        pairs: list[MmpPair] | None = None,
        *,
        activity_column: str = "",
        x_mode: str = "heavy_atoms",
        parent=None,
    ):
        super().__init__(
            parent_app,
            window_title="Activity Cliff Map",
            floating_dialog_cls=ActivityCliffMapDialog,
            default_color_hint="signed Δactivity",
            parent=parent,
        )
        self._pairs: list[MmpPair] = []
        self._points: list[ActivityCliffPoint] = []
        self._plotted_points: list[ActivityCliffPoint] = []
        self._activity_column = activity_column or ""
        self._x_mode = x_mode or "heavy_atoms"
        self._current_index: int | None = None

        x_row = QHBoxLayout()
        x_row.addWidget(QLabel("X axis:"))
        self._x_combo = QComboBox()
        self._x_combo.addItem("Changing heavy atoms", "heavy_atoms")
        self._x_combo.addItem("Fragment distance (1 − Tanimoto)", "frag_distance")
        idx = self._x_combo.findData(self._x_mode)
        if idx >= 0:
            self._x_combo.setCurrentIndex(idx)
        self._x_combo.currentIndexChanged.connect(lambda _i: self._rebuild_figure())
        x_row.addWidget(self._x_combo, 1)
        self._extra_opts_layout.addLayout(x_row)

        self._plot_view: PlotlyInteractiveView | None = None
        if _HAS_WEB and parent_app is not None:
            self._plot_view = _CliffPlotView(parent_app, self)
            self._plot_view.pointActivated.connect(self._on_point_activated)
            self._root.addWidget(self._plot_view, 1)
        else:
            missing = QLabel("Plotly WebEngine view is unavailable in this build.")
            missing.setAlignment(Qt.AlignCenter)
            self._root.addWidget(missing, 1)

        foot = self._footer_bar.layout()
        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setEnabled(False)
        self._btn_browse.setToolTip("Open the MMP pair browser for the selected cliff point")
        style_plot_footer_text_button(self._btn_browse)
        clear_idx = foot.indexOf(self._clear_sel_btn)
        insert_at = clear_idx + 1 if clear_idx >= 0 else 2
        foot.insertWidget(insert_at, self._btn_browse)
        self._btn_browse.clicked.connect(self._browse_current)

        self._finish_layout()
        self.set_pairs(pairs or [], activity_column=activity_column, x_mode=self._x_mode)

    def set_pairs(
        self,
        pairs: list[MmpPair],
        *,
        activity_column: str | None = None,
        x_mode: str | None = None,
    ) -> None:
        self._pairs = list(pairs or [])
        if activity_column is not None:
            self._activity_column = activity_column
        if x_mode is not None:
            self._x_mode = x_mode
            idx = self._x_combo.findData(self._x_mode)
            if idx >= 0:
                self._x_combo.blockSignals(True)
                self._x_combo.setCurrentIndex(idx)
                self._x_combo.blockSignals(False)
        self._points = build_activity_cliff_points(self._pairs)
        self._current_index = None
        self._btn_browse.setEnabled(False)
        self._reload_color_columns()
        self._rebuild_figure()

    def collect_session_state(self) -> dict:
        return {
            "kind": self.SESSION_KIND,
            **self._collect_encoding_chrome_state(),
            "activity_column": self._activity_column,
            "x_mode": str(self._x_combo.currentData() or self._x_mode),
            "pairs": [asdict(p) for p in self._pairs],
        }

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        from ..analysis.mmp_analysis import MmpPair

        pairs: list[MmpPair] = []
        raw_pairs = state.get("pairs")
        if isinstance(raw_pairs, list):
            for raw in raw_pairs:
                if isinstance(raw, dict):
                    pairs.append(MmpPair(**raw))
        self._apply_encoding_chrome_state(state)
        x_mode = str(state.get("x_mode") or "heavy_atoms")
        self.set_pairs(
            pairs,
            activity_column=str(state.get("activity_column") or ""),
            x_mode=x_mode,
        )

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "ActivityCliffMapPanel":
        panel = cls(parent_app, pairs=[], activity_column="")
        panel.apply_session_state(state)
        return panel

    def _encoding_sample_values(self):
        color_col = self.color_combo.currentText()
        if color_col == "(none)" or not self._points:
            return None
        pairs = [(p.oid_a, p.oid_b) for p in self._points[:64]]
        return self._column_values_for_oid_pairs(pairs, color_col)

    def _rebuild_figure(self) -> None:
        if self._plot_view is None:
            return
        self._x_mode = str(self._x_combo.currentData() or "heavy_atoms")
        points = self._points_for_visible_rows()
        self._current_index = reindex_retained_point(
            self._plotted_points, points, self._current_index
        )
        if self._current_index is None:
            self._btn_browse.setEnabled(False)
        self._plotted_points = points
        pairs = [(p.oid_a, p.oid_b) for p in points]
        enc = self._resolved_encoding(oid_pairs=pairs)
        fig = build_activity_cliff_figure(
            points,
            activity_column=self._activity_column,
            x_mode=self._x_mode,
            **enc,
        )
        oids = [p.oid_a for p in points]
        partners = [p.oid_b for p in points]
        self._plot_view.push_figure(fig, oids, partner_oids=partners)
        self._update_spectrum_controls()

    def _points_for_visible_rows(self) -> list[ActivityCliffPoint]:
        return retained_pair_points(self.parent_app, self._points)

    def _on_point_activated(self, point_index: int) -> None:
        plotted = self._plotted_points
        if not (0 <= point_index < len(plotted)):
            self._current_index = None
            self._btn_browse.setEnabled(False)
            return
        self._current_index = int(point_index)
        self._btn_browse.setEnabled(True)
        # Table selection is applied by the plot view (both pair partners).

    def _current_pair(self) -> MmpPair | None:
        if self._current_index is None:
            return None
        plotted = self._plotted_points
        if not (0 <= self._current_index < len(plotted)):
            return None
        pair_index = plotted[self._current_index].pair_index
        if not (0 <= pair_index < len(self._pairs)):
            return None
        return self._pairs[pair_index]

    def _browse_current(self) -> None:
        pair = self._current_pair()
        app = self.parent_app
        if pair is None or app is None:
            return
        try:
            app._open_mmp_browser([pair], activity_column=self._activity_column)
        except Exception:
            pass

    def _clear_selection(self) -> None:
        self._current_index = None
        self._btn_browse.setEnabled(False)
        if self._plot_view is not None:
            try:
                self._plot_view.clear_table_selection(update_plot=True)
            except Exception:
                pass
        elif self.parent_app is not None:
            try:
                self.parent_app.clear_table_selection()
            except Exception:
                pass


class ActivityCliffMapDialog(QDialog):
    """Floating window hosting a :class:`ActivityCliffMapPanel`."""

    def __init__(
        self,
        parent: Any,
        pairs: list[MmpPair] | None = None,
        *,
        activity_column: str = "",
        x_mode: str = "heavy_atoms",
        panel: ActivityCliffMapPanel | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.parent_app = parent
        else:
            self._panel = ActivityCliffMapPanel(
                parent,
                pairs or [],
                activity_column=activity_column,
                x_mode=x_mode,
            )

        self.setWindowTitle("Activity Cliff Map")
        self.resize(960, 680)
        self.setMinimumSize(640, 480)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._panel, 1)
        self._panel._sync_footer_chrome()
        make_window_resizable(self)

    def set_pairs(self, *args, **kwargs) -> None:
        if self._panel is not None:
            self._panel.set_pairs(*args, **kwargs)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        from .dockable_plot import handle_floating_plot_close_event

        handle_floating_plot_close_event(self, event)


class _CliffPlotView(PlotlyInteractiveView):
    """Plotly view that notifies the cliff dialog when a point is activated."""

    pointActivated = pyqtSignal(int)

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        super()._on_plot_point_clicked(point_index, additive=additive)
        self.pointActivated.emit(int(point_index))

    def _on_plot_points_selected(self, points_json: str, additive: bool = False) -> None:
        super()._on_plot_points_selected(points_json, additive=additive)
        if self._selected_point_indices:
            self.pointActivated.emit(int(sorted(self._selected_point_indices)[0]))
