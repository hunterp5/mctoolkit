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

from __future__ import annotations

import math
from pathlib import Path

import pytest
from rdkit import Chem
from rdkit.Chem import AllChem, rdDepictor
from rdkit.Chem.Draw import rdMolDraw2D
from rdkit.Geometry import Point3D

from molmanager.chem import depiction_layout as layout
from molmanager.chem.depiction_builder import build_scene, scene_revision
from molmanager.chem.depiction_layout import LayoutOptions, layout_for_drawing

ROOT = Path(__file__).resolve().parent.parent
RAPAMYCIN = (
    "CO[C@@H]1C[C@@H](CC[C@H]1O)C[C@@H](C)[C@@H]1CC(=O)[C@H](C)/C=C(C)/[C@@H](O)"
    "[C@@H](OC)C(=O)[C@H](C)C[C@H](C)/C=C/C=C/C=C(C)/[C@H](C[C@@H]2CC[C@@H](C)"
    "[C@@](O)(O2)C(=O)C(=O)N2CCCC[C@H]2C(=O)O1)OC"
)
PLAIN = LayoutOptions(
    macrocycle_coordgen=False, flip_inward_substituents=False, rotate_to_cell=False
)


def _positions(mol) -> list[tuple[float, float]]:
    conformer = mol.GetConformer()
    return [
        (conformer.GetAtomPosition(i).x, conformer.GetAtomPosition(i).y)
        for i in range(mol.GetNumAtoms())
    ]


def _inward_substituents(mol) -> int:
    positions = _positions(mol)
    count = 0
    for ring in mol.GetRingInfo().AtomRings():
        if len(ring) < layout.MACROCYCLE_RING_SIZE:
            continue
        polygon = [positions[i] for i in ring]
        for index in ring:
            for neighbour in mol.GetAtomWithIdx(index).GetNeighbors():
                other = neighbour.GetIdx()
                count += other not in ring and layout._inside(positions[other], polygon)
    return count


def _drawn_smiles(prepared) -> str:
    """SMILES read back from a prepared drawing: wedges for centres, coordinates for E/Z."""
    copy = Chem.Mol(prepared)
    for atom in copy.GetAtoms():
        atom.SetChiralTag(Chem.ChiralType.CHI_UNSPECIFIED)
    for bond in copy.GetBonds():
        if bond.GetBondType() == Chem.BondType.DOUBLE:
            bond.SetStereo(Chem.BondStereo.STEREONONE)
    conf_id = copy.GetConformer().GetId()
    Chem.AssignChiralTypesFromBondDirs(copy, conf_id)
    Chem.DetectBondStereochemistry(copy, conf_id)
    Chem.AssignStereochemistry(copy, cleanIt=True, force=True)
    return Chem.MolToSmiles(Chem.RemoveHs(copy))


def test_flat_coordinates_are_kept():
    mol = Chem.MolFromSmiles("c1ccccc1CC")
    rdDepictor.Compute2DCoords(mol)
    assert layout_for_drawing(mol, LayoutOptions()) is mol


def test_3d_coordinates_get_a_flat_layout():
    mol = Chem.AddHs(Chem.MolFromSmiles("CC(=O)Oc1ccccc1C(=O)O"))
    AllChem.EmbedMolecule(mol, randomSeed=7)
    mol = Chem.RemoveHs(mol)
    drawn = layout_for_drawing(mol, LayoutOptions())
    assert layout.has_drawing_coordinates(drawn)
    assert drawn.GetNumAtoms() == mol.GetNumAtoms()


def test_layout_ignores_the_process_wide_coordgen_switch():
    mol = Chem.MolFromSmiles("CC(C)Cc1ccc(cc1)[C@@H](C)C(=O)O")
    try:
        rdDepictor.SetPreferCoordGen(True)
        with_switch = _positions(layout_for_drawing(mol, LayoutOptions()))
    finally:
        rdDepictor.SetPreferCoordGen(False)
    assert _positions(layout_for_drawing(mol, LayoutOptions())) == pytest.approx(with_switch)


