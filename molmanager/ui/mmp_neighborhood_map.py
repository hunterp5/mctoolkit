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

"""Modeless MMP pair neighborhood network viewer."""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any

from PyQt5.QtCore import QObject, Qt, QRunnable, QThreadPool, pyqtSignal
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ..analysis.mmp_analysis import MmpPair, pairs_involving_oid
from ..analysis.mmp_neighborhood_analysis import MmpNetworkGraph, build_mmp_network_graph
from .dockable_plot import style_plot_footer_text_button
from .mmp_neighborhood_plot import _MMP_MARKER_OPACITY, build_mmp_neighborhood_figure
from .plotly_interactive_view import PlotlyInteractiveView
from .qt_widget_utils import make_window_minimizable
from .result_plot_panel import DockableResultPlotPanel

logger = logging.getLogger(__name__)

try:
    from PyQt5.QtWebEngineWidgets import QWebEngineView  # noqa: F401

    _HAS_WEB = True
except Exception:
    _HAS_WEB = False


class _LayoutSignals(QObject):
    finished = pyqtSignal(int, object)  # generation, MmpNetworkGraph
    failed = pyqtSignal(int, str)


class _LayoutWorker(QRunnable):
    """Build network layout off the GUI thread."""

    def __init__(
        self,
        generation: int,
        pairs: list[MmpPair],
        *,
        focus_oids: list[int] | None,
        max_hops: int,
        signals: _LayoutSignals,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._generation = int(generation)
        self._pairs = pairs
        self._focus_oids = focus_oids
        self._max_hops = int(max_hops)
        self._signals = signals

    def run(self) -> None:
        try:
            graph = build_mmp_network_graph(
                self._pairs,
                focus_oids=self._focus_oids,
                max_hops=self._max_hops if self._focus_oids else 0,
            )
            self._signals.finished.emit(self._generation, graph)
        except Exception as exc:
            logger.exception("MMP network layout failed")
            self._signals.failed.emit(self._generation, str(exc) or "Layout failed.")


class MmpNeighborhoodMapPanel(DockableResultPlotPanel):
    """Interactive MMP pair network; click a node to select it in the table."""

    SESSION_KIND = "mmp_neighborhood_map"

    def __init__(
        self,
        parent_app: Any,
        pairs: list[MmpPair] | None = None,
        *,
        activity_column: str = "",
        parent=None,
    ):
        super().__init__(
            parent_app,
            window_title="MMP Pair Network",
            floating_dialog_cls=MmpNeighborhoodMapDialog,
            default_color_hint=activity_column or "activity",
            parent=parent,
            default_marker_opacity=_MMP_MARKER_OPACITY,
        )
        self._pairs: list[MmpPair] = []
        self._graph: MmpNetworkGraph | None = None
        self._activity_column = activity_column or ""
        self._current_oid: int | None = None
        self._layout_generation = 0
        self._layout_signals = _LayoutSignals(self)
        self._layout_signals.finished.connect(self._on_layout_finished)
        self._layout_signals.failed.connect(self._on_layout_failed)
        self._pending_focus: list[int] | None = None

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Neighborhood hops:"))
        self._hops_sb = QSpinBox()
        self._hops_sb.setRange(0, 8)
        self._hops_sb.setValue(0)
        self._hops_sb.setToolTip(
            "0 = full network. When > 0, show only nodes within N hops of the "
            "current table selection (or the last clicked node)."
        )
        controls.addWidget(self._hops_sb)
        self._btn_rebuild = QPushButton("Rebuild focus")
        self._btn_rebuild.setToolTip(
            "Rebuild the graph using the current table selection as focus seeds "
            "(uses Neighborhood hops)."
        )
        style_plot_footer_text_button(self._btn_rebuild)
        controls.addWidget(self._btn_rebuild)
        controls.addStretch()
        self._extra_opts_layout.addLayout(controls)

        self._plot_view: PlotlyInteractiveView | None = None
        if _HAS_WEB and parent_app is not None:
            self._plot_view = _NetworkPlotView(parent_app, self)
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
            "Open the MMP pair browser for pairs involving the selected node."
        )
        style_plot_footer_text_button(self._btn_browse)
        clear_idx = foot.indexOf(self._clear_sel_btn)
        insert_at = clear_idx + 1 if clear_idx >= 0 else 2
        foot.insertWidget(insert_at, self._btn_browse)

        self._btn_rebuild.clicked.connect(self._rebuild_from_table_selection)
        self._btn_browse.clicked.connect(self._browse_current)

        self._finish_layout()
        self.set_pairs(pairs or [], activity_column=activity_column)

    def collect_session_state(self) -> dict:
        return {
            "kind": self.SESSION_KIND,
            **self._collect_encoding_chrome_state(),
            "activity_column": self._activity_column,
            "hops": int(self._hops_sb.value()),
            "pairs": [asdict(p) for p in self._pairs],
        }

    def apply_session_state(self, state: dict | None) -> None:
        if not isinstance(state, dict):
            return
        pairs: list[MmpPair] = []
        raw_pairs = state.get("pairs")
        if isinstance(raw_pairs, list):
            for raw in raw_pairs:
                if isinstance(raw, dict):
                    pairs.append(MmpPair(**raw))
        try:
            hops = int(state.get("hops", 0))
        except (TypeError, ValueError):
            hops = 0
        self._hops_sb.setValue(max(0, min(8, hops)))
        self._apply_encoding_chrome_state(state)
        self.set_pairs(pairs, activity_column=str(state.get("activity_column") or ""))

    @classmethod
    def from_session_state(cls, parent_app, state: dict | None) -> "MmpNeighborhoodMapPanel":
        panel = cls(parent_app, pairs=[], activity_column="")
        panel.apply_session_state(state)
        return panel

    def set_pairs(self, pairs: list[MmpPair], *, activity_column: str | None = None) -> None:
        self._pairs = list(pairs or [])
        if activity_column is not None:
            self._activity_column = activity_column
            self._default_color_hint = activity_column
        self._current_oid = None
        self._btn_browse.setEnabled(False)
        self._reload_color_columns()
        self._rebuild_graph(focus_oids=None)

    def _encoding_sample_values(self):
        color_col = self.color_combo.currentText()
        if color_col == "(none)" or self._graph is None:
            return None
        return self._column_values_for_oids(list(self._graph.node_oids[:64]), color_col)

    def _focus_oids_from_table(self) -> list[int]:
        app = self.parent_app
        if app is None:
            return []
        try:
            return sorted(int(o) for o in app._selected_oids_set())
        except Exception:
            return []

    def _rebuild_from_table_selection(self) -> None:
        hops = int(self._hops_sb.value())
        seeds = self._focus_oids_from_table()
        if hops > 0 and not seeds and self._current_oid is not None:
            seeds = [int(self._current_oid)]
        self._rebuild_graph(focus_oids=seeds if hops > 0 else None)

    def _set_busy(self, busy: bool) -> None:
        self._btn_rebuild.setEnabled(not busy)
        self._hops_sb.setEnabled(not busy)

    def _rebuild_graph(self, *, focus_oids: list[int] | None) -> None:
        hops = int(self._hops_sb.value())
        self._pending_focus = list(focus_oids) if focus_oids else None
        self._layout_generation += 1
        generation = self._layout_generation
        n_pairs = len(self._pairs)
        app = self.parent_app
        if app is not None and hasattr(app, "status_label"):
            app.status_label.setText(f"MMP network: laying out {n_pairs:,} pair(s)…")
        self._set_busy(True)
        worker = _LayoutWorker(
            generation,
            self._pairs,
            focus_oids=self._pending_focus,
            max_hops=hops,
            signals=self._layout_signals,
        )
        QThreadPool.globalInstance().start(worker)

    def _on_layout_finished(self, generation: int, graph: object) -> None:
        if int(generation) != self._layout_generation:
            return
        self._set_busy(False)
        if not isinstance(graph, MmpNetworkGraph):
            app = self.parent_app
            if app is not None and hasattr(app, "status_label"):
                app.status_label.setText("MMP network: layout failed.")
            return
        self._graph = graph
        self._rebuild_figure()

    def _rebuild_figure(self) -> None:
        if self._plot_view is None or self._graph is None:
            return
        try:
            enc = self._resolved_encoding(oids=list(self._graph.node_oids))
            fig = build_mmp_neighborhood_figure(
                self._graph,
                activity_column=self._activity_column,
                **enc,
            )
            self._plot_view.push_figure(fig, list(self._graph.node_oids))
            self._update_spectrum_controls()
        except Exception:
            logger.exception("Failed to render MMP neighborhood figure")
            app = self.parent_app
            if app is not None and hasattr(app, "status_label"):
                app.status_label.setText("MMP network: plot render failed.")

    def _on_layout_failed(self, generation: int, message: str) -> None:
        if int(generation) != self._layout_generation:
            return
        self._set_busy(False)
        app = self.parent_app
        if app is not None and hasattr(app, "status_label"):
            app.status_label.setText(f"MMP network: {message or 'layout failed.'}")

    def _on_point_activated(self, point_index: int) -> None:
        if self._graph is None:
            return
        if not (0 <= point_index < len(self._graph.node_oids)):
            self._current_oid = None
            self._btn_browse.setEnabled(False)
            return
        oid = int(self._graph.node_oids[point_index])
        self._current_oid = oid
        self._btn_browse.setEnabled(True)
        # Table selection is applied by the plot view.

    def _clear_selection(self) -> None:
        self._current_oid = None
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

    def _browse_current(self) -> None:
        app = self.parent_app
        if app is None or self._current_oid is None:
            return
        subset = pairs_involving_oid(self._pairs, self._current_oid)
        if not subset:
            return
        try:
            app._open_mmp_browser(subset, activity_column=self._activity_column)
        except Exception:
            pass


