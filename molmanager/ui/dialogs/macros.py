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

"""Edit and run saved macro recipes.

The dialog writes the document in ``workflows.macro_recipe``. Running it is
``MacroRunner``, which calls the same tool entry points as the individual dialogs.
"""

from __future__ import annotations

import json
from contextlib import suppress
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...platform_support.memory_guards import clamp_max_products_ui
from ...workflows.macro_recipe import (
    FILTER_KINDS,
    FILTER_NUMERIC,
    FILTER_SUBSTRUCTURE,
    FILTER_TEXT,
    ROW_SCOPE_LABELS,
    STEP_CALCULATOR,
    STEP_DESCRIPTORS,
    STEP_FILTER,
    STEP_KINDS,
    STEP_LABELS,
    STEP_PROTONATE,
    STEP_REACTION,
    MacroDocumentError,
    MacroRecipe,
    default_step,
    descriptor_tabs,
    format_issues,
    new_recipe,
    new_recipe_id,
    output_keys,
    recipe_from_json,
    recipe_to_json,
    step_to_json,
    validate_recipe,
)
from ..macro_library import load_macro_library, save_macro_library
from ..macro_runner import MacroRunner
from ..qt_widget_utils import make_window_resizable
from ..strings import TOOL_MACROS

_PAGE = {
    STEP_DESCRIPTORS: 0,
    STEP_CALCULATOR: 1,
    STEP_PROTONATE: 2,
    STEP_FILTER: 3,
    STEP_REACTION: 4,
}
_SCOPED = {STEP_DESCRIPTORS, STEP_CALCULATOR, STEP_PROTONATE}
_CLAUSE_LABEL = {
    FILTER_NUMERIC: "Numeric range",
    FILTER_TEXT: "Text",
    FILTER_SUBSTRUCTURE: "Substructure",
}


def _fill_editable(combo: QComboBox, choices: list[str], current: str) -> None:
    """Replace *combo* items and show *current*, even when it is not one of *choices*."""
    combo.blockSignals(True)
    combo.clear()
    items: list[str] = []
    for choice in choices:
        text = str(choice).strip()
        if text and text not in items:
            items.append(text)
    if current and current not in items:
        items.insert(0, current)
    combo.addItems(items)
    combo.setEditText(current)
    combo.blockSignals(False)


def _clause_label(clause: dict[str, Any]) -> str:
    kind = str(clause.get("kind") or FILTER_NUMERIC)
    if kind == FILTER_TEXT:
        column = clause.get("column") or "?"
        return f'Text  {column}  "{clause.get("text") or ""}"'
    if kind == FILTER_SUBSTRUCTURE:
        return f"Substructure  {clause.get('smarts') or ''}"
    return f"Range  {clause.get('column') or '?'}  {clause.get('min')}–{clause.get('max')}"


class _ReactantFields(QGroupBox):
    """One reactant pool: pasted SMILES or a structure file."""

    def __init__(self, title: str) -> None:
        super().__init__(title)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        self._mode = QComboBox()
        self._mode.addItem("SMILES", "smiles")
        self._mode.addItem("File", "file")
        layout.addWidget(self._mode)
        self._smiles = QPlainTextEdit()
        self._smiles.setPlaceholderText("One SMILES per line")
        self._smiles.setFixedHeight(72)
        layout.addWidget(self._smiles)
        path_row = QHBoxLayout()
        self._path = QLineEdit()
        self._path.setPlaceholderText("SDF, SMILES, or CSV")
        self._browse = QPushButton("Browse…")
        self._browse.clicked.connect(self._browse_file)
        path_row.addWidget(self._path, 1)
        path_row.addWidget(self._browse)
        layout.addLayout(path_row)
        self._mode.currentIndexChanged.connect(lambda _index: self._sync_mode())
        self._sync_mode()

    def load(self, mode: str, value: str) -> None:
        chosen = mode if mode in ("smiles", "file") else "smiles"
        index = self._mode.findData(chosen)
        self._mode.setCurrentIndex(index if index >= 0 else 0)
        if chosen == "file":
            self._path.setText(value)
            self._smiles.setPlainText("")
        else:
            self._smiles.setPlainText(value)
            self._path.clear()
        self._sync_mode()

    def read(self) -> tuple[str, str]:
        mode = str(self._mode.currentData() or "smiles")
        if mode == "file":
            return mode, self._path.text().strip()
        return mode, self._smiles.toPlainText().strip()

    def _sync_mode(self) -> None:
        file_mode = self._mode.currentData() == "file"
        self._smiles.setVisible(not file_mode)
        self._path.setVisible(file_mode)
        self._browse.setVisible(file_mode)

    def _browse_file(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Reactant file",
            self._path.text(),
            "Structures (*.sdf *.sd *.smi *.smiles *.txt *.csv);;All files (*.*)",
        )
        if path:
            self._path.setText(path)


