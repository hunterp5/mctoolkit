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

"""PCA, t-SNE, UMAP, and SOM dialogs (Data → Dimensionality Reduction)."""

from __future__ import annotations

from contextlib import suppress

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


class DimensionReductionMixin:
    def open_pca_dialog(self) -> None:
        self._open_dimension_reduction_dialog("pca")

    def open_tsne_dialog(self) -> None:
        self._open_dimension_reduction_dialog("tsne")

    def open_umap_dialog(self) -> None:
        self._open_dimension_reduction_dialog("umap")

    def open_som_dialog(self) -> None:
        self._open_dimension_reduction_dialog("som")

    def _open_dimension_reduction_dialog(self, kind: str) -> None:
        if not self.headers or self._table_model.rowCount() == 0:
            QMessageBox.information(
                self,
                "Dimensionality Reduction",
                "Open a file or add rows so the table has numeric data to analyze.",
            )
            return
        from ..dialogs.dimensionality_reduction import DIMRED_FLOATING_DIALOGS

        dialog_cls = DIMRED_FLOATING_DIALOGS.get(kind)
        if dialog_cls is None:
            QMessageBox.warning(
                self, "Dimensionality Reduction", f"Unknown embedding method: {kind!r}"
            )
            return
        attr = f"_{kind}_dialog"

        def _factory():
            d = dialog_cls(self)
            self._prepare_tool_dialog(d)
            d.setAttribute(Qt.WA_DeleteOnClose, True)
            return d

        previous = getattr(self, attr, None)
        dlg = reuse_or_show_modeless_singleton(
            self,
            attr,
            _factory,
            show=False,
        )
        if dlg is previous:
            with suppress(RuntimeError, AttributeError):
                getattr(dlg, "_panel", dlg)._reload_columns()
            self._sync_dialog_only_selected_scope(dlg)
            panel = getattr(dlg, "_panel", None)
            if panel is not None and getattr(panel, "_last_result", None) is not None:
                opener = getattr(panel, "_open_setup_dialog", None)
                if callable(opener):
                    opener()
                    return
        self._present_dimension_reduction_dialog(dlg)

    def _present_dimension_reduction_dialog(self, dlg) -> None:
        """Show embedding setup until a figure exists; then raise the plot window."""
        panel = getattr(dlg, "_panel", None)
        present = getattr(panel, "present_initial_ui", None)
        if callable(present):
            present()
            return
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
