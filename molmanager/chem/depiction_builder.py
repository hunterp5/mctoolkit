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

"""Build a :class:`DepictionScene` from an RDKit molecule, without Qt.

Coordinates come from :func:`~molmanager.chem.depiction_layout.layout_for_drawing`,
then RDKit's ``PrepareMolForDrawing`` sets the Kekulé form, wedges and added stereo
hydrogens as the PNG path does. The geometry follows RDKit's drawer where it agrees with the
IUPAC 2008 recommendations (docs/IUPAC_DRAWING.md) and the IUPAC rule where it
does not:

- Lengths are fractions of the mean bond length, so a scene has no pixel size.
- Ring double bonds put the second line inside the preferred ring (GR-1.10),
  ending on the angle bisectors so it stays parallel inside the ring corner.
- A double bond to a labelled terminal atom, or with no substituents to lean
  towards, is centred on the bond axis; any other one is offset towards the
  side with more substituents.
- Multi-character labels reverse when bonds come only from the right (GR-2.1.6),
  with charges kept at the free end of the label.
- Bonds stop at padded label boxes measured with the bundled font's metrics.
- Fragments are slid apart until their labels no longer overlap, so salts read.

Anything this builder cannot draw faithfully is reported by
:func:`scene_fallback_reason` so the caller keeps the RDKit picture for that row.
"""

from __future__ import annotations

import math

from rdkit import Chem
from rdkit.Chem.Draw import rdMolDraw2D

from molmanager.chem.depiction_scene import (
    MAX_COLOUR_ROLE,
    NO_INDEX,
    SCRIPT_SCALE,
    DepictionScene,
    Fill,
    Label,
    LabelOrientation,
    LabelPiece,
    PieceKind,
    Stroke,
    StrokeStyle,
    scene_bounds,
)
from molmanager.chem.depiction_layout import (
    LayoutOptions,
    current_layout_options,
    layout_for_drawing,
)
from molmanager.chem.depiction_text import cap_height, text_advance, text_ink_bounds

# Bump whenever the builder draws the same molecule differently, so cached scenes
# (saved in session files) are rebuilt instead of showing the old picture.
BUILDER_REVISION = 4

# Fractions of the mean bond length.
DOUBLE_BOND_OFFSET = 0.15
LABEL_EM = 0.55
LABEL_PADDING = 0.05
WEDGE_HALF_WIDTH = 0.1
HASH_SPACING = 0.1
FRAGMENT_GAP = 0.5
STEREO_H_LENGTH = 0.8
MIN_HASH_DASHES = 4
# Fractions of the normal label em size.
SUBSCRIPT_DROP = 0.25
SUPERSCRIPT_RISE = 0.45
# Space between the element line and stacked hydrogens above or below it.
_STACK_GAP = 0.3
# A bond counts as leaving a label sideways when its unit x exceeds this.
_SIDEWAYS = 0.1
# Bond length RDKit uses for generated coordinates, for molecules without bonds.
DEFAULT_BOND_LENGTH = 1.5

_DRAWABLE_BOND_TYPES = {
    Chem.BondType.SINGLE,
    Chem.BondType.DOUBLE,
    Chem.BondType.TRIPLE,
    Chem.BondType.AROMATIC,
}
# Lone atoms whose hydrogens are written first: H2O, H2S, HF, HCl, ...
_HYDROGEN_FIRST = {8, 9, 16, 17, 34, 35, 52, 53, 85}
_MINUS = "\u2212"
# Bisector ends are only used between these angles; outside them the end is inset.
_MIN_BISECT_ANGLE = math.radians(20)
_MAX_BISECT_ANGLE = math.radians(170)

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def _is_placeholder(atom) -> bool:
    """A molfile ``R`` / ``*`` atom: a dummy whose query matches any atom."""
    return atom.GetAtomicNum() == 0 and atom.DescribeQuery().startswith("AtomNull")


