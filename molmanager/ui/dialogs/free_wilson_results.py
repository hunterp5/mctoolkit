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

"""Free-Wilson results: coefficients, predictions, and missing analogs.

Substituent labels and missing-analog SMILES are drawn in the tables. The cell
text stays the SMILES so a hover or copy still yields the string.
"""

from __future__ import annotations

from PyQt5.QtCore import QSize, Qt
from PyQt5.QtGui import QColor, QFontMetrics, QPainter, QPalette, QPixmap
from PyQt5.QtWidgets import (
    QAbstractItemView,
    QAbstractScrollArea,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)
from rdkit import Chem

from ...analysis.free_wilson import (
    PREDICTED_COLUMN,
    SOURCE_COLUMN,
    SOURCE_VALUE,
    FreeWilsonResult,
    MissingAnalog,
    report_label,
)
from ...table.structure_image import molecule_pixmap
from ..qt_widget_utils import make_window_resizable, qobject_is_deleted
from ..strings import TOOL_FREE_WILSON

_DRAW_ERRORS = (RuntimeError, ValueError, TypeError, OSError)
_FRAG_W = 128
_FRAG_H = 80
_CAPTION_H = 18
# Wide channel so neighboring R groups read as separate drawings, not one molecule.
_STRIP_GAP = 48
_GAP_RULE = QColor(196, 196, 196)
_MOL_W = 220
_MOL_H = 96
_STRUCTURE_ROW_H = 112
_STRUCTURE_MARGIN = 4
_CELL_INK = QColor(32, 32, 32)
_SMILES_HEADER_TIP = "Drawn from the SMILES. Hover or copy the cell for the text."


def _fmt(value: float | None) -> str:
    if value is None:
        return ""
    return format(float(value), ".6g")


def _substituent_text(pairs: tuple[tuple[str, str], ...]) -> str:
    return ", ".join(f"{position}={label}" for position, label in pairs)


def _readonly_table(
    headers: list[str],
    structure_columns: tuple[int, ...] = (),
) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setSizeAdjustPolicy(QAbstractScrollArea.AdjustIgnored)
    table.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
    header = table.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeToContents)
    header.setStretchLastSection(True)
    if structure_columns:
        delegate = _StructureCellDelegate(table)
        for column in structure_columns:
            table.setItemDelegateForColumn(column, delegate)
            header_item = table.horizontalHeaderItem(column)
            if header_item is not None:
                header_item.setToolTip(_SMILES_HEADER_TIP)
        table.verticalHeader().setDefaultSectionSize(_STRUCTURE_ROW_H)
    return table


def _text_item(text: str) -> QTableWidgetItem:
    item = QTableWidgetItem(text)
    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
    return item


def _structure_item(text: str, pixmap: QPixmap | None) -> QTableWidgetItem:
    """Cell whose picture is *pixmap* and whose copied text is *text*."""
    item = _text_item(text)
    item.setToolTip(text)
    item.setTextAlignment(Qt.AlignCenter)
    if pixmap is not None and not pixmap.isNull():
        item.setData(Qt.DecorationRole, pixmap)
    return item


def _render_smiles(smiles: str, width: int, height: int) -> QPixmap | None:
    """2D depiction of *smiles*, or ``None`` when it has no heavy atoms to draw."""
    text = (smiles or "").strip()
    if not text or text == "H" or width <= 0 or height <= 0:
        return None
    try:
        mol = Chem.MolFromSmiles(text)
    except _DRAW_ERRORS:
        return None
    if mol is None or mol.GetNumHeavyAtoms() == 0:
        return None
    try:
        pixmap = molecule_pixmap(mol, width, height)
    except _DRAW_ERRORS:
        return None
    if pixmap.isNull():
        return None
    return pixmap


