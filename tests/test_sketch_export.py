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

"""Sketcher SMILES/SMARTS export (wildcards, isotopes, charges) and H toggle helpers."""

import math

from PyQt5.QtCore import QPoint
from rdkit import Chem

from molmanager.chem.smarts_macropatterns import mol_from_smarts
from molmanager.ui.sketcher.bonds import _bond_make
from molmanager.ui.sketcher.chem import (
    _rdkit_atom_from_sketch_node,
    _sketch_element_from_rdkit_atom,
)
from molmanager.ui.sketcher.constants import DEFAULT_WILDCARD_ELEMENTS, WILDCARD_ELEMENT
from molmanager.ui.sketcher.widget import SketchWidget
from molmanager.ui.sketcher.wildcards import _wildcard_query_smarts


def test_wildcard_smarts_uses_atomic_numbers_and_charge():
    assert _wildcard_query_smarts(["N", "O"], formal_charge=1) == "[#7,#8;+]"
    assert _wildcard_query_smarts(["C"], formal_charge=-1) == "[#6;-]"
    # Aliphatic letters must not be used — they miss aromatic atoms in search.
    assert "C" not in _wildcard_query_smarts(["C", "N"])
    a = _rdkit_atom_from_sketch_node(
        {"element": WILDCARD_ELEMENT, "wildcard_els": ["N", "O"]},
        formal_charge=1,
    )
    rw = Chem.RWMol()
    rw.AddAtom(a)
    smt = Chem.MolToSmarts(rw.GetMol())
    assert "+" in smt
    assert "#7" in smt and "#8" in smt


def test_deuterium_and_tritium_atoms():
    d = _rdkit_atom_from_sketch_node({"element": "D"})
    assert d.GetAtomicNum() == 1 and d.GetIsotope() == 2
    t = _rdkit_atom_from_sketch_node({"element": "T"})
    assert t.GetAtomicNum() == 1 and t.GetIsotope() == 3
    assert _sketch_element_from_rdkit_atom(d) == "D"
    assert _sketch_element_from_rdkit_atom(t) == "T"


def test_sketch_deuterium_smiles(qapp):  # noqa: ARG001
    w = SketchWidget()
    ids = []
    for i, el in enumerate(("C", "D")):
        nid = w.next_id
        w.next_id += 1
        w.nodes.append({"id": nid, "pos": QPoint(i * 40, 0), "element": el})
        ids.append(nid)
    w.bonds.append(_bond_make(ids[0], ids[1], 1, 0))
    smi = w.to_smiles()
    assert smi
    assert "[2H]" in smi or "D" in smi or smi.endswith("C") is False
    m = Chem.MolFromSmiles(smi)
    assert m is not None


def test_sketch_wildcard_export(qapp):  # noqa: ARG001
    w = SketchWidget()
    nid = w.next_id
    w.next_id += 1
    w.nodes.append(
        {
            "id": nid,
            "pos": QPoint(0, 0),
            "element": WILDCARD_ELEMENT,
            "wildcard_els": list(DEFAULT_WILDCARD_ELEMENTS),
            "charge": 1,
        }
    )
    smt = w.to_smarts()
    assert smt
    assert "+" in smt
    assert "#6" in smt and "#7" in smt and "#8" in smt
    # Copy-SMILES path for wildcards uses SMARTS so element lists survive.
    assert w.to_smiles() == smt
    q = mol_from_smarts(smt)
    assert q is not None
    assert Chem.MolFromSmiles("C[NH3+]").HasSubstructMatch(q)
    assert not Chem.MolFromSmiles("c1ccccc1").HasSubstructMatch(q)

    w2 = SketchWidget()
    nid = w2.next_id
    w2.next_id += 1
    w2.nodes.append(
        {
            "id": nid,
            "pos": QPoint(0, 0),
            "element": WILDCARD_ELEMENT,
            "wildcard_els": list(DEFAULT_WILDCARD_ELEMENTS),
        }
    )
    q2 = mol_from_smarts(w2.to_smarts())
    assert q2 is not None
    assert Chem.MolFromSmiles("c1ccccc1").HasSubstructMatch(q2)
    assert Chem.MolFromSmiles("CCO").HasSubstructMatch(q2)


