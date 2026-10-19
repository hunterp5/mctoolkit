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

"""Reusable Browser-style property column pickers (header combo + value label)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from .qt_widget_utils import apply_group_box_style

PROPERTY_COLUMN_SLOT_COUNT = 3
PROPERTY_COLUMN_SLOT_MAX = 10

_DEFAULT_COLUMN_PREFERENCES: tuple[tuple[str, ...], ...] = (
    ("SMILES", "Name", "CompoundName", "ID"),
    ("Name", "CompoundName", "CAS", "InChIKey"),
    ("MW", "MolWt", "cLogP", "LogP", "TPSA"),
    ("TPSA", "HBA", "HBD", "RotBonds", "Formula"),
    ("cLogP", "LogP", "InChIKey", "CAS", "ID"),
)


class PropertyColumnsPanel(QWidget):
    """Column pickers that show cell values for a table row identified by OID."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        slot_count: int = PROPERTY_COLUMN_SLOT_COUNT,
        max_slots: int = PROPERTY_COLUMN_SLOT_MAX,
    ):
        super().__init__(parent)
        self._app: Any = None
        self._oid: int | None = None
        capacity = max(1, int(max_slots))
        visible = max(0, min(int(slot_count), capacity))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._prop_box = QGroupBox()
        self._prop_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        apply_group_box_style(self._prop_box)
        self._rows_host = QWidget(self._prop_box)
        self._rows_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._rows_ly = QVBoxLayout(self._rows_host)
        self._rows_ly.setContentsMargins(12, 12, 12, 10)
        self._rows_ly.setSpacing(8)
        box_ly = QVBoxLayout(self._prop_box)
        box_ly.setContentsMargins(0, 0, 0, 0)
        box_ly.setSpacing(0)
        box_ly.addWidget(self._rows_host)

        self._prop_combos: list[QComboBox] = []
        self._prop_values: list[QLabel] = []
        self._prop_rows: list[QWidget] = []
        for _ in range(capacity):
            row = QWidget(self._rows_host)
            row.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            row_ly = QHBoxLayout(row)
            row_ly.setContentsMargins(0, 0, 0, 0)
            row_ly.setSpacing(10)
            cb = QComboBox()
            cb.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            cb.setMinimumContentsLength(10)
            cb.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            lab = QLabel("—")
            lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
            lab.setWordWrap(True)
            lab.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
            lab.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            row_ly.addWidget(cb, 0)
            row_ly.addWidget(lab, 1)
            self._rows_ly.addWidget(row)
            cb.currentIndexChanged.connect(lambda _i: self.update_values())
            self._prop_rows.append(row)
            self._prop_combos.append(cb)
            self._prop_values.append(lab)
        root.addWidget(self._prop_box)
        self._visible_slot_count = visible
        self._apply_visible_slot_count()

        # Compatibility aliases used by tests / older call sites.
        self._prop_combo_1 = self._prop_combos[0]
        self._prop_combo_2 = self._prop_combos[1] if capacity > 1 else self._prop_combos[0]
        self._prop_combo_3 = self._prop_combos[2] if capacity > 2 else self._prop_combos[0]
        self._prop_value_1 = self._prop_values[0]
        self._prop_value_2 = self._prop_values[1] if capacity > 1 else self._prop_values[0]
        self._prop_value_3 = self._prop_values[2] if capacity > 2 else self._prop_values[0]

    def visible_slot_count(self) -> int:
        return int(getattr(self, "_visible_slot_count", len(self._prop_combos)))

    def set_visible_slot_count(self, count: int) -> None:
        """Show the first *count* property pickers (0 hides all rows)."""
        capacity = len(self._prop_combos)
        n = max(0, min(int(count), capacity))
        if n == self.visible_slot_count():
            return
        self._visible_slot_count = n
        self._apply_visible_slot_count()
        self.update_values()

    def _apply_visible_slot_count(self) -> None:
        n = self.visible_slot_count()
        # Re-parent only the visible rows into the layout so the group box height
        # tracks the field count (hidden QForm/QVBox children still reserve space).
        while self._rows_ly.count():
            item = self._rows_ly.takeAt(0)
            w = item.widget() if item is not None else None
            if w is not None:
                w.hide()
                w.setParent(self._rows_host)
        for i, row in enumerate(self._prop_rows):
            if i < n:
                self._rows_ly.addWidget(row)
                row.show()
            else:
                row.hide()
                row.setParent(self._rows_host)
        self._prop_box.setVisible(n > 0)
        self.setVisible(n > 0)
        self._rows_host.adjustSize()
        self._prop_box.adjustSize()
        self.adjustSize()
        self._prop_box.updateGeometry()
        self.updateGeometry()

    def bind_app(self, app: Any) -> None:
        """Attach the main table app and (re)populate column choices."""
        self._app = app
        self.refresh_columns()
        self.update_values()

    def set_source_oid(self, oid: int | None) -> None:
        """Show values for this table row OID (or clear when *oid* is None)."""
        try:
            self._oid = int(oid) if oid is not None else None
        except (TypeError, ValueError):
            self._oid = None
        self.update_values()

    def source_oid(self) -> int | None:
        return self._oid

    def refresh_columns(self) -> None:
        """Populate the column pickers from current table headers."""
        try:
            headers = list(getattr(self._app, "headers", []) or [])
        except Exception:
            headers = []
        choices = [h for h in headers if h not in ("ID_HIDDEN", "Structure")]

        prev = [cb.currentText() for cb in self._prop_combos]
        for cb in self._prop_combos:
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("—", userData=None)
            for h in choices:
                cb.addItem(h, userData=h)
            cb.blockSignals(False)
        for cb, p in zip(self._prop_combos, prev, strict=False):
            if p and p != "—":
                j = cb.findText(p)
                if j >= 0:
                    cb.setCurrentIndex(j)

        def _set_default(cb: QComboBox, prefer: tuple[str, ...]) -> None:
            if cb.currentData() is not None:
                return
            for h in prefer:
                j = cb.findText(h)
                if j >= 0:
                    cb.setCurrentIndex(j)
                    return

        for i, cb in enumerate(self._prop_combos):
            prefer = _DEFAULT_COLUMN_PREFERENCES[i] if i < len(_DEFAULT_COLUMN_PREFERENCES) else ()
            if prefer:
                _set_default(cb, prefer)

    def cell_text_for_oid(self, oid: int, header: str) -> str:
        """Display text for *header* on the row with *oid*."""
        app = self._app
        if app is None or not header:
            return ""
        try:
            row = app.logical_row_for_oid(int(oid))
        except Exception:
            return ""
        if row is None or row < 0:
            return ""
        try:
            col = int(app.headers.index(header))
        except Exception:
            return ""
        try:
            cell_fn = getattr(app, "_table_cell_text", None)
            text = ""
            if callable(cell_fn):
                text = (cell_fn(row, col) or "").strip()
            if not text:
                model = getattr(app, "_table_model", None)
                if model is not None:
                    text = (model.backing_value_for_row_header(row, header) or "").strip()
            return text
        except Exception:
            return ""

    def update_values(self) -> None:
        """Refresh value labels from the current OID and combo selections."""
        oid = self._oid
        if oid is None:
            for lab in self._prop_values:
                lab.setText("—")
            return
        for cb, lab in zip(self._prop_combos, self._prop_values, strict=True):
            h = cb.currentData()
            if not h:
                lab.setText("—")
                continue
            v = self.cell_text_for_oid(oid, str(h))
            lab.setText(v if v != "" else "—")
