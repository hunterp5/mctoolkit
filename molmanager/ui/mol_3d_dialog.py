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

"""Floating ligand 3D/2D viewer dialog and openers."""

from __future__ import annotations

import base64
import json

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QDialog, QMessageBox, QVBoxLayout, QWidget

from rdkit import Chem

from ..conformers.conformer_column_codec import conformer_mol_blocks_b64_json
from .mol_3d_prepare import prepare_mol_2d, prepare_mol_3d
from .mol_3d_widget import Molecule3DViewerWidget
from .qt_widget_utils import make_window_resizable


class Molecule3DViewerDialog(QDialog):
    """Floating window hosting a :class:`Molecule3DViewerWidget`."""

    def __init__(
        self,
        mol: Chem.Mol | None,
        parent: QWidget | None = None,
        *,
        window_title: str = "View in 3D",
        flat: bool = False,
        multi_conf_blocks_json_b64: str | None = None,
        multi_conf_initial_superpose: bool = False,
        multi_conf_strain_overlay_json_b64: str = "",
        multi_conf_initial_index: int = 0,
        export_parent_oid: int | None = None,
        export_confs_column: str = "confs",
        strain_overlay: dict | None = None,
        source_oid: int | None = None,
        viewer_widget: Molecule3DViewerWidget | None = None,
    ):
        super().__init__(parent)
        self.parent_app = parent
        self.setModal(False)
        self.setWindowModality(Qt.NonModal)
        self.setWindowTitle(window_title)
        self.setAttribute(Qt.WA_DeleteOnClose, True)
        self._force_close = False

        if viewer_widget is not None:
            self._viewer_widget = viewer_widget
            self._viewer_widget.setParent(self)
            self._viewer_widget._window_title = window_title
            self._viewer_widget.rebind_parent_app(parent)
        else:
            if mol is None:
                raise ValueError("mol is required when viewer_widget is not provided")
            self._viewer_widget = Molecule3DViewerWidget(
                mol,
                parent,
                window_title=window_title,
                flat=flat,
                multi_conf_blocks_json_b64=multi_conf_blocks_json_b64,
                multi_conf_initial_superpose=multi_conf_initial_superpose,
                multi_conf_strain_overlay_json_b64=multi_conf_strain_overlay_json_b64,
                multi_conf_initial_index=multi_conf_initial_index,
                export_parent_oid=export_parent_oid,
                export_confs_column=export_confs_column,
                strain_overlay=strain_overlay,
                source_oid=source_oid,
            )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(self._viewer_widget, 1)
        self._viewer_widget._sync_footer_chrome()
        make_window_resizable(self)
        min_w = int(self._viewer_widget.embedded_minimum_width())
        self._viewer_widget.setMinimumWidth(min_w)
        self.setMinimumWidth(min_w)
        self.resize(max(min_w, 1280), 800)

    def closeEvent(self, event) -> None:  # noqa: N802 — Qt API name
        from .dockable_plot import handle_floating_plot_close_event

        handle_floating_plot_close_event(
            self,
            event,
            title="Close Viewer",
            message="Close this viewer?",
        )


def open_molecule_3d_viewer(
    mol: Chem.Mol,
    parent: QWidget | None = None,
    *,
    title: str = "View in 3D",
    source_oid: int | None = None,
) -> None:
    """Show *mol* in 3Dmol: multiple RDKit conformers use a conformer slider; otherwise embed once (ETKDG)."""
    if mol is None or not isinstance(mol, Chem.Mol):
        return
    try:
        nconf = int(mol.GetNumConformers())
    except Exception:
        nconf = 0
    if nconf > 1:
        try:
            m = Chem.Mol(mol)
        except Exception:
            m = mol
        payload = conformer_mol_blocks_b64_json(m)
        try:
            inner = json.loads(base64.b64decode(payload.encode("ascii")))
        except Exception:
            inner = []
        if not inner:
            QMessageBox.warning(
                parent,
                title,
                "This molecule reports multiple conformers but none could be serialized for the 3D viewer.",
            )
            return
        win_title = title if title else "View in 3D"
        if win_title == "View in 3D":
            win_title = "View Conformers"
        win_title = f"{win_title} ({len(inner)} conformers)"
        dlg = Molecule3DViewerDialog(
            m,
            parent,
            window_title=win_title,
            flat=False,
            multi_conf_blocks_json_b64=payload,
            multi_conf_initial_superpose=False,
            source_oid=source_oid,
            export_parent_oid=source_oid,
        )
        dlg.show()
        return

    m3d = prepare_mol_3d(mol)
    if m3d is None:
        QMessageBox.warning(
            parent,
            title,
            "Could not build a 3D conformation for this structure.\n"
            "Try editing the structure or simplifying the molecule.",
        )
        return
    dlg = Molecule3DViewerDialog(m3d, parent, window_title=title, flat=False, source_oid=source_oid)
    dlg.show()


def open_conformation_viewer_from_blocks_payload(
    parent: QWidget | None,
    blocks_json_b64: str,
    *,
    title: str = "View Conformers",
    initial_superpose: bool = False,
    strain_overlay: dict | None = None,
    initial_conf_index: int = 0,
    export_parent_oid: int | None = None,
    export_confs_column: str = "confs",
    source_oid: int | None = None,
) -> None:
    """Open the multi-conformer 3Dmol viewer (one-at-a-time and/or superpose) from packed mol blocks."""
    b = (blocks_json_b64 or "").strip()
    if not b:
        return
    n = 0
    try:
        inner = json.loads(base64.b64decode(b.encode("ascii")))
        if isinstance(inner, list):
            n = len(inner)
    except Exception:
        pass
    if n < 1:
        QMessageBox.warning(
            parent,
            title,
            "No conformers could be read from this cell for the 3D viewer.",
        )
        return
    strain_b64 = ""
    if strain_overlay:
        try:
            strain_b64 = base64.b64encode(
                json.dumps(strain_overlay, separators=(",", ":")).encode("utf-8")
            ).decode("ascii")
        except Exception:
            strain_b64 = ""
    dummy = Chem.MolFromSmiles("C")
    win_title = title if title else "View Conformers"
    if n > 1:
        win_title = f"{win_title} ({n} conformers)"
    if source_oid is None:
        source_oid = export_parent_oid
    dlg = Molecule3DViewerDialog(
        dummy,
        parent,
        window_title=win_title,
        flat=False,
        multi_conf_blocks_json_b64=b,
        multi_conf_initial_superpose=initial_superpose,
        multi_conf_strain_overlay_json_b64=strain_b64,
        multi_conf_initial_index=int(initial_conf_index),
        export_parent_oid=export_parent_oid,
        export_confs_column=export_confs_column,
        strain_overlay=strain_overlay,
        source_oid=source_oid,
    )
    dlg.show()


def open_molecule_2d_viewer(
    mol: Chem.Mol,
    parent: QWidget | None = None,
    *,
    title: str = "View in 2D",
    source_oid: int | None = None,
) -> None:
    """Lay out *mol* in 2D and show it in 3Dmol with an orthographic (flat) projection."""
    if mol is None or not isinstance(mol, Chem.Mol):
        return
    m2d = prepare_mol_2d(mol)
    if m2d is None:
        QMessageBox.warning(
            parent,
            title,
            "Could not compute a 2D layout for this structure.",
        )
        return
    dlg = Molecule3DViewerDialog(m2d, parent, window_title=title, flat=True, source_oid=source_oid)
    dlg.show()
