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

"""IUPAC ring geometry: bond-length polygons, large rings, substituents."""

from __future__ import annotations

import math

from PyQt5.QtCore import QPoint
from PyQt5.QtWidgets import QWidget

from molmanager.ui.sketcher.bonds import _bond_make, _bond_unpack
from molmanager.ui.sketcher.dialog import SketcherDialog
from molmanager.ui.sketcher.iupac_rings import (
    exterior_ring_substituent_direction,
    large_ring_offsets_y_up,
    ring_circumradius_for_bond_length,
    regular_ring_offsets_y_up,
)
from molmanager.ui.sketcher.iupac_style import iupac_sketch_style
from molmanager.ui.sketcher.widget import SketchWidget


def _ring_edge_lengths(pts: list[tuple[float, float]]) -> list[float]:
    n = len(pts)
    return [
        math.hypot(pts[(i + 1) % n][0] - pts[i][0], pts[(i + 1) % n][1] - pts[i][1])
        for i in range(n)
    ]


def test_sulfonamide_and_sulfoxide_valence_ok(qapp) -> None:  # noqa: ARG001
    """Hypervalent S (sulfone / sulfonamide / sulfoxide) must not flag valence errors."""
    from molmanager.ui.sketcher.bonds import _bond_make
    from molmanager.ui.sketcher.widget import SketchWidget

    w = SketchWidget()
    # Me–S(=O)(=O)–NH2 style: S with two doubles to O and singles to C and N.
    w.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "S"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "O"},
        {"id": 3, "pos": QPoint(100, 160), "element": "O"},
        {"id": 4, "pos": QPoint(40, 100), "element": "N"},
    ]
    w.bonds = [
        _bond_make(0, 1, 1, 0),
        _bond_make(0, 2, 2, 0),
        _bond_make(0, 3, 2, 0),
        _bond_make(0, 4, 1, 0),
    ]
    w.next_id = 5
    w._after_sketch_edit(notify=False)
    assert 0 not in w._valence_violations
    assert w._max_valence("S") >= 6
    assert w._node_implicit_h_count(w.nodes[0]) == 0
    assert w._node_condensed_label(w.nodes[0]) is None

    # Sulfoxide: S with one double O and two carbons (bond-order sum 4).
    w2 = SketchWidget()
    w2.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "S"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(40, 100), "element": "C"},
        {"id": 3, "pos": QPoint(100, 40), "element": "O"},
    ]
    w2.bonds = [
        _bond_make(0, 1, 1, 0),
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 2, 0),
    ]
    w2.next_id = 4
    w2._after_sketch_edit(notify=False)
    assert 0 not in w2._valence_violations
    assert w2._node_implicit_h_count(w2.nodes[0]) == 0


def test_divalent_sulfur_no_spurious_hydrogens(qapp) -> None:  # noqa: ARG001
    """Disulfides / thioethers are S(II): label as S, not SH4."""
    from molmanager.ui.sketcher.bonds import _bond_make
    from molmanager.ui.sketcher.widget import SketchWidget

    # Me–S–S–Me
    w = SketchWidget()
    w.nodes = [
        {"id": 0, "pos": QPoint(40, 100), "element": "C"},
        {"id": 1, "pos": QPoint(100, 100), "element": "S"},
        {"id": 2, "pos": QPoint(160, 100), "element": "S"},
        {"id": 3, "pos": QPoint(220, 100), "element": "C"},
    ]
    w.bonds = [
        _bond_make(0, 1, 1, 0),
        _bond_make(1, 2, 1, 0),
        _bond_make(2, 3, 1, 0),
    ]
    w.next_id = 4
    w._after_sketch_edit(notify=False)
    assert 1 not in w._valence_violations
    assert 2 not in w._valence_violations
    assert w._node_implicit_h_count(w.nodes[1]) == 0
    assert w._node_condensed_label(w.nodes[1]) is None
    assert w._node_implicit_h_count(w.nodes[2]) == 0

    # Me–S–Me thioether
    w2 = SketchWidget()
    w2.nodes = [
        {"id": 0, "pos": QPoint(40, 100), "element": "C"},
        {"id": 1, "pos": QPoint(100, 100), "element": "S"},
        {"id": 2, "pos": QPoint(160, 100), "element": "C"},
    ]
    w2.bonds = [_bond_make(0, 1, 1, 0), _bond_make(1, 2, 1, 0)]
    w2.next_id = 3
    w2._after_sketch_edit(notify=False)
    assert w2._node_implicit_h_count(w2.nodes[1]) == 0
    assert w2._node_condensed_label(w2.nodes[1]) is None

    # Me–SH thiol → SH
    w3 = SketchWidget()
    w3.nodes = [
        {"id": 0, "pos": QPoint(40, 100), "element": "C"},
        {"id": 1, "pos": QPoint(100, 100), "element": "S"},
    ]
    w3.bonds = [_bond_make(0, 1, 1, 0)]
    w3.next_id = 2
    w3._after_sketch_edit(notify=False)
    assert w3._node_implicit_h_count(w3.nodes[1]) == 1
    assert w3._node_condensed_label(w3.nodes[1]) == "SH"


