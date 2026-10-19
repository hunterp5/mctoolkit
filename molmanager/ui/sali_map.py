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

"""Modeless SALI map: fingerprint similarity vs |Δactivity| or |Δselectivity|."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ..analysis.sali_analysis import SaliPoint
from .dockable_plot import style_plot_footer_text_button
from .plotly_interactive_view import PlotlyInteractiveView
from .plot_table_sync import visible_oids_for_plot
from .qt_widget_utils import make_window_minimizable
from .result_plot_panel import DockableResultPlotPanel
from .sali_plot import build_sali_figure

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except Exception:
    _HAS_WEB = False


class SaliMapPanel(DockableResultPlotPanel):
    """Interactive SALI scatter; click a point to select both molecules."""

    SESSION_KIND = "sali_map"

    def __init__(
        self,
        parent_app: Any,
        points: list[SaliPoint] | None = None,
        *,
        activity_column: str = "",
        fp_choice: str = "",
        metric: str = "Tanimoto",
        off_target_column: str = "",
        treat_logarithmically: bool = False,
        parent=None,
    ):
        super().__init__(
            parent_app,
            window_title="SALI",
            floating_dialog_cls=SaliMapDialog,
            default_color_hint="SALI index",
            parent=parent,
        )
        self._points: list[SaliPoint] = []
        self._plotted_points: list[SaliPoint] = []
        self._activity_column = activity_column or ""
        self._fp_choice = fp_choice or ""
        self._metric = metric or "Tanimoto"
        self._off_target_column = off_target_column or ""
        self._treat_logarithmically = bool(treat_logarithmically)
        self._current_index: int | None = None

        self._plot_view: PlotlyInteractiveView | None = None
        if _HAS_WEB and parent_app is not None:
            self._plot_view = _SaliPlotView(parent_app, self)
            self._plot_view.pointActivated.connect(self._on_point_activated)
            self._root.addWidget(self._plot_view, 1)
        else:
            missing = QLabel("Plotly WebEngine view is unavailable in this build.")
            missing.setAlignment(Qt.AlignCenter)
            self._root.addWidget(missing, 1)

        foot = self._footer_bar.layout()
        self._btn_browse = QPushButton("Browse")
        self._btn_browse.setEnabled(False)
        self._btn_browse.setToolTip(
            "Open the SALI pair browser for the selected point (step through plot pairs)."
        )
        style_plot_footer_text_button(self._btn_browse)
        clear_idx = foot.indexOf(self._clear_sel_btn)
        insert_at = clear_idx + 1 if clear_idx >= 0 else 2
        foot.insertWidget(insert_at, self._btn_browse)
        self._btn_browse.clicked.connect(self._browse_current)

        self._finish_layout()
        self.set_points(
            points or [],
            activity_column=activity_column,
            fp_choice=self._fp_choice,
            metric=self._metric,
            off_target_column=self._off_target_column,
            treat_logarithmically=self._treat_logarithmically,
        )

    def set_points(
        self,
        points: list[SaliPoint],
        *,
        activity_column: str | None = None,
        fp_choice: str | None = None,
        metric: str | None = None,
        off_target_column: str | None = None,
        treat_logarithmically: bool | None = None,
    ) -> None:
        self._points = list(points or [])
        if activity_column is not None:
            self._activity_column = activity_column
        if fp_choice is not None:
            self._fp_choice = fp_choice
        if metric is not None:
            self._metric = metric
        if off_target_column is not None:
            self._off_target_column = off_target_column
        if treat_logarithmically is not None:
            self._treat_logarithmically = bool(treat_logarithmically)
        self._current_index = None
        self._btn_browse.setEnabled(False)
        self._reload_color_columns()
        self._rebuild_figure()

    def collect_session_state(self) -> dict:
        return {
            "kind": self.SESSION_KIND,
            **self._collect_encoding_chrome_state(),
            "activity_column": self._activity_column,
            "off_target_column": self._off_target_column,
            "treat_logarithmically": self._treat_logarithmically,
            "fp_choice": self._fp_choice,
            "metric": self._metric,
            "points": [asdict(p) for p in self._points],
        }

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        points: list[SaliPoint] = []
        raw_pts = state.get("points")
        if isinstance(raw_pts, list):
            for raw in raw_pts:
                if isinstance(raw, dict):
                    points.append(SaliPoint(**raw))
        self._apply_encoding_chrome_state(state)
        self.set_points(
            points,
            activity_column=str(state.get("activity_column") or ""),
            fp_choice=str(state.get("fp_choice") or ""),
            metric=str(state.get("metric") or "Tanimoto"),
            off_target_column=str(state.get("off_target_column") or ""),
            treat_logarithmically=bool(state.get("treat_logarithmically")),
        )

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "SaliMapPanel":
        panel = cls(parent_app, points=[], activity_column="", fp_choice="", metric="Tanimoto")
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
        sim_label = f"{self._metric} similarity"
        if self._fp_choice:
            sim_label = f"{self._fp_choice} ({self._metric})"
        points = self._points_for_visible_rows()
        self._plotted_points = points
        pairs = [(p.oid_a, p.oid_b) for p in points]
        enc = self._resolved_encoding(oid_pairs=pairs)
        fig = build_sali_figure(
            points,
            activity_column=self._activity_column,
            similarity_label=sim_label,
            selectivity=bool(self._off_target_column),
            treat_logarithmically=self._treat_logarithmically,
            **enc,
        )
        oids = [p.oid_a for p in points]
        partners = [p.oid_b for p in points]
        self._plot_view.push_figure(fig, oids, partner_oids=partners)
        self._update_spectrum_controls()

    def _points_for_visible_rows(self) -> list[SaliPoint]:
        keep = visible_oids_for_plot(self.parent_app)
        if keep is None:
            return list(self._points)
        return [p for p in self._points if int(p.oid_a) in keep and int(p.oid_b) in keep]

    def _on_point_activated(self, point_index: int) -> None:
        plotted = self._plotted_points
        if not (0 <= point_index < len(plotted)):
            self._current_index = None
            self._btn_browse.setEnabled(False)
            return
        self._current_index = int(point_index)
        self._btn_browse.setEnabled(True)
        # Table selection is applied by the plot view (both pair partners).

    def _browse_current(self) -> None:
        if self._current_index is None or self.parent_app is None:
            return
        plotted = self._plotted_points
        if not (0 <= self._current_index < len(plotted)):
            return
        open_browser = getattr(self.parent_app, "_open_sali_browser", None)
        if not callable(open_browser):
            return
        try:
            point = plotted[self._current_index]
            start_index = next(
                (i for i, p in enumerate(self._points) if p is point or p == point),
                0,
            )
            open_browser(
                self._points,
                activity_column=self._activity_column,
                fp_choice=self._fp_choice,
                metric=self._metric,
                start_index=start_index,
                off_target_column=self._off_target_column,
                treat_logarithmically=self._treat_logarithmically,
            )
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


class SaliMapDialog(QDialog):
    """Floating window hosting a :class:`SaliMapPanel`."""

    def __init__(
        self,
        parent: Any,
        points: list[SaliPoint] | None = None,
        *,
        activity_column: str = "",
        fp_choice: str = "",
        metric: str = "Tanimoto",
        off_target_column: str = "",
        treat_logarithmically: bool = False,
        panel: SaliMapPanel | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.parent_app = parent
        else:
            self._panel = SaliMapPanel(
                parent,
                points or [],
                activity_column=activity_column,
                fp_choice=fp_choice,
                metric=metric,
                off_target_column=off_target_column,
                treat_logarithmically=treat_logarithmically,
            )

        self.setWindowTitle("SALI")
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
        make_window_minimizable(self)

    def set_points(self, *args, **kwargs) -> None:
        if self._panel is not None:
            self._panel.set_points(*args, **kwargs)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        from .dockable_plot import handle_floating_plot_close_event

        handle_floating_plot_close_event(self, event)


class _SaliPlotView(PlotlyInteractiveView):
    """Plotly view that notifies when a SALI point is activated."""

    pointActivated = pyqtSignal(int)

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        super()._on_plot_point_clicked(point_index, additive=additive)
        self.pointActivated.emit(int(point_index))

    def _on_plot_points_selected(self, points_json: str, additive: bool = False) -> None:
        super()._on_plot_points_selected(points_json, additive=additive)
        if self._selected_point_indices:
            self.pointActivated.emit(int(sorted(self._selected_point_indices)[0]))