class _StructureCellDelegate(QStyledItemDelegate):
    """Paint a SMILES depiction on white so it fills the cell like the main table."""

    def paint(self, painter, option, index):  # noqa: N802 — Qt API name
        opt = QStyleOptionViewItem(option)
        painter.save()
        painter.fillRect(opt.rect, QColor(255, 255, 255))
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            self._paint_pixmap(painter, opt, pix)
        else:
            self._paint_label(painter, opt, str(index.data(Qt.DisplayRole) or ""))
        if opt.state & QStyle.State_Selected:
            highlight = opt.palette.color(QPalette.Highlight)
            highlight.setAlpha(48)
            painter.fillRect(opt.rect, highlight)
        painter.restore()

    def _paint_pixmap(self, painter: QPainter, opt: QStyleOptionViewItem, pix: QPixmap) -> None:
        margin = _STRUCTURE_MARGIN
        avail_w = max(1, opt.rect.width() - 2 * margin)
        avail_h = max(1, opt.rect.height() - 2 * margin)
        fitted = pix.scaled(avail_w, avail_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = opt.rect.x() + margin + (avail_w - fitted.width()) // 2
        y = opt.rect.y() + margin + (avail_h - fitted.height()) // 2
        painter.drawPixmap(x, y, fitted)

    def _paint_label(self, painter: QPainter, opt: QStyleOptionViewItem, text: str) -> None:
        painter.setPen(_CELL_INK)
        painter.setFont(opt.font)
        inner = opt.rect.adjusted(
            _STRUCTURE_MARGIN,
            _STRUCTURE_MARGIN,
            -_STRUCTURE_MARGIN,
            -_STRUCTURE_MARGIN,
        )
        shown = QFontMetrics(opt.font).elidedText(text, Qt.ElideMiddle, max(1, inner.width()))
        painter.drawText(inner, int(Qt.AlignCenter), shown)

    def sizeHint(self, option, index):  # noqa: N802 — Qt API name
        pix = index.data(Qt.DecorationRole)
        if isinstance(pix, QPixmap) and not pix.isNull():
            return QSize(pix.width() + 2 * _STRUCTURE_MARGIN, _STRUCTURE_ROW_H)
        return QSize(_FRAG_W, _STRUCTURE_ROW_H)


class FreeWilsonResultsDialog(QDialog):
    """Modeless summary of one Free-Wilson fit. Nothing is written until a button is used."""

    def __init__(self, result: FreeWilsonResult, parent=None):
        super().__init__(parent)
        self.parent_app = parent
        self._result = result
        self._added_smiles: set[str] = set()
        self._depictions: dict[tuple[str, int, int], QPixmap | None] = {}
        self.setWindowTitle(self._title())
        self.resize(980, 640)
        self.setAttribute(Qt.WA_DeleteOnClose, True)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        tabs = QTabWidget()
        tabs.addTab(self._summary_tab(), "Summary")
        tabs.addTab(self._contribution_tab(), "Contributions")
        tabs.addTab(self._observed_tab(), "Observed")
        tabs.addTab(self._missing_tab(), "Missing")
        root.addWidget(tabs, 1)
        make_window_resizable(self)

    def _title(self) -> str:
        column = (self._result.activity_column or "").strip()
        if column:
            return f"{TOOL_FREE_WILSON} — {column}"
        return TOOL_FREE_WILSON

    def _summary_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        text = QTextEdit()
        text.setReadOnly(True)
        text.setPlainText(self._summary_text())
        layout.addWidget(text)
        return page

    def _summary_text(self) -> str:
        result = self._result
        lines = [
            f"Report: {report_label(result.report)}",
            f"Fitted molecules: {result.n}",
            f"Parameters (including intercept): {result.n_parameters}",
            f"Intercept: {_fmt(result.intercept)}",
        ]
        if result.intercept_std_error is not None:
            lines.append(f"Intercept std. error: {_fmt(result.intercept_std_error)}")
        lines.append(f"R²: {_fmt(result.r_squared)}")
        lines.append(f"Adjusted R²: {_fmt(result.adjusted_r_squared) or '—'}")
        lines.append(f"RMSE: {_fmt(result.rmse)}")
        lines.append(f"Residual degrees of freedom: {result.residual_df}")
        if result.saturated:
            lines.append("The fit is saturated (no residual degrees of freedom).")
        if result.references:
            refs = ", ".join(f"{position}={label}" for position, label in result.references)
            lines.append(f"Reference substituents: {refs}")
        if result.skipped:
            counts: dict[str, int] = {}
            for row in result.skipped:
                counts[row.reason] = counts.get(row.reason, 0) + 1
            detail = ", ".join(f"{reason}: {count}" for reason, count in sorted(counts.items()))
            lines.append(f"Skipped rows: {len(result.skipped)} ({detail})")
        if result.position_counts:
            counts_text = ", ".join(
                f"{position}: {count}" for position, count in result.position_counts
            )
            lines.append(f"Substituents per position: {counts_text}")
        lines.append(f"Combinations: {result.n_combinations:,}")
        lines.append(f"Missing combinations: {result.n_missing:,}")
        lines.append(f"Listed missing analogs: {len(result.missing):,}")
        if result.enumeration_message:
            lines.append(result.enumeration_message)
        if result.n_zip_failed:
            lines.append(f"Combinations that could not be rebuilt: {result.n_zip_failed:,}")
        lines.append(
            "Predicted activities and missing structures are written to the table only "
            "from the Observed and Missing tabs."
        )
        return "\n".join(lines)

    def _contribution_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(
            ["Position", "Substituent", "Count", "Coefficient", "Std. error", "Note"],
            structure_columns=(1,),
        )
        table.setRowCount(len(self._result.coefficients))
        for row_index, coef in enumerate(self._result.coefficients):
            if not coef.identifiable:
                note = "not identifiable"
            elif coef.is_reference:
                note = "reference"
            else:
                note = ""
            table.setItem(row_index, 0, _text_item(coef.position))
            table.setItem(
                row_index,
                1,
                _structure_item(coef.label, self._depict_smiles(coef.label, _FRAG_W, _FRAG_H)),
            )
            values = [
                str(coef.count),
                _fmt(coef.coefficient),
                _fmt(coef.std_error),
                note,
            ]
            for offset, value in enumerate(values):
                table.setItem(row_index, offset + 2, _text_item(value))
        layout.addWidget(table)
        return page

    def _observed_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        table = _readonly_table(
            ["OID", "Observed", "Predicted", "Residual", "Substituents"],
            structure_columns=(4,),
        )
        table.setRowCount(len(self._result.observed))
        for row_index, row in enumerate(self._result.observed):
            values = [
                str(row.oid),
                _fmt(row.observed),
                _fmt(row.predicted),
                _fmt(row.residual),
            ]
            for column, value in enumerate(values):
                table.setItem(row_index, column, _text_item(value))
            text = _substituent_text(row.substituents)
            table.setItem(
                row_index,
                4,
                _structure_item(text, self._depict_substituents(row.substituents)),
            )
        layout.addWidget(table, 1)
        button_row = QHBoxLayout()
        self._write_btn = QPushButton("Write predictions")
        self._write_btn.setToolTip(
            f"Write {PREDICTED_COLUMN} for each fitted row. Does not add new rows."
        )
        self._write_btn.setEnabled(bool(self._result.observed))
        self._write_btn.clicked.connect(self._write_predictions)
        button_row.addWidget(self._write_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return page

    def _missing_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        if self._result.enumeration_message:
            note = QLabel(self._result.enumeration_message)
            note.setWordWrap(True)
            layout.addWidget(note)
        self._missing_table = _readonly_table(
            ["Substituents", "Predicted", "SMILES"],
            structure_columns=(0, 2),
        )
        self._missing_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self._missing_table.setRowCount(len(self._result.missing))
        for row_index, analog in enumerate(self._result.missing):
            substituent_text = _substituent_text(analog.substituents)
            self._missing_table.setItem(
                row_index,
                0,
                _structure_item(substituent_text, self._depict_substituents(analog.substituents)),
            )
            self._missing_table.setItem(row_index, 1, _text_item(_fmt(analog.predicted)))
            self._missing_table.setItem(
                row_index,
                2,
                _structure_item(analog.smiles, self._depict_smiles(analog.smiles, _MOL_W, _MOL_H)),
            )
        layout.addWidget(self._missing_table, 1)
        button_row = QHBoxLayout()
        self._add_selected_btn = QPushButton("Add selected to table")
        self._add_selected_btn.setToolTip(
            "Append the selected missing analogs as new rows with SMILES, "
            f"{PREDICTED_COLUMN}, R-group labels, and a source field."
        )
        self._add_all_btn = QPushButton("Add all shown")
        self._add_all_btn.setToolTip("Append every listed missing analog.")
        enabled = bool(self._result.missing)
        self._add_selected_btn.setEnabled(enabled)
        self._add_all_btn.setEnabled(enabled)
        self._add_selected_btn.clicked.connect(self._add_selected)
        self._add_all_btn.clicked.connect(self._add_all)
        button_row.addWidget(self._add_selected_btn)
        button_row.addWidget(self._add_all_btn)
        button_row.addStretch(1)
        layout.addLayout(button_row)
        return page

    def _depict_smiles(self, smiles: str, width: int, height: int) -> QPixmap | None:
        key = (smiles, width, height)
        if key not in self._depictions:
            self._depictions[key] = _render_smiles(smiles, width, height)
        return self._depictions[key]

    def _depict_substituents(self, pairs: tuple[tuple[str, str], ...]) -> QPixmap | None:
        """One captioned fragment per R position, with a gap between neighbors.

        Hydrogen stays the letter H. The rule in each gap keeps adjacent drawings
        from reading as a single structure.
        """
        if not pairs:
            return None
        gaps = max(0, len(pairs) - 1)
        width = len(pairs) * _FRAG_W + _STRIP_GAP * gaps
        image = QPixmap(max(1, width), _CAPTION_H + _FRAG_H)
        image.fill(Qt.white)
        painter = QPainter(image)
        try:
            metrics = QFontMetrics(painter.font())
            x = 0
            for index, (position, label) in enumerate(pairs):
                if index:
                    rule_x = x + _STRIP_GAP // 2
                    painter.setPen(_GAP_RULE)
                    painter.drawLine(rule_x, _CAPTION_H + 6, rule_x, _CAPTION_H + _FRAG_H - 6)
                    x += _STRIP_GAP
                painter.setPen(_CELL_INK)
                painter.drawText(x, 0, _FRAG_W, _CAPTION_H, Qt.AlignCenter, position)
                pixmap = self._depict_smiles(label, _FRAG_W, _FRAG_H)
                if pixmap is not None and not pixmap.isNull():
                    painter.drawPixmap(x, _CAPTION_H, pixmap)
                else:
                    shown = metrics.elidedText(label, Qt.ElideMiddle, _FRAG_W - 8)
                    painter.drawText(
                        x,
                        _CAPTION_H,
                        _FRAG_W,
                        _FRAG_H,
                        int(Qt.AlignCenter),
                        shown,
                    )
                x += _FRAG_W
        finally:
            painter.end()
        return image

    def _selected_analogs(self) -> list[MissingAnalog]:
        rows = sorted({item.row() for item in self._missing_table.selectedItems()})
        missing = self._result.missing
        return [missing[row] for row in rows if 0 <= row < len(missing)]

    def _write_predictions(self) -> None:
        app = self.parent_app
        if app is None or not hasattr(app, "on_calc_finished"):
            QMessageBox.warning(self, TOOL_FREE_WILSON, "The table is not available.")
            return
        rows = [(row.oid, {PREDICTED_COLUMN: _fmt(row.predicted)}) for row in self._result.observed]

        def _written(_headers: list[str]) -> None:
            self._mark_dirty(app)
            status = getattr(app, "status_label", None)
            if status is not None:
                status.setText(
                    f"{TOOL_FREE_WILSON}: wrote {PREDICTED_COLUMN} for {len(rows):,} row(s)."
                )
            if qobject_is_deleted(self):
                return
            self._write_btn.setEnabled(False)
            self._write_btn.setText("Predictions written")

        app.on_calc_finished(
            rows,
            [PREDICTED_COLUMN],
            finish_progress=False,
            on_complete=_written,
        )

    def _add_selected(self) -> None:
        analogs = [row for row in self._selected_analogs() if row.smiles not in self._added_smiles]
        if not analogs:
            QMessageBox.information(
                self,
                TOOL_FREE_WILSON,
                "Select one or more missing analogs that are not already added.",
            )
            return
        self._add_analogs(analogs)

    def _add_all(self) -> None:
        analogs = [row for row in self._result.missing if row.smiles not in self._added_smiles]
        if not analogs:
            return
        self._add_analogs(analogs)

    def _add_analogs(self, analogs: list[MissingAnalog]) -> None:
        app = self.parent_app
        if app is None or not hasattr(app, "add_rows_from_external_records_batch"):
            QMessageBox.warning(self, TOOL_FREE_WILSON, "The table is not available.")
            return
        records: list[tuple[str, dict[str, str]]] = []
        for analog in analogs:
            fields = {
                PREDICTED_COLUMN: _fmt(analog.predicted),
                SOURCE_COLUMN: SOURCE_VALUE,
            }
            for position, label in analog.substituents:
                fields[f"FW_{position}"] = label
            records.append((analog.smiles, fields))
        added = int(app.add_rows_from_external_records_batch(records, render_structures=True))
        for analog in analogs:
            self._added_smiles.add(analog.smiles)
        if len(self._added_smiles) >= len(self._result.missing):
            self._add_all_btn.setEnabled(False)
            self._add_all_btn.setText("All shown added")
        self._mark_dirty(app)
        status = getattr(app, "status_label", None)
        if status is not None:
            status.setText(f"{TOOL_FREE_WILSON}: added {added:,} missing analog(s).")

    def _mark_dirty(self, app: object) -> None:
        mark = getattr(app, "_mark_session_dirty", None)
        if callable(mark):
            mark()
