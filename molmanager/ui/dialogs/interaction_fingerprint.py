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

"""Interaction fingerprint dialog (Protein → Interaction Fingerprint)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from ..protein_viewer_models import STRUCTURE_FILE_FILTER
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_INTERACTION_FINGERPRINT
from .scope import selection_scope_checked


@dataclass(frozen=True)
class InteractionFingerprintDialogParams:
    """Receptor file, pose column, and column prefix for one fingerprint job."""

    receptor_path: str
    pose_column: str
    column_prefix: str
    only_selected: bool


class InteractionFingerprintDialog(QDialog):
    """Choose the receptor and the packed pose column to fingerprint."""

    def __init__(
        self,
        *,
        pose_columns: list[str],
        receptor_path: str = "",
        selected_row_count: int,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(TOOL_INTERACTION_FINGERPRINT)
        self.setMinimumWidth(520)
        self.resize(560, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)
        form = QFormLayout()

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit((receptor_path or "").strip())
        self.path_edit.setPlaceholderText("Receptor PDB or mmCIF")
        self.path_edit.setToolTip(
            "Protein the poses were docked into. Crystal ligands in the file are ignored."
        )
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Receptor:", path_row)

        self.pose_combo = QComboBox()
        self.pose_combo.setMinimumWidth(220)
        if pose_columns:
            self.pose_combo.addItems(pose_columns)
        else:
            self.pose_combo.addItem("(no pose columns)")
            self.pose_combo.setEnabled(False)
        self.pose_combo.setToolTip(
            "Packed poses column. The first pose in the cell is typed, "
            "which is the best-ranked pose when docking wrote them in order."
        )
        form.addRow("Pose column:", self.pose_combo)

        self.prefix_edit = QLineEdit("IFP")
        self.prefix_edit.setToolTip(
            "Writes this column and a second column named “prefix Residues”."
        )
        form.addRow("Column prefix:", self.prefix_edit)
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
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        self._ok = box.button(QDialogButtonBox.Ok)
        root.addWidget(box)
        self.path_edit.textChanged.connect(self._sync_ok)
        self.prefix_edit.textChanged.connect(self._sync_ok)
        self._sync_ok()
        make_window_minimizable(self)

    def _browse(self) -> None:
        path, _selected = QFileDialog.getOpenFileName(
            self,
            "Receptor structure",
            self.path_edit.text().strip(),
            STRUCTURE_FILE_FILTER,
        )
        if path:
            self.path_edit.setText(path)

    def _sync_ok(self) -> None:
        if self._ok is None:
            return
        path = self.path_edit.text().strip()
        prefix = self.prefix_edit.text().strip()
        self._ok.setEnabled(self.pose_combo.isEnabled() and bool(path) and bool(prefix))

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> InteractionFingerprintDialogParams:
        path = self.path_edit.text().strip()
        return InteractionFingerprintDialogParams(
            receptor_path=str(Path(path)),
            pose_column=self.pose_combo.currentText(),
            column_prefix=self.prefix_edit.text().strip() or "IFP",
            only_selected=self.only_selected_rows(),
        )
