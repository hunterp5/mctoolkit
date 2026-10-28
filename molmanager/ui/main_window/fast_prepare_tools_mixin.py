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

"""Prepare and Fast Prepare, bound on ``WorkspaceTools.structure_prep``."""

from __future__ import annotations

from PyQt5.QtCore import Qt

from ...platform_support.config import load_config
from ..analysis_job_support import enqueue_process_queue_job


class FastPrepareToolsMixin:
    def run_prepare(self) -> None:
        """Open Chemistry → Structure Preparation → Preparation Menu.

        Every standardization step starts unchecked.
        """
        from ..dialogs.prepare import PrepareDialog

        self._open_prepare_dialog(PrepareDialog, "Prepare")

    def run_fast_prepare(self) -> None:
        """Open Chemistry → Structure Preparation → Fast Prepare.

        Largest fragment, optional neutralize, and redraw.
        """
        from ..dialogs.fast_prepare import FastPrepareDialog

        self._open_prepare_dialog(FastPrepareDialog, "Fast Prepare")

    def _open_prepare_dialog(self, dialog_cls, tool_name: str) -> None:
        if not self.headers or not self.mols:
            return
        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = dialog_cls(candidates, self.headers, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(
            lambda *_, d=dlg, name=tool_name: self._on_fast_prepare_dialog_accepted(d, name)
        )
        dlg.show()

    def _on_fast_prepare_dialog_accepted(self, dlg, tool_name: str = "Prepare") -> None:
        from ...workflows.macro_record import fast_prepare_step
        from ..command_dispatch import dispatch_step

        cfg = dlg.config()
        allowed = self._selected_oids_set() if cfg.only_selected else None
        if self._abort_if_only_selected_but_empty(cfg.only_selected, allowed, tool_name):
            return
        dispatch_step(self, fast_prepare_step(cfg), {})

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
        depiction = getattr(self, "_depiction_coords", None)
        items = []
        for oid, blob, text in rows:
            xy = b""
            if depiction is not None:
                xy = depiction.get(src, int(oid)) or b""
            items.append((int(oid), blob or b"", text or None, xy))
        return items

    def start_fast_prepare_job(self, params: dict, *, allowed: set[int] | None, on_done) -> None:
        """Prepare structures. ``on_done`` runs after the columns are written, before Render 2D."""
        from PyQt5.QtCore import Qt

        from ...chem.structure_prepare import options_from_prepare_params
        from ...workers.fast_prepare import FastPrepareParams, FastPrepareWorker
        from ..job_signals import FastPrepareJobSignals, release_job_signals, retain_job_signals
        from ..macro_recorder import report_unless_replaying

        options = options_from_prepare_params(params)
        legacy = options is None
        tool_name = "Fast Prepare" if legacy else "Prepare"
        progress_name = "Fast prepare" if legacy else "Prepare"
        source = str(params.get("structure_source") or "").strip()
        update_target = bool(params.get("update_target", True))
        largest = params.get("largest_column")
        prepare_col = source if update_target else str(largest or "").strip()
        fragments = str(params.get("fragments_column") or "Fragments").strip()
        if not source or not prepare_col:
            message = "Choose a structure column."
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            report_unless_replaying(self, tool_name, message)
            return
        data = self._collect_fast_prepare_items(source, allowed)
        if not data:
            message = "No rows match the current scope and structure field."
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            report_unless_replaying(self, tool_name, message, warning=False)
            return
        render = (
            prepare_col == "Structure"
            if "render_2d" not in params
            else bool(params.get("render_2d"))
        )
        protonate_pending = bool(params.get("protonate")) and not params.get("_protonate_done")
        molecule_options = (
            options.before_protonation() if options is not None and protonate_pending else options
        )
        after = options.after_protonation() if options is not None and protonate_pending else None
        if (
            options is not None
            and molecule_options is not None
            and not molecule_options.has_edits()
        ):
            skipped = dict(params)
            skipped["_needs_render"] = bool(render)
            self._after_prepare_write(
                skipped, allowed, prepare_col, after, on_done, {"output": prepare_col}
            )
            return
        cfg = load_config()
        want_scene = bool(render and prepare_col == "Structure" and after is None)
        worker_params = FastPrepareParams(
            is_smiles=source != "Structure",
            need_smiles=True,
            neutralize=bool(params.get("neutralize")),
            options=molecule_options,
            batch_size=int(cfg.fast_prepare_batch_size),
            process_pool_min_rows=int(cfg.fast_prepare_process_pool_min_rows),
            want_scene=want_scene,
        )
        renders = (
            True
            if legacy
            else bool(want_scene or (render and after is None and prepare_col != "Structure"))
        )
        job = _FastPrepareJob(
            prepare_col,
            fragments,
            update_target,
            on_done,
            write_fragments=True
            if legacy
            else bool(molecule_options and molecule_options.largest_fragment),
            render_2d=renders,
            progress_name=progress_name,
        )
        sig = FastPrepareJobSignals(self)
        retain_job_signals(self, sig)

        def _batch(rows, is_last, state=job, held=sig) -> None:
            self._fast_prepare_on_batch(state, rows, is_last)
            if is_last:
                release_job_signals(self, held)

        def _finished(results, state=job, held=sig) -> None:
            release_job_signals(self, held)
            self._fast_prepare_on_finished(state, results)

        sig.fast_prepared_batch.connect(_batch, Qt.QueuedConnection)
        sig.fast_prepared.connect(_finished, Qt.QueuedConnection)
        held_params = dict(params)
        original_done = on_done

        def _chained(error, outputs, state=job) -> None:
            if error:
                if original_done is not None:
                    original_done(error, outputs or {})
                return
            self._after_prepare_write(
                held_params, allowed, state.prepare_col, after, original_done, outputs or {}
            )

        job.on_done = _chained
        enqueue_process_queue_job(
            self,
            progress_name,
            len(data),
            lambda ev, ps, d=data, p=worker_params, s=sig: FastPrepareWorker(
                d, p, s, cancel_event=ev, progress_state=ps
            ),
            queue_label=("Fast prepare: prepare structures" if legacy else "Prepare: structures"),
        )

    def _enqueue_fast_prepare(
        self, src: str, prepare_col: str, *, only_selected: bool, neutralize: bool = False
    ) -> None:
        """Queue the fused disconnect (and optional neutralize) pass over the rows in scope."""
        update_target = prepare_col == src
        self.start_fast_prepare_job(
            {
                "structure_source": src,
                "update_target": update_target,
                "largest_column": None if update_target else prepare_col,
                "fragments_column": getattr(self, "_fast_prepare_fragments_col", "Fragments"),
                "neutralize": bool(neutralize),
            },
            allowed=self._selected_oids_set() if only_selected else None,
            on_done=None,
        )

    def on_fast_prepare_batch(self, rows, is_last: bool) -> None:
        """Write one streamed Structure batch. The last signal finishes the job."""
        self._fast_prepare_on_batch(self._fast_prepare_job_from_window(), rows, is_last)

    def on_fast_prepare_finished(self, results) -> None:
        """Apply fused disconnect + neutralize results, then render depictions that still need it.

        One writeback per row: the old two-job chain wrote the disconnected parent and then
        immediately overwrote it with the neutralized molecule. A Structure job that already
        carried scenes is applied as a single streamed batch.
        """
        self._fast_prepare_on_finished(self._fast_prepare_job_from_window(), results)

    def _fast_prepare_job_from_window(self) -> "_FastPrepareJob":
        job = getattr(self, "_fast_prepare_window_job", None)
        if isinstance(job, _FastPrepareJob) and job.applying and not job.settled:
            return job
        job = _FastPrepareJob(
            getattr(self, "_fast_prepare_source", "Structure"),
            getattr(self, "_fast_prepare_fragments_col", "Fragments"),
            getattr(self, "_fast_prepare_update_target", True),
        )
        self._fast_prepare_window_job = job
        return job

    def _fast_prepare_on_batch(self, job: "_FastPrepareJob", rows, is_last: bool) -> None:
        if rows or not job.applying:
            self._apply_fast_prepare_rows(rows or [], job)
        if is_last:
            self._finish_fast_prepare_job(job, structure_scenes=True)

    def _fast_prepare_on_finished(self, job: "_FastPrepareJob", results) -> None:
        if results and len(results[0]) >= 6:
            self._fast_prepare_on_batch(job, results, True)
            return
        self._apply_fast_prepare_rows(results or [], job)
        self._finish_fast_prepare_job(job, structure_scenes=False)

    def _begin_fast_prepare_apply(self, job: "_FastPrepareJob") -> tuple[str, str, bool]:
        if job.applying:
            return job.apply_col, job.apply_fragments, job.apply_update
        job.apply_col = job.prepare_col
        job.apply_fragments = job.fragments_col
        job.apply_update = job.update_target
        job.fallback_oids = []
        job.written_oids = []
        job.applying = True
        self.table.setSortingEnabled(False)
        if job.write_fragments:
            self._ensure_disconnect_output_column(job.apply_fragments)
        if not job.apply_update:
            self._ensure_disconnect_output_column(job.apply_col)
        return job.apply_col, job.apply_fragments, job.apply_update

    def _apply_fast_prepare_rows(self, results, job: "_FastPrepareJob") -> None:
        """Write one batch of ``(oid, blob, fragments, smiles[, scene, xy])`` rows."""
        prepare_col, fragments_col, _update_target = self._begin_fast_prepare_apply(job)
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
                job.fallback_oids.append(oid)
            if xy:
                coords.append((oid, xy))
        oids = self._write_tool_structures(
            prepare_col, [(oid, blob, smiles) for oid, blob, _fragments, smiles in prepared]
        )
        job.written_oids.extend(oids)
        if fragments_col in self.headers:
            pairs = [(oid, fragments) for oid, _blob, fragments, _smiles in prepared]
            self._table_model.set_column_text_by_oids(fragments_col, pairs)
            job.fragment_pairs.extend(pairs)
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

    def _finish_fast_prepare_job(self, job: "_FastPrepareJob", *, structure_scenes: bool) -> None:
        if job.settled:
            return
        job.settled = True
        job.applying = False
        prepare_col = job.apply_col
        written = list(job.written_oids)
        fallbacks = list(job.fallback_oids)
        if getattr(self, "_fast_prepare_window_job", None) is job:
            self._fast_prepare_window_job = None
            self._fast_prepare_source = "Structure"
            self._fast_prepare_allowed_oids = None
            self._fast_prepare_fragments_col = "Fragments"
            self._fast_prepare_update_target = True
            self._fast_prepare_applying = False

        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()
        if job.on_done is not None:
            if self.has_partial_results_notice():
                job.on_done("Cancelled.", {})
            else:
                job.on_done(
                    None,
                    {"output": prepare_col, "fragments": job.fragments_col},
                )

        # Scenes already cover the Structure rows. Only the builder's leftovers are redrawn,
        # and they still have the coordinates just stored, so that redraw keeps the layout.
        redraw = fallbacks if structure_scenes else written
        label = job.progress_name
        rendered_dest = bool(
            job.render_2d
            and redraw
            and self._render_tool_structures(
                prepare_col, redraw, queue_title_prefix=f"{label}: ", serial=True
            )
        )
        fragments_col = job.fragments_col
        if (
            job.write_fragments
            and fragments_col
            and fragments_col != prepare_col
            and job.fragment_pairs
        ):
            depict = getattr(self, "_queue_generated_structure_renders", None)
            if callable(depict):
                depict(
                    [fragments_col],
                    {oid for oid, _text in job.fragment_pairs},
                    [(oid, {fragments_col: text}) for oid, text in job.fragment_pairs],
                )
        if rendered_dest:
            self.status_label.setText(f"{label}: rendering 2D…")
            return
        self.status_label.setText(self._consume_partial_results_notice() or f"{label} done.")

    def _after_prepare_write(self, params, allowed, column, after, on_done, outputs) -> None:
        """Run protonation, the edits that follow it, then the optional side tools."""
        if bool(params.get("protonate")) and not params.get("_protonate_done"):
            self._prepare_protonate(params, allowed, column, after, on_done, outputs)
            return
        if after is not None and after.has_edits():
            next_params = dict(params)
            next_params.update(
                {
                    "standardize": False,
                    "largest_fragment": False,
                    "neutralize": False,
                    "protonate": False,
                    "_protonate_done": True,
                    "canonical_tautomer": after.canonical_tautomer,
                    "remove_isotopes": after.remove_isotopes,
                    "explicit_hydrogens": after.explicit_hydrogens,
                    "structure_source": column,
                    "update_target": True,
                    "largest_column": None,
                }
            )
            self.start_fast_prepare_job(next_params, allowed=allowed, on_done=on_done)
            return
        self._prepare_side_jobs(params, allowed, column, on_done, outputs)

    def _prepare_protonate(self, params, allowed, column, after, on_done, outputs) -> None:
        from ...workflows.macro_recipe import ROW_SCOPE_SELECTION, ROW_SCOPE_TABLE
        from ...workflows.tool_requests import ProtonateRequest

        output = column if column != "Structure" else "Protonated"
        request = ProtonateRequest(
            structure_source=column,
            ph=float(params.get("protonate_ph") or 7.4),
            output_column=output,
            render_2d=bool(params.get("render_2d"))
            and not (after is not None and after.has_edits()),
            row_scope=ROW_SCOPE_SELECTION if allowed is not None else ROW_SCOPE_TABLE,
        )

        def _next(error, prot_outputs) -> None:
            if error:
                if on_done is not None:
                    on_done(error, {})
                return
            written = str((prot_outputs or {}).get("output") or output)
            marked = dict(params)
            marked["_protonate_done"] = True
            self._after_prepare_write(
                marked, allowed, written, after, on_done, prot_outputs or outputs
            )

        self.start_protonate_job(request, allowed=allowed, on_done=_next)

    def _prepare_side_jobs(self, params, allowed, column, on_done, outputs) -> None:
        if params.get("_needs_render"):
            rows = self._structure_tool_inputs(column, allowed)
            oids = [int(row[0]) for row in rows]
            if oids:
                self._render_tool_structures(column, oids, queue_title_prefix="Prepare: ")
        if params.get("generate_protomers"):
            self._prepare_protomers(params, column)
        if on_done is not None:
            on_done(
                None, outputs or {"output": column, "fragments": params.get("fragments_column")}
            )

    def _prepare_protomers(self, params, column) -> None:
        from ..dialogs.protomer import ProtomerGeneratorDialog

        dialog = ProtomerGeneratorDialog(self)
        dialog.ph_spin.setValue(float(params.get("protomer_ph") or 7.4))
        dialog.output_file.setText(str(params.get("protomer_output_file") or ""))
        dialog._refresh_structure_sources()
        index = dialog._structure_input.src_combo.findText(column)
        if index >= 0:
            dialog._structure_input.src_combo.setCurrentIndex(index)
        dialog.show()
        dialog._on_generate()


class _FastPrepareJob:
    """Columns and completion for one Fast Prepare writeback."""

    def __init__(
        self,
        prepare_col: str,
        fragments_col: str,
        update_target: bool,
        on_done=None,
        *,
        write_fragments: bool = True,
        render_2d: bool = True,
        progress_name: str = "Fast prepare",
    ):
        self.prepare_col = prepare_col
        self.fragments_col = fragments_col
        self.update_target = bool(update_target)
        self.on_done = on_done
        self.write_fragments = bool(write_fragments)
        self.render_2d = bool(render_2d)
        self.progress_name = progress_name
        self.applying = False
        self.settled = False
        self.apply_col = prepare_col
        self.apply_fragments = fragments_col
        self.apply_update = bool(update_target)
        self.fallback_oids: list[int] = []
        self.written_oids: list[int] = []
        self.fragment_pairs: list[tuple[int, str]] = []
