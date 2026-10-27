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

"""REINVENT results browser: structure preview, property table, then add to the table."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

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
from ...table.structure_image import molecule_pixmap
from ..dockable_plot import (
    add_centered_browser_nav,
    discard_host_dialog_after_dock,
    make_add_to_main_button,
    make_send_window_button,
    request_close_plot_widget,
    style_browser_nav_buttons,
    style_plot_footer_text_button,
    sync_footer_on_parent_change,
)
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton
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
_SINGLETON = "_reinvent_browser_dialog"

Record = tuple[str, dict[str, str]]


def add_reinvent_records_to_table(
    app: Any,
    records: Sequence[Record],
    *,
    unique_only: bool,
) -> tuple[int, int]:
    """Append REINVENT rows to the compound table. Returns (added, skipped)."""
    if app is None or not hasattr(app, "add_rows_from_external_records_batch"):
        return 0, 0
    existing: set[str] = set()
    key_of = None
    if unique_only and hasattr(app, "existing_canonical_structure_keys"):
        existing = set(app.existing_canonical_structure_keys() or ())
        key_of = getattr(app, "canonical_structure_key_from_smiles", None)
    seen: set[str] = set()
    batch: list[Record] = []
    skipped = 0
    for smiles, fields in records:
        text = (smiles or "").strip()
        if not text:
            skipped += 1
            continue
        if unique_only and callable(key_of):
            key = key_of(text)
            if key is None or key in existing or key in seen:
                skipped += 1
                continue
            seen.add(key)
        batch.append((text, dict(fields)))
    added = 0
    if batch:
        added = int(app.add_rows_from_external_records_batch(batch, render_structures=True) or 0)
    return added, skipped


def open_reinvent_browser(parent_app: Any, records: Sequence[Record], *, title: str) -> None:
    """Show *records* in the REINVENT browser, reusing a docked or floating one."""
    rows = [(smiles, dict(fields)) for smiles, fields in records if (smiles or "").strip()]
    if not rows:
        return
    app = parent_app
    reveal = getattr(app, "reveal_first_selected_row", None) if app is not None else None
    if callable(reveal):
        reveal(focus=False)
    if app is None:
        dialog = ReinventBrowserDialog(None)
        dialog.set_records(rows, title=title)
        dialog.show()
        return
    iter_docked = getattr(app, "iter_docked_plot_widgets", None)
    if callable(iter_docked):
        for widget in iter_docked():
            if isinstance(widget, ReinventBrowserWidget):
                widget.set_records(rows, title=title)
                show_docked = getattr(app, "show_docked_plot_panel", None)
                if callable(show_docked):
                    show_docked()
                widget.raise_()
                return

    def _factory() -> ReinventBrowserDialog:
        dialog = ReinventBrowserDialog(app)
        dialog.set_records(rows, title=title)
        return dialog

    def _on_reused(dialog: QWidget) -> None:
        setter = getattr(dialog, "set_records", None)
        if callable(setter):
            setter(rows, title=title)

    reuse_or_show_modeless_singleton(
        app,
        _SINGLETON,
        _factory,
        on_reused_visible=_on_reused,
    )


def _pixmap_from_smiles(smiles: str, width: int, height: int) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    try:
        pixmap = molecule_pixmap(mol, int(width), int(height))
    except (RuntimeError, TypeError, ValueError):
        return None
    return None if pixmap.isNull() else pixmap


def _field_headers(records: Sequence[Record]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for _smiles, fields in records:
        for key in fields:
            if key in seen or key.lower() == "smiles":
                continue
            seen.add(key)
            ordered.append(key)
    return ordered


class ReinventBrowserWidget(QWidget):
    """Browse REINVENT molecules with a 2D canvas and a property table."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = "REINVENT Browser"
        self._records: list[Record] = []
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
        preview_layout = QVBoxLayout(self._preview_host)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(0)
        self._struct_label = QLabel(self._preview_host)
        self._struct_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        style_browser_structure_label(self._struct_label)
        preview_layout.addWidget(self._struct_label, 1)
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
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_ID, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_SMILES, QHeaderView.Stretch)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        root.addWidget(self._table)

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_buttons = QHBoxLayout(self._nav_bar)
        row_buttons.setContentsMargins(0, 0, 0, 0)
        row_buttons.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First molecule (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous molecule (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next molecule (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last molecule (End)")
        style_browser_nav_buttons(self._btn_first, self._btn_back, self._btn_fwd, self._btn_last)
        add_centered_browser_nav(
            row_buttons,
            [self._btn_first, self._btn_back, self._btn_fwd, self._btn_last],
        )
        root.addWidget(self._nav_bar)

        self._footer_bar = QWidget(self)
        self._footer_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        footer = QHBoxLayout(self._footer_bar)
        footer.setContentsMargins(0, 0, 0, 0)
        footer.setSpacing(4)
        self._add_to_main_btn = make_add_to_main_button(
            self,
            tooltip="Dock this browser beside the compound table.",
        )
        self._add_to_main_btn.clicked.connect(self._add_to_main_window)
        footer.addWidget(self._add_to_main_btn)
        self._send_window_btn = make_send_window_button(
            self,
            tooltip="Open this docked browser in a separate floating window.",
        )
        self._send_window_btn.clicked.connect(self._send_to_new_window)
        footer.addWidget(self._send_window_btn)
        self._close_btn = QPushButton("Close")
        self._close_btn.setToolTip("Close this browser.")
        self._close_btn.clicked.connect(self._close_docked_browser)
        style_plot_footer_text_button(self._close_btn)
        footer.addWidget(self._close_btn)
        self._btn_add = QPushButton("Add to table")
        self._btn_add.setToolTip("Add these molecules to the compound table.")
        self._btn_add.setEnabled(False)
        self._btn_add.clicked.connect(self._add_to_table)
        style_plot_footer_text_button(self._btn_add)
        footer.addWidget(self._btn_add)
        footer.addStretch()
        self._cb_unique = QCheckBox("Skip structures already in the table")
        self._cb_unique.setChecked(True)
        self._cb_unique.setToolTip(
            "When adding to the table, skip SMILES that match an existing structure."
        )
        footer.addWidget(self._cb_unique)
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
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(lambda d=delta: self._step(d))

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

    def create_floating_dialog(self, parent_app) -> ReinventBrowserDialog:
        self.show()
        return ReinventBrowserDialog(parent_app, panel=self)

    def set_records(self, records: Sequence[Record], *, title: str) -> None:
        self._window_title = f"{title} Browser"
        self._records = [(smiles, dict(fields)) for smiles, fields in records if smiles.strip()]
        self._idx = 0
        self._preview_cache.clear()
        host = self.window()
        if isinstance(host, ReinventBrowserDialog):
            host.setWindowTitle(self._window_title)
        self._fill_table()
        self._update_ui()

    def current_record(self) -> Record | None:
        if not self._records or not (0 <= self._idx < len(self._records)):
            return None
        return self._records[self._idx]

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dialog = self.window()
        if not dock(self):
            return
        if isinstance(dialog, ReinventBrowserDialog):
            discard_host_dialog_after_dock(dialog, self.parent_app, _SINGLETON)

    def _send_to_new_window(self) -> None:
        if self.parent_app is None:
            return
        undock = getattr(self.parent_app, "undock_plot_to_window", None)
        if callable(undock):
            undock(self)

    def _close_docked_browser(self) -> None:
        request_close_plot_widget(self, title="Close Browser", message="Close this browser?")

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
        floating = isinstance(self.window(), ReinventBrowserDialog)
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
        self._idx = max(0, len(self._records) - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        if not self._records:
            return
        self._idx = (self._idx + int(delta)) % len(self._records)
        self._update_ui()

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        ratio = max(1.0, float(self.devicePixelRatioF()))
        width = int(self._struct_label.width())
        height = int(self._struct_label.height())
        if width < 32 or height < 32:
            width = BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
            height = BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
        return max(1, int(width * ratio)), max(1, int(height * ratio)), ratio

    def _fit_preview_pixmap(self, pixmap: QPixmap, ratio: float) -> QPixmap:
        width = int(self._struct_label.width())
        height = int(self._struct_label.height())
        if width < 32 or height < 32:
            pixmap.setDevicePixelRatio(ratio)
            return pixmap
        canvas_w = max(1, int(width * ratio))
        canvas_h = max(1, int(height * ratio))
        canvas = QPixmap(canvas_w, canvas_h)
        canvas.fill(QColor(255, 255, 255))
        fitted = pixmap
        if fitted.width() != canvas_w or fitted.height() != canvas_h:
            fitted = pixmap.scaled(canvas_w, canvas_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        painter = QPainter(canvas)
        painter.drawPixmap(
            (canvas_w - fitted.width()) // 2,
            (canvas_h - fitted.height()) // 2,
            fitted,
        )
        painter.end()
        canvas.setDevicePixelRatio(ratio)
        return canvas

    def _refresh_preview(self) -> None:
        record = self.current_record()
        if record is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("No REINVENT molecules.")
            return
        smiles = record[0].strip()
        if not smiles:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("Could not draw structure.")
            return
        width, height, ratio = self._preview_pixel_size()
        cache_key = (smiles, width, height)
        pixmap = self._preview_cache.get(cache_key)
        if pixmap is None or pixmap.isNull():
            pixmap = _pixmap_from_smiles(smiles, width, height)
            if pixmap is not None and not pixmap.isNull():
                self._preview_cache[cache_key] = pixmap
        if pixmap is None or pixmap.isNull():
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("Could not draw structure.")
            return
        self._struct_label.setPixmap(self._fit_preview_pixmap(pixmap, ratio))
        self._struct_label.setText("")

    def _fill_table(self) -> None:
        self._filling_table = True
        try:
            extras = _field_headers(self._records)
            self._extra_headers = extras
            headers = ["ID", "SMILES", *extras]
            self._table.clear()
            self._table.setColumnCount(len(headers))
            self._table.setHorizontalHeaderLabels(headers)
            self._table.setRowCount(len(self._records))
            header = self._table.horizontalHeader()
            header.setSectionResizeMode(_COL_ID, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(_COL_SMILES, QHeaderView.Stretch)
            for col in range(2, len(headers)):
                header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
            for row, (smiles, fields) in enumerate(self._records):
                self._table.setItem(row, _COL_ID, QTableWidgetItem(str(row + 1)))
                self._table.setItem(row, _COL_SMILES, QTableWidgetItem(smiles))
                for col, key in enumerate(extras, start=2):
                    self._table.setItem(row, col, QTableWidgetItem(str(fields.get(key, ""))))
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
        record = self.current_record()
        count = len(self._records)
        if record is None or count <= 0:
            self._meta.setText("No REINVENT molecules.")
            return
        self._meta.setText(f"{self._idx + 1} of {count}")

    def _update_ui(self) -> None:
        has_rows = bool(self._records)
        self._btn_first.setEnabled(has_rows)
        self._btn_back.setEnabled(has_rows)
        self._btn_fwd.setEnabled(has_rows)
        self._btn_last.setEnabled(has_rows)
        self._btn_add.setEnabled(has_rows and self.parent_app is not None)
        self._select_table_row(self._idx)
        self._sync_caption()
        self._refresh_preview()

    def _add_to_table(self) -> None:
        app = self.parent_app
        if app is None or not self._records:
            return
        unique_only = bool(self._cb_unique.isChecked())
        try:
            added, skipped = add_reinvent_records_to_table(
                app, self._records, unique_only=unique_only
            )
        except (RuntimeError, TypeError, ValueError, OSError) as exc:
            QMessageBox.warning(self, self._window_title, str(exc) or "Failed to add rows.")
            return
        if hasattr(app, "status_label"):
            if unique_only:
                app.status_label.setText(
                    f"{self._window_title}: added {added} unique row(s); "
                    f"skipped {skipped} (duplicates or errors)."
                )
            elif added:
                app.status_label.setText(
                    f"{self._window_title}: added {added} row(s) to the table."
                )
            else:
                app.status_label.setText(f"{self._window_title}: no rows were added.")
        note = f" ({skipped} skipped)." if skipped else "."
        self._meta.setText(f"Added {added} row(s) to the table{note}")


class ReinventBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`ReinventBrowserWidget`."""

    default_title = "REINVENT Browser"
    panel_cls = ReinventBrowserWidget
    refresh_preview_on_show = True
    min_size = (640, 720)
    initial_size = (720, 860)

    def set_records(self, records: Sequence[Record], *, title: str) -> None:
        self.setWindowTitle(f"{title} Browser")
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        panel.set_records(records, title=title)
