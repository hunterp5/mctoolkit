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

"""Drug Design Studio: a floating sketcher and live property strip."""

from __future__ import annotations

from PyQt5.QtWidgets import QMessageBox
from rdkit import Chem

from ..qt_widget_utils import qobject_is_deleted
from ..strings import TOOL_DESIGN_STUDIO


class DesignStudioMixin:
    """Open the design studio in its own window and load a structure into it."""

    def open_design_studio(self) -> None:
        self._show_design_studio()

    def open_design_studio_for_molecule(self, mol, *, caption: str = "") -> None:
        """Show the studio and replace the sketch with *mol*."""
        if mol is None or not isinstance(mol, Chem.Mol):
            self.status_label.setText(f"{TOOL_DESIGN_STUDIO}: that structure could not be read.")
            return
        panel = self._show_design_studio()
        if panel is None:
            return
        if not panel.load_molecule(mol, caption=caption):
            self.status_label.setText(f"{TOOL_DESIGN_STUDIO}: could not draw that structure.")
            return
        if caption:
            self.status_label.setText(f"{TOOL_DESIGN_STUDIO}: {caption}")

    def open_design_studio_for_smiles(self, smiles: str, *, caption: str = "") -> None:
        """Show the studio and replace the sketch with *smiles*."""
        mol = Chem.MolFromSmiles((smiles or "").strip())
        if mol is None:
            self.status_label.setText(f"{TOOL_DESIGN_STUDIO}: that structure could not be read.")
            return
        self.open_design_studio_for_molecule(mol, caption=caption)

    def _show_design_studio(self):
        from ..design_studio_panel import DesignStudioPanel

        try:
            for widget in self.iter_docked_plot_widgets():
                if isinstance(widget, DesignStudioPanel):
                    self._reveal_docked_design_studio(widget)
                    return widget
            existing = getattr(self, "_design_studio_dialog", None)
            if existing is not None and not qobject_is_deleted(existing):
                panel = getattr(existing, "_panel", None)
                if isinstance(panel, DesignStudioPanel):
                    existing.show()
                    existing.raise_()
                    return panel
            panel = DesignStudioPanel(self, self)
            dialog = panel.create_floating_dialog(self)
            prepare = getattr(self, "_prepare_tool_dialog", None)
            if callable(prepare):
                prepare(dialog)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            self.status_label.setText(f"{TOOL_DESIGN_STUDIO}: opened.")
            return panel
        except (RuntimeError, TypeError, ValueError) as exc:
            QMessageBox.warning(self, TOOL_DESIGN_STUDIO, str(exc) or "Could not open the studio.")
            return None

    def _reveal_docked_design_studio(self, widget) -> None:
        mgr = getattr(self, "_workspace_layout", None)
        pane = mgr.pane_for_widget(widget) if mgr is not None else None
        if pane is not None:
            pane.add_plot_widget(widget)
        show = getattr(self, "show_docked_plot_panel", None)
        if callable(show):
            show()
        widget.raise_()
