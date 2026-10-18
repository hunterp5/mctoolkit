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

"""Workspace plot docking owner: dock/undock, panel width, and pane close."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Iterator

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QMessageBox

from .layout_flags import FLAG_DIRECT_FLOAT_SHOW, FLAG_SNAPSHOT_TRANSITIONS, layout_flag
from .layout_geometry import grow_horizontal_plot_split, grow_vertical_pane_split
from .layout_perf import perf_span

logger = logging.getLogger(__name__)


class _SplitterSizeBatch:
    """Apply ``setSizes`` once per splitter at the end of a dock/undock transition."""

    def __init__(self) -> None:
        self._items: list[tuple[Any, list[int]]] = []
        self.defer_hold_release = False

    def set_sizes(self, splitter, sizes: list[int]) -> None:
        self._items.append((splitter, [max(0, int(s)) for s in sizes]))

    def apply(self) -> None:
        latest: dict[int, tuple[Any, list[int]]] = {}
        for splitter, sizes in self._items:
            latest[id(splitter)] = (splitter, sizes)
        for splitter, sizes in latest.values():
            try:
                splitter.setSizes(sizes)
            except RuntimeError:
                continue
        self._items.clear()


def _plot_dialog_and_widget_types():
    """Import plot window types when QtWebEngine is available in this process."""
    try:
        from .plot import PlotDialog, PlotWidget
    except ImportError:
        return None, None
    return PlotDialog, PlotWidget


class PlotDockHost:
    """Owns docked-plot lifecycle for :class:`~molmanager.ui.main_window.ChemistryWorkspaceWindow`.

    Public entry points remain on the main window (via :class:`PlotToolsMixin`) so
    existing callers keep working; this object holds the implementation.
    """

    def __init__(self, app: Any) -> None:
        self._app = app
        self._active_transitions: set[int] = set()

    def workspace(self):
        return getattr(self._app, "_workspace_layout", None)

    @staticmethod
    def _docked_widget_kind(plot_widget) -> str:
        title = getattr(plot_widget, "_window_title", None)
        if title:
            return str(title)
        if getattr(plot_widget, "dockable_in_workspace", False) and not getattr(
            plot_widget, "only_selected_cb", None
        ):
            return "Viewer"
        return "Plot"

    def iter_docked_plot_widgets(self):
        mgr = self.workspace()
        if mgr is None:
            return
        yield from mgr.iter_docked_widgets()

    def pane_for_plot_widget(self, plot_widget):
        mgr = self.workspace()
        if mgr is None:
            return None
        return mgr.pane_for_widget(plot_widget)

    def is_plot_docked(self, plot_widget) -> bool:
        return self.pane_for_plot_widget(plot_widget) is not None

    def find_docked_plot_widget(self, predicate):
        for w in self.iter_docked_plot_widgets():
            try:
                if predicate(w):
                    return w
            except RuntimeError:
                continue
        return None

    @property
    def _docked_plot_widget(self):
        """Compatibility: preferred pane's plot, else first docked plot."""
        mgr = self.workspace()
        if mgr is None:
            return None
        pref = mgr.preferred_pane()
        if pref is not None and pref.plot_widget() is not None:
            return pref.plot_widget()
        for w in mgr.iter_docked_widgets():
            return w
        return None

    @_docked_plot_widget.setter
    def _docked_plot_widget(self, value) -> None:
        # Legacy assignments clear nothing useful; ignore None writes from old paths.
        if value is None:
            return
        mgr = self.workspace()
        if mgr is None:
            return
        pane = mgr.preferred_pane() or (mgr.plot_panes()[0] if mgr.plot_panes() else None)
        if pane is not None:
            mgr.dock_into_pane(pane, value)

    def _plot_panel_splitter_sizes(self) -> list[int] | None:
        """Outer table|plots sizes when the workspace uses a horizontal outer splitter."""
        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return None
        splitter = mgr._splitters[0]
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return None
        if len(sizes) < 2:
            return None
        return sizes

    def _docked_plot_content_widths(self) -> tuple[int, int]:
        """Return ``(minimum_width, preferred_width)`` for docked plot content."""
        from .dockable_plot import (
            PLOT_PANEL_BASE_MINIMUM_WIDTH,
            PLOT_PANEL_DEFAULT_WIDTH,
            plot_embedded_minimum_width,
            plot_embedded_preferred_width,
        )

        widgets = list(self.iter_docked_plot_widgets())
        if not widgets:
            return PLOT_PANEL_BASE_MINIMUM_WIDTH, PLOT_PANEL_DEFAULT_WIDTH
        min_w = max(plot_embedded_minimum_width(w) for w in widgets)
        pref_w = max(plot_embedded_preferred_width(w) for w in widgets)
        return min_w, pref_w

    def _apply_plot_panel_minimum_width(self) -> int:
        from .dockable_plot import PLOT_PANEL_BASE_MINIMUM_WIDTH

        mgr = self.workspace()
        if mgr is None:
            return PLOT_PANEL_BASE_MINIMUM_WIDTH
        min_w, _pref = self._docked_plot_content_widths()
        if not list(self.iter_docked_plot_widgets()):
            min_w = PLOT_PANEL_BASE_MINIMUM_WIDTH
        return min_w

    def _ensure_plot_panel_width(
        self, preferred: int | None = None, batch: _SplitterSizeBatch | None = None
    ) -> None:
        """Give the plot region a usable width when the outer splitter is horizontal."""
        from .dockable_plot import PLOT_PANEL_COLLAPSED_WIDTH

        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return
        if mgr.layout_id in {"quadrants", "table_grid"}:
            return
        splitter = mgr._splitters[0]
        try:
            if splitter.orientation() != Qt.Horizontal:
                return
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return
        if len(sizes) < 2:
            return
        min_w = self._apply_plot_panel_minimum_width()
        _content_min, content_pref = self._docked_plot_content_widths()
        pair = grow_horizontal_plot_split(
            sizes[0],
            sizes[1],
            preferred=preferred,
            min_plot_w=min_w,
            content_pref_w=content_pref,
            collapsed_plot_w=PLOT_PANEL_COLLAPSED_WIDTH,
        )
        if pair is None:
            return
        if batch is not None:
            batch.set_sizes(splitter, list(pair))
        else:
            splitter.setSizes(list(pair))

    @staticmethod
    def _widget_pixel_size(widget) -> tuple[int, int]:
        """Best-effort on-screen size of a plot panel (content geometry first)."""
        try:
            w, h = int(widget.width()), int(widget.height())
            if w > 50 and h > 50:
                return w, h
        except RuntimeError:
            pass
        try:
            win = widget.window()
            if win is not None:
                w, h = int(win.width()), int(win.height())
                if w > 50 and h > 50:
                    return w, h
        except RuntimeError:
            pass
        return 0, 0

    def _round_trip_pixel_size(self, widget) -> tuple[int, int]:
        """Size used to match dock pane <-> floating host without chrome ratchet.

        Prefer the outer floating window when the plot is undocked so dialog frame
        pixels are not lost on the next dock. When already docked, use content size
        so the floating dialog opens near the pane the user just left.
        """
        if widget is None:
            return 0, 0
        try:
            win = widget.window()
        except RuntimeError:
            win = None
        # Floating host (dialog / top-level other than the main window).
        try:
            if win is not None and win is not widget and win is not self._app:
                w, h = int(win.width()), int(win.height())
                if w > 50 and h > 50:
                    return w, h
        except RuntimeError:
            pass
        return self._widget_pixel_size(widget)

    def _match_vertical_pane_height(
        self, pane, height: int, batch: _SplitterSizeBatch | None = None
    ) -> None:
        """When the pane sits in a vertical splitter, grow it toward ``height`` pixels."""
        mgr = self.workspace()
        if mgr is None or height < 50:
            return
        containing = getattr(mgr, "_splitter_containing", None)
        if not callable(containing):
            return
        splitter = containing(pane)
        if splitter is None:
            return
        try:
            if splitter.orientation() != Qt.Vertical:
                return
            sizes = [int(s) for s in splitter.sizes()]
            count = int(splitter.count())
        except RuntimeError:
            return
        index = next((i for i in range(count) if splitter.widget(i) is pane), -1)
        if index < 0 or len(sizes) != count:
            return
        new_sizes = grow_vertical_pane_split(sizes, index, int(height))
        if new_sizes is None:
            return
        if batch is not None:
            batch.set_sizes(splitter, new_sizes)
        else:
            splitter.setSizes(new_sizes)

    def _match_pane_to_plot_size(
        self,
        pane,
        width: int,
        height: int,
        batch: _SplitterSizeBatch | None = None,
    ) -> None:
        """Grow the destination pane toward the plot's current pixel size before dock."""
        if width > 50:
            self._ensure_plot_panel_width(preferred=width, batch=batch)
        if height > 50:
            self._match_vertical_pane_height(pane, height, batch=batch)

    @contextmanager
    def _dock_transition(self, plot_widget) -> Iterator[_SplitterSizeBatch | None]:
        """Guard dock/undock: one transition per widget, batched splitter sizes, resize hold."""
        if plot_widget is None:
            yield None
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(plot_widget):
                yield None
                return
        except Exception:
            pass
        key = id(plot_widget)
        if key in self._active_transitions:
            yield None
            return
        self._active_transitions.add(key)
        batch = _SplitterSizeBatch()
        self._set_dock_transition_buttons(plot_widget, False)
        self._set_plot_resize_hold(plot_widget, True)
        try:
            plot_widget.setUpdatesEnabled(False)
        except RuntimeError:
            pass
        try:
            yield batch
            batch.apply()
        finally:
            try:
                plot_widget.setUpdatesEnabled(True)
            except RuntimeError:
                pass
            if not batch.defer_hold_release:
                self._set_plot_resize_hold(plot_widget, False)
            self._set_dock_transition_buttons(plot_widget, True)
            self._active_transitions.discard(key)

    @staticmethod
    def _set_dock_transition_buttons(plot_widget, enabled: bool) -> None:
        for name in ("_add_to_main_btn", "_send_window_btn"):
            btn = getattr(plot_widget, name, None)
            if btn is None:
                continue
            try:
                btn.setEnabled(bool(enabled))
            except RuntimeError:
                continue

    @staticmethod
    def _apply_floating_dialog_size(dialog, width: int, height: int) -> None:
        """Resize a newly created floating host to the docked plot's last size."""
        if dialog is None or width < 50 or height < 50:
            return
        try:
            dialog.resize(int(width), int(height))
        except RuntimeError:
            pass

    @staticmethod
    def _iter_web_engine_views(widget):
        """Yield nested ``QWebEngineView`` widgets when QtWebEngine is available."""
        if widget is None:
            return
        try:
            from PyQt5.QtWebEngineWidgets import QWebEngineView
        except ImportError:
            return
        try:
            yield from widget.findChildren(QWebEngineView)
        except RuntimeError:
            return

    @classmethod
    def _resize_plot_surfaces(cls, widget, width: int, height: int) -> None:
        """Pin the plot panel and nested WebEngine views to ``width`` x ``height``."""
        if widget is None or width < 20 or height < 20:
            return
        try:
            widget.resize(int(width), int(height))
        except RuntimeError:
            pass
        for view in cls._iter_web_engine_views(widget):
            try:
                view.resize(int(width), int(height))
            except RuntimeError:
                continue

    @classmethod
    def _set_plot_resize_hold(cls, widget, hold: bool) -> None:
        """Ask Plotly shells to coalesce resizes until geometry settles."""
        js = f"window.molmanagerHoldResize && molmanagerHoldResize({'true' if hold else 'false'});"
        for view in cls._iter_web_engine_views(widget):
            try:
                page = view.page()
            except RuntimeError:
                continue
            if page is None:
                continue
            try:
                page.runJavaScript(js)
            except RuntimeError:
                continue

    def _begin_snapshot_placeholder(self, plot_widget):
        """Show a static grab of the web view during reparent when the flag is enabled."""
        if not layout_flag(FLAG_SNAPSHOT_TRANSITIONS):
            return None
        views = list(self._iter_web_engine_views(plot_widget))
        if not views:
            return None
        view = views[0]
        try:
            pixmap = view.grab()
        except RuntimeError:
            return None
        if pixmap is None or pixmap.isNull():
            return None
        from PyQt5.QtWidgets import QLabel

        overlay = QLabel(plot_widget)
        overlay.setPixmap(pixmap)
        try:
            overlay.setGeometry(view.geometry())
        except RuntimeError:
            overlay.deleteLater()
            return None
        overlay.show()
        overlay.raise_()

        def cleanup() -> None:
            try:
                overlay.hide()
                overlay.deleteLater()
            except RuntimeError:
                pass

        return cleanup

    def _register_floating_dialog(self, dlg, plot_widget) -> None:
        if not self._app._bind_undocked_browser_dialog(dlg):
            plot_dialog_cls, _plot_cls = _plot_dialog_and_widget_types()
            if plot_dialog_cls is not None and isinstance(dlg, plot_dialog_cls):
                self._app._register_plot_dialog(dlg)
            else:
                self._app._register_floating_result_dialog(dlg)

    def _show_floating_host(
        self,
        dlg,
        plot_widget,
        content_w: int,
        content_h: int,
        *,
        batch: _SplitterSizeBatch | None = None,
    ) -> None:
        """Reveal a floating host at the plot's last docked size."""
        if layout_flag(FLAG_DIRECT_FLOAT_SHOW):
            self._apply_floating_dialog_size(dlg, content_w, content_h)
            try:
                dlg.ensurePolished()
                layout = dlg.layout()
                if layout is not None:
                    layout.activate()
            except RuntimeError:
                pass
            plot_widget.show()
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            if batch is not None:
                batch.defer_hold_release = True
            QTimer.singleShot(0, lambda w=plot_widget: self._set_plot_resize_hold(w, False))
            try:
                plot_widget.setFocus(Qt.OtherFocusReason)
            except RuntimeError:
                pass
            return
        self._prepare_floating_host_geometry(dlg, plot_widget, content_w, content_h)
        plot_widget.show()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _float_widget(self, plot_widget, content_w: int, content_h: int) -> bool:
        """Move a docked plot into a floating dialog (single code path)."""
        factory = getattr(plot_widget, "create_floating_dialog", None)
        _dialog_cls, plot_cls = _plot_dialog_and_widget_types()
        snapshot_cleanup = self._begin_snapshot_placeholder(plot_widget)
        with self._dock_transition(plot_widget) as batch:
            if batch is None:
                if snapshot_cleanup is not None:
                    snapshot_cleanup()
                return False
            self._release_plot_widget_from_panel_host(plot_widget, sync_chrome=False)
            dlg = None
            if callable(factory):
                dlg = factory(self._app)
            elif plot_cls is not None and isinstance(plot_widget, plot_cls):
                from .plot import PlotDialog

                dlg = PlotDialog(self._app, plot_widget=plot_widget)
            if dlg is None:
                if snapshot_cleanup is not None:
                    snapshot_cleanup()
                return False
            self._app._prepare_tool_dialog(dlg)
            self._register_floating_dialog(dlg, plot_widget)
            self._show_floating_host(
                dlg, plot_widget, content_w, content_h, batch=batch
            )
        if snapshot_cleanup is not None:
            snapshot_cleanup()
        kind = self._docked_widget_kind(plot_widget)
        self._app.status_label.setText(f"{kind}: moved to separate window.")
        mark = getattr(self._app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True

    def _prepare_floating_host_geometry(self, dialog, plot_widget, content_w: int, content_h: int) -> None:
        """Size ``dialog`` off-screen so ``plot_widget`` matches docked content on first paint."""
        from PyQt5.QtCore import Qt
        from PyQt5.QtWidgets import QApplication

        if dialog is None or plot_widget is None or content_w < 50 or content_h < 50:
            return
        self._apply_floating_dialog_size(dialog, content_w, content_h)
        dialog.setAttribute(Qt.WA_DontShowOnScreen, True)
        try:
            dialog.show()
            app = QApplication.instance()
            if app is not None:
                app.processEvents()
            try:
                cur_w, cur_h = int(plot_widget.width()), int(plot_widget.height())
            except RuntimeError:
                cur_w, cur_h = 0, 0
            if cur_w > 0 and cur_h > 0:
                dw = int(content_w) - cur_w
                dh = int(content_h) - cur_h
                if abs(dw) > 1 or abs(dh) > 1:
                    try:
                        dialog.resize(int(dialog.width()) + dw, int(dialog.height()) + dh)
                    except RuntimeError:
                        pass
                    if app is not None:
                        app.processEvents()
            self._resize_plot_surfaces(plot_widget, content_w, content_h)
        finally:
            try:
                dialog.hide()
            except RuntimeError:
                pass
            dialog.setAttribute(Qt.WA_DontShowOnScreen, False)

    def _finalize_docked_plot_geometry(self, pane, plot_widget) -> None:
        """Apply stack geometry to a just-docked plot before the first visible paint."""
        if pane is None or plot_widget is None:
            return
        presize = getattr(pane, "_presize_stack_pages", None)
        if callable(presize):
            try:
                presize()
            except RuntimeError:
                pass
        stack = getattr(pane, "_stack", None)
        if stack is None:
            return
        try:
            sw, sh = int(stack.width()), int(stack.height())
        except RuntimeError:
            return
        if sw < 20 or sh < 20:
            return
        self._resize_plot_surfaces(plot_widget, sw, sh)

    def _target_plot_pane(self):
        """Return the active plot pane, expanding Table Only to a table|plot split."""
        mgr = self.workspace()
        if mgr is None:
            return None
        ensure = getattr(mgr, "ensure_single_plot_pane", None)
        if callable(ensure):
            return ensure()
        if mgr.plot_panes():
            return mgr.preferred_pane()
        from .main_window.workspace_layout import LAYOUT_TABLE_SINGLE

        self._app.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
        panes = mgr.plot_panes()
        return panes[0] if panes else None

    def dock_plot_widget(self, plot_widget, pane=None) -> bool:
        """Move a plot or viewer widget into the active workspace plot pane."""
        with perf_span("dock_plot_widget"):
            return self._dock_plot_widget(plot_widget, pane)

    def _dock_plot_widget(self, plot_widget, pane=None) -> bool:
        from .dockable_plot import is_dockable_workspace_widget

        if not is_dockable_workspace_widget(plot_widget):
            _dialog_cls, plot_cls = _plot_dialog_and_widget_types()
            if plot_cls is None or not isinstance(plot_widget, plot_cls):
                return False
        mgr = self.workspace()
        if mgr is None:
            return False

        # Capture floating host size before reparent so the pane can grow to match.
        src_w, src_h = self._round_trip_pixel_size(plot_widget)
        target = pane if pane is not None else self._target_plot_pane()
        if target is None:
            return False

        prior_teardown = getattr(plot_widget, "_scope_sync_disconnect", None)
        if callable(prior_teardown):
            prior_teardown()
        snapshot_cleanup = self._begin_snapshot_placeholder(plot_widget)
        with self._dock_transition(plot_widget) as batch:
            if batch is None:
                if snapshot_cleanup is not None:
                    snapshot_cleanup()
                return False
            if src_w > 50:
                self._match_pane_to_plot_size(target, src_w, src_h, batch=batch)
            else:
                self._ensure_plot_panel_width(preferred=None, batch=batch)
            mgr.dock_into_pane(
                target, plot_widget, restore_splitter_snapshot=False
            )
            self._finalize_docked_plot_geometry(target, plot_widget)
        if snapshot_cleanup is not None:
            snapshot_cleanup()
        # Paint the docked plot first; per-widget wire/selection can wait a tick.
        QTimer.singleShot(0, lambda w=plot_widget: self._wire_docked_plot_widget(w))
        kind = self._docked_widget_kind(plot_widget)
        pane_n = mgr.plot_panes().index(target) + 1
        n_pages = target.page_count()
        if n_pages > 1:
            self._app.status_label.setText(
                f"{kind}: docked in pane {pane_n} ({target.page_index() + 1}/{n_pages})."
            )
        else:
            self._app.status_label.setText(f"{kind}: docked in pane {pane_n}.")
        mark = getattr(self._app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        return True

    def _wire_docked_plot_widget(self, plot_widget) -> None:
        """Attach session/scope hooks used for any docked plot or viewer."""
        try:
            from PyQt5 import sip

            if plot_widget is None or sip.isdeleted(plot_widget):
                return
        except Exception:
            if plot_widget is None:
                return
        self._app._prepare_tool_plot(plot_widget)
        try:
            plot_widget.destroyed.disconnect(self._on_docked_plot_destroyed)
        except (TypeError, RuntimeError):
            pass
        try:
            plot_widget.destroyed.connect(self._on_docked_plot_destroyed)
        except RuntimeError:
            return
        # Footer chrome already adopted in the pane; refresh only this plot's selection.
        sync = getattr(plot_widget, "sync_from_table_selection", None)
        if callable(sync):
            try:
                sync()
            except RuntimeError:
                pass

    def _float_released_plot_widget(self, plot_widget) -> None:
        """Open a released docked plot in a floating dialog when possible."""
        if plot_widget is None:
            return
        content_w, content_h = self._widget_pixel_size(plot_widget)
        try:
            if self._float_widget(plot_widget, content_w, content_h):
                return
        except Exception:
            logger.exception("Failed to float released plot widget")
        try:
            plot_widget.setParent(None)
            plot_widget.deleteLater()
        except RuntimeError:
            pass

    def _sync_plot_panel_bottom_visibility(self) -> None:
        """No shared host bottom bar in multi-pane layout."""
        return

    def show_docked_plot_panel(self, preferred: int | None = None) -> None:
        """Ensure the workspace plot region has usable width."""
        mgr = self.workspace()
        if mgr is not None:
            mgr.show()
        # Session restore owns splitter sizes; do not fight them with auto-grow.
        if getattr(self._app, "_pending_session_workspace_layout", None):
            return
        # Preferred sizes must apply before the first docked paint (no deferred pass).
        if preferred is not None:
            self._ensure_plot_panel_width(preferred)
            return
        QTimer.singleShot(0, lambda: self._ensure_plot_panel_width(None))

    def hide_docked_plot_panel(self) -> None:
        """Collapse plot region width on horizontal layouts (table keeps space)."""
        mgr = self.workspace()
        if mgr is None or not mgr._splitters:
            return
        if mgr.layout_id == "quadrants":
            return
        splitter = mgr._splitters[0]
        try:
            sizes = [int(s) for s in splitter.sizes()]
        except RuntimeError:
            return
        total = sum(sizes) if sizes else 0
        if total <= 0:
            total = max(splitter.width(), 1)
        splitter.setSizes([total, 0])

    def _on_docked_plot_destroyed(self, *_args) -> None:
        mgr = self.workspace()
        if mgr is None:
            return
        for pane in mgr.plot_panes():
            for w in list(pane.plot_widgets()):
                try:
                    from PyQt5 import sip

                    if sip.isdeleted(w):
                        pane.remove_plot_widget(w)
                except Exception:
                    pass

    def close_plot_panel_keep_plot(self) -> None:
        """Hide/collapse the plot region; docked widgets are preserved."""
        self.hide_docked_plot_panel()
        self._app.status_label.setText("Plot panel hidden.")

    def close_docked_plot(self, plot_widget=None, *, confirm: bool = True) -> None:
        """Close a docked plot (``plot_widget`` or the preferred/occupied pane)."""
        mgr = self.workspace()
        if mgr is None:
            return
        if plot_widget is None:
            pane = mgr.preferred_pane()
            plot_widget = pane.plot_widget() if pane is not None else None
            if plot_widget is None:
                for p in mgr.plot_panes():
                    if p.plot_widget() is not None:
                        pane = p
                        plot_widget = p.plot_widget()
                        break
        else:
            pane = mgr.pane_for_widget(plot_widget)
        if plot_widget is None:
            self._app.status_label.setText("No docked plot to close.")
            return
        self._notify_docked_plot_closing(plot_widget)
        self._release_plot_widget_from_panel_host(plot_widget, discard=True)
        self._schedule_plot_widget_delete(plot_widget)
        self._apply_plot_panel_minimum_width()
        self._app.status_label.setText("Plot closed.")

    def close_plot_pane(self, pane=None) -> None:
        """Close a workspace plot pane and delete every plot it contains."""
        mgr = self.workspace()
        if mgr is None:
            return
        if pane is None:
            pane = mgr.preferred_pane()
        if pane is None:
            self._app.status_label.setText("No plot pane to close.")
            return

        widgets = list(pane.plot_widgets())
        if widgets:
            n = len(widgets)
            noun = "plot" if n == 1 else "plots"
            reply = QMessageBox.question(
                self._app,
                "Close Plot Pane",
                f"This pane has {n} {noun}. Close the pane and discard "
                f"{'it' if n == 1 else 'them'}?",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        try:
            pane.hide()
        except RuntimeError:
            pass

        for plot_widget in widgets:
            self._notify_docked_plot_closing(plot_widget)
            self._release_plot_widget_from_panel_host(plot_widget, discard=True)
            self._schedule_plot_widget_delete(plot_widget)

        if not mgr.remove_pane(pane):
            self._app.status_label.setText("Could not close plot pane.")
            return

        self._apply_plot_panel_minimum_width()
        remaining = len(mgr.plot_panes())
        if remaining:
            self._app.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). {remaining} pane(s) remain."
            )
        else:
            self._app.status_label.setText(
                f"Plot pane closed ({len(widgets)} plot(s) removed). Table-only layout."
            )

    def _release_plot_widget_from_panel_host(
        self, plot_widget, *, discard: bool = False, sync_chrome: bool = True
    ) -> None:
        mgr = self.workspace()
        if mgr is not None:
            mgr.release_widget(plot_widget, discard=discard)
        teardown = getattr(plot_widget, "_scope_sync_disconnect", None)
        if callable(teardown):
            teardown()
        if discard:
            return
        if sync_chrome:
            sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
            if callable(sync_footer):
                try:
                    sync_footer()
                except RuntimeError:
                    pass
        self._apply_plot_panel_minimum_width()

    def _schedule_plot_widget_delete(self, plot_widget) -> None:
        from .plot_web_surface import schedule_webengine_widget_delete

        schedule_webengine_widget_delete(plot_widget)

    def _notify_docked_plot_closing(self, plot_widget) -> None:
        closing = getattr(plot_widget, "on_docked_plot_closing", None)
        if not callable(closing):
            return
        try:
            closing()
        except RuntimeError:
            pass

    @staticmethod
    def _defer_plot_chrome_sync(plot_widget) -> None:
        sync_footer = getattr(plot_widget, "_sync_footer_chrome", None)
        if not callable(sync_footer):
            return

        def _run() -> None:
            try:
                from PyQt5 import sip

                if sip.isdeleted(plot_widget):
                    return
            except Exception:
                pass
            try:
                sync_footer()
            except RuntimeError:
                pass

        QTimer.singleShot(0, _run)

    def undock_plot_to_window(self, plot_widget=None) -> bool:
        """Move a docked plot into a floating window."""
        with perf_span("undock_plot_to_window"):
            return self._undock_plot_to_window(plot_widget)

    def _undock_plot_to_window(self, plot_widget=None) -> bool:
        mgr = self.workspace()
        if mgr is None:
            return False
        if plot_widget is None:
            pane = mgr.preferred_pane()
            plot_widget = pane.plot_widget() if pane is not None else None
            if plot_widget is None:
                for p in mgr.plot_panes():
                    if p.plot_widget() is not None:
                        plot_widget = p.plot_widget()
                        break
        if plot_widget is None:
            return False

        content_w, content_h = self._widget_pixel_size(plot_widget)
        if self._float_widget(plot_widget, content_w, content_h):
            return True
        _dialog_cls, plot_cls = _plot_dialog_and_widget_types()
        if plot_cls is None or not isinstance(plot_widget, plot_cls):
            self._release_plot_widget_from_panel_host(plot_widget)
            return False
        return False
