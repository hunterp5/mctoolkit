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

"""Render style, hydrogens, H-bonds, pocket, and Manager actions."""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import replace

from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QAction, QActionGroup, QColorDialog, QMessageBox

from ..protein.hydrogen_bonds import (
    HBOND_KIND_COMPLEX,
    HBOND_KIND_LIGAND,
    HBOND_KIND_PROTEIN,
    detect_hydrogen_bonds,
)
from ..protein.protein_interactions import (
    FAMILY_HALOGEN,
    FAMILY_HBOND,
    FAMILY_HYDROPHOBIC,
    FAMILY_IONIC,
    FAMILY_PI_CATION,
    FAMILY_PI_STACKING,
    detect_prolif_interactions,
    prolif_available,
    residue_pair_key,
)
from ..protein.structure_components import (
    component_id_for_atom,
    pocket_view_plan,
    polymer_residue_for_atom,
)
from .protein_viewer_models import (
    COMPONENT_COLOR_CHOICES,
    COMPONENT_STYLE_CHOICES,
    LIGAND_STYLE_CHOICES,
    LIGAND_STYLE_IDS,
    _LoadedSlot,
    copy_loaded_slots,
)
from .qt_widget_utils import qobject_is_deleted

logger = logging.getLogger(__name__)

_MANAGER_DELETE_UNDO_LIMIT = 50