def test_macrocycle_uses_coordgen_with_substituents_outside():
    mol = Chem.MolFromSmiles(RAPAMYCIN)
    plain = layout_for_drawing(mol, PLAIN)
    coordgen = layout_for_drawing(mol, LayoutOptions(rotate_to_cell=False))
    assert _positions(coordgen) != pytest.approx(_positions(plain))
    unflipped = layout._coordgen_layout(layout._with_stereo_hydrogens(mol))
    assert _inward_substituents(coordgen) < _inward_substituents(unflipped)
    assert _drawn_smiles(rdMolDraw2D.PrepareMolForDrawing(coordgen)) == Chem.MolToSmiles(mol)


def test_coordgen_is_dropped_when_it_draws_the_wrong_double_bond_shape(monkeypatch):
    mol = Chem.MolFromSmiles("C1CCCC/C=C/CCCCCC1")
    wrong = Chem.MolFromSmiles("C1CCCC/C=C\\CCCCCC1")
    monkeypatch.setattr(layout, "_coordgen_layout", lambda _base: layout._rdkit_layout(wrong))
    drawn = layout_for_drawing(mol, LayoutOptions(flip_inward_substituents=False))
    assert _drawn_smiles(rdMolDraw2D.PrepareMolForDrawing(drawn)) == Chem.MolToSmiles(mol)


def test_stereocentre_hydrogens_match_rdkits_drawer():
    mol = Chem.MolFromSmiles("CC[C@H]1CN2CC[C@H]1C[C@@H]2[C@@H](O)c1ccnc2ccc(OC)cc12")
    drawn = rdMolDraw2D.PrepareMolForDrawing(layout_for_drawing(mol, LayoutOptions()))
    assert drawn.GetNumAtoms() == rdMolDraw2D.PrepareMolForDrawing(mol).GetNumAtoms()
    assert _drawn_smiles(drawn) == Chem.MolToSmiles(mol)


def test_tall_layout_is_turned_to_fit_the_cell():
    mol = Chem.MolFromSmiles("CCCCCCCCCC")
    rdDepictor.Compute2DCoords(mol)
    conformer = mol.GetConformer()
    for index in range(mol.GetNumAtoms()):
        conformer.SetAtomPosition(index, Point3D(0.6 * (index % 2), 1.3 * index, 0.0))
    before = layout._cell_fit(_positions(mol), 0.0, 1.5)
    layout._rotate_to_cell(mol)
    after = layout._cell_fit(_positions(mol), 0.0, 1.5)
    assert after >= before * layout.MIN_ROTATION_GAIN
    lengths = [
        math.dist(*(_positions(mol)[i] for i in (b.GetBeginAtomIdx(), b.GetEndAtomIdx())))
        for b in mol.GetBonds()
    ]
    assert min(lengths) == pytest.approx(max(lengths), rel=0.2)


def test_rotation_aims_at_the_default_cell():
    from molmanager.table.structure_depiction_layout import (
        DEFAULT_STRUCTURE_DEPICT_HEIGHT,
        DEFAULT_STRUCTURE_DEPICT_WIDTH,
    )

    assert layout.CELL_ASPECT == pytest.approx(
        DEFAULT_STRUCTURE_DEPICT_WIDTH / DEFAULT_STRUCTURE_DEPICT_HEIGHT
    )


def test_generated_layouts_keep_the_drawn_stereo():
    mismatches_before = mismatches_after = 0
    for index, mol in enumerate(Chem.SDMolSupplier(str(ROOT / "samples" / "fda_approved.sdf"))):
        if index >= 600:
            break
        if mol is None:
            continue
        base = Chem.Mol(mol)
        base.RemoveAllConformers()
        expected = Chem.MolToSmiles(base)
        old = _drawn_smiles(rdMolDraw2D.PrepareMolForDrawing(base))
        new = _drawn_smiles(
            rdMolDraw2D.PrepareMolForDrawing(layout_for_drawing(base, LayoutOptions()))
        )
        mismatches_before += old != expected
        mismatches_after += new != expected
        assert new == expected or old != expected, index
    assert mismatches_after <= mismatches_before


def test_scene_atoms_keep_their_indices():
    mol = Chem.MolFromSmiles(RAPAMYCIN)
    scene, reason = build_scene(mol, LayoutOptions())
    assert scene is not None, reason
    assert len(scene.atoms) >= mol.GetNumAtoms()


def test_scene_revision_follows_the_layout_options():
    revisions = {
        scene_revision(LayoutOptions()),
        scene_revision(PLAIN),
        scene_revision(LayoutOptions(rotate_to_cell=False)),
    }
    assert len(revisions) == 3
