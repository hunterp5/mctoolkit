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

"""Random Molecule results browser: SMILES table, 2D canvas, arrow-key browsing."""

from __future__ import annotations

from typing import Any, Sequence

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QColor, QKeySequence, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QShortcut,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ...sources.random_molecule_sources import RandomSourceMolecule
from ...table.structure_image import molecule_pixmap
from ..dockable_plot import (
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_send_window_button,
    request_close_plot_widget,
    add_centered_browser_nav,
    style_browser_nav_buttons,
    style_plot_footer_text_button,
    sync_footer_on_parent_change,
)
from ..strings import TOOL_RANDOM_MOLECULE
from .chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    install_browser_nav_shortcuts,
    style_browser_data_table,
    style_browser_preview_host,
    style_browser_structure_label,
)

_TABLE_MAX_HEIGHT = 220
_COL_ID = 0
_COL_SMILES = 1

_PREFERRED_EXTRA_COLS = ("Source", "ChEMBL_ID", "CID", "ZINC_ID")


def add_random_source_hits_to_table(
    app: Any,
    hits: Sequence[RandomSourceMolecule],
    *,
    unique_only: bool,
) -> tuple[int, int]:
    """Append random-molecule hits to the compound table. Returns (added, skipped)."""
    if app is None:
        return 0, 0
    existing = app.existing_canonical_structure_keys() if unique_only else set()
    seen_batch: set[str] = set()
    batch: list[tuple[str, dict[str, str]]] = []
    skipped = 0
    for hit in hits:
        smi = (hit.smiles or "").strip()
        if not smi:
            skipped += 1
            continue
        if unique_only:
            key = app.canonical_structure_key_from_smiles(smi)
            if key is None:
                skipped += 1
                continue
            if key in existing or key in seen_batch:
                skipped += 1
                continue
            seen_batch.add(key)
        batch.append((smi, dict(hit.fields)))
    added = 0
    if batch:
        added = int(app.add_rows_from_external_records_batch(batch) or 0)
    return added, skipped


def _pixmap_from_smiles(smiles: str, width: int, height: int) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    try:
        pm = molecule_pixmap(mol, int(width), int(height))
    except Exception:
        return None
    return None if pm.isNull() else pm


