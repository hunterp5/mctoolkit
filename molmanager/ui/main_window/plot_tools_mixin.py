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

"""Plot↔table sync, floating plot dialogs, and thin dock API over PlotDockHost."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class PlotToolsMixin:
    @property
    def plot_dock(self):
        """Workspace docking owner (:class:`~molmanager.ui.plot_dock_host.PlotDockHost`)."""
        host = getattr(self, "_plot_dock_host", None)
        if host is None:
            from ..plot_dock_host import PlotDockHost

            host = PlotDockHost(self)
            self._plot_dock_host = host
        return host

    def _workspace(self):
        return self.plot_dock.workspace()

    @staticmethod
    def _docked_widget_kind(plot_widget) -> str:
        from ..plot_dock_host import PlotDockHost

        return PlotDockHost._docked_widget_kind(plot_widget)

    def iter_docked_plot_widgets(self):
        yield from self.plot_dock.iter_docked_plot_widgets()

    def pane_for_plot_widget(self, plot_widget):
        return self.plot_dock.pane_for_plot_widget(plot_widget)

    def is_plot_docked(self, plot_widget) -> bool:
        return self.plot_dock.is_plot_docked(plot_widget)

    def find_docked_plot_widget(self, predicate):
        return self.plot_dock.find_docked_plot_widget(predicate)

    @property
    def _docked_plot_widget(self):
        return self.plot_dock._docked_plot_widget

    @_docked_plot_widget.setter
    def _docked_plot_widget(self, value) -> None:
        self.plot_dock._docked_plot_widget = value

    def _plot_panel_splitter_sizes(self) -> list[int] | None:
        return self.plot_dock._plot_panel_splitter_sizes()

    def _docked_plot_content_widths(self) -> tuple[int, int]:
        return self.plot_dock._docked_plot_content_widths()

    def _apply_plot_panel_minimum_width(self) -> int:
        return self.plot_dock._apply_plot_panel_minimum_width()

    def _ensure_plot_panel_width(self, preferred: int | None = None) -> None:
        self.plot_dock._ensure_plot_panel_width(preferred)

    def _target_plot_pane(self):
        return self.plot_dock._target_plot_pane()

    def dock_plot_widget(self, plot_widget, pane=None) -> bool:
        return self.plot_dock.dock_plot_widget(plot_widget, pane)

    def _wire_docked_plot_widget(self, plot_widget) -> None:
        self.plot_dock._wire_docked_plot_widget(plot_widget)

    def _float_released_plot_widget(self, plot_widget) -> None:
        self.plot_dock._float_released_plot_widget(plot_widget)

    def _sync_plot_panel_bottom_visibility(self) -> None:
        self.plot_dock._sync_plot_panel_bottom_visibility()

    def show_docked_plot_panel(self, preferred: int | None = None) -> None:
        self.plot_dock.show_docked_plot_panel(preferred=preferred)

    def hide_docked_plot_panel(self) -> None:
        self.plot_dock.hide_docked_plot_panel()

    def _on_docked_plot_destroyed(self, *_args) -> None:
        self.plot_dock._on_docked_plot_destroyed(*_args)

    def close_plot_panel_keep_plot(self) -> None:
        self.plot_dock.close_plot_panel_keep_plot()

    def close_docked_plot(self, plot_widget=None, *, confirm: bool = True) -> None:
        self.plot_dock.close_docked_plot(plot_widget, confirm=confirm)

    def close_plot_pane(self, pane=None) -> None:
        self.plot_dock.close_plot_pane(pane)

    def _release_plot_widget_from_panel_host(self, plot_widget, **kwargs) -> None:
        self.plot_dock._release_plot_widget_from_panel_host(plot_widget, **kwargs)

    def undock_plot_to_window(self, plot_widget=None) -> bool:
        return self.plot_dock.undock_plot_to_window(plot_widget)

    def _prepare_tool_plot(self, plot_widget) -> None:
        """Keep docked plot scope UI in sync with table selection changes."""
        self._attach_tool_scope_sync(plot_widget, on_finished_signal=plot_widget.destroyed)

    def _iter_active_plot_selection_views(self) -> list:
        """Plot surfaces that mirror table row selection (dock, floating plotter, PCA/t-SNE)."""
        from ..dockable_plot import iter_plot_selection_views

        views: list = []
        seen: set[int] = set()

        def add_from(root) -> None:
            for view in iter_plot_selection_views(root):
                key = id(view)
                if key in seen:
                    continue
                seen.add(key)
                views.append(view)

        for docked in self.iter_docked_plot_widgets():
            add_from(docked)
        for plot_dlg in self._iter_plot_dialogs():
            pw = getattr(plot_dlg, "_plot_widget", None)
            if pw is not None:
                add_from(pw)
            else:
                add_from(plot_dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            panel = getattr(dlg, "_panel", None)
            if panel is not None:
                add_from(panel)
                continue
            add_from(dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            try:
                from PyQt5 import sip

                if sip.isdeleted(dlg):
                    continue
            except Exception:
                pass
            panel = getattr(dlg, "_panel", None)
            if panel is not None:
                add_from(panel)
            else:
                add_from(dlg)
        return views

    def _refresh_active_plot_axis_columns(self) -> None:
        """Update plotter axis dropdowns when table columns or numeric bounds change."""
        for view in self._iter_active_plot_selection_views():
            refresh = getattr(view, "refresh_axis_columns", None) or getattr(
                view, "refresh_spoke_columns", None
            )
            if callable(refresh):
                try:
                    refresh()
                except RuntimeError:
                    pass

    def _sync_active_plots_from_table_selection(self) -> None:
        from ..plot_table_sync import selected_oids_for_plot

        self._refresh_attached_tool_scope_labels()
        selected = selected_oids_for_plot(self)
        # Share one OID set across every open plot for this fan-out tick.
        self._cached_plot_selected_oids = frozenset(selected)
        try:
            for view in self._iter_active_plot_selection_views():
                try:
                    sync = getattr(view, "sync_from_table_selection", None)
                    if not callable(sync):
                        continue
                    try:
                        sync(selected_oids=selected)
                    except TypeError:
                        sync()
                except RuntimeError:
                    pass
        finally:
            self._cached_plot_selected_oids = None

    def _schedule_sync_active_plots_from_table_selection(self) -> None:
        timer = getattr(self, "_plot_table_sync_timer", None)
        if timer is None:
            return
        timer.start(40)

    def _iter_active_plot_hosts(self) -> list:
        """Docked / floating plot panels that can rebuild from the current table."""
        hosts: list = []
        seen: set[int] = set()

        def add(candidate) -> None:
            if candidate is None:
                return
            key = id(candidate)
            if key in seen:
                return
            seen.add(key)
            hosts.append(candidate)

        for docked in self.iter_docked_plot_widgets():
            add(docked)
        for plot_dlg in self._iter_plot_dialogs():
            add(getattr(plot_dlg, "_plot_widget", None) or plot_dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            add(getattr(dlg, "_panel", None) or dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            add(getattr(dlg, "_panel", None) or dlg)
        return hosts

    def _replot_active_plots(self) -> None:
        """Refresh plot data after filters or table edits change visible rows."""
        # Warm sticky visible-row cache once for every open host (incl. debounced Plotter).
        self._visible_source_row_indices()
        hosts = list(self._iter_active_plot_hosts())
        restore_idle = getattr(self, "_restore_idle_status", None)
        work_active = getattr(self, "_status_work_is_active", None)
        show_update = (
            bool(hosts)
            and getattr(self, "status_label", None) is not None
            and not (callable(work_active) and work_active())
        )
        if show_update:
            try:
                self.status_label.setText(f"Updating plots… ({len(hosts)})")
            except RuntimeError:
                show_update = False
        for host in hosts:
            fn = getattr(host, "_schedule_plot", None) or getattr(host, "_rebuild_figure", None)
            if not callable(fn):
                continue
            try:
                fn()
            except RuntimeError:
                pass
        if show_update and callable(restore_idle):
            restore_idle()

    def _schedule_active_plots_replot(self, *, delay_ms: int = 80, force: bool = False) -> None:
        if (
            not force
            and getattr(self, "_background_job_ui_active", None)
            and self._background_job_ui_active()
        ):
            return
        timer = getattr(self, "_plot_replot_timer", None)
        if timer is None:
            return
        timer.start(max(0, int(delay_ms)))

    def _prune_plot_dialogs(self) -> None:
        alive: list = []
        for dlg in getattr(self, "_plot_dialogs", []):
            try:
                dlg.isVisible()
                alive.append(dlg)
            except RuntimeError:
                pass
        self._plot_dialogs = alive

    def _iter_plot_dialogs(self) -> list:
        self._prune_plot_dialogs()
        return list(self._plot_dialogs)

    def _register_plot_dialog(self, dlg) -> None:
        """Track a floating plotter window (multiple instances allowed)."""
        if not hasattr(self, "_plot_dialogs"):
            self._plot_dialogs = []
        self._prune_plot_dialogs()
        self._plot_dialogs.append(dlg)
        panel = getattr(dlg, "_plot_widget", None)
        custom = getattr(panel, "_pane_display_title", None) if panel is not None else None
        if isinstance(custom, str) and custom.strip():
            dlg.setWindowTitle(custom.strip())
        else:
            n = len(self._plot_dialogs)
            dlg.setWindowTitle("Plot Data" if n == 1 else f"Plot Data ({n})")
        dlg.destroyed.connect(lambda *_a, d=dlg: self._unregister_plot_dialog(d))

    def _unregister_plot_dialog(self, dlg) -> None:
        try:
            self._plot_dialogs.remove(dlg)
        except (ValueError, AttributeError):
            pass
        self._prune_plot_dialogs()

    def _create_plot_dialog(self):
        from ..plot import PlotDialog

        d = PlotDialog(self)
        self._prepare_tool_dialog(d)
        return d

    def _bind_undocked_browser_dialog(self, dlg) -> bool:
        """Track Data → Browser / Predict SOM windows after undock. Return True if handled."""
        from ..metabolite_browser import MetaboliteBrowserDialog
        from ..pose_browser import PoseBrowserDialog
        from ..random_molecule_browser import RandomMoleculeBrowserDialog
        from ..selection_browser import SelectionBrowserDialog
        from ..som_browser import SomBrowserDialog

        if isinstance(dlg, SelectionBrowserDialog):
            self._selection_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_selection_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        if isinstance(dlg, PoseBrowserDialog):
            self._pose_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_pose_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        if isinstance(dlg, SomBrowserDialog):
            self._som_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_som_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        if isinstance(dlg, MetaboliteBrowserDialog):
            self._metabolite_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_metabolite_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        if isinstance(dlg, RandomMoleculeBrowserDialog):
            self._random_molecule_browser_dialog = dlg
            try:
                dlg.destroyed.connect(self._on_random_molecule_browser_dialog_destroyed)
            except Exception:
                pass
            return True
        return False

    def _on_random_molecule_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_random_molecule_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._random_molecule_browser_dialog = None

    def _register_floating_result_dialog(self, dlg) -> None:
        """Track undocked SALI/cliff/MMP/etc. windows for table↔plot selection sync."""
        if not hasattr(self, "_floating_result_dialogs"):
            self._floating_result_dialogs = []
        alive: list = []
        for existing in self._floating_result_dialogs:
            try:
                from PyQt5 import sip

                if sip.isdeleted(existing):
                    continue
            except Exception:
                pass
            alive.append(existing)
        if dlg not in alive:
            alive.append(dlg)
            try:
                dlg.destroyed.connect(lambda *_a, d=dlg: self._unregister_floating_result_dialog(d))
            except Exception:
                pass
        self._floating_result_dialogs = alive

    def _unregister_floating_result_dialog(self, dlg) -> None:
        try:
            self._floating_result_dialogs.remove(dlg)
        except (ValueError, AttributeError):
            pass
