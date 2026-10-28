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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Chemistry → Calculate → Metabolites (BioTransformer)."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...chem.structure_payload import mols_from_payloads
from ...predictions.biotransformer_metabolites import (
    CYP_MODE_LABELS,
    DEFAULT_CYP_MODE,
    DEFAULT_MAX_METABOLITES,
    DEFAULT_NSTEPS,
    METABOLISM_OPTIONS,
    install_ready_message,
    uses_cyp_mode,
)
from ...platform_support.memory_guards import check_product_enumeration, clamp_max_products_ui
from ...workers.biotransformer_worker import BiotransformerRequest, BiotransformerWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_METABOLITES
from .structure_input import attach_structure_input


def _set_combo_current_data(combo: QComboBox, data) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return


class BiotransformerDialog(QDialog):
    """Predict BioTransformer metabolites from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_biotransformer_state(parent)
        self._build_biotransformer_ui()
        self._wire_biotransformer_ui()

    def _init_biotransformer_state(self, parent) -> None:
        self.setWindowTitle(TOOL_PREDICT_METABOLITES)
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._selected_row_count = n_sel
        self._have_selection = n_sel > 0

    def _build_biotransformer_ui(self) -> None:
        n_sel = self._selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_lyt = QVBoxLayout(structures)
        struct_lyt.setContentsMargins(8, 6, 8, 6)
        struct_lyt.setSpacing(4)
        attach_structure_input(self, struct_lyt, selected_row_count=n_sel)
        root.addWidget(structures)

        metabolism = QGroupBox("Metabolism")
        form = QFormLayout(metabolism)
        form.setContentsMargins(8, 6, 8, 6)
        form.setSpacing(4)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.subset_combo = QComboBox()
        for value, label in METABOLISM_OPTIONS:
            self.subset_combo.addItem(label, value)
        self.subset_combo.setToolTip(
            "BioTransformer module. AllHuman covers host plus gut reactions at each step."
        )
        form.addRow("Metabolism:", self.subset_combo)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 3)
        self.steps_spin.setValue(DEFAULT_NSTEPS)
        self.steps_spin.setToolTip("Maximum biotransformation generations (1–3).")
        form.addRow("Steps:", self.steps_spin)

        self.cyp_combo = QComboBox()
        for value, label in CYP_MODE_LABELS:
            self.cyp_combo.addItem(label, value)
        _set_combo_current_data(self.cyp_combo, DEFAULT_CYP_MODE)
        form.addRow("CYP mode:", self.cyp_combo)

        self.max_spin = QSpinBox()
        self.max_spin.setRange(1, clamp_max_products_ui(10_000))
        self.max_spin.setValue(min(DEFAULT_MAX_METABOLITES, clamp_max_products_ui(10_000)))
        self.max_spin.setToolTip("Cap products kept per parent molecule.")
        form.addRow("Max metabolites:", self.max_spin)
        root.addWidget(metabolism)

        output = QGroupBox("Output")
        out_lyt = QVBoxLayout(output)
        out_lyt.setContentsMargins(8, 6, 8, 6)
        out_lyt.setSpacing(4)
        self.add_rows_cb = QCheckBox("Add metabolites as new table rows")
        self.add_rows_cb.setToolTip(
            "Append each product as a new row with parent SMILES, reaction, and generation."
        )
        out_lyt.addWidget(self.add_rows_cb)
        root.addWidget(output)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        btn_row.addStretch()
        self.predict_btn = QPushButton("Predict")
        btn_row.addWidget(self.predict_btn)
        root.addLayout(btn_row)

    def _wire_biotransformer_ui(self) -> None:
        self.subset_combo.currentIndexChanged.connect(self._sync_cyp_mode)
        self.predict_btn.clicked.connect(self._on_predict)
        self._refresh_structure_sources()
        self._sync_cyp_mode()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _sync_cyp_mode(self) -> None:
        metabolism = str(self.subset_combo.currentData() or "allHuman")
        self.cyp_combo.setEnabled(uses_cyp_mode(metabolism))

    def _on_predict(self) -> None:
        missing = install_ready_message()
        if missing:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, missing)
            return
        if self.parent_app is None:
            return
        metabolism = str(self.subset_combo.currentData() or "allHuman")
        nsteps = int(self.steps_spin.value())
        cyp_mode = int(self.cyp_combo.currentData() or DEFAULT_CYP_MODE)
        max_mets = int(self.max_spin.value())
        guard = check_product_enumeration(max_mets)
        if not guard.ok:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, guard.message)
            return
        add_as_rows = bool(self.add_rows_cb.isChecked())
        payloads = self._structure_input.collect_payloads(self, TOOL_PREDICT_METABOLITES)
        if payloads is None:
            return
        from ...predictions.biotransformer_metabolites import metabolite_output_columns

        payloads = self.parent_app._filter_rows_for_resume(payloads, metabolite_output_columns())

        bt_signals = self.parent_app._ensure_biotransformer_signals()
        n = len(payloads)
        enqueue_process_queue_job(
            self.parent_app,
            TOOL_PREDICT_METABOLITES,
            n,
            lambda ev, ps, p=payloads, met=metabolism, ns=nsteps, cm=cyp_mode, mm=max_mets, ar=add_as_rows, ws=self.parent_app.signals, sig=bt_signals: (
                BiotransformerWorker(
                    BiotransformerRequest(
                        rows=mols_from_payloads(p),
                        metabolism=met,
                        nsteps=ns,
                        cyp_mode=cm,
                        max_metabolites=mm,
                        add_as_rows=ar,
                    ),
                    ws,
                    sig,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"{TOOL_PREDICT_METABOLITES} ({n} molecules)",
        )
        self.close()
