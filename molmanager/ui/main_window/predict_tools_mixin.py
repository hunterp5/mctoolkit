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

"""pKa, permeability, SOM, metabolites, and protomer prediction dialogs."""

from __future__ import annotations

import re

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QMessageBox

from ..analysis_job_support import (
    enqueue_process_queue_job,
    ensure_table_ready_for_tool,
    report_cancellable_job_failure,
)
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton
from ..strings import (
    TOOL_PREDICT_METABOLITES,
    TOOL_PREDICT_SOM,
)


def som_map_export_filename(oid: int, header: str = "SOM Map") -> str:
    """Default PNG filename for a SOM Map cell export."""
    stem = re.sub(r"[^\w\-]+", "_", (header or "SOM_Map").strip()).strip("_") or "SOM_Map"
    return f"{stem}_{int(oid)}.png"


def save_som_map_pixmap(pm: QPixmap, path: str) -> str | None:
    """Write *pm* as PNG, appending ``.png`` when needed. Returns the path or ``None``."""
    out = (path or "").strip()
    if not out or pm is None or pm.isNull():
        return None
    if not out.lower().endswith(".png"):
        out += ".png"
    if not pm.save(out, "PNG"):
        return None
    return out


class PredictToolsMixin:
    def _ensure_pka_predictor_signals(self):
        """Signals live on the main window so pKa jobs survive dialog close."""
        sig = getattr(self, "_pka_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import PKaPredictorSignals

        sig = PKaPredictorSignals(self)
        sig.finished.connect(self._on_pka_prediction_finished)
        sig.failed.connect(self._on_pka_prediction_failed)
        self._pka_predictor_signals = sig
        return sig

    def _on_pka_prediction_finished(self, results: list, include_pi: bool = False) -> None:
        table_rows = [(o, t, pi) for o, t, pi in results if o is not None]
        lone = [(t, pi) for o, t, pi in results if o is None]
        if table_rows:
            if include_pi:
                res = [(int(o), {"pKa": text, "pI": pi}) for o, text, pi in table_rows]
                headers = ["pKa", "pI"]
            else:
                res = [(int(o), {"pKa": text}) for o, text, _pi in table_rows]
                headers = ["pKa"]
            self.on_calc_finished(res, headers, progress_label="pKa prediction")
        if lone:
            pka_txt, pi_txt = lone[0]
            msg = f"pKa: {pka_txt}"
            if include_pi:
                msg = f"{msg}\npI: {pi_txt}"
            QMessageBox.information(self, "Predict pKa", msg)
        if not table_rows:
            self._finish_tool_progress("pKa prediction")

    def _on_pka_prediction_failed(self, msg: str) -> None:
        self._finish_tool_progress("pKa prediction")
        QMessageBox.warning(self, "Predict pKa", msg or "Prediction failed.")

    def open_pka_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, "Predict pKa"):
            return
        from ..dialogs import PKaPredictorDialog
        from ..pka_gpu_hint import maybe_remind_unipka_cuda_wheel

        maybe_remind_unipka_cuda_wheel(self)
        dlg = PKaPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_permeability_predictor_signals(self):
        sig = getattr(self, "_permeability_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import PermeabilityPredictorSignals

        sig = PermeabilityPredictorSignals(self)
        sig.finished.connect(self._on_permeability_prediction_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_permeability_prediction_failed, Qt.QueuedConnection)
        self._permeability_predictor_signals = sig
        return sig

    def schedule_permeability_prediction(
        self,
        src: str,
        *,
        only_selected: bool,
        output_columns: tuple[str, ...],
    ) -> None:
        """Gather rows and enqueue prediction on the next event-loop tick (keeps the dialog responsive)."""
        QTimer.singleShot(
            0,
            lambda: self._start_permeability_prediction(src, only_selected, output_columns),
        )

    def _start_permeability_prediction(
        self,
        src: str,
        only_selected: bool,
        output_columns: tuple[str, ...],
    ) -> None:
        from ...workers import PermeabilityPredictorWorker

        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, "Predict Permeability"):
            return
        # Blob-only rows (SDF / sessions with no SMILES column) are valid structures.
        # SMILES are derived on the worker so this snapshot does not hydrate RDKit here.
        payloads = [
            payload
            for payload in self.collect_scoped_table_structure_payloads(
                src, only_selected=only_selected
            )
            if payload.oid is not None and payload.has_structure()
        ]
        if not payloads:
            QMessageBox.information(
                self,
                "Predict Permeability",
                "No valid structures were found for this scope and source.",
            )
            return
        perm_signals = self._ensure_permeability_predictor_signals()
        n = len(payloads)
        enqueue_process_queue_job(
            self,
            "Predict Permeability",
            n,
            lambda ev, ps, r=payloads, ws=self.signals, sig=perm_signals, c=output_columns: (
                PermeabilityPredictorWorker(
                    r, ws, sig, cancel_event=ev, output_columns=c, progress_state=ps
                )
            ),
            queue_label=f"Predict Permeability ({n} rows)",
        )

    def _on_permeability_prediction_finished(self, results: list) -> None:
        if not results:
            self._finish_tool_progress("Predict Permeability")
            return
        calc_h = list(results[0][1].keys())
        res = [(oid, row_d) for oid, row_d in results]
        self.on_calc_finished(res, calc_h, progress_label="Predict Permeability")

    def _on_permeability_prediction_failed(self, msg: str) -> None:
        self._finish_tool_progress("Predict Permeability")
        QMessageBox.warning(self, "Predict Permeability", msg or "Prediction failed.")

    def open_permeability_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, "Predict Permeability"):
            return
        from ..dialogs import PermeabilityPredictorDialog

        dlg = PermeabilityPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_som_predictor_signals(self):
        sig = getattr(self, "_som_predictor_signals", None)
        if sig is not None:
            return sig
        from ...workers import SomPredictorSignals

        sig = SomPredictorSignals(self)
        sig.finished.connect(self._on_som_prediction_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_som_prediction_failed, Qt.QueuedConnection)
        self._som_predictor_signals = sig
        return sig

    def _host_unavailable(self) -> bool:
        try:
            from PyQt5 import sip

            if sip.isdeleted(self):
                return True
        except Exception:
            return True
        try:
            from ...workers.process_pool_utils import application_is_shutting_down

            return bool(application_is_shutting_down())
        except Exception:
            return False

    def _on_som_prediction_finished(self, results: list) -> None:
        if self._host_unavailable():
            return
        from ..som_browser import records_from_worker_rows

        table_rows = [row for row in results if row and row[0] is not None]
        if table_rows:
            calc_h = list(table_rows[0][4]) if table_rows[0][4] else list(table_rows[0][1].keys())
            res = [(int(oid), cols) for oid, cols, _png, _atoms, _headers in table_rows]
            self.on_calc_finished(
                res,
                calc_h,
                progress_label=TOOL_PREDICT_SOM,
                on_complete=lambda cols, rows=table_rows: self._apply_som_map_pixmaps(cols, rows),
            )
        else:
            self._finish_tool_progress(TOOL_PREDICT_SOM)

        records = records_from_worker_rows(results)
        if records:
            self._som_browse_records = list(records)
            self._sync_predict_viewer_actions()
            self._open_som_browser(records)
        elif not table_rows:
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "No sites of metabolism were returned.",
            )
        if not table_rows:
            notice = self._consume_partial_results_notice()
            if notice:
                self.status_label.setText(notice)

    def _apply_som_map_pixmaps(self, written: list[str], table_rows: list) -> None:
        from ...predictions.som_prediction import SOM_MAP_COLUMN
        from ...table.structure_depiction_layout import (
            structure_depict_height,
            structure_depict_width,
        )
        from ...table.structure_image import pixmap_from_structure_image

        map_col = written[0] if written else SOM_MAP_COLUMN
        if map_col in self.headers:
            self._table_model.register_pixmap_column(map_col)
        dw, dh = structure_depict_width(), structure_depict_height()
        last_pm = None
        for oid, _cols, png, _atoms, _headers in table_rows:
            if not png:
                continue
            pm = pixmap_from_structure_image(png, dw, dh)
            if pm is not None and not pm.isNull():
                self._table_model.set_column_pixmap(int(oid), map_col, pm)
                last_pm = pm
                view_row = self._resolve_structure_row_for_oid(int(oid))
                if view_row != -1:
                    need_h = max(dh, int(pm.height()))
                    if int(self.table.rowHeight(view_row)) < need_h:
                        self.table.setRowHeight(int(view_row), need_h)
        sync_w = getattr(self, "_sync_data_pixmap_column_width", None)
        if callable(sync_w) and last_pm is not None:
            sync_w(map_col, last_pm, dw)

    def _on_som_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_som_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._som_browser_dialog = None

    def _discard_stale_som_browser_dialog(self) -> None:
        dlg = getattr(self, "_som_browser_dialog", None)
        if dlg is None:
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(dlg) or getattr(dlg, "_panel", None) is None:
                self._som_browser_dialog = None
                try:
                    dlg.close()
                    dlg.deleteLater()
                except RuntimeError:
                    pass
        except Exception:
            self._som_browser_dialog = None

    def _open_som_browser(self, records, *, focus_oid: int | None = None) -> None:
        from ..som_browser import SomBrowserDialog, SomBrowserWidget

        if self._host_unavailable():
            return
        self._som_browse_records = list(records or [])
        self._discard_stale_som_browser_dialog()
        if focus_oid is None:
            self.reveal_first_selected_row(focus=False)

        def _focus(widget) -> None:
            if widget is None or focus_oid is None:
                return
            jump = getattr(widget, "jump_to_oid", None)
            if callable(jump):
                jump(int(focus_oid))

        for w in self.iter_docked_plot_widgets():
            if isinstance(w, SomBrowserWidget):
                mgr = self._workspace()
                if mgr is not None:
                    pane = mgr.pane_for_widget(w)
                    if pane is not None:
                        mgr.set_preferred_pane(pane)
                self.show_docked_plot_panel()
                w.set_records(records)
                _focus(w)
                w.raise_()
                self.status_label.setText(f"{TOOL_PREDICT_SOM}: focused in workspace pane.")
                return

        def _factory():
            dlg = SomBrowserDialog(self)
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))
            return dlg

        def _on_reused(dlg):
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))

        reuse_or_show_modeless_singleton(
            self,
            "_som_browser_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def open_som_browser_for_oid(self, oid: int | None) -> None:
        """Open the Predict SOM browser focused on one table row."""
        from ..som_browser import records_from_table

        records = list(getattr(self, "_som_browse_records", None) or ())
        missing = oid is not None and not any(r.oid == int(oid) for r in records)
        if not records or missing:
            table_recs = records_from_table(self)
            if table_recs:
                records = table_recs
                self._som_browse_records = list(records)
        if not records:
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "No SOM maps to browse. Run Predict SOM first.",
            )
            return
        self._open_som_browser(records, focus_oid=oid)

    def open_som_viewer(self) -> None:
        """Open the SOM map browser from the Predict → SOM → Viewer menu."""
        self.open_som_browser_for_oid(None)

    def _has_som_viewer_data(self) -> bool:
        if getattr(self, "_som_browse_records", None):
            return True
        from ...predictions.som_prediction import is_som_map_header

        return any(is_som_map_header(h) for h in (self.headers or []))

    def _has_metabolite_viewer_data(self) -> bool:
        if getattr(self, "_metabolite_browse_records", None):
            return True
        from ...predictions.biotransformer_metabolites import (
            METABOLITE_COUNT_COLUMN,
            METABOLITE_SMILES_COLUMN,
            is_metabolite_column_header,
        )

        headers = list(self.headers or [])
        return any(
            is_metabolite_column_header(h, METABOLITE_SMILES_COLUMN)
            or is_metabolite_column_header(h, METABOLITE_COUNT_COLUMN)
            for h in headers
        )

    def _sync_predict_viewer_actions(self) -> None:
        som_act = getattr(self, "_act_som_viewer", None)
        if som_act is not None:
            try:
                som_act.setEnabled(self._has_som_viewer_data())
            except RuntimeError:
                pass
        met_act = getattr(self, "_act_metabolite_viewer", None)
        if met_act is not None:
            try:
                met_act.setEnabled(self._has_metabolite_viewer_data())
            except RuntimeError:
                pass

    def export_som_map_for_oid(self, oid: int, header: str) -> None:
        """Save the SOM Map cell image for one table row."""
        from PyQt5.QtWidgets import QFileDialog

        pm = self._table_model.column_pixmap_copy(int(oid), header)
        if pm is None or pm.isNull():
            QMessageBox.information(
                self,
                TOOL_PREDICT_SOM,
                "This cell has no SOM map image to export.",
            )
            return
        suggested = som_map_export_filename(int(oid), header)
        path, _sel = QFileDialog.getSaveFileName(
            self,
            "Export SOM Map",
            suggested,
            "PNG image (*.png);;All files (*.*)",
        )
        if not path:
            return
        written = save_som_map_pixmap(pm, path)
        if not written:
            QMessageBox.warning(self, TOOL_PREDICT_SOM, "Could not save the SOM map image.")
            return
        self.status_label.setText(f"Exported SOM map to {written}")

    def _on_som_prediction_failed(self, msg: str) -> None:
        if self._host_unavailable():
            return
        report_cancellable_job_failure(
            self,
            TOOL_PREDICT_SOM,
            msg,
            progress_label=TOOL_PREDICT_SOM,
            failure_fallback="Prediction failed.",
        )

    def open_som_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, TOOL_PREDICT_SOM):
            return
        from ..dialogs import SomPredictorDialog

        dlg = SomPredictorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_biotransformer_signals(self):
        sig = getattr(self, "_biotransformer_signals", None)
        if sig is not None:
            return sig
        from ...workers import BiotransformerSignals

        sig = BiotransformerSignals(self)
        sig.finished.connect(self._on_biotransformer_finished, Qt.QueuedConnection)
        sig.failed.connect(self._on_biotransformer_failed, Qt.QueuedConnection)
        self._biotransformer_signals = sig
        return sig

    def _on_biotransformer_finished(self, results: list) -> None:
        if self._host_unavailable():
            return
        from ..metabolite_browser import records_from_worker_rows

        table_rows = [row for row in results if row and row[0] is not None]
        add_as_rows = bool(results[0][4]) if results else False
        if table_rows:
            calc_h = list(table_rows[0][3]) if table_rows[0][3] else list(table_rows[0][1].keys())
            res = [(int(oid), cols) for oid, cols, _hits, _headers, _add, _smi in table_rows]
            self.on_calc_finished(res, calc_h, progress_label=TOOL_PREDICT_METABOLITES)
        else:
            self._finish_tool_progress(TOOL_PREDICT_METABOLITES)

        if add_as_rows:
            extra: list[tuple[str, dict[str, str]]] = []
            for row in results:
                if not row or len(row) < 6:
                    continue
                parent_smi = str(row[5] or "")
                parent_id = "" if row[0] is None else str(row[0])
                for hit in row[2] or ():
                    smi = str((hit or {}).get("smiles") or "").strip()
                    if not smi:
                        continue
                    gen = hit.get("generation")
                    extra.append(
                        (
                            smi,
                            {
                                "Parent ID": parent_id,
                                "Parent SMILES": parent_smi,
                                "Reaction": str(hit.get("reaction") or ""),
                                "Enzyme": str(hit.get("enzyme") or ""),
                                "Generation": "" if gen is None else str(gen),
                                "Enumeration_Method": "BioTransformer",
                            },
                        )
                    )
            if extra:
                self.add_rows_from_external_records_batch(extra, render_structures=True)

        records = records_from_worker_rows(results)
        if records:
            self._metabolite_browse_records = list(records)
            self._sync_predict_viewer_actions()
            self._open_metabolite_browser(records)
        elif not table_rows:
            QMessageBox.information(
                self,
                TOOL_PREDICT_METABOLITES,
                "No metabolites were returned.",
            )
        if not table_rows:
            notice = self._consume_partial_results_notice()
            if notice:
                self.status_label.setText(notice)

    def _on_metabolite_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_metabolite_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._metabolite_browser_dialog = None

    def _discard_stale_metabolite_browser_dialog(self) -> None:
        dlg = getattr(self, "_metabolite_browser_dialog", None)
        if dlg is None:
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(dlg) or getattr(dlg, "_panel", None) is None:
                self._metabolite_browser_dialog = None
                try:
                    dlg.close()
                    dlg.deleteLater()
                except RuntimeError:
                    pass
        except Exception:
            self._metabolite_browser_dialog = None

    def _open_metabolite_browser(self, records, *, focus_oid: int | None = None) -> None:
        from ..metabolite_browser import MetaboliteBrowserDialog, MetaboliteBrowserWidget

        if self._host_unavailable():
            return
        if not records:
            return
        self._metabolite_browse_records = list(records)
        self._discard_stale_metabolite_browser_dialog()
        if focus_oid is None:
            self.reveal_first_selected_row(focus=False)

        def _focus(widget) -> None:
            if widget is None or focus_oid is None:
                return
            jump = getattr(widget, "jump_to_oid", None)
            if callable(jump):
                jump(int(focus_oid))

        for w in self.iter_docked_plot_widgets():
            if isinstance(w, MetaboliteBrowserWidget):
                mgr = self._workspace()
                if mgr is not None:
                    pane = mgr.pane_for_widget(w)
                    if pane is not None:
                        mgr.set_preferred_pane(pane)
                self.show_docked_plot_panel()
                w.set_records(records)
                _focus(w)
                w.raise_()
                self.status_label.setText(f"{TOOL_PREDICT_METABOLITES}: focused in workspace pane.")
                return

        def _factory():
            dlg = MetaboliteBrowserDialog(self)
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))
            return dlg

        def _on_reused(dlg):
            dlg.set_records(records)
            _focus(getattr(dlg, "_panel", None))

        reuse_or_show_modeless_singleton(
            self,
            "_metabolite_browser_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def open_metabolite_viewer(self) -> None:
        """Open the metabolite browser from the Predict → Metabolites → Viewer menu."""
        from ..metabolite_browser import records_from_table

        records = list(getattr(self, "_metabolite_browse_records", None) or ())
        if not records:
            table_recs = records_from_table(self)
            if table_recs:
                records = table_recs
                self._metabolite_browse_records = list(records)
        if not records:
            QMessageBox.information(
                self,
                TOOL_PREDICT_METABOLITES,
                "No metabolite predictions to browse. Run Predict Metabolites first.",
            )
            return
        self._open_metabolite_browser(records)

    def _on_biotransformer_failed(self, msg: str) -> None:
        if self._host_unavailable():
            return
        report_cancellable_job_failure(
            self,
            TOOL_PREDICT_METABOLITES,
            msg,
            progress_label=TOOL_PREDICT_METABOLITES,
            failure_fallback="Prediction failed.",
        )

    def open_biotransformer_predictor(self) -> None:
        if not ensure_table_ready_for_tool(self, TOOL_PREDICT_METABOLITES):
            return
        from ..dialogs import BiotransformerDialog

        dlg = BiotransformerDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_protomer_generator(self) -> None:
        if not ensure_table_ready_for_tool(self, "Generate Protomers"):
            return
        from ..dialogs import ProtomerGeneratorDialog
        from ..pka_gpu_hint import maybe_remind_unipka_cuda_wheel

        maybe_remind_unipka_cuda_wheel(self)
        dlg = ProtomerGeneratorDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
