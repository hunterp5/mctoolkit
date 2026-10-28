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


"""Descriptor calculation dialogs (writeback is ``TableWriteService`` / ``ColumnWriteMixin``)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMessageBox,
)

from ... import workers
from ..analysis_job_support import enqueue_process_queue_job
from ..strings import TOOL_BEMIS_MURCKO, TOOL_COMMON_CORE

# ``allowed`` omitted means "use only_selected". None means every row.
_MISSING_ROW_SCOPE = object()


class DescriptorsToolsMixin:
    def _on_calculated_results(self, res, calc_h) -> None:
        """Write calculated columns from the shared worker signals."""
        self._apply_calculated_results(res, calc_h, listener=None)

    def _apply_calculated_results(self, res, calc_h, listener) -> None:
        """Write *res*, then call *listener* with the headers that landed.

        *listener* belongs to one descriptor job. Shared signals (Murcko,
        common core, a dialog run) pass None.
        """

        def _after_write(written: list[str]) -> None:
            if listener is not None:
                listener(written)

        self.on_calc_finished(res, calc_h, on_complete=_after_write)

    def _on_common_core_failed(self, message: str) -> None:
        self._finish_tool_progress(TOOL_COMMON_CORE)
        text = message or "Common core search failed."
        if text == "Cancelled.":
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            return
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, TOOL_COMMON_CORE, text)

    def open_bemis_murcko(self) -> None:
        if not self.headers:
            return
        from ..dialogs import BemisMurckoDialog

        sources = self.chemistry_tool_structure_sources()
        dialog = BemisMurckoDialog(sources, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(dialog)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.accepted.connect(lambda *_, dlg=dialog: self._on_bemis_murcko_accepted(dlg))
        dialog.show()

    def _on_bemis_murcko_accepted(self, dialog) -> None:
        headers, keys = dialog.get_selected()
        if not headers:
            return
        src = dialog.src_combo.currentText()
        rows = self._rows_for_structure_column_job(
            src, dialog.only_selected_rows(), TOOL_BEMIS_MURCKO
        )
        if rows is None:
            return
        data, oids_list, is_text = rows
        self._enqueue_column_calc(
            title=TOOL_BEMIS_MURCKO,
            data=data,
            disp_headers=self._result_column_names(headers, oids_list),
            int_fns=keys,
            is_text=is_text,
        )

    def open_common_core(self) -> None:
        if not self.headers:
            return
        from ..dialogs import CommonCoreDialog

        sources = self.chemistry_tool_structure_sources()
        dialog = CommonCoreDialog(sources, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(dialog)
        dialog.setAttribute(Qt.WA_DeleteOnClose, True)
        dialog.accepted.connect(lambda *_, dlg=dialog: self._on_common_core_accepted(dlg))
        dialog.show()

    def _on_common_core_accepted(self, dialog) -> None:
        params = dialog.params()
        rows = self._rows_for_structure_column_job(
            params.structure_source, dialog.only_selected_rows(), TOOL_COMMON_CORE
        )
        if rows is None:
            return
        data, _oids, _is_text = rows
        if len(data) < 2:
            QMessageBox.information(
                self,
                TOOL_COMMON_CORE,
                "Common core needs at least two structures.",
            )
            self.status_label.setText("Ready.")
            return
        enqueue_process_queue_job(
            self,
            TOOL_COMMON_CORE,
            len(data),
            lambda ev, ps, payload=data, opts=params: workers.CommonCoreWorker(
                payload,
                outliers=opts.outliers,
                complete_rings=opts.complete_rings,
                timeout=opts.timeout,
                signals=self.signals,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{TOOL_COMMON_CORE} ({len(data)} rows)",
        )

    def open_calc(self):
        if not self.headers:
            return
        from ..dialogs import PropertyDialog

        desc_src_cols = self.chemistry_tool_structure_sources()
        d = PropertyDialog(desc_src_cols, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_calc_descriptors_dialog_accepted(dlg))
        d.show()

    def _on_calc_descriptors_dialog_accepted(self, d) -> None:
        from ...workflows.macro_recipe import ROW_SCOPE_SELECTION

        request = d.request()
        only_selected = request.row_scope == ROW_SCOPE_SELECTION
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Calculate Descriptors"):
            return
        from ...workflows.macro_record import descriptor_step
        from ..command_dispatch import dispatch_step

        dispatch_step(self, descriptor_step(request), {})

    def start_descriptor_calculation(
        self,
        request,
        *,
        allowed: set[int] | None,
        on_done,
        title: str = "Calculate descriptors",
    ) -> None:
        """Calculate *keys* for *allowed* rows (``None`` means every row).

        *on_done* is ``(error, outputs)`` where outputs maps each internal key to
        the column header that was written. The dialog passes ``None``.
        """
        from ...descriptors.descriptors_3d import int_fns_need_3d
        from ...workflows.macro_recipe import descriptor_display_by_key

        source = request.structure_source
        keys = list(request.keys)
        displays = list(request.displays) or None
        clean_keys = [str(key).strip() for key in keys if str(key).strip()]
        if on_done is not None and not clean_keys:
            on_done("Choose at least one descriptor.", {})
            return
        if displays is None:
            catalog = descriptor_display_by_key()
            missing = [key for key in clean_keys if key not in catalog]
            if missing:
                message = f"Unknown descriptor {missing[0]}."
                if on_done is not None:
                    on_done(message, {})
                else:
                    QMessageBox.warning(self, title, message)
                return
            displays = [catalog[key] for key in clean_keys]
        if source not in self.headers:
            message = f'Column "{source}" is not in the table.'
            if on_done is not None:
                on_done(message, {})
            else:
                QMessageBox.warning(self, title, message)
                self.status_label.setText("Ready.")
            return
        rows = self._rows_for_structure_column_job(
            source,
            False,
            title,
            allowed=allowed,
            notify=on_done is None,
        )
        if rows is None:
            if on_done is not None:
                on_done("No rows to process for this scope and source.", {})
            return
        data, oids_list, is_text = rows
        calc_headers = self._result_column_names(displays, oids_list)
        need_coords = int_fns_need_3d(clean_keys)
        packed_confs, confs_cols, ensemble_db = (
            self._ensemble_inputs_for_descriptor_job(oids_list, source)
            if need_coords
            else ({}, {}, None)
        )

        def _listen(written: list[str], bound=list(clean_keys), done=on_done) -> None:
            if done is None:
                return
            outputs = {
                str(key): str(header) for key, header in zip(bound, written) if key and header
            }
            if bound and not outputs:
                done("Descriptors produced no columns.", {})
                return
            done(None, outputs)

        signals = None
        if on_done is not None:
            from PyQt5.QtCore import Qt

            from ..job_signals import (
                DescriptorJobSignals,
                release_job_signals,
                retain_job_signals,
            )

            signals = DescriptorJobSignals(self)
            retain_job_signals(self, signals)

            def _slot(res, headers, listen=_listen, bridge=signals) -> None:
                release_job_signals(self, bridge)
                self._apply_calculated_results(res, headers, listen)

            signals.calculated.connect(_slot, Qt.QueuedConnection)
        self._enqueue_column_calc(
            title=title,
            data=data,
            disp_headers=calc_headers,
            int_fns=clean_keys,
            is_text=is_text,
            confs_by_idx=packed_confs,
            confs_col_by_idx=confs_cols,
            ensemble_db=ensemble_db,
            signals=signals,
        )

    def _rows_for_structure_column_job(
        self,
        src: str,
        only_selected: bool,
        title: str,
        *,
        allowed=_MISSING_ROW_SCOPE,
        notify: bool = True,
    ):
        """Return ``(row inputs, oids, text source)`` or None when the job should not start.

        A text source is any column other than Structure: those cells are parsed as
        molecule text. Structure uses the stored molecule.

        *allowed* overrides *only_selected* when it is passed. ``None`` means every
        row. Omit it to keep the dialog's selected-rows checkbox.
        """
        if src not in self.headers:
            if notify:
                QMessageBox.warning(self, title, f'Column "{src}" is not in the table.')
            self.status_label.setText("Ready.")
            return None
        is_text = src != "Structure"
        s_idx = self.headers.index(src)
        if allowed is _MISSING_ROW_SCOPE:
            allowed_set = self._selected_oids_set() if only_selected else None
            if self._abort_if_only_selected_but_empty(only_selected, allowed_set, title):
                return None
        else:
            allowed_set = None if allowed is None else {int(oid) for oid in allowed}
            if allowed_set is not None and not allowed_set:
                if notify:
                    QMessageBox.information(
                        self,
                        title,
                        "No rows to process for this scope and source.",
                    )
                self.status_label.setText("Ready.")
                return None
        oids_list = self._all_oids_in_table_order()
        if allowed_set is not None:
            oids_list = [o for o in oids_list if o in allowed_set]
        if not is_text:
            data = self._structure_tool_inputs(src, allowed_set)
        else:
            from ..table_reader_view import WindowTableReader

            reader = WindowTableReader(self)
            data = [
                (oid, reader.cell_text(reader.row_for_oid(oid), s_idx) or "") for oid in oids_list
            ]
        if not data:
            if notify:
                QMessageBox.information(
                    self,
                    title,
                    "No rows to process for this scope and source.",
                )
            self.status_label.setText("Ready.")
            return None
        return data, oids_list, is_text

    def _enqueue_column_calc(
        self,
        *,
        title: str,
        data,
        disp_headers,
        int_fns,
        is_text: bool,
        confs_by_idx=None,
        confs_col_by_idx=None,
        ensemble_db=None,
        signals=None,
    ) -> None:
        data = self._filter_rows_for_resume(data, disp_headers)
        req = workers.CalcDescriptorsRequest(
            data=data,
            disp_headers=disp_headers,
            int_fns=int_fns,
            is_smiles=is_text,
            confs_by_idx=confs_by_idx,
            confs_col_by_idx=confs_col_by_idx,
            ensemble_db=ensemble_db,
            progress_label=title,
        )
        worker_signals = self.signals if signals is None else signals
        enqueue_process_queue_job(
            self,
            title,
            len(data),
            lambda ev, ps, request=req, sigs=worker_signals: workers.CalcWorker(
                request,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"{title} ({len(data)} rows)",
        )

    def _ensemble_inputs_for_descriptor_job(
        self, oids, src: str
    ) -> tuple[dict[int, str], dict[int, str], str | None]:
        """Packed-cell fallback map, column map, and ensemble DB path for 3D descriptors."""
        from ...conformers.conformer_column_codec import (
            rehydrate_v1_confs_cell,
            unpack_confs_blocks_json_b64,
        )
        from ...storage import EnsembleStore, ensemble_db_path

        preferred: list[str] = []
        src_h = (src or "").strip()
        if src_h in ("confs", "superpose") and src_h in self.headers:
            preferred.append(src_h)
        for col in ("confs", "superpose"):
            if col not in preferred and col in self.headers:
                preferred.append(col)
        if not preferred:
            return {}, {}, None
        sc = getattr(self, "_confs_blocks_sidecar", None)
        db = str(ensemble_db_path(self) or "") or None
        packed: dict[int, str] = {}
        cols: dict[int, str] = {}
        mapping = sc if sc is not None else {}
        for oid in oids:
            r = self.logical_row_for_oid(int(oid))
            if r < 0:
                continue
            for col in preferred:
                if isinstance(sc, EnsembleStore) and (int(oid), col) in sc:
                    cols[int(oid)] = col
                    break
                raw = self._table_model.backing_value_for_row_header(r, col)
                full = rehydrate_v1_confs_cell(raw, col, int(oid), mapping)
                if unpack_confs_blocks_json_b64(full):
                    packed[int(oid)] = full
                    break
        return packed, cols, db
