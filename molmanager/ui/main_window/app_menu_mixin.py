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

"""Main menubar and workspace dialog openers."""

from __future__ import annotations

import sys
from collections.abc import Sequence

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QHBoxLayout,
    QMenu,
    QToolButton,
    QWidget,
)

from ...platform_support.config import load_config
from ...table.open_messages import preflight_open_path
from ..recent_paths import (
    KIND_SESSION,
    RecentEntry,
    clear_recent,
    forget_recent,
    load_recent,
    recent_display_name,
)
from .menu_builder import install_menu_specs
from .menu_spec import MAIN_WINDOW_MENUS


class AppMenuMixin:
    def init_menubar(self):
        mb = self.menuBar()
        install_menu_specs(self, mb, MAIN_WINDOW_MENUS)
        calc = getattr(self, "_act_custom_calc", None)
        if calc is not None and load_config().disable_custom_calc:
            calc.setEnabled(False)
            calc.setToolTip("Calculator disabled by MOLMANAGER_DISABLE_CUSTOM_CALC.")
        if sys.platform == "win32":
            mb.setNativeMenuBar(False)
        self._install_menubar_corner(mb)
        self._sync_main_toolbar_for_table_ready()

    def _populate_recent_menu(self) -> None:
        """Fill File → Open Recent with saved files, then saved sessions."""
        menu = self._recent_menu
        menu.clear()
        entries = load_recent()
        files = [entry for entry in entries if entry.kind != KIND_SESSION]
        sessions = [entry for entry in entries if entry.kind == KIND_SESSION]
        if not files and not sessions:
            empty = menu.addAction("No Recent Items")
            empty.setEnabled(False)
            return
        if files:
            self._add_recent_section(menu, "Files", files)
        if files and sessions:
            menu.addSeparator()
        if sessions:
            self._add_recent_section(menu, "Sessions", sessions)
        menu.addSeparator()
        clear = menu.addAction("Clear Recent")
        clear.triggered.connect(lambda *_args: clear_recent())

    def _add_recent_section(self, menu: QMenu, title: str, entries: Sequence[RecentEntry]) -> None:
        header = menu.addAction(title)
        header.setEnabled(False)
        peers = [entry.path for entry in entries]
        for entry in entries:
            label = recent_display_name(entry.path, peers).replace("&", "&&")
            act = menu.addAction(label)
            act.setToolTip(entry.path)
            act.setStatusTip(entry.path)
            act.triggered.connect(
                lambda *_args, kind=entry.kind, path=entry.path: self._open_recent_entry(kind, path)
            )

    def _open_recent_entry(self, kind: str, path: str) -> None:
        """Open a recent data file or session. Drop the entry when the path is unusable."""
        problem = preflight_open_path(path)
        if problem:
            forget_recent(path)
            title = "Open Session" if kind == KIND_SESSION else "Open File"
            self._warn_could_not_open(title, problem)
            return
        if kind == KIND_SESSION:
            self.apply_saved_session_from_file(path)
            return
        self.load_file(path)

    def _install_menubar_corner(self, mb) -> None:
        corner = QWidget(mb)
        corner_ly = QHBoxLayout(corner)
        corner_ly.setContentsMargins(0, 0, 4, 0)

        btn_layout = QToolButton(corner)
        btn_layout.setText("Layout")
        btn_layout.setToolTip("Choose how the table and plot panes are arranged.")
        btn_layout.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_layout.setAutoRaise(True)
        btn_layout.setFocusPolicy(Qt.NoFocus)
        btn_layout.setFont(mb.font())
        btn_layout.clicked.connect(self.open_workspace_layout_picker)
        self._btn_workspace_layout = btn_layout
        corner_ly.addWidget(btn_layout)

        btn_proc = QToolButton(corner)
        btn_proc.setText("Log")
        btn_proc.setToolTip(
            "View running and queued jobs, and the session log "
            "(tool output, status history, warnings)."
        )
        btn_proc.setToolButtonStyle(Qt.ToolButtonTextOnly)
        btn_proc.setAutoRaise(True)
        btn_proc.setFocusPolicy(Qt.NoFocus)
        btn_proc.setFont(mb.font())
        btn_proc.clicked.connect(self.open_processes_dialog)
        self._btn_processes = btn_proc
        corner_ly.addWidget(btn_proc)
        mb.setCornerWidget(corner, Qt.TopRightCorner)

    def _set_ingest_loading(self, loading: bool) -> None:
        """Track file/import ingest and gray out the main toolbar until the table is ready."""
        self._ingest_loading = bool(loading)
        self._sync_main_toolbar_for_table_ready()
        self._sync_status_chrome_for_workspace()

    def _sync_main_toolbar_for_table_ready(self) -> None:
        """Disable menubar and Layout while ``_ingest_loading``.

        Log stays enabled so a long load can still be inspected.
        """
        if getattr(self, "_dock_results_mode", False):
            return
        enabled = not bool(getattr(self, "_ingest_loading", False))
        mb = self.menuBar()
        for action in mb.actions():
            menu = action.menu()
            if menu is not None:
                menu.setEnabled(enabled)
            else:
                action.setEnabled(enabled)
        calc = getattr(self, "_act_custom_calc", None)
        calc_blocked = bool(load_config().disable_custom_calc)
        for action in getattr(self, "_hotkey_actions", {}).values():
            if action is None:
                continue
            if action is calc and calc_blocked:
                action.setEnabled(False)
            else:
                action.setEnabled(enabled)
        btn = getattr(self, "_btn_workspace_layout", None)
        if btn is not None:
            btn.setEnabled(enabled)

    def open_protein_viewer(self):
        """Open the Protein Viewer window (3Dmol.js + chain Manager)."""
        dlg = self._ensure_protein_viewer(show=True)
        finder = getattr(self, "_live_pose_browser", None)
        if dlg is not None and callable(finder) and finder() is not None:

            def _sync_live_poses() -> None:
                browser = finder() if callable(finder) else None
                if browser is None:
                    return
                begin = getattr(dlg, "begin_canvas_load", None)
                end = getattr(dlg, "end_canvas_load", None)
                if callable(begin):
                    from ..strings import LOADING_DETAIL_PROTEIN_VIEWER

                    begin(LOADING_DETAIL_PROTEIN_VIEWER)
                try:
                    snap = getattr(self, "_last_dock_results", None) or {}
                    prepare = getattr(self, "_prepare_protein_viewer_for_poses", None)
                    if callable(prepare):
                        prepare(
                            dlg, snap.get("receptor_path"), crystal_path=snap.get("crystal_path")
                        )
                    self._dock_pose_zoomed = False
                    sync = getattr(browser, "_sync_pose_views", None)
                    if callable(sync):
                        sync()
                finally:
                    if callable(end):
                        end()

            queue = getattr(dlg, "queue_after_canvas_bootstrap", None)
            if callable(queue) and not getattr(dlg, "_canvas_bootstrapped", True):
                queue(_sync_live_poses)
            else:
                _sync_live_poses()
        return dlg

    def _ensure_protein_viewer(self, *, show: bool = True):
        """Create or reuse the Protein Viewer; apply a saved session snapshot on first create."""
        from ..protein_viewer import ProteinViewerDialog
        from ..qt_widget_utils import qobject_is_deleted
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        existing = getattr(self, "_protein_viewer_dialog", None)
        created = existing is None or qobject_is_deleted(existing)

        reuse_or_show_modeless_singleton(
            self,
            "_protein_viewer_dialog",
            lambda: ProteinViewerDialog(self),
            show=False,
        )
        dlg = self._protein_viewer_dialog
        payload = getattr(self, "_protein_viewer_session", None)
        has_content = bool(created and isinstance(payload, dict) and payload.get("structures"))
        if dlg is not None and created and not getattr(dlg, "_canvas_bootstrapped", False):
            begin = getattr(dlg, "begin_canvas_load", None)
            if callable(begin):
                from ..strings import (
                    LOADING_DETAIL_PROTEIN_VIEWER,
                    LOADING_DETAIL_PROTEIN_VIEWER_START,
                )

                detail = (
                    LOADING_DETAIL_PROTEIN_VIEWER
                    if has_content
                    else LOADING_DETAIL_PROTEIN_VIEWER_START
                )
                begin(detail, paint=False)
            if has_content:
                setter = getattr(dlg, "set_pending_session_state", None)
                if callable(setter):
                    setter(payload)
        if show and dlg is not None:
            dlg.show()
            dlg.raise_()
            dlg.activateWindow()
            flush = getattr(dlg, "flush_canvas_load_paint", None)
            if created and callable(flush):
                flush()
        if created and dlg is not None:
            boot = getattr(dlg, "schedule_canvas_bootstrap", None)
            if callable(boot):
                boot()
        return dlg

    def open_protein_sequence(self):
        """Open the Protein Sequence MSA window (independent of Viewer Sequence)."""
        from ..dialogs.protein_sequence_msa import ProteinSequenceMsaDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        reuse_or_show_modeless_singleton(
            self,
            "_protein_msa_dialog",
            lambda: ProteinSequenceMsaDialog(self),
            show=True,
        )
        return self._protein_msa_dialog

    def open_simulation(self):
        """Open the simulation workspace for the current protein viewer structure."""
        from ..simulation.window import SimulationWindow
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        viewer = self._ensure_protein_viewer(show=False)
        window = reuse_or_show_modeless_singleton(
            self,
            "_simulation_window",
            lambda: SimulationWindow(self, viewer=viewer),
            show=True,
        )
        pending = getattr(self, "_simulation_session", None)
        if isinstance(pending, dict) and not getattr(window, "_session_applied", False):
            from ...sim.document import SimulationDocumentError, document_from_dict

            try:
                window.document = document_from_dict(pending)
                window._reload_stages()
                window._session_applied = True
            except (SimulationDocumentError, TypeError, ValueError):
                window._session_applied = True
        return window

    def start_simulation_macro(self, path: str, preset: str, row_scope: str, on_done) -> None:
        """Load a saved document or preset and start it from a macro step."""
        window = self.open_simulation()
        if path:
            window.load_path(path)
        elif preset:
            window.load_preset(preset)
        window.run_finished.connect(lambda result, done=on_done: _finish_simulation_macro(result, done))
        window.start_run(row_scope=row_scope or "structure")

    def open_workspace_layout_picker(self) -> None:
        """Show the graphic layout picker and apply the chosen preset."""
        from ..dialogs.workspace_layout_picker import WorkspaceLayoutPickerDialog

        mgr = getattr(self, "_workspace_layout", None)
        current = mgr.layout_id if mgr is not None else None
        dlg = WorkspaceLayoutPickerDialog(self, current_layout_id=current)
        dlg.layout_chosen.connect(self.apply_workspace_layout)
        dlg.exec_()

    def apply_workspace_layout(self, layout_id: str) -> None:
        """Apply a workspace layout preset and undock plots that no longer fit."""
        mgr = getattr(self, "_workspace_layout", None)
        if mgr is None:
            return
        extras = mgr.apply_layout(layout_id, preserve_plots=True)
        for w in extras:
            self._float_released_plot_widget(w)
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        self.status_label.setText(f"Layout: {layout_id.replace('_', ' ')}.")

    def _on_processes_dialog_destroyed(self) -> None:
        self._processes_dialog = None

    def open_processes_dialog(self) -> None:
        from ..processes_dialog import ProcessesDialog

        dlg = getattr(self, "_processes_dialog", None)
        if dlg is not None:
            try:
                dlg.show()
                dlg.raise_()
                dlg.activateWindow()
                dlg._reload()
                return
            except RuntimeError:
                self._processes_dialog = None
        w = ProcessesDialog(self)
        self._processes_dialog = w
        w.destroyed.connect(self._on_processes_dialog_destroyed)
        w.show()


def _finish_simulation_macro(result, on_done) -> None:
    """Tell the macro runner whether the simulation finished."""
    if isinstance(result, dict) and result.get("status") == "failed":
        on_done(str(result.get("message") or "Simulation failed."))
        return
    on_done(None)
