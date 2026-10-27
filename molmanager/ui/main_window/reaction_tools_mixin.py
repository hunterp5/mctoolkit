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

"""Chemistry → Extract Reaction Info and Structure Enumeration (including reaction enumeration)."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..strings import TOOL_REACTION_ENUMERATION, TOOL_REACTION_EXTRACT, TOOL_RGROUP_ENUMERATION
from ...chem.reaction_extract import (
    DEFAULT_PRODUCT_PREFIX,
    DEFAULT_REACTANT_PREFIX,
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
        from ...workflows.macro_record import extract_step
        from ...workflows.tool_requests import row_scope_from_only_selected
        from ..command_dispatch import dispatch_step

        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_REACTION_EXTRACT):
            return
        dispatch_step(
            self,
            extract_step(d.params(), row_scope_from_only_selected(only_selected)),
            {},
        )

    def start_reaction_extract_job(
        self, params: dict, *, allowed: set[int] | None, on_done
    ) -> None:
        """Split a reaction column. ``on_done(error, {"col_1": header, ...})``.

        Keys are ``col_1``, ``col_2``, … in the order the columns are written, so a
        later step can refer to them after the headers are uniquified.
        """
        from ..macro_recorder import report_unless_replaying

        source = str(params.get("source_column") or "").strip()
        if not source or source not in self.headers:
            self._fail_reaction_extract("Choose a reaction column.", on_done)
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [oid for oid in oids if oid in allowed]
        if not oids:
            message = "No rows to process for this scope."
            self.status_label.setText("Ready.")
            on_done(message, {})
            report_unless_replaying(self, TOOL_REACTION_EXTRACT, message, warning=False)
            return
        try:
            column_index = self.headers.index(source)
        except ValueError:
            self._fail_reaction_extract("Choose a reaction column.", on_done)
            return
        texts = [self._reaction_extract_text(int(oid), source, column_index) for oid in oids]
        try:
            headers, row_dicts = extract_reaction_column_values(
                texts,
                str(params.get("mode") or "both"),
                reactant_prefix=str(params.get("reactant_prefix") or DEFAULT_REACTANT_PREFIX),
                product_prefix=str(params.get("product_prefix") or DEFAULT_PRODUCT_PREFIX),
            )
        except (TypeError, ValueError) as exc:
            self._fail_reaction_extract(str(exc) or "Could not extract that column.", on_done)
            return
        if not headers:
            message = "No reactants or products could be parsed from that column."
            self.status_label.setText("Ready.")
            on_done(message, {})
            report_unless_replaying(self, TOOL_REACTION_EXTRACT, message, warning=False)
            return
        rows = [(int(oid), row_dicts[index]) for index, oid in enumerate(oids)]

        def _after(written: list[str]) -> None:
            self.status_label.setText(
                f'{TOOL_REACTION_EXTRACT}: {len(written)} column(s) from "{source}".'
            )
            if not written:
                on_done("Reaction extract produced no columns.", {})
                return
            outputs = {f"col_{index}": header for index, header in enumerate(written, start=1)}
            on_done(None, outputs)

        self.on_calc_finished(
            rows, headers, progress_label=TOOL_REACTION_EXTRACT, on_complete=_after
        )

    def _reaction_extract_text(self, oid: int, source: str, column_index: int) -> str:
        row = self._table_model.logical_row_for_oid(oid)
        if row < 0:
            return ""
        raw = self._table_model.backing_value_for_row_header(row, source) or ""
        if not raw:
            raw = self._table_cell_text(row, column_index) or ""
        return raw

    def _fail_reaction_extract(self, message: str, on_done) -> None:
        from ..macro_recorder import report_unless_replaying

        self.status_label.setText("Ready.")
        on_done(message, {})
        report_unless_replaying(self, TOOL_REACTION_EXTRACT, message)

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
        from ...workflows.macro_record import reaction_step
        from ..command_dispatch import dispatch_step

        dispatch_step(self, reaction_step(d.params()), {})

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
        from PyQt5.QtCore import Qt

        from ..job_signals import ReactionJobSignals, release_job_signals, retain_job_signals

        bridge = ReactionJobSignals(self)
        retain_job_signals(self, bridge)

        def _finished(result, done=on_done, held=bridge) -> None:
            release_job_signals(self, held)
            self._complete_reaction_enum(result, done)

        def _failed(message, tool_title, done=on_done, held=bridge) -> None:
            release_job_signals(self, held)
            self._fail_reaction_enum(message, tool_title, done)

        bridge.reaction_enum_finished.connect(_finished, Qt.QueuedConnection)
        bridge.reaction_enum_failed.connect(_failed, Qt.QueuedConnection)
        enqueue_process_queue_job(
            self,
            TOOL_REACTION_ENUMERATION,
            request.max_products,
            lambda ev, ps, req=request, sigs=bridge: workers.ReactionEnumerationWorker(
                req,
                TOOL_REACTION_ENUMERATION,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{TOOL_REACTION_ENUMERATION} ({request.reaction_name})",
        )

    def on_reaction_enum_finished(self, result) -> None:
        self._complete_reaction_enum(result, None)

    def _complete_reaction_enum(self, result, on_done) -> None:
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
            if on_done is not None:
                on_done("Cancelled.", {})
            return
        if parts:
            self.status_label.setText(f"{TOOL_REACTION_ENUMERATION}: {', '.join(parts)}{suffix}.")
        elif not result.products:
            self.status_label.setText(
                f"{TOOL_REACTION_ENUMERATION}: no products generated{suffix}."
            )
        if on_done is not None:
            on_done(None, {})

    def on_reaction_enum_failed(self, message: str, tool_title: str) -> None:
        self._fail_reaction_enum(message, tool_title, None)

    def _fail_reaction_enum(self, message: str, tool_title: str, on_done) -> None:
        if message == "Cancelled.":
            self._finish_tool_progress(tool_title)
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            if on_done is not None:
                on_done("Cancelled.", {})
            return
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        text = message or "Reaction enumeration failed."
        if on_done is not None:
            on_done(text, {})
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
        from ...workflows.macro_record import rgroup_step
        from ..command_dispatch import dispatch_step

        dispatch_step(self, rgroup_step(request), {})

    def start_rgroup_enumeration(self, params: dict, on_done=None) -> None:
        """Enumerate *params*. ``on_done(error, {})`` runs when the products are queued."""
        from ...chem.rgroup_enumeration import RGroupEnumerationRequest, RGroupPoolInput
        from ...platform_support.memory_guards import check_product_enumeration

        pools = tuple(
            RGroupPoolInput(
                label=int(pool.get("label") or 0),
                mode=str(pool.get("mode") or "smiles"),
                file_path=str(pool.get("file_path") or ""),
                smiles_text=str(pool.get("smiles_text") or ""),
            )
            for pool in params.get("pools") or []
            if isinstance(pool, dict)
        )
        request = RGroupEnumerationRequest(
            core_smiles=str(params.get("core_smiles") or "").strip(),
            core_id=str(params.get("core_id") or "core").strip() or "core",
            pools=pools,
            max_products=int(params.get("max_products") or 1),
            output_filters=str(params.get("output_filters") or ""),
            add_to_table=bool(params.get("add_to_table", True)),
            save_to_file=bool(params.get("save_to_file", False)),
            save_path=str(params.get("save_path") or "").strip() or None,
        )
        guard = check_product_enumeration(request.max_products)
        if not guard.ok:
            if on_done is not None:
                on_done(guard.message, {})
            else:
                QMessageBox.warning(self, TOOL_RGROUP_ENUMERATION, guard.message)
            return
        from PyQt5.QtCore import Qt

        from ..job_signals import RGroupJobSignals, release_job_signals, retain_job_signals

        bridge = RGroupJobSignals(self)
        retain_job_signals(self, bridge)

        def _finished(result, done=on_done, held=bridge) -> None:
            release_job_signals(self, held)
            self._complete_rgroup_enum(result, done)

        def _failed(message, tool_title, done=on_done, held=bridge) -> None:
            release_job_signals(self, held)
            self._fail_rgroup_enum(message, tool_title, done)

        bridge.rgroup_enum_finished.connect(_finished, Qt.QueuedConnection)
        bridge.rgroup_enum_failed.connect(_failed, Qt.QueuedConnection)
        shown = request.core_id or "core"
        if len(shown) > 48:
            shown = shown[:45] + "..."
        enqueue_process_queue_job(
            self,
            TOOL_RGROUP_ENUMERATION,
            request.max_products,
            lambda ev, ps, req=request, sigs=bridge: workers.RGroupEnumerationWorker(
                req,
                TOOL_RGROUP_ENUMERATION,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{TOOL_RGROUP_ENUMERATION} ({shown})",
        )

    def on_rgroup_enum_finished(self, result) -> None:
        self._complete_rgroup_enum(result, None)

    def _complete_rgroup_enum(self, result, on_done) -> None:
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
            if on_done is not None:
                on_done("Cancelled.", {})
            return
        if parts:
            self.status_label.setText(f"{TOOL_RGROUP_ENUMERATION}: {', '.join(parts)}{suffix}.")
        elif not result.products:
            self.status_label.setText(f"{TOOL_RGROUP_ENUMERATION}: no products generated{suffix}.")
        if on_done is not None:
            on_done(None, {})

    def on_rgroup_enum_failed(self, message: str, tool_title: str) -> None:
        self._fail_rgroup_enum(message, tool_title, None)

    def _fail_rgroup_enum(self, message: str, tool_title: str, on_done) -> None:
        if message == "Cancelled.":
            self._finish_tool_progress(tool_title)
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            if on_done is not None:
                on_done("Cancelled.", {})
            return
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        text = message or "R-group enumeration failed."
        if on_done is not None:
            on_done(text, {})
            return
        QMessageBox.warning(self, tool_title, text)