def test_sketch_wildcard_aromatic_ring_matches_substructure(qapp):  # noqa: ARG001
    """Kekulé ring with a C/N wildcard must match aromatic benzene/pyridine (Search path)."""
    w = SketchWidget()
    ids = []
    for i in range(6):
        ang = math.radians(60 * i - 90)
        nid = w.next_id
        w.next_id += 1
        if i == 0:
            w.nodes.append(
                {
                    "id": nid,
                    "pos": QPoint(int(80 * math.cos(ang)), int(80 * math.sin(ang))),
                    "element": WILDCARD_ELEMENT,
                    "wildcard_els": ["C", "N"],
                }
            )
        else:
            w.nodes.append(
                {
                    "id": nid,
                    "pos": QPoint(int(80 * math.cos(ang)), int(80 * math.sin(ang))),
                    "element": "C",
                }
            )
        ids.append(nid)
    for i in range(6):
        order = 2 if i % 2 == 0 else 1
        w.bonds.append(_bond_make(ids[i], ids[(i + 1) % 6], order, 0))

    smt = w.to_smarts()
    assert smt
    assert "#6" in smt and "#7" in smt
    # Aromatic bond markers after sanitize (not Kekulé =/- only).
    assert ":" in smt
    q = mol_from_smarts(smt)
    assert q is not None
    assert Chem.MolFromSmiles("c1ccccc1").HasSubstructMatch(q)
    assert Chem.MolFromSmiles("c1ccncc1").HasSubstructMatch(q)
    assert Chem.MolFromSmiles("c1ccccc1O").HasSubstructMatch(q)


def test_toggle_explicit_hydrogens(qapp):  # noqa: ARG001
    w = SketchWidget()
    nid = w.next_id
    w.next_id += 1
    w.nodes.append({"id": nid, "pos": QPoint(0, 0), "element": "C"})
    assert not w.sketch_has_explicit_hydrogens()
    ok, _ = w.add_explicit_hydrogens_from_implicit()
    assert ok
    assert w.sketch_has_explicit_hydrogens()
    ok, _ = w.remove_explicit_hydrogens_from_sketch()
    assert ok
    assert not w.sketch_has_explicit_hydrogens()


def _sketch_cip_labels(w: SketchWidget) -> dict[int, str]:
    ids = {n["id"] for n in w.nodes}
    out = w._mol_from_node_ids(ids, return_idmap=True)
    assert out is not None
    mol, sk2rd = out
    cip = w._assign_tetrahedral_cip(mol)
    rd2sk = {rd: sk for sk, rd in sk2rd.items()}
    return {rd2sk[rd]: label for rd, label in cip.items() if rd in rd2sk and label in ("R", "S")}


def test_add_remove_hydrogens_preserves_tetrahedral_stereo(qapp) -> None:  # noqa: ARG001
    """Add→remove explicit H must not drop CIP / wedges (rewedge after remove)."""
    from molmanager.ui.sketcher.bonds import BOND_STEREO_HASH, BOND_STEREO_WEDGE, _bond_unpack

    mol = Chem.MolFromSmiles("C[C@H](O)N")
    w = SketchWidget()
    w.resize(600, 400)
    assert w.load_from_rdkit_mol(mol)
    before = _sketch_cip_labels(w)
    assert before, "expected at least one R/S center before H toggle"
    assert any(_bond_unpack(b)[3] in (BOND_STEREO_WEDGE, BOND_STEREO_HASH) for b in w.bonds)

    ok, err = w.add_explicit_hydrogens_from_implicit()
    assert ok, err
    assert w.sketch_has_explicit_hydrogens()
    mid = _sketch_cip_labels(w)
    assert mid, "stereo must survive adding explicit hydrogens"

    ok, err = w.remove_explicit_hydrogens_from_sketch()
    assert ok, err
    assert not w.sketch_has_explicit_hydrogens()
    after = _sketch_cip_labels(w)
    assert after, "stereo must survive removing explicit hydrogens"
    assert set(after.values()) == set(before.values())
    assert any(_bond_unpack(b)[3] in (BOND_STEREO_WEDGE, BOND_STEREO_HASH) for b in w.bonds)


