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

"""BRICS/RECAP/R-group fragment tools."""

from __future__ import annotations

import logging

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QMessageBox,
)

from ..strings import (
    TOOL_BRICS_DECOMP,
    TOOL_BRICS_RECOMP,
    TOOL_CORE_DECOMP,
    TOOL_RECAP_DECOMP,
    TOOL_RECAP_RECOMP,
)
from ...chem.structure_payload import oid_mol_rows_from_payloads
from ...table.structure_depiction_layout import structure_depict_height, structure_depict_width
from ... import workers
from ..analysis_job_support import enqueue_process_queue_job

logger = logging.getLogger(__name__)


class FragmentToolsMixin:
    def open_core_based_decomposition(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_CORE_DECOMP,
                "Load a table with at least one row first.",
            )
            return
        candidates = self.chemistry_tool_structure_sources()
        from ..dialogs import CoreBasedDecompositionDialog

        d = CoreBasedDecompositionDialog(candidates, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_core_based_decomposition_dialog_accepted(dlg))
        d.show()

    def _on_core_based_decomposition_dialog_accepted(self, d) -> None:
        p = d.params()
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_CORE_DECOMP):
            return
        src = p.structure_source
        payloads = self.collect_scoped_table_structure_payloads(src, only_selected=only_selected)
        if not payloads:
            QMessageBox.information(
                self,
                TOOL_CORE_DECOMP,
                "No valid structures were found for the selected source and scope.",
            )
            self.status_label.setText("Ready.")
            return
        enqueue_process_queue_job(
            self,
            "Core-based decomposition",
            len(payloads),
            lambda ev, ps, dt=payloads, pp=p, sigs=self.signals: workers.RGroupDecompositionWorker(
                oid_mol_rows_from_payloads(dt),
                pp.core_query,
                pp.column_prefix,
                pp.only_match_at_r_groups,
                pp.remove_hydrogens_post_match,
                pp.matching,
                sigs,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"Core-based decomposition ({len(payloads)} rows)",
        )

    def on_rgroup_decomp_finished(self, res, col_headers: list) -> None:
        self.on_calc_finished(res, col_headers, progress_label=TOOL_CORE_DECOMP)

    def on_rgroup_decomp_failed(self, message: str) -> None:
        self._clear_tool_progress()
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, TOOL_CORE_DECOMP, message or "Core-based decomposition failed.")

    def open_brics_decomposition(self) -> None:
        self._open_fragment_decomposition_dialog(
            method="brics",
            window_title=TOOL_BRICS_DECOMP,
            default_prefix="BRICS",
        )

    def open_recap_decomposition(self) -> None:
        self._open_fragment_decomposition_dialog(
            method="recap",
            window_title=TOOL_RECAP_DECOMP,
            default_prefix="RECAP",
        )

    def _open_fragment_decomposition_dialog(
        self,
        *,
        method: str,
        window_title: str,
        default_prefix: str,
    ) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                window_title,
                "Load a table with at least one row first.",
            )
            return
        from ..dialogs import FragmentDecompositionDialog

        d = FragmentDecompositionDialog(
            window_title=window_title,
            default_prefix=default_prefix,
            method=method,
            structure_sources=self.chemistry_tool_structure_sources(),
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_fragment_decomposition_dialog_accepted(dlg))
        d.show()

    def _on_fragment_decomposition_dialog_accepted(self, d) -> None:
        p = d.params()
        only_selected = d.only_selected_rows()
        if self._abort_if_only_selected_but_empty(
            only_selected, self._selected_oids_set(), p.tool_title
        ):
            return
        data = self.collect_scoped_table_structure_payloads(
            p.structure_source, only_selected=only_selected
        )
        if not data:
            QMessageBox.information(
                self,
                p.tool_title,
                "No valid structures were found for the selected source and scope.",
            )
            self.status_label.setText("Ready.")
            return
        prefix = p.column_prefix or ("BRICS" if p.method == "brics" else "RECAP")
        method = "brics" if p.method == "brics" else "recap"
        self._fragment_decomp_render_2d_after = bool(getattr(p, "render_2d", False))
        enqueue_process_queue_job(
            self,
            p.tool_title,
            len(data),
            lambda ev, ps, dt=data, m=method, pref=prefix, title=p.tool_title, sigs=self.signals: (
                workers.FragmentDecompositionWorker(
                    oid_mol_rows_from_payloads(dt),
                    m,
                    pref,
                    title,
                    sigs,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"{p.tool_title} ({len(data)} rows)",
        )

    def on_fragment_decomp_finished(self, res, col_headers: list, tool_title: str) -> None:
        self._finish_tool_progress(tool_title)
        self.on_calc_finished(
            res,
            col_headers,
            finish_progress=False,
            on_complete=lambda cols, t=tool_title: self._fragment_decomp_maybe_render(cols, t),
        )

    def _fragment_decomp_maybe_render(self, written: list[str], tool_title: str) -> None:
        do_render = bool(getattr(self, "_fragment_decomp_render_2d_after", False))
        self._fragment_decomp_render_2d_after = False
        # Optionally render new fragment SMILES columns so the user can see the pieces immediately.
        # Uses pixmap-only columns (hide SMILES text) and queues the renders so the GUI stays responsive.
        if do_render and tool_title in (TOOL_BRICS_DECOMP, TOOL_RECAP_DECOMP) and written:
            try:
                base_w, base_h = structure_depict_width(), structure_depict_height()
                for h in written:
                    if h not in self.headers:
                        continue
                    renders, row_by_oid = self._build_render2d_tasks_in_table_order(
                        h, base_w, base_h, None
                    )
                    if renders:
                        self._start_render_2d_batch(
                            renders,
                            row_by_oid,
                            h,
                            column_pixmap_mode=True,
                            queue_title_prefix=f"{tool_title}: ",
                        )
            except Exception:
                logger.exception("Fragment decomposition: auto 2D render failed")

    def on_fragment_decomp_failed(self, message: str, tool_title: str) -> None:
        self._clear_tool_progress()
        self._fragment_decomp_render_2d_after = False
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, tool_title, message or "Fragment decomposition failed.")

    def open_brics_recomposition(self) -> None:
        self._open_fragment_recomposition_dialog(
            method="brics",
            window_title=TOOL_BRICS_RECOMP,
            default_prefix="BRICS",
        )

    def open_recap_recomposition(self) -> None:
        self._open_fragment_recomposition_dialog(
            method="recap",
            window_title=TOOL_RECAP_RECOMP,
            default_prefix="RECAP",
        )

    def _open_fragment_recomposition_dialog(
        self,
        *,
        method: str,
        window_title: str,
        default_prefix: str,
    ) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                window_title,
                "Load a table with fragment columns from decomposition first.",
            )
            return
        from ..dialogs import FragmentRecompositionDialog

        d = FragmentRecompositionDialog(
            window_title=window_title,
            default_prefix=default_prefix,
            method=method,
            table_headers=list(self.headers),
            selected_row_count=len(self._selected_logical_rows()),
            parent=self,
        )
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_fragment_recomposition_dialog_accepted(dlg))
        d.show()

    def _collect_fragment_smiles_for_prefix(
        self,
        prefix: str,
        *,
        only_selected: bool,
    ) -> list[str]:
        from ...chem.fragment_decomposition import fragment_columns_for_prefix

        cols = fragment_columns_for_prefix(self.headers, prefix)
        if not cols:
            return []
        allowed = self._selected_oids_set() if only_selected else None
        col_idx = {h: self.headers.index(h) for h in cols}
        out: list[str] = []
        for r in range(self._table_model.rowCount()):
            t0 = self._table_model.cell_text(r, 0)
            if not t0.isdigit():
                continue
            oid = int(t0)
            if allowed is not None and oid not in allowed:
                continue
            for h in cols:
                raw = self._table_cell_text(r, col_idx[h])
                if not raw:
                    raw = self._table_model.backing_value_for_row_header(r, h) or ""
                if raw:
                    out.append(str(raw).strip())
        return out

    def _on_fragment_recomposition_dialog_accepted(self, d) -> None:
        p = d.params()
        from ...platform_support.memory_guards import check_product_enumeration

        guard = check_product_enumeration(p.max_products)
        if not guard.ok:
            QMessageBox.warning(self, p.tool_title, guard.message)
            return
        only_selected = d.only_selected_rows()
        if self._abort_if_only_selected_but_empty(
            only_selected, self._selected_oids_set(), p.tool_title
        ):
            return
        fragments = self._collect_fragment_smiles_for_prefix(
            p.column_prefix, only_selected=only_selected
        )
        if not fragments:
            QMessageBox.information(
                self,
                p.tool_title,
                f"No fragment SMILES found in columns matching “{p.column_prefix}_1”, “{p.column_prefix}_2”, …",
            )
            self.status_label.setText("Ready.")
            return
        method = "brics" if p.method == "brics" else "recap"
        enqueue_process_queue_job(
            self,
            p.tool_title,
            p.max_products,
            lambda ev, ps, fr=fragments, pp=p, m=method, sigs=self.signals: (
                workers.FragmentRecompositionWorker(
                    fr,
                    m,
                    pp.max_depth,
                    pp.max_products,
                    pp.tool_title,
                    sigs,
                    output_filters=pp.output_filters,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"{p.tool_title} ({len(fragments)} fragments)",
        )

    def on_fragment_recomp_finished(
        self, products: list, tool_title: str, skipped: int = 0
    ) -> None:
        self._finish_tool_progress(tool_title)
        method_label = "BRICS" if "BRICS" in tool_title.upper() else "RECAP"
        records = [
            (str(smi), {"Recompose_Method": method_label})
            for smi in products
            if (smi or "").strip()
        ]
        n = self.add_rows_from_external_records_batch(records, render_structures=True)
        suffix = ""
        if skipped > 0:
            suffix = f" ({skipped:,} assembly candidate(s) skipped by constraints)"
        if self.has_partial_results_notice():
            return
        self.status_label.setText(f"{tool_title}: added {n:,} product row(s){suffix}.")

    def on_fragment_recomp_failed(self, message: str, tool_title: str) -> None:
        if message == "Cancelled.":
            self._finish_tool_progress(tool_title)
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            return
        self.status_label.setText("Ready.")
        QMessageBox.warning(self, tool_title, message or "Fragment recomposition failed.")
