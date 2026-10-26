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

"""Sketcher with a live descriptor and druglike MPO strip.

Opens in its own window. The footer can dock it beside the table.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from PyQt5.QtCore import QEvent, QObject, QRunnable, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ..analysis.design_studio import DesignSnapshot, compute_design_snapshot
from .sketcher.dialog import SketcherDialog
from .sketcher.physical_properties import compute_ionization_properties
from .browsers.chrome import BrowserHostDialog, apply_browser_body_layout
from .dockable_plot import (
    apply_plot_chrome_glyphs,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_close_plot_button,
    make_send_window_button,
    request_close_plot_widget,
    style_plot_footer_text_button,
    sync_docked_footer_bar,
    sync_footer_on_parent_change,
)
from .strings import TOOL_DESIGN_STUDIO
from .threadpool_access import start_runnable_on_app_pool

logger = logging.getLogger(__name__)

_DEFAULT_CAPTION = "Draw a structure. Scores update as the sketch changes."
_PKA_FAILED = "pKa calculation failed"
_TERM_DIGITS = {"MW": 2, "LogP": 2, "TPSA": 1, "QED": 3, "RotBonds": 0}


def _fmt_num(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{value:.{digits}f}"


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

        self._caption = QLabel(_DEFAULT_CAPTION)
        self._caption.setWordWrap(True)
        root.addWidget(self._caption)

        self._mpo_title = QLabel("Druglike MPO")
        title_font = QFont(self._mpo_title.font())
        title_font.setBold(True)
        self._mpo_title.setFont(title_font)
        self._mpo_title.setToolTip(
            "Geometric mean of desirability for MW, LogP, TPSA, QED, and rotatable bonds. "
            "MW scores 1 at or below 350 and 0 at or above 500. "
            "LogP is 1 at 2.5 and 0 outside 0–5. "
            "TPSA is 1 at 75 and 0 outside 20–140. "
            "QED scores 0 at or below 0.3 and 1 at or above 0.7. "
            "Rotatable bonds score 1 at or below 5 and 0 at or above 10. "
            "One property outside its gate pulls this score to zero."
        )
        root.addWidget(self._mpo_title)

        self._mpo_value = QLabel("—")
        mpo_font = QFont(self._mpo_value.font())
        mpo_font.setPointSize(mpo_font.pointSize() + 6)
        mpo_font.setBold(True)
        self._mpo_value.setFont(mpo_font)
        root.addWidget(self._mpo_value)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        grid.addWidget(QLabel("Property"), 0, 0)
        grid.addWidget(QLabel("Value"), 0, 1)
        score_header = QLabel("D")
        score_header.setToolTip("Desirability, from 0 to 1.")
        grid.addWidget(score_header, 0, 2)
        self._value_labels: dict[str, QLabel] = {}
        self._desirability_labels: dict[str, QLabel] = {}
        for row, key in enumerate(("MW", "LogP", "TPSA", "QED", "RotBonds"), start=1):
            grid.addWidget(QLabel(_term_label(key)), row, 0)
            value = QLabel("—")
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            desir = QLabel("—")
            desir.setTextInteractionFlags(Qt.TextSelectableByMouse)
            grid.addWidget(value, row, 1)
            grid.addWidget(desir, row, 2)
            self._value_labels[key] = value
            self._desirability_labels[key] = desir
        root.addLayout(grid)

        self._hbd_hba = QLabel("HBD / HBA  —")
        self._ro5 = QLabel("Ro5  —")
        root.addWidget(self._hbd_hba)
        root.addWidget(self._ro5)

        self._logd = QLabel("LogD (7.4)  —")
        self._pka = QLabel("pKa  —")
        self._cns = QLabel("CNS MPO  —")
        self._ab_mps = QLabel("AB-MPS  —")
        for label in (self._logd, self._pka, self._cns, self._ab_mps):
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            root.addWidget(label)
        self._logd.setToolTip("Heuristic until a Uni-pKa result replaces it.")
        self._cns.setToolTip("Wager CNS MPO (0–6). Heuristic until Uni-pKa finishes.")
        self._ab_mps.setToolTip(
            "AbbVie MPS. Lower is more druglike. Heuristic until Uni-pKa finishes."
        )
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(400)
        self._timer.timeout.connect(self._refresh_now)

    def set_caption(self, text: str) -> None:
        self._caption.setText((text or "").strip() or _DEFAULT_CAPTION)

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
            self._pka.setText("pKa  —")
            self._pka.setToolTip("")
            return
        self._pka.setText("pKa  …")
        self._pka.setToolTip("")
        try:
            mol_copy = Chem.Mol(mol)
        except TypeError:
            self._pka.setText("pKa  —")
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
            self._mpo_value.setText("—")
            for label in self._value_labels.values():
                label.setText("—")
            for label in self._desirability_labels.values():
                label.setText("—")
            self._hbd_hba.setText("HBD / HBA  —")
            self._ro5.setText("Ro5  —")
            self._logd.setText("LogD (7.4)  —")
            self._cns.setText("CNS MPO  —")
            self._ab_mps.setText("AB-MPS  —")
            return
        self._mpo_value.setText(_fmt_num(snapshot.mpo, 2))
        by_key = {term.key: term for term in snapshot.terms}
        for key, label in self._value_labels.items():
            term = by_key.get(key)
            label.setText("—" if term is None else _fmt_num(term.value, _TERM_DIGITS.get(key, 2)))
        for key, label in self._desirability_labels.items():
            term = by_key.get(key)
            desir = None if term is None else term.desirability
            label.setText(_fmt_num(desir, 2))
        self._hbd_hba.setText(f"HBD / HBA  {snapshot.hbd} / {snapshot.hba}")
        violations = snapshot.ro5_violations
        viol_text = "—" if violations is None else str(int(violations))
        self._ro5.setText(f"Ro5  {snapshot.ro5_pass or '—'} ({viol_text})")
        self._logd.setText(f"LogD (7.4)  {_fmt_num(snapshot.logd, 2)}")
        self._cns.setText(f"CNS MPO  {_fmt_num(snapshot.cns_mpo, 2)}")
        self._ab_mps.setText(f"AB-MPS  {_fmt_num(snapshot.ab_mps, 2)}")

    def _apply_ionization(self, result: dict) -> None:
        logd = result.get("logd")
        cns = result.get("cns_mpo")
        ab_mps = result.get("ab_mps")
        if logd is not None:
            self._logd.setText(f"LogD (7.4)  {_fmt_num(float(logd), 2)}")
            self._logd.setToolTip("Uni-pKa LogD at pH 7.4.")
        pkas = result.get("pka_values") or ()
        if isinstance(pkas, (list, tuple)) and pkas:
            text = ", ".join(f"{float(value):.2f}" for value in pkas)
            self._pka.setText(f"pKa  {text}")
            self._pka.setToolTip("")
        else:
            self._pka.setText("pKa  —")
        if cns is not None:
            self._cns.setText(f"CNS MPO  {_fmt_num(float(cns), 2)}")
            self._cns.setToolTip("Wager CNS MPO (0–6) with Uni-pKa.")
        if ab_mps is not None:
            self._ab_mps.setText(f"AB-MPS  {_fmt_num(float(ab_mps), 2)}")
            self._ab_mps.setToolTip("AbbVie MPS with Uni-pKa LogD. Lower is more druglike.")

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
            self._pka.setText("pKa  —")
        self._drain_pending_ionization()

    def _on_ionization_failed(self, generation: int, msg: str) -> None:
        self._release_ionization_busy(generation)
        if generation != self._generation:
            self._drain_pending_ionization()
            return
        if msg != "cancelled":
            self._pka.setText("pKa  —")
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


class DesignStudioPanel(QWidget):
    """Sketcher on the left, live scores on the right."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = TOOL_DESIGN_STUDIO

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._sketcher = SketcherDialog(self, app=parent_app)
        self._sketcher.set_embedded(True)
        self._sketcher.setMinimumSize(480, 320)

        self._strip = DesignPropertyStrip(self._sketcher, self)
        self._strip.setMinimumWidth(240)
        self._strip.setMaximumWidth(300)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setWidget(self._strip)
        scroll.setMinimumWidth(250)
        scroll.setMaximumWidth(310)

        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._sketcher)
        splitter.addWidget(scroll)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 0)
        self._sketcher.show()
        root.addWidget(splitter, 1)

        self._sketcher.canvas.sketchChanged.connect(self._strip.schedule_refresh)

        footer = QHBoxLayout()
        self._add_row_btn = QPushButton("Add to table", self)
        self._add_row_btn.setToolTip("Append the current sketch as a new table row.")
        style_plot_footer_text_button(self._add_row_btn)
        self._add_row_btn.clicked.connect(self._add_sketch_to_table)
        self._add_to_main_btn = make_add_to_main_button(self, tooltip="Dock beside the table")
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        self._send_window_btn = make_send_window_button(self, tooltip="Open in a separate window")
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        self._close_btn = make_close_plot_button(self, tooltip="Close the Drug Design Studio.")
        self._close_btn.clicked.connect(self._close_docked)
        footer.addWidget(self._add_row_btn)
        footer.addStretch(1)
        footer.addWidget(self._add_to_main_btn)
        footer.addWidget(self._send_window_btn)
        footer.addWidget(self._close_btn)
        root.addLayout(footer)
        self._sync_footer_chrome()
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
        """Replace the sketch. *caption* is the line above the scores."""
        self._strip.set_caption(caption)
        loaded = self._sketcher.load_structure_from_mol(mol, confirm_if_nonempty=False)
        if loaded:
            self._strip.schedule_refresh()
        return loaded

    def shutdown(self) -> None:
        self._strip.shutdown()

    def on_docked_plot_closing(self) -> None:
        self.shutdown()

    def _add_sketch_to_table(self) -> None:
        self._sketcher._add_to_table()

    def _add_to_main_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        dock = getattr(app, "dock_plot_widget", None)
        if not callable(dock) or not dock(self):
            return
        dlg = self.window()
        if isinstance(dlg, DesignStudioWindow):
            discard_host_dialog_after_dock(dlg, app, "_design_studio_dialog")

    def _send_to_new_window(self) -> None:
        app = self.parent_app
        if app is None:
            return
        undock = getattr(app, "undock_plot_to_window", None)
        if callable(undock):
            undock(self)

    def _close_docked(self) -> None:
        self.shutdown()
        request_close_plot_widget(
            self,
            title="Close Drug Design Studio",
            message="Close the Drug Design Studio?",
        )

    def _is_docked(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        return bool(callable(check) and check(self))

    def _sync_footer_chrome(self) -> None:
        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), DesignStudioWindow)
        docked = self._is_docked()
        self._add_to_main_btn.setVisible(floating or not docked)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(docked)
        sync_docked_footer_bar(self, docked=docked)

    def changeEvent(self, event) -> None:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API
        self.shutdown()
        super().closeEvent(event)


class DesignStudioWindow(BrowserHostDialog):
    """Floating shell for :class:`DesignStudioPanel`."""

    default_title = TOOL_DESIGN_STUDIO
    close_title = "Close Drug Design Studio"
    close_message = "Close the Drug Design Studio?"
    panel_cls = DesignStudioPanel
    min_size = (900, 560)
    initial_size = (1180, 760)
