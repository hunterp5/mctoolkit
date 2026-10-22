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

"""Modeless dialog: rank MMP transforms by support and activity effect."""

from __future__ import annotations

import logging
from typing import Any

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)
from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from ..analysis.mmp_analysis import (
    MmpPair,
    TransformSummary,
    aggregate_transforms,
    pairs_for_summary,
    pairs_involving_oid,
)
from .qt_widget_utils import make_window_resizable
from .widgets import NumericTableWidgetItem

logger = logging.getLogger(__name__)

_COL_CORE = 0
_COL_TRANSFORM = 1
_COL_N = 2
_COL_MEDIAN = 3
_COL_MEAN = 4
_COL_WIN = 5
_COL_IMPROVE = 6
_COL_WORSEN = 7
_COL_MIN = 8
_COL_MAX = 9

_HEADERS = (
    "Core",
    "Transform",
    "n",
    "Median Δ",
    "Mean Δ",
    "Win %",
    "Improve",
    "Worsen",
    "Min Δ",
    "Max Δ",
)

_ROW_HEIGHT = 104
_CORE_COL_WIDTH = 140
_TRANSFORM_COL_WIDTH = 280
_FRAG_W = 120
_FRAG_H = 92
_ARROW_W = 32
_CORE_W = 128


class _LedgerStructureDelegate(QStyledItemDelegate):
    """Paint Core/Transform 2D images so they fill the cell like the main table."""

    def paint(self, painter, option, index):  # noqa: N802 — Qt API name
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        pix = index.data(Qt.DecorationRole)
        if not isinstance(pix, QPixmap) or pix.isNull():
            super().paint(painter, option, index)
            return
        painter.save()
        painter.fillRect(opt.rect, QColor(255, 255, 255))
        margin = 2
        avail_w = max(1, opt.rect.width() - 2 * margin)
        avail_h = max(1, opt.rect.height() - 2 * margin)
        fitted = pix.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = opt.rect.x() + margin + (avail_w - fitted.width()) // 2
        y = opt.rect.y() + margin + (avail_h - fitted.height()) // 2
        painter.drawPixmap(x, y, fitted)
        if opt.state & QStyle.State_Selected:
            painter.fillRect(opt.rect, QColor(0, 120, 215, 48))
        painter.restore()


def _try_configure_drawer(drawer, width: int) -> None:
    try:
        from ..chem.structure_2d_depiction import configure_mol_drawer as cfg

        cfg(drawer, width)
    except Exception:
        pass


def _fmt_delta(value: float) -> str:
    text = f"{value:.4g}"
    if text.startswith("-") or text == "0":
        return text
    return f"+{text}"


