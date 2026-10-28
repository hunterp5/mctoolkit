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

"""Disconnect / neutralize / explicit-H adapters on ``WorkspaceTools.structure_prep``."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ... import workers
from ..analysis_job_support import enqueue_process_queue_job


class StructureEditMixin:
    def run_disconnect_fragments(self) -> None:
        if not self.headers or not self.mols:
            return
        candidates = self.chemistry_tool_structure_sources()
        from ..dialogs import DisconnectFragmentsDialog

        n_sel = len(self._selected_logical_rows())
        dlg = DisconnectFragmentsDialog(candidates, self.headers, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_disconnect_fragments_dialog_accepted(d))
        dlg.show()

    def _on_disconnect_fragments_dialog_accepted(self, dlg) -> None:
        src, update_target, largest_col, fragments_col, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Disconnect Largest Fragments"
        ):
            return
        self.status_label.setText("Disconnecting fragments…")
        self._enqueue_disconnect_fragments(
            src,
            update_target=update_target,
            largest_col=largest_col,
            fragments_col=fragments_col,
            only_selected=only_selected,
            no_render_2d=no_render_2d,
        )

    def _enqueue_disconnect_fragments(
        self,
        src: str,
        *,
        update_target: bool,
        largest_col: str | None,
        fragments_col: str,
        only_selected: bool,
        no_render_2d: bool,
        queue_title_prefix: str = "",
    ) -> None:
        allowed = self._selected_oids_set() if only_selected else None
        self._disconnect_source = src
        self._disconnect_update_target = update_target
        self._disconnect_largest_col = src if update_target else largest_col
        self._disconnect_fragments_col = fragments_col
        self._disconnect_no_render_2d = no_render_2d
        data = self._structure_tool_inputs(src, allowed, with_source_text=True)
        if not data:
            QMessageBox.information(
                self,
                "Disconnect Largest Fragments",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return
        suffix = "" if src == "Structure" else " (column)"
        enqueue_process_queue_job(
            self,
            "Disconnect fragments",
            len(data),
            lambda ev, ps, d=data, s=self.signals: workers.DisconnectFragmentsWorker(
                d, s, is_smiles=False, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"{queue_title_prefix}disconnect largest fragments{suffix}",
        )

    def run_add_explicit_hydrogens(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import AddExplicitHydrogensDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = AddExplicitHydrogensDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_add_explicit_hydrogens_dialog_accepted(d))
        dlg.show()

    def _on_add_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        from ...workflows.macro_recipe import STEP_EXPLICIT_H
        from ...workflows.macro_record import structure_edit_step
        from ..command_dispatch import dispatch_step

        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Add Explicit Hydrogens"):
            return
        dispatch_step(
            self,
            structure_edit_step(
                STEP_EXPLICIT_H, src, only_selected=only_selected, no_render_2d=no_render_2d
            ),
            {},
        )

    def start_explicit_hydrogens_job(
        self, params: dict, *, allowed: set[int] | None, on_done
    ) -> None:
        """Add explicit hydrogens. ``on_done(error, {"output": column})`` runs after the write."""
        self._start_structure_edit_job(
            "add",
            source=str(params.get("structure_source") or "").strip(),
            no_render_2d=bool(params.get("no_render_2d")),
            allowed=allowed,
            on_done=on_done,
            title="Add Explicit Hydrogens",
            progress="Adding explicit hydrogens…",
            queue_label="Add explicit hydrogens",
        )

    def _enqueue_add_explicit_hydrogens(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
    ) -> None:
        scope = "selection" if only_selected else "table"
        self.start_explicit_hydrogens_job(
            {"structure_source": src, "no_render_2d": no_render_2d, "row_scope": scope},
            allowed=self._selected_oids_set() if only_selected else None,
            on_done=None,
        )

    def run_remove_explicit_hydrogens(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import RemoveExplicitHydrogensDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = RemoveExplicitHydrogensDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(
            lambda *_, d=dlg: self._on_remove_explicit_hydrogens_dialog_accepted(d)
        )
        dlg.show()

    def _on_remove_explicit_hydrogens_dialog_accepted(self, dlg) -> None:
        from ...workflows.macro_recipe import STEP_REMOVE_H
        from ...workflows.macro_record import structure_edit_step
        from ..command_dispatch import dispatch_step

        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(
            only_selected, allowed, "Remove Explicit Hydrogens"
        ):
            return
        dispatch_step(
            self,
            structure_edit_step(
                STEP_REMOVE_H, src, only_selected=only_selected, no_render_2d=no_render_2d
            ),
            {},
        )

    def start_remove_explicit_hydrogens_job(
        self, params: dict, *, allowed: set[int] | None, on_done
    ) -> None:
        """Remove explicit hydrogens. ``on_done`` runs after the write."""
        self._start_structure_edit_job(
            "remove",
            source=str(params.get("structure_source") or "").strip(),
            no_render_2d=bool(params.get("no_render_2d")),
            allowed=allowed,
            on_done=on_done,
            title="Remove Explicit Hydrogens",
            progress="Removing explicit hydrogens…",
            queue_label="Remove explicit hydrogens",
        )

    def _enqueue_remove_explicit_hydrogens(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
    ) -> None:
        scope = "selection" if only_selected else "table"
        self.start_remove_explicit_hydrogens_job(
            {"structure_source": src, "no_render_2d": no_render_2d, "row_scope": scope},
            allowed=self._selected_oids_set() if only_selected else None,
            on_done=None,
        )

    def run_neutralize(self) -> None:
        if not self.headers or not self.mols:
            return
        from ..dialogs import NeutralizeDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = NeutralizeDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_neutralize_dialog_accepted(d))
        dlg.show()

    def _on_neutralize_dialog_accepted(self, dlg) -> None:
        from ...workflows.macro_recipe import STEP_NEUTRALIZE
        from ...workflows.macro_record import structure_edit_step
        from ..command_dispatch import dispatch_step

        src, only_selected, no_render_2d = dlg.config()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Neutralize"):
            return
        dispatch_step(
            self,
            structure_edit_step(
                STEP_NEUTRALIZE, src, only_selected=only_selected, no_render_2d=no_render_2d
            ),
            {},
        )

    def start_neutralize_job(
        self,
        params: dict,
        *,
        allowed: set[int] | None,
        on_done,
        rows: list[tuple] | None = None,
    ) -> None:
        """Neutralize structures. ``on_done(error, {"output": column})`` runs after the write."""
        self._start_structure_edit_job(
            "neutralize",
            source=str(params.get("structure_source") or "").strip(),
            no_render_2d=bool(params.get("no_render_2d")),
            allowed=allowed,
            on_done=on_done,
            title="Neutralize",
            progress="Neutralizing structures…",
            queue_label="Neutralize",
            rows=rows,
        )

    def _enqueue_neutralize(
        self,
        src: str,
        *,
        only_selected: bool = False,
        no_render_2d: bool = False,
        rows: list[tuple] | None = None,
        queue_title_prefix: str = "",
    ) -> None:
        """Queue neutralization; *rows* overrides the rows collected from *src*."""
        scope = "selection" if only_selected else "table"
        self.start_neutralize_job(
            {"structure_source": src, "no_render_2d": no_render_2d, "row_scope": scope},
            allowed=self._selected_oids_set() if only_selected else None,
            on_done=None,
            rows=rows,
        )
        if queue_title_prefix:
            self.status_label.setText(f"{queue_title_prefix}neutralize".strip())

    def _start_structure_edit_job(
        self,
        mode: str,
        *,
        source: str,
        no_render_2d: bool,
        allowed: set[int] | None,
        on_done,
        title: str,
        progress: str,
        queue_label: str,
        rows: list[tuple] | None = None,
    ) -> None:
        from PyQt5.QtCore import Qt

        from ..job_signals import StructureEditJobSignals, release_job_signals, retain_job_signals
        from ..macro_recorder import report_unless_replaying

        if not source or source not in self.headers:
            message = "Choose a structure column."
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            report_unless_replaying(self, title, message)
            return
        data = list(rows) if rows is not None else self._structure_tool_inputs(source, allowed)
        if not data:
            message = "No rows match the current scope and structure field."
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            report_unless_replaying(self, title, message, warning=False)
            return
        worker_cls, signal_name = _structure_edit_worker(mode)
        sig = StructureEditJobSignals(self)
        retain_job_signals(self, sig)

        def _finished(
            results, done=on_done, held=sig, src=source, skip_render=no_render_2d
        ) -> None:
            release_job_signals(self, held)
            self._complete_structure_edit(results, src, skip_render, done)

        getattr(sig, signal_name).connect(_finished, Qt.QueuedConnection)
        self.status_label.setText(progress)
        enqueue_process_queue_job(
            self,
            queue_label,
            len(data),
            lambda ev, ps, d=data, s=sig, cls=worker_cls: cls(
                d, s, is_smiles=False, cancel_event=ev, progress_state=ps
            ),
            queue_label=queue_label,
        )

    def _complete_structure_edit(self, results, source: str, no_render_2d: bool, on_done) -> None:
        def _written(_column: str, done=on_done, src=source) -> None:
            if done is None:
                return
            if self.has_partial_results_notice():
                done("Cancelled.", {})
                return
            done(None, {"output": src})

        self._apply_mol_tool_results(
            results,
            src=source,
            no_render_2d=no_render_2d,
            on_written=_written,
        )

    def on_disconnect_fragments_finished(self, results):
        self.table.setSortingEnabled(False)
        src = getattr(self, "_disconnect_source", "Structure")
        update_target = getattr(self, "_disconnect_update_target", True)
        largest_col = getattr(self, "_disconnect_largest_col", src)
        fragments_col = getattr(self, "_disconnect_fragments_col", "Fragments")
        no_render_2d = getattr(self, "_disconnect_no_render_2d", False)
        self._disconnect_source = "Structure"
        self._disconnect_update_target = True
        self._disconnect_largest_col = "Structure"
        self._disconnect_fragments_col = "Fragments"
        self._disconnect_no_render_2d = False

        self._ensure_disconnect_output_column(fragments_col)
        dest = src if update_target else largest_col
        if not update_target:
            self._ensure_disconnect_output_column(largest_col)
            if not no_render_2d and largest_col in self.headers:
                self._table_model.register_pixmap_column(largest_col)

        prepared = [
            (int(oid), bytes(blob), fragments, smiles)
            for oid, blob, fragments, smiles in results
            if blob
        ]
        oids = self._write_tool_structures(
            dest, [(oid, blob, smiles) for oid, blob, _fragments, smiles in prepared]
        )
        fragment_pairs = [(oid, fragments) for oid, _blob, fragments, _smiles in prepared]
        if fragments_col in self.headers:
            self._table_model.set_column_text_by_oids(fragments_col, fragment_pairs)
        self.schedule_calculate_global_bounds()
        self._clear_tool_progress()

        rendered_dest = False
        if not no_render_2d and self._tool_target_renders_2d(dest):
            rendered_dest = self._render_tool_structures(dest, oids, serial=True)
        if (
            not no_render_2d
            and fragments_col
            and fragments_col != dest
            and fragments_col in self.headers
            and fragment_pairs
        ):
            depict = getattr(self, "_queue_generated_structure_renders", None)
            if callable(depict):
                depict(
                    [fragments_col],
                    set(oids),
                    [(oid, {fragments_col: text}) for oid, text in fragment_pairs],
                )
        if rendered_dest:
            return
        self.status_label.setText(self._consume_partial_results_notice() or "Done.")

    def on_neutralize_finished(self, results) -> None:
        src = getattr(self, "_neutralize_source", "Structure")
        no_render_2d = getattr(self, "_neutralize_no_render_2d", False)
        self._neutralize_source = "Structure"
        self._neutralize_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)

    def on_add_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self, "_add_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self, "_add_explicit_hydrogens_no_render_2d", False)
        self._add_explicit_hydrogens_source = "Structure"
        self._add_explicit_hydrogens_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)

    def on_remove_explicit_hydrogens_finished(self, results) -> None:
        src = getattr(self, "_remove_explicit_hydrogens_source", "Structure")
        no_render_2d = getattr(self, "_remove_explicit_hydrogens_no_render_2d", False)
        self._remove_explicit_hydrogens_source = "Structure"
        self._remove_explicit_hydrogens_no_render_2d = False
        self._apply_mol_tool_results(results, src=src, no_render_2d=no_render_2d)


def _structure_edit_worker(mode: str):
    from ...workers import (
        AddExplicitHydrogensWorker,
        NeutralizeWorker,
        RemoveExplicitHydrogensWorker,
    )

    workers = {
        "add": (AddExplicitHydrogensWorker, "explicit_hydrogens_added"),
        "remove": (RemoveExplicitHydrogensWorker, "explicit_hydrogens_removed"),
        "neutralize": (NeutralizeWorker, "neutralized"),
    }
    return workers[mode]