def test_regular_ring_chords_match_bond_length() -> None:
    for n in range(3, 9):
        pts = regular_ring_offsets_y_up(n, bond_length=60)
        edges = _ring_edge_lengths(pts)
        assert abs(sorted(edges)[len(edges) // 2] - 60) < 0.05
        assert abs(ring_circumradius_for_bond_length(n, 60) * 2 * math.sin(math.pi / n) - 60) < 1e-6


def test_large_rings_are_reentrant_with_uniform_bonds() -> None:
    for n in range(9, 15):
        pts = large_ring_offsets_y_up(n, bond_length=60)
        edges = _ring_edge_lengths(pts)
        assert abs(sorted(edges)[len(edges) // 2] - 60) < 1.5
        crosses = []
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            x2, y2 = pts[(i + 2) % n]
            crosses.append((x1 - x0) * (y2 - y1) - (y1 - y0) * (x2 - x1))
        assert any(c * crosses[0] < 0 for c in crosses)


def test_large_rings_not_circular() -> None:
    """Macrocycles must be hexagonal/reentrant, not regular circular polygons."""
    for n in range(9, 15):
        pts = large_ring_offsets_y_up(n, bond_length=60)
        # Regular n-gon: all radii equal. Hex form: radii vary (reentrants).
        radii = [math.hypot(x, y) for x, y in pts]
        assert max(radii) - min(radii) > 5.0

    from molmanager.ui.sketcher.iupac_rings import (
        PREFERRED_RING_BOND_ANGLES_DEG,
        _interior_bond_angles_deg,
    )

    for n in (10, 12, 14):
        pts = large_ring_offsets_y_up(n, bond_length=60)
        angs = _interior_bond_angles_deg(pts)
        for ang in angs:
            assert min(abs(ang - p) for p in PREFERRED_RING_BOND_ANGLES_DEG) < 15.0


def test_macrocycle_uses_local_painter_not_rdkit(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QPoint

    from molmanager.ui.sketcher.widget import SketchWidget

    w = SketchWidget()
    w._median_bond_length_px = 60.0
    w.add_ring(12, center=QPoint(300, 300))
    assert len(w.nodes) == 12
    assert w._has_macrocycle_ring()
    assert not w._should_paint_sketch_with_rdkit()
    # Geometry must be reentrant (not circular).
    import math

    cx = sum(n["pos"].x() for n in w.nodes) / 12
    cy = sum(n["pos"].y() for n in w.nodes) / 12
    radii = [math.hypot(n["pos"].x() - cx, n["pos"].y() - cy) for n in w.nodes]
    assert max(radii) - min(radii) > 8.0


def test_macrocycle_load_from_mol_keeps_rdkit_table_layout(qapp) -> None:  # noqa: ARG001
    """Table→sketcher load keeps RDKit/default pose; hex only after Clean Up."""
    import math

    from rdkit import Chem

    from molmanager.ui.sketcher.widget import SketchWidget

    mol = Chem.MolFromSmiles("C1CCCCCCCCCCC1")
    w = SketchWidget()
    w.resize(800, 600)
    assert w.load_from_rdkit_mol(mol)
    assert len(w.nodes) == 12
    cx = sum(n["pos"].x() for n in w.nodes) / 12
    cy = sum(n["pos"].y() for n in w.nodes) / 12
    radii = [math.hypot(n["pos"].x() - cx, n["pos"].y() - cy) for n in w.nodes]
    # RDKit default macrocycle is roughly circular (low radius spread).
    assert max(radii) - min(radii) < 8.0
    assert w.cleanup_layout_2d()
    cx = sum(n["pos"].x() for n in w.nodes) / 12
    cy = sum(n["pos"].y() for n in w.nodes) / 12
    radii = [math.hypot(n["pos"].x() - cx, n["pos"].y() - cy) for n in w.nodes]
    assert max(radii) - min(radii) > 8.0


def test_macrocycle_stereo_cip_assigned_on_load(qapp) -> None:  # noqa: ARG001
    from rdkit import Chem

    from molmanager.ui.sketcher.bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE, _bond_unpack
    from molmanager.ui.sketcher.widget import SketchWidget

    mol = Chem.MolFromSmiles("C[C@H]1CCCC[C@@H](C)CCCCC1")
    w = SketchWidget()
    w.resize(800, 600)
    assert w.load_from_rdkit_mol(mol)
    w._after_sketch_edit(notify=False)
    assert len(w._chiral_center_ids) >= 2
    assert set(w._stereo_cip_by_node_id.values()) <= {"R", "S"}
    assert len(w._stereo_cip_by_node_id) >= 2
    # ST-1.2 / ST-1.3: methyl substituents carry wedge/hash; no stereo-H clutter.
    assert not any(n.get("element") == "H" for n in w.nodes)
    stereo_bonds = [
        _bond_unpack(b)
        for b in w.bonds
        if _bond_unpack(b)[3] in (BOND_STEREO_WEDGE, BOND_STEREO_HASH)
    ]
    assert stereo_bonds
    # Wedges present → no unspecified-stereo cautions at those centers.
    assert not (w._chiral_center_ids & w._chiral_stereo_issue_ids)


def test_macrocycle_skips_stereo_h_when_substituent_can_wedge() -> None:
    """ST-1.2/1.3: omit stereo-H when a substituent can take the wedge/hash."""
    from rdkit import Chem

    from molmanager.ui.sketcher.sketch_rdkit import SketchWidgetRdkitMixin

    macro = Chem.MolFromSmiles("C[C@H]1CCCCCCCCCC1")
    Chem.AssignStereochemistry(macro, cleanIt=True, force=True)
    assert SketchWidgetRdkitMixin._stereocenter_indices_needing_explicit_h(macro) == []

    acyclic = Chem.MolFromSmiles("C[C@H](O)N")
    Chem.AssignStereochemistry(acyclic, cleanIt=True, force=True)
    assert SketchWidgetRdkitMixin._stereocenter_indices_needing_explicit_h(acyclic) == []

    # Ring-only ligands + H: no exocyclic wedge target → stereo-H is required.
    fused = Chem.MolFromSmiles("C1CC[C@H]2CCCC[C@@H]12")
    Chem.AssignStereochemistry(fused, cleanIt=True, force=True)
    assert SketchWidgetRdkitMixin._stereocenter_indices_needing_explicit_h(fused) != []


def test_load_omits_stereo_h_when_substituent_can_wedge(qapp) -> None:  # noqa: ARG001
    """Table→sketcher: wedge on a heavy substituent; no explicit stereo-H (ST-1.2)."""
    from rdkit import Chem

    from molmanager.ui.sketcher.bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE, _bond_unpack
    from molmanager.ui.sketcher.widget import SketchWidget

    mol = Chem.MolFromSmiles("C[C@H](O)N")
    w = SketchWidget()
    w.resize(800, 600)
    assert w.load_from_rdkit_mol(mol)
    w._after_sketch_edit(notify=False)
    assert not any(n.get("element") == "H" for n in w.nodes)
    stereo_bonds = [
        _bond_unpack(b)
        for b in w.bonds
        if _bond_unpack(b)[3] in (BOND_STEREO_WEDGE, BOND_STEREO_HASH)
    ]
    assert stereo_bonds
    assert w._chiral_center_ids
    assert not (w._chiral_center_ids & w._chiral_stereo_issue_ids)


def test_load_draws_stereo_h_when_ring_only_ligands(qapp) -> None:  # noqa: ARG001
    """When no exocyclic wedge target exists, draw stereo-H (ST-1.2 / ST-1.3)."""
    from rdkit import Chem

    from molmanager.ui.sketcher.bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE, _bond_unpack
    from molmanager.ui.sketcher.widget import SketchWidget

    mol = Chem.MolFromSmiles("C1CC[C@H]2CCCC[C@@H]12")
    w = SketchWidget()
    w.resize(800, 600)
    assert w.load_from_rdkit_mol(mol)
    w._after_sketch_edit(notify=False)
    h_ids = {n["id"] for n in w.nodes if n.get("element") == "H"}
    assert h_ids, "expected stereochemical hydrogens when only ring ligands exist"
    stereo_bonds = [
        _bond_unpack(b)
        for b in w.bonds
        if _bond_unpack(b)[3] in (BOND_STEREO_WEDGE, BOND_STEREO_HASH)
    ]
    assert stereo_bonds
    assert any(a in h_ids or b in h_ids for a, b, _o, _s in stereo_bonds)


def test_stereo_with_wedge_not_unspecified_caution(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtCore import QPoint

    from molmanager.ui.sketcher.bonds import BOND_STEREO_WEDGE
    from molmanager.ui.sketcher.widget import SketchWidget

    w = SketchWidget()
    # Simple chiral carbon with a wedge — CIP may or may not assign, but must not caution.
    w.nodes = [
        {"id": 0, "pos": QPoint(100, 100), "element": "C"},
        {"id": 1, "pos": QPoint(160, 100), "element": "C"},
        {"id": 2, "pos": QPoint(100, 40), "element": "O"},
        {"id": 3, "pos": QPoint(40, 100), "element": "N"},
        {"id": 4, "pos": QPoint(100, 160), "element": "F"},
    ]
    w.bonds = [
        _bond_make(0, 1, 1, BOND_STEREO_WEDGE),
        _bond_make(0, 2, 1, 0),
        _bond_make(0, 3, 1, 0),
        _bond_make(0, 4, 1, 0),
    ]
    w.next_id = 5
    w._after_sketch_edit(notify=False)
    assert 0 not in w._chiral_stereo_issue_ids

    from molmanager.ui.sketcher.iupac_rings import rotate_offsets_to_inward_heteroatoms

    pts = large_ring_offsets_y_up(12, bond_length=60)
    radii = [math.hypot(x, y) for x, y in pts]
    inward = min(range(12), key=lambda i: radii[i])
    # Put O at index 0 in the element list; after rotate it should sit on an inward site.
    els = ["O"] + ["C"] * 11
    rotated = rotate_offsets_to_inward_heteroatoms(pts, els)
    # Element index 0 maps to rotated[0]; that vertex should be among the most inward.
    r0 = math.hypot(*rotated[0])
    assert r0 <= sorted(radii)[3]
    assert inward >= 0  # smoke: inward index exists


def test_add_ring_uses_median_chord(qapp) -> None:  # noqa: ARG001
    w = SketchWidget()
    w._median_bond_length_px = 60.0
    ids = w.add_ring(5, center=QPoint(200, 200))
    assert len(ids) == 5
    edges = []
    by = {n["id"]: n for n in w.nodes}
    for a, b, _o, _s in w.bonds:
        pa, pb = by[a]["pos"], by[b]["pos"]
        edges.append(math.hypot(pb.x() - pa.x(), pb.y() - pa.y()))
    assert abs(sorted(edges)[len(edges) // 2] - 60) < 1.5


def test_exterior_substituent_bisector() -> None:
    # Two ring bonds at 0° and 120° → larger exterior gap midpoint near 240° / -120°.
    vec = exterior_ring_substituent_direction([0.0, math.radians(120)])
    assert vec is not None
    ang = math.atan2(vec[1], vec[0])
    # Should point roughly opposite the 60° interior bisector.
    assert abs(((ang - math.radians(240) + math.pi) % (2 * math.pi)) - math.pi) < math.radians(20)


def test_bond_width_near_label_stroke() -> None:
    style = iupac_sketch_style(60)
    # Roughly on the order of a few pixels; within GR-1.2 vs ACS baseline.
    assert 1.0 <= style.bond_width_px <= 8.0
    assert 4 <= style.hash_bar_count <= 10


def _screen_cross(ax: float, ay: float, bx: float, by: float, px: float, py: float) -> float:
    """Signed area of A→B against A→P in screen coordinates."""
    return (bx - ax) * (py - ay) - (by - ay) * (px - ax)


def _fused_atoms_are_outside(widget: SketchWidget, bond_index: int, old_ids: set[int]) -> bool:
    """True when every new atom sits across the bond from the ring it was fused to."""
    a_id, b_id, _order, _stereo = _bond_unpack(widget.bonds[bond_index])
    na = next(node for node in widget.nodes if node["id"] == a_id)
    nb = next(node for node in widget.nodes if node["id"] == b_id)
    ax, ay = float(na["pos"].x()), float(na["pos"].y())
    bx, by = float(nb["pos"].x()), float(nb["pos"].y())
    old = [node for node in widget.nodes if node["id"] in old_ids]
    cx = sum(float(node["pos"].x()) for node in old) / len(old)
    cy = sum(float(node["pos"].y()) for node in old) / len(old)
    interior = _screen_cross(ax, ay, bx, by, cx, cy)
    new_nodes = [node for node in widget.nodes if node["id"] not in old_ids]
    if not new_nodes or abs(interior) < 1.0:
        return False
    for node in new_nodes:
        side = _screen_cross(ax, ay, bx, by, float(node["pos"].x()), float(node["pos"].y()))
        if side * interior >= 0:
            return False
        nearest = min(
            math.hypot(node["pos"].x() - other["pos"].x(), node["pos"].y() - other["pos"].y())
            for other in old
        )
        if nearest < 20.0:
            return False
    return True


def test_fused_ring_sits_outside_the_attached_ring(qapp) -> None:  # noqa: ARG001
    """Ortho-fusion shares the clicked bond and grows away from that ring."""
    for template in ("Benzene", "Cyclopentyl", "Cyclopropane"):
        for bond_index in range(6):
            widget = SketchWidget()
            widget.resize(800, 600)
            widget._median_bond_length_px = 60.0
            widget.place_template("Cyclohexyl", center=QPoint(400, 300))
            old_ids = {node["id"] for node in widget.nodes}
            widget.place_template(template, fuse_bond=bond_index)
            assert _fused_atoms_are_outside(widget, bond_index, old_ids)

    widget = SketchWidget()
    widget.resize(800, 600)
    widget._median_bond_length_px = 60.0
    widget.place_template("Cyclohexyl", center=QPoint(400, 300))
    old_ids = {node["id"] for node in widget.nodes}
    widget.place_template("Naphthalene", fuse_bond=2)
    assert _fused_atoms_are_outside(widget, 2, old_ids)


def test_spiro_and_fusion_placement(qapp) -> None:  # noqa: ARG001
    dlg = SketcherDialog(QWidget())
    c = dlg.canvas
    c._median_bond_length_px = 60.0
    c.place_template("Cyclohexyl", center=QPoint(200, 200))
    assert len(c.nodes) == 6
    # Fuse benzene onto a ring bond.
    c.place_template("Benzene", fuse_bond=0)
    assert len(c.nodes) == 10  # 6 + 4 new (2 shared)
    # Spiro: attach cyclopropane to a ring atom.
    before = len(c.nodes)
    ring_atom = c.nodes[0]["id"]
    c.place_template("Cyclopropane", attach_to=ring_atom)
    assert len(c.nodes) == before + 2  # share 1, add 2
    dlg.close()
