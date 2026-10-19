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

"""QSAR and AutoQSAR tool windows (Data menu)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox


class QsarMixin:
    def open_qsar_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "QSAR",
                "Open a file or add rows with activity and descriptor data first.",
            )
            return
        from ..dialogs.qsar import QSARDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            d = QSARDialog(self)
            self._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        reuse_or_show_modeless_singleton(
            self,
            "_qsar_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def open_auto_qsar_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "AutoQSAR",
                "Open a file or add rows with activity data first.",
            )
            return
        from ..dialogs.auto_qsar import AutoQSARDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            dialog = AutoQSARDialog(self)
            self._prepare_tool_dialog(dialog)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            return dialog

        reuse_or_show_modeless_singleton(
            self,
            "_auto_qsar_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )

    def open_comsia_dialog(self) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "CoMSIA",
                "Open a file or add rows with activity data and aligned 3D poses first.",
            )
            return
        from ..dialogs.comsia import ComsiaDialog
        from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton

        def _factory():
            dialog = ComsiaDialog(self)
            self._prepare_tool_dialog(dialog)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            return dialog

        reuse_or_show_modeless_singleton(
            self,
            "_comsia_dialog",
            _factory,
            on_reused_visible=lambda dlg: self._sync_dialog_only_selected_scope(dlg),
        )
