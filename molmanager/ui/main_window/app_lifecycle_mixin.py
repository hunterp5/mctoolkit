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

"""Session dirty tracking, SQLite mirror, close/shutdown for ChemistryWorkspaceWindow."""

from __future__ import annotations

import logging
import time

from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import QApplication, QMainWindow, QMessageBox

from ..compound_table_model import CompoundTableModel
from ...platform_support.exception_policy import log_swallowed_exception

logger = logging.getLogger(__name__)


class AppLifecycleMixin:
    def _wire_table_plot_refresh(self) -> None:
        """Replot open Plotly views when table cells or rows change."""
        model = getattr(self, "_table_model", None)
        if model is None:
            return

        def _on_data_changed(top_left, bottom_right, roles=()) -> None:
            # Structure pixmap paints while scrolling must not replot (status bar / WebEngine).
            if CompoundTableModel.is_structure_paint_data_change(top_left, bottom_right, roles):
                return
            self._schedule_active_plots_replot()

        def _on_rows_changed(*_args) -> None:
            # Row delete/undo must refresh every open plot, including during a
            # background job. ``force`` matches filter apply: a dropped schedule
            # would leave deleted points on analysis maps.
            self._schedule_active_plots_replot(force=True)

        model.dataChanged.connect(_on_data_changed)
        model.rowsInserted.connect(_on_rows_changed)
        model.rowsRemoved.connect(_on_rows_changed)
        model.modelReset.connect(_on_rows_changed)

    def _wire_sqlite_store_dirty_tracking(self) -> None:
        model = getattr(self, "_table_model", None)
        if model is None:
            return
        mark = self._mark_sqlite_store_dirty

        def _on_data_changed(top_left, bottom_right, roles=()) -> None:
            if CompoundTableModel.is_structure_paint_data_change(top_left, bottom_right, roles):
                return
            mark()

        model.dataChanged.connect(_on_data_changed)
        model.rowsInserted.connect(lambda *_args: mark())
        model.rowsRemoved.connect(lambda *_args: mark())
        model.columnsInserted.connect(lambda *_args: mark())
        model.columnsRemoved.connect(lambda *_args: mark())
        model.modelReset.connect(lambda *_args: mark())
        model.layoutChanged.connect(lambda *_args: mark())

    def _mark_sqlite_store_dirty(self) -> None:
        if getattr(self, "_ingest_sqlite_paused_dirty", False):
            return
        if self._sqlite_store is None:
            self._mark_session_dirty()
            return
        self._sqlite_store_dirty = True
        if self._sqlite_rebuild_in_progress:
            self._sqlite_rebuild_stale = True
        self._mark_session_dirty()

    def _mark_session_dirty(self) -> None:
        """Record that the workspace differs from the last save or successful open."""
        if getattr(self, "_session_mutation_paused", False):
            return
        if getattr(self, "_ingest_sqlite_paused_dirty", False):
            return
        self._session_dirty = True

    def _clear_session_dirty(self) -> None:
        self._session_dirty = False

    def _session_has_unsaved_changes(self) -> bool:
        return bool(getattr(self, "_session_dirty", False))

    def _finish_session_clean_if_pending(self) -> None:
        """Clear dirty after a replace-open finishes revealing the table."""
        self._session_mutation_paused = False
        if getattr(self, "_pending_session_clean_on_ready", False):
            self._clear_session_dirty()
            self._pending_session_clean_on_ready = False

    def _ensure_sqlite_store_current(self) -> bool:
        """Return True when the SQLite mirror is ready for filter/search pushdown."""
        if self._sqlite_store is None:
            return False
        if not self._sqlite_store_dirty:
            return True
        if self._sqlite_rebuild_in_progress:
            return False
        schedule = getattr(self, "_schedule_sqlite_rebuild", None)
        if callable(schedule):
            schedule()
        return False

    def closeEvent(self, event: QCloseEvent) -> None:
        if getattr(self, "_dock_results_mode", False):
            if not getattr(self, "_dock_results_force_close", False):
                self.hide()
                event.ignore()
                return
            # MRO puts QMainWindow before this mixin; call it explicitly.
            QMainWindow.closeEvent(self, event)
            return
        # Skip modal prompt under pytest / headless teardown, or when nothing changed.
        if not getattr(self, "_suppress_exit_session_prompt", False):
            if not self._confirm_protein_viewer_before_quit():
                event.ignore()
                return
            if self._session_has_unsaved_changes():
                reply = QMessageBox.question(
                    self,
                    "Save Session",
                    "Save the current session before exiting?",
                    QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                    QMessageBox.Save,
                )
                if reply == QMessageBox.Cancel:
                    event.ignore()
                    return
                if reply == QMessageBox.Save:
                    save = getattr(self, "save_session_as", None)
                    if callable(save) and not save():
                        event.ignore()
                        return
                    wait = getattr(self, "_wait_session_save", None)
                    if callable(wait):
                        wait()
                    if not getattr(self, "_session_save_last_ok", True):
                        event.ignore()
                        return
        self._prepare_application_shutdown()
        QMainWindow.closeEvent(self, event)

    def _confirm_protein_viewer_before_quit(self) -> bool:
        """Ask to Save to Session if the Protein Viewer is still open with unsaved edits."""
        dlg = getattr(self, "_protein_viewer_dialog", None)
        if dlg is None:
            return True
        try:
            visible = dlg.isVisible()
        except RuntimeError:
            return True
        if not visible:
            try:
                dlg._suppress_close_prompt = True
            except RuntimeError:
                pass
            return True
        confirm = getattr(dlg, "confirm_close_or_save_to_session", None)
        if callable(confirm) and not confirm():
            return False
        try:
            dlg._suppress_close_prompt = True
        except RuntimeError:
            pass
        return True

    def _prepare_application_shutdown(self) -> None:
        """Stop timers, cancel background work, close modeless dialogs, drain thread pools."""
        t = getattr(self, "_apply_filters_timer", None)
        if t is not None:
            t.stop()
        mem_t = getattr(self, "_memory_status_timer", None)
        if mem_t is not None:
            mem_t.stop()

        self.background_activity.prepare_for_quit()

        pq = getattr(self, "process_queue", None)
        if pq is not None:
            # Must be first: kill process pools and cancel running/queued jobs so
            # long-running Uni-pKa/descriptor work does not keep the interpreter alive
            # after the window closes.
            try:
                pq.shutdown_for_exit()
            except Exception:
                log_swallowed_exception(
                    logger, "process_queue.shutdown_for_exit failed during quit"
                )

        for dlg in list(getattr(self, "_plot_dialogs", [])):
            try:
                dlg.close()
            except RuntimeError:
                pass
        self._plot_dialogs = []

        for attr in (
            "_processes_dialog",
            "_selection_browser_dialog",
            "_pose_browser_dialog",
            "_metabolite_browser_dialog",
            "_mmp_browser_dialog",
            "_mmp_ledger_dialog",
            "_activity_cliff_map_dialog",
            "_mmp_neighborhood_map_dialog",
            "_sali_map_dialog",
            "_sali_browser_dialog",
            "_sketcher_dialog",
            "_protein_viewer_dialog",
            "_protein_msa_dialog",
            "_calculator_dialog",
            "_data_analysis_dialog",
            "_cluster_dialog",
            "_external_db_dialog",
            "_pubchem_dialog",
            "_chembl_dialog",
            "_patent_query_dialog",
            "_smina_dock_dialog",
            "_pdbqt_generator_dialog",
            "_pdb_fixer_dialog",
        ):
            dlg = getattr(self, attr, None)
            if dlg is None:
                continue
            setattr(self, attr, None)
            try:
                dlg.destroyed.disconnect()
            except (TypeError, RuntimeError):
                pass
            if attr == "_protein_viewer_dialog":
                try:
                    dlg._suppress_close_prompt = True
                except RuntimeError:
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

        for dlg in list(getattr(self, "_floating_result_dialogs", [])):
            try:
                dlg.close()
            except RuntimeError:
                pass
        self._floating_result_dialogs = []

        from ..qt_widget_utils import qobject_is_deleted

        for win in list(getattr(self, "_dock_result_windows", [])):
            if qobject_is_deleted(win):
                continue
            try:
                win._dock_results_force_close = True
                win.close()
            except RuntimeError:
                pass
        self._dock_result_windows = []

        QApplication.processEvents()

        # Brief drain after cancel/kill; this should be near-instant on app close.
        shutdown_wait_ms = 750
        deadline = time.monotonic() + shutdown_wait_ms / 1000.0
        while time.monotonic() < deadline:
            QApplication.processEvents()
            if pq is None or (not pq.has_running_job() and not pq.snapshot().get("fast_running")):
                break
            time.sleep(0.05)

        tp = getattr(self, "threadpool", None)
        if tp is not None:
            clear = getattr(tp, "clear", None)
            if callable(clear):
                clear()

        rtp = getattr(self, "_render_threadpool", None)
        if rtp is not None:
            clear = getattr(rtp, "clear", None)
            if callable(clear):
                clear()

        # Avoid blocking on shutdown; cooperative cancel + pool termination should be enough.
        try:
            from ...chem.fingerprint_cache import clear as clear_fingerprint_cache

            clear_fingerprint_cache()
        except Exception:
            log_swallowed_exception(logger, "fingerprint_cache.clear failed during quit")
        try:
            from ...ionization.microstate_cache import clear as clear_microstate_cache

            clear_microstate_cache()
        except Exception:
            log_swallowed_exception(logger, "microstate_cache.clear failed during quit")
        store = getattr(self, "_sqlite_store", None)
        if store is not None:
            try:
                store.close()
            except Exception:
                log_swallowed_exception(logger, "sqlite_store.close failed during quit")
        ensembles = getattr(self, "_confs_blocks_sidecar", None)
        closer = getattr(ensembles, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                log_swallowed_exception(logger, "ensemble_store.close failed during quit")
        mols = getattr(self, "mols", None)
        closer = getattr(mols, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                log_swallowed_exception(logger, "mol_store.close failed during quit")
        model = getattr(self, "_table_model", None)
        png_store = getattr(model, "_structure_png_store", None) if model is not None else None
        closer = getattr(png_store, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                log_swallowed_exception(logger, "structure_png_store.close failed during quit")
        extra = getattr(model, "_extra_pixmaps", None) if model is not None else None
        closer = getattr(extra, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                log_swallowed_exception(logger, "extra_pixmap_store.close failed during quit")
