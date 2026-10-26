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

"""Chemistry → Reaction (extract components, reaction enumeration) and R-group enumeration."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..strings import TOOL_REACTION_ENUMERATION, TOOL_REACTION_EXTRACT, TOOL_RGROUP_ENUMERATION
from ...chem.reaction_extract import (
    extract_reaction_column_values,
    preferred_reaction_source_column,
)
from ...chem.reaction_file_io import reaction_smarts_from_app_selection
from ... import workers
from ..analysis_job_support import enqueue_process_queue_job

logger = logging.getLogger(__name__)


class ReactionToolsMixin:
    def open_reaction_extract(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_REACTION_EXTRACT,
                "Open a file or add rows so the table has a reaction column to extract from.",
            )
            return
        columns = self._filterable_data_column_names()
        if not columns:
            QMessageBox.information(
                self,
                TOOL_REACTION_EXTRACT,
                "No text columns are available to extract from.",
            )
            return
        from ..dialogs import ReactionExtractDialog

        d = ReactionExtractDialog(
            columns,
            len(self._selected_logical_rows()),
            self,
            default_column=preferred_reaction_source_column(self.headers),
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_reaction_extract_dialog_accepted(dlg))
        d.show()

    def _on_reaction_extract_dialog_accepted(self, d) -> None:
        p = d.params()
        source = p.source_column
        if not source or source not in self.headers:
            QMessageBox.warning(self, TOOL_REACTION_EXTRACT, "Choose a reaction column.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_REACTION_EXTRACT):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(
                self, TOOL_REACTION_EXTRACT, "No rows to process for this scope."
            )
            return
        try:
            ci = self.headers.index(source)
        except ValueError:
            QMessageBox.warning(self, TOOL_REACTION_EXTRACT, "Choose a reaction column.")
            return
        texts: list[str] = []
        for oid in oids:
            row = self._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                texts.append("")
                continue
            raw = self._table_model.backing_value_for_row_header(row, source) or ""
            if not raw:
                raw = self._table_cell_text(row, ci) or ""
            texts.append(raw)
        try:
            headers, row_dicts = extract_reaction_column_values(
                texts,
                p.mode,
                reactant_prefix=p.reactant_prefix,
                product_prefix=p.product_prefix,
            )
        except ValueError as exc:
            QMessageBox.warning(
                self, TOOL_REACTION_EXTRACT, str(exc) or "Could not extract that column."
            )
            return
        if not headers:
            QMessageBox.information(
                self,
                TOOL_REACTION_EXTRACT,
                "No reactants or products could be parsed from that column.",
            )
            return
        rows = [(int(oid), row_dicts[j]) for j, oid in enumerate(oids)]
        written = self.on_calc_finished(rows, headers, progress_label=TOOL_REACTION_EXTRACT)
        self.status_label.setText(
            f'{TOOL_REACTION_EXTRACT}: {len(written)} column(s) from "{source}".'
        )

    def open_reaction_enumeration(self) -> None:
        from ..dialogs import ReactionEnumerationDialog

        d = ReactionEnumerationDialog(
            parent=self,
            initial_smarts=reaction_smarts_from_app_selection(self),
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_reaction_enumeration_dialog_accepted(dlg))
        d.show()

    def _on_reaction_enumeration_dialog_accepted(self, d) -> None:
        self.start_reaction_enumeration(d.params(), on_done=None)

    def start_reaction_enumeration(self, request, on_done=None) -> None:
        """Enumerate *request*. ``on_done(error, {})`` runs when the job finishes.

        The dialog passes ``on_done=None`` and keeps its warning boxes.
        """
        from ...platform_support.memory_guards import check_product_enumeration

        guard = check_product_enumeration(request.max_products)
        if not guard.ok:
            if on_done is not None:
                on_done(guard.message, {})
            else:
                QMessageBox.warning(self, TOOL_REACTION_ENUMERATION, guard.message)
            return
        self._macro_reaction_done = on_done
        enqueue_process_queue_job(
            self,
            TOOL_REACTION_ENUMERATION,
            request.max_products,
            lambda ev, ps, req=request, sigs=self.signals: workers.ReactionEnumerationWorker(
                req,
                TOOL_REACTION_ENUMERATION,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{TOOL_REACTION_ENUMERATION} ({request.reaction_name})",
        )

    def on_reaction_enum_finished(self, result) -> None:
        done = getattr(self, "_macro_reaction_done", None)
        self._macro_reaction_done = None
        self._finish_tool_progress(TOOL_REACTION_ENUMERATION)
        parts: list[str] = []
        if result.add_to_table and result.products:
            records = [
                (
                    str(smi),
                    {
                        "Reaction": str(result.reaction_name or ""),
                        "Enumeration_Method": "Reaction",
                    },
                )
                for smi in result.products
                if (smi or "").strip()
            ]
            n = self.add_rows_from_external_records_batch(records, render_structures=True)
            parts.append(f"added {n:,} row(s) to table")
        if result.save_to_file and result.save_path:
            parts.append(f"wrote {int(result.written_count):,} structure(s) to {result.save_path}")
        suffix = ""
        if int(result.skipped) > 0:
            suffix = f" ({int(result.skipped):,} outcome(s) skipped by constraints or duplicates)"
        if self.has_partial_results_notice():
            if done is not None:
                done("Cancelled.", {})
            return
        if parts:
            self.status_label.setText(f"{TOOL_REACTION_ENUMERATION}: {', '.join(parts)}{suffix}.")
        elif not result.products:
            self.status_label.setText(
                f"{TOOL_REACTION_ENUMERATION}: no products generated{suffix}."
            )
        if done is not None:
            done(None, {})

    def on_reaction_enum_failed(self, message: str, tool_title: str) -> None:
        done = getattr(self, "_macro_reaction_done", None)
        self._macro_reaction_done = None
        if message == "Cancelled.":
            self._finish_tool_progress(tool_title)
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            if done is not None:
                done("Cancelled.", {})
            return
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        text = message or "Reaction enumeration failed."
        if done is not None:
            done(text, {})
            return
        QMessageBox.warning(self, tool_title, text)

    def open_rgroup_enumeration(self) -> None:
        from ..dialogs import RGroupEnumerationDialog

        dialog = RGroupEnumerationDialog(parent=self)
        self._prepare_tool_dialog(dialog)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.accepted.connect(
            lambda *_, dlg=dialog: self._on_rgroup_enumeration_dialog_accepted(dlg)
        )
        dialog.show()

    def _on_rgroup_enumeration_dialog_accepted(self, dialog) -> None:
        try:
            request = dialog.request()
        except ValueError as exc:
            QMessageBox.warning(
                self, TOOL_RGROUP_ENUMERATION, str(exc) or "Check the core and lists."
            )
            return
        from ...platform_support.memory_guards import check_product_enumeration

        guard = check_product_enumeration(request.max_products)
        if not guard.ok:
            QMessageBox.warning(self, TOOL_RGROUP_ENUMERATION, guard.message)
            return
        shown = request.core_id or "core"
        if len(shown) > 48:
            shown = shown[:45] + "..."
        enqueue_process_queue_job(
            self,
            TOOL_RGROUP_ENUMERATION,
            request.max_products,
            lambda ev, ps, req=request, sigs=self.signals: workers.RGroupEnumerationWorker(
                req,
                TOOL_RGROUP_ENUMERATION,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{TOOL_RGROUP_ENUMERATION} ({shown})",
        )

    def on_rgroup_enum_finished(self, result) -> None:
        self._finish_tool_progress(TOOL_RGROUP_ENUMERATION)
        parts: list[str] = []
        if result.add_to_table and result.products:
            records = [
                (str(product.smiles), product.field_map())
                for product in result.products
                if (product.smiles or "").strip()
            ]
            added = self.add_rows_from_external_records_batch(records, render_structures=True)
            parts.append(f"added {added:,} row(s) to table")
        if result.save_to_file and result.save_path:
            parts.append(f"wrote {int(result.written_count):,} structure(s) to {result.save_path}")
        suffix = ""
        if int(result.skipped) > 0:
            suffix = f" ({int(result.skipped):,} outcome(s) skipped by constraints or duplicates)"
        if self.has_partial_results_notice():
            return
        if parts:
            self.status_label.setText(f"{TOOL_RGROUP_ENUMERATION}: {', '.join(parts)}{suffix}.")
        elif not result.products:
            self.status_label.setText(f"{TOOL_RGROUP_ENUMERATION}: no products generated{suffix}.")

    def on_rgroup_enum_failed(self, message: str, tool_title: str) -> None:
        if message == "Cancelled.":
            self._finish_tool_progress(tool_title)
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            return
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, tool_title, message or "R-group enumeration failed.")
