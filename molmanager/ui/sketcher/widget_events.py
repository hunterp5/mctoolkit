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

"""Mouse, keyboard, and shortcut input for :class:`~molmanager.ui.sketcher.widget.SketchWidget`."""

from __future__ import annotations

import math
from typing import Any

from PyQt5.QtCore import QPoint, QRect, Qt
from PyQt5.QtWidgets import QAction, QMenu, QMessageBox, QWidget

from .bonds import BOND_STEREO_PLAIN, _bond_make, _bond_unpack
from .constants import DEFAULT_WILDCARD_ELEMENTS, SKETCH_MEDIAN_BOND_PX, WILDCARD_ELEMENT
from .sketch_grid import snap_to_hex_grid
from .rgroups import rgroup_label_from_element
from .sketch_reactions import snap_arrow_end
from .wildcards import _is_wildcard_node


class SketchWidgetEventsMixin:
    """Qt event handlers forwarded onto ``SketchWidget``.

    Unhandled input calls ``QWidget`` directly. ``super()`` would look up the
    host that binds these methods, not the sketch widget.
    """

    def _release_marquee_mouse_grab_if_any(self) -> None:
        if QWidget.mouseGrabber() is self:
            self.releaseMouse()

    def mousePressEvent(self, ev):
        wpt = ev.pos()
        pt = self._widget_point_to_model(wpt)
        if ev.button() == Qt.MiddleButton or (ev.button() == Qt.LeftButton and self._space_pan):
            self._panning = True
            self._pan_last = QPoint(wpt)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ev.button() == Qt.LeftButton and self.chain_mode:
            hit = self._hit_node(pt)
            self._chain_anchor = int(hit["id"]) if hit is not None else None
            self._chain_press = QPoint(pt)
            self._chain_preview = self.preview_carbon_chain(
                self._chain_anchor, self._chain_press, pt
            )
            self._mouse_down_pos = QPoint(wpt)
            self.setCursor(Qt.CrossCursor)
            self.update()
            return
        if ev.button() == Qt.LeftButton:
            hit = self._hit_node(pt)
            self._mouse_down_pos = QPoint(wpt)

            if self.text_mode:
                self._drag_candidate = hit["id"] if hit is not None else None
                self._drag_start = None
                self._is_dragging = False
                self.update()
                return

            if self.reaction_arrow_mode:
                self._arrow_dragging = True
                self._arrow_drag_start = QPoint(pt)
                self._arrow_drag_pos = QPoint(pt)
                self.selected_reaction_arrow = False
                self.setCursor(Qt.CrossCursor)
                self.update()
                return

            if self.select_mode:
                if self.hit_rotate_handle(wpt):
                    self.begin_selection_rotate(pt)
                    self.setCursor(Qt.CrossCursor)
                    self.update()
                    return
                shift = bool(ev.modifiers() & Qt.ShiftModifier)
                if hit is not None:
                    if shift:
                        now_on = self._toggle_atom_in_selection(hit["id"])
                        if now_on:
                            self._maybe_move = True
                            self._move_start_pos = QPoint(pt)
                        else:
                            self._maybe_move = False
                            self._move_start_pos = None
                    elif hit["id"] not in self.selected_nodes:
                        self.selected_nodes = [hit["id"]]
                        self._sync_selected_bonds_from_nodes()
                        self._maybe_move = True
                        self._move_start_pos = QPoint(pt)
                    else:
                        self._sync_selected_bonds_from_nodes()
                        self._maybe_move = True
                        self._move_start_pos = QPoint(pt)
                else:
                    bi_m, _ = self._hit_bond(pt)
                    if bi_m is not None and bi_m in self.selected_bond_indices and not shift:
                        self._maybe_move = True
                        self._move_start_pos = QPoint(pt)
                        self._selecting = False
                        self._select_start = None
                        self.update()
                        return
                    if bi_m is not None:
                        a0, b0, _, __ = _bond_unpack(self.bonds[bi_m])
                        s0 = self._selected_node_set()
                        if shift:
                            now_on = self._toggle_bond_in_selection(bi_m)
                            if now_on:
                                self._maybe_move = True
                                self._move_start_pos = QPoint(pt)
                            else:
                                self._maybe_move = False
                                self._move_start_pos = None
                            self._selecting = False
                            self._select_start = None
                            self.update()
                            return
                        if a0 in s0 and b0 in s0:
                            self._maybe_move = True
                            self._move_start_pos = QPoint(pt)
                            self._selecting = False
                            self._select_start = None
                            self.update()
                            return
                        # Click an unselected bond: select that bond (replace).
                        self._replace_selection_with_bond(bi_m)
                        self._maybe_move = True
                        self._move_start_pos = QPoint(pt)
                        self._selecting = False
                        self._select_start = None
                        self.update()
                        return
                    if self._hit_reaction_arrow(pt) and not shift:
                        self.selected_nodes = []
                        self.selected_bond_indices = set()
                        self.selected_reaction_arrow = True
                        self._maybe_move = True
                        self._move_start_pos = QPoint(pt)
                        self._arrow_move_orig = self._arrow_copy(self.reaction_arrow)
                        self._selecting = False
                        self._select_start = None
                        self.update()
                        return
                    if shift:
                        self._select_additive_base_nodes = list(self.selected_nodes)
                        self._select_additive_base_bonds = set(self.selected_bond_indices)
                    else:
                        self.selected_nodes = []
                        self.selected_bond_indices = set()
                        self.selected_reaction_arrow = False
                        self._select_additive_base_nodes = None
                        self._select_additive_base_bonds = None
                    self._maybe_move = False
                    self._move_start_pos = None
                    self._moving = False
                    self._move_orig = {}
                    self._selecting = True
                    self._select_start = QPoint(wpt)
                    self._selection_rect = None
                    if getattr(self, "select_tool", "box") == "lasso":
                        self._lasso_points = [QPoint(wpt)]
                    else:
                        self._lasso_points = []
                    self.grabMouse()
                self.update()
                return

            if hit is not None and not self.erase_mode:
                self._drag_candidate = hit["id"]
            else:
                self._drag_candidate = None

            # Click on bond applies the active bond tool (order / stereo / dative / wavy).
            # A ring template uses that same click to fuse onto the bond.
            if (
                isinstance(self.hover, tuple)
                and self.hover[0] == "bond"
                and not self.erase_mode
                and not self.active_template
            ):
                bi = self.hover[1]
                changed = self._apply_active_bond_tool(bi)
                self._mouse_down_pos = None
                self._drag_candidate = None
                self._suppress_click = True
                if changed:
                    try:
                        self._refresh_hover_from_cursor()
                    except Exception:
                        pass
                    self._after_sketch_edit()
                return

            if self.erase_mode:
                if hit is not None:
                    node = next((n for n in self.nodes if n["id"] == hit["id"]), None)
                    conn = [
                        b
                        for b in self.bonds
                        if _bond_unpack(b)[0] == hit["id"] or _bond_unpack(b)[1] == hit["id"]
                    ]
                    self._push_undo("del_node", (node, conn))
                    self._delete_node(hit["id"])
                    self._suppress_click = True
                    return
                bi, _ = self._hit_bond(pt)
                if bi is not None:
                    b = self.bonds.pop(bi)
                    self._push_undo("del_bond", b)
                    self._after_sketch_edit()
                    return
                if self._hit_reaction_arrow(pt):
                    self._set_reaction_arrow(None)
                    self._suppress_click = True
                    return
                self._after_sketch_edit()
                return

        elif ev.button() == Qt.RightButton:
            if self._hit_reaction_arrow(pt) and self._hit_node(pt) is None:
                menu = QMenu(self)
                act_text = QAction("Edit reaction text…", self)
                act_text.triggered.connect(self._open_reaction_text_dialog)
                menu.addAction(act_text)
                menu.exec_(self.mapToGlobal(wpt))
                self.update()
                return
            hit = self._hit_node(pt)
            if hit:
                menu = QMenu(self)
                self._add_copy_paste_menu_actions(menu, paste_anchor=pt)
                act_edit = QAction("Edit Atom...", self)
                act_edit.triggered.connect(lambda ch, h=hit: self._open_edit_atom_dialog(h))
                menu.addAction(act_edit)
                act_fc = QAction("Edit Formal Charge…", self)
                act_fc.setToolTip(
                    "Set the atom’s integer formal charge (e.g. +2 on sulfur, −1 on oxygen)."
                )
                act_fc.triggered.connect(lambda ch, h=hit: self._open_edit_formal_charge_dialog(h))
                menu.addAction(act_fc)
                act_h_atom = QAction("Implicit Hydrogens", self)
                act_h_atom.setCheckable(True)
                act_h_atom.setEnabled(not _is_wildcard_node(hit))
                hid = hit["id"]
                act_h_atom.setChecked(self.atom_has_explicit_hydrogen_neighbors(hid))
                act_h_atom.setToolTip(
                    "Toggle explicit H atoms on this atom (RDKit AddHs / remove neighbor hydrogens)."
                )

                def _do_h_atom(checked=False, atom_id=hid):
                    if checked:
                        ok, msg = self.add_explicit_hydrogens_on_atom(atom_id)
                    else:
                        ok, msg = self.remove_explicit_hydrogens_on_atom(atom_id)
                    dlg = self._sketcher_dialog_if()
                    parent_w = dlg if dlg is not None else self
                    if not ok:
                        QMessageBox.information(parent_w, "Implicit Hydrogens", msg)
                    elif dlg is not None:
                        dlg._update_sketch_status()

                act_h_atom.triggered.connect(_do_h_atom)
                menu.addAction(act_h_atom)
                if hit.get("element") == "C" and not _is_wildcard_node(hit):
                    act_xc = QAction("Explicit Carbon", self)
                    act_xc.setCheckable(True)
                    act_xc.setChecked(bool(hit.get("explicit_carbon")))
                    act_xc.setToolTip(
                        "Show a C label for this carbon instead of the usual skeletal (unlabeled) drawing."
                    )
                    act_xc.toggled.connect(
                        lambda on, h=hit["id"]: self._set_explicit_carbon_visible(h, on)
                    )
                    menu.addAction(act_xc)
                if not _is_wildcard_node(hit):
                    act_lp = QAction("Lone Pairs", self)
                    act_lp.setCheckable(True)
                    act_lp.setChecked(bool(hit.get("show_lone_pairs")))
                    act_lp.setToolTip("Show Lewis lone pairs on this atom only.")
                    act_lp.toggled.connect(
                        lambda on, h=hit["id"]: self._set_atom_lone_pairs_visible(h, on)
                    )
                    menu.addAction(act_lp)
                    act_ox = QAction("Oxidation State", self)
                    act_ox.setCheckable(True)
                    act_ox.setChecked(bool(hit.get("show_oxidation_state")))
                    act_ox.setToolTip("Show the approximate oxidation state on this atom only.")
                    act_ox.toggled.connect(
                        lambda on, h=hit["id"]: self._set_atom_oxidation_visible(h, on)
                    )
                    menu.addAction(act_ox)
                if _is_wildcard_node(hit):
                    act_ed = QAction("Edit wildcard elements...", self)
                    act_ed.triggered.connect(lambda ch, h=hit: self._edit_wildcard_dialog(h))
                    menu.addAction(act_ed)
                menu.addSeparator()
                act_st = QAction("Show Stereochemistry", self)
                act_st.setCheckable(True)
                _hid = hit["id"]
                act_st.setChecked(_hid in self._stereo_label_node_ids)
                act_st.toggled.connect(lambda on, h=_hid: self._set_stereo_label_visible(h, on))
                menu.addAction(act_st)
                self._add_selection_transform_actions(menu, hit_ids={hit["id"]})
                self._add_cleanup_selected_action(menu, hit_ids={hit["id"]})
                self._add_copy_selected_smiles_action(menu, hit_ids={hit["id"]})
                self._add_group_action_if_applicable(menu)
                menu.exec_(self.mapToGlobal(pt))
            else:
                bi, _ = self._hit_bond(pt)
                if bi is not None:
                    a_idx, b_idx, order, st = _bond_unpack(self.bonds[bi])
                    menu = QMenu(self)
                    self._add_copy_paste_menu_actions(menu, paste_anchor=pt)

                    set_menu = menu.addMenu("Set order")
                    for o in [1, 2, 3]:
                        act_o = QAction(str(o), self)

                        def _seto(ch, val=o, bi_m=bi, ao=a_idx, bo=b_idx):
                            _, _, cur_o, cur_s = _bond_unpack(self.bonds[bi_m])
                            if val == cur_o:
                                return
                            new_st = cur_s if val == 1 else 0
                            self.bonds[bi_m] = _bond_make(ao, bo, val, new_st)
                            self._push_undo("chg_bond", (ao, bo, (cur_o, cur_s), (val, new_st)))
                            try:
                                self._refresh_hover_from_cursor()
                            except Exception:
                                pass
                            self._after_sketch_edit()

                        act_o.triggered.connect(_seto)
                        set_menu.addAction(act_o)

                    stereo_menu = menu.addMenu("Bond type (single-bond styles)")
                    for label, sval in [
                        ("Plain", 0),
                        ("Wedge (narrow at first atom)", 1),
                        ("Hash / dashed wedge", 2),
                        ("Wavy (unspecified stereo)", 3),
                        ("Dative (dashed)", 4),
                    ]:
                        sa = QAction(label, self)

                        def _set_st(ch, sv=sval, bi_m=bi, ao=a_idx, bo=b_idx):
                            _, _, o0, s0 = _bond_unpack(self.bonds[bi_m])
                            if o0 != 1 and sv != 0:
                                return
                            if sv == s0 and o0 == 1:
                                return
                            order_set = 1
                            self.bonds[bi_m] = _bond_make(ao, bo, order_set, sv)
                            self._push_undo("chg_bond", (ao, bo, (o0, s0), (order_set, sv)))
                            self._after_sketch_edit()

                        sa.triggered.connect(_set_st)
                        stereo_menu.addAction(sa)

                    self._add_selection_transform_actions(menu, hit_ids={a_idx, b_idx})
                    self._add_cleanup_selected_action(menu, hit_ids={a_idx, b_idx})
                    self._add_group_action_if_applicable(menu)
                    menu.exec_(self.mapToGlobal(pt))
                else:
                    dlg = self._sketcher_dialog_if()
                    if dlg is not None:
                        dlg.show_sketch_canvas_menu(self.mapToGlobal(wpt))
        self.update()

    def mouseDoubleClickEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return QWidget.mouseDoubleClickEvent(self, ev)
        pt = self._widget_point_to_model(ev.pos())
        if self._hit_reaction_arrow(pt) and self._hit_node(pt) is None:
            self._open_reaction_text_dialog()
            ev.accept()
            return
        hit = self._hit_node(pt)
        bi, _bd = self._hit_bond(pt)
        if hit is None and bi is None:
            return QWidget.mouseDoubleClickEvent(self, ev)
        if not self.nodes:
            return QWidget.mouseDoubleClickEvent(self, ev)
        seed: int | None = None
        if hit is not None:
            seed = hit["id"]
        elif bi is not None and 0 <= bi < len(self.bonds):
            a, b, _, __ = _bond_unpack(self.bonds[bi])
            seed = a
        if seed is None:
            return QWidget.mouseDoubleClickEvent(self, ev)
        comp: set[int] | None = None
        for c in self.connected_components():
            if seed in c:
                comp = c
                break
        if not comp:
            return QWidget.mouseDoubleClickEvent(self, ev)
        self._activate_select_mode_from_parent()
        self.selected_nodes = sorted(comp)
        self._sync_selected_bonds_from_nodes()
        self._selection_rect = None
        self._selecting = False
        self._lasso_points = []
        self._maybe_move = False
        self._moving = False
        self._move_orig = {}
        self._move_start_pos = None
        self._release_marquee_mouse_grab_if_any()
        ev.accept()
        self._after_sketch_edit()

    def mouseMoveEvent(self, ev):
        wpt = ev.pos()
        pt = self._widget_point_to_model(wpt)

        if self._panning and self._pan_last is not None:
            self.pan_by_widget_delta(wpt.x() - self._pan_last.x(), wpt.y() - self._pan_last.y())
            self._pan_last = QPoint(wpt)
            self.setCursor(Qt.ClosedHandCursor)
            return

        if self.chain_mode and self._chain_press is not None:
            self._chain_preview = self.preview_carbon_chain(
                self._chain_anchor, self._chain_press, pt
            )
            self.setCursor(Qt.CrossCursor)
            self.update()
            return

        if self._rotating:
            self.update_selection_rotate(pt)
            self.setCursor(Qt.CrossCursor)
            return

        if self._arrow_dragging and self._arrow_drag_start is not None:
            snap = bool(ev.modifiers() & Qt.ShiftModifier)
            x1, y1 = snap_arrow_end(
                float(self._arrow_drag_start.x()),
                float(self._arrow_drag_start.y()),
                float(pt.x()),
                float(pt.y()),
                snap=snap,
            )
            self._arrow_drag_pos = QPoint(int(round(x1)), int(round(y1)))
            self.setCursor(Qt.CrossCursor)
            self.update()
            return

        if self.select_mode:
            if self._moving and self._move_start_pos is not None:
                dx = pt.x() - self._move_start_pos.x()
                dy = pt.y() - self._move_start_pos.y()
                dx, dy = self._clamp_selection_delta(dx, dy)
                for nid, orig in list(self._move_orig.items()):
                    n = next((x for x in self.nodes if x["id"] == nid), None)
                    if n:
                        n["pos"] = QPoint(int(orig.x() + dx), int(orig.y() + dy))
                if self.selected_reaction_arrow and self._arrow_move_orig is not None:
                    oa, ob = self._arrow_move_orig
                    self.reaction_arrow = (
                        QPoint(int(oa.x() + dx), int(oa.y() + dy)),
                        QPoint(int(ob.x() + dx), int(ob.y() + dy)),
                    )
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
                return
            if self._selecting and self._select_start is not None:
                if getattr(self, "select_tool", "box") == "lasso":
                    pts = getattr(self, "_lasso_points", None)
                    if pts is None:
                        self._lasso_points = [QPoint(self._select_start), QPoint(wpt)]
                    else:
                        last = pts[-1]
                        dx = wpt.x() - last.x()
                        dy = wpt.y() - last.y()
                        if dx * dx + dy * dy >= 4:
                            pts.append(QPoint(wpt))
                    self._selection_rect = None
                    self._apply_lasso_selection_from_points()
                    self.update()
                    return
                sx, sy = self._select_start.x(), self._select_start.y()
                minx, maxx = min(sx, wpt.x()), max(sx, wpt.x())
                miny, maxy = min(sy, wpt.y()), max(sy, wpt.y())
                self._selection_rect = QRect(minx, miny, maxx - minx, maxy - miny)
                model_rect = self._widget_rect_to_model(self._selection_rect)
                rect_nodes = [
                    n["id"]
                    for n in self.nodes
                    if (
                        model_rect.left() <= n["pos"].x() <= model_rect.right()
                        and model_rect.top() <= n["pos"].y() <= model_rect.bottom()
                    )
                ]
                base_nodes = self._select_additive_base_nodes
                base_bonds = self._select_additive_base_bonds
                if base_nodes is not None and base_bonds is not None:
                    seen = set(base_nodes)
                    self.selected_nodes = list(base_nodes) + [
                        nid for nid in rect_nodes if nid not in seen
                    ]
                    self._sync_selected_bonds_from_marquee_rect(model_rect)
                    self.selected_bond_indices = set(base_bonds) | set(self.selected_bond_indices)
                else:
                    self.selected_nodes = rect_nodes
                    self._sync_selected_bonds_from_marquee_rect(model_rect)
                self.update()
                return
            if self._maybe_move and self._move_start_pos is not None:
                dx = pt.x() - self._move_start_pos.x()
                dy = pt.y() - self._move_start_pos.y()
                if dx * dx + dy * dy >= (6**2):
                    self._moving = True
                    self._maybe_move = False
                    move_ids = self._atoms_for_selection_move()
                    self._move_orig = {
                        n["id"]: QPoint(n["pos"].x(), n["pos"].y())
                        for n in self.nodes
                        if n["id"] in move_ids
                    }
                    if self.selected_reaction_arrow and self.reaction_arrow is not None:
                        self._arrow_move_orig = self._arrow_copy(self.reaction_arrow)
                    self.setCursor(Qt.ClosedHandCursor)
                    self.update()
                    return

        if (
            self._drag_candidate is not None
            and not self._is_dragging
            and self._mouse_down_pos is not None
        ):
            if not self.text_mode:
                dx = wpt.x() - self._mouse_down_pos.x()
                dy = wpt.y() - self._mouse_down_pos.y()
                if dx * dx + dy * dy >= (6**2):
                    self._is_dragging = True
                    self._drag_start = self._drag_candidate
                    self._drag_pos = QPoint(pt)
                    self.setCursor(Qt.ClosedHandCursor)

        if self._is_dragging:
            self._drag_pos = QPoint(pt)
            hit = self._hit_node(pt)
            self.hover = hit["id"] if hit else None
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            return

        hit = self._hit_node(pt)
        bi, _ = self._hit_bond(pt)
        sel = self._selected_node_set()
        if self.text_mode:
            if hit:
                self.hover = hit["id"]
                self.setCursor(Qt.IBeamCursor)
            else:
                self.hover = None
                self.setCursor(Qt.IBeamCursor)
        elif self.select_mode:
            if hit and hit["id"] in sel:
                self.hover = hit["id"]
                self.setCursor(Qt.OpenHandCursor)
            elif bi is not None and bi in self.selected_bond_indices:
                self.hover = ("bond", bi)
                self.setCursor(Qt.OpenHandCursor)
            elif hit:
                self.hover = hit["id"]
                self.setCursor(Qt.PointingHandCursor)
            elif bi is not None:
                self.hover = ("bond", bi)
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.hover = None
                self.setCursor(Qt.ArrowCursor)
        elif hit:
            self.hover = hit["id"]
            self.setCursor(Qt.PointingHandCursor)
        else:
            if bi is not None:
                self.hover = ("bond", bi)
                self.setCursor(Qt.PointingHandCursor)
            elif self._hit_reaction_arrow(pt):
                self.hover = ("arrow", 0)
                self.setCursor(Qt.PointingHandCursor)
            else:
                self.hover = None
                if (
                    self.erase_mode
                    or self.reaction_arrow_mode
                    or self.chain_mode
                    or self._carbon_chain_cursor_active()
                ):
                    self.setCursor(Qt.CrossCursor)
                else:
                    self.setCursor(Qt.ArrowCursor)
        self.update()

    def mouseReleaseEvent(self, ev):
        if self._panning and ev.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._panning = False
            self._pan_last = None
            return
        if self._rotating and ev.button() == Qt.LeftButton:
            self.end_selection_rotate()
            return
        if getattr(self, "armed_abbrev", None) and ev.button() == Qt.LeftButton:
            self._apply_armed_abbrev(self._widget_point_to_model(ev.pos()))
            self._mouse_down_pos = None
            self._drag_candidate = None
            self._is_dragging = False
            self._drag_start = None
            self.update()
            return
        if self.chain_mode and ev.button() == Qt.LeftButton and self._chain_press is not None:
            end_pt = self._widget_point_to_model(ev.pos())
            anchor = self._chain_anchor
            press = self._chain_press
            self._chain_anchor = None
            self._chain_press = None
            self._chain_preview = []
            self._mouse_down_pos = None
            self.finish_carbon_chain(anchor, press, end_pt)
            self.update()
            return
        if ev.button() != Qt.LeftButton:
            return

        if self.text_mode:
            nid = self._drag_candidate
            self._drag_candidate = None
            self._mouse_down_pos = None
            if nid is not None:
                hit = next((n for n in self.nodes if n["id"] == nid), None)
                if hit is not None:
                    self._open_edit_atom_dialog(hit)
            try:
                self._refresh_hover_from_cursor()
            except Exception:
                self.setCursor(Qt.IBeamCursor)
            self.update()
            return

        if self._arrow_dragging:
            end_pt = self._widget_point_to_model(ev.pos())
            self._commit_arrow_drag(end_pt, snap=bool(ev.modifiers() & Qt.ShiftModifier))
            self._mouse_down_pos = None
            try:
                self._refresh_hover_from_cursor()
            except Exception:
                self.setCursor(Qt.CrossCursor)
            return

        if self.select_mode:
            if self._moving:
                moves = []
                for nid, old_pos in self._move_orig.items():
                    n = next((x for x in self.nodes if x["id"] == nid), None)
                    if n:
                        new_pos = QPoint(n["pos"].x(), n["pos"].y())
                        if old_pos.x() != new_pos.x() or old_pos.y() != new_pos.y():
                            moves.append((nid, old_pos, new_pos))
                if moves:
                    self._push_undo("move_nodes", moves)
                    moved = len(moves)
                    noun = "atom" if moved == 1 else "atoms"
                    self._report_status(f"Moved {moved} {noun}.")
                if self._arrow_move_orig is not None and self.reaction_arrow is not None:
                    old = self._arrow_move_orig
                    new = self._arrow_copy(self.reaction_arrow)
                    if new is not None and (old[0] != new[0] or old[1] != new[1]):
                        self._push_undo("set_arrow", (old, new))
                self._arrow_move_orig = None
                self._moving = False
                self._move_start_pos = None
                self._move_orig = {}
                try:
                    self._refresh_hover_from_cursor()
                except Exception:
                    self.setCursor(Qt.ArrowCursor)
                self.update()
                return
            self._announce_selection()
            if self._selecting:
                self._selecting = False
                self._select_start = None
                self._selection_rect = None
                self._lasso_points = []
                self._select_additive_base_nodes = None
                self._select_additive_base_bonds = None
                self._release_marquee_mouse_grab_if_any()
                try:
                    self._refresh_hover_from_cursor()
                except Exception:
                    self.setCursor(Qt.ArrowCursor)
                self.update()
                return
            if self._maybe_move:
                self._maybe_move = False
                self._move_start_pos = None
                try:
                    self._refresh_hover_from_cursor()
                except Exception:
                    self.setCursor(Qt.ArrowCursor)
                self.update()
                return

        if self._suppress_click and not self._is_dragging:
            self._suppress_click = False
            self._mouse_down_pos = None
            self._drag_candidate = None
            return

        if self._is_dragging:
            self._is_dragging = False
            self.setCursor(Qt.ArrowCursor)
            end_pt = self._widget_point_to_model(ev.pos())
            start_id = self._drag_start
            self._drag_start = None
            self._drag_pos = None
            self._drag_candidate = None
            self._mouse_down_pos = None

            hit = self._hit_node(end_pt)
            if hit and start_id is not None and hit["id"] != start_id:
                a, b = start_id, hit["id"]
                found = None
                for bi, bo in enumerate(self.bonds):
                    ba, bb, _, __ = _bond_unpack(bo)
                    if (ba == a and bb == b) or (ba == b and bb == a):
                        found = bi
                        break
                if found is None:
                    order, st = self._bond_tool_order_stereo()
                    bond = _bond_make(a, b, order, st)
                    self.bonds.append(bond)
                    self._push_undo("add_bond", bond)
                    self._after_sketch_edit()
                else:
                    if self._apply_active_bond_tool(found):
                        try:
                            self._refresh_hover_from_cursor()
                        except Exception:
                            pass
                        self._after_sketch_edit()
            else:
                if start_id is not None:
                    base = next((n for n in self.nodes if n["id"] == start_id), None)
                    if base is None:
                        return
                    bx, by = base["pos"].x(), base["pos"].y()
                    ex0, ey0 = float(end_pt.x()), float(end_pt.y())
                    dx = ex0 - bx
                    dy = ey0 - by
                    dist = math.hypot(dx, dy)
                    do_snap = bool(getattr(self, "snap_geometry", True)) and not (
                        ev.modifiers() & Qt.ShiftModifier
                    )
                    med = float(
                        getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX
                    )
                    order, pst = self._bond_tool_order_stereo()
                    # Place the new atom at the drop point so bond length and angle match the drag.
                    if dist < 1e-6:
                        ix, iy = self._compute_extension_vector(
                            start_id, snap=do_snap, new_bond_order=order
                        )
                        ex = int(round(bx + ix * med))
                        ey = int(round(by + iy * med))
                    elif do_snap:
                        ang = math.atan2(dy, dx)
                        neigh_angs = []
                        neigh_orders = []
                        for bond in self.bonds:
                            a0, b0, o0, __ = _bond_unpack(bond)
                            if a0 != start_id and b0 != start_id:
                                continue
                            oid = b0 if a0 == start_id else a0
                            on = next((n for n in self.nodes if n["id"] == oid), None)
                            if on:
                                neigh_angs.append(
                                    math.atan2(on["pos"].y() - by, on["pos"].x() - bx)
                                )
                                neigh_orders.append(int(o0))
                        max_exist = max(neigh_orders) if neigh_orders else 1
                        prefer_linear = (
                            max_exist >= 3 or order >= 3 or (max_exist == 2 and order == 2)
                        )
                        if prefer_linear and len(neigh_angs) == 1:
                            ang = neigh_angs[0] + math.pi
                        ang = snap_to_hex_grid(ang)
                        ex = int(round(bx + math.cos(ang) * med))
                        ey = int(round(by + math.sin(ang) * med))
                    else:
                        ex = int(round(ex0))
                        ey = int(round(ey0))
                    pel = self.place_element if self.place_element is not None else "C"
                    if rgroup_label_from_element(pel) is not None:
                        order, pst = 1, BOND_STEREO_PLAIN
                    nid = self.next_id
                    self.next_id += 1
                    node: dict[str, Any] = {"id": nid, "pos": QPoint(ex, ey), "element": pel}
                    if pel == WILDCARD_ELEMENT:
                        node["wildcard_els"] = list(DEFAULT_WILDCARD_ELEMENTS)
                    self.nodes.append(node)
                    from .bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE

                    if order == 1 and pst in (BOND_STEREO_WEDGE, BOND_STEREO_HASH):
                        bond = _bond_make(start_id, nid, order, pst)
                    else:
                        bond = _bond_make(start_id, nid, order, pst)
                    self.bonds.append(bond)
                    self._push_undo("add_bonded_node", (node, bond))
                    self._after_sketch_edit()
            return

        end_pt = self._widget_point_to_model(ev.pos())

        # charge placement
        if self.active_charge and self._drag_candidate is not None:
            nid = self._drag_candidate
            n = next((x for x in self.nodes if x["id"] == nid), None)
            if n is not None:
                old = int(n.get("charge", 0) or 0)
                n["charge"] = int(self.active_charge)
                self._push_undo("chg_charge", (nid, old, int(n["charge"])))
                self._after_sketch_edit()
            try:
                p = self._sketcher_dialog_if()
                if p and hasattr(p, "charge_plus"):
                    p.charge_plus.setChecked(False)
                if p and hasattr(p, "charge_minus"):
                    p.charge_minus.setChecked(False)
            except Exception:
                pass
            self.active_charge = None
            self._drag_candidate = None
            self._mouse_down_pos = None
            return

        # template placement (active_template stays set until another tool/mode is chosen)
        if self.active_template:
            tpl = self.active_template
            if self._drag_candidate is not None:
                self.place_template(tpl, attach_to=self._drag_candidate)
            else:
                bi, _ = self._hit_bond(end_pt)
                if bi is not None:
                    self.place_template(tpl, fuse_bond=bi)
                else:
                    self.place_template(tpl, center=end_pt)
            self._drag_candidate = None
            self._mouse_down_pos = None
            return

        if self._drag_candidate is not None:
            base_id = self._drag_candidate
            tgt = next((n for n in self.nodes if n["id"] == base_id), None)
            if tgt is not None and rgroup_label_from_element(self.place_element) is not None:
                self.place_rgroup_on(base_id, self.place_element)
            elif tgt is not None and self.place_element == "C":
                is_plain_carbon = (
                    tgt.get("element") == "C"
                    and not _is_wildcard_node(tgt)
                    and not tgt.get("abbrev")
                )
                if is_plain_carbon:
                    self.add_carbon_to(base_id)
                    node = self.nodes[-1]
                    bond = next(
                        (
                            b
                            for b in self.bonds
                            if (b[0] == base_id and b[1] == node["id"])
                            or (b[1] == base_id and b[0] == node["id"])
                        ),
                        None,
                    )
                    if bond is not None:
                        self._push_undo("add_bonded_node", (node, bond))
                    else:
                        self._push_undo("add_node", node)
                    self._after_sketch_edit()
                else:
                    self._mutate_atom_element(tgt, "C", None)
            elif tgt is not None and self.place_element is not None:
                wels = (
                    list(DEFAULT_WILDCARD_ELEMENTS)
                    if self.place_element == WILDCARD_ELEMENT
                    else None
                )
                self._mutate_atom_element(tgt, self.place_element, wels)
        else:
            ex, ey = end_pt.x(), end_pt.y()
            if self.place_element is None:
                self._drag_candidate = None
                self._mouse_down_pos = None
                return
            nid = self.next_id
            self.next_id += 1
            node: dict[str, Any] = {"id": nid, "pos": QPoint(ex, ey), "element": self.place_element}
            if self.place_element == WILDCARD_ELEMENT:
                node["wildcard_els"] = list(DEFAULT_WILDCARD_ELEMENTS)
            self.nodes.append(node)
            self._push_undo("add_node", node)
            self._after_sketch_edit()

        self._drag_candidate = None
        self._mouse_down_pos = None

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space_pan = True
            ev.accept()
            return
        if ev.key() in (Qt.Key_1, Qt.Key_2, Qt.Key_3) and not (
            ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        ):
            order = int(ev.key() - Qt.Key_0)
            dialog = self._sketcher_dialog_if()
            if dialog is not None and hasattr(dialog, "_on_bond_tool"):
                dialog._on_bond_tool(order, BOND_STEREO_PLAIN)
            else:
                self.active_bond_order = order
                self.active_bond_stereo = BOND_STEREO_PLAIN
            ev.accept()
            return
        arrows = {
            Qt.Key_Left: (-4, 0),
            Qt.Key_Right: (4, 0),
            Qt.Key_Up: (0, -4),
            Qt.Key_Down: (0, 4),
        }
        if ev.key() in arrows and not (
            ev.modifiers() & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier)
        ):
            step = 16 if ev.modifiers() & Qt.ShiftModifier else 4
            dx, dy = arrows[ev.key()]
            if self.nudge_selection(dx // 4 * step, dy // 4 * step):
                ev.accept()
                return
        if ev.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            if self._sketcher_dialog_if() is None:
                if self._handle_delete_key():
                    ev.accept()
                    return

        try:
            if isinstance(self.hover, int):
                k = ev.key()
                mods = ev.modifiers()
                if mods & Qt.ShiftModifier:
                    if k == Qt.Key_C:
                        self._set_atom(
                            "Cl", next((n for n in self.nodes if n["id"] == self.hover), None)
                        )
                        return
                    if k == Qt.Key_B:
                        self._set_atom(
                            "Br", next((n for n in self.nodes if n["id"] == self.hover), None)
                        )
                        return
                key_char = None
                if Qt.Key_A <= k <= Qt.Key_Z:
                    key_char = chr(k)
                if key_char:
                    el = key_char.upper()
                    if el in ["C", "N", "O", "S", "P", "F", "I", "H"]:
                        self._set_atom(
                            el, next((n for n in self.nodes if n["id"] == self.hover), None)
                        )
                        return
        except Exception:
            pass

        QWidget.keyPressEvent(self, ev)

    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Space and not ev.isAutoRepeat():
            self._space_pan = False
            ev.accept()
            return
        QWidget.keyReleaseEvent(self, ev)

    def wheelEvent(self, ev):
        delta = ev.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1.0 / 1.15
        self.zoom_about_widget_point(factor, ev.pos())
        ev.accept()

    def focusOutEvent(self, ev):
        self._space_pan = False
        QWidget.focusOutEvent(self, ev)
