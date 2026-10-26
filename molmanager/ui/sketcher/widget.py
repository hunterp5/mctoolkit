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

from __future__ import annotations

import json
import math
from typing import TYPE_CHECKING, Any

from PyQt5.QtCore import QLineF, QPoint, QPointF, QRect, Qt, pyqtSignal
from PyQt5.QtGui import (
    QCursor,
    QPainter,
)

if TYPE_CHECKING:
    from PyQt5.QtGui import QPainterPath
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QInputDialog,
    QLineEdit,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from rdkit import Chem

from .alkene_stereo import infer_alkene_ez_for_sketch_mol
from .bonds import (
    BOND_STEREO_HASH,
    BOND_STEREO_PLAIN,
    BOND_STEREO_VALUES,
    BOND_STEREO_WAVY,
    BOND_STEREO_WEDGE,
    _bond_make,
    _bond_record_ok,
    _bond_unpack,
    sanitize_sketch_stereo_bonds,
)
from .contracted_labels import contracted_max_bonds, parse_edit_atom_input
from .iupac_rings import (
    exterior_ring_substituent_direction,
    fusion_ring_offsets_for_bond,
    ring_circumradius_for_bond_length,
    ring_vertex_offsets_y_up,
    rotate_offsets_to_inward_heteroatoms,
    spiro_second_ring_offsets_y_up,
)
from .iupac_validate import format_iupac_issues, validate_iupac_sketch
from .sketch_grid import chain_points, snap_to_hex_grid
from .sketch_graph import connected_components_from_graph, topology_fingerprint
from .sketch_rdkit import SketchWidgetRdkitMixin
from .constants import (
    CLIPBOARD_PREFIX,
    DEFAULT_WILDCARD_ELEMENTS,
    SKETCH_MEDIAN_BOND_PX,
    SKETCH_RING_TEMPLATES,
    WILDCARD_ELEMENT,
    WILDCARD_ELEMENT_CHOICES,
)
from .sketch_reactions import (
    MIN_REACTION_ARROW_LENGTH,
    fragment_side,
    join_reaction_string,
    plus_sign_positions,
    snap_arrow_end,
)
from .rgroups import is_rgroup_node, rgroup_element, rgroup_label_from_element
from .wildcards import (
    WildcardElementsDialog,
    _is_wildcard_node,
    _normalize_wildcard_elements,
)
from .widget_painting import SketchWidgetPaintMixin
from .widget_events import SketchWidgetEventsMixin


def _count_label(count: int, singular: str) -> str:
    """``1 atom`` or ``2 atoms``."""
    noun = singular if count == 1 else f"{singular}s"
    return f"{count} {noun}"