class MmpNeighborhoodMapDialog(QDialog):
    """Floating window hosting a :class:`MmpNeighborhoodMapPanel`."""

    def __init__(
        self,
        parent: Any,
        pairs: list[MmpPair] | None = None,
        *,
        activity_column: str = "",
        panel: MmpNeighborhoodMapPanel | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        if panel is not None:
            self._panel = panel
            self._panel.setParent(self)
            self._panel.parent_app = parent
        else:
            self._panel = MmpNeighborhoodMapPanel(
                parent, pairs or [], activity_column=activity_column
            )

        self.setWindowTitle("MMP Pair Network")
        self.resize(980, 700)
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

    def set_pairs(self, *args, **kwargs) -> None:
        if self._panel is not None:
            self._panel.set_pairs(*args, **kwargs)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        from .dockable_plot import handle_floating_plot_close_event

        handle_floating_plot_close_event(self, event)


class _NetworkPlotView(PlotlyInteractiveView):
    """Plotly view that notifies when a network node is activated."""

    pointActivated = pyqtSignal(int)

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        super()._on_plot_point_clicked(point_index, additive=additive)
        self.pointActivated.emit(int(point_index))

    def _on_plot_points_selected(self, points_json: str, additive: bool = False) -> None:
        super()._on_plot_points_selected(points_json, additive=additive)
        if self._selected_point_indices:
            self.pointActivated.emit(int(sorted(self._selected_point_indices)[0]))
