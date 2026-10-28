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

"""Dialog for Chemistry → Extract Reaction Info."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QRadioButton,
    QVBoxLayout,
)

from ...chem.reaction_extract import (
    EXTRACT_MODES,
    ExtractMode,
    ReactionExtractParams,
    extract_reaction_column_values,
    preferred_reaction_source_column,
)
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_REACTION_EXTRACT
from .scope import selection_scope_checked

ReactionExtractDialogParams = ReactionExtractParams


class ReactionExtractDialog(QDialog):
    """Choose a reaction column and write reactant/product components to new columns."""

    def __init__(
        self,
        columns: list[str],
        selected_row_count: int = 0,
        parent=None,
        *,
        default_column: str | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setWindowTitle(TOOL_REACTION_EXTRACT)
        self.setMinimumWidth(440)
        self.resize(480, 0)
        self._have_selection = selected_row_count > 0

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.col_combo = QComboBox()
        self.col_combo.addItems(columns)
        self.col_combo.setToolTip("Column of reaction SMARTS / SMIRKS to split into components.")
        preferred = default_column or preferred_reaction_source_column(columns)
        if preferred and preferred in columns:
            self.col_combo.setCurrentText(preferred)
        form.addRow("Column:", self.col_combo)
        root.addLayout(form)

        mode_box = QGroupBox("Extract")
        mode_row = QHBoxLayout(mode_box)
        mode_row.setContentsMargins(8, 6, 8, 6)
        self._mode_group = QButtonGroup(self)
        self._mode_buttons: dict[ExtractMode, QRadioButton] = {}
        mode_tips = {
            "reactants": "Write each reactant to its own new column.",
            "products": "Write each product to its own new column.",
            "both": "Write each reactant and each product to its own new column.",
        }
        for label, mode in EXTRACT_MODES:
            btn = QRadioButton(label)
            btn.setToolTip(mode_tips[mode])
            self._mode_group.addButton(btn)
            self._mode_buttons[mode] = btn
            mode_row.addWidget(btn)
        self._mode_buttons["both"].setChecked(True)
        mode_row.addStretch(1)
        root.addWidget(mode_box)

        self.preview_label = QLabel("")
        self.preview_label.setWordWrap(True)
        self.preview_label.setStyleSheet("color: #444;")
        root.addWidget(self.preview_label)

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
        root.addWidget(box)

        self.col_combo.currentTextChanged.connect(self._update_preview)
        for btn in self._mode_buttons.values():
            btn.toggled.connect(self._update_preview)
        self.only_selected_cb.toggled.connect(self._update_preview)
        self._update_preview()
        make_window_minimizable(self)

    def _extract_mode(self) -> ExtractMode:
        for mode, btn in self._mode_buttons.items():
            if btn.isChecked():
                return mode
        return "both"

    def _sample_texts(self) -> list[str]:
        app = self.parent_app
        col = (self.col_combo.currentText() or "").strip()
        if app is None or not col:
            return []
        only_sel = self.only_selected_rows()
        allowed = app._selected_oids_set() if only_sel else None
        from ...services.table_reader import backing_then_cell
        from ..table_reader_view import WindowTableReader

        if col not in app.headers:
            return []
        texts: list[str] = []
        m = app._table_model
        reader = WindowTableReader(app)
        for r in range(m.rowCount()):
            oid = m.row_oid(r)
            if allowed is not None and oid not in allowed:
                continue
            texts.append(backing_then_cell(reader, r, col))
            if len(texts) >= 400:
                break
        return texts

    def _update_preview(self, *_args) -> None:
        label = getattr(self, "preview_label", None)
        if label is None:
            return
        col = (self.col_combo.currentText() or "").strip()
        if not col:
            label.setText("Choose a reaction column.")
            return
        headers, _rows = extract_reaction_column_values(self._sample_texts(), self._extract_mode())
        if not headers:
            label.setText("No reactants or products found in the current scope.")
            return
        shown = ", ".join(headers[:8])
        extra = "" if len(headers) <= 8 else f", … ({len(headers)} total)"
        label.setText(f"New columns: {shown}{extra}")

    def only_selected_rows(self) -> bool:
        return selection_scope_checked(self)

    def params(self) -> ReactionExtractDialogParams:
        return ReactionExtractDialogParams(
            source_column=(self.col_combo.currentText() or "").strip(),
            mode=self._extract_mode(),
        )

    def accept(self) -> None:
        if not (self.col_combo.currentText() or "").strip():
            QMessageBox.warning(self, TOOL_REACTION_EXTRACT, "Choose a reaction column.")
            self.col_combo.setFocus(Qt.OtherFocusReason)
            return
        super().accept()
