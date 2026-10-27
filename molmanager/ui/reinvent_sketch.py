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

"""Open the sketcher and write SMARTS back into a REINVENT scaffold field."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit, QMessageBox, QWidget


def fill_scaffold_from_sketcher(parent: QWidget, editor: QLineEdit) -> None:
    """Let the user draw a scaffold and store its SMARTS in *editor*."""
    try:
        from .sketcher import SketcherDialog
    except ImportError as exc:
        QMessageBox.warning(parent, parent.windowTitle(), str(exc))
        return
    current = editor.text().strip()
    initial = _mol_from_pattern(current) if current else None
    dialog = SketcherDialog(parent, initial_mol=initial)
    dialog.setModal(True)
    dialog.setWindowModality(Qt.ApplicationModal)
    dialog.setAttribute(Qt.WA_DeleteOnClose, False)
    dialog.exec_()
    try:
        smarts = (dialog.canvas.to_smarts() or "").strip()
    except (AttributeError, RuntimeError, TypeError, ValueError):
        smarts = ""
    dialog.deleteLater()
    if not smarts:
        QMessageBox.information(
            parent,
            parent.windowTitle(),
            "No scaffold could be read from the sketch.",
        )
        return
    if "." in smarts:
        smarts = smarts.split(".", 1)[0].strip()
        QMessageBox.information(
            parent,
            parent.windowTitle(),
            "The sketch had more than one fragment. The first one was used as the scaffold.",
        )
    editor.setText(smarts)


def _mol_from_pattern(pattern: str):
    from rdkit import Chem, rdBase

    blocker = rdBase.BlockLogs()
    try:
        mol = Chem.MolFromSmiles(pattern)
        if mol is not None:
            return mol
        return Chem.MolFromSmarts(pattern)
    finally:
        del blocker