def test_explicit_hydrogens_use_iupac_bond_angles(qapp) -> None:  # noqa: ARG001
    """Terminal methyl H should sit near tetrahedral (~109.5°) gaps, not stacked."""
    w = SketchWidget()
    # C–C horizontal; add H on the right carbon.
    c0, c1 = 0, 1
    w.nodes = [
        {"id": c0, "pos": QPoint(100, 100), "element": "C"},
        {"id": c1, "pos": QPoint(160, 100), "element": "C"},
    ]
    w.bonds = [_bond_make(c0, c1, 1, 0)]
    w.next_id = 2
    ok, err = w.add_explicit_hydrogens_on_atom(c1)
    assert ok, err
    h_nodes = [n for n in w.nodes if n.get("element") == "H"]
    assert len(h_nodes) == 3
    parent = next(n for n in w.nodes if n["id"] == c1)
    px, py = float(parent["pos"].x()), float(parent["pos"].y())
    angles = sorted(math.atan2(float(n["pos"].y()) - py, float(n["pos"].x()) - px) for n in h_nodes)
    # Include the existing C–C neighbor angle when measuring gaps among all four ligands.
    all_ang = sorted(
        angles
        + [
            math.atan2(
                float(next(n for n in w.nodes if n["id"] == c0)["pos"].y()) - py,
                float(next(n for n in w.nodes if n["id"] == c0)["pos"].x()) - px,
            )
        ]
    )
    gaps = []
    for i in range(len(all_ang)):
        a1 = all_ang[i]
        a2 = all_ang[(i + 1) % len(all_ang)] if i + 1 < len(all_ang) else all_ang[0] + 2 * math.pi
        gaps.append(a2 - a1 if a2 >= a1 else a2 + 2 * math.pi - a1)
    # Tetrahedral / equal-fan gaps for CH3 with one heavy neighbor (~90° with 4 ligands).
    assert all(math.degrees(g) > 60.0 for g in gaps), gaps
    assert max(math.degrees(g) for g in gaps) < 150.0, gaps
    # Hydrogens must not stack on top of each other.
    for i, a in enumerate(h_nodes):
        for b in h_nodes[i + 1 :]:
            dist = math.hypot(
                float(a["pos"].x()) - float(b["pos"].x()),
                float(a["pos"].y()) - float(b["pos"].y()),
            )
            assert dist > 20.0, dist


def test_add_explicit_hydrogens_skips_condensed_oh_nh(qapp) -> None:  # noqa: ARG001
    """OH/NH condensed groups must not be expanded when adding implicit→explicit H."""
    w = SketchWidget()
    w.resize(600, 400)
    # C–O (alcohol) and C–N (amine)
    c, o, n = 0, 1, 2
    w.nodes = [
        {"id": c, "pos": QPoint(120, 120), "element": "C"},
        {"id": o, "pos": QPoint(180, 120), "element": "O"},
        {"id": n, "pos": QPoint(120, 60), "element": "N"},
    ]
    w.bonds = [_bond_make(c, o, 1, 0), _bond_make(c, n, 1, 0)]
    w.next_id = 3
    assert w._node_condensed_label(w.nodes[1]) == "OH"
    assert w._node_condensed_label(w.nodes[2]) in ("NH2", "NH")

    ok, err = w.add_explicit_hydrogens_on_atom(o)
    assert not ok
    assert "already" in err.lower() or "OH" in err or "NH" in err

    ok, err = w.add_explicit_hydrogens_from_implicit()
    assert ok, err
    # Explicit H only on carbon — not on O or N.
    o_has_h = w.atom_has_explicit_hydrogen_neighbors(o)
    n_has_h = w.atom_has_explicit_hydrogen_neighbors(n)
    c_has_h = w.atom_has_explicit_hydrogen_neighbors(c)
    assert not o_has_h
    assert not n_has_h
    assert c_has_h
    # Condensed labels should still resolve for O/N after the edit.
    o_node = next(x for x in w.nodes if x["id"] == o)
    n_node = next(x for x in w.nodes if x["id"] == n)
    assert w._node_condensed_label(o_node) == "OH"
    assert w._node_condensed_label(n_node) in ("NH2", "NH")


