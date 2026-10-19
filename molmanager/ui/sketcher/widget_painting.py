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

"""ACS Document 1996–style 2D rendering for :class:`~molmanager.ui.sketcher.widget.SketchWidget`."""

from __future__ import annotations

import math

from PyQt5.QtCore import QPoint, QPointF, Qt
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen, QPolygonF

from .chem import sketch_lone_pair_count, sketch_oxidation_state
from .sketch_rdkit_paint import render_sketch_mol_to_pixmap, sketch_rdkit_paint_cache_key
from .constants import SKETCH_MEDIAN_BOND_PX, WILDCARD_ELEMENT
from .bonds import (
    BOND_STEREO_DATIVE,
    BOND_STEREO_HASH,
    BOND_STEREO_WAVY,
    BOND_STEREO_WEDGE,
    _bond_unpack,
)
from .element_colors import rdkit_default_element_rgb
from .iupac_labels import (
    label_should_reverse,
    neighbor_bond_sides,
    oriented_display_label,
)
from .iupac_style import (
    condensed_heteroatom_label,
    explicit_carbon_label,
    iupac_sketch_style,
    iupac_structure_font,
)
from .rgroups import is_rgroup_node
from .wildcards import _is_wildcard_node, _normalize_wildcard_elements


class SketchWidgetPaintMixin:
    def _acs_style(self):
        med = getattr(self, "_median_bond_length_px", None)
        if med is None or med <= 0:
            med = float(SKETCH_MEDIAN_BOND_PX)
        return iupac_sketch_style(med)

    def _atom_shows_label(self, n: dict) -> bool:
        """True when an atom symbol / contracted label is painted at this node (GR-2)."""
        if n.get("abbrev"):
            return True
        el = n.get("element")
        if el == WILDCARD_ELEMENT:
            return True
        if el == "C":
            nid = n["id"]
            has_conn = any(
                (_bond_unpack(b)[0] == nid or _bond_unpack(b)[1] == nid) for b in self.bonds
            )
            if n.get("explicit_carbon") or not has_conn:
                return True
            return bool(int(n.get("charge", 0) or 0))
        return True

    def _atom_label_text_for_node(self, n: dict) -> str | None:
        """Visible atom / condensed / contracted label text, or None if unlabeled."""
        if not self._atom_shows_label(n):
            return None
        if n.get("abbrev"):
            return str(n.get("abbrev") or "")
        el = n.get("element")
        if is_rgroup_node(n):
            return str(el)
        if el == WILDCARD_ELEMENT:
            return "*"
        if el == "C":
            if n.get("explicit_carbon"):
                return self._explicit_carbon_display_label(n)
            nid = n["id"]
            has_conn = any(
                (_bond_unpack(b)[0] == nid or _bond_unpack(b)[1] == nid) for b in self.bonds
            )
            if not has_conn or int(n.get("charge", 0) or 0):
                return "C"
            return None
        return self._node_condensed_label(n) or str(el or "")

    def _atom_label_orientation(self, n: dict, text: str) -> tuple[str, bool]:
        """
        GR-2.1.6 display string and whether the bonded character is at the end (reversed).

        Returns ``(display_text, attach_at_end)``.
        """
        if is_rgroup_node(n):
            return str(n.get("element") or text), False
        left, right, _up, _down = neighbor_bond_sides(
            int(n["id"]),
            (float(n["pos"].x()), float(n["pos"].y())),
            self.nodes,
            self.bonds,
            unpack=_bond_unpack,
        )
        rev = label_should_reverse(text, has_left=left, has_right=right)
        display = oriented_display_label(text, reverse=rev)
        return display, rev

    def _label_bond_inset_px(self, n: dict, style, *, from_other: dict | None = None) -> float:
        """
        Stop bond ink short of a labeled atom (GR-2.1.5) so termini do not cross letters.

        Inset targets the attachment character (first letter L→R, last letter when reversed).
        """
        text = self._atom_label_text_for_node(n)
        if text is None:
            return 0.0
        display, attach_at_end = self._atom_label_orientation(n, text)
        font = iupac_structure_font(style.label_font_pt)
        fm = QFontMetrics(font)
        # Half-width of the attachment character (first / last).
        if len(display) <= 1:
            ch = display or "C"
        else:
            ch = display[-1] if attach_at_end else display[0]
        chw = fm.horizontalAdvance(ch) if hasattr(fm, "horizontalAdvance") else fm.width(ch)
        base = max(chw * 0.55, float(style.label_font_pt) * 0.42, 4.5)
        # Slightly larger when the bond approaches from the side the label extends into.
        if from_other is not None and len(display) > 1:
            dx = float(from_other["pos"].x()) - float(n["pos"].x())
            # Bond coming from the left toward a reversed label (extends left) → more inset.
            if attach_at_end and dx < 0:
                base *= 1.05
            elif (not attach_at_end) and dx > 0:
                base *= 1.05
        return base

    def _unlabeled_junction_trim_px(self, n: dict, style) -> float:
        """
        Slight distal trim at unlabeled multi-bond atoms so stereo wedges meet
        adjacent singles/doubles cleanly instead of covering the junction.
        """
        if self._atom_shows_label(n):
            return 0.0
        nid = n["id"]
        deg = sum(1 for b in self.bonds if _bond_unpack(b)[0] == nid or _bond_unpack(b)[1] == nid)
        if deg < 2:
            return 0.0
        return max(1.5, float(style.bond_width_px) * 0.85)

    def _trimmed_bond_segment(
        self,
        ni: dict,
        nj: dict,
        style,
        *,
        stereo: bool = False,
    ) -> tuple[float, float, float, float]:
        """Bond endpoints after label insets (and stereo distal join trim)."""
        x1, y1 = float(ni["pos"].x()), float(ni["pos"].y())
        x2, y2 = float(nj["pos"].x()), float(nj["pos"].y())
        dx, dy = x2 - x1, y2 - y1
        length = math.hypot(dx, dy)
        if length < 1e-6:
            return x1, y1, x2, y2
        ux, uy = dx / length, dy / length
        i1 = self._label_bond_inset_px(ni, style, from_other=nj)
        i2 = self._label_bond_inset_px(nj, style, from_other=ni)
        if stereo:
            # Tip stays at the stereocenter (ST); only distal end is join-trimmed.
            i2 = max(i2, self._unlabeled_junction_trim_px(nj, style))
        if i1 + i2 + 4.0 >= length:
            room = max(0.0, length - 4.0)
            total = i1 + i2
            if total > 1e-6:
                scale = room / total
                i1 *= scale
                i2 *= scale
            else:
                i1 = i2 = 0.0
        return x1 + ux * i1, y1 + uy * i1, x2 - ux * i2, y2 - uy * i2

    def _fill_text_path(
        self, p: QPainter, path: QPainterPath, fill: QColor, *, halo_w: float = 0.0
    ) -> None:
        if halo_w > 0.5:
            halo = QPen(QColor(255, 255, 255))
            halo.setWidthF(halo_w)
            halo.setJoinStyle(Qt.RoundJoin)
            halo.setCapStyle(Qt.RoundCap)
            p.setPen(halo)
            p.setBrush(Qt.NoBrush)
            p.drawPath(path)
        p.fillPath(path, QBrush(fill))

    def _acs_ink_pen(self, style, width: float | None = None) -> QPen:
        pen = QPen(QColor(*style.ink))
        pen.setWidthF(width if width is not None else style.bond_width_px)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _bond_parallel_offset(
        self, x1: float, y1: float, x2: float, y2: float, dist: float
    ) -> tuple[float, float]:
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        return (-dy / length * dist, dx / length * dist)

    def _wedge_triangle_points(
        self, x1: float, y1: float, x2: float, y2: float, half_width: float
    ) -> tuple[QPointF, QPointF, QPointF]:
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        return (
            QPointF(x1, y1),
            QPointF(x2 - px * half_width, y2 - py * half_width),
            QPointF(x2 + px * half_width, y2 + py * half_width),
        )

    def _draw_hashed_wedge(
        self,
        p: QPainter,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        half_width: float,
        *,
        n_bars: int,
        pen: QPen,
    ) -> None:
        """IUPAC/ACS hashed wedge: parallel bars perpendicular to the bond, widening from tip."""
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        n = max(4, int(n_bars))
        ink = QPen(pen.color())
        ink.setWidthF(max(1.0, pen.widthF() * 0.9))
        ink.setCapStyle(Qt.FlatCap)
        p.setPen(ink)
        # Keep a small clear tip and stop short of the wide terminus for clean joins.
        t0 = 0.08
        t1 = 0.96
        for i in range(n):
            t = t0 + (t1 - t0) * ((i + 0.5) / n)
            cx = x1 + dx * t
            cy = y1 + dy * t
            half = half_width * t
            p.drawLine(
                QPointF(cx - px * half, cy - py * half),
                QPointF(cx + px * half, cy + py * half),
            )

    def _ring_atom_ids(self) -> set[int]:
        """Atom ids on cycles via leaf-trimming (GR-1.10 double-bond sidedness)."""
        key = (
            len(self.nodes),
            len(self.bonds),
            tuple(tuple(_bond_unpack(b)) for b in self.bonds[:64]),
        )
        cached = getattr(self, "_iupac_ring_atom_ids", None)
        if cached is not None and getattr(self, "_iupac_ring_cache_key", None) == key:
            return cached
        adj: dict[int, set[int]] = {}
        for b in self.bonds:
            a, bo, _o, _s = _bond_unpack(b)
            adj.setdefault(a, set()).add(bo)
            adj.setdefault(bo, set()).add(a)
        deg = {k: len(v) for k, v in adj.items()}
        from collections import deque

        q = deque([k for k, d in deg.items() if d <= 1])
        removed: set[int] = set()
        while q:
            u = q.popleft()
            if u in removed:
                continue
            removed.add(u)
            for v in adj.get(u, ()):
                if v in removed:
                    continue
                deg[v] -= 1
                if deg[v] == 1:
                    q.append(v)
        ring = set(adj.keys()) - removed
        self._iupac_ring_atom_ids = ring
        self._iupac_ring_cache_key = key
        return ring

    def _bond_adjacency(self) -> dict[int, set[int]]:
        adj: dict[int, set[int]] = {}
        for b in self.bonds:
            a, bo, _o, _s = _bond_unpack(b)
            adj.setdefault(a, set()).add(bo)
            adj.setdefault(bo, set()).add(a)
        return adj

    def _smallest_cycle_through_bond(self, a_id: int, b_id: int) -> set[int] | None:
        """Smallest simple cycle containing edge a–b (ring-interior double-bond bias)."""
        from collections import deque

        adj = self._bond_adjacency()
        if b_id not in adj.get(a_id, ()) or a_id not in adj.get(b_id, ()):
            return None
        parent: dict[int, int | None] = {a_id: None}
        q: deque[int] = deque([a_id])
        found_prev: int | None = None
        while q:
            u = q.popleft()
            for v in adj.get(u, ()):
                if u == a_id and v == b_id:
                    continue
                if v == b_id:
                    found_prev = u
                    q.clear()
                    break
                if v in parent:
                    continue
                parent[v] = u
                q.append(v)
            if found_prev is not None:
                break
        if found_prev is None:
            return None
        cycle = {b_id, found_prev}
        cur: int | None = found_prev
        while cur is not None and cur != a_id:
            cur = parent.get(cur)
            if cur is None:
                break
            cycle.add(cur)
        cycle.add(a_id)
        return cycle if len(cycle) >= 3 else None

    def _cycle_double_bond_count(self, atom_set: set[int]) -> int:
        n_dbl = 0
        for b in self.bonds:
            u, v, o, _s = _bond_unpack(b)
            if o >= 2 and u in atom_set and v in atom_set:
                n_dbl += 1
        return n_dbl

    def _cycle_is_aromatic_like(self, face: set[int]) -> bool:
        """
        Heuristic mancude / Kekulé aromatic face (GR-3.5): 5–7 atoms with enough doubles.

        Benzene-like: 6 atoms + 3 doubles; five-membered heteroarenes: ≥2 doubles.
        """
        n = len(face)
        if n < 5 or n > 7:
            return False
        n_dbl = self._cycle_double_bond_count(face)
        if n == 6:
            return n_dbl >= 2
        return n_dbl >= 2

    def _ring_interior_offset_sign(self, ni: dict, nj: dict, ox: float, oy: float) -> float:
        """
        Return +1/-1 so ``(ox, oy) * sign`` points into the ring (GR-1.10 / GR-3.5).

        Uses the smallest cycle through the bond so aromatic Kekulé offsets stay interior.
        """
        face = self._smallest_cycle_through_bond(int(ni["id"]), int(nj["id"]))
        if face is None:
            face = self._ring_atom_ids()
        if not face:
            return 1.0
        pts = [n for n in self.nodes if n["id"] in face]
        if not pts:
            return 1.0
        cx = sum(float(n["pos"].x()) for n in pts) / len(pts)
        cy = sum(float(n["pos"].y()) for n in pts) / len(pts)
        mx = (float(ni["pos"].x()) + float(nj["pos"].x())) * 0.5
        my = (float(ni["pos"].y()) + float(nj["pos"].y())) * 0.5
        if ox * (cx - mx) + oy * (cy - my) < 0:
            return -1.0
        return 1.0

    def _fusion_or_ring_double_offset_sign(self, ni: dict, nj: dict, ox: float, oy: float) -> float:
        """
        Double-bond offset side for ring bonds (GR-1.10 / GR-3.5 / GR-1.10.4).

        Aromatic / mancude faces always offset into that face. Otherwise fusion bonds
        prefer the face with more other double bonds; remaining rings use the
        smallest-cycle interior.
        """
        a_id, b_id = int(ni["id"]), int(nj["id"])
        face = self._smallest_cycle_through_bond(a_id, b_id)
        if face is None:
            return self._ring_interior_offset_sign(ni, nj, ox, oy)

        # Aromatic Kekulé doubles: always interior to the aromatic face (GR-3.5).
        if self._cycle_is_aromatic_like(face):
            pts = [n for n in self.nodes if n["id"] in face]
            cx = sum(float(n["pos"].x()) for n in pts) / len(pts)
            cy = sum(float(n["pos"].y()) for n in pts) / len(pts)
            mx = (float(ni["pos"].x()) + float(nj["pos"].x())) * 0.5
            my = (float(ni["pos"].y()) + float(nj["pos"].y())) * 0.5
            if ox * (cx - mx) + oy * (cy - my) < 0:
                return -1.0
            return 1.0

        def doubles_in(atom_set: set[int]) -> int:
            n_dbl = 0
            for b in self.bonds:
                u, v, o, _s = _bond_unpack(b)
                if o < 2:
                    continue
                if u in atom_set and v in atom_set and {u, v} != {a_id, b_id}:
                    n_dbl += 1
            return n_dbl

        face_dbl = doubles_in(face)
        adj = self._bond_adjacency()
        other = set()
        for end in (a_id, b_id):
            for nbr in adj.get(end, ()):
                if nbr in (a_id, b_id) or nbr in face:
                    continue
                other.add(nbr)
        if other:
            alt = {a_id, b_id} | other
            changed = True
            while changed:
                changed = False
                for u in list(alt):
                    for v in adj.get(u, ()):
                        if v in face and v not in (a_id, b_id):
                            continue
                        if v not in alt and v in self._ring_atom_ids():
                            if len(alt) < len(face) + 6:
                                alt.add(v)
                                changed = True
            # Prefer aromatic alternate face, else more doubles (GR-1.10.4).
            prefer_alt = False
            if len(alt) >= 3:
                if self._cycle_is_aromatic_like(alt) and not self._cycle_is_aromatic_like(face):
                    prefer_alt = True
                elif doubles_in(alt) > face_dbl:
                    prefer_alt = True
            if prefer_alt:
                pts = [n for n in self.nodes if n["id"] in alt]
                cx = sum(float(n["pos"].x()) for n in pts) / len(pts)
                cy = sum(float(n["pos"].y()) for n in pts) / len(pts)
                mx = (float(ni["pos"].x()) + float(nj["pos"].x())) * 0.5
                my = (float(ni["pos"].y()) + float(nj["pos"].y())) * 0.5
                if ox * (cx - mx) + oy * (cy - my) < 0:
                    return -1.0
                return 1.0
        return self._ring_interior_offset_sign(ni, nj, ox, oy)

    def _double_bond_side_substituent_counts(self, ni: dict, nj: dict) -> tuple[int, int, int, int]:
        """
        Count substituents on each side of bond ni–nj (cross-product sign).

        Returns ``(pos_side, neg_side, ni_extra_count, nj_extra_count)``.
        """
        x1, y1 = float(ni["pos"].x()), float(ni["pos"].y())
        x2, y2 = float(nj["pos"].x()), float(nj["pos"].y())
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1e-6)
        ux, uy = dx / length, dy / length
        pos_n = neg_n = 0
        ni_extra = nj_extra = 0
        for end, is_i in ((ni, True), (nj, False)):
            eid = int(end["id"])
            ex, ey = float(end["pos"].x()), float(end["pos"].y())
            for b in self.bonds:
                a, bo, _o, _s = _bond_unpack(b)
                if a != eid and bo != eid:
                    continue
                oid = bo if a == eid else a
                if oid in (ni["id"], nj["id"]):
                    continue
                on = next((x for x in self.nodes if x["id"] == oid), None)
                if on is None:
                    continue
                if is_i:
                    ni_extra += 1
                else:
                    nj_extra += 1
                ox = float(on["pos"].x()) - ex
                oy = float(on["pos"].y()) - ey
                cross = ux * oy - uy * ox
                if cross > 1e-6:
                    pos_n += 1
                elif cross < -1e-6:
                    neg_n += 1
        return pos_n, neg_n, ni_extra, nj_extra

    def _draw_iupac_double_bond(self, p: QPainter, ni: dict, nj: dict, pen: QPen, style) -> None:
        """
        IUPAC GR-1.10 double bond: centered (carbonyl-like) or offset with shortened outer stroke.
        """
        x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style)
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        dist = float(style.double_bond_offset_px)
        ox, oy = self._bond_parallel_offset(x1, y1, x2, y2, dist)

        ring = self._ring_atom_ids()
        in_ring = ni["id"] in ring and nj["id"] in ring
        pos_n, neg_n, ni_extra, nj_extra = self._double_bond_side_substituent_counts(ni, nj)

        # GR-1.10.2: ≥2 substituents on one end, none on the other → centered (e.g. C=O).
        # Unsubstituted C=C (both ends bare) also uses a centered double bond.
        # Asymmetric alkenes (e.g. propene 1 vs 0) use offset toward the more substituted side.
        centered = (
            (ni_extra >= 2 and nj_extra == 0)
            or (nj_extra >= 2 and ni_extra == 0)
            or (ni_extra == 0 and nj_extra == 0)
        )

        p.setPen(pen)
        if centered and not in_ring:
            half_ox, half_oy = ox * 0.5, oy * 0.5
            p.drawLine(
                QPointF(x1 - half_ox, y1 - half_oy),
                QPointF(x2 - half_ox, y2 - half_oy),
            )
            p.drawLine(
                QPointF(x1 + half_ox, y1 + half_oy),
                QPointF(x2 + half_ox, y2 + half_oy),
            )
            return

        # Offset style: main stroke on the atom–atom axis; second stroke offset & shortened.
        if in_ring:
            # Aromatic / ring doubles: second stroke toward ring interior (GR-1.10 / GR-3.5).
            side = self._fusion_or_ring_double_offset_sign(ni, nj, ox, oy)
        elif pos_n != neg_n:
            # GR-1.10.1: offset toward the more substituted side.
            side = 1.0 if pos_n > neg_n else -1.0
        else:
            side = 1.0

        p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
        # Shorten offset segment (~12–18% each end) toward angle bisectors.
        t_start = 0.14 if ni_extra > 0 else 0.0
        t_end = 0.14 if nj_extra > 0 else 0.0
        if in_ring:
            t_start = max(t_start, 0.10)
            t_end = max(t_end, 0.10)
        # Extra clearance when an end is labeled so the outer stroke does not clip letters.
        if self._atom_shows_label(ni):
            t_start = max(t_start, 0.06)
        if self._atom_shows_label(nj):
            t_end = max(t_end, 0.06)
        sx = x1 + ux * (length * t_start) + ox * side
        sy = y1 + uy * (length * t_start) + oy * side
        ex = x2 - ux * (length * t_end) + ox * side
        ey = y2 - uy * (length * t_end) + oy * side
        p.drawLine(QPointF(sx, sy), QPointF(ex, ey))

    def _draw_bond(
        self, p: QPainter, ni: dict, nj: dict, order: int, stereo: int, pen: QPen
    ) -> None:
        if order != 1:
            stereo = 0
        style = self._acs_style()
        p.setPen(pen)
        if order == 1 and stereo == BOND_STEREO_WEDGE:
            x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style, stereo=True)
            apex, left, right = self._wedge_triangle_points(
                x1, y1, x2, y2, style.wedge_half_width_px
            )
            p.setBrush(QBrush(QColor(*style.ink)))
            p.setPen(Qt.NoPen)
            p.drawPolygon(QPolygonF([apex, left, right]))
            p.setBrush(Qt.NoBrush)
            p.setPen(pen)
            return
        if order == 1 and stereo == BOND_STEREO_HASH:
            x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style, stereo=True)
            self._draw_hashed_wedge(
                p,
                x1,
                y1,
                x2,
                y2,
                style.wedge_half_width_px,
                n_bars=getattr(style, "hash_bar_count", 6),
                pen=pen,
            )
            return
        if order == 1 and stereo == BOND_STEREO_WAVY:
            x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style)
            self._draw_wavy_bond(p, x1, y1, x2, y2, pen)
            return
        if order == 1 and stereo == BOND_STEREO_DATIVE:
            x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style)
            self._draw_dative_bond(p, x1, y1, x2, y2, pen, style)
            return
        if order == 1:
            x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style)
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            return
        if order == 2:
            self._draw_iupac_double_bond(p, ni, nj, pen, style)
            return
        x1, y1, x2, y2 = self._trimmed_bond_segment(ni, nj, style)
        dist = style.triple_bond_offset_px
        ox, oy = self._bond_parallel_offset(x1, y1, x2, y2, dist)
        for ox2, oy2 in ((-ox, -oy), (0.0, 0.0), (ox, oy)):
            p.drawLine(
                QPointF(x1 + ox2, y1 + oy2),
                QPointF(x2 + ox2, y2 + oy2),
            )

    def _draw_wavy_bond(
        self, p: QPainter, x1: float, y1: float, x2: float, y2: float, pen: QPen
    ) -> None:
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        amp = max(2.5, min(6.0, length * 0.08))
        waves = max(2, min(5, int(round(length / 14.0))))
        n = max(12, waves * 8)
        path = QPainterPath()
        for i in range(n + 1):
            t = i / n
            wave = math.sin(t * math.pi * waves) * amp
            x = x1 + dx * t + px * wave
            y = y1 + dy * t + py * wave
            if i == 0:
                path.moveTo(x, y)
            else:
                path.lineTo(x, y)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)

    def _draw_dative_bond(
        self,
        p: QPainter,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        pen: QPen,
        style,
    ) -> None:
        """Arrow from atom1 → atom2 (donor → acceptor), matching RDKit DATIVE begin→end."""
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head = max(6.0, min(11.0, length * 0.22))
        half = max(3.0, style.wedge_half_width_px * 0.55)
        sx2 = x2 - ux * head
        sy2 = y2 - uy * head
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(sx2, sy2))
        p.setBrush(QBrush(pen.color()))
        p.setPen(Qt.NoPen)
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x2, y2),
                    QPointF(sx2 + px * half, sy2 + py * half),
                    QPointF(sx2 - px * half, sy2 - py * half),
                ]
            )
        )
        p.setBrush(Qt.NoBrush)

    def _draw_element_label(
        self,
        p: QPainter,
        pos: QPoint,
        text: str,
        *,
        font_pt: int,
        fill: QColor,
        node: dict | None = None,
    ) -> None:
        """
        Paint an atom label (GR-0 / GR-2.1.5 / GR-2.1.6).

        Multi-character labels reverse when bonds are only on the right. The bonded
        element character is centered on *pos*; the rest of the label extends away.
        """
        font = iupac_structure_font(font_pt)
        fm = QFontMetrics(font)
        display = text
        attach_at_end = False
        if node is not None and len(text) > 1:
            display, attach_at_end = self._atom_label_orientation(node, text)
        if len(display) <= 1:
            tw = (
                fm.horizontalAdvance(display)
                if hasattr(fm, "horizontalAdvance")
                else fm.width(display)
            )
            x = float(pos.x() - tw / 2)
        elif attach_at_end:
            prefix = display[:-1]
            pw = (
                fm.horizontalAdvance(prefix)
                if hasattr(fm, "horizontalAdvance")
                else fm.width(prefix)
            )
            last = display[-1]
            lw = fm.horizontalAdvance(last) if hasattr(fm, "horizontalAdvance") else fm.width(last)
            x = float(pos.x()) - pw - lw / 2
        else:
            first = display[0]
            fw = (
                fm.horizontalAdvance(first) if hasattr(fm, "horizontalAdvance") else fm.width(first)
            )
            x = float(pos.x()) - fw / 2
        y = float(pos.y() + fm.ascent() * 0.35)
        path = QPainterPath()
        path.addText(x, y, font, display)
        self._fill_text_path(p, path, fill, halo_w=max(3.0, font_pt * 0.32))

    def _draw_formal_charge(
        self,
        p: QPainter,
        pos: QPoint,
        ch: int,
        *,
        symbol: str | None,
        font_pt: int,
        node: dict | None = None,
    ) -> None:
        if not ch:
            return
        if ch == 1:
            label = "+"
        elif ch == -1:
            label = "−"
        else:
            label = f"{ch:+d}".replace("-", "−")
        ch_pt = max(7, int(round(font_pt * 0.58)))
        font = iupac_structure_font(ch_pt, weight=QFont.Bold)
        fm = QFontMetrics(font)
        if symbol:
            display = symbol
            attach_at_end = False
            if node is not None and len(symbol) > 1:
                display, attach_at_end = self._atom_label_orientation(node, symbol)
            sym_font = iupac_structure_font(font_pt)
            sym_fm = QFontMetrics(sym_font)
            tw = (
                sym_fm.horizontalAdvance(display)
                if hasattr(sym_fm, "horizontalAdvance")
                else sym_fm.width(display)
            )
            if len(display) <= 1:
                left = float(pos.x()) - tw / 2
                right = left + tw
            elif attach_at_end:
                prefix = display[:-1]
                pw = (
                    sym_fm.horizontalAdvance(prefix)
                    if hasattr(sym_fm, "horizontalAdvance")
                    else sym_fm.width(prefix)
                )
                last = display[-1]
                lw = (
                    sym_fm.horizontalAdvance(last)
                    if hasattr(sym_fm, "horizontalAdvance")
                    else sym_fm.width(last)
                )
                left = float(pos.x()) - pw - lw / 2
                right = left + tw
            else:
                first = display[0]
                fw = (
                    sym_fm.horizontalAdvance(first)
                    if hasattr(sym_fm, "horizontalAdvance")
                    else sym_fm.width(first)
                )
                left = float(pos.x()) - fw / 2
                right = left + tw
            # Charge sits past the free end of the label (GR-5 near the atom symbol).
            chw = (
                fm.horizontalAdvance(label) if hasattr(fm, "horizontalAdvance") else fm.width(label)
            )
            bx = right + 1.0 if not attach_at_end else left - chw - 1.0
            by = float(pos.y()) - sym_fm.ascent() * 0.45 + fm.ascent() * 0.5
        else:
            bx = float(pos.x() + 7)
            by = float(pos.y() - 5 + fm.ascent())
        path = QPainterPath()
        path.addText(bx, by, font, label)
        # IUPAC GR-5: charge marks use the same ink as the diagram (not a second color).
        style = self._acs_style()
        p.fillPath(path, QBrush(QColor(*style.ink)))

    def _annotation_offset(self, nid: int, pos: QPoint, slot: int) -> QPoint:
        ux, uy, vx, vy = self._bond_avoidance_axes(nid, pos)
        d = self.radius + 9
        dirs = ((ux, uy), (vx, vy), (-ux, -uy), (-vx, -vy))
        dx, dy = dirs[slot % 4]
        return QPoint(int(round(dx * d)), int(round(dy * d)))

    def _bond_avoidance_axes(self, nid: int, pos: QPoint) -> tuple[float, float, float, float]:
        pts: list[QPoint] = []
        for b in self.bonds:
            a, b0, _, __ = _bond_unpack(b)
            other = b0 if a == nid else a if b0 == nid else None
            if other is None:
                continue
            on = next((x for x in self.nodes if x["id"] == other), None)
            if on is not None:
                pts.append(on["pos"])
        if not pts:
            ux, uy = -0.82, -0.58
        else:
            sx = sy = 0.0
            for pt in pts:
                dx = float(pt.x() - pos.x())
                dy = float(pt.y() - pos.y())
                length = math.hypot(dx, dy)
                if length > 1e-6:
                    sx += dx / length
                    sy += dy / length
            length = math.hypot(sx, sy)
            ux, uy = (-sx / length, -sy / length) if length > 1e-6 else (0.0, -1.0)
        return ux, uy, -uy, ux

    def _point_segment_distance(
        self, px: float, py: float, x1: float, y1: float, x2: float, y2: float
    ) -> float:
        vx, vy = x2 - x1, y2 - y1
        den = vx * vx + vy * vy
        if den < 1e-12:
            return math.hypot(px - x1, py - y1)
        t = max(0.0, min(1.0, ((px - x1) * vx + (py - y1) * vy) / den))
        return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))

    def _stereo_label_collision_score(
        self,
        nid: int,
        cx: float,
        cy: float,
        *,
        half_w: float,
        half_h: float,
    ) -> float:
        """Lower is better. Penalize proximity to bonds and other atom labels (GR-11.1)."""
        score = 0.0
        samples = [
            (cx, cy),
            (cx - half_w, cy - half_h),
            (cx + half_w, cy - half_h),
            (cx - half_w, cy + half_h),
            (cx + half_w, cy + half_h),
        ]
        for b in self.bonds:
            a, bo, _o, _s = _bond_unpack(b)
            na = next((x for x in self.nodes if x["id"] == a), None)
            nb = next((x for x in self.nodes if x["id"] == bo), None)
            if na is None or nb is None:
                continue
            x1, y1 = float(na["pos"].x()), float(na["pos"].y())
            x2, y2 = float(nb["pos"].x()), float(nb["pos"].y())
            for sx, sy in samples:
                d = self._point_segment_distance(sx, sy, x1, y1, x2, y2)
                if d < half_h + 2.0:
                    score += (half_h + 2.0 - d) * 8.0
                elif d < half_h + 8.0:
                    score += (half_h + 8.0 - d) * 1.5
        for n in self.nodes:
            if int(n["id"]) == int(nid):
                continue
            ax, ay = float(n["pos"].x()), float(n["pos"].y())
            shows = False
            try:
                shows = bool(self._atom_shows_label(n))
            except Exception:
                el = str(n.get("element") or "")
                shows = el not in ("C",) or bool(n.get("abbrev")) or bool(n.get("explicit_carbon"))
            rad = float(self.radius) * (1.15 if shows else 0.55)
            for sx, sy in samples:
                d = math.hypot(sx - ax, sy - ay)
                if d < rad + half_h:
                    score += (rad + half_h - d) * 6.0
        return score

    def _stereo_descriptor_offset(
        self, nid: int, pos: QPoint, *, half_w: float = 10.0, half_h: float = 7.0
    ) -> QPoint:
        """
        IUPAC GR-11.1: place atom stereo annotations in open space, clear of bonds
        and atom labels. Prefer opposite a wedged/hashed bond when that site is free.
        """
        style = self._acs_style()
        sep = max(float(style.label_font_pt) * 0.7, float(self.radius) * 0.65, half_h + 4.0)
        preferred: list[tuple[float, float]] = []
        sx = sy = 0.0
        n_w = 0
        for b in self.bonds:
            a, bo, o, s = _bond_unpack(b)
            if o != 1 or s not in (BOND_STEREO_WEDGE, BOND_STEREO_HASH):
                continue
            if a != nid:
                continue
            on = next((x for x in self.nodes if x["id"] == bo), None)
            if on is None:
                continue
            dx = float(on["pos"].x()) - float(pos.x())
            dy = float(on["pos"].y()) - float(pos.y())
            length = math.hypot(dx, dy)
            if length < 1e-6:
                continue
            sx += dx / length
            sy += dy / length
            n_w += 1
        if n_w > 0:
            length = math.hypot(sx, sy)
            if length > 1e-6:
                preferred.append((-sx / length, -sy / length))
        ux, uy, vx, vy = self._bond_avoidance_axes(nid, pos)
        for dx, dy in (
            (ux, uy),
            (-ux, -uy),
            (vx, vy),
            (-vx, -vy),
            (0.0, -1.0),
            (0.0, 1.0),
            (1.0, 0.0),
            (-1.0, 0.0),
            (0.707, -0.707),
            (-0.707, -0.707),
            (0.707, 0.707),
            (-0.707, 0.707),
        ):
            preferred.append((dx, dy))

        best_off = QPoint(0, -int(round(sep)))
        best_score = float("inf")
        px, py = float(pos.x()), float(pos.y())
        distances = (sep, sep * 1.25, sep * 1.55, sep * 1.9)
        seen: set[tuple[int, int]] = set()
        for ux, uy in preferred:
            length = math.hypot(ux, uy)
            if length < 1e-6:
                continue
            ux, uy = ux / length, uy / length
            for dist in distances:
                ox = int(round(ux * dist))
                oy = int(round(uy * dist))
                key = (ox, oy)
                if key in seen:
                    continue
                seen.add(key)
                sc = self._stereo_label_collision_score(
                    nid, px + ox, py + oy, half_w=half_w, half_h=half_h
                )
                sc += 0.01 * len(seen)
                if sc < best_score:
                    best_score = sc
                    best_off = QPoint(ox, oy)
                    if sc < 0.5:
                        return best_off
        return best_off

    def _draw_cip_label(self, p: QPainter, pos: QPoint, nid: int, code: str) -> None:
        """Draw CIP (R)/(S) per ST-0.7 / GR-11.1 (smaller italic annotation)."""
        style = self._acs_style()
        label = f"({code})"
        pt = max(7, int(round(style.label_font_pt * 0.72)))
        font = iupac_structure_font(pt, italic=True)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(label) if hasattr(fm, "horizontalAdvance") else fm.width(label)
        half_w = tw * 0.5
        half_h = float(fm.height()) * 0.45
        off = self._stereo_descriptor_offset(nid, pos, half_w=half_w, half_h=half_h)
        bx = pos.x() + off.x() - tw // 2
        by = pos.y() + off.y() + fm.ascent() // 3
        path = QPainterPath()
        path.addText(float(bx), float(by), font, label)
        self._fill_text_path(p, path, QColor(*style.ink), halo_w=max(2.5, pt * 0.28))

    def _draw_alkene_ez_label(
        self, p: QPainter, ni: dict, nj: dict, code: str, *, font_pt: int
    ) -> None:
        """Draw bond-based (E)/(Z) near the midpoint (GR-11.2), clear of bond ink."""
        style = self._acs_style()
        x1, y1 = float(ni["pos"].x()), float(ni["pos"].y())
        x2, y2 = float(nj["pos"].x()), float(nj["pos"].y())
        mx, my = (x1 + x2) * 0.5, (y1 + y2) * 0.5
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        # Prefer the less-substituted perpendicular side.
        pos_n = neg_n = 0
        for end in (ni, nj):
            eid = int(end["id"])
            ex, ey = float(end["pos"].x()), float(end["pos"].y())
            for b in self.bonds:
                a, bo, _o, _s = _bond_unpack(b)
                if a != eid and bo != eid:
                    continue
                oid = bo if a == eid else a
                if oid in (ni["id"], nj["id"]):
                    continue
                on = next((x for x in self.nodes if x["id"] == oid), None)
                if on is None:
                    continue
                cross = ux * (float(on["pos"].y()) - ey) - uy * (float(on["pos"].x()) - ex)
                if cross > 1e-6:
                    pos_n += 1
                elif cross < -1e-6:
                    neg_n += 1
        side = -1.0 if pos_n > neg_n else 1.0
        # Also prefer the side opposite an offset double-bond outer stroke when one end is substituted.
        _, _, ni_extra, nj_extra = self._double_bond_side_substituent_counts(ni, nj)
        ring = self._ring_atom_ids()
        in_ring = ni["id"] in ring and nj["id"] in ring
        centered = (
            (ni_extra >= 2 and nj_extra == 0)
            or (nj_extra >= 2 and ni_extra == 0)
            or (ni_extra == 0 and nj_extra == 0)
        )
        dbl_span = float(style.double_bond_offset_px)
        if not centered or in_ring:
            # Offset doubles: place label on the side without the outer stroke when possible.
            ox0, oy0 = self._bond_parallel_offset(x1, y1, x2, y2, 1.0)
            if in_ring:
                dbl_side = self._ring_interior_offset_sign(ni, nj, ox0, oy0)
            elif pos_n != neg_n:
                dbl_side = 1.0 if pos_n > neg_n else -1.0
            else:
                dbl_side = 1.0
            if side * dbl_side > 0:
                side = -dbl_side
            # Clearance past the farther parallel stroke + half glyph height.
            clear_bond = dbl_span + 2.0
        else:
            clear_bond = dbl_span * 0.5 + 2.0

        label = f"({code})"
        pt = max(7, int(round(float(font_pt) * 0.72)))
        font = iupac_structure_font(pt, italic=True)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(label) if hasattr(fm, "horizontalAdvance") else fm.width(label)
        text_clear = max(float(fm.height()) * 0.55, float(pt) * 0.65)
        half_w = tw * 0.5
        half_h = float(fm.height()) * 0.45
        best_tx = mx
        best_ty = my
        best_score = float("inf")
        for s in (side, -side):
            for extra in (0.0, 4.0, 8.0, 12.0):
                dist = clear_bond + text_clear + 3.0 + extra
                ox, oy = self._bond_parallel_offset(x1, y1, x2, y2, dist * s)
                cx, cy = mx + ox, my + oy
                sc = self._stereo_label_collision_score(-1, cx, cy, half_w=half_w, half_h=half_h)
                if s != side:
                    sc += 2.0
                if sc < best_score:
                    best_score = sc
                    best_tx = cx - tw / 2
                    best_ty = cy + fm.ascent() / 3
        path = QPainterPath()
        path.addText(float(best_tx), float(best_ty), font, label)
        self._fill_text_path(p, path, QColor(*style.ink), halo_w=max(2.5, pt * 0.28))

    def _draw_atom_selection_ring(
        self, p: QPainter, pos: QPoint, *, selected: bool, hover: bool
    ) -> None:
        style = self._acs_style()
        r = float(self.radius) + style.atom_selection_radius_extra
        if selected:
            pen = QPen(QColor(0, 80, 200))
            pen.setWidthF(style.selection_pen_width)
        elif hover:
            pen = QPen(QColor(100, 140, 220))
            pen.setWidthF(style.hover_pen_width)
        else:
            return
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(pos, int(r), int(r))

    def _draw_atom_issue_ring(
        self, p: QPainter, pos: QPoint, *, valence: bool, stereo: bool, iupac: bool = False
    ) -> None:
        if not valence and not stereo and not iupac:
            return
        if valence:
            color = QColor(200, 50, 40)
        elif stereo:
            color = QColor(140, 80, 180)
        else:
            color = QColor(180, 120, 40)
        pen = QPen(color, 1.5, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(pos, self.radius + 2, self.radius + 2)

    def _set_stereo_label_visible(self, node_id: int, visible: bool) -> None:
        if visible:
            self._stereo_label_node_ids.add(node_id)
        else:
            self._stereo_label_node_ids.discard(node_id)
        self._after_sketch_edit()

    def _should_paint_sketch_with_rdkit(self) -> bool:
        if (
            not self.nodes
            or self.sketch_has_wildcards()
            or any(is_rgroup_node(n) for n in self.nodes)
        ):
            return False
        # Wavy / dative use custom ACS glyphs; keep those sketches on the local painter.
        for b in self.bonds:
            if _bond_unpack(b)[3] in (BOND_STEREO_WAVY, BOND_STEREO_DATIVE):
                return False
        # Explicit C labels need ACS drawing so bonds stop at the atom label.
        if any(n.get("element") == "C" and n.get("explicit_carbon") for n in self.nodes):
            return False
        # Ring double bonds: local ACS painter keeps all offsets interior (GR-3.5).
        # RDKit's left-of-bond offset alternates around a ring (some exterior).
        ring = self._ring_atom_ids()
        if ring:
            for b in self.bonds:
                a, bo, o, _s = _bond_unpack(b)
                if o == 2 and a in ring and bo in ring:
                    return False
            # Macrocycles (≥9): RDKit MolDraw2D re-embeds circular rings; affine fit cannot
            # recover hexagonal GR-3.3.2 geometry — always paint locally.
            if self._has_macrocycle_ring():
                return False
        # Contracted group labels (CF3, Ph, …) are drawn locally (GR-2.2 / GR-2.3).
        if any(n.get("abbrev") for n in self.nodes):
            return False
        # Condensed heteroatom H labels (OH, NH2, …) are drawn locally (GR-2).
        if any(self._node_condensed_label(n) for n in self.nodes):
            return False
        return True

    def _has_macrocycle_ring(self) -> bool:
        """True when any simple cycle has ≥9 atoms (GR-3.3.2 macrocycle)."""
        from collections import defaultdict, deque

        adj: dict[int, set[int]] = defaultdict(set)
        for b in self.bonds:
            a, bo, _o, _s = _bond_unpack(b)
            adj[a].add(bo)
            adj[bo].add(a)
        # Enumerate a shortest cycle through each edge; stop if any length ≥9.
        for start, nbrs in adj.items():
            for nb in nbrs:
                if nb < start:
                    continue
                parent: dict[int, int | None] = {start: None}
                q: deque[int] = deque([start])
                found = None
                while q:
                    u = q.popleft()
                    for v in adj.get(u, ()):
                        if u == start and v == nb:
                            continue
                        if v == nb:
                            found = u
                            q.clear()
                            break
                        if v in parent:
                            continue
                        parent[v] = u
                        q.append(v)
                    if found is not None:
                        break
                if found is None:
                    continue
                length = 2
                cur: int | None = found
                while cur is not None and cur != start:
                    length += 1
                    cur = parent.get(cur)
                    if length >= 9:
                        return True
        return False

    def _node_implicit_h_count(self, n: dict, *, include_carbon: bool = False) -> int:
        if _is_wildcard_node(n) or is_rgroup_node(n):
            return 0
        el = str(n.get("element") or "")
        if el in ("H", "D", "T", WILDCARD_ELEMENT):
            return 0
        if el == "C" and not include_carbon:
            return 0
        # Explicit H neighbors already shown as atoms — do not also condense.
        nid = int(n["id"])
        for b in self.bonds:
            a, bo, _o, _s = _bond_unpack(b)
            other = bo if a == nid else a if bo == nid else None
            if other is None:
                continue
            on = next((x for x in self.nodes if x["id"] == other), None)
            if on is not None and on.get("element") in ("H", "D", "T"):
                return 0
        fc = int(n.get("charge", 0) or 0)
        bond_sum = int(self._current_valence(nid))
        target = int(self._target_valence_for_implicit_h(el, bond_sum, fc))
        return max(0, target - bond_sum)

    def _node_condensed_label(self, n: dict) -> str | None:
        return condensed_heteroatom_label(
            str(n.get("element") or ""), self._node_implicit_h_count(n)
        )

    def _explicit_carbon_display_label(self, n: dict) -> str:
        """CHₙ label for Explicit Carbon, including implicit hydrogens (GR-2)."""
        return explicit_carbon_label(self._node_implicit_h_count(n, include_carbon=True))

    def _set_explicit_carbon_visible(self, node_id: int, visible: bool) -> None:
        n = next((x for x in self.nodes if x["id"] == node_id), None)
        if n is None or n.get("element") != "C":
            return
        old = bool(n.get("explicit_carbon"))
        on = bool(visible)
        if old == on:
            return
        if on:
            n["explicit_carbon"] = True
        else:
            n.pop("explicit_carbon", None)
        self._push_undo("chg_explicit_carbon", (node_id, old, on))
        self._invalidate_rdkit_sketch_paint_cache()
        self._after_sketch_edit()

    def _set_node_flag_visible(
        self, node_id: int, flag: str, visible: bool, *, undo_op: str
    ) -> None:
        n = next((x for x in self.nodes if x["id"] == node_id), None)
        if n is None:
            return
        old = bool(n.get(flag))
        on = bool(visible)
        if old == on:
            return
        if on:
            n[flag] = True
        else:
            n.pop(flag, None)
        self._push_undo(undo_op, (node_id, old, on))
        self._invalidate_rdkit_sketch_paint_cache()
        self._after_sketch_edit()

    def _set_atom_lone_pairs_visible(self, node_id: int, visible: bool) -> None:
        self._set_node_flag_visible(
            node_id, "show_lone_pairs", visible, undo_op="chg_show_lone_pairs"
        )

    def _set_atom_oxidation_visible(self, node_id: int, visible: bool) -> None:
        self._set_node_flag_visible(
            node_id, "show_oxidation_state", visible, undo_op="chg_show_oxidation_state"
        )

    def _invalidate_rdkit_sketch_paint_cache(self) -> None:
        self._rdkit_sketch_paint_cache_key = None
        self._rdkit_sketch_paint_cache = None

    def _try_paint_rdkit_sketch_structure(self, p: QPainter) -> bool:
        if not self._should_paint_sketch_with_rdkit():
            return False
        cache_key = sketch_rdkit_paint_cache_key(self.nodes, self.bonds)
        view_bucket = max(1, int(round(max(1.0, float(getattr(self, "_view_scale", 1.0))) * 2)))
        cache_key = cache_key + (view_bucket, int(round(max(1.0, float(self.devicePixelRatioF())))))
        if (
            getattr(self, "_rdkit_sketch_paint_cache", None) is not None
            and getattr(self, "_rdkit_sketch_paint_cache_key", None) == cache_key
        ):
            pm, transform = self._rdkit_sketch_paint_cache
        else:
            ids = {n["id"] for n in self.nodes}
            out = self._mol_from_node_ids(ids, return_idmap=True)
            if out is None:
                return False
            mol, idmap = out
            if mol is None or mol.GetNumAtoms() == 0:
                return False
            med = float(getattr(self, "_median_bond_length_px", None) or SKETCH_MEDIAN_BOND_PX)
            view_scale = max(1.0, float(getattr(self, "_view_scale", 1.0)))
            dpr = max(1.0, float(self.devicePixelRatioF()))
            render_scale = max(2, min(4, int(round(max(view_scale, dpr) * 2))))
            rendered = render_sketch_mol_to_pixmap(
                mol,
                idmap,
                self.nodes,
                pad_px=max(32.0, med * 0.65),
                bond_scale_px=med,
                render_scale=render_scale,
            )
            if rendered is None:
                return False
            self._rdkit_sketch_paint_cache = rendered
            self._rdkit_sketch_paint_cache_key = cache_key
            pm, transform = rendered
        p.save()
        p.setRenderHint(
            QPainter.SmoothPixmapTransform, float(getattr(self, "_view_scale", 1.0)) != 1.0
        )
        p.setTransform(transform, combine=True)
        p.drawPixmap(0, 0, pm)
        p.restore()
        return True

    def _bond_highlight_stroke_width(self, style, order: int, *, selected: bool) -> float:
        """Width of a single centerline underlay that covers single/double/triple bond ink."""
        ink_w = max(1.0, float(style.bond_width_px))
        pad = float(style.bond_selection_extra_width if selected else 0.8)
        if order >= 3:
            span = 2.0 * float(style.triple_bond_offset_px)
        elif order == 2:
            span = float(style.double_bond_offset_px)
        else:
            span = 0.0
        return max(ink_w + pad * 2.0, span + ink_w * 2.0 + pad)

    def _draw_bond_highlight_underlay(
        self,
        p: QPainter,
        ni: dict,
        nj: dict,
        order: int,
        *,
        color: QColor,
        selected: bool,
        style,
    ) -> None:
        """Draw one rounded stroke along the bond axis (avoids thick multi-line redraws)."""
        pen = QPen(color)
        pen.setWidthF(self._bond_highlight_stroke_width(style, order, selected=selected))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        p.setPen(pen)
        p.drawLine(ni["pos"], nj["pos"])

    def _paint_sketch_bond_highlights(self, p: QPainter, style) -> None:
        selected_bonds = set(self.selected_bond_indices)
        hover_bond: int | None = None
        if isinstance(self.hover, tuple) and self.hover[0] == "bond":
            try:
                hover_bond = int(self.hover[1])
            except (TypeError, ValueError):
                hover_bond = None

        for bi in sorted(selected_bonds):
            if bi < 0 or bi >= len(self.bonds):
                continue
            a, b, order, _stereo = _bond_unpack(self.bonds[bi])
            ni = next((n for n in self.nodes if n["id"] == a), None)
            nj = next((n for n in self.nodes if n["id"] == b), None)
            if ni and nj:
                self._draw_bond_highlight_underlay(
                    p,
                    ni,
                    nj,
                    order,
                    color=QColor(0, 100, 220, 110),
                    selected=True,
                    style=style,
                )

        if (
            hover_bond is not None
            and 0 <= hover_bond < len(self.bonds)
            and hover_bond not in selected_bonds
        ):
            a, b, order, _stereo = _bond_unpack(self.bonds[hover_bond])
            ni = next((n for n in self.nodes if n["id"] == a), None)
            nj = next((n for n in self.nodes if n["id"] == b), None)
            if ni and nj:
                self._draw_bond_highlight_underlay(
                    p,
                    ni,
                    nj,
                    order,
                    color=QColor(80, 140, 230, 90),
                    selected=False,
                    style=style,
                )

    def _paint_sketch_atom_overlays(self, p: QPainter, style) -> None:
        stereo_issue = getattr(self, "_chiral_stereo_issue_ids", set())
        iupac_atoms = getattr(self, "_iupac_issue_atom_ids", set())
        for n in self.nodes:
            pos = n["pos"]
            nid = n["id"]
            self._draw_atom_issue_ring(
                p,
                pos,
                valence=nid in self._valence_violations or nid in self._charge_violations,
                stereo=nid in stereo_issue,
                iupac=nid in iupac_atoms
                and nid not in self._valence_violations
                and nid not in stereo_issue,
            )
            self._draw_atom_selection_ring(
                p,
                pos,
                selected=nid in self.selected_nodes,
                hover=self.hover == nid,
            )

        for bi, bond in enumerate(self.bonds):
            i, j, order, stereo = _bond_unpack(bond)
            if order != 2:
                continue
            ez = (getattr(self, "_alkene_ez_by_bond_index", None) or {}).get(bi)
            if ez not in ("E", "Z"):
                continue
            ni = next((n for n in self.nodes if n["id"] == i), None)
            nj = next((n for n in self.nodes if n["id"] == j), None)
            if ni and nj:
                self._draw_alkene_ez_label(p, ni, nj, str(ez), font_pt=style.label_font_pt)

        for n in self.nodes:
            code = self._stereo_cip_by_node_id.get(n["id"])
            if n["id"] in self._stereo_label_node_ids and code in ("R", "S"):
                self._draw_cip_label(p, pos=n["pos"], nid=n["id"], code=code)

        self._paint_sketch_lone_pairs(p, style)
        self._paint_sketch_oxidation_states(p, style)

    def _node_lone_pair_count(self, n: dict) -> int:
        if _is_wildcard_node(n) or is_rgroup_node(n):
            return 0
        nid = int(n["id"])
        fc = int(n.get("charge", 0) or 0)
        bond_sum = int(self._current_valence(nid))
        target = int(self._target_valence_for_implicit_h(str(n.get("element", "")), bond_sum, fc))
        implicit_h = max(0, target - bond_sum)
        return sketch_lone_pair_count(
            str(n.get("element", "")),
            formal_charge=fc,
            bond_order_sum=bond_sum,
            implicit_h=implicit_h,
        )

    def _lone_pair_directions(self, n: dict, count: int) -> list[float]:
        """Return ``count`` angles (radians) for lone-pair placement around node ``n``."""
        if count <= 0:
            return []
        nid = int(n["id"])
        cx, cy = float(n["pos"].x()), float(n["pos"].y())
        angles: list[float] = []
        for bond in self.bonds:
            a, b, _o, _s = _bond_unpack(bond)
            if a != nid and b != nid:
                continue
            other_id = b if a == nid else a
            other = next((x for x in self.nodes if x["id"] == other_id), None)
            if other is None:
                continue
            dx = float(other["pos"].x()) - cx
            dy = float(other["pos"].y()) - cy
            if math.hypot(dx, dy) < 1e-6:
                continue
            angles.append(math.atan2(dy, dx))
        if not angles:
            return [2.0 * math.pi * i / count - math.pi / 2.0 for i in range(count)]

        angles.sort()
        # Gaps between consecutive bond directions (including wrap-around).
        gaps: list[tuple[float, float]] = []
        for i, ang in enumerate(angles):
            nxt = angles[(i + 1) % len(angles)]
            span = (nxt - ang) % (2.0 * math.pi)
            if span < 1e-6:
                span = 2.0 * math.pi
            mid = (ang + span / 2.0) % (2.0 * math.pi)
            if mid > math.pi:
                mid -= 2.0 * math.pi
            gaps.append((span, mid))
        gaps.sort(key=lambda g: g[0], reverse=True)
        dirs = [g[1] for g in gaps[:count]]
        while len(dirs) < count:
            # Extra pairs: evenly fill remaining slots from the largest gap midpoints.
            dirs.append(2.0 * math.pi * len(dirs) / count)
        return dirs[:count]

    def _draw_lone_pair_at(self, p: QPainter, cx: float, cy: float, angle: float, style) -> None:
        """Draw one Lewis lone pair (two dots) along ``angle`` from the atom center."""
        r = max(10.0, float(getattr(self, "radius", 14)) * 0.95)
        pair_sep = max(3.0, float(style.bond_width_px) * 2.2)
        dot_r = max(1.35, float(style.bond_width_px) * 0.85)
        ux, uy = math.cos(angle), math.sin(angle)
        px, py = -uy, ux
        mx, my = cx + ux * r, cy + uy * r
        ink = QColor(*style.ink)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(ink))
        for sign in (-1.0, 1.0):
            p.drawEllipse(
                QPointF(mx + px * pair_sep * 0.5 * sign, my + py * pair_sep * 0.5 * sign),
                dot_r,
                dot_r,
            )
        p.setBrush(Qt.NoBrush)

    def _paint_sketch_lone_pairs(self, p: QPainter, style, *, only_flagged: bool = False) -> None:
        global_on = bool(getattr(self, "show_lone_pairs", False))
        for n in self.nodes:
            if only_flagged:
                if not n.get("show_lone_pairs"):
                    continue
            elif not global_on and not n.get("show_lone_pairs"):
                continue
            n_lp = self._node_lone_pair_count(n)
            if n_lp <= 0:
                continue
            cx, cy = float(n["pos"].x()), float(n["pos"].y())
            for ang in self._lone_pair_directions(n, n_lp):
                self._draw_lone_pair_at(p, cx, cy, ang, style)

    def _node_oxidation_state(self, n: dict) -> int | None:
        if _is_wildcard_node(n) or is_rgroup_node(n):
            return None
        nid = int(n["id"])
        partners: list[tuple[str, int]] = []
        for b in self.bonds:
            a, bo, order, _s = _bond_unpack(b)
            other = bo if a == nid else a if bo == nid else None
            if other is None:
                continue
            on = next((x for x in self.nodes if x["id"] == other), None)
            if on is None:
                continue
            partners.append((str(on.get("element") or "C"), int(order)))
        # Condensed H already counted as implicit for heteroatoms; for OS include them.
        # For carbons, count only explicit neighbors (skeletal H are implicit in OS via formula).
        el = str(n.get("element") or "")
        if el == "C":
            # Estimate implicit H from valence for OS (CH4 → −4, etc.).
            fc = int(n.get("charge", 0) or 0)
            bond_sum = int(self._current_valence(nid))
            target = int(self._target_valence_for_implicit_h(el, bond_sum, fc))
            implicit_h = max(0, target - bond_sum)
        else:
            implicit_h = self._node_implicit_h_count(n)
        return sketch_oxidation_state(el, partners, implicit_h=implicit_h)

    def _draw_oxidation_state_label(self, p: QPainter, n: dict, os_val: int, style) -> None:
        pos = n["pos"]
        if os_val == 0:
            text = "0"
        else:
            text = f"{os_val:+d}".replace("-", "−")
        off = self._annotation_offset(int(n["id"]), pos, 1)
        pt = max(7, style.charge_font_pt)
        font = iupac_structure_font(pt)
        fm = QFontMetrics(font)
        tw = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
        bx = float(pos.x() + off.x() - tw / 2)
        by = float(pos.y() + off.y() + fm.ascent() / 3)
        path = QPainterPath()
        path.addText(bx, by, font, text)
        # Distinct from formal charge: muted blue-gray (coloring preserved).
        self._fill_text_path(p, path, QColor(40, 70, 120), halo_w=max(2.0, pt * 0.22))

    def _paint_sketch_oxidation_states(self, p: QPainter, style) -> None:
        for n in self.nodes:
            if not n.get("show_oxidation_state"):
                continue
            os_val = self._node_oxidation_state(n)
            if os_val is None:
                continue
            self._draw_oxidation_state_label(p, n, os_val, style)

    def _paint_sketch_structure_acs(self, p: QPainter, style) -> None:
        ink = self._acs_ink_pen(style)
        p.setPen(ink)
        p.setBrush(Qt.NoBrush)

        # Soft selection/hover underlays first so multi-bond ink stays crisp on top.
        self._paint_sketch_bond_highlights(p, style)

        for bi, bond in enumerate(self.bonds):
            i, j, order, stereo = _bond_unpack(bond)
            ni = next((n for n in self.nodes if n["id"] == i), None)
            nj = next((n for n in self.nodes if n["id"] == j), None)
            if not ni or not nj:
                continue
            self._draw_bond(p, ni, nj, order, stereo, ink)

        self._paint_sketch_atom_overlays(p, style)
        self._paint_sketch_element_labels(p, style)

    def _paint_sketch_element_labels(self, p: QPainter, style) -> None:
        """Draw atom symbols / contracted labels (ACS path and RDKit-bond path)."""
        for n in self.nodes:
            pos = n["pos"]
            el = n["element"]
            abbrev = n.get("abbrev")
            if abbrev:
                c = rdkit_default_element_rgb(str(el) if el else "C")
                self._draw_element_label(
                    p, pos, str(abbrev), font_pt=style.label_font_pt, fill=QColor(*c), node=n
                )
                ch = n.get("charge", 0)
                if ch:
                    self._draw_formal_charge(
                        p, pos, ch, symbol=str(abbrev), font_pt=style.label_font_pt, node=n
                    )
            elif is_rgroup_node(n):
                self._draw_element_label(
                    p,
                    pos,
                    str(el),
                    font_pt=style.label_font_pt,
                    fill=QColor(20, 70, 140),
                    node=n,
                )
                continue
            elif el == WILDCARD_ELEMENT:
                self._draw_element_label(
                    p, pos, "*", font_pt=style.label_font_pt + 1, fill=QColor(80, 40, 120), node=n
                )
                sub = ",".join(_normalize_wildcard_elements(n))
                if len(sub) > 10:
                    sub = sub[:9] + "..."
                self._draw_element_label(
                    p,
                    QPoint(pos.x(), pos.y() + 10),
                    sub,
                    font_pt=style.charge_font_pt,
                    fill=QColor(60, 60, 60),
                    node=n,
                )
                ch = n.get("charge", 0)
                if ch:
                    self._draw_formal_charge(
                        p, pos, ch, symbol="*", font_pt=style.label_font_pt, node=n
                    )
                continue

            if el == "C":
                has_conn = any(
                    (_bond_unpack(b)[0] == n["id"] or _bond_unpack(b)[1] == n["id"])
                    for b in self.bonds
                )
                show_c = bool(n.get("explicit_carbon")) or not has_conn
                ch = int(n.get("charge", 0) or 0)
                if show_c:
                    c = rdkit_default_element_rgb(el)
                    # Explicit Carbon: include implicit H (CH3, CH2, …); charge drawn after H (GR-5.1).
                    label = (
                        self._explicit_carbon_display_label(n) if n.get("explicit_carbon") else "C"
                    )
                    self._draw_element_label(
                        p, pos, label, font_pt=style.label_font_pt, fill=QColor(*c), node=n
                    )
                    if ch:
                        self._draw_formal_charge(
                            p, pos, ch, symbol=label, font_pt=style.label_font_pt, node=n
                        )
                elif ch:
                    # Prefer showing C with charge (GR-5.1) even when skeletal C is hidden.
                    c = rdkit_default_element_rgb(el)
                    self._draw_element_label(
                        p, pos, "C", font_pt=style.label_font_pt, fill=QColor(*c), node=n
                    )
                    self._draw_formal_charge(
                        p, pos, ch, symbol="C", font_pt=style.label_font_pt, node=n
                    )
            else:
                c = rdkit_default_element_rgb(el)
                label = self._node_condensed_label(n) or el
                self._draw_element_label(
                    p, pos, label, font_pt=style.label_font_pt, fill=QColor(*c), node=n
                )
                ch = n.get("charge", 0)
                if ch:
                    self._draw_formal_charge(
                        p, pos, ch, symbol=label, font_pt=style.label_font_pt, node=n
                    )

    def _paint_sketch_structure(self, p: QPainter, style) -> None:
        if self._try_paint_rdkit_sketch_structure(p):
            self._paint_sketch_bond_highlights(p, style)
            # RDKit pixmap is drawn with noAtomLabels; paint crisp ACS heteroatom labels here.
            self._paint_sketch_element_labels(p, style)
            self._paint_sketch_atom_overlays(p, style)
            return
        self._paint_sketch_structure_acs(p, style)

    def _paint_reaction_arrow(
        self, p: QPainter, start: QPoint, end: QPoint, style, *, preview: bool = False
    ) -> None:
        x1, y1 = float(start.x()), float(start.y())
        x2, y2 = float(end.x()), float(end.y())
        dx, dy = x2 - x1, y2 - y1
        length = max(math.hypot(dx, dy), 1.0)
        ux, uy = dx / length, dy / length
        px, py = -uy, ux
        head = max(10.0, min(16.0, length * 0.18))
        half = max(5.0, style.wedge_half_width_px * 0.85)
        color = QColor(60, 120, 200) if preview else QColor(20, 20, 20)
        if getattr(self, "selected_reaction_arrow", False) and not preview:
            color = QColor(40, 90, 180)
        pen = QPen(color)
        pen.setWidthF(max(1.8, style.bond_width_px * 1.35))
        pen.setCapStyle(Qt.RoundCap)
        if preview:
            pen.setStyle(Qt.DashLine)
        sx2 = x2 - ux * head
        sy2 = y2 - uy * head
        p.setPen(pen)
        p.drawLine(QPointF(x1, y1), QPointF(sx2, sy2))
        p.setBrush(QBrush(color))
        p.setPen(Qt.NoPen)
        p.drawPolygon(
            QPolygonF(
                [
                    QPointF(x2, y2),
                    QPointF(sx2 + px * half, sy2 + py * half),
                    QPointF(sx2 - px * half, sy2 - py * half),
                ]
            )
        )
        p.setBrush(Qt.NoBrush)

    def _paint_reaction_pluses(self, p: QPainter, style) -> None:
        pts = self._reaction_plus_positions()
        if not pts:
            return
        arm = max(6.0, style.label_font_pt * 0.55)
        pen = QPen(QColor(20, 20, 20))
        pen.setWidthF(max(1.6, style.bond_width_px * 1.1))
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        for x, y in pts:
            p.drawLine(QPointF(x - arm, y), QPointF(x + arm, y))
            p.drawLine(QPointF(x, y - arm), QPointF(x, y + arm))

    def paintEvent(self, ev) -> None:
        self._ensure_bonds_sanitized()
        style = self._acs_style()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(255, 255, 255))
        p.setRenderHint(QPainter.Antialiasing, True)

        p.save()
        self._apply_view_transform(p)
        self._paint_sketch_structure(p, style)
        arr = getattr(self, "reaction_arrow", None)
        if arr is not None:
            self._paint_reaction_arrow(p, arr[0], arr[1], style)
            self._paint_reaction_pluses(p, style)
        if getattr(self, "_arrow_dragging", False) and self._arrow_drag_start is not None:
            end = self._arrow_drag_pos or self._arrow_drag_start
            self._paint_reaction_arrow(p, self._arrow_drag_start, end, style, preview=True)
        if self._is_dragging and self._drag_start is not None and self._drag_pos is not None:
            start = next((n for n in self.nodes if n["id"] == self._drag_start), None)
            if start:
                dpen = QPen(QColor(60, 120, 200))
                dpen.setStyle(Qt.DashLine)
                dpen.setWidthF(max(1.0, style.bond_width_px * 0.75))
                p.setPen(dpen)
                p.drawLine(start["pos"], self._drag_pos)
        p.restore()

        if self._selection_rect is not None:
            r = self._selection_rect
            sel_pen = QPen(QColor(80, 120, 200))
            sel_pen.setStyle(Qt.DashLine)
            sel_pen.setWidth(1)
            p.setPen(sel_pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(r.left(), r.top(), r.width(), r.height())
        lasso_pts = getattr(self, "_lasso_points", None) or []
        if (
            self._selecting
            and getattr(self, "select_tool", "box") == "lasso"
            and len(lasso_pts) >= 2
        ):
            path = QPainterPath()
            path.moveTo(QPointF(float(lasso_pts[0].x()), float(lasso_pts[0].y())))
            for wp in lasso_pts[1:]:
                path.lineTo(QPointF(float(wp.x()), float(wp.y())))
            if len(lasso_pts) >= 3:
                path.closeSubpath()
                p.setBrush(QBrush(QColor(80, 120, 200, 28)))
            else:
                p.setBrush(Qt.NoBrush)
            sel_pen = QPen(QColor(80, 120, 200))
            sel_pen.setStyle(Qt.DashLine)
            sel_pen.setWidth(1)
            p.setPen(sel_pen)
            p.drawPath(path)
