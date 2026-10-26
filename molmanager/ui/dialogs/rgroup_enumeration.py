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

"""Dialog for Chemistry → Structure Enumeration → R-Group."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
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
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...chem.fragment_recomposition_filters import (
    parse_recomposition_filter_text,
    recomposition_filter_property_help,
)
from ...chem.rgroup_enumeration import (
    RGroupEnumerationRequest,
    RGroupPoolInput,
    prepare_core,
)
from ...platform_support.config import load_config
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_RGROUP_ENUMERATION
from .reaction_enumeration import ReactionEnumerationOutputPanel

_FILE_FILTER = (
    "Structure files (*.sdf *.sd *.smi *.smiles *.txt *.csv);;"
    "SDF (*.sdf);;SMILES (*.smi *.smiles *.txt);;CSV (*.csv);;All files (*.*)"
)


def attachment_label_from_text(text: str) -> int:
    """Parse ``R1``, ``1``, or ``[*:1]`` into the core attachment number."""
    raw = (text or "").strip()
    token = raw.upper().replace(" ", "")
    if token.startswith("[*:") and token.endswith("]"):
        token = token[3:-1]
    elif token.startswith("*:"):
        token = token[2:]
    elif token.startswith("R"):
        token = token[1:]
    if not token.isdigit() or int(token) <= 0:
        raise ValueError(f"Attachment point {raw!r} should look like R1.")
    return int(token)


class _RGroupFileRow(QWidget):
    """One core point and the building-block file that attaches there."""

    def __init__(self, label: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.core_label = int(label)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(QLabel("Attachment point"))
        self.point_edit = QLineEdit(f"R{label}")
        self.point_edit.setPlaceholderText("R1")
        self.point_edit.setFixedWidth(72)
        self.point_edit.setToolTip(
            "Core point this file attaches to. Use R1 for the core atom labeled [*:1]."
        )
        row.addWidget(self.point_edit)
        self.file_edit = QLineEdit()
        self.file_edit.setPlaceholderText("Building-block file (.sdf, .smi, .txt, or .csv)")
        self.file_edit.setToolTip(
            "Each structure needs one * on the atom that should bond to the core, for example CCN*."
        )
        row.addWidget(self.file_edit, 1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_file)
        row.addWidget(browse_btn)

    def attachment_label(self) -> int:
        return attachment_label_from_text(self.point_edit.text())

    def file_path(self) -> str:
        return (self.file_edit.text() or "").strip()

    def restore(self, point_text: str, file_path: str) -> None:
        self.point_edit.setText(point_text)
        self.file_edit.setText(file_path)

    def _browse_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select building-block file",
            self.file_edit.text() or "",
            _FILE_FILTER,
        )
        if path:
            self.file_edit.setText(path)


class RGroupEnumerationDialog(QDialog):
    """Sketch a core, point each attachment at a building-block list, and enumerate."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(TOOL_RGROUP_ENUMERATION)
        self.setMinimumWidth(560)
        self.resize(600, 640)
        self._panels: list[_RGroupFileRow] = []
        self._build_ui()
        make_window_minimizable(self)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 8)
        root.setSpacing(8)

        core_box = QGroupBox("Core")
        core_lyt = QVBoxLayout(core_box)
        core_row = QHBoxLayout()
        self.core_edit = QLineEdit()
        self.core_edit.setPlaceholderText("[*:1]c1ccc([*:2])cc1")
        self.core_edit.setToolTip(
            "Scaffold SMILES. Number each dummy: [*:1], [*:2]. Unnumbered * atoms are labeled in order."
        )
        self.core_edit.editingFinished.connect(self.sync_attachment_points)
        core_row.addWidget(self.core_edit, 1)
        self.sketch_btn = QPushButton("Sketcher…")
        self.sketch_btn.clicked.connect(self._use_sketcher)
        core_row.addWidget(self.sketch_btn)
        core_lyt.addLayout(core_row)

        id_row = QFormLayout()
        self.core_id_edit = QLineEdit()
        self.core_id_edit.setPlaceholderText("Optional. Defaults to the core SMILES.")
        id_row.addRow("Core ID:", self.core_id_edit)
        core_lyt.addLayout(id_row)
        root.addWidget(core_box)

        blocks_box = QGroupBox("Building blocks")
        blocks_lyt = QVBoxLayout(blocks_box)
        self._pool_host = QWidget()
        self._pool_layout = QVBoxLayout(self._pool_host)
        self._pool_layout.setContentsMargins(0, 0, 0, 0)
        self._pool_layout.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._pool_host)
        scroll.setMinimumHeight(180)
        blocks_lyt.addWidget(scroll)
        root.addWidget(blocks_box, 1)

        limits = QFormLayout()
        self.max_products_sb = QSpinBox()
        max_prod_cap = int(load_config().memory_guard_enum_max_products)
        self.max_products_sb.setRange(1, max_prod_cap)
        self.max_products_sb.setValue(min(2000, max_prod_cap))
        self.max_products_sb.setToolTip("Stop after this many accepted unique product SMILES.")
        limits.addRow("Max products:", self.max_products_sb)
        root.addLayout(limits)

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
        self.output_panel = ReactionEnumerationOutputPanel(
            save_placeholder="rgroup_products.sdf",
            browse_title="Save R-group products",
        )
        out_lyt.addWidget(self.output_panel)
        root.addWidget(out_box)

        self._button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._button_box.accepted.connect(self._on_accept)
        self._button_box.rejected.connect(self.reject)
        root.addWidget(self._button_box)

    def sync_attachment_points(self) -> str | None:
        """Show one file row per core attachment point. Return an error, or None."""
        text = (self.core_edit.text() or "").strip()
        if not text:
            self._set_panels(())
            return "Enter a core SMILES with numbered attachment points, for example [*:1]c1ccccc1."
        try:
            _mol, labels = prepare_core(text)
        except ValueError as exc:
            self._set_panels(())
            return str(exc)
        self._set_panels(labels)
        return None

    def request(self) -> RGroupEnumerationRequest:
        """Validated job inputs. Raises ``ValueError`` when the form is incomplete."""
        error = self.sync_attachment_points()
        if error:
            raise ValueError(error)
        pools: list[RGroupPoolInput] = []
        seen: set[int] = set()
        for panel in self._panels:
            label = panel.attachment_label()
            if label in seen:
                raise ValueError(f"Attachment point R{label} is listed more than once.")
            seen.add(label)
            file_path = panel.file_path()
            if not file_path:
                raise ValueError(f"Choose a building-block file for R{label}.")
            pools.append(RGroupPoolInput(label, "file", file_path, ""))
        _mol, core_labels = prepare_core(self.core_edit.text())
        if tuple(sorted(seen)) != core_labels:
            names = ", ".join(f"R{label}" for label in core_labels)
            raise ValueError(
                f"Building-block files must cover the core attachment points ({names})."
            )
        filter_text = self.output_filters_edit.toPlainText().strip()
        if filter_text:
            parse_recomposition_filter_text(filter_text)
        add_to_table, save_to_file, save_path = self.output_panel.options()
        if not add_to_table and not save_to_file:
            raise ValueError("Choose at least one output destination (table and/or file).")
        if save_to_file and not save_path:
            raise ValueError("Choose an output SDF file path.")
        core_smiles = self.core_edit.text().strip()
        core_id = self.core_id_edit.text().strip() or core_smiles
        return RGroupEnumerationRequest(
            core_smiles=core_smiles,
            core_id=core_id,
            pools=tuple(pools),
            max_products=int(self.max_products_sb.value()),
            output_filters=filter_text,
            add_to_table=add_to_table,
            save_to_file=save_to_file,
            save_path=save_path,
        )

    def _set_panels(self, labels: tuple[int, ...]) -> None:
        previous = {
            panel.core_label: (panel.point_edit.text(), panel.file_path()) for panel in self._panels
        }
        while self._pool_layout.count():
            item = self._pool_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        self._panels = []
        for label in labels:
            panel = _RGroupFileRow(label, self._pool_host)
            saved = previous.get(label)
            if saved is not None:
                panel.restore(*saved)
            self._pool_layout.addWidget(panel)
            self._panels.append(panel)
        self._pool_layout.addStretch(1)

    def _use_sketcher(self) -> None:
        try:
            from ..sketcher import SketcherDialog
        except ImportError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        host = self.parent() or self
        dlg = SketcherDialog(host)
        dlg.setModal(True)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.exec_()
        try:
            parts = dlg.canvas.fragment_smiles_parts()
        except (AttributeError, RuntimeError, TypeError, ValueError):
            parts = []
        if not parts:
            QMessageBox.information(
                self, self.windowTitle(), "No valid SMILES could be exported from the sketch."
            )
            return
        self.core_edit.setText(str(parts[0]).strip())
        if len(parts) > 1:
            QMessageBox.information(
                self,
                self.windowTitle(),
                "The sketcher had more than one fragment. The first one was used as the core.",
            )
        self.sync_attachment_points()

    def _on_accept(self) -> None:
        try:
            self.request()
        except ValueError as exc:
            QMessageBox.warning(self, self.windowTitle(), str(exc))
            return
        self.accept()
