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

from ...workers.chemistry_descriptors import CalcDescriptorsRequest, CalcWorker
from ..analysis_job_support import enqueue_process_queue_job


class DescriptorsToolsMixin:
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
        from ...descriptors.descriptors_3d import int_fns_need_3d

        disp, fns = d.get_selected()
        src = d.src_combo.currentText()
        is_s = src != "Structure"
        s_idx = self.headers.index(src)
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Calculate Descriptors"):
            return
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        calc_headers = self._result_column_names(disp, oids_list)

        packed_confs, confs_cols, ensemble_db = (
            self._ensemble_inputs_for_descriptor_job(oids_list, src)
            if int_fns_need_3d(fns)
            else ({}, {}, None)
        )
        if not is_s:
            data = self._structure_tool_inputs(src, allowed)
        else:
            data = [
                (o, self._table_cell_text(self.logical_row_for_oid(o), s_idx)) for o in oids_list
            ]
        if not data:
            QMessageBox.information(
                self,
                "Calculate Descriptors",
                "No rows to process for this scope and source.",
            )
            self.status_label.setText("Ready.")
            return

        req = CalcDescriptorsRequest(
            data=data,
            disp_headers=calc_headers,
            int_fns=fns,
            is_smiles=is_s,
            confs_by_idx=packed_confs,
            confs_col_by_idx=confs_cols,
            ensemble_db=ensemble_db,
        )

        enqueue_process_queue_job(
            self,
            "Calculate descriptors",
            len(data),
            lambda ev, ps, request=req: CalcWorker(
                request,
                self.signals,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"Calculate descriptors ({len(data)} rows)",
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