def scene_fallback_reason(mol) -> str | None:
    """Why *mol* needs the RDKit picture, or ``None`` when a scene can be built.

    Reasons are short stable tokens, so fallback rates can be counted by reason.
    """
    if mol is None or mol.GetNumAtoms() == 0:
        return "empty"
    if mol.GetNumAtoms() >= NO_INDEX or mol.GetNumBonds() >= NO_INDEX:
        return "too_large"
    if Chem.GetMolSubstanceGroups(mol):
        return "substance_groups"
    for atom in mol.GetAtoms():
        if atom.HasQuery() and not _is_placeholder(atom):
            return "query_atom"
        if atom.GetAtomicNum() > MAX_COLOUR_ROLE:
            return "unknown_element"
        if atom.GetNumRadicalElectrons():
            return "radical"
        if atom.HasProp("_displayLabel") or atom.HasProp("_displayLabelW"):
            return "display_label"
    for bond in mol.GetBonds():
        if bond.HasQuery():
            return "query_bond"
        if bond.GetBondType() not in _DRAWABLE_BOND_TYPES:
            return f"bond_{str(bond.GetBondType()).lower()}"
    return None


def scene_revision(layout: LayoutOptions | None = None) -> int:
    """Cache revision of scenes built now: the builder revision plus the layout options."""
    options = layout if layout is not None else current_layout_options()
    return BUILDER_REVISION * 8 + options.token


def build_scene(
    mol, layout: LayoutOptions | None = None
) -> tuple[DepictionScene | None, str | None]:
    """``(scene, None)`` for a drawable molecule, else ``(None, reason)``.

    *layout* defaults to :func:`current_layout_options`; pass it when building many scenes.
    """
    reason = scene_fallback_reason(mol)
    if reason is not None:
        return None, reason
    try:
        prepared = rdMolDraw2D.PrepareMolForDrawing(layout_for_drawing(mol, layout))
    except (RuntimeError, ValueError):
        return None, "prepare_failed"
    if any(b.GetBondType() == Chem.BondType.AROMATIC for b in prepared.GetBonds()):
        return None, "not_kekulized"
    return _SceneBuilder(prepared, first_added_atom=mol.GetNumAtoms()).build(), None


def _sub(p: Point, q: Point) -> Point:
    return (p[0] - q[0], p[1] - q[1])


def _add(p: Point, q: Point, scale: float = 1.0) -> Point:
    return (p[0] + q[0] * scale, p[1] + q[1] * scale)


def _lerp(p: Point, q: Point, t: float) -> Point:
    return (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t)


def _length(v: Point) -> float:
    return math.hypot(v[0], v[1])


def _unit(v: Point) -> Point:
    size = _length(v)
    if size < 1e-12:
        return (0.0, 0.0)
    return (v[0] / size, v[1] / size)


def _cross(u: Point, v: Point) -> float:
    return u[0] * v[1] - u[1] * v[0]


def _segment_distance(point: Point, p: Point, q: Point) -> float:
    """Distance from *point* to the segment ``p → q``."""
    seg = _sub(q, p)
    size = seg[0] * seg[0] + seg[1] * seg[1]
    if size < 1e-12:
        return _length(_sub(point, p))
    t = max(0.0, min(1.0, ((point[0] - p[0]) * seg[0] + (point[1] - p[1]) * seg[1]) / size))
    return _length(_sub(point, _lerp(p, q, t)))


def _gap_bisectors(angles: list[float]) -> list[Point]:
    """Unit vectors bisecting each gap between bond *angles* (radians) around an atom."""
    if not angles:
        return []
    ordered = sorted(angles)
    out = []
    for k, start in enumerate(ordered):
        end = ordered[(k + 1) % len(ordered)]
        gap = (end - start) % (2 * math.pi) or 2 * math.pi
        mid = start + gap / 2
        out.append((math.cos(mid), math.sin(mid)))
    return out


def _box_interval(p: Point, q: Point, box: Box) -> tuple[float, float] | None:
    """Parameter range of segment ``p → q`` inside *box* (Liang–Barsky), or ``None``."""
    dx = q[0] - p[0]
    dy = q[1] - p[1]
    t_in, t_out = 0.0, 1.0
    for along, room in (
        (-dx, p[0] - box[0]),
        (dx, box[2] - p[0]),
        (-dy, p[1] - box[1]),
        (dy, box[3] - p[1]),
    ):
        if abs(along) < 1e-12:
            if room < 0:
                return None
            continue
        t = room / along
        if along < 0:
            t_in = max(t_in, t)
        else:
            t_out = min(t_out, t)
        if t_in > t_out:
            return None
    return t_in, t_out


