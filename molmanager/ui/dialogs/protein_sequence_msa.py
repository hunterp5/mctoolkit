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

"""Protein → Sequence: FASTA / Viewer-chain MSA via local MAFFT."""

from __future__ import annotations

import threading
from pathlib import Path

from PyQt5.QtCore import Qt, QThreadPool
from PyQt5.QtGui import QCloseEvent
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.bundled_paths import ensure_mafft_ready, resolve_mafft_executable
from ...protein.protein_msa import (
    FastaRecord,
    alignment_html,
    format_identity_matrix,
    parse_fasta,
    record_from_viewer_chain,
    records_to_clustal,
    records_to_fasta,
    unique_record_name,
)
from ...workers.protein_msa import MafftAlignWorker
from ..qt_widget_utils import make_window_resizable, qobject_is_deleted

_POOL_ROLE = Qt.UserRole
_FASTA_FILTER = "FASTA (*.fa *.fasta *.faa *.txt);;All files (*)"


class _PasteFastaDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Paste FASTA / sequences")
        self.resize(520, 360)
        root = QVBoxLayout(self)
        hint = QLabel("Paste FASTA records or bare amino-acid sequences (blank-line separated).")
        hint.setWordWrap(True)
        root.addWidget(hint)
        self.edit = QPlainTextEdit()
        self.edit.setPlaceholderText(">seq1\nMKTAYIAK...\n>seq2\nMKTAYIAQ...")
        root.addWidget(self.edit, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def text(self) -> str:
        return self.edit.toPlainText()


class ProteinSequenceMsaDialog(QDialog):
    """Modeless multiple-sequence alignment workspace (not the Viewer chain editor)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Protein Sequence")
        self.setMinimumSize(780, 560)
        self.resize(920, 640)
        make_window_resizable(self)

        self._aligned: list[FastaRecord] = []
        self._worker: MafftAlignWorker | None = None
        self._cancel_event: threading.Event | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        hint = QLabel(
            "Align amino-acid sequences with a local MAFFT install. "
            "This window is independent of Protein Viewer → Sequence (the 3D chain editor)."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        splitter = QSplitter(Qt.Vertical)
        root.addWidget(splitter, 1)

        pool_box = QGroupBox("Sequences")
        pool_l = QHBoxLayout(pool_box)
        self.pool = QListWidget()
        self.pool.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.pool.itemSelectionChanged.connect(self._sync_pool_buttons)
        self.pool.itemDoubleClicked.connect(lambda _item: self._rename_selected())
        pool_l.addWidget(self.pool, 1)

        side = QVBoxLayout()
        self.btn_open = QPushButton("Open FASTA…")
        self.btn_open.clicked.connect(self._open_fasta)
        self.btn_paste = QPushButton("Paste FASTA / sequences…")
        self.btn_paste.clicked.connect(self._paste_fasta)
        self.btn_viewer = QPushButton("Add from Protein Viewer")
        self.btn_viewer.setToolTip("Copy polymer chains from the open Protein Viewer.")
        self.btn_viewer.clicked.connect(self._add_from_viewer)
        self.btn_rename = QPushButton("Rename")
        self.btn_rename.clicked.connect(self._rename_selected)
        self.btn_remove = QPushButton("Remove")
        self.btn_remove.clicked.connect(self._remove_selected)
        for btn in (
            self.btn_open,
            self.btn_paste,
            self.btn_viewer,
            self.btn_rename,
            self.btn_remove,
        ):
            side.addWidget(btn)
        side.addStretch(1)
        pool_l.addLayout(side)
        splitter.addWidget(pool_box)

        view_host = QWidget()
        view_l = QVBoxLayout(view_host)
        view_l.setContentsMargins(0, 0, 0, 0)
        self.tabs = QTabWidget()
        self.align_view = QTextBrowser()
        self.align_view.setOpenExternalLinks(False)
        self.tabs.addTab(self.align_view, "Alignment")
        self.identity_view = QPlainTextEdit()
        self.identity_view.setReadOnly(True)
        self.identity_view.setPlaceholderText("Pairwise percent identity after alignment.")
        self.tabs.addTab(self.identity_view, "Identity")
        view_l.addWidget(self.tabs, 1)
        splitter.addWidget(view_host)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        run_row = QHBoxLayout()
        self.btn_align = QPushButton("Align")
        self.btn_align.setToolTip("Need at least two sequences. Runs MAFFT --auto --amino.")
        self.btn_align.clicked.connect(self._align)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_align)
        self.btn_export_fa = QPushButton("Export FASTA…")
        self.btn_export_fa.clicked.connect(lambda: self._export("fasta"))
        self.btn_export_aln = QPushButton("Export Clustal…")
        self.btn_export_aln.clicked.connect(lambda: self._export("clustal"))
        run_row.addWidget(self.btn_align)
        run_row.addWidget(self.btn_cancel)
        run_row.addStretch(1)
        run_row.addWidget(self.btn_export_fa)
        run_row.addWidget(self.btn_export_aln)
        root.addLayout(run_row)

        self.status = QLabel("Add at least two sequences, then Align.")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        close_box = QDialogButtonBox(QDialogButtonBox.Close)
        close_box.rejected.connect(self.close)
        close_box.accepted.connect(self.close)
        root.addWidget(close_box)

        self._sync_pool_buttons()
        self._sync_export_buttons()

    def pool_records(self) -> list[FastaRecord]:
        records: list[FastaRecord] = []
        for i in range(self.pool.count()):
            rec = self.pool.item(i).data(_POOL_ROLE)
            if isinstance(rec, FastaRecord) and rec.sequence:
                records.append(rec)
        return records

    def _pool_names(self) -> set[str]:
        return {rec.name for rec in self.pool_records()}

    def _add_records(self, incoming: list[FastaRecord]) -> int:
        added = 0
        names = self._pool_names()
        for rec in incoming:
            if not rec.sequence:
                continue
            name = unique_record_name(rec.name, names)
            names.add(name)
            stored = FastaRecord(name=name, sequence=rec.sequence)
            item = QListWidgetItem(self._item_label(stored))
            item.setData(_POOL_ROLE, stored)
            self.pool.addItem(item)
            added += 1
        self._sync_pool_buttons()
        return added

    @staticmethod
    def _item_label(rec: FastaRecord) -> str:
        return f"{rec.name}  ({len(rec.sequence)} aa)"

    def _open_fasta(self) -> None:
        path, _filt = QFileDialog.getOpenFileName(self, "Open FASTA", "", _FASTA_FILTER)
        if not path:
            return
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Open FASTA", str(exc))
            return
        records = parse_fasta(text)
        if not records:
            QMessageBox.information(
                self, "Open FASTA", "No amino-acid sequences found in that file."
            )
            return
        n = self._add_records(records)
        self.status.setText(f"Added {n} sequence(s) from {Path(path).name}.")

    def _paste_fasta(self) -> None:
        dlg = _PasteFastaDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        records = parse_fasta(dlg.text())
        if not records:
            QMessageBox.information(self, "Paste sequences", "No amino-acid sequences found.")
            return
        n = self._add_records(records)
        self.status.setText(f"Added {n} sequence(s) from paste.")

    def _add_from_viewer(self) -> None:
        app = self.parent_app
        viewer = getattr(app, "_protein_viewer_dialog", None) if app is not None else None
        if viewer is None or qobject_is_deleted(viewer):
            QMessageBox.information(
                self,
                "Protein Viewer",
                "Open Protein → Viewer and load a structure first, then add chains here.",
            )
            return
        refresh = getattr(viewer, "_refresh_sequence_chains", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass
        chains = list(getattr(viewer, "_sequence_chains", None) or [])
        incoming: list[FastaRecord] = []
        for chain in chains:
            stem = Path(getattr(chain, "structure_name", "") or "viewer").stem
            cid = getattr(chain, "chain", "") or "?"
            rec = record_from_viewer_chain(f"{stem}_chain_{cid}", getattr(chain, "sequence", ""))
            if rec is not None:
                incoming.append(rec)
        if not incoming:
            QMessageBox.information(
                self,
                "Protein Viewer",
                "No polymer amino-acid sequences are available in the Viewer.",
            )
            return
        n = self._add_records(incoming)
        self.status.setText(f"Added {n} chain(s) from Protein Viewer.")

    def _rename_selected(self) -> None:
        items = self.pool.selectedItems()
        if len(items) != 1:
            return
        item = items[0]
        rec = item.data(_POOL_ROLE)
        if not isinstance(rec, FastaRecord):
            return
        text, ok = QInputDialog.getText(self, "Rename sequence", "Name:", text=rec.name)
        if not ok:
            return
        label = (text or "").strip()
        if not label:
            return
        names = self._pool_names() - {rec.name}
        new_name = unique_record_name(label, names) if label in names else label
        updated = FastaRecord(name=new_name, sequence=rec.sequence)
        item.setData(_POOL_ROLE, updated)
        item.setText(self._item_label(updated))

    def _remove_selected(self) -> None:
        for item in list(self.pool.selectedItems()):
            row = self.pool.row(item)
            self.pool.takeItem(row)
        self._sync_pool_buttons()

    def _sync_pool_buttons(self) -> None:
        selected = len(self.pool.selectedItems())
        self.btn_rename.setEnabled(selected == 1)
        self.btn_remove.setEnabled(selected >= 1)
        running = self._worker is not None
        self.btn_align.setEnabled((not running) and len(self.pool_records()) >= 2)

    def _sync_export_buttons(self) -> None:
        has = len(self._aligned) >= 2
        self.btn_export_fa.setEnabled(has)
        self.btn_export_aln.setEnabled(has)

    def _align(self) -> None:
        records = self.pool_records()
        if len(records) < 2:
            QMessageBox.information(self, "Align", "Need at least two sequences to align.")
            return
        missing = ensure_mafft_ready()
        if missing:
            QMessageBox.warning(self, "MAFFT not found", missing)
            return
        exe = resolve_mafft_executable()
        if not exe:
            QMessageBox.warning(self, "MAFFT not found", missing or "MAFFT was not found.")
            return
        self._cancel_event = threading.Event()
        worker = MafftAlignWorker(records, exe, cancel_event=self._cancel_event)
        worker.signals.finished.connect(self._on_aligned)
        worker.signals.failed.connect(self._on_align_failed)
        self._worker = worker
        self.btn_cancel.setEnabled(True)
        self._sync_pool_buttons()
        self.status.setText("Running MAFFT…")
        QThreadPool.globalInstance().start(worker)

    def _cancel_align(self) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        self.status.setText("Cancelling…")

    def _on_aligned(self, aligned: list) -> None:
        if qobject_is_deleted(self):
            return
        self._clear_worker()
        rows = [r for r in aligned if isinstance(r, FastaRecord)]
        if len(rows) < 2:
            self.status.setText("MAFFT did not return an alignment.")
            return
        self._aligned = rows
        self.align_view.setHtml(alignment_html(rows))
        self.identity_view.setPlainText(format_identity_matrix(rows))
        length = max(len(r.sequence) for r in rows)
        self.status.setText(f"Aligned {len(rows)} sequences ({length} columns).")
        self.tabs.setCurrentIndex(0)
        self._sync_export_buttons()

    def _on_align_failed(self, message: str) -> None:
        if qobject_is_deleted(self):
            return
        self._clear_worker()
        text = (message or "").strip() or "MAFFT alignment failed."
        self.status.setText(text)
        if text != "Cancelled.":
            QMessageBox.warning(self, "MAFFT", text)

    def _clear_worker(self) -> None:
        self._worker = None
        self._cancel_event = None
        self.btn_cancel.setEnabled(False)
        self._sync_pool_buttons()

    def _export(self, kind: str) -> None:
        if len(self._aligned) < 2:
            QMessageBox.information(self, "Export", "Align sequences first.")
            return
        if kind == "clustal":
            path, _filt = QFileDialog.getSaveFileName(
                self, "Export Clustal", "alignment.aln", "Clustal (*.aln *.clustal);;All files (*)"
            )
            body = records_to_clustal(self._aligned)
        else:
            path, _filt = QFileDialog.getSaveFileName(
                self, "Export FASTA", "alignment.fa", "FASTA (*.fa *.fasta);;All files (*)"
            )
            body = records_to_fasta(self._aligned)
        if not path:
            return
        try:
            Path(path).write_text(body, encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Export", str(exc))
            return
        self.status.setText(f"Wrote {Path(path).name}.")

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._cancel_event is not None:
            self._cancel_event.set()
        super().closeEvent(event)
