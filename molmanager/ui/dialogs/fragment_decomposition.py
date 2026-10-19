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

"""Chemistry → Reaction → R-Group Decomposition dialogs."""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QSpinBox,
    QVBoxLayout,
)

from ...chem.fragment_decomposition import detect_fragment_column_prefixes
from ...chem.fragment_recomposition_filters import (
    parse_recomposition_filter_text,
    recomposition_filter_property_help,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_CORE_DECOMP
from .scope import selection_scope_checked


@dataclass(frozen=True)
class FragmentDecompDialogParams:
    """Arguments from :class:`FragmentDecompositionDialog` for the worker."""

    structure_source: str
    column_prefix: str
    method: str  # "brics" | "recap"
    tool_title: str
    render_2d: bool


class FragmentDecompositionDialog(QDialog):
    """Structure source, column prefix, and scope for BRICS or RECAP decomposition."""

    def __init__(
        self,
        *,
        window_title: str,
        default_prefix: str,
        method: str,
        structure_sources: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self._method = method
        self._tool_title = window_title
        self.setWindowTitle(window_title)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText(default_prefix)
        self.prefix_edit.setToolTip(
            "New columns are named PREFIX_1, PREFIX_2, … (one per fragment)."
        )
        form.addRow("Column name prefix:", self.prefix_edit)
        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        self.render_2d_cb = QCheckBox("Render 2D after decomposition")
        self.render_2d_cb.setChecked(False)
        self.render_2d_cb.setToolTip(
            "Render the new fragment columns as 2D depictions (pixmap-only) after decomposition finishes."
        )
        root.addWidget(self.render_2d_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> FragmentDecompDialogParams:
        return FragmentDecompDialogParams(
            structure_source=self.src_combo.currentText(),
            column_prefix=(self.prefix_edit.text() or "").strip(),
            method=self._method,
            tool_title=self._tool_title,
            render_2d=bool(self.render_2d_cb.isChecked()),
        )


@dataclass(frozen=True)
class FragmentRecompDialogParams:
    """Arguments from :class:`FragmentRecompositionDialog` for the worker."""

    column_prefix: str
    method: str  # "brics" | "recap"
    max_depth: int
    max_products: int
    output_filters: str
    tool_title: str


class FragmentRecompositionDialog(QDialog):
    """Pool fragment SMILES columns and run BRICS or RECAP recomposition."""

    def __init__(
        self,
        *,
        window_title: str,
        default_prefix: str,
        method: str,
        table_headers: list[str],
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self._method = method
        self._tool_title = window_title
        self._table_headers = list(table_headers)
        self.setWindowTitle(window_title)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.prefix_combo = QComboBox()
        self.prefix_combo.setEditable(True)
        prefixes = detect_fragment_column_prefixes(self._table_headers)
        if default_prefix not in prefixes:
            prefixes = [default_prefix] + prefixes
        self.prefix_combo.addItems(prefixes)
        self.prefix_combo.setCurrentText(default_prefix)
        self.prefix_combo.setToolTip(
            "Use fragment columns from decomposition (e.g. BRICS_1, BRICS_2 or RECAP_1, …)."
        )
        form.addRow("Fragment column prefix:", self.prefix_combo)

        self.max_depth_sb = QSpinBox()
        self.max_depth_sb.setRange(1, 8)
        self.max_depth_sb.setValue(3)
        self.max_depth_sb.setToolTip("Maximum BRICS coupling depth when assembling products.")
        form.addRow("Max coupling depth:", self.max_depth_sb)

        self.max_products_sb = QSpinBox()
        from ...platform_support.config import load_config

        max_prod_cap = int(load_config().memory_guard_enum_max_products)
        self.max_products_sb.setRange(10, max_prod_cap)
        self.max_products_sb.setValue(min(2000, max_prod_cap))
        self.max_products_sb.setToolTip(
            "Stop after this many accepted product SMILES that meet generation constraints."
        )
        form.addRow("Max products:", self.max_products_sb)
        root.addLayout(form)

        filters_box = QGroupBox("Generation constraints")
        filters_lyt = QVBoxLayout(filters_box)
        self.output_filters_edit = QPlainTextEdit()
        self.output_filters_edit.setPlaceholderText(
            "Optional. Comma- or line-separated AND conditions, e.g.\n"
            "MW 200-500, LogP <= 5, HeavyAtoms >= 10, TPSA < 140"
        )
        self.output_filters_edit.setToolTip(
            "Only assemble products that satisfy these property limits. "
            "Candidates that fail a constraint are skipped and do not count toward max products. "
            f"Supported properties include {recomposition_filter_property_help()}."
        )
        self.output_filters_edit.setMaximumHeight(88)
        filters_lyt.addWidget(self.output_filters_edit)
        root.addWidget(filters_box)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not (self.prefix_combo.currentText() or "").strip():
            QMessageBox.warning(self, self.windowTitle(), "Enter a fragment column prefix.")
            return
        filter_text = self.output_filters_edit.toPlainText().strip()
        if filter_text:
            try:
                parse_recomposition_filter_text(filter_text)
            except ValueError as exc:
                QMessageBox.warning(self, self.windowTitle(), str(exc))
                return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> FragmentRecompDialogParams:
        return FragmentRecompDialogParams(
            column_prefix=(self.prefix_combo.currentText() or "").strip(),
            method=self._method,
            max_depth=int(self.max_depth_sb.value()),
            max_products=int(self.max_products_sb.value()),
            output_filters=self.output_filters_edit.toPlainText().strip(),
            tool_title=self._tool_title,
        )


@dataclass(frozen=True)
class CoreBasedDecompDialogParams:
    """Arguments from :class:`CoreBasedDecompositionDialog` for the worker."""

    core_query: str
    structure_source: str
    column_prefix: str
    only_match_at_r_groups: bool
    remove_hydrogens_post_match: bool
    matching: str  # "greedy" or "exhaustive"


class CoreBasedDecompositionDialog(QDialog):
    """Core SMARTS/SMILES, structure column, RDKit core-based decomposition options."""

    def __init__(self, structure_sources: list[str], selected_row_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_CORE_DECOMP)
        self.setMinimumWidth(420)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("e.g. c1ccc([*:1])cc1 or SMARTS with dummy labels")
        self.core_edit.setToolTip(
            "Parsed as SMARTS first, then as SMILES. Use RDKit-style dummy atoms on the core "
            "that map to substituents in the row molecules."
        )
        form.addRow("Core (SMARTS or SMILES):", self.core_edit)

        self.src_combo = QComboBox()
        self.src_combo.addItems(structure_sources)
        form.addRow("Molecules from:", self.src_combo)

        self.prefix_edit = QLineEdit()
        self.prefix_edit.setText("RGD")
        self.prefix_edit.setToolTip("New columns are named PREFIX_Core, PREFIX_R1, â€¦")
        form.addRow("Column name prefix:", self.prefix_edit)

        self.only_rg_cb = QCheckBox("Only match at R-groups (onlyMatchAtRGroups)")
        self.only_rg_cb.setChecked(True)
        form.addRow(self.only_rg_cb)

        self.remove_h_cb = QCheckBox("Remove hydrogens after match (removeHydrogensPostMatch)")
        self.remove_h_cb.setChecked(True)
        form.addRow(self.remove_h_cb)

        self.match_combo = QComboBox()
        self.match_combo.addItems(["Greedy", "Exhaustive"])
        self.match_combo.setToolTip("Greedy is faster; Exhaustive explores more matchings.")
        form.addRow("Matching strategy:", self.match_combo)

        root.addLayout(form)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._on_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        make_window_minimizable(self)

    def _on_accept(self) -> None:
        if not (self.core_edit.text() or "").strip():
            QMessageBox.warning(self, TOOL_CORE_DECOMP, "Enter a core SMARTS or SMILES.")
            return
        self.accept()

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> CoreBasedDecompDialogParams:
        strat = self.match_combo.currentText().strip().lower()
        return CoreBasedDecompDialogParams(
            core_query=(self.core_edit.text() or "").strip(),
            structure_source=self.src_combo.currentText(),
            column_prefix=(self.prefix_edit.text() or "").strip() or "RGD",
            only_match_at_r_groups=bool(self.only_rg_cb.isChecked()),
            remove_hydrogens_post_match=bool(self.remove_h_cb.isChecked()),
            matching="exhaustive" if strat.startswith("exhaustive") else "greedy",
        )
