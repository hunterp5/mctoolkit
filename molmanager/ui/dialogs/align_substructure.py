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

"""Chemistry → Prepare Structures → Align to Substructure."""

from __future__ import annotations

import math
from dataclasses import dataclass

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ...table.structure_image import molecule_pixmap
from ...chem.substructure_align import (
    conformer_xy,
    prepare_query_mol,
    query_mol_from_text,
    set_conformer_xy,
)
from ..qt_widget_utils import make_window_minimizable
from ..sketcher.iupac_orient import reflect_x, reflect_y, rotate_points
from .scope import selection_scope_checked

_PREVIEW_W = 280
_PREVIEW_H = 160


@dataclass(frozen=True)
class AlignSubstructureConfig:
    """What the dialog asked to do."""

    column: str
    only_selected: bool
    action: str
    template: object | None = None
    skip_existing: bool = True


class AlignSubstructureDialog(QDialog):
    """Pick a column and an oriented substructure, or clear a stored orientation."""

    def __init__(self, source_labels: list[str], selected_row_count: int = 0, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Align to Substructure")
        self.resize(520, 460)
        self._have_selection = selected_row_count > 0
        self._custom_mol = None
        self._ignore_text = False
        self._result: AlignSubstructureConfig | None = None

        root = QVBoxLayout(self)
        form = QFormLayout()
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels or ["Structure"])
        self.src_combo.setToolTip("Structure column whose pictures should share this orientation.")
        form.addRow("Target column:", self.src_combo)
        root.addLayout(form)

        self.query_edit = QPlainTextEdit()
        self.query_edit.setPlaceholderText("SMILES, SMARTS, or molfile")
        self.query_edit.setFixedHeight(72)
        self.query_edit.setToolTip(
            "Substructure to pin. A molfile keeps its coordinates. "
            "SMILES and SMARTS start from a default layout you can rotate or redraw."
        )
        root.addWidget(self.query_edit)

        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setMinimumHeight(_PREVIEW_H)
        self.preview.setStyleSheet("background: white; border: 1px solid palette(mid);")
        root.addWidget(self.preview)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        root.addWidget(self.error_label)

        buttons = QHBoxLayout()
        self.sketch_btn = QPushButton("Edit in sketcher…")
        self.sketch_btn.setToolTip(
            "Draw the substructure, including wildcards, in the orientation you want."
        )
        self.rot_btn = QPushButton("Rotate 90°")
        self.flip_h_btn = QPushButton("Flip horizontal")
        self.flip_v_btn = QPushButton("Flip vertical")
        buttons.addWidget(self.sketch_btn)
        buttons.addWidget(self.rot_btn)
        buttons.addWidget(self.flip_h_btn)
        buttons.addWidget(self.flip_v_btn)
        buttons.addStretch(1)
        root.addLayout(buttons)

        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        root.addWidget(self.only_selected_cb)

        self.skip_existing_cb = QCheckBox("Skip rows that already have an orientation")
        self.skip_existing_cb.setChecked(True)
        self.skip_existing_cb.setToolTip(
            "Leave rows aligned by an earlier query unchanged, so this query orients the rest. "
            "Uncheck to replace an existing orientation when a molecule contains both substructures."
        )
        root.addWidget(self.skip_existing_cb)

        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        self._align_btn = box.addButton("Align", QDialogButtonBox.AcceptRole)
        self._reset_btn = box.addButton("Reset orientation", QDialogButtonBox.ResetRole)
        self._reset_btn.setToolTip(
            "Drop the stored orientation for rows in scope and redraw them with the usual layout."
        )
        box.rejected.connect(self.reject)
        self._align_btn.clicked.connect(self._accept_align)
        self._reset_btn.clicked.connect(self._accept_reset)
        root.addWidget(box)

        self._parse_timer = QTimer(self)
        self._parse_timer.setSingleShot(True)
        self._parse_timer.setInterval(200)
        self._parse_timer.timeout.connect(self._refresh_preview)
        self.query_edit.textChanged.connect(self._on_text_changed)
        self.sketch_btn.clicked.connect(self._edit_in_sketcher)
        self.rot_btn.clicked.connect(lambda: self._transform("rot"))
        self.flip_h_btn.clicked.connect(lambda: self._transform("flip_h"))
        self.flip_v_btn.clicked.connect(lambda: self._transform("flip_v"))
        make_window_minimizable(self)
        self._refresh_preview()

    def config(self) -> AlignSubstructureConfig | None:
        return self._result

    def _on_text_changed(self) -> None:
        if self._ignore_text:
            return
        self._custom_mol = None
        self._parse_timer.start()

    def _current_query(self):
        if self._custom_mol is not None:
            return self._custom_mol, ""
        return query_mol_from_text(self.query_edit.toPlainText())

    def _refresh_preview(self) -> None:
        mol, err = self._current_query()
        self.error_label.setText(err)
        if mol is None:
            self.preview.setPixmap(QPixmap())
            self.preview.setText("No query")
            return
        try:
            self.preview.setPixmap(molecule_pixmap(mol, _PREVIEW_W, _PREVIEW_H))
            self.preview.setText("")
        except (ValueError, RuntimeError, TypeError):
            self.preview.setPixmap(QPixmap())
            self.preview.setText("Could not preview this query")

    def _transform(self, kind: str) -> None:
        mol, err = self._current_query()
        if mol is None:
            self.error_label.setText(err or "Enter a substructure before rotating it.")
            return
        xs, ys = conformer_xy(mol)
        if len(xs) < 2:
            self.error_label.setText("This query has no coordinates to transform.")
            return
        if kind == "rot":
            xs, ys = rotate_points(xs, ys, math.pi / 2.0)
        elif kind == "flip_h":
            xs, ys = reflect_x(xs, ys)
        else:
            xs, ys = reflect_y(xs, ys)
        try:
            self._custom_mol = set_conformer_xy(mol, xs, ys)
        except ValueError as exc:
            self.error_label.setText(str(exc))
            return
        self._refresh_preview()

    def _edit_in_sketcher(self) -> None:
        from ..sketcher import SketcherDialog

        mol, _err = self._current_query()
        host = self.parent() or self
        dlg = SketcherDialog(host, initial_mol=mol)
        dlg.setModal(True)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        dlg.exec_()
        try:
            sketched = dlg.canvas.to_query_mol()
        except (AttributeError, RuntimeError):
            sketched = None
        if sketched is None:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "Draw a single fragment. Disconnected sketches are not used as the query.",
            )
            dlg.deleteLater()
            return
        prepared, err = prepare_query_mol(sketched)
        if prepared is None:
            QMessageBox.information(self, self.windowTitle(), err)
            dlg.deleteLater()
            return
        try:
            text = dlg.canvas.to_smiles() or dlg.canvas.to_smarts()
        except (AttributeError, RuntimeError):
            text = ""
        dlg.deleteLater()
        self._ignore_text = True
        try:
            self.query_edit.setPlainText((text or "").strip())
        finally:
            self._ignore_text = False
        self._custom_mol = prepared
        self._refresh_preview()

    def _accept_align(self) -> None:
        mol, err = self._current_query()
        if mol is None:
            QMessageBox.warning(self, self.windowTitle(), err or "Enter a substructure.")
            return
        self._result = AlignSubstructureConfig(
            column=self.src_combo.currentText(),
            only_selected=selection_scope_checked(self),
            action="align",
            template=mol,
            skip_existing=self.skip_existing_cb.isChecked(),
        )
        self.accept()

    def _accept_reset(self) -> None:
        self._result = AlignSubstructureConfig(
            column=self.src_combo.currentText(),
            only_selected=selection_scope_checked(self),
            action="reset",
            template=None,
            skip_existing=self.skip_existing_cb.isChecked(),
        )
        self.accept()
