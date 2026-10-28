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

"""Tests for CompoundTableModel (no full window required)."""

from __future__ import annotations

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPixmap

from molmanager.ui.compound_table_model import CompoundTableModel
from molmanager.ui.theme import set_table_text_alignment


@pytest.fixture()
def model(qapp):  # noqa: ARG001 — ensures QApplication exists for Qt types
    set_table_text_alignment("left", "center", persist=False)
    headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    m = CompoundTableModel(headers)
    return m


def test_append_row_and_oid_index(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "CC", "MW": "30.07"})
    assert model.rowCount() == 1
    assert model.row_oid(0) == 10
    assert model.logical_row_for_oid(10) == 0
    assert (model.cell_text(0, model._headers.index("SMILES")) or "") == "CC"


def test_oid_text_left_aligned_row_header_centered(model: CompoundTableModel):
    model.append_row(42, {"SMILES": "C", "MW": "16"})
    oid_idx = model.index(0, 0)
    assert model.data(oid_idx, Qt.DisplayRole) == "42"
    assert model.data(oid_idx, Qt.TextAlignmentRole) == int(Qt.AlignLeft | Qt.AlignVCenter)
    assert model.headerData(0, Qt.Vertical, Qt.TextAlignmentRole) == int(Qt.AlignCenter)
    assert model.headerData(0, Qt.Vertical, Qt.DisplayRole) == "1"


def test_table_cell_text_is_left_aligned(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "CCO", "MW": "46.07"})
    left = int(Qt.AlignLeft | Qt.AlignVCenter)
    smiles = model.index(0, model._headers.index("SMILES"))
    mw = model.index(0, model._headers.index("MW"))
    struct = model.index(0, CompoundTableModel.STRUCTURE_COL)
    assert model.data(smiles, Qt.TextAlignmentRole) == left
    assert model.data(mw, Qt.TextAlignmentRole) == left
    assert model.data(struct, Qt.TextAlignmentRole) == left


def test_table_cell_text_alignment_follows_runtime_setting(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "CCO", "MW": "46.07"})
    smiles = model.index(0, model._headers.index("SMILES"))
    set_table_text_alignment("right", "top", persist=False)
    assert model.data(smiles, Qt.TextAlignmentRole) == int(Qt.AlignRight | Qt.AlignTop)
    set_table_text_alignment("center", "bottom", persist=False)
    assert model.data(smiles, Qt.TextAlignmentRole) == int(Qt.AlignHCenter | Qt.AlignBottom)
    set_table_text_alignment("left", "center", persist=False)
    assert model.data(smiles, Qt.TextAlignmentRole) == int(Qt.AlignLeft | Qt.AlignVCenter)


def test_set_cell_text_updates_value(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "16"})
    model.set_cell_text(1, "MW", "16.043")
    sci = model._headers.index("SMILES")
    mwi = model._headers.index("MW")
    assert model.cell_text(0, mwi) == "16.043"
    assert model.cell_text(0, sci) == "C"


def test_set_cell_text_batch_updates_row(model: CompoundTableModel):
    model.append_row(7, {"SMILES": "CC", "MW": "30"})
    model.set_cell_text_batch(7, {"SMILES": "CCC", "MW": "44.1"})
    sci = model._headers.index("SMILES")
    mwi = model._headers.index("MW")
    assert model.cell_text(0, sci) == "CCC"
    assert model.cell_text(0, mwi) == "44.1"


def test_set_backing_text_updates_pixmap_column(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "Protonated"])
    model.append_row(1, {"Protonated": "CC(=O)O"})
    model.register_pixmap_column("Protonated")
    prot = model._headers.index("Protonated")
    assert model.cell_text(0, prot) == ""
    assert model.backing_value_for_row_header(0, "Protonated") == "CC(=O)O"
    model.set_cell_text(1, "Protonated", "CCO")
    assert model.backing_value_for_row_header(0, "Protonated") == "CC(=O)O"
    model.set_backing_text(1, "Protonated", "CCO")
    assert model.backing_value_for_row_header(0, "Protonated") == "CCO"
    assert model.cell_text(0, prot) == ""
    idx = model.index(0, prot)
    assert model.data(idx, Qt.DisplayRole) == "CCO"
    assert model.data(idx, Qt.DecorationRole) is None
    pix = QPixmap(16, 16)
    pix.fill(QColor(255, 255, 255))
    model.set_column_pixmap(1, "Protonated", pix)
    assert model.data(idx, Qt.DisplayRole) == ""
    assert model.data(idx, Qt.DecorationRole) is not None
    assert model.backing_value_for_row_header(0, "Protonated") == "CCO"


