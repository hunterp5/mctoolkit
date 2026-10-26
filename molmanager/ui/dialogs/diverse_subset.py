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

"""Data → Similarity → Diverse Subset."""

from __future__ import annotations

from dataclasses import replace

from PyQt5.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...chem.rdkit_fingerprints import (
    SIMILARITY_FP_TYPE_LABELS,
    descriptor_onbits_column_aliases,
    select_default_fingerprint,
)
from ...chem.structure_payload import mols_from_payloads
from ...platform_support.config import load_config
from ...platform_support.memory_guards import check_diverse_subset_workload
from ...workers.diverse_subset_worker import (
    DIVERSE_SUBSET_MODE_LABELS,
    DiverseSubsetRequest,
    DiverseSubsetWorker,
)
from ..qt_widget_utils import make_window_minimizable
from ..analysis_job_support import enqueue_process_queue_job
from .scope import selection_scope_checked

_OID_SCAN_PUMP_EVERY = 4096

_DEFAULT_COLUMN = "Diverse subset rank"


class DiverseSubsetDialog(QDialog):
    """Pick a maximally diverse compound subset using fingerprint MaxMin (Tanimoto distance)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_diverse_subset_state(parent)
        self._build_diverse_subset_ui()
        self._wire_diverse_subset_ui()

    def _init_diverse_subset_state(self, parent) -> None:
        self.setWindowTitle("Diverse Subset")
        self.setMinimumWidth(460)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._selected_row_count = n_sel
        self._table_row_count = parent._table_model.rowCount() if parent else 1
        self._scope_oids: list[int] = []
        self._pending_column_name = ""
        self._onbits_column: str | None = None

    def _build_diverse_subset_ui(self) -> None:
        n_sel = self._selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        features = QGroupBox("Features")
        feat_form = QFormLayout(features)
        feat_form.setContentsMargins(8, 6, 8, 6)
        feat_form.setSpacing(4)
        feat_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.src_combo = QComboBox()
        feat_form.addRow("Structure source:", self.src_combo)

        self.fp_combo = QComboBox()
        self.fp_combo.addItems(SIMILARITY_FP_TYPE_LABELS)
        select_default_fingerprint(self.fp_combo)
        feat_form.addRow("Fingerprint:", self.fp_combo)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        feat_form.addRow("", self.only_selected_cb)
        root.addWidget(features)

        subset = QGroupBox("Subset")
        subset_form = QFormLayout(subset)
        subset_form.setContentsMargins(8, 6, 8, 6)
        subset_form.setSpacing(4)
        subset_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.mode_combo = QComboBox()
        for key, label in DIVERSE_SUBSET_MODE_LABELS:
            self.mode_combo.addItem(label, key)
        self.mode_combo.setToolTip(
            "Exact MaxMin on the full pool. Fast prefilters (Leader / subsample) then "
            "MaxMin on a candidate pool — better for BindingDB-scale tables. Auto picks "
            "Exact when the pool is at or below the configured exact-row threshold."
        )
        subset_form.addRow("Algorithm:", self.mode_combo)

        self.subset_size_spin = QSpinBox()
        self.subset_size_spin.setRange(1, 1_000_000)
        n_rows = self._table_row_count
        self.subset_size_spin.setValue(min(50, max(1, n_rows)))
        self.subset_size_spin.setToolTip(
            "Number of compounds to keep in the diverse subset (MaxMin on Tanimoto distance)."
        )
        subset_form.addRow("Subset size:", self.subset_size_spin)

        self.select_subset_cb = QCheckBox("Select subset in table")
        self.select_subset_cb.setChecked(True)
        self.select_subset_cb.setToolTip("Highlight the picked rows in the compound table.")
        subset_form.addRow("", self.select_subset_cb)
        root.addWidget(subset)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.add_column_cb = QCheckBox("Add rank column")
        self.add_column_cb.setChecked(True)
        self.add_column_cb.setToolTip(
            "Rank 1 is the first MaxMin pick; higher ranks are added for diversity."
        )
        out_form.addRow("", self.add_column_cb)

        self.column_name_edit = QLineEdit(_DEFAULT_COLUMN)
        self.column_name_edit.setPlaceholderText("Column name in table")
        out_form.addRow("Rank column:", self.column_name_edit)
        root.addWidget(output)

        btn_row = QHBoxLayout()
        self.run_btn = QPushButton("Pick Diverse Subset")
        btn_row.addWidget(self.run_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def _wire_diverse_subset_ui(self) -> None:
        self.run_btn.clicked.connect(self.run)
        self._refresh_structure_sources()
        make_window_minimizable(self)

    def _selected_mode_key(self) -> str:
        return str(self.mode_combo.currentData() or "auto")

    def _refresh_structure_sources(self) -> None:
        self.src_combo.clear()
        if self.parent_app is None:
            return
        self.src_combo.addItems(self.parent_app.chemistry_tool_structure_sources())

    def _matching_onbits_column(self, fp_choice: str) -> str | None:
        app = self.parent_app
        if app is None:
            return None
        headers = app.headers
        for col in descriptor_onbits_column_aliases(fp_choice):
            if col in headers:
                return col
        return None

    def _unique_column_name(self, base: str) -> str:
        name = (base or "").strip() or _DEFAULT_COLUMN
        if name not in self.parent_app.headers:
            return name
        cnt = 1
        while f"{name} ({cnt})" in self.parent_app.headers:
            cnt += 1
        return f"{name} ({cnt})"

    def _scope_oids_in_table(self, only_selected: bool) -> list[int]:
        """OID list in table order (cheap; no RDKit). Pumps the event loop on large tables."""
        allowed = self.parent_app._selected_oids_set() if only_selected else None
        oids: list[int] = []
        m = self.parent_app._table_model
        n = m.rowCount()
        for r in range(n):
            if r > 0 and r % _OID_SCAN_PUMP_EVERY == 0:
                QApplication.processEvents()
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue
            oids.append(int(oid))
        return oids

    def _onbits_values_single_pass(self, oid_set: set[int]) -> dict[int, str] | None:
        """One table scan for on-bits cells (avoids per-OID row lookups on BindingDB)."""
        col = self._onbits_column
        app = self.parent_app
        if not col or col not in app.headers:
            return None
        hidx = app.headers.index(col)
        m = app._table_model
        out: dict[int, str] = {}
        n = m.rowCount()
        for r in range(n):
            if r > 0 and r % _OID_SCAN_PUMP_EVERY == 0:
                QApplication.processEvents()
            oid = int(m.row_oid(r))
            if oid not in oid_set:
                continue
            out[oid] = app._table_cell_text(r, hidx) or ""
        return out

    def run(self) -> None:
        app = self.parent_app
        src = self.src_combo.currentText()
        only_sel = selection_scope_checked(self)
        if only_sel and not app._selected_oids_set():
            app.status_label.setText(
                "Diverse subset: \u201cSelected Rows Only\u201d is checked but nothing is selected."
            )
            return

        app.status_label.setText("Diverse subset: preparing…")
        QApplication.processEvents()

        # Cheap OID enumeration only — molecule resolution uses snapshots, not Qt in the worker.
        oids = self._scope_oids_in_table(only_sel)
        if not oids:
            app.status_label.setText("Diverse subset: no rows in this scope.")
            return

        fp_choice = self.fp_combo.currentText()
        mode = self._selected_mode_key()
        self._onbits_column = self._matching_onbits_column(fp_choice)
        use_onbits_col = self._onbits_column is not None
        onbits_by_oid = None
        if use_onbits_col:
            onbits_by_oid = self._onbits_values_single_pass(set(oids))

        # Approximate eligible count for guards (on-bits filter applied in worker).
        n_est = len(oids)
        if use_onbits_col and onbits_by_oid is not None:
            n_est = 0
            for oid in oids:
                t = (onbits_by_oid.get(oid, "") or "").strip()
                if not t or t.upper() == "N/A":
                    continue
                try:
                    int(float(t))
                except ValueError:
                    continue
                n_est += 1
            if n_est <= 0:
                app.status_label.setText(
                    f"Diverse subset: no eligible rows with values in “{self._onbits_column}”."
                )
                return

        k = int(self.subset_size_spin.value())
        if k < 1:
            app.status_label.setText("Diverse subset: subset size must be at least 1.")
            return
        if k > n_est:
            app.status_label.setText(
                f"Diverse subset: subset size ({k}) exceeds eligible rows ({n_est})."
            )
            return

        guard = check_diverse_subset_workload(n_est, k, mode=mode)
        if not guard.ok:
            QMessageBox.warning(self, "Diverse Subset", guard.message)
            return

        cfg = load_config()
        if mode == "exact" and n_est > int(cfg.diverse_subset_exact_max_rows):
            reply = QMessageBox.question(
                self,
                "Diverse Subset",
                f"Exact MaxMin on {n_est:,} compounds may be slow. Continue anyway?\n\n"
                f"Tip: choose Fast or Auto for large libraries "
                f"(exact threshold {cfg.diverse_subset_exact_max_rows:,}).",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        payloads = app.collect_scoped_table_structure_payloads(src, only_selected=only_sel)
        if not payloads:
            app.status_label.setText(
                "Diverse subset: no molecules available for this structure source "
                "(load/prepare structures first)."
            )
            return

        self._scope_oids = list(oids)
        self._pending_column_name = ""
        if self.add_column_cb.isChecked():
            self._pending_column_name = self._unique_column_name(self.column_name_edit.text())

        app._diverse_subset_run_ctx = {
            "pending_column_name": self._pending_column_name,
            "select_subset": self.select_subset_cb.isChecked(),
        }
        sig = app._ensure_diverse_subset_signals()
        req = DiverseSubsetRequest(
            fp_choice=fp_choice,
            subset_size=k,
            oids=list(oids),
            structure_source=src,
            mols_by_oid=None,
            structure_texts=None,
            onbits_by_oid=onbits_by_oid,
            use_onbits_column=use_onbits_col,
            mode=mode,
        )
        enqueue_process_queue_job(
            app,
            "Diverse subset",
            n_est,
            lambda ev, ps, r=req, pl=payloads, s=sig: DiverseSubsetWorker(
                replace(
                    r,
                    mols_by_oid={
                        oid: mol for oid, mol in mols_from_payloads(pl) if oid is not None
                    },
                ),
                s,
                cancel_event=ev,
                progress_state=ps,
            ),
            queue_label=f"Diverse subset ({n_est} rows, pick {k}, {mode})",
        )
        self.close()
