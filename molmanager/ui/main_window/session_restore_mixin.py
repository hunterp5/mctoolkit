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

"""CMS session async restore, finalize steps, and workspace reveal."""

from __future__ import annotations

import logging
import sys
import time

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtWidgets import QApplication

from ...chem.depiction_builder import scene_revision
from ...conformers.conformer_column_codec import deserialize_confs_sidecar
from ...ionization.microstate_cache import restore_ionization_sidecar
from ...services.chemistry_columns import is_legacy_som_map_header
from ...storage import ensure_confs_sidecar, ensure_mol_store, reset_mol_store
from ...storage.structure_render_store import StructureRenderStore
from ...table.open_messages import damaged_session_message, message_for_session_read_failure
from ...table.session_codec import parse_session_global_bounds
from ...table.session_v4 import SessionOpenResult
from ...workers.session_save import SessionOpenWorker
from ...workers.signals import SessionOpenSignals
from ..recent_paths import KIND_SESSION, remember_recent
from ..strings import LOADING_DETAIL_SESSION, TOOL_RENDER_2D, loaded_session_status
from ..threadpool_access import start_runnable_on_app_pool
from ..widgets import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard

logger = logging.getLogger(__name__)

# Cap how long Open waits on Plotly/WebEngine after Render 2D finishes.
_SESSION_PLOT_WAIT_S = 3.0