def test_numeric_bounds_by_column(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10"})
    model.append_row(1, {"SMILES": "CC", "MW": "20"})
    bounds = model.numeric_bounds_by_column()
    assert "MW" in bounds
    assert bounds["MW"]["min"] == 10.0
    assert bounds["MW"]["max"] == 20.0
    assert bounds["MW"]["is_int"] is True


def test_numeric_bounds_mixed_int_and_float_not_integer_column(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10"})
    model.append_row(1, {"SMILES": "CC", "MW": "20.5"})
    bounds = model.numeric_bounds_by_column()
    assert bounds["MW"]["min"] == 10.0
    assert bounds["MW"]["max"] == 20.5
    assert bounds["MW"]["is_int"] is False


def test_numeric_bounds_incremental_edit_matches_full_rescan(model: CompoundTableModel):
    model.append_row(0, {"SMILES": "C", "MW": "10", "LogP": "1"})
    model.append_row(1, {"SMILES": "CC", "MW": "20", "LogP": "2"})
    model.numeric_bounds_by_column()
    model.set_cell_text(0, "MW", "15")
    b1 = model.numeric_bounds_by_column()
    model._invalidate_numeric_bounds_all()
    b2 = model.numeric_bounds_by_column()
    assert b1 == b2
    assert b1["MW"] == {"min": 15.0, "max": 20.0, "is_int": True}


def test_column_text_by_oid(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "12"})
    model.append_row(2, {"SMILES": "CC", "MW": "30"})
    snap = model.column_text_by_oid("MW")
    assert snap == {1: "12", 2: "30"}


def test_duplicate_column_at_bulk_copy(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "10", "LogP": "1"})
    model.append_row(2, {"SMILES": "CC", "MW": "20", "LogP": "2"})
    model.duplicate_column_at(model.columnCount(), "MW (Copy)", model._headers.index("MW"))
    mwi = model._headers.index("MW (Copy)")
    assert model.cell_text(0, mwi) == "10"
    assert model.cell_text(1, mwi) == "20"


def test_duplicate_column_at_copies_pixmap_column(qapp):  # noqa: ARG001
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "Protonated"])
    model.append_row(1, {"Protonated": "CCO"})
    model.register_pixmap_column("Protonated")
    pix = QPixmap(8, 8)
    pix.fill(QColor(255, 255, 255))
    model.set_column_pixmap(1, "Protonated", pix)
    dest = model.columnCount()
    model.duplicate_column_at(dest, "Protonated (Copy)", model._headers.index("Protonated"))
    assert model.is_pixmap_data_column("Protonated (Copy)")
    assert model.backing_value_for_row_header(0, "Protonated (Copy)") == "CCO"
    copied = model.column_pixmap_copy(1, "Protonated (Copy)")
    assert copied is not None and not copied.isNull()


def test_remove_column_at_keeps_other_bounds_cache(model: CompoundTableModel):
    for i in range(50):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.insert_column_at(model.columnCount(), "Extra", None)
    for i in range(50):
        model.set_cell_text(i, model._headers.index("Extra"), str(float(i)))
    cache = model.numeric_bounds_by_column()
    mw_meta = cache["MW"]
    extra_col = model._headers.index("Extra")
    model.remove_column_at(extra_col)
    assert model._numeric_bounds_cache is not None
    assert "Extra" not in model._numeric_bounds_cache
    assert model._numeric_bounds_cache["MW"] == mw_meta


