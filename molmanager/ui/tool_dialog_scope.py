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

"""Tool dialog scope UI: modeless show, selection-scope sync, empty-selection guard.

Lives off plot/ingest mixins so Cluster/QSAR/MPO and ``analysis_job_support`` do
not depend on plot-mixin behavior.
"""

from __future__ import annotations

from typing import Any, Protocol

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox, QWidget

from .app_roles import TableSelection


class ToolScopeHost(TableSelection, Protocol):
    """What ``ToolDialogScope`` needs: the table, selection counts, and a parent widget.

    Beyond the ``TableSelection`` kernel role this names three window forwards. They are
    the remaining coupling to the facade, so the list is meant to shrink, not grow.
    """

    def window(self) -> QWidget: ...
    def _selected_row_count_fast(self) -> int: ...
    def _selected_logical_rows(self) -> list: ...


class ToolDialogScope:
    """Collaborator: modeless tool dialogs and selected-rows-only scope chrome.

    Owns the list of dialogs whose scope checkbox tracks the table selection; the window
    reaches these methods through ``install_window_forwards``.
    """

    def __init__(self, app: ToolScopeHost) -> None:
        self._app = app
        self._scope_sync_targets: list = []

    def _prepare_tool_dialog(self, dialog: QDialog) -> None:
        """Let the main table stay interactive and keep scope UI in sync while the dialog is open."""
        dialog.setModal(False)
        dialog.setWindowModality(Qt.NonModal)
        self._attach_tool_scope_sync(dialog, on_finished_signal=dialog.finished)

    def _attach_tool_scope_sync(self, target, *, on_finished_signal) -> None:
        """Track a dialog/plot ``only_selected_cb`` until teardown.

        Labels are refreshed by the selection fan-out
        (:meth:`_refresh_attached_tool_scope_labels`), once per selection change.
        """
        if getattr(target, "only_selected_cb", None) is None:
            return
        prior = getattr(target, "_scope_sync_disconnect", None)
        if callable(prior):
            prior()
        if target not in self._scope_sync_targets:
            self._scope_sync_targets.append(target)
        self._sync_dialog_only_selected_scope(target)

        def teardown(*_args):
            try:
                self._scope_sync_targets.remove(target)
            except ValueError:
                pass
            target._scope_sync_disconnect = None

        on_finished_signal.connect(teardown)
        target._scope_sync_disconnect = teardown

    def _sync_dialog_only_selected_scope(
        self, dialog: QDialog, *, selected_count: int | None = None
    ) -> None:
        """Refresh a tool dialog's scope checkbox label/count from the current table selection."""
        cb = getattr(dialog, "only_selected_cb", None)
        if cb is None:
            return
        try:
            from PyQt5 import sip

            if sip.isdeleted(cb):
                return
        except Exception:
            pass
        prefix = getattr(dialog, "_only_selected_scope_prefix", "Selected Rows Only")
        n = self._app._selected_row_count_fast() if selected_count is None else int(selected_count)
        try:
            if n > 0:
                cb.setEnabled(True)
                cb.setText(f"{prefix} ({n} row(s))")
            else:
                cb.setEnabled(False)
                cb.setChecked(False)
                cb.setText(prefix)
        except RuntimeError:
            return

    def _refresh_attached_tool_scope_labels(self) -> None:
        """Update all open tool/plot scope checkboxes once per selection fan-out."""
        n = self._app._selected_row_count_fast()
        alive: list = []
        for target in list(self._scope_sync_targets):
            try:
                from PyQt5 import sip

                if sip.isdeleted(target):
                    continue
            except Exception:
                pass
            alive.append(target)
            self._sync_dialog_only_selected_scope(target, selected_count=n)
        self._scope_sync_targets = alive

    def _abort_if_only_selected_but_empty(
        self, only_selected: bool, allowed: set | frozenset | None, title: str
    ) -> bool:
        """Return True if the user should stop (warning shown for empty selection)."""
        if only_selected and not allowed:
            QMessageBox.warning(
                self._app.window(),
                title,
                "\u201cSelected Rows Only\u201d is checked but nothing is selected.",
            )
            return True
        return False


def prepare_tool_dialog(app: Any, dialog: QDialog) -> None:
    """Module entry used by ``analysis_job_support`` (no plot-mixin import)."""
    scope = getattr(app, "tool_scope", None)
    if scope is not None:
        scope._prepare_tool_dialog(dialog)
        return
    app._prepare_tool_dialog(dialog)


def abort_if_only_selected_but_empty(
    app: Any,
    only_selected: bool,
    allowed: set | frozenset | None,
    title: str,
) -> bool:
    scope = getattr(app, "tool_scope", None)
    if scope is not None:
        return bool(scope._abort_if_only_selected_but_empty(only_selected, allowed, title))
    return bool(app._abort_if_only_selected_but_empty(only_selected, allowed, title))
