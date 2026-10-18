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
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Modeless BioTransformer results browser: parent plus metabolites, like Data → Browser."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from PyQt5.QtCore import QEvent, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...predictions.biotransformer_metabolites import (
    BIOTRANSFORMER_CANCELLED,
    METABOLITE_COUNT_COLUMN,
    METABOLITE_REACTIONS_COLUMN,
    METABOLITE_SMILES_COLUMN,
    is_metabolite_column_header,
    parse_metabolite_smiles_cell,
)
from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ...chem.structure_2d_depiction import render_molecule_png
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
from ..strings import TOOL_PREDICT_METABOLITES
from ..widgets import NumericTableWidgetItem
from .chrome import (
    BrowserHostDialog,
    apply_browser_body_layout,
    install_browser_nav_shortcuts,
    style_browser_data_table,
    style_browser_preview_host,
    style_browser_structure_label,
)

_THUMB_W = 120
_THUMB_H = 100
_TABLE_MAX_HEIGHT = _THUMB_H * 3 + 56

_COL_ROLE = 0
_COL_STRUCT = 1
_COL_REACTION = 2
_COL_ENZYME = 3
_COL_STEP = 4
_SMILES_ROLE = Qt.UserRole
_KIND_ROLE = Qt.UserRole + 1

ROLE_PARENT = "Parent"
ROLE_METABOLITE = "Metabolite"


@dataclass(frozen=True)
class MetaboliteBrowseHit:
    smiles: str
    reaction: str = ""
    enzyme: str = ""
    biosystem: str = ""
    generation: int | None = None
    precursor_smiles: str = ""


@dataclass(frozen=True)
class MetaboliteBrowseRecord:
    """One parent molecule and its predicted metabolites."""

    oid: int | None
    smiles: str
    metabolites: tuple[MetaboliteBrowseHit, ...] = ()
    error: str | None = None
    columns: dict[str, str] = field(default_factory=dict)


def _coerce_hit(item: Any) -> MetaboliteBrowseHit | None:
    if isinstance(item, MetaboliteBrowseHit):
        return item
    if isinstance(item, dict):
        smi = str(item.get("smiles") or "").strip()
        if not smi:
            return None
        gen = item.get("generation")
        try:
            generation = int(gen) if gen is not None and str(gen).strip() != "" else None
        except (TypeError, ValueError):
            generation = None
        return MetaboliteBrowseHit(
            smiles=smi,
            reaction=str(item.get("reaction") or ""),
            enzyme=str(item.get("enzyme") or ""),
            biosystem=str(item.get("biosystem") or ""),
            generation=generation,
            precursor_smiles=str(item.get("precursor_smiles") or ""),
        )
    return None


def records_from_worker_rows(rows: Sequence) -> list[MetaboliteBrowseRecord]:
    """Convert Predict Metabolites worker tuples into browser records."""
    out: list[MetaboliteBrowseRecord] = []
    for row in rows or ():
        if not row:
            continue
        oid = row[0]
        cols = dict(row[1] or {})
        hits_raw = row[2] if len(row) > 2 else ()
        parent_smi = str(row[5] if len(row) > 5 else "") or ""
        hits = tuple(h for h in (_coerce_hit(x) for x in (hits_raw or ())) if h is not None)
        err = None
        if not hits:
            err = str(cols.get("Metabolite Reactions") or "").strip() or None
            if err in {"N/A", ""}:
                err = "No metabolites were returned."
        rec = MetaboliteBrowseRecord(
            oid=None if oid is None else int(oid),
            smiles=parent_smi,
            metabolites=hits,
            error=err if not hits else None,
            columns=cols,
        )
        if rec.error == BIOTRANSFORMER_CANCELLED and not rec.metabolites:
            continue
        out.append(rec)
    return out


def _first_matching_header(headers: Sequence[str], base: str) -> str | None:
    named = [h for h in headers if is_metabolite_column_header(h, base)]
    return named[0] if named else None


