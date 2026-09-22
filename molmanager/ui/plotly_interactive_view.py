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

"""Embedded Plotly view with table-linked point selection (shared by Plotter and PCA/t-SNE)."""

from __future__ import annotations

import json
import tempfile
import time
import webbrowser
from pathlib import Path
from typing import TYPE_CHECKING

from PyQt5.QtCore import QObject, QTimer, QUrl, pyqtSlot
from PyQt5.QtWebChannel import QWebChannel
from PyQt5.QtWidgets import QVBoxLayout, QWidget
from plotly import graph_objects as go

from .plot_hover import hover_cards_payload, resolve_default_hover_columns
from .plot_table_sync import (
    apply_table_selection_for_source_rows,
    build_oid_point_index,
    clear_table_selection_from_plot,
    point_indices_for_oids as _point_indices_for_oids,
    run_javascript_apply_figure,
    run_javascript_set_selection,
    selected_oids_for_plot,
    selection_visual_push_key,
    source_rows_for_point_indices,
)
from .plot_web_surface import build_plot_web_view, no_web_surface
from .plotly_html import figure_payload_json

if TYPE_CHECKING:
    from .main_window import ChemistryWorkspaceWindow


class _PlotBridge(QObject):
    def __init__(self, view: "PlotlyInteractiveView") -> None:
        super().__init__(view)
        self._view = view

    @pyqtSlot(int, bool)
    def pointClicked(self, point_index: int, additive: bool = False) -> None:  # noqa: N802
        self._view._on_plot_point_clicked(int(point_index), additive=bool(additive))

    @pyqtSlot(str, bool)
    def pointsSelected(self, points_json: str, additive: bool = False) -> None:  # noqa: N802
        self._view._on_plot_points_selected(points_json, additive=bool(additive))

    @pyqtSlot(int)
    def radarTraceClicked(self, trace_index: int) -> None:  # noqa: N802
        handler = getattr(self._view, "_on_radar_trace_clicked", None)
        if callable(handler):
            handler(int(trace_index))

    @pyqtSlot(int, result=str)
    def hoverCardJson(self, point_index: int) -> str:  # noqa: N802
        return self._view._hover_card_json_for_point(int(point_index))

    @pyqtSlot(str, result=str)
    def hoverCardsJson(self, indices_json: str) -> str:  # noqa: N802
        return self._view._hover_card_json_for_points(indices_json)


