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

"""Patent-linked chemical similarity search via SureChEMBL (EBI public API)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRunnable, Qt, pyqtSignal
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...sources.surechembl_api import similarity_search
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..threadpool_access import start_runnable_on_app_pool


@dataclass(frozen=True)
class PatentSearchHit:
    smiles: str
    fields: dict[str, str]


class _PatentSearchSignals(QObject):
    finished = pyqtSignal(list, str)  # list[PatentSearchHit], log text
    failed = pyqtSignal(str)


class _PatentSearchWorker(QRunnable):
    def __init__(
        self, smiles: str, min_tanimoto: float, max_hits: int, signals: _PatentSearchSignals
    ):
        super().__init__()
        self.smiles = smiles
        self.min_tanimoto = min_tanimoto
        self.max_hits = max_hits
        self.signals = signals
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        class _Ev:
            def is_set(_self) -> bool:
                return self._cancel

        try:
            rows = similarity_search(
                self.smiles,
                min_tanimoto=self.min_tanimoto,
                max_hits=self.max_hits,
                cancel_event=_Ev(),
            )
        except Exception as e:
            self.signals.failed.emit(str(e))
            return
        hits = []
        for d in rows:
            smi = d.pop("SMILES", "")
            if not smi:
                continue
            hits.append(PatentSearchHit(smi, dict(d)))
        log = f"Query SMILES: {self.smiles}\nMin Tanimoto (SureChEMBL): {self.min_tanimoto}\nHits: {len(hits)}"
        self.signals.finished.emit(hits, log)


class PatentQueryDialog(QDialog):
    """Similarity search against SureChEMBL (chemistry from patents and documents)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Query Database — Patents (SureChEMBL)")
        self.resize(780, 520)
        self._last: list[PatentSearchHit] = []
        self._worker: _PatentSearchWorker | None = None
        self._signals = _PatentSearchSignals()

        root = QVBoxLayout(self)

        row = QHBoxLayout()
        row.addWidget(QLabel("Query SMILES:"))
        self.smiles = QLineEdit()
        self.smiles.setPlaceholderText("Paste a SMILES string, or use Sketcher / selected rows…")
        row.addWidget(self.smiles, 1)
        self.btn_query = QPushButton("Search")
        self.btn_query.setToolTip("Search SureChEMBL for compounds similar to this SMILES.")
        self.btn_query.clicked.connect(self._run_query)
        row.addWidget(self.btn_query)
        self.chk_only_selected = QCheckBox("Use first selected row SMILES")
        self.chk_only_selected.setToolTip(
            "When checked, ignores the text box and uses the first SMILES from the current table selection."
        )
        row.addWidget(self.chk_only_selected)
        self.btn_sketch = QPushButton("Sketcher…")
        self.btn_sketch.clicked.connect(self._use_sketcher)
        row.addWidget(self.btn_sketch)
        root.addLayout(row)

        opts = QGroupBox("Search parameters")
        form = QFormLayout(opts)
        self.spin_tc = QDoubleSpinBox()
        self.spin_tc.setRange(0.30, 1.00)
        self.spin_tc.setDecimals(2)
        self.spin_tc.setSingleStep(0.05)
        self.spin_tc.setValue(0.70)
        self.spin_tc.setToolTip(
            "Minimum Tanimoto similarity on SureChEMBL's server-side fingerprints "
            "(RDKit Morgan, 256 bits, radius 2 — see SureChEMBL documentation)."
        )
        form.addRow("Min. Tanimoto:", self.spin_tc)

        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 500)
        self.spin_max.setValue(25)
        self.spin_max.setToolTip("Maximum number of similar structures to retrieve.")
        form.addRow("Max. structures:", self.spin_max)
        root.addWidget(opts)

        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        apply_monospace_to_text_edit(self.out)
        root.addWidget(self.out, 1)

        bottom = QHBoxLayout()
        self.btn_add = QPushButton("Add hits to table")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_table)
        bottom.addWidget(self.btn_add)
        self.btn_add_unique = QPushButton("Add unique structures only")
        self.btn_add_unique.setEnabled(False)
        self.btn_add_unique.setToolTip(
            "Skip rows whose canonical SMILES already exists in the table, "
            "and skip duplicates within this hit list."
        )
        self.btn_add_unique.clicked.connect(self._add_unique_to_table)
        bottom.addWidget(self.btn_add_unique)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_query)
        bottom.addWidget(self.btn_cancel)
        bottom.addStretch()
        root.addLayout(bottom)

        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_query)
        make_window_minimizable(self)

    def _resolve_query_smiles(self) -> str | None:
        if self.chk_only_selected.isChecked():
            app = self.parent_app
            if app is None:
                QMessageBox.information(self, "Query Patents", "Main application is not available.")
                return None
            try:
                lst = app._selected_smiles_strings()
            except Exception:
                lst = []
            if not lst:
                QMessageBox.information(
                    self, "Query Patents", "Select one or more rows that have a SMILES value first."
                )
                return None
            return lst[0].strip()
        raw = (self.smiles.text() or "").strip()
        if not raw:
            QMessageBox.information(self, "Query Patents", "Enter a SMILES string first.")
            return None
        return raw.split()[0].strip()

    def _use_sketcher(self) -> None:
        try:
            from ..sketcher import SketcherDialog
        except Exception as e:
            QMessageBox.warning(self, "Query Patents", str(e))
            return
        dlg = SketcherDialog(self.parent_app if self.parent_app is not None else self)
        dlg.setModal(True)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.exec_()
        try:
            parts = dlg.canvas.fragment_smiles_parts()
        except Exception:
            parts = []
        if not parts:
            QMessageBox.information(
                self, "Query Patents", "No valid SMILES could be exported from the sketch."
            )
            return
        self.chk_only_selected.setChecked(False)
        self.smiles.setText(parts[0])
        self.status.setText("SMILES loaded from sketcher — press Search when ready.")

    def _run_query(self) -> None:
        smi = self._resolve_query_smiles()
        if not smi:
            return
        self._last = []
        self.btn_add.setEnabled(False)
        self.btn_add_unique.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_query.setEnabled(False)
        self.chk_only_selected.setEnabled(False)
        self.btn_sketch.setEnabled(False)
        self.status.setText("Querying SureChEMBL…")
        self.out.setPlainText("")

        self._worker = _PatentSearchWorker(
            smi,
            float(self.spin_tc.value()),
            int(self.spin_max.value()),
            self._signals,
        )
        start_runnable_on_app_pool(self.parent_app, self._worker)

    def _cancel_query(self) -> None:
        w = getattr(self, "_worker", None)
        if w is not None:
            try:
                w.cancel()
            except Exception:
                pass
        self.status.setText("Cancelling…")

    def _on_finished(self, hits: list, log: str) -> None:
        self._last = list(hits or [])
        self.btn_add.setEnabled(bool(self._last))
        self.btn_add_unique.setEnabled(bool(self._last))
        self.btn_cancel.setEnabled(False)
        self.btn_query.setEnabled(True)
        self.chk_only_selected.setEnabled(True)
        self.btn_sketch.setEnabled(True)
        self.status.setText(f"Done. Retrieved {len(self._last)} structure(s).")
        self.out.setPlainText(log)
        self._worker = None

    def _on_failed(self, msg: str) -> None:
        self._last = []
        self.btn_add.setEnabled(False)
        self.btn_add_unique.setEnabled(False)
        self.btn_cancel.setEnabled(False)
        self.btn_query.setEnabled(True)
        self.chk_only_selected.setEnabled(True)
        self.btn_sketch.setEnabled(True)
        self._worker = None
        low = (msg or "").lower()
        if "cancel" in low:
            self.status.setText("Cancelled.")
            self.out.setPlainText(msg or "")
            return
        self.status.setText("Failed.")
        self.out.setPlainText(msg or "Unknown error.")
        QMessageBox.warning(self, "Query Patents (SureChEMBL)", msg or "Search failed.")

    def _add_unique_to_table(self) -> None:
        self._add_to_table(unique_only=True)

    def _add_to_table(self, *, unique_only: bool = False) -> None:
        if self.parent_app is None or not self._last:
            return
        app = self.parent_app
        existing = app.existing_canonical_structure_keys() if unique_only else set()
        seen_batch: set[str] = set()
        batch: list[tuple[str, dict[str, str]]] = []
        skipped = 0
        for h in self._last:
            smi = (h.smiles or "").strip()
            if unique_only:
                key = app.canonical_structure_key_from_smiles(smi)
                if key is None:
                    skipped += 1
                    continue
                if key in existing or key in seen_batch:
                    skipped += 1
                    continue
                seen_batch.add(key)
            batch.append((smi, h.fields))
        added = 0
        if batch:
            try:
                added = app.add_rows_from_external_records_batch(batch)
            except Exception:
                skipped += len(batch)
                added = 0
        if hasattr(app, "status_label"):
            if unique_only:
                app.status_label.setText(
                    f"SureChEMBL: added {added} unique row(s); skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(f"SureChEMBL: added {added} row(s) to the table.")
            else:
                app.status_label.setText("SureChEMBL: no rows were added.")
