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

"""Multi-pane workspace layouts: fixed-left table + configurable plot panes."""

from __future__ import annotations

from contextlib import suppress
from typing import Callable

from PyQt5.QtCore import QCoreApplication, QEvent, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (
    QSizePolicy,
    QSplitter,
    QSplitterHandle,
    QVBoxLayout,
    QWidget,
)

from ..dockable_plot import PLOT_PANEL_DEFAULT_WIDTH, suspend_parent_change_chrome
from .plot_pane import PlotPane

LAYOUT_TABLE_ONLY = "table_only"
LAYOUT_TABLE_SINGLE = "table_single"
LAYOUT_TABLE_STACK = "table_stack"
LAYOUT_TABLE_SIDE = "table_side"
LAYOUT_QUADRANTS = "quadrants"
LAYOUT_TABLE_GRID = "table_grid"
DEFAULT_LAYOUT_ID = LAYOUT_TABLE_ONLY

LAYOUT_PRESETS: tuple[tuple[str, str], ...] = (
    (LAYOUT_TABLE_ONLY, "Table Only"),
    (LAYOUT_TABLE_SINGLE, "Table | 1 plot"),
    (LAYOUT_TABLE_STACK, "Table | 2 stacked plots"),
    (LAYOUT_TABLE_SIDE, "Table | 2 side-by-side plots"),
    (LAYOUT_QUADRANTS, "Quadrants (table upper-left)"),
    (LAYOUT_TABLE_GRID, "Grid 2×3 (table upper-left)"),
)

_LAYOUT_PANE_COUNTS: dict[str, int] = {
    LAYOUT_TABLE_ONLY: 0,
    LAYOUT_TABLE_SINGLE: 1,
    LAYOUT_TABLE_STACK: 2,
    LAYOUT_TABLE_SIDE: 2,
    LAYOUT_QUADRANTS: 3,
    LAYOUT_TABLE_GRID: 5,
}


def _reparent_hidden(widget: QWidget, host: QWidget | None) -> None:
    """Move ``widget`` under ``host`` (or unparent) without flashing a window."""
    try:
        widget.hide()
        widget.setParent(host)
        widget.hide()
    except RuntimeError:
        return


def _hide_discarded_chrome(widget: QWidget) -> None:
    """Hide splitter handles and plot-pane chrome before the old tree is dropped."""
    with suppress(RuntimeError):
        widget.hide()
    try:
        handles = widget.findChildren(QSplitterHandle)
        panes = widget.findChildren(PlotPane)
    except RuntimeError:
        return
    for child in (*handles, *panes):
        with suppress(RuntimeError):
            child.hide()
        header = getattr(child, "_header", None)
        if header is not None:
            with suppress(RuntimeError):
                header.hide()


def _flush_deferred_deletes() -> None:
    with suppress(RuntimeError):
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)


def _equalize_splitter(splitter: QSplitter) -> None:
    """Give each splitter child the same share of the current span."""
    try:
        n = int(splitter.count())
    except RuntimeError:
        return
    if n <= 1:
        return
    try:
        orient = splitter.orientation()
        span = int(splitter.width() if orient == Qt.Horizontal else splitter.height())
        handle = int(splitter.handleWidth()) * max(0, n - 1)
    except RuntimeError:
        return
    inner = span - handle if span > handle else 0
    if inner <= 0:
        splitter.setSizes([1] * n)
        return
    base, rem = divmod(inner, n)
    splitter.setSizes([base + (1 if i < rem else 0) for i in range(n)])


