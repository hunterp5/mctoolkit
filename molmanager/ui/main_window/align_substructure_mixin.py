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

"""Align structure pictures to an oriented substructure (``WorkspaceTools.structure_prep``)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ...chem.depiction_coords import apply_depiction_coords
from ...chem.substructure_align import partition_alignment_scope
from ..analysis_job_support import enqueue_process_queue_job


class AlignSubstructureMixin:
    def mol_with_stored_depiction(self, mol, oid: int, column: str = "Structure"):
        """Copy *mol* with the stored 2D pose for this row, when the atom count still matches."""
        store = getattr(self, "_depiction_coords", None)
        if store is None or mol is None:
            return mol
        return apply_depiction_coords(mol, store.get(str(column), int(oid)))

    def run_align_substructure(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            return
        from ..dialogs import AlignSubstructureDialog

        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = AlignSubstructureDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_align_substructure_accepted(d))
        dlg.show()

    def _on_align_substructure_accepted(self, dlg) -> None:
        cfg = dlg.config()
        if cfg is None:
            return
        if cfg.action == "reset":
            self._reset_substructure_orientation(cfg.column, cfg.only_selected)
            return
        self._enqueue_substructure_align(cfg)

    def _enqueue_substructure_align(self, cfg) -> None:
        from ...workers import SubstructureAlignWorker

        allowed = self._selected_oids_set() if cfg.only_selected else None
        if self._abort_if_only_selected_but_empty(
            cfg.only_selected, allowed, "Align to Substructure"
        ):
            return
        rows = self._structure_tool_inputs(cfg.column, allowed)
        if not rows:
            QMessageBox.information(
                self,
                "Align to Substructure",
                "No rows match the current scope and structure field.",
            )
            self.status_label.setText("Ready.")
            return
        store = self._depiction_coords
        already = set(store.column_items(cfg.column))
        keep, skipped_existing = partition_alignment_scope(
            [int(row[0]) for row in rows],
            already,
            skip_existing=bool(cfg.skip_existing),
        )
        if not keep:
            self.status_label.setText(f"Aligned 0, skipped {skipped_existing}.")
            return
        keep_set = set(keep)
        data = [row for row in rows if int(row[0]) in keep_set]
        try:
            template_blob = cfg.template.ToBinary()
        except (ValueError, RuntimeError):
            QMessageBox.warning(
                self, "Align to Substructure", "Could not send that query to the alignment job."
            )
            return
        column = cfg.column
        self.status_label.setText("Aligning structures…")
        enqueue_process_queue_job(
            self,
            "Align to Substructure",
            len(data),
            lambda ev, ps, d=data, blob=template_blob, col=column, skipped=skipped_existing, sigs=self.signals: (
                SubstructureAlignWorker(
                    d,
                    blob,
                    column=col,
                    skipped_existing=skipped,
                    signals=sigs,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"Align to Substructure ({len(data)} rows)",
        )

    def on_substructure_aligned(self, payload) -> None:
        self._finish_tool_progress("Align to Substructure", status_message=None)
        data = payload if isinstance(payload, dict) else {}
        column = str(data.get("column") or "Structure")
        aligned = [(int(oid), bytes(blob)) for oid, blob in (data.get("aligned") or []) if blob]
        considered = int(data.get("considered") or 0)
        skipped_existing = int(data.get("skipped_existing") or 0)
        self._depiction_coords.set_many(column, aligned)
        oids = [oid for oid, _blob in aligned]
        self._forget_depiction_pictures(column, oids)
        skipped = max(0, considered - len(aligned)) + skipped_existing
        notice = self._consume_partial_results_notice()
        message = f"Aligned {len(aligned)}, skipped {skipped}."
        if notice:
            message = f"{notice} {message}"
        if oids and self._tool_target_renders_2d(column):
            self.status_label.setText(message)
            if self._render_tool_structures(
                column, oids, queue_title_prefix="Align to Substructure: "
            ):
                return
        self.status_label.setText(message)

    def _reset_substructure_orientation(self, column: str, only_selected: bool) -> None:
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Align to Substructure"):
            return
        rows = self._structure_tool_inputs(column, allowed)
        oids = [int(row[0]) for row in rows]
        cleared = self._depiction_coords.discard_column_oids(column, oids)
        if not cleared:
            self.status_label.setText("No stored orientation in scope.")
            return
        self._forget_depiction_pictures(column, cleared)
        self.status_label.setText(f"Reset orientation for {len(cleared)} row(s).")
        if self._tool_target_renders_2d(column):
            self._render_tool_structures(
                column, cleared, queue_title_prefix="Align to Substructure: "
            )

    def _forget_depiction_pictures(self, column: str, oids: list[int]) -> None:
        if not oids:
            return
        model = self._table_model
        if column == "Structure":
            model.clear_structure_pixmaps_for_oids(oids)
        elif column in self.headers and model.is_pixmap_data_column(column):
            model.clear_column_pixmaps_for_oids(column, oids)
