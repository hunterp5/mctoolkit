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

"""Sketcher with a live descriptor strip and a design list.

Opens in its own window. It is not docked into the table workspace.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt5.QtCore import QEvent, QObject, QRunnable, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ..analysis.design_studio import (
    DesignSnapshot,
    DesignSuggestion,
    SeriesRow,
    compute_design_snapshot,
    mmp_suggestions,
    rgroup_swap_suggestions,
    suggest_core_column,
)
from ..analysis.sar_matrix import rgroup_index, suggest_rgroup_axes
from ..services.activity_records import parse_activity_float
from .browsers.chrome import BrowserHostDialog, apply_browser_body_layout
from .dockable_plot import style_plot_footer_text_button
from .sketcher.dialog import SketcherDialog
from .sketcher.physical_properties import compute_ionization_properties
from .strings import TOOL_DESIGN_STUDIO
from .threadpool_access import start_runnable_on_app_pool

logger = logging.getLogger(__name__)

_PKA_FAILED = "pKa calculation failed"
_TERM_DIGITS = {"MW": 2, "LogP": 2, "TPSA": 1, "QED": 3, "RotBonds": 0}


def _canonical_smiles(smiles: str) -> str:
    text = (smiles or "").strip()
    if not text:
        return ""
    mol = Chem.MolFromSmiles(text)
    if mol is None:
        return ""
    try:
        return Chem.MolToSmiles(mol, canonical=True) or ""
    except (RuntimeError, ValueError, TypeError):
        return ""


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


def _desirability_color(value: float | None) -> QColor | None:
    """Blend a low score toward red and a high score toward green."""
    if value is None:
        return None
    amount = min(1.0, max(0.0, float(value)))
    worse = (252, 220, 220)
    better = (170, 214, 186)
    return QColor(
        int(worse[0] * (1.0 - amount) + better[0] * amount),
        int(worse[1] * (1.0 - amount) + better[1] * amount),
        int(worse[2] * (1.0 - amount) + better[2] * amount),
    )


def _paint_desirability(label: QLabel, value: float | None) -> None:
    color = _desirability_color(value)
    if color is None:
        label.setStyleSheet("")
        return
    label.setStyleSheet(f"background-color: {color.name()}; color: #141414; padding: 1px 4px;")


def _section_label(text: str) -> QLabel:
    label = QLabel(text)
    font = QFont(label.font())
    font.setBold(True)
    label.setFont(font)
    return label


def _value_label() -> QLabel:
    label = QLabel("—")
    label.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return label


class _StudioIonSignals(QObject):
    finished = pyqtSignal(int, object)
    failed = pyqtSignal(int, str)


class _StudioIonWorker(QRunnable):
    """Uni-pKa for the sketch. The strip keeps heuristic scores if this fails."""

    def __init__(
        self,
        mol: Chem.Mol,
        generation: int,
        signals: _StudioIonSignals,
        cancel_event: threading.Event,
    ):
        super().__init__()
        self.setAutoDelete(True)
        self._mol = mol
        self._generation = generation
        self._signals = signals
        self._cancel_event = cancel_event

    def run(self) -> None:
        try:
            if self._cancel_event.is_set():
                self._signals.failed.emit(self._generation, "cancelled")
                return
            result = compute_ionization_properties(self._mol, cancel_event=self._cancel_event)
        except (RuntimeError, ValueError, TypeError, OSError) as exc:
            msg = str(exc) or _PKA_FAILED
            if msg != "cancelled":
                logger.debug("design studio ionization failed: %s", msg)
            self._signals.failed.emit(self._generation, msg)
            return
        if self._cancel_event.is_set():
            self._signals.failed.emit(self._generation, "cancelled")
            return
        self._signals.finished.emit(self._generation, result)


class DesignPropertyStrip(QWidget):
    """Descriptor values, druglike MPO, and ionization scores for the sketch."""

    def __init__(self, sketcher: SketcherDialog, parent: QWidget | None = None):
        super().__init__(parent)
        self._sketcher = sketcher
        self._generation = 0
        self._active_generation = 0
        self._ion_busy = False
        self._pending_mol: Chem.Mol | None = None
        self._pending_generation = 0
        self._cancel_event = threading.Event()
        self._ion_signals = _StudioIonSignals(self)
        self._ion_signals.finished.connect(self._on_ionization_finished)
        self._ion_signals.failed.connect(self._on_ionization_failed)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        self._druglike_details = QWidget(self)
        detail_grid = QGridLayout(self._druglike_details)
        detail_grid.setContentsMargins(0, 4, 0, 0)
        detail_grid.setHorizontalSpacing(10)
        detail_grid.setVerticalSpacing(2)
        detail_grid.addWidget(QLabel("Property"), 0, 0)
        detail_grid.addWidget(QLabel("Value"), 0, 1)
        score_header = QLabel("Score")
        score_header.setToolTip("Desirability from 0 to 1. Color follows that score.")
        detail_grid.addWidget(score_header, 0, 2)
        self._value_labels: dict[str, QLabel] = {}
        self._desirability_labels: dict[str, QLabel] = {}
        for row, key in enumerate(("MW", "LogP", "TPSA", "QED", "RotBonds"), start=1):
            detail_grid.addWidget(QLabel(_term_label(key)), row, 0)
            value = _value_label()
            desir = _value_label()
            detail_grid.addWidget(value, row, 1)
            detail_grid.addWidget(desir, row, 2)
            self._value_labels[key] = value
            self._desirability_labels[key] = desir
        hbd_row = 6
        detail_grid.addWidget(QLabel("HBD"), hbd_row, 0)
        self._hbd = _value_label()
        detail_grid.addWidget(self._hbd, hbd_row, 1)
        hba_row = 7
        detail_grid.addWidget(QLabel("HBA"), hba_row, 0)
        self._hba = _value_label()
        detail_grid.addWidget(self._hba, hba_row, 1)
        root.addWidget(self._druglike_details)

        root.addWidget(_section_label("Ionization"))
        ion_grid = QGridLayout()
        ion_grid.setHorizontalSpacing(10)
        ion_grid.setVerticalSpacing(2)
        ion_grid.addWidget(QLabel("Property"), 0, 0)
        ion_grid.addWidget(QLabel("Value"), 0, 1)
        ion_score = QLabel("Score")
        ion_score.setToolTip(
            "CNS MPO is 0–6, higher is better. AB-MPS is lower when a compound is more druglike. "
            "Those scores are not desirabilities from 0 to 1."
        )
        ion_grid.addWidget(ion_score, 0, 2)
        self._logd = _value_label()
        self._pka = _value_label()
        self._cns = _value_label()
        self._ab_mps = _value_label()
        self._cns_score = _value_label()
        self._ab_mps_score = _value_label()
        self._logd.setToolTip("Heuristic until a Uni-pKa result replaces it.")
        self._cns.setToolTip("Wager CNS MPO (0–6). Heuristic until Uni-pKa finishes.")
        self._cns_score.setToolTip(self._cns.toolTip())
        self._ab_mps.setToolTip(
            "AbbVie MPS. Lower is more druglike. Heuristic until Uni-pKa finishes."
        )
        self._ab_mps_score.setToolTip(self._ab_mps.toolTip())
        for row, name, value, score in (
            (1, "LogD (7.4)", self._logd, None),
            (2, "pKa", self._pka, None),
            (3, "CNS MPO", self._cns, self._cns_score),
            (4, "AB-MPS", self._ab_mps, self._ab_mps_score),
        ):
            ion_grid.addWidget(QLabel(name), row, 0)
            ion_grid.addWidget(value, row, 1)
            if score is not None:
                ion_grid.addWidget(score, row, 2)
        root.addLayout(ion_grid)
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh_now)

    def set_caption(self, text: str) -> None:
        """Captions are no longer shown above the property table."""
        _ = text

    def schedule_refresh(self) -> None:
        """Debounce sketch edits before recomputing."""
        self._timer.start()

    def shutdown(self) -> None:
        self._timer.stop()
        self._cancel_event.set()
        self._pending_mol = None

    def _refresh_now(self) -> None:
        self._generation += 1
        generation = self._generation
        self._cancel_event.set()
        mol = self._current_mol()
        snapshot = compute_design_snapshot(mol)
        self._show_snapshot(snapshot)
        if snapshot.error or mol is None:
            self._pending_mol = None
            self._pka.setText("—")
            self._pka.setToolTip("")
            return
        self._pka.setText("…")
        self._pka.setToolTip("")
        try:
            mol_copy = Chem.Mol(mol)
        except TypeError:
            self._pka.setText("—")
            return
        self._start_or_coalesce_ionization(mol_copy, generation)

    def _current_mol(self) -> Chem.Mol | None:
        try:
            return self._sketcher._sketch_mol_for_3d()
        except (RuntimeError, ValueError, TypeError, AttributeError):
            logger.debug("design studio could not read the sketch", exc_info=True)
            return None

    def _show_snapshot(self, snapshot: DesignSnapshot) -> None:
        if snapshot.error or not snapshot.terms:
            for label in self._value_labels.values():
                label.setText("—")
            for label in self._desirability_labels.values():
                label.setText("—")
                _paint_desirability(label, None)
            self._hbd.setText("—")
            self._hba.setText("—")
            self._logd.setText("—")
            self._cns.setText("—")
            self._cns_score.setText("—")
            self._ab_mps.setText("—")
            self._ab_mps_score.setText("—")
            return
        by_key = {term.key: term for term in snapshot.terms}
        for key, label in self._value_labels.items():
            term = by_key.get(key)
            label.setText("—" if term is None else _fmt_num(term.value, _TERM_DIGITS.get(key, 2)))
            desir = None if term is None else term.desirability
            score = self._desirability_labels[key]
            score.setText(_fmt_num(desir, 2))
            score.setToolTip(f"{_term_label(key)} desirability {_fmt_num(desir, 2)}")
            _paint_desirability(score, desir)
        self._hbd.setText("—" if snapshot.hbd is None else str(snapshot.hbd))
        self._hba.setText("—" if snapshot.hba is None else str(snapshot.hba))
        self._set_ionization_pair(self._logd, None, snapshot.logd)
        self._set_ionization_pair(self._cns, self._cns_score, snapshot.cns_mpo)
        self._set_ionization_pair(self._ab_mps, self._ab_mps_score, snapshot.ab_mps)

    def _set_ionization_pair(
        self, value_label: QLabel, score_label: QLabel | None, value: float | None
    ) -> None:
        text = _fmt_num(value, 2)
        value_label.setText(text)
        if score_label is not None:
            score_label.setText(text)

    def _apply_ionization(self, result: dict) -> None:
        logd = result.get("logd")
        cns = result.get("cns_mpo")
        ab_mps = result.get("ab_mps")
        if logd is not None:
            self._logd.setText(_fmt_num(float(logd), 2))
            self._logd.setToolTip("Uni-pKa LogD at pH 7.4.")
        pkas = result.get("pka_values") or ()
        if isinstance(pkas, (list, tuple)) and pkas:
            self._pka.setText(", ".join(f"{float(value):.2f}" for value in pkas))
            self._pka.setToolTip("")
        else:
            self._pka.setText("—")
        if cns is not None:
            text = _fmt_num(float(cns), 2)
            self._cns.setText(text)
            self._cns_score.setText(text)
            tip = "Wager CNS MPO (0–6) with Uni-pKa."
            self._cns.setToolTip(tip)
            self._cns_score.setToolTip(tip)
        if ab_mps is not None:
            text = _fmt_num(float(ab_mps), 2)
            self._ab_mps.setText(text)
            self._ab_mps_score.setText(text)
            tip = "AbbVie MPS with Uni-pKa LogD. Lower is more druglike."
            self._ab_mps.setToolTip(tip)
            self._ab_mps_score.setToolTip(tip)

    def _start_or_coalesce_ionization(self, mol: Chem.Mol, generation: int) -> None:
        if self._ion_busy:
            self._pending_mol = mol
            self._pending_generation = generation
            return
        self._ion_busy = True
        self._active_generation = generation
        self._cancel_event = threading.Event()
        worker = _StudioIonWorker(mol, generation, self._ion_signals, self._cancel_event)
        start_runnable_on_app_pool(getattr(self._sketcher, "parent_app", None), worker)

    def _drain_pending_ionization(self) -> None:
        pending = self._pending_mol
        generation = self._pending_generation
        self._pending_mol = None
        if pending is None or generation != self._generation:
            return
        self._start_or_coalesce_ionization(pending, generation)

    def _release_ionization_busy(self, generation: int) -> None:
        if generation == self._active_generation:
            self._ion_busy = False

    def _on_ionization_finished(self, generation: int, result: object) -> None:
        self._release_ionization_busy(generation)
        if generation != self._generation or not isinstance(result, dict):
            self._drain_pending_ionization()
            return
        try:
            self._apply_ionization(result)
        except (TypeError, ValueError):
            logger.debug("design studio ionization result was unreadable", exc_info=True)
            self._pka.setText("—")
        self._drain_pending_ionization()

    def _on_ionization_failed(self, generation: int, msg: str) -> None:
        self._release_ionization_busy(generation)
        if generation != self._generation:
            self._drain_pending_ionization()
            return
        if msg != "cancelled":
            self._pka.setText("—")
            self._pka.setToolTip(msg or _PKA_FAILED)
        self._drain_pending_ionization()


def _term_label(key: str) -> str:
    for term_key, label in (
        ("MW", "MW"),
        ("LogP", "LogP"),
        ("TPSA", "TPSA"),
        ("QED", "QED"),
        ("RotBonds", "Rotatable bonds"),
    ):
        if term_key == key:
            return label
    return key


class DesignList(QWidget):
    """Suggestions and bioisosteric replacements that can be sent to the table."""

    def __init__(self, studio: DesignStudioPanel):
        super().__init__(studio)
        self._studio = studio
        self._entries: list[DesignSuggestion] = []
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 4, 8, 8)
        root.setSpacing(6)
        title = QLabel("Design list")
        title_font = QFont(title.font())
        title_font.setBold(True)
        title.setFont(title_font)
        title.setToolTip(
            "Suggestions and bioisosteric replacements for this session. "
            "Select rows and send the ones you want to the table."
        )
        root.addWidget(title)
        self._list = QListWidget(self)
        self._list.setSelectionMode(QListWidget.ExtendedSelection)
        self._list.itemClicked.connect(self._apply_current)
        self._list.itemSelectionChanged.connect(self._sync_buttons)
        root.addWidget(self._list, 1)
        buttons = QHBoxLayout()
        self._add_btn = QPushButton("Add suggestions", self)
        self._add_btn.setToolTip(
            "Add MMP transforms and one-point R-group swaps for the current sketch."
        )
        style_plot_footer_text_button(self._add_btn)
        self._add_btn.clicked.connect(self.add_suggestions)
        self._send_btn = QPushButton("Send to table", self)
        self._send_btn.setToolTip("Add the selected designs to the main table.")
        style_plot_footer_text_button(self._send_btn)
        self._send_btn.clicked.connect(self.send_selected)
        self._remove_btn = QPushButton("Remove", self)
        self._remove_btn.setToolTip("Remove the selected designs from this list.")
        style_plot_footer_text_button(self._remove_btn)
        self._remove_btn.clicked.connect(self.remove_selected)
        buttons.addWidget(self._add_btn)
        buttons.addWidget(self._send_btn)
        buttons.addWidget(self._remove_btn)
        root.addLayout(buttons)
        self._rebuild()

    def add_suggestions(self) -> None:
        """Append MMP and R-group ideas for the current sketch. Existing rows stay."""
        studio = self._studio
        pairs = []
        app = studio.parent_app
        if app is not None:
            pairs = list(getattr(app, "_mmp_last_pairs", None) or [])
        suggestions = mmp_suggestions(studio.current_mol(), pairs)
        suggestions.extend(rgroup_swap_suggestions(studio.current_smiles(), studio.series_rows()))
        if not suggestions:
            studio.show_status("No suggestions for this structure. Run MMP, or decompose a series.")
            return
        added = self._append(suggestions)
        if added:
            studio.show_status(f"Added {added} suggestion(s) to the design list.")
            return
        studio.show_status("Those suggestions are already on the design list.")

    def add_bioisosteres(self, products: list[tuple[str, str]]) -> int:
        """Append ``(replacement name, SMILES)`` rows. Returns how many were new."""
        entries: list[DesignSuggestion] = []
        for name, smiles in products:
            canon = _canonical_smiles(smiles)
            if not canon:
                continue
            title = (name or "").strip() or "Bioisostere"
            entries.append(
                DesignSuggestion(smiles=canon, title=title, detail=canon, source="bioisostere")
            )
        return self._append(entries)

    def send_selected(self) -> None:
        """Add the selected designs to the main table. Rows that are already there stay put."""
        studio = self._studio
        smiles = self._selected_smiles()
        if not smiles:
            studio.show_status("Select designs to send to the table.")
            return
        app = studio.parent_app
        if app is None:
            studio.show_status("Open the Design Studio from a table before sending designs.")
            return
        fresh = [one for one in smiles if _oid_with_smiles(app, one) is None]
        already = len(smiles) - len(fresh)
        if not fresh:
            studio.show_status("Those designs are already in the table.")
            return
        noun = "design" if len(fresh) == 1 else "designs"
        if not studio._sketcher._confirm_table_write(
            "Send to table",
            f"Send {len(fresh)} {noun} to the table as new rows?",
        ):
            return
        added = studio._sketcher._append_molecules_from_smiles_parts(fresh)
        if added <= 0:
            studio.show_status("Could not add these designs to the table.")
            return
        sent = "design" if added == 1 else "designs"
        message = f"Sent {added} {sent} to the table."
        if already:
            message += f" {already} already there."
        studio.show_status(message)
        status = getattr(app, "status_label", None)
        if status is not None:
            status.setText(f"{TOOL_DESIGN_STUDIO}: {message}")

    def remove_selected(self) -> None:
        indices = []
        for item in self._list.selectedItems():
            index = item.data(Qt.UserRole + 1)
            if isinstance(index, int):
                indices.append(index)
        if not indices:
            return
        for index in sorted(set(indices), reverse=True):
            if 0 <= index < len(self._entries):
                del self._entries[index]
        self._rebuild()
        self._studio.show_status("Removed the selected designs.")

    def _append(self, entries: list[DesignSuggestion]) -> int:
        known = {entry.smiles for entry in self._entries}
        added = 0
        for entry in entries:
            smiles = _canonical_smiles(entry.smiles)
            if not smiles or smiles in known:
                continue
            known.add(smiles)
            self._entries.append(
                DesignSuggestion(
                    smiles=smiles,
                    title=entry.title,
                    detail=entry.detail,
                    source=entry.source,
                )
            )
            added += 1
        if added:
            self._rebuild()
        return added

    def _selected_smiles(self) -> list[str]:
        found: list[str] = []
        seen: set[str] = set()
        for item in self._list.selectedItems():
            raw = item.data(Qt.UserRole)
            if not isinstance(raw, str) or not raw.strip() or raw in seen:
                continue
            seen.add(raw)
            found.append(raw)
        return found

    def _rebuild(self) -> None:
        self._list.clear()
        if not self._entries:
            item = QListWidgetItem("No designs yet.")
            item.setFlags(item.flags() & ~Qt.ItemIsSelectable & ~Qt.ItemIsEnabled)
            self._list.addItem(item)
            self._sync_buttons()
            return
        for index, entry in enumerate(self._entries):
            kind = "Bioisostere" if entry.source == "bioisostere" else "Suggestion"
            item = QListWidgetItem(f"{kind} · {entry.title}\n{entry.detail}")
            item.setToolTip(entry.detail)
            item.setData(Qt.UserRole, entry.smiles)
            item.setData(Qt.UserRole + 1, index)
            self._list.addItem(item)
        self._sync_buttons()

    def _sync_buttons(self) -> None:
        has_selection = bool(self._selected_smiles())
        self._send_btn.setEnabled(has_selection)
        self._remove_btn.setEnabled(has_selection)

    def _apply_current(self, item: QListWidgetItem) -> None:
        smiles = item.data(Qt.UserRole)
        if not smiles:
            return
        self._studio.load_smiles(str(smiles), caption=item.text().split("\n", 1)[0])


class DesignStudioPanel(QWidget):
    """Sketcher on the left, scores and the design list on the right."""

    dockable_in_workspace = False
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = TOOL_DESIGN_STUDIO

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._sketcher = SketcherDialog(self, app=parent_app)
        self._sketcher.install_chemistry_menu()
        self._sketcher.set_embedded(True)
        self._sketcher.prefer_host_window_edit_keys()
        self._sketcher.setMinimumSize(480, 320)

        self._strip = DesignPropertyStrip(self._sketcher, self)
        self._strip.setMinimumWidth(240)
        scroll = QScrollArea(self._sketcher)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self._strip)
        scroll.setMinimumWidth(250)
        scroll.setMaximumWidth(320)

        self._design_list = DesignList(self)
        self._sketcher._design_list = self._design_list
        right = QSplitter(Qt.Vertical, self._sketcher)
        right.setChildrenCollapsible(False)
        right.addWidget(scroll)
        right.addWidget(self._design_list)
        right.setStretchFactor(0, 1)
        right.setStretchFactor(1, 1)
        self._sketcher.place_beside_canvas(right)
        self._sketcher.show()
        root.addWidget(self._sketcher, 1)

        self._status = QStatusBar(self)
        self._sketcher.place_structure_status(self._status)
        self._status.showMessage("Ready.")
        root.addWidget(self._status)

        self._sketcher.canvas.sketchChanged.connect(self._strip.schedule_refresh)
        self._sketcher.canvas.statusMessage.connect(self.show_status)
        original_status = self._sketcher.show_sketch_status

        def _forward_status(message: str) -> None:
            original_status(message)
            self.show_status(message)

        self._sketcher.show_sketch_status = _forward_status
        self.setMinimumWidth(self.embedded_minimum_width())

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self.parent_app = parent_app
        self._app = parent_app
        if parent_app is not None and getattr(parent_app, "_table_model", None) is not None:
            self._sketcher.parent_app = parent_app

    def embedded_minimum_width(self) -> int:
        return 760

    def embedded_preferred_width(self) -> int:
        return 1100

    def create_floating_dialog(self, parent_app) -> DesignStudioWindow:
        self.show()
        dialog = DesignStudioWindow(parent_app, panel=self)
        if parent_app is not None:
            parent_app._design_studio_dialog = dialog
        return dialog

    def load_molecule(self, mol: Chem.Mol, *, caption: str = "") -> bool:
        """Replace the sketch. The design list is left as it is."""
        self._strip.set_caption(caption)
        loaded = self._sketcher.load_structure_from_mol(mol, confirm_if_nonempty=False)
        if loaded:
            self._strip.schedule_refresh()
        return loaded

    def load_smiles(self, smiles: str, *, caption: str = "") -> bool:
        mol = Chem.MolFromSmiles((smiles or "").strip())
        if mol is None:
            self.show_status("That design could not be read.")
            return False
        return self.load_molecule(mol, caption=caption)

    def show_status(self, message: str) -> None:
        """One line at the bottom of the studio, the same role as the sketcher status bar."""
        self._status.showMessage((message or "").strip() or "Ready.")

    def current_mol(self) -> Chem.Mol | None:
        try:
            return self._sketcher._sketch_mol_for_3d()
        except (RuntimeError, ValueError, TypeError, AttributeError):
            return None

    def current_smiles(self) -> str:
        mol = self.current_mol()
        if mol is None:
            return ""
        try:
            return Chem.MolToSmiles(Chem.Mol(mol), canonical=True) or ""
        except (RuntimeError, ValueError, TypeError):
            return ""

    def series_rows(self) -> list[SeriesRow]:
        """Decomposed table rows used for one-point swaps."""
        app = self.parent_app
        model = getattr(app, "_table_model", None) if app is not None else None
        headers = list(getattr(app, "headers", []) or [])
        if app is None or model is None or not headers:
            return []
        row_axis, col_axis, page_axis = suggest_rgroup_axes(headers)
        axes = [name for name in (row_axis, col_axis, page_axis) if name]
        if len(axes) < 2:
            axes = [name for name in headers if rgroup_index(name) is not None]
        if not axes:
            return []
        core_column = suggest_core_column(headers, axes[0])
        if not core_column:
            return []
        activity = _activity_column(headers, _numeric_headers(model))
        rows: list[SeriesRow] = []
        mols = getattr(app, "mols", {}) or {}
        for index in range(model.rowCount()):
            try:
                oid = int(model.row_oid(index))
            except (TypeError, ValueError):
                continue
            substituents = tuple((axis, _cell_text(model, index, axis, headers)) for axis in axes)
            product = ""
            mol = mols.get(oid)
            if mol is not None:
                try:
                    product = Chem.MolToSmiles(mol, canonical=True) or ""
                except (RuntimeError, ValueError, TypeError):
                    product = ""
            activity_value = None
            if activity:
                activity_value = parse_activity_float(_cell_text(model, index, activity, headers))
            rows.append(
                SeriesRow(
                    core_smiles=_cell_text(model, index, core_column, headers),
                    substituents=substituents,
                    activity=activity_value,
                    product_smiles=product,
                )
            )
        return rows

    def shutdown(self) -> None:
        self._strip.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        self.shutdown()
        super().closeEvent(event)


def _numeric_headers(model) -> set[str]:
    bounds = getattr(model, "numeric_bounds_by_column", None)
    if not callable(bounds):
        return set()
    try:
        found = bounds()
    except (RuntimeError, TypeError, ValueError):
        return set()
    if isinstance(found, dict):
        return set(found)
    return set(found or ())


def _activity_column(headers: list[str], numeric: set[str]) -> str | None:
    preferred = ("pic50", "pki", "pec50", "ic50", "ki", "activity", "potency")
    names = [name for name in headers if name in numeric and name not in {"ID_HIDDEN"}]
    for token in preferred:
        for name in names:
            if token in name.casefold():
                return name
    return names[0] if names else None


def _cell_text(model, row: int, header: str, headers: list[str]) -> str:
    if header not in headers:
        return ""
    column = headers.index(header)
    text = (model.cell_text(row, column) or "").strip()
    if text:
        return text
    backing = getattr(model, "backing_value_for_row_header", None)
    if not callable(backing):
        return ""
    return (backing(row, header) or "").strip()


def _oid_with_smiles(app, smiles: str) -> int | None:
    target = (smiles or "").strip()
    mols = getattr(app, "mols", None) or {}
    for oid, mol in mols.items():
        try:
            current = Chem.MolToSmiles(mol, canonical=True) or ""
        except (RuntimeError, ValueError, TypeError):
            continue
        if current == target:
            return int(oid)
    return None


class DesignStudioWindow(BrowserHostDialog):
    """Floating shell for :class:`DesignStudioPanel`."""

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().changeEvent(event)
        if event.type() != QEvent.ActivationChange:
            return
        panel = getattr(self, "_panel", None)
        sketcher = getattr(panel, "_sketcher", None) if panel is not None else None
        sync = getattr(sketcher, "_sync_parent_edit_hotkeys", None)
        if callable(sync):
            sync()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if not getattr(self, "_force_close", False):
            answer = QMessageBox.question(
                self,
                self.close_title,
                self.close_message,
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
        else:
            self._force_close = False
        panel = getattr(self, "_panel", None)
        shutdown = getattr(panel, "shutdown", None)
        if callable(shutdown):
            shutdown()
        event.accept()

    default_title = TOOL_DESIGN_STUDIO
    close_title = "Close Design Studio"
    close_message = "Close the Design Studio?"
    panel_cls = DesignStudioPanel
    min_size = (900, 560)
    initial_size = (1180, 760)