class _StepEditor(QWidget):
    """Fields for the selected step. The parent commits them into the recipe document."""

    def __init__(self) -> None:
        super().__init__()
        self._loading = False
        self._clauses: list[dict[str, Any]] = []
        self._clause_index = -1
        self._presets_ready = False
        self._preset_by_id: dict[str, Any] = {}
        self._desc_ready = False
        self._refs: list[str] = []
        self._sources: list[str] = ["Structure"]
        self._columns: list[str] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._step_id = QLineEdit()
        self._step_id.setPlaceholderText("desc1")
        form.addRow("Step id:", self._step_id)
        self._scope = QComboBox()
        for key, label in ROW_SCOPE_LABELS.items():
            self._scope.addItem(label, key)
        self._scope_label = QLabel("Rows:")
        form.addRow(self._scope_label, self._scope)
        root.addLayout(form)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_descriptors())
        self._stack.addWidget(self._build_calculator())
        self._stack.addWidget(self._build_protonate())
        self._stack.addWidget(self._build_filter())
        self._stack.addWidget(self._build_reaction())
        root.addWidget(self._stack, 1)

    def load(
        self,
        step: dict[str, Any],
        *,
        refs: list[str],
        structure_sources: list[str],
        columns: list[str],
    ) -> None:
        """Show *step*. *refs* are ``${id.key}`` tokens from earlier steps."""
        self._loading = True
        kind = str(step.get("kind") or STEP_DESCRIPTORS)
        params = step.get("params") if isinstance(step.get("params"), dict) else {}
        self._step_id.setText(str(step.get("id") or ""))
        scope = str(params.get("row_scope") or "table")
        scope_index = self._scope.findData(scope)
        self._scope.setCurrentIndex(scope_index if scope_index >= 0 else 0)
        self._scope.setVisible(kind in _SCOPED)
        self._scope_label.setVisible(kind in _SCOPED)
        self._stack.setCurrentIndex(_PAGE.get(kind, 0))
        self._refs = list(refs)
        self._sources = list(structure_sources) or ["Structure"]
        self._columns = list(columns)
        if kind == STEP_DESCRIPTORS:
            self._load_descriptors(params)
        elif kind == STEP_CALCULATOR:
            self._load_calculator(params)
        elif kind == STEP_PROTONATE:
            self._load_protonate(params)
        elif kind == STEP_FILTER:
            self._load_filter(params)
        elif kind == STEP_REACTION:
            self._load_reaction(params)
        self._loading = False

    def read_into(self, step: dict[str, Any]) -> None:
        """Copy the visible fields back onto *step*."""
        if self._loading:
            return
        kind = str(step.get("kind") or "")
        typed = self._step_id.text().strip()
        if typed:
            step["id"] = typed
        params = dict(step.get("params") or {})
        if kind in _SCOPED:
            params["row_scope"] = str(self._scope.currentData() or "table")
        if kind == STEP_DESCRIPTORS:
            params["structure_source"] = self._desc_source.currentText().strip() or "Structure"
            params["descriptors"] = self._checked_descriptors()
        elif kind == STEP_CALCULATOR:
            params["column"] = self._calc_column.text().strip()
            params["expression"] = self._calc_expr.text().strip()
        elif kind == STEP_PROTONATE:
            params["structure_source"] = self._prot_source.currentText().strip() or "Structure"
            params["ph"] = float(self._prot_ph.value())
            params["output_column"] = self._prot_column.text().strip()
            params["render_2d"] = self._prot_render.isChecked()
        elif kind == STEP_FILTER:
            self._store_clause()
            params["replace"] = self._filter_replace.isChecked()
            params["clauses"] = [dict(clause) for clause in self._clauses]
        elif kind == STEP_REACTION:
            params.update(self._read_reaction(params))
        step["params"] = params

    def _build_descriptors(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._desc_source = QComboBox()
        self._desc_source.setEditable(True)
        layout.addWidget(self._desc_source)
        self._desc_search = QLineEdit()
        self._desc_search.setPlaceholderText("Filter descriptors")
        self._desc_search.textChanged.connect(self._filter_descriptors)
        layout.addWidget(self._desc_search)
        self._desc_list = QListWidget()
        self._desc_list.setMinimumHeight(140)
        layout.addWidget(self._desc_list, 1)
        return page

    def _build_calculator(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._calc_column = QLineEdit()
        form.addRow("Column:", self._calc_column)
        self._calc_expr = QLineEdit()
        self._calc_expr.setPlaceholderText("[MolWt] / 100")
        form.addRow("Expression:", self._calc_expr)
        self._calc_insert = QComboBox()
        self._calc_insert.activated.connect(self._insert_calculator_token)
        form.addRow("Insert:", self._calc_insert)
        return page

    def _build_protonate(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._prot_source = QComboBox()
        self._prot_source.setEditable(True)
        form.addRow("Structure:", self._prot_source)
        self._prot_ph = QDoubleSpinBox()
        self._prot_ph.setRange(0.0, 14.0)
        self._prot_ph.setDecimals(2)
        self._prot_ph.setSingleStep(0.1)
        form.addRow("pH:", self._prot_ph)
        self._prot_column = QLineEdit()
        form.addRow("Output column:", self._prot_column)
        self._prot_render = QCheckBox("Render 2D in the output column")
        self._prot_render.setToolTip(
            "Depictions are drawn in the background after the column is written. "
            "The next macro step does not wait for them."
        )
        form.addRow("", self._prot_render)
        return page

    def _build_filter(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._filter_replace = QCheckBox("Replace the current filter panel")
        self._filter_replace.setToolTip(
            "Checked replaces every filter card. Unchecked adds these cards beside them."
        )
        layout.addWidget(self._filter_replace)
        row = QHBoxLayout()
        self._clause_list = QListWidget()
        self._clause_list.setMaximumHeight(110)
        self._clause_list.currentRowChanged.connect(self._on_clause_row)
        row.addWidget(self._clause_list, 1)
        buttons = QVBoxLayout()
        add_clause = QPushButton("Add")
        remove_clause = QPushButton("Remove")
        add_clause.clicked.connect(self._add_clause)
        remove_clause.clicked.connect(self._remove_clause)
        buttons.addWidget(add_clause)
        buttons.addWidget(remove_clause)
        buttons.addStretch(1)
        row.addLayout(buttons)
        layout.addLayout(row)
        self._clause_kind = QComboBox()
        for kind in FILTER_KINDS:
            self._clause_kind.addItem(_CLAUSE_LABEL[kind], kind)
        self._clause_kind.currentIndexChanged.connect(lambda _index: self._sync_clause_kind())
        layout.addWidget(self._clause_kind)
        self._clause_stack = QStackedWidget()
        self._clause_stack.addWidget(self._build_numeric_clause())
        self._clause_stack.addWidget(self._build_text_clause())
        self._clause_stack.addWidget(self._build_substructure_clause())
        layout.addWidget(self._clause_stack)
        self._clause_invert = QCheckBox("Invert")
        layout.addWidget(self._clause_invert)
        return page

    def _build_numeric_clause(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._num_column = QComboBox()
        self._num_column.setEditable(True)
        self._num_min = QDoubleSpinBox()
        self._num_max = QDoubleSpinBox()
        for spin in (self._num_min, self._num_max):
            spin.setRange(-1.0e12, 1.0e12)
            spin.setDecimals(4)
        form.addRow("Column:", self._num_column)
        form.addRow("Min:", self._num_min)
        form.addRow("Max:", self._num_max)
        return page

    def _build_text_clause(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._text_column = QComboBox()
        self._text_column.setEditable(True)
        self._text_value = QLineEdit()
        self._text_partial = QCheckBox("Partial match")
        self._text_case = QCheckBox("Case sensitive")
        form.addRow("Column:", self._text_column)
        form.addRow("Text:", self._text_value)
        form.addRow("", self._text_partial)
        form.addRow("", self._text_case)
        return page

    def _build_substructure_clause(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(0, 0, 0, 0)
        self._ss_source = QComboBox()
        self._ss_source.setEditable(True)
        self._ss_smarts = QLineEdit()
        form.addRow("Structure:", self._ss_source)
        form.addRow("SMARTS:", self._ss_smarts)
        return page

    def _build_reaction(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self._preset = QComboBox()
        self._preset.activated.connect(self._apply_preset)
        form.addRow("Preset:", self._preset)
        self._rxn_name = QLineEdit()
        form.addRow("Name:", self._rxn_name)
        self._smarts = QLineEdit()
        form.addRow("SMARTS:", self._smarts)
        self._max_products = QSpinBox()
        self._max_products.setRange(1, clamp_max_products_ui(1_000_000_000))
        form.addRow("Max products:", self._max_products)
        layout.addLayout(form)
        self._reactant1 = _ReactantFields("Reactant 1")
        self._reactant2 = _ReactantFields("Reactant 2")
        layout.addWidget(self._reactant1)
        layout.addWidget(self._reactant2)
        self._add_to_table = QCheckBox("Add products to the table")
        self._save_to_file = QCheckBox("Save products to a file")
        self._save_path = QLineEdit()
        self._save_path.setPlaceholderText("SDF path")
        layout.addWidget(self._add_to_table)
        layout.addWidget(self._save_to_file)
        layout.addWidget(self._save_path)
        layout.addStretch(1)
        return page

    def _ensure_descriptors(self) -> None:
        if self._desc_ready:
            return
        for tab, items in descriptor_tabs():
            for display, key in items:
                item = QListWidgetItem(f"{tab} — {display}")
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Unchecked)
                item.setData(Qt.UserRole, str(key))
                self._desc_list.addItem(item)
        self._desc_ready = True

    def _load_descriptors(self, params: dict[str, Any]) -> None:
        self._ensure_descriptors()
        _fill_editable(
            self._desc_source,
            list(self._sources) + list(self._refs),
            str(params.get("structure_source") or "Structure"),
        )
        wanted = {str(key) for key in params.get("descriptors") or []}
        for index in range(self._desc_list.count()):
            item = self._desc_list.item(index)
            key = str(item.data(Qt.UserRole) or "")
            item.setCheckState(Qt.Checked if key in wanted else Qt.Unchecked)
        self._filter_descriptors(self._desc_search.text())

    def _checked_descriptors(self) -> list[str]:
        self._ensure_descriptors()
        keys: list[str] = []
        for index in range(self._desc_list.count()):
            item = self._desc_list.item(index)
            if item.checkState() == Qt.Checked:
                key = str(item.data(Qt.UserRole) or "")
                if key:
                    keys.append(key)
        return keys

    def _filter_descriptors(self, text: str) -> None:
        needle = text.strip().lower()
        for index in range(self._desc_list.count()):
            item = self._desc_list.item(index)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def _load_calculator(self, params: dict[str, Any]) -> None:
        self._calc_column.setText(str(params.get("column") or ""))
        self._calc_expr.setText(str(params.get("expression") or ""))
        self._calc_insert.blockSignals(True)
        self._calc_insert.clear()
        self._calc_insert.addItem("Insert a column…", "")
        for name in self._columns:
            if name:
                self._calc_insert.addItem(name, f"[{name}]")
        for ref in self._refs:
            self._calc_insert.addItem(ref, ref)
        self._calc_insert.blockSignals(False)

    def _insert_calculator_token(self, index: int) -> None:
        token = str(self._calc_insert.itemData(index) or "")
        if token:
            self._calc_expr.insert(token)

    def _load_protonate(self, params: dict[str, Any]) -> None:
        _fill_editable(
            self._prot_source,
            list(self._sources) + list(self._refs),
            str(params.get("structure_source") or "Structure"),
        )
        try:
            ph = float(params.get("ph", 7.4))
        except (TypeError, ValueError):
            ph = 7.4
        self._prot_ph.setValue(ph)
        self._prot_column.setText(str(params.get("output_column") or "Protonated"))
        self._prot_render.setChecked(bool(params.get("render_2d", False)))

    def _load_filter(self, params: dict[str, Any]) -> None:
        self._filter_replace.setChecked(bool(params.get("replace", True)))
        raw = params.get("clauses") if isinstance(params.get("clauses"), list) else []
        self._clauses = [dict(clause) for clause in raw if isinstance(clause, dict)]
        self._clause_list.blockSignals(True)
        self._clause_list.clear()
        for clause in self._clauses:
            self._clause_list.addItem(_clause_label(clause))
        self._clause_index = 0 if self._clauses else -1
        if self._clauses:
            self._clause_list.setCurrentRow(0)
            self._load_clause(0)
        self._clause_list.blockSignals(False)

    def _on_clause_row(self, row: int) -> None:
        if self._loading:
            return
        self._store_clause()
        self._clause_index = row
        self._load_clause(row)

    def _add_clause(self) -> None:
        if self._loading:
            return
        self._store_clause()
        clause = {
            "kind": FILTER_NUMERIC,
            "column": "MolWt",
            "min": 0,
            "max": 500,
            "inverted": False,
        }
        self._clauses.append(clause)
        self._clause_list.addItem(_clause_label(clause))
        self._clause_list.setCurrentRow(len(self._clauses) - 1)

    def _remove_clause(self) -> None:
        row = self._clause_list.currentRow()
        if row < 0 or row >= len(self._clauses):
            return
        self._loading = True
        del self._clauses[row]
        self._clause_list.takeItem(row)
        self._clause_index = -1
        self._loading = False
        if self._clauses:
            self._clause_list.setCurrentRow(min(row, len(self._clauses) - 1))
        else:
            self._clause_index = -1

    def _sync_clause_kind(self) -> None:
        kind = str(self._clause_kind.currentData() or FILTER_NUMERIC)
        self._clause_stack.setCurrentIndex(FILTER_KINDS.index(kind) if kind in FILTER_KINDS else 0)

    def _load_clause(self, row: int) -> None:
        if row < 0 or row >= len(self._clauses):
            return
        clause = self._clauses[row]
        kind = str(clause.get("kind") or FILTER_NUMERIC)
        if kind not in FILTER_KINDS:
            kind = FILTER_NUMERIC
        kind_index = self._clause_kind.findData(kind)
        self._clause_kind.setCurrentIndex(kind_index if kind_index >= 0 else 0)
        self._sync_clause_kind()
        choices = list(self._columns) + list(self._refs)
        _fill_editable(self._num_column, choices, str(clause.get("column") or ""))
        _fill_editable(self._text_column, choices, str(clause.get("column") or ""))
        _fill_editable(
            self._ss_source,
            list(self._sources) + list(self._refs),
            str(clause.get("structure_source") or "Structure"),
        )
        self._num_min.setValue(float(clause.get("min") or 0))
        self._num_max.setValue(float(clause.get("max") or 0))
        self._text_value.setText(str(clause.get("text") or ""))
        self._text_partial.setChecked(bool(clause.get("partial_match", True)))
        self._text_case.setChecked(bool(clause.get("case_sensitive", False)))
        self._ss_smarts.setText(str(clause.get("smarts") or ""))
        self._clause_invert.setChecked(bool(clause.get("inverted", False)))

    def _store_clause(self) -> None:
        if self._loading or not 0 <= self._clause_index < len(self._clauses):
            return
        kind = str(self._clause_kind.currentData() or FILTER_NUMERIC)
        clause: dict[str, Any] = {"kind": kind, "inverted": self._clause_invert.isChecked()}
        if kind == FILTER_TEXT:
            clause["column"] = self._text_column.currentText().strip()
            clause["text"] = self._text_value.text()
            clause["partial_match"] = self._text_partial.isChecked()
            clause["case_sensitive"] = self._text_case.isChecked()
        elif kind == FILTER_SUBSTRUCTURE:
            clause["structure_source"] = self._ss_source.currentText().strip() or "Structure"
            clause["smarts"] = self._ss_smarts.text().strip()
        else:
            clause["column"] = self._num_column.currentText().strip()
            clause["min"] = float(self._num_min.value())
            clause["max"] = float(self._num_max.value())
        self._clauses[self._clause_index] = clause
        item = self._clause_list.item(self._clause_index)
        if item is not None:
            item.setText(_clause_label(clause))

    def _ensure_presets(self) -> None:
        if self._presets_ready:
            return
        from ...chem.reaction_enumeration import load_reaction_presets

        self._preset.blockSignals(True)
        self._preset.clear()
        self._preset.addItem("Custom", "")
        self._preset_by_id = {}
        for preset in load_reaction_presets():
            self._preset.addItem(preset.name, preset.id)
            self._preset_by_id[str(preset.id)] = preset
        self._preset.blockSignals(False)
        self._presets_ready = True

    def _load_reaction(self, params: dict[str, Any]) -> None:
        self._ensure_presets()
        smarts = str(params.get("smarts") or "")
        self._rxn_name.setText(str(params.get("reaction_name") or ""))
        self._smarts.setText(smarts)
        self._select_preset(smarts)
        try:
            products = int(params.get("max_products") or 100)
        except (TypeError, ValueError):
            products = 100
        self._max_products.setValue(max(1, products))
        self._reactant1.load(
            str(params.get("reactant_1_mode") or "smiles"),
            str(params.get("reactant_1") or ""),
        )
        self._reactant2.load(
            str(params.get("reactant_2_mode") or "smiles"),
            str(params.get("reactant_2") or ""),
        )
        self._add_to_table.setChecked(bool(params.get("add_to_table", True)))
        self._save_to_file.setChecked(bool(params.get("save_to_file", False)))
        self._save_path.setText(str(params.get("save_path") or ""))

    def _select_preset(self, smarts: str) -> None:
        matched = 0
        text = smarts.strip()
        if text:
            for index in range(self._preset.count()):
                preset = self._preset_by_id.get(str(self._preset.itemData(index) or ""))
                if preset is not None and str(preset.smarts).strip() == text:
                    matched = index
                    break
        self._preset.blockSignals(True)
        self._preset.setCurrentIndex(matched)
        self._preset.blockSignals(False)

    def _apply_preset(self, index: int) -> None:
        if self._loading:
            return
        preset = self._preset_by_id.get(str(self._preset.itemData(index) or ""))
        if preset is None or not str(preset.smarts).strip():
            return
        self._smarts.setText(str(preset.smarts))
        self._rxn_name.setText(str(preset.name))

    def _read_reaction(self, previous: dict[str, Any]) -> dict[str, Any]:
        mode1, value1 = self._reactant1.read()
        mode2, value2 = self._reactant2.read()
        filters = previous.get("output_filters", "")
        return {
            "reaction_name": self._rxn_name.text().strip(),
            "smarts": self._smarts.text().strip(),
            "reactant_1_mode": mode1,
            "reactant_1": value1,
            "reactant_2_mode": mode2,
            "reactant_2": value2,
            "max_products": int(self._max_products.value()),
            "output_filters": filters if isinstance(filters, str) else "",
            "add_to_table": self._add_to_table.isChecked(),
            "save_to_file": self._save_to_file.isChecked(),
            "save_path": self._save_path.text().strip(),
        }


class MacroDialog(QDialog):
    """Library of recipes on the left, the selected recipe's steps on the right."""

    def __init__(
        self,
        app: Any = None,
        *,
        library: list[MacroRecipe] | None = None,
        persist: bool = True,
    ) -> None:
        parent = app if isinstance(app, QWidget) else None
        super().__init__(parent)
        self._app = app
        self._persist = persist
        self._loading = False
        self._macro_index = -1
        self._step_index = -1
        source = library if library is not None else (load_macro_library() if persist else [])
        self._docs: list[dict[str, Any]] = [recipe_to_json(recipe) for recipe in source]
        self.setWindowTitle(TOOL_MACROS)
        self.resize(960, 680)
        self._runner = MacroRunner(app, self)
        self._runner.progressed.connect(self._on_progress)
        self._runner.finished.connect(self._on_runner_finished)
        self._build()
        make_window_resizable(self)
        if self._docs:
            self._macro_index = 0
            self._step_index = 0 if self._docs[0]["steps"] else -1
        self._reload_macro_list()
        self._show_macro()

    def edited_library(self) -> list[MacroRecipe]:
        """The recipes currently in the editor, including uncommitted field edits."""
        self._commit_macro(self._macro_index)
        return [recipe_from_json(doc) for doc in self._docs]

    def add_macro(self) -> None:
        """Append an empty recipe and select it."""
        self._commit_macro(self._macro_index)
        self._docs.append(recipe_to_json(new_recipe(self._next_macro_name())))
        self._macro_index = len(self._docs) - 1
        self._step_index = -1
        self._reload_macro_list()
        self._show_macro()

    def add_step(self, kind: str) -> None:
        """Append a default step of *kind* to the selected macro."""
        if self._macro_index < 0:
            self.add_macro()
        self._commit_step()
        doc = self._docs[self._macro_index]
        existing = {str(step.get("id") or "") for step in doc["steps"]}
        doc["steps"].append(step_to_json(default_step(kind, existing)))
        self._step_index = len(doc["steps"]) - 1
        self._reload_steps()
        self._show_step()

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        with suppress(MacroDocumentError):
            self._save_if_persistent()
        if self._runner.is_running:
            self._runner.cancel()
        super().closeEvent(event)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        splitter = QSplitter()
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Macros"))
        self._macro_list = QListWidget()
        self._macro_list.currentRowChanged.connect(self._on_macro_row)
        left_layout.addWidget(self._macro_list, 1)
        left_buttons = QHBoxLayout()
        self._new_btn = QPushButton("New")
        self._dup_btn = QPushButton("Duplicate")
        self._del_btn = QPushButton("Delete")
        self._new_btn.clicked.connect(self.add_macro)
        self._dup_btn.clicked.connect(self._duplicate_macro)
        self._del_btn.clicked.connect(self._delete_macro)
        left_buttons.addWidget(self._new_btn)
        left_buttons.addWidget(self._dup_btn)
        left_buttons.addWidget(self._del_btn)
        left_layout.addLayout(left_buttons)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self._name = QLineEdit()
        self._name.setPlaceholderText("Macro name")
        self._name.editingFinished.connect(self._on_name_edited)
        right_layout.addWidget(self._name)
        step_row = QHBoxLayout()
        self._step_list = QListWidget()
        self._step_list.setMaximumHeight(150)
        self._step_list.currentRowChanged.connect(self._on_step_row)
        step_row.addWidget(self._step_list, 1)
        step_buttons = QVBoxLayout()
        self._add_btn = QPushButton("Add step")
        menu = QMenu(self._add_btn)
        for kind in STEP_KINDS:
            menu.addAction(STEP_LABELS[kind], lambda _checked=False, k=kind: self.add_step(k))
        self._add_btn.setMenu(menu)
        self._remove_step_btn = QPushButton("Remove")
        self._up_btn = QPushButton("Up")
        self._down_btn = QPushButton("Down")
        self._remove_step_btn.clicked.connect(self._remove_step)
        self._up_btn.clicked.connect(lambda: self._move_step(-1))
        self._down_btn.clicked.connect(lambda: self._move_step(1))
        for button in (self._add_btn, self._remove_step_btn, self._up_btn, self._down_btn):
            step_buttons.addWidget(button)
        step_buttons.addStretch(1)
        step_row.addLayout(step_buttons)
        right_layout.addLayout(step_row)
        self._editor = _StepEditor()
        right_layout.addWidget(self._editor, 1)
        hint = QLabel(
            "A later step can use a column this step writes: ${stepId.key}. "
            "Descriptor keys are the internal names (MolWt, not Mol Weight). "
            "Calculator writes ${stepId.output}. Protonate writes output, percent, and pka."
        )
        hint.setWordWrap(True)
        right_layout.addWidget(hint)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 1)
        root.addWidget(splitter, 1)

        self._status = QLabel("Choose a macro or create one.")
        self._status.setWordWrap(True)
        root.addWidget(self._status)
        actions = QHBoxLayout()
        self._save_btn = QPushButton("Save")
        self._run_btn = QPushButton("Run")
        self._stop_btn = QPushButton("Stop")
        self._close_btn = QPushButton("Close")
        self._stop_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._save_clicked)
        self._run_btn.clicked.connect(self._run)
        self._stop_btn.clicked.connect(self._runner.cancel)
        self._close_btn.clicked.connect(self.close)
        actions.addWidget(self._save_btn)
        actions.addWidget(self._run_btn)
        actions.addWidget(self._stop_btn)
        actions.addStretch(1)
        actions.addWidget(self._close_btn)
        root.addLayout(actions)
        self._idle_buttons = (
            self._new_btn,
            self._dup_btn,
            self._del_btn,
            self._add_btn,
            self._remove_step_btn,
            self._up_btn,
            self._down_btn,
        )

    def _reload_macro_list(self) -> None:
        self._macro_list.blockSignals(True)
        self._macro_list.clear()
        for doc in self._docs:
            self._macro_list.addItem(str(doc.get("name") or "Macro"))
        if 0 <= self._macro_index < self._macro_list.count():
            self._macro_list.setCurrentRow(self._macro_index)
        self._macro_list.blockSignals(False)

    def _reload_steps(self) -> None:
        self._step_list.blockSignals(True)
        self._step_list.clear()
        if 0 <= self._macro_index < len(self._docs):
            for step in self._docs[self._macro_index]["steps"]:
                kind = str(step.get("kind") or "")
                label = STEP_LABELS.get(kind, kind)
                self._step_list.addItem(f"{step.get('id')}  {label}")
        if 0 <= self._step_index < self._step_list.count():
            self._step_list.setCurrentRow(self._step_index)
        self._step_list.blockSignals(False)

    def _show_macro(self) -> None:
        if self._macro_index < 0 or self._macro_index >= len(self._docs):
            self._macro_index = -1
            self._step_index = -1
            self._name.clear()
            self._name.setEnabled(False)
            self._step_list.clear()
            self._editor.setEnabled(False)
            return
        doc = self._docs[self._macro_index]
        self._name.setEnabled(True)
        self._loading = True
        self._name.setText(str(doc.get("name") or ""))
        self._loading = False
        if not doc["steps"]:
            self._step_index = -1
        elif self._step_index < 0 or self._step_index >= len(doc["steps"]):
            self._step_index = 0
        self._reload_steps()
        self._show_step()

    def _show_step(self) -> None:
        if self._macro_index < 0:
            self._editor.setEnabled(False)
            return
        steps = self._docs[self._macro_index]["steps"]
        if not 0 <= self._step_index < len(steps):
            self._step_index = -1
            self._editor.setEnabled(False)
            return
        self._editor.setEnabled(True)
        self._editor.load(
            steps[self._step_index],
            refs=self._ref_tokens(),
            structure_sources=self._structure_sources(),
            columns=self._column_names(),
        )

    def _commit_macro(self, index: int) -> None:
        if index < 0 or index >= len(self._docs) or self._runner.is_running:
            return
        name = self._name.text().strip()
        if name:
            self._docs[index]["name"] = name
            item = self._macro_list.item(index)
            if item is not None:
                item.setText(name)
        if index == self._macro_index:
            self._commit_step()

    def _commit_step(self) -> None:
        if self._runner.is_running or self._macro_index < 0 or self._step_index < 0:
            return
        steps = self._docs[self._macro_index]["steps"]
        if self._step_index >= len(steps):
            return
        if not self._editor.isEnabled():
            return
        self._editor.read_into(steps[self._step_index])
        item = self._step_list.item(self._step_index)
        if item is not None:
            step = steps[self._step_index]
            kind = str(step.get("kind") or "")
            item.setText(f"{step.get('id')}  {STEP_LABELS.get(kind, kind)}")

    def _on_macro_row(self, row: int) -> None:
        if self._loading or row == self._macro_index:
            return
        self._commit_macro(self._macro_index)
        self._macro_index = row
        self._step_index = 0
        self._show_macro()

    def _on_step_row(self, row: int) -> None:
        if self._loading or row == self._step_index:
            return
        self._commit_step()
        self._step_index = row
        self._show_step()

    def _on_name_edited(self) -> None:
        if self._loading:
            return
        self._commit_macro(self._macro_index)

    def _duplicate_macro(self) -> None:
        if self._macro_index < 0:
            return
        self._commit_macro(self._macro_index)
        copied = json.loads(json.dumps(self._docs[self._macro_index]))
        copied["id"] = new_recipe_id()
        copied["name"] = f"{copied.get('name') or 'Macro'} copy"
        self._docs.append(copied)
        self._macro_index = len(self._docs) - 1
        self._step_index = 0 if copied["steps"] else -1
        self._reload_macro_list()
        self._show_macro()

    def _delete_macro(self) -> None:
        if self._macro_index < 0:
            return
        name = str(self._docs[self._macro_index].get("name") or "this macro")
        answer = QMessageBox.question(self, TOOL_MACROS, f'Delete "{name}"?')
        if answer != QMessageBox.Yes:
            return
        del self._docs[self._macro_index]
        if self._docs:
            self._macro_index = min(self._macro_index, len(self._docs) - 1)
            self._step_index = 0
        else:
            self._macro_index = -1
            self._step_index = -1
        self._reload_macro_list()
        self._show_macro()

    def _remove_step(self) -> None:
        if self._macro_index < 0 or self._step_index < 0:
            return
        steps = self._docs[self._macro_index]["steps"]
        if self._step_index >= len(steps):
            return
        del steps[self._step_index]
        if steps:
            self._step_index = min(self._step_index, len(steps) - 1)
        else:
            self._step_index = -1
        self._reload_steps()
        self._show_step()

    def _move_step(self, delta: int) -> None:
        if self._macro_index < 0 or self._step_index < 0:
            return
        self._commit_step()
        steps = self._docs[self._macro_index]["steps"]
        target = self._step_index + delta
        if not 0 <= target < len(steps):
            return
        steps[self._step_index], steps[target] = steps[target], steps[self._step_index]
        self._step_index = target
        self._reload_steps()
        self._show_step()

    def _ref_tokens(self) -> list[str]:
        if self._macro_index < 0:
            return []
        tokens: list[str] = []
        steps = self._docs[self._macro_index]["steps"]
        for step in steps[: max(self._step_index, 0)]:
            params = step.get("params") if isinstance(step.get("params"), dict) else {}
            for key in output_keys(str(step.get("kind") or ""), params):
                tokens.append(f"${{{step.get('id')}.{key}}}")
        return tokens

    def _structure_sources(self) -> list[str]:
        getter = getattr(self._app, "chemistry_tool_structure_sources", None)
        if callable(getter):
            sources = [str(source) for source in (getter() or []) if source]
            if sources:
                return sources
        return ["Structure"]

    def _column_names(self) -> list[str]:
        headers = [str(header) for header in (getattr(self._app, "headers", None) or []) if header]
        bounds = getattr(self._app, "global_bounds", None)
        if isinstance(bounds, dict):
            for name in bounds:
                if name and str(name) not in headers:
                    headers.append(str(name))
        return headers

    def _next_macro_name(self) -> str:
        names = {str(doc.get("name") or "") for doc in self._docs}
        number = 1
        while f"Macro {number}" in names:
            number += 1
        return f"Macro {number}"

    def _save_clicked(self) -> None:
        if not self._persist:
            return
        try:
            self._save_if_persistent()
        except MacroDocumentError as exc:
            QMessageBox.warning(self, TOOL_MACROS, str(exc))
            return
        self._status.setText("Macros saved.")

    def _save_if_persistent(self) -> None:
        if not self._persist:
            return
        save_macro_library(self.edited_library())

    def _run(self) -> None:
        if self._runner.is_running or self._macro_index < 0:
            return
        try:
            recipes = self.edited_library()
        except MacroDocumentError as exc:
            QMessageBox.warning(self, TOOL_MACROS, str(exc))
            return
        recipe = recipes[self._macro_index]
        issues = validate_recipe(recipe)
        if issues:
            QMessageBox.warning(self, TOOL_MACROS, format_issues(issues))
            return
        if self._persist:
            save_macro_library(recipes)
        self._set_busy(True)
        self._runner.start(recipe)

    def _on_progress(self, message: str) -> None:
        self._status.setText(message)

    def _on_runner_finished(self, ok: bool, message: str) -> None:
        self._set_busy(False)
        self._status.setText(message)
        if not ok and message != "Cancelled.":
            QMessageBox.warning(self, TOOL_MACROS, message)

    def _set_busy(self, busy: bool) -> None:
        self._run_btn.setEnabled(not busy)
        self._save_btn.setEnabled(not busy)
        self._stop_btn.setEnabled(busy)
        self._macro_list.setEnabled(not busy)
        self._step_list.setEnabled(not busy)
        self._name.setEnabled(not busy and self._macro_index >= 0)
        self._editor.setEnabled(not busy and self._step_index >= 0)
        for button in self._idle_buttons:
            button.setEnabled(not busy)
