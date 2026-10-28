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

"""Chemistry → Structure Preparation → Preparation Menu.

Each box starts off; a run includes only the checked ones.
"""

from __future__ import annotations

from dataclasses import dataclass

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..qt_widget_utils import make_window_minimizable
from .disconnect_fragments import _validate_fragment_output_columns
from .scope import selection_scope_checked


@dataclass(frozen=True)
class PrepareDialogConfig:
    """Checked preparation options and the columns they write."""

    source_column: str
    update_target: bool
    largest_column: str | None
    fragments_column: str
    only_selected: bool
    standardize: bool
    largest_fragment: bool
    canonical_tautomer: bool
    render_2d: bool
    neutralize: bool
    protonate: bool
    protonate_ph: float
    generate_protomers: bool
    protomer_ph: float
    protomer_output_file: str
    explicit_hydrogens: str
    remove_isotopes: bool


class PrepareDialog(QDialog):
    """Checklist of every structure-preparation option."""

    def __init__(
        self,
        source_labels: list[str],
        existing_headers: list[str],
        selected_row_count: int = 0,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Prepare")
        self.setMinimumWidth(480)
        self.resize(500, 680)
        self._existing = list(existing_headers)
        self._have_selection = selected_row_count > 0
        self._selected_row_count = selected_row_count

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        body = QVBoxLayout(host)
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        self._build_structures(body, source_labels)
        self._build_output(body)
        self._build_options(body)
        body.addStretch(1)
        scroll.setWidget(host)
        root.addWidget(scroll, 1)

        box = QDialogButtonBox(QDialogButtonBox.Cancel)
        run = box.addButton("Run", QDialogButtonBox.AcceptRole)
        run.clicked.connect(self._try_accept)
        box.rejected.connect(self.reject)
        root.addWidget(box)
        self._sync_enabled_fields()
        make_window_minimizable(self)

    def _build_structures(self, body: QVBoxLayout, source_labels: list[str]) -> None:
        structures = QGroupBox("Structures")
        form = QFormLayout(structures)
        form.setContentsMargins(8, 6, 8, 6)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.src_combo = QComboBox()
        self.src_combo.addItems(source_labels)
        form.addRow("Target column:", self.src_combo)
        self.only_selected_cb = QCheckBox("Selected Rows Only")
        self._only_selected_scope_prefix = "Selected Rows Only"
        if self._have_selection:
            self.only_selected_cb.setText(
                f"{self._only_selected_scope_prefix} ({self._selected_row_count} row(s))"
            )
        else:
            self.only_selected_cb.setEnabled(False)
        form.addRow("", self.only_selected_cb)
        body.addWidget(structures)

    def _build_output(self, body: QVBoxLayout) -> None:
        output = QGroupBox("Output")
        form = QFormLayout(output)
        form.setContentsMargins(8, 6, 8, 6)
        form.setFieldGrowthPolicy(QFormLayout.ExpandingFieldsGrow)
        self.radio_update_target = QRadioButton("Update Target Column")
        self.radio_new_columns = QRadioButton("New Column")
        self.radio_update_target.setChecked(True)
        form.addRow(self.radio_update_target)
        form.addRow(self.radio_new_columns)
        self.largest_edit = QLineEdit("Prepared")
        form.addRow("New column:", self.largest_edit)
        self.fragments_edit = QLineEdit("Fragments")
        form.addRow("Other fragments:", self.fragments_edit)
        self.radio_update_target.toggled.connect(self._sync_enabled_fields)
        self.radio_new_columns.toggled.connect(self._sync_enabled_fields)
        body.addWidget(output)

    def _build_options(self, body: QVBoxLayout) -> None:
        options, layout = self._section("Options")
        self.standardize_cb = self._check(
            layout,
            "Standardize",
            False,
            "Remove explicit hydrogens, disconnect metal–organic bonds, normalize "
            "functional groups, and reionize. Reionize moves a proton between equivalent "
            "sites. It does not set a pH 7.4 form.",
        )
        self.fragment_cb = self._check(
            layout,
            "Largest organic fragment",
            False,
            "Keep the largest organic piece. Salts and other pieces are written to the "
            "fragments column.",
        )
        self.tautomer_cb = self._check(
            layout,
            "Canonical tautomer",
            False,
            "Map equivalent tautomers onto one representation. The search stops after "
            "100 transforms, so a very large molecule may differ from an exhaustive "
            "tautomer. RDKit drops tetrahedral and double-bond stereo while doing this.",
        )
        self.render_cb = self._check(
            layout,
            "Render 2D",
            False,
            "Redraw the prepared structures. The current orientation is kept when "
            "the atom count does not change.",
        )
        body.addWidget(options)

        charge, charge_layout = self._section("Protonation and neutralization")
        self.neutralize_cb = self._check(
            charge_layout,
            "Neutralize",
            False,
            "Zero the net formal charge with RDKit Uncharger. This does not set a "
            "physiological protonation state.",
        )
        self.protonate_cb = self._check(
            charge_layout,
            "Protonate",
            False,
            "Write the dominant protomer at the chosen pH. This replaces Neutralize.",
        )
        self.protonate_ph = self._ph_row(charge_layout, "Protonate pH:")
        self.protomers_cb = self._check(
            charge_layout,
            "Generate protomers",
            False,
            "Enumerate protomers at the chosen pH and show them so you can add rows. "
            "An output file is optional.",
        )
        self.protomer_ph = self._ph_row(charge_layout, "Protomer pH:")
        file_row = QHBoxLayout()
        self.protomer_file = QLineEdit()
        self.protomer_file.setPlaceholderText("Optional SDF or CSV")
        self.protomer_file.setToolTip(
            "Leave blank to keep the results in the dialog only. "
            "A path writes every protomer when generation finishes."
        )
        self.protomer_browse = QPushButton("Browse…")
        self.protomer_browse.clicked.connect(self._browse_protomer_file)
        file_row.addWidget(self.protomer_file, 1)
        file_row.addWidget(self.protomer_browse)
        charge_layout.addLayout(file_row)
        body.addWidget(charge)

        hydrogens, hydrogen_layout = self._section("Explicit hydrogens and isotope labels")
        self.add_h_cb = self._check(
            hydrogen_layout,
            "Add explicit hydrogens",
            False,
            "Draw valence hydrogens as atoms. Formal charge and protonation stay the same.",
        )
        self.remove_h_cb = self._check(
            hydrogen_layout,
            "Remove explicit hydrogens",
            False,
            "Hide explicit valence hydrogens. Formal charge and protonation stay the same.",
        )
        self.isotope_cb = self._check(
            hydrogen_layout,
            "Remove isotope labels",
            False,
            "Clear mass numbers such as deuterium. A labeled analog is left unchanged "
            "while this is off.",
        )
        body.addWidget(hydrogens)

        self.neutralize_cb.toggled.connect(self._on_neutralize)
        self.protonate_cb.toggled.connect(self._on_protonate)
        self.add_h_cb.toggled.connect(self._on_add_h)
        self.remove_h_cb.toggled.connect(self._on_remove_h)
        for box in (
            self.fragment_cb,
            self.protonate_cb,
            self.protomers_cb,
        ):
            box.toggled.connect(self._sync_enabled_fields)

    def _section(self, title: str) -> tuple[QGroupBox, QVBoxLayout]:
        box = QGroupBox(title)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)
        return box, layout

    def _check(self, layout: QVBoxLayout, text: str, checked: bool, tip: str) -> QCheckBox:
        box = QCheckBox(text)
        box.setChecked(checked)
        box.setToolTip(tip)
        layout.addWidget(box)
        return box

    def _ph_row(self, layout: QVBoxLayout, label: str) -> QDoubleSpinBox:
        row = QFormLayout()
        spin = QDoubleSpinBox()
        spin.setRange(0.0, 14.0)
        spin.setDecimals(2)
        spin.setSingleStep(0.1)
        spin.setValue(7.40)
        row.addRow(label, spin)
        layout.addLayout(row)
        return spin

    def _on_neutralize(self, on: bool) -> None:
        if on:
            self.protonate_cb.setChecked(False)

    def _on_protonate(self, on: bool) -> None:
        if on:
            self.neutralize_cb.setChecked(False)

    def _on_add_h(self, on: bool) -> None:
        if on:
            self.remove_h_cb.setChecked(False)

    def _on_remove_h(self, on: bool) -> None:
        if on:
            self.add_h_cb.setChecked(False)

    def _browse_protomer_file(self) -> None:
        path, _selected = QFileDialog.getSaveFileName(
            self,
            "Protomer output",
            self.protomer_file.text().strip(),
            "Structure file (*.sdf);;CSV (*.csv)",
        )
        if path:
            self.protomer_file.setText(path)
            self.protomers_cb.setChecked(True)

    def _sync_enabled_fields(self) -> None:
        self.largest_edit.setEnabled(self.radio_new_columns.isChecked())
        self.fragments_edit.setEnabled(self.fragment_cb.isChecked())
        self.protonate_ph.setEnabled(self.protonate_cb.isChecked())
        protomers_on = self.protomers_cb.isChecked()
        self.protomer_ph.setEnabled(protomers_on)
        self.protomer_file.setEnabled(protomers_on)
        self.protomer_browse.setEnabled(protomers_on)

    def _explicit_hydrogens(self) -> str:
        if self.add_h_cb.isChecked():
            return "add"
        if self.remove_h_cb.isChecked():
            return "remove"
        return ""

    def _try_accept(self) -> None:
        update_target = self.radio_update_target.isChecked()
        largest = (self.largest_edit.text() or "").strip()
        fragments = (self.fragments_edit.text() or "").strip() or "Fragments"
        needs_output = any(
            (
                self.standardize_cb.isChecked(),
                self.fragment_cb.isChecked(),
                self.tautomer_cb.isChecked(),
                self.neutralize_cb.isChecked(),
                self.isotope_cb.isChecked(),
                self._explicit_hydrogens(),
            )
        )
        if needs_output and not _validate_fragment_output_columns(
            self,
            update_target=update_target,
            target_column=self.src_combo.currentText(),
            largest_name=largest,
            smallest_name=fragments if self.fragment_cb.isChecked() else "Fragments",
        ):
            return
        if not needs_output and not any(
            (
                self.render_cb.isChecked(),
                self.protonate_cb.isChecked(),
                self.protomers_cb.isChecked(),
            )
        ):
            QMessageBox.information(self, "Prepare", "Choose at least one option.")
            return
        self.accept()

    def config(self) -> PrepareDialogConfig:
        update_target = self.radio_update_target.isChecked()
        return PrepareDialogConfig(
            source_column=self.src_combo.currentText(),
            update_target=update_target,
            largest_column=None if update_target else (self.largest_edit.text() or "").strip(),
            fragments_column=(self.fragments_edit.text() or "").strip() or "Fragments",
            only_selected=selection_scope_checked(self),
            standardize=self.standardize_cb.isChecked(),
            largest_fragment=self.fragment_cb.isChecked(),
            canonical_tautomer=self.tautomer_cb.isChecked(),
            render_2d=self.render_cb.isChecked(),
            neutralize=self.neutralize_cb.isChecked(),
            protonate=self.protonate_cb.isChecked(),
            protonate_ph=float(self.protonate_ph.value()),
            generate_protomers=self.protomers_cb.isChecked(),
            protomer_ph=float(self.protomer_ph.value()),
            protomer_output_file=self.protomer_file.text().strip(),
            explicit_hydrogens=self._explicit_hydrogens(),
            remove_isotopes=self.isotope_cb.isChecked(),
        )
