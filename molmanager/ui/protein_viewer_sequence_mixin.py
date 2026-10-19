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

"""Sequence window wiring for the Protein Viewer."""

from __future__ import annotations

from dataclasses import replace

from ..protein.structure_components import (
    PolymerChain,
    delete_pdb_residues,
    letter_to_resn,
    parse_polymer_sequences,
    rewrite_pdb_residue_names,
)
from .protein_sequence import ProteinSequenceDialog
from .protein_viewer_models import _LoadedSlot
from .qt_widget_utils import qobject_is_deleted


class ProteinViewerSequenceMixin:
    def open_sequence_window(self) -> None:
        """Open or raise the Sequence window for the current polymer chains."""
        dlg = self._sequence_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._sequence_dialog = None
            dlg = None
        if dlg is None:
            dlg = ProteinSequenceDialog(self)
            dlg.residue_selection_changed.connect(self._on_sequence_selection)
            dlg.residues_mutated.connect(self._on_sequence_mutated)
            dlg.residues_deleted.connect(self._on_sequence_deleted)
            dlg.focus_residues_requested.connect(self._on_sequence_focus)
            dlg.destroyed.connect(self._on_sequence_dialog_destroyed)
            self._sequence_dialog = dlg
        self._refresh_sequence_chains(force=True)
        dlg.set_chains(self._sequence_chains)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_sequence_dialog_destroyed(self) -> None:
        self._sequence_dialog = None

    def _refresh_sequence_chains(self, *, force: bool = False) -> None:
        dlg = self._sequence_dialog
        live = dlg is not None and not qobject_is_deleted(dlg)
        if not force and not live:
            return
        filtered: list[PolymerChain] = []
        for model, slot in enumerate(self._slots):
            fmt = "cif" if slot.fmt == "cif" else "pdb"
            for poly in parse_polymer_sequences(slot.text, fmt):
                residues = [
                    replace(
                        res,
                        structure_id=slot.structure_id,
                        model=model,
                    )
                    for res in poly.residues
                    if self._sequence_residue_is_live(res, slot)
                ]
                if residues:
                    filtered.append(
                        PolymerChain(
                            chain=poly.chain,
                            residues=list(residues),
                            structure_id=slot.structure_id,
                            structure_name=slot.name,
                        )
                    )
        self._sequence_chains = filtered
        self._sync_sequence_dialog()

    def _sequence_residue_is_live(self, res, slot: _LoadedSlot) -> bool:
        rows = slot.rows
        if not rows:
            return False
        if res.kind in {"polymer", "missing"}:
            return any(row.spec.kind == "polymer" and row.spec.chain == res.chain for row in rows)
        if res.kind == "water":
            return any(row.spec.kind == "water" and row.spec.chain == res.chain for row in rows)
        return any(
            row.spec.kind == res.kind
            and row.spec.chain == res.chain
            and row.spec.resn == res.resn
            and row.spec.resi == res.resi
            for row in rows
        )

    def _sync_sequence_dialog(self) -> None:
        dlg = self._sequence_dialog
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_chains(self._sequence_chains)

    def _set_residue_highlight(
        self,
        selections: list[dict],
        *,
        sync_selection: bool = False,
    ) -> None:
        self._residue_highlight = list(selections)
        if sync_selection:
            selected_ids = [row.spec.component_id for row in self._rows if row.selected]
            self.viewer.set_residue_highlight(
                {"sels": self._residue_highlight, "selectedIds": selected_ids}
            )
        else:
            self.viewer.set_residue_highlight(self._residue_highlight)
        atom_level = any(
            (sel or {}).get("atom") or ((sel or {}).get("serial") not in (None, ""))
            for sel in self._residue_highlight
        )
        if not atom_level:
            self._set_atom_status("")

    def _on_sequence_selection(self, selections: list) -> None:
        self._set_residue_highlight(list(selections or []))

    def _on_sequence_focus(self, selections: list) -> None:
        if selections:
            self.viewer.zoom_to_selections(list(selections))

    def _slot_for_residue(self, residue) -> _LoadedSlot | None:
        sid = getattr(residue, "structure_id", "") or ""
        if sid:
            for slot in self._slots:
                if slot.structure_id == sid:
                    return slot
        return self._active_slot()

    def _on_sequence_mutated(self, items: list) -> None:
        payload = []
        by_slot: dict[str, list[tuple[str, str, str, str]]] = {}
        for residue, letter in items:
            resn = letter_to_resn(letter)
            if not resn:
                continue
            entry = {
                "chain": residue.chain,
                "resi": residue.selection().get("resi"),
                "icode": residue.icode,
                "resn": resn,
            }
            if residue.model is not None:
                entry["model"] = residue.model
            payload.append(entry)
            slot = self._slot_for_residue(residue)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, []).append(
                (residue.chain, residue.resi, residue.icode, resn)
            )
        if not payload:
            return
        for slot in self._slots:
            changes = by_slot.get(slot.structure_id)
            if changes and slot.fmt in {"pdb", "pqr"}:
                slot.text = rewrite_pdb_residue_names(slot.text, changes)
                self._invalidate_hbonds(slot.structure_id)
        self.viewer.mutate_residues(payload)
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()
        if self._hbond_kinds_enabled():
            self._push_hbonds()

    def _on_sequence_deleted(self, residues: list) -> None:
        if not residues:
            return
        sels = []
        for res in residues:
            sel = res.selection()
            sel["structure_id"] = res.structure_id
            sel["kind"] = res.kind
            sel["resn"] = res.resn
            sels.append(sel)
        deleter = getattr(self, "delete_residue_selections", None)
        if callable(deleter):
            deleter(sels, confirm=False)
            return
        keys = {(res.chain, res.resi, res.icode) for res in residues}
        js_sels = [res.selection() for res in residues]
        by_slot: dict[str, set[tuple[str, str, str]]] = {}
        for res in residues:
            slot = self._slot_for_residue(res)
            if slot is None:
                continue
            by_slot.setdefault(slot.structure_id, set()).add((res.chain, res.resi, res.icode))
        for slot in self._slots:
            slot_keys = by_slot.get(slot.structure_id)
            if slot_keys and slot.fmt in {"pdb", "pqr"}:
                slot.text = delete_pdb_residues(slot.text, slot_keys)
                self._invalidate_hbonds(slot.structure_id)
        self.viewer.delete_residues(js_sels)
        self._residue_highlight = [
            sel
            for sel in self._residue_highlight
            if (str(sel.get("chain")), str(sel.get("resi")), str(sel.get("icode") or ""))
            not in {(k[0], k[1], k[2]) for k in keys}
        ]
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._sequence_chains = dlg.chains()
        self.viewer.set_residue_highlight(self._residue_highlight)
        if self._hbond_kinds_enabled():
            self._push_hbonds()
