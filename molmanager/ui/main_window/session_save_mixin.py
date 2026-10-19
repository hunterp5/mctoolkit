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

"""Session save / document build / File open-save entry points."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable

from PyQt5.QtWidgets import QApplication, QFileDialog, QMessageBox

from ...conformers.conformer_column_codec import serialize_confs_sidecar
from ...ionization.microstate_cache import serialize_ionization_sidecar
from ...services.filter_config import cfg_column
from ...table.open_messages import (
    damaged_session_message,
    message_for_session_read_failure,
    not_a_session_message,
    preflight_open_path,
)
from ...table.session_codec import (
    compact_global_bounds,
    dumps_session_document,
    expand_session_document,
    loads_session_bytes,
    session_format_ok,
    session_version_ok,
)
from ...table.session_document_build import assemble_session_document
from ...chem.molecule_conversion import mol_to_canonical_smiles
from ...workers.session_save import SessionSaveWorker
from ..background_jobs import register_background_job, unregister_background_job
from ..threadpool_access import start_runnable_on_app_pool
from ..widgets import CategoryFilterCard, FilterCard, SubstructureFilterCard, TextFilterCard

logger = logging.getLogger(__name__)


class SessionSaveMixin:
    def _session_format_ok(self, fmt: object) -> bool:
        return session_format_ok(fmt)

    def _session_version_ok(self, version: object) -> bool:
        return session_version_ok(version)

    def new_session(self) -> None:
        """Launch a new MolManager instance with nothing loaded."""
        try:
            subprocess.Popen([sys.executable, "-m", "molmanager"], close_fds=True)
        except Exception as e:
            QMessageBox.warning(self, "New Session", str(e))

    def close_session(self) -> None:
        """Discard the current session and return to the empty start screen."""
        if not self._confirm_close_session():
            return
        self._reset_to_idle_session()

    def _confirm_close_session(self) -> bool:
        """Ask before discarding unsaved work. Headless tests skip the prompt."""
        if getattr(self, "_suppress_exit_session_prompt", False):
            return True
        if not self._session_has_workspace_content():
            return True
        confirm_protein = getattr(self, "_confirm_protein_viewer_before_quit", None)
        if callable(confirm_protein) and not confirm_protein():
            return False
        if self._session_has_unsaved_changes():
            reply = QMessageBox.question(
                self,
                "Close Session",
                "Save the current session before closing?",
                QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
                QMessageBox.Save,
            )
            if reply == QMessageBox.Cancel:
                return False
            if reply == QMessageBox.Save:
                save = getattr(self, "save_session_as", None)
                if not callable(save) or not save():
                    return False
                wait = getattr(self, "_wait_session_save", None)
                if callable(wait):
                    wait()
                if not getattr(self, "_session_save_last_ok", True):
                    return False
            return True
        reply = QMessageBox.question(
            self,
            "Close Session",
            "Close the current session and return to the start screen?\n\n"
            "The table, filters, plots, lists, notepad, and Protein Viewer "
            "for this session will be cleared.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        return reply == QMessageBox.Yes

    def _session_has_workspace_content(self) -> bool:
        """True when this window holds data that Close Session would discard."""
        model = getattr(self, "_table_model", None)
        if model is not None and model.rowCount() > 0:
            return True
        if getattr(self, "filters", None):
            return True
        if getattr(self, "_session_source_path", None):
            return True
        has_unsaved = getattr(self, "_session_has_unsaved_changes", None)
        if callable(has_unsaved) and has_unsaved():
            return True
        if getattr(self, "_protein_viewer_session", None):
            return True
        dlg = getattr(self, "_protein_viewer_dialog", None)
        if dlg is not None:
            try:
                if dlg.isVisible():
                    return True
            except RuntimeError:
                pass
        if getattr(self, "_plot_dialogs", None) or getattr(self, "_floating_result_dialogs", None):
            return True
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is not None:
            for pane in mgr.plot_panes():
                if pane.plot_widgets():
                    return True
        collect_notepad = getattr(self, "collect_notepad_session", None)
        if callable(collect_notepad) and collect_notepad():
            return True
        store_fn = getattr(self, "_row_list_store", None)
        if callable(store_fn) and store_fn().names():
            return True
        if getattr(self, "_last_dock_results", None):
            return True
        if getattr(self, "_mmp_last_pairs", None):
            return True
        if getattr(self, "_som_browse_records", None):
            return True
        return False

    def _reset_to_idle_session(self) -> None:
        """Drop session state and cover the workspace with the start screen."""
        from ...analysis.mmp_session import restore_mmp_ledger_for_session

        self._session_mutation_paused = True
        try:
            self._cancel_in_flight_session_work()
            discard_plots = getattr(self, "_discard_floating_plot_dialogs", None)
            if callable(discard_plots):
                discard_plots()
            discard_protein = getattr(self, "_discard_protein_viewer", None)
            if callable(discard_protein):
                discard_protein()
            self.clear_all()
            if callable(discard_plots):
                discard_plots()
            restore_mmp_ledger_for_session(self, None)
            self._session_source_path = None
            panel = getattr(self, "f_panel", None)
            if panel is not None:
                panel.setVisible(False)
            show_idle = getattr(self, "_show_idle_workspace", None)
            if callable(show_idle):
                show_idle()
        finally:
            self._session_mutation_paused = False
            self._pending_session_clean_on_ready = False
        clear_dirty = getattr(self, "_clear_session_dirty", None)
        if callable(clear_dirty):
            clear_dirty()
        self._sqlite_store_dirty = False
        label = getattr(self, "status_label", None)
        if label is not None:
            label.setText("Ready.")

    def _cancel_in_flight_session_work(self) -> None:
        """Stop jobs that would write back into a session that is closing."""
        reject = getattr(self, "_reject_file_ingest_results", None)
        if callable(reject):
            reject()
        self._sql_load_generation = int(getattr(self, "_sql_load_generation", 0)) + 1
        cancel_sql = getattr(self, "_sql_load_cancel_event", None)
        if cancel_sql is not None:
            cancel_sql.set()
        invalidate = getattr(self, "_invalidate_substructure_async_jobs", None)
        if callable(invalidate):
            invalidate()
        for name in ("cancel_render_2d_batch", "cancel_gnina_dock"):
            cancel_tool = getattr(self, name, None)
            if callable(cancel_tool):
                cancel_tool()
        from ..background_jobs import cancel_background_job

        for job_id in list((getattr(self, "_background_job_cancels", None) or {}).keys()):
            cancel_background_job(self, job_id)
        queue = getattr(self, "process_queue", None)
        if queue is None:
            return
        queue.clear_queued()
        queue.cancel_running()
        for job_id in list(getattr(queue, "_fast_running", {}) or {}):
            queue.cancel_fast_job(job_id)

    def duplicate_session(self) -> None:
        """Launch a new MolManager instance with the current table state."""
        try:
            path = self._session_bundle_temp_path()
            snapshot = self._snapshot_session_save_inputs()
        except Exception as e:
            QMessageBox.warning(self, "Duplicate Session", str(e))
            return
        self._enqueue_session_save(
            path,
            snapshot,
            clear_dirty=False,
            status_prefix="Session duplicated to",
            dialog_title="Duplicate Session",
            on_success=lambda p=path: self._launch_duplicate_session(p),
        )

    def _launch_duplicate_session(self, path: str) -> None:
        subprocess.Popen(
            [sys.executable, "-m", "molmanager", "--load-session", path], close_fds=True
        )

    def _write_session_csv(self) -> str:
        """Serialize current table to a session CSV (includes all columns except Structure image)."""
        if not self.headers or self._table_model.rowCount() == 0:
            # Still create an empty session file.
            heads = ["SMILES"]
        else:
            # Ensure SMILES is first for readability.
            heads = [h for h in self.headers if h not in ("ID_HIDDEN", "Structure")]
            if "SMILES" in heads:
                heads.remove("SMILES")
                heads.insert(0, "SMILES")
            else:
                heads.insert(0, "SMILES")

        session_dir = os.path.join(tempfile.gettempdir(), "MolManagerSessions")
        os.makedirs(session_dir, exist_ok=True)
        fname = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.csv"
        out_path = os.path.join(session_dir, fname)

        import csv

        with open(out_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=heads)
            w.writeheader()
            for r in range(self._table_model.rowCount()):
                row: dict[str, str] = {}
                # Prefer existing SMILES cell; fall back to RDKit mol if present.
                smi = ""
                if "SMILES" in self.headers:
                    smi = self._table_cell_text(r, self.headers.index("SMILES"))
                if not smi:
                    idr = self._table_model.cell_text(r, 0)
                    if idr.isdigit():
                        mol = self._mol_for_structure_row(r)
                        if mol is not None:
                            smi = mol_to_canonical_smiles(mol)
                row["SMILES"] = smi

                for h in heads:
                    if h == "SMILES":
                        continue
                    if h in self.headers:
                        row[h] = self._export_cell_text(r, self.headers.index(h))
                    else:
                        row[h] = ""
                w.writerow(row)

        return out_path

    def _session_bundle_temp_path(self) -> str:
        """Return a new ``.cms`` path under the temp session directory (does not write)."""
        session_dir = os.path.join(tempfile.gettempdir(), "MolManagerSessions")
        os.makedirs(session_dir, exist_ok=True)
        fname = f"session_{time.strftime('%Y%m%d_%H%M%S')}_{os.getpid()}.cms"
        return os.path.join(session_dir, fname)

    def _session_data_headers(self) -> list[str]:
        return [h for h in self.headers if h not in ("ID_HIDDEN", "Structure")]

    def _snapshot_structure_payloads(
        self, oids: set[int] | None
    ) -> dict[int, tuple[bytes | None, str]]:
        """One MolStore scan of ``(blob, smiles)`` — no RDKit hydrate on the GUI thread."""
        payloads: dict[int, tuple[bytes | None, str]] = {}
        iter_fn = getattr(self.mols, "iter_structure_payloads", None)
        if not callable(iter_fn):
            return payloads
        for oid, blob, smi in iter_fn():
            oid_i = int(oid)
            if oids is not None and oid_i not in oids:
                continue
            payloads[oid_i] = (blob, smi or "")
        return payloads

    def _snapshot_session_save_inputs(self, *, oids: set[int] | None = None) -> dict:
        """Cheap GUI snapshot: cell text + stored structure payloads, no RDKit serialize."""
        data_headers = self._session_data_headers()
        entries = self._table_model.export_rows_for_sqlite(data_headers)
        if oids is not None:
            entries = [(oid, cells) for oid, cells in entries if oid in oids]
        return {
            "headers": list(self.headers),
            "entries": entries,
            "payloads": self._snapshot_structure_payloads(oids),
            "metadata": self._session_document_metadata(oids=oids),
            "ensembles": self._ensembles_sqlite_for_session(oids),
        }

    def _build_session_document(self, *, oids: set[int] | None = None) -> dict:
        """Synchronous compact document (tests). File save uses :meth:`_enqueue_session_save`."""
        return assemble_session_document(self._snapshot_session_save_inputs(oids=oids))

    def _session_document_metadata(self, *, oids: set[int] | None = None) -> dict:
        hh = self.table.horizontalHeader()
        n = self._table_model.columnCount()
        logical_order = sorted(range(n), key=lambda lg: hh.visualIndex(lg)) if n else []
        sort_col = None
        sort_asc = True
        sort_mode = None
        ss = getattr(self, "_session_sort", None)
        if isinstance(ss, dict) and ss.get("column") is not None:
            sc = ss["column"]
            if isinstance(sc, int) and 0 <= sc < n:
                sort_col = sc
                sort_asc = bool(ss.get("ascending", True))
                sort_mode = str(ss.get("mode") or "auto")
        want = oids
        filters_out: list[dict] = []
        for f in self.filters:
            if isinstance(f, SubstructureFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "substructure",
                        "title": f.filter_title(),
                        "smarts": cfg.get("smarts", "") or "",
                        "structure_source": cfg.get("structure_source", "Structure") or "Structure",
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
            elif isinstance(f, TextFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "text",
                        "title": f.filter_title(),
                        "property": cfg_column(cfg),
                        "text": cfg.get("text", "") or "",
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                        "case_sensitive": bool(cfg.get("case_sensitive", False)),
                        "partial_match": bool(cfg.get("partial_match", True)),
                    }
                )
            elif isinstance(f, CategoryFilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "category",
                        "title": f.filter_title(),
                        "property": cfg_column(cfg),
                        "values": list(cfg.get("values") or []),
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
            elif isinstance(f, FilterCard):
                cfg = f.get_cfg()
                filters_out.append(
                    {
                        "kind": "range",
                        "title": f.filter_title(),
                        "property": cfg_column(cfg),
                        "min": cfg.get("min"),
                        "max": cfg.get("max"),
                        "enabled": cfg.get("enabled", True),
                        "inverted": cfg.get("inverted", False),
                    }
                )
        doc = {
            "format": self._SESSION_FORMAT,
            "version": self._SESSION_VERSION,
            "headers": list(self.headers),
            "global_bounds": compact_global_bounds(getattr(self, "global_bounds", None)),
            "next_oid": int(self.next_oid),
            "zoomed_ids": sorted(int(x) for x in self.zoomed_ids if want is None or int(x) in want),
            "structure_field_override": getattr(self, "_structure_field_override", None),
            "filter_panel_visible": bool(self.f_panel.isVisible()),
            "workspace_layout": (
                self._workspace_layout.collect_splitter_sizes()
                if getattr(self, "_workspace_layout", None) is not None
                else None
            ),
            "plot_panel_visible": True,
            "plot_panel_width": (self._plot_panel_splitter_sizes() or [0, 0])[1],
            "docked_plots": self._collect_docked_plots(),
            "floating_plots": self._collect_floating_plots(),
            "table_layout": self._collect_table_layout(),
            "filters": filters_out,
            "column_logical_order": logical_order,
            "sort_column": sort_col,
            "sort_ascending": sort_asc,
            "sort_mode": sort_mode,
            "column_colors": self._table_model.export_column_color_rules(),
            "logarithmic_columns": sorted(
                h for h in getattr(self, "_logarithmic_columns", set()) if h in self.headers
            ),
            "confs_sidecar": serialize_confs_sidecar(self._confs_sidecar_for_session(want)),
            "som_browse": self._session_som_browse_payload(oids=want),
            "ionization_sidecar": serialize_ionization_sidecar(),
            "mmp_ledger": self._session_mmp_ledger_payload(),
            "dock_results": self._session_dock_results_payload(oids=want),
            "protein_viewer": self._collect_protein_viewer(),
            "gnina_dock": self._collect_gnina_dock(),
        }
        collect_search = getattr(self, "collect_table_search_session", None)
        if callable(collect_search):
            search_payload = collect_search()
            if search_payload:
                doc["table_search"] = search_payload
        collect_lists = getattr(self, "collect_row_lists_session", None)
        if callable(collect_lists):
            lists_payload = collect_lists(oids=want)
            if lists_payload:
                doc["row_lists"] = lists_payload
        collect_notepad = getattr(self, "collect_notepad_session", None)
        if callable(collect_notepad):
            notepad_payload = collect_notepad()
            if notepad_payload:
                doc["notepad"] = notepad_payload
        return doc

    def _confs_sidecar_for_session(self, oids: set[int] | None) -> dict[tuple[int, str], str]:
        from ...storage import EnsembleStore

        store = getattr(self, "_confs_blocks_sidecar", None)
        if store is None or isinstance(store, EnsembleStore):
            return {}
        if oids is None:
            return store
        return {k: v for k, v in store.items() if int(k[0]) in oids}

    def _ensembles_sqlite_for_session(self, oids: set[int] | None) -> bytes | None:
        from ...storage import EnsembleStore

        store = getattr(self, "_confs_blocks_sidecar", None)
        if not isinstance(store, EnsembleStore) or len(store) == 0:
            return None
        if oids is not None and not any(int(k[0]) in oids for k in store):
            return None
        blob = store.export_sqlite_bytes(None if oids is None else oids)
        return blob or None

    def _session_som_browse_payload(self, *, oids: set[int] | None = None) -> list[dict]:
        """Atom-level SOM maps for session restore (redraws table images on open)."""
        from ..som_browser import records_from_table, serialize_som_browse_records

        records = list(getattr(self, "_som_browse_records", None) or ())
        if not records:
            records = records_from_table(self)
        payload = serialize_som_browse_records(records)
        if oids is None:
            return payload
        kept: list[dict] = []
        for item in payload:
            try:
                oid = int(item.get("oid"))
            except (TypeError, ValueError):
                continue
            if oid in oids:
                kept.append(item)
        return kept

    def _session_mmp_ledger_payload(self) -> dict | None:
        """Last MMP run for Transform Ledger reopen after session open."""
        from ...analysis.mmp_session import serialize_mmp_ledger_payload

        return serialize_mmp_ledger_payload(
            getattr(self, "_mmp_last_pairs", None),
            activity_column=str(getattr(self, "_mmp_last_activity_column", "") or ""),
        )

    def _session_dock_results_payload(self, *, oids: set[int] | None = None) -> dict | None:
        """Last docking run for Pose Browser reopen after session open."""
        from ...docking.pose_file_io import serialize_dock_results_payload

        return serialize_dock_results_payload(
            getattr(self, "_last_dock_results", None),
            oids=oids,
        )

    def _collect_protein_viewer(self) -> dict | None:
        payload = getattr(self, "_protein_viewer_session", None)
        if not isinstance(payload, dict) or not payload.get("structures"):
            return None
        try:
            return json.loads(json.dumps(payload))
        except (TypeError, ValueError):
            logger.exception("Skipping Protein Viewer with non-JSON-serializable session state")
            return None

    def commit_protein_viewer_session(self, payload: dict | None) -> None:
        """Store a Protein Viewer snapshot for the next File → Session → Save Session."""
        if isinstance(payload, dict) and payload.get("structures"):
            self._protein_viewer_session = json.loads(json.dumps(payload))
        else:
            self._protein_viewer_session = None
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()

    def save_session_as(self) -> bool:
        """Prompt for a path and save the session. Returns True if a write was started."""
        return self._prompt_save_session_document(
            dialog_title="Save Session",
            oids=None,
            clear_dirty=True,
            status_prefix="Session saved to",
        )

    def save_selected_to_session(self) -> bool:
        """Write a new ``.cms`` that contains only the currently selected table rows."""
        oids = {int(o) for o in self._selected_oids_set()}
        if not oids:
            QMessageBox.information(
                self,
                "Save Selected to Session",
                "No rows are selected. Select one or more rows in the table first.",
            )
            return False
        return self._prompt_save_session_document(
            dialog_title="Save Selected to Session",
            oids=oids,
            clear_dirty=False,
            status_prefix="Selected rows saved to session",
        )

    def _prompt_save_session_document(
        self,
        *,
        dialog_title: str,
        oids: set[int] | None,
        clear_dirty: bool,
        status_prefix: str,
    ) -> bool:
        path, _ = QFileDialog.getSaveFileName(
            self, dialog_title, "", "MolManager Session (*.cms);;JSON (*.json)"
        )
        if not path:
            return False
        low = path.lower()
        if not low.endswith(".cms") and not low.endswith(".json"):
            path += ".cms"
        try:
            snapshot = self._snapshot_session_save_inputs(oids=oids)
        except Exception as e:
            logger.exception("Save session snapshot failed")
            QMessageBox.warning(self, dialog_title, str(e))
            return False
        return self._enqueue_session_save(
            path,
            snapshot,
            clear_dirty=clear_dirty,
            status_prefix=status_prefix,
            dialog_title=dialog_title,
        )

    def _enqueue_session_save(
        self,
        path: str,
        snapshot: dict,
        *,
        clear_dirty: bool,
        status_prefix: str,
        dialog_title: str,
        on_success: Callable[[], None] | None = None,
    ) -> bool:
        """Queue compact+write off the GUI thread. Returns True if a write was started."""
        pending = {
            "path": path,
            "clear_dirty": bool(clear_dirty),
            "status_prefix": str(status_prefix),
            "dialog_title": str(dialog_title),
            "on_success": on_success,
        }
        sigs = getattr(self, "_session_save_signals", None)
        pool = getattr(self, "threadpool", None)
        if sigs is None or pool is None:
            return self._write_session_snapshot_sync(snapshot, pending)
        self._session_save_gen = int(getattr(self, "_session_save_gen", 0)) + 1
        gen = self._session_save_gen
        jobs = getattr(self, "_session_save_pending", None)
        if jobs is None:
            jobs = {}
            self._session_save_pending = jobs
        jobs[gen] = pending
        self._session_save_last_ok = False
        n_rows = max(1, len(snapshot.get("entries") or []))
        job_id = f"session-save-{gen}"
        pending["job_id"] = job_id
        register_background_job(self, job_id, f"Saving session ({n_rows:,} rows)")
        begin = getattr(self, "_begin_tool_progress", None)
        if callable(begin):
            begin("Saving session", n_rows, job_id=job_id)
        self.status_label.setText("Saving session…")
        prog = getattr(self, "_tool_progress_state", None)
        bind = getattr(prog, "bind", None)
        if callable(bind) and job_id:
            prog = bind(job_id)
        start_runnable_on_app_pool(
            self,
            SessionSaveWorker(gen, path, snapshot, sigs, progress_state=prog),
        )
        return True

    def _write_session_snapshot_sync(self, snapshot: dict, pending: dict) -> bool:
        """Fallback when the thread pool or save signals are unavailable."""
        path = pending["path"]
        try:
            payload = dumps_session_document(assemble_session_document(snapshot))
            with open(path, "wb") as handle:
                handle.write(payload)
        except Exception as e:
            logger.exception("Save session failed: %s", path)
            QMessageBox.warning(self, pending.get("dialog_title") or "Save Session", str(e))
            self._session_save_last_ok = False
            return False
        self._apply_session_save_success(pending)
        self._session_save_last_ok = True
        return True

    def _unregister_session_save_job(self, pending: dict | None) -> None:
        job_id = None if pending is None else pending.get("job_id")
        if job_id:
            unregister_background_job(self, str(job_id))
        finish = getattr(self, "_finish_tool_progress", None)
        if callable(finish):
            finish("Saving session", status_message=None, job_id=job_id)

    def _apply_session_save_success(self, pending: dict) -> None:
        path = pending["path"]
        self.status_label.setText(f"{pending['status_prefix']} {path}")
        if pending.get("clear_dirty"):
            clear = getattr(self, "_clear_session_dirty", None)
            if callable(clear):
                clear()
        self._session_source_path = path
        write_cache = getattr(self, "_write_session_structure_cache", None)
        if callable(write_cache):
            write_cache(path)
        on_success = pending.get("on_success")
        if callable(on_success):
            on_success()

    def _on_session_save_finished(self, job_gen: int, path: str) -> None:
        jobs = getattr(self, "_session_save_pending", None) or {}
        pending = jobs.pop(int(job_gen), None)
        self._unregister_session_save_job(pending)
        if pending is None:
            return
        self._session_save_last_ok = True
        try:
            self._apply_session_save_success(pending)
        except Exception as e:
            logger.exception("Session save follow-up failed: %s", path)
            self._session_save_last_ok = False
            QMessageBox.warning(self, pending.get("dialog_title") or "Save Session", str(e))

    def _on_session_save_failed(self, job_gen: int, message: str) -> None:
        jobs = getattr(self, "_session_save_pending", None) or {}
        pending = jobs.pop(int(job_gen), None)
        self._unregister_session_save_job(pending)
        self._session_save_last_ok = False
        title = (pending or {}).get("dialog_title") or "Save Session"
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, title, message or "Could not save the session.")

    def _wait_session_save(self, timeout_ms: int = 120_000) -> bool:
        """Drain the app thread pool so a queued session write can finish (quit / tests)."""
        pool = getattr(self, "threadpool", None)
        ok = True
        if pool is not None:
            ok = bool(pool.waitForDone(int(timeout_ms)))
        app = QApplication.instance()
        if app is not None:
            app.processEvents()
        return ok

    def open_session_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open Session",
            "",
            "MolManager Session (*.cms *.json);;Legacy session CSV (*.csv);;All files (*.*)",
        )
        if not path:
            return
        if path.lower().endswith(".csv"):
            self.load_session_csv(path)
        else:
            self.apply_saved_session_from_file(path)

    def apply_saved_session_from_file(self, path: str) -> bool:
        problem = preflight_open_path(path)
        if problem:
            logger.warning("Open session: %s", problem)
            self._warn_could_not_open("Open Session", problem)
            return False
        try:
            with open(path, "rb") as f:
                raw = f.read()
            d = expand_session_document(loads_session_bytes(raw))
        except Exception as e:
            logger.exception("Open session: could not read %s", path)
            self._warn_could_not_open("Open Session", message_for_session_read_failure(path, e))
            return False
        if not self._session_format_ok(d.get("format")) or not self._session_version_ok(
            d.get("version")
        ):
            self._warn_could_not_open("Open Session", not_a_session_message(path))
            return False
        self._note_open_attempt("Open Session")
        self._session_source_path = path
        try:
            self._apply_session_document(d)
        except Exception:
            logger.exception("Open session: apply failed for %s", path)
            self._finish_failed_open()
            self._warn_could_not_open("Open Session", damaged_session_message(path))
            return False
        return True