def test_load_preserves_aromatic_kekule_doubles_with_stereo_h(qapp) -> None:  # noqa: ARG001
    """Sanitize after stereo-H must not leave aromatic rings as all singles."""
    from molmanager.ui.sketcher.bonds import _bond_unpack

    mol = Chem.MolFromSmiles("C[C@H](O)c1ccccc1")
    w = SketchWidget()
    w.resize(600, 400)
    assert w.load_from_rdkit_mol(mol)
    orders = [_bond_unpack(b)[2] for b in w.bonds]
    assert orders.count(2) >= 3, f"expected Kekulé doubles in phenyl, got {orders}"


def test_to_smiles_selected_exports_subset(qapp) -> None:  # noqa: ARG001
    """Selection SMILES uses only selected atoms (and bonds between them)."""
    w = SketchWidget()
    ids = []
    for i, el in enumerate(("C", "C", "O")):
        nid = w.next_id
        w.next_id += 1
        w.nodes.append({"id": nid, "pos": QPoint(i * 40, 0), "element": el})
        ids.append(nid)
    w.bonds.append(_bond_make(ids[0], ids[1], 1, 0))
    w.bonds.append(_bond_make(ids[1], ids[2], 1, 0))
    assert w.to_smiles_selected() == ""
    w.selected_nodes = [ids[1], ids[2]]
    sel = w.to_smiles_selected()
    assert sel
    m = Chem.MolFromSmiles(sel)
    assert m is not None
    assert m.GetNumAtoms() == 2
    assert {a.GetSymbol() for a in m.GetAtoms()} == {"C", "O"}


def test_to_smiles_selected_ignores_unselected_bond_endpoints(qapp) -> None:  # noqa: ARG001
    """Selected bonds must not pull unselected endpoint atoms into the export."""
    w = SketchWidget()
    ids = []
    for i, el in enumerate(("C", "C", "O", "N")):
        nid = w.next_id
        w.next_id += 1
        w.nodes.append({"id": nid, "pos": QPoint(i * 40, 0), "element": el})
        ids.append(nid)
    w.bonds.append(_bond_make(ids[0], ids[1], 1, 0))
    w.bonds.append(_bond_make(ids[1], ids[2], 1, 0))
    w.bonds.append(_bond_make(ids[2], ids[3], 1, 0))
    # Marquee-style: middle bond selected, but only the oxygen atom is selected.
    w.selected_nodes = [ids[2]]
    w.selected_bond_indices = {1}  # C–O bond (ids[1]–ids[2])
    sel = w.to_smiles_selected()
    assert sel
    m = Chem.MolFromSmiles(sel) or Chem.MolFromSmarts(sel)
    assert m is not None
    assert m.GetNumAtoms() == 1
    assert m.GetAtomWithIdx(0).GetSymbol() == "O"
    # Bond-only selection (no atoms) exports nothing.
    w.selected_nodes = []
    w.selected_bond_indices = {0, 1, 2}
    assert w.to_smiles_selected() == ""


def test_rgroup_click_exports_numbered_dummy(qapp):  # noqa: ARG001
    from molmanager.chem.rgroup_enumeration import prepare_core

    w = SketchWidget()
    nid = w.next_id
    w.next_id += 1
    w.nodes.append({"id": nid, "pos": QPoint(0, 0), "element": "C"})
    w.place_rgroup_on(nid, "R1")
    smi = w.to_smiles()
    assert smi
    assert "[*:1]" in smi
    _core, labels = prepare_core(smi)
    assert labels == (1,)
    r_nodes = [n for n in w.nodes if n.get("element") == "R1"]
    assert len(r_nodes) == 1
    w.place_rgroup_on(r_nodes[0]["id"], "R2")
    assert r_nodes[0]["element"] == "R2"
    assert "[*:2]" in (w.to_smiles() or "")


def test_rgroup_smiles_reloads_as_r_labels(qapp):  # noqa: ARG001
    w = SketchWidget()
    mol = Chem.MolFromSmiles("[*:1]c1ccc([*:2])cc1")
    assert mol is not None
    assert w.load_from_rdkit_mol(mol)
    labels = sorted(n["element"] for n in w.nodes if str(n.get("element", "")).startswith("R"))
    assert labels == ["R1", "R2"]
    exported = w.to_smiles() or ""
    assert "[*:1]" in exported and "[*:2]" in exported
