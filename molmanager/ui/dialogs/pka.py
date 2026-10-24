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

from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
)

from ...chem.structure_payload import mols_from_payloads
from ...workers import PKaPredictorWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from .structure_input import attach_structure_input


class PKaPredictorDialog(QDialog):
    """Predict macro pKa values (Uni-pKa) from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Predict pKa")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_lyt = QVBoxLayout(structures)
        struct_lyt.setContentsMargins(8, 6, 8, 6)
        struct_lyt.setSpacing(4)
        attach_structure_input(self, struct_lyt, selected_row_count=n_sel)
        root.addWidget(structures)

        output = QGroupBox("Output")
        out_lyt = QVBoxLayout(output)
        out_lyt.setContentsMargins(8, 6, 8, 6)
        out_lyt.setSpacing(4)

        self.most_basic_only_cb = QCheckBox("Only calculate most basic pKa")
        self.most_basic_only_cb.setToolTip(
            "When checked, write a single value: the highest predicted pKa (strongest base / "
            "most basic ionization step). Otherwise all macro pKas are listed."
        )
        self.most_basic_only_cb.toggled.connect(self._on_most_basic_toggled)
        out_lyt.addWidget(self.most_basic_only_cb)

        self.most_acidic_only_cb = QCheckBox("Only calculate most acidic pKa")
        self.most_acidic_only_cb.setToolTip(
            "When checked, write a single value: the lowest predicted pKa (strongest acid / "
            "most acidic ionization step)."
        )
        self.most_acidic_only_cb.toggled.connect(self._on_most_acidic_toggled)
        out_lyt.addWidget(self.most_acidic_only_cb)

        self.include_pi_cb = QCheckBox("Calculate isoelectric point (pI)")
        self.include_pi_cb.setToolTip(
            "When checked, also write a shared pI column (pH where mean charge crosses zero). "
            "Simple acids and bases are N/A. Off by default; Protonate and descriptors do not write pI."
        )
        out_lyt.addWidget(self.include_pi_cb)
        root.addWidget(output)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        self.predict_btn.clicked.connect(self._on_predict)
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _on_most_basic_toggled(self, on: bool) -> None:
        if on:
            self.most_acidic_only_cb.blockSignals(True)
            self.most_acidic_only_cb.setChecked(False)
            self.most_acidic_only_cb.blockSignals(False)

    def _on_most_acidic_toggled(self, on: bool) -> None:
        if on:
            self.most_basic_only_cb.blockSignals(True)
            self.most_basic_only_cb.setChecked(False)
            self.most_basic_only_cb.blockSignals(False)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        rows = self._structure_input.collect_payloads(self, "Predict pKa")
        if rows is None:
            return

        most_basic = bool(self.most_basic_only_cb.isChecked())
        most_acidic = bool(self.most_acidic_only_cb.isChecked())
        include_pi = bool(self.include_pi_cb.isChecked())
        pka_signals = self.parent_app._ensure_pka_predictor_signals()
        n = len(rows)
        enqueue_process_queue_job(
            self.parent_app,
            "pKa prediction",
            n,
            lambda ev, ps, r=rows, ws=self.parent_app.signals, sig=pka_signals, mb=most_basic, ma=most_acidic, ip=include_pi: (
                PKaPredictorWorker(
                    mols_from_payloads(r),
                    ws,
                    sig,
                    cancel_event=ev,
                    most_basic_only=mb,
                    most_acidic_only=ma,
                    include_pi=ip,
                    progress_state=ps,
                )
            ),
            queue_label=f"pKa prediction ({n} molecules)",
        )
        self.close()
