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

"""Dialog for Chemistry → Reaction → Reaction Based Enumeration."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ...chem.fragment_recomposition_filters import (
    parse_recomposition_filter_text,
    recomposition_filter_property_help,
)
from ...chem.reaction_enumeration import (
    ReactionEnumerationRequest,
    load_reaction_presets,
    load_reactant_molecules_from_smiles_text,
    validate_reaction_smarts,
)
from ...chem.reaction_file_io import load_reaction_smarts_from_rxn_path
from ...platform_support.config import load_config
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_REACTION_ENUMERATION

ReactionEnumerationDialogParams = ReactionEnumerationRequest


class ReactionEnumerationOutputPanel(QWidget):
    """Destination checkboxes for table append and SDF export."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        save_placeholder: str = "reaction_products.sdf",
        browse_title: str = "Save reaction products",
    ):
        super().__init__(parent)
        self._save_placeholder = save_placeholder
        self._browse_title = browse_title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self.add_to_table_cb = QCheckBox("Add products to table")
        self.add_to_table_cb.setChecked(True)
        self.add_to_table_cb.setToolTip(
            "Append enumerated product rows to the main compound table."
        )
        layout.addWidget(self.add_to_table_cb)

        self.save_to_file_cb = QCheckBox("Save products to file")
        self.save_to_file_cb.setToolTip("Write enumerated products to an SDF file.")
        self.save_to_file_cb.toggled.connect(self._sync_save_path_enabled)
        layout.addWidget(self.save_to_file_cb)

        path_row = QHBoxLayout()
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setPlaceholderText(self._save_placeholder)
        self.save_path_edit.setEnabled(False)
        path_row.addWidget(self.save_path_edit, 1)
        self.save_browse_btn = QPushButton("Browse…")
        self.save_browse_btn.setEnabled(False)
        self.save_browse_btn.clicked.connect(self._browse_save_path)
        path_row.addWidget(self.save_browse_btn)
        layout.addLayout(path_row)

    def _sync_save_path_enabled(self, enabled: bool) -> None:
        self.save_path_edit.setEnabled(bool(enabled))
        self.save_browse_btn.setEnabled(bool(enabled))

    def _browse_save_path(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            self._browse_title,
            self.save_path_edit.text() or self._save_placeholder,
            "SDF (*.sdf);;All files (*.*)",
        )
        if path:
            if not path.lower().endswith(".sdf"):
                path = f"{path}.sdf"
            self.save_path_edit.setText(path)

    def options(self) -> tuple[bool, bool, str | None]:
        save = bool(self.save_to_file_cb.isChecked())
        path = (self.save_path_edit.text() or "").strip() or None
        return bool(self.add_to_table_cb.isChecked()), save, path if save else None

    def validate(self, dialog: QDialog) -> bool:
        add_to_table, save_to_file, save_path = self.options()
        if not add_to_table and not save_to_file:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                "Choose at least one output destination (table and/or file).",
            )
            return False
        if save_to_file and not save_path:
            QMessageBox.warning(dialog, dialog.windowTitle(), "Choose an output SDF file path.")
            return False
        return True


