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

"""Tests for the Predict SOM results browser."""

from __future__ import annotations

from molmanager.predictions.som_prediction import (
    SOM_CANCELLED_ERROR,
    SOM_MAP_COLUMN,
    SOM_P1_SITES_COLUMN,
    SOM_P2_SITES_COLUMN,
    SOM_PHASE_COLUMN,
    SOM_PROB_COLUMN,
    SOM_SITES_COLUMN,
    SomAtomHit,
    is_som_map_header,
)
from molmanager.ui.dockable_plot import is_dockable_workspace_widget
from molmanager.ui.som_browser import (
    SomBrowseRecord,
    SomBrowserDialog,
    SomBrowserWidget,
    SomColorScaleWidget,
    records_from_worker_rows,
)


def test_records_from_worker_rows_maps_atoms() -> None:
    rows = [
        (
            7,
            {SOM_MAP_COLUMN: "CCO", SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
            b"",
            [SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)],
            [SOM_MAP_COLUMN],
        ),
        (
            None,
            {SOM_MAP_COLUMN: "Empty SMILES."},
            None,
            [],
            [SOM_MAP_COLUMN],
        ),
    ]
    recs = records_from_worker_rows(rows)
    assert len(recs) == 2
    assert recs[0].oid == 7
    assert recs[0].smiles == "CCO"
    assert recs[0].atoms[0].is_som
    assert recs[0].error is None
    assert recs[1].oid is None
    assert recs[1].error == "Empty SMILES."
    assert recs[1].smiles == ""


def test_records_from_worker_rows_omits_cancelled() -> None:
    rows = [
        (
            1,
            {SOM_MAP_COLUMN: "CCO", SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
            b"",
            [SomAtomHit(0, 0.9, True)],
            [SOM_MAP_COLUMN],
        ),
        (
            2,
            {SOM_MAP_COLUMN: SOM_CANCELLED_ERROR},
            None,
            [],
            [SOM_MAP_COLUMN],
        ),
    ]
    recs = records_from_worker_rows(rows)
    assert len(recs) == 1
    assert recs[0].oid == 1
    all_recs = records_from_worker_rows(rows, include_cancelled=True)
    assert len(all_recs) == 2
    assert all_recs[1].error == SOM_CANCELLED_ERROR


def test_som_browser_widget_is_workspace_dockable():
    assert getattr(SomBrowserWidget, "dockable_in_workspace", False) is True
    assert is_dockable_workspace_widget(SomBrowserWidget)
    assert hasattr(SomBrowserWidget, "create_floating_dialog")
    assert getattr(SomBrowserWidget, "supports_floating_title", True) is False
    assert not hasattr(SomBrowserWidget, "_toggle_options_visible")
    assert not hasattr(SomBrowserWidget, "_prop_panel")


def test_som_browser_steps_between_maps(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)),
            columns={SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
        ),
        SomBrowseRecord(
            oid=2,
            smiles="c1ccccc1",
            atoms=(SomAtomHit(0, 0.2, False),),
            columns={SOM_SITES_COLUMN: "—", SOM_PROB_COLUMN: "0:0.20"},
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w._btn_back.text() == ""
    assert w._btn_fwd.text() == ""
    assert w._btn_select.text() == ""
    assert not w._btn_back.icon().isNull()
    assert not w._btn_fwd.icon().isNull()
    assert not w._btn_select.icon().isNull()
    assert "1 / 2" in w._meta.text()
    assert w._atom_table.rowCount() == 2
    atom_h = w._atom_table.height()
    w._step(1)
    assert "2 / 2" in w._meta.text()
    assert w._atom_table.rowCount() == 1
    assert w._atom_table.height() == atom_h
    w._go_first()
    assert "1 / 2" in w._meta.text()
    w.close()


def test_som_browser_emphasizes_selected_atom(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)),
            columns={SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w._emphasized_atom is None
    w._atom_table.selectRow(1)
    assert w._emphasized_atom == 1
    w._atom_table.clearSelection()
    assert w._emphasized_atom is None
    w.close()


def test_som_browser_has_color_scale(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.9, True), SomAtomHit(1, 0.1, False)),
            columns={SOM_SITES_COLUMN: "0", SOM_PROB_COLUMN: "0:0.90"},
        ),
        SomBrowseRecord(
            oid=2,
            smiles="CCO",
            atoms=(
                SomAtomHit(0, 0.9, True, is_phase1_som=True, is_phase2_som=False),
                SomAtomHit(1, 0.8, True, is_phase1_som=False, is_phase2_som=True),
            ),
            columns={
                SOM_SITES_COLUMN: "0, 1",
                SOM_P1_SITES_COLUMN: "0",
                SOM_P2_SITES_COLUMN: "1",
                SOM_PROB_COLUMN: "0:0.90; 1:0.80",
            },
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w._color_scale.parent() is w._preview_host
    assert w._struct_label.parent() is w._preview_host
    assert not w._color_scale.isHidden()
    w._step(1)
    assert not w._color_scale.isHidden()
    w.close()


def test_som_browser_preview_fits_label(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="c1ccccc1O",
            atoms=(SomAtomHit(0, 0.91, True), SomAtomHit(6, 0.40, True)),
        ),
    ]
    dlg = SomBrowserDialog(None)
    dlg.set_records(recs)
    dlg.show()
    qapp.processEvents()
    w = dlg._panel
    w._refresh_preview()
    pm = w._struct_label.pixmap()
    assert pm is not None and not pm.isNull()
    dpr = max(1.0, float(pm.devicePixelRatio()))
    assert abs(pm.width() / dpr - w._struct_label.width()) <= 1
    assert abs(pm.height() / dpr - w._struct_label.height()) <= 1
    assert w._color_scale.height() == w._struct_label.height()
    assert w._color_scale.y() == w._struct_label.y()
    dlg.close()


