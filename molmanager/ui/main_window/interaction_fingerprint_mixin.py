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

"""Interaction fingerprint tool window (Protein menu)."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox
from rdkit import Chem

from ...conformers.conformer_output import iter_single_conformer_mols
from ...docking.pose_file_io import is_poses_header
from ...protein.interaction_fingerprint import fingerprint_headers
from ...protein.protein_interactions import prolif_available
from ..analysis_job_support import (
    enqueue_process_queue_job,
    ensure_table_ready_for_tool,
    report_cancellable_job_failure,
    show_activity_tool_dialog,
)
from ..strings import TOOL_INTERACTION_FINGERPRINT
from ..table_dataframe import scoped_table_analysis_row_indices
from .conformer_writeback import mol_for_ensemble_column


class InteractionFingerprintMixin:
    """Fingerprint the first stored pose of each row against a receptor file."""

    def open_interaction_fingerprint(self) -> None:
        if not ensure_table_ready_for_tool(
            self,
            TOOL_INTERACTION_FINGERPRINT,
            require_rows=True,
            empty_message="Load a table with docked poses first.",
        ):
            return
        if not prolif_available():
            QMessageBox.warning(
                self,
                TOOL_INTERACTION_FINGERPRINT,
                "Interaction fingerprints need ProLIF. Install it with: pip install prolif",
            )
            return
        pose_columns = [name for name in self.headers if is_poses_header(name)]
        if not pose_columns:
            QMessageBox.warning(
                self,
                TOOL_INTERACTION_FINGERPRINT,
                "No poses column is on the table. Dock a ligand or import packed poses first.",
            )
            return
        snap = getattr(self, "_last_dock_results", None) or {}
        receptor = str(snap.get("receptor_path") or "").strip()
        from ..dialogs.interaction_fingerprint import InteractionFingerprintDialog

        dialog = InteractionFingerprintDialog(
            pose_columns=pose_columns,
            receptor_path=receptor,
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        show_activity_tool_dialog(
            self,
            dialog,
            on_accepted=self._on_interaction_fingerprint_accepted,
        )

    def _on_interaction_fingerprint_accepted(self, dialog) -> None:
        params = dialog.params()
        rows = scoped_table_analysis_row_indices(
            self,
            visible_only=True,
            only_selected=params.only_selected,
        )
        if not rows:
            QMessageBox.information(
                self,
                TOOL_INTERACTION_FINGERPRINT,
                "No rows to fingerprint for this scope.",
            )
            return
        poses: list[tuple[int, Chem.Mol | None]] = []
        for row_index in rows:
            oid = int(self._table_model.row_oid(row_index))
            packed = mol_for_ensemble_column(self, oid, params.pose_column, min_conformers=1)
            pose = None
            if packed is not None:
                singles = iter_single_conformer_mols(packed)
                if singles:
                    pose = singles[0]
            poses.append((oid, pose))
        fp_header, residue_header = fingerprint_headers(params.column_prefix)
        poses = self._filter_rows_for_resume(poses, [fp_header, residue_header])
        from ...workers.interaction_fingerprint import InteractionFingerprintWorker

        def _make_worker(cancel_event, progress_state):
            return InteractionFingerprintWorker(
                poses,
                receptor_path=params.receptor_path,
                fingerprint_header=fp_header,
                residues_header=residue_header,
                signals=self.signals,
                cancel_event=cancel_event,
                progress_state=progress_state,
            )

        enqueue_process_queue_job(
            self,
            TOOL_INTERACTION_FINGERPRINT,
            len(poses),
            _make_worker,
        )

    def on_ifp_finished(self, result) -> None:
        rows = [
            (
                int(row.oid),
                {
                    result.fingerprint_header: row.fingerprint,
                    result.residues_header: row.residues,
                },
            )
            for row in result.rows
        ]
        if not rows:
            self.status_label.setText("Interaction fingerprint: no rows written.")
            return
        n_contacts = sum(1 for row in result.rows if row.fingerprint not in {"", "N/A"})
        missing = int(result.n_missing_pose)
        extra = f", {missing} without a pose" if missing else ""
        status = f"Interaction fingerprint: {n_contacts} row(s) with contacts{extra}."
        if result.cancelled:
            status = f"Interaction fingerprint cancelled. {status}"

        def _set_status(_headers: list[str]) -> None:
            self.status_label.setText(status)

        self.on_calc_finished(
            rows,
            [result.fingerprint_header, result.residues_header],
            progress_label=TOOL_INTERACTION_FINGERPRINT,
            on_complete=_set_status,
        )

    def on_ifp_failed(self, message: str) -> None:
        report_cancellable_job_failure(
            self,
            TOOL_INTERACTION_FINGERPRINT,
            message,
            progress_label=TOOL_INTERACTION_FINGERPRINT,
            failure_fallback="Interaction fingerprint failed.",
        )
