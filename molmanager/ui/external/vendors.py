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

"""Query Database dialog for PubChem chemical vendors."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from PyQt5.QtCore import QObject, QRunnable, Qt, QUrl, pyqtSignal
from PyQt5.QtGui import QDesktopServices, QKeySequence
from PyQt5.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QShortcut,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)
from rdkit import Chem

from ...sources.pubchem_vendors import (
    COLUMN_PRODUCT_ID,
    COLUMN_VENDOR,
    VendorLookup,
    lookup_vendors,
)
from ..qt_widget_utils import apply_monospace_to_text_edit, make_window_minimizable
from ..threadpool_access import start_runnable_on_app_pool
from .query_form import DatabaseQueryBar

_TITLE = "Vendors"


@dataclass(frozen=True)
class VendorResult:
    smiles: str
    vendor: str
    product_id: str
    url: str
    fields: dict[str, str]


class _QuerySignals(QObject):
    progress = pyqtSignal(int, int, str)
    structure_done = pyqtSignal(list, str)
    finished = pyqtSignal(list, list)


class _VendorBatchWorker(QRunnable):
    def __init__(self, smiles_list: list[str]):
        super().__init__()
        self.smiles_list = smiles_list
        self.signals = _QuerySignals()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        results: list[VendorResult] = []
        logs: list[str] = []
        total = len(self.smiles_list)
        for done, smiles in enumerate(self.smiles_list, start=1):
            if self._cancel:
                logs.append("Cancelled by user.")
                self.signals.structure_done.emit([], "Cancelled by user.")
                break
            self.signals.progress.emit(done, total, smiles)
            query = (smiles or "").strip()
            batch: list[VendorResult] = []
            before = len(logs)
            if Chem.MolFromSmiles(query) is None:
                logs.append(f"{query} | invalid SMILES")
            else:
                lookup = lookup_vendors(query)
                _append_lookup(batch, logs, query, lookup)
            results.extend(batch)
            self.signals.structure_done.emit(batch, "\n".join(logs[before:]))
        self.signals.finished.emit(results, logs)


def _append_lookup(
    results: list[VendorResult],
    logs: list[str],
    smiles: str,
    lookup: VendorLookup,
) -> None:
    if lookup.error:
        logs.append(f"{smiles} | ERROR: {lookup.error}")
        return
    if lookup.cid is None:
        logs.append(f"{smiles} | no PubChem compound")
        return
    if not lookup.offers:
        logs.append(f"{smiles} | no vendors")
        return
    logs.append(f"{smiles} | CID={lookup.cid} | {len(lookup.offers)} vendor(s)")
    for offer in lookup.offers:
        results.append(
            VendorResult(
                smiles=smiles,
                vendor=offer.vendor,
                product_id=offer.product_id,
                url=offer.url,
                fields=offer.as_fields(),
            )
        )


def group_vendor_results(results: Sequence[VendorResult]) -> list[list[VendorResult]]:
    """Products grouped by query SMILES, in the order the queries were returned."""
    order: list[str] = []
    grouped: dict[str, list[VendorResult]] = {}
    for result in results:
        bucket = grouped.get(result.smiles)
        if bucket is None:
            bucket = []
            grouped[result.smiles] = bucket
            order.append(result.smiles)
        bucket.append(result)
    return [grouped[smiles] for smiles in order]


def _vendor_count_label(count: int) -> str:
    noun = "vendor" if count == 1 else "vendors"
    return f"{count} {noun}"


def _query_item(products: Sequence[VendorResult]) -> QTreeWidgetItem:
    """Collapsed parent for one query. Children are vendor, product ID, and URL."""
    smiles = products[0].smiles
    parent = QTreeWidgetItem([f"{smiles} — {_vendor_count_label(len(products))}", "", ""])
    parent.setToolTip(0, smiles)
    for product in products:
        child = QTreeWidgetItem([product.vendor, product.product_id, product.url])
        child.setToolTip(0, product.vendor)
        if product.product_id:
            child.setToolTip(1, product.product_id)
        if product.url:
            child.setToolTip(2, product.url)
        parent.addChild(child)
    return parent


def fill_vendor_tree(tree: QTreeWidget, results: Sequence[VendorResult]) -> None:
    """Replace the tree with one expandable row per query that has vendors."""
    tree.setUpdatesEnabled(False)
    tree.clear()
    for products in group_vendor_results(results):
        item = _query_item(products)
        tree.addTopLevelItem(item)
        item.setFirstColumnSpanned(True)
        item.setExpanded(False)
    tree.setUpdatesEnabled(True)


class VendorQueryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle("Query Database — Vendors")
        self.resize(860, 560)
        self._last: list[VendorResult] = []
        self._streamed = False
        self._worker: _VendorBatchWorker | None = None

        root = QVBoxLayout(self)
        self.query_bar = DatabaseQueryBar(self, include_mode=False)
        self.smiles = self.query_bar.smiles
        self.btn_query = self.query_bar.btn_query
        self.chk_only_selected = self.query_bar.chk_only_selected
        self.btn_sketch = self.query_bar.btn_sketch
        self.smiles.setPlaceholderText("Paste one SMILES per line, or use the Sketcher…")
        self.btn_query.setToolTip(
            "Look up chemical vendors for the SMILES above, or for selected rows "
            "when “Only Query Selected” is checked."
        )
        self.btn_query.clicked.connect(self._run_query)
        self.btn_sketch.clicked.connect(self._use_sketcher)
        root.addWidget(self.query_bar)

        self.status = QLabel("")
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Query / Vendor", "Product ID", "URL"])
        self.tree.setAlternatingRowColors(True)
        self.tree.setUniformRowHeights(True)
        self.tree.setRootIsDecorated(True)
        self.tree.setExpandsOnDoubleClick(True)
        self.tree.setToolTip(
            "Expand a query to see its vendors. Double-click a URL to open the product page."
        )
        header = self.tree.header()
        header.setStretchLastSection(True)
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.tree.itemDoubleClicked.connect(self._open_product_url)
        root.addWidget(self.tree, 1)

        self.out = QTextEdit()
        self.out.setReadOnly(True)
        self.out.setPlaceholderText(
            "Structures with no vendor, and any lookup errors, are listed here."
        )
        self.out.setMaximumHeight(96)
        apply_monospace_to_text_edit(self.out)
        root.addWidget(self.out)

        bottom = QHBoxLayout()
        self.btn_add = QPushButton("Add result(s) to table")
        self.btn_add.setEnabled(False)
        self.btn_add.clicked.connect(self._add_to_table)
        bottom.addWidget(self.btn_add)
        self.btn_add_unique = QPushButton("Add unique products only")
        self.btn_add_unique.setEnabled(False)
        self.btn_add_unique.setToolTip(
            "Skip a row when the same structure, vendor, and product ID is already "
            "in the table or already in this result."
        )
        self.btn_add_unique.clicked.connect(self._add_unique_to_table)
        bottom.addWidget(self.btn_add_unique)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.clicked.connect(self._cancel_query)
        bottom.addWidget(self.btn_cancel)
        bottom.addStretch()
        root.addLayout(bottom)

        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self._run_query)
        make_window_minimizable(self)

    def _parse_smiles_inputs(self) -> list[str]:
        raw = (self.smiles.text() or "").strip()
        if not raw:
            return []
        parts = [part.strip() for part in raw.replace(";", "\n").splitlines() if part.strip()]
        out: list[str] = []
        seen: set[str] = set()
        for part in parts:
            if part not in seen:
                out.append(part)
                seen.add(part)
        return out

    def _selected_smiles(self) -> list[str] | None:
        app = self.parent_app
        if app is None:
            QMessageBox.information(self, _TITLE, "Main application is not available.")
            return None
        try:
            smiles_list = app._selected_smiles_strings()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            smiles_list = []
        if not smiles_list:
            QMessageBox.information(
                self, _TITLE, "Select one or more rows that have a SMILES value first."
            )
            return None
        return list(smiles_list)

    def _use_sketcher(self) -> None:
        try:
            from ..sketcher import SketcherDialog
        except ImportError as exc:
            QMessageBox.warning(self, _TITLE, str(exc))
            return
        dlg = SketcherDialog(self.parent_app if self.parent_app is not None else self)
        dlg.setModal(True)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.exec_()
        try:
            parts = dlg.canvas.fragment_smiles_parts()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            parts = []
        if not parts:
            QMessageBox.information(
                self, _TITLE, "No valid SMILES could be exported from the sketch."
            )
            return
        self.chk_only_selected.setChecked(False)
        self.smiles.setText("\n".join(parts))
        self.status.setText("SMILES loaded from sketcher — press Query when ready.")

    def _run_query(self) -> None:
        if self.chk_only_selected.isChecked():
            smiles_list = self._selected_smiles()
            if not smiles_list:
                return
        else:
            smiles_list = self._parse_smiles_inputs()
            if not smiles_list:
                QMessageBox.information(self, _TITLE, "Enter at least one SMILES string first.")
                return

        self._last = []
        self._streamed = False
        self.tree.clear()
        self.btn_add.setEnabled(False)
        self.btn_add_unique.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.query_bar.set_busy(True)
        self.status.setText(f"Starting vendor query… (N={len(smiles_list)})")
        self.out.setPlainText("")
        self._worker = _VendorBatchWorker(smiles_list)
        self._worker.signals.progress.connect(self._on_progress)
        self._worker.signals.structure_done.connect(self._on_structure_done)
        self._worker.signals.finished.connect(self._on_finished)
        start_runnable_on_app_pool(self.parent_app, self._worker)

    def _cancel_query(self) -> None:
        worker = self._worker
        if worker is not None:
            worker.cancel()
        self.status.setText("Cancelling…")

    def _on_progress(self, done: int, total: int, smiles: str) -> None:
        self.status.setText(f"Querying vendors… {done}/{total}  ({smiles})")

    def _on_structure_done(self, batch: list, log_line: str) -> None:
        self._streamed = True
        if batch:
            self._last.extend(batch)
            item = _query_item(batch)
            self.tree.addTopLevelItem(item)
            item.setFirstColumnSpanned(True)
        if log_line:
            self.out.append(log_line)

    def _on_finished(self, results: list, logs: list) -> None:
        if not self._streamed:
            self._last = list(results or [])
            fill_vendor_tree(self.tree, self._last)
            self.out.setPlainText("\n".join(str(line) for line in (logs or [])))
        self._streamed = False
        if self.tree.topLevelItemCount() == 1:
            self.tree.topLevelItem(0).setExpanded(True)
        self.btn_add.setEnabled(bool(self._last))
        self.btn_add_unique.setEnabled(bool(self._last))
        self.btn_cancel.setEnabled(False)
        self.query_bar.set_busy(False)
        self.status.setText(
            f"Done. Vendor products: {len(self._last)}. Structures with no vendor were omitted."
        )
        self._worker = None

    def _open_product_url(self, item: QTreeWidgetItem, column: int) -> None:
        if item is None or item.parent() is None or column != 2:
            return
        url = (item.text(2) or "").strip()
        if url.startswith(("http://", "https://")):
            QDesktopServices.openUrl(QUrl(url))

    def _add_unique_to_table(self) -> None:
        self._add_to_table(unique_only=True)

    def _add_to_table(self, *, unique_only: bool = False) -> None:
        app = self.parent_app
        if app is None or not self._last:
            return
        existing = _existing_vendor_keys(app) if unique_only else set()
        seen: set[tuple[str, str, str]] = set()
        batch: list[tuple[str, dict[str, str]]] = []
        skipped = 0
        for result in self._last:
            smiles = (result.smiles or "").strip()
            if unique_only:
                key = _product_key(app, smiles, result.vendor, result.product_id)
                if key is None or key in existing or key in seen:
                    skipped += 1
                    continue
                seen.add(key)
            batch.append((smiles, result.fields))
        added = 0
        if batch:
            try:
                added = int(app.add_rows_from_external_records_batch(batch))
            except (RuntimeError, TypeError, ValueError, OSError):
                skipped += len(batch)
                added = 0
        _set_add_status(app, added=added, skipped=skipped, unique_only=unique_only)


def _product_key(app, smiles: str, vendor: str, product_id: str) -> tuple[str, str, str] | None:
    raw = (smiles or "").strip()
    if not raw:
        return None
    key_fn = getattr(app, "canonical_structure_key_from_smiles", None)
    structure = key_fn(raw) if callable(key_fn) else None
    return (structure or raw, vendor.strip(), product_id.strip())


def _existing_vendor_keys(app) -> set[tuple[str, str, str]]:
    headers = list(getattr(app, "headers", []) or [])
    model = getattr(app, "_table_model", None)
    header_fn = getattr(app, "_canonical_smiles_header_for_updates", None)
    if model is None or not callable(header_fn):
        return set()
    smiles_header = header_fn()
    if (
        not smiles_header
        or smiles_header not in headers
        or COLUMN_VENDOR not in headers
        or COLUMN_PRODUCT_ID not in headers
    ):
        return set()
    smiles_col = headers.index(smiles_header)
    vendor_col = headers.index(COLUMN_VENDOR)
    product_col = headers.index(COLUMN_PRODUCT_ID)
    keys: set[tuple[str, str, str]] = set()
    for row in range(model.rowCount()):
        key = _product_key(
            app,
            model.cell_text(row, smiles_col),
            model.cell_text(row, vendor_col) or "",
            model.cell_text(row, product_col) or "",
        )
        if key is not None:
            keys.add(key)
    return keys


def _set_add_status(app, *, added: int, skipped: int, unique_only: bool) -> None:
    label = getattr(app, "status_label", None)
    if label is None:
        return
    if unique_only:
        label.setText(
            f"Vendors: added {added} unique product row(s); skipped {skipped} (duplicates or errors)."
        )
    elif added:
        label.setText(f"Vendors: added {added} row(s) to the table.")
    else:
        label.setText("Vendors: no rows were added.")