class ReactantInputPanel(QWidget):
    """One reactant pool: structure file or pasted SMILES lines."""

    _FILE_FILTER = (
        "Structure files (*.sdf *.sd *.smi *.smiles *.txt *.csv);;"
        "SDF (*.sdf);;SMILES (*.smi *.smiles *.txt);;CSV (*.csv);;All files (*.*)"
    )

    def __init__(self, label: str, parent: QWidget | None = None):
        super().__init__(parent)
        self._label = label
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(f"{label} input:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("Structure file", "file")
        self.mode_combo.addItem("SMILES text", "smiles")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo, 1)
        layout.addLayout(mode_row)

        self.stack = QStackedWidget()
        file_page = QWidget()
        file_lyt = QHBoxLayout(file_page)
        file_lyt.setContentsMargins(0, 0, 0, 0)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Path to .sdf, .smi, .txt, or .csv")
        file_lyt.addWidget(self.file_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        file_lyt.addWidget(browse_btn)
        self.stack.addWidget(file_page)

        smiles_page = QWidget()
        smiles_lyt = QVBoxLayout(smiles_page)
        smiles_lyt.setContentsMargins(0, 0, 0, 0)
        self.smiles_edit = QPlainTextEdit()
        self.smiles_edit.setPlaceholderText("One SMILES per line")
        self.smiles_edit.setMaximumHeight(88)
        smiles_lyt.addWidget(self.smiles_edit)
        self.stack.addWidget(smiles_page)
        layout.addWidget(self.stack)

        self._on_mode_changed(self.mode_combo.currentIndex())

    def set_label(self, label: str) -> None:
        self._label = label

    def _on_mode_changed(self, _index: int) -> None:
        self.stack.setCurrentIndex(0 if self.mode() == "file" else 1)

    def mode(self) -> str:
        return str(self.mode_combo.currentData() or "file")

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            f"Select {self._label} file",
            self.file_edit.text() or "",
            self._FILE_FILTER,
        )
        if path:
            self.file_edit.setText(path)

    def validate(self, dialog: QDialog) -> bool:
        if self.mode() == "file":
            if not (self.file_edit.text() or "").strip():
                QMessageBox.warning(
                    dialog, dialog.windowTitle(), f"Choose a file for {self._label}."
                )
                return False
            return True
        text = self.smiles_edit.toPlainText().strip()
        if not text:
            QMessageBox.warning(
                dialog,
                dialog.windowTitle(),
                f"Enter at least one SMILES for {self._label}.",
            )
            return False
        try:
            load_reactant_molecules_from_smiles_text(text)
        except ValueError as exc:
            QMessageBox.warning(dialog, dialog.windowTitle(), str(exc))
            return False
        return True

    def values(self) -> tuple[str, str, str]:
        return (
            self.mode(),
            (self.file_edit.text() or "").strip(),
            self.smiles_edit.toPlainText(),
        )


