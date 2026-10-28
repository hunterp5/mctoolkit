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

"""Chemistry → Prepare Structures → Protonate → Generate Protomers."""

from __future__ import annotations

import csv
from pathlib import Path

from PyQt5.QtWidgets import (
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ...services.column_labels import COLUMN_PARENT_OID, COLUMN_PROTOMER_SOURCE_OID_LEGACY
from ...chem.structure_payload import mols_from_payloads
from ...workers.protomer_generator import (
    ProtomerGeneratorRequest,
    ProtomerGeneratorSignals,
    ProtomerGeneratorWorker,
)
from ..analysis_job_support import enqueue_process_queue_job
from ..qt_widget_utils import make_window_minimizable
from .structure_input import attach_structure_input


def write_protomer_file(path: str, rows: list[tuple]) -> None:
    """Write protomer rows ``(source oid, smiles, percent, pKa)`` to SDF or CSV."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.suffix.lower() == ".sdf":
        _write_protomer_sdf(destination, rows)
        return
    _write_protomer_csv(destination, rows)


def _write_protomer_sdf(path: Path, rows: list[tuple]) -> None:
    from rdkit import Chem

    writer = Chem.SDWriter(str(path))
    try:
        for source_oid, smiles, percent, pka in rows:
            mol = Chem.MolFromSmiles(str(smiles))
            if mol is None:
                continue
            mol.SetProp("SMILES", str(smiles))
            mol.SetProp("Protomer_percent", f"{float(percent):.2f}")
            mol.SetProp("pKa", str(pka or "N/A"))
            mol.SetProp("Source_OID", "" if source_oid is None else str(source_oid))
            writer.write(mol)
    finally:
        writer.close()


def _write_protomer_csv(path: Path, rows: list[tuple]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Source OID", "SMILES", "Protomer %", "pKa"])
        for source_oid, smiles, percent, pka in rows:
            writer.writerow(
                [
                    "" if source_oid is None else source_oid,
                    smiles,
                    f"{float(percent):.2f}",
                    str(pka or "N/A"),
                ]
            )


class ProtomerGeneratorDialog(QDialog):
    """Enumerate protomers from a Uni-pKa ionization ensemble and estimate populations at a target pH."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_protomer_state(parent)
        self._build_protomer_ui()
        self._wire_protomer_ui()

    def _init_protomer_state(self, parent) -> None:
        self.setWindowTitle("Generate Protomers")
        self.setMinimumWidth(420)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._selected_row_count = n_sel
        self._have_selection = n_sel > 0

    def _build_protomer_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_lyt = QVBoxLayout(structures)
        struct_lyt.setContentsMargins(8, 6, 8, 6)
        struct_lyt.setSpacing(4)
        attach_structure_input(self, struct_lyt, selected_row_count=self._selected_row_count)
        root.addWidget(structures)

        conditions = QGroupBox("Conditions")
        cond_form = QFormLayout(conditions)
        cond_form.setContentsMargins(8, 6, 8, 6)
        cond_form.setSpacing(4)
        self.ph_spin = QDoubleSpinBox()
        self.ph_spin.setRange(0.0, 14.0)
        self.ph_spin.setDecimals(2)
        self.ph_spin.setSingleStep(0.1)
        self.ph_spin.setValue(7.40)
        self.ph_spin.setToolTip("Target pH for approximate protomer population weights.")
        cond_form.addRow("pH:", self.ph_spin)
        root.addWidget(conditions)

        gen_row = QHBoxLayout()
        gen_row.setSpacing(6)
        self.generate_btn = QPushButton("Generate")
        gen_row.addWidget(self.generate_btn)
        gen_row.addStretch()
        root.addLayout(gen_row)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["Source OID", "SMILES", "% (approx.)"])
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setMinimumHeight(160)
        root.addWidget(self.results_table, 1)

        file_row = QHBoxLayout()
        self.output_file = QLineEdit()
        self.output_file.setPlaceholderText("Optional SDF or CSV")
        self.output_file.setToolTip(
            "Leave blank to keep the results in this dialog. "
            "A path writes every protomer when generation finishes."
        )
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_output_file)
        file_row.addWidget(self.output_file, 1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        add_row = QHBoxLayout()
        self.add_all_btn = QPushButton("Add all to main table")
        self.add_sel_btn = QPushButton("Add selected to main table")
        add_row.addWidget(self.add_all_btn)
        add_row.addWidget(self.add_sel_btn)
        add_row.addStretch()
        root.addLayout(add_row)

    def _wire_protomer_ui(self) -> None:
        self.generate_btn.clicked.connect(self._on_generate)
        self.add_all_btn.clicked.connect(self._add_all_to_main)
        self.add_sel_btn.clicked.connect(self._add_selected_to_main)
        self._prot_signals = ProtomerGeneratorSignals(self.parent_app)
        self._prot_signals.finished.connect(self._on_finished)
        self._prot_signals.failed.connect(self._on_failed)
        self._refresh_structure_sources()
        self.adjustSize()
        make_window_minimizable(self)

    def _refresh_structure_sources(self) -> None:
        self._structure_input.refresh_sources(self.parent_app)

    def _on_generate(self) -> None:
        if self.parent_app is None:
            return
        payloads = self._structure_input.collect_payloads(self, "Generate Protomers")
        if payloads is None:
            return

        self.generate_btn.setEnabled(False)
        ph = float(self.ph_spin.value())
        n = len(payloads)
        enqueue_process_queue_job(
            self.parent_app,
            "Generate protomers",
            n,
            lambda ev, ps, p=payloads, h=ph, ws=self.parent_app.signals, sig=self._prot_signals: (
                ProtomerGeneratorWorker(
                    ProtomerGeneratorRequest(rows=mols_from_payloads(p), pH=h),
                    ws,
                    sig,
                    cancel_event=ev,
                    progress_state=ps,
                )
            ),
            queue_label=f"Generate protomers ({n} molecules)",
        )

    def _on_finished(self, rows: list) -> None:
        self.generate_btn.setEnabled(True)
        self.results_table.setRowCount(0)
        rows_sorted = sorted(rows, key=lambda t: -float(t[2]))
        for src_oid, smi, pct in rows_sorted:
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            oid_txt = "" if src_oid is None else str(int(src_oid))
            self.results_table.setItem(r, 0, QTableWidgetItem(oid_txt))
            self.results_table.setItem(r, 1, QTableWidgetItem(smi))
            self.results_table.setItem(r, 2, QTableWidgetItem(f"{pct:.2f}"))
        self.parent_app._finish_tool_progress(
            "Generate protomers",
            status_message=self.parent_app._consume_partial_results_notice() or "Ready.",
        )
        source_oids = {int(oid) for oid, _smi, _pct in rows if oid is not None}
        self._write_unipka_pka_for_oids(source_oids)
        self._write_output_file(rows_sorted)

    def _on_failed(self, msg: str) -> None:
        self.generate_btn.setEnabled(True)
        self.parent_app._finish_tool_progress("Generate protomers")
        QMessageBox.warning(self, "Generate Protomers", msg or "Generation failed.")

    def _pka_for_source_oid(self, oid: int | None) -> str:
        if oid is None or self.parent_app is None:
            return "N/A"
        from molmanager.ionization.unipka_ensembles import format_pka_values, pka_values_from_states
        from molmanager.ionization.microstate_cache import lookup as cache_lookup
        from molmanager.services.structure_grouping import structure_key

        mol = self.parent_app.mols.get(int(oid))
        if mol is None:
            row = self.parent_app._table_model.logical_row_for_oid(int(oid))
            if row >= 0:
                mol = self.parent_app._mol_for_structure_row(row)
        if mol is None:
            return "N/A"
        hit, states = cache_lookup(structure_key(mol))
        if not hit:
            return "N/A"
        return format_pka_values(pka_values_from_states(states))

    def _write_unipka_pka_for_oids(self, source_oids: set[int]) -> None:
        if not source_oids or self.parent_app is None:
            return
        rows = []
        for oid in sorted(source_oids):
            rows.append((int(oid), {"pKa": self._pka_for_source_oid(oid)}))
        if rows:
            self.parent_app.on_calc_finished(
                rows, ["pKa"], finish_progress=False, progress_label=None
            )

    def _browse_output_file(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Protomer output",
            self.output_file.text().strip(),
            "Structure file (*.sdf);;CSV (*.csv)",
        )
        if path:
            self.output_file.setText(path)

    def _write_output_file(self, rows: list) -> None:
        path = self.output_file.text().strip()
        if not path:
            return
        records = []
        for src_oid, smi, pct in rows:
            records.append((src_oid, smi, float(pct), self._pka_for_source_oid(src_oid)))
        try:
            write_protomer_file(path, records)
        except (OSError, ValueError, RuntimeError) as exc:
            QMessageBox.warning(self, "Generate Protomers", str(exc) or "Could not write the file.")
            return
        if self.parent_app is not None:
            self.parent_app.status_label.setText(f"Wrote {len(records)} protomer(s) to {path}.")

    def _unique_col(self, base: str) -> str:
        name = base
        i = 1
        while name in self.parent_app.headers:
            i += 1
            name = f"{base} ({i})"
        return name

    def _parent_oid_column(self) -> str:
        """Reuse existing lineage column when present (incl. legacy protomer header)."""
        headers = self.parent_app.headers
        if COLUMN_PARENT_OID in headers:
            return COLUMN_PARENT_OID
        if COLUMN_PROTOMER_SOURCE_OID_LEGACY in headers:
            return COLUMN_PROTOMER_SOURCE_OID_LEGACY
        return self._unique_col(COLUMN_PARENT_OID)

    def _add_rows_to_main(self, table_rows: set[int]) -> None:
        if not table_rows:
            return
        pct_col = self._unique_col("Protomer %")
        src_col = self._parent_oid_column()
        batch: list[tuple[str, dict[str, str]]] = []
        for r in sorted(table_rows):
            oid_item = self.results_table.item(r, 0)
            smi_item = self.results_table.item(r, 1)
            pct_item = self.results_table.item(r, 2)
            if smi_item is None or pct_item is None:
                continue
            smi = (smi_item.text() or "").strip()
            if not smi:
                continue
            oid_txt = (oid_item.text() if oid_item is not None else "").strip()
            pct_txt = (pct_item.text() or "").strip()
            fields = {pct_col: pct_txt, src_col: oid_txt}
            src_oid = int(oid_txt) if oid_txt.isdigit() else None
            fields["pKa"] = self._pka_for_source_oid(src_oid)
            batch.append((smi, fields))
        if not batch:
            return
        added = self.parent_app.add_rows_from_external_records_batch(batch)
        self.parent_app.status_label.setText(f"Added {added} protomer row(s) to the table.")

    def _add_all_to_main(self) -> None:
        n = self.results_table.rowCount()
        if n == 0:
            return
        self._add_rows_to_main(set(range(n)))

    def _add_selected_to_main(self) -> None:
        sel = {i.row() for i in self.results_table.selectedIndexes()}
        if not sel:
            QMessageBox.information(
                self, "Generate Protomers", "Select one or more rows in the results table."
            )
            return
        self._add_rows_to_main(sel)
