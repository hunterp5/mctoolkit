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

"""Calculator, potency units, random columns, split/join columns, fingerprint similarity, and diverse subset."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox

from ...platform_support.config import load_config
from ...chem.molecule_conversion import safe_float
from ...workers import CustomCalcWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton
from ..strings import (
    TOOL_CALCULATOR,
    TOOL_JOIN_COLUMNS,
    TOOL_POTENCY,
    TOOL_RANDOM_NUMBER,
    TOOL_SPLIT_COLUMN,
)


class TableCalcMixin:
    def _run_calculator_from_dialog(self, dlg) -> None:
        from ..dialogs import CalculatorDialog

        if not isinstance(dlg, CalculatorDialog):
            return
        self.new_c = dlg.name_input.text().strip()
        if not self.new_c:
            QMessageBox.warning(self, TOOL_CALCULATOR, "Enter a name for the new column.")
            return
        self.new_c = self._unique_table_column_names([self.new_c])[0]
        expr = dlg.expr_input.text().strip()
        if not expr:
            QMessageBox.warning(self, TOOL_CALCULATOR, "Enter an expression to evaluate.")
            return
        only_selected = dlg.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_CALCULATOR):
            return
        numeric_vars = list(self.global_bounds.keys())
        h_map = {h: i for i, h in enumerate(self.headers)}
        oids_list = self._all_oids_in_table_order()
        if allowed is not None:
            oids_list = [o for o in oids_list if o in allowed]
        row_data = [
            (
                o,
                {
                    v: (self._table_cell_text(self.logical_row_for_oid(o), h_map[v]) or "0")
                    for v in numeric_vars
                },
            )
            for o in oids_list
        ]
        if not row_data:
            QMessageBox.information(
                self,
                TOOL_CALCULATOR,
                "No rows to process for this scope.",
            )
            self.status_label.setText("Ready.")
            return
        enqueue_process_queue_job(
            self,
            "Calculator…",
            len(row_data),
            lambda ev, ps, rd=row_data, ex=expr, sigs=self.signals: CustomCalcWorker(
                rd, ex, sigs, cancel_event=ev, progress_state=ps
            ),
            queue_label=f"Calculator ({len(row_data)} rows)",
        )

    def open_random_number_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_RANDOM_NUMBER,
                "Load a table with at least one row first.",
            )
            return
        from ..dialogs import RandomNumberDialog

        d = RandomNumberDialog(len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_random_number_dialog_accepted(dlg))
        d.show()

    def open_random_molecule_dialog(self) -> None:
        from ..dialogs import RandomMoleculeDialog

        d = RandomMoleculeDialog(self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.show()

    def _on_random_number_dialog_accepted(self, d) -> None:
        from ...table.random_number_columns import generate_random_values

        p = d.params()
        col = p.column_name
        if not col:
            QMessageBox.warning(self, TOOL_RANDOM_NUMBER, "Enter a name for the output column.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_RANDOM_NUMBER):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_RANDOM_NUMBER, "No rows to process for this scope.")
            self.status_label.setText("Ready.")
            return
        try:
            values = generate_random_values(len(oids), p.params)
        except ValueError as exc:
            QMessageBox.warning(
                self, TOOL_RANDOM_NUMBER, str(exc) or "Invalid random-number settings."
            )
            return
        rows = [(int(oid), {col: text}) for oid, text in zip(oids, values)]
        written = self.on_calc_finished(rows, [col], progress_label=TOOL_RANDOM_NUMBER)
        final_col = written[0] if written else col
        self.status_label.setText(
            f'{TOOL_RANDOM_NUMBER}: column "{final_col}" updated ({len(rows)} row(s)).'
        )

    def open_calculator(self):
        if not self.headers:
            return
        if load_config().disable_custom_calc:
            QMessageBox.information(
                self,
                TOOL_CALCULATOR,
                "The calculator is disabled by policy (environment variable MOLMANAGER_DISABLE_CUSTOM_CALC).",
            )
            return
        numeric_vars = list(self.global_bounds.keys())
        from ..dialogs import CalculatorDialog

        def _factory():
            d = CalculatorDialog(numeric_vars, len(self._selected_logical_rows()), self)
            d.setModal(False)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            d.apply_requested.connect(lambda dlg=d: self._run_calculator_from_dialog(dlg))
            self._prepare_tool_dialog(d)
            return d

        reuse_or_show_modeless_singleton(
            self,
            "_calculator_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def open_potency_standardization(self):
        if not self.headers:
            return
        numeric_columns = list(self.global_bounds.keys())
        from ..dialogs import PotencyStandardizationDialog

        def _factory():
            dialog = PotencyStandardizationDialog(
                numeric_columns, len(self._selected_logical_rows()), self
            )
            dialog.setModal(False)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            dialog.apply_requested.connect(lambda dlg=dialog: self._run_potency_from_dialog(dlg))
            self._prepare_tool_dialog(dialog)
            return dialog

        reuse_or_show_modeless_singleton(
            self,
            "_potency_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def _run_potency_from_dialog(self, dlg) -> None:
        from ...chem.potency import output_headers, standardize_activity
        from ..dialogs import PotencyStandardizationDialog

        if not isinstance(dlg, PotencyStandardizationDialog):
            return
        request = dlg.pending_request
        if request is None or request.column not in self.headers:
            QMessageBox.warning(self, TOOL_POTENCY, "Choose an activity column from the table.")
            return
        only_selected = dlg.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_POTENCY):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [oid for oid in oids if oid in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_POTENCY, "No rows to process for this scope.")
            return
        activity_col = self.headers.index(request.column)
        headers = output_headers(
            request.measure,
            write_molar=request.write_molar,
            write_p=request.write_p,
            write_ki=request.write_ki,
        )
        substrate_fixed = _fixed_molar(request.substrate_constant, request.substrate_unit)
        km_fixed = _fixed_molar(request.km_constant, request.km_unit)
        rows: list[tuple[int, dict[str, str]]] = []
        for oid in oids:
            row = self.logical_row_for_oid(oid)
            activity = "" if row < 0 else self._table_cell_text(row, activity_col)
            substrate = substrate_fixed
            km = km_fixed
            if request.write_ki and request.substrate_column:
                substrate = _column_molar(
                    self, oid, request.substrate_column, request.substrate_unit, allow_zero=True
                )
            if request.write_ki and request.km_column:
                km = _column_molar(self, oid, request.km_column, request.km_unit, allow_zero=False)
            rows.append(
                (
                    int(oid),
                    standardize_activity(
                        activity,
                        unit=request.unit,
                        measure=request.measure,
                        write_molar=request.write_molar,
                        write_p=request.write_p,
                        write_ki=request.write_ki,
                        substrate_molar=substrate,
                        km_molar=km,
                    ),
                )
            )
        written = self.on_calc_finished(rows, headers, progress_label=TOOL_POTENCY)
        self.status_label.setText(
            f"{TOOL_POTENCY}: wrote {len(written)} column(s) for {len(rows)} row(s)."
        )

    def _ensure_blank_table_headers(self) -> None:
        """Create ID and Structure columns so Add Row/Column work before a file is loaded."""
        if self.headers and self._table_model.columnCount() >= 2:
            return
        self.headers = ["ID_HIDDEN", "Structure"]
        self.table.setSortingEnabled(False)
        self._table_model.clear_rows()
        self._table_model.set_headers(list(self.headers))
        self.table.setColumnHidden(0, True)
        set_stack = getattr(self, "_set_workspace_stack_index", None)
        if callable(set_stack):
            set_stack(1)

    def add_blank_table_row(self, count: int | None = None) -> None:
        """Append empty rows (Data → Table → Add Row). *count* skips the dialog."""
        from ..dialogs.add_table import MAX_ADD_ROWS, AddTableRowsDialog
        from .table_undo_commands import UndoAddBlankRowCommand

        if count is None:
            dlg = AddTableRowsDialog(self)
            if dlg.exec_() != QDialog.Accepted:
                return
            count = dlg.row_count()
        n = max(1, min(MAX_ADD_ROWS, int(count)))
        self._ensure_blank_table_headers()
        self._undo_stack.push(UndoAddBlankRowCommand(self, n))

    def add_blank_table_column(self, name: str | None = None, *, count: int | None = None) -> None:
        """Append empty data columns (Data → Table → Add Column)."""
        from ..dialogs.add_table import MAX_ADD_COLUMNS, AddTableColumnsDialog
        from .table_undo_commands import UndoAddBlankColumnCommand

        if name is None and count is None:
            dlg = AddTableColumnsDialog(self)
            if dlg.exec_() != QDialog.Accepted:
                return
            name = dlg.column_name()
            count = dlg.column_count()
        label = (name or "").strip() or "Column"
        if label in ("ID_HIDDEN", "Structure"):
            QMessageBox.warning(
                self,
                "Add Column",
                "That name is reserved. Choose a different column name.",
            )
            return
        n = 1 if count is None else max(1, min(MAX_ADD_COLUMNS, int(count)))
        self._ensure_blank_table_headers()
        unique = self._unique_table_column_names([label] * n)
        self._undo_stack.push(UndoAddBlankColumnCommand(self, unique))

    def open_split_column_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "Open a file or add rows so the table has a column to split.",
            )
            return
        columns = self._filterable_data_column_names()
        if not columns:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No text columns are available to split.",
            )
            return
        from ..dialogs import SplitColumnDialog

        d = SplitColumnDialog(columns, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_split_column_dialog_accepted(dlg))
        d.show()

    def _on_split_column_dialog_accepted(self, d) -> None:
        from ...table.column_split import (
            MAX_SPLIT_COLUMNS,
            apply_keep_mode,
            output_column_names,
            pad_split_rows,
            split_column_values,
            split_width,
        )

        p = d.params()
        source = p.source_column
        if not source or source not in self.headers:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Choose a column to split.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_SPLIT_COLUMN):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_SPLIT_COLUMN, "No rows to process for this scope.")
            return
        try:
            ci = self.headers.index(source)
        except ValueError:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, "Choose a column to split.")
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
            _delim, parts = split_column_values(texts, p.mode, custom=p.custom)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_SPLIT_COLUMN, str(exc) or "Could not split the column.")
            return
        keep = getattr(p, "keep", "all") or "all"
        if keep in ("largest", "smallest"):
            parts = apply_keep_mode(parts, keep)
        n_cols = split_width(parts)
        if keep == "all" and n_cols < 2:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No split fields were found. Check the separator and try again.",
            )
            return
        if n_cols < 1:
            QMessageBox.information(
                self,
                TOOL_SPLIT_COLUMN,
                "No values were found. Check the separator and try again.",
            )
            return
        truncated = any(len(row) > MAX_SPLIT_COLUMNS for row in parts)
        padded = pad_split_rows(parts, n_cols)
        if keep in ("largest", "smallest"):
            headers = [p.prefix or source]
        else:
            headers = output_column_names(p.prefix or source, n_cols)
        rows = [
            (int(oid), {headers[i]: padded[j][i] for i in range(n_cols)})
            for j, oid in enumerate(oids)
        ]
        written = self.on_calc_finished(rows, headers, progress_label=TOOL_SPLIT_COLUMN)
        extra = f" (capped at {n_cols})" if truncated else ""
        self.status_label.setText(
            f'{TOOL_SPLIT_COLUMN}: {len(written)} column(s) from "{source}"{extra}.'
        )

    def open_join_columns_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                TOOL_JOIN_COLUMNS,
                "Open a file or add rows so the table has columns to join.",
            )
            return
        columns = self._filterable_data_column_names()
        if not columns:
            QMessageBox.information(
                self,
                TOOL_JOIN_COLUMNS,
                "No text columns are available to join.",
            )
            return
        from ..dialogs import JoinColumnsDialog

        d = JoinColumnsDialog(columns, len(self._selected_logical_rows()), self)
        self._prepare_tool_dialog(d)
        d.setAttribute(Qt.WA_DeleteOnClose, True)
        d.accepted.connect(lambda *_, dlg=d: self._on_join_columns_dialog_accepted(dlg))
        d.show()

    def _on_join_columns_dialog_accepted(self, d) -> None:
        from ...table.column_join import join_two_values, resolve_join_delimiter

        p = d.params()
        left = p.left_column
        right = p.right_column
        if not left or left not in self.headers or not right or right not in self.headers:
            QMessageBox.warning(self, TOOL_JOIN_COLUMNS, "Choose two columns to join.")
            return
        only_selected = d.only_selected_rows()
        allowed = self._selected_oids_set() if only_selected else None
        if self._abort_if_only_selected_but_empty(only_selected, allowed, TOOL_JOIN_COLUMNS):
            return
        oids = self._all_oids_in_table_order()
        if allowed is not None:
            oids = [o for o in oids if o in allowed]
        if not oids:
            QMessageBox.information(self, TOOL_JOIN_COLUMNS, "No rows to process for this scope.")
            return
        try:
            delim = resolve_join_delimiter(p.mode, p.custom)
        except ValueError as exc:
            QMessageBox.warning(self, TOOL_JOIN_COLUMNS, str(exc) or "Could not join the columns.")
            return
        try:
            li = self.headers.index(left)
            ri = self.headers.index(right)
        except ValueError:
            QMessageBox.warning(self, TOOL_JOIN_COLUMNS, "Choose two columns to join.")
            return
        out_name = (p.output_column or "").strip() or f"{left}_{right}"

        def _cell(oid: int, header: str, col_idx: int) -> str:
            row = self._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                return ""
            raw = self._table_model.backing_value_for_row_header(row, header) or ""
            if not raw:
                raw = self._table_cell_text(row, col_idx) or ""
            return raw

        rows = [
            (
                int(oid),
                {
                    out_name: join_two_values(
                        _cell(oid, left, li),
                        _cell(oid, right, ri),
                        delim,
                        skip_empty=bool(p.skip_empty),
                    )
                },
            )
            for oid in oids
        ]
        written = self.on_calc_finished(rows, [out_name], progress_label=TOOL_JOIN_COLUMNS)
        final_col = written[0] if written else out_name
        self.status_label.setText(
            f'{TOOL_JOIN_COLUMNS}: column "{final_col}" from "{left}" and "{right}" '
            f"({len(rows)} row(s))."
        )

    def open_fp_similarity(self):
        if not self.headers:
            return
        from ..dialogs import FPSimilarityDialog

        dlg = FPSimilarityDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_fp_similarity_signals(self):
        """Signals on the main window so fingerprint-similarity jobs survive dialog close."""
        sig = getattr(self, "_fp_similarity_signals", None)
        if sig is not None:
            return sig
        from ...workers import FPSimilaritySignals

        sig = FPSimilaritySignals(self)
        sig.finished.connect(self._on_fp_similarity_finished)
        sig.failed.connect(self._on_fp_similarity_failed)
        self._fp_similarity_signals = sig
        return sig

    def _on_fp_similarity_finished(self, rows) -> None:
        ctx = getattr(self, "_fp_similarity_run_ctx", None) or {}
        job_id = ctx.get("job_id")
        self._finish_tool_progress("Fingerprint similarity", job_id=job_id)
        from ..dialogs.fp_similarity import apply_fp_similarity_column

        apply_fp_similarity_column(
            self,
            compare_oids=set(ctx.get("compare_oids") or []),
            column_name=str(ctx.get("pending_column_name") or ""),
            rows=rows,
        )

    def _on_fp_similarity_failed(self, msg: str) -> None:
        from ..analysis_job_support import report_cancellable_job_failure

        ctx = getattr(self, "_fp_similarity_run_ctx", None) or {}
        report_cancellable_job_failure(
            self,
            "Fingerprint Similarity",
            msg,
            progress_label="Fingerprint similarity",
            failure_fallback="Fingerprint similarity failed.",
            cancelled_status="Cancelled.",
            job_id=ctx.get("job_id"),
        )

    def open_diverse_subset(self) -> None:
        if not self.headers:
            return
        from ..dialogs import DiverseSubsetDialog

        dlg = DiverseSubsetDialog(self)
        self._prepare_tool_dialog(dlg)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _ensure_diverse_subset_signals(self):
        """Signals on the main window so diverse subset jobs survive dialog close."""
        sig = getattr(self, "_diverse_subset_signals", None)
        if sig is not None:
            return sig
        from ...workers import DiverseSubsetSignals

        sig = DiverseSubsetSignals(self)
        sig.finished.connect(self._on_diverse_subset_finished)
        sig.failed.connect(self._on_diverse_subset_failed)
        self._diverse_subset_signals = sig
        return sig

    def _on_diverse_subset_finished(
        self, picked_oids: list, column_rows: list, n_cached: int, n_computed: int
    ) -> None:
        from PyQt5.QtCore import QTimer

        self._finish_tool_progress("Diverse subset")
        ctx = getattr(self, "_diverse_subset_run_ctx", None) or {}
        picked = [int(o) for o in (picked_oids or [])]

        def _apply_results() -> None:
            col_name = (ctx.get("pending_column_name") or "").strip()
            if col_name and column_rows:
                m = self._table_model
                nc = m.columnCount()
                self.headers.append(col_name)
                m.insert_column_at(nc, col_name, None)
                try:
                    self.table.setUpdatesEnabled(False)
                except Exception:
                    pass
                try:
                    # Sparse write: only picked ranks (avoid BindingDB-scale full-column fill).
                    m.set_column_text_by_oids(
                        col_name,
                        [(int(oid), str(rank)) for oid, rank in column_rows],
                    )
                    self._sync_global_bounds_for_headers([col_name], refresh_filters=True)
                finally:
                    try:
                        self.table.setUpdatesEnabled(True)
                    except Exception:
                        pass
            # Select after column insert — inserting columns clears Qt selection.
            if ctx.get("select_subset") and picked:
                self.select_table_oids(picked)
            cache_note = ""
            if n_cached or n_computed:
                cache_note = f" ({n_cached} cached fingerprint(s), {n_computed} computed)"
            col_note = f" Column '{col_name}' added." if col_name else ""
            self.status_label.setText(
                f"Diverse subset: picked {len(picked)} compound(s).{cache_note}{col_note}"
            )

        QTimer.singleShot(0, _apply_results)

    def _on_diverse_subset_failed(self, msg: str) -> None:
        self._finish_tool_progress("Diverse subset")
        if msg == "Cancelled.":
            self.status_label.setText("Cancelled.")
        else:
            self.status_label.setText(f"Diverse subset failed: {msg or 'Computation failed.'}")

    def on_custom_calc_finished(self, res):
        # If the expression failed for every row, don't add an all-error column.
        ok_any = False
        for _idx, val in res:
            t = (val or "").strip()
            if safe_float(t) is not None:
                ok_any = True
                break
        if not ok_any:
            QMessageBox.warning(
                self,
                TOOL_CALCULATOR,
                "The expression produced no numeric results (all rows failed). No column was added.",
            )
            self.status_label.setText(f"{TOOL_CALCULATOR}: no numeric results.")
            self._clear_tool_progress()
            return

        self._finish_tool_progress("Calculator…")
        self.on_calc_finished(
            [(int(oid), {self.new_c: str(val)}) for oid, val in res],
            [self.new_c],
            finish_progress=False,
        )
        self.status_label.setText(
            self._consume_partial_results_notice()
            or f'{TOOL_CALCULATOR}: column "{self.new_c}" updated.'
        )


def _fixed_molar(value: float | None, unit: str) -> float | None:
    from ...chem.potency import to_molar

    if value is None:
        return None
    return to_molar(value, unit)


def _column_molar(app, oid: int, column: str, unit: str, *, allow_zero: bool) -> float | None:
    from ...chem.potency import parse_concentration, to_molar

    if column not in app.headers:
        return None
    row = app.logical_row_for_oid(oid)
    if row < 0:
        return None
    value = parse_concentration(
        app._table_cell_text(row, app.headers.index(column)), allow_zero=allow_zero
    )
    if value is None:
        return None
    return to_molar(value, unit)
