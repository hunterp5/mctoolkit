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

"""MPO Scoring dialog — desirability functions over numeric columns (Data menu)."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ...analysis.mpo_scoring import (
    CombineMethod,
    DesirabilityDirection,
    DesirabilityKind,
    DesirabilitySpec,
)
from ..qt_widget_utils import boxed_form, make_window_minimizable
from .scope import selection_scope_checked

if TYPE_CHECKING:
    from ..main_window import ChemistryWorkspaceWindow

_KIND_LABELS: tuple[tuple[str, DesirabilityKind], ...] = (
    ("Linear", "linear"),
    ("Gaussian", "gaussian"),
    ("Step", "step"),
)
_DIR_LABELS: tuple[tuple[str, DesirabilityDirection], ...] = (
    ("Maximize (higher better)", "maximize"),
    ("Minimize (lower better)", "minimize"),
    ("Target / range", "target"),
)
_COMBINE_LABELS: tuple[tuple[str, CombineMethod], ...] = (
    ("Arithmetic mean", "arithmetic"),
    ("Geometric mean", "geometric"),
)


def _numeric_columns_and_bounds(
    parent: ChemistryWorkspaceWindow | None,
) -> tuple[list[str], dict[str, tuple[float, float]]]:
    """Sorted numeric headers and (min, max) from the window's global_bounds."""
    bounds = getattr(parent, "global_bounds", None) or {}
    columns = sorted(str(k) for k in bounds.keys())
    parsed: dict[str, tuple[float, float]] = {}
    for k, meta in bounds.items():
        lo, hi = 0.0, 1.0
        if isinstance(meta, dict):
            try:
                lo = float(meta.get("min", 0.0))
            except (TypeError, ValueError):
                lo = 0.0
            try:
                hi = float(meta.get("max", 1.0))
            except (TypeError, ValueError):
                hi = 1.0
        elif isinstance(meta, (tuple, list)) and len(meta) >= 2:
            try:
                lo = float(meta[0])
                hi = float(meta[1])
            except (TypeError, ValueError):
                lo, hi = 0.0, 1.0
        if not (hi > lo):
            hi = lo + 1.0
        parsed[str(k)] = (lo, hi)
    return columns, parsed


@dataclass
class _CriterionDraft:
    column: str
    kind: DesirabilityKind = "linear"
    direction: DesirabilityDirection = "maximize"
    weight: float = 1.0
    low: float = 0.0
    high: float = 1.0
    target: float = 0.5
    center: float = 0.0
    sigma: float = 1.0

    def to_spec(self) -> DesirabilitySpec:
        return DesirabilitySpec(
            column=self.column,
            kind=self.kind,
            direction=self.direction,
            weight=float(self.weight),
            low=float(self.low),
            high=float(self.high),
            target=float(self.target),
            center=float(self.center),
            sigma=float(self.sigma),
        )

    def summary(self) -> str:
        if self.kind == "gaussian":
            return f"center={self.center:g}, σ={self.sigma:g}, w={self.weight:g}"
        if self.kind == "step":
            if self.direction == "maximize":
                return f"≥ {self.high:g}, w={self.weight:g}"
            if self.direction == "minimize":
                return f"≤ {self.low:g}, w={self.weight:g}"
            return f"[{self.low:g}, {self.high:g}], w={self.weight:g}"
        # linear
        if self.direction == "target":
            return f"[{self.low:g}…{self.target:g}…{self.high:g}], w={self.weight:g}"
        if self.direction == "minimize":
            return f"1@{self.low:g} → 0@{self.high:g}, w={self.weight:g}"
        return f"0@{self.low:g} → 1@{self.high:g}, w={self.weight:g}"


@dataclass(frozen=True)
class MPOScoringDialogParams:
    """Validated settings from :class:`MPOScoringDialog`."""

    output_column: str
    specs: tuple[DesirabilitySpec, ...]
    combine: CombineMethod
    write_individual: bool
    decimals: int