class ReactionEnumerationDialog(QDialog):
    """Pick a reaction template, reactants, and output destinations."""

    def __init__(self, parent=None, initial_smarts: str = ""):
        super().__init__(parent)
        self._init_enum_state()
        self._build_enum_ui()
        self._wire_enum_ui()
        self._on_preset_changed(self.preset_combo.currentIndex())
        if (initial_smarts or "").strip():
            self._apply_loaded_smarts((initial_smarts or "").strip())

    def _init_enum_state(self) -> None:
        self._presets = load_reaction_presets()
        self.setWindowTitle(TOOL_REACTION_ENUMERATION)
        self.setMinimumWidth(520)
        self.resize(560, 0)

    def _build_enum_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        form = QFormLayout()
        self.preset_combo = QComboBox()
        for preset in self._presets:
            self.preset_combo.addItem(preset.name, preset.id)
        form.addRow("Reaction:", self.preset_combo)

        self.preset_desc = QLabel()
        self.preset_desc.setWordWrap(True)
        form.addRow("", self.preset_desc)

        self.smarts_edit = QLineEdit()
        self.smarts_edit.setPlaceholderText("[reactant1].[reactant2]>>[product]")
        self.smarts_edit.setToolTip(
            "RDKit reaction SMARTS with exactly two reactants separated by a dot before >>."
        )
        smarts_row = QHBoxLayout()
        smarts_row.setContentsMargins(0, 0, 0, 0)
        smarts_row.addWidget(self.smarts_edit, 1)
        self.load_rxn_btn = QPushButton("Load RXN…")
        self.load_rxn_btn.setToolTip("Fill Reaction SMARTS from an MDL .rxn or .rdf file.")
        smarts_row.addWidget(self.load_rxn_btn)
        form.addRow("Reaction SMARTS:", smarts_row)
        root.addLayout(form)

        reactants_box = QGroupBox("Reactants")
        reactants_lyt = QVBoxLayout(reactants_box)
        self.reactant1_panel = ReactantInputPanel("Reactant 1")
        self.reactant2_panel = ReactantInputPanel("Reactant 2")
        reactants_lyt.addWidget(self.reactant1_panel)
        reactants_lyt.addWidget(self.reactant2_panel)
        root.addWidget(reactants_box)

        limits_form = QFormLayout()
        self.max_products_sb = QSpinBox()
        max_prod_cap = int(load_config().memory_guard_enum_max_products)
        self.max_products_sb.setRange(1, max_prod_cap)
        self.max_products_sb.setValue(min(2000, max_prod_cap))
        self.max_products_sb.setToolTip("Stop after this many accepted unique product SMILES.")
        limits_form.addRow("Max products:", self.max_products_sb)
        root.addLayout(limits_form)

        filters_box = QGroupBox("Product constraints (optional)")
        filters_lyt = QVBoxLayout(filters_box)
        self.output_filters_edit = QPlainTextEdit()
        self.output_filters_edit.setPlaceholderText(
            "Optional. Comma- or line-separated AND conditions, e.g.\n"
            "MW 200-500, LogP <= 5, HeavyAtoms >= 10"
        )
        self.output_filters_edit.setToolTip(
            "Only keep products that satisfy these property limits. "
            f"Supported properties include {recomposition_filter_property_help()}."
        )
        self.output_filters_edit.setMaximumHeight(72)
        filters_lyt.addWidget(self.output_filters_edit)
        root.addWidget(filters_box)

        out_box = QGroupBox("Output")
        out_lyt = QVBoxLayout(out_box)
        self.output_panel = ReactionEnumerationOutputPanel()
        out_lyt.addWidget(self.output_panel)
        root.addWidget(out_box)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        root.addWidget(self._button_box)

    def _wire_enum_ui(self) -> None:
        self.preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        self.load_rxn_btn.clicked.connect(self._browse_rxn)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        make_window_minimizable(self)

    def _select_custom_preset(self) -> None:
        for i, preset in enumerate(self._presets):
            if preset.id == "custom":
                self.preset_combo.setCurrentIndex(i)
                return

    def _apply_loaded_smarts(self, smarts: str) -> None:
        self._select_custom_preset()
        self.smarts_edit.setText(smarts)

    def _browse_rxn(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open reaction file",
            "",
            "Reactions (*.rxn *.rdf);;RXN (*.rxn);;RDF (*.rdf);;All files (*.*)",
        )
        if not path:
            return
        try:
            smarts, n_rxn = load_reaction_smarts_from_rxn_path(path)
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self._apply_loaded_smarts(smarts)
        if n_rxn > 1:
            QMessageBox.information(
                self,
                self.windowTitle(),
                f"Loaded the first of {n_rxn} reactions from that file.",
            )

    def _current_preset(self):
        idx = self.preset_combo.currentIndex()
        if idx < 0 or idx >= len(self._presets):
            return self._presets[-1]
        return self._presets[idx]

    def _on_preset_changed(self, _index: int) -> None:
        preset = self._current_preset()
        self.preset_desc.setText(preset.description)
        self.reactant1_panel.set_label(preset.reactant_labels[0])
        self.reactant2_panel.set_label(preset.reactant_labels[1])
        if preset.id != "custom":
            self.smarts_edit.setText(preset.smarts)
        elif not self.smarts_edit.text().strip():
            self.smarts_edit.clear()

    def _on_accept(self) -> None:
        smarts = (self.smarts_edit.text() or "").strip()
        try:
            validate_reaction_smarts(smarts)
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        if not self.reactant1_panel.validate(self):
            return
        if not self.reactant2_panel.validate(self):
            return
        filter_text = self.output_filters_edit.toPlainText().strip()
        if filter_text:
            try:
                parse_recomposition_filter_text(filter_text)
            except ValueError as exc:
                QMessageBox.warning(self, self.windowTitle(), str(exc))
                return
        if not self.output_panel.validate(self):
            return
        self.accept()

    def params(self) -> ReactionEnumerationRequest:
        preset = self._current_preset()
        add_to_table, save_to_file, save_path = self.output_panel.options()
        mode1, file1, smiles1 = self.reactant1_panel.values()
        mode2, file2, smiles2 = self.reactant2_panel.values()
        return ReactionEnumerationRequest(
            reaction_name=preset.name,
            rxn_smarts=(self.smarts_edit.text() or "").strip(),
            reactant_1_mode=mode1,
            reactant_2_mode=mode2,
            reactant_file_1=file1,
            reactant_file_2=file2,
            reactant_smiles_1=smiles1,
            reactant_smiles_2=smiles2,
            max_products=int(self.max_products_sb.value()),
            output_filters=self.output_filters_edit.toPlainText().strip(),
            add_to_table=add_to_table,
            save_to_file=save_to_file,
            save_path=save_path,
        )