def records_from_table(app: Any) -> list[MetaboliteBrowseRecord]:
    """Rebuild browser records from Predict Metabolites parent-row columns."""
    model = getattr(app, "_table_model", None)
    headers = list(getattr(app, "headers", None) or [])
    if model is None or not headers:
        return []
    smiles_h = _first_matching_header(headers, METABOLITE_SMILES_COLUMN)
    count_h = _first_matching_header(headers, METABOLITE_COUNT_COLUMN)
    rxn_h = _first_matching_header(headers, METABOLITE_REACTIONS_COLUMN)
    if smiles_h is None and count_h is None:
        return []
    out: list[MetaboliteBrowseRecord] = []
    n = int(model.rowCount())
    for row in range(n):
        try:
            oid = int(model.row_oid(row))
        except (TypeError, ValueError):
            continue
        smiles_cell = (
            str(model.backing_value_for_row_header(row, smiles_h) or "") if smiles_h else ""
        )
        count_cell = str(model.backing_value_for_row_header(row, count_h) or "") if count_h else ""
        rxn_cell = str(model.backing_value_for_row_header(row, rxn_h) or "") if rxn_h else ""
        products = parse_metabolite_smiles_cell(smiles_cell)
        count_ok = count_cell.strip() not in {"", "N/A", "n/a"}
        if not products and not count_ok:
            continue
        parent_smi = str(model.backing_value_for_row_header(row, "SMILES") or "").strip()
        if not parent_smi:
            mols = getattr(app, "mols", None) or {}
            mol = mols.get(oid)
            if mol is not None:
                from ...chem.molecule_conversion import mol_to_canonical_smiles

                parent_smi = mol_to_canonical_smiles(mol) or ""
        hits = tuple(MetaboliteBrowseHit(smiles=smi) for smi in products)
        err = None
        if not hits:
            err = rxn_cell.strip() if rxn_cell.strip() not in {"", "N/A"} else None
            if not err:
                err = "No metabolites were returned."
        if err == BIOTRANSFORMER_CANCELLED and not hits:
            continue
        cols = {
            h: str(model.backing_value_for_row_header(row, h) or "")
            for h in (smiles_h, count_h, rxn_h)
            if h
        }
        out.append(
            MetaboliteBrowseRecord(
                oid=oid,
                smiles=parent_smi,
                metabolites=hits,
                error=err if not hits else None,
                columns=cols,
            )
        )
    return out


def _pixmap_from_smiles(smiles: str, width: int, height: int) -> QPixmap | None:
    mol = Chem.MolFromSmiles(smiles or "")
    if mol is None:
        return None
    try:
        png = render_molecule_png(mol, int(width), int(height))
    except Exception:
        return None
    pm = QPixmap.fromImage(QImage.fromData(png))
    return None if pm.isNull() else pm


