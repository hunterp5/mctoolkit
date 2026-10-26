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

"""Open the sketcher the way the application does, then draw and load a structure."""

from __future__ import annotations

from PyQt5.QtCore import QEvent, QPoint, Qt
from PyQt5.QtGui import QMouseEvent
from rdkit import Chem

from molmanager.chem.reaction_file_io import RXN_ANNOTATION_HEADER
from molmanager.ui.sketcher import SketcherDialog


def _click(widget, pos: QPoint) -> None:
    """Press and release the left button at *pos* in *widget* coordinates."""
    press = QMouseEvent(
        QEvent.MouseButtonPress, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    release = QMouseEvent(
        QEvent.MouseButtonRelease, pos, Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
    )
    widget.mousePressEvent(press)
    widget.mouseReleaseEvent(release)


def test_package_import_opens_a_blank_sketcher(qapp) -> None:  # noqa: ARG001
    """Tools → Sketcher imports the dialog and shows an empty drawing canvas."""
    assert RXN_ANNOTATION_HEADER == "Reaction Annotation"
    dialog = SketcherDialog()
    dialog.resize(1400, 900)
    dialog.show()
    qapp.processEvents()
    assert dialog.isVisible()
    assert dialog.tb_draw.isChecked()
    assert dialog.canvas.place_element == "C"
    assert dialog.canvas.nodes == []
    dialog.canvas.repaint()
    qapp.processEvents()
    assert dialog._status_tool.text().startswith("Draw")
    assert dialog.canvas.height() > dialog.height() * 0.7
    assert dialog._status_bar.height() < 48

    _click(dialog.canvas, QPoint(220, 180))
    _click(dialog.canvas, QPoint(300, 220))
    assert len(dialog.canvas.nodes) == 2
    assert {node["element"] for node in dialog.canvas.nodes} == {"C"}
    dialog.canvas.repaint()
    qapp.processEvents()
    dialog.close()


def test_open_sketcher_loads_a_structure(qapp) -> None:  # noqa: ARG001
    """Edit in Sketcher shows the molecule after the dialog's deferred load."""
    mol = Chem.MolFromSmiles("c1ccccc1O")
    assert mol is not None
    dialog = SketcherDialog(initial_mol=mol)
    dialog.show()
    qapp.processEvents()
    assert dialog.select_btn.isChecked()
    assert dialog.canvas.select_mode
    assert len(dialog.canvas.nodes) >= 7
    assert any(node["element"] == "O" for node in dialog.canvas.nodes)
    dialog.canvas.repaint()
    qapp.processEvents()
    assert dialog.canvas._last_structure_paint == "scene"
    dialog.canvas.cleanup_layout_2d()
    assert len(dialog.canvas.nodes) >= 7
    dialog.close()