class MmpTransformLedgerDialog(QDialog):
    """Browse MMP transforms aggregated from a pair list; drill into the pair browser."""

    def __init__(
        self,
        parent: Any,
        pairs: list[MmpPair],
        *,
        activity_column: str,
    ):
        super().__init__(parent)
        self._app = parent
        self._pairs: list[MmpPair] = []
        self._pairs_for_summaries: list[MmpPair] = []
        self._summaries: list[TransformSummary] = []
        self._activity_column = activity_column
        self._reference_oid: int | None = None
        self._preview_cache: dict[tuple, QPixmap] = {}
        self._transform_icon_cache: dict[str, QPixmap] = {}
        self._core_icon_cache: dict[str, QPixmap] = {}

        self.setWindowTitle("MMP Transform Ledger")
        self.resize(980, 640)
        self.setMinimumSize(720, 480)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Filter:"))
        self._filter_edit = QLineEdit()
        self._filter_edit.setPlaceholderText("Substring match on core or transform SMILES…")
        self._filter_edit.setClearButtonEnabled(True)
        filter_row.addWidget(self._filter_edit, 1)
        root.addLayout(filter_row)

        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(list(_HEADERS))
        self._table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SingleSelection)
        self._table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self._table.setAlternatingRowColors(True)
        self._table.setIconSize(QSize(_TRANSFORM_COL_WIDTH - 4, _ROW_HEIGHT - 4))
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(_ROW_HEIGHT)
        self._table.setSortingEnabled(True)
        # Prevent long content / header modes from driving an expanding min-size loop on Windows.
        self._table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
        self._table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(False)
        hdr.setSectionResizeMode(_COL_CORE, QHeaderView.Fixed)
        hdr.setSectionResizeMode(_COL_TRANSFORM, QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_CORE, _CORE_COL_WIDTH)
        self._table.setColumnWidth(_COL_TRANSFORM, _TRANSFORM_COL_WIDTH)
        for col in range(2, len(_HEADERS)):
            hdr.setSectionResizeMode(col, QHeaderView.Interactive)
            self._table.setColumnWidth(col, 78)
        struct_delegate = _LedgerStructureDelegate(self._table)
        self._table.setItemDelegateForColumn(_COL_CORE, struct_delegate)
        self._table.setItemDelegateForColumn(_COL_TRANSFORM, struct_delegate)
        root.addWidget(self._table, 1)

        actions = QHBoxLayout()
        self._btn_browse = QPushButton("Browse Pairs")
        self._btn_browse.setToolTip("Open the pair browser for the selected transform")
        self._btn_cliffs = QPushButton("Activity Cliffs")
        self._btn_cliffs.setToolTip(
            "Open the activity-cliff scatter for the pairs currently shown in this ledger "
            "(respects reference filter)."
        )
        self._btn_network = QPushButton("Pair Network")
        self._btn_network.setToolTip(
            "Open the MMP pair neighborhood graph for the pairs currently shown in this ledger "
            "(respects reference filter)."
        )
        self._btn_ref_selected = QPushButton("Make Reference")
        self._btn_ref_selected.setToolTip(
            "Use the currently selected table molecule as the reference (exactly one row). "
            "Shows only pairs involving that molecule; transforms and Δ are oriented "
            "as reference → partner. Click again with no single-row selection to show all pairs."
        )
        actions.addWidget(self._btn_browse)
        actions.addWidget(self._btn_cliffs)
        actions.addWidget(self._btn_network)
        actions.addStretch(1)
        actions.addWidget(self._btn_ref_selected)
        root.addLayout(actions)

        self._filter_edit.textChanged.connect(self._apply_filter)
        self._btn_ref_selected.clicked.connect(self._reference_from_table_selection)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._table.cellDoubleClicked.connect(lambda *_a: self._browse_selected())
        self._btn_browse.clicked.connect(self._browse_selected)
        self._btn_cliffs.clicked.connect(self._open_activity_cliffs)
        self._btn_network.clicked.connect(self._open_pair_network)

        make_window_resizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.set_pairs(pairs, activity_column=activity_column)

    def set_pairs(self, pairs: list[MmpPair], *, activity_column: str | None = None) -> None:
        """Replace the underlying pair list and rebuild the ledger table."""
        self._pairs = list(pairs or [])
        if activity_column is not None:
            self._activity_column = activity_column
        # Keep the active reference even when it has no pairs (empty table).
        self._preview_cache.clear()
        self._transform_icon_cache.clear()
        self._core_icon_cache.clear()
        self._rebuild_summaries()

    def _visible_pairs(self) -> list[MmpPair]:
        if self._reference_oid is None:
            return list(self._pairs)
        return pairs_involving_oid(self._pairs, self._reference_oid)

    def _rebuild_summaries(self) -> None:
        self._summaries = aggregate_transforms(self._pairs, reference_oid=self._reference_oid)
        self._pairs_for_summaries = self._visible_pairs()
        n_pairs = len(self._pairs_for_summaries)
        self._populate_table()
        self._btn_cliffs.setEnabled(n_pairs > 0)
        self._btn_network.setEnabled(n_pairs > 0)
        if self._table.rowCount() > 0:
            self._table.selectRow(0)
        else:
            self._btn_browse.setEnabled(False)

    def _reference_from_table_selection(self) -> None:
        app = self._app
        if app is None:
            return
        try:
            oids = sorted(int(o) for o in app._selected_oids_set())
        except Exception:
            oids = []
        if len(oids) != 1:
            # No single-row selection: clear reference and show all pairs again.
            if self._reference_oid is not None:
                self._reference_oid = None
                self._rebuild_summaries()
            else:
                try:
                    app.status_label.setText(
                        "MMP ledger: select exactly one table molecule for reference."
                    )
                except Exception:
                    pass
            return
        oid = oids[0]
        self._reference_oid = oid
        self._rebuild_summaries()
        if not pairs_involving_oid(self._pairs, oid):
            try:
                app.status_label.setText(
                    f"MMP ledger: ID {oid} has no matched pairs (showing empty table)."
                )
            except Exception:
                pass

    def _populate_table(self) -> None:
        filter_text = (self._filter_edit.text() or "").strip().lower()
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)
        for summary in self._summaries:
            hay = f"{summary.core} {summary.transform}".lower()
            if filter_text and filter_text not in hay:
                continue
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._set_row(row, summary)
        self._table.setSortingEnabled(True)
        self._btn_browse.setEnabled(self._table.rowCount() > 0)

    def _set_row(self, row: int, summary: TransformSummary) -> None:
        key = (summary.core, summary.transform)

        core_item = QTableWidgetItem()
        core_item.setData(Qt.UserRole, key)
        core_item.setToolTip(summary.core or "(no core SMILES)")
        core_item.setFlags(core_item.flags() & ~Qt.ItemIsEditable)
        core_pm = self._core_icon(summary.core)
        if core_pm is not None and not core_pm.isNull():
            core_item.setData(Qt.DecorationRole, core_pm)
        else:
            core_item.setText("—")
            core_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, _COL_CORE, core_item)

        transform_item = QTableWidgetItem()
        transform_item.setData(Qt.UserRole, key)
        transform_item.setToolTip(summary.transform)
        transform_item.setFlags(transform_item.flags() & ~Qt.ItemIsEditable)
        pm = self._transform_icon(summary)
        if pm is not None and not pm.isNull():
            transform_item.setData(Qt.DecorationRole, pm)
        else:
            transform_item.setText("→")
            transform_item.setTextAlignment(Qt.AlignCenter)
        self._table.setItem(row, _COL_TRANSFORM, transform_item)
        self._table.setRowHeight(row, _ROW_HEIGHT)

        def _num(col: int, value: float | int, *, display: str | None = None) -> None:
            item = NumericTableWidgetItem()
            item.setData(Qt.EditRole, float(value))
            item.setText(display if display is not None else str(value))
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._table.setItem(row, col, item)

        _num(_COL_N, summary.n, display=str(summary.n))
        _num(_COL_MEDIAN, summary.median_delta, display=_fmt_delta(summary.median_delta))
        _num(_COL_MEAN, summary.mean_delta, display=_fmt_delta(summary.mean_delta))
        win_pct = 100.0 * summary.win_rate
        _num(_COL_WIN, win_pct, display=f"{win_pct:.0f}%")
        _num(_COL_IMPROVE, summary.n_improve, display=str(summary.n_improve))
        _num(_COL_WORSEN, summary.n_worsen, display=str(summary.n_worsen))
        _num(_COL_MIN, summary.min_delta, display=_fmt_delta(summary.min_delta))
        _num(_COL_MAX, summary.max_delta, display=_fmt_delta(summary.max_delta))

    def _core_icon(self, core: str) -> QPixmap | None:
        key = core or ""
        cached = self._core_icon_cache.get(key)
        if cached is not None:
            return cached
        if not key:
            return None
        pm = self._render_frag_fixed(key, _CORE_W, _FRAG_H)
        if pm is not None and not pm.isNull():
            self._core_icon_cache[key] = pm
        return pm

    def _transform_icon(self, summary: TransformSummary) -> QPixmap | None:
        cache_key = f"{summary.core}|{summary.transform}"
        cached = self._transform_icon_cache.get(cache_key)
        if cached is not None:
            return cached
        pm = self._render_transform_pair(summary.sidechain_from, summary.sidechain_to)
        if pm is not None and not pm.isNull():
            self._transform_icon_cache[cache_key] = pm
        return pm

    def _render_transform_pair(self, side_from: str, side_to: str) -> QPixmap | None:
        left = self._render_frag_fixed(side_from, _FRAG_W, _FRAG_H)
        right = self._render_frag_fixed(side_to, _FRAG_W, _FRAG_H)
        if left is None and right is None:
            return None
        if left is None:
            left = QPixmap(_FRAG_W, _FRAG_H)
            left.fill(Qt.transparent)
        if right is None:
            right = QPixmap(_FRAG_W, _FRAG_H)
            right.fill(Qt.transparent)
        total_w = _FRAG_W + _ARROW_W + _FRAG_W
        out = QPixmap(total_w, _FRAG_H)
        out.fill(Qt.transparent)
        painter = QPainter(out)
        try:
            painter.drawPixmap(0, 0, left)
            painter.setPen(self.palette().color(self.palette().WindowText))
            painter.drawText(_FRAG_W, 0, _ARROW_W, _FRAG_H, Qt.AlignCenter, "→")
            painter.drawPixmap(_FRAG_W + _ARROW_W, 0, right)
        finally:
            painter.end()
        return out

    def _render_frag_fixed(self, smiles: str, pw: int, ph: int) -> QPixmap | None:
        if not smiles:
            return None
        cache_key = (smiles, pw, ph, "fixed")
        cached = self._preview_cache.get(cache_key)
        if cached is not None and not cached.isNull():
            return cached
        try:
            mol = Chem.MolFromSmiles(smiles)
        except Exception:
            mol = None
        if mol is None:
            return None
        pm = self._render_mol(mol, pw, ph)
        if pm is not None and not pm.isNull():
            self._preview_cache[cache_key] = pm
        return pm

    def _render_mol(self, mol: Chem.Mol, pw: int, ph: int) -> QPixmap | None:
        try:
            drawer = rdMolDraw2D.MolDraw2DCairo(pw, ph)
            _try_configure_drawer(drawer, pw)
            rdMolDraw2D.PrepareAndDrawMolecule(drawer, mol)
            drawer.FinishDrawing()
            img = QImage.fromData(drawer.GetDrawingText())
            return QPixmap.fromImage(img)
        except Exception:
            return None

    def _apply_filter(self, _text: str = "") -> None:
        prev = self._selected_key()
        self._populate_table()
        if prev:
            for row in range(self._table.rowCount()):
                item = self._table.item(row, _COL_TRANSFORM)
                if item is not None and item.data(Qt.UserRole) == prev:
                    self._table.selectRow(row)
                    return
        if self._table.rowCount() > 0:
            self._table.selectRow(0)
        else:
            self._btn_browse.setEnabled(False)

    def _selected_key(self) -> tuple[str, str] | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self._table.item(rows[0].row(), _COL_TRANSFORM)
        if item is None:
            item = self._table.item(rows[0].row(), _COL_CORE)
        if item is None:
            return None
        value = item.data(Qt.UserRole)
        if isinstance(value, tuple) and len(value) == 2:
            return str(value[0]), str(value[1])
        return None

    def _selected_summary(self) -> TransformSummary | None:
        key = self._selected_key()
        if key is None:
            return None
        core, transform = key
        for s in self._summaries:
            if s.core == core and s.transform == transform:
                return s
        return None

    def _on_selection_changed(self) -> None:
        summary = self._selected_summary()
        self._btn_browse.setEnabled(summary is not None)

    def _browse_selected(self) -> None:
        summary = self._selected_summary()
        app = self._app
        if summary is None or app is None:
            return
        subset = pairs_for_summary(self._pairs, summary)
        if not subset:
            return
        try:
            app._open_mmp_browser(subset, activity_column=self._activity_column)
        except Exception:
            pass

    def _open_activity_cliffs(self) -> None:
        app = self._app
        visible = self._visible_pairs()
        if app is None or not visible:
            return
        try:
            app._open_activity_cliff_map(
                visible,
                activity_column=self._activity_column,
                x_mode="heavy_atoms",
            )
        except Exception:
            logger.exception("Open activity cliffs from ledger failed")

    def _open_pair_network(self) -> None:
        app = self._app
        visible = self._visible_pairs()
        if app is None or not visible:
            return
        try:
            app._open_mmp_neighborhood_map(
                visible,
                activity_column=self._activity_column,
            )
        except Exception:
            logger.exception("Open pair network from ledger failed")
