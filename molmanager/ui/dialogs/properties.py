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

"""Chemistry → Calculate Descriptors."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...chem.structural_alerts import available_alert_catalogs
from ...descriptors.catalog import iter_descriptor_tab_items
from ...reference.descriptor_tooltips import descriptor_checkbox_tooltip
from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked


class PropertyDialog(QDialog):
    """Pick descriptor columns (and optional selected-row scope) for CalcWorker."""

    def __init__(self, columns, selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self._init_property_state(columns, selected_row_count)
        self._build_property_ui()
        self._wire_property_ui()

    def _init_property_state(self, columns, selected_row_count: int) -> None:
        self.setWindowTitle("Calculate Descriptors")
        self.resize(820, 700)
        self._source_columns = [c for c in columns if (c or "").strip()]
        self._selected_row_count = int(selected_row_count)
        self._have_selection = selected_row_count > 0
        self._alert_catalogs = ()
        self._alert_checks = {}

    def _build_property_ui(self) -> None:
        root = QVBoxLayout(self)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel("Target Column:"))
        self.src_combo = QComboBox()
        self.src_combo.addItems(self._source_columns)
        target_row.addWidget(self.src_combo, 1)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({self._selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        target_row.addWidget(self.only_selected_cb, 0, Qt.AlignVCenter)
        root.addLayout(target_row)

        self.tabs = QTabWidget()
        bar = self.tabs.tabBar()
        bar.setUsesScrollButtons(True)
        bar.setExpanding(False)
        bar.setDrawBase(True)

        self.cbs = {}
        for cat_name, items in iter_descriptor_tab_items():
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            tab = QWidget()
            tab_lyt = QVBoxLayout(tab)
            for disp, internal in items:
                cb = QCheckBox(disp)
                tip = descriptor_checkbox_tooltip(internal)
                if tip:
                    cb.setToolTip(tip)
                tab_lyt.addWidget(cb)
                self.cbs[disp] = (cb, internal)
            tab_lyt.addStretch()
            scroll.setWidget(tab)
            self.tabs.addTab(scroll, cat_name)
        self._add_structural_alerts_tab()

        root.addWidget(self.tabs, 1)
        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok)
        root.addWidget(self._button_box)
        self._lock_width_to_tabs()

    def _lock_width_to_tabs(self) -> None:
        """Open wide enough for every tab label, and refuse a narrower resize."""
        bar = self.tabs.tabBar()
        bar.ensurePolished()
        margins = self.layout().contentsMargins()
        width = bar.sizeHint().width() + margins.left() + margins.right()
        self.setMinimumWidth(width)
        if self.width() < width:
            self.resize(width, self.height())

    def _wire_property_ui(self) -> None:
        self._button_box.accepted.connect(self.accept)
        make_window_minimizable(self)

    def _add_structural_alerts_tab(self) -> None:
        """Catalog checkboxes. Each checked set writes a count column and a name column."""
        catalogs = available_alert_catalogs()
        if not catalogs:
            return
        self._alert_catalogs = catalogs
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        tab = QWidget()
        tab_lyt = QVBoxLayout(tab)
        for spec in catalogs:
            cb = QCheckBox(spec.label)
            count_header, _count_key = spec.column_pairs()[0]
            names_header, _names_key = spec.column_pairs()[1]
            cb.setToolTip(f"{spec.summary} Writes {count_header} and {names_header}.")
            tab_lyt.addWidget(cb)
            self._alert_checks[spec.key] = cb
        tab_lyt.addStretch()
        scroll.setWidget(tab)
        insert_at = self.tabs.count()
        for index in range(self.tabs.count()):
            if self.tabs.tabText(index) == "Drug-likeness":
                insert_at = index + 1
                break
        self.tabs.insertTab(insert_at, scroll, "Structural Alerts")

    def get_selected(self):
        sel_disp, sel_int = [], []
        for d, (cb, i) in self.cbs.items():
            if cb.isChecked():
                sel_disp.append(d)
                sel_int.append(i)
        for spec in self._alert_catalogs:
            if self._alert_checks[spec.key].isChecked():
                for header, internal in spec.column_pairs():
                    sel_disp.append(header)
                    sel_int.append(internal)
        return sel_disp, sel_int

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)
