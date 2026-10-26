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

"""Macros menu entry. The editor and runner stay out of this module's import."""

from __future__ import annotations

from typing import Any


class MacroTools:
    """Open the macro editor. Methods use ``self._app``, not the window as self."""

    def __init__(self, app: Any) -> None:
        self._app = app

    def open_macros(self) -> None:
        """Show the macro library. One editor window is reused."""
        from PyQt5.QtCore import Qt

        from .dialogs.macros import MacroDialog
        from .singleton_modeless_dialog import reuse_or_show_modeless_singleton

        app = self._app

        def _factory() -> MacroDialog:
            dialog = MacroDialog(app)
            dialog.setModal(False)
            dialog.setAttribute(Qt.WA_DeleteOnClose, True)
            return dialog

        reuse_or_show_modeless_singleton(app, "_macro_dialog", _factory)
