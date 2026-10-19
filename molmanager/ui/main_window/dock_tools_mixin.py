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

"""Gnina dock, PDBQT/PDB prepare, and the pose browser."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QMessageBox

from rdkit import Chem

from ...conformers.conformer_column_codec import pack_mols_as_confs_cell
from ...docking.pose_file_io import (
    dock_poses_pack_meta,
    group_dock_poses,
    is_poses_header,
    pose_table_props,
    stamp_pose_parent_oids,
)
from ...services.column_labels import COLUMN_PARENT_OID
from ...chem.molecule_conversion import mol_to_canonical_smiles
from ..singleton_modeless_dialog import reuse_or_show_modeless_singleton


def _copy_dock_pose_mols(mols: list) -> list:
    """Independent RDKit copies so the pose browser can reopen after it is closed."""
    out: list = []
    for mol in mols or []:
        if mol is None:
            continue
        try:
            out.append(Chem.Mol(mol))
        except Exception:
            continue
    return out


class DockToolsMixin:
    def open_dock_results_window(
        self,
        mols: list,
        *,
        title: str = "Pose browser",
        receptor_path: str | None = None,
        crystal_path: str | None = None,
    ):
        """Open the pose browser in the Protein Viewer Manager, or as a floating window."""
        from ..pose_browser import PoseBrowserDialog, PoseBrowserWidget

        usable = [m for m in (mols or []) if m is not None]
        if not usable:
            return None
        copies = _copy_dock_pose_mols(usable)
        rec_path = (receptor_path or "").strip() or None
        xtal_path = (crystal_path or "").strip() or None
        self._store_last_dock_results(
            copies,
            title=title,
            receptor_path=rec_path,
            crystal_path=xtal_path,
        )
        protein = self._live_protein_viewer()
        if protein is not None:
            self._prepare_protein_viewer_for_poses(protein, rec_path, crystal_path=xtal_path)

        def _load(widget) -> None:
            setter = getattr(widget, "set_poses", None)
            if callable(setter):
                setter(copies, title=title, receptor_path=rec_path, crystal_path=xtal_path)

        def _dock_in_viewer(widget) -> bool:
            viewer = self._live_protein_viewer()
            dock = getattr(viewer, "dock_side_widget", None) if viewer is not None else None
            return callable(dock) and bool(dock(widget))

        existing = self._live_pose_browser()
        if existing is not None:
            _load(existing)
            viewer = self._live_protein_viewer()
            already = getattr(viewer, "is_side_docked", None) if viewer is not None else None
            if viewer is not None and not (callable(already) and already(existing)):
                host = existing.window()
                from ..pose_browser import PoseBrowserDialog

                if _dock_in_viewer(existing):
                    if isinstance(host, PoseBrowserDialog):
                        from ..dockable_plot_chrome import discard_host_dialog_after_dock

                        discard_host_dialog_after_dock(host, self, "_pose_browser_dialog")
                    return existing
            self._raise_pose_browser(existing)
            return self._pose_browser_open_result(existing)

        widget = PoseBrowserWidget(self)
        _load(widget)
        if _dock_in_viewer(widget):
            return widget

        def _factory():
            dlg = PoseBrowserDialog(self, panel=widget)
            dlg.setWindowTitle("Pose Browser")
            return dlg

        def _on_reused(dlg):
            _load(getattr(dlg, "_panel", None))
            dlg.setWindowTitle("Pose Browser")

        return reuse_or_show_modeless_singleton(
            self,
            "_pose_browser_dialog",
            _factory,
            self._on_pose_browser_dialog_destroyed,
            on_reused_visible=_on_reused,
        )

    def _pose_browser_open_result(self, widget):
        """Return the Manager-docked panel, or its floating dialog host."""
        from ..pose_browser import PoseBrowserDialog

        protein = self._live_protein_viewer()
        check_side = getattr(protein, "is_side_docked", None) if protein is not None else None
        if callable(check_side) and widget is not None and bool(check_side(widget)):
            return widget
        check = getattr(self, "is_plot_docked", None)
        if callable(check) and widget is not None and bool(check(widget)):
            return widget
        host = widget.window() if widget is not None else None
        if isinstance(host, PoseBrowserDialog):
            return host
        return widget

    def _on_pose_browser_dialog_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        try:
            sender = self.sender()
        except RuntimeError:
            return
        current = getattr(self, "_pose_browser_dialog", None)
        if sender is not None and current is not None and current is not sender:
            return
        self._pose_browser_dialog = None
        self._clear_protein_viewer_dock_pose()

    def _on_pose_browser_widget_destroyed(self, *_args) -> None:
        from ..qt_widget_utils import qobject_is_deleted

        if qobject_is_deleted(self):
            return
        self._clear_protein_viewer_dock_pose()

    def _clear_protein_viewer_dock_pose(self) -> None:
        protein = self._live_protein_viewer()
        if protein is None:
            return
        clearer = getattr(protein, "clear_dock_pose", None)
        if callable(clearer):
            clearer()

    def _clear_protein_viewer_dock_pose_if_idle(self) -> None:
        if self._live_pose_browser() is not None:
            return
        self._clear_protein_viewer_dock_pose()

    def _pose_browser_window_is_open(self, widget) -> bool:
        """True when the pose browser is docked in a visible viewer or in a visible window."""
        from ..qt_widget_utils import qobject_is_deleted

        if widget is None or qobject_is_deleted(widget):
            return False
        protein = self._live_protein_viewer()
        if protein is not None:
            try:
                viewer_open = bool(protein.isVisible())
            except RuntimeError:
                viewer_open = False
            check = getattr(protein, "is_side_docked", None)
            if viewer_open and callable(check) and bool(check(widget)):
                return True
        check = getattr(self, "is_plot_docked", None)
        if callable(check) and bool(check(widget)):
            return True
        try:
            host = widget.window()
        except RuntimeError:
            return False
        if host is None or qobject_is_deleted(host) or host is protein:
            return False
        try:
            return bool(host.isVisible())
        except RuntimeError:
            return False

    def _live_pose_browser(self):
        """Return the Manager-docked or visible floating pose-browser panel."""
        from ..pose_browser import PoseBrowserDialog, PoseBrowserWidget
        from ..qt_widget_utils import qobject_is_deleted

        protein = self._live_protein_viewer()
        lister = getattr(protein, "side_docked_widgets", None) if protein is not None else None
        if callable(lister):
            for w in lister():
                if isinstance(w, PoseBrowserWidget) and self._pose_browser_window_is_open(w):
                    return w
        lister = getattr(self, "iter_docked_plot_widgets", None)
        if callable(lister):
            for w in lister():
                if isinstance(w, PoseBrowserWidget) and self._pose_browser_window_is_open(w):
                    return w
        dlg = getattr(self, "_pose_browser_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return None
        panel = getattr(dlg, "_panel", None)
        if not isinstance(panel, PoseBrowserWidget):
            if isinstance(dlg, PoseBrowserDialog):
                panel = getattr(dlg, "_panel", None)
            else:
                panel = None
        if isinstance(panel, PoseBrowserWidget) and self._pose_browser_window_is_open(panel):
            return panel
        return None

    def _raise_pose_browser(self, widget) -> None:
        """Focus a Manager-docked pose browser or raise its floating window."""
        protein = self._live_protein_viewer()
        check_side = getattr(protein, "is_side_docked", None) if protein is not None else None
        if callable(check_side) and widget is not None and bool(check_side(widget)):
            try:
                protein.show()
                protein.raise_()
                protein.activateWindow()
                show = getattr(protein, "show_side_widget", None)
                if callable(show):
                    show(widget)
                widget.show()
                widget.raise_()
            except RuntimeError:
                pass
            return
        check = getattr(self, "is_plot_docked", None)
        docked = callable(check) and widget is not None and bool(check(widget))
        if docked:
            pane_for = getattr(self, "pane_for_plot_widget", None)
            pane = pane_for(widget) if callable(pane_for) else None
            mgr = getattr(self, "_workspace_layout", None)
            if pane is not None:
                if mgr is not None:
                    mgr.set_preferred_pane(pane)
                show_page = getattr(pane, "add_plot_widget", None)
                if callable(show_page):
                    show_page(widget)
            show = getattr(self, "show_docked_plot_panel", None)
            if callable(show):
                show()
            widget.raise_()
            status = getattr(self, "status_label", None)
            if status is not None:
                status.setText("Pose Browser: focused in workspace pane.")
            return
        host = widget.window() if widget is not None else None
        if host is None:
            return
        try:
            host.show()
            host.raise_()
            host.activateWindow()
        except RuntimeError:
            pass

    def _live_dock_result_windows(self) -> list:
        """Floating pose-browser hosts still live (compat for Protein Viewer sync)."""
        browser = self._live_pose_browser()
        if browser is None:
            return []
        host = browser.window()
        return [host if host is not None else browser]

    def open_dock_results_viewer(self):
        """Raise the pose browser, or recreate it from the last docking run."""
        existing = self._live_pose_browser()
        if existing is not None:
            self._raise_pose_browser(existing)
            return self._pose_browser_open_result(existing)
        snap = getattr(self, "_last_dock_results", None) or {}
        mols = list(snap.get("mols") or [])
        if not mols:
            mols = self._mols_from_table_pose_columns()
            if mols:
                self._store_last_dock_results(
                    mols,
                    title=str(snap.get("title") or "Pose browser"),
                    receptor_path=snap.get("receptor_path"),
                    crystal_path=snap.get("crystal_path"),
                )
                snap = getattr(self, "_last_dock_results", None) or {}
        if not mols:
            QMessageBox.information(
                self,
                "Pose Browser",
                "No docking results to show. Run Gnina first.",
            )
            return None
        return self.open_dock_results_window(
            _copy_dock_pose_mols(mols),
            title=str(snap.get("title") or "Pose browser"),
            receptor_path=snap.get("receptor_path"),
            crystal_path=snap.get("crystal_path"),
        )

    def _store_last_dock_results(
        self,
        mols: list,
        *,
        title: str = "Pose browser",
        receptor_path: str | None = None,
        crystal_path: str | None = None,
    ) -> None:
        """Keep the last docking run so Pose Browser can reopen, including after Open Session."""
        copies = _copy_dock_pose_mols(mols)
        rec_path = (receptor_path or "").strip() or None
        xtal_path = (crystal_path or "").strip() or None
        self._last_dock_results = (
            {
                "mols": copies,
                "title": str(title or "Pose browser"),
                "receptor_path": rec_path,
                "crystal_path": xtal_path,
            }
            if copies
            else None
        )
        self._set_pose_browser_action_enabled(bool(copies))

    def _set_pose_browser_action_enabled(self, enabled: bool) -> None:
        act = getattr(self, "_act_dock_viewer", None)
        if act is None:
            return
        try:
            act.setEnabled(bool(enabled))
        except RuntimeError:
            pass

    def _mols_from_table_pose_columns(self) -> list:
        """Rebuild pose molecules from packed ``poses`` table columns (session fallback)."""
        from ...conformers.conformer_output import iter_single_conformer_mols
        from .conformer_writeback import mol_for_ensemble_column

        model = getattr(self, "_table_model", None)
        if model is None:
            return []
        headers = [h for h in list(getattr(self, "headers", []) or []) if is_poses_header(h)]
        if not headers:
            return []
        try:
            n = int(model.rowCount())
        except Exception:
            return []
        out: list = []
        for row in range(n):
            try:
                oid = int(model.row_oid(row))
            except Exception:
                continue
            for header in headers:
                packed = mol_for_ensemble_column(self, oid, header, min_conformers=1)
                if packed is None:
                    continue
                for mol in iter_single_conformer_mols(packed):
                    try:
                        mol.SetProp(COLUMN_PARENT_OID, str(oid))
                    except Exception:
                        pass
                    out.append(mol)
        return out

    def _live_protein_viewer(self):
        """Return the open Protein Viewer on this window."""
        from ..qt_widget_utils import qobject_is_deleted

        dlg = getattr(self, "_protein_viewer_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return None
        return dlg

    def _prepare_protein_viewer_for_poses(
        self,
        dlg,
        receptor_path: str | None,
        crystal_path: str | None = None,
    ) -> None:
        """Load receptor (and crystal ligand) if the Protein Viewer is empty, then show it."""
        if dlg is None:
            return
        if not getattr(dlg, "_slots", None):
            path = (receptor_path or "").strip()
            rec = Path(path) if path else None
            if rec is not None and rec.is_file():
                adder = getattr(dlg, "add_structure_path", None)
                if callable(adder):
                    adder(rec, refit=True)
        has_ligand = any(
            getattr(getattr(row, "spec", None), "kind", "") == "ligand"
            for row in getattr(dlg, "_rows", [])
        )
        crystal = (crystal_path or "").strip()
        if crystal and not has_ligand:
            lig_add = getattr(dlg, "add_ligand_path", None)
            if callable(lig_add):
                lig_add(crystal, name="Crystal ligand", color_scheme="default", refit=False)
        try:
            dlg.show()
            dlg.raise_()
        except RuntimeError:
            pass

    def _sync_protein_viewer_dock_pose(self, mol, *, caption: str | None = None) -> None:
        protein = self._live_protein_viewer()
        if protein is None:
            return
        setter = getattr(protein, "set_dock_pose", None)
        if not callable(setter):
            return
        zoom = not bool(getattr(self, "_dock_pose_zoomed", False))
        text = caption or "Dock pose"
        if setter(mol, zoom=zoom, caption=text):
            self._dock_pose_zoomed = True

    def write_dock_poses_to_table(self, mols: list) -> str | None:
        """Pack docked poses into a ``poses`` column, grouped by parent table row."""
        usable = [m for m in (mols or []) if m is not None]
        if not usable:
            return None
        model = getattr(self, "_table_model", None)
        if model is None:
            return None
        known: set[int] = set()
        try:
            n = int(model.rowCount())
        except Exception:
            n = 0
        for row in range(n):
            try:
                known.add(int(model.row_oid(row)))
            except Exception:
                continue
        stamp_pose_parent_oids(usable, known)
        by_oid, orphan_groups = group_dock_poses(usable, known)
        if not by_oid and not orphan_groups:
            return None
        col = self._next_packed_ensemble_column("poses", list(by_oid))
        pairs: list[tuple[int, str]] = []
        for oid, group in by_oid.items():
            pairs.append((int(oid), pack_mols_as_confs_cell(dock_poses_pack_meta(group), group)))
        for group in orphan_groups:
            oid = self._append_orphan_dock_pose_row(group)
            if oid is None:
                continue
            for mol in group:
                try:
                    mol.SetProp(COLUMN_PARENT_OID, str(int(oid)))
                except Exception:
                    continue
            pairs.append((int(oid), pack_mols_as_confs_cell(dock_poses_pack_meta(group), group)))
        if pairs:
            self._write_packed_ensemble_cells(col, pairs)
        return col

    def _append_orphan_dock_pose_row(self, mols: list) -> int | None:
        """Add one table row for a file-docked ligand so packed poses have a place to live."""
        first = next((m for m in (mols or []) if m is not None), None)
        if first is None:
            return None
        ensure = getattr(self, "_ensure_columns", None)
        if callable(ensure):
            ensure(["SMILES"])
        try:
            oid = int(self.next_oid)
            self.next_oid = oid + 1
        except Exception:
            return None
        try:
            stored = Chem.Mol(first)
        except Exception:
            stored = first
        from ..mol_viewer_3d import prepare_mol_2d

        depict = prepare_mol_2d(stored)
        self.mols[oid] = depict if depict is not None else stored
        props = pose_table_props(first)
        smi = (props.get("SMILES") or "").strip() or mol_to_canonical_smiles(stored)
        cells: dict[str, str] = {}
        for header in list(self.headers[2:]):
            if header == "SMILES":
                cells[header] = smi
            elif header == "Name":
                cells[header] = (props.get("Name") or "").strip()
            elif header == COLUMN_PARENT_OID:
                cells[header] = ""
            else:
                cells[header] = ""
        self._table_model.append_rows_batch([(oid, cells)])
        render = getattr(self, "start_render_worker", None)
        live = self.mols.get(oid)
        if callable(render) and live is not None:
            render(oid, live, skip_mol_props=True)
        return oid

    def _new_gnina_dock_dialog(self):
        """Build a Gnina dialog and refill it from the saved session setup."""
        from ..dialogs.gnina_dock import GninaDockDialog

        dlg = GninaDockDialog(self)
        state = getattr(self, "_gnina_dock_session", None)
        if isinstance(state, dict):
            dlg.apply_gnina_session(state)
        return dlg

    def remember_gnina_dock_session(self, state: dict | None) -> None:
        """Keep the Gnina setup for the next session save and the next dialog open."""
        from ..dialogs.gnina_dock import gnina_session_worth_saving

        cleaned = state if gnina_session_worth_saving(state) else None
        if cleaned == getattr(self, "_gnina_dock_session", None):
            return
        self._gnina_dock_session = cleaned
        mark = getattr(self, "_mark_session_dirty", None)
        if callable(mark):
            mark()

    def open_gnina_dock(self):
        """Open the Gnina docking dialog."""
        dlg = reuse_or_show_modeless_singleton(
            self,
            "_smina_dock_dialog",
            self._new_gnina_dock_dialog,
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)
        protein = self._live_protein_viewer()
        if protein is not None:
            current = (
                getattr(dlg, "edit_pharmacophore", None) and dlg.edit_pharmacophore.text()
            ) or ""
            if not str(current).strip():
                getter = getattr(protein, "pharmacophore_file_for_gnina", None)
                path = getter() if callable(getter) else ""
                setter = getattr(dlg, "set_pharmacophore_path", None)
                if path and callable(setter):
                    setter(path)
        return dlg

    open_smina_dock = open_gnina_dock

    def open_dock_prepare(self):
        from ..dialogs.pdbqt_generator import PdbqtGeneratorDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_pdbqt_generator_dialog",
            lambda: PdbqtGeneratorDialog(self),
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)

    def open_dock_prepare_pdb(self):
        from ..dialogs.pdb_fixer import PdbFixerDialog

        dlg = reuse_or_show_modeless_singleton(
            self,
            "_pdb_fixer_dialog",
            lambda: PdbFixerDialog(self),
        )
        dlg.setAttribute(Qt.WA_DeleteOnClose, True)
        self._prepare_tool_dialog(dlg)