def test_insert_column_at_marks_only_new_bounds_dirty(model: CompoundTableModel):
    for i in range(50):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.numeric_bounds_by_column()
    model.insert_column_at(model.columnCount(), "LogP", None)
    assert model._numeric_bounds_cache is not None
    assert "LogP" in (model._numeric_bounds_dirty_cols or set())


def test_refresh_numeric_bounds_for_headers_scans_only_target(model: CompoundTableModel) -> None:
    for i in range(40):
        model.append_row(i, {"SMILES": "C", "MW": str(10 + i)})
    model.insert_column_at(model.columnCount(), "Extra", None)
    for i in range(40):
        model.set_cell_text(i, "Extra", str(float(i)))
    full = model.numeric_bounds_by_column()
    mw_before = full["MW"]
    model.refresh_numeric_bounds_for_headers(["Extra"])
    assert model._numeric_bounds_cache is not None
    assert model._numeric_bounds_cache["MW"] == mw_before
    assert model._numeric_bounds_cache["Extra"]["min"] == 0.0


def test_fill_column_from_oid_map_sets_default(model: CompoundTableModel) -> None:
    model.append_row(1, {"SMILES": "C", "MW": "1"})
    model.append_row(2, {"SMILES": "CC", "MW": "2"})
    model.insert_column_at(model.columnCount(), "Score", None)
    model.fill_column_from_oid_map("Score", {2: "0.9"}, default="N/A")
    assert model.cell_text(0, model._headers.index("Score")) == "N/A"
    assert model.cell_text(1, model._headers.index("Score")) == "0.9"


def test_apply_columns_values_bulk(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "10"})
    model.append_row(2, {"SMILES": "CC", "MW": "20"})
    model.insert_column_at(model.columnCount(), "LogP", None)
    model.apply_columns_values_bulk(
        ["MW", "LogP"],
        [(1, {"MW": "11", "LogP": "1.1"}), (2, {"MW": "22", "LogP": "2.2"})],
    )
    mwi = model._headers.index("MW")
    lpi = model._headers.index("LogP")
    assert model.cell_text(0, mwi) == "11"
    assert model.cell_text(1, mwi) == "22"
    assert model.cell_text(0, lpi) == "1.1"


def test_set_column_text_by_oids(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "C", "MW": "1"})
    model.append_row(11, {"SMILES": "CC", "MW": "2"})
    model.set_column_text_by_oids("MW", [(10, "3"), (11, "4")])
    mwi = model._headers.index("MW")
    assert model.cell_text(0, mwi) == "3"
    assert model.cell_text(1, mwi) == "4"


def test_numeric_gradient_column_coloring(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "C", "MW": "10"})
    model.append_row(11, {"SMILES": "CC", "MW": "20"})
    model.set_column_color_numeric_gradient(
        "MW",
        min_value=10.0,
        max_value=20.0,
        low_color=QColor(0, 0, 255),
        high_color=QColor(255, 0, 0),
        alpha=120,
    )
    idx_low = model.index(0, model._headers.index("MW"))
    idx_high = model.index(1, model._headers.index("MW"))
    c_low = model.data(idx_low, Qt.BackgroundRole)
    c_high = model.data(idx_high, Qt.BackgroundRole)
    assert isinstance(c_low, QColor)
    assert isinstance(c_high, QColor)
    assert c_low.alpha() == 120
    assert c_high.alpha() == 120
    assert c_low != c_high


def test_categorical_column_coloring_is_deterministic(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "1"})
    model.append_row(11, {"SMILES": "B", "MW": "2"})
    model.append_row(12, {"SMILES": "A", "MW": "3"})
    model.set_column_color_categorical("SMILES", alpha=100)
    sci = model._headers.index("SMILES")
    c1 = model.data(model.index(0, sci), Qt.BackgroundRole)
    c2 = model.data(model.index(1, sci), Qt.BackgroundRole)
    c3 = model.data(model.index(2, sci), Qt.BackgroundRole)
    assert isinstance(c1, QColor)
    assert isinstance(c2, QColor)
    assert isinstance(c3, QColor)
    assert c1.alpha() == 100 and c2.alpha() == 100 and c3.alpha() == 100
    assert c1 == c3
    assert c1 != c2


