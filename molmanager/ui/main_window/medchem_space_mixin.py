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

"""BOILED-Egg, golden-triangle, and LipE plots (Data menu)."""

from __future__ import annotations

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class MedChemSpaceMixin:
    def open_boiled_egg_plot(self) -> None:
        self._open_medchem_space_dialog(
            plot_kind="boiled_egg",
            title="BOILED-Egg plot",
            attr="_boiled_egg_dialog",
        )

    def open_golden_triangle_plot(self) -> None:
        self._open_medchem_space_dialog(
            plot_kind="golden_triangle",
            title="Golden Triangle plot",
            attr="_golden_triangle_dialog",
        )

    def open_lipe_plot(self) -> None:
        self._open_medchem_space_dialog(
            plot_kind="lipe",
            title="LipE plot",
            attr="_lipe_dialog",
            present_settings=True,
        )

    def _open_medchem_space_dialog(
        self,
        *,
        plot_kind: str,
        title: str,
        attr: str,
        present_settings: bool = False,
    ) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Data",
                "Open a file or add rows with structures to plot medicinal chemistry space.",
            )
            return
        from ..dialogs.medchem_space import MedChemSpaceDialog

        def _factory():
            d = MedChemSpaceDialog(self, plot_kind=plot_kind, window_title=title)
            self._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        previous = getattr(self, attr, None) if present_settings else None
        dlg = reuse_or_show_modeless_singleton(
            self,
            attr,
            _factory,
            show=not present_settings,
            on_reused_visible=(None if present_settings else self._sync_dialog_only_selected_scope),
        )
        if not present_settings:
            dlg.raise_()
            dlg.activateWindow()
            return
        self._sync_dialog_only_selected_scope(dlg)
        panel = getattr(dlg, "_panel", None)
        if dlg is previous and panel is not None and panel._full_dataset is not None:
            opener = getattr(panel, "_open_setup_dialog", None)
            if callable(opener):
                opener()
                return
        present = getattr(panel, "present_initial_ui", None)
        if callable(present):
            present()
            return
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
