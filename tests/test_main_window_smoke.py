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


def _one_row_session(**metadata):
    """Write a one-row session file (``CCO``) with *metadata* over the workspace defaults."""
    from session_roundtrip import saved_document, save_session_file

    source = ChemistryWorkspaceWindow()
    source.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    source._table_model.set_headers(list(source.headers))
    source._table_model.append_row(0, {"SMILES": "CCO", "MW": "46"})
    source.next_oid = 1
    return save_session_file(source, doc={**saved_document(source), **metadata})


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
    w.selection_store.set({0})

    w.clear_all()

    assert w._table_model.rowCount() == 0
    assert w.mols == {}
    assert w.headers == []
    assert w.next_oid == 0
    assert w.selection_store.is_empty()
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
        "Send Selected to New Session",
        "Close Session",
    ]


def test_close_session_returns_to_idle_screen(qapp):  # noqa: ARG001
    from molmanager.ui.strings import LOADING_DETAIL_IDLE

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._reveal_workspace_ready()
    w._session_source_path = "example.cms"
    w._mark_session_dirty()
    w.f_panel.setVisible(True)

    w.close_session()

    assert w._table_model.rowCount() == 0
    assert w.headers == []
    assert w._session_source_path is None
    assert not w._session_has_unsaved_changes()
    assert w._table_stack.currentIndex() == 0
    assert w._loading_detail.text() == LOADING_DETAIL_IDLE
    assert w.f_panel.isVisible() is False
    assert w.status_label.text() == "Ready."


def test_close_session_cancel_keeps_table(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w._suppress_exit_session_prompt = False
    w._clear_session_dirty()
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.No)

    w.close_session()

    assert w._table_model.rowCount() == 2


