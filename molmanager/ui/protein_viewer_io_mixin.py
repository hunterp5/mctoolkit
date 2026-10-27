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

"""Open/save/session state for the Protein Viewer window."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from PyQt5.QtCore import QByteArray
from PyQt5.QtWidgets import QFileDialog, QInputDialog, QMessageBox

from ..protein.structure_components import (
    LoadedStructure,
    component_id_for_atom,
    delete_cif_residues,
    delete_pdb_residues,
    load_structure_file,
    parse_polymer_sequences,
    parse_structure_atoms,
    parse_structure_components,
    scope_structure_component,
    _residue_key3,
)
from .protein_viewer_models import (
    STRUCTURE_FILE_FILTER,
    STRUCTURE_SAVE_FILTER,
    NamedManagerGroup,
    _ComponentView,
    _LoadedSlot,
    _component_state_key,
    unscoped_component_id,
)
from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)


class ProteinViewerIoMixin:
    @property
    def _rows(self) -> list[_ComponentView]:
        return [row for slot in self._slots for row in slot.rows]

    @property
    def _loaded(self) -> LoadedStructure | None:
        slot = self._active_slot()
        if slot is None:
            return None
        return LoadedStructure(
            path=slot.path,
            text=slot.text,
            sniffed_format=slot.fmt,
            viewer_format=slot.fmt,
            components=tuple(row.spec for row in slot.rows),
        )

    @property
    def _viewer_text(self) -> str:
        slot = self._active_slot()
        return slot.text if slot is not None else ""

    @property
    def _viewer_fmt(self) -> str:
        slot = self._active_slot()
        return slot.fmt if slot is not None else "pdb"

    def _slot_by_id(self, structure_id: str | None) -> _LoadedSlot | None:
        sid = (structure_id or "").strip()
        if sid:
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
            return None
        selected = [r.spec.structure_id for r in self._rows if r.selected]
        if selected:
            sid = selected[-1]
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        if self._slots:
            return self._slots[-1]
        return None

    def _active_slot(self) -> _LoadedSlot | None:
        return self._slot_by_id(None)

    def _manager_groups(self) -> list[tuple[str, str]]:
        return [(slot.structure_id, slot.name) for slot in self._slots]

    def _refresh_manager(self) -> None:
        names = [slot.name for slot in self._slots]
        filename = ", ".join(names) if names else ""
        self.manager.set_structure(
            self._rows,
            filename=filename,
            groups=self._manager_groups(),
            named_groups=list(getattr(self, "_named_groups", []) or []),
        )
        if len(names) == 1:
            self.setWindowTitle(f"Protein Viewer — {names[0]}")
        elif names:
            self.setWindowTitle(f"Protein Viewer — {len(names)} structures")
        else:
            self.setWindowTitle("Protein Viewer")

    def _ensure_named_group(self, name: str) -> NamedManagerGroup:
        groups = getattr(self, "_named_groups", None)
        if groups is None:
            self._named_groups = []
            groups = self._named_groups
        key = name.casefold()
        for group in groups:
            if group.name.casefold() == key:
                return group
        seq = int(getattr(self, "_group_seq", 0) or 0) + 1
        self._group_seq = seq
        group = NamedManagerGroup(group_id=f"grp{seq}", name=name, component_ids=[])
        groups.append(group)
        return group

    def _on_add_to_group(self, name: str) -> None:
        label = (name or "").strip()
        if not label:
            return
        ids = self._selected_component_ids()
        if not ids:
            return
        group = self._ensure_named_group(label)
        seen = set(group.component_ids)
        for cid in ids:
            if cid not in seen:
                group.component_ids.append(cid)
                seen.add(cid)
        self._refresh_manager()
        self._mark_viewer_unsaved()

    def _on_remove_from_group(self, group_id: str) -> None:
        ids = set(self._selected_component_ids())
        if not ids:
            return
        groups = getattr(self, "_named_groups", None) or []
        changed = False
        for group in groups:
            if group_id and group.group_id != group_id:
                continue
            kept = [cid for cid in group.component_ids if cid not in ids]
            if kept != group.component_ids:
                group.component_ids = kept
                changed = True
        if not changed:
            return
        self._refresh_manager()
        self._mark_viewer_unsaved()

    def _on_rename_group(self, group_id: str) -> None:
        groups = getattr(self, "_named_groups", None) or []
        group = next((item for item in groups if item.group_id == group_id), None)
        if group is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Group", "Group name:", text=group.name)
        name = (name or "").strip()
        if not ok or not name or name == group.name:
            return
        group.name = name
        self._refresh_manager()
        self._mark_viewer_unsaved()

    def _on_delete_group(self, group_id: str) -> None:
        groups = getattr(self, "_named_groups", None) or []
        kept = [group for group in groups if group.group_id != group_id]
        if len(kept) == len(groups):
            return
        self._named_groups = kept
        self._refresh_manager()
        self._mark_viewer_unsaved()

    def _named_groups_session_payload(self) -> list[dict]:
        by_id = {row.spec.component_id: row for row in self._rows}
        slots_by_sid = {slot.structure_id: slot for slot in self._slots}
        payload: list[dict] = []
        for group in getattr(self, "_named_groups", None) or []:
            members: list[dict] = []
            for cid in group.component_ids:
                row = by_id.get(cid)
                if row is None:
                    continue
                slot = slots_by_sid.get(row.spec.structure_id)
                members.append(
                    {
                        "structure": slot.name if slot is not None else "",
                        "componentId": unscoped_component_id(cid),
                    }
                )
            payload.append(
                {
                    "id": group.group_id,
                    "name": group.name,
                    "members": members,
                }
            )
        return payload

    def _restore_named_groups(self, raw) -> None:
        self._named_groups = []
        self._group_seq = 0
        if not isinstance(raw, list):
            return
        max_seq = 0
        for spec in raw:
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or "").strip()
            if not name:
                continue
            gid = str(spec.get("id") or "").strip()
            if not gid:
                gid = f"grp{len(self._named_groups) + 1}"
            if gid.startswith("grp"):
                try:
                    max_seq = max(max_seq, int(gid[3:]))
                except ValueError:
                    pass
            ids: list[str] = []
            seen: set[str] = set()
            members = spec.get("members")
            if not isinstance(members, list):
                members = [
                    {"structure": "", "componentId": str(cid)}
                    for cid in spec.get("componentIds") or []
                ]
            for member in members:
                if not isinstance(member, dict):
                    continue
                cid = self._live_component_id(
                    str(member.get("structure") or ""),
                    str(member.get("componentId") or ""),
                )
                if cid and cid not in seen:
                    ids.append(cid)
                    seen.add(cid)
            self._named_groups.append(NamedManagerGroup(group_id=gid, name=name, component_ids=ids))
        self._group_seq = max_seq

    def _live_component_id(self, structure_name: str, unscoped: str) -> str:
        want = (unscoped or "").strip()
        if not want:
            return ""
        slots = list(self._slots)
        if structure_name:
            named = [slot for slot in slots if slot.name == structure_name]
            if named:
                slots = named
        for slot in slots:
            for row in slot.rows:
                cid = row.spec.component_id
                if cid == want or unscoped_component_id(cid) == want:
                    return cid
        return ""

    def _unique_slot_name(self, name: str) -> str:
        used = {slot.name for slot in self._slots}
        if name not in used:
            return name
        stem = Path(name).stem
        suffix = Path(name).suffix
        n = 2
        while True:
            candidate = f"{stem} ({n}){suffix}"
            if candidate not in used:
                return candidate
            n += 1

    def prepare_source(self, structure_id: str | None = None) -> tuple[str, str, str, Path | None]:
        """Return (display name, file text, viewer format, path) for Prepare."""
        slot = self._slot_by_id(structure_id)
        if slot is None:
            return ("", "", "pdb", None)
        return (slot.name, slot.text, slot.fmt, slot.path)

    def prepare_source_id(self) -> str:
        """Structure id of the file Prepare will read."""
        slot = self._active_slot()
        return slot.structure_id if slot is not None else ""

    def prepare_slot_payload(self, structure_id: str) -> tuple[str, str]:
        """Return ``(text, fmt)`` for a loaded structure id."""
        sid = (structure_id or "").strip()
        for slot in self._slots:
            if slot.structure_id == sid:
                return slot.text, slot.fmt
        return "", "pdb"

    def prepare_chain_ids(self, structure_id: str | None = None) -> tuple[str, ...]:
        """Unique chain IDs on a loaded structure (for PDBFixer Keep chains)."""
        slot = self._slot_by_id(structure_id)
        if slot is None:
            return ()
        seen: list[str] = []
        for row in slot.rows:
            chain = (row.spec.chain or "").strip()
            if chain and chain not in seen:
                seen.append(chain)
        return tuple(seen)

    def prepare_water_keys(
        self, structure_id: str | None = None
    ) -> tuple[tuple[str, str, str], ...]:
        """Residue keys for Manager-selected water groups on a loaded structure."""
        slot = self._slot_by_id(structure_id)
        if slot is None:
            return ()
        selected_chains = {
            row.spec.chain
            for row in slot.rows
            if row.selected and row.spec.kind == "water" and row.spec.chain
        }
        if not selected_chains:
            return ()
        keys: list[tuple[str, str, str]] = []
        seen: set[tuple[str, str, str]] = set()
        for poly in parse_polymer_sequences(slot.text, slot.fmt):
            if poly.chain not in selected_chains:
                continue
            for res in poly.residues:
                if res.kind != "water":
                    continue
                key = (res.chain, res.resi, res.icode)
                if key in seen:
                    continue
                seen.add(key)
                keys.append(key)
        return tuple(keys)

    def prepare_ligand_options(
        self, structure_id: str | None = None
    ) -> list[tuple[str, tuple[str, str, str], bool, str]]:
        """Ligands on loaded structures: ``(label, residue key, selected, structure_id)``."""
        sid = (structure_id or "").strip()
        slots = [slot for slot in self._slots if not sid or slot.structure_id == sid]
        if not slots:
            return []
        multi = len(slots) > 1
        active = self._active_slot()
        rows_by_slot: list[tuple[_LoadedSlot, list[_ComponentView]]] = []
        for slot in slots:
            lig_rows = [row for row in slot.rows if row.spec.kind == "ligand"]
            if lig_rows:
                rows_by_slot.append((slot, lig_rows))
        if not rows_by_slot:
            return []
        any_selected = any(row.selected for _slot, lig_rows in rows_by_slot for row in lig_rows)
        out: list[tuple[str, tuple[str, str, str], bool, str]] = []
        for slot, lig_rows in rows_by_slot:
            for row in lig_rows:
                spec = row.spec
                key = (spec.chain or "", str(spec.resi or "").strip() or "0", spec.icode or "")
                label = spec.label or f"{spec.resn} {spec.chain}{spec.resi}"
                if multi:
                    label = f"{slot.name}: {label}"
                selected = bool(row.selected) if any_selected else False
                out.append((label, key, selected, slot.structure_id))
        if not any_selected and out:
            ranked: list[tuple[int, bool, tuple[str, str, str], str]] = []
            for slot, lig_rows in rows_by_slot:
                for row in lig_rows:
                    spec = row.spec
                    key = (
                        spec.chain or "",
                        str(spec.resi or "").strip() or "0",
                        spec.icode or "",
                    )
                    ranked.append(
                        (
                            int(spec.n_atoms or 0),
                            slot is active,
                            key,
                            slot.structure_id,
                        )
                    )
            ranked.sort(key=lambda item: (item[1], item[0]), reverse=True)
            best_key, best_sid = ranked[0][2], ranked[0][3]
            out = [
                (label, key, key == best_key and sid == best_sid, sid)
                for label, key, _selected, sid in out
            ]
        return out

    def open_structure_dialog(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Open structure", "", STRUCTURE_FILE_FILTER)
        for i, path in enumerate(paths):
            self.add_structure_path(path, refit=(i == len(paths) - 1))

    def save_structure_dialog(self) -> None:
        slot = self._active_slot()
        if slot is None:
            QMessageBox.information(self, "Save Structure", "Open a structure first.")
            return
        fmt = (slot.fmt or "pdb").lower()
        if fmt == "cif":
            suffix = ".cif"
            selected = "mmCIF (*.cif *.mmcif *.mcif)"
        else:
            suffix = ".pdb"
            selected = "PDB (*.pdb)"
        default_name = (
            Path(slot.name).with_suffix(suffix) if slot.name else Path(f"structure{suffix}")
        )
        start = str(slot.path) if slot.path and slot.path.parent.is_dir() else str(default_name)
        path, _ = QFileDialog.getSaveFileName(
            self, "Save structure", start, STRUCTURE_SAVE_FILTER, selected
        )
        if not path:
            return
        rec = Path(path)
        if not rec.suffix:
            rec = rec.with_suffix(suffix)
        try:
            rec.write_bytes(slot.text.encode("utf-8"))
        except OSError as exc:
            QMessageBox.warning(self, "Save Structure", str(exc))

    def load_structure_path(self, path: str | Path) -> None:
        self.add_structure_path(path, refit=True)

    def add_structure_path(self, path: str | Path, *, refit: bool = True) -> None:
        begin = getattr(self, "begin_canvas_load", None)
        end = getattr(self, "end_canvas_load", None)
        if callable(begin):
            from .strings import LOADING_DETAIL_PROTEIN_STRUCTURE

            begin(LOADING_DETAIL_PROTEIN_STRUCTURE)
        try:
            self._add_structure_path_now(path, refit=refit)
        finally:
            if callable(end):
                end()

    def _add_structure_path_now(self, path: str | Path, *, refit: bool = True) -> None:
        try:
            loaded = load_structure_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Protein Viewer", str(exc))
            return
        text = loaded.text
        fmt = loaded.viewer_format
        if loaded.sniffed_format == "pdbqt":
            from .dock_complex_viewer import pdbqt_to_pdb_text

            text = pdbqt_to_pdb_text(loaded.text) or loaded.text
            fmt = "pdb"
        if not loaded.components:
            QMessageBox.information(
                self,
                "Protein Viewer",
                "No atoms were found in that file.",
            )
            return
        self._append_loaded_slot(
            text=text,
            fmt=fmt,
            components=loaded.components,
            name=loaded.path.name,
            path=loaded.path,
            refit=refit,
            auto_interactions=True,
        )

    def _append_loaded_slot(
        self,
        *,
        text: str,
        fmt: str,
        components,
        name: str,
        path: Path | None,
        refit: bool,
        row_states: list[dict] | None = None,
        push: bool = True,
        auto_interactions: bool = False,
        ligand_color_scheme: str | None = None,
    ) -> None:
        sid = f"s{self._slot_seq}"
        self._slot_seq += 1
        self._clear_manager_delete_history()
        model = len(self._slots)
        protein_style = self._checked_style(self._protein_style_actions, "cartoon")
        ligand_style = self._checked_style(self._ligand_style_actions, "ballstick")
        protein_color = self._checked_style(self._protein_color_actions, "default")
        ligand_color = self._checked_style(self._ligand_color_actions, "default")
        state_by_key = {
            _component_state_key(item): item
            for item in (row_states or [])
            if isinstance(item, dict)
        }
        rows = []
        for comp in components:
            spec = scope_structure_component(comp, structure_id=sid, model=model)
            saved = state_by_key.get(_component_state_key(spec))
            style = (
                protein_style
                if spec.kind == "polymer"
                else ligand_style
                if spec.kind == "ligand"
                else spec.default_style
            )
            if spec.kind == "polymer":
                color_scheme = protein_color
            elif spec.kind == "ligand":
                color_scheme = ligand_color_scheme or ligand_color
            else:
                color_scheme = "default"
            visible = spec.default_visible
            selected = False
            if saved:
                style = str(saved.get("style") or style)
                color_scheme = str(saved.get("color_scheme") or color_scheme)
                visible = bool(saved.get("visible", visible))
                selected = bool(saved.get("selected", False))
            rows.append(
                _ComponentView(
                    spec=spec,
                    visible=visible,
                    selected=selected,
                    style=style,
                    color_scheme=color_scheme,
                    loaded_style=style,
                    loaded_color_scheme=color_scheme,
                )
            )
        self._slots.append(
            _LoadedSlot(
                structure_id=sid,
                name=self._unique_slot_name(name),
                path=path or Path(name),
                text=text,
                fmt=fmt,
                rows=rows,
            )
        )
        self._residue_highlight = []
        self._set_atom_status("")
        if auto_interactions:
            self._enable_protein_ligand_interactions_for_complex()
        if push:
            added_index = len(self._slots) - 1
            self._refresh_manager()
            self._refresh_sequence_chains()
            self._push_structure(
                refit=refit,
                append_from=added_index if added_index > 0 else None,
            )
            self._refresh_pocket_overlays(zoom=False)
            self._mark_viewer_unsaved()

    def add_ligand_mol(
        self,
        mol,
        *,
        name: str = "Dock pose",
        color_scheme: str = "magenta",
        refit: bool = False,
        push: bool = True,
    ) -> bool:
        """Append a docked pose as its own Manager structure (does not replace the complex)."""
        from .dock_complex_viewer import ligand_mol_to_pdb_text, pose_manager_slot_name

        text = ligand_mol_to_pdb_text(mol)
        if not text.strip():
            return False
        components = parse_structure_components(text, "pdb")
        if not components:
            return False
        raw_name = (name or "").strip() or pose_manager_slot_name(mol, 1)
        slot_name = raw_name if raw_name.lower().endswith(".pdb") else f"{raw_name}.pdb"
        self._append_loaded_slot(
            text=text,
            fmt="pdb",
            components=components,
            name=slot_name,
            path=Path(slot_name),
            refit=refit,
            auto_interactions=False,
            push=push,
            ligand_color_scheme=color_scheme or None,
        )
        return True

    def add_dock_pose_mols(self, mols: list, *, prefix: str = "Pose") -> int:
        """Append each docked pose as a Manager structure. Returns how many were added."""
        from .dock_complex_viewer import pose_manager_slot_name

        usable = [mol for mol in (mols or []) if mol is not None]
        if not usable:
            return 0
        first_index = len(self._slots)
        added = 0
        for i, mol in enumerate(usable, start=1):
            if self.add_ligand_mol(
                mol,
                name=pose_manager_slot_name(mol, i, prefix=prefix),
                refit=False,
                push=False,
            ):
                added += 1
        if not added:
            return 0
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(
            refit=False,
            append_from=first_index if first_index > 0 else None,
        )
        self._refresh_pocket_overlays(zoom=False)
        self._mark_viewer_unsaved()
        return added

    def add_ligand_path(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        color_scheme: str = "default",
        refit: bool = False,
    ) -> bool:
        """Load a crystal/ligand file into the Manager (PDB/mmCIF, or first SDF mol)."""
        rec = Path(str(path)).expanduser()
        if not rec.is_file():
            return False
        suffix = rec.suffix.lower()
        if suffix in {".pdb", ".ent", ".cif", ".mmcif", ".mcif", ".pqr", ".pdbqt"}:
            before = len(self._slots)
            self.add_structure_path(rec, refit=refit)
            return len(self._slots) > before
        from rdkit import Chem

        mol = None
        try:
            if suffix in {".sdf", ".sd"}:
                suppl = Chem.SDMolSupplier(str(rec), removeHs=False, sanitize=False)
                mol = next((item for item in suppl if item is not None), None)
            else:
                mol = Chem.MolFromMolFile(str(rec), removeHs=False, sanitize=False)
        except Exception:
            mol = None
        if mol is None:
            return False
        return self.add_ligand_mol(
            mol,
            name=name or rec.stem or "Crystal ligand",
            color_scheme=color_scheme,
            refit=refit,
        )

    def _duplicate_slot_name(self, name: str) -> str:
        rec = Path(name)
        stem = rec.stem or name
        suffix = rec.suffix
        return f"{stem} copy{suffix}"

    def _residue_keys_for_component_rows(
        self, slot: _LoadedSlot, rows: list[_ComponentView]
    ) -> set[tuple[str, str, str]]:
        want = {row.spec.component_id for row in rows}
        specs = [row.spec for row in slot.rows]
        model = None
        if slot.rows:
            model = (slot.rows[0].spec.selection or {}).get("model")
        keep: set[tuple[str, str, str]] = set()
        for atom in parse_structure_atoms(slot.text, slot.fmt):
            cid = component_id_for_atom(
                specs,
                chain=atom.chain,
                resn=atom.resn,
                resi=atom.resi,
                icode=atom.icode,
                model=model,
                structure_id=slot.structure_id,
            )
            if cid in want:
                keep.add(_residue_key3(atom.chain, atom.resi, atom.icode))
        return keep

    def _structure_text_for_rows(self, slot: _LoadedSlot, rows: list[_ComponentView]) -> str:
        keep = self._residue_keys_for_component_rows(slot, rows)
        if not keep:
            return ""
        atoms = parse_structure_atoms(slot.text, slot.fmt)
        all_keys = {_residue_key3(atom.chain, atom.resi, atom.icode) for atom in atoms}
        drop = all_keys - keep
        if not drop:
            return slot.text
        if (slot.fmt or "").lower() in {"cif", "mmcif"}:
            return delete_cif_residues(slot.text, drop)
        return delete_pdb_residues(slot.text, drop)

    def _row_state_snapshot(self, rows: list[_ComponentView]) -> list[dict]:
        return [
            {
                "kind": row.spec.kind,
                "chain": row.spec.chain,
                "resn": row.spec.resn,
                "resi": row.spec.resi,
                "icode": row.spec.icode,
                "style": row.style,
                "color_scheme": row.color_scheme,
                "visible": row.visible,
                "selected": False,
            }
            for row in rows
        ]

    def duplicate_selected(self) -> None:
        if self.manager.selected_items_are_groups_only():
            return
        ids = set(self._selected_component_ids())
        if not ids:
            return
        snapshots: list[tuple[_LoadedSlot, list[_ComponentView], str]] = []
        for slot in list(self._slots):
            rows = [row for row in slot.rows if row.spec.component_id in ids]
            if not rows:
                continue
            if len(rows) == len(slot.rows):
                text = slot.text
            else:
                text = self._structure_text_for_rows(slot, rows)
            if not (text or "").strip():
                continue
            snapshots.append((slot, rows, text))
        if not snapshots:
            return
        start = len(self._slots)
        appended = False
        for slot, rows, text in snapshots:
            parse_fmt = "cif" if (slot.fmt or "").lower() in {"cif", "mmcif"} else "pdb"
            try:
                components = parse_structure_components(text, parse_fmt)
            except Exception:
                logger.exception("Failed to parse duplicated structure %s", slot.name)
                continue
            if not components:
                continue
            self._append_loaded_slot(
                text=text,
                fmt=slot.fmt,
                components=components,
                name=self._duplicate_slot_name(slot.name),
                path=None,
                refit=False,
                row_states=self._row_state_snapshot(rows),
                push=False,
            )
            appended = True
        if not appended:
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=False, append_from=start if start else None)
        self._refresh_pocket_overlays(zoom=False)
        self._mark_viewer_unsaved()

    def _reindex_models(self) -> None:
        for model, slot in enumerate(self._slots):
            slot.rows = [
                replace(
                    row,
                    spec=scope_structure_component(
                        row.spec, structure_id=slot.structure_id, model=model
                    ),
                )
                for row in slot.rows
            ]

    def close_structure(self, *, mark_dirty: bool = True, keep_edit_history: bool = False) -> None:
        dead = [slot.structure_id for slot in self._slots]
        drop_overlays = getattr(self, "_drop_overlay_structures", None)
        if callable(drop_overlays):
            drop_overlays(dead)
        timer = getattr(self, "_canvas_push_timer", None)
        if timer is not None:
            timer.stop()
        self._slots = []
        if not keep_edit_history:
            self._clear_manager_delete_history()
            self._named_groups = []
            self._group_seq = 0
        self._sequence_chains = []
        self._residue_highlight = []
        self._set_atom_status("")
        self._pocket_payload_data = None
        self._pocket_surface_payload = None
        self._docking_box_payload = None
        self._dock_pose_payload = None
        self._dock_pose_mol = None
        invalidate_pose = getattr(self, "_invalidate_dock_pose_overlay", None)
        if callable(invalidate_pose):
            invalidate_pose()
        else:
            self._dock_pose_overlay = None
        self._invalidate_hbonds()
        self._sync_pocket_surface_dialog()
        act_box = getattr(self, "_act_docking_box", None)
        if act_box is not None:
            act_box.blockSignals(True)
            act_box.setChecked(False)
            act_box.blockSignals(False)
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(False)
        self._act_all_atoms.blockSignals(False)
        self._check_style_action(self._protein_style_actions, "cartoon")
        self._check_style_action(self._ligand_style_actions, "ballstick")
        self._check_style_action(self._protein_color_actions, "default")
        self._check_style_action(self._ligand_color_actions, "default")
        self.setWindowTitle("Protein Viewer")
        self.manager.set_structure([])
        self._sync_sequence_dialog()
        self.viewer.set_payload(
            {
                "data": "",
                "fmt": "pdb",
                "models": [],
                "components": [],
                "residueHighlight": [],
                "pocket": None,
                "pocketSurface": {"active": False},
                "dockingBox": None,
                "dockPose": {"active": False},
                "hbonds": {"active": False, "bonds": []},
                "hydrogens": self._hydrogen_mode(),
                "refit": True,
            }
        )
        if mark_dirty:
            self._mark_viewer_unsaved()

    def _mark_viewer_unsaved(self) -> None:
        """Live edits stay in this window until File → Save to Session."""
        self._session_dirty = True

    def save_viewer_to_session(self) -> bool:
        """Commit the live viewer into the current MolManager session snapshot."""
        parent = self.parent()
        commit = getattr(parent, "commit_protein_viewer_session", None)
        state = self.collect_session_state()
        if not callable(commit):
            self._session_dirty = False
            return True
        try:
            commit(state)
        except (TypeError, ValueError):
            QMessageBox.warning(
                self,
                "Save to Session",
                "Could not write the Protein Viewer into the current session.",
            )
            return False
        self._session_dirty = False
        self.append_log("Saved Protein Viewer to the current session.")
        return True

    def confirm_close_or_save_to_session(self) -> bool:
        """Prompt before close when the live viewer is not the committed snapshot."""
        if getattr(self, "_suppress_close_prompt", False):
            return True
        if not getattr(self, "_session_dirty", False):
            return True
        parent = self.parent()
        committed = getattr(parent, "_protein_viewer_session", None) if parent is not None else None
        if not self._slots and not committed:
            self._session_dirty = False
            return True
        reply = QMessageBox.question(
            self,
            "Save to Session",
            "Save the Protein Viewer to the current MolManager session before closing?",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save,
        )
        if reply == QMessageBox.Cancel:
            return False
        if reply == QMessageBox.Save:
            return self.save_viewer_to_session()
        return True

    def collect_session_state(self) -> dict | None:
        """JSON payload committed by File → Save to Session."""
        if not self._slots:
            return None
        structures = []
        for slot in self._slots:
            structures.append(
                {
                    "name": slot.name,
                    "path": str(slot.path) if slot.path else "",
                    "fmt": slot.fmt,
                    "text": slot.text,
                    "rows": [
                        {
                            "kind": row.spec.kind,
                            "chain": row.spec.chain,
                            "resn": row.spec.resn,
                            "resi": row.spec.resi,
                            "icode": row.spec.icode,
                            "visible": row.visible,
                            "selected": row.selected,
                            "style": row.style,
                            "color_scheme": row.color_scheme,
                        }
                        for row in slot.rows
                    ],
                }
            )
        state: dict = {
            "structures": structures,
            "hydrogens": self._hydrogen_mode(),
            "hbonds": {
                "protein": bool(
                    self._act_hbond_protein is not None and self._act_hbond_protein.isChecked()
                ),
                "ligand": bool(
                    self._act_hbond_ligand is not None and self._act_hbond_ligand.isChecked()
                ),
                "complex": bool(
                    self._act_hbond_complex is not None and self._act_hbond_complex.isChecked()
                ),
            },
            "interactions": {
                "hydrophobic": bool(
                    self._act_interact_hydrophobic is not None
                    and self._act_interact_hydrophobic.isChecked()
                ),
                "ionic": bool(
                    self._act_interact_ionic is not None and self._act_interact_ionic.isChecked()
                ),
                "pi_stacking": bool(
                    self._act_interact_pi_stacking is not None
                    and self._act_interact_pi_stacking.isChecked()
                ),
                "pi_cation": bool(
                    self._act_interact_pi_cation is not None
                    and self._act_interact_pi_cation.isChecked()
                ),
                "halogen": bool(
                    self._act_interact_halogen is not None
                    and self._act_interact_halogen.isChecked()
                ),
            },
            "allAtoms": bool(self._act_all_atoms.isChecked()),
            "pocket": bool(self._pocket_payload_data),
            "pocketSurface": {
                "active": bool(
                    self._pocket_surface_payload is not None
                    and self._pocket_surface_payload.get("active")
                ),
                **self._pocket_surface_style(),
            },
            "dockingBox": self._docking_box_payload,
            "pharmacophore": self._ensure_pharmacophore().to_dict(),
            "pharmacophorePath": str(getattr(self, "_pharmacophore_path", None) or ""),
            "namedGroups": self._named_groups_session_payload(),
            "residueHighlight": list(self._residue_highlight or []),
        }
        splitters: dict[str, list[int]] = {}
        main = getattr(self, "_main_splitter", None)
        log = getattr(self, "_log_splitter", None)
        if main is not None:
            try:
                splitters["main"] = [int(x) for x in main.sizes()]
            except RuntimeError:
                pass
        if log is not None:
            try:
                splitters["log"] = [int(x) for x in log.sizes()]
            except RuntimeError:
                pass
        if splitters:
            state["splitters"] = splitters
        fetch = getattr(self.viewer, "fetch_camera", None)
        if callable(fetch):
            camera = fetch()
            try:
                json.dumps(camera)
            except (TypeError, ValueError):
                camera = None
            if isinstance(camera, (list, dict)):
                state["camera"] = camera
        try:
            geo = self.saveGeometry()
            if geo is not None and not geo.isEmpty():
                state["geometry"] = bytes(geo.toBase64()).decode("ascii")
        except RuntimeError:
            pass
        return state

    def apply_session_state(self, state: dict | None) -> None:
        """Rebuild Manager rows and the 3D canvas from a session payload."""
        if not isinstance(state, dict):
            return
        self.close_structure(mark_dirty=False)
        for spec in state.get("structures") or []:
            if not isinstance(spec, dict):
                continue
            text = str(spec.get("text") or "")
            if not text.strip():
                continue
            fmt = str(spec.get("fmt") or "pdb").lower()
            parse_fmt = "cif" if fmt == "cif" else "pdb"
            try:
                components = parse_structure_components(text, parse_fmt)
            except Exception:
                continue
            if not components:
                continue
            name = str(spec.get("name") or "structure")
            raw_path = str(spec.get("path") or "")
            path = Path(raw_path) if raw_path else Path(name)
            self._append_loaded_slot(
                text=text,
                fmt="cif" if fmt == "cif" else "pdb",
                components=components,
                name=name,
                path=path,
                refit=False,
                row_states=list(spec.get("rows") or []),
                push=False,
            )
        hydrogens = str(state.get("hydrogens") or "polar")
        if hydrogens not in ("all", "polar", "none"):
            hydrogens = "polar"
        self._set_hydrogen_mode(hydrogens)
        hbonds = state.get("hbonds") if isinstance(state.get("hbonds"), dict) else {}
        for act, key in (
            (self._act_hbond_protein, "protein"),
            (self._act_hbond_ligand, "ligand"),
            (self._act_hbond_complex, "complex"),
        ):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(bool(hbonds.get(key)))
            act.blockSignals(False)
        interactions = (
            state.get("interactions") if isinstance(state.get("interactions"), dict) else {}
        )
        for act, key in (
            (self._act_interact_hydrophobic, "hydrophobic"),
            (self._act_interact_ionic, "ionic"),
            (self._act_interact_pi_stacking, "pi_stacking"),
            (self._act_interact_pi_cation, "pi_cation"),
            (self._act_interact_halogen, "halogen"),
        ):
            if act is None:
                continue
            act.blockSignals(True)
            act.setChecked(bool(interactions.get(key)))
            act.blockSignals(False)
        geo = state.get("geometry")
        if isinstance(geo, str) and geo.strip():
            try:
                self.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
            except Exception:
                logger.debug("Protein viewer restore geometry failed", exc_info=True)
        self._restore_session_splitters(state.get("splitters"))
        highlight = state.get("residueHighlight")
        if isinstance(highlight, list):
            self._residue_highlight = [item for item in highlight if isinstance(item, dict)]
        if state.get("allAtoms"):
            for slot in self._slots:
                slot.rows = [
                    replace(row, style="ballstick") if row.spec.kind == "polymer" else row
                    for row in slot.rows
                ]
        self._restore_named_groups(state.get("namedGroups"))
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._sync_render_menus_from_rows()
        if "allAtoms" in state:
            self._sync_all_atoms_check(bool(state.get("allAtoms")))
        camera = state.get("camera")
        has_camera = isinstance(camera, (list, dict))
        if self._slots:
            self._push_structure(
                refit=not has_camera,
                camera=camera if has_camera else None,
            )
            if state.get("pocket"):
                self._activate_pocket(zoom=False)
            raw_surface = state.get("pocketSurface")
            if isinstance(raw_surface, dict):
                from .dialogs.protein_pocket_surface import normalize_pocket_surface_settings

                self._pocket_surface_settings = normalize_pocket_surface_settings(raw_surface)
                if raw_surface.get("active"):
                    self._activate_pocket_surface(notify=False)
            elif raw_surface:
                self._activate_pocket_surface(notify=False)
            self._sync_pocket_surface_dialog()
            box = state.get("dockingBox")
            if isinstance(box, dict) and box.get("active"):
                from ..docking.search_box import docking_box_from_dict

                parsed = docking_box_from_dict(box)
                payload = parsed.viewer_payload() if parsed is not None else box
                self._docking_box_payload = payload
                act = getattr(self, "_act_docking_box", None)
                if act is not None:
                    act.blockSignals(True)
                    act.setChecked(True)
                    act.blockSignals(False)
                self.viewer.set_docking_box(payload)
        pharma = state.get("pharmacophore")
        if pharma is not None:
            apply_pharma = getattr(self, "apply_pharmacophore_state", None)
            if callable(apply_pharma):
                apply_pharma(pharma, path=str(state.get("pharmacophorePath") or ""))
        self._session_dirty = False

    def _restore_session_splitters(self, splitters: object) -> None:
        if not isinstance(splitters, dict):
            return
        for attr, key in (("_main_splitter", "main"), ("_log_splitter", "log")):
            widget = getattr(self, attr, None)
            sizes = splitters.get(key)
            if widget is None or not isinstance(sizes, list) or len(sizes) < 2:
                continue
            try:
                widget.setSizes([int(x) for x in sizes[:2]])
            except (TypeError, ValueError, RuntimeError):
                continue

    def open_prepare_dialog(self) -> None:
        """Open the Fast Prepare pipeline dialog for a Manager structure or file."""
        dlg = self._prepare_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._prepare_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_prepare import ProteinPrepareDialog

            dlg = ProteinPrepareDialog(self)
            dlg.prepared.connect(self._on_structure_prepared)
            dlg.smina_prepared.connect(self._on_smina_prepared)
            dlg.destroyed.connect(self._on_prepare_dialog_destroyed)
            self._prepare_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_prepare_dialog_destroyed(self) -> None:
        self._prepare_dialog = None

    def open_pdbfixer_dialog(self) -> None:
        """Open the PDBFixer repair/clean dialog for a Manager structure or file."""
        dlg = self._pdbfixer_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._pdbfixer_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_pdbfixer import ProteinPdbFixerDialog

            dlg = ProteinPdbFixerDialog(self)
            dlg.prepared.connect(self._on_structure_fixed)
            dlg.destroyed.connect(self._on_pdbfixer_dialog_destroyed)
            self._pdbfixer_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_pdbfixer_dialog_destroyed(self) -> None:
        self._pdbfixer_dialog = None

    def open_pdb2pqr_dialog(self) -> None:
        """Open the pdb2pqr protonation dialog for a Manager structure or file."""
        dlg = self._pdb2pqr_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._pdb2pqr_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_pdb2pqr import ProteinPdb2pqrDialog

            dlg = ProteinPdb2pqrDialog(self)
            dlg.prepared.connect(self._on_structure_protonated)
            dlg.destroyed.connect(self._on_pdb2pqr_dialog_destroyed)
            self._pdb2pqr_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_pdb2pqr_dialog_destroyed(self) -> None:
        self._pdb2pqr_dialog = None

    def open_simulation_window(self) -> None:
        """Open the simulation workspace for the structure loaded in this viewer."""
        host = self.parent()
        opener = getattr(host, "open_simulation", None)
        if callable(opener):
            opener()
            return
        from .simulation.window import SimulationWindow

        window = SimulationWindow(None, viewer=self, parent=self)
        window.show()
        window.raise_()
        window.activateWindow()

    def open_minimize_dialog(self) -> None:
        """Open the Minimize dialog for a Manager structure or file."""
        dlg = self._minimize_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._minimize_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_minimize import ProteinMinimizeDialog

            dlg = ProteinMinimizeDialog(self)
            dlg.minimized.connect(self._on_structure_minimized)
            dlg.destroyed.connect(self._on_minimize_dialog_destroyed)
            self._minimize_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_minimize_dialog_destroyed(self) -> None:
        self._minimize_dialog = None

    def open_dock_file_dialog(self) -> None:
        """Open the Dock File dialog for a Manager structure or file."""
        dlg = self._dock_file_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._dock_file_dialog = None
            dlg = None
        if dlg is None:
            from .dialogs.protein_dock_file import ProteinDockFileDialog

            dlg = ProteinDockFileDialog(self)
            dlg.smina_prepared.connect(self._on_smina_prepared)
            dlg.destroyed.connect(self._on_dock_file_dialog_destroyed)
            self._dock_file_dialog = dlg
        dlg.prefill_from_viewer()
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_dock_file_dialog_destroyed(self) -> None:
        self._dock_file_dialog = None

    def _on_structure_minimized(self, output_path: str) -> None:
        path = Path(output_path)
        if not path.is_file():
            QMessageBox.warning(self, "Minimize Complex", f"Minimized file was not found:\n{path}")
            return
        self.add_structure_path(path, refit=False)

    def _on_structure_prepared(self, output_pdb: str) -> None:
        self._overlay_prepared_path(output_pdb, "Fast Prepare")

    def _on_structure_fixed(self, output_pdb: str) -> None:
        self._overlay_prepared_path(output_pdb, "PDBFixer")

    def _on_structure_protonated(self, output_pdb: str) -> None:
        self._overlay_prepared_path(output_pdb, "pdb2pqr")

    def _overlay_prepared_path(self, output_pdb: str, title: str) -> None:
        path = Path(output_pdb)
        if not path.is_file():
            QMessageBox.warning(self, title, f"Prepared file was not found:\n{path}")
            return
        self.add_structure_path(path, refit=False)

    def _on_smina_prepared(self, result) -> None:
        setter = getattr(self, "set_docking_box_from_prepare", None)
        if callable(setter):
            setter(result)
