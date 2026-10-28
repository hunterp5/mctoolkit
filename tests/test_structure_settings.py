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

"""Tests for 2D structure depiction size settings."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtWidgets")

from molmanager.table.structure_depiction_layout import (
    DEFAULT_STRUCTURE_DEPICT_HEIGHT,
    DEFAULT_STRUCTURE_DEPICT_WIDTH,
    DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT,
    MAX_STRUCTURE_DEPICT_WIDTH,
    MIN_STRUCTURE_DEPICT_HEIGHT,
    MIN_STRUCTURE_DEPICT_WIDTH,
    set_structure_depict_size,
    structure_column_minimum_width,
    structure_depict_height,
    structure_depict_size_for_cell_resize,
    structure_depict_width,
    structure_row_default_height,
)


@pytest.fixture(autouse=True)
def _reset_structure_size():
    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )
    yield
    set_structure_depict_size(
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        persist=False,
    )


def test_set_structure_depict_size_clamps_and_updates_runtime() -> None:
    w, h = set_structure_depict_size(9999, 10, persist=False)
    assert w == MAX_STRUCTURE_DEPICT_WIDTH
    assert h == MIN_STRUCTURE_DEPICT_HEIGHT
    assert structure_depict_width() == MAX_STRUCTURE_DEPICT_WIDTH
    assert structure_depict_height() == MIN_STRUCTURE_DEPICT_HEIGHT


def test_structure_row_default_height_tracks_depiction_height() -> None:
    set_structure_depict_size(180, 150, persist=False)
    assert structure_row_default_height() == 150 + (
        DEFAULT_STRUCTURE_ROW_DEFAULT_HEIGHT - DEFAULT_STRUCTURE_DEPICT_HEIGHT
    )


def test_structure_column_minimum_width_uses_runtime_size() -> None:
    set_structure_depict_size(300, 250, persist=False)
    assert structure_column_minimum_width() == 300 + 28
    assert structure_column_minimum_width(zoomed=True) == 600 + 28


def test_structure_column_minimum_width_tracks_runtime_size() -> None:
    set_structure_depict_size(300, 250, persist=False)
    assert structure_column_minimum_width() == 300 + 28


def test_reaction_depict_size_is_wider_same_height() -> None:
    from molmanager.table.structure_depiction_layout import (
        REACTION_DEPICT_WIDTH_MULTIPLIER,
        reaction_depict_size,
    )

    set_structure_depict_size(200, 160, persist=False)
    w, h = reaction_depict_size()
    assert w == 200 * REACTION_DEPICT_WIDTH_MULTIPLIER
    assert h == 160
    zw, zh = reaction_depict_size(zoomed=True)
    assert zw == 400 * REACTION_DEPICT_WIDTH_MULTIPLIER
    assert zh == 320
    assert structure_depict_width() == 200
    assert structure_depict_height() == 160


def test_cell_resize_uses_one_scale_for_both_axes() -> None:
    # A horizontal drag scales height by the same fraction of the cell.
    width, height = structure_depict_size_for_cell_resize(210, 170, 238, 180, 40, 0)
    assert (width, height) == (round(210 * 278 / 238), round(170 * 278 / 238))
    # Extra column space scales with the picture. A 120 px shrink of a 500 px
    # cell does not collapse the drawing to the minimum.
    wide_w, wide_h = structure_depict_size_for_cell_resize(210, 170, 500, 180, -120, 0)
    assert (wide_w, wide_h) == (round(210 * 380 / 500), round(170 * 380 / 500))
    assert wide_w > MIN_STRUCTURE_DEPICT_WIDTH
    # A vertical drag scales width the same way.
    width, height = structure_depict_size_for_cell_resize(210, 170, 238, 180, 0, 36)
    assert (width, height) == (round(210 * 216 / 180), round(170 * 216 / 180))
    hi_w, hi_h = structure_depict_size_for_cell_resize(210, 170, 238, 180, 9999, 9999)
    assert hi_w == MAX_STRUCTURE_DEPICT_WIDTH
    assert hi_h == round(170 * MAX_STRUCTURE_DEPICT_WIDTH / 210)
    lo_w, lo_h = structure_depict_size_for_cell_resize(210, 170, 238, 180, -9999, -9999)
    assert lo_w == MIN_STRUCTURE_DEPICT_WIDTH
    assert lo_h == round(170 * MIN_STRUCTURE_DEPICT_WIDTH / 210)


def test_wide_structure_column_resize_does_not_collapse_the_depiction(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "CCO"})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(900, 360)
    view.show()
    QApplication.processEvents()
    col = CompoundTableModel.STRUCTURE_COL
    origin_w = structure_depict_width()
    origin_h = structure_depict_height()
    view.setColumnWidth(col, 500)
    QApplication.processEvents()
    hh = view.horizontalHeader()
    grip = int(hh.sectionViewportPosition(col)) + int(view.columnWidth(col)) - 2
    hh.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, QPoint(grip, 6), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    )
    hh.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, QPoint(grip, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    hh.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove, QPoint(grip - 120, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    QApplication.processEvents()
    assert structure_depict_width() == round(origin_w * 380 / 500)
    assert structure_depict_height() == round(origin_h * 380 / 500)
    assert structure_depict_width() > MIN_STRUCTURE_DEPICT_WIDTH
    hh.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(grip - 120, 6),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )
    view.deleteLater()


def test_row_border_resize_scales_depiction_width_and_height(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "CCO"})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(900, 360)
    view.show()
    QApplication.processEvents()
    origin_w = structure_depict_width()
    origin_h = structure_depict_height()
    origin_row = int(view.rowHeight(0))
    vh = view.verticalHeader()
    grip = int(vh.sectionViewportPosition(0)) + origin_row - 2
    vh.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, QPoint(8, grip), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    vh.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove, QPoint(8, grip + 36), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    QApplication.processEvents()
    assert structure_depict_width() == round(origin_w * (origin_row + 36) / origin_row)
    assert structure_depict_height() == round(origin_h * (origin_row + 36) / origin_row)
    vh.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(8, grip + 36),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )
    view.deleteLater()


def test_rendered_columns_scale_with_the_depiction_size(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent, QPixmap
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView
    from molmanager.ui.compound_table_view import StructureDelegate

    headers = ["ID_HIDDEN", "Structure", "Murcko Scaffold", "Reaction"]
    model = CompoundTableModel(headers)
    model.append_row(1, {"Murcko Scaffold": "C1CCCCC1", "Reaction": "C>>O"})
    model.register_pixmap_column("Murcko Scaffold")
    model.register_pixmap_column("Reaction")
    source_w, source_h = structure_depict_width(), structure_depict_height()
    model.note_pixmap_column_source_size("Murcko Scaffold", source_w, source_h)
    model.note_pixmap_column_source_size("Reaction", source_w, source_h)
    model.set_column_pixmap(1, "Murcko Scaffold", QPixmap(source_w, source_h))
    model.set_column_pixmap(1, "Reaction", QPixmap(source_w * 3, source_h))
    delegate = StructureDelegate(None, model)
    view = CompoundTableView()
    view.set_compound_model(model)
    view.setItemDelegate(delegate)
    view.resize(1100, 360)
    view.show()
    QApplication.processEvents()
    structure = CompoundTableModel.STRUCTURE_COL
    murcko = headers.index("Murcko Scaffold")
    reaction = headers.index("Reaction")
    view.setColumnWidth(structure, 400)
    view.setColumnWidth(murcko, 500)
    view.setColumnWidth(reaction, 700)
    QApplication.processEvents()
    hh = view.horizontalHeader()
    grip = int(hh.sectionViewportPosition(murcko)) + int(view.columnWidth(murcko)) - 2
    hh.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, QPoint(grip, 6), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    )
    hh.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, QPoint(grip, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    hh.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove, QPoint(grip - 120, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    QApplication.processEvents()
    new_w = round(source_w * 380 / 500)
    new_h = round(source_h * 380 / 500)
    assert (structure_depict_width(), structure_depict_height()) == (new_w, new_h)
    assert view.columnWidth(structure) == round(400 * new_w / source_w)
    assert view.columnWidth(reaction) == round(700 * new_w / source_w)
    murcko_pix = delegate._pixmap_for_cell(
        model.data(model.index(0, murcko), Qt.DecorationRole), model.index(0, murcko)
    )
    reaction_pix = delegate._pixmap_for_cell(
        model.data(model.index(0, reaction), Qt.DecorationRole), model.index(0, reaction)
    )
    assert (murcko_pix.width(), murcko_pix.height()) == (new_w, new_h)
    assert (reaction_pix.width(), reaction_pix.height()) == (new_w * 3, new_h)
    cell = view.visualRect(model.index(0, murcko))
    fitted = delegate._pixmap_inside_cell(murcko_pix, cell)
    assert fitted.width() <= max(1, cell.width() - 4)
    assert fitted.height() <= max(1, cell.height() - 4)
    hh.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(grip - 120, 6),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )
    view.deleteLater()
