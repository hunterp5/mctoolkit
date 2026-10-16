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

"""Lists menu: save the current selection under a name, recall it, and delete lists."""

from __future__ import annotations

from PyQt5.QtWidgets import QAction, QDialog, QMessageBox

from ..row_lists import RowListStore, normalize_list_name


class RowListsMixin:
    def _row_list_store(self) -> RowListStore:
        store = getattr(self, "_row_lists", None)
        if not isinstance(store, RowListStore):
            store = RowListStore()
            self._row_lists = store
        return store

    def _rebuild_lists_menu(self) -> None:
        """Insert one action per named list above the Manage Lists divider."""
        menu = getattr(self, "_lists_menu", None)
        anchor = getattr(self, "_act_lists_footer_separator", None)
        if menu is None or anchor is None:
            return
        for act in list(getattr(self, "_list_name_actions", ())):
            menu.removeAction(act)
            act.deleteLater()
        actions: list[QAction] = []
        store = self._row_list_store()
        for name in store.names():
            act = QAction(name.replace("&", "&&"), menu)
            count = self._live_row_list_count(name)
            noun = "row" if count == 1 else "rows"
            act.setToolTip(f"Select the {count} {noun} in this list.")
            act.setData(name)
            act.triggered.connect(
                lambda _checked=False, list_name=name: self.apply_row_list(list_name)
            )
            menu.insertAction(anchor, act)
            actions.append(act)
        self._list_name_actions = actions

    def _live_row_list_count(self, name: str) -> int:
        finder = getattr(self, "logical_row_for_oid", None)
        n = 0
        for oid in self._row_list_store().oids(name):
            if not callable(finder):
                n += 1
                continue
            try:
                row = int(finder(int(oid)))
            except (TypeError, ValueError):
                continue
            if row >= 0:
                n += 1
        return n

    def add_selected_to_list(self) -> None:
        """Prompt for a list name and store the current row selection under it."""
        oids = self._selected_oids_set()
        if not oids:
            QMessageBox.information(
                self,
                "Add Selected to List",
                "No rows are selected. Select one or more rows in the table first.",
            )
            return
        from ..dialogs.row_lists import AddSelectedToListDialog

        dlg = AddSelectedToListDialog(self, existing_names=self._row_list_store().names())
        if dlg.exec_() != QDialog.Accepted:
            return
        self.commit_named_row_list(dlg.list_name(), oids)

    def commit_named_row_list(self, name: str, oids: set[int] | frozenset[int] | list[int]) -> bool:
        """Add *oids* to *name*. Return True when the list was created or gained rows."""
        key = normalize_list_name(name)
        if not key or not oids:
            return False
        created, n_new = self._row_list_store().add(key, oids)
        label = getattr(self, "status_label", None)
        if not created and n_new == 0:
            if label is not None:
                label.setText(f'Selected rows are already in list "{key}".')
            return False
        self._rebuild_lists_menu()
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        if label is not None:
            if created:
                label.setText(f'Created list "{key}" with {n_new} row(s).')
            else:
                label.setText(f'Added {n_new} row(s) to list "{key}".')
        return True

    def apply_row_list(self, name: str) -> int:
        """Replace the table selection with the rows stored in *name*."""
        oids = self._row_list_store().oids(name)
        return int(self.select_table_oids(oids, extra_status=f"List: {name}."))

    def manage_row_lists(self) -> None:
        """Open the dialog that deletes named lists."""
        from ..dialogs.row_lists import ManageListsDialog

        store = self._row_list_store()
        entries = [(name, self._live_row_list_count(name)) for name in store.names()]
        dlg = ManageListsDialog(self, entries=entries)
        if dlg.exec_() != QDialog.Accepted:
            return
        removed = store.retain(dlg.remaining_names())
        if not removed:
            return
        self._rebuild_lists_menu()
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()
        label = getattr(self, "status_label", None)
        if label is not None:
            noun = "list" if len(removed) == 1 else "lists"
            label.setText(f"Deleted {len(removed)} {noun}.")

    def clear_row_lists(self) -> None:
        self._row_list_store().clear()
        self._rebuild_lists_menu()

    def collect_row_lists_session(self, *, oids: set[int] | None = None) -> list[dict] | None:
        """Lists for the session document. Omit lists whose rows are not in *oids*."""
        keep = oids
        if keep is None:
            model = getattr(self, "_table_model", None)
            all_oids = getattr(model, "all_oids_in_order", None)
            if callable(all_oids):
                keep = {int(x) for x in all_oids()}
        payload = self._row_list_store().to_session(keep_oids=keep)
        return payload or None

    def restore_row_lists_session(self, payload: object | None) -> None:
        self._row_list_store().load_session(payload)
        self._rebuild_lists_menu()