class SessionRestoreMixin:
    def _append_filter_widget(self, card, *, title: str | None = None) -> None:
        if title:
            card.set_filter_title(str(title))
        else:
            from ..filters.cards import next_default_filter_title

            card.set_filter_title(next_default_filter_title(self.filters, type(card)))
        card.changed.connect(self.apply_filters)
        card.removed.connect(lambda c=card: self.remove_filter(c))
        self.f_container.addWidget(card)
        self.filters.append(card)
        self._sync_filter_panel_scroll_content()

    def _show_session_loading_page(self) -> None:
        self._set_ingest_loading(True)
        self._set_workspace_stack_index(0)
        self._loading_detail.setText(LOADING_DETAIL_SESSION)
        self.status_label.setText("Loading session…")

    def _open_session_v4_file(self, path: str) -> None:
        """Read *path* on a worker thread; :meth:`_on_session_file_read` installs it.

        The current workspace is kept until the read succeeds.
        """
        self._show_session_loading_page()
        try:
            from ...workers.render2d_pool import warm_render2d_process_pool

            warm_render2d_process_pool()
        except Exception:
            logger.debug("render pool warm failed", exc_info=True)
        self._session_open_generation = int(getattr(self, "_session_open_generation", 0)) + 1
        self._session_parse_busy = True
        signals = SessionOpenSignals(self)
        worker = SessionOpenWorker(
            self._session_open_generation,
            path,
            signals,
            want_scene_revision=scene_revision(),
        )
        # Pytest has no lasting event-loop turn for threadpool completions; read inline.
        if "pytest" in sys.modules:
            signals.finished.connect(self._on_session_file_read, type=Qt.DirectConnection)
            signals.failed.connect(self._on_session_file_read_failed, type=Qt.DirectConnection)
            worker.run()
            self._drain_pending_session_load()
            return
        signals.finished.connect(self._on_session_file_read, type=Qt.QueuedConnection)
        signals.failed.connect(self._on_session_file_read_failed, type=Qt.QueuedConnection)
        start_runnable_on_app_pool(self, worker)

    def _on_session_file_read_failed(self, generation: int, message: str) -> None:
        if generation != getattr(self, "_session_open_generation", 0):
            return
        self._session_parse_busy = False
        path = str(getattr(self, "_session_source_path", None) or "")
        logger.warning("Session read failed for %s: %s", path, message)
        self._finish_failed_open()
        self._warn_could_not_open(
            "Open Session", message_for_session_read_failure(path, ValueError(message))
        )

    def _on_session_file_read(self, generation: int, result: object) -> None:
        if not isinstance(result, SessionOpenResult):
            return
        if generation != getattr(self, "_session_open_generation", 0):
            result.discard_temp_files()
            return
        self._session_parse_busy = False
        try:
            self._install_opened_session(result)
        except Exception:
            result.discard_temp_files()
            logger.exception("Open session: install failed")
            self._on_session_open_failed()
            return
        remember_recent(KIND_SESSION, str(self._session_source_path or ""))

    def _install_opened_session(self, result: SessionOpenResult) -> None:
        """Swap the read rows and store files into the workspace, then run finalize."""
        doc = result.manifest
        gen = self._prepare_session_surface(doc)
        try:
            self.table.setUpdatesEnabled(False)
        except Exception:
            pass
        if result.mol_db is not None:
            ensure_mol_store(self).adopt_file(result.mol_db)
            result.temp_files.remove(result.mol_db)
        if result.ensembles_db is not None:
            ensure_confs_sidecar(self).adopt_file(result.ensembles_db)
            result.temp_files.remove(result.ensembles_db)
        self._table_model.install_rows(result.rows)
        if result.render_db is not None:
            store = StructureRenderStore()
            store.adopt_file(result.render_db)
            result.temp_files.remove(result.render_db)
            self._table_model.set_structure_png_store(store)
        n = result.rows.n
        self._loading_detail.setText(
            f"Session loaded ({n:,} row(s)).\nRestoring filters and workspace…"
        )
        self._begin_session_finalize(doc, result.max_oid, gen=gen)

    def _prepare_session_surface(self, doc: dict) -> int:
        """Clear the workspace and install session headers. Returns the load generation."""
        self._session_mutation_paused = True
        self._pending_session_clean_on_ready = True
        self._session_finalize_ctx = None
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._session_plot_wait_deadline = None
        self._session_structure_cache_hit = False
        self._discard_floating_plot_dialogs()
        # Keep the loading page up through clear_all → row install (avoid workspace flash).
        self._show_session_loading_page()
        self.clear_all()
        self._session_hold_workspace_surfaces = True
        # clear_all() bumps the load generation; capture after that so callbacks match.
        self._session_load_generation = int(getattr(self, "_session_load_generation", 0)) + 1
        gen = self._session_load_generation
        self._show_session_loading_page()
        headers = doc.get("headers") or ["ID_HIDDEN", "Structure", "SMILES"]
        if len(headers) < 2 or headers[0] != "ID_HIDDEN" or headers[1] != "Structure":
            raise ValueError("Invalid session headers.")
        self.headers = list(headers)
        # Per-row zoom was a double-click. Depiction size is the shared cell size now.
        self.zoomed_ids = set()
        self.table.setSortingEnabled(False)
        self._table_model.clear_rows()
        self._table_model.set_headers(list(self.headers))
        layout_early = doc.get("table_layout")
        if isinstance(layout_early, dict):
            pix_cols = layout_early.get("pixmap_columns")
            if isinstance(pix_cols, list):
                for name in pix_cols:
                    if (
                        isinstance(name, str)
                        and name in self.headers
                        and name not in ("ID_HIDDEN", "Structure")
                        and not is_legacy_som_map_header(name)
                    ):
                        self._table_model.register_pixmap_column(name)
        self.table.setColumnHidden(0, True)
        reset_mol_store(self)
        self._clear_filter_target_smiles_cache()
        self.global_bounds = {}
        return gen

    def _drain_pending_session_load(self, *, timeout_s: float = 60.0) -> None:
        """Process Qt events until session read/install/finalize complete."""
        deadline = time.monotonic() + float(timeout_s)
        while time.monotonic() < deadline:
            busy = bool(getattr(self, "_session_parse_busy", False))
            busy = busy or getattr(self, "_session_finalize_ctx", None) is not None
            busy = busy or bool(getattr(self, "_session_awaiting_ready", False))
            busy = busy or bool(getattr(self, "_session_waiting_for_render", False))
            if not busy:
                return
            QApplication.processEvents()
            time.sleep(0.001)
        raise TimeoutError("Timed out waiting for session restore to finish.")

    def _on_session_open_failed(self) -> None:
        """Leave the loading page after the workspace was cleared for a session that failed."""
        self._session_parse_busy = False
        self._session_finalize_ctx = None
        self._session_awaiting_ready = False
        self._session_waiting_for_render = False
        self._session_hold_workspace_surfaces = False
        self._show_session_workspace_when_ready()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass
        self._finish_failed_open()
        path = str(getattr(self, "_session_source_path", None) or "")
        self._warn_could_not_open("Open Session", damaged_session_message(path))

    def _begin_session_finalize(self, doc: dict, max_id: int, *, gen: int) -> None:
        self._session_finalize_ctx = {
            "gen": int(gen),
            "doc": doc,
            "max_id": int(max_id),
            "step": 0,
        }
        QTimer.singleShot(0, self._session_finalize_step)

    def _session_finalize_step(self) -> None:
        ctx = getattr(self, "_session_finalize_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            return
        doc = ctx["doc"]
        max_id = int(ctx["max_id"])
        step = int(ctx["step"])
        try:
            if step == 0:
                self._loading_detail.setText("Preparing filters…")
                want_next = int(doc.get("next_oid", max_id + 1))
                self.next_oid = want_next if want_next > max_id else max_id + 1
                saved_bounds = parse_session_global_bounds(doc.get("global_bounds"))
                if saved_bounds:
                    list_fn = getattr(self._table_model, "list_bounds_data_headers", None)
                    if callable(list_fn):
                        allowed = set(list_fn())
                        saved_bounds = {
                            key: meta for key, meta in saved_bounds.items() if key in allowed
                        }
                if saved_bounds:
                    install = getattr(self._table_model, "install_numeric_bounds_cache", None)
                    if callable(install):
                        install(saved_bounds)
                    self.global_bounds = dict(saved_bounds)
                    refresh = getattr(self, "_refresh_bounds_on_filter_cards", None)
                    if callable(refresh):
                        refresh()
                    self._session_finalize_after_bounds()
                    return
                self.calculate_global_bounds(
                    on_complete=lambda: self._session_finalize_after_bounds()
                )
                return
            if step == 1:
                self._loading_detail.setText("Applying sort, colors, and filters…")
                self._finalize_session_table_chrome(doc)
                # Start 2D under the overlay so it overlaps plot restore.
                self._start_session_auto_render2d()
                ctx["step"] = 2
                QTimer.singleShot(0, self._session_finalize_step)
                return
            if step == 2:
                if not getattr(self, "_session_waiting_for_render", False):
                    self._loading_detail.setText("Restoring workspace and plots…")
                self._finalize_session_workspace_and_plots(doc)
                ctx["step"] = 3
                QTimer.singleShot(0, self._session_finalize_step)
                return
            # step 3 — sidecars + reveal
            if not getattr(self, "_session_waiting_for_render", False):
                self._loading_detail.setText("Restoring tool data…")
            self._finalize_session_sidecars_and_reveal(doc)
            self._session_finalize_ctx = None
        except Exception:
            self._session_finalize_ctx = None
            self._session_awaiting_ready = False
            self._session_waiting_for_render = False
            self._session_hold_workspace_surfaces = False
            self._show_session_workspace_when_ready()
            try:
                self.table.setUpdatesEnabled(True)
            except Exception:
                pass
            self._set_ingest_loading(False)
            self._session_mutation_paused = False
            self._pending_session_clean_on_ready = False
            self._set_workspace_stack_index(1)
            raise

    def _session_finalize_after_bounds(self) -> None:
        """Continue finalize after filter bounds are ready (keeps overlay until table is usable)."""
        ctx = getattr(self, "_session_finalize_ctx", None)
        if not ctx or ctx.get("gen") != getattr(self, "_session_load_generation", 0):
            return
        if int(ctx.get("step", -1)) != 0:
            return
        doc = ctx["doc"]
        max_id = int(ctx["max_id"])
        self._loading_detail.setText("Restoring filters…")
        self._finalize_session_filters(doc, max_id)
        ctx["step"] = 1
        QTimer.singleShot(0, self._session_finalize_step)

    def _finalize_session_filters(self, doc: dict, max_id: int) -> None:
        # next_oid is set before bounds complete in ``_session_finalize_step``.
        _ = max_id
        for spec in doc.get("filters") or []:
            kind = spec.get("kind")
            if kind == "substructure":
                sources = ["Structure"]
                get_srcs = getattr(self, "chemistry_tool_structure_sources", None)
                if callable(get_srcs):
                    sources = get_srcs() or sources
                c = SubstructureFilterCard(structure_sources=sources)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                c.set_smarts(str(spec.get("smarts", "") or ""))
                c.set_structure_source(
                    str(spec.get("structure_source", "Structure") or "Structure")
                )
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "range":
                props = list(self.global_bounds.keys()) or ["SMILES"]
                c = FilterCard(props, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                p = str(spec.get("property", "") or "")
                if p:
                    try:
                        c.restore_state(p, float(spec.get("min", 0)), float(spec.get("max", 0)))
                    except Exception:
                        pass
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "text":
                cols = self._filterable_data_column_names()
                if not cols:
                    cols = list(self.global_bounds.keys()) or ["SMILES"]
                c = TextFilterCard(cols, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                c.restore_from_session(
                    str(spec.get("property", "") or ""),
                    str(spec.get("text", "") or ""),
                    case_sensitive=bool(spec.get("case_sensitive", False)),
                    partial_match=bool(spec.get("partial_match", True)),
                )
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
            elif kind == "category":
                cols = self._filterable_data_column_names()
                if not cols:
                    cols = list(self.global_bounds.keys()) or ["SMILES"]
                c = CategoryFilterCard(cols, self)
                self._append_filter_widget(c, title=str(spec.get("title") or "") or None)
                vals = spec.get("values")
                if not isinstance(vals, list):
                    vals = []
                c.restore_from_session(str(spec.get("property", "") or ""), vals)
                c.restore_filter_flags(
                    bool(spec.get("enabled", True)), bool(spec.get("inverted", False))
                )
        self.f_panel.setVisible(bool(doc.get("filter_panel_visible", False)))

    def _finalize_session_workspace_and_plots(self, doc: dict) -> None:
        self._discard_docked_plot_widgets()
        ws = self._workspace_layout_payload_from_session_doc(doc)
        self._pending_session_workspace_layout = ws if isinstance(ws, dict) else None
        self._pending_session_column_order = (
            doc.get("column_logical_order")
            if isinstance(doc.get("column_logical_order"), list)
            else None
        )
        mgr = getattr(self, "_workspace_layout", None)
        docked_payload = doc.get("docked_plots")
        panes_data = docked_payload.get("panes") if isinstance(docked_payload, dict) else None
        if not isinstance(panes_data, list):
            panes_data = []
        saved_layout = self._resolve_session_workspace_layout_id(docked_payload, panes_data)
        if mgr is not None and saved_layout:
            if mgr.layout_id != saved_layout:
                mgr.apply_layout(saved_layout, preserve_plots=False)
            if isinstance(ws, dict):
                mgr.restore_splitter_sizes(ws)
        elif mgr is not None and isinstance(ws, dict):
            layout_id = ws.get("layout_id")
            if isinstance(layout_id, str) and layout_id:
                mgr.apply_layout(layout_id, preserve_plots=False)
            mgr.restore_splitter_sizes(ws)
        elif getattr(self, "_workspace_layout", None) is not None:
            saved_w = doc.get("plot_panel_width")
            if isinstance(saved_w, (int, float)) and saved_w > 0:
                ensure = getattr(self, "_ensure_plot_panel_width", None)
                if callable(ensure):
                    QTimer.singleShot(0, lambda: ensure(int(saved_w)))
        self._restore_docked_plots(docked_payload)
        # Re-assert the saved layout id after docking so leftover stacked/side panes cannot stick.
        if mgr is not None and saved_layout and mgr.layout_id != saved_layout:
            mgr.apply_layout(saved_layout, preserve_plots=True)
            if isinstance(ws, dict):
                mgr.restore_splitter_sizes(ws)
        self._restore_floating_plots(doc.get("floating_plots"))
        self._restore_protein_viewer(doc.get("protein_viewer"))
        self._restore_gnina_dock(doc.get("gnina_dock"))
        self._restore_simulation(doc.get("simulation"))
        self._hide_session_workspace_until_ready()
        self._restore_pending_workspace_layout()
        co = self._pending_session_column_order
        if isinstance(co, list):
            self._restore_column_visual_order([int(x) for x in co])

    def _finalize_session_table_chrome(self, doc: dict) -> None:
        sc = doc.get("sort_column")
        self.table.setSortingEnabled(False)
        if sc is not None and isinstance(sc, int) and 0 <= sc < self._table_model.columnCount():
            asc = bool(doc.get("sort_ascending", True))
            mode = doc.get("sort_mode") or "auto"
            if mode not in ("auto", "numeric", "alphabetic"):
                mode = "auto"
            self._table_model.sort(
                sc, Qt.AscendingOrder if asc else Qt.DescendingOrder, sort_kind=mode
            )
            self._session_sort = {"column": sc, "ascending": asc, "mode": mode}
        else:
            self._session_sort = None
        col_colors = doc.get("column_colors")
        if isinstance(col_colors, dict):
            self._table_model.restore_column_color_rules(col_colors)
        log_cols = doc.get("logarithmic_columns") or []
        self._logarithmic_columns = {
            str(h) for h in log_cols if isinstance(h, str) and h in self.headers
        }
        self.apply_filters()
        rows_n = self._table_model.rowCount()
        self.status_label.setText(loaded_session_status(rows_n))
        if getattr(self, "_sqlite_store", None) is not None:
            self._sqlite_store_dirty = True

    def _finalize_session_sidecars_and_reveal(self, doc: dict) -> None:
        side = deserialize_confs_sidecar(doc.get("confs_sidecar"))
        if side:
            ensure_confs_sidecar(self).update(side)
        depiction = getattr(self, "_depiction_coords", None)
        if depiction is not None:
            depiction.load_session(doc.get("depiction_2d"))
        restore_ionization_sidecar(doc.get("ionization_sidecar"))
        from ...analysis.mmp_session import restore_mmp_ledger_for_session

        restore_mmp_ledger_for_session(self, doc.get("mmp_ledger"))
        from ..metabolite_browser import restore_metabolite_browse_for_session

        restore_metabolite_browse_for_session(self, doc.get("metabolite_browse"))
        from ...docking.pose_file_io import restore_dock_results_for_session

        restore_dock_results_for_session(self, doc.get("dock_results"))
        restorer = getattr(self, "restore_pose_column_contexts", None)
        if callable(restorer):
            restorer(doc.get("pose_column_contexts"))
        self._pending_session_table_layout = doc.get("table_layout")
        self._restore_table_layout(self._pending_session_table_layout)
        restore_search = getattr(self, "restore_table_search_session", None)
        if callable(restore_search):
            restore_search(doc.get("table_search"))
        restore_replace = getattr(self, "restore_find_replace_session", None)
        if callable(restore_replace):
            restore_replace(doc.get("table_find_replace"))
        restore_lists = getattr(self, "restore_row_lists_session", None)
        if callable(restore_lists):
            restore_lists(doc.get("row_lists"))
        restore_notepad = getattr(self, "restore_notepad_session", None)
        if callable(restore_notepad):
            restore_notepad(doc.get("notepad"))
        self._session_awaiting_ready = True
        self._session_plot_wait_deadline = None
        self._hide_session_workspace_until_ready()
        self._deferred_session_post_load_follow_up()

    def _reveal_table_after_session_prep(self) -> None:
        """Leave the loading overlay once session rows, 2D, filters, and plots are ready."""
        sync_numbers = getattr(self.table, "sync_row_number_column_width", None)
        if callable(sync_numbers):
            sync_numbers()
        self._set_ingest_loading(False)
        self._set_workspace_stack_index(1)
        finish_clean = getattr(self, "_finish_session_clean_if_pending", None)
        if callable(finish_clean):
            finish_clean()
        try:
            self.table.setUpdatesEnabled(True)
        except Exception:
            pass

    def _start_session_auto_render2d(self) -> None:
        """Start auto Render 2D under the overlay; saved scenes for every row skip the wait."""
        if self._session_scenes_cover_table():
            self._session_waiting_for_render = False
            return
        render = getattr(self, "_try_auto_render_all_structures_after_ingest", None)
        # Set the wait flag first so a synchronous batch-finished callback cannot
        # race past a later True assignment and leave Open hanging.
        self._session_waiting_for_render = True
        n = int(self._table_model.rowCount()) if getattr(self, "_table_model", None) else 0
        detail = getattr(self, "_loading_detail", None)
        if detail is not None and n > 0:
            try:
                detail.setText(f"{TOOL_RENDER_2D}…\n0 / {n:,}")
            except RuntimeError:
                pass
        started = bool(callable(render) and render())
        if not started:
            self._session_waiting_for_render = False

    def _session_scenes_cover_table(self) -> bool:
        """True when the session file supplied a scene for every structure row.

        Saved scenes come from the current builder (the read drops older revisions) and do
        not depend on the cell size. Rows still without a scene are drawn by auto-render.
        """
        store = getattr(self._table_model, "_structure_png_store", None)
        n = len(store) if store is not None else 0
        if n <= 0 or self._structure_oids_without_scene():
            return False
        self._session_structure_cache_hit = True
        self._apply_scene_zoom_overrides()
        refresh = getattr(self, "_refresh_visible_structure_cells", None)
        if callable(refresh):
            refresh()
        self.status_label.setText(f"Loaded {n:,} saved depiction(s).")
        return True

    def _hide_session_workspace_until_ready(self) -> None:
        """Keep independent floating plot windows hidden until the workspace overlay lifts."""
        if not getattr(self, "_session_hold_workspace_surfaces", False):
            return
        for dlg in self._iter_floating_plot_hosts():
            try:
                dlg.hide()
            except RuntimeError:
                pass

    def _show_session_workspace_when_ready(self) -> None:
        """Show restored floating plots, Search, and Find and Replace with the workspace."""
        self._session_hold_workspace_surfaces = False
        for dlg in self._iter_floating_plot_hosts():
            try:
                dlg.show()
            except RuntimeError:
                pass
        panel = getattr(self, "_search_panel", None)
        if panel is not None and getattr(self, "_session_search_want_visible", False):
            try:
                panel.setVisible(True)
                populate = getattr(self, "_populate_table_search_columns_combo", None)
                if callable(populate):
                    populate()
            except RuntimeError:
                pass
        self._session_search_want_visible = False
        replace_panel = getattr(self, "_find_replace_panel", None)
        want_replace = bool(getattr(self, "_session_find_replace_want_visible", False))
        if replace_panel is not None and want_replace:
            try:
                replace_panel.setVisible(True)
                populate_replace = getattr(self, "_populate_find_replace_columns", None)
                if callable(populate_replace):
                    populate_replace()
            except RuntimeError:
                pass
        self._session_find_replace_want_visible = False

    def _session_plot_host_waiting_for_web(self, host) -> bool:
        """True when a restored plot has a WebEngine view that has not finished loading."""
        stack = [host]
        seen: set[int] = set()
        while stack:
            widget = stack.pop()
            if widget is None:
                continue
            key = id(widget)
            if key in seen:
                continue
            seen.add(key)
            web = getattr(widget, "web", None)
            if web is not None:
                if hasattr(widget, "_web_ready") and not bool(getattr(widget, "_web_ready", False)):
                    return True
            for attr in ("_plot_widget", "_panel", "_viewer_widget", "_view"):
                child = getattr(widget, attr, None)
                if child is not None:
                    stack.append(child)
        return False

    def _set_session_plot_wait_progress(self) -> None:
        """Phase label only: Plotly/WebEngine do not expose a real draw percent."""
        detail = getattr(self, "_loading_detail", None)
        if detail is None:
            return
        try:
            detail.setText("Preparing plots…")
        except RuntimeError:
            pass

    def _session_plots_ready_for_reveal(self) -> bool:
        """True when restored Plotly views are ready, or the wait deadline has passed."""
        hosts_fn = getattr(self, "_iter_active_plot_hosts", None)
        hosts = list(hosts_fn()) if callable(hosts_fn) else []
        waiting = any(self._session_plot_host_waiting_for_web(host) for host in hosts)
        if not waiting:
            return True
        now = time.monotonic()
        deadline = getattr(self, "_session_plot_wait_deadline", None)
        if deadline is None:
            self._session_plot_wait_deadline = now + _SESSION_PLOT_WAIT_S
            return False
        return now >= float(deadline)

    def _session_on_render2d_batch_finished(self) -> None:
        """Continue session reveal after auto Render 2D (or cancel) completes."""
        if getattr(self, "_session_waiting_for_render", False):
            self._session_waiting_for_render = False
        if not getattr(self, "_session_awaiting_ready", False):
            return
        self._set_session_plot_wait_progress()
        QTimer.singleShot(0, self._session_try_reveal_when_ready)

    def _session_try_reveal_when_ready(self) -> None:
        """Show the workspace after rows, 2D, and restored plots are ready."""
        if not getattr(self, "_session_awaiting_ready", False):
            return
        if getattr(self, "_session_waiting_for_render", False):
            return
        if not self._session_plots_ready_for_reveal():
            self._set_session_plot_wait_progress()
            QTimer.singleShot(50, self._session_try_reveal_when_ready)
            return
        self._session_awaiting_ready = False
        self._session_plot_wait_deadline = None
        self._show_session_workspace_when_ready()
        self._restore_pending_workspace_layout()
        self._reveal_table_after_session_prep()
        rerun = getattr(self, "_rerun_restored_table_search", None)
        if callable(rerun):
            rerun()
        finish = getattr(self, "_finish_deferred_session_workspace_restore", None)
        if callable(finish):
            QTimer.singleShot(0, finish)
        n = self._table_model.rowCount()
        cur = self.status_label.text() or ""
        if TOOL_RENDER_2D in cur or "auto 2D render skipped" in cur:
            return
        self.status_label.setText(loaded_session_status(n) if n else "Ready.")

    def _deferred_session_post_load_follow_up(self) -> None:
        """Migrate packed ensembles, restore chrome, then reveal when 2D and plots are ready."""
        migrate = getattr(self, "_migrate_legacy_confs_cells_to_sidecar", None)
        if callable(migrate):
            migrate()
        pending = getattr(self, "_pending_session_table_layout", None)
        self._restore_pending_workspace_layout()
        self._restore_session_table_chrome(pending)
        self._session_try_reveal_when_ready()
