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

"""Random molecules dialog (Tools → Random → Molecule)."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
)

from ...sources.random_molecule_sources import (
    FILTER_PROPERTY_SPECS,
    SOURCE_CHOICES,
    IntBounds,
    RandomMoleculeFilters,
    RandomSourceMolecule,
    fetch_random_molecules,
    source_label,
)
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..strings import TOOL_RANDOM_MOLECULE
from ..threadpool_access import start_runnable_on_app_pool


@dataclass(frozen=True)
class RandomMoleculeDialogParams:
    source: str
    count: int
    seed: int | None
    add_unique_only: bool
    filters: RandomMoleculeFilters


def _any_spin(max_val: int) -> QSpinBox:
    sb = QSpinBox()
    sb.setRange(-1, int(max_val))
    sb.setSpecialValueText("any")
    sb.setValue(-1)
    sb.setToolTip("Leave as “any” for no bound on this side.")
    return sb


def _spin_or_none(sb: QSpinBox) -> int | None:
    value = int(sb.value())
    return None if value < 0 else value


def _bounds_from_spins(lo: QSpinBox, hi: QSpinBox) -> IntBounds:
    minimum = _spin_or_none(lo)
    maximum = _spin_or_none(hi)
    if minimum is not None and maximum is not None and minimum > maximum:
        minimum, maximum = maximum, minimum
    return IntBounds(minimum=minimum, maximum=maximum)


class _RandomMoleculeSignals(QObject):
    progress = pyqtSignal(int, int, str)  # have, want, source_label
    finished = pyqtSignal(list, str)  # list[RandomSourceMolecule], log
    failed = pyqtSignal(str)


class _RandomMoleculeWorker(QRunnable):
    def __init__(
        self,
        source: str,
        count: int,
        seed: int | None,
        signals: _RandomMoleculeSignals,
        filters: RandomMoleculeFilters | None = None,
    ):
        super().__init__()
        self.source = source
        self.count = count
        self.seed = seed
        self.signals = signals
        self.filters = filters
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        label = source_label(self.source)
        try:
            hits = fetch_random_molecules(
                self.source,
                self.count,
                seed=self.seed,
                cancel_check=lambda: self._cancel,
                progress=lambda have, want, lab=label: self.signals.progress.emit(
                    int(have), int(want), lab
                ),
                filters=self.filters,
            )
        except Exception as e:
            self.signals.failed.emit(str(e) or f"{label} request failed.")
            return
        filt = self.filters.summary() if self.filters is not None else "(none)"
        lines = [
            f"Source: {label}",
            f"Requested: {self.count}",
            f"Retrieved: {len(hits)}",
            f"Seed: {self.seed if self.seed is not None else '(none)'}",
            f"Filters: {filt}",
            "",
        ]
        for h in hits[:40]:
            lines.append(f"{h.molecule_id}\t{(h.smiles or '')[:80]}")
        if len(hits) > 40:
            lines.append(f"… ({len(hits) - 40} more)")
        self.signals.finished.emit(hits, "\n".join(lines))


class RandomMoleculeDialog(QDialog):
    """Pull a user-specified number of random catalog molecules into the table."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_RANDOM_MOLECULE)
        self.setMinimumWidth(480)
        self.resize(560, 560)
        make_window_minimizable(self)

        self._last: list[RandomSourceMolecule] = []
        self._worker: _RandomMoleculeWorker | None = None
        self._signals = _RandomMoleculeSignals()
        self._signals.progress.connect(self._on_progress)
        self._signals.finished.connect(self._on_finished)
        self._signals.failed.connect(self._on_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        tip = QLabel(
            "Fetch random small molecules from ChEMBL, PubChem, or ZINC and add them "
            "to the table (canonical SMILES plus database IDs)."
        )
        tip.setWordWrap(True)
        root.addWidget(tip)

        form = QFormLayout()
        self.source_combo = QComboBox()
        for key, label in SOURCE_CHOICES:
            self.source_combo.addItem(label, key)
        self.source_combo.setToolTip(
            "Public catalog to sample. ChEMBL and PubChem use random offsets into the "
            "index; ZINC uses the public random-substance endpoint."
        )
        self.source_combo.currentIndexChanged.connect(self._sync_fetch_button)
        form.addRow("Source:", self.source_combo)

        self.count_sb = QSpinBox()
        self.count_sb.setRange(1, 500)
        self.count_sb.setValue(10)
        self.count_sb.setToolTip("How many random compounds to retrieve.")
        form.addRow("Number of molecules:", self.count_sb)

        self.seed_sb = QSpinBox()
        self.seed_sb.setRange(0, 2_147_483_647)
        self.seed_sb.setValue(0)
        self.seed_sb.setSpecialValueText("None")
        self.seed_sb.setToolTip(
            "Optional RNG seed for reproducible sampling (0 = no seed). "
            "ChEMBL and PubChem sample catalog offsets; ZINC shuffles server-random pages."
        )
        form.addRow("Seed (optional):", self.seed_sb)

        self.chk_unique = QCheckBox("Skip structures already in the table")
        self.chk_unique.setChecked(True)
        self.chk_unique.setToolTip(
            "When adding results, skip SMILES that match an existing table structure (canonical key)."
        )
        form.addRow("", self.chk_unique)
        root.addLayout(form)

        filt_box = QGroupBox("Property filters")
        filt_box.setToolTip(
            "Optional inclusive min/max windows. Sampling continues until enough hits match "
            "(RDKit counts on the returned SMILES)."
        )
        grid = QGridLayout(filt_box)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        hdr_min = QLabel("Min")
        hdr_max = QLabel("Max")
        grid.addWidget(hdr_min, 0, 1)
        grid.addWidget(hdr_max, 0, 2)
        self._min_spins: dict[str, QSpinBox] = {}
        self._max_spins: dict[str, QSpinBox] = {}
        for row, (key, label, _col, max_val) in enumerate(FILTER_PROPERTY_SPECS, start=1):
            grid.addWidget(QLabel(f"{label}:"), row, 0)
            lo = _any_spin(max_val)
            hi = _any_spin(max_val)
            self._min_spins[key] = lo
            self._max_spins[key] = hi
            grid.addWidget(lo, row, 1)
            grid.addWidget(hi, row, 2)
        root.addWidget(filt_box)

        btn_row = QHBoxLayout()
        self.btn_fetch = QPushButton("Fetch from ChEMBL")
        self.btn_fetch.clicked.connect(self._start_fetch)
        btn_row.addWidget(self.btn_fetch)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_fetch)
        btn_row.addWidget(self.btn_cancel)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

        self.status = QLabel("Ready.")
        root.addWidget(self.status)

        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("Fetch log…")
        apply_monospace_to_text_edit(self.log)
        root.addWidget(self.log, 1)

        bottom = QHBoxLayout()
        bottom.addStretch(1)
        box = QDialogButtonBox(QDialogButtonBox.Close)
        box.rejected.connect(self.reject)
        bottom.addWidget(box)
        root.addLayout(bottom)

        self._sync_fetch_button()

    def _current_source_key(self) -> str:
        data = self.source_combo.currentData()
        if data:
            return str(data)
        return str(self.source_combo.currentText() or "chembl")

    def _current_source_label(self) -> str:
        return source_label(self._current_source_key())

    def _sync_fetch_button(self, *_args) -> None:
        self.btn_fetch.setText(f"Fetch from {self._current_source_label()}")

    def params(self) -> RandomMoleculeDialogParams:
        seed_val = int(self.seed_sb.value())
        return RandomMoleculeDialogParams(
            source=self._current_source_key(),
            count=int(self.count_sb.value()),
            seed=None if seed_val == 0 else seed_val,
            add_unique_only=bool(self.chk_unique.isChecked()),
            filters=RandomMoleculeFilters(
                **{
                    key: _bounds_from_spins(self._min_spins[key], self._max_spins[key])
                    for key, *_rest in FILTER_PROPERTY_SPECS
                }
            ),
        )

    def _set_busy(self, busy: bool) -> None:
        self.btn_fetch.setEnabled(not busy)
        self.btn_cancel.setEnabled(busy)
        self.source_combo.setEnabled(not busy)
        self.count_sb.setEnabled(not busy)
        self.seed_sb.setEnabled(not busy)
        for sb in (*self._min_spins.values(), *self._max_spins.values()):
            sb.setEnabled(not busy)

    def _start_fetch(self) -> None:
        if self._worker is not None:
            return
        p = self.params()
        label = source_label(p.source)
        self._last = []
        self.log.clear()
        self.status.setText(f"Fetching {p.count} random molecule(s) from {label}…")
        self._set_busy(True)
        worker = _RandomMoleculeWorker(p.source, p.count, p.seed, self._signals, p.filters)
        self._worker = worker
        start_runnable_on_app_pool(self.parent_app, worker)

    def _cancel_fetch(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self.status.setText("Cancelling…")

    def _on_progress(self, have: int, want: int, label: str) -> None:
        self.status.setText(f"Fetching from {label}… {have}/{want}")

    def _on_finished(self, hits: list, log: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._last = list(hits or [])
        self.status.setText(f"Done. Retrieved {len(self._last)} molecule(s).")
        self.log.setPlainText(log or "")
        self._open_results_browser()

    def _on_failed(self, msg: str) -> None:
        self._worker = None
        self._set_busy(False)
        self._last = []
        low = (msg or "").lower()
        if "cancel" in low:
            self.status.setText("Cancelled.")
            self.log.setPlainText(msg or "")
            return
        self.status.setText("Failed.")
        self.log.setPlainText(msg or "Unknown error.")
        QMessageBox.warning(self, TOOL_RANDOM_MOLECULE, msg or "Request failed.")

    def _open_results_browser(self) -> None:
        hits = list(self._last)
        if not hits:
            return
        from ..random_molecule_browser import (
            RandomMoleculeBrowserDialog,
            RandomMoleculeBrowserWidget,
        )
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        unique_only = bool(self.chk_unique.isChecked())
        app = self.parent_app
        if app is not None:
            iter_docked = getattr(app, "iter_docked_plot_widgets", None)
            if callable(iter_docked):
                for widget in iter_docked():
                    if isinstance(widget, RandomMoleculeBrowserWidget):
                        widget.set_hits(hits, unique_only=unique_only)
                        show_docked = getattr(app, "show_docked_plot_panel", None)
                        if callable(show_docked):
                            show_docked()
                        widget.raise_()
                        return

            def _factory():
                dlg = RandomMoleculeBrowserDialog(app)
                dlg.set_hits(hits, unique_only=unique_only)
                return dlg

            def _on_reused(dlg) -> None:
                dlg.set_hits(hits, unique_only=unique_only)

            reuse_or_show_modeless_singleton(
                app,
                "_random_molecule_browser_dialog",
                _factory,
                on_reused_visible=_on_reused,
            )
            return
        dlg = RandomMoleculeBrowserDialog(None)
        dlg.set_hits(hits, unique_only=unique_only)
        dlg.show()

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().closeEvent(event)

    def reject(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
        super().reject()
