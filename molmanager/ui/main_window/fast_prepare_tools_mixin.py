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

"""Fast Prepare adapter bound on ``WorkspaceTools.structure_prep`` (not a window base)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ...platform_support.config import load_config
from ..analysis_job_support import enqueue_process_queue_job


class FastPrepareToolsMixin:
    def run_fast_prepare(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import FastPrepareDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = FastPrepareDialog(candidates, self.headers, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_fast_prepare_dialog_accepted(d))
        dlg.show()

    def _on_fast_prepare_dialog_accepted(self, dlg) -> None:
        cfg = dlg.config()
        allowed = self._selected_oids_set() if cfg.only_selected else None
        if self._abort_if_only_selected_but_empty(cfg.only_selected, allowed, "Fast Prepare"):
            return
        prepare_col = cfg.source_column if cfg.update_target else cfg.largest_column
        self._fast_prepare_source = prepare_col
        self._fast_prepare_allowed_oids = allowed
        self._fast_prepare_fragments_col = cfg.fragments_column
        self._fast_prepare_update_target = cfg.update_target
        self._enqueue_fast_prepare(
            cfg.source_column,
            prepare_col,
            only_selected=cfg.only_selected,
            neutralize=cfg.neutralize,
        )

    def _fast_prepare_target_is_text(self, prepare_col: str) -> bool:
        """True when the Fast Prepare output column holds SMILES text rather than a depiction.

        A column the dialog named but that does not exist yet (New Column mode) counts as text: it
        is created as a plain data column before the results are written.
        """
        if prepare_col == "Structure":
            return False
        return not (
            prepare_col in self.headers and self._table_model.is_pixmap_data_column(prepare_col)
        )

    def _collect_fast_prepare_items(self, src: str, allowed: set[int] | None) -> list[tuple]:
        """Worker input rows for the scope, in table order, without hydrating molecules.

        The Structure column sends ``(oid, stored_blob, source_text)``; the worker rebuilds each
        molecule in its child process. Any other column sends ``(oid, cell_text)``, read from the
        backing text so image-only columns work too.
        """
        rows = self._structure_tool_inputs(src, allowed, with_source_text=True)
        if src != "Structure":
            return [(oid, text) for oid, _blob, text in rows]
        return [(oid, blob or b"", text or None) for oid, blob, text in rows]

    def _enqueue_fast_prepare(
        self, src: str, prepare_col: str, *, only_selected: bool, neutralize: bool = False
    ) -> None:
        """Queue the fused disconnect (and optional neutralize) pass over the rows in scope."""
        from ...workers.fast_prepare import FastPrepareParams, FastPrepareWorker

        allowed = self._selected_oids_set() if only_selected else None
        is_smiles = src != "Structure"
        data = self._collect_fast_prepare_items(src, allowed)

        if not data:
            QMessageBox.information(
                self,
                "Fast Prepare",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return

        # The mol store keeps a SMILES beside every blob (session save reads it), so the child
        # processes always canonicalize; the GUI thread never runs MolToSmiles. Structure output
        # also comes back with a depiction scene, so drawing does not start a second job.
        cfg = load_config()
        params = FastPrepareParams(
            is_smiles=is_smiles,
            need_smiles=True,
            neutralize=bool(neutralize),
            batch_size=int(cfg.fast_prepare_batch_size),
            process_pool_min_rows=int(cfg.fast_prepare_process_pool_min_rows),
            want_scene=prepare_col == "Structure",
        )
        enqueue_process_queue_job(
            self,
            "Fast prepare",
            len(data),
            lambda ev, ps, d=data, p=params, s=self.signals: FastPrepareWorker(
                d, p, s, cancel_event=ev, progress_state=ps
            ),
            queue_label="Fast prepare: prepare structures",
        )

    def on_fast_prepare_batch(self, rows, is_last: bool) -> None:
        """Write one streamed Structure batch. The last signal finishes the job."""
        if rows or not getattr(self, "_fast_prepare_applying", False):
            self._apply_fast_prepare_rows(rows or [])
        if is_last:
            self._finish_fast_prepare(structure_scenes=True)

    def on_fast_prepare_finished(self, results) -> None:
        """Apply fused disconnect + neutralize results, then render depictions that still need it.

        One writeback per row: the old two-job chain wrote the disconnected parent and then
        immediately overwrote it with the neutralized molecule. A Structure job that already
        carried scenes is applied as a single streamed batch.
        """
        if results and len(results[0]) >= 6:
            self.on_fast_prepare_batch(results, True)
            return
        self._apply_fast_prepare_rows(results or [])
        self._finish_fast_prepare(structure_scenes=False)

    def _fast_prepare_job_columns(self) -> tuple[str, str, bool]:
        if getattr(self, "_fast_prepare_applying", False):
            return (
                self._fast_prepare_apply_col,
                self._fast_prepare_apply_fragments,
                self._fast_prepare_apply_update,
            )
        prepare_col = getattr(self, "_fast_prepare_source", "Structure")
        fragments_col = getattr(self, "_fast_prepare_fragments_col", "Fragments")
        update_target = getattr(self, "_fast_prepare_update_target", True)
        self._fast_prepare_apply_col = prepare_col
        self._fast_prepare_apply_fragments = fragments_col
        self._fast_prepare_apply_update = update_target
        self._fast_prepare_fallback_oids = []
        self._fast_prepare_written_oids = []
        self._fast_prepare_applying = True
        self.table.setSortingEnabled(False)
        self._ensure_disconnect_output_column(fragments_col)
        if not update_target:
            self._ensure_disconnect_output_column(prepare_col)
        return prepare_col, fragments_col, update_target

    def _apply_fast_prepare_rows(self, results) -> None:
        """Write one batch of ``(oid, blob, fragments, smiles[, scene, xy])`` rows."""
        prepare_col, fragments_col, _update_target = self._fast_prepare_job_columns()
        prepared: list[tuple[int, bytes, str, str]] = []
        scenes: list[tuple[int, bytes]] = []
        coords: list[tuple[int, bytes]] = []
        for row in results:
            blob = bytes(row[1]) if row[1] else b""
            if not blob:
                continue
            oid = int(row[0])
            prepared.append((oid, blob, row[2], row[3]))
            if len(row) < 6:
                continue
            scene = bytes(row[4] or b"")
            xy = bytes(row[5] or b"")
            if scene:
                scenes.append((oid, scene))
            elif prepare_col == "Structure":
                self._fast_prepare_fallback_oids.append(oid)
            if xy:
                coords.append((oid, xy))
        oids = self._write_tool_structures(
            prepare_col, [(oid, blob, smiles) for oid, blob, _fragments, smiles in prepared]
        )
        self._fast_prepare_written_oids.extend(oids)
        if fragments_col in self.headers:
            self._table_model.set_column_text_by_oids(
                fragments_col, [(oid, fragments) for oid, _blob, fragments, _smiles in prepared]
            )
        depiction = getattr(self, "_depiction_coords", None)
        if depiction is not None and coords:
            # Writeback drops the previous orientation. These are the coordinates the scene used,
            # so a later Render 2D rebuilds the same picture.
            depiction.set_many(prepare_col, coords)
        if scenes:
            self._store_fast_prepare_scenes(scenes)

    def _store_fast_prepare_scenes(self, scenes: list[tuple[int, bytes]]) -> None:
        """Put packed scenes on the table as they arrive, creating the store on the first batch."""
        from ...platform_support.config import load_config
        from ...storage.structure_render_store import StructureRenderStore

        model = self._table_model
        store = model._structure_png_store
        if store is None:
            cfg = load_config()
            store = StructureRenderStore(
                max_decoded_pixmaps=cfg.structure_render_pixmap_lru,
                max_png_entries=cfg.structure_render_png_max_entries,
            )
            model.set_structure_png_store(store)
            hook = getattr(self, "_ensure_structure_lazy_scroll_hook", None)
            if callable(hook):
                hook()
        store.ingest_batch(scenes)
        repaint = getattr(self, "_repaint_visible_rendered_rows", None)
        if callable(repaint):
            repaint({oid for oid, _scene in scenes})

    def _finish_fast_prepare(self, *, structure_scenes: bool) -> None:
        prepare_col = getattr(self, "_fast_prepare_apply_col", "Structure")
        written = list(getattr(self, "_fast_prepare_written_oids", []))
        fallbacks = list(getattr(self, "_fast_prepare_fallback_oids", []))
        self._fast_prepare_source = "Structure"
        self._fast_prepare_allowed_oids = None
        self._fast_prepare_fragments_col = "Fragments"
        self._fast_prepare_update_target = True
        self._fast_prepare_applying = False
        self._fast_prepare_fallback_oids = []
        self._fast_prepare_written_oids = []

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()

        # Scenes already cover the Structure rows. Only the builder's leftovers are redrawn,
        # and they still have the coordinates just stored, so that redraw keeps the layout.
        redraw = fallbacks if structure_scenes else written
        if redraw and self._render_tool_structures(
            prepare_col, redraw, queue_title_prefix="Fast prepare: "
        ):
            self.status_label.setText("Fast prepare: rendering 2D…")
            return
        self.status_label.setText(self._consume_partial_results_notice() or "Fast prepare done.")
