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

"""Chemistry → Predict → SOM."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ...chem.structure_payload import mols_from_payloads
from ...predictions.som_prediction import (
    DEFAULT_THRESHOLD,
    METABOLISM_SUBSET_OPTIONS,
)
from ...workers.som_worker import SomPredictorRequest, SomPredictorWorker
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_SOM
from .structure_input import attach_structure_input


class SomPredictorDialog(QDialog):
    """Predict FAME3R sites of metabolism from a structure column or a SMILES string."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_som_state(parent)
        self._build_som_ui()
        self._wire_som_ui()

    def _init_som_state(self, parent) -> None:
        self.setWindowTitle(TOOL_PREDICT_SOM)
        self.setMinimumWidth(360)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._selected_row_count = n_sel
        self._have_selection = n_sel > 0

    def _build_som_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        attach_structure_input(self, root, selected_row_count=self._selected_row_count)

        sub_row = QHBoxLayout()
        sub_row.setSpacing(6)
        sub_row.addWidget(QLabel("Metabolism:"))
        self.subset_combo = QComboBox()
        for value, label in METABOLISM_SUBSET_OPTIONS:
            self.subset_combo.addItem(label, value)
        self.subset_combo.setToolTip(
            "FAME3R model family. Phase 1 and 2 runs two NERDD jobs (slower) "
            "and writes separate Phase 1 and Phase 2 site columns."
        )
        sub_row.addWidget(self.subset_combo, 1)
        root.addLayout(sub_row)

        thr_row = QHBoxLayout()
        thr_row.setSpacing(6)
        thr_row.addWidget(QLabel("SOM threshold:"))
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(0.05, 0.95)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setValue(DEFAULT_THRESHOLD)
        self.threshold_spin.setToolTip(
            "Atoms with probability above this value are marked as sites of metabolism "
            "(FAME3R default is 0.30)."
        )
        thr_row.addWidget(self.threshold_spin)
        thr_row.addStretch()
        root.addLayout(thr_row)

        self.fame_score_cb = QCheckBox("Compute FAME score (applicability domain)")
        self.fame_score_cb.setToolTip(
            "Optional NERDD extra: similarity of each atom environment to the training set "
            "(0–1; higher is more reliable). Slows the job."
        )
        root.addWidget(self.fame_score_cb)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        self.predict_btn = QPushButton("Predict")
        btn_row.addWidget(self.predict_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    def _wire_som_ui(self) -> None:
        self.predict_btn.clicked.connect(self._on_predict)
        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _on_predict(self) -> None:
        if self.parent_app is None:
            return
        payloads = self._structure_input.collect_payloads(self, TOOL_PREDICT_SOM)
        if payloads is None:
            return

        from ...table.structure_depiction_layout import (
            structure_depict_height,
            structure_depict_width,
        )

        map_w = structure_depict_width()
        map_h = structure_depict_height()
        metabolism = str(self.subset_combo.currentData() or "all")
        fame = bool(self.fame_score_cb.isChecked())
        thresh = float(self.threshold_spin.value())
        som_signals = self.parent_app._ensure_som_predictor_signals()
        n = len(payloads)
        enqueue_process_queue_job(
            self.parent_app,
            "Predict SOM",
            n,
            lambda ev, ps, p=payloads, ms=metabolism, fs=fame, th=thresh, mw=map_w, mh=map_h, ws=self.parent_app.signals, sig=som_signals: (
                SomPredictorWorker(
                    SomPredictorRequest(
                        rows=mols_from_payloads(p),
                        metabolism_subset=ms,
                        fame_score=fs,
                        threshold=th,
                        map_width=mw,
                        map_height=mh,
                    ),
                    ws,
                    sig,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"Predict SOM ({n} molecules)",
        )
        self.close()