def _extra_field_headers(hits: Sequence[RandomSourceMolecule]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for name in _PREFERRED_EXTRA_COLS:
        if any(name in (h.fields or {}) for h in hits) and name not in seen:
            seen.add(name)
            ordered.append(name)
    for hit in hits:
        for key in hit.fields or {}:
            if key in seen or key in {"SMILES", "smiles"}:
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


class RandomMoleculeBrowserWidget(QWidget):
    """Browse fetched random molecules with a 2D canvas and SMILES table."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = f"{TOOL_RANDOM_MOLECULE} Browser"
        self._hits: list[RandomSourceMolecule] = []
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._filling_table = False
        self._extra_headers: list[str] = []

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._preview_host = QWidget(self)
        self._preview_host.setMinimumSize(
            BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
            BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
        )
        self._preview_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        style_browser_preview_host(self._preview_host)
        preview_ly = QVBoxLayout(self._preview_host)
        preview_ly.setContentsMargins(0, 0, 0, 0)
        preview_ly.setSpacing(0)
        self._struct_label = QLabel(self._preview_host)
        self._struct_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        style_browser_structure_label(self._struct_label)
        preview_ly.addWidget(self._struct_label, 1)
        root.addWidget(self._preview_host, 1)

        self._table = QTableWidget(0, 2)
        self._table.setHorizontalHeaderLabels(["ID", "SMILES"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setMaximumHeight(_TABLE_MAX_HEIGHT)
        self._table.setFixedHeight(_TABLE_MAX_HEIGHT)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self._table.setWordWrap(False)
        style_browser_data_table(self._table)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_ID, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_SMILES, QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        root.addWidget(self._table)

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_btns = QHBoxLayout(self._nav_bar)
        row_btns.setContentsMargins(0, 0, 0, 0)
        row_btns.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First molecule (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous molecule (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next molecule (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last molecule (End)")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
        )
        add_centered_browser_nav(
            row_btns,
            [self._btn_first, self._btn_back, self._btn_fwd, self._btn_last],
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        foot = QHBoxLayout(self._footer_bar)
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(4)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this browser beside the compound table.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        foot.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked browser in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        foot.addWidget(self._send_window_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this browser.")
        self._close_btn.clicked.connect(self._close_docked_browser)
        style_plot_footer_text_button(self._close_btn)
        foot.addWidget(self._close_btn)
        self._btn_add = QPushButton("Add to table")
        self._btn_add.setToolTip("Add these random molecules to the compound table.")
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._add_to_table)
        style_plot_footer_text_button(self._btn_add)
        foot.addWidget(self._btn_add)
        foot.addStretch()
        self._cb_unique = QCheckBox("Skip structures already in the table")
        self._cb_unique.setChecked(True)
        self._cb_unique.setToolTip(
            "When adding to the table, skip SMILES that match an existing structure."
        )
        foot.addWidget(self._cb_unique)
        root.addWidget(self._footer_bar)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)

        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )
        for delta, key in ((-1, Qt.Key_Up), (1, Qt.Key_Down)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda d=delta: self._step(d))

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_preview)

        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._update_ui()

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self.parent_app = parent_app
        self._app = parent_app

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH)

    def create_floating_dialog(self, parent_app) -> "RandomMoleculeBrowserDialog":
        self.show()
        return RandomMoleculeBrowserDialog(parent_app, panel=self)

    def set_hits(
        self,
        hits: Sequence[RandomSourceMolecule],
        *,
        unique_only: bool | None = None,
    ) -> None:
        self._hits = [h for h in (hits or ()) if (h.smiles or "").strip()]
        self._idx = 0
        self._preview_cache.clear()
        if unique_only is not None:
            self._cb_unique.setChecked(bool(unique_only))
        self._fill_table()
        self._update_ui()

    def current_hit(self) -> RandomSourceMolecule | None:
        if not self._hits or not (0 <= self._idx < len(self._hits)):
            return None
        return self._hits[self._idx]

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, RandomMoleculeBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_random_molecule_browser_dialog")

    def _send_to_new_window(self) -> None:
        if self.parent_app is not None:
            undock = getattr(self.parent_app, "undock_plot_to_window", None)
            if callable(undock):
                undock(self)

    def _close_docked_browser(self) -> None:
        request_close_plot_widget(
            self,
            title="Close Browser",
            message="Close this browser?",
        )

    def _is_docked_in_main_window(self) -> bool:
        app = self.parent_app
        if app is None:
            return False
        check = getattr(app, "is_plot_docked", None)
        if callable(check):
            return bool(check(self))
        return False

    def _sync_footer_chrome(self) -> None:
        from ..dockable_plot import apply_plot_chrome_glyphs, sync_docked_footer_bar

        apply_plot_chrome_glyphs(self)
        floating = isinstance(self.window(), RandomMoleculeBrowserDialog)
        docked = self._is_docked_in_main_window()
        self._add_to_main_btn.setVisible(floating)
        self._send_window_btn.setVisible(docked)
        self._close_btn.setVisible(True)
        sync_docked_footer_bar(self, docked=docked)

    def event(self, event) -> bool:  # noqa: N802 — Qt API
        if event.type() == QEvent.ParentChange:
            sync_footer_on_parent_change(self)
        return super().event(event)

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.start()

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, len(self._hits) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._hits:
            return
        self._idx = (self._idx + int(delta)) % len(self._hits)
        self._update_ui()

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            lw = BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
            lh = BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
        return max(1, int(lw * dpr)), max(1, int(lh * dpr)), dpr

    def _fit_preview_pixmap(self, pm: QPixmap, dpr: float) -> QPixmap:
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            pm.setDevicePixelRatio(dpr)
            return pm
        canvas_w = max(1, int(lw * dpr))
        canvas_h = max(1, int(lh * dpr))
        canvas = QPixmap(canvas_w, canvas_h)
        canvas.fill(QColor(255, 255, 255))
        fitted = pm
        if fitted.width() != canvas_w or fitted.height() != canvas_h:
            fitted = pm.scaled(canvas_w, canvas_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        x = (canvas_w - fitted.width()) // 2
        y = (canvas_h - fitted.height()) // 2
        painter.drawPixmap(x, y, fitted)
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return canvas

    def _refresh_preview(self) -> None:
        hit = self.current_hit()
        if hit is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("No random molecules.")
            return
        smiles = (hit.smiles or "").strip()
        if not smiles:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("Could not draw structure.")
            return
        pw, ph, dpr = self._preview_pixel_size()
        cache_key = (smiles, pw, ph)
        pm = self._preview_cache.get(cache_key)
        if pm is None or pm.isNull():
            pm = _pixmap_from_smiles(smiles, pw, ph)
            if pm is not None and not pm.isNull():
                self._preview_cache[cache_key] = pm
        if pm is None or pm.isNull():
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("Could not draw structure.")
            return
        pm = self._fit_preview_pixmap(pm, dpr)
        self._struct_label.setPixmap(pm)
        self._struct_label.setText("")

    def _fill_table(self) -> None:
        self._filling_table = True
        try:
            extras = _extra_field_headers(self._hits)
            self._extra_headers = extras
            headers = ["ID", "SMILES", *extras]
            self._table.clear()
            self._table.setColumnCount(len(headers))
            self._table.setHorizontalHeaderLabels(headers)
            self._table.setRowCount(len(self._hits))
            hdr = self._table.horizontalHeader()
            hdr.setSectionResizeMode(_COL_ID, QHeaderView.ResizeToContents)
            hdr.setSectionResizeMode(_COL_SMILES, QHeaderView.Stretch)
            for col in range(2, len(headers)):
                hdr.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            for row, hit in enumerate(self._hits):
                self._table.setItem(row, _COL_ID, QTableWidgetItem(str(hit.molecule_id)))
                self._table.setItem(row, _COL_SMILES, QTableWidgetItem(str(hit.smiles or "")))
                for col, key in enumerate(extras, start=2):
                    self._table.setItem(
                        row, col, QTableWidgetItem(str((hit.fields or {}).get(key, "")))
                    )
        finally:
            self._filling_table = False

    def _select_table_row(self, row: int) -> None:
        if not (0 <= row < self._table.rowCount()):
            return
        self._filling_table = True
        try:
            self._table.selectRow(row)
            item = self._table.item(row, _COL_SMILES)
            if item is not None:
                self._table.scrollToItem(item)
        finally:
            self._filling_table = False

    def _on_table_selection_changed(self) -> None:
        if self._filling_table:
            return
        row = self._table.currentRow()
        if row < 0 or row == self._idx:
            return
        self._idx = row
        self._sync_caption()
        self._refresh_preview()

    def _sync_caption(self) -> None:
        hit = self.current_hit()
        n = len(self._hits)
        if hit is None or n <= 0:
            self._meta.setText("No random molecules.")
            return
        self._meta.setText(f"{self._idx + 1} of {n}  —  {hit.molecule_id}")

    def _update_ui(self) -> None:
        has = bool(self._hits)
        self._btn_first.setEnabled(has)
        self._btn_back.setEnabled(has)
        self._btn_fwd.setEnabled(has)
        self._btn_last.setEnabled(has)
        self._btn_add.setEnabled(has and self.parent_app is not None)
        self._select_table_row(self._idx)
        self._sync_caption()
        self._refresh_preview()

    def _add_to_table(self) -> None:
        app = self.parent_app
        if app is None or not self._hits:
            return
        unique_only = bool(self._cb_unique.isChecked())
        try:
            added, skipped = add_random_source_hits_to_table(
                app, self._hits, unique_only=unique_only
            )
        except Exception as e:
            QMessageBox.warning(self, TOOL_RANDOM_MOLECULE, str(e) or "Failed to add rows.")
            return
        if hasattr(app, "status_label"):
            if unique_only:
                app.status_label.setText(
                    f"{TOOL_RANDOM_MOLECULE}: added {added} unique row(s); "
                    f"skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(
                    f"{TOOL_RANDOM_MOLECULE}: added {added} row(s) to the table."
                )
            else:
                app.status_label.setText(f"{TOOL_RANDOM_MOLECULE}: no rows were added.")
        self._meta.setText(
            f"Added {added} row(s) to the table" + (f" ({skipped} skipped)." if skipped else ".")
        )


class RandomMoleculeBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`RandomMoleculeBrowserWidget`."""

    default_title = f"{TOOL_RANDOM_MOLECULE} Browser"
    panel_cls = RandomMoleculeBrowserWidget
    refresh_preview_on_show = True
    min_size = (640, 720)
    initial_size = (720, 860)

    def set_hits(
        self,
        hits: Sequence[RandomSourceMolecule],
        *,
        unique_only: bool | None = None,
    ) -> None:
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        panel.set_hits(hits, unique_only=unique_only)
