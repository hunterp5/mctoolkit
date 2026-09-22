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

"""Plotly shell load/push and table ↔ plot selection linking for :class:`PlotWidget`."""

from __future__ import annotations

import json
import time
import webbrowser

from PyQt5.QtCore import QTimer, QUrl
from plotly import graph_objects as go

from ..plotting.plot_axes import (
    PLOT_TYPE_BOX,
    PLOT_TYPE_HEATMAP,
    PLOT_TYPE_HISTOGRAM,
    PLOT_TYPE_LINE_2D,
    PLOT_TYPE_RADAR,
    PLOT_TYPE_VIOLIN,
)
from .plot_table_sync import (
    apply_table_selection_for_source_rows,
    build_oid_point_index,
    clear_table_selection_from_plot,
    point_indices_for_oids,
    run_javascript_apply_figure,
    run_javascript_set_selection,
    selected_oids_for_plot,
    selection_visual_push_key,
    source_rows_for_point_indices,
)


class PlotShellMixin:
    """Interactive shell lifecycle and bidirectional selection sync."""

    def _supports_table_linked_selection(self) -> bool:
        """Plot types that mirror table row selection via ``molmanagerSetSelection``."""
        ptype = self._current_plot_type()
        mode = self._effective_plot_mode()
        if ptype == PLOT_TYPE_LINE_2D and mode == "2D":
            return True
        if ptype == PLOT_TYPE_HEATMAP:
            return False
        if ptype in (PLOT_TYPE_BOX, PLOT_TYPE_VIOLIN, PLOT_TYPE_RADAR):
            return False
        if ptype == PLOT_TYPE_HISTOGRAM:
            return mode == "Histogram"
        return mode in ("2D", "3D")

    def _load_plot_shell(self) -> None:
        if self.web is None:
            return
        from .plotly_shell import ensure_interactive_plot_shell

        try:
            self._plot_shell_path = ensure_interactive_plot_shell()
            self.web.load(QUrl.fromLocalFile(str(self._plot_shell_path)))
        except RuntimeError:
            return

    def _annotate_scatter_selection_meta(self, fig: go.Figure) -> None:
        """Tell the Plotly shell which traces map to table row indices (skip fit lines, etc.)."""
        meta: dict = {}
        if self._supports_table_linked_selection():
            indices: list[int] = []
            for i, tr in enumerate(fig.data):
                t = getattr(tr, "type", None)
                mode = str(getattr(tr, "mode", "") or "")
                if t in ("scatter", "scattergl") and ("markers" in mode or mode == ""):
                    indices.append(i)
                elif t == "scatter3d" and i == 0:
                    indices.append(i)
                elif t == "histogram" and i == 0:
                    indices.append(i)
            if indices:
                meta["molmanager_selection_traces"] = indices
        persist = bool(
            getattr(self, "hover_persist_cb", None) and self.hover_persist_cb.isChecked()
        )
        meta["molmanager_hover_persist"] = persist
        if meta:
            fig.update_layout(meta=meta)

    def _push_plotly_figure(self, fig: go.Figure) -> None:
        from .plotly_html import figure_payload_json

        self._apply_user_plot_labels(fig)
        self._oid_point_index = build_oid_point_index(self._plotted_oids)
        self._last_pushed_selection_key = None
        self._annotate_scatter_selection_meta(fig)
        self._pending_payload_json = figure_payload_json(fig)
        self._last_browser_opened_path = None
        if self._web_ready:
            self._apply_pending_payload()
            QTimer.singleShot(0, self.sync_from_table_selection)
            QTimer.singleShot(50, self._sync_hover_persist_visual)

    def _apply_pending_payload(self) -> None:
        if not self._web_ready or not self._pending_payload_json:
            return
        run_javascript_apply_figure(self.web.page(), self._pending_payload_json)
        self._arm_ignore_plot_clear()
        QTimer.singleShot(300, self.sync_from_table_selection)

    def sync_from_table_selection(
        self, selected_oids: set[int] | frozenset[int] | None = None
    ) -> None:
        """Highlight plot points for the current table row selection."""
        if not self._plotted_oids or self.parent_app is None:
            return
        if not self._supports_table_linked_selection():
            return
        selected = (
            {int(x) for x in selected_oids}
            if selected_oids is not None
            else selected_oids_for_plot(self.parent_app)
        )
        new_idxs = point_indices_for_oids(
            self._plotted_oids, selected, oid_index=getattr(self, "_oid_point_index", None)
        )
        if new_idxs == self._selected_point_indices and self._last_pushed_selection_key is not None:
            return
        self._selected_point_indices = new_idxs
        self._arm_ignore_plot_clear()
        self._sync_plot_selection_visual()

    def _sync_plot_selection_visual(self) -> None:
        if not self._web_ready:
            self._pending_table_selection_sync = True
            return
        self._pending_table_selection_sync = False
        key = selection_visual_push_key(self._selected_point_indices)
        if key == getattr(self, "_last_pushed_selection_key", None):
            return
        self._last_pushed_selection_key = key
        run_javascript_set_selection(self.web.page(), self._selected_point_indices)
        QTimer.singleShot(0, self._sync_hover_persist_visual)

    def _clear_plot_table_selection(self, *, update_plot: bool = True) -> None:
        self._selected_point_indices = set()
        self._ignore_plot_clear_until = 0.0
        clear_table_selection_from_plot(self.parent_app)
        if update_plot:
            self._sync_plot_selection_visual()
        else:
            self._last_pushed_selection_key = None
            self._sync_hover_persist_visual()

    def _arm_ignore_plot_clear(self, ms: int = 500) -> None:
        self._ignore_plot_clear_until = time.monotonic() + (ms / 1000.0)

    def _render_empty_plot(self, title: str) -> None:
        self._stats_panel.set_lines(["No statistics for the current plot."])
        fig = go.Figure()
        fig.update_layout(
            title=title,
            xaxis={"visible": False},
            yaxis={"visible": False},
            annotations=[
                {
                    "text": title,
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                }
            ],
            margin={"l": 20, "r": 20, "t": 50, "b": 20},
        )
        self._push_plotly_figure(fig)

    def _on_web_load_finished(self, ok: bool) -> None:
        if not ok:
            self._fallback_open_in_browser("Plot view failed to load in embedded renderer.")
            return

        def _after_probe(result) -> None:
            if not bool(result):
                self._fallback_open_in_browser(
                    "Embedded Plotly renderer is not supported on this system."
                )
                return
            self._web_ready = True
            self._apply_pending_payload()
            QTimer.singleShot(0, self.sync_from_table_selection)
            if self._pending_table_selection_sync:
                QTimer.singleShot(0, self.sync_from_table_selection)

        QTimer.singleShot(
            0,
            lambda: self.web.page().runJavaScript(
                "typeof window.Plotly !== 'undefined' && typeof window.molmanagerApply === 'function'",
                _after_probe,
            ),
        )

    def _fallback_open_in_browser(self, reason: str) -> None:
        path = str(self._plot_shell_path)
        if self._last_browser_opened_path == path:
            return
        self._last_browser_opened_path = path
        webbrowser.open(self._plot_shell_path.as_uri())
        self.parent_app.status_label.setText(f"Plot fallback: opened in browser ({reason})")

    def _select_rows_for_oids(self, oids: list[int]) -> None:
        source_rows: list[int] = []
        for oid in oids:
            row = self.parent_app.logical_row_for_oid(int(oid))
            if row >= 0:
                source_rows.append(int(row))
        if not source_rows:
            return
        self._select_rows_for_source_rows(source_rows)

    def _select_rows_for_point_indices(self, point_indices: list[int]) -> None:
        source_rows = source_rows_for_point_indices(
            self.parent_app, self._plotted_oids, point_indices
        )
        # Do not scroll the table — keeps docked-plot clicks from flashing scrollbars.
        apply_table_selection_for_source_rows(
            self.parent_app,
            source_rows,
            scroll=False,
            debounce=len(source_rows) > 1,
        )

    def _select_rows_for_source_rows(self, source_rows: list[int]) -> None:
        apply_table_selection_for_source_rows(
            self.parent_app,
            source_rows,
            scroll=False,
            debounce=len(source_rows) > 1,
        )

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        if point_index < 0:
            return
        idx = int(point_index)
        if additive:
            self._selected_point_indices.add(idx)
        else:
            self._selected_point_indices = {idx}
        self._arm_ignore_plot_clear()
        self._select_rows_for_point_indices(sorted(self._selected_point_indices))
        self._sync_plot_selection_visual()
        n = len(self._selected_point_indices)
        if n > 1:
            self.parent_app.status_label.setText(f"Plot: selected {n:,} point(s).")
        elif 0 <= idx < len(self._plotted_oids):
            oid = int(self._plotted_oids[idx])
            row = self.parent_app.logical_row_for_oid(oid)
            if row >= 0:
                self.parent_app.status_label.setText(f"Plot: selected row {row + 1:,} (OID {oid}).")

    def _on_plot_points_selected(self, points_json: str, *, additive: bool = False) -> None:
        try:
            raw = json.loads(points_json or "[]")
            idxs = [int(x) for x in raw if isinstance(x, (int, float))]
        except Exception:
            idxs = []
        if not idxs:
            if additive:
                return
            if time.monotonic() < self._ignore_plot_clear_until:
                return
            self._clear_plot_table_selection()
            self.parent_app.status_label.setText("Plot: selection cleared.")
            return
        new_idxs = {i for i in idxs if 0 <= i < len(self._plotted_oids)}
        if not new_idxs:
            return
        if additive:
            self._selected_point_indices |= new_idxs
        else:
            self._selected_point_indices = new_idxs
        self._arm_ignore_plot_clear()
        sel_sorted = sorted(self._selected_point_indices)
        self._select_rows_for_point_indices(sel_sorted)
        self.parent_app.status_label.setText(f"Plot: selected {len(sel_sorted):,} point(s).")
        self._sync_plot_selection_visual()