class ProteinViewerStyleMixin:
    def _on_all_atoms_toggled(self, checked: bool) -> None:
        style = "ballstick" if checked else "cartoon"
        self._check_style_action(self._protein_style_actions, style)
        self._apply_kind_style("polymer", style)

    def _hydrogen_mode(self) -> str:
        for mode in ("all", "none", "polar"):
            for act in self._hydrogen_mode_actions.get(mode) or ():
                if act is not None and act.isChecked():
                    return mode
        if self._act_hydrogens_all is not None and self._act_hydrogens_all.isChecked():
            return "all"
        if self._act_hydrogens_none is not None and self._act_hydrogens_none.isChecked():
            return "none"
        return "polar"

    def _sync_hydrogen_mode_actions(self, mode: str) -> None:
        chosen = mode if mode in ("all", "polar", "none") else "polar"
        for key, acts in (getattr(self, "_hydrogen_mode_actions", None) or {}).items():
            for act in acts:
                if act is None:
                    continue
                act.blockSignals(True)
                act.setChecked(key == chosen)
                act.blockSignals(False)

    def _set_hydrogen_mode(self, mode: str) -> None:
        chosen = mode if mode in ("all", "polar", "none") else "polar"
        self._sync_hydrogen_mode_actions(chosen)
        self.viewer.set_hydrogens(chosen)
        self._mark_viewer_unsaved()

    def _add_hydrogen_mode_menu(self, menu) -> None:
        """All / Polar / None hydrogen visibility (same mode as Render → Hydrogens)."""
        group = QActionGroup(self)
        group.setExclusive(True)
        specs = (
            (
                "all",
                "&All",
                "Show all explicit hydrogens on residues and ligands whose heavy atoms "
                "are visible (not cartoon-only or hidden).",
            ),
            (
                "polar",
                "&Polar",
                "Show hydrogens bonded to heteroatoms on protein and ligand. "
                "Hydrogens appear only when that residue or ligand's heavy atoms are visible.",
            ),
            (
                "none",
                "&None",
                "Hide all explicit hydrogens on the 3D canvas.",
            ),
        )
        store = getattr(self, "_hydrogen_mode_actions", None)
        if store is None:
            self._hydrogen_mode_actions = {"all": [], "polar": [], "none": []}
            store = self._hydrogen_mode_actions
        for mode, label, tip in specs:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setToolTip(tip)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(lambda _checked=False, m=mode: self._set_hydrogen_mode(m))
            store.setdefault(mode, []).append(act)

    def _protein_ligand_interaction_actions(self):
        """Intermolecular contact toggles (not intramolecular protein/ligand H-bonds)."""
        return (
            self._act_hbond_complex,
            self._act_interact_hydrophobic,
            self._act_interact_ionic,
            self._act_interact_pi_stacking,
            self._act_interact_pi_cation,
            self._act_interact_halogen,
        )

    def _enable_protein_ligand_interactions_for_complex(self) -> None:
        """Turn on ligand intramolecular H-bonds and protein–ligand overlays when present."""
        kinds = {row.spec.kind for row in self._rows}
        acts = []
        if "ligand" in kinds:
            acts.append(self._act_hbond_ligand)
        if "ligand" in kinds and "polymer" in kinds:
            acts.extend(self._protein_ligand_interaction_actions())
        for act in acts:
            if act is None or act.isChecked():
                continue
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)

    def _hbond_kinds_enabled(self) -> set[str]:
        kinds: set[str] = set()
        if self._act_hbond_protein is not None and self._act_hbond_protein.isChecked():
            kinds.add(HBOND_KIND_PROTEIN)
        if self._act_hbond_ligand is not None and self._act_hbond_ligand.isChecked():
            kinds.add(HBOND_KIND_LIGAND)
        if self._act_hbond_complex is not None and self._act_hbond_complex.isChecked():
            kinds.add(HBOND_KIND_COMPLEX)
        return kinds

    def _prolif_families_enabled(self) -> set[str]:
        families: set[str] = set()
        for act, family in (
            (self._act_interact_hydrophobic, FAMILY_HYDROPHOBIC),
            (self._act_interact_ionic, FAMILY_IONIC),
            (self._act_interact_pi_stacking, FAMILY_PI_STACKING),
            (self._act_interact_pi_cation, FAMILY_PI_CATION),
            (self._act_interact_halogen, FAMILY_HALOGEN),
        ):
            if act is not None and act.isChecked():
                families.add(family)
        return families

    def _interaction_overlay_active(self) -> bool:
        return bool(self._hbond_kinds_enabled() or self._prolif_families_enabled())

    def _invalidate_hbonds(self, structure_id: str | None = None) -> None:
        if getattr(self, "_prolif_cache", None) is None:
            self._prolif_cache = {}
        if structure_id is None:
            self._hbond_cache.clear()
            self._prolif_cache.clear()
        else:
            self._hbond_cache.pop(structure_id, None)
            self._prolif_cache.pop(structure_id, None)

    def _slot_model_index(self, slot: _LoadedSlot) -> int | None:
        for row in slot.rows:
            model = (row.spec.selection or {}).get("model")
            if model is not None:
                try:
                    return int(model)
                except (TypeError, ValueError):
                    return None
        return None

    def _ensure_hbond_cache(self) -> None:
        if not self._hbond_kinds_enabled():
            return
        for slot in self._slots:
            if slot.structure_id in self._hbond_cache:
                continue
            self._hbond_cache[slot.structure_id] = detect_hydrogen_bonds(
                slot.text, slot.fmt, model=self._slot_model_index(slot)
            )

    def _ensure_prolif_cache(self) -> None:
        if getattr(self, "_prolif_cache", None) is None:
            self._prolif_cache = {}
        families = self._prolif_families_enabled()
        need_complex = HBOND_KIND_COMPLEX in self._hbond_kinds_enabled()
        if not families and not need_complex:
            return
        if not prolif_available():
            if families and not getattr(self, "_prolif_missing_logged", False):
                self._prolif_missing_logged = True
                self.append_log(
                    "ProLIF is not installed. Hydrophobic, ionic, π-stacking, π-cation, "
                    "and halogen overlays need `pip install prolif` "
                    '(or `pip install -e ".[docking]"`). Protein–ligand hydrogen bonds '
                    "still use the geometric detector."
                )
            for slot in self._slots:
                self._prolif_cache.setdefault(slot.structure_id, ())
            return
        for slot in self._slots:
            if slot.structure_id in self._prolif_cache:
                continue
            self.append_log(f"Running ProLIF on {slot.name}…")
            try:
                contacts = detect_prolif_interactions(
                    slot.text, slot.fmt, model=self._slot_model_index(slot)
                )
            except Exception as exc:
                logger.debug("ProLIF overlay failed for %s", slot.name, exc_info=True)
                self.append_log(f"ProLIF failed for {slot.name}: {exc}")
                self._prolif_cache[slot.structure_id] = ()
                continue
            self._prolif_cache[slot.structure_id] = contacts
            self.append_log(f"ProLIF found {len(contacts)} contact(s) in {slot.name}.")

    def _hbond_endpoint_visible(self, bond, *, model: int | None) -> bool:
        return self._residue_pair_visible(
            bond.donor_chain,
            bond.donor_resn,
            bond.donor_resi,
            bond.donor_icode,
            bond.donor_kind,
            bond.acceptor_chain,
            bond.acceptor_resn,
            bond.acceptor_resi,
            bond.acceptor_icode,
            bond.acceptor_kind,
            model=model,
        )

    def _prolif_contact_visible(self, contact, *, model: int | None) -> bool:
        return self._residue_pair_visible(
            contact.ligand_chain,
            contact.ligand_resn,
            contact.ligand_resi,
            contact.ligand_icode,
            "ligand",
            contact.protein_chain,
            contact.protein_resn,
            contact.protein_resi,
            contact.protein_icode,
            "polymer",
            model=model,
        )

    def _dock_pose_live(self) -> bool:
        return bool(getattr(self, "_dock_pose_payload", None))

    def _pose_hbond_visible(self, bond, *, model: int | None) -> bool:
        if bond.kind == HBOND_KIND_LIGAND:
            return True
        return self._residue_pair_visible(
            bond.donor_chain,
            bond.donor_resn,
            bond.donor_resi,
            bond.donor_icode,
            bond.donor_kind,
            bond.acceptor_chain,
            bond.acceptor_resn,
            bond.acceptor_resi,
            bond.acceptor_icode,
            bond.acceptor_kind,
            model=model,
            allow_dock_pose_ligand=True,
        )

    def _pose_prolif_contact_visible(self, contact, *, model: int | None) -> bool:
        return self._residue_pair_visible(
            contact.ligand_chain,
            contact.ligand_resn,
            contact.ligand_resi,
            contact.ligand_icode,
            "ligand",
            contact.protein_chain,
            contact.protein_resn,
            contact.protein_resi,
            contact.protein_icode,
            "polymer",
            model=model,
            allow_dock_pose_ligand=True,
        )

    def _residue_pair_visible(
        self,
        chain_a: str,
        resn_a: str,
        resi_a: str,
        icode_a: str,
        kind_a: str,
        chain_b: str,
        resn_b: str,
        resi_b: str,
        icode_b: str,
        kind_b: str,
        *,
        model: int | None,
        allow_dock_pose_ligand: bool = False,
    ) -> bool:
        return self._residue_is_visible(
            chain=chain_a,
            resn=resn_a,
            resi=resi_a,
            icode=icode_a,
            kind=kind_a,
            model=model,
            allow_dock_pose_ligand=allow_dock_pose_ligand,
        ) and self._residue_is_visible(
            chain=chain_b,
            resn=resn_b,
            resi=resi_b,
            icode=icode_b,
            kind=kind_b,
            model=model,
            allow_dock_pose_ligand=allow_dock_pose_ligand,
        )

    def _residue_is_visible(
        self,
        *,
        chain: str,
        resn: str,
        resi: str,
        icode: str,
        kind: str,
        model: int | None,
        allow_dock_pose_ligand: bool = False,
    ) -> bool:
        if allow_dock_pose_ligand and kind == "ligand" and self._dock_pose_live():
            return True
        resi_s = str(resi)
        for row in self._rows:
            if not row.visible:
                continue
            spec = row.spec
            sel_model = (spec.selection or {}).get("model")
            if model is not None and sel_model is not None:
                try:
                    if int(sel_model) != int(model):
                        continue
                except (TypeError, ValueError):
                    continue
            if spec.kind == "polymer" and kind == "polymer" and spec.chain == chain:
                return True
            if (
                spec.kind == kind
                and spec.chain == chain
                and spec.resn == resn
                and spec.resi == resi_s
                and spec.icode == icode
            ):
                return True
        return False

    def _hbond_overlay_payload(self) -> dict:
        kinds = self._hbond_kinds_enabled()
        families = self._prolif_families_enabled()
        if (not kinds and not families) or not self._slots:
            return {"active": False, "bonds": []}
        self._ensure_hbond_cache()
        pose_live = self._dock_pose_live()
        if not pose_live and (families or HBOND_KIND_COMPLEX in kinds):
            self._ensure_prolif_cache()
        pose_overlay = getattr(self, "_dock_pose_overlay", None) if pose_live else None
        bonds = []
        for slot in self._slots:
            model = self._slot_model_index(slot)
            prolif_hits = () if pose_live else self._prolif_cache.get(slot.structure_id, ())
            prolif_hbonds = [c for c in prolif_hits if c.family == FAMILY_HBOND]
            prolif_pairs = {
                residue_pair_key(
                    c.ligand_chain,
                    c.ligand_resi,
                    c.ligand_icode,
                    c.ligand_resn,
                    c.protein_chain,
                    c.protein_resi,
                    c.protein_icode,
                    c.protein_resn,
                )
                for c in prolif_hbonds
            }
            if kinds:
                for bond in self._hbond_cache.get(slot.structure_id, ()):
                    if bond.kind not in kinds:
                        continue
                    if pose_live and bond.kind in {HBOND_KIND_LIGAND, HBOND_KIND_COMPLEX}:
                        continue
                    if bond.kind == HBOND_KIND_COMPLEX and prolif_pairs:
                        pair = residue_pair_key(
                            bond.donor_chain,
                            bond.donor_resi,
                            bond.donor_icode,
                            bond.donor_resn,
                            bond.acceptor_chain,
                            bond.acceptor_resi,
                            bond.acceptor_icode,
                            bond.acceptor_resn,
                        )
                        if pair in prolif_pairs:
                            continue
                    if not self._hbond_endpoint_visible(bond, model=model):
                        continue
                    bonds.append(bond.to_payload())
                if HBOND_KIND_COMPLEX in kinds:
                    for contact in prolif_hbonds:
                        if not self._prolif_contact_visible(contact, model=model):
                            continue
                        bonds.append(contact.to_payload())
            for contact in prolif_hits:
                if contact.family == FAMILY_HBOND or contact.family not in families:
                    continue
                if not self._prolif_contact_visible(contact, model=model):
                    continue
                bonds.append(contact.to_payload())
        if pose_live and isinstance(pose_overlay, tuple) and len(pose_overlay) == 2:
            pose_hbonds, pose_prolif = pose_overlay
            slot = self._receptor_slot_for_dock_pose()
            model = self._slot_model_index(slot) if slot is not None else None
            prolif_hbonds = [c for c in pose_prolif if c.family == FAMILY_HBOND]
            prolif_pairs = {
                residue_pair_key(
                    c.ligand_chain,
                    c.ligand_resi,
                    c.ligand_icode,
                    c.ligand_resn,
                    c.protein_chain,
                    c.protein_resi,
                    c.protein_icode,
                    c.protein_resn,
                )
                for c in prolif_hbonds
            }
            if kinds:
                for bond in pose_hbonds or ():
                    if bond.kind not in kinds:
                        continue
                    if bond.kind == HBOND_KIND_COMPLEX and prolif_pairs:
                        pair = residue_pair_key(
                            bond.donor_chain,
                            bond.donor_resi,
                            bond.donor_icode,
                            bond.donor_resn,
                            bond.acceptor_chain,
                            bond.acceptor_resi,
                            bond.acceptor_icode,
                            bond.acceptor_resn,
                        )
                        if pair in prolif_pairs:
                            continue
                    if not self._pose_hbond_visible(bond, model=model):
                        continue
                    bonds.append(bond.to_payload())
                if HBOND_KIND_COMPLEX in kinds:
                    for contact in prolif_hbonds:
                        if not self._pose_prolif_contact_visible(contact, model=model):
                            continue
                        bonds.append(contact.to_payload())
            for contact in pose_prolif or ():
                if contact.family == FAMILY_HBOND or contact.family not in families:
                    continue
                if not self._pose_prolif_contact_visible(contact, model=model):
                    continue
                bonds.append(contact.to_payload())
        return {"active": True, "bonds": bonds}

    def _on_hbond_toggles(self, _checked: bool = False) -> None:
        if self._dock_pose_live():
            self._invalidate_dock_pose_overlay()
            if self._interaction_overlay_active():
                self._schedule_dock_pose_overlay_job()
        self._push_hbonds()
        self._mark_viewer_unsaved()

    def _push_hbonds(self) -> None:
        self.viewer.set_hbonds(self._hbond_overlay_payload())

    def _style_choices_for_kind(self, kind: str) -> tuple[tuple[str, str], ...]:
        if kind == "ligand":
            return LIGAND_STYLE_CHOICES
        return COMPONENT_STYLE_CHOICES

    def _style_allowed_for_kind(self, kind: str, style: str) -> bool:
        return style in {key for key, _label in self._style_choices_for_kind(kind)}

    def _apply_kind_style(self, kind: str, style: str) -> None:
        if not self._style_allowed_for_kind(kind, style):
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.style != style:
                    new_rows.append(replace(row, style=style))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        self._clear_pocket_overlay()
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _add_select_style_menu(self, menu) -> None:
        for style_id, label in COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Apply this style to the Manager selection.")
            act.triggered.connect(lambda _checked=False, s=style_id: self._on_style_requested(s))
            menu.addAction(act)
        menu.addSeparator()
        self._add_hydrogen_mode_menu(menu.addMenu("&Hydrogens"))

    def _add_select_color_menu(self, menu) -> None:
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setToolTip("Color carbons in the Manager selection; heteroatoms stay CPK.")
            act.triggered.connect(lambda _checked=False, c=color_id: self._apply_selected_color(c))
            menu.addAction(act)
        menu.addSeparator()
        act_custom = QAction("Custom…", self, triggered=self._on_select_custom_color)
        act_custom.setToolTip("Pick a carbon color for the Manager selection.")
        menu.addAction(act_custom)

    def _selected_component_ids(self) -> list[str]:
        return self.manager.selected_component_ids() or [
            r.spec.component_id for r in self._rows if r.selected
        ]

    def _require_selection(self) -> list[str]:
        ids = self._selected_component_ids()
        if not ids:
            QMessageBox.information(
                self,
                "Select",
                "Select a chain or ligand in the Manager first.",
            )
        return ids

    def _set_selected_visible(self, visible: bool) -> None:
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_select_custom_color(self) -> None:
        chosen = QColorDialog.getColor(QColor("#2ca02c"), self, "Carbon color")
        if not chosen.isValid():
            return
        self._apply_selected_color(chosen.name())

    def _apply_selected_color(self, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed and not str(color_scheme).startswith("#"):
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        self._clear_pocket_overlay()
        if changed:
            self._push_states()

    def _add_render_style_menu(
        self,
        menu,
        *,
        kind: str,
        default: str,
        choices: tuple[tuple[str, str], ...] | None = None,
    ) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for style_id, label in choices or COMPONENT_STYLE_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(style_id)
            if style_id == default:
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, s=style_id, k=kind: self._on_render_style_chosen(k, s)
            )
            actions[style_id] = act
        return actions

    def _add_render_color_menu(self, menu, *, kind: str) -> dict[str, QAction]:
        group = QActionGroup(self)
        group.setExclusive(True)
        actions: dict[str, QAction] = {}
        for color_id, label in COMPONENT_COLOR_CHOICES:
            act = QAction(label, self)
            act.setCheckable(True)
            act.setData(color_id)
            if color_id == "default":
                act.setChecked(True)
            group.addAction(act)
            menu.addAction(act)
            act.triggered.connect(
                lambda _checked=False, c=color_id, k=kind: self._on_render_color_chosen(k, c)
            )
            actions[color_id] = act
        return actions

    def _on_render_style_chosen(self, kind: str, style: str) -> None:
        self._apply_kind_style(kind, style)
        if kind == "polymer":
            self._sync_all_atoms_check(style == "ballstick")

    def _on_render_color_chosen(self, kind: str, color_scheme: str) -> None:
        self._apply_kind_color(kind, color_scheme)

    def _apply_kind_color(self, kind: str, color_scheme: str) -> None:
        allowed = {key for key, _label in COMPONENT_COLOR_CHOICES}
        if color_scheme not in allowed:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.kind == kind and row.color_scheme != color_scheme:
                    new_rows.append(replace(row, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        self._clear_pocket_overlay()
        if changed:
            self._push_states()

    def _checked_style(self, actions: dict[str, QAction], fallback: str) -> str:
        for style_id, act in actions.items():
            if act.isChecked():
                return style_id
        return fallback

    def _check_style_action(self, actions: dict[str, QAction], style: str) -> None:
        act = actions.get(style)
        if act is None or act.isChecked():
            return
        act.blockSignals(True)
        act.setChecked(True)
        act.blockSignals(False)

    def _sync_all_atoms_check(self, checked: bool) -> None:
        if self._act_all_atoms.isChecked() == checked:
            return
        self._act_all_atoms.blockSignals(True)
        self._act_all_atoms.setChecked(checked)
        self._act_all_atoms.blockSignals(False)

    def _restore_loaded_render_styles(self) -> bool:
        """Restore each component's style and color from when it was loaded."""
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                style = row.loaded_style or row.spec.default_style
                color_scheme = row.loaded_color_scheme or "default"
                if row.style != style or row.color_scheme != color_scheme:
                    new_rows.append(replace(row, style=style, color_scheme=color_scheme))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        return changed

    def _clear_pocket_overlay(self) -> None:
        if self._pocket_payload_data is None:
            return
        self._pocket_payload_data = None
        self.viewer.set_pocket({"active": False})

    def _sync_render_menus_from_rows(self) -> None:
        polymer = {r.style for r in self._rows if r.spec.kind == "polymer"}
        ligand = {r.style for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer) == 1:
            style = next(iter(polymer))
            self._check_style_action(self._protein_style_actions, style)
            self._sync_all_atoms_check(style == "ballstick")
        if len(ligand) == 1:
            style = next(iter(ligand))
            if style not in LIGAND_STYLE_IDS:
                style = "ballstick"
            self._check_style_action(self._ligand_style_actions, style)
        polymer_color = {r.color_scheme for r in self._rows if r.spec.kind == "polymer"}
        ligand_color = {r.color_scheme for r in self._rows if r.spec.kind == "ligand"}
        if len(polymer_color) == 1:
            self._check_style_action(self._protein_color_actions, next(iter(polymer_color)))
        if len(ligand_color) == 1:
            self._check_style_action(self._ligand_color_actions, next(iter(ligand_color)))

    def _on_pocket(self) -> None:
        self._activate_pocket(zoom=True)

    def open_pocket_surface_dialog(self) -> None:
        """Open Pocket Surface options. The surface is drawn only when OK is clicked."""
        from .dialogs.protein_pocket_surface import ProteinPocketSurfaceDialog

        dlg = self._pocket_surface_dialog
        if dlg is not None and qobject_is_deleted(dlg):
            self._pocket_surface_dialog = None
            dlg = None
        if dlg is None:
            dlg = ProteinPocketSurfaceDialog(self)
            dlg.settings_changed.connect(self._on_pocket_surface_settings)
            dlg.show_toggled.connect(self._on_pocket_surface_show)
            dlg.generate_requested.connect(self._on_pocket_surface_generate)
            dlg.destroyed.connect(self._on_pocket_surface_dialog_destroyed)
            self._pocket_surface_dialog = dlg
        dlg.set_settings(self._pocket_surface_style())
        dlg.set_showing(
            bool(
                self._pocket_surface_payload is not None
                and self._pocket_surface_payload.get("active")
            )
        )
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _on_pocket_surface_generate(self) -> None:
        """Build the pocket surface from the dialog options and close on success."""
        from .dialogs.protein_pocket_surface import normalize_pocket_surface_settings

        dlg = self._pocket_surface_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            self._pocket_surface_settings = normalize_pocket_surface_settings(dlg.settings())
        if self._activate_pocket_surface():
            self._sync_pocket_surface_dialog()
            if dlg is not None and not qobject_is_deleted(dlg):
                dlg.accept()
            return
        self._sync_pocket_surface_dialog()

    def _on_pocket_surface_dialog_destroyed(self) -> None:
        self._pocket_surface_dialog = None

    def _on_pocket_surface_show(self, show: bool) -> None:
        if show:
            if self._activate_pocket_surface():
                self._sync_pocket_surface_dialog()
                return
            self._sync_pocket_surface_dialog()
            return
        self._hide_pocket_surface()

    def _on_pocket_surface_settings(self, settings: dict) -> None:
        from .dialogs.protein_pocket_surface import normalize_pocket_surface_settings

        self._pocket_surface_settings = normalize_pocket_surface_settings(settings)
        if self._pocket_surface_payload is None or not self._pocket_surface_payload.get("active"):
            return
        self._activate_pocket_surface(notify=False)

    def _pocket_surface_style(self) -> dict:
        from .dialogs.protein_pocket_surface import normalize_pocket_surface_settings

        return normalize_pocket_surface_settings(self._pocket_surface_settings)

    def _hide_pocket_surface(self) -> None:
        self._pocket_surface_payload = None
        self.viewer.set_pocket_surface({"active": False})
        self._sync_pocket_surface_dialog()
        self._mark_viewer_unsaved()

    def _sync_pocket_surface_dialog(self) -> None:
        dlg = getattr(self, "_pocket_surface_dialog", None)
        if dlg is None or qobject_is_deleted(dlg):
            return
        dlg.set_settings(self._pocket_surface_style())
        dlg.set_showing(
            bool(
                self._pocket_surface_payload is not None
                and self._pocket_surface_payload.get("active")
            )
        )

    def _activate_pocket_surface(self, *, notify: bool = True) -> bool:
        payload = self._compute_pocket_payload()
        residue_sels = list((payload or {}).get("residueSels") or [])
        if payload is None:
            if notify:
                QMessageBox.information(
                    self,
                    "Pocket Surface",
                    "Open a structure that contains a ligand, or select a ligand in the Manager.",
                )
            self._pocket_surface_payload = None
            self.viewer.set_pocket_surface({"active": False})
            return False
        if not residue_sels:
            if notify:
                QMessageBox.information(
                    self,
                    "Pocket Surface",
                    "No protein residues are within 4.5 Å of the ligand.",
                )
            self._pocket_surface_payload = None
            self.viewer.set_pocket_surface({"active": False})
            return False
        surface = {
            "active": True,
            "residueSels": residue_sels,
            **self._pocket_surface_style(),
        }
        if surface.get("colorScheme") == "hydrophobicity":
            from ..protein.surface_color import hydrophobicity_residue_colors

            surface["residueColors"] = hydrophobicity_residue_colors()
        self._pocket_surface_payload = surface
        self.viewer.set_pocket_surface(surface)
        self._mark_viewer_unsaved()
        return True

    def _pocket_surface_overlay_payload(self) -> dict | None:
        payload = self._pocket_surface_payload
        if payload is None or not payload.get("active"):
            return {"active": False}
        return payload

    def _refresh_pocket_surface(self) -> None:
        payload = self._pocket_surface_payload
        if payload is None or not payload.get("active"):
            return
        if self._activate_pocket_surface(notify=False):
            self._sync_pocket_surface_dialog()
            return
        self._hide_pocket_surface()

    def _refresh_pocket_overlays(self, *, zoom: bool = False) -> None:
        if self._pocket_payload_data is not None:
            self._refresh_pocket(zoom=zoom)
        self._refresh_pocket_surface()

    def _activate_pocket(self, *, zoom: bool) -> bool:
        payload = self._compute_pocket_payload()
        if payload is None:
            if zoom:
                QMessageBox.information(
                    self,
                    "Pocket",
                    "Open a structure that contains a ligand, or select a ligand in the Manager.",
                )
            return False
        self._pocket_payload_data = payload
        self.viewer.set_pocket(payload)
        if zoom:
            sels = payload.get("zoomSels") or []
            if sels:
                self.viewer.zoom_to_selections(sels)
        return True

    def _refresh_pocket(self, *, zoom: bool) -> None:
        if self._pocket_payload_data is None:
            return
        if self._activate_pocket(zoom=zoom):
            return
        self._pocket_payload_data = None
        self.viewer.set_pocket({"active": False})

    def _docking_box_overlay_payload(self) -> dict | None:
        payload = self._docking_box_payload
        if not payload:
            return None
        act = getattr(self, "_act_docking_box", None)
        if act is not None and not act.isChecked():
            return {"active": False}
        return payload

    def _on_docking_box_toggled(self, checked: bool) -> None:
        if checked and not self._docking_box_payload:
            return
        self.viewer.set_docking_box(self._docking_box_overlay_payload())

    def set_docking_box_from_prepare(self, result) -> None:
        """Show the Gnina box from a Prepare run and enable Render → Docking Box."""
        box = getattr(result, "box", None)
        if box is None:
            return
        payload = box.viewer_payload()
        self._docking_box_payload = payload
        act = getattr(self, "_act_docking_box", None)
        if act is not None:
            act.blockSignals(True)
            act.setChecked(True)
            act.blockSignals(False)
        self.viewer.set_docking_box(payload)
        self._mark_viewer_unsaved()

    def _dock_pose_overlay_payload(self) -> dict | None:
        payload = getattr(self, "_dock_pose_payload", None)
        if not payload:
            return None
        return payload

    def set_dock_pose(self, mol, *, zoom: bool = False, caption: str = "") -> bool:
        """Overlay a docked pose in the pocket without adding a Manager slot."""
        from .dock_complex_viewer import ligand_display_payload

        if mol is None:
            self.clear_dock_pose()
            return False
        b64, fmt = ligand_display_payload(mol)
        if not b64:
            return False
        live = {"active": True, "data": b64, "fmt": fmt or "sdf", "zoom": bool(zoom)}
        stored = dict(live)
        stored["zoom"] = False
        from rdkit import Chem

        try:
            self._dock_pose_mol = Chem.Mol(mol)
        except Exception:
            self._dock_pose_mol = mol
        self._dock_pose_payload = stored
        self.viewer.set_dock_pose(live)
        if caption:
            self._set_atom_status(caption)
        on_changed = getattr(self, "_on_dock_pose_changed", None)
        if callable(on_changed):
            on_changed()
        return True

    def clear_dock_pose(self) -> None:
        """Remove the transient dock-pose overlay from the 3D canvas."""
        self._dock_pose_mol = None
        self._dock_pose_payload = None
        invalidate = getattr(self, "_invalidate_dock_pose_overlay", None)
        if callable(invalidate):
            invalidate()
        self.viewer.set_dock_pose({"active": False})
        if self._interaction_overlay_active():
            self._push_hbonds()

    def _compute_pocket_payload(self) -> dict | None:
        selected_ligands = [r for r in self._rows if r.selected and r.spec.kind == "ligand"]
        if selected_ligands:
            sid = selected_ligands[0].spec.structure_id
            slot = next((s for s in self._slots if s.structure_id == sid), None)
            lig_rows = [r for r in selected_ligands if r.spec.structure_id == sid]
        else:
            slot = self._active_slot()
            lig_rows = [r for r in (slot.rows if slot else []) if r.spec.kind == "ligand"]
        if slot is None or not lig_rows:
            return None
        model = None
        for row in lig_rows:
            model = (row.spec.selection or {}).get("model")
            if model is not None:
                break
        keys = [(r.spec.chain, r.spec.resn, r.spec.resi, r.spec.icode) for r in lig_rows]
        plan = pocket_view_plan(slot.text, slot.fmt, ligand_keys=keys, model=model)
        if plan is None:
            return None
        polar_b64 = ""
        if plan.polar_h_pdb:
            polar_b64 = base64.b64encode(plan.polar_h_pdb.encode("utf-8")).decode("ascii")
        return {
            "active": True,
            "ligandSels": list(plan.ligand_sels),
            "residueSels": list(plan.residue_sels),
            "zoomSels": list(plan.ligand_sels),
            "polarHPdb": polar_b64,
        }

    def delete_selected_chains(self) -> None:
        if self.manager.selected_items_are_groups_only():
            for gid in self.manager.selected_user_group_ids():
                self._on_delete_group(gid)
            return
        ids = self._selected_component_ids()
        if not ids:
            return
        labels = [r.spec.label for r in self._rows if r.spec.component_id in set(ids)]
        preview = ", ".join(labels[:6])
        if len(labels) > 6:
            preview += "…"
        n = len(ids)
        msg = f"Delete {n} selected chain{'s' if n != 1 else ''} from the viewer?"
        if preview:
            msg += f"\n\n{preview}"
        if (
            QMessageBox.question(
                self, "Delete chains", msg, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
            )
            != QMessageBox.Yes
        ):
            return
        before = copy_loaded_slots(self._slots)
        drop = set(ids)
        kept: list[_LoadedSlot] = []
        dropped_sids: list[str] = []
        for slot in self._slots:
            rows = [r for r in slot.rows if r.spec.component_id not in drop]
            if rows:
                slot.rows = rows
                kept.append(slot)
            else:
                dropped_sids.append(slot.structure_id)
        self._slots = kept
        self._reindex_models()
        drop_overlays = getattr(self, "_drop_overlay_structures", None)
        if callable(drop_overlays) and dropped_sids:
            drop_overlays(dropped_sids)
        self._push_manager_delete_undo(before, copy_loaded_slots(self._slots))
        if not self._slots:
            self.close_structure(keep_edit_history=True)
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        if dropped_sids:
            invalidate = getattr(self, "_invalidate_hbonds", None)
            if callable(invalidate):
                invalidate()
        schedule = getattr(self, "_schedule_canvas_structure_push", None)
        if callable(schedule):
            schedule(refit=False)
        else:
            self._push_structure(refit=False)
            self._refresh_pocket_overlays(zoom=False)
        self._mark_viewer_unsaved()

    def _clear_manager_delete_history(self) -> None:
        self._manager_delete_undo = []
        self._manager_delete_redo = []
        self._sync_manager_edit_actions()

    def _sync_manager_edit_actions(self) -> None:
        undo = getattr(self, "_act_undo", None)
        redo = getattr(self, "_act_redo", None)
        if undo is not None:
            undo.setEnabled(bool(self._manager_delete_undo))
        if redo is not None:
            redo.setEnabled(bool(self._manager_delete_redo))

    def _push_manager_delete_undo(
        self,
        before: list[_LoadedSlot],
        after: list[_LoadedSlot],
    ) -> None:
        self._manager_delete_undo.append((before, after))
        if len(self._manager_delete_undo) > _MANAGER_DELETE_UNDO_LIMIT:
            self._manager_delete_undo = self._manager_delete_undo[-_MANAGER_DELETE_UNDO_LIMIT:]
        self._manager_delete_redo = []
        self._sync_manager_edit_actions()

    def _restore_manager_slots(self, slots: list[_LoadedSlot]) -> None:
        self._slots = copy_loaded_slots(slots)
        self._reindex_models()
        self._residue_highlight = []
        self._set_atom_status("")
        skip = getattr(self, "_overlay_skip_sids", None)
        if callable(skip):
            skip().difference_update(slot.structure_id for slot in self._slots)
        invalidate = getattr(self, "_invalidate_hbonds", None)
        if callable(invalidate):
            invalidate()
        if not self._slots:
            self.close_structure(keep_edit_history=True)
            return
        self._refresh_manager()
        self._refresh_sequence_chains()
        self._push_structure(refit=False)
        self._refresh_pocket_overlays(zoom=False)
        self._mark_viewer_unsaved()
        sync_edit = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync_edit):
            sync_edit()

    def undo_manager_delete(self) -> None:
        if not self._manager_delete_undo:
            return
        before, after = self._manager_delete_undo.pop()
        self._manager_delete_redo.append((before, after))
        self._restore_manager_slots(before)
        self._sync_manager_edit_actions()

    def redo_manager_delete(self) -> None:
        if not self._manager_delete_redo:
            return
        before, after = self._manager_delete_redo.pop()
        self._manager_delete_undo.append((before, after))
        self._restore_manager_slots(after)
        self._sync_manager_edit_actions()

    def focus_selected(self) -> None:
        ids = self._require_selection()
        if ids:
            self.viewer.zoom_to_components(ids)

    def clear_selection(self) -> None:
        """Deselect Manager rows and drop the 3D atom/residue highlight."""
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.selected:
                    new_rows.append(replace(row, selected=False))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        self._syncing_from_atom = True
        try:
            self.manager.apply_row_states(self._rows)
            clearer = getattr(self.manager, "clear_component_selection", None)
            if callable(clearer):
                clearer()
            self._set_residue_highlight([])
            self._set_atom_status("")
        finally:
            self._syncing_from_atom = False
        sync_edit = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync_edit):
            sync_edit()
        if changed:
            self._push_states()

    def invert_selection(self) -> None:
        """Select unselected Manager components and deselect the current selection."""
        selected = {row.spec.component_id for row in self._rows if row.selected}
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                now = row.spec.component_id not in selected
                if row.selected != now:
                    new_rows.append(replace(row, selected=now))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        self._syncing_from_atom = True
        try:
            self.manager.apply_row_states(self._rows)
            if self._residue_highlight:
                self._set_residue_highlight([])
                self._set_atom_status("")
        finally:
            self._syncing_from_atom = False
        sync_edit = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync_edit):
            sync_edit()
        if changed:
            self._push_states()

    def _on_visibility_changed(self, component_id: str, visible: bool) -> None:
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id == component_id and row.visible != visible:
                    new_rows.append(replace(row, visible=visible))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if changed:
            self.manager.apply_row_states(self._rows)
            self._push_states()

    def _on_manager_selection(self, ids: list) -> None:
        want = set(ids)
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                selected = row.spec.component_id in want
                if row.selected != selected:
                    new_rows.append(replace(row, selected=selected))
                    changed = True
                else:
                    new_rows.append(row)
            slot.rows = new_rows
        if not self._syncing_from_atom and self._residue_highlight:
            self._residue_highlight = []
            self.viewer.set_residue_highlight([])
            self._set_atom_status("")
        if changed:
            self._push_states()

    def _on_style_requested(self, style: str) -> None:
        allowed = {key for key, _label in COMPONENT_STYLE_CHOICES}
        if style not in allowed:
            return
        ids = set(self._require_selection())
        if not ids:
            return
        changed = False
        for slot in self._slots:
            new_rows = []
            for row in slot.rows:
                if row.spec.component_id in ids:
                    if not self._style_allowed_for_kind(row.spec.kind, style):
                        new_rows.append(row)
                        continue
                    if row.style != style:
                        new_rows.append(replace(row, style=style))
                        changed = True
                        continue
                new_rows.append(row)
            slot.rows = new_rows
        self._clear_pocket_overlay()
        if changed:
            self._push_states()
            self._sync_render_menus_from_rows()

    def _set_atom_status(self, text: str) -> None:
        lbl = getattr(self, "_atom_status", None)
        if lbl is None:
            return
        lbl.setText(text or "")

    def _atom_status_text(self, data: dict) -> str:
        chain = str(data.get("chain") or "").strip()
        resn = str(data.get("resn") or "").strip()
        resi = data.get("resi")
        resi_s = str(resi).strip() if resi is not None and str(resi).strip() != "" else ""
        icode = str(data.get("icode") or "").strip()
        atom = str(data.get("atom") or "").strip()
        elem = str(data.get("elem") or "").strip()
        serial = data.get("serial")
        alt = str(data.get("altLoc") or data.get("altloc") or "").strip()
        loc = f"{chain}:" if chain else ""
        loc += " ".join(part for part in (resn, resi_s + icode) if part)
        bits = [part for part in (loc.strip(), atom) if part]
        if elem and elem.upper() != atom.upper():
            bits.append(elem)
        if alt and alt not in {"", " ", "A"}:
            bits.append(f"alt {alt}")
        try:
            if serial is not None and str(serial).strip() != "":
                bits.append(f"#{int(serial)}")
        except (TypeError, ValueError):
            if serial not in (None, ""):
                bits.append(f"#{serial}")
        return "  ".join(bits)

    def _on_atom_picked(self, payload: str) -> None:
        try:
            data = json.loads(payload or "{}")
        except json.JSONDecodeError:
            return
        hook = getattr(self, "_on_pharmacophore_atom_picked", None)
        if callable(hook):
            hook(data)
        model = data.get("model")
        try:
            model_i = int(model) if model is not None and str(model).strip() != "" else None
        except (TypeError, ValueError):
            model_i = None
        cid = component_id_for_atom(
            (r.spec for r in self._rows),
            chain=str(data.get("chain") or ""),
            resn=str(data.get("resn") or ""),
            resi=data.get("resi"),
            icode=str(data.get("icode") or ""),
            model=model_i,
        )
        if not cid:
            return
        spec = next((r.spec for r in self._rows if r.spec.component_id == cid), None)
        icode = str(data.get("icode") or "")
        double_click = bool(data.get("doubleClick"))
        kind = spec.kind if spec is not None else ""
        whole_ligand = double_click and kind == "ligand"
        whole_residue = double_click and kind == "polymer"
        if whole_ligand:
            sel = dict(spec.selection or {})
            if not sel:
                sel = {
                    "chain": str(data.get("chain") or ""),
                    "resi": data.get("resi"),
                }
                if icode:
                    sel["icode"] = icode
                if spec.resn:
                    sel["resn"] = spec.resn
            if model_i is not None and "model" not in sel:
                sel["model"] = model_i
        elif whole_residue:
            sel = {
                "chain": str(data.get("chain") or ""),
                "resi": data.get("resi"),
            }
            if icode:
                sel["icode"] = icode
            if model_i is not None:
                sel["model"] = model_i
            try:
                sel["resi"] = int(str(sel["resi"]).strip())
            except (TypeError, ValueError):
                sel["resi"] = str(sel.get("resi") or "")
        else:
            sel = {
                "chain": str(data.get("chain") or ""),
                "resi": data.get("resi"),
            }
            if icode:
                sel["icode"] = icode
            atom = str(data.get("atom") or "").strip()
            if atom:
                sel["atom"] = atom
            serial = data.get("serial")
            try:
                if serial is not None and str(serial).strip() != "":
                    sel["serial"] = int(serial)
            except (TypeError, ValueError):
                pass
            if model_i is not None:
                sel["model"] = model_i
            try:
                sel["resi"] = int(str(sel["resi"]).strip())
            except (TypeError, ValueError):
                sel["resi"] = str(sel.get("resi") or "")
        sel["resn"] = str(data.get("resn") or sel.get("resn") or "")
        sel["kind"] = kind
        sel["component_id"] = cid
        if spec is not None:
            sel["structure_id"] = spec.structure_id
        highlights = [sel]
        merger = getattr(self, "_merge_structure_edit_pick", None)
        if callable(merger) and not whole_ligand and not whole_residue:
            highlights = merger(sel) or [sel]
        if whole_ligand and spec is not None and len(highlights) == 1:
            status = spec.label
        elif whole_residue and len(highlights) == 1:
            residue_data = {
                "chain": data.get("chain"),
                "resn": data.get("resn"),
                "resi": data.get("resi"),
                "icode": data.get("icode"),
            }
            status = self._atom_status_text(residue_data)
        elif len(highlights) > 1:
            status_fn = getattr(self, "_structure_edit_status_text", None)
            status = (
                status_fn(highlights)
                if callable(status_fn)
                else "  —  ".join(self._atom_status_text(item) for item in highlights)
            )
        else:
            status = self._atom_status_text(data)
        self._syncing_from_atom = True
        try:
            for slot in self._slots:
                slot.rows = [
                    replace(row, selected=row.spec.component_id == cid) for row in slot.rows
                ]
            self.manager.apply_row_states(self._rows)
            self._set_residue_highlight(highlights)
            self._set_atom_status(status)
            self._push_states()
        finally:
            self._syncing_from_atom = False
        sync_edit = getattr(self, "_sync_structure_edit_actions", None)
        if callable(sync_edit):
            sync_edit()
        dlg = self._sequence_dialog
        if dlg is not None and not qobject_is_deleted(dlg):
            hit = polymer_residue_for_atom(
                self._sequence_chains,
                chain=str(data.get("chain") or ""),
                resi=data.get("resi"),
                icode=icode,
                structure_id=spec.structure_id if spec is not None else "",
            )
            if hit is not None:
                dlg.select_residue(hit.chain, hit.resi, hit.icode, structure_id=hit.structure_id)