class SketchWidget(
    SketchWidgetEventsMixin, SketchWidgetPaintMixin, SketchWidgetRdkitMixin, QWidget
):
    """
    Chemical sketch widget: place atoms, draw bonds by dragging, adjust bond order,
    erase, select/move, templates, undo/redo, and export SMILES via RDKit.

    Stereo model: wedge/hash on **single** bonds only (narrow tip = stereocenter atom in the bond tuple);
    alkene **E/Z** from 2D layout via ``alkene_stereo``. Not a full tautomer/atropisomer engine—see
    ``docs/STEREO_AND_ISOMERISM.md``.

    Bonds: stored **order** 1/2/3 only; aromatic mol loads may appear as order 1 lines. Valence UI sums
    bond orders vs RDKit-based caps—see ``docs/VALENCE_BONDS_AND_AROMATICITY.md``.
    """

    sketchChanged = pyqtSignal()
    statusMessage = pyqtSignal(str)

    def _sketcher_dialog_if(self):
        """Nearest ``SketcherDialog`` ancestor (canvas may sit under a splitter)."""
        from .dialog import SketcherDialog

        w = self.parent()
        while w is not None:
            if isinstance(w, SketcherDialog):
                return w
            w = w.parent()
        return None

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setMinimumSize(500, 400)

        self.nodes: list[
            dict[str, Any]
        ] = []  # {'id': int, 'pos': QPoint, 'element': str, 'charge'?: int}
        self.bonds: list[tuple[int, int, int, int]] = []  # (a_id, b_id, order, stereo)
        # stereo: 0 plain, 1 wedge, 2 hash, 3 wavy, 4 dative (order 1 only for 1–4)
        self.next_id = 0
        self.sel: int | None = None

        # placement / modes
        self.place_element: str | None = None
        self.erase_mode = False
        self.select_mode = False
        self.select_tool = "box"  # "box" | "lasso" while select_mode is on
        self.text_mode = False
        self.chain_mode = False
        self.reaction_arrow_mode = False
        self.reaction_arrow: tuple[QPoint, QPoint] | None = None
        self.reaction_above: str = ""
        self.reaction_below: str = ""
        self.selected_reaction_arrow = False
        self.armed_abbrev: str | None = None
        self._arrow_dragging = False
        self._arrow_drag_start: QPoint | None = None
        self._arrow_drag_pos: QPoint | None = None
        self._arrow_move_orig: tuple[QPoint, QPoint] | None = None
        self.active_template: str | None = None
        self.active_charge: int | None = None  # +1, -1, or None
        self.active_bond_order: int = 1  # 1/2/3 for newly drawn or applied bonds
        self.active_bond_stereo: int = 0  # 0 plain, 1 wedge, 2 hash, 3 wavy, 4 dative (single only)
        self.show_lone_pairs: bool = False  # View → Show Lone Pairs

        # hover & interaction state
        self.hover: int | tuple[str, int] | None = None  # node id, or ('bond', bond_index)
        self.selected_nodes: list[int] = []
        self.selected_bond_indices: set[int] = set()
        self._last_selection_status: tuple[tuple[int, ...], tuple[int, ...], bool] = ((), (), False)
        self._selecting = False
        self._select_start: QPoint | None = None
        self._selection_rect: QRect | None = None
        self._lasso_points: list[QPoint] = []
        # When Shift+marquee: keep prior selection and union with the drag rect.
        self._select_additive_base_nodes: list[int] | None = None
        self._select_additive_base_bonds: set[int] | None = None
        self._moving = False
        self._move_start_pos: QPoint | None = None
        self._move_orig: dict[int, QPoint] = {}

        self._is_dragging = False
        self._drag_start: int | None = None
        self._drag_pos: QPoint | None = None
        self._drag_candidate: int | None = None
        self._mouse_down_pos: QPoint | None = None
        self._maybe_move = False
        self._suppress_click = False
        self._chain_anchor: int | None = None
        self._chain_press: QPoint | None = None
        self._chain_preview: list[QPoint] = []
        self._rotating = False
        self._rotate_orig: dict[int, QPoint] = {}
        self._rotate_cen: tuple[float, float] | None = None
        self._rotate_start = 0.0
        self._panning = False
        self._pan_last: QPoint | None = None
        self._space_pan = False

        self._angle_signs: dict[int, int] = {}
        self._undo: list[tuple[str, Any]] = []
        self._redo: list[tuple[str, Any]] = []

        self.radius = 14
        self._median_bond_length_px = float(SKETCH_MEDIAN_BOND_PX)
        self._view_scale = 1.0
        self._view_pan = QPointF(0.0, 0.0)
        self._last_structure_paint = ""
        self._rdkit_sketch_paint_cache_key = None
        self._rdkit_sketch_paint_cache = None
        self._valence_violations: set[int] = set()
        self._charge_violations: set[int] = set()

        # User "Group": fixed union of fragments → one SMILES entry (dot-separated) until sketch changes or Ungroup.
        # True salt (cation + anion fragments) uses ion ordering; otherwise fragments are only co-grouped, not as a salt.
        self._salt_bundle_smiles: str | None = None
        self._salt_bundle_nodes: frozenset[int] | None = (
            None  # node ids in the grouped fragments only
        )
        self._salt_bundle_fragment_count: int | None = None
        self._group_bundle_is_salt: bool = False

        self._chiral_center_ids: set[int] = set()
        self._chiral_stereo_issue_ids: set[int] = set()
        self._stereo_cip_by_node_id: dict[int, str] = {}
        self._alkene_ez_by_bond_index: dict[int, str] = {}
        self._stereo_label_node_ids: set[int] = set()
        self._iupac_issue_atom_ids: set[int] = set()
        self._iupac_issue_bond_indices: set[int] = set()
        self._iupac_issues_summary: str = ""
        self.snap_geometry: bool = True  # Shift bypasses while drawing

        self._ccache_fp: tuple[tuple[int, ...], tuple[tuple[int, int], ...]] | None = None
        self._ccache_comps: tuple[frozenset[int], ...] = ()

        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    def _carbon_chain_cursor_active(self) -> bool:
        """Carbon tool uses crosshair over empty canvas (chain / replace-on-click)."""
        return (
            self.place_element == "C"
            and not self.select_mode
            and not self.erase_mode
            and not self.text_mode
            and not self.reaction_arrow_mode
            and self.active_template is None
        )

    def _notify_sketch_changed(self) -> None:
        self.sketchChanged.emit()

    def _report_status(self, message: str) -> None:
        """Send one line to the sketcher status bar."""
        text = (message or "").strip()
        if text:
            self.statusMessage.emit(text)

    def _selection_fingerprint(self) -> tuple[tuple[int, ...], tuple[int, ...], bool]:
        return (
            tuple(int(i) for i in self.selected_nodes),
            tuple(sorted(int(i) for i in self.selected_bond_indices)),
            bool(self.selected_reaction_arrow),
        )

    def _remember_selection(self) -> None:
        self._last_selection_status = self._selection_fingerprint()

    def _announce_selection(self) -> None:
        """Report a selection change once, after a click or marquee finishes."""
        key = self._selection_fingerprint()
        if key == self._last_selection_status:
            return
        self._last_selection_status = key
        atoms, bonds, arrow = key
        parts: list[str] = []
        if atoms:
            parts.append(_count_label(len(atoms), "atom"))
        if bonds:
            parts.append(_count_label(len(bonds), "bond"))
        if arrow:
            parts.append("the reaction arrow")
        if not parts:
            self._report_status("Selection cleared.")
            return
        if len(parts) == 1:
            detail = parts[0]
        elif len(parts) == 2:
            detail = f"{parts[0]} and {parts[1]}"
        else:
            detail = f"{parts[0]}, {parts[1]}, and {parts[2]}"
        self._report_status(f"Selected {detail}.")

    @staticmethod
    def _deleted_status(atoms: int, bonds: int, arrow: bool) -> str:
        parts: list[str] = []
        if atoms:
            parts.append(_count_label(atoms, "atom"))
        if bonds:
            parts.append(_count_label(bonds, "bond"))
        if arrow:
            parts.append("the reaction arrow")
        if not parts:
            return "Nothing to delete."
        if len(parts) == 1:
            detail = parts[0]
        elif len(parts) == 2:
            detail = f"{parts[0]} and {parts[1]}"
        else:
            detail = f"{parts[0]}, {parts[1]}, and {parts[2]}"
        return f"Deleted {detail}."

    def _clear_salt_bundle(self) -> None:
        self._salt_bundle_smiles = None
        self._salt_bundle_nodes = None
        self._salt_bundle_fragment_count = None
        self._group_bundle_is_salt = False

    def _salt_invalidate_if_stale(self) -> None:
        if self._salt_bundle_nodes is None:
            return
        U = self._salt_bundle_nodes
        cur = frozenset(n["id"] for n in self.nodes)
        if not U <= cur:
            self._clear_salt_bundle()
            return
        comps_u = [c for c in self.connected_components() if c & U]
        if (
            self._salt_bundle_fragment_count is not None
            and len(comps_u) != self._salt_bundle_fragment_count
        ):
            self._clear_salt_bundle()

    def _selected_node_set(self) -> set[int]:
        return set(self.selected_nodes)

    def _sync_selected_bonds_from_nodes(self) -> None:
        """Bonds whose both endpoints are in the current node selection (click / replace selection)."""
        s = self._selected_node_set()
        self.selected_bond_indices = {
            bi
            for bi, bond in enumerate(self.bonds)
            if _bond_unpack(bond)[0] in s and _bond_unpack(bond)[1] in s
        }

    def _union_bonds_for_selected_nodes(self) -> None:
        """Add bonds with both endpoints selected; keep any already-selected bonds."""
        s = self._selected_node_set()
        extra = {
            bi
            for bi, bond in enumerate(self.bonds)
            if _bond_unpack(bond)[0] in s and _bond_unpack(bond)[1] in s
        }
        self.selected_bond_indices = set(self.selected_bond_indices) | extra

    def _toggle_atom_in_selection(self, nid: int) -> bool:
        """Shift-click atom: add if absent, remove if present. Returns True if now selected."""
        if nid in self.selected_nodes:
            self.selected_nodes = [x for x in self.selected_nodes if x != nid]
            return False
        self.selected_nodes = list(self.selected_nodes) + [nid]
        self._union_bonds_for_selected_nodes()
        return True

    def _toggle_bond_in_selection(self, bi: int) -> bool:
        """
        Shift-click bond: add/remove that bond only (does not select endpoints).

        Returns True if the bond is selected after the toggle.
        """
        if not (0 <= bi < len(self.bonds)):
            return False
        buds = set(self.selected_bond_indices)
        if bi in buds:
            buds.discard(bi)
            self.selected_bond_indices = buds
            return False
        buds.add(bi)
        self.selected_bond_indices = buds
        return True

    def _replace_selection_with_bond(self, bi: int) -> None:
        if not (0 <= bi < len(self.bonds)):
            return
        a, b, _, __ = _bond_unpack(self.bonds[bi])
        self.selected_nodes = [a, b]
        self.selected_bond_indices = {bi}

    @staticmethod
    def _segment_intersects_rect(x1: float, y1: float, x2: float, y2: float, rect: QRect) -> bool:
        """True if the segment crosses or lies inside the axis-aligned rectangle."""
        r = rect.normalized()
        if r.isEmpty():
            return False
        p1 = QPointF(x1, y1)
        p2 = QPointF(x2, y2)
        if r.contains(p1.toPoint()) or r.contains(p2.toPoint()):
            return True
        seg = QLineF(p1, p2)
        left, top, right, bottom = (
            float(r.left()),
            float(r.top()),
            float(r.right()),
            float(r.bottom()),
        )
        edges = (
            QLineF(left, top, right, top),
            QLineF(right, top, right, bottom),
            QLineF(right, bottom, left, bottom),
            QLineF(left, bottom, left, top),
        )
        for edge in edges:
            itype, _ = seg.intersects(edge)
            if itype == QLineF.BoundedIntersection:
                return True
        return False

    def _sync_selected_bonds_from_marquee_rect(self, rect: QRect | None) -> None:
        """Marquee: any bond whose segment intersects the selection rectangle."""
        if rect is None:
            self.selected_bond_indices = set()
            return
        r = rect.normalized()
        if r.width() <= 0 and r.height() <= 0:
            r = QRect(r.left(), r.top(), 1, 1)
        elif r.width() <= 0:
            r = QRect(r.left(), r.top(), 1, r.height())
        elif r.height() <= 0:
            r = QRect(r.left(), r.top(), r.width(), 1)
        buds: set[int] = set()
        for bi, bond in enumerate(self.bonds):
            a, b, _, __ = _bond_unpack(bond)
            na = next((n for n in self.nodes if n["id"] == a), None)
            nb = next((n for n in self.nodes if n["id"] == b), None)
            if not na or not nb:
                continue
            x1, y1 = float(na["pos"].x()), float(na["pos"].y())
            x2, y2 = float(nb["pos"].x()), float(nb["pos"].y())
            if self._segment_intersects_rect(x1, y1, x2, y2, r):
                buds.add(bi)
        self.selected_bond_indices = buds

    def _lasso_path_model(self) -> QPainterPath:
        from PyQt5.QtGui import QPainterPath

        path = QPainterPath()
        pts = getattr(self, "_lasso_points", None) or []
        if not pts:
            return path
        m0 = self._widget_point_to_model(pts[0])
        path.moveTo(float(m0.x()), float(m0.y()))
        for wp in pts[1:]:
            m = self._widget_point_to_model(wp)
            path.lineTo(float(m.x()), float(m.y()))
        if len(pts) >= 3:
            path.closeSubpath()
        return path

    def _sync_selected_bonds_from_lasso_path(self, path) -> None:
        """Lasso: bonds whose segment samples fall inside the freeform path."""
        from PyQt5.QtCore import QPointF

        if path is None or path.isEmpty():
            self.selected_bond_indices = set()
            return
        buds: set[int] = set()
        for bi, bond in enumerate(self.bonds):
            a, b, _, __ = _bond_unpack(bond)
            na = next((n for n in self.nodes if n["id"] == a), None)
            nb = next((n for n in self.nodes if n["id"] == b), None)
            if not na or not nb:
                continue
            x1, y1 = float(na["pos"].x()), float(na["pos"].y())
            x2, y2 = float(nb["pos"].x()), float(nb["pos"].y())
            hit = False
            for i in range(9):
                t = i / 8.0
                if path.contains(QPointF(x1 + (x2 - x1) * t, y1 + (y2 - y1) * t)):
                    hit = True
                    break
            if hit:
                buds.add(bi)
        self.selected_bond_indices = buds

    def _apply_lasso_selection_from_points(self) -> None:
        """Update atom/bond selection from the in-progress widget-space lasso polyline."""
        from PyQt5.QtCore import QPointF

        path = self._lasso_path_model()
        if len(getattr(self, "_lasso_points", []) or []) < 3 or path.isEmpty():
            rect_nodes: list[int] = []
            self.selected_bond_indices = set()
        else:
            rect_nodes = [
                n["id"]
                for n in self.nodes
                if path.contains(QPointF(float(n["pos"].x()), float(n["pos"].y())))
            ]
            self._sync_selected_bonds_from_lasso_path(path)
        base_nodes = self._select_additive_base_nodes
        base_bonds = self._select_additive_base_bonds
        if base_nodes is not None and base_bonds is not None:
            seen = set(base_nodes)
            self.selected_nodes = list(base_nodes) + [nid for nid in rect_nodes if nid not in seen]
            self.selected_bond_indices = set(base_bonds) | set(self.selected_bond_indices)
        else:
            self.selected_nodes = rect_nodes

    def _atoms_for_selection_move(self) -> set[int]:
        """Atoms to translate: explicitly selected plus endpoints of selected bonds."""
        s = self._selected_node_set()
        for bi in self.selected_bond_indices:
            if 0 <= bi < len(self.bonds):
                a, b, _, __ = _bond_unpack(self.bonds[bi])
                s.add(a)
                s.add(b)
        return s

    def _clamp_selection_delta(self, dx: int, dy: int) -> tuple[int, int]:
        """Keep all atoms in _move_orig inside the visible model viewport when moving as a group."""
        if not self._move_orig:
            return dx, dy
        m = int(self.radius) + 6
        min_x, max_x, min_y, max_y = self._model_viewport_bounds()
        lo_x = max(min_x + m - int(o.x()) for o in self._move_orig.values())
        hi_x = min(max_x - m - int(o.x()) for o in self._move_orig.values())
        lo_y = max(min_y + m - int(o.y()) for o in self._move_orig.values())
        hi_y = min(max_y - m - int(o.y()) for o in self._move_orig.values())
        if lo_x > hi_x:
            dx = int((lo_x + hi_x) / 2)
        else:
            dx = min(max(dx, lo_x), hi_x)
        if lo_y > hi_y:
            dy = int((lo_y + hi_y) / 2)
        else:
            dy = min(max(dy, lo_y), hi_y)
        return dx, dy

    def _delete_selected_atoms_and_bonds(self) -> None:
        """Remove selected bonds (only those still present), then selected atoms; clears selection."""
        if not self.select_mode or (
            not self.selected_nodes
            and not self.selected_bond_indices
            and not self.selected_reaction_arrow
        ):
            return
        removed_atoms = len(self.selected_nodes)
        removed_bonds = len(self.selected_bond_indices)
        removed_arrow = bool(self.selected_reaction_arrow)
        for bi in sorted(self.selected_bond_indices, reverse=True):
            if 0 <= bi < len(self.bonds):
                b = self.bonds.pop(bi)
                self._push_undo("del_bond", b)
        for nid in list(self.selected_nodes):
            node = next((n for n in self.nodes if n["id"] == nid), None)
            if node is None:
                continue
            conn = [b for b in self.bonds if b[0] == nid or b[1] == nid]
            self._push_undo("del_node", (node, conn))
            self._delete_node(nid)
        self.selected_nodes = []
        self.selected_bond_indices = set()
        if self.selected_reaction_arrow:
            self._set_reaction_arrow(None)
            self.selected_reaction_arrow = False
        self.hover = None
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)
        self._report_status(self._deleted_status(removed_atoms, removed_bonds, removed_arrow))
        self._remember_selection()

    def _try_delete_hover_target(self, *, refresh_hover: bool = True) -> bool:
        """Delete the atom or bond under the cursor, if any."""
        if refresh_hover:
            try:
                local = self.mapFromGlobal(QCursor.pos())
                if self.rect().contains(local):
                    self._refresh_hover_from_cursor()
            except Exception:
                pass
        if isinstance(self.hover, int):
            nid = int(self.hover)
            node = next((n for n in self.nodes if n["id"] == nid), None)
            if node is None:
                return False
            conn = [b for b in self.bonds if b[0] == nid or b[1] == nid]
            self._push_undo("del_node", (node, conn))
            self._delete_node(nid)
            self.hover = None
            self._report_status("Deleted 1 atom.")
            self._remember_selection()
            return True
        if isinstance(self.hover, tuple) and self.hover[0] == "bond":
            try:
                bi = int(self.hover[1])
            except (TypeError, ValueError):
                return False
            if 0 <= bi < len(self.bonds):
                b = self.bonds.pop(bi)
                self._push_undo("del_bond", b)
                self.hover = None
                self._after_sketch_edit(notify=True, notify_if_valence_failed=True)
                self._report_status("Deleted 1 bond.")
                self._remember_selection()
                return True
        if isinstance(self.hover, tuple) and self.hover[0] == "arrow":
            if self.reaction_arrow is not None:
                self._set_reaction_arrow(None)
                self.hover = None
                self._report_status("Deleted the reaction arrow.")
                self._remember_selection()
                return True
        return False

    def _handle_delete_key(self) -> bool:
        """Delete hover target first, else selection fallback. Returns True when handled."""
        if self._try_delete_hover_target():
            return True
        if self.select_mode and (
            self.selected_nodes or self.selected_bond_indices or self.selected_reaction_arrow
        ):
            self._delete_selected_atoms_and_bonds()
            return True
        if self.sel is not None:
            node = next((n for n in self.nodes if n["id"] == self.sel), None)
            if node is not None:
                conn = [b for b in self.bonds if b[0] == self.sel or b[1] == self.sel]
                self._push_undo("del_node", (node, conn))
            self._delete_node(self.sel)
            self._report_status("Deleted 1 atom.")
            self._remember_selection()
            return True
        return False

    @staticmethod
    def _formal_charge(node: dict[str, Any]) -> int:
        ch = node.get("charge", 0)
        if ch is None:
            return 0
        try:
            return int(ch)
        except (TypeError, ValueError):
            return 0

    def connected_components(self) -> list[set[int]]:
        """Heavy-atom connectivity via bonds. Each isolated atom is its own component."""
        fp = topology_fingerprint(self.nodes, self.bonds)
        if fp != self._ccache_fp:
            self._ccache_fp = fp
            raw = connected_components_from_graph(self.nodes, self.bonds)
            self._ccache_comps = tuple(frozenset(c) for c in raw)
        return [set(c) for c in self._ccache_comps]

    def fragment_count(self) -> int:
        return len(self.connected_components())

    def _max_bond_order_sum(self, element: str, fc: int) -> int:
        """
        Allowed sum of bond orders to neighboring heavy atoms before implicit H.
        Charge-aware so e.g. N+, O-, quaternary ammonium do not spuriously trip validation.
        """
        if fc == 1:
            if element == "N":
                return 4
            if element == "O":
                return 3
            if element in ("S", "P"):
                return 5
        if fc == -1:
            if element == "O":
                return 1
            if element == "N":
                return 2
        base = self._max_valence(element)
        if fc > 0:
            return max(1, base - fc)
        if fc < 0:
            return max(1, base + fc)
        return base

    def _max_bond_order_sum_for_node(self, n: dict[str, Any], fc: int) -> int:
        ab_cap = contracted_max_bonds(n.get("abbrev"))
        if ab_cap is not None:
            return int(ab_cap)
        if is_rgroup_node(n):
            return 1
        if _is_wildcard_node(n):
            els = _normalize_wildcard_elements(n)
            return max(self._max_bond_order_sum(el, fc) for el in els)
        return self._max_bond_order_sum(n["element"], fc)

    def sketch_has_wildcards(self) -> bool:
        return any(_is_wildcard_node(n) for n in self.nodes)

    # ---------- View transform (zoom scales drawing proportionally) ----------
    def _view_center(self) -> QPointF:
        return QPointF(self.rect().center())

    def _widget_point_to_model(self, pt: QPoint) -> QPoint:
        """Map widget pixels to sketch model coordinates (inverse of paint-time view scale)."""
        c = self._view_center()
        s = float(self._view_scale)
        pan = self._view_pan
        if abs(s) < 1e-9:
            return QPoint(pt)
        return QPoint(
            int(round((pt.x() - c.x() - pan.x()) / s + c.x())),
            int(round((pt.y() - c.y() - pan.y()) / s + c.y())),
        )

    def _model_point_to_widget(self, pt: QPoint) -> QPoint:
        """Map sketch model coordinates to widget pixels."""
        c = self._view_center()
        s = float(self._view_scale)
        pan = self._view_pan
        return QPoint(
            int(round(c.x() + pan.x() + (float(pt.x()) - c.x()) * s)),
            int(round(c.y() + pan.y() + (float(pt.y()) - c.y()) * s)),
        )

    def _widget_rect_to_model(self, rect: QRect) -> QRect:
        p1 = self._widget_point_to_model(rect.topLeft())
        p2 = self._widget_point_to_model(rect.bottomRight())
        left, right = min(p1.x(), p2.x()), max(p1.x(), p2.x())
        top, bottom = min(p1.y(), p2.y()), max(p1.y(), p2.y())
        return QRect(
            QPoint(left, top), QPoint(max(right, left + 1), max(bottom, top + 1))
        ).normalized()

    def _model_viewport_bounds(self) -> tuple[int, int, int, int]:
        """Model-space axis-aligned bounds visible in the widget."""
        r = self.rect()
        corners = [
            self._widget_point_to_model(r.topLeft()),
            self._widget_point_to_model(r.topRight()),
            self._widget_point_to_model(r.bottomLeft()),
            self._widget_point_to_model(r.bottomRight()),
        ]
        return (
            min(p.x() for p in corners),
            max(p.x() for p in corners),
            min(p.y() for p in corners),
            max(p.y() for p in corners),
        )

    def _apply_view_transform(self, p: QPainter) -> None:
        c = self._view_center()
        pan = self._view_pan
        p.translate(c.x() + pan.x(), c.y() + pan.y())
        p.scale(self._view_scale, self._view_scale)
        p.translate(-c.x(), -c.y())

    def _refresh_sketch_draw_metrics(self) -> None:
        """Sync line weights / hit radius to the current model-space median bond length."""
        mb = self._median_bond_length_sketch_px()
        if mb is not None and mb > 0:
            self._median_bond_length_px = mb
        else:
            self._median_bond_length_px = float(SKETCH_MEDIAN_BOND_PX)
        ratio = self._median_bond_length_px / float(SKETCH_MEDIAN_BOND_PX)
        self.radius = max(10, int(round(14 * ratio)))

    # ---------- Geometry / hits ----------
    def _hit_node(self, pt: QPoint):
        for n in self.nodes:
            d2 = (n["pos"].x() - pt.x()) ** 2 + (n["pos"].y() - pt.y()) ** 2
            if d2 <= (self.radius * 1.5) ** 2:
                return n
        return None

    def _point_to_segment_distance_sq(self, px, py, x1, y1, x2, y2):
        vx, vy = x2 - x1, y2 - y1
        wx, wy = px - x1, py - y1
        c1 = vx * wx + vy * wy
        if c1 <= 0:
            dx, dy = px - x1, py - y1
            return dx * dx + dy * dy
        c2 = vx * vx + vy * vy
        if c2 <= c1:
            dx, dy = px - x2, py - y2
            return dx * dx + dy * dy
        b = c1 / c2
        bx, by = x1 + b * vx, y1 + b * vy
        dx, dy = px - bx, py - by
        return dx * dx + dy * dy

    def _hit_bond(self, pt: QPoint):
        best_i, best_d = None, None
        px, py = pt.x(), pt.y()
        for bi, bond in enumerate(self.bonds):
            a, b, order, _ = _bond_unpack(bond)
            ni = next((n for n in self.nodes if n["id"] == a), None)
            nj = next((n for n in self.nodes if n["id"] == b), None)
            if not ni or not nj:
                continue
            d2 = self._point_to_segment_distance_sq(
                px, py, ni["pos"].x(), ni["pos"].y(), nj["pos"].x(), nj["pos"].y()
            )
            if best_d is None or d2 < best_d:
                best_d, best_i = d2, bi
        hit_slop = max(8.0, self._median_bond_length_px * 0.2)
        if best_d is not None and best_d <= hit_slop * hit_slop:
            return best_i, best_d
        return None, None

    def _arrow_copy(self, arrow: tuple[QPoint, QPoint] | None) -> tuple[QPoint, QPoint] | None:
        if arrow is None:
            return None
        a, b = arrow
        return (QPoint(a), QPoint(b))

    def _hit_reaction_arrow(self, pt: QPoint) -> bool:
        arr = self.reaction_arrow
        if arr is None:
            return False
        a, b = arr
        d2 = self._point_to_segment_distance_sq(pt.x(), pt.y(), a.x(), a.y(), b.x(), b.y())
        hit_slop = max(10.0, self._median_bond_length_px * 0.22)
        return d2 <= hit_slop * hit_slop

    def _set_reaction_arrow(
        self, arrow: tuple[QPoint, QPoint] | None, *, undo: bool = True
    ) -> None:
        old = self._arrow_copy(self.reaction_arrow)
        new = self._arrow_copy(arrow)
        if old is None and new is None:
            return
        if old is not None and new is not None and old[0] == new[0] and old[1] == new[1]:
            return
        if undo:
            self._push_undo("set_arrow", (old, new))
        self.reaction_arrow = new
        if new is None:
            self.selected_reaction_arrow = False
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)

    def _commit_arrow_drag(self, end: QPoint, *, snap: bool) -> None:
        start = self._arrow_drag_start
        self._arrow_dragging = False
        self._arrow_drag_start = None
        self._arrow_drag_pos = None
        if start is None:
            return
        x1, y1 = snap_arrow_end(
            float(start.x()),
            float(start.y()),
            float(end.x()),
            float(end.y()),
            snap=snap,
        )
        head = QPoint(int(round(x1)), int(round(y1)))
        length = math.hypot(head.x() - start.x(), head.y() - start.y())
        if length < MIN_REACTION_ARROW_LENGTH:
            self.update()
            return
        self._set_reaction_arrow((QPoint(start), head))

    def set_reaction_text(self, above: str, below: str) -> None:
        """Store the labels drawn above and below the reaction arrow."""
        new = ((above or "").strip(), (below or "").strip())
        old = (self.reaction_above, self.reaction_below)
        if old == new:
            return
        self.reaction_above, self.reaction_below = new
        self._push_undo("set_reaction_text", (old, new))
        self._after_sketch_edit()

    def reaction_annotation(self) -> str:
        """Table cell for the arrow labels. Above and below are separated by `` | ``."""
        above = (self.reaction_above or "").strip()
        below = (self.reaction_below or "").strip()
        if above and below:
            return f"{above} | {below}"
        return above or below

    def _open_reaction_text_dialog(self) -> None:
        if self.reaction_arrow is None:
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("Reaction text")
        form = QFormLayout(dialog)
        above = QLineEdit(self.reaction_above)
        below = QLineEdit(self.reaction_below)
        above.setPlaceholderText("Reagents, above the arrow")
        below.setPlaceholderText("Conditions, below the arrow")
        form.addRow("Above", above)
        form.addRow("Below", below)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        form.addRow(buttons)
        if dialog.exec_() != QDialog.Accepted:
            return
        self.set_reaction_text(above.text(), below.text())

    def _fragment_centroid(self, comp: set[int]) -> tuple[float, float] | None:
        xs: list[float] = []
        ys: list[float] = []
        for n in self.nodes:
            if n["id"] in comp:
                xs.append(float(n["pos"].x()))
                ys.append(float(n["pos"].y()))
        if not xs:
            return None
        return (sum(xs) / len(xs), sum(ys) / len(ys))

    def reaction_fragment_groups(self) -> tuple[list[set[int]], list[set[int]]] | None:
        """Connected components on the tail (reactants) and head (products) of the arrow."""
        arr = self.reaction_arrow
        if arr is None:
            return None
        a, b = arr
        reactants: list[set[int]] = []
        products: list[set[int]] = []
        for comp in self.connected_components():
            cxy = self._fragment_centroid(comp)
            if cxy is None:
                continue
            side = fragment_side(
                cxy[0], cxy[1], float(a.x()), float(a.y()), float(b.x()), float(b.y())
            )
            if side == "product":
                products.append(comp)
            else:
                reactants.append(comp)
        return reactants, products

    def to_reaction_smarts(self) -> str:
        """Reaction SMILES/SMARTS from the sketch, or ``\"\"`` when no complete reaction."""
        groups = self.reaction_fragment_groups()
        if groups is None:
            return ""
        reactants, products = groups
        if not reactants or not products:
            return ""
        use_smarts = self.sketch_has_wildcards()
        left: list[str] = []
        right: list[str] = []
        for comp in reactants:
            part = (
                self._component_to_smarts(comp) if use_smarts else self._component_to_smiles(comp)
            )
            if part:
                left.append(part)
        for comp in products:
            part = (
                self._component_to_smarts(comp) if use_smarts else self._component_to_smiles(comp)
            )
            if part:
                right.append(part)
        if not left or not right:
            return ""
        return join_reaction_string(left, right)

    def _reaction_plus_positions(self) -> list[tuple[float, float]]:
        groups = self.reaction_fragment_groups()
        arr = self.reaction_arrow
        if groups is None or arr is None:
            return []
        a, b = arr
        out: list[tuple[float, float]] = []
        for comps in groups:
            cents: list[tuple[float, float]] = []
            for comp in comps:
                cxy = self._fragment_centroid(comp)
                if cxy is not None:
                    cents.append(cxy)
            out.extend(
                plus_sign_positions(cents, float(a.x()), float(a.y()), float(b.x()), float(b.y()))
            )
        return out

    def _refresh_hover_from_cursor(self):
        try:
            gpos = QCursor.pos()
            lpos = self._widget_point_to_model(self.mapFromGlobal(gpos))
            hit = self._hit_node(lpos)
            bi, _ = self._hit_bond(lpos)
            arrow_hit = self._hit_reaction_arrow(lpos)
            sel = self._selected_node_set()
            if self.select_mode:
                if hit and hit["id"] in sel:
                    self.hover = hit["id"]
                    self.setCursor(Qt.OpenHandCursor)
                elif bi is not None and bi in self.selected_bond_indices:
                    self.hover = ("bond", bi)
                    self.setCursor(Qt.OpenHandCursor)
                elif self.selected_reaction_arrow and arrow_hit:
                    self.hover = ("arrow", 0)
                    self.setCursor(Qt.OpenHandCursor)
                elif hit:
                    self.hover = hit["id"]
                    self.setCursor(Qt.PointingHandCursor)
                elif bi is not None:
                    self.hover = ("bond", bi)
                    self.setCursor(Qt.PointingHandCursor)
                elif arrow_hit:
                    self.hover = ("arrow", 0)
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
                elif arrow_hit:
                    self.hover = ("arrow", 0)
                    self.setCursor(Qt.PointingHandCursor)
                else:
                    self.hover = None
                    if (
                        self.erase_mode
                        or self.reaction_arrow_mode
                        or self._carbon_chain_cursor_active()
                    ):
                        self.setCursor(Qt.CrossCursor)
                    else:
                        self.setCursor(Qt.ArrowCursor)
            self.update()
        except Exception:
            pass

    # ---------- Valence checks ----------
    def _valence_list_for_element(self, element: str) -> list[int]:
        """RDKit allowed valences for *element* (ascending), or empty if unknown."""
        if rgroup_label_from_element(element) is not None:
            return []
        if element in ("H", "D", "T"):
            return [1]
        try:
            pt = Chem.GetPeriodicTable()
            an = pt.GetAtomicNumber(element)
            if an <= 0:
                return []
            return sorted({int(v) for v in pt.GetValenceList(an) if int(v) > 0})
        except Exception:
            return []

    def _default_valence(self, element: str) -> int:
        """Common / lowest preferred valence (e.g. S=2), not the hypervalent maximum."""
        if rgroup_label_from_element(element) is not None:
            return 0
        if element in ("H", "D", "T"):
            return 1
        try:
            pt = Chem.GetPeriodicTable()
            an = pt.GetAtomicNumber(element)
            if an > 0:
                dv = pt.GetDefaultValence(an)
                if dv > 0:
                    return int(dv)
        except Exception:
            pass
        vlist = self._valence_list_for_element(element)
        if vlist:
            return min(vlist)
        if element in ("Na", "K", "Rb", "Cs", "Li"):
            return 1
        if element in ("Mg", "Ca", "Sr", "Ba"):
            return 2
        if element in ("Zn", "Cd", "Hg", "Cu", "Ag", "Au", "Ni", "Pd", "Pt", "Co"):
            return 4
        return 4

    def _max_valence(self, element: str) -> int:
        """
        Maximum allowed sum of incident bond orders (validation ceiling).

        Uses RDKit's valence-list high end so sulfonamides / sulfones (S=6) and
        phosphates (P=5/7) are legal. Do **not** use this for implicit-H counts —
        see ``_target_valence_for_implicit_h``.
        """
        if rgroup_label_from_element(element) is not None:
            return 1
        if element in ("H", "D", "T"):
            return 1
        vlist = self._valence_list_for_element(element)
        if vlist:
            return max(vlist)
        try:
            pt = Chem.GetPeriodicTable()
            an = pt.GetAtomicNumber(element)
            if an > 0:
                dv = pt.GetDefaultValence(an)
                if dv > 0:
                    return int(dv)
        except Exception:
            pass
        if element in ("Na", "K", "Rb", "Cs", "Li"):
            return 1
        if element in ("Mg", "Ca", "Sr", "Ba"):
            return 2
        if element in ("Zn", "Cd", "Hg", "Cu", "Ag", "Au", "Ni", "Pd", "Pt", "Co"):
            return 4
        if element in ("P", "As"):
            return 5
        if element in ("S", "Se", "Te"):
            return 6
        return 8

    def _target_valence_for_implicit_h(self, element: str, bond_sum: int, fc: int) -> int:
        """
        Valence used to estimate implicit H / condensed labels / lone pairs.

        Chooses the smallest allowed valence ≥ current bond-order sum so divalent
        sulfur (disulfides, thioethers) stays at 2 (not SH₄), while S with two
        S=O doubles targets 6.
        """
        need = max(0, int(bond_sum))
        if fc != 0 and element in ("N", "O", "S", "P"):
            # Prefer the same charge-aware caps used for validation when specialized.
            if fc == 1 and element in ("N", "O", "S", "P"):
                return max(need, self._max_bond_order_sum(element, fc))
            if fc == -1 and element in ("O", "N"):
                return max(need, self._max_bond_order_sum(element, fc))
        vlist = self._valence_list_for_element(element)
        if not vlist:
            base = self._default_valence(element)
            if fc > 0:
                return max(need, base - fc)
            if fc < 0:
                return max(need, base - fc)
            return max(need, base)
        candidates = [v for v in vlist if v >= need]
        target = min(candidates) if candidates else max(vlist)
        if fc > 0:
            return max(need, target - fc)
        if fc < 0:
            return max(need, target - fc)
        return target

    def _heavy_neighbor_count(self, node_id: int) -> int:
        n = 0
        for bond in self.bonds:
            a, b, _o, _s = _bond_unpack(bond)
            if a == node_id or b == node_id:
                n += 1
        return n

    def _current_valence(self, node_id: int) -> int:
        s = 0
        for bond in self.bonds:
            a, b, order, _ = _bond_unpack(bond)
            if a == node_id or b == node_id:
                s += order
        return s

    def _recompute_chiral_highlights(self) -> None:
        """Tetrahedral R/S (wedge/hash) and alkene E/Z from sketch geometry + RDKit ranking."""
        self._chiral_center_ids = set()
        self._chiral_stereo_issue_ids = set()
        self._stereo_cip_by_node_id = {}
        self._alkene_ez_by_bond_index = {}
        if not self.nodes:
            return
        try:
            ids = {n["id"] for n in self.nodes}
            out = self._mol_from_node_ids(ids, return_idmap=True)
            if out is None:
                return
            mol, sk2rd = out
            if mol is None or mol.GetNumAtoms() == 0:
                return
            try:
                mol.UpdatePropertyCache(strict=False)
            except Exception:
                pass
            try:
                Chem.SanitizeMol(
                    mol,
                    sanitizeOps=Chem.SanitizeFlags.SANITIZE_PROPERTIES
                    | Chem.SanitizeFlags.SANITIZE_SYMMRINGS,
                )
            except Exception:
                pass
            inv = {v: k for k, v in sk2rd.items()}
            # Atoms that already have a wedge/hash tip (legal drawn stereo).
            stereo_tip_ids: set[int] = set()
            for bond in self.bonds:
                a, _b, o, s = _bond_unpack(bond)
                if o == 1 and s in (BOND_STEREO_WEDGE, BOND_STEREO_HASH):
                    stereo_tip_ids.add(a)

            cip_by_rd = self._assign_tetrahedral_cip(mol)

            for rd_idx, tag in cip_by_rd.items():
                if rd_idx not in inv:
                    continue
                nid = inv[rd_idx]
                self._chiral_center_ids.add(nid)
                if tag in ("R", "S"):
                    self._stereo_cip_by_node_id[nid] = str(tag)
                elif nid not in stereo_tip_ids:
                    # Unassigned CIP with no drawn wedge/hash → unspecified caution.
                    self._chiral_stereo_issue_ids.add(nid)
            try:
                ez_rd = infer_alkene_ez_for_sketch_mol(mol)
            except Exception:
                ez_rd = {}
            for bi, bond in enumerate(self.bonds):
                a, b, o, _s = _bond_unpack(bond)
                if o != 2:
                    continue
                ai, bj = sk2rd.get(a), sk2rd.get(b)
                if ai is None or bj is None:
                    continue
                key = (min(ai, bj), max(ai, bj))
                lab = ez_rd.get(key)
                if lab in ("E", "Z"):
                    self._alkene_ez_by_bond_index[bi] = lab
        except Exception:
            self._chiral_center_ids = set()
            self._chiral_stereo_issue_ids = set()
            self._stereo_cip_by_node_id = {}
            self._alkene_ez_by_bond_index = {}

    def _recompute_valence_violations(self, *, notify: bool = True) -> None:
        live_ids = {n["id"] for n in self.nodes}
        self._stereo_label_node_ids &= live_ids
        bad: set[int] = set()
        charge_bad: set[int] = set()
        for n in self.nodes:
            vid = n["id"]
            val = self._current_valence(vid)
            fc = self._formal_charge(n)
            cap = self._max_bond_order_sum_for_node(n, fc)
            if val > cap:
                bad.add(vid)
                if fc != 0:
                    charge_bad.add(vid)
        self._valence_violations = bad
        self._charge_violations = charge_bad
        self._recompute_chiral_highlights()
        # Stereo tip / between-center cleanup may depend on freshly computed chiral ids.
        self._ensure_bonds_sanitized()
        self.refresh_iupac_validation()
        self._refresh_sketch_draw_metrics()
        self.update()
        if notify:
            self._notify_sketch_changed()

    def _after_sketch_edit(
        self,
        *,
        valence: bool = True,
        notify: bool = True,
        notify_if_valence_failed: bool = False,
    ) -> None:
        """Recompute valence/stereo highlights, repaint, and optionally notify listeners.

        Wraps valence recomputation in ``try/except`` so a bad intermediate graph cannot leave the
        widget without a repaint. On success, ``_recompute_valence_violations`` handles
        ``update`` and (when ``notify``) ``_notify_sketch_changed``. On failure, repaints; callers
        that must still emit ``sketch_changed`` (for example bulk delete) set
        ``notify_if_valence_failed=True``.
        """
        self._invalidate_rdkit_sketch_paint_cache()
        if valence:
            try:
                self._recompute_valence_violations(notify=notify)
                return
            except Exception:
                try:
                    self.update()
                except Exception:
                    pass
                if notify and notify_if_valence_failed:
                    try:
                        self._notify_sketch_changed()
                    except Exception:
                        pass
                return
        try:
            self.update()
        except Exception:
            pass
        if notify:
            try:
                self._notify_sketch_changed()
            except Exception:
                pass

    def _bond_tool_order_stereo(self) -> tuple[int, int]:
        """Return (order, stereo) for the active toolbar bond tool."""
        order = int(getattr(self, "active_bond_order", 1) or 1)
        order = 1 if order < 1 else 3 if order > 3 else order
        stereo = int(getattr(self, "active_bond_stereo", 0) or 0)
        if order != 1:
            return order, BOND_STEREO_PLAIN
        if stereo not in BOND_STEREO_VALUES:
            stereo = BOND_STEREO_PLAIN
        return 1, stereo

    def _apply_active_bond_tool(self, bi: int) -> bool:
        """Set bond ``bi`` to the active tool's order/stereo. Returns True if changed."""
        if not (0 <= bi < len(self.bonds)):
            return False
        a, b, order, st = _bond_unpack(self.bonds[bi])
        new_order, new_st = self._bond_tool_order_stereo()
        new_a, new_b = a, b
        # ST-0.5: do not place wedge/hash between two stereocenters.
        if (
            new_order == 1
            and new_st in (BOND_STEREO_WEDGE, BOND_STEREO_HASH)
            and a in getattr(self, "_chiral_center_ids", set())
            and b in getattr(self, "_chiral_center_ids", set())
        ):
            new_st = BOND_STEREO_PLAIN
        # Tip at the atom under the cursor when applying stereo; else most substituted.
        if new_order == 1 and new_st in (BOND_STEREO_WEDGE, BOND_STEREO_HASH):
            tip = self.hover if isinstance(self.hover, int) else None
            if tip == b:
                new_a, new_b = b, a
            elif tip == a:
                new_a, new_b = a, b
            else:
                mult: set[int] = set()
                for bond in self.bonds:
                    xa, xb, xo, _ = _bond_unpack(bond)
                    if xo >= 2:
                        mult.add(xa)
                        mult.add(xb)
                if new_a in mult and new_b not in mult:
                    new_a, new_b = new_b, new_a
                elif new_a not in mult and new_b not in mult:
                    if self._heavy_neighbor_count(new_b) > self._heavy_neighbor_count(new_a):
                        new_a, new_b = new_b, new_a
        if (new_a, new_b, new_order, new_st) == (a, b, order, st):
            return False
        self.bonds[bi] = _bond_make(new_a, new_b, new_order, new_st)
        self._push_undo("chg_bond", (a, b, (order, st), (new_order, new_st)))
        return True

    def _snapshot_sketch_state(self) -> dict[str, Any]:
        nodes: list[dict[str, Any]] = []
        for n in self.nodes:
            d = dict(n)
            d["pos"] = QPoint(n["pos"])
            if "wildcard_els" in n:
                d["wildcard_els"] = list(n.get("wildcard_els") or [])
            nodes.append(d)
        return {
            "nodes": nodes,
            "bonds": [tuple(_bond_unpack(b)) for b in self.bonds],
            "next_id": int(self.next_id),
            "stereo_labels": sorted(int(x) for x in self._stereo_label_node_ids),
            "salt_smiles": self._salt_bundle_smiles,
            "salt_nodes": frozenset(self._salt_bundle_nodes)
            if self._salt_bundle_nodes is not None
            else None,
            "salt_frag_count": self._salt_bundle_fragment_count,
            "group_is_salt": bool(self._group_bundle_is_salt),
            "reaction_arrow": None
            if self.reaction_arrow is None
            else (
                (int(self.reaction_arrow[0].x()), int(self.reaction_arrow[0].y())),
                (int(self.reaction_arrow[1].x()), int(self.reaction_arrow[1].y())),
            ),
            "reaction_above": self.reaction_above,
            "reaction_below": self.reaction_below,
        }

    def _restore_sketch_state(self, payload: dict[str, Any]) -> None:
        self.nodes = []
        for n in payload.get("nodes") or []:
            d = dict(n)
            pos = d.get("pos")
            if isinstance(pos, QPoint):
                d["pos"] = QPoint(pos)
            elif isinstance(pos, (tuple, list)) and len(pos) >= 2:
                d["pos"] = QPoint(int(pos[0]), int(pos[1]))
            self.nodes.append(d)
        self.bonds = [_bond_make(*_bond_unpack(b)) for b in (payload.get("bonds") or [])]
        self.next_id = int(
            payload.get("next_id") or (max((n["id"] for n in self.nodes), default=-1) + 1)
        )
        self.sel = None
        self.selected_nodes = []
        self.selected_bond_indices = set()
        self._selection_rect = None
        self._selecting = False
        self._select_start = None
        self._lasso_points = []
        self._release_marquee_mouse_grab_if_any()
        self._stereo_label_node_ids = {int(x) for x in (payload.get("stereo_labels") or [])}
        salt_nodes = payload.get("salt_nodes")
        self._salt_bundle_smiles = payload.get("salt_smiles")
        self._salt_bundle_nodes = frozenset(salt_nodes) if salt_nodes is not None else None
        self._salt_bundle_fragment_count = payload.get("salt_frag_count")
        self._group_bundle_is_salt = bool(payload.get("group_is_salt"))
        raw_arrow = payload.get("reaction_arrow")
        self.reaction_arrow = None
        if isinstance(raw_arrow, (tuple, list)) and len(raw_arrow) == 2:
            a, b = raw_arrow
            if isinstance(a, QPoint) and isinstance(b, QPoint):
                self.reaction_arrow = (QPoint(a), QPoint(b))
            elif (
                isinstance(a, (tuple, list))
                and isinstance(b, (tuple, list))
                and len(a) >= 2
                and len(b) >= 2
            ):
                self.reaction_arrow = (
                    QPoint(int(a[0]), int(a[1])),
                    QPoint(int(b[0]), int(b[1])),
                )
        self.selected_reaction_arrow = False
        self.reaction_above = str(payload.get("reaction_above") or "")
        self.reaction_below = str(payload.get("reaction_below") or "")
        self._ensure_bonds_sanitized()

    def _swap_clear_sketch_undo(self, other: dict[str, Any], *, to_redo: bool) -> None:
        cur = self._snapshot_sketch_state()
        self._restore_sketch_state(other)
        if to_redo:
            self._redo.append(("clear_sketch", cur))
        else:
            self._undo.append(("clear_sketch", cur))

    # ---------- Undo/redo ----------
    def _push_undo(self, op: str, data: Any):
        self._undo.append((op, data))
        self._redo.clear()

    def _commit_template_placement(self, before: dict[str, Any]) -> None:
        """Record one undo step for a full ring-template drop (nodes, bonds, and fit)."""
        self._push_undo("clear_sketch", before)
        self.ensure_sketch_fits_viewport(refresh=False)
        self._after_sketch_edit()

    def _ensure_bonds_sanitized(self) -> None:
        """Drop malformed bond tuples and normalize stereo for multi-order bonds."""
        out: list[tuple[int, int, int, int]] = []
        for b in self.bonds:
            if not _bond_record_ok(b):
                continue
            a, bo, o, s = _bond_unpack(b)
            if o != 1:
                s = BOND_STEREO_PLAIN
            elif s not in BOND_STEREO_VALUES:
                s = BOND_STEREO_PLAIN
            out.append(_bond_make(a, bo, o, s))
        chiral = getattr(self, "_chiral_center_ids", None) or set()
        out = sanitize_sketch_stereo_bonds(out, chiral_center_ids=chiral)
        if len(out) != len(self.bonds):
            self.selected_bond_indices = set()
        if out != self.bonds:
            self.bonds = out

    def refresh_iupac_validation(self) -> list:
        """Recompute IUPAC issues and soft-highlight sets; return the issue list."""
        issues = validate_iupac_sketch(
            self.nodes,
            self.bonds,
            chiral_center_ids=getattr(self, "_chiral_center_ids", set()) or set(),
            median_bond_px=getattr(self, "_median_bond_length_px", None),
        )
        self._iupac_issue_atom_ids = {aid for iss in issues for aid in iss.atom_ids}
        self._iupac_issue_bond_indices = {bi for iss in issues for bi in iss.bond_indices}
        self._iupac_issues_summary = format_iupac_issues(issues)
        return issues

    def structure_issue_report(self) -> tuple[str, list[str]]:
        """
        Aggregate valence / stereo / IUPAC findings for the toolbar status control.

        Returns ``(level, messages)`` where *level* is ``\"ok\"``, ``\"caution\"``,
        or ``\"error\"``. Unspecified stereochemistry is caution; invalid valence is error.
        """
        errors: list[str] = []
        cautions: list[str] = []

        for n in self.nodes:
            nid = int(n["id"])
            if nid in getattr(self, "_valence_violations", set()):
                el = str(n.get("element") or "?")
                errors.append(f"Invalid valence at atom {nid} ({el}).")
            elif nid in getattr(self, "_charge_violations", set()):
                el = str(n.get("element") or "?")
                errors.append(f"Charge/valence conflict at atom {nid} ({el}).")

        for nid in sorted(getattr(self, "_chiral_stereo_issue_ids", set()) or ()):
            cautions.append(f"Unspecified tetrahedral stereochemistry at atom {nid}.")

        for bond in self.bonds:
            a, b, _o, st = _bond_unpack(bond)
            if st == BOND_STEREO_WAVY:
                cautions.append(f"Unspecified (wavy) stereochemistry on bond {a}–{b}.")

        hard_codes = frozenset({"stereo_on_multiple", "stereo_between_centers", "atom_overlap"})
        issues = self.refresh_iupac_validation()
        for iss in issues:
            if iss.code in hard_codes:
                errors.append(iss.message)
            else:
                cautions.append(iss.message)

        groups = self.reaction_fragment_groups()
        if self.reaction_arrow is not None:
            if groups is None or not groups[0] or not groups[1]:
                cautions.append(
                    "Reaction arrow: place reactants on the tail side and products on the head side."
                )
            elif not self.to_reaction_smarts():
                cautions.append("Reaction arrow: could not export reaction SMILES/SMARTS.")

        def _uniq(msgs: list[str]) -> list[str]:
            seen: set[str] = set()
            out: list[str] = []
            for m in msgs:
                if m in seen:
                    continue
                seen.add(m)
                out.append(m)
            return out

        errors = _uniq(errors)
        cautions = _uniq(cautions)
        if errors:
            return "error", errors + [m for m in cautions if m not in errors]
        if cautions:
            return "caution", cautions
        if not self.nodes:
            return "ok", ["Empty sketch."]
        return "ok", ["No valence or stereochemistry issues flagged."]

    def undo(self) -> None:
        """Undo one sketch edit and report it on the status bar."""
        if not self._undo:
            self._report_status("Nothing to undo.")
            return
        self._perform_undo()
        self._report_status("Undone.")

    def _perform_undo(self) -> None:
        if not self._undo:
            return
        self._ensure_bonds_sanitized()
        op, data = self._undo.pop()
        if op == "clear_sketch":
            self._swap_clear_sketch_undo(data, to_redo=True)
            self._after_sketch_edit()
            return
        if op == "set_arrow":
            old, _new = data
            self.reaction_arrow = self._arrow_copy(old)
            if self.reaction_arrow is None:
                self.selected_reaction_arrow = False
            self._redo.append(("set_arrow", data))
            self._after_sketch_edit()
            return
        if op == "set_reaction_text":
            old, _new = data
            self.reaction_above, self.reaction_below = old
            self._redo.append(("set_reaction_text", data))
            self._after_sketch_edit()
            return
        if op == "add_node":
            node = data
            nid = node["id"]
            conn = [b for b in self.bonds if b[0] == nid or b[1] == nid]
            self.bonds = [b for b in self.bonds if b[0] != nid and b[1] != nid]
            self.nodes = [n for n in self.nodes if n["id"] != nid]
            self._redo.append(("del_node", (node, conn)))
        elif op == "add_bonded_node":
            node, bond = data
            nid = node["id"]
            bt = _bond_make(*_bond_unpack(bond))
            self.bonds = [b for b in self.bonds if b != bt and b[0] != nid and b[1] != nid]
            self.nodes = [n for n in self.nodes if n["id"] != nid]
            self._redo.append(("del_bonded_node", (node, bt)))
        elif op == "add_bond":
            if not _bond_record_ok(data):
                pass
            else:
                bond = _bond_make(*_bond_unpack(data))
                for i, b in enumerate(self.bonds):
                    if b == bond:
                        self.bonds.pop(i)
                        self._redo.append(("del_bond", bond))
                        break
        elif op == "move_nodes":
            moves = data
            for nid, old_pos, new_pos in moves:
                n = next((n for n in self.nodes if n["id"] == nid), None)
                if n:
                    n["pos"] = QPoint(old_pos.x(), old_pos.y())
            rev = [(nid, new_pos, old_pos) for nid, old_pos, new_pos in moves]
            self._redo.append(("move_nodes", rev))
        elif op == "del_node":
            node, conn = data
            self.nodes.append(node)
            for b in conn:
                self.bonds.append(_bond_make(*_bond_unpack(b)))
            self._redo.append(("add_node", node))
        elif op == "del_bond":
            if not _bond_record_ok(data):
                pass
            else:
                bond = _bond_make(*_bond_unpack(data))
                self.bonds.append(bond)
                self._redo.append(("add_bond", bond))
        elif op == "chg_atom":
            if len(data) >= 5:
                nid, old_el, new_el, old_w, new_w = data[:5]
            else:
                nid, old_el, new_el = data[:3]
                old_w, new_w = None, None
            old_ab = data[5] if len(data) >= 7 else None
            new_ab = data[6] if len(data) >= 7 else None
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n:
                n["element"] = old_el
                if old_el == WILDCARD_ELEMENT:
                    n["wildcard_els"] = list(old_w) if old_w else list(DEFAULT_WILDCARD_ELEMENTS)
                else:
                    n.pop("wildcard_els", None)
                if old_ab:
                    n["abbrev"] = old_ab
                else:
                    n.pop("abbrev", None)
                self._redo.append(("chg_atom", (nid, new_el, old_el, new_w, old_w, new_ab, old_ab)))
        elif op == "chg_charge":
            nid, old, new = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n:
                if int(old or 0) == 0:
                    n.pop("charge", None)
                else:
                    n["charge"] = int(old)
                self._redo.append(("chg_charge", (nid, new, old)))
        elif op == "chg_explicit_carbon":
            nid, old, new = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if old:
                    n["explicit_carbon"] = True
                else:
                    n.pop("explicit_carbon", None)
                self._redo.append(("chg_explicit_carbon", (nid, new, old)))
        elif op == "chg_show_lone_pairs":
            nid, old, new = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if old:
                    n["show_lone_pairs"] = True
                else:
                    n.pop("show_lone_pairs", None)
                self._redo.append(("chg_show_lone_pairs", (nid, new, old)))
        elif op == "chg_show_oxidation_state":
            nid, old, new = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if old:
                    n["show_oxidation_state"] = True
                else:
                    n.pop("show_oxidation_state", None)
                self._redo.append(("chg_show_oxidation_state", (nid, new, old)))
        elif op == "chg_bond":
            if len(data) == 4 and isinstance(data[2], int):
                a, b, old_o, new_o = data
                old_os, new_os = (old_o, 0), (new_o, 0)
            else:
                a, b, old_os, new_os = data
            for i, bb in enumerate(self.bonds):
                x, y, o, s = _bond_unpack(bb)
                if {x, y} != {a, b}:
                    continue
                if x == a and y == b:
                    self.bonds[i] = _bond_make(x, y, old_os[0], old_os[1])
                else:
                    sr = old_os[1]
                    if sr == BOND_STEREO_WEDGE:
                        sr = BOND_STEREO_HASH
                    elif sr == BOND_STEREO_HASH:
                        sr = BOND_STEREO_WEDGE
                    self.bonds[i] = _bond_make(x, y, old_os[0], sr)
                self._redo.append(("chg_bond", (a, b, new_os, old_os)))
                break
        elif op == "add_hs_local":
            payload = data
            nids = {n["id"] for n in payload["nodes"]}
            for bb in payload["bonds"]:
                bt = _bond_make(*_bond_unpack(bb))
                self.bonds = [b for b in self.bonds if b != bt]
            self.nodes = [n for n in self.nodes if n["id"] not in nids]
            self._redo.append(("add_hs_redo", payload))
            self._after_sketch_edit()
            return
        elif op == "del_hs_local":
            payload = data
            for n in payload["nodes"]:
                self.nodes.append(n)
            mx_id = max((n["id"] for n in self.nodes), default=0)
            self.next_id = max(self.next_id, mx_id + 1)
            if payload.get("prev_bonds") is not None:
                self.bonds = [_bond_make(*_bond_unpack(b)) for b in payload["prev_bonds"]]
            else:
                for bb in payload["bonds"]:
                    self.bonds.append(_bond_make(*_bond_unpack(bb)))
            self._redo.append(("del_hs_redo", payload))
            self._after_sketch_edit()
            return
        elif op == "add_chain":
            payload = data
            nids = set(payload["new_ids"])
            self.nodes = [n for n in self.nodes if n["id"] not in nids]
            self.bonds = [
                b
                for b in self.bonds
                if _bond_unpack(b)[0] not in nids and _bond_unpack(b)[1] not in nids
            ]
            self.selected_nodes = [i for i in self.selected_nodes if i not in nids]
            self._redo.append(("add_chain_redo", payload))
            self._after_sketch_edit()
            return
        elif op == "paste_group":
            payload = data
            for nid in payload["new_ids"]:
                self.nodes = [n for n in self.nodes if n["id"] != nid]
                self.bonds = [
                    b for b in self.bonds if _bond_unpack(b)[0] != nid and _bond_unpack(b)[1] != nid
                ]
            if self.sel in payload["new_ids"]:
                self.sel = None
            self.selected_nodes = [x for x in self.selected_nodes if x not in payload["new_ids"]]
            self.selected_bond_indices = set()
            self._redo.append(("paste_redo", payload))
        self._after_sketch_edit()

    def redo(self) -> None:
        """Redo one sketch edit and report it on the status bar."""
        if not self._redo:
            self._report_status("Nothing to redo.")
            return
        self._perform_redo()
        self._report_status("Redone.")

    def _perform_redo(self) -> None:
        if not self._redo:
            return
        self._ensure_bonds_sanitized()
        op, data = self._redo.pop()
        if op == "clear_sketch":
            self._swap_clear_sketch_undo(data, to_redo=False)
            self._after_sketch_edit()
            return
        if op == "set_arrow":
            _old, new = data
            self.reaction_arrow = self._arrow_copy(new)
            if self.reaction_arrow is None:
                self.selected_reaction_arrow = False
            self._undo.append(("set_arrow", data))
            self._after_sketch_edit()
            return
        if op == "set_reaction_text":
            _old, new = data
            self.reaction_above, self.reaction_below = new
            self._undo.append(("set_reaction_text", data))
            self._after_sketch_edit()
            return
        if op == "del_node":
            node, conn = data
            self.nodes.append(node)
            for b in conn:
                self.bonds.append(_bond_make(*_bond_unpack(b)))
            self._undo.append(("add_node", node))
            self._after_sketch_edit()
            return
        if op == "del_bonded_node":
            node, bond = data
            self.nodes.append(node)
            mx_id = max((n["id"] for n in self.nodes), default=0)
            self.next_id = max(self.next_id, mx_id + 1)
            self.bonds.append(_bond_make(*_bond_unpack(bond)))
            self._undo.append(("add_bonded_node", (node, _bond_make(*_bond_unpack(bond)))))
            self._after_sketch_edit()
            return
        if op == "del_bond":
            if not _bond_record_ok(data):
                self._after_sketch_edit()
                return
            bond = _bond_make(*_bond_unpack(data))
            self.bonds.append(bond)
            self._undo.append(("add_bond", bond))
            self._after_sketch_edit()
            return
        if op == "add_bond":
            if not _bond_record_ok(data):
                self._after_sketch_edit()
                return
            bond = _bond_make(*_bond_unpack(data))
            for i, b in enumerate(self.bonds):
                if b == bond:
                    self.bonds.pop(i)
                    self._undo.append(("del_bond", bond))
                    break
            self._after_sketch_edit()
            return
        if op == "add_bonded_node":
            node, bond = data
            nid = node["id"]
            bt = _bond_make(*_bond_unpack(bond))
            self.bonds = [b for b in self.bonds if b != bt and b[0] != nid and b[1] != nid]
            self.nodes = [n for n in self.nodes if n["id"] != nid]
            self._undo.append(("del_bonded_node", (node, bt)))
            self._after_sketch_edit()
            return
        if op == "add_hs_redo":
            payload = data
            for n in payload["nodes"]:
                self.nodes.append(n)
            mx_id = max((n["id"] for n in self.nodes), default=0)
            self.next_id = max(self.next_id, mx_id + 1)
            for bb in payload["bonds"]:
                self.bonds.append(_bond_make(*_bond_unpack(bb)))
            self._undo.append(("add_hs_local", payload))
            self._after_sketch_edit()
            return
        if op == "del_hs_redo":
            payload = data
            nids = {n["id"] for n in payload["nodes"]}
            self.nodes = [n for n in self.nodes if n["id"] not in nids]
            if payload.get("after_bonds") is not None:
                self.bonds = [_bond_make(*_bond_unpack(b)) for b in payload["after_bonds"]]
            else:
                for bb in payload["bonds"]:
                    bt = _bond_make(*_bond_unpack(bb))
                    self.bonds = [b for b in self.bonds if b != bt]
            self._undo.append(("del_hs_local", payload))
            self._after_sketch_edit()
            return
        if op == "add_chain_redo":
            payload = data
            self.nodes.extend(payload["nodes"])
            for bond in payload["bonds"]:
                self.bonds.append(_bond_make(*_bond_unpack(bond)))
            if payload["nodes"]:
                self.next_id = max(self.next_id, max(int(n["id"]) for n in payload["nodes"]) + 1)
            self._undo.append(("add_chain", payload))
            self._after_sketch_edit()
            return
        if op == "paste_redo":
            self._paste_fragment_payload(
                data["fragment"], QPoint(int(data["anchor"][0]), int(data["anchor"][1]))
            )
            return
        if op == "chg_bond":
            if len(data) == 4 and isinstance(data[2], int):
                a, b, old_o, new_o = data
                old_os, new_os = (old_o, 0), (new_o, 0)
            else:
                a, b, old_os, new_os = data
            for i, bb in enumerate(self.bonds):
                x, y, o, s = _bond_unpack(bb)
                if {x, y} != {a, b}:
                    continue
                if x == a and y == b:
                    self.bonds[i] = _bond_make(x, y, new_os[0], new_os[1])
                else:
                    sr = new_os[1]
                    if sr == BOND_STEREO_WEDGE:
                        sr = BOND_STEREO_HASH
                    elif sr == BOND_STEREO_HASH:
                        sr = BOND_STEREO_WEDGE
                    self.bonds[i] = _bond_make(x, y, new_os[0], sr)
                self._undo.append(("chg_bond", (a, b, old_os, new_os)))
                break
            self._after_sketch_edit()
            return
        if op == "chg_atom":
            if len(data) >= 5:
                nid, new_el, old_el, new_w, old_w = data[:5]
            else:
                nid, new_el, old_el = data[:3]
                new_w, old_w = None, None
            new_ab = data[5] if len(data) >= 7 else None
            old_ab = data[6] if len(data) >= 7 else None
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                n["element"] = new_el
                if new_el == WILDCARD_ELEMENT:
                    n["wildcard_els"] = list(new_w) if new_w else list(DEFAULT_WILDCARD_ELEMENTS)
                else:
                    n.pop("wildcard_els", None)
                if new_ab:
                    n["abbrev"] = new_ab
                else:
                    n.pop("abbrev", None)
                self._undo.append(("chg_atom", (nid, old_el, new_el, old_w, new_w, old_ab, new_ab)))
            self._after_sketch_edit()
            return
        if op == "chg_charge":
            try:
                nid, new, old = data
            except Exception:
                nid, new = data[0], data[1]
                old = None
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if int(new or 0) == 0:
                    n.pop("charge", None)
                else:
                    n["charge"] = int(new)
                if old is not None:
                    self._undo.append(("chg_charge", (nid, old, new)))
            self._after_sketch_edit()
            return
        if op == "chg_explicit_carbon":
            nid, new, old = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if new:
                    n["explicit_carbon"] = True
                else:
                    n.pop("explicit_carbon", None)
                self._undo.append(("chg_explicit_carbon", (nid, old, new)))
            self._after_sketch_edit()
            return
        if op == "chg_show_lone_pairs":
            nid, new, old = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if new:
                    n["show_lone_pairs"] = True
                else:
                    n.pop("show_lone_pairs", None)
                self._undo.append(("chg_show_lone_pairs", (nid, old, new)))
            self._after_sketch_edit()
            return
        if op == "chg_show_oxidation_state":
            nid, new, old = data
            n = next((n for n in self.nodes if n["id"] == nid), None)
            if n is not None:
                if new:
                    n["show_oxidation_state"] = True
                else:
                    n.pop("show_oxidation_state", None)
                self._undo.append(("chg_show_oxidation_state", (nid, old, new)))
            self._after_sketch_edit()
            return
        if op == "move_nodes":
            moves = data
            for nid, old_pos, new_pos in moves:
                n = next((n for n in self.nodes if n["id"] == nid), None)
                if n:
                    n["pos"] = QPoint(new_pos.x(), new_pos.y())
            rev = [(nid, old_pos, new_pos) for nid, old_pos, new_pos in moves]
            self._undo.append(("move_nodes", rev))
            self._after_sketch_edit()
            return
        self._after_sketch_edit()

    # ---------- Editing helpers ----------
    def _delete_node(self, nid: int):
        self.nodes = [n for n in self.nodes if n["id"] != nid]
        self.bonds = [b for b in self.bonds if b[0] != nid and b[1] != nid]
        if self.sel == nid:
            self.sel = None
        self._after_sketch_edit()

    def _set_atom(self, element: str, hit: dict[str, Any] | None):
        if hit:
            self._mutate_atom_element(hit, element, None)
        else:
            self.place_element = element
            self.update()

    def _mutate_atom_element(
        self,
        hit: dict[str, Any],
        new_el: str,
        wildcard_els: list[str] | None,
        abbrev: str | None = None,
    ) -> None:
        """Change an existing atom (with undo). For wildcards, pass ``wildcard_els`` or None for defaults."""
        nid = hit["id"]
        n = next((x for x in self.nodes if x["id"] == nid), None)
        if n is None:
            return
        old_el = n["element"]
        old_w = tuple(_normalize_wildcard_elements(n)) if _is_wildcard_node(n) else None
        old_ab = n.get("abbrev")
        new_ab = abbrev
        if new_el == WILDCARD_ELEMENT:
            raw = list(wildcard_els) if wildcard_els else list(DEFAULT_WILDCARD_ELEMENTS)
            clean = [x for x in raw if x in WILDCARD_ELEMENT_CHOICES]
            if not clean:
                clean = list(DEFAULT_WILDCARD_ELEMENTS)
            new_w_store = tuple(sorted(set(clean)))
            if old_el == WILDCARD_ELEMENT and old_w == new_w_store and not old_ab:
                return
            n["element"] = WILDCARD_ELEMENT
            n["wildcard_els"] = list(new_w_store)
            n.pop("explicit_carbon", None)
            n.pop("abbrev", None)
            new_ab = None
        else:
            if old_el == new_el and old_ab == new_ab and not _is_wildcard_node(n):
                return
            n["element"] = new_el
            n.pop("wildcard_els", None)
            if new_el != "C":
                n.pop("explicit_carbon", None)
            if new_ab:
                n["abbrev"] = new_ab
                n.pop("explicit_carbon", None)
            else:
                n.pop("abbrev", None)
        new_w_store = tuple(_normalize_wildcard_elements(n)) if _is_wildcard_node(n) else None
        self._push_undo("chg_atom", (nid, old_el, new_el, old_w, new_w_store, old_ab, new_ab))
        self._after_sketch_edit()

    def _edit_wildcard_dialog(self, hit: dict[str, Any]) -> None:
        d = WildcardElementsDialog(_normalize_wildcard_elements(hit), self)
        if d.exec_() != QDialog.Accepted:
            return
        sel = d.selected_elements()
        if not sel:
            QMessageBox.warning(self, "Wildcard", "Select at least one element.")
            return
        self._mutate_atom_element(hit, WILDCARD_ELEMENT, sel)

    def _open_edit_atom_dialog(self, hit: dict[str, Any]) -> None:
        if hit.get("abbrev"):
            hint = str(hit["abbrev"])
        elif _is_wildcard_node(hit):
            hint = "*"
        else:
            hint = str(hit.get("element", "C"))
        txt, ok = QInputDialog.getText(
            self,
            "Edit Atom",
            "Element, contracted group, R-group, or * (e.g. C, N, CF3, Ph, R1, R2, *):",
            text=hint,
        )
        if not ok:
            return
        parsed = parse_edit_atom_input(txt)
        if parsed is None:
            QMessageBox.warning(
                self,
                "Edit Atom",
                "Unknown symbol. Use an element, a contracted label (CF3, Ph, OMe, …), R1, R2, or *.",
            )
            return
        new_el, wels, abbrev = parsed
        self._mutate_atom_element(hit, new_el, wels, abbrev=abbrev)

    @staticmethod
    def _parse_formal_charge_text(raw: str) -> int | None:
        """Return integer formal charge, or 0 for neutral, or None if invalid."""
        s = (raw or "").strip().replace("−", "-")
        if s in ("", "none", "None", "neutral", "0"):
            return 0
        if s.startswith("+"):
            s = s[1:]
        try:
            v = int(s, 10)
        except ValueError:
            return None
        if v < -12 or v > 12:
            return None
        return v

    def _open_edit_formal_charge_dialog(self, hit: dict[str, Any]) -> None:
        nid = hit["id"]
        n = next((x for x in self.nodes if x["id"] == nid), None)
        if n is None:
            return
        cur = int(self._formal_charge(n))
        hint = str(cur) if cur != 0 else "0"
        txt, ok = QInputDialog.getText(
            self,
            "Edit Formal Charge",
            "Formal charge (integer). Examples: 0, 1, -1, +2, -3 (neutral uses 0):",
            text=hint,
        )
        if not ok:
            return
        new_q = self._parse_formal_charge_text(txt)
        if new_q is None:
            QMessageBox.warning(
                self,
                "Formal charge",
                "Enter an integer between -12 and +12 (e.g. 0, -2, +3).",
            )
            return
        if new_q == cur:
            return
        old = int(self._formal_charge(n))
        if new_q == 0:
            n.pop("charge", None)
        else:
            n["charge"] = new_q
        self._push_undo("chg_charge", (nid, old, new_q))
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)

    def _selection_fragment_ids(self) -> set[int]:
        return self._atoms_for_selection_move()

    def _serialize_selection_fragment(self) -> dict[str, Any] | None:
        ids = self._selection_fragment_ids()
        if not ids:
            return None
        cx = cy = 0.0
        for i in ids:
            n = next((x for x in self.nodes if x["id"] == i), None)
            if n:
                cx += n["pos"].x()
                cy += n["pos"].y()
        nlen = max(len(ids), 1)
        cx /= nlen
        cy /= nlen
        nodes_j: list[dict[str, Any]] = []
        for old_id in sorted(ids):
            n = next((x for x in self.nodes if x["id"] == old_id), None)
            if not n:
                continue
            ent: dict[str, Any] = {
                "old_id": old_id,
                "element": n["element"],
                "rx": n["pos"].x() - cx,
                "ry": n["pos"].y() - cy,
                "charge": self._formal_charge(n),
            }
            if _is_wildcard_node(n):
                ent["wildcard_els"] = list(_normalize_wildcard_elements(n))
            nodes_j.append(ent)
        bonds_j: list[list[int]] = []
        for b in self.bonds:
            a, b0, o, s = _bond_unpack(b)
            if a in ids and b0 in ids:
                bonds_j.append([int(a), int(b0), int(o), int(s)])
        stereo_labels = sorted(int(x) for x in (ids & self._stereo_label_node_ids))
        return {"nodes": nodes_j, "bonds": bonds_j, "stereo_labels": stereo_labels}

    def copy_selection_to_clipboard(self) -> bool:
        if not self.select_mode:
            self._report_status("Turn on Select, then pick atoms to copy.")
            return False
        frag = self._serialize_selection_fragment()
        if not frag or not frag.get("nodes"):
            self._report_status("Nothing selected to copy.")
            return False
        blob = CLIPBOARD_PREFIX + json.dumps(frag, separators=(",", ":"))
        QApplication.clipboard().setText(blob)
        self._report_status(f"Copied {_count_label(len(frag['nodes']), 'atom')}.")
        return True

    def _clipboard_sketch_fragment(self) -> dict[str, Any] | None:
        text = QApplication.clipboard().text()
        if not text.startswith(CLIPBOARD_PREFIX):
            return None
        try:
            frag = json.loads(text[len(CLIPBOARD_PREFIX) :])
        except Exception:
            return None
        if not isinstance(frag, dict) or "nodes" not in frag:
            return None
        return frag

    def clipboard_has_sketch_fragment(self) -> bool:
        frag = self._clipboard_sketch_fragment()
        return bool(frag and frag.get("nodes"))

    def copy_selected_as_smiles_to_clipboard(self) -> bool:
        """Copy SMILES/SMARTS of the current selection to the system clipboard."""
        smi = self.to_smiles_selected()
        if not smi:
            self._report_status("Could not copy the selection as SMILES.")
            return False
        QApplication.clipboard().setText(smi)
        self._report_status("Copied selected SMILES.")
        return True

    def _paste_fragment_payload(self, frag: dict[str, Any], anchor: QPoint) -> None:
        old_to_new: dict[int, int] = {}
        new_ids: list[int] = []
        ax, ay = float(anchor.x()), float(anchor.y())
        for ent in frag["nodes"]:
            oid = int(ent["old_id"])
            nid = self.next_id
            self.next_id += 1
            old_to_new[oid] = nid
            ch = int(ent.get("charge", 0) or 0)
            el = str(ent["element"])
            node: dict[str, Any] = {
                "id": nid,
                "pos": QPoint(int(ax + float(ent["rx"])), int(ay + float(ent["ry"]))),
                "element": el,
            }
            if el == WILDCARD_ELEMENT:
                node["element"] = WILDCARD_ELEMENT
                raw = ent.get("wildcard_els") or DEFAULT_WILDCARD_ELEMENTS
                clean = [str(x).strip() for x in raw if str(x).strip() in WILDCARD_ELEMENT_CHOICES]
                node["wildcard_els"] = clean or list(DEFAULT_WILDCARD_ELEMENTS)
            if ch:
                node["charge"] = ch
            self.nodes.append(node)
            new_ids.append(nid)
        bi0 = len(self.bonds)
        for brec in frag.get("bonds", []):
            if not isinstance(brec, (list, tuple)) or len(brec) < 2:
                continue
            oa, ob = int(brec[0]), int(brec[1])
            o = int(brec[2])
            s = int(brec[3]) if len(brec) > 3 else 0
            na, nb = old_to_new.get(oa), old_to_new.get(ob)
            if na is None or nb is None:
                continue
            self.bonds.append(_bond_make(na, nb, o, s))
        for oid in frag.get("stereo_labels", []):
            try:
                oi = int(oid)
            except (TypeError, ValueError):
                continue
            nid = old_to_new.get(oi)
            if nid is not None:
                self._stereo_label_node_ids.add(nid)
        self._push_undo(
            "paste_group",
            {"new_ids": new_ids, "fragment": frag, "anchor": [anchor.x(), anchor.y()]},
        )
        self.selected_nodes = list(new_ids)
        self.selected_bond_indices = set(range(bi0, len(self.bonds)))
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)

    def paste_from_clipboard(self, anchor: QPoint | None = None) -> bool:
        pt = anchor if anchor is not None else self.rect().center()
        before = len(self.nodes)
        frag = self._clipboard_sketch_fragment()
        if frag:
            self._paste_fragment_payload(frag, pt)
        else:
            text = QApplication.clipboard().text() or ""
            mol = self._mol_from_clipboard_text(text)
            if mol is None or not self.append_mol_at(mol, pt):
                self._report_status("Clipboard has no structure to paste.")
                return False
        added = len(self.nodes) - before
        if added <= 0:
            self._report_status("Clipboard has no structure to paste.")
            return False
        self._report_status(f"Pasted {_count_label(added, 'atom')}.")
        self._remember_selection()
        return True

    def clipboard_has_pastable_structure(self) -> bool:
        """True when the clipboard holds a sketch fragment, a molfile, or SMILES."""
        if self.clipboard_has_sketch_fragment():
            return True
        text = QApplication.clipboard().text() or ""
        return self._mol_from_clipboard_text(text) is not None

    @staticmethod
    def _mol_from_clipboard_text(text: str):
        from molmanager.chem.molecule_conversion import looks_like_mol_block

        raw = (text or "").strip()
        if not raw or raw.startswith("MOLMANAGER_SKETCHCLIP:"):
            return None
        if looks_like_mol_block(raw):
            mol = Chem.MolFromMolBlock(raw)
            if mol is not None and mol.GetNumAtoms() > 0:
                return mol
        first = raw.splitlines()[0].strip()
        if not first or len(first) > 4000 or " " in first:
            return None
        mol = Chem.MolFromSmiles(first)
        if mol is not None and mol.GetNumAtoms() > 0:
            return mol
        return None

    def copy_molblock_to_clipboard(self) -> bool:
        """Copy a molfile of the selection, or of the whole sketch when nothing is selected."""
        ids = self._selection_fragment_ids() or {int(n["id"]) for n in self.nodes}
        if not ids:
            self._report_status("Nothing to copy as a molfile.")
            return False
        mol = self._mol_from_node_ids(ids)
        if mol is None or mol.GetNumAtoms() == 0:
            self._report_status("Nothing to copy as a molfile.")
            return False
        try:
            block = Chem.MolToMolBlock(mol)
        except Exception:
            self._report_status("Could not copy the molfile.")
            return False
        if not block:
            self._report_status("Could not copy the molfile.")
            return False
        QApplication.clipboard().setText(block)
        self._report_status(f"Copied molfile ({_count_label(mol.GetNumAtoms(), 'atom')}).")
        return True

    def copy_depiction_png_to_clipboard(self) -> bool:
        """Copy a PNG of the depiction scene, without selection chrome."""
        from PyQt5.QtCore import QRectF
        from PyQt5.QtGui import QImage

        from molmanager.table.depiction_painter import light_palette, paint_scene

        scene = self.depiction_scene_for_canvas()
        if scene is None:
            self._report_status("Could not copy the image.")
            return False
        image = QImage(640, 480, QImage.Format_ARGB32)
        image.fill(Qt.white)
        painter = QPainter(image)
        try:
            paint_scene(painter, scene, QRectF(0, 0, 640, 480), light_palette(), line_width_px=1.6)
        finally:
            painter.end()
        QApplication.clipboard().setImage(image)
        self._report_status("Copied image.")
        return True

    def arm_contracted_label(self, raw: str) -> bool:
        """Contract *raw* onto the hovered or sole selected atom, or arm the next click."""
        from .contracted_labels import lookup_contracted_label

        label = lookup_contracted_label(raw)
        if label is None:
            return False
        target = self._abbrev_target_node()
        if target is not None:
            self._mutate_atom_element(target, label.element, None, abbrev=label.display)
            self.armed_abbrev = None
            self._report_status(f"Contracted {label.display}.")
            return True
        self.armed_abbrev = label.display
        self._report_status(f"{label.display} armed. Click an atom or empty canvas.")
        return True

    def _abbrev_target_node(self) -> dict[str, Any] | None:
        if isinstance(self.hover, int):
            found = next((n for n in self.nodes if int(n["id"]) == int(self.hover)), None)
            if found is not None:
                return found
        if len(self.selected_nodes) == 1:
            nid = int(self.selected_nodes[0])
            return next((n for n in self.nodes if int(n["id"]) == nid), None)
        return None

    def _apply_armed_abbrev(self, pt: QPoint) -> None:
        from .contracted_labels import lookup_contracted_label

        label = lookup_contracted_label(self.armed_abbrev or "")
        self.armed_abbrev = None
        if label is None:
            return
        hit = self._hit_node(pt)
        if hit is not None:
            self._mutate_atom_element(hit, label.element, None, abbrev=label.display)
            self._report_status(f"Contracted {label.display}.")
            return
        nid = self.next_id
        self.next_id += 1
        node = {
            "id": nid,
            "pos": QPoint(pt.x(), pt.y()),
            "element": label.element,
            "abbrev": label.display,
        }
        self.nodes.append(node)
        self._push_undo("add_node", node)
        self._after_sketch_edit()
        self._report_status(f"Placed {label.display}.")

    def _add_copy_paste_menu_actions(self, menu: QMenu, *, paste_anchor: QPoint) -> None:
        """Copy / Paste for the current selection, then a divider (context menus)."""
        act_copy = QAction("Copy", self)
        act_copy.setToolTip(
            "Copy the selected atoms and bonds so they can be pasted on the canvas."
        )
        act_copy.setEnabled(bool(self.select_mode and self._selection_fragment_ids()))
        act_copy.triggered.connect(self.copy_selection_to_clipboard)
        menu.addAction(act_copy)
        act_paste = QAction("Paste", self)
        act_paste.setToolTip("Paste a sketch fragment, molfile, or SMILES at the click location.")
        act_paste.setEnabled(self.clipboard_has_pastable_structure())
        anchor = QPoint(paste_anchor)
        act_paste.triggered.connect(lambda _=False, pt=anchor: self.paste_from_clipboard(pt))
        menu.addAction(act_paste)
        menu.addSeparator()

    def clear(self, *, push_undo: bool = True):
        had_sketch = bool(self.nodes or self.bonds or self.reaction_arrow is not None)
        if push_undo and had_sketch:
            self._push_undo("clear_sketch", self._snapshot_sketch_state())
        self.nodes = []
        self.bonds = []
        self.next_id = 0
        self.sel = None
        self.selected_nodes = []
        self.selected_bond_indices = set()
        self.reaction_arrow = None
        self.selected_reaction_arrow = False
        self._arrow_dragging = False
        self._arrow_drag_start = None
        self._arrow_drag_pos = None
        self._selection_rect = None
        self._selecting = False
        self._select_start = None
        self._lasso_points = []
        self._release_marquee_mouse_grab_if_any()
        self._chiral_center_ids = set()
        self._chiral_stereo_issue_ids = set()
        self._stereo_cip_by_node_id = {}
        self._alkene_ez_by_bond_index = {}
        self._stereo_label_node_ids.clear()
        self._clear_salt_bundle()
        self._last_selection_status = ((), (), False)
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)
        if push_undo and had_sketch:
            self._report_status("Sketch cleared.")

    def _median_bond_length_sketch_px(self) -> float | None:
        """Median Euclidean bond length in current sketch pixel coordinates."""
        if not self.bonds:
            return None
        pos = {n["id"]: n["pos"] for n in self.nodes}
        lens: list[float] = []
        for b in self.bonds:
            a, bj, _, __ = _bond_unpack(b)
            pa, pb = pos.get(a), pos.get(bj)
            if pa is None or pb is None:
                continue
            lens.append(math.hypot(float(pa.x() - pb.x()), float(pa.y() - pb.y())))
        if not lens:
            return None
        lens.sort()
        return float(lens[len(lens) // 2])

    def fit_sketch_to_viewport(
        self,
        margin: int | None = None,
        max_scale: float = 5.0,
        min_scale: float = 0.06,
        *,
        refresh: bool = True,
    ) -> bool:
        """
        Uniformly scale and translate the sketch so all atoms fit inside the widget rect with margin.
        Does not record undo. Used by View → Fit Structure and ``ensure_sketch_fits_viewport``.

        Returns True if positions were scaled/translated; False if unchanged.
        """
        if not self.nodes and self.reaction_arrow is None:
            return False
        r = self.rect()
        rw, rh = r.width(), r.height()
        if rw < 48 or rh < 48:
            return False
        pad = int(self.radius * 1.5)
        xs = [n["pos"].x() for n in self.nodes]
        ys = [n["pos"].y() for n in self.nodes]
        if self.reaction_arrow is not None:
            a, b = self.reaction_arrow
            xs.extend([a.x(), b.x()])
            ys.extend([a.y(), b.y()])
        if not xs:
            return False
        minx = float(min(xs)) - pad
        maxx = float(max(xs)) + pad
        miny = float(min(ys)) - pad
        maxy = float(max(ys)) + pad
        bw = max(maxx - minx, 40.0)
        bh = max(maxy - miny, 40.0)
        if margin is None:
            margin = max(48, min(rw, rh) // 12)
        avail_w = max(float(rw - 2 * margin), 60.0)
        avail_h = max(float(rh - 2 * margin), 60.0)
        scale = min(avail_w / bw, avail_h / bh)
        scale = max(min(scale, max_scale), min_scale)
        tcx = float(r.center().x())
        tcy = float(r.center().y())
        mx = 0.5 * (minx + maxx)
        my = 0.5 * (miny + maxy)
        changed = False
        for n in self.nodes:
            x, y = float(n["pos"].x()), float(n["pos"].y())
            nx = int(round((x - mx) * scale + tcx))
            ny = int(round((y - my) * scale + tcy))
            if n["pos"].x() != nx or n["pos"].y() != ny:
                changed = True
            n["pos"] = QPoint(nx, ny)
        if self.reaction_arrow is not None:
            a, b = self.reaction_arrow
            na = QPoint(
                int(round((float(a.x()) - mx) * scale + tcx)),
                int(round((float(a.y()) - my) * scale + tcy)),
            )
            nb = QPoint(
                int(round((float(b.x()) - mx) * scale + tcx)),
                int(round((float(b.y()) - my) * scale + tcy)),
            )
            if a != na or b != nb:
                changed = True
            self.reaction_arrow = (na, nb)
        if not changed and abs(scale - 1.0) < 1e-9:
            return False
        self._view_scale = 1.0
        self._view_pan = QPointF(0.0, 0.0)
        self._refresh_sketch_draw_metrics()
        if refresh:
            self._after_sketch_edit(notify=True, notify_if_valence_failed=True)
        else:
            self.update()
        return True

    def ensure_sketch_fits_viewport(
        self, *, margin: int | None = None, refresh: bool = True
    ) -> bool:
        """
        If any atom lies outside the canvas (with margin), scale/center so the whole sketch fits.

        Does not enlarge small sketches — only shrinks/translates when needed. Safe after
        imports, Clean Up, and large template drops.
        """
        if not self.nodes:
            return False
        r = self.rect()
        rw, rh = r.width(), r.height()
        if rw < 48 or rh < 48:
            return False
        pad = int(max(self.radius * 1.5, 8))
        if margin is None:
            margin = max(36, min(rw, rh) // 16)
        xs = [n["pos"].x() for n in self.nodes]
        ys = [n["pos"].y() for n in self.nodes]
        minx, maxx = float(min(xs)) - pad, float(max(xs)) + pad
        miny, maxy = float(min(ys)) - pad, float(max(ys)) + pad
        inner = r.adjusted(margin, margin, -margin, -margin)
        if (
            minx >= inner.left()
            and maxx <= inner.right()
            and miny >= inner.top()
            and maxy <= inner.bottom()
        ):
            return False
        return self.fit_sketch_to_viewport(margin=margin, refresh=refresh)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self.nodes:
            self.ensure_sketch_fits_viewport(refresh=False)

    def center_sketch_in_viewport(self, push_undo: bool = True) -> None:
        """Translate all atoms so the sketch bounding box is centered in the widget (undoable)."""
        if not self.nodes:
            return
        r = self.rect()
        if r.width() < 8 or r.height() < 8:
            return
        xs = [n["pos"].x() for n in self.nodes]
        ys = [n["pos"].y() for n in self.nodes]
        mx = 0.5 * (min(xs) + max(xs))
        my = 0.5 * (min(ys) + max(ys))
        tcx = float(r.center().x())
        tcy = float(r.center().y())
        dx = int(round(tcx - mx))
        dy = int(round(tcy - my))
        if dx == 0 and dy == 0:
            return
        moves: list[tuple[int, QPoint, QPoint]] = []
        if push_undo:
            for n in self.nodes:
                oid = n["id"]
                op = QPoint(n["pos"].x(), n["pos"].y())
                np = QPoint(op.x() + dx, op.y() + dy)
                moves.append((oid, op, np))
        for n in self.nodes:
            n["pos"] = QPoint(n["pos"].x() + dx, n["pos"].y() + dy)
        if push_undo and moves:
            self._push_undo("move_nodes", moves)
        self._after_sketch_edit(notify=True, notify_if_valence_failed=True)

    def zoom_about_viewport_center(self, factor: float, push_undo: bool = False) -> None:
        """Zoom about the widget center. Atoms stay in model space."""
        del push_undo
        self.zoom_about_widget_point(factor, self.rect().center())

    def zoom_about_widget_point(self, factor: float, widget_pt: QPoint) -> None:
        """
        Zoom the view about a widget pixel so the model point under it stays put.

        Does not move atoms or record undo.
        """
        if abs(factor - 1.0) < 1e-6:
            return
        factor = float(factor)
        if factor <= 0:
            return
        old = float(self._view_scale)
        new = max(0.08, min(12.0, old * factor))
        actual = new / old if old else 1.0
        center = self._view_center()
        pan = self._view_pan
        wx = float(widget_pt.x()) - center.x()
        wy = float(widget_pt.y()) - center.y()
        self._view_pan = QPointF(
            wx * (1.0 - actual) + pan.x() * actual, wy * (1.0 - actual) + pan.y() * actual
        )
        self._view_scale = new
        self.update()

    def pan_by_widget_delta(self, dx: float, dy: float) -> None:
        """Shift the view by widget pixels. Atoms stay in model space."""
        pan = self._view_pan
        self._view_pan = QPointF(pan.x() + float(dx), pan.y() + float(dy))
        self.update()

    def active_tool_name(self) -> str:
        """Short name of the armed tool, for the footer."""
        if self.armed_abbrev:
            return self.armed_abbrev
        if self.chain_mode:
            return "Chain"
        if self.erase_mode:
            return "Erase"
        if self.text_mode:
            return "Text"
        if self.reaction_arrow_mode:
            return "Reaction arrow"
        if self.select_mode:
            return "Lasso" if self.select_tool == "lasso" else "Select"
        if self.active_template:
            return str(self.active_template)
        element = self.place_element or "C"
        return f"Draw {element}"

    def sketch_formula(self) -> str | None:
        """Molecular formula when the sketch is one fragment RDKit can describe."""
        if not self.nodes:
            return None
        components = self.connected_components()
        if len(components) != 1:
            return None
        mol = self._mol_from_node_ids(set(components[0]))
        if mol is None or mol.GetNumAtoms() == 0:
            return None
        try:
            from rdkit.Chem.rdMolDescriptors import CalcMolFormula

            mol.UpdatePropertyCache(strict=False)
            return str(CalcMolFormula(mol))
        except Exception:
            return None

    def nudge_selection(self, dx: int, dy: int) -> bool:
        """Move the selection by model pixels. One undo step."""
        ids = self._atoms_for_selection_move()
        if not ids or (dx == 0 and dy == 0):
            return False
        moves: list[tuple[int, QPoint, QPoint]] = []
        for node in self.nodes:
            if int(node["id"]) not in ids:
                continue
            old = QPoint(node["pos"].x(), node["pos"].y())
            new = QPoint(old.x() + int(dx), old.y() + int(dy))
            node["pos"] = new
            moves.append((int(node["id"]), old, new))
        if not moves:
            return False
        self._push_undo("move_nodes", moves)
        self._after_sketch_edit()
        return True

    def _can_group_selection(self) -> bool:
        sel = self._selected_node_set()
        if len(sel) < 2:
            return False
        n_touch = sum(1 for c in self.connected_components() if c & sel)
        return n_touch >= 2

    def _add_group_action_if_applicable(self, menu: QMenu) -> None:
        if self.select_mode and self._can_group_selection():
            menu.addSeparator()
            act = QAction("Group selection for export", self)
            act.triggered.connect(self._run_group_selection_menu)
            menu.addAction(act)

    def _add_cleanup_selected_action(self, menu: QMenu, *, hit_ids: set[int] | None = None) -> None:
        """Add Clean Up Selected when the selection includes *hit_ids* (if given)."""
        ids = self._atoms_for_selection_move()
        if len(ids) < 2:
            return
        if hit_ids is not None and not (ids & hit_ids):
            return
        menu.addSeparator()
        act = QAction("Clean Up Selected", self)
        act.setToolTip("Re-layout only the selected atoms with the same layout as Clean Up.")
        act.triggered.connect(self._menu_cleanup_selected)
        menu.addAction(act)

    def _menu_cleanup_selected(self) -> None:
        ok = self.cleanup_layout_2d_selected()
        dlg = self._sketcher_dialog_if()
        parent_w = dlg if dlg is not None else self
        if not ok:
            QMessageBox.information(
                parent_w,
                "Clean Up Selected",
                "Could not re-layout the selection. Select at least two connected atoms, "
                "or try fixing valence issues first.",
            )
            return
        if dlg is not None:
            dlg._update_sketch_status()
        issues = self.refresh_iupac_validation()
        if issues:
            from molmanager.ui.sketcher.iupac_validate import format_iupac_issues

            summary = format_iupac_issues(issues, limit=5)
            QMessageBox.information(
                parent_w,
                "Clean Up Selected",
                f"Selection layout updated. IUPAC notes:\n{summary}",
            )
            self.update()

    def _add_copy_selected_smiles_action(
        self, menu: QMenu, *, hit_ids: set[int] | None = None
    ) -> None:
        """Add Copy Selected as SMILES when the selection includes *hit_ids* (if given)."""
        ids = self._atoms_for_selection_move()
        if not ids:
            return
        if hit_ids is not None and not (ids & hit_ids):
            return
        menu.addSeparator()
        act = QAction("Copy Selected as SMILES", self)
        act.setToolTip("Copy the SMILES (or SMARTS) of the current selection to the clipboard.")
        act.triggered.connect(self._menu_copy_selected_smiles)
        menu.addAction(act)

    def _menu_copy_selected_smiles(self) -> None:
        if self.copy_selected_as_smiles_to_clipboard():
            return
        dlg = self._sketcher_dialog_if()
        parent_w = dlg if dlg is not None else self
        QMessageBox.warning(
            parent_w,
            "Copy Selected as SMILES",
            "Could not copy — no valid SMILES/SMARTS for the selection.",
        )

    def _selection_transform_atom_ids(self) -> set[int]:
        """Atoms moved by selection transforms (explicit selection + selected-bond endpoints)."""
        if not self.select_mode:
            return set()
        return self._atoms_for_selection_move()

    def _selection_centroid(self, ids: set[int]) -> tuple[float, float] | None:
        pts: list[QPoint] = []
        for nid in ids:
            n = next((x for x in self.nodes if x["id"] == nid), None)
            if n is not None:
                pts.append(n["pos"])
        if not pts:
            return None
        return (
            sum(float(p.x()) for p in pts) / len(pts),
            sum(float(p.y()) for p in pts) / len(pts),
        )

    def _apply_selection_position_moves(
        self, ids: set[int], new_pos_by_id: dict[int, QPoint]
    ) -> bool:
        moves: list[tuple[int, QPoint, QPoint]] = []
        for nid in ids:
            n = next((x for x in self.nodes if x["id"] == nid), None)
            if n is None:
                continue
            newp = new_pos_by_id.get(nid)
            if newp is None:
                continue
            oldp = QPoint(n["pos"].x(), n["pos"].y())
            if oldp.x() == newp.x() and oldp.y() == newp.y():
                continue
            n["pos"] = newp
            moves.append((nid, oldp, newp))
        if not moves:
            return False
        self._push_undo("move_nodes", moves)
        self._after_sketch_edit()
        return True

    def _commit_carbon_chain(self, anchor_id: int | None, points: list[QPoint]) -> bool:
        """Add zigzag carbons. *anchor_id* is the existing atom the first bond leaves, if any."""
        if not points:
            return False
        stored_nodes: list[dict[str, Any]] = []
        stored_bonds: list[tuple[int, int, int, int]] = []
        prev = anchor_id
        for point in points:
            nid = self.next_id
            self.next_id += 1
            node = {"id": nid, "pos": QPoint(point.x(), point.y()), "element": "C"}
            self.nodes.append(node)
            stored_nodes.append({"id": nid, "pos": QPoint(point.x(), point.y()), "element": "C"})
            if prev is not None:
                bond = _bond_make(int(prev), nid, 1, BOND_STEREO_PLAIN)
                self.bonds.append(bond)
                stored_bonds.append(bond)
            prev = nid
        self._push_undo(
            "add_chain",
            {
                "nodes": stored_nodes,
                "bonds": stored_bonds,
                "new_ids": [int(n["id"]) for n in stored_nodes],
            },
        )
        self._after_sketch_edit()
        self._report_status(f"Added {_count_label(len(stored_nodes), 'atom')}.")
        return True

    def preview_carbon_chain(
        self, anchor_id: int | None, press: QPoint, target: QPoint
    ) -> list[QPoint]:
        """Ghost carbons for a chain drag. Includes a carbon at *press* when there is no anchor."""
        med = float(getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX)
        if anchor_id is None:
            origin = (float(press.x()), float(press.y()))
            extra = chain_points(origin, (float(target.x()), float(target.y())), med)
            points = [QPoint(press.x(), press.y())]
            points.extend(QPoint(int(round(x)), int(round(y))) for x, y in extra)
            return points
        anchor = next((n for n in self.nodes if int(n["id"]) == int(anchor_id)), None)
        if anchor is None:
            return []
        origin = (float(anchor["pos"].x()), float(anchor["pos"].y()))
        extra = chain_points(origin, (float(target.x()), float(target.y())), med)
        if extra:
            return [QPoint(int(round(x)), int(round(y))) for x, y in extra]
        ux, uy = self._compute_extension_vector(int(anchor_id), snap=True, new_bond_order=1)
        return [
            QPoint(
                int(round(origin[0] + ux * med)),
                int(round(origin[1] + uy * med)),
            )
        ]

    def finish_carbon_chain(self, anchor_id: int | None, press: QPoint, target: QPoint) -> bool:
        """Commit the chain preview as one undo step."""
        return self._commit_carbon_chain(
            anchor_id, self.preview_carbon_chain(anchor_id, press, target)
        )

    def selection_frame_widget(self) -> tuple[QRect, QPoint | None] | None:
        """Widget-space selection frame and rotate handle, or ``None`` when nothing is selected."""
        ids = {int(i) for i in self.selected_nodes}
        nodes = [n for n in self.nodes if int(n["id"]) in ids]
        if not nodes or self._selecting:
            return None
        mapped = [self._model_point_to_widget(n["pos"]) for n in nodes]
        pad = 16
        left = min(p.x() for p in mapped) - pad
        right = max(p.x() for p in mapped) + pad
        top = min(p.y() for p in mapped) - pad
        bottom = max(p.y() for p in mapped) + pad
        rect = QRect(QPoint(left, top), QPoint(right, bottom))
        handle = None
        if len(nodes) >= 2:
            handle = QPoint(int(round((left + right) / 2.0)), top - 12)
        return rect, handle

    def hit_rotate_handle(self, widget_pt: QPoint) -> bool:
        """True when *widget_pt* is on the selection rotate handle."""
        if not self.select_mode or self._selecting:
            return False
        framed = self.selection_frame_widget()
        if framed is None or framed[1] is None:
            return False
        handle = framed[1]
        dx = widget_pt.x() - handle.x()
        dy = widget_pt.y() - handle.y()
        return dx * dx + dy * dy <= 14 * 14

    def begin_selection_rotate(self, model_pt: QPoint) -> None:
        ids = self._selection_transform_atom_ids()
        cen = self._selection_centroid(ids)
        if cen is None or len(ids) < 2:
            return
        self._rotating = True
        self._rotate_orig = {
            int(n["id"]): QPoint(n["pos"].x(), n["pos"].y())
            for n in self.nodes
            if int(n["id"]) in ids
        }
        self._rotate_cen = cen
        self._rotate_start = math.atan2(float(model_pt.y()) - cen[1], float(model_pt.x()) - cen[0])

    def update_selection_rotate(self, model_pt: QPoint) -> None:
        if not self._rotating or self._rotate_cen is None:
            return
        cx, cy = self._rotate_cen
        delta = math.atan2(float(model_pt.y()) - cy, float(model_pt.x()) - cx) - self._rotate_start
        ca, sa = math.cos(delta), math.sin(delta)
        for nid, old in self._rotate_orig.items():
            node = next((n for n in self.nodes if int(n["id"]) == nid), None)
            if node is None:
                continue
            dx = float(old.x()) - cx
            dy = float(old.y()) - cy
            node["pos"] = QPoint(
                int(round(cx + dx * ca + dy * sa)),
                int(round(cy - dx * sa + dy * ca)),
            )
        self.update()

    def end_selection_rotate(self) -> None:
        if not self._rotating:
            return
        moves: list[tuple[int, QPoint, QPoint]] = []
        for nid, old in self._rotate_orig.items():
            node = next((n for n in self.nodes if int(n["id"]) == nid), None)
            if node is None:
                continue
            new = QPoint(node["pos"].x(), node["pos"].y())
            if old.x() != new.x() or old.y() != new.y():
                moves.append((nid, old, new))
        self._rotating = False
        self._rotate_orig = {}
        self._rotate_cen = None
        if moves:
            self._push_undo("move_nodes", moves)
            self._after_sketch_edit()
        else:
            self.update()

    def rotate_selection(self, degrees: float) -> bool:
        """Rotate the current selection about its centroid (degrees, counterclockwise on screen)."""
        ids = self._selection_transform_atom_ids()
        if len(ids) < 2:
            return False
        cen = self._selection_centroid(ids)
        if cen is None:
            return False
        cx, cy = cen
        # Screen Y increases downward: use [cos sin; −sin cos] for visual counterclockwise.
        ang = math.radians(float(degrees))
        ca, sa = math.cos(ang), math.sin(ang)
        new_pos: dict[int, QPoint] = {}
        for nid in ids:
            n = next((x for x in self.nodes if x["id"] == nid), None)
            if n is None:
                continue
            dx = float(n["pos"].x()) - cx
            dy = float(n["pos"].y()) - cy
            nx = cx + dx * ca + dy * sa
            ny = cy - dx * sa + dy * ca
            new_pos[nid] = QPoint(int(round(nx)), int(round(ny)))
        return self._apply_selection_position_moves(ids, new_pos)

    def flip_selection_horizontal(self) -> bool:
        """Mirror the selection across a vertical axis through its centroid."""
        ids = self._selection_transform_atom_ids()
        if len(ids) < 2:
            return False
        cen = self._selection_centroid(ids)
        if cen is None:
            return False
        cx, _cy = cen
        new_pos = {
            nid: QPoint(int(round(2.0 * cx - float(n["pos"].x()))), int(n["pos"].y()))
            for nid in ids
            for n in (next((x for x in self.nodes if x["id"] == nid), None),)
            if n is not None
        }
        return self._apply_selection_position_moves(ids, new_pos)

    def flip_selection_vertical(self) -> bool:
        """Mirror the selection across a horizontal axis through its centroid."""
        ids = self._selection_transform_atom_ids()
        if len(ids) < 2:
            return False
        cen = self._selection_centroid(ids)
        if cen is None:
            return False
        _cx, cy = cen
        new_pos = {
            nid: QPoint(int(n["pos"].x()), int(round(2.0 * cy - float(n["pos"].y()))))
            for nid in ids
            for n in (next((x for x in self.nodes if x["id"] == nid), None),)
            if n is not None
        }
        return self._apply_selection_position_moves(ids, new_pos)

    def _open_rotate_selection_dialog(self) -> None:
        ids = self._selection_transform_atom_ids()
        if len(ids) < 2:
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("Rotate")
        form = QFormLayout()
        cw = QDoubleSpinBox()
        cw.setRange(0.0, 3600.0)
        cw.setDecimals(1)
        cw.setSuffix(" °")
        cw.setValue(0.0)
        ccw = QDoubleSpinBox()
        ccw.setRange(0.0, 3600.0)
        ccw.setDecimals(1)
        ccw.setSuffix(" °")
        ccw.setValue(0.0)
        form.addRow("Rotation (Clockwise)", cw)
        form.addRow("Rotation (Counterclockwise)", ccw)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        root = QVBoxLayout(dlg)
        root.addLayout(form)
        root.addWidget(buttons)
        if dlg.exec_() != QDialog.Accepted:
            return
        # rotate_selection is counterclockwise; clockwise is the opposite sense.
        degrees = float(ccw.value()) - float(cw.value())
        if abs(degrees) < 1e-9:
            return
        self.rotate_selection(degrees)

    def _add_selection_transform_actions(
        self, menu: QMenu, *, hit_ids: set[int] | None = None
    ) -> None:
        """Add Rotate / Flip actions when a multi-atom selection includes *hit_ids*."""
        ids = self._selection_transform_atom_ids()
        if len(ids) < 2:
            return
        if hit_ids is not None and not (ids & hit_ids):
            return
        menu.addSeparator()
        act_rot = QAction("Rotate", self)
        act_rot.setToolTip("Rotate the selected structure about its center.")
        act_rot.triggered.connect(self._open_rotate_selection_dialog)
        menu.addAction(act_rot)
        act_fv = QAction("Flip Vertical", self)
        act_fv.setToolTip("Flip the selected structure vertically.")
        act_fv.triggered.connect(self.flip_selection_vertical)
        menu.addAction(act_fv)
        act_fh = QAction("Flip Horizontally", self)
        act_fh.setToolTip("Flip the selected structure horizontally.")
        act_fh.triggered.connect(self.flip_selection_horizontal)
        menu.addAction(act_fh)

    # ---------- Placement (chain / templates) ----------
    def add_ring(
        self,
        n: int,
        center: QPoint | None = None,
        radius: int | None = None,
        elements=None,
        bond_orders=None,
        *,
        bond_length: float | None = None,
    ):
        """
        Place an *n*-membered ring with IUPAC bond lengths (GR-1.1 / GR-3.3).

        ``radius`` is legacy circumradius; when omitted, chord length equals the
        sketch median bond (or *bond_length*). Rings with n≥9 use reentrant shapes.
        """
        c = center if center is not None else self.rect().center()
        elems = elements if elements is not None else ["C"] * n
        orders = bond_orders if bond_orders is not None else [1] * n
        bl = float(
            bond_length
            if bond_length is not None and bond_length > 0
            else getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX
        )
        if radius is not None and int(radius) > 0 and n < 9:
            # Legacy path: interpret radius as circumradius (caller may pass chord-derived R).
            r = float(radius)
            from .iupac_style import iupac_ring_vertex_offset

            ang0 = iupac_ring_vertex_offset(n)
            offsets = [
                (r * math.cos(ang0 + 2 * math.pi * i / n), r * math.sin(ang0 + 2 * math.pi * i / n))
                for i in range(n)
            ]
        else:
            offsets = ring_vertex_offsets_y_up(n, bond_length=bl)
            if n >= 9:
                offsets = rotate_offsets_to_inward_heteroatoms(offsets, elems)
        ids: list[int] = []
        for i in range(n):
            dx, dy = offsets[i]
            x = int(round(c.x() + dx))
            y = int(round(c.y() - dy))  # Y-up offsets → screen Y-down
            nid = self.next_id
            self.next_id += 1
            self.nodes.append(
                {"id": nid, "pos": QPoint(x, y), "element": elems[i] if i < len(elems) else "C"}
            )
            ids.append(nid)
        for i in range(n):
            a = ids[i]
            b = ids[(i + 1) % n]
            o = orders[i] if i < len(orders) else 1
            self.bonds.append(_bond_make(a, b, o, 0))
        self.update()
        return ids

    def _compute_extension_vector(
        self, atom_id: int, *, snap: bool | None = None, new_bond_order: int | None = None
    ):
        base = next((n for n in self.nodes if n["id"] == atom_id), None)
        if base is None:
            return (1.0, 0.0)
        bx, by = base["pos"].x(), base["pos"].y()
        neigh = [
            b for b in self.bonds if _bond_unpack(b)[0] == atom_id or _bond_unpack(b)[1] == atom_id
        ]
        angles: list[float] = []
        neigh_orders: list[int] = []
        for bond in neigh:
            a, b, o, __ = _bond_unpack(bond)
            nid = b if a == atom_id else a
            nnode = next((n for n in self.nodes if n["id"] == nid), None)
            if nnode:
                ang = math.atan2(nnode["pos"].y() - by, nnode["pos"].x() - bx)
                angles.append(ang)
                neigh_orders.append(int(o))
        if not angles:
            return (1.0, 0.0)
        do_snap = self.snap_geometry if snap is None else bool(snap)
        if new_bond_order is None:
            new_bond_order, _ = self._bond_tool_order_stereo()
        new_o = int(new_bond_order)
        max_exist = max(neigh_orders) if neigh_orders else 1
        # Linear: alkyne (any triple) or allene (existing double + new double).
        prefer_linear = max_exist >= 3 or new_o >= 3 or (max_exist == 2 and new_o == 2)
        prefer_trigonal = (not prefer_linear) and (max_exist == 2 or new_o == 2)

        # GR-4.2.1: single substituent on a ring atom bisects the larger exterior angle.
        ring_atoms = self._ring_atom_ids() if hasattr(self, "_ring_atom_ids") else set()
        if (
            atom_id in ring_atoms
            and len(angles) == 2
            and not prefer_linear
            and all(
                (b if a == atom_id else a) in ring_atoms
                for bond in neigh
                for a, b, _o, _s in [_bond_unpack(bond)]
            )
        ):
            vec = exterior_ring_substituent_direction(angles)
            if vec is not None:
                if do_snap:
                    ang = snap_to_hex_grid(math.atan2(vec[1], vec[0]))
                    return (math.cos(ang), math.sin(ang))
                return vec

        if len(angles) == 1:
            neigh_ang = angles[0]
            if prefer_linear:
                ang_new = neigh_ang + math.pi
            else:
                sign = self._angle_signs.get(atom_id, 1)
                # sp2-style (~120° internal) vs sp3 tetrahedral (~109.5° internal)
                dev = math.radians(60.0) if prefer_trigonal else math.radians(180.0 - 109.47)
                ang_new = neigh_ang + math.pi - sign * dev
                self._angle_signs[atom_id] = -sign
            if do_snap:
                ang_new = snap_to_hex_grid(ang_new)
            return (math.cos(ang_new), math.sin(ang_new))
        angles_s = sorted(angles)
        max_gap = -1.0
        best_mid = 0.0
        for i in range(len(angles_s)):
            a1 = angles_s[i]
            a2 = (
                angles_s[(i + 1) % len(angles_s)]
                if i + 1 < len(angles_s)
                else angles_s[0] + 2 * math.pi
            )
            gap = a2 - a1 if a2 >= a1 else (a2 + 2 * math.pi - a1)
            if gap > max_gap:
                max_gap = gap
                best_mid = a1 + gap / 2.0
        sign = self._angle_signs.get(atom_id, 1)
        if len(angles_s) == 2:
            a1, a2 = angles_s[0], angles_s[1]
            d = (a2 - a1) % (2 * math.pi)
            d = min(d, 2 * math.pi - d)
            if prefer_linear and abs(d - math.pi) < math.radians(25):
                # Already near-linear neighbors; extend in largest gap (already mid).
                pass
            elif d < math.radians(75) and max_gap > math.radians(100):
                best_mid += sign * math.radians(15)
                self._angle_signs[atom_id] = -sign
        elif max_gap > math.radians(150):
            best_mid += sign * math.radians(25)
            self._angle_signs[atom_id] = -sign
        if do_snap:
            best_mid = snap_to_hex_grid(best_mid)
        return (math.cos(best_mid), math.sin(best_mid))

    def _activate_select_mode_from_parent(self) -> None:
        dlg = self._sketcher_dialog_if()
        if dlg is not None and hasattr(dlg, "select_btn") and hasattr(dlg, "_toggle_select"):
            dlg.select_btn.blockSignals(True)
            dlg.select_btn.setChecked(True)
            dlg.select_btn.blockSignals(False)
            dlg._toggle_select(True)
        else:
            self.select_mode = True
            self.select_tool = "box"
            self.erase_mode = False
            self.text_mode = False

    def _place_fused_template(
        self,
        name: str,
        center: QPoint | None,
        attach_to: int | None,
        fuse_bond: int | None,
        bond_length: float,
    ) -> None:
        from .fused_templates import (
            fused_template,
            screen_points_centered,
            screen_points_on_bond,
        )

        template = fused_template(name)
        if template is None:
            return
        before = self._snapshot_sketch_state()
        prefer_side = 1.0
        points: list[tuple[float, float]] | None = None
        shared: dict[int, int] = {}
        if fuse_bond is not None and 0 <= int(fuse_bond) < len(self.bonds):
            a_id, b_id, _o, _s = _bond_unpack(self.bonds[int(fuse_bond)])
            na = next((x for x in self.nodes if x["id"] == a_id), None)
            nb = next((x for x in self.nodes if x["id"] == b_id), None)
            if na is not None and nb is not None:
                ax, ay = float(na["pos"].x()), float(na["pos"].y())
                bx, by = float(nb["pos"].x()), float(nb["pos"].y())
                ring = self._ring_atom_ids() if hasattr(self, "_ring_atom_ids") else set()
                if a_id in ring and b_id in ring and hasattr(self, "_smallest_cycle_through_bond"):
                    face = self._smallest_cycle_through_bond(a_id, b_id)
                    if face:
                        cx = sum(float(x["pos"].x()) for x in self.nodes if x["id"] in face) / len(
                            face
                        )
                        cy = sum(float(x["pos"].y()) for x in self.nodes if x["id"] in face) / len(
                            face
                        )
                        mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
                        dx, dy = bx - ax, by - ay
                        px, py = -dy, dx
                        if px * (cx - mx) + py * (cy - my) > 0:
                            prefer_side = -1.0
                points = screen_points_on_bond(template, ax, ay, bx, by, prefer_side=prefer_side)
                shared = {template.fusion[0]: a_id, template.fusion[1]: b_id}
        if points is None:
            if attach_to is not None:
                base = next((n for n in self.nodes if n["id"] == attach_to), None)
                if base is None:
                    return
                ux, uy = self._compute_extension_vector(attach_to)
                span = bond_length * 2.2
                cpt = (
                    float(base["pos"].x()) + ux * span,
                    float(base["pos"].y()) + uy * span,
                )
            else:
                cpt_q = center if center is not None else self.rect().center()
                cpt = (float(cpt_q.x()), float(cpt_q.y()))
            points = screen_points_centered(template, cpt[0], cpt[1], bond_length)
        id_of: dict[int, int] = dict(shared)
        for index, (x, y) in enumerate(points):
            if index in id_of:
                continue
            nid = self.next_id
            self.next_id += 1
            self.nodes.append(
                {
                    "id": nid,
                    "pos": QPoint(int(round(x)), int(round(y))),
                    "element": template.elements[index],
                }
            )
            id_of[index] = nid
        existing = {frozenset((_bond_unpack(b)[0], _bond_unpack(b)[1])) for b in self.bonds}
        for i, j, order in template.bonds:
            ia, ib = id_of[i], id_of[j]
            if frozenset((ia, ib)) in existing:
                continue
            self.bonds.append(_bond_make(ia, ib, order, 0))
            existing.add(frozenset((ia, ib)))
        if attach_to is not None and not shared:
            nearest = min(
                id_of.values(),
                key=lambda nid: self._node_distance_sq(attach_to, nid),
            )
            pair = frozenset((attach_to, nearest))
            if pair not in existing and nearest != attach_to:
                self.bonds.append(_bond_make(attach_to, nearest, 1, 0))
        self._commit_template_placement(before)

    def _node_distance_sq(self, a_id: int, b_id: int) -> float:
        a = next((n for n in self.nodes if n["id"] == a_id), None)
        b = next((n for n in self.nodes if n["id"] == b_id), None)
        if a is None or b is None:
            return 1e18
        dx = float(a["pos"].x() - b["pos"].x())
        dy = float(a["pos"].y() - b["pos"].y())
        return dx * dx + dy * dy

    def place_template(
        self,
        name: str,
        center: QPoint | None = None,
        attach_to: int | None = None,
        radius: int | None = None,
        bond_length: int | None = None,
        *,
        fuse_bond: int | None = None,
    ):
        from .fused_templates import FUSED_TEMPLATE_SMILES

        if name in FUSED_TEMPLATE_SMILES:
            bl = float(
                bond_length
                if bond_length is not None and bond_length > 0
                else getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX
            )
            self._place_fused_template(name, center, attach_to, fuse_bond, bl)
            return
        tpl = SKETCH_RING_TEMPLATES.get(name)
        if tpl is None:
            return
        n, elems, orders = tpl
        bl = float(
            bond_length
            if bond_length is not None and bond_length > 0
            else getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX
        )
        ring_r = (
            int(round(ring_circumradius_for_bond_length(n, bl))) if radius is None else int(radius)
        )

        # --- Ortho-fusion onto an existing bond (GR-3.3.3) ---
        before = self._snapshot_sketch_state()

        if fuse_bond is not None and 0 <= int(fuse_bond) < len(self.bonds):
            a_id, b_id, _o, _s = _bond_unpack(self.bonds[int(fuse_bond)])
            na = next((x for x in self.nodes if x["id"] == a_id), None)
            nb = next((x for x in self.nodes if x["id"] == b_id), None)
            if na is None or nb is None:
                return
            ax, ay = float(na["pos"].x()), float(na["pos"].y())
            bx, by = float(nb["pos"].x()), float(nb["pos"].y())
            ring = self._ring_atom_ids() if hasattr(self, "_ring_atom_ids") else set()
            side = 1.0
            if a_id in ring and b_id in ring and hasattr(self, "_smallest_cycle_through_bond"):
                face = self._smallest_cycle_through_bond(a_id, b_id)
                if face:
                    cx = sum(float(x["pos"].x()) for x in self.nodes if x["id"] in face) / len(face)
                    cy = sum(float(x["pos"].y()) for x in self.nodes if x["id"] in face) / len(face)
                    mx, my = (ax + bx) * 0.5, (ay + by) * 0.5
                    dx, dy = bx - ax, -(by - ay)
                    px, py = -dy, dx
                    if px * (cx - mx) + py * (-(cy - my)) > 0:
                        side = -1.0
            world = fusion_ring_offsets_for_bond(
                n,
                bond_length=bl,
                ax=ax,
                ay=-ay,
                bx=bx,
                by=-by,
                prefer_side=side,
            )
            id_map = {0: a_id, 1: b_id}
            new_ids: list[int] = []
            for i in range(2, n):
                wx, wy = world[i]
                nid = self.next_id
                self.next_id += 1
                self.nodes.append(
                    {
                        "id": nid,
                        "pos": QPoint(int(round(wx)), int(round(-wy))),
                        "element": elems[i] if i < len(elems) else "C",
                    }
                )
                id_map[i] = nid
                new_ids.append(nid)
            for i in range(n):
                ia, ib = id_map[i], id_map[(i + 1) % n]
                if {ia, ib} == {a_id, b_id}:
                    continue
                o = orders[i] if i < len(orders) else 1
                bond = _bond_make(ia, ib, o, 0)
                self.bonds.append(bond)
            self._commit_template_placement(before)
            return

        if attach_to is not None:
            base = next((node for node in self.nodes if node["id"] == attach_to), None)
            if base is None:
                return
            bx, by = base["pos"].x(), base["pos"].y()
            ring_atoms = self._ring_atom_ids() if hasattr(self, "_ring_atom_ids") else set()
            ring_neigh_dirs: list[tuple[float, float]] = []
            if attach_to in ring_atoms:
                for bond in self.bonds:
                    a, b, _o, _s = _bond_unpack(bond)
                    if a != attach_to and b != attach_to:
                        continue
                    oid = b if a == attach_to else a
                    if oid not in ring_atoms:
                        continue
                    on = next((x for x in self.nodes if x["id"] == oid), None)
                    if on is None:
                        continue
                    ring_neigh_dirs.append(
                        (float(on["pos"].x() - bx), float(-(on["pos"].y() - by)))
                    )
            if len(ring_neigh_dirs) >= 2:
                offsets = spiro_second_ring_offsets_y_up(
                    n, bond_length=bl, existing_ring_neighbor_dirs=ring_neigh_dirs
                )
                id_map = {0: attach_to}
                new_ids = []
                for i in range(1, n):
                    dx, dy = offsets[i]
                    nid = self.next_id
                    self.next_id += 1
                    self.nodes.append(
                        {
                            "id": nid,
                            "pos": QPoint(int(round(bx + dx)), int(round(by - dy))),
                            "element": elems[i] if i < len(elems) else "C",
                        }
                    )
                    id_map[i] = nid
                    new_ids.append(nid)
                for i in range(n):
                    ia, ib = id_map[i], id_map[(i + 1) % n]
                    o = orders[i] if i < len(orders) else 1
                    bond = _bond_make(ia, ib, o, 0)
                    self.bonds.append(bond)
                self._commit_template_placement(before)
                return

            ux, uy = self._compute_extension_vector(attach_to)
            c_r = ring_circumradius_for_bond_length(n, bl) if n < 9 else bl * 1.6
            cpt = QPoint(int(bx + ux * (bl + c_r)), int(by + uy * (bl + c_r)))
            pre_nodes = [nid["id"] for nid in self.nodes]
            self.add_ring(n, center=cpt, elements=elems, bond_orders=orders, bond_length=bl)
            new_ids = [nid["id"] for nid in self.nodes if nid["id"] not in pre_nodes]
            if not new_ids:
                self._commit_template_placement(before)
                return
            best = None
            best_d = None
            for nid in new_ids:
                nn = next((no for no in self.nodes if no["id"] == nid), None)
                if nn:
                    d = (nn["pos"].x() - bx) ** 2 + (nn["pos"].y() - by) ** 2
                    if best_d is None or d < best_d:
                        best_d = d
                        best = nn
            if best is None:
                self._commit_template_placement(before)
                return
            bond = _bond_make(attach_to, best["id"], 1, 0)
            self.bonds.append(bond)
            self._commit_template_placement(before)
            return

        cpt = center if center is not None else self.rect().center()
        self.add_ring(
            n,
            center=cpt,
            radius=ring_r if n < 9 else None,
            elements=elems,
            bond_orders=orders,
            bond_length=bl,
        )
        self._commit_template_placement(before)

    def add_carbon_to(self, atom_id: int, bond_length: int = SKETCH_MEDIAN_BOND_PX):
        base = next((n for n in self.nodes if n["id"] == atom_id), None)
        if base is None:
            return
        bx, by = base["pos"].x(), base["pos"].y()
        order, pst = self._bond_tool_order_stereo()
        ux, uy = self._compute_extension_vector(
            atom_id,
            snap=bool(getattr(self, "snap_geometry", True)),
            new_bond_order=order,
        )
        med = float(getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX)
        bond_length = max(int(bond_length), int(round(med * 0.5)), 20)
        if getattr(self, "snap_geometry", True):
            bond_length = int(round(med))
        nx = int(bx + ux * bond_length)
        ny = int(by + uy * bond_length)

        nid = self.next_id
        self.next_id += 1
        node = {"id": nid, "pos": QPoint(nx, ny), "element": "C"}
        self.nodes.append(node)
        self.bonds.append(_bond_make(atom_id, nid, order, pst))
        self.update()

    def place_rgroup_on(self, atom_id: int, element: str) -> None:
        """Attach ``R1`` or ``R2`` to *atom_id*, or renumber an R atom that was clicked."""
        label = rgroup_label_from_element(element)
        if label is None:
            return
        element = rgroup_element(label)
        base = next((n for n in self.nodes if n["id"] == atom_id), None)
        if base is None:
            return
        if is_rgroup_node(base):
            self._mutate_atom_element(base, element, None)
            return
        for bond in self.bonds:
            a, b, _order, _stereo = _bond_unpack(bond)
            other_id = b if a == atom_id else a if b == atom_id else None
            if other_id is None:
                continue
            other = next((n for n in self.nodes if n["id"] == other_id), None)
            if (
                other is not None
                and rgroup_label_from_element(str(other.get("element") or "")) == label
            ):
                return
        bx, by = base["pos"].x(), base["pos"].y()
        ux, uy = self._compute_extension_vector(
            atom_id,
            snap=bool(getattr(self, "snap_geometry", True)),
            new_bond_order=1,
        )
        med = float(getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX)
        bond_length = max(int(round(med)), 20)
        nid = self.next_id
        self.next_id += 1
        node = {
            "id": nid,
            "pos": QPoint(int(bx + ux * bond_length), int(by + uy * bond_length)),
            "element": element,
        }
        bond = _bond_make(atom_id, nid, 1, 0)
        self.nodes.append(node)
        self.bonds.append(bond)
        self._push_undo("add_bonded_node", (node, bond))
        self._after_sketch_edit()