def test_save_selected_to_session_writes_subset_without_clearing_dirty(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog

    from molmanager.table.session_v4 import read_session_v4

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.selection_store.set({1})
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
    opened = read_session_v4(out)
    opened.discard_temp_files()
    assert list(opened.rows.oids) == [1]


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


def test_send_selected_to_new_session_opens_subset(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from molmanager.table.session_v4 import read_session_v4

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.selection_store.set({1})
    w._mark_session_dirty()
    source = str(tmp_path / "original.cms")
    w._session_source_path = source
    launched: list[list[str]] = []

    def fake_popen(args, **kwargs):  # noqa: ARG001
        launched.append([str(part) for part in args])

    monkeypatch.setattr(
        "molmanager.ui.main_window.session_save_mixin.subprocess.Popen",
        fake_popen,
    )
    assert w.send_selected_to_new_session() is True
    assert w.threadpool.waitForDone(60_000)
    qapp.processEvents()
    assert w._session_source_path == source
    assert w._session_has_unsaved_changes()
    assert w._table_model.rowCount() == 2
    assert len(launched) == 1
    args = launched[0]
    assert "--load-session" in args
    path = args[args.index("--load-session") + 1]
    opened = read_session_v4(path)
    opened.discard_temp_files()
    assert list(opened.rows.oids) == [1]
    assert w.status_label.text().startswith("Selected rows sent to ")


def test_send_selected_to_new_session_requires_selection(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    seen: dict[str, str] = {}

    def fake_info(_parent, title, text):
        seen["title"] = title
        seen["text"] = text

    monkeypatch.setattr(QMessageBox, "information", fake_info)

    def fail_launch(*_args, **_kwargs):
        raise AssertionError("window should not launch")

    monkeypatch.setattr(
        "molmanager.ui.main_window.session_save_mixin.subprocess.Popen",
        fail_launch,
    )
    assert w.send_selected_to_new_session() is False
    assert seen["title"] == "Send Selected to New Session"
    assert "No rows are selected" in seen["text"]
    assert w._table_model.rowCount() == 2


def test_session_load_uses_loading_page_then_reveals(qapp, monkeypatch):  # noqa: ARG001
    monkeypatch.setattr(
        ChemistryWorkspaceWindow,
        "_try_auto_render_all_structures_after_ingest",
        lambda self: False,
    )
    w = ChemistryWorkspaceWindow()
    path = _one_row_session(filter_panel_visible=True)
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
    assert w.apply_saved_session_from_file(str(path))
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
    assert w.apply_saved_session_from_file(str(_one_row_session()))
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


def test_selection_store_is_the_selection(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_oids({0})
    qapp.processEvents()
    w.selection_store.set({1})

    assert w._selected_oids_set() == {1}
    assert w._selected_logical_rows() == [1]
    assert w._table_model.highlighted_oids() == frozenset({1})


def test_selection_survives_filtering(qapp):  # noqa: ARG001
    """Selection is keyed by OID, so rows hidden by a filter stay selected."""
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_oids({0, 1})
    qapp.processEvents()
    w._filter_proxy_model.set_visible_oids(frozenset({1}))
    qapp.processEvents()

    assert w._selected_oids_set() == {0, 1}


def test_large_selection_pruned_on_row_delete(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.selection_store.set({0, 1})
    w._table_model.remove_row_at(0)
    qapp.processEvents()

    assert w._selected_oids_set() == {1}


def test_plot_fanout_is_leading_edge_throttled(qapp, monkeypatch):  # noqa: ARG001
    """First change syncs plots at once; a burst coalesces into one trailing sync."""
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    syncs: list[frozenset[int]] = []
    monkeypatch.setattr(
        w,
        "_sync_active_plots_from_table_selection",
        lambda: syncs.append(w.selection_store.oids),
    )

    w.selection_store.set({0})
    assert syncs == [frozenset({0})]
    w.selection_store.set({1})
    w.selection_store.set({0, 1})
    assert len(syncs) == 1

    w._plot_table_sync_timer.timeout.emit()
    assert syncs == [frozenset({0}), frozenset({0, 1})]
    w._plot_table_sync_timer.stop()
    w._plot_table_sync_timer.timeout.emit()
    assert len(syncs) == 2


def test_reveal_first_selected_row_targets_earliest_visible(qapp, monkeypatch):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 5)
    w.select_table_rows([3, 1], reveal=False)
    seen: list[tuple] = []
    monkeypatch.setattr(
        w,
        "_refresh_table_selection_visual",
        lambda rows, **k: seen.append((rows, k)),
    )
    w.reveal_first_selected_row()
    assert seen == [([1], {"focus": False, "center": True})]
    w.close()


def test_select_without_reveal_leaves_table_focus_and_scroll(qapp, monkeypatch):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    revealed: list[object] = []
    monkeypatch.setattr(w, "_refresh_table_selection_visual", lambda *a, **k: revealed.append(a))

    w.select_table_rows([1], reveal=False)
    assert revealed == []
    assert w._selected_oids_set() == {1}

    w.select_table_rows([0])
    assert len(revealed) == 1


def test_selection_change_origin_reaches_subscribers(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    origins: list[object] = []
    w.selection_store.changed.connect(origins.append)
    plot = object()

    w.select_table_rows([0], origin=plot)
    w.clear_table_selection(origin=plot)

    assert origins == [plot, plot]


def _seed_rows(w: ChemistryWorkspaceWindow, n: int) -> None:
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "MW"]
    w._table_model.set_headers(list(w.headers))
    for oid in range(n):
        w._table_model.append_row(oid, {"SMILES": "C" * (oid + 1), "MW": str(oid)})
    w.next_oid = n


def test_row_header_modifiers_drive_entry_selection(qapp):  # noqa: ARG001
    from PyQt5.QtCore import Qt

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 6)
    ctl = w.table.row_selection_controller()

    ctl.press_row(1, Qt.NoModifier)
    assert w._selected_oids_set() == {1}
    ctl.press_row(3, Qt.ShiftModifier)
    assert w._selected_oids_set() == {1, 2, 3}
    ctl.press_row(5, Qt.ControlModifier)
    assert w._selected_oids_set() == {1, 2, 3, 5}
    ctl.press_row(2, Qt.ControlModifier)
    assert w._selected_oids_set() == {1, 3, 5}
    # Ctrl+Shift adds the range from the last anchor (row 2) without dropping anything.
    ctl.press_row(0, Qt.ControlModifier | Qt.ShiftModifier)
    assert w._selected_oids_set() == {0, 1, 2, 3, 5}
    assert not w.table.selectionModel().hasSelection()
    w.close()


def test_column_header_modifiers_match_row_selection(qapp, monkeypatch):  # noqa: ARG001
    """Ctrl toggles a column; Ctrl+Shift adds a range; both keep the entry selection."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 6)
    structure = w.headers.index("Structure")
    smiles = w.headers.index("SMILES")
    mw = w.headers.index("MW")
    mods = Qt.NoModifier

    def modifiers():
        return mods

    monkeypatch.setattr(QApplication, "keyboardModifiers", modifiers)

    def click(col: int, modifiers_value) -> None:
        nonlocal mods
        mods = modifiers_value
        w._on_horizontal_header_section_clicked(col)

    click(smiles, Qt.NoModifier)
    assert w._selected_full_column_indices() == [smiles]
    assert w.selection_store.is_empty()
    assert w.status_label.text() == "Selected 6 of 6 row(s). 1 column."

    click(mw, Qt.ShiftModifier)
    assert sorted(w._selected_full_column_indices()) == [smiles, mw]
    assert w.status_label.text() == "Selected 6 of 6 row(s). 2 columns."

    click(structure, Qt.ControlModifier)
    assert sorted(w._selected_full_column_indices()) == [structure, smiles, mw]

    click(smiles, Qt.ControlModifier)
    assert sorted(w._selected_full_column_indices()) == [structure, mw]

    # Ctrl+Shift adds the range from the last anchor (SMILES) and keeps Structure.
    click(mw, Qt.ControlModifier | Qt.ShiftModifier)
    assert sorted(w._selected_full_column_indices()) == [structure, smiles, mw]

    w.select_table_rows([4])
    click(smiles, Qt.ControlModifier)
    assert w._selected_oids_set() == {4}
    assert w._selected_full_column_indices() == [smiles]
    click(mw, Qt.ControlModifier)
    assert w._selected_oids_set() == {4}
    assert sorted(w._selected_full_column_indices()) == [smiles, mw]
    click(smiles, Qt.ControlModifier)
    click(mw, Qt.ControlModifier)
    assert w._selected_full_column_indices() == []
    assert w._selected_oids_set() == {4}
    assert w.status_label.text() == "Selected 1 of 6 row(s)."

    # Shift replaces the columns and clears entries. Anchor is the last Ctrl click (MW).
    click(smiles, Qt.ShiftModifier)
    assert sorted(w._selected_full_column_indices()) == [smiles, mw]
    assert w.selection_store.is_empty()

    w.select_table_rows([1])
    click(structure, Qt.NoModifier)
    assert w._selected_full_column_indices() == [structure]
    assert w.selection_store.is_empty()

    w._column_selection_anchor = None
    click(mw, Qt.ControlModifier | Qt.ShiftModifier)
    assert sorted(w._selected_full_column_indices()) == [structure, mw]
    assert w._column_selection_anchor == mw
    w.close()
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtTest import QTest

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 4)
    w.resize(900, 600)
    w._reveal_workspace_ready()
    w.show()
    qapp.processEvents()
    vh = w.table.verticalHeader()
    y = vh.sectionViewportPosition(2) + vh.sectionSize(2) // 2
    QTest.mouseClick(vh.viewport(), Qt.LeftButton, Qt.NoModifier, QPoint(5, y))
    qapp.processEvents()
    assert w._selected_oids_set() == {2}
    assert not w.table.selectionModel().hasSelection()
    w.close()


def test_cell_click_clears_entries_but_right_click_in_selection_keeps_them(qapp):  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 4)
    w.resize(900, 600)
    w._reveal_workspace_ready()
    w.show()
    qapp.processEvents()
    view = w.table.model()
    w.select_table_rows([1, 2])
    qapp.processEvents()

    inside = w.table.visualRect(view.index(1, 3)).center()
    QTest.mouseClick(w.table.viewport(), Qt.RightButton, Qt.NoModifier, inside)
    assert w._selected_oids_set() == {1, 2}

    outside = w.table.visualRect(view.index(3, 3)).center()
    QTest.mouseClick(w.table.viewport(), Qt.LeftButton, Qt.NoModifier, outside)
    assert w._selected_oids_set() == set()
    assert w.table.selectionModel().isSelected(view.index(3, 3))
    w.close()


def test_select_all_selects_shown_entries(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 4)
    w.table.setRowHidden(3, True)
    w.table.selectAll()
    assert w._selected_oids_set() == {0, 1, 2}
    assert not w.table.selectionModel().hasSelection()
    w.close()


def test_copy_includes_selected_entry_rows(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QApplication

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 3)
    w.select_table_oids({0, 2})
    assert not w.table.selectionModel().hasSelection()
    w.edit_copy()
    # Structure (col 1) copies the SMILES text; ID_HIDDEN is never copied.
    assert QApplication.clipboard().text() == "C\tC\t0\nCCC\tCCC\t2"
    w.close()


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

    _select_row_and_column(w, 0, 3)
    qapp.processEvents()
    assert w._delete_selection_kind() == "both"
    w.close()


def _select_row_and_column(w, row: int, col: int) -> None:
    """User-style selection of one full column, then Ctrl+click on one row header."""
    from PyQt5.QtCore import Qt

    w._select_columns([col])
    w.table.row_selection_controller().press_row(row, Qt.ControlModifier)


def test_select_table_rows_updates_status(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    w.select_table_rows([0])
    qapp.processEvents()
    assert w.status_label.text() == "Selected 1 of 2 row(s)."
    w.close()


def test_user_table_selection_reports_entry_count(qapp):  # noqa: ARG001
    """Row-header clicks and select-all report the entry count; column select does not."""
    from PyQt5.QtCore import Qt

    w = ChemistryWorkspaceWindow()
    _seed_rows(w, 6)
    ctl = w.table.row_selection_controller()

    ctl.press_row(1, Qt.NoModifier)
    assert w.status_label.text() == "Selected 1 of 6 row(s)."
    ctl.press_row(3, Qt.ShiftModifier)
    assert w.status_label.text() == "Selected 3 of 6 row(s)."
    ctl.select_all()
    assert w.status_label.text() == "Selected 6 of 6 row(s)."
    ctl.clear_for_cell_input()
    assert w.status_label.text() == "Selected 0 of 6 row(s)."

    ctl.press_row(0, Qt.NoModifier)
    w._select_columns([3])
    assert w.status_label.text() == "Selected 6 of 6 row(s). 1 column."
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
    _select_row_and_column(w, 0, 3)
    monkeypatch.setattr(w, "_ask_delete_rows_or_columns", lambda *a, **k: "columns")
    w.edit_delete_selection()
    assert "MW" not in w.headers
    assert w._table_model.rowCount() == 2


def test_delete_selection_both_can_choose_rows(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    w = ChemistryWorkspaceWindow()
    _seed_two_rows(w)
    _select_row_and_column(w, 0, 3)
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
    titles = [a.text() for a in menu.actions() if a.text()]
    assert "header_duplicate" in names
    assert "header_rename" not in names
    assert "header_delete" not in names
    assert "Sort" not in titles
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

    sm = w.table.selectionModel()

    clear_table_selection_from_plot(w)
    assert w.selection_store.is_empty()
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
    # Incremental expand path (not a full apply_layout rebuild from the picker).
    assert w._workspace_layout.ensure_single_plot_pane() is pane


def test_dock_fits_plot_to_existing_pane(qapp):  # noqa: ARG001
    """Docking sizes the widget to the pane; the pane split does not move."""
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.resize(1200, 800)
    w.show()
    w._reveal_workspace_ready()
    qapp.processEvents()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    qapp.processEvents()
    before = w._plot_panel_splitter_sizes()
    assert before is not None

    plot = QLabel("plot")
    plot.dockable_in_workspace = True
    plot.resize(1000, 900)
    plot.show()
    qapp.processEvents()

    assert w.dock_plot_widget(plot) is True
    qapp.processEvents()
    assert w._plot_panel_splitter_sizes() == before
    pane = w._workspace_layout.plot_panes()[0]
    assert plot.width() == pane._stack.width()
    assert plot.height() == pane._stack.height()


def test_undock_resizes_floating_dialog_to_docked_size(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.resize(1100, 700)
    w.show()
    w._reveal_workspace_ready()
    qapp.processEvents()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    qapp.processEvents()

    plot = QLabel("plot")
    plot.dockable_in_workspace = True
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, plot)
    qapp.processEvents()
    # Force a known docked geometry for the assertion.
    w._ensure_plot_panel_width(preferred=480)
    qapp.processEvents()
    src_w, src_h = plot.width(), plot.height()
    assert src_w > 50 and src_h > 50

    class _Dlg(QDialog):
        def __init__(self, parent=None, panel=None):
            super().__init__(parent)
            self.resize(960, 900)
            self._panel = panel
            ly = QVBoxLayout(self)
            if panel is not None:
                ly.addWidget(panel, 1)

    plot.create_floating_dialog = lambda app: _Dlg(app, panel=plot)
    monkeypatch.setattr(w, "_prepare_tool_dialog", lambda *_a, **_k: None)
    monkeypatch.setattr(w, "_bind_undocked_browser_dialog", lambda *_a, **_k: False)
    monkeypatch.setattr(w, "_register_floating_result_dialog", lambda *_a, **_k: None)

    assert w.undock_plot_to_window(plot) is True
    qapp.processEvents()
    host = plot.window()
    assert isinstance(host, _Dlg)
    assert abs(plot.width() - src_w) <= 1
    assert abs(plot.height() - src_h) <= 1


def test_redock_keeps_pane_size(qapp, monkeypatch):  # noqa: ARG001
    """A resized floating window does not change the pane it is docked back into."""
    from PyQt5.QtWidgets import QDialog, QLabel, QVBoxLayout

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.resize(1200, 800)
    w.show()
    w._reveal_workspace_ready()
    qapp.processEvents()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    qapp.processEvents()

    plot = QLabel("plot")
    plot.dockable_in_workspace = True
    pane = w._workspace_layout.plot_panes()[0]
    w._workspace_layout.dock_into_pane(pane, plot)
    qapp.processEvents()
    w._ensure_plot_panel_width(preferred=560)
    qapp.processEvents()
    before = w._plot_panel_splitter_sizes()
    assert before is not None
    assert before[1] >= 540

    class _Dlg(QDialog):
        def __init__(self, parent=None, panel=None):
            super().__init__(parent)
            self.resize(960, 900)
            self._panel = panel
            ly = QVBoxLayout(self)
            if panel is not None:
                ly.addWidget(panel, 1)

    plot.create_floating_dialog = lambda app: _Dlg(app, panel=plot)
    monkeypatch.setattr(w, "_prepare_tool_dialog", lambda *_a, **_k: None)
    monkeypatch.setattr(w, "_bind_undocked_browser_dialog", lambda *_a, **_k: False)
    monkeypatch.setattr(w, "_register_floating_result_dialog", lambda *_a, **_k: None)

    assert w.undock_plot_to_window(plot) is True
    qapp.processEvents()
    host = plot.window()
    assert isinstance(host, _Dlg)
    host.resize(360, 300)
    qapp.processEvents()

    assert w.dock_plot_widget(plot) is True
    qapp.processEvents()
    assert w._plot_panel_splitter_sizes() == before


def test_dock_wire_syncs_only_docked_plot(qapp, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QLabel

    from molmanager.ui.main_window.workspace_layout import LAYOUT_TABLE_SINGLE

    w = ChemistryWorkspaceWindow()
    w.apply_workspace_layout(LAYOUT_TABLE_SINGLE)
    pane = w._workspace_layout.plot_panes()[0]

    existing = QLabel("existing")
    existing.dockable_in_workspace = True
    existing._sync_calls = 0

    def _sync_existing(*_a, **_k):
        existing._sync_calls += 1

    existing.sync_from_table_selection = _sync_existing
    w._workspace_layout.dock_into_pane(pane, existing)

    incoming = QLabel("incoming")
    incoming.dockable_in_workspace = True
    incoming._sync_calls = 0

    def _sync_incoming(*_a, **_k):
        incoming._sync_calls += 1

    incoming.sync_from_table_selection = _sync_incoming

    fanout = []
    monkeypatch.setattr(w, "_sync_active_plots_from_table_selection", lambda: fanout.append(True))
    monkeypatch.setattr(w, "_prepare_tool_plot", lambda *_a, **_k: None)

    assert w.dock_plot_widget(incoming) is True
    qapp.processEvents()

    assert fanout == []
    assert incoming._sync_calls >= 1
    assert existing._sync_calls == 0


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
    qapp.processEvents()
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
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Chemistry")
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
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Chemistry")
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
    tools = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Chemistry")
    labels = [a.text().replace("&", "") for a in tools.actions()]
    assert "Reaction" not in labels
    assert "Extract Info…" not in labels
    assert "Reaction Based…" not in labels
    assert labels.index("Structure Decomposition") == labels.index("Predict") + 1
    assert labels.index("Structure Enumeration") == labels.index("Structure Decomposition") + 1
    assert labels.index("REINVENT") == labels.index("Structure Enumeration") + 1
    assert labels.index("Extract Reaction Info…") == labels.index("REINVENT") + 1
    reinvent = next(
        a.menu() for a in tools.actions() if a.text().replace("&", "") == "REINVENT"
    )
    reinvent_labels = [a.text().replace("&", "") for a in reinvent.actions()]
    assert reinvent_labels == ["Sampling…", "Learning…"]
    extract = next(a for a in tools.actions() if a.text().replace("&", "") == "Extract Reaction Info…")
    assert extract.menu() is None
    decomp = next(
        a.menu() for a in tools.actions() if a.text().replace("&", "") == "Structure Decomposition"
    )
    decomp_labels = [a.text().replace("&", "") for a in decomp.actions()]
    assert decomp_labels == [
        "Core-Based…",
        "BRICS…",
        "RECAP…",
    ]
    enum = next(
        a.menu() for a in tools.actions() if a.text().replace("&", "") == "Structure Enumeration"
    )
    enum_labels = [a.text().replace("&", "") for a in enum.actions()]
    assert enum_labels == [
        "R-Group…",
        "BRICS…",
        "RECAP…",
        "Reaction Based…",
    ]
    w.close()


def test_data_menu_nests_analyze_and_split_under_table(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
    labels = [a.text().replace("&", "") for a in data.actions()]
    assert labels[0] == "Table"
    assert labels[1] == "Lists"
    assert "Statistics…" not in labels
    assert "Analyze Table…" not in labels
    assert "Split Column…" not in labels
    assert "Cluster…" not in labels
    assert "Binning…" not in labels
    similarity = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "Similarity")
    similarity_labels = [a.text().replace("&", "") for a in similarity.actions() if not a.isSeparator()]
    assert similarity_labels == [
        "Fingerprint Similarity...",
        "Diverse Subset…",
        "Cluster…",
        "Binning…",
    ]
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
    chemistry = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Chemistry")
    tools_labels = [a.text().replace("&", "") for a in tools.actions()]
    chemistry_labels = [a.text().replace("&", "") for a in chemistry.actions()]
    assert "Dimensionality Reduction" not in tools_labels
    assert "MedChem" not in tools_labels
    assert "Dimensionality Reduction" not in chemistry_labels
    assert "MedChem" not in chemistry_labels
    data = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Data")
    data_labels = [a.text().replace("&", "") for a in data.actions()]
    assert "MedChem Plots" in data_labels
    assert "DimRed Plots" not in data_labels
    assert "Dimensionality Reduction" in data_labels
    assert "Filter" in data_labels
    assert "Search…" in data_labels
    assert "BOILED-Egg…" not in data_labels
    assert "Golden Triangle…" not in data_labels
    assert "Principal Component Analysis…" not in data_labels
    assert "t-SNE Visualization…" not in data_labels
    assert "UMAP Visualization…" not in data_labels
    assert "Self-Organizing Map…" not in data_labels
    assert data_labels.index("Dimensionality Reduction") == data_labels.index("MedChem Plots") + 1
    medchem = next(a.menu() for a in data.actions() if a.text().replace("&", "") == "MedChem Plots")
    assert [a.text().replace("&", "") for a in medchem.actions()] == [
        "BOILED-Egg…",
        "Golden Triangle…",
        "LipE…",
    ]
    dimred = next(
        a.menu() for a in data.actions() if a.text().replace("&", "") == "Dimensionality Reduction"
    )
    assert [a.text().replace("&", "") for a in dimred.actions()] == [
        "Principal Component Analysis…",
        "t-SNE Visualization…",
        "UMAP Visualization…",
        "Self-Organizing Map…",
    ]
    w.close()