def test_three_point_gradient_column_coloring(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "0"})
    model.append_row(11, {"SMILES": "B", "MW": "50"})
    model.append_row(12, {"SMILES": "C", "MW": "100"})
    model.set_column_color_three_point_gradient(
        "MW",
        min_value=0.0,
        mid_value=50.0,
        max_value=100.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=110,
    )
    mwi = model._headers.index("MW")
    low = model.data(model.index(0, mwi), Qt.BackgroundRole)
    mid = model.data(model.index(1, mwi), Qt.BackgroundRole)
    high = model.data(model.index(2, mwi), Qt.BackgroundRole)
    assert isinstance(low, QColor) and isinstance(mid, QColor) and isinstance(high, QColor)
    assert low.alpha() == 110 and mid.alpha() == 110 and high.alpha() == 110
    assert low != mid and mid != high


def test_export_restore_column_color_rules(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "A", "MW": "1"})
    model.append_row(2, {"SMILES": "B", "MW": "9"})
    model.set_column_color_three_point_gradient(
        "MW",
        min_value=1.0,
        mid_value=5.0,
        max_value=9.0,
        low_color=QColor(0, 0, 255),
        mid_color=QColor(255, 255, 255),
        high_color=QColor(255, 0, 0),
        alpha=101,
    )
    saved = model.export_column_color_rules()
    model.clear_column_coloring("MW")
    model.restore_column_color_rules(saved)
    restored = model.column_color_rule_spec("MW")
    assert restored is not None
    assert restored.get("mode") == "numeric3"
    assert int(restored.get("alpha", 0)) == 101


def test_remove_rows_by_oids_bulk(model: CompoundTableModel):
    for oid, mw in ((1, "10"), (2, "20"), (3, "30")):
        model.append_row(oid, {"SMILES": "C", "MW": mw})
    removed = model.remove_rows_by_oids(frozenset({1, 3}))
    assert removed == 2
    assert model.rowCount() == 1
    assert model.row_oid(0) == 2
    assert model.logical_row_for_oid(1) < 0
    assert model.logical_row_for_oid(3) < 0


def test_remove_row_clears_structure_png_store(model: CompoundTableModel):
    from molmanager.storage.structure_render_store import StructureRenderStore

    model.append_row(5, {"SMILES": "CC", "MW": "30"})
    store = StructureRenderStore(max_decoded_pixmaps=8)
    store.ingest_png(5, b"png-5")
    model.set_structure_png_store(store)
    assert store.has_png(5)
    model.remove_row_at(0)
    assert not store.has_png(5)


def test_insert_rows_batch_restores_order(model: CompoundTableModel):
    model.append_row(10, {"SMILES": "A", "MW": "1"})
    model.append_row(30, {"SMILES": "C", "MW": "3"})
    model.remove_rows_by_oids(frozenset({10}))
    model.insert_rows_batch([(0, 10, {"SMILES": "A", "MW": "1"})])
    assert model.rowCount() == 2
    assert model.row_oid(0) == 10
    assert model.row_oid(1) == 30
    assert model.cell_text(0, model._headers.index("SMILES")) == "A"


def test_is_structure_paint_data_change(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "16"})
    struct = model.index(0, CompoundTableModel.STRUCTURE_COL)
    mw = model.index(0, model._headers.index("MW"))
    paint = list(CompoundTableModel.STRUCTURE_PAINT_ROLES)
    assert CompoundTableModel.is_structure_paint_data_change(struct, struct, paint)
    assert CompoundTableModel.is_structure_paint_data_change(struct, struct, ())
    assert (
        CompoundTableModel.is_structure_paint_data_change(
            mw, mw, [Qt.DisplayRole, Qt.EditRole, Qt.BackgroundRole]
        )
        is False
    )


