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

"""Tests for Chemistry → Substructure → Align to Substructure."""

from __future__ import annotations

import math

from rdkit import Chem
from rdkit.Chem import AllChem

from molmanager.chem.depiction_coords import (
    DepictionCoordStore,
    apply_depiction_coords,
    pack_xy,
    unpack_xy,
)
from molmanager.chem.substructure_align import (
    align_mol_to_template,
    align_structure_rows,
    conformer_xy,
    partition_alignment_scope,
    query_mol_from_text,
    set_conformer_xy,
)


def _rotated_query(text: str, angle: float):
    query, err = query_mol_from_text(text)
    assert query is not None, err
    xs, ys = conformer_xy(query)
    cos_a, sin_a = math.cos(angle), math.sin(angle)
    rx = [x * cos_a - y * sin_a for x, y in zip(xs, ys)]
    ry = [x * sin_a + y * cos_a for x, y in zip(xs, ys)]
    return set_conformer_xy(query, rx, ry)


def _matched_points(smiles: str, template) -> list[tuple[float, float]]:
    mol = Chem.MolFromSmiles(smiles)
    blob = align_mol_to_template(mol, template)
    assert blob is not None
    points = unpack_xy(blob)
    assert points is not None and len(points) == mol.GetNumAtoms()
    match = mol.GetSubstructMatch(template)
    return [points[i] for i in match]


def _shape_rms(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> float:
    """RMS after removing translation and uniform scale (rotation is kept)."""

    def _norm(pts):
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        centered = [(x - cx, y - cy) for x, y in pts]
        scale = math.sqrt(sum(x * x + y * y for x, y in centered) / len(pts)) or 1.0
        return [(x / scale, y / scale) for x, y in centered]

    na, nb = _norm(a), _norm(b)
    return math.sqrt(
        sum((xa - xb) ** 2 + (ya - yb) ** 2 for (xa, ya), (xb, yb) in zip(na, nb)) / len(na)
    )


def test_matching_rows_share_the_template_orientation() -> None:
    template = _rotated_query("c1ccc2ncccc2c1", math.radians(37))
    template_pts = list(zip(*conformer_xy(template)))
    for smiles in ("Cc1ccc2ncccc2c1", "OCCc1ccnc2ccccc12"):
        matched = _matched_points(smiles, template)
        assert _shape_rms(matched, template_pts) < 0.15


def test_non_match_returns_none() -> None:
    template, _err = query_mol_from_text("c1ccc2ncccc2c1")
    assert align_mol_to_template(Chem.MolFromSmiles("CCCCO"), template) is None
    rows = [(1, Chem.MolFromSmiles("CCCCO")), (2, Chem.MolFromSmiles("c1ccc2ncccc2c1"))]
    aligned, skipped, cancelled = align_structure_rows(rows, template)
    assert [oid for oid, _blob in aligned] == [2]
    assert skipped == 1
    assert cancelled is False


def test_smarts_query_pins_more_than_one_element() -> None:
    template = _rotated_query("c1ccc([#7,#8])cc1", math.radians(90))
    template_pts = list(zip(*conformer_xy(template)))
    for smiles in ("Nc1ccccc1", "Oc1ccccc1"):
        matched = _matched_points(smiles, template)
        assert _shape_rms(matched, template_pts) < 0.15


def test_skip_existing_leaves_first_hit_in_place() -> None:
    keep, skipped = partition_alignment_scope([1, 2, 3], {2}, skip_existing=True)
    assert keep == [1, 3]
    assert skipped == 1
    keep, skipped = partition_alignment_scope([1, 2, 3], {2}, skip_existing=False)
    assert keep == [1, 2, 3]
    assert skipped == 0

    store = DepictionCoordStore()
    first, _ = query_mol_from_text("c1ccccc1")
    second, _ = query_mol_from_text("C1CCNCC1")
    rows = {1: Chem.MolFromSmiles("c1ccccc1C1CCNCC1"), 2: Chem.MolFromSmiles("C1CCNCC1CC")}
    aligned, _skipped, _ = align_structure_rows(list(rows.items()), first)
    store.set_many("Structure", aligned)
    before = store.get("Structure", 1)
    keep, _ = partition_alignment_scope(
        list(rows), set(store.column_items("Structure")), skip_existing=True
    )
    aligned, _skipped, _ = align_structure_rows([(oid, rows[oid]) for oid in keep], second)
    store.set_many("Structure", aligned)
    assert store.get("Structure", 1) == before
    assert store.get("Structure", 2) is not None


def test_stale_coordinates_are_ignored() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert apply_depiction_coords(mol, pack_xy([(0.0, 0.0), (1.0, 0.0)])) is mol
    assert apply_depiction_coords(mol, b"\x00\x01\x02") is mol
    applied = apply_depiction_coords(mol, pack_xy([(0.0, 0.0), (1.0, 0.0), (2.0, 1.0)]))
    assert applied is not mol
    assert applied.GetNumConformers() == 1
    assert applied.GetConformer().GetAtomPosition(2).x == 2.0


def test_molfile_query_keeps_its_coordinates() -> None:
    mol = Chem.MolFromSmiles("c1ccccc1O")
    AllChem.Compute2DCoords(mol)
    xs, ys = conformer_xy(mol)
    turned = set_conformer_xy(mol, [-y for y in ys], list(xs))
    query, err = query_mol_from_text(Chem.MolToMolBlock(turned))
    assert query is not None, err
    qx, qy = conformer_xy(query)
    for i in range(turned.GetNumAtoms()):
        assert math.isclose(qx[i], -ys[i], abs_tol=1e-3)
        assert math.isclose(qy[i], xs[i], abs_tol=1e-3)


def test_query_rejects_fragments_and_single_atoms() -> None:
    assert query_mol_from_text("C")[0] is None
    assert query_mol_from_text("CC.CC")[0] is None
    assert query_mol_from_text("")[0] is None


def test_session_round_trip() -> None:
    store = DepictionCoordStore()
    assert store.to_session() is None
    blob = pack_xy([(0.0, 0.0), (1.5, -0.5)])
    store.set("Structure", 7, blob)
    store.set("Core", 8, blob)
    payload = store.to_session({7})
    assert payload is not None and len(payload["rows"]) == 1
    restored = DepictionCoordStore()
    restored.load_session(store.to_session())
    assert restored.get("Structure", 7) == blob
    assert restored.get("Core", 8) == blob
    restored.discard_oids([7])
    assert restored.get("Structure", 7) is None


def test_window_aligns_and_writes_back(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    assert callable(getattr(w, "run_align_substructure", None))
    store = w._depiction_coords
    blob = pack_xy([(0.0, 0.0), (1.0, 0.0), (2.0, 0.0)])
    w.on_substructure_aligned(
        {"column": "Structure", "aligned": [(3, blob)], "considered": 2, "skipped_existing": 1}
    )
    assert store.get("Structure", 3) == blob
    assert w.status_label.text().endswith("Aligned 1, skipped 2.")
    w._write_tool_structures("Structure", [(3, Chem.MolFromSmiles("CCO").ToBinary(), "CCO")])
    assert store.get("Structure", 3) is None
    w.close()
