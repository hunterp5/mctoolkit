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

"""Docked/floating plot and protein-viewer session collect/restore."""

from __future__ import annotations

import json
import logging

from PyQt5.QtCore import QByteArray

from ..qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


class SessionPlotsMixin:
    def _close_live_protein_viewer(self) -> None:
        dlg = getattr(self, "_protein_viewer_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            self._protein_viewer_dialog = None
            return
        try:
            dlg._suppress_close_prompt = True
            close_struct = getattr(dlg, "close_structure", None)
            if callable(close_struct):
                close_struct(mark_dirty=False)
            dlg.hide()
            dlg.close()
        except RuntimeError:
            pass
        try:
            dlg.setParent(None)
        except RuntimeError:
            pass
        self._protein_viewer_dialog = None

    def _discard_protein_viewer(self) -> None:
        self._protein_viewer_session = None
        self._close_live_protein_viewer()

    def _restore_protein_viewer(self, payload: object) -> None:
        """Keep the snapshot only; the window is rebuilt when Protein → Viewer opens."""
        self._close_live_protein_viewer()
        if not isinstance(payload, dict) or not payload.get("structures"):
            self._protein_viewer_session = None
            return
        try:
            self._protein_viewer_session = json.loads(json.dumps(payload))
        except (TypeError, ValueError):
            logger.exception("Skipping Protein Viewer restore with invalid session state")
            self._protein_viewer_session = None

    def _restore_simulation(self, payload: object) -> None:
        """Keep a saved simulation document for the next time the workspace opens."""
        from ...sim.document import SimulationDocumentError, document_from_dict

        window = getattr(self, "_simulation_window", None)
        if not isinstance(payload, dict):
            self._simulation_session = None
            return
        try:
            document = document_from_dict(payload)
        except (SimulationDocumentError, TypeError, ValueError):
            self._simulation_session = None
            return
        self._simulation_session = payload
        if window is not None:
            window.document = document
            window._reload_stages()

    def _apply_committed_protein_viewer_session(self, dlg) -> None:
        payload = getattr(self, "_protein_viewer_session", None)
        if not isinstance(payload, dict) or not payload.get("structures"):
            return
        apply_state = getattr(dlg, "apply_session_state", None)
        if callable(apply_state):
            apply_state(payload)
        try:
            dlg._session_dirty = False
        except RuntimeError:
            pass

    def _collect_gnina_dock(self) -> dict | None:
        """Gnina paths and options from the open dialog, or the last closed snapshot."""
        from ..dialogs.gnina_dock import gnina_session_worth_saving

        dlg = getattr(self, "_smina_dock_dialog", None)
        state = None
        if dlg is not None and not qobject_is_deleted(dlg):
            collect = getattr(dlg, "gnina_session_state", None)
            if callable(collect):
                try:
                    state = collect()
                except RuntimeError:
                    state = None
        if not isinstance(state, dict):
            state = getattr(self, "_gnina_dock_session", None)
        if not gnina_session_worth_saving(state):
            return None
        try:
            return json.loads(json.dumps(state))
        except (TypeError, ValueError):
            logger.exception("Skipping Gnina session snapshot with non-JSON state")
            return None

    def _restore_gnina_dock(self, payload: object) -> None:
        """Keep the Gnina setup and refill an already-open dialog."""
        from ..dialogs.gnina_dock import gnina_session_worth_saving

        if not gnina_session_worth_saving(payload):
            self._gnina_dock_session = None
            return
        try:
            self._gnina_dock_session = json.loads(json.dumps(payload))
        except (TypeError, ValueError):
            logger.exception("Skipping Gnina restore with invalid session state")
            self._gnina_dock_session = None
            return
        dlg = getattr(self, "_smina_dock_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return
        apply_state = getattr(dlg, "apply_gnina_session", None)
        if callable(apply_state):
            apply_state(self._gnina_dock_session)

    def _collect_docked_plots(self) -> dict:
        """Docked plot widgets keyed by workspace pane (Plotter and analysis maps)."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return {"panes": [], "preferred_pane_id": None, "layout_id": None}
        panes_out: list[dict] = []
        for i, pane in enumerate(mgr.plot_panes()):
            plots: list[dict] = []
            for widget in pane.plot_widgets():
                collect = getattr(widget, "collect_session_state", None)
                if not callable(collect):
                    continue
                try:
                    state = collect()
                except Exception:
                    logger.exception("Skipping docked plot while collecting session state")
                    continue
                if not isinstance(state, dict):
                    continue
                try:
                    json.dumps(state)
                except (TypeError, ValueError):
                    logger.exception(
                        "Skipping docked plot with non-JSON-serializable session state"
                    )
                    continue
                kind = str(state.get("kind") or "plotter")
                entry: dict = {"kind": kind, "state": state}
                custom_title = getattr(widget, "_pane_display_title", None)
                if isinstance(custom_title, str) and custom_title.strip():
                    entry["display_title"] = custom_title.strip()
                plots.append(entry)
            if not plots:
                continue
            panes_out.append(
                {
                    "pane_id": pane.pane_id,
                    "pane_index": i,
                    "current": pane.page_index(),
                    "plots": plots,
                }
            )
        pref = mgr.preferred_pane()
        return {
            "panes": panes_out,
            "preferred_pane_id": pref.pane_id if pref is not None else None,
            "layout_id": mgr.session_layout_id(),
        }

    def _iter_floating_plot_hosts(self) -> list:
        """Floating plot/viewer/browser dialogs that can be session-serialized."""
        hosts: list = []
        seen: set[int] = set()

        def add(dlg) -> None:
            if dlg is None:
                return
            try:
                from PyQt5 import sip

                if sip.isdeleted(dlg):
                    return
            except Exception:
                pass
            key = id(dlg)
            if key in seen:
                return
            seen.add(key)
            hosts.append(dlg)

        for dlg in list(getattr(self, "_plot_dialogs", []) or []):
            add(dlg)
        for dlg in list(getattr(self, "_floating_result_dialogs", []) or []):
            add(dlg)
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_lipe_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_selection_browser_dialog",
            "_pose_browser_dialog",
            "_metabolite_browser_dialog",
            "_molecule_3d_viewer_dialog",
        ):
            add(getattr(self, attr, None))
        return hosts

    @staticmethod
    def _floating_plot_panel(dlg):
        for attr in ("_plot_widget", "_panel", "_viewer_widget"):
            panel = getattr(dlg, attr, None)
            if panel is not None:
                return panel
        return None

    def _collect_floating_plots(self) -> list[dict]:
        """Undocked plot windows to restore beside docked panes."""
        out: list[dict] = []
        for dlg in self._iter_floating_plot_hosts():
            panel = self._floating_plot_panel(dlg)
            if panel is None:
                continue
            try:
                if not dlg.isVisible() and (
                    (
                        getattr(panel, "DIMRED_SESSION_KIND", None) == "dimension_reduction"
                        and getattr(panel, "_last_result", None) is None
                    )
                    or (
                        getattr(panel, "MEDCHEM_SESSION_KIND", None) == "medchem_space"
                        and getattr(panel, "_plot_kind", None) == "lipe"
                        and getattr(panel, "_full_dataset", None) is None
                    )
                ):
                    continue
            except RuntimeError:
                continue
            collect = getattr(panel, "collect_session_state", None)
            if not callable(collect):
                continue
            try:
                state = collect()
            except Exception:
                logger.exception("Skipping floating plot while collecting session state")
                continue
            if not isinstance(state, dict):
                continue
            try:
                json.dumps(state)
            except (TypeError, ValueError):
                logger.exception("Skipping floating plot with non-JSON-serializable session state")
                continue
            kind = str(state.get("kind") or "plotter")
            entry: dict = {"kind": kind, "state": state}
            custom_title = getattr(panel, "_pane_display_title", None)
            if isinstance(custom_title, str) and custom_title.strip():
                entry["display_title"] = custom_title.strip()
            try:
                geo = dlg.saveGeometry()
                if geo is not None and not geo.isEmpty():
                    entry["geometry"] = bytes(geo.toBase64()).decode("ascii")
            except RuntimeError:
                pass
            try:
                title = str(dlg.windowTitle() or "").strip()
            except RuntimeError:
                title = ""
            if title:
                entry["window_title"] = title
            out.append(entry)
        return out

    def _discard_floating_plot_dialogs(self) -> None:
        """Close floating plot windows so a session restore starts clean."""
        for dlg in list(self._iter_floating_plot_hosts()):
            try:
                dlg._force_close = True
            except Exception:
                pass
            try:
                dlg.hide()
                dlg.close()
            except RuntimeError:
                pass
            try:
                dlg.setParent(None)
            except RuntimeError:
                pass
        self._plot_dialogs = []
        self._floating_result_dialogs = []
        for attr in (
            "_pca_dialog",
            "_tsne_dialog",
            "_umap_dialog",
            "_som_dialog",
            "_boiled_egg_dialog",
            "_golden_triangle_dialog",
            "_lipe_dialog",
            "_sali_map_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_selection_browser_dialog",
            "_pose_browser_dialog",
            "_metabolite_browser_dialog",
            "_molecule_3d_viewer_dialog",
        ):
            if getattr(self, attr, None) is not None:
                setattr(self, attr, None)

    def _discard_docked_plot_widgets(self) -> None:
        """Detach and delete docked plot widgets so a session restore starts clean."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        widgets = []
        for pane in mgr.plot_panes():
            widgets.extend(pane.plot_widgets())
            pane.set_plot_widgets([])
        for widget in widgets:
            try:
                widget.setParent(None)
                widget.deleteLater()
            except RuntimeError:
                pass

    def _restore_docked_plot_widget(self, spec: dict):
        from ..docked_plot_session import restore_docked_plot_widget

        return restore_docked_plot_widget(self, spec)

    def _workspace_layout_payload_from_session_doc(self, doc: object) -> dict | None:
        """Workspace splitter snapshot: top-level key, else copy inside table_layout."""
        if not isinstance(doc, dict):
            return None
        ws = doc.get("workspace_layout")
        embedded = None
        table_layout = doc.get("table_layout")
        if isinstance(table_layout, dict):
            maybe = table_layout.get("workspace")
            if isinstance(maybe, dict) and maybe:
                embedded = maybe
        if isinstance(ws, dict) and ws:
            if not ws.get("layout_id") and isinstance(embedded, dict) and embedded.get("layout_id"):
                merged = dict(ws)
                merged["layout_id"] = embedded["layout_id"]
                return merged
            return ws
        return embedded

    def _resolve_session_workspace_layout_id(
        self, docked_payload: object, panes_data: list
    ) -> str | None:
        """Pick the workspace layout id to use when restoring docked plots."""
        from .workspace_layout import (
            LAYOUT_PRESETS,
            LAYOUT_TABLE_SIDE,
            LAYOUT_TABLE_SINGLE,
        )

        known = {p[0] for p in LAYOUT_PRESETS}
        candidates: list[str] = []
        for source in (
            getattr(self, "_pending_session_workspace_layout", None),
            docked_payload if isinstance(docked_payload, dict) else None,
        ):
            if not isinstance(source, dict):
                continue
            lid = source.get("layout_id")
            if isinstance(lid, str) and lid in known and lid not in candidates:
                candidates.append(lid)

        # The saved workspace id is authoritative (split vs stacked vs table-only).
        if candidates:
            return candidates[0]

        max_idx = 0
        for spec in panes_data:
            if not isinstance(spec, dict):
                continue
            try:
                max_idx = max(max_idx, int(spec.get("pane_index", 0)))
            except (TypeError, ValueError):
                continue
        need_multi = max_idx > 0 or len(panes_data) > 1

        if not panes_data:
            return None
        if not need_multi:
            return LAYOUT_TABLE_SINGLE
        return LAYOUT_TABLE_SIDE

    def _restore_floating_plots(self, payload: object) -> None:
        """Re-open undocked plot windows from session state."""
        if not isinstance(payload, list) or not payload:
            return
        from ..dockable_plot import plot_widget_display_title

        for spec in payload:
            if not isinstance(spec, dict):
                continue
            widget = self._restore_docked_plot_widget(spec)
            if widget is None:
                continue
            factory = getattr(widget, "create_floating_dialog", None)
            if not callable(factory):
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
                continue
            try:
                dlg = factory(self)
            except Exception:
                logger.exception("Failed to recreate floating plot from session")
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
                continue
            prepare = getattr(self, "_prepare_tool_dialog", None)
            if callable(prepare):
                prepare(dlg)
            # Prefer plotter registration without importing PlotDialog (WebEngine).
            if (
                getattr(dlg, "_plot_widget", None) is not None
                and getattr(dlg, "_panel", None) is None
            ):
                self._register_plot_dialog(dlg)
            elif not self._bind_undocked_browser_dialog(dlg):
                self._register_floating_result_dialog(dlg)
            title = spec.get("display_title") or spec.get("window_title")
            if isinstance(title, str) and title.strip():
                try:
                    dlg.setWindowTitle(title.strip())
                except RuntimeError:
                    pass
            else:
                try:
                    dlg.setWindowTitle(plot_widget_display_title(widget))
                except RuntimeError:
                    pass
            geo = spec.get("geometry")
            if isinstance(geo, str) and geo:
                try:
                    raw = QByteArray.fromBase64(geo.encode("ascii"))
                    dlg.restoreGeometry(raw)
                except (RuntimeError, ValueError):
                    pass
            sync = getattr(widget, "_sync_footer_chrome", None)
            if callable(sync):
                sync()
            try:
                if getattr(self, "_session_hold_workspace_surfaces", False):
                    widget.hide()
                    dlg.hide()
                else:
                    widget.show()
                    dlg.show()
            except RuntimeError:
                pass

    def _restore_docked_plots(self, payload: object) -> None:
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        panes_data = payload.get("panes") if isinstance(payload, dict) else None
        if not isinstance(panes_data, list):
            panes_data = []
        saved_layout = self._resolve_session_workspace_layout_id(payload, panes_data)
        if panes_data:
            need_layout = False
            if not mgr.plot_panes():
                need_layout = True
            elif saved_layout and mgr.layout_id != saved_layout:
                need_layout = True
            elif saved_layout:
                # Enough panes for the highest saved pane index?
                max_idx = 0
                for spec in panes_data:
                    if not isinstance(spec, dict):
                        continue
                    try:
                        max_idx = max(max_idx, int(spec.get("pane_index", 0)))
                    except (TypeError, ValueError):
                        continue
                if max_idx >= len(mgr.plot_panes()):
                    need_layout = True
            if need_layout and saved_layout:
                mgr.apply_layout(saved_layout, preserve_plots=False)
        for pane in mgr.plot_panes():
            leftover = pane.plot_widgets()
            pane.set_plot_widgets([])
            for widget in leftover:
                try:
                    widget.setParent(None)
                    widget.deleteLater()
                except RuntimeError:
                    pass
        if not panes_data:
            return
        for spec in panes_data:
            if not isinstance(spec, dict):
                continue
            pane = None
            pane_id = spec.get("pane_id")
            if isinstance(pane_id, str) and pane_id:
                pane = mgr.find_pane(pane_id)
            if pane is None:
                try:
                    idx = int(spec.get("pane_index", 0))
                except (TypeError, ValueError):
                    idx = 0
                panes = mgr.plot_panes()
                if not panes:
                    continue
                pane = panes[max(0, min(idx, len(panes) - 1))]
            widgets = []
            for plot_spec in spec.get("plots") or []:
                if not isinstance(plot_spec, dict):
                    continue
                widget = self._restore_docked_plot_widget(plot_spec)
                if widget is None:
                    continue
                widgets.append(widget)
            if not widgets:
                continue
            for widget in widgets:
                wire = getattr(self, "_wire_docked_plot_widget", None)
                if callable(wire):
                    wire(widget)
            try:
                current = int(spec.get("current", 0))
            except (TypeError, ValueError):
                current = 0
            pane.set_plot_widgets(widgets, current=current)
        pref_id = payload.get("preferred_pane_id") if isinstance(payload, dict) else None
        if isinstance(pref_id, str) and pref_id:
            pref = mgr.find_pane(pref_id)
            if pref is not None:
                mgr.set_preferred_pane(pref)
        # Re-assert saved workspace layout in case docking hooks changed it.
        if saved_layout and mgr.layout_id != saved_layout:
            mgr.apply_layout(saved_layout, preserve_plots=True)
        show = getattr(self, "show_docked_plot_panel", None)
        if callable(show):
            show()