class PlotlyInteractiveView(QWidget):
    """Plotly scatter with lasso/click selection synced to the compound table."""

    def __init__(
        self, parent_app: ChemistryWorkspaceWindow | None = None, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.parent_app = parent_app
        self._plot_shell_path = (
            Path(tempfile.gettempdir()) / f"MOLMANAGER_plot_shell_{id(self)}.html"
        )
        self._last_browser_opened_path: str | None = None
        self.plotted_oids: list[int] = []
        self._partner_oids: list[int] | None = None
        self._oid_point_index: dict[int, list[int]] = {}
        self._selected_point_indices: set[int] = set()
        self._last_pushed_selection_key: tuple[int, int] | None = None
        self._web_ready = False
        self._pending_table_selection_sync = False
        self._pending_payload_json: str | None = None
        self._ignore_plot_clear_until: float = 0.0
        # Match Plotter: hover cards are transient unless the user enables persist.
        self._hover_persist = False
        self._hover_show_structure = True
        self._hover_columns: list[str] | None = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.web = build_plot_web_view(self, minimum_height=220)
        layout.addWidget(self.web if self.web is not None else no_web_surface(self), 1)

        self._bridge = _PlotBridge(self)
        self._web_channel = None
        if self.web is None:
            return
        self._web_channel = QWebChannel(self.web.page())
        self._web_channel.registerObject("chemBridge", self._bridge)
        self.web.page().setWebChannel(self._web_channel)
        self.web.loadFinished.connect(self._on_web_load_finished)
        QTimer.singleShot(0, self._load_plot_shell)

    def push_figure(
        self,
        fig: go.Figure,
        oids: list[int],
        *,
        partner_oids: list[int] | None = None,
    ) -> None:
        """Display a figure and map point indices to table OIDs.

        ``partner_oids`` (same length as ``oids``) marks the second molecule in
        pair plots so table selection of either partner highlights the point.
        """
        self.plotted_oids = list(oids)
        self._partner_oids = list(partner_oids) if partner_oids is not None else None
        self._oid_point_index = build_oid_point_index(self.plotted_oids, self._partner_oids)
        self._last_pushed_selection_key = None
        self._selected_point_indices = {
            i for i in self._selected_point_indices if 0 <= i < len(self.plotted_oids)
        }
        try:
            self._prepare_figure_for_shell(fig, self.plotted_oids)
        except Exception:
            pass
        self._pending_payload_json = figure_payload_json(fig)
        self._last_browser_opened_path = None
        if self._web_ready:
            self._apply_pending_payload()
            QTimer.singleShot(0, self.sync_from_table_selection)
            QTimer.singleShot(50, self._sync_hover_persist_visual)

    def _prepare_figure_for_shell(self, fig: go.Figure, oids: list[int]) -> None:
        """Annotate selection meta, customdata, and disable native hover labels."""
        meta = dict(getattr(fig.layout, "meta", None) or {})
        if "molmanager_selection_traces" not in meta:
            indices: list[int] = []
            for i, tr in enumerate(fig.data):
                t = getattr(tr, "type", None)
                mode = str(getattr(tr, "mode", "") or "")
                if t in ("scatter", "scattergl") and ("markers" in mode or mode == ""):
                    indices.append(i)
                elif t == "scatter3d" and i == 0:
                    indices.append(i)
            if indices:
                meta["molmanager_selection_traces"] = indices
        meta["molmanager_hover_persist"] = bool(self._hover_persist)
        fig.update_layout(meta=meta, clickmode="event+select", dragmode="lasso")

        custom = [[int(oid)] for oid in oids]
        sel_traces = meta.get("molmanager_selection_traces") or [0]
        for ti in sel_traces:
            try:
                idx = int(ti)
            except Exception:
                continue
            if idx < 0 or idx >= len(fig.data):
                continue
            tr = fig.data[idx]
            t = getattr(tr, "type", None)
            if t not in ("scatter", "scattergl", "scatter3d"):
                continue
            n = 0
            try:
                n = len(tr.x) if tr.x is not None else 0
            except Exception:
                n = 0
            if n and len(custom) == n:
                fig.data[idx].customdata = custom
            fig.data[idx].hoverinfo = "none"

    def point_indices_for_oids(self, oids: set[int] | frozenset[int]) -> set[int]:
        """Map table OIDs to scatter point indices in the current figure."""
        return _point_indices_for_oids(self.plotted_oids, oids, oid_index=self._oid_point_index)

    def select_oids(self, oids: set[int] | frozenset[int] | list[int]) -> int:
        """Select table rows (and plot points) for the given OIDs. Returns rows selected."""
        oid_set = {int(o) for o in oids}
        indices = sorted(self.point_indices_for_oids(oid_set))
        if not indices or self.parent_app is None:
            return 0
        self._selected_point_indices = set(indices)
        self._arm_ignore_plot_clear()
        self._select_rows_for_point_indices(indices)
        self.sync_selection_visual()
        return len(indices)

    def sync_from_table_selection(
        self, selected_oids: set[int] | frozenset[int] | None = None
    ) -> None:
        """Highlight plot points for the current table row selection."""
        if not self.plotted_oids or self.parent_app is None:
            return
        selected = (
            {int(x) for x in selected_oids}
            if selected_oids is not None
            else selected_oids_for_plot(self.parent_app)
        )
        new_idxs = _point_indices_for_oids(
            self.plotted_oids, selected, oid_index=self._oid_point_index
        )
        if new_idxs == self._selected_point_indices:
            # Still push visual if we never painted (e.g. after replot).
            if self._last_pushed_selection_key is not None:
                return
        self._selected_point_indices = new_idxs
        self._arm_ignore_plot_clear()
        self.sync_selection_visual()

    def sync_selection_visual(self) -> None:
        if not self._web_ready:
            self._pending_table_selection_sync = True
            return
        self._pending_table_selection_sync = False
        key = selection_visual_push_key(self._selected_point_indices)
        if key == self._last_pushed_selection_key:
            return
        self._last_pushed_selection_key = key
        run_javascript_set_selection(self.web.page(), self._selected_point_indices)
        QTimer.singleShot(0, self._sync_hover_persist_visual)

    def clear_table_selection(self, *, update_plot: bool = True) -> None:
        self._selected_point_indices = set()
        self._ignore_plot_clear_until = 0.0
        if self.parent_app is not None:
            clear_table_selection_from_plot(self.parent_app)
        if update_plot:
            self.sync_selection_visual()
        else:
            self._last_pushed_selection_key = None
            self._sync_hover_persist_visual()

    def set_hover_options(
        self,
        *,
        columns: list[str] | None = None,
        show_structure: bool | None = None,
        persist: bool | None = None,
    ) -> None:
        """Configure hover-card columns / structure / persist (Plotter On Hover parity)."""
        if columns is not None:
            cleaned = [str(c).strip() for c in columns if str(c or "").strip()]
            self._hover_columns = cleaned
        if show_structure is not None:
            self._hover_show_structure = bool(show_structure)
        if persist is not None:
            self._hover_persist = bool(persist)
            self._sync_hover_persist_visual()

    def _active_hover_columns(self) -> list[str]:
        if self._hover_columns is not None:
            return list(self._hover_columns)
        return self._default_hover_columns()

    def _default_hover_columns(self) -> list[str]:
        headers = list(getattr(self.parent_app, "headers", []) or []) if self.parent_app else []
        return resolve_default_hover_columns(headers)

    def _hover_card_json_for_point(self, point_index: int) -> str:
        if point_index < 0 or point_index >= len(self.plotted_oids):
            return ""
        oid = int(self.plotted_oids[point_index])
        payload = hover_cards_payload(
            self.parent_app,
            [oid],
            self._active_hover_columns(),
            show_structure=bool(self._hover_show_structure),
        )
        return json.dumps(payload, separators=(",", ":"))

    def _hover_card_json_for_points(self, indices_json: str) -> str:
        try:
            raw = json.loads(indices_json or "[]")
            idxs = [int(x) for x in raw if isinstance(x, (int, float))]
        except Exception:
            idxs = []
        oids: list[int] = []
        n = len(self.plotted_oids)
        for i in idxs:
            if 0 <= i < n:
                oids.append(int(self.plotted_oids[i]))
        if not oids:
            return ""
        payload = hover_cards_payload(
            self.parent_app,
            oids,
            self._active_hover_columns(),
            show_structure=bool(self._hover_show_structure),
        )
        return json.dumps(payload, separators=(",", ":"))

    def _sync_hover_persist_visual(self) -> None:
        if not self._web_ready:
            return
        persist = bool(self._hover_persist)
        self.web.page().runJavaScript(
            f"window.molmanagerSetHoverPersist && molmanagerSetHoverPersist({json.dumps(persist)});"
        )
        if not persist:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        from .plot_hover import HOVER_MULTI_MAX_ITEMS

        n_sel = len(self._selected_point_indices)
        if n_sel == 0 or n_sel > HOVER_MULTI_MAX_ITEMS:
            self.web.page().runJavaScript(
                "window.molmanagerClearHoverPin && molmanagerClearHoverPin();"
            )
            return
        idxs = sorted(self._selected_point_indices)
        js_idxs = json.dumps(idxs)
        self.web.page().runJavaScript(
            f"window.molmanagerPinHoverPoints && molmanagerPinHoverPoints({json.dumps(js_idxs)});"
        )

    def _load_plot_shell(self) -> None:
        if self.web is None:
            return
        from .plotly_shell import ensure_interactive_plot_shell

        try:
            self._plot_shell_path = ensure_interactive_plot_shell()
            self.web.load(QUrl.fromLocalFile(str(self._plot_shell_path)))
        except RuntimeError:
            return

    def _apply_pending_payload(self) -> None:
        if not self._web_ready or not self._pending_payload_json:
            return
        run_javascript_apply_figure(self.web.page(), self._pending_payload_json)
        self._arm_ignore_plot_clear()
        QTimer.singleShot(300, self.sync_from_table_selection)

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
        if self.parent_app is None:
            return
        path = str(self._plot_shell_path)
        if self._last_browser_opened_path == path:
            return
        self._last_browser_opened_path = path
        webbrowser.open(self._plot_shell_path.as_uri())
        self.parent_app.status_label.setText(f"Plot fallback: opened in browser ({reason})")

    def _arm_ignore_plot_clear(self, ms: int = 500) -> None:
        self._ignore_plot_clear_until = time.monotonic() + (ms / 1000.0)

    def _select_rows_for_point_indices(self, point_indices: list[int]) -> None:
        if self.parent_app is None:
            return
        source_rows = source_rows_for_point_indices(
            self.parent_app,
            self.plotted_oids,
            point_indices,
            partner_oids=self._partner_oids,
        )
        # Avoid focus-stealing into the main table (breaks Shift+select in floating plots).
        apply_table_selection_for_source_rows(
            self.parent_app,
            source_rows,
            scroll=False,
            debounce=len(source_rows) > 1,
        )

    def _on_plot_point_clicked(self, point_index: int, *, additive: bool = False) -> None:
        if point_index < 0 or self.parent_app is None:
            return
        idx = int(point_index)
        if additive:
            self._selected_point_indices.add(idx)
        else:
            self._selected_point_indices = {idx}
        self._arm_ignore_plot_clear()
        self._select_rows_for_point_indices(sorted(self._selected_point_indices))
        self.sync_selection_visual()
        n = len(self._selected_point_indices)
        if n > 1:
            self.parent_app.status_label.setText(f"Plot: selected {n:,} point(s).")
        elif 0 <= idx < len(self.plotted_oids):
            oid = int(self.plotted_oids[idx])
            row = self.parent_app.logical_row_for_oid(oid)
            if row >= 0:
                self.parent_app.status_label.setText(f"Plot: selected row {row + 1:,} (OID {oid}).")

    def _on_plot_points_selected(self, points_json: str, *, additive: bool = False) -> None:
        if self.parent_app is None:
            return
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
            self.clear_table_selection()
            self.parent_app.status_label.setText("Plot: selection cleared.")
            return
        new_idxs = {i for i in idxs if 0 <= i < len(self.plotted_oids)}
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
        self.sync_selection_visual()