def _trim(p: Point, q: Point, boxes: list[Box]) -> tuple[float, float] | None:
    """Parameter range of ``p → q`` left after cutting off ends inside *boxes*.

    Only a box covering an end shortens the segment; ``None`` when nothing is left.
    """
    t0, t1 = 0.0, 1.0
    for box in boxes:
        inside = _box_interval(p, q, box)
        if inside is None:
            continue
        lo, hi = inside
        if lo <= t0 + 1e-9 < hi:
            t0 = hi
        elif lo < t1 - 1e-9 <= hi:
            t1 = lo
    if t1 - t0 < 1e-6:
        return None
    return t0, t1


class _SceneBuilder:
    """One molecule's scene. Use once: ``_SceneBuilder(prepared_mol).build()``.

    Atoms from *first_added_atom* on are the stereo hydrogens drawing preparation
    added; they are re-placed and left out of the mean bond length.
    """

    def __init__(self, mol, first_added_atom: int | None = None) -> None:
        self.mol = mol
        self.first_added = mol.GetNumAtoms() if first_added_atom is None else first_added_atom
        conf = mol.GetConformer()
        self.pos: list[Point] = []
        for index in range(mol.GetNumAtoms()):
            point = conf.GetAtomPosition(index)
            self.pos.append((float(point.x), float(point.y)))
        lengths = [
            _length(_sub(self.pos[b.GetBeginAtomIdx()], self.pos[b.GetEndAtomIdx()]))
            for b in mol.GetBonds()
            if max(b.GetBeginAtomIdx(), b.GetEndAtomIdx()) < self.first_added
        ]
        lengths = [size for size in lengths if size > 1e-6]
        self.mbl = sum(lengths) / len(lengths) if lengths else DEFAULT_BOND_LENGTH
        self.em = LABEL_EM * self.mbl
        self._place_added_hydrogens()
        self.roles = [atom.GetAtomicNum() for atom in mol.GetAtoms()]
        self.trim_boxes: dict[int, Box] = {}
        self._stereo_double_bonds: set[int] | None = None
        self.strokes: list[Stroke] = []
        self.fills: list[Fill] = []
        self.labels: list[Label] = []

    def build(self) -> DepictionScene:
        labels = self._labels()
        if self._separate_fragments(labels):
            labels = self._labels()
        pad = LABEL_PADDING * self.mbl
        for index, label in labels.items():
            self.labels.append(label)
            x0, y0, x1, y1 = label.box
            self.trim_boxes[index] = (x0 - pad, y0 - pad, x1 + pad, y1 + pad)
        for bond in self.mol.GetBonds():
            self._bond(bond)
        atoms = tuple(self.pos)
        return DepictionScene(
            atoms=atoms,
            bond_count=self.mol.GetNumBonds(),
            mean_bond_length=self.mbl,
            label_size=self.em,
            bounds=scene_bounds(atoms, self.strokes, self.fills, self.labels),
            strokes=tuple(self.strokes),
            fills=tuple(self.fills),
            labels=tuple(self.labels),
        )

    def _place_added_hydrogens(self) -> None:
        """Put each added stereo hydrogen where it has the most room.

        Drawing preparation adds them one unit from their atom whatever the drawing's
        bond length, often towards a neighbouring hydrogen or substituent (two ring
        fusion hydrogens can land half a unit apart). Candidates are RDKit's direction
        and the bisector of every gap between the atom's other bonds, at
        ``STEREO_H_LENGTH`` of the mean bond length; the one farthest from other
        atoms and bonds wins. With three other bonds in the plane the wedge reads the
        same in any gap, so the stereo is unchanged.
        """
        for index in range(self.first_added, self.mol.GetNumAtoms()):
            atom = self.mol.GetAtomWithIdx(index)
            if atom.GetAtomicNum() != 1 or atom.GetDegree() != 1:
                continue
            parent = atom.GetNeighbors()[0].GetIdx()
            here = self.pos[parent]
            reach = STEREO_H_LENGTH * self.mbl
            others = [_sub(self.pos[i], here) for i in self._others(parent, index) if i < index]
            directions = [_unit(_sub(self.pos[index], here))]
            directions += _gap_bisectors([math.atan2(v[1], v[0]) for v in others])
            candidates = [_add(here, d, reach) for d in directions if d != (0.0, 0.0)]
            if candidates:
                self.pos[index] = max(candidates, key=lambda q: self._clearance(q, index))

    def _clearance(self, point: Point, hydrogen: int) -> float:
        """Distance from *point* to the nearest atom or bond placed before *hydrogen*.

        Hydrogens are placed in index order, so lower indices are heavy atoms and
        hydrogens already moved; later ones are still at RDKit's positions and ignored.
        """
        best = min(
            (_length(_sub(point, self.pos[i])) for i in range(hydrogen)),
            default=math.inf,
        )
        for bond in self.mol.GetBonds():
            a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
            if max(a, b) < hydrogen:
                best = min(best, _segment_distance(point, self.pos[a], self.pos[b]))
        return best

    def _separate_fragments(self, labels: dict[int, Label]) -> bool:
        """Slide fragments right until no two share space, labels included.

        Generated coordinates space fragments by atom position only, so ions without
        bonds (``[NH4+].[Cl-]``) sit one unit apart and their labels overlap. Fragments
        are swept left to right; each moves just clear of every fragment already placed
        that overlaps it vertically. Returns whether any atom moved.
        """
        fragments = Chem.GetMolFrags(self.mol)
        if len(fragments) < 2:
            return False
        extents = []
        for atoms in fragments:
            boxes = [labels[i].box for i in atoms if i in labels]
            boxes += [(*self.pos[i], *self.pos[i]) for i in atoms]
            extents.append(
                [
                    min(b[0] for b in boxes),
                    min(b[1] for b in boxes),
                    max(b[2] for b in boxes),
                    max(b[3] for b in boxes),
                ]
            )
        gap = FRAGMENT_GAP * self.mbl
        placed: list[list[float]] = []
        moved = False
        for order in sorted(range(len(fragments)), key=lambda k: extents[k][0]):
            box = extents[order]
            shift = max(
                (
                    other[2] + gap - box[0]
                    for other in placed
                    if other[1] < box[3] and box[1] < other[3]
                ),
                default=0.0,
            )
            if shift > 1e-9:
                box[0] += shift
                box[2] += shift
                for i in fragments[order]:
                    self.pos[i] = (self.pos[i][0] + shift, self.pos[i][1])
                moved = True
            placed.append(box)
        return moved

    # Labels

    def _labels(self) -> dict[int, Label]:
        """Label of every atom that needs one, by atom index."""
        labels = {}
        for atom in self.mol.GetAtoms():
            label = self._label(atom)
            if label is not None:
                labels[atom.GetIdx()] = label
        return labels

    def _needs_label(self, atom) -> bool:
        if atom.GetAtomicNum() != 6:
            return True
        return bool(
            atom.GetDegree() == 0
            or atom.GetIsotope()
            or atom.GetFormalCharge()
            or atom.GetAtomMapNum()
            or self._is_cumulated_centre(atom)
        )

    def _is_cumulated_centre(self, atom) -> bool:
        """Middle carbon of a straight C=C=C, which would read as one long bond (GR-1.5)."""
        bonds = atom.GetBonds()
        if len(bonds) != 2 or any(b.GetBondType() != Chem.BondType.DOUBLE for b in bonds):
            return False
        here = self.pos[atom.GetIdx()]
        u, v = (_unit(_sub(self.pos[b.GetOtherAtomIdx(atom.GetIdx())], here)) for b in bonds)
        return u[0] * v[0] + u[1] * v[1] < math.cos(_MAX_BISECT_ANGLE)

    @staticmethod
    def _hydrogen_count(atom) -> int:
        """Hydrogens written in the label; bonded carbons never show theirs."""
        if atom.GetAtomicNum() == 0 or (atom.GetAtomicNum() == 6 and atom.GetDegree()):
            return 0
        return atom.GetTotalNumHs()

    def _orientation(self, atom) -> LabelOrientation:
        """Side the hydrogens go on.

        East by default; west when bonds come only from the right (GR-2.1.6); north
        or south when bonds come from both sides, away from where the bonds point.
        """
        here = self.pos[atom.GetIdx()]
        left = right = False
        sum_y = 0.0
        for other in atom.GetNeighbors():
            dx, dy = _unit(_sub(self.pos[other.GetIdx()], here))
            sum_y += dy
            left = left or dx < -_SIDEWAYS
            right = right or dx > _SIDEWAYS
        if atom.GetDegree() == 0:
            hydrogen_first = atom.GetAtomicNum() in _HYDROGEN_FIRST and atom.GetTotalNumHs()
            return LabelOrientation.WEST if hydrogen_first else LabelOrientation.EAST
        if left and right:
            return LabelOrientation.NORTH if sum_y <= 0 else LabelOrientation.SOUTH
        return LabelOrientation.WEST if right and not left else LabelOrientation.EAST

    @staticmethod
    def _symbol(atom) -> str:
        if atom.GetAtomicNum() == 0:
            if atom.HasProp("dummyLabel") and atom.GetProp("dummyLabel").strip():
                return atom.GetProp("dummyLabel").strip()
            if atom.HasProp("_MolFileRLabel"):
                return f"R{atom.GetUnsignedProp('_MolFileRLabel')}"
            return atom.GetSymbol() or "*"
        return atom.GetSymbol()

    @staticmethod
    def _charge_text(charge: int) -> str:
        if not charge:
            return ""
        sign = "+" if charge > 0 else _MINUS
        return sign if abs(charge) == 1 else f"{abs(charge)}{sign}"

    def _size(self, kind: PieceKind) -> float:
        return self.em if kind == PieceKind.NORMAL else self.em * SCRIPT_SCALE

    def _rise(self, kind: PieceKind) -> float:
        if kind == PieceKind.SUBSCRIPT:
            return -SUBSCRIPT_DROP * self.em
        if kind == PieceKind.SUPERSCRIPT:
            return SUPERSCRIPT_RISE * self.em
        return 0.0

    def _pens(self, run: list[tuple[str, PieceKind]]) -> list[float]:
        """Pen start of each piece of *run*, from 0."""
        pens = []
        pen = 0.0
        for text, kind in run:
            pens.append(pen)
            pen += text_advance(text, self._size(kind))
        return pens

    def _place(self, run, pens, shift: float, baseline: float, placed: list, boxes: list) -> None:
        """Append *run*'s pieces at *baseline*, moved right by *shift*, and their ink boxes."""
        for (text, kind), start in zip(run, pens):
            origin = (start + shift, baseline + self._rise(kind))
            placed.append(LabelPiece(origin[0], origin[1], text, kind))
            x0, y0, x1, y1 = text_ink_bounds(text, self._size(kind))
            if x1 > x0:
                boxes.append((origin[0] + x0, origin[1] + y0, origin[0] + x1, origin[1] + y1))

    def _label(self, atom) -> Label | None:
        if not self._needs_label(atom):
            return None
        orientation = self._orientation(atom)
        isotope = [(str(atom.GetIsotope()), PieceKind.SUPERSCRIPT)] if atom.GetIsotope() else []
        element = (self._symbol(atom), PieceKind.NORMAL)
        hydrogens = []
        count = self._hydrogen_count(atom)
        if count:
            hydrogens.append(("H", PieceKind.NORMAL))
            if count > 1:
                hydrogens.append((str(count), PieceKind.SUBSCRIPT))
        charge_text = self._charge_text(atom.GetFormalCharge())
        charge = [(charge_text, PieceKind.SUPERSCRIPT)] if charge_text else []
        mapping = [(f":{atom.GetAtomMapNum()}", PieceKind.NORMAL)] if atom.GetAtomMapNum() else []

        stacked = orientation in (LabelOrientation.NORTH, LabelOrientation.SOUTH)
        if stacked and not hydrogens:
            orientation = LabelOrientation.EAST
            stacked = False
        if orientation == LabelOrientation.WEST:
            run = charge + hydrogens + isotope + [element] + mapping
        elif stacked:
            run = isotope + [element] + charge + mapping
        else:
            run = isotope + [element] + hydrogens + charge + mapping
        if len(run) == 1 and not stacked:
            orientation = LabelOrientation.CENTRE

        x, y = self.pos[atom.GetIdx()]
        pens = self._pens(run)
        element_index = run.index(element)
        ink = text_ink_bounds(element[0], self.em)
        element_centre = (ink[0] + ink[2]) / 2
        shift = x - (pens[element_index] + element_centre)
        cap = cap_height(self.em)
        baseline = y - cap / 2
        placed: list[LabelPiece] = []
        boxes: list[Box] = []
        self._place(run, pens, shift, baseline, placed, boxes)
        if stacked:
            h_pens = self._pens(hydrogens)
            h_ink = text_ink_bounds("H", self.em)
            h_shift = x - (h_ink[0] + h_ink[2]) / 2
            gap = cap + _STACK_GAP * self.em
            h_baseline = baseline + gap if orientation == LabelOrientation.NORTH else baseline - gap
            self._place(hydrogens, h_pens, h_shift, h_baseline, placed, boxes)
        if not boxes:
            return None
        box = (
            min(b[0] for b in boxes),
            min(b[1] for b in boxes),
            max(b[2] for b in boxes),
            max(b[3] for b in boxes),
        )
        return Label(
            atom=atom.GetIdx(),
            anchor=(x, y),
            orientation=orientation,
            role=self.roles[atom.GetIdx()],
            box=box,
            pieces=tuple(placed),
        )

    # Bonds

    def _bond(self, bond) -> None:
        kind = bond.GetBondType()
        if kind == Chem.BondType.DOUBLE:
            self._double(bond)
        elif kind == Chem.BondType.TRIPLE:
            self._triple(bond)
        else:
            direction = bond.GetBondDir()
            if direction == Chem.BondDir.BEGINWEDGE:
                self._wedge(bond)
            elif direction == Chem.BondDir.BEGINDASH:
                self._hash(bond)
            elif direction == Chem.BondDir.UNKNOWN:
                self._line(bond, *self._ends(bond), style=StrokeStyle.WAVY)
            else:
                self._line(bond, *self._ends(bond))

    def _ends(self, bond) -> tuple[Point, Point]:
        return self.pos[bond.GetBeginAtomIdx()], self.pos[bond.GetEndAtomIdx()]

    def _boxes(self, bond) -> list[Box]:
        found = []
        for index in (bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()):
            box = self.trim_boxes.get(index)
            if box is not None:
                found.append(box)
        return found

    def _line(self, bond, p: Point, q: Point, style: StrokeStyle = StrokeStyle.SOLID) -> None:
        """One trimmed line of *bond*, split at its midpoint when the end colours differ."""
        span = _trim(p, q, self._boxes(bond))
        if span is None:
            return
        start, end = _lerp(p, q, span[0]), _lerp(p, q, span[1])
        role_a = self.roles[bond.GetBeginAtomIdx()]
        role_b = self.roles[bond.GetEndAtomIdx()]
        index = bond.GetIdx()
        if role_a == role_b or style == StrokeStyle.WAVY:
            role = role_a if role_a == role_b else 6
            self.strokes.append(Stroke(*start, *end, role, style, index))
            return
        mid = _lerp(start, end, 0.5)
        self.strokes.append(Stroke(*start, *mid, role_a, style, index))
        self.strokes.append(Stroke(*mid, *end, role_b, style, index))

    def _frame(self, bond) -> tuple[Point, Point, Point, Point]:
        """``(p, q, direction, normal)`` with the normal to the left of ``p → q``."""
        p, q = self._ends(bond)
        direction = _unit(_sub(q, p))
        return p, q, direction, (-direction[1], direction[0])

    def _bisector_end(self, at: int, other: int, toward: int, side: float) -> Point | None:
        """Inner-line end at atom *at*: on the bisector with neighbour *toward*.

        ``None`` when *toward* is not on *side* of the bond or the angle is too open
        or too tight for a clean corner.
        """
        here = self.pos[at]
        along = _unit(_sub(self.pos[other], here))
        branch = _unit(_sub(self.pos[toward], here))
        if _cross(along, branch) * side <= 0:
            return None
        angle = math.acos(max(-1.0, min(1.0, along[0] * branch[0] + along[1] * branch[1])))
        if not _MIN_BISECT_ANGLE < angle < _MAX_BISECT_ANGLE:
            return None
        bisector = _unit(_add(along, branch))
        return _add(here, bisector, DOUBLE_BOND_OFFSET * self.mbl / math.sin(angle / 2))

    def _inner_end(self, at: int, other: int, candidates, side: float) -> Point:
        """Bisector end with the first usable neighbour, else an inset point."""
        for toward in candidates:
            end = self._bisector_end(at, other, toward, side)
            if end is not None:
                return end
        here = self.pos[at]
        direction = _unit(_sub(self.pos[other], here))
        normal = (-direction[1], direction[0])
        offset = DOUBLE_BOND_OFFSET * self.mbl
        return _add(_add(here, normal, side * offset), direction, offset)

    def _preferred_ring(self, bond) -> set[int] | None:
        """Atoms of the ring the second line goes inside, or ``None`` outside rings.

        As in RDKit: the first ring whose bonds all share this bond's aromaticity, so a
        fused aromatic bond lines the aromatic ring, otherwise the first ring.
        """
        rings = [ring for ring in self.mol.GetRingInfo().BondRings() if bond.GetIdx() in ring]
        if not rings:
            return None
        aromatic = bond.GetIsAromatic()
        chosen = next(
            (
                ring
                for ring in rings
                if all(self.mol.GetBondWithIdx(i).GetIsAromatic() == aromatic for i in ring)
            ),
            rings[0],
        )
        atoms: set[int] = set()
        for index in chosen:
            ring_bond = self.mol.GetBondWithIdx(index)
            atoms.update((ring_bond.GetBeginAtomIdx(), ring_bond.GetEndAtomIdx()))
        return atoms

    def _others(self, at: int, exclude: int) -> list[int]:
        return [
            n.GetIdx() for n in self.mol.GetAtomWithIdx(at).GetNeighbors() if n.GetIdx() != exclude
        ]

    def _double(self, bond) -> None:
        a, b = bond.GetBeginAtomIdx(), bond.GetEndAtomIdx()
        p, q, _direction, normal = self._frame(bond)
        offset = DOUBLE_BOND_OFFSET * self.mbl
        if bond.GetStereo() == Chem.BondStereo.STEREOANY and self._can_be_stereo(bond):
            half = offset / 2
            self._line(bond, _add(p, normal, half), _add(q, normal, -half))
            self._line(bond, _add(p, normal, -half), _add(q, normal, half))
            return
        ring = self._preferred_ring(bond)
        if ring is not None:
            ring_a = [i for i in self._others(a, b) if i in ring]
            ring_b = [i for i in self._others(b, a) if i in ring]
            # The next ring atom marks the inside; a ring centre misleads in puckered macrocycles.
            inside = self.pos[(ring_a or ring_b)[0]]
            side = 1.0 if _cross(_sub(q, p), _sub(inside, p)) >= 0 else -1.0
            self._line(bond, p, q)
            self._line(
                bond, self._inner_end(a, b, ring_a, side), self._inner_end(b, a, ring_b, -side)
            )
            return
        others_a, others_b = self._others(a, b), self._others(b, a)
        if self._centred(a, b, others_a, others_b):
            half = offset / 2
            self._line(bond, _add(p, normal, half), _add(q, normal, half))
            self._line(bond, _add(p, normal, -half), _add(q, normal, -half))
            return
        side = self._substituent_side(p, q, others_a + others_b)
        self._line(bond, p, q)
        self._line(
            bond, self._inner_end(a, b, others_a, side), self._inner_end(b, a, others_b, -side)
        )

    def _can_be_stereo(self, bond) -> bool:
        """Whether *bond* could be E or Z, so an "either" flag on it means something.

        Files flag bonds as either-stereo that have two identical groups on one end
        (malotilate's dithiole ylidene); drawn crossed they look twisted for nothing.
        """
        if self._stereo_double_bonds is None:
            self._stereo_double_bonds = {
                int(info.centeredOn)
                for info in Chem.FindPotentialStereo(Chem.Mol(self.mol))
                if info.type == Chem.StereoType.Bond_Double
            }
        return bond.GetIdx() in self._stereo_double_bonds

    def _centred(self, a: int, b: int, others_a: list[int], others_b: list[int]) -> bool:
        """Centre a chain double bond on its axis instead of offsetting the second line.

        Centred between two labelled atoms (N=N, N=O), at a cumulated centre (C=C=C), and
        for a terminal double bond unless the far atom has exactly one other substituent
        to lean towards, as in an aldehyde.
        """
        if a in self.trim_boxes and b in self.trim_boxes:
            return True
        for end in (a, b):
            if self._is_cumulated_centre(self.mol.GetAtomWithIdx(end)):
                return True
        for others, far_others in ((others_a, others_b), (others_b, others_a)):
            if not others and len(far_others) != 1:
                return True
        return False

    def _substituent_side(self, p: Point, q: Point, neighbours: list[int]) -> float:
        """+1 when more substituents sit left of ``p → q``, else -1; ties go to the first."""
        axis = _sub(q, p)
        signs = [1 if _cross(axis, _sub(self.pos[n], p)) > 0 else -1 for n in neighbours]
        total = sum(signs)
        if total:
            return 1.0 if total > 0 else -1.0
        return float(signs[0]) if signs else 1.0

    def _triple(self, bond) -> None:
        p, q, _direction, normal = self._frame(bond)
        offset = DOUBLE_BOND_OFFSET * self.mbl
        self._line(bond, p, q)
        self._line(bond, _add(p, normal, offset), _add(q, normal, offset))
        self._line(bond, _add(p, normal, -offset), _add(q, normal, -offset))

    def _wedge_span(self, bond) -> tuple[Point, Point, Point, float, float] | None:
        p, q, _direction, normal = self._frame(bond)
        span = _trim(p, q, self._boxes(bond))
        if span is None:
            return None
        return p, q, normal, span[0], span[1]

    def _wide_corner(self, bond, tip: Point, corner: Point, side: float) -> Point:
        """*corner* of a wedge's wide end, moved onto the neighbouring bond on *side*.

        The wedge edge from *tip* through *corner* is extended or shortened to meet the
        nearest other bond at the wide-end atom, so the wedge joins it without a notch
        or overhang. Unchanged when there is no such bond or the meeting point is far off.
        """
        far_atom = bond.GetEndAtomIdx()
        here = self.pos[far_atom]
        axis = _sub(here, tip)
        edge = _sub(corner, tip)
        best = None
        for other in self._others(far_atom, bond.GetBeginAtomIdx()):
            along = _unit(_sub(self.pos[other], here))
            if _cross(axis, along) * side <= 0:
                continue
            denom = _cross(edge, along)
            if abs(denom) < 1e-9:
                continue
            offset = _sub(here, tip)
            s = _cross(offset, along) / denom
            u = _cross(offset, edge) / denom
            if not 0.5 < s < 1.5 or not 0 <= u < 0.5 * self.mbl:
                continue
            if best is None or u < best[0]:
                best = (u, _add(tip, edge, s))
        return corner if best is None else best[1]

    def _wedge(self, bond) -> None:
        """Solid wedge, narrow at the stereocentre (the begin atom)."""
        found = self._wedge_span(bond)
        if found is None:
            return
        p, q, normal, t0, t1 = found
        half = WEDGE_HALF_WIDTH * self.mbl
        role_a = self.roles[bond.GetBeginAtomIdx()]
        role_b = self.roles[bond.GetEndAtomIdx()]
        cuts = [(t0, t1, role_a)] if role_a == role_b else [(t0, 0.5, role_a), (0.5, t1, role_b)]
        tip = _lerp(p, q, t0)
        for start, end, role in cuts:
            if end - start < 1e-6:
                continue
            near, far = _lerp(p, q, start), _lerp(p, q, end)
            far_left = _add(far, normal, end * half)
            far_right = _add(far, normal, -end * half)
            if end > 1 - 1e-9:
                far_left = self._wide_corner(bond, tip, far_left, 1.0)
                far_right = self._wide_corner(bond, tip, far_right, -1.0)
            points = []
            if start * half > 1e-6:
                points.append(_add(near, normal, start * half))
            points.append(_add(near, normal, -start * half))
            points.append(far_right)
            points.append(far_left)
            self.fills.append(Fill(tuple(points), role, bond.GetIdx()))

    def _hash(self, bond) -> None:
        """Hashed wedge: dashes widen from the stereocentre (the begin atom)."""
        found = self._wedge_span(bond)
        if found is None:
            return
        p, q, normal, t0, t1 = found
        half = WEDGE_HALF_WIDTH * self.mbl
        count = max(
            MIN_HASH_DASHES, round(_length(_sub(q, p)) * (t1 - t0) / (HASH_SPACING * self.mbl))
        )
        role_a = self.roles[bond.GetBeginAtomIdx()]
        role_b = self.roles[bond.GetEndAtomIdx()]
        for step in range(1, count + 1):
            t = t0 + (t1 - t0) * step / count
            centre = _lerp(p, q, t)
            width = max(t * half, 0.15 * half)
            role = role_a if t < 0.5 else role_b
            self.strokes.append(
                Stroke(
                    *_add(centre, normal, width),
                    *_add(centre, normal, -width),
                    role,
                    StrokeStyle.HASH,
                    bond.GetIdx(),
                )
            )
