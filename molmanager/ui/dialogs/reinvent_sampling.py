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

"""Chemistry → REINVENT Sampling. Runs a local REINVENT 4 install and appends SMILES."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...generative.reinvent_sampling import (
    CONFIRM_SAMPLE_COUNT,
    GENERATORS,
    MISSING_REINVENT_MSG,
    ReinventSamplingCancelled,
    ReinventSamplingError,
    SamplingOutcome,
    SamplingRequest,
    estimated_sample_count,
    execute_sampling,
    normalize_seed_lines,
    resolve_reinvent_executable,
    seed_text_for_row,
    validate_request,
)
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..strings import TOOL_REINVENT_SAMPLING
from ..threadpool_access import start_runnable_on_app_pool

_SEED_SELECTED = "selected"
_SEED_ALL = "all"
_SEED_PASTED = "pasted"


class _SamplingSignals(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)


class _SamplingWorker(QRunnable):
    """Run REINVENT off the GUI thread. ``cancel`` stops the subprocess."""

    def __init__(self, executable: str, request: SamplingRequest, signals: _SamplingSignals):
        super().__init__()
        self.executable = executable
        self.request = request
        self.signals = signals
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            outcome = execute_sampling(
                self.executable,
                self.request,
                cancel=lambda: self._cancel,
                on_log=self.signals.log.emit,
            )
        except ReinventSamplingCancelled:
            self.signals.finished.emit(
                SamplingOutcome(records=(), parsed=0, skipped_invalid=0, cancelled=True)
            )
            return
        except ReinventSamplingError as exc:
            self.signals.failed.emit(str(exc))
            return
        self.signals.finished.emit(outcome)


class ReinventSamplingDialog(QDialog):
    """Sample molecules with REINVENT 4 and append them to the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._worker: _SamplingWorker | None = None
        self._signals = _SamplingSignals(self)
        self._signals.log.connect(self._append_log)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)
        self.setWindowTitle(TOOL_REINVENT_SAMPLING)
        self.setMinimumWidth(640)

        root = QVBoxLayout(self)
        intro = QLabel(
            "Samples molecules with a local REINVENT 4 install. "
            "Set the command under Settings → Configure → REINVENT. "
            "Prior ids such as .reinvent are files in that install's priors folder."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        form = QFormLayout()
        self.generator_combo = QComboBox()
        for spec in GENERATORS:
            self.generator_combo.addItem(spec.label, spec.key)
        self.generator_combo.currentIndexChanged.connect(self._on_generator_changed)
        form.addRow("Generator", self.generator_combo)

        model_row = QHBoxLayout()
        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("prior id or model file")
        self.model_edit.setToolTip(
            "A REINVENT prior id (a file in the install's priors folder) or a path to a .prior file. "
            "The text is passed through as model_file."
        )
        model_row.addWidget(self.model_edit, 1)
        self.preset_combo = QComboBox()
        self.preset_combo.setToolTip(
            "Fill the model box with a public prior id for this generator."
        )
        self.preset_combo.activated.connect(self._apply_preset)
        model_row.addWidget(self.preset_combo)
        browse_model = QPushButton("Browse…")
        browse_model.clicked.connect(self._browse_model)
        model_row.addWidget(browse_model)
        form.addRow("Model", model_row)

        self.device_combo = QComboBox()
        self.device_combo.addItems(["cpu", "cuda:0"])
        self.device_combo.setToolTip(
            "cpu always works. cuda:0 needs an NVIDIA GPU in the REINVENT environment."
        )
        form.addRow("Device", self.device_combo)

        self._count_label = QLabel("Molecules")
        self.count_spin = QSpinBox()
        self.count_spin.setRange(1, 100_000)
        self.count_spin.setValue(50)
        self.count_spin.setToolTip(
            "For R-group, linker, and similar-molecule models this many samples are drawn for each seed."
        )
        form.addRow(self._count_label, self.count_spin)

        self.strategy_label = QLabel("Sampling")
        self.strategy_combo = QComboBox()
        self.strategy_combo.addItems(["multinomial", "beamsearch"])
        self.strategy_combo.setToolTip(
            "Multinomial draws randomly. Beam search is deterministic and uses more memory."
        )
        form.addRow(self.strategy_label, self.strategy_combo)

        self.temperature_label = QLabel("Temperature")
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.05, 2.0)
        self.temperature_spin.setSingleStep(0.05)
        self.temperature_spin.setDecimals(2)
        self.temperature_spin.setValue(1.0)
        self.temperature_spin.setToolTip("Mol2Mol sampling temperature. 1.0 is the model default.")
        form.addRow(self.temperature_label, self.temperature_spin)
        root.addLayout(form)

        checks = QHBoxLayout()
        self.unique_check = QCheckBox("Unique molecules")
        self.unique_check.setChecked(True)
        self.unique_check.setToolTip(
            "Keep one canonical SMILES when the same molecule is drawn more than once."
        )
        self.randomize_check = QCheckBox("Randomize seed SMILES")
        self.randomize_check.setChecked(True)
        self.randomize_check.setToolTip(
            "Shuffle atom order in seed SMILES before sampling. Useful for LibInvent and LinkInvent."
        )
        checks.addWidget(self.unique_check)
        checks.addWidget(self.randomize_check)
        checks.addStretch(1)
        root.addLayout(checks)

        self.seed_box = QGroupBox("Seeds")
        seed_layout = QVBoxLayout(self.seed_box)
        seed_row = QHBoxLayout()
        self.seed_source = QComboBox()
        self.seed_source.addItem("Selected rows", _SEED_SELECTED)
        self.seed_source.addItem("All rows", _SEED_ALL)
        self.seed_source.addItem("Pasted SMILES", _SEED_PASTED)
        self.seed_source.currentIndexChanged.connect(self._sync_seed_editor)
        seed_row.addWidget(self.seed_source, 1)
        self.seed_browse = QPushButton("Browse…")
        self.seed_browse.clicked.connect(self._browse_seeds)
        seed_row.addWidget(self.seed_browse)
        seed_layout.addLayout(seed_row)
        self.seed_hint = QLabel("")
        self.seed_hint.setWordWrap(True)
        seed_layout.addWidget(self.seed_hint)
        self.seed_text = QTextEdit()
        self.seed_text.setPlaceholderText("One seed per line")
        self.seed_text.setMinimumHeight(80)
        apply_monospace_to_text_edit(self.seed_text)
        seed_layout.addWidget(self.seed_text)
        root.addWidget(self.seed_box)

        buttons = QHBoxLayout()
        self.sample_button = QPushButton("Sample")
        self.sample_button.setDefault(True)
        self.sample_button.clicked.connect(self._on_sample)
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.sample_button)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        self.log_edit.setMinimumHeight(140)
        self.log_edit.setPlaceholderText("REINVENT output")
        apply_monospace_to_text_edit(self.log_edit)
        root.addWidget(self.log_edit, 1)

        self._on_generator_changed()
        make_window_minimizable(self)

    def request(self, seeds: tuple[str, ...] = ()) -> SamplingRequest:
        """Sampling request for the current widgets. *seeds* are attached as given."""
        spec = GENERATORS[self.generator_combo.currentIndex()]
        strategy = self.strategy_combo.currentText() if spec.uses_sample_strategy else ""
        return SamplingRequest(
            generator=spec.key,
            model_file=self.model_edit.text().strip(),
            num_smiles=int(self.count_spin.value()),
            device=self.device_combo.currentText(),
            unique_molecules=self.unique_check.isChecked(),
            randomize_smiles=self.randomize_check.isChecked(),
            sample_strategy=strategy,
            temperature=float(self.temperature_spin.value()),
            seeds=seeds,
        )

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)

    def _on_generator_changed(self, *_args) -> None:
        spec = GENERATORS[self.generator_combo.currentIndex()]
        current = self.model_edit.text().strip()
        known = {model for gen in GENERATORS for model in gen.models}
        if not current or current in known:
            self.model_edit.setText(spec.default_model)
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        self.preset_combo.addItems(spec.models)
        self.preset_combo.blockSignals(False)
        self._count_label.setText("Samples per seed" if spec.needs_seeds else "Molecules")
        for widget in (
            self.strategy_label,
            self.strategy_combo,
            self.temperature_label,
            self.temperature_spin,
        ):
            widget.setVisible(False)
        self.strategy_label.setVisible(spec.uses_sample_strategy)
        self.strategy_combo.setVisible(spec.uses_sample_strategy)
        self.temperature_label.setVisible(spec.uses_temperature)
        self.temperature_spin.setVisible(spec.uses_temperature)
        self.seed_box.setVisible(spec.needs_seeds)
        self.seed_hint.setText(spec.blurb)
        self._sync_seed_editor()

    def _sync_seed_editor(self, *_args) -> None:
        pasted = self.seed_source.currentData() == _SEED_PASTED
        self.seed_text.setVisible(pasted)
        self.seed_browse.setVisible(pasted)

    def _apply_preset(self, index: int) -> None:
        text = self.preset_combo.itemText(index).strip()
        if text:
            self.model_edit.setText(text)

    def _browse_model(self) -> None:
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "REINVENT model",
            self.model_edit.text().strip(),
            "REINVENT models (*.prior *.model);;All files (*.*)",
        )
        if path:
            self.model_edit.setText(path)

    def _browse_seeds(self) -> None:
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "Seed SMILES",
            "",
            "SMILES (*.smi *.smiles *.txt);;All files (*.*)",
        )
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            QMessageBox.warning(self, TOOL_REINVENT_SAMPLING, f"Could not read that file:\n{exc}")
            return
        self.seed_text.setPlainText(text)
        index = self.seed_source.findData(_SEED_PASTED)
        if index >= 0:
            self.seed_source.setCurrentIndex(index)

    def _on_sample(self) -> None:
        if self._worker is not None:
            return
        spec = GENERATORS[self.generator_combo.currentIndex()]
        seeds: tuple[str, ...] = ()
        if spec.needs_seeds:
            gathered = self._seeds_for_run()
            if gathered is None:
                return
            seeds = gathered
        request = self.request(seeds)
        message = validate_request(request)
        if message:
            QMessageBox.warning(self, TOOL_REINVENT_SAMPLING, message)
            return
        count = estimated_sample_count(request)
        if count > CONFIRM_SAMPLE_COUNT:
            answer = QMessageBox.question(
                self,
                TOOL_REINVENT_SAMPLING,
                f"This run asks REINVENT for about {count:,} SMILES. Continue?",
            )
            if answer != QMessageBox.Yes:
                return
        executable = resolve_reinvent_executable("")
        if not executable:
            QMessageBox.warning(self, TOOL_REINVENT_SAMPLING, MISSING_REINVENT_MSG)
            return
        self.log_edit.clear()
        self._set_running(True)
        worker = _SamplingWorker(executable, request, self._signals)
        self._worker = worker
        start_runnable_on_app_pool(self.parent_app, worker)
        if hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText(f"{TOOL_REINVENT_SAMPLING}…")

    def _on_stop(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._append_log("Stopping…")

    def _seeds_for_run(self) -> tuple[str, ...] | None:
        source = self.seed_source.currentData()
        if source == _SEED_PASTED:
            seeds = normalize_seed_lines(self.seed_text.toPlainText())
        else:
            seeds = tuple(self._table_seed_lines(only_selected=source == _SEED_SELECTED))
        if seeds:
            return seeds
        if source == _SEED_SELECTED:
            text = "Select one or more rows, or paste SMILES."
        elif source == _SEED_ALL:
            text = "The table has no structures to use as seeds."
        else:
            text = "Paste at least one seed SMILES."
        QMessageBox.information(self, TOOL_REINVENT_SAMPLING, text)
        return None

    def _table_seed_lines(self, *, only_selected: bool) -> list[str]:
        app = self.parent_app
        if app is None or not hasattr(app, "_all_oids_in_table_order"):
            return []
        headers = getattr(app, "headers", None) or []
        oids = list(app._all_oids_in_table_order())
        if only_selected:
            allowed = set(app._selected_oids_set())
            oids = [oid for oid in oids if oid in allowed]
        header = ""
        if hasattr(app, "_canonical_smiles_header_for_updates"):
            header = app._canonical_smiles_header_for_updates() or ""
        lines: list[str] = []
        seen: set[str] = set()
        for oid in oids:
            row = app._table_model.logical_row_for_oid(int(oid))
            if row < 0:
                continue
            cell = ""
            if header and header in headers:
                cell = app._table_model.backing_value_for_row_header(row, header) or ""
                if not str(cell).strip():
                    cell = app._table_model.cell_text(row, headers.index(header)) or ""
            mol = (
                app._mol_for_structure_row(row) if hasattr(app, "_mol_for_structure_row") else None
            )
            text = seed_text_for_row(str(cell), mol)
            if text and text not in seen:
                seen.add(text)
                lines.append(text)
        return lines

    def _set_running(self, running: bool) -> None:
        self.sample_button.setEnabled(not running)
        self.stop_button.setEnabled(running)
        self.generator_combo.setEnabled(not running)
        self.model_edit.setEnabled(not running)
        self.preset_combo.setEnabled(not running)
        self.device_combo.setEnabled(not running)
        self.count_spin.setEnabled(not running)
        self.strategy_combo.setEnabled(not running)
        self.temperature_spin.setEnabled(not running)
        self.unique_check.setEnabled(not running)
        self.randomize_check.setEnabled(not running)
        self.seed_source.setEnabled(not running)
        self.seed_text.setEnabled(not running)

    def _append_log(self, line: str) -> None:
        self.log_edit.append(line)

    def _on_finished(self, outcome: SamplingOutcome) -> None:
        self._worker = None
        self._set_running(False)
        added = 0
        app = self.parent_app
        if (
            outcome.records
            and app is not None
            and hasattr(app, "add_rows_from_external_records_batch")
        ):
            added = int(
                app.add_rows_from_external_records_batch(
                    list(outcome.records),
                    render_structures=True,
                )
            )
        skipped = ""
        if outcome.skipped_invalid:
            skipped = f" Skipped {outcome.skipped_invalid} invalid SMILES."
        if outcome.cancelled:
            message = f"Stopped. Added {added} row(s).{skipped}"
        elif added:
            message = f"Added {added} row(s).{skipped}"
        else:
            message = f"REINVENT finished without any valid molecules.{skipped}"
        self._append_log(message)
        if app is not None and hasattr(app, "status_label"):
            app.status_label.setText(f"{TOOL_REINVENT_SAMPLING}: {message}")
        if not outcome.cancelled and added == 0:
            QMessageBox.information(self, TOOL_REINVENT_SAMPLING, message)

    def _on_failed(self, message: str) -> None:
        self._worker = None
        self._set_running(False)
        text = message or "REINVENT sampling failed."
        self._append_log(text)
        if self.parent_app is not None and hasattr(self.parent_app, "status_label"):
            self.parent_app.status_label.setText(f"{TOOL_REINVENT_SAMPLING} failed.")
        QMessageBox.warning(self, TOOL_REINVENT_SAMPLING, text)