def test_som_color_scale_widget_paints(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap

    w = SomColorScaleWidget()
    w.resize(68, 200)
    pm = QPixmap(w.size())
    pm.fill(Qt.transparent)
    w.render(pm)
    assert not pm.isNull()
    w.close()


def test_som_browser_shows_phase_column(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(
                SomAtomHit(0, 0.9, True, is_phase1_som=True, is_phase2_som=False),
                SomAtomHit(1, 0.8, True, is_phase1_som=False, is_phase2_som=True),
            ),
            columns={
                SOM_SITES_COLUMN: "0, 1",
                SOM_P1_SITES_COLUMN: "0",
                SOM_P2_SITES_COLUMN: "1",
                SOM_PROB_COLUMN: "0:0.90; 1:0.80",
            },
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w._atom_table.columnCount() == 5
    assert w._atom_table.horizontalHeaderItem(3).text() == "Phase"
    assert w._atom_table.item(0, 3).text() == "P1"
    assert w._atom_table.item(1, 3).text() == "P2"
    w.close()


def test_som_browser_atom_table_sorts_numerically(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt

    recs = [
        SomBrowseRecord(
            oid=1,
            smiles="CCO",
            atoms=(
                SomAtomHit(2, 0.10, False),
                SomAtomHit(10, 0.90, True),
                SomAtomHit(3, 0.50, True),
            ),
        ),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    table = w._atom_table
    assert table.isSortingEnabled()
    assert [table.item(r, 0).text() for r in range(3)] == ["10", "3", "2"]
    table.sortItems(0, Qt.AscendingOrder)
    assert [table.item(r, 0).text() for r in range(3)] == ["2", "3", "10"]
    table.sortItems(1, Qt.DescendingOrder)
    assert [table.item(r, 0).text() for r in range(3)] == ["10", "3", "2"]
    table.sortItems(2, Qt.AscendingOrder)
    assert [table.item(r, 2).text() for r in range(3)] == ["", "yes", "yes"]
    w.close()


def test_is_som_map_header() -> None:
    assert is_som_map_header("SOM Map")
    assert is_som_map_header("SOM Map 2")
    assert not is_som_map_header("SOM Sites")
    assert not is_som_map_header("Structure")


def test_atoms_from_som_columns_parses_phase_sites() -> None:
    from molmanager.ui.som_browser import _atoms_from_som_columns

    hits = _atoms_from_som_columns(
        {
            SOM_SITES_COLUMN: "0, 1",
            SOM_PROB_COLUMN: "0:0.90; 1:0.80",
            SOM_P1_SITES_COLUMN: "0",
            SOM_P2_SITES_COLUMN: "1",
            SOM_PHASE_COLUMN: "0:P1; 1:P2",
        }
    )
    by_id = {h.atom_id: h for h in hits}
    assert by_id[0].is_som and by_id[0].is_phase1_som
    assert by_id[1].is_phase2_som and not by_id[1].is_phase1_som


def test_som_browse_session_payload_roundtrip() -> None:
    from molmanager.ui.som_browser import (
        deserialize_som_browse_records,
        serialize_som_browse_records,
    )

    recs = [
        SomBrowseRecord(
            oid=4,
            smiles="CCO",
            atoms=(SomAtomHit(0, 0.91, True, is_phase1_som=True, is_phase2_som=False),),
        )
    ]
    raw = serialize_som_browse_records(recs)
    back = deserialize_som_browse_records(raw)
    assert len(back) == 1
    assert back[0].oid == 4
    assert back[0].smiles == "CCO"
    assert back[0].atoms[0].probability == 0.91
    assert back[0].atoms[0].is_phase1_som is True


def test_som_browser_jump_to_oid(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(oid=1, smiles="CCO", atoms=(SomAtomHit(0, 0.9, True),)),
        SomBrowseRecord(oid=2, smiles="c1ccccc1", atoms=(SomAtomHit(0, 0.2, False),)),
    ]
    w = SomBrowserWidget(None)
    w.set_records(recs)
    assert w.jump_to_oid(2) is True
    assert w._current() is not None and w._current().oid == 2
    w.close()


class _StoreApp:
    def __init__(self, selected: set[int]) -> None:
        from molmanager.ui.selection_store import SelectionStore

        self.selection_store = SelectionStore()
        self.selection_store.set(selected)


def test_som_browser_only_selected_filters(qapp) -> None:  # noqa: ARG001
    recs = [
        SomBrowseRecord(oid=1, smiles="CCO", atoms=(SomAtomHit(0, 0.9, True),)),
        SomBrowseRecord(oid=2, smiles="c1ccccc1", atoms=(SomAtomHit(0, 0.2, False),)),
    ]
    w = SomBrowserWidget(_StoreApp({2}))
    w.set_records(recs)
    assert w._cb_only_selected.text() == "Browse Only Selected"
    assert w._cb_only_selected.parent() is w._nav_bar
    assert w._meta.parent() is w._footer_bar
    assert not hasattr(w, "_close_btn")
    foot = w._footer_bar.layout()
    dock_idx = foot.indexOf(w._add_to_main_btn)
    send_idx = foot.indexOf(w._send_window_btn)
    meta_idx = foot.indexOf(w._meta)
    assert meta_idx == 0
    assert dock_idx > meta_idx
    assert send_idx > dock_idx
    root = w.layout()
    assert root.indexOf(w._footer_bar) == 0
    assert root.indexOf(w._nav_bar) > root.indexOf(w._atom_table)
    w._cb_only_selected.setChecked(True)
    assert [r.oid for r in w._records] == [2]
    w._cb_only_selected.setChecked(False)
    assert [r.oid for r in w._records] == [1, 2]
    w.close()


def test_som_browser_rescopes_on_store_change(qapp) -> None:  # noqa: ARG001
    """Large / plot-made selections reach the browser via the store, not Qt selection."""
    app = _StoreApp({2})
    w = SomBrowserWidget(app)
    w.set_records(
        [
            SomBrowseRecord(oid=1, smiles="CCO", atoms=(SomAtomHit(0, 0.9, True),)),
            SomBrowseRecord(oid=2, smiles="c1ccccc1", atoms=(SomAtomHit(0, 0.2, False),)),
        ]
    )
    w._cb_only_selected.setChecked(True)
    app.selection_store.set({1})
    w._selection_timer.timeout.emit()
    assert [r.oid for r in w._records] == [1]
    w.close()


def test_som_browser_dialog_set_records_without_panel(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.som_browser import SomBrowserDialog

    dlg = SomBrowserDialog(None)
    dlg._panel = None
    dlg.set_records([])
    dlg.close()


def test_som_browser_nav_shortcuts_are_widget_scoped(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QShortcut

    w = SomBrowserWidget(None)
    scs = w.findChildren(QShortcut)
    assert scs
    assert all(sc.context() == Qt.WidgetWithChildrenShortcut for sc in scs)
    w.close()


def test_discard_host_dialog_after_dock_clears_attr(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QDialog

    from molmanager.ui.dockable_plot import discard_host_dialog_after_dock

    class Host:
        _dlg = None

    host = Host()
    dlg = QDialog()
    dlg._panel = object()
    dlg._force_close = False
    host._dlg = dlg
    discard_host_dialog_after_dock(dlg, host, "_dlg")
    assert host._dlg is None
    qapp.processEvents()


def test_pixmap_column_size_hint_matches_image(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QStyleOptionViewItem

    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.table_selection_delegate import RowHighlightDelegate

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SOM Map"])
    model.append_row(1, {})
    model.register_pixmap_column("SOM Map")
    pm = QPixmap(80, 60)
    pm.fill(Qt.white)
    model.set_column_pixmap(1, "SOM Map", pm)
    delegate = RowHighlightDelegate(model)
    idx = model.index(0, 2)
    assert delegate._index_is_pixmap_column(idx)
    assert delegate._cell_has_pixmap(idx)
    hint = delegate.sizeHint(QStyleOptionViewItem(), idx)
    assert hint.width() >= 80
    assert hint.height() >= 60


def test_empty_som_map_cells_skip_pixmap_background(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap
    from PyQt5.QtWidgets import QStyleOptionViewItem

    from molmanager.table.structure_depiction_layout import structure_depict_height
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.table_selection_delegate import RowHighlightDelegate

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "SOM Map"])
    model.append_row(1, {})
    model.append_row(2, {})
    model.register_pixmap_column("SOM Map")
    pm = QPixmap(80, 60)
    pm.fill(Qt.white)
    model.set_column_pixmap(1, "SOM Map", pm)
    delegate = RowHighlightDelegate(model)
    populated = model.index(0, 2)
    empty = model.index(1, 2)
    assert delegate._index_is_pixmap_column(populated)
    assert delegate._index_is_pixmap_column(empty)
    assert delegate._cell_has_pixmap(populated)
    assert not delegate._cell_has_pixmap(empty)
    empty_hint = delegate.sizeHint(QStyleOptionViewItem(), empty)
    populated_hint = delegate.sizeHint(QStyleOptionViewItem(), populated)
    assert populated_hint.height() >= 60
    assert empty_hint.height() < populated_hint.height()
    assert empty_hint.height() < structure_depict_height()


def test_som_map_export_filename() -> None:
    from molmanager.ui.main_window.tools_sql_predict_mixin import som_map_export_filename

    assert som_map_export_filename(12) == "SOM_Map_12.png"
    assert som_map_export_filename(3, "SOM Map 2") == "SOM_Map_2_3.png"


def test_save_som_map_pixmap(tmp_path, qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtGui import QPixmap

    from molmanager.ui.main_window.tools_sql_predict_mixin import save_som_map_pixmap

    pm = QPixmap(24, 16)
    pm.fill(Qt.red)
    dest = tmp_path / "map"
    written = save_som_map_pixmap(pm, str(dest))
    assert written == str(dest) + ".png"
    data = dest.with_suffix(".png").read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert save_som_map_pixmap(QPixmap(), str(tmp_path / "empty.png")) is None
