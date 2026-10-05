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

"""Main-window mixin smoke tests (clear_all, selection, chemistry sources)."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow


def _seed_two_rows(w: ChemistryWorkspaceWindow) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CCO", "MW": "46.07"})
    w._table_model.append_row(1, {"SMILES": "CC", "MW": "30.07"})
    w.mols[0] = Chem.MolFromSmiles("CCO")
    w.mols[1] = Chem.MolFromSmiles("CC")
    w.next_oid = 2


def test_cold_start_shows_idle_loading_page(qapp):  # noqa: ARG001
    from molmanager.ui.strings import LOADING_DETAIL_IDLE

    w = ChemistryWorkspaceWindow()
    assert w._table_stack.currentIndex() == 0
    assert w._loading_detail.text() == LOADING_DETAIL_IDLE
    assert w._ingest_loading is False


def test_clear_all_resets_table_and_ingest_flags(qapp):  # noqa: ARG001
    from molmanager.ui.strings import LOADING_DETAIL_IDLE

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._reveal_workspace_ready()
    w._selected_oids_override = frozenset({0})

    w.clear_all()

    assert w._table_model.rowCount() == 0
    assert w.mols == {}
    assert w.headers == []
    assert w.next_oid == 0
    assert w._selected_oids_override is None
    assert w._ingest_loading is False
    assert w._table_stack.currentIndex() == 0
    assert w._loading_detail.text() == LOADING_DETAIL_IDLE


def test_clear_all_keeps_loading_overlay_during_open(qapp):  # noqa: ARG001
    """Session/file open sets the overlay before clear_all; do not flash the empty table."""
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._set_workspace_stack_index(0)

    w.clear_all()

    assert w._ingest_loading is True
    assert w._table_stack.currentIndex() == 0


def test_exit_save_prompt_skipped_when_clean(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    w = ChemistryWorkspaceWindow()
    w._suppress_exit_session_prompt = False
    assert not w._session_has_unsaved_changes()

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        return QMessageBox.Cancel

    monkeypatch.setattr(QMessageBox, "question", boom)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert called["n"] == 0
    assert ev.isAccepted()


def test_exit_save_prompt_shown_when_dirty(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    w = ChemistryWorkspaceWindow()
    w._suppress_exit_session_prompt = False
    _seed_two_rows(w)
    w._mark_session_dirty()
    assert w._session_has_unsaved_changes()

    called = {"n": 0}

    def discard(*_a, **_k):
        called["n"] += 1
        return QMessageBox.Discard

    monkeypatch.setattr(QMessageBox, "question", discard)
    monkeypatch.setattr(w, "_prepare_application_shutdown", lambda: None)
    ev = QCloseEvent()
    w.closeEvent(ev)
    assert called["n"] == 1
    assert ev.isAccepted()


def test_save_session_clears_dirty(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._mark_session_dirty()
    out = tmp_path / "t.cms"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "MolManager Session (*.cms)"),
    )
    assert w.save_session_as() is True
    assert w.threadpool.waitForDone(60_000)
    qapp.processEvents()
    assert not w._session_has_unsaved_changes()


def test_file_session_submenu_lists_session_actions(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "File")
    file_labels = [a.text().replace("&", "") for a in file_menu.actions() if a.text().strip()]
    assert "Session" in file_labels
    assert "Open Session…" not in file_labels
    assert "Save Session…" not in file_labels
    session_menu = next(
        a.menu() for a in file_menu.actions() if a.text().replace("&", "") == "Session"
    )
    session_labels = [a.text().replace("&", "") for a in session_menu.actions() if a.text().strip()]
    assert session_labels == [
        "Open Session…",
        "Save Session…",
        "Save Selected to Session…",
        "New Session",
        "Duplicate Session",
    ]


def test_save_selected_to_session_writes_subset_without_clearing_dirty(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog

    from molmanager.table.session_codec import expand_session_document, loads_session_bytes

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({1})
    w._mark_session_dirty()
    out = tmp_path / "selected.cms"
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(out), "MolManager Session (*.cms)"),
    )
    assert w.save_selected_to_session() is True
    assert w.threadpool.waitForDone(60_000)
    qapp.processEvents()
    assert w._session_has_unsaved_changes()
    doc = expand_session_document(loads_session_bytes(out.read_bytes()))
    assert [row["id"] for row in doc["rows"]] == [1]


def test_save_selected_to_session_requires_selection(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog, QMessageBox

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    seen: dict[str, str] = {}

    def fake_info(_parent, title, text):
        seen["title"] = title
        seen["text"] = text

    monkeypatch.setattr(QMessageBox, "information", fake_info)
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("dialog should not open")),
    )
    assert w.save_selected_to_session() is False
    assert seen["title"] == "Save Selected to Session"
    assert "No rows are selected" in seen["text"]


def test_session_load_uses_loading_page_then_reveals(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemistryWorkspaceWindow()
    doc = {
        "format": "molmanager_session",
        "version": w._SESSION_VERSION,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
        "rows": [{"id": 0, "cells": {"SMILES": "CCO", "MW": "46"}}],
        "next_oid": 1,
        "filter_panel_visible": True,
    }
    seen = {"loading": False, "filters_covered": False}

    orig_begin = w._begin_session_finalize
    orig_filters = w._finalize_session_filters

    def wrap_begin(d, max_id, *, gen):
        seen["loading"] = w._table_stack.currentWidget() is w._loading_page
        return orig_begin(d, max_id, gen=gen)

    def wrap_filters(d, max_id):
        orig_filters(d, max_id)
        seen["filters_covered"] = not w.f_panel.isVisibleTo(w._workspace_stack)
        seen["filters_restored"] = not w.f_panel.isHidden()

    monkeypatch.setattr(w, "_begin_session_finalize", wrap_begin)
    monkeypatch.setattr(w, "_finalize_session_filters", wrap_filters)
    w._apply_session_document(doc)
    assert seen["loading"] is True
    assert seen["filters_covered"] is True
    assert seen["filters_restored"] is True
    assert w._table_stack.currentWidget() is w._workspace_ready_page
    assert w.f_panel.isVisibleTo(w._workspace_stack)
    assert not w._session_has_unsaved_changes()
    assert not w._ingest_loading


def test_session_load_waits_for_auto_render_before_reveal(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QTimer

    held = {"loading": False, "called": False}

    def fake_render(self):
        held["called"] = True
        held["loading"] = self._table_stack.currentIndex() == 0
        # Finish on the next turn so drain can wait under the overlay.
        QTimer.singleShot(0, self._session_on_render2d_batch_finished)
        return True

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemistryWorkspaceWindow()
    doc = {
        "format": "molmanager_session",
        "version": w._SESSION_VERSION,
        "headers": ["ID_HIDDEN", "Structure", "SMILES", "MW"],
        "rows": [{"id": 0, "cells": {"SMILES": "CCO", "MW": "46"}}],
        "next_oid": 1,
    }
    w._apply_session_document(doc)
    assert held["called"] is True
    assert held["loading"] is True
    assert w._table_stack.currentIndex() == 1
    assert not w._session_awaiting_ready
    assert not w._session_waiting_for_render
    assert not w._ingest_loading


def test_session_overlay_keeps_plot_restore_over_render2d_progress(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w._set_ingest_loading(True)
    w._set_workspace_stack_index(0)
    w._session_awaiting_ready = True
    w._loading_detail.setText("Preparing plots…")
    w._on_tool_progress("Render 2D", 3, 10)
    assert w._loading_detail.text() == "Preparing plots…"
    w._session_awaiting_ready = False
    w._on_tool_progress("Render 2D", 4, 10)
    assert "Render 2D" in (w._loading_detail.text() or "")
    assert "4/10" in (w._loading_detail.text() or "")


def test_file_ingest_reveals_before_auto_render_finishes(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    held = {"loading": False}

    def fake_render(self):
        held["loading"] = self._table_stack.currentIndex() == 0
        return True

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    qapp.processEvents()
    assert held["loading"] is True
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()


def test_file_ingest_reveals_immediately_when_auto_render_skipped(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    def fake_render(self):
        self.status_label.setText("Loaded 2 rows — auto 2D render skipped (limit 1).")
        return False

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    qapp.processEvents()
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading
    assert "auto 2D render skipped" in w.status_label.text()


def test_file_ingest_reveals_during_large_auto_render(qapp, monkeypatch):  # noqa: ARG001
    """Auto Render 2D does not block reveal; images fill in after the table is shown."""
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)

    def fake_render(self):
        return True

    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        fake_render,
    )
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._ingest_prep_before_reveal = True
    w._set_workspace_stack_index(0)
    w._post_ingest_after_color_caches()
    qapp.processEvents()
    assert w._table_stack.currentIndex() == 1
    assert not w._ingest_waiting_for_render
    assert not w._ingest_loading
    assert not w._status_host.isHidden()


def test_file_ingest_progress_updates_loading_overlay(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._set_ingest_loading(True)
    w._set_workspace_stack_index(0)
    w._on_tool_progress("Render 2D", 3, 10)
    assert "Render 2D" in (w._loading_detail.text() or "")
    assert "3/10" in (w._loading_detail.text() or "")
    assert w._status_host.isHidden()
    assert not w._memory_status_timer.isActive()
    w._set_ingest_loading(False)
    w._set_workspace_stack_index(1)
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()


def test_search_open_does_not_inset_filter_cards(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.f_panel.setVisible(True)
    w._search_panel.setVisible(True)
    w._search_panel.resize(400, 64)
    w._sync_filter_panel_scroll_content()
    assert getattr(w, "_filter_table_top_pad", None) is None
    layout = w.f_panel.layout()
    assert layout is not None
    assert layout.itemAt(0).widget() is w._filter_scroll


def test_select_table_oids_updates_selection_set(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)

    n = w.select_table_oids({1})
    qapp.processEvents()

    assert n == 1
    assert w._selected_oids_set() == {1}
    assert w._selected_logical_rows() == [1]


def test_selected_oids_override_preferred(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_oids({0})
    qapp.processEvents()
    w._selected_oids_override = frozenset({1})

    assert w._selected_oids_set() == {1}


def test_column_header_click_keeps_table_scroll(qapp):  # noqa: ARG001
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtTest import QTest

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    for i in range(80):
        w._table_model.append_row(i, {"SMILES": "C", "MW": str(i)})
        w.mols[i] = Chem.MolFromSmiles("C")
    w.next_oid = 80
    w.resize(900, 420)
    w.show()
    qapp.processEvents()
    vbar = w.table.verticalScrollBar()
    hbar = w.table.horizontalScrollBar()
    vbar.setValue(max(1, int(vbar.maximum()) // 2))
    if hbar.maximum() > 0:
        hbar.setValue(min(80, int(hbar.maximum())))
    qapp.processEvents()
    before_v = int(vbar.value())
    before_h = int(hbar.value())
    assert before_v > 0
    smiles_col = w.headers.index("SMILES")
    hh = w.table.horizontalHeader()
    x = int(hh.sectionViewportPosition(smiles_col) + max(8, hh.sectionSize(smiles_col) // 4))
    y = max(1, int(hh.height() // 2))
    QTest.mouseClick(hh.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(x, y))
    qapp.processEvents()
    after_v = int(vbar.value())
    after_h = int(hbar.value())
    assert after_v > 1000
    assert abs(after_v - before_v) <= 16
    assert abs(after_h - before_h) <= 16
    assert w._selected_full_column_indices() == [smiles_col]
    w.close()


def test_delete_selection_kind_rows_columns_cells(qapp):  # noqa: ARG001
    from PyQt5.QtCore import QItemSelectionModel

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    assert w._delete_selection_kind() == "empty"

    w.select_table_oids({0})
    qapp.processEvents()
    assert w._delete_selection_kind() == "rows"

    w.clear_table_selection()
    w._select_columns([3])
    qapp.processEvents()
    assert w._delete_selection_kind() == "columns"
    assert w._selected_full_column_indices() == [3]

    w.clear_table_selection()
    sm = w.table.selectionModel()
    view = w.table.model()
    sm.select(view.index(0, 3), QItemSelectionModel.ClearAndSelect)
    qapp.processEvents()
    assert w._delete_selection_kind() == "cells"

    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    qapp.processEvents()
    assert w._delete_selection_kind() == "both"
    w.close()


def test_select_table_rows_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_rows([0])
    qapp.processEvents()
    assert w.status_label.text() == "Selected 1 of 2 row(s)."
    w.close()


def test_invert_table_selection_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_rows([0])
    qapp.processEvents()
    w.invert_table_selection()
    qapp.processEvents()
    assert w.status_label.text() == "Selected 1 of 2 row(s). Inverted."
    w.close()


def test_rename_column_header_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    mw = w.headers.index("MW")
    w._rename_column_header(mw, "MolWt")
    assert w.headers[mw] == "MolWt"
    assert w.status_label.text() == "Renamed column 'MW' to 'MolWt'."
    w.close()


def test_toggle_filter_panel_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    assert w.f_panel.isHidden()
    w.toggle_filter_panel()
    assert not w.f_panel.isHidden()
    assert w.status_label.text() == "Filter panel shown (0 filters)."
    w.toggle_filter_panel()
    assert w.f_panel.isHidden()
    assert w.status_label.text() == "Filter panel hidden."
    w.close()


def test_apply_table_sort_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    mw = w.headers.index("MW")
    w._apply_table_sort(mw, True, "numeric")
    assert [w._table_model.row_oid(i) for i in range(2)] == [1, 0]
    assert w.status_label.text() == "Sorted 'MW' numeric ascending."
    w._apply_table_sort(mw, False, "alphabetic")
    assert [w._table_model.row_oid(i) for i in range(2)] == [0, 1]
    assert w.status_label.text() == "Sorted 'MW' alphabetic descending."
    w.close()


def test_delete_selection_clears_cells_after_confirm(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QItemSelectionModel
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    sm = w.table.selectionModel()
    view = w.table.model()
    sm.select(view.index(0, 3), QItemSelectionModel.ClearAndSelect)
    w.edit_delete_selection()
    assert w._table_model.cell_text(0, 3) == ""
    assert w._table_model.cell_text(1, 3) == "30.07"


def test_delete_selection_deletes_column_after_confirm(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._select_columns([3])
    w.edit_delete_selection()
    assert "MW" not in w.headers
    assert w._table_model.rowCount() == 2


def test_delete_selection_both_can_choose_columns(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    monkeypatch.setattr(w, "_ask_delete_rows_or_columns", lambda *a, **k: "columns")
    w.edit_delete_selection()
    assert "MW" not in w.headers
    assert w._table_model.rowCount() == 2


def test_delete_selection_both_can_choose_rows(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._selected_oids_override = frozenset({0})
    w._select_columns([3])
    monkeypatch.setattr(w, "_ask_delete_rows_or_columns", lambda *a, **k: "rows")
    w.edit_delete_selection()
    assert "MW" in w.headers
    assert w._table_model.rowCount() == 1
    assert w._table_model.cell_text(0, 0) == "1"


def test_chemistry_tool_structure_sources_smoke(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)

    sources = w.chemistry_tool_structure_sources()
    assert sources[0] == "Structure"
    assert "SMILES" in sources
    assert "MW" not in sources
    assert w._canonical_smiles_header_for_updates() == "SMILES"


def test_structure_header_menu_offers_duplicate_not_rename(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    menu = w._create_header_context_menu(1)
    assert menu is not None
    names = [a.objectName() for a in menu.actions()]
    assert "header_duplicate" in names
    assert "header_rename" not in names
    assert "header_delete" not in names
    select_menu = next(a.menu() for a in menu.actions() if a.text() == "Select")
    select_names = [a.objectName() for a in select_menu.actions() if a.objectName()]
    assert "header_select_all" in select_names
    assert "header_select_all_visible" not in select_names
    assert "header_select_first_occurrence" in select_names


def test_header_select_all_uses_visible_rows_only(qapp):  # noqa: ARG001
    from molmanager.ui.widgets import FilterCard

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.calculate_global_bounds()
    card = FilterCard(list(w.global_bounds.keys()), w, initial_property="MW")
    card.restore_state("MW", 40.0, 50.0)
    w.filters = [card]
    w._apply_filters_impl_sync(None)
    assert w._visible_oids_set() == frozenset({0})

    w._select_all_rows()
    qapp.processEvents()
    assert w._selected_oids_set() == {0}
    w.close()


def test_plot_clear_selection_drops_header_select_highlight(qapp):  # noqa: ARG001
    from molmanager.ui.plot_table_sync import clear_table_selection_from_plot

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._select_first_occurrence_per_distinct_structure()
    qapp.processEvents()
    assert w._selected_oids_set() == {0, 1}

    w._selected_oids_override = frozenset({0, 1})
    w._table_model.set_highlighted_oids(frozenset({0, 1}))
    sm = w.table.selectionModel()
    if sm is not None:
        sm.clearSelection()

    clear_table_selection_from_plot(w)
    assert w._selected_oids_override is None
    assert w._table_model.highlighted_oids() is None
    assert w._selected_oids_set() == set()
    assert sm is None or not sm.hasSelection()
    w.close()


def test_duplicate_structure_column_is_chemistry_source(qapp):  # noqa: ARG001
    from molmanager.table.structure_depiction_layout import structure_column_minimum_width
    from molmanager.ui.compound_table_model import CompoundTableModel
    from molmanager.ui.main_window.table_undo_commands import UndoDuplicateColumnCommand

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    struct_w = structure_column_minimum_width() + 40
    w.table.setColumnWidth(CompoundTableModel.STRUCTURE_COL, struct_w)
    w._undo_stack.push(UndoDuplicateColumnCommand(w, 1, "Structure"))
    assert "Structure (Copy)" in w.headers
    assert w._table_model.is_pixmap_data_column("Structure (Copy)")
    assert w._table_model.backing_value_for_row_header(0, "Structure (Copy)") == "CCO"
    assert w._table_model.backing_value_for_row_header(1, "Structure (Copy)") == "CC"
    assert "Structure (Copy)" in w.chemistry_tool_structure_sources()
    copy_col = w.headers.index("Structure (Copy)")
    assert w.table.columnWidth(copy_col) == w.table.columnWidth(CompoundTableModel.STRUCTURE_COL)
    assert w.table.columnWidth(copy_col) == struct_w
    assert w._undo_stack.canUndo()
    w._undo_stack.undo()
    assert "Structure (Copy)" not in w.headers


def test_new_window_and_file_load_use_table_only_layout(qapp):  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY, LAYOUT_TABLE_STACK

    w = ChemistryWorkspaceWindow()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    w.apply_workspace_layout(LAYOUT_TABLE_STACK)
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_STACK
    w._apply_table_only_layout_for_file_load()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY


def test_docking_from_table_only_uses_split_view(qapp):  # noqa: ARG001
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY, LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    pane = w._target_plot_pane()
    assert pane is not None
    assert w._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE
    assert len(w._workspace_layout.plot_panes()) == 1
    assert w._workspace_layout.preferred_pane() is pane


def test_close_docked_plot_closes_without_prompt(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel, QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    plot = QLabel("plot")
    w._workspace_layout.dock_into_pane(pane, plot)

    prompted = []

    def _question(*args, **kwargs):
        prompted.append(True)
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", _question)
    w.close_docked_plot(plot)
    assert prompted == []
    assert list(pane.plot_widgets()) == []


def test_close_plot_pane_prompts_when_occupied(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel, QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, QLabel("plot"))

    answers = iter([QMessageBox.No, QMessageBox.Yes])
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: next(answers),
    )
    w.close_plot_pane(pane)
    assert pane in w._workspace_layout.plot_panes()
    assert list(pane.plot_widgets())

    w.close_plot_pane(pane)
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_ONLY

    assert w._workspace_layout.layout_id == LAYOUT_TABLE_ONLY
    assert list(w.iter_docked_plot_widgets()) == []


def test_close_empty_plot_pane_skips_prompt(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SIDE

    w = ChemistryWorkspaceWindow()
    w.apply_workspace_layout(LAYOUT_TABLE_SIDE)
    pane = w._workspace_layout.plot_panes()[1]
    assert pane.is_empty()

    called = {"n": 0}

    def boom(*_a, **_k):
        called["n"] += 1
        return QMessageBox.No

    monkeypatch.setattr(QMessageBox, "question", boom)
    w.close_plot_pane(pane)
    assert called["n"] == 0
    assert len(w._workspace_layout.plot_panes()) == 1
    assert pane not in w._workspace_layout.plot_panes()
    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    assert w._workspace_layout.layout_id == LAYOUT_TABLE_SINGLE


def test_clear_all_re_enables_menubar_after_ingest(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    mb = w.menuBar()
    file_menu = next(a.menu() for a in mb.actions() if a.menu() is not None)
    w._set_ingest_loading(True)
    assert not file_menu.isEnabled()

    w._set_ingest_loading(False)
    w.clear_all()

    assert file_menu.isEnabled()
    assert w._btn_workspace_layout.isEnabled()


def test_status_memory_tracker_starts_before_window_shown(qapp, monkeypatch):  # noqa: ARG001
    """Polling must start during __init__; isVisible() is False until show()."""
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemistryWorkspaceWindow()
    assert not w.isVisible()
    assert not w._status_host.isHidden()
    assert w._memory_status_timer.isActive()
    assert w._memory_status_label.text().startswith("Mem: ")


def test_status_and_memory_labels_use_smaller_font(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.ui.theme import default_app_font_pt, status_bar_font_pt

    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemistryWorkspaceWindow()
    app_pt = int(w._app_font_pt or default_app_font_pt())
    expected = status_bar_font_pt(app_pt)
    assert w.status_label.font().pointSize() == expected
    assert w._memory_status_label.font().pointSize() == expected
    w._set_app_font_pt(14, persist=False)
    assert w.status_label.font().pointSize() == 13
    assert w._memory_status_label.font().pointSize() == 13
    w._set_app_font_pt(app_pt, persist=False)


def test_status_memory_tracker_stops_when_status_bar_hidden(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr("molmanager.ui.theme.load_status_bar_visible", lambda: True)
    monkeypatch.setattr("molmanager.ui.gui_settings_mixin.load_status_bar_visible", lambda: True)
    w = ChemistryWorkspaceWindow()
    w._apply_status_bar_visible(False, persist=False)
    assert w._status_host.isHidden()
    assert not w._memory_status_timer.isActive()
    w._apply_status_bar_visible(True, persist=False)
    assert w._memory_status_timer.isActive()
    assert w._memory_status_label.text().startswith("Mem: ")


def test_pka_prediction_writes_pi_only_when_requested(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._on_pka_prediction_finished([(0, "4.76", "N/A")], False)
    assert "pKa" in w.headers
    assert "pI" not in w.headers
    assert w._table_model.value_for_header(0, "pKa") == "4.76"
    w._on_pka_prediction_finished([(0, "4.76", "5.97")], True)
    assert "pI" in w.headers
    assert w._table_model.value_for_header(0, "pI") == "5.97"


def test_tools_menu_nests_superpose_under_conformations(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    labels = [a.text().replace("&", "") for a in tools.actions()]
    assert "Generate Conformations" not in labels
    assert "Conformations" in labels
    assert not any(lbl.startswith("Superpose") for lbl in labels)
    conf = next(a.menu() for a in tools.actions() if a.text().replace("&", "") == "Conformations")
    conf_labels = [a.text().replace("&", "") for a in conf.actions()]
    assert conf_labels == ["Generate", "", "Superpose…", "Screen Pharmacophore…"]
    gen = next(a.menu() for a in conf.actions() if a.text().replace("&", "") == "Generate")
    assert [a.text().replace("&", "") for a in gen.actions()] == [
        "Stochastic…",
        "Systematic…",
        "CONFORGE…",
    ]
    w.close()


def test_prepare_structures_nests_explicit_hydrogens(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    prepare = next(
        a.menu() for a in tools.actions() if a.text().replace("&", "") == "Prepare Structures"
    )
    labels = [a.text().replace("&", "") for a in prepare.actions()]
    assert "Add Explicit Hydrogens…" not in labels
    assert "Remove Explicit Hydrogens…" not in labels
    assert "Explicit Hydrogens" in labels
    assert "Protonate" in labels
    assert "Protonate Structures" not in labels
    assert labels.index("Protonate") == labels.index("Disconnect Largest Fragments…") + 1
    protonate = next(
        a.menu() for a in prepare.actions() if a.text().replace("&", "") == "Protonate"
    )
    p_labels = [a.text().replace("&", "") for a in protonate.actions()]
    assert p_labels == ["Protonate…", "Generate Protomers…", "Neutralize…"]
    hydrogens = next(
        a.menu() for a in prepare.actions() if a.text().replace("&", "") == "Explicit Hydrogens"
    )
    h_labels = [a.text().replace("&", "") for a in hydrogens.actions()]
    assert h_labels == ["Add…", "Remove…"]
    w.close()


def test_tools_menu_nests_reaction_tools(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    labels = [a.text().replace("&", "") for a in tools.actions()]
    assert "R-Group Decomposition" not in labels
    assert "Reaction Based Enumeration…" not in labels
    assert "Reaction" in labels
    reaction = next(a.menu() for a in tools.actions() if a.text().replace("&", "") == "Reaction")
    rxn_labels = [a.text().replace("&", "") for a in reaction.actions()]
    assert "R-Group Decomposition" in rxn_labels
    assert "Extract…" in rxn_labels
    assert "Reaction Based Enumeration…" in rxn_labels
    assert rxn_labels.index("Extract…") < rxn_labels.index("R-Group Decomposition")
    decomp = next(
        a.menu() for a in reaction.actions() if a.text().replace("&", "") == "R-Group Decomposition"
    )
    decomp_labels = [a.text().replace("&", "") for a in decomp.actions()]
    assert "Core-Based Decomposition…" in decomp_labels
    w.close()


def test_data_menu_nests_analyze_and_split_under_table(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
    labels = [a.text().replace("&", "") for a in data.actions()]
    assert labels[0] == "Table"
    assert "Statistics…" not in labels
    assert "Analyze Table…" not in labels
    assert "Split Column…" not in labels
    table = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "Table")
    table_labels = [a.text().replace("&", "") for a in table.actions() if not a.isSeparator()]
    assert table_labels == ["Operations", "Statistics…"]
    ops = next(a.menu() for a in table.actions() if a.text().replace("&", "") == "Operations")
    ops_labels = [a.text().replace("&", "") for a in ops.actions() if not a.isSeparator()]
    assert ops_labels == ["Add Row…", "Add Column…", "Split Column…", "Join Columns…"]
    w.close()


def test_add_blank_row_and_column_on_empty_table(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    w.add_blank_table_row(3)
    assert w.headers[:2] == ["ID_HIDDEN", "Structure"]
    assert w._table_model.rowCount() == 3
    oid = w._table_model.row_oid(0)
    assert oid >= 0
    w.add_blank_table_column("MW", count=2)
    assert "MW" in w.headers
    assert "MW (1)" in w.headers
    w._undo_stack.undo()
    assert "MW" not in w.headers
    assert "MW (1)" not in w.headers
    w._undo_stack.undo()
    assert w._table_model.rowCount() == 0
    w.close()


def test_data_menu_nests_medchem_with_dimensionality_reduction(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    tools_labels = [a.text().replace("&", "") for a in tools.actions()]
    assert "Dimensionality Reduction" not in tools_labels
    assert "MedChem" not in tools_labels
    data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
    data_labels = [a.text().replace("&", "") for a in data.actions()]
    assert "MedChem Plots" in data_labels
    assert "DimRed Plots" in data_labels
    assert "Filter" in data_labels
    assert "Search…" in data_labels
    assert "BOILED-Egg plot…" not in data_labels
    assert "Golden Triangle plot…" not in data_labels
    assert "Principal Component Analysis…" not in data_labels
    assert "t-SNE Visualization…" not in data_labels
    assert "UMAP Visualization…" not in data_labels
    assert "Self-Organizing Map…" not in data_labels
    assert data_labels.index("DimRed Plots") == data_labels.index("MedChem Plots") + 1
    medchem = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "MedChem Plots")
    assert [a.text().replace("&", "") for a in medchem.actions()] == [
        "BOILED-Egg plot…",
        "Golden Triangle plot…",
    ]
    dimred = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "DimRed Plots")
    assert [a.text().replace("&", "") for a in dimred.actions()] == [
        "Principal Component Analysis…",
        "t-SNE Visualization…",
        "UMAP Visualization…",
        "Self-Organizing Map…",
    ]
    w.close()