def test_structure_paint_does_not_mark_sqlite_store_dirty(model: CompoundTableModel):
    from molmanager.ui.main_window.app_lifecycle_mixin import AppLifecycleMixin

    class _Host(AppLifecycleMixin):
        def __init__(self) -> None:
            self._table_model = model
            self._ingest_sqlite_paused_dirty = False
            self._sqlite_store = object()
            self._sqlite_store_dirty = False
            self._sqlite_rebuild_in_progress = False
            self._session_mutation_paused = False
            self._session_dirty = False
            self._wire_sqlite_store_dirty_tracking()

    model.append_row(1, {"SMILES": "C", "MW": "16"})
    host = _Host()
    model.notify_structure_column_changed(0, 0)
    assert host._sqlite_store_dirty is False
    assert host._session_dirty is False
    model.set_cell_text(1, "MW", "18")
    assert host._sqlite_store_dirty is True


def test_data_cells_are_not_inline_editable(model: CompoundTableModel):
    model.append_row(1, {"SMILES": "C", "MW": "16"})
    smiles = model.index(0, model._headers.index("SMILES"))
    assert not (model.flags(smiles) & Qt.ItemIsEditable)


def test_compound_table_view_disables_inline_edit_triggers(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QAbstractItemView

    from molmanager.ui.compound_table_model import CompoundTableView

    view = CompoundTableView()
    assert view.editTriggers() == QAbstractItemView.NoEditTriggers
    view.deleteLater()


def test_compound_table_view_pixel_scrolls_and_keeps_edge_grip(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QAbstractItemView, QApplication

    from molmanager.ui.compound_table_model import (
        CompoundTableHeaderView,
        CompoundTableModel,
        CompoundTableView,
    )

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    model.append_row(1, {"SMILES": "CCO"})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(800, 360)
    view.show()
    QApplication.processEvents()

    assert view.horizontalScrollMode() == QAbstractItemView.ScrollPerPixel
    assert view.verticalScrollMode() == QAbstractItemView.ScrollPerPixel
    hh = view.horizontalHeader()
    assert isinstance(hh, CompoundTableHeaderView)
    assert hh.stretchLastSection() is False
    assert hh.sectionsClickable() is True

    smiles = model._headers.index("SMILES")
    left = int(hh.sectionViewportPosition(smiles))
    vp_w = int(hh.viewport().width())
    view.setColumnWidth(smiles, max(40, vp_w - left))
    QApplication.processEvents()
    assert hh.section_for_viewport_right_grip(vp_w - 1) == smiles

    old_w = int(view.columnWidth(smiles))
    press = QMouseEvent(
        QEvent.MouseButtonPress,
        QPoint(vp_w - 1, 4),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    hh.mousePressEvent(press)
    move = QMouseEvent(
        QEvent.MouseMove,
        QPoint(max(1, vp_w - 80), 4),
        Qt.LeftButton,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    hh.mouseMoveEvent(move)
    release = QMouseEvent(
        QEvent.MouseButtonRelease,
        QPoint(max(1, vp_w - 80), 4),
        Qt.LeftButton,
        Qt.NoButton,
        Qt.NoModifier,
    )
    hh.mouseReleaseEvent(release)
    assert int(view.columnWidth(smiles)) < old_w

    view.setColumnWidth(smiles, 2400)
    view.updateGeometries()
    bar = view.horizontalScrollBar()
    length = int(hh.length())
    width = int(view.viewport().width())
    assert int(bar.maximum()) >= length - width
    view.deleteLater()


def test_header_drag_scroll_step_grows_toward_viewport_edge(qapp):  # noqa: ARG001
    from molmanager.ui.compound_table_view import (
        _HEADER_DRAG_SCROLL_MAX_STEP_PX,
        _HEADER_DRAG_SCROLL_MIN_STEP_PX,
        CompoundTableView,
    )

    view = CompoundTableView()
    view.resize(400, 240)
    hh = view.horizontalHeader()
    vp_w = 400
    hh.viewport().resize(vp_w, 24)
    assert hh._header_drag_scroll_step(vp_w // 2) == 0
    assert hh._header_drag_scroll_step(vp_w - 1) == 0
    right = hh._header_drag_scroll_step(vp_w)
    farther = hh._header_drag_scroll_step(vp_w + 40)
    assert right >= _HEADER_DRAG_SCROLL_MIN_STEP_PX
    assert farther > right
    assert farther <= _HEADER_DRAG_SCROLL_MAX_STEP_PX
    left = hh._header_drag_scroll_step(-1)
    assert left <= -_HEADER_DRAG_SCROLL_MIN_STEP_PX
    view.deleteLater()


def test_header_drag_autoscrolls_quickly_at_viewport_edge(qapp):
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    headers = ["ID_HIDDEN", "Structure"] + [f"C{i}" for i in range(16)]
    model = CompoundTableModel(headers)
    model.append_row(1, {f"C{i}": "x" for i in range(16)})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(420, 300)
    for col in range(2, model.columnCount()):
        view.setColumnWidth(col, 140)
    view.show()
    QApplication.processEvents()
    hh = view.horizontalHeader()
    if int(hh.viewport().width()) <= 0:
        hh.viewport().resize(400, 24)
    bar = view.horizontalScrollBar()
    assert bar.maximum() > 80
    hh._section_drag_active = True
    before = int(bar.value())
    hh._update_section_drag_scroll(int(hh.viewport().width()) + 30)
    for _ in range(4):
        hh._on_header_drag_scroll_tick()
    assert int(bar.value()) - before >= 80
    hh._stop_section_drag_scroll()
    assert not hh._section_drag_active
    assert not hh._section_drag_timer.isActive()
    view.deleteLater()


def test_structure_column_resize_past_header_does_not_scroll_the_table(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    headers = ["ID_HIDDEN", "Structure"] + [f"C{i}" for i in range(8)]
    model = CompoundTableModel(headers)
    model.append_row(1, {f"C{i}": "x" for i in range(8)})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(640, 320)
    for col in range(2, model.columnCount()):
        view.setColumnWidth(col, 160)
    view.show()
    QApplication.processEvents()
    hh = view.horizontalHeader()
    vpw = int(hh.viewport().width())
    view.setColumnWidth(1, max(80, vpw - 36))
    QApplication.processEvents()
    bar = view.horizontalScrollBar()
    assert int(bar.maximum()) > 40
    grip = int(hh.sectionViewportPosition(1)) + int(view.columnWidth(1)) - 2
    old_w = int(view.columnWidth(1))
    hh.mouseMoveEvent(
        QMouseEvent(QEvent.MouseMove, QPoint(grip, 6), Qt.NoButton, Qt.NoButton, Qt.NoModifier)
    )
    hh.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, QPoint(grip, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    hh.leaveEvent(QEvent(QEvent.Leave))
    hh.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove,
            QPoint(vpw + 48, 6),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    QApplication.processEvents()
    assert int(bar.value()) == 0
    assert int(view.columnWidth(1)) > old_w
    hh.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(vpw + 48, 6),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )
    view.deleteLater()


def test_header_column_drag_still_autoscrolls_from_section_body(qapp):
    from PyQt5.QtCore import QEvent, QPoint, Qt
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication

    from molmanager.ui.compound_table_model import CompoundTableModel, CompoundTableView

    headers = ["ID_HIDDEN", "Structure"] + [f"C{i}" for i in range(12)]
    model = CompoundTableModel(headers)
    model.append_row(1, {f"C{i}": "x" for i in range(12)})
    view = CompoundTableView()
    view.set_compound_model(model)
    view.resize(480, 280)
    for col in range(1, model.columnCount()):
        view.setColumnWidth(col, 140)
    view.show()
    QApplication.processEvents()
    hh = view.horizontalHeader()
    vpw = int(hh.viewport().width())
    if vpw <= 0:
        hh.viewport().resize(440, 24)
        vpw = 440
    bar = view.horizontalScrollBar()
    assert int(bar.maximum()) > 40
    col = 2
    mid = int(hh.sectionViewportPosition(col)) + int(view.columnWidth(col)) // 2
    assert 0 < mid < vpw - 24
    hh.mousePressEvent(
        QMouseEvent(
            QEvent.MouseButtonPress, QPoint(mid, 6), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier
        )
    )
    hh.mouseMoveEvent(
        QMouseEvent(
            QEvent.MouseMove,
            QPoint(vpw + 36, 6),
            Qt.LeftButton,
            Qt.LeftButton,
            Qt.NoModifier,
        )
    )
    assert int(bar.value()) > 0
    hh.mouseReleaseEvent(
        QMouseEvent(
            QEvent.MouseButtonRelease,
            QPoint(vpw + 36, 6),
            Qt.LeftButton,
            Qt.NoButton,
            Qt.NoModifier,
        )
    )
    view.deleteLater()


def test_table_header_stylesheet_uses_palette_roles(qapp):  # noqa: ARG001
    from molmanager.ui.compound_table_view import TABLE_HEADER_SECTION_QSS, CompoundTableView

    qss = TABLE_HEADER_SECTION_QSS.lower()
    assert "palette(button)" in qss
    assert "palette(button-text)" in qss
    view = CompoundTableView()
    assert "palette(button)" in view.horizontalHeader().styleSheet().lower()
    assert "palette(button)" in view.verticalHeader().styleSheet().lower()
    view.deleteLater()


def test_compound_table_headers_follow_application_palette(qapp):
    from PyQt5.QtGui import QColor, QPalette

    from molmanager.ui.compound_table_view import CompoundTableView

    prev = qapp.palette()
    view = CompoundTableView()
    try:
        pal = QPalette(prev)
        pal.setColor(QPalette.Button, QColor("#112233"))
        pal.setColor(QPalette.ButtonText, QColor("#c0ffee"))
        qapp.setPalette(pal)
        view.refresh_theme()
        hh = view.horizontalHeader()
        vh = view.verticalHeader()
        assert hh.palette().color(QPalette.Button).name() == "#112233"
        assert hh.viewport().palette().color(QPalette.Button).name() == "#112233"
        assert vh.palette().color(QPalette.Button).name() == "#112233"
        pal.setColor(QPalette.Button, QColor("#445566"))
        qapp.setPalette(pal)
        view.refresh_theme()
        assert hh.palette().color(QPalette.Button).name() == "#445566"
        assert vh.palette().color(QPalette.Button).name() == "#445566"
    finally:
        qapp.setPalette(prev)
        view.deleteLater()


def test_compound_table_headers_resize_with_table_font(qapp):  # noqa: ARG001
    from PyQt5.QtGui import QFont

    from molmanager.ui.compound_table_view import CompoundTableView

    view = CompoundTableView()
    small = QFont(view.font())
    small.setPointSize(8)
    large = QFont(view.font())
    large.setPointSize(24)
    view.apply_table_font(small)
    h_small = int(view.horizontalHeader().height())
    w_small = int(view.verticalHeader().width())
    view.apply_table_font(large)
    h_large = int(view.horizontalHeader().height())
    w_large = int(view.verticalHeader().width())
    assert h_large > h_small
    assert w_large > w_small
    view.apply_table_font(small)
    assert int(view.horizontalHeader().height()) == h_small
    assert int(view.verticalHeader().width()) == w_small
    view.deleteLater()


def test_row_number_column_width_matches_final_count_on_bulk_insert(qapp):  # noqa: ARG001
    """A silent file-load insert must widen the row numbers before any later font pass."""
    from PyQt5.QtGui import QFont

    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.compound_table_view import CompoundTableView, header_bar_extent_for_font
    from molmanager.ui.filter_proxy_model import FilterProxyModel

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SMILES"])
    view = CompoundTableView()
    proxy = FilterProxyModel()
    proxy.setSourceModel(model)
    view.setModel(proxy)
    font = QFont(view.font())
    font.setPointSize(10)
    view.apply_table_font(font)
    empty_width = int(view.verticalHeader().width())

    model.begin_silent_appends()
    model.append_columns_batch(list(range(1, 5001)), {"SMILES": ["C"] * 5000})
    assert int(view.verticalHeader().width()) == empty_width
    model.end_silent_appends()

    vh = view.verticalHeader()
    fitted = header_bar_extent_for_font(vh, vh.font())
    assert fitted > empty_width
    assert int(vh.width()) == fitted
    assert int(vh.minimumWidth()) == fitted
    assert int(vh.maximumWidth()) == fitted
    view.deleteLater()
