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
    MAX_STRUCTURE_DEPICT_HEIGHT,
    MAX_STRUCTURE_DEPICT_WIDTH,
    MIN_STRUCTURE_DEPICT_HEIGHT,
    MIN_STRUCTURE_DEPICT_WIDTH,
    set_structure_depict_size,
    structure_column_minimum_width,
    structure_column_width_for_depict_scale,
    structure_depict_height,
    structure_depict_size_for_corner_drag,
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


def test_corner_drag_scales_width_with_picture_and_height_one_to_one() -> None:
    width, height = structure_depict_size_for_corner_drag(210, 170, 210, 40, -15)
    assert (width, height) == (250, 155)
    # A reaction picture is three times as wide, so the same pointer motion
    # changes the shared molecule size by a third.
    width, height = structure_depict_size_for_corner_drag(210, 170, 630, 63, 0)
    assert (width, height) == (231, 170)
    assert structure_depict_size_for_corner_drag(210, 170, 210, 9999, 9999) == (
        MAX_STRUCTURE_DEPICT_WIDTH,
        MAX_STRUCTURE_DEPICT_HEIGHT,
    )
    assert structure_depict_size_for_corner_drag(210, 170, 210, -9999, -9999) == (
        MIN_STRUCTURE_DEPICT_WIDTH,
        MIN_STRUCTURE_DEPICT_HEIGHT,
    )


def test_column_width_keeps_slack_while_depiction_scales() -> None:
    # 210 px picture + 28 px padding, plus 40 px the user added.
    assert structure_column_width_for_depict_scale(278, 210, 210, 250) == 318
    # No slack: the column grows by the same number of pixels as the picture.
    assert structure_column_width_for_depict_scale(238, 210, 210, 250) == 278


def _dark_corner_pixels(view, rect) -> int:
    image = view.viewport().grab().toImage()
    dark = 0
    for x in range(rect.right() - 5, rect.right() + 1):
        for y in range(rect.bottom() - 5, rect.bottom() + 1):
            color = image.pixelColor(x, y)
            if color.red() < 80 and color.green() < 80 and color.blue() < 80:
                dark += 1
    return dark


def _corner_mouse(kind, local, global_pos, button, buttons):
    from PyQt5.QtCore import QPointF, Qt
    from PyQt5.QtGui import QMouseEvent

    return QMouseEvent(
        kind, QPointF(local), QPointF(global_pos), button, buttons, Qt.NoModifier
    )


def test_structure_column_corner_drag_resizes_depiction(qapp):  # noqa: ARG001
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView
    from molmanager.ui.compound_table_view import scaled_structure_pixmap

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "CCO"})
    model.append_row(2, {"SMILES": "CCN"})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(900, 420)
    view.show()
    QApplication.processEvents()
    col = CompoundTableModel.STRUCTURE_COL
    origin_w = structure_depict_width()
    origin_h = structure_depict_height()
    view.setColumnWidth(col, structure_column_minimum_width())
    view.viewport().update()
    QApplication.processEvents()

    rect = view.structure_cell_corner_rect(0, col)
    lower = view.structure_cell_corner_rect(1, col)
    assert rect is not None and lower is not None
    assert lower.top() > rect.bottom()
    header = view.horizontalHeader()
    column_right = int(header.sectionViewportPosition(col)) + int(view.columnWidth(col)) - 1
    assert column_right - 2 <= rect.right() <= column_right
    assert rect.width() == 16
    assert view.structure_cell_corner_rect(0, 0) is None
    assert view.structure_cell_corner_rect(0, model._headers.index("SMILES")) is None
    assert _dark_corner_pixels(view, rect) >= 4
    assert _dark_corner_pixels(view, lower) >= 4

    chosen: list[tuple[int, int]] = []
    view.structure_depict_resized.connect(lambda w, h: chosen.append((int(w), int(h))))
    local = rect.center()
    origin = view.viewport().mapToGlobal(local)
    press = _corner_mouse(
        QEvent.MouseButtonPress, local, origin, Qt.LeftButton, Qt.LeftButton
    )
    assert view.viewportEvent(press)
    moved = local + QPoint(40, 20)
    move = _corner_mouse(
        QEvent.MouseMove,
        moved,
        origin + QPoint(40, 20),
        Qt.LeftButton,
        Qt.LeftButton,
    )
    assert view.viewportEvent(move)
    assert structure_depict_width() == origin_w + 40
    assert structure_depict_height() == origin_h + 20
    assert view.columnWidth(col) == structure_column_minimum_width()
    assert view.rowHeight(0) == structure_row_default_height()
    assert view.rowHeight(1) == structure_row_default_height()
    assert chosen == []
    delegate = view.itemDelegateForColumn(col)
    live = delegate._pixmap_for_cell(QPixmap(origin_w, origin_h))
    assert live.width() == origin_w + 40
    assert live.height() == origin_h + 20

    release = _corner_mouse(
        QEvent.MouseButtonRelease,
        moved,
        origin + QPoint(40, 20),
        Qt.LeftButton,
        Qt.NoButton,
    )
    assert view.viewportEvent(release)
    assert chosen == [(origin_w + 40, origin_h + 20)]
    assert view.structure_depict_resize_active() is False

    picture = scaled_structure_pixmap(
        QPixmap(origin_w, origin_h),
        origin_w,
        origin_h,
        origin_w + 40,
        origin_h + 20,
    )
    assert picture.width() == origin_w + 40
    assert picture.height() == origin_h + 20
    view.deleteLater()


def test_structure_column_corner_drag_cancel_restores_size(qapp):  # noqa: ARG001
    from PyQt5.QtCore import QEvent, QPointF, Qt
    from PyQt5.QtGui import QKeyEvent
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
    origin_col = structure_column_minimum_width()
    view.setColumnWidth(col, origin_col)
    QApplication.processEvents()
    origin_row = view.rowHeight(0)
    rect = view.structure_cell_corner_rect(0, col)
    assert rect is not None
    local = rect.center()
    origin = view.viewport().mapToGlobal(local)
    assert view.viewportEvent(
        _corner_mouse(QEvent.MouseButtonPress, local, origin, Qt.LeftButton, Qt.LeftButton)
    )
    assert view.viewportEvent(
        _corner_mouse(
            QEvent.MouseMove,
            local + QPointF(30, 40),
            origin + QPointF(30, 40),
            Qt.LeftButton,
            Qt.LeftButton,
        )
    )
    assert structure_depict_width() == origin_w + 30
    assert structure_depict_height() == origin_h + 40
    assert view.rowHeight(0) != origin_row
    chosen: list[tuple[int, int]] = []
    view.structure_depict_resized.connect(lambda w, h: chosen.append((w, h)))
    view.keyPressEvent(QKeyEvent(QEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    assert structure_depict_width() == origin_w
    assert structure_depict_height() == origin_h
    assert view.columnWidth(col) == origin_col
    assert view.rowHeight(0) == origin_row
    assert chosen == []
    assert view.structure_depict_resize_active() is False
    view.deleteLater()


def test_pixmap_column_has_a_corner_grip(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "CCO"})
    model.register_pixmap_column("SMILES")
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(900, 360)
    view.show()
    QApplication.processEvents()
    smiles = model._headers.index("SMILES")
    view.setColumnWidth(smiles, 160)
    QApplication.processEvents()
    view.viewport().update()
    QApplication.processEvents()
    rect = view.structure_cell_corner_rect(0, smiles)
    assert rect is not None
    assert _dark_corner_pixels(view, rect) >= 4
    view.deleteLater()
