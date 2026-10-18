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

from __future__ import annotations

import uuid

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ...platform_support.config import load_config
from ...plotting.plot_radar import resolve_entry_row_oid
from ...chem.molecule_conversion import parse_molecule_from_cell_text
from ...chem.structure_payload import mol_from_payload, mols_from_payloads
from ...workers import (
    FPSimilarityWorker,
    SIMILARITY_FP_TYPE_LABELS,
    SIMILARITY_METRIC_LABELS,
)
from ..strings import COLUMN_TANIMOTO_SIMILARITY
from ..chunked_table_write import ChunkedTableWriter
from ..qt_widget_utils import make_window_minimizable
from ..analysis_job_support import enqueue_fast_process_queue_job
from .scope import selection_scope_checked

_DEFAULT_METRIC = "Tanimoto"


class FPSimilarityDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Fingerprint Similarity")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._compare_oids: set[int] = set()
        self._pending_column_name = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(6)

        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        root.addLayout(form)

        self.src_combo = QComboBox()
        self._refresh_structure_sources()
        form.addRow("Structure source:", self.src_combo)

        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        form.addRow("Fingerprint:", self.fp_combo)

        self.metric_combo = QComboBox()
        self.metric_combo.addItems(SIMILARITY_METRIC_LABELS)
        form.addRow("Similarity metric:", self.metric_combo)

        self.column_name_edit = QLineEdit()
        self.column_name_edit.setPlaceholderText("Column name in table")
        self._sync_default_column_name()
        self.metric_combo.currentTextChanged.connect(self._sync_default_column_name)
        form.addRow("Output column:", self.column_name_edit)

        query_row = QHBoxLayout()
        self.query_combo = QComboBox()
        self.query_combo.addItems(["From Table Row", "SMILES Input"])
        query_row.addWidget(self.query_combo)
        self.row_input = QLineEdit()
        self.row_input.setPlaceholderText("Row ID (OID or row number)")
        self.row_input.setToolTip("Table OID or 1-based row number.")
        query_row.addWidget(self.row_input, 1)
        self.smi_input = QLineEdit()
        self.smi_input.setPlaceholderText("Enter SMILES")
        self.smi_input.setVisible(False)
        query_row.addWidget(self.smi_input, 1)
        form.addRow("Query:", query_row)

        self.only_selected_cb = QCheckBox("Only compare to selected rows")
        self._only_selected_scope_prefix = "Only compare to selected rows"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)

        btn_row = QHBoxLayout()
        self.compute_btn = QPushButton("Compute and Add Column")
        self.compute_btn.clicked.connect(self.compute)
        btn_row.addWidget(self.compute_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self.query_combo.currentIndexChanged.connect(self._toggle_query_mode)
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _default_column_base(self) -> str:
        metric = self.metric_combo.currentText().strip() or _DEFAULT_METRIC
        if metric == _DEFAULT_METRIC:
            return COLUMN_TANIMOTO_SIMILARITY
        return f"{metric} Similarity"

    def _sync_default_column_name(self, *_args) -> None:
        if self.column_name_edit.text().strip():
            return
        self.column_name_edit.setText(self._default_column_base())

    def _toggle_query_mode(self, idx: int) -> None:
        from_table = idx == 0
        self.row_input.setVisible(from_table)
        self.smi_input.setVisible(not from_table)

    def _unique_column_name(self, base: str) -> str:
        name = (base or "").strip() or self._default_column_base()
        if name not in self.parent_app.headers:
            return name
        cnt = 1
        while f"{name} ({cnt})" in self.parent_app.headers:
            cnt += 1
        return f"{name} ({cnt})"

    def _compare_oids_in_scope(self, only_selected: bool) -> set[int]:
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        oids: set[int] = set()
        m = self.parent_app._table_model
        for r in range(m.rowCount()):
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue
            oids.add(oid)
        return oids

    def _resolve_query_oid(self) -> int | None:
        app = self.parent_app
        return resolve_entry_row_oid(
            self.row_input.text(),
            model=app._table_model,
            row_for_oid=app.logical_row_for_oid,
        )

    def _query_mol_and_oid(self, src: str) -> tuple[object | None, int | None]:
        if self.query_combo.currentIndex() == 0:
            qid = self._resolve_query_oid()
            if qid is None:
                return None, None
            payloads = self.parent_app.collect_scoped_table_structure_payloads(
                src, only_selected=False
            )
            for payload in payloads:
                if payload.oid == qid:
                    return mol_from_payload(payload), qid
            return None, qid
        smi = self.smi_input.text().strip()
        if not smi:
            return None, None
        return parse_molecule_from_cell_text(smi), None

    def compute(self) -> None:
        fp_choice = self.fp_combo.currentText()
        metric = self.metric_combo.currentText().strip() or _DEFAULT_METRIC
        src = self.src_combo.currentText()
        only_sel = selection_scope_checked(self)
        if only_sel and not self.parent_app._selected_oids_set():
            self.parent_app.status_label.setText(
                "Fingerprint similarity: \u201cOnly compare to selected rows\u201d "
                "is checked but nothing is selected."
            )
            return

        qmol, _qid = self._query_mol_and_oid(src)
        if qmol is None:
            if self.query_combo.currentIndex() == 0:
                self.parent_app.status_label.setText(
                    "Fingerprint similarity: enter a valid row ID (OID or row number)."
                )
            else:
                self.parent_app.status_label.setText(
                    "Fingerprint similarity: could not parse query SMILES."
                )
            return

        compare_oids = self._compare_oids_in_scope(only_sel)
        payloads = self.parent_app.collect_scoped_table_structure_payloads(
            src, only_selected=only_sel
        )

        if not compare_oids:
            self.parent_app.status_label.setText(
                "Fingerprint similarity: no rows in scope for comparison."
            )
            return

        self._compare_oids = compare_oids
        self._pending_column_name = self._unique_column_name(self.column_name_edit.text())
        app = self.parent_app
        app._fp_similarity_run_ctx = {
            "compare_oids": set(compare_oids),
            "pending_column_name": self._pending_column_name,
        }
        sig = app._ensure_fp_similarity_signals()
        n_targets = len(payloads)
        app._fp_similarity_run_ctx["job_id"] = enqueue_fast_process_queue_job(
            app,
            "Fingerprint similarity",
            max(1, n_targets + 1),
            lambda ev, ps, q=qmol, t=payloads, c=fp_choice, m=metric, s=sig: FPSimilarityWorker(
                q,
                mols_from_payloads(t),
                c,
                s,
                metric=m,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label="Fingerprint similarity",
        )
        self.close()


def apply_fp_similarity_column(app, *, compare_oids: set[int], column_name: str, rows) -> None:
    """Write fingerprint-similarity scores into a new table column."""
    name = (column_name or "").strip()
    if not name:
        return
    success = {oid: f"{sim:.4f}" for oid, sim, _ in (rows or [])}
    oid_map = {oid: success.get(oid, "N/A") for oid in compare_oids}
    model = app._table_model
    app.headers.append(name)
    model.insert_column_at(model.columnCount(), name, None)

    n_rows = model.rowCount()
    n_scored = len(success)
    n_na = len(compare_oids) - n_scored
    cfg = load_config()
    chunked = n_rows >= max(500, int(cfg.tool_table_chunk_rows))

    def write_chunk(start: int, end: int, is_last: bool) -> None:
        model.fill_column_from_oid_map(
            name,
            oid_map,
            default="",
            start_row=start,
            end_row=end,
            emit=True,
            rebuild_color=is_last,
        )

    def on_done() -> None:
        app._sync_global_bounds_for_headers([name], refresh_filters=True)
        if chunked:
            app._finish_tool_progress("Writing results", status_message=None, job_id=write_job_id)
        app.status_label.setText(f"Added '{name}' with {n_scored} score(s); {n_na} N/A in scope")

    writer = getattr(app, "_fp_similarity_writer", None)
    if writer is not None:
        writer.cancel()
    write_job_id = str(uuid.uuid4())[:8] if chunked else None
    writer = ChunkedTableWriter(
        table=app.table,
        total=n_rows,
        chunk=max(250, int(cfg.ingest_gui_chunk_size)) if chunked else max(1, n_rows),
        write_chunk=write_chunk,
        on_progress=(
            (
                lambda done, total, jid=write_job_id: app._tool_progress_state.update(
                    "Writing results…", done, total, job_id=jid
                )
            )
            if chunked
            else None
        ),
        on_done=on_done,
        should_continue=lambda: True,
    )
    app._fp_similarity_writer = writer
    if chunked:
        app._begin_tool_progress("Writing results", n_rows, job_id=write_job_id)
        writer.start()
    else:
        writer.run_now()
