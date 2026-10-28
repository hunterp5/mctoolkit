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

"""Chemistry → Structure Preparation → Fast Prepare."""

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
    QRadioButton,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from .disconnect_fragments import _validate_fragment_output_columns
from .scope import selection_scope_checked


@dataclass(frozen=True)
class FastPrepareDialogConfig:
    """Values the Fast Prepare dialog collects for the table-side job."""

    source_column: str
    update_target: bool
    largest_column: str | None
    fragments_column: str
    only_selected: bool
    neutralize: bool


class FastPrepareDialog(QDialog):
    """Disconnect largest fragment, optionally neutralize, then render 2D in one pipeline."""

    def __init__(
        self,
        source_labels: list[str],
        existing_headers: list[str],
        selected_row_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Fast Prepare")
        self.setMinimumWidth(420)
        self._existing = list(existing_headers)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        structures = QGroupBox("Structures")
        struct_form = QFormLayout(structures)
        struct_form.setContentsMargins(8, 6, 8, 6)
        struct_form.setSpacing(4)
        struct_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        struct_form.addRow("Target column:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        struct_form.addRow("", self.only_selected_cb)
        root.addWidget(structures)

        output = QGroupBox("Output")
        out_form = QFormLayout(output)
        out_form.setContentsMargins(8, 6, 8, 6)
        out_form.setSpacing(4)
        out_form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.radio_update_target = QRadioButton("Update Target Column")
        self.radio_new_columns = QRadioButton("New Column")
        self.radio_update_target.setChecked(True)
        out_form.addRow(self.radio_update_target)
        out_form.addRow(self.radio_new_columns)
        self.largest_edit = QLineEdit("Largest fragment SMILES")
        out_form.addRow("Largest Fragment:", self.largest_edit)
        self.fragments_edit = QLineEdit("Fragments")
        out_form.addRow("Smallest Fragment:", self.fragments_edit)
        root.addWidget(output)

        self.radio_update_target.toggled.connect(self._sync_output_fields)
        self.radio_new_columns.toggled.connect(self._sync_output_fields)

        options = QGroupBox("Options")
        opt_lyt = QVBoxLayout(options)
        opt_lyt.setContentsMargins(8, 6, 8, 6)
        opt_lyt.setSpacing(4)
        self.neutralize_cb = QCheckBox("Neutralize")
        self.neutralize_cb.setChecked(False)
        self.neutralize_cb.setToolTip(
            "After keeping the largest fragment, zero net formal charge with RDKit Uncharger. "
            "Leave off to keep the fragment charges as-is."
        )
        opt_lyt.addWidget(self.neutralize_cb)
        root.addWidget(options)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._sync_output_fields()
        self.adjustSize()
        make_window_minimizable(self)

    def _sync_output_fields(self) -> None:
        self.largest_edit.setEnabled(self.radio_new_columns.isChecked())

    def _try_accept(self) -> None:
        update_target = self.radio_update_target.isChecked()
        largest = (self.largest_edit.text() or "").strip()
        smallest = (self.fragments_edit.text() or "").strip()
        if not _validate_fragment_output_columns(
            self,
            update_target=update_target,
            target_column=self.src_combo.currentText(),
            largest_name=largest,
            smallest_name=smallest,
        ):
            return
        self.accept()

    def config(self) -> FastPrepareDialogConfig:
        update_target = self.radio_update_target.isChecked()
        return FastPrepareDialogConfig(
            source_column=self.src_combo.currentText(),
            update_target=update_target,
            largest_column=None if update_target else (self.largest_edit.text() or "").strip(),
            fragments_column=(self.fragments_edit.text() or "").strip(),
            only_selected=selection_scope_checked(self),
            neutralize=bool(self.neutralize_cb.isChecked()),
        )