class WorkspaceLayoutManager(QWidget):
    """Owns the content splitter tree: table region + plot panes."""

    layout_changed = pyqtSignal(str)
    pane_close_requested = pyqtSignal(object)  # PlotPane

    def __init__(self, table_area: QWidget, parent: QWidget | None = None):
        super().__init__(parent)
        self._table_area = table_area
        self._layout_id = DEFAULT_LAYOUT_ID
        self._panes: list[PlotPane] = []
        self._preferred_pane_id: str | None = None
        self._splitters: list[QSplitter] = []
        self._equalize_token = 0
        self._layout_freeze_depth = 0
        self._root_ly = QVBoxLayout(self)
        self._root_ly.setContentsMargins(0, 0, 0, 0)
        self._root_ly.setSpacing(0)
        self._workspace_root: QWidget | None = None
        self.setAutoFillBackground(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # Park reused widgets here so setParent(None) never promotes them to top-level.
        self._graveyard = QWidget(self)
        self._graveyard.hide()
        self._graveyard.setAttribute(Qt.WA_DontShowOnScreen, True)
        self._graveyard.resize(0, 0)
        self.apply_layout(DEFAULT_LAYOUT_ID, preserve_plots=False)

    @property
    def layout_id(self) -> str:
        return self._layout_id

    def session_layout_id(self) -> str:
        """Layout id to persist. A leftover 1-pane stack/side is saved as split view."""
        n = len(self._panes)
        if n <= 0:
            return LAYOUT_TABLE_ONLY
        if n == 1:
            return LAYOUT_TABLE_SINGLE
        return self._layout_id

    def plot_panes(self) -> list[PlotPane]:
        return list(self._panes)

    def preferred_pane(self) -> PlotPane | None:
        if not self._panes:
            return None
        if self._preferred_pane_id:
            for p in self._panes:
                if p.pane_id == self._preferred_pane_id:
                    return p
        for p in self._panes:
            if p.is_empty():
                return p
        return self._panes[0]

    def set_preferred_pane(self, pane: PlotPane | None) -> None:
        self._preferred_pane_id = pane.pane_id if pane is not None else None
        for p in self._panes:
            p.set_active(p is pane)

    def refresh_theme(self) -> None:
        """Refresh plot pane selection outlines and pager fonts for the current GUI theme."""
        pref = self.preferred_pane()
        for pane in self._panes:
            pane.refresh_theme()
            pane.set_active(pane is pref)

    def pane_for_widget(self, widget: QWidget | None) -> PlotPane | None:
        if widget is None:
            return None
        for p in self._panes:
            if widget in p.plot_widgets():
                return p
        return None

    def iter_docked_widgets(self):
        for p in self._panes:
            yield from p.plot_widgets()

    def find_pane(self, pane_id: str) -> PlotPane | None:
        for p in self._panes:
            if p.pane_id == pane_id:
                return p
        return None

    def dock_into_pane(self, pane: PlotPane, widget: QWidget) -> QWidget | None:
        """Dock ``widget`` into ``pane`` (appends; does not replace other plots)."""
        snapshot = self.collect_splitter_sizes()
        previous = pane.plot_widget()
        other = self.pane_for_widget(widget)
        # One chrome pass after reparent; skip ParentChange footer work mid-move.
        with suspend_parent_change_chrome():
            if other is not None and other is not pane:
                other.remove_plot_widget(widget)
            pane.add_plot_widget(widget)
        self.restore_splitter_sizes(snapshot)
        self.set_preferred_pane(pane)
        return previous if previous is not widget else None

    def release_widget(self, widget: QWidget, *, discard: bool = False) -> bool:
        pane = self.pane_for_widget(widget)
        if pane is None:
            return False
        with suspend_parent_change_chrome():
            return pane.remove_plot_widget(widget, discard=discard)

    def ensure_single_plot_pane(self) -> PlotPane | None:
        """Return a plot pane, expanding Table Only to table|1 plot without a full rebuild."""
        if self._panes:
            return self.preferred_pane()

        old_root = self._workspace_root
        if old_root is not None:
            _hide_discarded_chrome(old_root)
        self._stash(self._table_area)
        if old_root is not None and old_root is not self._table_area:
            self._discard_workspace_root(old_root)
        elif old_root is self._table_area:
            with suppress(RuntimeError):
                self._root_ly.removeWidget(old_root)
        self._workspace_root = None
        self._splitters.clear()
        self._panes.clear()
        self._preferred_pane_id = None

        self._begin_layout_freeze()
        try:
            self._layout_id = LAYOUT_TABLE_SINGLE
            root = self._build_table_with_plot_area(None, 1)
            self._workspace_root = root
            self._root_ly.addWidget(root, 1)
            with suppress(RuntimeError):
                self._table_area.show()
            pref = self.preferred_pane()
            self.set_preferred_pane(pref)
            self.layout_changed.emit(self._layout_id)
            return pref
        finally:
            self._end_layout_freeze()

    def collect_splitter_sizes(self) -> dict:
        """Serializable nested splitter sizes for the current layout."""
        sizes: dict[str, list[int]] = {}
        ratios: dict[str, list[float]] = {}
        orientations: dict[str, str] = {}
        for i, sp in enumerate(self._splitters):
            try:
                vals = [int(s) for s in sp.sizes()]
            except RuntimeError:
                continue
            key = f"splitter_{i}"
            sizes[key] = vals
            total = float(sum(vals)) or 1.0
            ratios[key] = [float(v) / total for v in vals]
            with suppress(RuntimeError):
                orientations[key] = (
                    "horizontal" if sp.orientation() == Qt.Horizontal else "vertical"
                )
        return {
            "layout_id": self.session_layout_id(),
            "sizes": sizes,
            "ratios": ratios,
            "preferred_pane_id": self._preferred_pane_id,
            "orientations": orientations,
        }

    def restore_splitter_sizes(self, payload: dict | None) -> None:
        if not isinstance(payload, dict):
            return
        lid = payload.get("layout_id")
        # Sizes are layout-shaped; never apply a side-by-side snapshot onto stacked panes.
        if isinstance(lid, str) and lid and lid != self._layout_id:
            return
        sizes_map = payload.get("sizes")
        ratios_map = payload.get("ratios")
        if not isinstance(sizes_map, dict):
            sizes_map = {}
        if not isinstance(ratios_map, dict):
            ratios_map = {}
        for i, sp in enumerate(self._splitters):
            key = f"splitter_{i}"
            try:
                count = int(sp.count())
            except RuntimeError:
                continue
            applied = False
            ratios = ratios_map.get(key)
            if isinstance(ratios, list) and len(ratios) == count and count > 0:
                try:
                    orient = sp.orientation()
                    span = int(sp.width() if orient == Qt.Horizontal else sp.height())
                    if span <= 0:
                        span = int(sum(int(s) for s in sp.sizes()))
                    if span > 0:
                        floats = [max(0.0, float(r)) for r in ratios]
                        rsum = sum(floats) or 1.0
                        floats = [r / rsum for r in floats]
                        ints = [max(0, int(round(r * span))) for r in floats]
                        drift = span - sum(ints)
                        if ints:
                            ints[-1] = max(0, ints[-1] + drift)
                        sp.setSizes(ints)
                        applied = True
                except (RuntimeError, TypeError, ValueError):
                    applied = False
            if applied:
                continue
            vals = sizes_map.get(key)
            if isinstance(vals, list) and len(vals) == count:
                with suppress(RuntimeError, TypeError, ValueError):
                    sp.setSizes([max(0, int(v)) for v in vals])
        if sizes_map or ratios_map:
            # Saved sizes win over the deferred equal-quadrant pass from apply_layout.
            self._cancel_pending_equalize()
        pref_id = payload.get("preferred_pane_id")
        if isinstance(pref_id, str) and pref_id:
            pane = self.find_pane(pref_id)
            if pane is not None:
                self.set_preferred_pane(pane)

    def _layout_tree_matches(self, layout_id: str) -> bool:
        """True when the live widget tree already matches ``layout_id``."""
        if self._workspace_root is None or self._workspace_root is self._table_area:
            return False
        if len(self._panes) != _LAYOUT_PANE_COUNTS.get(layout_id, 0):
            return False
        if layout_id == LAYOUT_TABLE_ONLY:
            # Table-only must not keep a splitter (stale handles look like plot space).
            return not self._splitters and not isinstance(self._workspace_root, QSplitter)
        return isinstance(self._workspace_root, QSplitter) and bool(self._splitters)

    def apply_layout(
        self,
        layout_id: str,
        *,
        preserve_plots: bool = True,
        on_extra_plot: Callable[[QWidget], None] | None = None,
    ) -> list[QWidget]:
        """
        Rebuild the workspace for ``layout_id``.

        Returns plot widgets that no longer fit (caller should undock them).
        """
        if layout_id not in {p[0] for p in LAYOUT_PRESETS}:
            layout_id = DEFAULT_LAYOUT_ID
        if layout_id == self._layout_id and self._layout_tree_matches(layout_id):
            return []

        # Hide/park the old tree with painting enabled. Freezing the backing store
        # during hide leaves splitter handles and pane chrome painted on screen.
        kept_stacks = self._release_current_workspace(preserve_plots=preserve_plots)
        self._begin_layout_freeze()
        try:
            return self._build_layout_now(
                layout_id,
                kept_stacks=kept_stacks,
                on_extra_plot=on_extra_plot,
            )
        finally:
            self._end_layout_freeze()

    def _stash(self, widget: QWidget) -> None:
        """Park a reused widget in the hidden graveyard (never a top-level window)."""
        _reparent_hidden(widget, self._graveyard)

    def _discard_workspace_root(self, old_root: QWidget) -> None:
        _hide_discarded_chrome(old_root)
        with suppress(RuntimeError):
            self._root_ly.removeWidget(old_root)
        _reparent_hidden(old_root, self._graveyard)
        with suppress(RuntimeError):
            old_root.deleteLater()

    def _release_current_workspace(
        self, *, preserve_plots: bool
    ) -> list[tuple[list[QWidget], int]]:
        """Hide and park the current tree so leftover handles/headers cannot linger."""
        kept_stacks: list[tuple[list[QWidget], int]] = []
        if preserve_plots:
            for pane in list(self._panes):
                widgets = pane.plot_widgets()
                if not widgets:
                    pane.take_plot_widgets()
                    continue
                idx = pane.page_index()
                taken = pane.take_plot_widgets()
                kept_stacks.append((taken, idx))
                for widget in taken:
                    self._stash(widget)
        else:
            for pane in list(self._panes):
                for widget in pane.take_plot_widgets():
                    self._stash(widget)

        old_root = self._workspace_root
        if old_root is not None:
            _hide_discarded_chrome(old_root)

        self._stash(self._table_area)

        if old_root is not None and old_root is not self._table_area:
            self._discard_workspace_root(old_root)
        elif old_root is self._table_area:
            with suppress(RuntimeError):
                self._root_ly.removeWidget(old_root)
        self._workspace_root = None

        self._splitters.clear()
        self._panes.clear()
        return kept_stacks

    def _build_layout_now(
        self,
        layout_id: str,
        *,
        kept_stacks: list[tuple[list[QWidget], int]],
        on_extra_plot: Callable[[QWidget], None] | None,
    ) -> list[QWidget]:
        extras: list[QWidget] = []
        with suspend_parent_change_chrome():
            self._layout_id = layout_id

            if layout_id == LAYOUT_TABLE_ONLY:
                root = self._build_table_only()
            elif layout_id == LAYOUT_QUADRANTS:
                root = self._build_quadrants()
            elif layout_id == LAYOUT_TABLE_GRID:
                root = self._build_table_grid()
            elif layout_id == LAYOUT_TABLE_SIDE:
                root = self._build_table_with_plot_area(Qt.Horizontal, 2)
            elif layout_id == LAYOUT_TABLE_SINGLE:
                root = self._build_table_with_plot_area(None, 1)
            elif layout_id == LAYOUT_TABLE_STACK:
                root = self._build_table_with_plot_area(Qt.Vertical, 2)
            else:
                self._layout_id = DEFAULT_LAYOUT_ID
                root = self._build_table_only()

            self._workspace_root = root
            self._root_ly.addWidget(root, 1)
            with suppress(RuntimeError):
                self._table_area.show()
            if self._layout_id == LAYOUT_QUADRANTS:
                self.equalize_quadrant_splitters()
                self._schedule_equal_quadrants()

            for i, (widgets, idx) in enumerate(kept_stacks):
                if i < len(self._panes):
                    self._panes[i].set_plot_widgets(widgets, current=idx)
                    for widget in widgets:
                        with suppress(RuntimeError):
                            widget.show()
                else:
                    extras.extend(widgets)
                    if on_extra_plot is not None:
                        for widget in widgets:
                            on_extra_plot(widget)

            pref = self.preferred_pane()
            self.set_preferred_pane(pref)
            for p in self._panes:
                self._wire_pane(p)
        self.layout_changed.emit(self._layout_id)
        return extras

    def _begin_layout_freeze(self) -> None:
        """Suppress paints of this widget while the new splitter tree is inserted."""
        depth = int(getattr(self, "_layout_freeze_depth", 0))
        if depth == 0:
            self.setUpdatesEnabled(False)
        self._layout_freeze_depth = depth + 1

    def _end_layout_freeze(self) -> None:
        depth = max(0, int(getattr(self, "_layout_freeze_depth", 0)) - 1)
        self._layout_freeze_depth = depth
        if depth:
            return
        with suppress(RuntimeError):
            self.setUpdatesEnabled(True)
        _flush_deferred_deletes()
        self._repaint_workspace()
        QTimer.singleShot(0, self._repaint_workspace)

    def _repaint_workspace(self) -> None:
        """Erase stale backing-store pixels after a splitter tree swap."""
        with suppress(RuntimeError):
            self.update()
        parent = self.parentWidget()
        if parent is not None:
            with suppress(RuntimeError):
                parent.update()
        win = self.window()
        if win is not None and win is not self:
            with suppress(RuntimeError):
                win.update()

    def _splitter_containing(self, widget: QWidget) -> QSplitter | None:
        for splitter in self._splitters:
            for i in range(splitter.count()):
                if splitter.widget(i) is widget:
                    return splitter
        return None

    def remove_pane(self, pane: PlotPane) -> bool:
        """Remove a plot pane from the splitter tree (plots must already be detached)."""
        if pane not in self._panes:
            return False
        is_last = len(self._panes) <= 1
        splitter = self._splitter_containing(pane)
        if splitter is None and not is_last:
            return False

        index = -1
        removed_size = 0
        if splitter is not None:
            for i in range(splitter.count()):
                if splitter.widget(i) is pane:
                    index = i
                    break
            if index < 0 and not is_last:
                return False
            if index >= 0:
                old_sizes = [int(s) for s in splitter.sizes()]
                removed_size = old_sizes[index] if index < len(old_sizes) else 0

        if self._preferred_pane_id == pane.pane_id:
            self._preferred_pane_id = None

        pane.set_plot_widgets([])
        self._panes.remove(pane)
        _hide_discarded_chrome(pane)
        _reparent_hidden(pane, self._graveyard)
        with suppress(RuntimeError):
            pane.deleteLater()

        if splitter is not None and index >= 0:
            remaining = splitter.count()
            if remaining > 0 and removed_size > 0:
                new_sizes = [int(s) for s in splitter.sizes()]
                target = min(index, remaining - 1)
                new_sizes[target] = max(0, new_sizes[target] + removed_size)
                splitter.setSizes(new_sizes)

        if not self._panes:
            self._collapse_to_table_only()
            self.layout_changed.emit(self._layout_id)
            return True

        self._flatten_redundant_splitters()
        pref = self.preferred_pane()
        self.set_preferred_pane(pref)
        # Closing one of two stacked/side panes looks like split view; persist it that way.
        if len(self._panes) == 1 and self._layout_id != LAYOUT_TABLE_SINGLE:
            self._layout_id = LAYOUT_TABLE_SINGLE
            self.layout_changed.emit(self._layout_id)
        return True

    def _drop_splitter(self, splitter: QSplitter) -> None:
        if splitter in self._splitters:
            self._splitters.remove(splitter)
        _hide_discarded_chrome(splitter)
        _reparent_hidden(splitter, self._graveyard)
        with suppress(RuntimeError):
            splitter.deleteLater()

    def _discard_splitter_branch(self, widget: QWidget) -> None:
        """Hide and delete a splitter subtree that is not the compound table."""
        if widget is self._table_area:
            return
        if isinstance(widget, PlotPane):
            if widget in self._panes:
                self._panes.remove(widget)
            _hide_discarded_chrome(widget)
            _reparent_hidden(widget, self._graveyard)
            with suppress(RuntimeError):
                widget.deleteLater()
            return
        if isinstance(widget, QSplitter):
            for i in range(widget.count() - 1, -1, -1):
                child = widget.widget(i)
                if child is not None:
                    self._discard_splitter_branch(child)
            self._drop_splitter(widget)
            return
        _reparent_hidden(widget, self._graveyard)
        with suppress(RuntimeError):
            widget.deleteLater()

    def _flatten_redundant_splitters(self) -> None:
        """Unwrap 1-child splitters so a leftover pane sits beside the table."""
        changed = True
        while changed:
            changed = False
            for splitter in list(self._splitters):
                try:
                    if splitter.count() != 1:
                        continue
                    child = splitter.widget(0)
                except RuntimeError:
                    continue
                parent = splitter.parentWidget()
                if isinstance(parent, QSplitter):
                    idx = next(
                        (i for i in range(parent.count()) if parent.widget(i) is splitter),
                        -1,
                    )
                    if idx < 0:
                        continue
                    sizes = [int(s) for s in parent.sizes()]
                    child.setParent(None)
                    parent.insertWidget(idx, child)
                    self._drop_splitter(splitter)
                    if len(sizes) == parent.count():
                        parent.setSizes(sizes)
                    changed = True
                    break
                if splitter is self._workspace_root:
                    # Never promote the table to workspace root (breaks later apply_layout).
                    if child is self._table_area:
                        continue
                    self._root_ly.removeWidget(splitter)
                    child.setParent(None)
                    self._workspace_root = child
                    self._root_ly.addWidget(child, 1)
                    self._drop_splitter(splitter)
                    changed = True
                    break

    def _collapse_to_table_only(self) -> None:
        """Rebuild the table-only host so the table is never the workspace root."""
        self.apply_layout(LAYOUT_TABLE_ONLY, preserve_plots=False)

    def _on_pane_activated(self, pane: PlotPane) -> None:
        self.set_preferred_pane(pane)

    def _on_pane_close_requested(self, pane: PlotPane) -> None:
        self.pane_close_requested.emit(pane)

    def _wire_pane(self, pane: PlotPane) -> None:
        with suppress(TypeError):
            pane.activated.disconnect(self._on_pane_activated)
        with suppress(TypeError):
            pane.close_requested.disconnect(self._on_pane_close_requested)
        pane.activated.connect(self._on_pane_activated)
        pane.close_requested.connect(self._on_pane_close_requested)

    def _new_pane(self, index: int) -> PlotPane:
        pane = PlotPane(f"pane_{index}", self)
        self._panes.append(pane)
        self._wire_pane(pane)
        return pane

    def _track_splitter(self, splitter: QSplitter) -> QSplitter:
        self._splitters.append(splitter)
        return splitter

    def _cancel_pending_equalize(self) -> None:
        self._equalize_token += 1

    def _schedule_equal_quadrants(self) -> None:
        """Re-equalize after Qt assigns real geometry to the new splitter tree."""
        self._equalize_token += 1
        token = self._equalize_token
        QTimer.singleShot(0, lambda t=token: self._apply_equal_quadrants(t))

    def _apply_equal_quadrants(self, token: int) -> None:
        if token != self._equalize_token or self._layout_id != LAYOUT_QUADRANTS:
            return
        self.equalize_quadrant_splitters()

    def equalize_quadrant_splitters(self) -> None:
        """Make the 2×2 quadrant splitters 50/50 (table UL, plots UR/LL/LR)."""
        if self._layout_id != LAYOUT_QUADRANTS:
            return
        for splitter in self._splitters:
            _equalize_splitter(splitter)

    def _build_table_only(self) -> QWidget:
        """Full-width table with no plot panes."""
        host = QWidget()
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        host.setAutoFillBackground(True)
        ly = QVBoxLayout(host)
        ly.setContentsMargins(0, 0, 0, 0)
        ly.setSpacing(0)
        ly.addWidget(self._table_area, 1)
        return host

    def _build_table_with_plot_area(
        self, plot_orientation: Qt.Orientation | None, n_panes: int
    ) -> QWidget:
        outer = self._track_splitter(QSplitter(Qt.Horizontal))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)
        outer.addWidget(self._table_area)
        if n_panes <= 1 or plot_orientation is None:
            pane = self._new_pane(0)
            outer.addWidget(pane)
            outer.setStretchFactor(0, 1)
            outer.setStretchFactor(1, 1)
            outer.setSizes([700, PLOT_PANEL_DEFAULT_WIDTH])
            return outer

        plot_split = self._track_splitter(QSplitter(plot_orientation))
        plot_split.setHandleWidth(6)
        plot_split.setChildrenCollapsible(False)
        for i in range(n_panes):
            plot_split.addWidget(self._new_pane(i))
            plot_split.setStretchFactor(i, 1)
        if plot_orientation == Qt.Vertical:
            plot_split.setSizes([400, 400])
        else:
            plot_split.setSizes([420, 420])
        outer.addWidget(plot_split)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        outer.setSizes([700, PLOT_PANEL_DEFAULT_WIDTH])
        return outer

    def _build_quadrants(self) -> QWidget:
        """Four equal cells: table upper-left; plot panes UR, LL, LR."""
        outer = self._track_splitter(QSplitter(Qt.Vertical))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)

        top = self._track_splitter(QSplitter(Qt.Horizontal))
        top.setHandleWidth(6)
        top.setChildrenCollapsible(False)
        top.addWidget(self._table_area)
        top.addWidget(self._new_pane(0))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)

        bottom = self._track_splitter(QSplitter(Qt.Horizontal))
        bottom.setHandleWidth(6)
        bottom.setChildrenCollapsible(False)
        bottom.addWidget(self._new_pane(1))
        bottom.addWidget(self._new_pane(2))
        bottom.setStretchFactor(0, 1)
        bottom.setStretchFactor(1, 1)

        outer.addWidget(top)
        outer.addWidget(bottom)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        _equalize_splitter(top)
        _equalize_splitter(bottom)
        _equalize_splitter(outer)
        return outer

    def _build_table_grid(self) -> QWidget:
        """Table upper-left; five plot panes in the other cells of a 2×3 grid."""
        outer = self._track_splitter(QSplitter(Qt.Vertical))
        outer.setHandleWidth(6)
        outer.setChildrenCollapsible(False)

        top = self._track_splitter(QSplitter(Qt.Horizontal))
        top.setHandleWidth(6)
        top.setChildrenCollapsible(False)
        top.addWidget(self._table_area)
        top.addWidget(self._new_pane(0))
        top.addWidget(self._new_pane(1))
        top.setStretchFactor(0, 1)
        top.setStretchFactor(1, 1)
        top.setStretchFactor(2, 1)
        top.setSizes([500, 400, 400])

        bottom = self._track_splitter(QSplitter(Qt.Horizontal))
        bottom.setHandleWidth(6)
        bottom.setChildrenCollapsible(False)
        for i in range(3):
            bottom.addWidget(self._new_pane(i + 2))
            bottom.setStretchFactor(i, 1)
        bottom.setSizes([400, 400, 400])

        outer.addWidget(top)
        outer.addWidget(bottom)
        outer.setStretchFactor(0, 1)
        outer.setStretchFactor(1, 1)
        outer.setSizes([450, 450])
        return outer
