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

"""Open Plotter, Sketcher, Browser structure views, and Data analysis."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class ViewerOpenersMixin:
    def open_data_analysis(self):
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self, "Data", "Open a file or add rows so the table has data to analyze."
            )
            return
        from ..dialogs.data_analysis import DataAnalysisDialog

        def _factory() -> DataAnalysisDialog:
            dlg = DataAnalysisDialog(self)
            self._prepare_tool_dialog(dlg)
            return dlg

        def _on_reused(dlg: DataAnalysisDialog) -> None:
            self._sync_dialog_only_selected_scope(dlg)
            dlg._sync_selected_columns_only_scope()
            dlg.refresh_table_data()

        reuse_or_show_modeless_singleton(
            self,
            "_data_analysis_dialog",
            _factory,
            on_reused_visible=_on_reused,
        )

    def open_plot(self):
        if not self.headers:
            return
        # Prefer opening a new floating plotter so multiple PlotWidgets can be docked.
        dlg = self._create_plot_dialog()
        self._register_plot_dialog(dlg)
        self._sync_dialog_only_selected_scope(dlg)
        self._sync_active_plots_from_table_selection()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def open_sketcher(self, mol=None, *, source_oid=None, update_on_close=False):
        # QAction.triggered passes False; never treat that as a molecule.
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        from ..sketcher import SketcherDialog

        def _on_reuse(dlg):
            if mol is not None:
                if not dlg.load_structure_from_mol(mol):
                    return
            elif update_on_close:
                dlg.canvas.clear(push_undo=False)
            dlg.set_source_entry(source_oid, update_on_close=update_on_close)

        reuse_or_show_modeless_singleton(
            self,
            "_sketcher_dialog",
            lambda: SketcherDialog(
                self,
                initial_mol=mol,
                source_oid=source_oid,
                update_on_close=update_on_close,
            ),
            on_reused_visible=_on_reuse if mol is not None or update_on_close else None,
        )

    def open_molecule_3d(self, mol=None, *, source_oid=None):
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        if mol is None and source_oid is None:
            return
        self.open_selection_browser(focus_oid=source_oid, preview_mode="3dmol_3d")

    def open_molecule_2d(self, mol=None, *, source_oid=None):
        if mol is not None and not isinstance(mol, Chem.Mol):
            mol = None
        if mol is None and source_oid is None:
            return
        self.open_selection_browser(focus_oid=source_oid, preview_mode="3dmol_2d")