class MetaboliteBrowserWidget(QWidget):
    """Step through parent molecules and inspect BioTransformer products."""

    dockable_in_workspace = True
    supports_floating_title = False

    def __init__(self, parent_app: Any = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.parent_app = parent_app
        self._app = parent_app
        self._window_title = f"{TOOL_PREDICT_METABOLITES} Browser"
        self._records: list[MetaboliteBrowseRecord] = []
        self._all_records: list[MetaboliteBrowseRecord] = []
        self._idx = 0
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._canvas_smiles = ""
        self._canvas_kind = ROLE_PARENT
        self._filling_table = False
        self._connected_selection_store = None

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
        self._struct_label.setMargin(0)
        self._struct_label.setIndent(0)
        style_browser_structure_label(self._struct_label)
        preview_ly.addWidget(self._struct_label, 1)
        root.addWidget(self._preview_host, 1)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(["Role", "Structure", "Reaction", "Enzyme", "Step"])
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.setMaximumHeight(_TABLE_MAX_HEIGHT)
        self._table.setFixedHeight(_TABLE_MAX_HEIGHT)
        self._table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._table.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        style_browser_data_table(self._table)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(_COL_ROLE, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_STRUCT, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_REACTION, QHeaderView.Stretch)
        hdr.setSectionResizeMode(_COL_ENZYME, QHeaderView.ResizeToContents)
        hdr.setSectionResizeMode(_COL_STEP, QHeaderView.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_table_selection_changed)
        root.addWidget(self._table)

        self._nav_bar = QWidget(self)
        self._nav_bar.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        row_btns = QHBoxLayout(self._nav_bar)
        row_btns.setContentsMargins(0, 0, 0, 0)
        row_btns.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First parent (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous parent (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next parent (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last parent (End)")
        self._btn_select = QPushButton()
        self._btn_select.setToolTip("Select this parent row in the compound table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_select,
        )
        add_centered_browser_nav(
            row_btns,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_select,
            ],
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
        foot.addStretch()
        self._cb_only_selected = QCheckBox("Browse Only Selected")
        self._cb_only_selected.setToolTip(
            "When checked, this browser walks only table rows that are currently selected."
        )
        self._cb_only_selected.toggled.connect(self._on_only_selected_toggled)
        foot.addWidget(self._cb_only_selected)
        root.addWidget(self._footer_bar)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_row)

        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_preview)
        self._selection_timer = QTimer(self)
        self._selection_timer.setSingleShot(True)
        self._selection_timer.setInterval(80)
        self._selection_timer.timeout.connect(self._refresh_selected_scope)

        self._sync_footer_chrome()
        self.setMinimumWidth(self.embedded_minimum_width())
        self._connect_table_selection()
        self._update_ui()

    def rebind_parent_app(self, parent_app: Any | None) -> None:
        self._disconnect_table_selection()
        self.parent_app = parent_app
        self._app = parent_app
        self._connect_table_selection()

    def embedded_minimum_width(self) -> int:
        return max(360, BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)

    def embedded_preferred_width(self) -> int:
        return max(self.embedded_minimum_width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH)

    def create_floating_dialog(self, parent_app) -> "MetaboliteBrowserDialog":
        self.show()
        return MetaboliteBrowserDialog(parent_app, panel=self)

    def set_records(self, records: list[MetaboliteBrowseRecord]) -> None:
        self._all_records = list(records or [])
        self._preview_cache.clear()
        has_oid = any(r.oid is not None for r in self._all_records)
        self._cb_only_selected.setEnabled(has_oid)
        self._apply_record_scope(preserve_oid=False)

    def jump_to_oid(self, oid: int | None) -> bool:
        """Show the record for ``oid``, turning off selected-only if needed."""
        if oid is None:
            return False
        want = int(oid)
        if not any(r.oid == want for r in self._all_records):
            return False
        if self._cb_only_selected.isChecked():
            self._cb_only_selected.blockSignals(True)
            self._cb_only_selected.setChecked(False)
            self._cb_only_selected.blockSignals(False)
        self._records = list(self._all_records)
        for i, rec in enumerate(self._records):
            if rec.oid == want:
                self._idx = i
                self._update_ui()
                return True
        return False

    def _add_to_main_window(self) -> None:
        if self.parent_app is None:
            return
        dock = getattr(self.parent_app, "dock_plot_widget", None)
        if not callable(dock):
            return
        dlg = self.window()
        if not dock(self):
            return
        if isinstance(dlg, MetaboliteBrowserDialog):
            discard_host_dialog_after_dock(dlg, self.parent_app, "_metabolite_browser_dialog")

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
        floating = isinstance(self.window(), MetaboliteBrowserDialog)
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

    def _current(self) -> MetaboliteBrowseRecord | None:
        if not self._records or not (0 <= self._idx < len(self._records)):
            return None
        return self._records[self._idx]

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

    def _on_only_selected_toggled(self, _checked: bool = False) -> None:
        self._apply_record_scope(preserve_oid=True)

    def _selected_oids(self) -> frozenset[int]:
        store = self._selection_store_or_none()
        return store.oids if store is not None else frozenset()

    def _selection_store_or_none(self):
        return getattr(self._app, "selection_store", None) if self._app is not None else None

    def _apply_record_scope(self, *, preserve_oid: bool) -> None:
        cur_oid = None
        if preserve_oid:
            rec = self._current()
            if rec is not None and rec.oid is not None:
                cur_oid = int(rec.oid)
        recs = list(self._all_records)
        if self._cb_only_selected.isChecked():
            selected = self._selected_oids()
            recs = [r for r in recs if r.oid is not None and int(r.oid) in selected]
        self._records = recs
        self._idx = 0
        if cur_oid is not None:
            for i, rec in enumerate(self._records):
                if rec.oid == cur_oid:
                    self._idx = i
                    break
        self._update_ui()

    def _connect_table_selection(self) -> None:
        self._disconnect_table_selection()
        store = self._selection_store_or_none()
        if store is None:
            return
        store.changed.connect(self._on_host_table_selection_changed)
        self._connected_selection_store = store

    def _disconnect_table_selection(self) -> None:
        store = getattr(self, "_connected_selection_store", None)
        if store is None:
            return
        try:
            store.changed.disconnect(self._on_host_table_selection_changed)
        except (TypeError, RuntimeError):
            pass
        self._connected_selection_store = None

    def _on_host_table_selection_changed(self, _origin: object = None) -> None:
        if not self._cb_only_selected.isChecked():
            return
        timer = getattr(self, "_selection_timer", None)
        if timer is not None:
            timer.start()

    def _refresh_selected_scope(self) -> None:
        if self._cb_only_selected.isChecked():
            self._apply_record_scope(preserve_oid=True)

    def _select_current_row(self) -> None:
        rec = self._current()
        app = self._app
        if rec is None or rec.oid is None or app is None:
            return
        select = getattr(app, "select_table_oids", None)
        if callable(select):
            select([int(rec.oid)], extra_status=TOOL_PREDICT_METABOLITES)

    def _preview_pixel_size(self) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = int(self._struct_label.width())
        lh = int(self._struct_label.height())
        if lw < 32 or lh < 32:
            lw = BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH
            lh = BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT
        return max(1, int(lw * dpr)), max(1, int(lh * dpr)), dpr

    def _fit_preview_pixmap(self, pm: QPixmap, dpr: float) -> QPixmap:
        """Place the depiction on a white canvas that matches the preview label."""
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
        rec = self._current()
        smiles = self._canvas_smiles
        if rec is None:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText("No metabolite results.")
            return
        if not smiles:
            self._struct_label.clear()
            self._struct_label.setPixmap(QPixmap())
            self._struct_label.setText(rec.error or "Could not draw structure.")
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
            self._struct_label.setText(rec.error or "Could not draw structure.")
            return
        pm = self._fit_preview_pixmap(pm, dpr)
        self._struct_label.setPixmap(pm)
        self._struct_label.setText("")

    def _on_table_selection_changed(self) -> None:
        if self._filling_table:
            return
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, _COL_ROLE)
        if item is None:
            return
        smiles = str(item.data(_SMILES_ROLE) or "")
        kind = str(item.data(_KIND_ROLE) or ROLE_METABOLITE)
        if smiles == self._canvas_smiles and kind == self._canvas_kind:
            return
        self._canvas_smiles = smiles
        self._canvas_kind = kind
        self._refresh_preview()

    def _set_table_row(
        self,
        row: int,
        *,
        kind: str,
        smiles: str,
        reaction: str = "",
        enzyme: str = "",
        generation: int | None = None,
    ) -> None:
        role_item = QTableWidgetItem(kind)
        role_item.setData(_SMILES_ROLE, smiles)
        role_item.setData(_KIND_ROLE, kind)
        if kind == ROLE_PARENT:
            font = QFont(role_item.font())
            font.setBold(True)
            role_item.setFont(font)
        self._table.setItem(row, _COL_ROLE, role_item)
        struct_item = QTableWidgetItem()
        thumb = _pixmap_from_smiles(smiles, _THUMB_W, _THUMB_H)
        if thumb is not None:
            struct_item.setData(Qt.DecorationRole, thumb)
        self._table.setItem(row, _COL_STRUCT, struct_item)
        self._table.setItem(row, _COL_REACTION, QTableWidgetItem(reaction))
        self._table.setItem(row, _COL_ENZYME, QTableWidgetItem(enzyme))
        step = "" if generation is None else str(generation)
        step_item = NumericTableWidgetItem(step)
        if generation is not None:
            step_item.setData(Qt.EditRole, int(generation))
        self._table.setItem(row, _COL_STEP, step_item)
        self._table.setRowHeight(row, _THUMB_H + 8)

    def _fill_table(self, rec: MetaboliteBrowseRecord | None) -> None:
        self._filling_table = True
        self._table.blockSignals(True)
        try:
            if rec is None:
                self._table.setRowCount(0)
                self._canvas_smiles = ""
                self._canvas_kind = ROLE_PARENT
                return
            hits = rec.metabolites
            self._table.setRowCount(1 + len(hits))
            self._set_table_row(0, kind=ROLE_PARENT, smiles=rec.smiles)
            for i, hit in enumerate(hits):
                self._set_table_row(
                    i + 1,
                    kind=ROLE_METABOLITE,
                    smiles=hit.smiles,
                    reaction=hit.reaction,
                    enzyme=hit.enzyme,
                    generation=hit.generation,
                )
            self._canvas_smiles = rec.smiles
            self._canvas_kind = ROLE_PARENT
            self._table.selectRow(0)
        finally:
            self._table.blockSignals(False)
            self._filling_table = False

    def _update_ui(self) -> None:
        rec = self._current()
        n = len(self._records)
        row_txt = ""
        if rec is not None and rec.oid is not None and self._app is not None:
            try:
                logical = int(self._app._table_model.logical_row_for_oid(int(rec.oid)))
                if logical >= 0:
                    row_txt = f"  ·  Row {logical + 1}"
            except Exception:
                row_txt = f"  (row {rec.oid})"
        elif rec is not None and rec.oid is not None:
            row_txt = f"  (row {rec.oid})"
        self._meta.setText(f"{TOOL_PREDICT_METABOLITES}: {self._idx + 1} / {max(n, 1)}{row_txt}")
        enabled = n > 1
        self._btn_first.setEnabled(enabled)
        self._btn_back.setEnabled(enabled)
        self._btn_fwd.setEnabled(enabled)
        self._btn_last.setEnabled(enabled)
        self._btn_select.setEnabled(rec is not None and rec.oid is not None)
        self._fill_table(rec)
        self._refresh_preview()


class MetaboliteBrowserDialog(BrowserHostDialog):
    """Floating window hosting a :class:`MetaboliteBrowserWidget`."""

    default_title = f"{TOOL_PREDICT_METABOLITES} Browser"
    panel_cls = MetaboliteBrowserWidget
    refresh_preview_on_show = True
    min_size = (640, 780)
    initial_size = (720, 900)

    def set_records(self, records: list[MetaboliteBrowseRecord]) -> None:
        panel = getattr(self, "_panel", None)
        if panel is None:
            return
        panel.set_records(records)

    def jump_to_oid(self, oid: int | None) -> bool:
        panel = getattr(self, "_panel", None)
        if panel is None:
            return False
        return bool(panel.jump_to_oid(oid))
