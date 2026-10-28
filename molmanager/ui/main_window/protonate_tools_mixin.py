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

"""Protomer generation adapter bound on ``WorkspaceTools.structure_prep`` (not a window base)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..analysis_job_support import enqueue_process_queue_job


class ProtonateToolsMixin:
    def run_protonate(self) -> None:
        """Generate dominant protomer into a new column and optionally render it."""
        if not self.headers or self._table_model.rowCount() == 0:
            return
        from ..dialogs import ProtonateDialog
        from ..pka_gpu_hint import maybe_remind_unipka_cuda_wheel

        maybe_remind_unipka_cuda_wheel(self)
        candidates = self.chemistry_tool_structure_sources()
        n_sel = len(self._selected_logical_rows())
        dlg = ProtonateDialog(candidates, n_sel, self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.accepted.connect(lambda *_, d=dlg: self._on_protonate_dialog_accepted(d))
        dlg.show()

    def _on_protonate_dialog_accepted(self, dlg) -> None:
        from ...workflows.macro_recipe import ROW_SCOPE_SELECTION

        request = dlg.request()
        only_selected = request.row_scope == ROW_SCOPE_SELECTION
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Protonate"):
            return
        from ...workflows.macro_record import protonate_step
        from ..command_dispatch import dispatch_step

        dispatch_step(self, protonate_step(request), {})

    def start_protonate_job(self, request, *, allowed: set[int] | None, on_done) -> None:
        """Write the dominant protomer. ``on_done(error, outputs)`` maps output, percent, and pka.

        *allowed* ``None`` uses every row. The dialog passes ``on_done=None``.
        """
        from ...workers.protonate_worker import ProtonateWorker, protomer_percent_column_name

        source = request.structure_source
        ph = float(request.ph)
        output_column = request.output_column
        render_2d = bool(request.render_2d)
        out_col = (output_column or "").strip() or "Protonated"
        if source not in getattr(self, "headers", []):
            message = f'Column "{source}" is not in the table.'
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            else:
                QMessageBox.warning(self, "Protonate", message)
            return
        data = self._filter_rows_for_resume(
            self._structure_tool_inputs(source, allowed),
            [out_col, protomer_percent_column_name(float(ph))],
        )
        if not data:
            message = "No rows match the current scope and structure field."
            self.status_label.setText("Ready.")
            if on_done is not None:
                on_done(message, {})
            else:
                QMessageBox.information(self, "Protonate", message)
            return

        from PyQt5.QtCore import Qt

        from ..job_signals import ProtonateJobSignals, release_job_signals, retain_job_signals

        ctx = {
            "out_col": out_col,
            "ph": float(ph),
            "render_2d": bool(render_2d),
            "allowed_oids": set(oid for oid, _ in data),
        }
        sig = ProtonateJobSignals(self)
        retain_job_signals(self, sig)

        def _finished(rows, context=ctx, done=on_done, held=sig) -> None:
            release_job_signals(self, held)
            self._complete_protonate_job(rows, context, done)

        def _failed(msg, done=on_done, held=sig) -> None:
            release_job_signals(self, held)
            self._fail_protonate_job(msg, done)

        sig.finished.connect(_finished, Qt.QueuedConnection)
        sig.failed.connect(_failed, Qt.QueuedConnection)
        n = len(data)
        enqueue_process_queue_job(
            self,
            "Protonate",
            n,
            lambda ev, ps, r=data, ph=ph, s=sig, ws=self.signals: ProtonateWorker(
                r,
                ph,
                signals=s,
                cancel_event=ev,
                progress_state=ps,
                worker_signals=ws,
                progress_message="Protonate",
            ),
            queue_label=f"Protonate ({n} molecules)",
        )

    def _notify_protonate_done(
        self, on_done, error: str | None, written: list[str] | None = None
    ) -> None:
        if on_done is None:
            return
        if error:
            on_done(error, {})
            return
        headers = [str(header) for header in (written or []) if header]
        outputs: dict[str, str] = {}
        if headers:
            outputs["output"] = headers[0]
        if len(headers) > 1:
            outputs["percent"] = headers[1]
        if len(headers) > 2:
            outputs["pka"] = headers[2]
        on_done(None, outputs)

    def _complete_protonate_job(self, rows: list, ctx: dict, on_done) -> None:
        from ...workers.protonate_worker import protomer_percent_column_name

        out_col = str(ctx.get("out_col") or "Protonated")
        pct_col = protomer_percent_column_name(float(ctx.get("ph", 7.4)))
        render_2d = bool(ctx.get("render_2d"))

        if not rows:
            self._finish_tool_progress("Protonate")
            self.status_label.setText(
                self._consume_partial_results_notice() or "Protonate: no results."
            )
            self._notify_protonate_done(on_done, "Protonate produced no results.")
            return

        res = []
        for row in rows:
            oid, smi, pct, pka = row[0], row[1], row[2], row[3]
            pka_text = str(pka or "").strip() or "N/A"
            res.append(
                (
                    int(oid),
                    {
                        out_col: str(smi),
                        pct_col: f"{float(pct):.2f}",
                        "pKa": pka_text,
                    },
                )
            )

        def _after(cols: list[str], done=on_done) -> None:
            self.status_label.setText(f"Protonate: wrote {out_col}, the population, and pKa.")
            self._notify_protonate_done(done, None, cols)

        self.on_calc_finished(
            res,
            [out_col, pct_col, "pKa"],
            progress_label="Protonate",
            on_complete=_after,
            depict_structures=render_2d,
        )

    def _fail_protonate_job(self, msg: str, on_done) -> None:
        self._finish_tool_progress("Protonate")
        if msg == "Cancelled.":
            self.status_label.setText(self._consume_partial_results_notice() or "Cancelled.")
            self._notify_protonate_done(on_done, "Cancelled.")
        else:
            text = msg or "Computation failed."
            self.status_label.setText(f"Protonate failed: {text}")
            self._notify_protonate_done(on_done, text)