class MPOScoringDialog(QDialog):
    """Configure per-property desirabilities and write an overall MPO score column."""

    def __init__(self, parent: ChemistryWorkspaceWindow | None = None):
        super().__init__(parent)
        self.parent_app = parent
        self._init_mpo_state(parent)
        self._build_mpo_ui()
        self._wire_mpo_ui()
        self._set_editor_enabled(False)
        if not self._numeric_columns:
            self.add_btn.setEnabled(False)
            self.prop_combo.setEnabled(False)

    def _init_mpo_state(self, parent: ChemistryWorkspaceWindow | None) -> None:
        self.setWindowTitle("MPO Scoring")
        self.setMinimumWidth(560)
        self.resize(620, 520)
        make_window_minimizable(self)
        n_sel = len(parent._selected_logical_rows()) if parent is not None else 0
        self._have_selection = n_sel > 0
        self._initial_selected_row_count = n_sel
        self._drafts: list[_CriterionDraft] = []
        self._updating = False
        self._numeric_columns, self._bounds = _numeric_columns_and_bounds(parent)

    def _build_mpo_ui(self) -> None:
        n_sel = self._initial_selected_row_count
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        output, top = boxed_form("Output")
        self.out_edit = QLineEdit("MPO_Score")
        self.out_edit.setToolTip("Overall desirability column written to the table.")
        top.addRow("Output column:", self.out_edit)

        self.combine_combo = QComboBox()
        for label, _key in _COMBINE_LABELS:
            self.combine_combo.addItem(label)
        self.combine_combo.setToolTip(
            "Arithmetic mean is a weighted average of desirabilities; "
            "geometric mean is the classic Derringer–Suich overall desirability."
        )
        top.addRow("Combine:", self.combine_combo)

        self.indiv_cb = QCheckBox("Also write per-property desirability columns")
        self.indiv_cb.setChecked(False)
        self.indiv_cb.setToolTip('Creates columns named like "MPO_d_<property>".')
        top.addRow(self.indiv_cb)

        self.decimals_sb = QSpinBox()
        self.decimals_sb.setRange(0, 8)
        self.decimals_sb.setValue(4)
        top.addRow("Decimals:", self.decimals_sb)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(f"{self._only_selected_scope_prefix} ({n_sel} row(s))")
        else:
            self.only_selected_cb.setEnabled(False)
        top.addRow("", self.only_selected_cb)
        root.addWidget(output)

        crit_box = QGroupBox("Property criteria")
        crit_lyt = QVBoxLayout(crit_box)
        row = QHBoxLayout()
        self.prop_combo = QComboBox()
        self.prop_combo.addItems(self._numeric_columns)
        self.prop_combo.setToolTip("Numeric table columns available for desirability scoring.")
        row.addWidget(self.prop_combo, 1)
        self.add_btn = QPushButton("Add")
        row.addWidget(self.add_btn)
        self.remove_btn = QPushButton("Remove")
        row.addWidget(self.remove_btn)
        crit_lyt.addLayout(row)

        self.list_w = QListWidget()
        crit_lyt.addWidget(self.list_w, 1)
        root.addWidget(crit_box, 1)

        edit_box = QGroupBox("Selected criterion")
        self.edit_form = QFormLayout(edit_box)

        self.kind_combo = QComboBox()
        for label, _k in _KIND_LABELS:
            self.kind_combo.addItem(label)
        self.edit_form.addRow("Function:", self.kind_combo)

        self.dir_combo = QComboBox()
        for label, _d in _DIR_LABELS:
            self.dir_combo.addItem(label)
        self.edit_form.addRow("Goal:", self.dir_combo)

        self.low_sb = QDoubleSpinBox()
        self.high_sb = QDoubleSpinBox()
        self.target_sb = QDoubleSpinBox()
        self.center_sb = QDoubleSpinBox()
        self.sigma_sb = QDoubleSpinBox()
        self.weight_sb = QDoubleSpinBox()
        for sb in (self.low_sb, self.high_sb, self.target_sb, self.center_sb):
            sb.setDecimals(6)
            sb.setRange(-1e12, 1e12)
        self.sigma_sb.setDecimals(6)
        self.sigma_sb.setRange(1e-12, 1e12)
        self.sigma_sb.setValue(1.0)
        self.weight_sb.setDecimals(4)
        self.weight_sb.setRange(0.0, 1e6)
        self.weight_sb.setValue(1.0)

        self._low_row = self.edit_form.rowCount()
        self.edit_form.addRow("Low:", self.low_sb)
        self.edit_form.addRow("High:", self.high_sb)
        self.edit_form.addRow("Target:", self.target_sb)
        self.edit_form.addRow("Center:", self.center_sb)
        self.edit_form.addRow("Sigma:", self.sigma_sb)
        self.edit_form.addRow("Weight:", self.weight_sb)

        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #444;")
        self.edit_form.addRow(self.hint)
        root.addWidget(edit_box)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        root.addWidget(self._button_box)

    def _wire_mpo_ui(self) -> None:
        self.add_btn.clicked.connect(self._on_add)
        self.remove_btn.clicked.connect(self._on_remove)
        self.list_w.currentRowChanged.connect(self._on_select)
        self.kind_combo.currentIndexChanged.connect(self._on_editor_changed)
        self.dir_combo.currentIndexChanged.connect(self._on_editor_changed)
        for sb in (
            self.low_sb,
            self.high_sb,
            self.target_sb,
            self.center_sb,
            self.sigma_sb,
            self.weight_sb,
        ):
            sb.valueChanged.connect(self._on_editor_changed)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> MPOScoringDialogParams:
        out = (self.out_edit.text() or "").strip() or "MPO_Score"
        combine = _COMBINE_LABELS[self.combine_combo.currentIndex()][1]
        specs = tuple(d.to_spec() for d in self._drafts)
        return MPOScoringDialogParams(
            output_column=out,
            specs=specs,
            combine=combine,
            write_individual=bool(self.indiv_cb.isChecked()),
            decimals=int(self.decimals_sb.value()),
        )

    def _on_add(self) -> None:
        col = str(self.prop_combo.currentText() or "").strip()
        if not col:
            return
        if any(d.column == col for d in self._drafts):
            QMessageBox.information(
                self, "MPO Scoring", f'"{col}" is already in the criteria list.'
            )
            return
        lo, hi = self._bounds.get(col, (0.0, 1.0))
        if not (hi > lo):
            hi = lo + 1.0
        mid = 0.5 * (lo + hi)
        draft = _CriterionDraft(
            column=col,
            kind="linear",
            direction="maximize",
            weight=1.0,
            low=lo,
            high=hi,
            target=mid,
            center=mid,
            sigma=max((hi - lo) / 4.0, 1e-6),
        )
        self._drafts.append(draft)
        item = QListWidgetItem(self._item_label(draft))
        self.list_w.addItem(item)
        self.list_w.setCurrentRow(len(self._drafts) - 1)

    def _on_remove(self) -> None:
        row = self.list_w.currentRow()
        if row < 0 or row >= len(self._drafts):
            return
        self._drafts.pop(row)
        self.list_w.takeItem(row)
        if self._drafts:
            self.list_w.setCurrentRow(min(row, len(self._drafts) - 1))
        else:
            self._set_editor_enabled(False)

    def _item_label(self, draft: _CriterionDraft) -> str:
        kind = next(lbl for lbl, k in _KIND_LABELS if k == draft.kind)
        return f"{draft.column}  ·  {kind}  ·  {draft.summary()}"

    def _on_select(self, row: int) -> None:
        if row < 0 or row >= len(self._drafts):
            self._set_editor_enabled(False)
            return
        self._set_editor_enabled(True)
        self._load_editor(self._drafts[row])

    def _set_editor_enabled(self, on: bool) -> None:
        for w in (
            self.kind_combo,
            self.dir_combo,
            self.low_sb,
            self.high_sb,
            self.target_sb,
            self.center_sb,
            self.sigma_sb,
            self.weight_sb,
        ):
            w.setEnabled(on)
        if not on:
            self.hint.setText("Add a numeric property to configure its desirability function.")

    def _load_editor(self, draft: _CriterionDraft) -> None:
        self._updating = True
        try:
            kind_i = next(i for i, (_l, k) in enumerate(_KIND_LABELS) if k == draft.kind)
            dir_i = next(i for i, (_l, d) in enumerate(_DIR_LABELS) if d == draft.direction)
            self.kind_combo.setCurrentIndex(kind_i)
            self.dir_combo.setCurrentIndex(dir_i)
            self.low_sb.setValue(float(draft.low))
            self.high_sb.setValue(float(draft.high))
            self.target_sb.setValue(float(draft.target))
            self.center_sb.setValue(float(draft.center))
            self.sigma_sb.setValue(float(draft.sigma))
            self.weight_sb.setValue(float(draft.weight))
        finally:
            self._updating = False
        self._sync_editor_visibility()

    def _on_editor_changed(self, *_args) -> None:
        if self._updating:
            return
        row = self.list_w.currentRow()
        if row < 0 or row >= len(self._drafts):
            return
        kind = _KIND_LABELS[self.kind_combo.currentIndex()][1]
        direction = _DIR_LABELS[self.dir_combo.currentIndex()][1]
        draft = replace(
            self._drafts[row],
            kind=kind,
            direction=direction,
            low=float(self.low_sb.value()),
            high=float(self.high_sb.value()),
            target=float(self.target_sb.value()),
            center=float(self.center_sb.value()),
            sigma=float(self.sigma_sb.value()),
            weight=float(self.weight_sb.value()),
        )
        self._drafts[row] = draft
        item = self.list_w.item(row)
        if item is not None:
            item.setText(self._item_label(draft))
        self._sync_editor_visibility()

    def _sync_editor_visibility(self) -> None:
        kind = _KIND_LABELS[self.kind_combo.currentIndex()][1]
        direction = _DIR_LABELS[self.dir_combo.currentIndex()][1]
        is_gauss = kind == "gaussian"
        is_step = kind == "step"
        is_linear = kind == "linear"

        self.dir_combo.setEnabled(not is_gauss)
        self.center_sb.setEnabled(is_gauss)
        self.sigma_sb.setEnabled(is_gauss)
        self.low_sb.setEnabled(is_linear or is_step)
        self.high_sb.setEnabled(is_linear or is_step)
        self.target_sb.setEnabled(is_linear and direction == "target")

        if is_gauss:
            self.hint.setText(
                "Gaussian: desirability = exp(−½ ((x − center) / σ)²), peak = 1 at center."
            )
        elif is_step and direction == "maximize":
            self.hint.setText("Step (maximize): score 1 if value ≥ High, else 0.")
        elif is_step and direction == "minimize":
            self.hint.setText("Step (minimize): score 1 if value ≤ Low, else 0.")
        elif is_step:
            self.hint.setText("Step (range): score 1 if Low ≤ value ≤ High, else 0.")
        elif direction == "maximize":
            self.hint.setText(
                "Linear (maximize): 0 at/below Low, 1 at/above High, linear in between."
            )
        elif direction == "minimize":
            self.hint.setText(
                "Linear (minimize): 1 at/below Low, 0 at/above High, linear in between."
            )
        else:
            self.hint.setText(
                "Linear (target): 0 outside [Low, High], rises to 1 at Target between the bounds."
            )

    def _on_accept(self) -> None:
        try:
            p = self.params()
        except Exception as exc:
            QMessageBox.warning(self, "MPO Scoring", str(exc))
            return
        if not p.specs:
            QMessageBox.information(self, "MPO Scoring", "Add at least one property criterion.")
            return
        if not p.output_column:
            QMessageBox.warning(self, "MPO Scoring", "Enter an output column name.")
            return
        for spec in p.specs:
            if spec.kind == "gaussian" and (spec.sigma is None or float(spec.sigma) <= 0):
                QMessageBox.warning(
                    self, "MPO Scoring", f'"{spec.column}": sigma must be positive.'
                )
                return
            if spec.kind == "linear" and spec.direction != "target":
                if spec.low is None or spec.high is None:
                    QMessageBox.warning(self, "MPO Scoring", f'"{spec.column}": set Low and High.')
                    return
        self.accept()
