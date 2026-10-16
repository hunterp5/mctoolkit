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

"""Shared floating shell for side-by-side pair browsers (MMP, SALI)."""

from __future__ import annotations

from typing import Any

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...table.structure_depiction_layout import (
    BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT,
    BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH,
)
from ..dockable_plot import add_centered_browser_nav, style_browser_nav_buttons
from ..qt_widget_utils import make_window_minimizable
from .chrome import (
    apply_browser_body_layout,
    install_browser_nav_shortcuts,
    make_pair_mol_panel,
    make_pair_prop_box,
    make_pair_prop_value_row,
)


class PairBrowserDialog(QDialog):
    """Two-molecule pair browser with the same preview wells, props, and nav as other browsers."""

    window_title = "Pairs"
    select_status = "pair"

    def __init__(self, parent: Any, *, activity_column: str):
        super().__init__(parent)
        self._app = parent
        self._activity_column = activity_column
        self._idx = getattr(self, "_idx", 0)
        self._preview_cache: dict[tuple, QPixmap] = getattr(self, "_preview_cache", {})
        self._prefer_keys: tuple[int, int] | None = getattr(self, "_prefer_keys", None)

        self.setWindowTitle(self.window_title)
        self.resize(920, 620)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)

        root = QVBoxLayout(self)
        apply_browser_body_layout(root)

        self._meta = QLabel()
        self._meta.setAlignment(Qt.AlignCenter)
        root.addWidget(self._meta)

        self._populate_header(root)

        pair_row = QHBoxLayout()
        pair_row.setSpacing(8)
        self._left_panel = make_pair_mol_panel("Molecule A")
        self._right_panel = make_pair_mol_panel("Molecule B")
        pair_row.addWidget(self._left_panel["box"], 1)
        pair_row.addWidget(self._right_panel["box"], 1)
        root.addLayout(pair_row, 1)

        self._add_comparison_section(root)

        self._prepare_nav_extras()
        nav = QHBoxLayout()
        nav.setContentsMargins(0, 0, 0, 0)
        nav.setSpacing(4)
        self._btn_first = QPushButton("<<")
        self._btn_first.setToolTip("First pair (Home)")
        self._btn_back = QPushButton("←")
        self._btn_back.setToolTip("Previous pair (←)")
        self._btn_fwd = QPushButton("→")
        self._btn_fwd.setToolTip("Next pair (→)")
        self._btn_last = QPushButton(">>")
        self._btn_last.setToolTip("Last pair (End)")
        self._btn_select = QPushButton()
        self._btn_select.setToolTip("Select both molecules of this pair in the main table")
        style_browser_nav_buttons(
            self._btn_first,
            self._btn_back,
            self._btn_fwd,
            self._btn_last,
            self._btn_select,
        )
        self._cb_selected_only = QCheckBox("Selected Only")
        self._cb_selected_only.setToolTip(
            "When checked, browse only pairs that involve at least one molecule "
            "from the current table selection."
        )
        add_centered_browser_nav(
            nav,
            [
                self._btn_first,
                self._btn_back,
                self._btn_fwd,
                self._btn_last,
                self._btn_select,
            ],
            leading=self._nav_leading_widgets(),
            trailing=self._nav_trailing_widgets(),
        )
        self._nav_layout = nav
        root.addLayout(nav)

        self._btn_first.clicked.connect(self._go_first)
        self._btn_back.clicked.connect(lambda: self._step(-1))
        self._btn_fwd.clicked.connect(lambda: self._step(1))
        self._btn_last.clicked.connect(self._go_last)
        self._btn_select.clicked.connect(self._select_current_pair)
        self._cb_selected_only.toggled.connect(self._on_selected_only_toggled)
        install_browser_nav_shortcuts(
            self,
            go_first=self._go_first,
            step=self._step,
            go_last=self._go_last,
        )

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(60)
        self._resize_timer.timeout.connect(self._refresh_previews)

        make_window_minimizable(self)
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self._refresh_property_columns()
        self._update_ui()

    def _populate_header(self, root: QVBoxLayout) -> None:
        """Optional widgets between the caption and the pair cards."""

    def _add_comparison_section(self, root: QVBoxLayout) -> None:
        """Column pickers under the pair cards. Subclasses may show a data table instead."""
        self._prop_box, self._prop_form = make_pair_prop_box()
        self._prop_combo_1 = QComboBox()
        self._prop_combo_2 = QComboBox()
        self._prop_combo_3 = QComboBox()
        for cb in (self._prop_combo_1, self._prop_combo_2, self._prop_combo_3):
            cb.setSizeAdjustPolicy(QComboBox.AdjustToContents)
            cb.currentIndexChanged.connect(lambda _i: self._update_property_values())
        self._prop_value_1 = make_pair_prop_value_row()
        self._prop_value_2 = make_pair_prop_value_row()
        self._prop_value_3 = make_pair_prop_value_row()
        self._prop_form.addRow(self._prop_combo_1, self._prop_value_1["host"])
        self._prop_form.addRow(self._prop_combo_2, self._prop_value_2["host"])
        self._prop_form.addRow(self._prop_combo_3, self._prop_value_3["host"])
        root.addWidget(self._prop_box)

    def _prepare_nav_extras(self) -> None:
        """Create extra nav widgets before the nav row is assembled."""

    def _nav_leading_widgets(self) -> list[QWidget]:
        return []

    def _nav_trailing_widgets(self) -> list[QWidget]:
        return [self._cb_selected_only]

    def _item_count(self) -> int:
        raise NotImplementedError

    def _current_pair_oids(self) -> tuple[int, int] | None:
        raise NotImplementedError

    def _on_selected_only_toggled(self, _checked: bool) -> None:
        raise NotImplementedError

    def _update_ui(self) -> None:
        raise NotImplementedError

    def _refresh_previews(self) -> None:
        raise NotImplementedError

    def resizeEvent(self, event) -> None:  # noqa: N802 — Qt API
        super().resizeEvent(event)
        self._resize_timer.start()

    def _selected_oids(self) -> set[int]:
        app = self._app
        if app is None:
            return set()
        try:
            return {int(o) for o in app._selected_oids_set()}
        except Exception:
            return set()

    def _go_first(self) -> None:
        self._idx = 0
        self._update_ui()

    def _go_last(self) -> None:
        self._idx = max(0, self._item_count() - 1)
        self._update_ui()

    def _step(self, delta: int) -> None:
        n = self._item_count()
        if n <= 0:
            return
        self._idx = (self._idx + int(delta)) % n
        self._update_ui()

    def _select_current_pair(self) -> None:
        oids = self._current_pair_oids()
        app = self._app
        if oids is None or app is None:
            return
        try:
            app.select_table_oids([oids[0], oids[1]], extra_status=self.select_status)
        except Exception:
            pass

    def _sync_nav_enabled(self, *, count: int, extra: list[QWidget] | None = None) -> None:
        has = count > 0
        self._btn_first.setEnabled(has)
        self._btn_last.setEnabled(has)
        self._btn_back.setEnabled(count > 1)
        self._btn_fwd.setEnabled(count > 1)
        self._btn_select.setEnabled(has)
        for widget in extra or []:
            widget.setEnabled(has)

    def _clear_pair_panels(self) -> None:
        for panel in (self._left_panel, self._right_panel):
            panel["struct"].clear()
            panel["struct"].setPixmap(QPixmap())
            panel["activity"].setText("—")

    def _refresh_property_columns(self) -> None:
        """Populate the 3 column pickers from current table headers, preserving selections."""
        try:
            headers = list(getattr(self._app, "headers", []) or [])
        except Exception:
            headers = []
        choices = [h for h in headers if h not in ("ID_HIDDEN", "Structure")]
        combos = (self._prop_combo_1, self._prop_combo_2, self._prop_combo_3)
        prev = [cb.currentText() for cb in combos]
        for cb in combos:
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("—", userData=None)
            for h in choices:
                cb.addItem(h, userData=h)
            cb.blockSignals(False)
        for cb, p in zip(combos, prev, strict=False):
            if p and p != "—":
                j = cb.findText(p)
                if j >= 0:
                    cb.setCurrentIndex(j)

        def _set_default(cb: QComboBox, prefer: list[str]) -> None:
            if cb.currentData() is not None:
                return
            for h in prefer:
                j = cb.findText(h)
                if j >= 0:
                    cb.setCurrentIndex(j)
                    return

        act = self._activity_column
        _set_default(self._prop_combo_1, [act, "SMILES", "Name", "CompoundName", "ID"])
        _set_default(self._prop_combo_2, ["Name", "CompoundName", "CAS", "InChIKey", "SMILES"])
        _set_default(self._prop_combo_3, ["MW", "MolWt", "cLogP", "LogP", "TPSA"])

    def _cell_text_for_oid(self, oid: int, header: str) -> str:
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
            text = (app._table_cell_text(row, col) or "").strip()
            if not text:
                text = (app._table_model.backing_value_for_row_header(row, header) or "").strip()
            return text
        except Exception:
            return ""

    def _update_property_values(self) -> None:
        oids = self._current_pair_oids()
        rows = [
            (self._prop_combo_1, self._prop_value_1),
            (self._prop_combo_2, self._prop_value_2),
            (self._prop_combo_3, self._prop_value_3),
        ]
        if oids is None:
            for _cb, vals in rows:
                vals["a"].setText("—")
                vals["b"].setText("—")
            return
        oid_a, oid_b = oids
        for cb, vals in rows:
            h = cb.currentData()
            if not h:
                vals["a"].setText("—")
                vals["b"].setText("—")
                continue
            va = self._cell_text_for_oid(oid_a, str(h))
            vb = self._cell_text_for_oid(oid_b, str(h))
            vals["a"].setText(f"A: {va}" if va else "A: —")
            vals["b"].setText(f"B: {vb}" if vb else "B: —")

    def _preview_pixel_size(self, label: QLabel) -> tuple[int, int, float]:
        dpr = max(1.0, float(self.devicePixelRatioF()))
        lw = max(label.width(), BROWSER_STRUCTURE_PREVIEW_MIN_WIDTH // 2)
        lh = max(label.height(), BROWSER_STRUCTURE_PREVIEW_MIN_HEIGHT // 2)
        return int(lw * dpr), int(lh * dpr), dpr
