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


"""Protein Viewer menu and overlay for 3D pharmacophore features."""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from PyQt5.QtWidgets import QFileDialog, QMessageBox

from ..protein.pharmacophore import (
    PHARMACOPHORE_FILE_FILTER,
    Pharmacophore,
    PharmacophoreFeature,
    features_from_mol,
    load_pharmacophore,
    mol_from_ligand_atoms,
    pharmacophore_from_dict,
    save_pharmacophore,
)
from .qt_widget_utils import qobject_is_deleted
from ..protein.structure_atoms import parse_structure_atoms

logger = logging.getLogger(__name__)


class ProteinViewerPharmacophoreMixin:
    """Menubar Pharmacophore actions, canvas overlay, and session payload."""

    def _ensure_pharmacophore(self) -> Pharmacophore:
        pharma = getattr(self, "_pharmacophore", None)
        if not isinstance(pharma, Pharmacophore):
            self._pharmacophore = Pharmacophore()
        return self._pharmacophore

    def _pharmacophore_overlay_payload(self) -> dict:
        if not getattr(self, "_pharmacophore_overlay_visible", False):
            return {"active": False, "features": []}
        return self._ensure_pharmacophore().overlay_payload()

    def _push_pharmacophore_overlay(
        self, *, sync_dialog: bool = True, mark_unsaved: bool = True
    ) -> None:
        self._pharmacophore_overlay_visible = True
        viewer = getattr(self, "viewer", None)
        setter = getattr(viewer, "set_pharmacophore", None) if viewer is not None else None
        if callable(setter):
            setter(self._pharmacophore_overlay_payload())
        if sync_dialog:
            self._sync_pharmacophore_dialog()
        if mark_unsaved:
            mark = getattr(self, "_mark_viewer_unsaved", None)
            if callable(mark):
                mark()

    def _hide_pharmacophore_canvas_overlay(self) -> None:
        self._pharmacophore_overlay_visible = False
        viewer = getattr(self, "viewer", None)
        setter = getattr(viewer, "set_pharmacophore", None) if viewer is not None else None
        if callable(setter):
            setter({"active": False, "features": []})

    def _pharmacophore_editor_is_open(self) -> bool:
        dlg = getattr(self, "_pharmacophore_dialog", None)
        return dlg is not None and not qobject_is_deleted(dlg) and bool(dlg.isVisible())

    def open_pharmacophore_dialog(self) -> None:
        """Open the modeless pharmacophore editor."""
        from .dialogs.protein_pharmacophore import ProteinPharmacophoreDialog

        dlg = getattr(self, "_pharmacophore_dialog", None)
        if dlg is not None and qobject_is_deleted(dlg):
            self._pharmacophore_dialog = None
            dlg = None
        if dlg is None:
            dlg = ProteinPharmacophoreDialog(self)
            dlg.add_at_coords.connect(self._on_pharmacophore_add_xyz)
            dlg.feature_changed.connect(self._on_pharmacophore_feature_changed)
            dlg.feature_removed.connect(self._on_pharmacophore_feature_removed)
            dlg.from_ligand_clicked.connect(self.add_pharmacophore_from_ligand)
            dlg.open_clicked.connect(self.open_pharmacophore_file)
            dlg.save_clicked.connect(self.save_pharmacophore_file)
            dlg.clear_clicked.connect(self.clear_pharmacophore)
            dlg.send_gnina_clicked.connect(self.send_pharmacophore_to_gnina)
            dlg.finished.connect(self._on_pharmacophore_editor_closed)
            dlg.destroyed.connect(self._on_pharmacophore_dialog_destroyed)
            self._pharmacophore_dialog = dlg
        self._sync_pharmacophore_dialog()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self._push_pharmacophore_overlay(mark_unsaved=False)

    def _on_pharmacophore_editor_closed(self, *_args) -> None:
        self._hide_pharmacophore_canvas_overlay()

    def _on_pharmacophore_dialog_destroyed(self) -> None:
        self._pharmacophore_dialog = None
        self._hide_pharmacophore_canvas_overlay()

    def _sync_pharmacophore_dialog(self) -> None:
        dlg = getattr(self, "_pharmacophore_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_features(list(self._ensure_pharmacophore().features))

    def _on_pharmacophore_atom_picked(self, data: dict) -> None:
        try:
            x = float(data.get("x"))
            y = float(data.get("y"))
            z = float(data.get("z"))
        except (TypeError, ValueError):
            return
        dlg = getattr(self, "_pharmacophore_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_last_xyz(
            x,
            y,
            z,
            str(data.get("elem") or data.get("element") or ""),
        )

    def _on_pharmacophore_add_xyz(
        self,
        feature_type: str,
        atom: str,
        x: float,
        y: float,
        z: float,
        radius: float,
    ) -> None:
        self._ensure_pharmacophore().add_feature(
            feature_type=feature_type,
            x=x,
            y=y,
            z=z,
            radius=radius,
            atom=atom,
        )
        self._push_pharmacophore_overlay()

    def _on_pharmacophore_feature_changed(self, row: int, feat: PharmacophoreFeature) -> None:
        pharma = self._ensure_pharmacophore()
        if row < 0 or row >= len(pharma.features):
            return
        pharma.features[row] = feat.normalized()
        self._push_pharmacophore_overlay(sync_dialog=False)

    def _on_pharmacophore_feature_removed(self, row: int) -> None:
        pharma = self._ensure_pharmacophore()
        if row < 0 or row >= len(pharma.features):
            return
        del pharma.features[row]
        self._push_pharmacophore_overlay()

    def clear_pharmacophore(self) -> None:
        self._pharmacophore = Pharmacophore()
        self._pharmacophore_path = None
        self._push_pharmacophore_overlay()

    def add_pharmacophore_from_ligand(self) -> None:
        mols = self._ligand_mols_for_pharmacophore()
        if not mols:
            QMessageBox.information(
                self,
                "Pharmacophore",
                "Select a ligand in the Manager, or load a structure that contains one.",
            )
            return
        added = 0
        pharma = self._ensure_pharmacophore()
        for mol in mols:
            for feat in features_from_mol(mol):
                pharma.add_feature(
                    feature_type=feat.type,
                    x=feat.x,
                    y=feat.y,
                    z=feat.z,
                    radius=feat.radius,
                    atom=feat.atom,
                )
                added += 1
        if not added:
            QMessageBox.information(
                self,
                "Pharmacophore",
                "RDKit BaseFeatures found no 3D sites on the ligand. "
                "The ligand needs a 3D conformer with recognizable donors, acceptors, "
                "or aromatic rings.",
            )
            return
        self._push_pharmacophore_overlay()

    def _ligand_mols_for_pharmacophore(self) -> list:
        rows = [
            row for row in getattr(self, "_rows", []) if getattr(row.spec, "kind", "") == "ligand"
        ]
        selected = [row for row in rows if getattr(row, "selected", False)]
        targets = selected or rows
        if not targets:
            return []
        mols = []
        slots = {slot.structure_id: slot for slot in getattr(self, "_slots", [])}
        for row in targets:
            slot = slots.get(row.spec.structure_id)
            if slot is None:
                continue
            try:
                atoms = parse_structure_atoms(slot.text, slot.fmt)
            except Exception:
                logger.debug("Pharmacophore ligand parse failed", exc_info=True)
                continue
            wanted = [
                atom
                for atom in atoms
                if str(atom.chain or "") == str(row.spec.chain or "")
                and str(atom.resn or "") == str(row.spec.resn or "")
                and str(atom.resi or "") == str(row.spec.resi or "")
                and str(atom.icode or "") == str(row.spec.icode or "")
            ]
            mol = mol_from_ligand_atoms(wanted)
            if mol is not None:
                mols.append(mol)
        return mols

    def open_pharmacophore_file(self) -> None:
        start = str(getattr(self, "_pharmacophore_path", None) or "")
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Open pharmacophore",
            start,
            PHARMACOPHORE_FILE_FILTER,
        )
        if not path:
            return
        try:
            self._pharmacophore = load_pharmacophore(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Pharmacophore", str(exc))
            return
        self._pharmacophore_path = path
        self._push_pharmacophore_overlay()

    def save_pharmacophore_file(self) -> str:
        start = str(getattr(self, "_pharmacophore_path", None) or "pharmacophore.json")
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Save pharmacophore",
            start,
            PHARMACOPHORE_FILE_FILTER,
        )
        if not path:
            return ""
        dest = Path(path)
        if dest.suffix.lower() not in {".json", ".mph4"}:
            dest = dest.with_suffix(".json")
        try:
            save_pharmacophore(dest, self._ensure_pharmacophore())
        except OSError as exc:
            QMessageBox.warning(self, "Pharmacophore", str(exc))
            return ""
        self._pharmacophore_path = str(dest)
        return str(dest)

    def pharmacophore_file_for_gnina(self) -> str:
        """Return a JSON path Gnina can load, writing a temp file if unsaved."""
        pharma = self._ensure_pharmacophore()
        if not pharma.enabled_features():
            return ""
        existing = str(getattr(self, "_pharmacophore_path", None) or "").strip()
        if existing and Path(existing).is_file():
            try:
                save_pharmacophore(existing, pharma)
            except OSError:
                logger.debug("Could not refresh pharmacophore file", exc_info=True)
            else:
                return existing
        handle = tempfile.NamedTemporaryFile(
            prefix="molmanager_pharma_",
            suffix=".json",
            delete=False,
        )
        handle.close()
        save_pharmacophore(handle.name, pharma)
        self._pharmacophore_temp_path = handle.name
        return handle.name

    def apply_pharmacophore_state(self, raw: object, *, path: str = "") -> None:
        if raw is None:
            return
        try:
            self._pharmacophore = pharmacophore_from_dict(raw)
        except ValueError:
            logger.debug("Session pharmacophore ignored", exc_info=True)
            return
        if path:
            self._pharmacophore_path = path
        if self._pharmacophore_editor_is_open():
            self._push_pharmacophore_overlay()
        else:
            self._hide_pharmacophore_canvas_overlay()

    def send_pharmacophore_to_gnina(self) -> None:
        path = self.pharmacophore_file_for_gnina()
        if not path:
            QMessageBox.information(
                self,
                "Pharmacophore",
                "Add at least one enabled feature before sending to Gnina.",
            )
            return
        parent = self.parent()
        opener = getattr(parent, "open_gnina_dock", None)
        if not callable(opener):
            QMessageBox.information(
                self,
                "Pharmacophore",
                f"Saved to {path}. Open Protein → Dock Ligand → Gnina and browse to that file.",
            )
            return
        dlg = opener()
        setter = getattr(dlg, "set_pharmacophore_path", None)
        if callable(setter):
            setter(path)
        elif dlg is not None:
            edit = getattr(dlg, "edit_pharmacophore", None)
            if edit is not None:
                edit.setText(path)

    def screen_pharmacophore_table(self) -> None:
        path = self.pharmacophore_file_for_gnina()
        if not path:
            QMessageBox.information(
                self,
                "Pharmacophore",
                "Add at least one enabled feature before screening the table.",
            )
            return
        parent = self.parent()
        opener = getattr(parent, "open_pharmacophore_screen", None)
        if not callable(opener):
            QMessageBox.information(
                self,
                "Pharmacophore",
                f"Saved to {path}. Open Chemistry → Conformations → Screen Pharmacophore… "
                "and browse to that file.",
            )
            return
        opener(path)
