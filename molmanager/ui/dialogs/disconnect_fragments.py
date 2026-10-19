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

"""Chemistry → Prepare Structures → Disconnect Largest Fragments."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from ..qt_widget_utils import make_window_minimizable
from .scope import selection_scope_checked

_RESERVED_DISCONNECT_COLUMNS = frozenset({"ID_HIDDEN"})


def _validate_fragment_output_columns(
    dialog: QDialog,
    *,
    update_target: bool,
    target_column: str,
    largest_name: str,
    smallest_name: str,
) -> bool:
    if not smallest_name:
        QMessageBox.warning(
            dialog, dialog.windowTitle(), "Enter a name for the smallest fragment column."
        )
        return False
    if update_target:
        if smallest_name in _RESERVED_DISCONNECT_COLUMNS:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                f"The smallest fragment column name “{smallest_name}” is reserved.",
            )
            return False
        return True
    if not largest_name:
        QMessageBox.warning(
            dialog, dialog.windowTitle(), "Enter a name for the largest fragment column."
        )
        return False
    if largest_name == smallest_name:
        QMessageBox.warning(
            dialog,
            dialog.windowTitle(),
            "Largest and smallest fragment columns must have different names.",
        )
        return False
    if largest_name == target_column:
        QMessageBox.warning(
            dialog,
            dialog.windowTitle(),
            "Largest fragment column must differ from the target column when using a new column.",
        )
        return False
    for label, name in (("Largest fragment", largest_name), ("Smallest fragment", smallest_name)):
        if name in _RESERVED_DISCONNECT_COLUMNS:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                f"The {label} column name “{name}” is reserved.",
            )
            return False
    return True


class DisconnectFragmentsDialog(QDialog):
    """Pick the target structure field; update it by default or write results to new columns."""

    def __init__(
        self,
        source_labels: list[str],
        existing_headers: list[str],
        selected_row_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Disconnect Largest Fragments")
        self._existing = list(existing_headers)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        form = QFormLayout()
        form.setVerticalSpacing(4)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        form.addRow("Target column:", self.src_combo)

        self.radio_update_target = QRadioButton("Update Target Column")
        self.radio_new_columns = QRadioButton("New Column")
        self.radio_update_target.setChecked(True)
        form.addRow(self.radio_update_target)
        form.addRow(self.radio_new_columns)

        self.largest_edit = QLineEdit("Largest fragment SMILES")
        form.addRow("Largest Fragment:", self.largest_edit)
        self.fragments_edit = QLineEdit("Fragments")
        form.addRow("Smallest Fragment:", self.fragments_edit)
        root.addLayout(form)

        self.radio_update_target.toggled.connect(self._sync_output_fields)
        self.radio_new_columns.toggled.connect(self._sync_output_fields)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)
        self.no_render_2d_cb = QCheckBox("No Render 2D")
        root.addWidget(self.no_render_2d_cb)

        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        box.accepted.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._sync_output_fields()
        self.adjustSize()
        make_window_minimizable(self)

    def _sync_output_fields(self) -> None:
        new_only = self.radio_new_columns.isChecked()
        self.largest_edit.setEnabled(new_only)

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

    def config(self) -> tuple[str, bool, str | None, str, bool, bool]:
        """
        Returns ``(target_column, update_target, largest_column_or_None, smaller_fragments_column,
        only_selected_rows, no_render_2d)``.

        When *update_target* is true, the largest fragment is written to the target column and
        *largest_column_or_None* is ``None``. Otherwise results go to the named largest column.
        """
        src = self.src_combo.currentText()
        update_target = self.radio_update_target.isChecked()
        largest = None if update_target else (self.largest_edit.text() or "").strip()
        fragments = (self.fragments_edit.text() or "").strip()
        only_sel = selection_scope_checked(self)
        no_render = self.no_render_2d_cb.isChecked()
        return src, update_target, largest, fragments, only_sel, no_render
