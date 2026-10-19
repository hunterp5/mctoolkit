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

"""Chemistry → Conformations → Superpose."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...workers import SuperposeParams, SuperposeStructuresParams
from ...workers.superpose_types import (
    SUPERPOSE_ALIGN_ON_LABELS,
    SUPERPOSE_GEOMETRY_LABELS,
    SUPERPOSE_TARGET_LABELS,
)
from ..qt_widget_utils import make_window_minimizable
from .conformer_output import add_centered_run_button, conformer_options_group
from .scope import selection_scope_checked


def _set_combo_item_enabled(combo: QComboBox, index: int, enabled: bool) -> None:
    model = combo.model()
    item = getattr(model, "item", None)
    if callable(item):
        row = item(index)
        if row is not None:
            row.setEnabled(enabled)


def _fill_combo(combo: QComboBox, labels: tuple[tuple[str, str], ...]) -> None:
    for key, label in labels:
        combo.addItem(label, key)


def _set_combo_current_data(combo: QComboBox, data) -> None:
    for i in range(combo.count()):
        if combo.itemData(i) == data:
            combo.setCurrentIndex(i)
            return


class SuperposeDialog(QDialog):
    """Unified superposition: conformers vs structures, 3D spatial vs 2D topological."""

    def __init__(
        self,
        selected_row_count: int = 0,
        *,
        source_columns: list[str] | None = None,
        has_confs: bool = True,
        default_target: str = "structures",
        parent=None,
    ):
        super().__init__(parent)
        self._init_superpose_state(selected_row_count, source_columns, has_confs, default_target)
        self._build_superpose_ui()
        self._wire_superpose_ui()

    def _init_superpose_state(
        self,
        selected_row_count: int,
        source_columns: list[str] | None,
        has_confs: bool,
        default_target: str,
    ) -> None:
        self.setWindowTitle("Superpose")
        self.setMinimumWidth(420)
        self.resize(460, 0)
        self._selected_row_count = int(selected_row_count)
        self._have_selection = selected_row_count > 0
        self._has_confs = bool(has_confs)
        sources = [c for c in (source_columns or ["Structure"]) if c]
        self._source_columns = sources or ["Structure"]
        target = (default_target or "structures").strip().lower()
        if target not in {key for key, _ in SUPERPOSE_TARGET_LABELS}:
            target = "structures"
        if not self._has_confs:
            target = "structures"
        self._default_target = target

    def _build_superpose_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        form.setSpacing(6)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)

        self.target_combo = QComboBox()
        _fill_combo(self.target_combo, SUPERPOSE_TARGET_LABELS)
        self.target_combo.setToolTip(
            "Conformers overlay the packed confs ensemble on each row. "
            "Structures overlay every molecule in scope onto the first row (table order)."
        )
        if not self._has_confs:
            for i, (key, _label) in enumerate(SUPERPOSE_TARGET_LABELS):
                if key == "conformers":
                    _set_combo_item_enabled(self.target_combo, i, False)
                    break
            self.target_combo.setToolTip(
                "Add a confs column first (Chemistry → Conformations) to superpose ensembles."
            )
        _set_combo_current_data(self.target_combo, self._default_target)
        form.addRow("Align:", self.target_combo)

        self.geom_combo = QComboBox()
        _fill_combo(self.geom_combo, SUPERPOSE_GEOMETRY_LABELS)
        self.geom_combo.setToolTip(
            "3D spatial: rigid AlignMol overlay (O3A when no atom map). "
            "2D topological: regenerate drawings on a shared core "
            "(GenerateDepictionMatching2DStructure)."
        )
        form.addRow("Geometry:", self.geom_combo)

        self.src_combo = QComboBox()
        self.src_combo.addItems(self._source_columns)
        self.src_combo.setToolTip(
            "Where to read coordinates for structure overlay. Prefer confs when present; "
            "Structure uses the in-memory molecule (embeds 3D when Geometry is 3D spatial)."
        )
        form.addRow("Source:", self.src_combo)

        self.ref_sb = QSpinBox()
        self.ref_sb.setRange(0, 499)
        self.ref_sb.setValue(0)
        self.ref_sb.setToolTip(
            "0-based index into the conformer list for each row (sorted by RDKit conformer id). "
            "If a row has fewer conformers than this index, the last conformer is used as reference."
        )
        form.addRow("Reference index:", self.ref_sb)

        self.align_on_combo = QComboBox()
        _fill_combo(self.align_on_combo, SUPERPOSE_ALIGN_ON_LABELS)
        self.align_on_combo.setToolTip(
            "Largest ring system uses the fused SSSR set with the most atoms. "
            "Most central ring is the SSSR ring nearest the molecule centroid "
            "(3D coordinates when present, otherwise graph distance). "
            "Custom pattern restricts alignment to a SMILES/SMARTS match."
        )
        form.addRow("Align on:", self.align_on_combo)

        self.align_pat_edit = QLineEdit()
        self.align_pat_edit.setPlaceholderText("SMILES or SMARTS")
        self.align_pat_edit.setToolTip(
            "Alignment uses only atoms that match this query. For structures, a miss "
            "falls through to MCS (when enabled) or O3A in 3D. For conformers the pattern must match."
        )
        self.align_smarts_cb = QCheckBox("SMARTS")
        self.align_smarts_cb.setChecked(False)
        self.align_smarts_cb.setToolTip("Parse the pattern as SMARTS instead of SMILES.")
        self._pattern_host = QWidget()
        pat_row = QHBoxLayout(self._pattern_host)
        pat_row.setContentsMargins(0, 0, 0, 0)
        pat_row.setSpacing(6)
        pat_row.addWidget(self.align_pat_edit, 1)
        pat_row.addWidget(self.align_smarts_cb)
        form.addRow("Pattern:", self._pattern_host)

        self.max_align_sb = QSpinBox()
        self.max_align_sb.setRange(10, 500)
        self.max_align_sb.setValue(50)
        self.max_align_sb.setToolTip(
            "Maximum iterations for RDKit AlignMol when an atom map is used."
        )
        form.addRow("Max iterations:", self.max_align_sb)
        self._form = form
        root.addLayout(form)

        self.heavy_cb = QCheckBox("Heavy atoms only")
        self.heavy_cb.setChecked(True)
        self.heavy_cb.setToolTip(
            "Alignment uses non-hydrogen atoms only (recommended when hydrogens are noisy)."
        )

        self.reflect_cb = QCheckBox("Allow reflection")
        self.reflect_cb.setChecked(False)
        self.reflect_cb.setToolTip(
            "If checked, 3D AlignMol may use a reflected pose; leave off to preserve chirality."
        )

        self.mcs_cb = QCheckBox("Use MCS when no atom map")
        self.mcs_cb.setChecked(True)
        self.mcs_cb.setToolTip(
            "Find a maximum common substructure between each probe and the reference."
        )

        self.o3a_cb = QCheckBox("O3A overlay if no atom map")
        self.o3a_cb.setChecked(True)
        self.o3a_cb.setToolTip(
            "3D only: if pattern, ring, and MCS do not yield an atom map, overlay with Crippen / MMFF O3A."
        )

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({self._selected_row_count} row(s))"
            )
            if self._default_target == "structures":
                self.only_selected_cb.setChecked(True)
        else:
            self.only_selected_cb.setEnabled(False)

        root.addWidget(
            conformer_options_group(
                self.heavy_cb,
                self.reflect_cb,
                self.mcs_cb,
                self.o3a_cb,
                self.only_selected_cb,
            )
        )

        self.run_btn = add_centered_run_button(root)
        self.run_btn.clicked.connect(self.accept)

    def _wire_superpose_ui(self) -> None:
        self.target_combo.currentIndexChanged.connect(self._sync_mode)
        self.geom_combo.currentIndexChanged.connect(self._sync_mode)
        self.align_on_combo.currentIndexChanged.connect(self._sync_mode)
        make_window_minimizable(self)
        self._sync_mode()

    def _sync_mode(self) -> None:
        is_conf = self.target() == "conformers"
        is_2d = self.geometry() == "2d"
        custom = str(self.align_on_combo.currentData() or "") == "pattern"
        self._set_form_row_visible(self.ref_sb, is_conf)
        self._set_form_row_visible(self.src_combo, not is_conf)
        self._set_form_row_visible(self._pattern_host, custom)
        self._set_form_row_visible(self.max_align_sb, not is_2d)
        self.mcs_cb.setVisible(not is_conf)
        self.o3a_cb.setVisible(not is_conf and not is_2d)
        self.reflect_cb.setVisible(not is_2d)

    def _set_form_row_visible(self, field, visible: bool) -> None:
        field.setVisible(visible)
        lab = self._form.labelForField(field)
        if lab is not None:
            lab.setVisible(visible)

    def _align_payload(self) -> tuple[str, str, bool]:
        mode = str(self.align_on_combo.currentData() or "")
        if mode == "pattern":
            return (
                "",
                (self.align_pat_edit.text() or "").strip(),
                bool(self.align_smarts_cb.isChecked()),
            )
        return mode, "", False

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def target(self) -> str:
        val = self.target_combo.currentData()
        return "conformers" if val == "conformers" else "structures"

    def geometry(self) -> str:
        val = self.geom_combo.currentData()
        return "2d" if val == "2d" else "3d"

    def source_column(self) -> str:
        return str(self.src_combo.currentText() or "Structure")

    def conformer_params(self) -> SuperposeParams:
        align_mode, pattern, is_smarts = self._align_payload()
        return SuperposeParams(
            reference_conformer_index=int(self.ref_sb.value()),
            heavy_atoms_only=bool(self.heavy_cb.isChecked()),
            reflect=bool(self.reflect_cb.isChecked()),
            max_align_iters=int(self.max_align_sb.value()),
            align_pattern=pattern,
            align_pattern_is_smarts=is_smarts,
            geometry=self.geometry(),
            align_mode=align_mode,
        )

    def structure_params(self) -> SuperposeStructuresParams:
        align_mode, pattern, is_smarts = self._align_payload()
        return SuperposeStructuresParams(
            heavy_atoms_only=bool(self.heavy_cb.isChecked()),
            reflect=bool(self.reflect_cb.isChecked()),
            max_align_iters=int(self.max_align_sb.value()),
            align_pattern=pattern,
            align_pattern_is_smarts=is_smarts,
            use_mcs=bool(self.mcs_cb.isChecked()),
            geometry=self.geometry(),
            use_o3a=bool(self.o3a_cb.isChecked()),
            align_mode=align_mode,
        )

    def params(self) -> SuperposeParams | SuperposeStructuresParams:
        if self.target() == "conformers":
            return self.conformer_params()
        return self.structure_params()


class SuperposeConformersDialog(SuperposeDialog):
    """Compatibility wrapper that opens the unified dialog on conformers."""

    def __init__(self, selected_row_count: int = 0, parent=None, **kwargs):
        kwargs.setdefault("has_confs", True)
        kwargs.setdefault("default_target", "conformers")
        super().__init__(selected_row_count, parent=parent, **kwargs)


class SuperposeStructuresDialog(SuperposeDialog):
    """Compatibility wrapper that opens the unified dialog on structures."""

    def __init__(
        self,
        selected_row_count: int = 0,
        *,
        source_columns: list[str] | None = None,
        parent=None,
        **kwargs,
    ):
        kwargs.setdefault("default_target", "structures")
        super().__init__(
            selected_row_count,
            source_columns=source_columns,
            parent=parent,
            **kwargs,
        )
