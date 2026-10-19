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

"""Protein Viewer inventory parsing and Manager actions (no Qt WebEngine required)."""

from __future__ import annotations

from pathlib import Path

from molmanager.protein.structure_components import (
    add_cif_chem_bond,
    add_pdb_conect,
    cif_has_component_bonds,
    cif_viewer_bond_tables,
    component_id_for_atom,
    delete_cif_atoms,
    delete_pdb_atoms,
    delete_pdb_residues,
    diff_sequence_edit,
    letter_to_resn,
    load_structure_file,
    parse_cif_chem_comp_bonds,
    parse_polymer_sequences,
    parse_structure_components,
    pdb_conect_partners,
    pdb_serial_for_atom,
    pocket_view_plan,
    polymer_sequence_entries,
    remove_cif_chem_bond,
    remove_pdb_conect,
    rewrite_pdb_residue_names,
    scope_structure_component,
    sniff_structure_format,
)
from molmanager.ui.protein_viewer import build_protein_viewer_html

_MINI_PDB = """\
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00           N
ATOM      2  CA  MET A   1      26.010  13.311  -8.124  1.00  0.00           C
ATOM      3  N   LEU B   2      10.000  11.000  12.000  1.00  0.00           N
HETATM  100  O81 AXI A2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  101  C80 AXI A2000     -26.813  -2.112  -9.925  1.00 30.83           C
HETATM  200  MG   MG A2001     -10.000   0.000   0.000  1.00 20.00          MG
HETATM  201  O   HOH A2002     -11.000   1.000   0.000  1.00 30.00           O
HETATM  202  O   HOH B2003     -12.000   1.000   0.000  1.00 30.00           O
END
"""

_MINI_CIF = """\
data_test
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_seq_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_model_num
ATOM 1 N N GLY A 1 1 GLY A 1.000 2.000 3.000 1
ATOM 2 C CA GLY A 1 1 GLY A 2.000 2.000 3.000 1
HETATM 3 S S24 AXI A . 2000 AXI A -26.050 -1.540 -9.129 1
HETATM 4 MG MG MG A . 2001 MG A -10.000 0.000 0.000 1
HETATM 5 O O HOH A . 2002 HOH A -11.000 1.000 0.000 1
"""

_MINI_CIF_BONDS = """\
data_lig
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_comp_id
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.pdbx_PDB_model_num
HETATM 1 C C80 LIG 1 LIG A 0.000 0.000 0.000 1
HETATM 2 O O81 LIG 1 LIG A 1.210 0.000 0.000 1
loop_
_chem_comp_atom.comp_id
_chem_comp_atom.atom_id
_chem_comp_atom.type_symbol
LIG C80 C
LIG O81 O
loop_
_chem_comp_bond.comp_id
_chem_comp_bond.atom_id_1
_chem_comp_bond.atom_id_2
_chem_comp_bond.value_order
_chem_comp_bond.pdbx_aromatic_flag
LIG C80 O81 doub N
"""

_POCKET_PDB = """\
ATOM      1  N   SER A  10       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  SER A  10       1.450   0.000   0.000  1.00  0.00           C
ATOM      3  CB  SER A  10       2.000   1.400   0.000  1.00  0.00           C
ATOM      4  OG  SER A  10       3.350   1.400   0.000  1.00  0.00           O
ATOM      5  N   ALA A  50      40.000  40.000  40.000  1.00  0.00           N
ATOM      6  CA  ALA A  50      41.500  40.000  40.000  1.00  0.00           C
HETATM  100  C1  LIG A  99       4.200   1.400   0.200  1.00  0.00           C
HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O
END
"""

_POCKET_H_PDB = """\
ATOM      1  N   SER A  10       0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  SER A  10       1.450   0.000   0.000  1.00  0.00           C
ATOM      3  CB  SER A  10       2.000   1.400   0.000  1.00  0.00           C
ATOM      4  OG  SER A  10       3.350   1.400   0.000  1.00  0.00           O
ATOM      5  HG  SER A  10       3.900   2.100   0.000  1.00  0.00           H
ATOM      6  HA  SER A  10       1.700  -0.500   0.900  1.00  0.00           H
ATOM      7  N   ALA A  50      40.000  40.000  40.000  1.00  0.00           N
ATOM      8  CA  ALA A  50      41.500  40.000  40.000  1.00  0.00           C
HETATM  100  C1  LIG A  99       4.200   1.400   0.200  1.00  0.00           C
HETATM  101  O1  LIG A  99       5.400   1.400   0.200  1.00  0.00           O
HETATM  102  HO1 LIG A  99       5.900   2.100   0.200  1.00  0.00           H
HETATM  103  H1  LIG A  99       4.000   0.500   0.700  1.00  0.00           H
HETATM  104  P1  LIG A  99       6.800   1.400   0.200  1.00  0.00           P
HETATM  105  HP1 LIG A  99       7.400   2.200   0.200  1.00  0.00           H
END
"""


def test_parse_pdb_splits_chains_ligand_metal_water():
    comps = parse_structure_components(_MINI_PDB, "pdb")
    kinds = {c.kind for c in comps}
    assert kinds == {"polymer", "ligand", "metal", "water"}
    polymers = [c for c in comps if c.kind == "polymer"]
    assert [c.chain for c in polymers] == ["A", "B"]
    assert polymers[0].n_residues == 1
    assert polymers[0].default_style == "cartoon"
    sel = polymers[0].selection
    assert sel.get("chain") == "A" or any(
        isinstance(part, dict) and part.get("chain") == "A" for part in (sel.get("and") or [])
    )
    ligand = next(c for c in comps if c.kind == "ligand")
    assert ligand.resn == "AXI"
    assert ligand.resi == "2000"
    assert ligand.chain == "A"
    assert ligand.default_style == "ballstick"
    assert ligand.selection.get("hetflag") is True
    metal = next(c for c in comps if c.kind == "metal")
    assert metal.resn == "MG"
    waters = [c for c in comps if c.kind == "water"]
    assert [c.chain for c in waters] == ["A", "B"]
    assert [c.component_id for c in waters] == ["water:A", "water:B"]
    assert all(c.n_residues == 1 for c in waters)
    assert all(c.default_visible is False for c in waters)
    assert waters[0].selection.get("chain") == "A" or any(
        isinstance(part, dict) and part.get("chain") == "A"
        for part in (waters[0].selection.get("and") or [])
    )


def test_parse_mmcif_inventory():
    comps = parse_structure_components(_MINI_CIF, "cif")
    kinds = {c.kind for c in comps}
    assert "polymer" in kinds
    assert "ligand" in kinds
    assert "metal" in kinds
    assert "water" in kinds
    polymer = next(c for c in comps if c.kind == "polymer")
    assert polymer.chain == "A"
    scoped = scope_structure_component(polymer, structure_id="s0", model=1)
    assert scoped.component_id.startswith("s0:")
    assert scoped.selection.get("model") == 1
    ligand = next(c for c in comps if c.kind == "ligand")
    assert ligand.resn == "AXI"
    assert ligand.resi == "2000"
    assert ligand.selection.get("hetflag") is True
    water = next(c for c in comps if c.kind == "water")
    assert water.chain == "A"
    assert water.component_id == "water:A"


def test_mmcif_het_keeps_numeric_label_seq_id():
    from molmanager.protein.structure_components import (
        atoms_to_mmcif,
        parse_structure_atoms,
        pdb_to_mmcif,
    )

    cif = pdb_to_mmcif(_MINI_PDB, data_name="mini")
    assert "AXI A . 2000" not in cif
    assert "AXI A 2000 2000" in cif
    rebuilt = atoms_to_mmcif(parse_structure_atoms(cif, "cif"), data_name="mini")
    assert "AXI A . 2000" not in rebuilt
    assert "AXI A 2000 2000" in rebuilt


def test_parse_cif_chem_comp_double_bonds():
    bonds = parse_cif_chem_comp_bonds(_MINI_CIF_BONDS)
    assert "LIG" in bonds
    assert any(b.order == 2 and {b.atom_id_1, b.atom_id_2} == {"C80", "O81"} for b in bonds["LIG"])
    tables = cif_viewer_bond_tables(_MINI_CIF_BONDS)
    assert tables["LIG"][0][2] == 2
    assert cif_has_component_bonds(_MINI_CIF_BONDS, ["LIG"])
    assert not cif_has_component_bonds(_MINI_CIF, ["AXI"])


def test_parse_cif_loops_reuses_same_text():
    from molmanager.protein.structure_cif import _parse_cif_loops

    first = _parse_cif_loops(_MINI_CIF_BONDS)
    second = _parse_cif_loops(_MINI_CIF_BONDS)
    assert first is second


def test_mol_from_cif_component_sets_double_bond():
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import mol_from_cif_component

    mol = mol_from_cif_component(_MINI_CIF_BONDS, "LIG")
    assert mol is not None
    assert mol.GetNumAtoms() == 2
    assert any(bond.GetBondType() == Chem.BondType.DOUBLE for bond in mol.GetBonds())


def test_sniff_cif_and_pdbqt():
    assert sniff_structure_format("foo.cif", "data_4AGC\n") == "cif"
    assert sniff_structure_format("rec.pdbqt", "ROOT\nATOM      1  C   LIG A   1\n") == "pdbqt"
    assert sniff_structure_format("x.pdb", "HEADER    TEST\n") == "pdb"


def test_load_structure_file_roundtrip(tmp_path):
    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    loaded = load_structure_file(path)
    assert loaded.sniffed_format == "pdb"
    assert loaded.viewer_format == "pdb"
    assert len(loaded.components) >= 4
    assert loaded.path.name == "mini.pdb"


def test_load_rejects_binary(tmp_path):
    path = tmp_path / "blob.pdb"
    path.write_bytes(b"HEADER\x00\x00\xff")
    try:
        load_structure_file(path)
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "binary" in str(exc).lower()


def test_component_id_for_atom_prefers_ligand():
    comps = parse_structure_components(_MINI_PDB, "pdb")
    assert component_id_for_atom(comps, chain="A", resn="AXI", resi="2000") == next(
        c.component_id for c in comps if c.kind == "ligand"
    )
    assert component_id_for_atom(comps, chain="A", resn="MET", resi="1").startswith("polymer:A")
    assert component_id_for_atom(comps, chain="A", resn="HOH", resi="2002") == "water:A"
    assert component_id_for_atom(comps, chain="B", resn="HOH", resi="2003") == "water:B"
    assert component_id_for_atom(comps, chain="A", resn="MG", resi="2001").startswith("metal:")


def test_empty_non_pdb_gets_single_structure_row():
    comps = parse_structure_components("not a coordinate file", "pdb")
    assert len(comps) == 1
    assert comps[0].component_id == "structure"
    assert comps[0].selection == {}


def test_protein_viewer_help_topic():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("protein_viewer")
    assert "Topic unavailable" not in h
    assert "Protein Viewer" in h
    assert "Goal" in h
    assert "Manager" in h
    assert "Sequence" in h
    assert "Prepare" in h
    assert "Color" in h
    assert "Select" in h
    assert "Save to Session" in h
    assert "dock pane" in h.lower()
    assert "header arrows" in h.lower()
    assert "pose browser" in h.lower()


def test_parse_polymer_sequences_one_letter_codes():
    chains = parse_polymer_sequences(_MINI_PDB, "pdb")
    assert [c.chain for c in chains] == ["A", "B"]
    assert chains[0].sequence == "M+*~"
    assert chains[1].sequence == "L~"
    kinds_a = [res.kind for res in chains[0].residues]
    assert kinds_a == ["polymer", "ligand", "metal", "water"]
    cif_chains = parse_polymer_sequences(_MINI_CIF, "cif")
    assert cif_chains[0].sequence == "G+*~"


def test_parse_polymer_sequences_includes_seqres_gaps():
    pdb = """\
SEQRES   1 A    3  MET ALA LEU
REMARK 465     ALA A    15
ATOM      1  CA  MET A  10      0.000   0.000   0.000  1.00  0.00           C
ATOM      2  CA  LEU A  20      4.000   0.000   0.000  1.00  0.00           C
END
"""
    chains = parse_polymer_sequences(pdb, "pdb")
    assert len(chains) == 1
    assert [res.kind for res in chains[0].residues] == ["polymer", "missing", "polymer"]
    assert chains[0].sequence == "MaL"
    assert chains[0].residues[1].resn == "ALA"
    assert chains[0].residues[1].resi == "15"

    cif = """\
data_gap
loop_
_pdbx_poly_seq_scheme.asym_id
_pdbx_poly_seq_scheme.mon_id
_pdbx_poly_seq_scheme.pdb_seq_num
_pdbx_poly_seq_scheme.auth_seq_num
_pdbx_poly_seq_scheme.pdb_mon_id
_pdbx_poly_seq_scheme.pdb_strand_id
_pdbx_poly_seq_scheme.pdb_ins_code
_pdbx_poly_seq_scheme.hetero
A MET 10 ? ? A . n
A ALA 15 ? ? A . n
A LEU 20 20 LEU A . n
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_seq_id
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
ATOM 1 C CA LEU A 20 4.000 0.000 0.000
"""
    cif_chains = parse_polymer_sequences(cif, "cif")
    assert cif_chains[0].sequence == "maL"
    assert [res.kind for res in cif_chains[0].residues] == ["missing", "missing", "polymer"]
    entries = polymer_sequence_entries(cif, "cif")
    assert entries["A"][0] == ("MET", "10", "", False)


def test_4agc_sequence_includes_unobserved_nterminus():
    from pathlib import Path

    import pytest

    path = Path("samples/4AGC.cif")
    if not path.is_file():
        pytest.skip("samples/4AGC.cif is not present")
    chains = parse_polymer_sequences(path.read_text(encoding="utf-8"), "cif")
    polymer = next(c for c in chains if c.chain == "A")
    assert polymer.sequence.startswith("mgghhhhh")
    assert any(res.kind == "missing" and res.resi == "769" for res in polymer.residues)
    assert any(
        res.kind == "polymer" and res.resn == "TYR" and res.resi == "801"
        for res in polymer.residues
    )


def test_diff_sequence_edit_mutate_and_delete():
    edit = diff_sequence_edit("MAL", "MSL")
    assert edit.mutations == ((1, "S"),)
    assert edit.deletions == ()
    assert not edit.rejected_insert
    deleted = diff_sequence_edit("MAL", "ML")
    assert 1 in deleted.deletions
    assert not deleted.rejected_insert
    inserted = diff_sequence_edit("MAL", "MVAL")
    assert inserted.rejected_insert
    hetero = diff_sequence_edit("M+*~", "M+*")
    assert 3 in hetero.deletions
    assert not hetero.invalid_letter
    bad = diff_sequence_edit("MAL", "M1L")
    assert bad.invalid_letter
    assert letter_to_resn("S") == "SER"


def test_hetero_only_pdb_chains_stay_separate():
    pdb = """\
ATOM      1  N   MET A   1      27.340  24.430   2.614  1.00  0.00           N
HETATM  100  O81 AXI L2000     -26.050  -1.540  -9.129  1.00 32.47           O
HETATM  201  O   HOH W2002     -11.000   1.000   0.000  1.00 30.00           O
END
"""
    comps = parse_structure_components(pdb, "pdb")
    by_kind = {c.kind: c for c in comps}
    assert by_kind["polymer"].chain == "A"
    assert by_kind["ligand"].chain == "L"
    assert by_kind["ligand"].component_id.startswith("ligand:L:")
    assert by_kind["water"].chain == "W"
    assert by_kind["water"].component_id == "water:W"
    chains = parse_polymer_sequences(pdb, "pdb")
    assert [c.chain for c in chains] == ["A", "L", "W"]
    assert [c.sequence for c in chains] == ["M", "+", "~"]


def test_rewrite_and_delete_pdb_residues():
    renamed = rewrite_pdb_residue_names(_MINI_PDB, [("A", "1", "", "SER")])
    assert "SER A   1" in renamed or "SER A   1" in renamed.replace("  ", " ")
    assert "MET A   1" not in renamed
    removed = delete_pdb_residues(_MINI_PDB, {("A", "1", "")})
    assert "MET" not in removed
    assert "LEU" in removed


_CONECT_PDB = """\
HETATM  100  C80 LIG A   1       0.000   0.000   0.000  1.00  0.00           C
HETATM  101  O81 LIG A   1       1.210   0.000   0.000  1.00  0.00           O
HETATM  102  C82 LIG A   1       2.420   0.000   0.000  1.00  0.00           C
CONECT  100  101
CONECT  101  100  102
END
"""


def test_delete_pdb_atoms_strips_conect():
    dropped = delete_pdb_atoms(_CONECT_PDB, {("A", "1", "", "C80")})
    assert "C80" not in dropped
    assert "O81" in dropped
    assert "C82" in dropped
    partners = pdb_conect_partners(dropped)
    assert 100 not in partners
    assert partners.get(101) == (102,)
    assert pdb_serial_for_atom(_CONECT_PDB, ("A", "1", "", "O81")) == 101


def test_pdb_conect_add_and_remove():
    added = add_pdb_conect(_CONECT_PDB, 100, 102)
    partners = pdb_conect_partners(added)
    assert 102 in partners[100]
    assert 100 in partners[102]
    removed = remove_pdb_conect(added, 100, 101)
    partners = pdb_conect_partners(removed)
    assert 101 not in partners.get(100, ())
    assert 102 in partners[100]


def test_delete_cif_atoms_and_chem_bonds():
    dropped = delete_cif_atoms(_MINI_CIF_BONDS, {("A", "1", "", "C80")})
    assert "C80" not in dropped
    assert "O81" in dropped
    bonds = parse_cif_chem_comp_bonds(dropped)
    assert "LIG" not in bonds
    added = add_cif_chem_bond(_MINI_CIF_BONDS.replace("doub", "sing"), "LIG", "C80", "O81", order=2)
    tables = cif_viewer_bond_tables(added)
    assert any(row[:2] == ["C80", "O81"] and row[2] == 2 for row in tables["LIG"])
    cleared = remove_cif_chem_bond(added, "LIG", "O81", "C80")
    assert "LIG" not in parse_cif_chem_comp_bonds(cleared)


def test_protein_viewer_init_script_lives_in_js_file():
    from molmanager.ui import protein_viewer_html

    py_path = Path(protein_viewer_html.__file__)
    js_path = py_path.with_name("protein_viewer.js")
    py = py_path.read_text(encoding="utf-8")
    js = js_path.read_text(encoding="utf-8")
    assert "function molmanagerInitView" in js
    assert "molmanagerSetProteinPayload" in js
    assert "__RESET_JS__" in js
    assert "molmanagerSetProteinPayload" not in py
    html = build_protein_viewer_html()
    assert "molmanagerSetProteinPayload" in html
    assert "__RESET_JS__" not in html


def test_build_protein_viewer_html_has_setters():
    html = build_protein_viewer_html()
    assert "molmanagerSetProteinPayload" in html
    assert "molmanagerAddProteinModels" in html
    assert "addModelsFromPayload" in html
    assert "molmanagerModelCount" in html
    assert "payload.models" in html
    assert "payload.camera" in html
    assert "molmanagerGetView" in html
    assert "molmanagerSetView" in html
    assert "molmanagerApplyComponentStates" in html
    assert "molmanagerDeleteComponents" in html
    assert "molmanagerZoomToComponents" in html
    assert "molmanagerSetResidueHighlight" in html
    assert "molmanagerSetPocket" in html
    assert "molmanagerSetPocketSurface" in html
    assert "applyPocketSurface" in html
    assert "p.wireframe" in html
    assert "p.surfaceType" in html
    assert "paintPocketResidueColors" in html
    assert "paintPocketCharges" in html
    assert "partialCharge" in html
    assert "showAtoms" in html
    assert "showResidues" in html
    assert "applyInteractionResidues" in html
    assert "applyInteractionAtoms" in html
    assert "molmanagerSetHydrogens" in html
    assert "molmanagerSetHbonds" in html
    assert "applyHydrogenVisibility" in html
    assert "indexVisibleHeavyResidues" in html
    assert "atomHasAtomRepresentation" in html
    assert "normalizeHydrogensMode" in html
    assert "normalizeHydrogenElements" in html
    assert "attachHydrogensToHeavies" in html
    assert "showHydrogenParent" in html
    assert "keepH: true" in html
    assert html.count("function isHydrogenAtom") == 1
    assert "at.style.hidden = true" in html
    assert "at.hidden = true" in html
    assert 'mode === "none"' in html
    assert "visibleHeavies[residueResKey(at)]" in html
    assert "opacity <= 0.05" in html
    assert 'atomModelId(at) + "\\t" + (at.chain' in html
    assert "applyHydrogenBonds" in html
    assert "applyPocketOverlay" in html
    assert "addStyle(resSel, {stick: {radius: 0.15}})" in html
    assert "addPocketResidueLabels" not in html
    assert "addResLabels" not in html
    assert "molmanagerMutateResidues" in html
    assert "molmanagerDeleteResidues" in html
    assert "molmanagerEditBond" in html
    assert "ord >= 1" in html
    assert "Reset Structure" in html
    assert "__RESET_JS__" not in html
    assert "qwebchannel.js" in html
    assert "cartoon" in html
    assert "applyCifBondOrders" in html
    assert "md.cifBonds" in html
    assert "atomIsHydrogen" in html
    assert "carbonScheme" in html
    assert "carbonSpec" in html
    assert "v.setStyle({}, {})" in html
    assert "hetflag: true" in html
    assert "indexResidueHeavies" in html
    assert "at.style[k].hidden = true" in html
    assert "atomLooksHidden" in html
    assert "v.setClickable({}, true" in html
    assert "doubleClick" in html
    assert "ligandComponentId" in html
    assert "applyClickTargets" in html
    assert "clicksphere" in html
    assert 'elem: "H"' in html
    assert "hydrogenHideSpec" in html
    assert "opacity: 0.01" not in html
    assert "bindViewerKeys" in html
    assert "deleteRequested" in html
    assert "undoRequested" in html
    assert 'sphere: {scale: 0.34, color: "orange"}' in html
    assert 'cross: {radius: 0.7, color: "orange"}' in html
    assert 'sphere: {scale: 0.42, color: "orange"}' not in html
    assert 'v.setClickable({elem: ["H", "D", "T"], invert: true}' not in html
    assert "v.addStyle({model: atomModelId(at), serial: at.serial}, {hidden: true})" not in html
    assert "molmanagerSetDockPose" in html
    assert "molmanagerSetPharmacophore" in html
    assert "applyPharmacophore" in html
    assert "alpha: 0.58" in html
    assert "wireframe: true" in html
    assert "linewidth: 2" in html
    assert "payload.pharmacophore" in html


def test_protein_viewer_has_prepare_log(qapp):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    assert dlg.log.isReadOnly()
    dlg.append_log("")
    assert dlg.log.toPlainText() == ""
    dlg.append_log("hello")
    text = dlg.log.toPlainText()
    assert "hello" in text
    assert "[" in text
    dlg.close()


def test_protein_viewer_manager_reaches_window_bottom(qapp):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    dlg.resize(1100, 720)
    dlg.show()
    qapp.processEvents()
    ready = dlg._workspace_ready_page
    manager = dlg.manager
    log = dlg.log
    ready_h = int(ready.height())
    mgr_bottom = int(manager.mapTo(ready, manager.rect().bottomLeft()).y())
    assert mgr_bottom >= ready_h - 2
    log_right = int(log.mapTo(ready, log.rect().topRight()).x())
    mgr_left = int(manager.mapTo(ready, manager.rect().topLeft()).x())
    assert log_right <= mgr_left + 2
    assert int(log.height()) <= max(64, int(dlg.viewer.height()) // 6)
    dlg.close()


def test_protein_viewer_canvas_load_overlay_nests(qapp):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    assert dlg.canvas_loading_visible() is False
    dlg.begin_canvas_load("Loading structures…", paint=False)
    assert dlg.canvas_loading_visible() is True
    assert "Loading structures" in dlg._loading_detail.text()
    dlg.begin_canvas_load("Loading structure…", paint=False)
    assert dlg.canvas_loading_visible() is True
    dlg.end_canvas_load()
    assert dlg.canvas_loading_visible() is True
    dlg.end_canvas_load()
    assert dlg.canvas_loading_visible() is False
    dlg.close()


def test_open_protein_viewer_shows_before_session_restore(qapp, tmp_path, monkeypatch):
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_embed import ProteinEmbedView
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    seed = w.open_protein_viewer()
    seed.add_structure_path(src, refit=True)
    assert seed.save_viewer_to_session() is True
    payload = w._collect_protein_viewer()
    seed._suppress_close_prompt = True
    seed.close()
    w._protein_viewer_dialog = None
    w._protein_viewer_session = payload

    seen: list[tuple[bool, bool]] = []
    orig = ProteinViewerDialog.apply_session_state

    def wrapped(self, state):
        seen.append((self.isVisible(), self.canvas_loading_visible()))
        return orig(self, state)

    monkeypatch.setattr(ProteinViewerDialog, "apply_session_state", wrapped)
    dlg = w.open_protein_viewer()
    assert seen == [(True, True)]
    assert dlg.canvas_loading_visible() is False
    assert [slot.name for slot in dlg._slots] == ["mini.pdb"]
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()


def test_open_protein_viewer_empty_releases_start_overlay(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow
    from molmanager.ui.protein_embed import ProteinEmbedView

    monkeypatch.setattr(ProteinEmbedView, "_ensure_web", lambda self: None)
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    assert dlg is not None
    assert dlg.isVisible() is True
    assert dlg._canvas_bootstrapped is True
    assert dlg.canvas_loading_visible() is False
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()


def test_atom_pick_selects_individual_atom(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,"model":0}'
    )
    hl = dlg._residue_highlight
    assert len(hl) == 1
    assert hl[0]["atom"] == "CA"
    assert hl[0]["serial"] == 2
    assert hl[0]["chain"] == "A"
    assert hl[0]["resi"] == 1
    assert "CA" in dlg._atom_status.text()
    polymer = next(r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A")
    assert polymer.selected
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","atom":"H","elem":"H","serial":9,"model":0}'
    )
    assert dlg._residue_highlight[0]["atom"] == "H"
    assert dlg._residue_highlight[0]["serial"] == 9
    assert "H" in dlg._atom_status.text()
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,'
        '"doubleClick":true,"model":0}'
    )
    res_hl = dlg._residue_highlight[0]
    assert res_hl.get("atom") in (None, "")
    assert "serial" not in res_hl
    assert res_hl["chain"] == "A"
    assert res_hl["resi"] == 1
    assert "CA" not in dlg._atom_status.text()
    assert "MET" in dlg._atom_status.text()
    polymer = next(r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A")
    assert polymer.selected
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,'
        '"doubleClick":true,"model":0}'
    )
    lig_hl = dlg._residue_highlight[0]
    assert lig_hl.get("atom") in (None, "")
    assert "serial" not in lig_hl
    ligand = next(r for r in dlg._rows if r.spec.kind == "ligand")
    assert ligand.selected
    assert not next(
        r for r in dlg._rows if r.spec.kind == "polymer" and r.spec.chain == "A"
    ).selected
    dlg.clear_selection()
    assert dlg._residue_highlight == []
    assert dlg._atom_status.text() == ""
    assert not any(r.selected for r in dlg._rows)
    dlg.close()


def test_edit_structure_two_atom_pick_and_atom_delete(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMenuBar, QMessageBox

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    mb = dlg.findChild(QMenuBar)
    edit_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Edit")
    edit_labels = [a.text().replace("&", "") for a in edit_menu.actions() if a.text().strip()]
    assert edit_labels == [
        "Undo",
        "Redo",
        "Edit Structure",
        "Delete Atom(s)",
        "Add Bond",
        "Delete Bond",
    ]
    dlg._act_edit_structure.setChecked(True)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"O81","elem":"O","serial":100,"model":0}'
    )
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,"model":0}'
    )
    atoms = dlg._highlighted_edit_atoms()
    assert [sel["atom"] for sel in atoms] == ["O81", "C80"]
    assert dlg._act_add_bond.isEnabled() is True
    dlg.add_highlighted_bond()
    partners = pdb_conect_partners(dlg._slots[0].text)
    assert 101 in partners[100]
    assert dlg._act_undo.isEnabled() is True
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._act_edit_structure.setChecked(False)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,"model":0}'
    )
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg.delete_selected()
    text = dlg._slots[0].text
    assert " CA  MET" not in text
    assert " N   MET" in text
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    dlg.undo_manager_delete()
    assert "CA" in dlg._slots[0].text
    dlg.close()


def test_delete_selected_residue_ligand_and_undo(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg._on_atom_picked(
        '{"chain":"A","resn":"MET","resi":"1","icode":"","atom":"CA","elem":"C","serial":2,'
        '"doubleClick":true,"model":0}'
    )
    assert dlg._residue_highlight[0].get("atom") in (None, "")
    polymer_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "polymer")
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg.delete_selected()
    text = dlg._slots[0].text
    assert " MET A" not in text
    assert " LEU B" in text
    assert " AXI A" in text
    assert polymer_id in {r.spec.component_id for r in dlg._rows}
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is True
    dlg.undo_manager_delete()
    assert " MET A" in dlg._slots[0].text
    dlg._on_atom_picked(
        '{"chain":"A","resn":"AXI","resi":"2000","atom":"C80","elem":"C","serial":101,'
        '"doubleClick":true,"model":0}'
    )
    dlg.delete_selected()
    assert " AXI A" not in dlg._slots[0].text
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    assert polymer_id in {r.spec.component_id for r in dlg._rows}
    dlg.undo_manager_delete()
    assert " AXI A" in dlg._slots[0].text
    assert any(r.spec.kind == "ligand" for r in dlg._rows)
    dlg.close()


def test_sequence_delete_is_undoable(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg._refresh_sequence_chains(force=True)
    met = next(
        res
        for chain in dlg._sequence_chains
        for res in chain.residues
        if res.chain == "A" and res.resi == "1"
    )
    dlg._on_sequence_deleted([met])
    assert " MET A" not in dlg._slots[0].text
    assert " LEU B" in dlg._slots[0].text
    assert dlg._act_undo.isEnabled() is True
    dlg.undo_manager_delete()
    assert " MET A" in dlg._slots[0].text
    dlg.close()


def test_pocket_view_plan_near_ligand_residues_and_polar_h():
    plan = pocket_view_plan(_POCKET_PDB, "pdb")
    assert plan is not None
    lig = plan.ligand_sels
    assert len(lig) == 1
    assert lig[0]["resn"] == "LIG"
    assert lig[0]["resi"] == 99
    assert lig[0].get("hetflag") is True
    nearby = {(s["resn"], s["resi"]) for s in plan.residue_sels}
    assert ("SER", 10) in nearby
    assert ("ALA", 50) not in nearby
    assert any(
        line[76:78].strip() == "H"
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM"))
    )


def test_pocket_view_plan_keeps_only_polar_hydrogens():
    plan = pocket_view_plan(_POCKET_H_PDB, "pdb")
    assert plan is not None
    h_names = {
        line[12:16].strip()
        for line in plan.polar_h_pdb.splitlines()
        if line.startswith(("ATOM", "HETATM")) and line[76:78].strip() == "H"
    }
    assert "HG" in h_names
    assert "HO1" in h_names
    assert "HP1" in h_names
    assert "HA" not in h_names
    assert "H1" not in h_names


def test_protein_viewer_html_draws_heteroatom_polar_hydrogens():
    html = build_protein_viewer_html()
    assert "function polarHeavy" in html
    assert "polarHeavyAtom" in html
    assert "showPolarHydrogen" in html
    assert "foundPolar" in html
    assert "keepH: true" in html
    assert "normalizeHydrogenElements" in html
    assert "attachHydrogensToHeavies" in html
    assert "showHydrogenParent" in html
    assert "{stick: {radius: 0.12, hidden: false}, sphere: {scale: 0.16, hidden: false}}" in html
    assert "v.setStyle({model: mid}, {hidden: true})" not in html


def test_protein_menu_opens_viewer(qapp):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    labels = [a.text().replace("&", "") for a in w.menuBar().actions()]
    assert "Protein" in labels
    protein_menu = next(
        a.menu() for a in w.menuBar().actions() if a.text().replace("&", "") == "Protein"
    )
    viewer_labels = [a.text().replace("&", "") for a in protein_menu.actions()]
    assert "Viewer" in viewer_labels
    assert any(lab.startswith("Sequence") for lab in viewer_labels)
    assert "Dock Ligand" in viewer_labels
    w.open_protein_viewer()
    dlg = w._protein_viewer_dialog
    assert dlg is not None
    assert dlg.windowTitle() == "Protein Viewer"
    assert dlg.manager.tree.topLevelItemCount() == 0
    dlg.close()
    w.close()


def test_log_reaches_window_bottom_with_manager(qapp):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    dlg = ProteinViewerDialog()
    dlg.resize(1180, 760)
    dlg.show()
    qapp.processEvents()
    log_bottom = dlg.log.mapTo(dlg, dlg.log.rect().bottomRight()).y()
    mgr_bottom = dlg.manager.mapTo(dlg, dlg.manager.rect().bottomRight()).y()
    tree_bottom = dlg.manager.tree.mapTo(dlg, dlg.manager.tree.rect().bottomRight()).y()
    assert abs(log_bottom - mgr_bottom) <= 2
    assert abs(log_bottom - tree_bottom) <= 2
    status_bottom = dlg._atom_status.mapTo(dlg, dlg._atom_status.rect().bottomRight()).y()
    assert status_bottom < dlg.log.mapTo(dlg, dlg.log.rect().topLeft()).y()
    dlg.close()


def test_manager_hide_select_delete(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.protein_viewer import _ID_ROLE, ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert not hasattr(dlg.manager, "btn_open")
    assert not hasattr(dlg.manager, "hint")
    assert not hasattr(dlg.manager, "btn_hide")
    ids = [r.spec.component_id for r in dlg._rows]
    assert any("polymer:A" in i for i in ids)
    assert dlg.manager.tree.topLevelItemCount() == 1
    assert dlg.manager.tree.topLevelItem(0).text(0) == "mini.pdb"
    chain_labels = [
        dlg.manager.tree.topLevelItem(0).child(i).text(0)
        for i in range(dlg.manager.tree.topLevelItem(0).childCount())
    ]
    assert chain_labels == ["Chain A", "Chain B"]
    chain_a = dlg.manager.tree.topLevelItem(0).child(0)
    assert [chain_a.child(i).text(0) for i in range(chain_a.childCount())] == [
        "Polymer",
        "AXI 2000",
        "MG 2001",
        "Water",
    ]
    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    water_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "water")
    assert next(r for r in dlg._rows if r.spec.component_id == water_id).visible is False

    dlg._on_visibility_changed(ligand_id, False)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is False

    dlg._on_manager_selection([ligand_id])
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).selected is True
    assert next(r for r in dlg._rows if r.spec.kind == "polymer").selected is False
    dlg.invert_selection()
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).selected is False
    assert any(r.selected for r in dlg._rows if r.spec.kind == "polymer")
    dlg.invert_selection()
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).selected is True
    assert next(r for r in dlg._rows if r.spec.kind == "polymer").selected is False

    dlg._on_style_requested("stick")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).style == "stick"
    assert next(r for r in dlg._rows if r.spec.kind == "polymer").style == "cartoon"

    dlg._apply_selected_color("green")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).color_scheme == "green"
    assert all(r.color_scheme == "default" for r in dlg._rows if r.spec.kind == "polymer")
    lig_payload = next(p for p in dlg._component_payloads() if p["kind"] == "ligand")
    assert lig_payload["carbonScheme"] == "greenCarbon"

    dlg._set_selected_visible(False)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is False
    dlg._set_selected_visible(True)
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).visible is True

    dlg._apply_selected_color("#fa8072")
    assert next(r for r in dlg._rows if r.spec.component_id == ligand_id).color_scheme == "#fa8072"
    lig_payload = next(p for p in dlg._component_payloads() if p["kind"] == "ligand")
    assert lig_payload["carbonScheme"] == "#fa8072"

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    ligand_item = None
    for i in range(dlg.manager.tree.topLevelItemCount()):
        file_item = dlg.manager.tree.topLevelItem(i)
        for j in range(file_item.childCount()):
            group = file_item.child(j)
            for k in range(group.childCount()):
                item = group.child(k)
                if item.data(0, _ID_ROLE) == ligand_id:
                    ligand_item = item
    assert ligand_item is not None
    dlg.manager.tree.clearSelection()
    ligand_item.setSelected(True)
    dlg.delete_selected()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    dlg.close()


def test_manager_delete_undo_redo(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMenuBar, QMessageBox

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    mb = dlg.findChild(QMenuBar)
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert labels[:4] == ["File", "Edit", "Tools", "Render"]
    edit_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Edit")
    edit_labels = [a.text().replace("&", "") for a in edit_menu.actions() if a.text().strip()]
    assert edit_labels == [
        "Undo",
        "Redo",
        "Edit Structure",
        "Delete Atom(s)",
        "Add Bond",
        "Delete Bond",
    ]
    assert dlg._act_undo.isEnabled() is False
    assert dlg._act_redo.isEnabled() is False

    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_manager_selection([ligand_id])
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    dlg.delete_selected()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is True
    assert dlg._act_redo.isEnabled() is False

    dlg.undo_manager_delete()
    assert ligand_id in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is False
    assert dlg._act_redo.isEnabled() is True

    dlg.redo_manager_delete()
    assert ligand_id not in {r.spec.component_id for r in dlg._rows}
    assert dlg._act_undo.isEnabled() is True
    assert dlg._act_redo.isEnabled() is False
    dlg.close()


def test_manager_context_menu_duplicate(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtWidgets import QMenu

    from molmanager.ui.protein_viewer import _ID_ROLE, ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert dlg.manager.tree.contextMenuPolicy() == Qt.CustomContextMenu
    menu_labels = [
        action.text().replace("&", "")
        for action in dlg.manager._make_context_menu().actions()
        if action.text()
    ]
    assert menu_labels == ["Delete", "Duplicate", "Add to Group"]

    ligand_id = next(r.spec.component_id for r in dlg._rows if r.spec.kind == "ligand")
    ligand_item = None
    for i in range(dlg.manager.tree.topLevelItemCount()):
        file_item = dlg.manager.tree.topLevelItem(i)
        for j in range(file_item.childCount()):
            group = file_item.child(j)
            for k in range(group.childCount()):
                item = group.child(k)
                if item.data(0, _ID_ROLE) == ligand_id:
                    ligand_item = item
    assert ligand_item is not None

    dlg.manager.tree.clearSelection()
    shown: list[list[str]] = []

    def fake_exec(self, *a, **k):  # noqa: ARG001
        shown.append([action.text().replace("&", "") for action in self.actions() if action.text()])
        return None

    monkeypatch.setattr(dlg.manager.tree, "itemAt", lambda _pos: ligand_item)
    monkeypatch.setattr(QMenu, "exec_", fake_exec)
    dlg.manager._on_context_menu(QPoint(0, 0))
    assert ligand_item.isSelected()
    assert shown == [["Delete", "Duplicate", "Add to Group"]]

    dlg._on_manager_selection([ligand_id])
    dlg._apply_selected_color("green")
    dlg.duplicate_selected()
    assert len(dlg._slots) == 2
    assert dlg._slots[1].name == "mini copy.pdb"
    assert {row.spec.kind for row in dlg._slots[1].rows} == {"ligand"}
    assert "AXI" in dlg._slots[1].text
    assert "MET" not in dlg._slots[1].text
    assert any(row.spec.kind == "polymer" for row in dlg._slots[0].rows)
    copy_ligand = next(row for row in dlg._slots[1].rows if row.spec.kind == "ligand")
    assert copy_ligand.color_scheme == "green"

    dlg.manager.tree.clearSelection()
    dlg.manager.tree.topLevelItem(0).setSelected(True)
    dlg.duplicate_selected()
    assert len(dlg._slots) == 3
    assert dlg._slots[2].name == "mini copy (2).pdb"
    assert len(dlg._slots[2].rows) == len(dlg._slots[0].rows)
    dlg.close()


def test_manager_named_groups(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import (
        USER_GROUP_KIND,
        _GROUP_ROLE,
        _ID_ROLE,
        _KIND_ROLE,
        ProteinViewerDialog,
    )

    def _walk(tree):
        def walk(item):
            yield item
            for i in range(item.childCount()):
                yield from walk(item.child(i))

        for i in range(tree.topLevelItemCount()):
            yield from walk(tree.topLevelItem(i))

    def _file_item(tree, cid):
        for item in _walk(tree):
            if item.data(0, _ID_ROLE) == cid and not item.data(0, _GROUP_ROLE):
                return item
        return None

    def _group_folder(tree, name):
        for i in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(i)
            if item.data(0, _KIND_ROLE) == USER_GROUP_KIND and item.text(0) == name:
                return item
        return None

    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.add_structure_path(first, refit=False)
    dlg.add_structure_path(second, refit=False)
    ligand_ids = [row.spec.component_id for row in dlg._rows if row.spec.kind == "ligand"]
    polymer_ids = [row.spec.component_id for row in dlg._rows if row.spec.kind == "polymer"]
    assert len(ligand_ids) == 2
    assert len(polymer_ids) >= 2

    dlg.manager.tree.clearSelection()
    _file_item(dlg.manager.tree, ligand_ids[0]).setSelected(True)
    dlg._on_add_to_group("Pocket")
    folder = _group_folder(dlg.manager.tree, "Pocket")
    assert folder is not None
    assert folder.childCount() == 1
    assert folder.child(0).data(0, _ID_ROLE) == ligand_ids[0]

    dlg.manager.tree.clearSelection()
    _file_item(dlg.manager.tree, polymer_ids[0]).setSelected(True)
    dlg._on_add_to_group("pocket")
    folder = _group_folder(dlg.manager.tree, "Pocket")
    member_ids = [folder.child(i).data(0, _ID_ROLE) for i in range(folder.childCount())]
    assert ligand_ids[0] in member_ids
    assert polymer_ids[0] in member_ids

    dlg.manager.tree.clearSelection()
    _file_item(dlg.manager.tree, ligand_ids[1]).setSelected(True)
    dlg._on_add_to_group("Pocket")
    folder = _group_folder(dlg.manager.tree, "Pocket")
    member_ids = [folder.child(i).data(0, _ID_ROLE) for i in range(folder.childCount())]
    assert ligand_ids[0] in member_ids
    assert ligand_ids[1] in member_ids
    assert polymer_ids[0] in member_ids
    labels = [folder.child(i).text(0) for i in range(folder.childCount())]
    assert any("first.pdb" in text or "second.pdb" in text for text in labels)

    dlg.manager.tree.clearSelection()
    folder.setSelected(True)
    group_labels = [
        action.text().replace("&", "")
        for action in dlg.manager._make_context_menu(folder).actions()
        if action.text()
    ]
    assert group_labels == ["Rename Group…", "Remove Group"]

    state = dlg.collect_session_state()
    assert state is not None
    payload = state["namedGroups"]
    assert len(payload) == 1
    assert payload[0]["name"] == "Pocket"
    assert len(payload[0]["members"]) == 3

    dlg2 = ProteinViewerDialog()
    dlg2.apply_session_state(state)
    folder2 = _group_folder(dlg2.manager.tree, "Pocket")
    assert folder2 is not None
    assert folder2.childCount() == 3

    member = folder2.child(0)
    drop_id = member.data(0, _ID_ROLE)
    dlg2.manager.tree.clearSelection()
    member.setSelected(True)
    dlg2._on_remove_from_group(str(member.data(0, _GROUP_ROLE) or ""))
    folder2 = _group_folder(dlg2.manager.tree, "Pocket")
    remaining = [folder2.child(i).data(0, _ID_ROLE) for i in range(folder2.childCount())]
    assert drop_id not in remaining
    assert folder2.childCount() == 2
    assert len(dlg2._slots) == 2

    dlg2._on_delete_group(str(folder2.data(0, _GROUP_ROLE) or ""))
    assert _group_folder(dlg2.manager.tree, "Pocket") is None
    assert len(dlg2._slots) == 2
    dlg.close()
    dlg2.close()


def test_tools_dock_ligand_opens_gnina(qapp):  # noqa: ARG001
    from PyQt5.QtWidgets import QWidget

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    class _Host(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.opened = 0

        def open_gnina_dock(self) -> None:
            self.opened += 1

    host = _Host()
    dlg = ProteinViewerDialog(host)
    dlg._act_dock_ligand.trigger()
    assert host.opened == 1
    dlg.close()
    host.close()


def test_unscoped_component_id():
    from molmanager.ui.protein_viewer_models import unscoped_component_id

    assert unscoped_component_id("s0:ligand:A:AXI:2000") == "ligand:A:AXI:2000"
    assert unscoped_component_id("s12:polymer:A") == "polymer:A"
    assert unscoped_component_id("ligand:A:AXI:2000") == "ligand:A:AXI:2000"


def test_sequence_window_select_and_edit(qapp, tmp_path):  # noqa: ARG001
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QMenuBar

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "mini.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    dlg._refresh_sequence_chains(force=True)
    assert [c.sequence for c in dlg._sequence_chains] == ["M+*~", "L~"]
    mb = dlg.findChild(QMenuBar)
    assert mb is not None
    labels = [a.text().replace("&", "") for a in mb.actions()]
    assert labels[:4] == ["File", "Edit", "Tools", "Render"]
    assert labels[4] == "Select"
    assert "Sequence" not in labels
    tools_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Tools")
    tools_labels = [a.text().replace("&", "") for a in tools_menu.actions() if a.text().strip()]
    assert tools_labels[:3] == ["Prepare", "Dock Ligand…", "Pharmacophore"]
    corner = mb.cornerWidget(Qt.TopRightCorner)
    assert corner is not None
    assert dlg._btn_sequence is not None
    assert dlg._btn_sequence.text() == "Sequence"
    assert dlg._btn_sequence.parent() is corner
    select_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Select")
    select_labels = [a.text().replace("&", "") for a in select_menu.actions() if a.text().strip()]
    assert select_labels[:4] == ["Hide", "Show", "Focus", "Invert Selection"]
    assert "Delete" in select_labels
    assert "Clear Selection" in select_labels
    assert "Render" in select_labels
    assert "Color" in select_labels
    select_render = next(
        a.menu() for a in select_menu.actions() if a.text().replace("&", "") == "Render"
    )
    select_color = next(
        a.menu() for a in select_menu.actions() if a.text().replace("&", "") == "Color"
    )
    assert "Cartoon" in [a.text().replace("&", "") for a in select_render.actions()]
    select_render_labels = [a.text().replace("&", "") for a in select_render.actions()]
    assert "Spheres" not in select_render_labels
    assert "Wireframe" not in select_render_labels
    assert "Hydrogens" in select_render_labels
    select_h = next(
        a.menu() for a in select_render.actions() if a.text().replace("&", "") == "Hydrogens"
    )
    assert [a.text().replace("&", "") for a in select_h.actions()] == ["All", "Polar", "None"]
    select_h_all = next(a for a in select_h.actions() if a.text().replace("&", "") == "All")
    select_h_polar = next(a for a in select_h.actions() if a.text().replace("&", "") == "Polar")
    assert select_h_polar.isChecked()
    select_h_all.trigger()
    assert dlg._hydrogen_mode() == "all"
    assert dlg._act_hydrogens_all.isChecked()
    assert all(a.isChecked() for a in dlg._hydrogen_mode_actions["all"])
    dlg._act_hydrogens_polar.trigger()
    assert dlg._hydrogen_mode() == "polar"
    assert select_h_polar.isChecked()
    assert "Custom…" in [a.text().replace("&", "") for a in select_color.actions()]
    render_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Render")
    render_labels = [a.text().replace("&", "") for a in render_menu.actions() if a.text().strip()]
    assert "Protein" in render_labels
    assert "Ligand" in render_labels
    assert "Focus Pocket" in render_labels
    assert "Pocket" not in render_labels
    assert "All Atoms" in render_labels
    assert render_labels.index("Focus Pocket") == render_labels.index("Reset Camera") - 1
    protein_menu = next(
        a.menu() for a in render_menu.actions() if a.text().replace("&", "") == "Protein"
    )
    ligand_menu = next(
        a.menu() for a in render_menu.actions() if a.text().replace("&", "") == "Ligand"
    )
    protein_styles = [a.text().replace("&", "") for a in protein_menu.actions() if a.text().strip()]
    ligand_styles = [a.text().replace("&", "") for a in ligand_menu.actions() if a.text().strip()]
    assert "Cartoon" in protein_styles
    assert "Spheres" not in protein_styles
    assert "Wireframe" not in protein_styles
    assert "Cartoon" not in ligand_styles
    assert "Spheres" not in ligand_styles
    assert "Wireframe" not in ligand_styles
    assert "Ball and stick" in ligand_styles
    assert "Sticks" in ligand_styles
    assert "Color" in protein_styles
    protein_color_menu = next(
        a.menu() for a in protein_menu.actions() if a.text().replace("&", "") == "Color"
    )
    ligand_color_menu = next(
        a.menu() for a in ligand_menu.actions() if a.text().replace("&", "") == "Color"
    )
    color_labels = [a.text().replace("&", "") for a in protein_color_menu.actions()]
    assert color_labels == [a.text().replace("&", "") for a in ligand_color_menu.actions()]
    assert "Default" in color_labels
    assert "Green" in color_labels
    dlg._on_render_style_chosen("polymer", "surface")
    dlg._on_render_style_chosen("ligand", "stick")
    assert all(r.style == "surface" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "stick" for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_render_color_chosen("ligand", "green")
    dlg._on_render_color_chosen("polymer", "cyan")
    assert all(r.color_scheme == "green" for r in dlg._rows if r.spec.kind == "ligand")
    assert all(r.color_scheme == "cyan" for r in dlg._rows if r.spec.kind == "polymer")
    payloads = dlg._component_payloads()
    lig_payload = next(p for p in payloads if p["kind"] == "ligand")
    prot_payload = next(p for p in payloads if p["kind"] == "polymer")
    assert lig_payload["carbonScheme"] == "greenCarbon"
    assert prot_payload["carbonScheme"] == "cyanCarbon"
    assert prot_payload["cartoonColor"] == "cyan"
    dlg.open_sequence_window()
    seq = dlg._sequence_dialog
    assert seq is not None
    assert seq.windowTitle() == "Sequence"
    assert seq.tabs.count() == 2
    seq.select_residue("A", "2000", "")
    assert dlg._residue_highlight
    assert dlg._residue_highlight[0]["chain"] == "A"
    captured: list[list] = []
    seq.residues_mutated.connect(captured.append)
    editor = seq._editor_at(0)
    assert editor is not None
    assert editor.isReadOnly()
    ligand_menu = editor._make_context_menu()
    ligand_mutate = next(
        a.menu() for a in ligand_menu.actions() if a.text().replace("&", "") == "Mutate"
    )
    assert not ligand_mutate.isEnabled()
    seq.select_residue("A", "1", "")
    original = editor.toPlainText()
    QTest.keyClick(editor, Qt.Key_S)
    assert editor.toPlainText() == original
    assert not captured
    menu = editor._make_context_menu()
    mutate_menu = next(a.menu() for a in menu.actions() if a.text().replace("&", "") == "Mutate")
    assert mutate_menu is not None
    assert mutate_menu.isEnabled()
    labels = [a.text().replace("&", "") for a in mutate_menu.actions()]
    assert "S  SER" in labels
    ser_act = next(a for a in mutate_menu.actions() if a.text().replace("&", "") == "S  SER")
    ser_act.trigger()
    assert captured
    residue, letter = captured[0][0]
    assert letter == "S"
    assert residue.resn == "MET"
    dlg._act_all_atoms.setChecked(True)
    assert all(r.style == "ballstick" for r in dlg._rows if r.spec.kind == "polymer")
    dlg._act_all_atoms.setChecked(False)
    assert all(r.style == "cartoon" for r in dlg._rows if r.spec.kind == "polymer")
    seq.close()
    dlg.close()


def test_reset_camera_restores_loaded_styles(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "reset.pdb"
    path.write_text(_POCKET_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert all(r.style == "cartoon" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "ballstick" for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_render_style_chosen("polymer", "surface")
    dlg._on_render_style_chosen("ligand", "stick")
    dlg._on_render_color_chosen("polymer", "cyan")
    dlg._on_render_color_chosen("ligand", "green")
    dlg._act_all_atoms.setChecked(True)
    dlg._on_pocket()
    assert dlg._pocket_payload_data is not None
    dlg._reset_camera()
    assert all(r.style == "cartoon" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "ballstick" for r in dlg._rows if r.spec.kind == "ligand")
    assert all(
        r.color_scheme == "default" for r in dlg._rows if r.spec.kind in ("polymer", "ligand")
    )
    assert not dlg._act_all_atoms.isChecked()
    assert dlg._protein_style_actions["cartoon"].isChecked()
    assert dlg._ligand_style_actions["ballstick"].isChecked()
    assert dlg._protein_color_actions["default"].isChecked()
    assert dlg._ligand_color_actions["default"].isChecked()
    assert dlg._pocket_payload_data is None
    dlg.close()


def test_reset_camera_keeps_styles_from_load_menus(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "reset_menu.pdb"
    path.write_text(_MINI_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg._protein_style_actions["surface"].trigger()
    dlg._ligand_style_actions["stick"].trigger()
    dlg.load_structure_path(path)
    assert all(r.style == "surface" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "stick" for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_render_style_chosen("polymer", "cartoon")
    dlg._on_render_style_chosen("ligand", "ballstick")
    dlg._reset_camera()
    assert all(r.style == "surface" for r in dlg._rows if r.spec.kind == "polymer")
    assert all(r.style == "stick" for r in dlg._rows if r.spec.kind == "ligand")
    assert dlg._protein_style_actions["surface"].isChecked()
    assert dlg._ligand_style_actions["stick"].isChecked()
    dlg.close()


def test_pocket_view_menu_builds_overlay(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    path = tmp_path / "pocket.pdb"
    path.write_text(_POCKET_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert not dlg._act_pocket.isCheckable()
    assert dlg._act_hydrogens_polar.isChecked()
    assert not dlg._act_hydrogens_all.isChecked()
    assert not dlg._act_hydrogens_none.isChecked()
    dlg._act_hydrogens_all.trigger()
    assert dlg._hydrogen_mode() == "all"
    dlg._act_hydrogens_none.trigger()
    assert dlg._hydrogen_mode() == "none"
    dlg._act_hydrogens_polar.trigger()
    assert dlg._hydrogen_mode() == "polar"
    assert dlg._act_hbond_protein is not None
    assert not dlg._act_hbond_protein.isChecked()
    assert dlg._act_hbond_ligand.isChecked()
    assert dlg._act_hbond_complex.isChecked()
    dlg._on_pocket()
    payload = dlg._pocket_payload_data
    assert payload is not None
    assert payload["active"] is True
    assert payload["ligandSels"]
    assert any(s.get("resn") == "SER" for s in payload["residueSels"])
    assert payload["polarHPdb"]
    dlg._on_render_style_chosen("polymer", "cartoon")
    assert dlg._pocket_payload_data is None
    dlg._on_pocket()
    assert dlg._pocket_payload_data is not None
    dlg._on_render_style_chosen("polymer", "surface")
    assert dlg._pocket_payload_data is None
    assert all(r.style == "surface" for r in dlg._rows if r.spec.kind == "polymer")
    dlg.close()


def test_normalize_pocket_surface_settings():
    from molmanager.ui.dialogs.protein_pocket_surface import (
        DEFAULT_POCKET_SURFACE_SETTINGS,
        normalize_pocket_surface_settings,
    )

    assert normalize_pocket_surface_settings(None)["color"] == "lightgray"
    custom = normalize_pocket_surface_settings({"color": "#1a2b3c", "opacity": 0.2, "wireframe": 1})
    assert custom["color"] == "#1a2b3c"
    assert custom["opacity"] == 0.2
    assert custom["wireframe"] is True
    element = normalize_pocket_surface_settings({"colorScheme": "element"})
    assert element["colorScheme"] == "element"
    clamped = normalize_pocket_surface_settings(
        {"opacity": 9, "linewidth": 0.1, "surfaceType": "nope"}
    )
    assert clamped["opacity"] == 1.0
    assert clamped["linewidth"] == 0.5
    assert clamped["surfaceType"] == "ms"
    hydro = normalize_pocket_surface_settings({"colorScheme": "hydrophobicity"})
    assert hydro["colorScheme"] == "hydrophobicity"
    assert hydro["color"] == "lightgray"
    charge = normalize_pocket_surface_settings({"color": "charge"})
    assert charge["colorScheme"] == "charge"
    assert (
        normalize_pocket_surface_settings({})["opacity"]
        == DEFAULT_POCKET_SURFACE_SETTINGS["opacity"]
    )


def test_pocket_surface_menu_toggle(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.dialogs.protein_pocket_surface import ProteinPocketSurfaceDialog
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    shown: list[str] = []

    def _info(_parent, title, *_a, **_k):
        shown.append(str(title))
        return QMessageBox.Ok

    monkeypatch.setattr(QMessageBox, "information", _info)
    path = tmp_path / "pocket.pdb"
    path.write_text(_POCKET_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert not dlg._act_pocket_surface.isCheckable()
    dlg.open_pocket_surface_dialog()
    surf = dlg._pocket_surface_dialog
    assert isinstance(surf, ProteinPocketSurfaceDialog)
    assert surf.isVisible()
    assert not surf.chk_show.isChecked()
    assert dlg._pocket_surface_payload is None
    surf.btn_ok.click()
    assert not surf.isVisible()
    assert surf.chk_show.isChecked()
    payload = dlg._pocket_surface_payload
    assert payload is not None
    assert payload["active"] is True
    assert payload["opacity"] == 0.7
    assert payload["color"] == "lightgray"
    assert payload["wireframe"] is False
    assert payload["surfaceType"] == "ms"
    assert any(s.get("resn") == "SER" for s in payload["residueSels"])
    surf.spin_opacity.setValue(40)
    assert dlg._pocket_surface_payload["opacity"] == 0.4
    surf.chk_wireframe.setChecked(True)
    assert dlg._pocket_surface_payload["wireframe"] is True
    green = surf.combo_color.findData("green")
    surf.combo_color.setCurrentIndex(green)
    assert dlg._pocket_surface_payload["color"] == "green"
    vdw = surf.combo_type.findData("vdw")
    surf.combo_type.setCurrentIndex(vdw)
    assert dlg._pocket_surface_payload["surfaceType"] == "vdw"
    hydro = surf.combo_color.findData("hydrophobicity")
    surf.combo_color.setCurrentIndex(hydro)
    assert dlg._pocket_surface_payload["colorScheme"] == "hydrophobicity"
    residue_colors = dlg._pocket_surface_payload["residueColors"]
    assert residue_colors["ARG"] != residue_colors["ILE"]
    charge = surf.combo_color.findData("charge")
    surf.combo_color.setCurrentIndex(charge)
    assert dlg._pocket_surface_payload["colorScheme"] == "charge"
    assert "residueColors" not in dlg._pocket_surface_payload
    surf.combo_color.setCurrentIndex(green)
    assert dlg._pocket_surface_payload["color"] == "green"
    assert dlg._pocket_surface_payload["colorScheme"] == "solid"
    dlg._on_render_style_chosen("polymer", "cartoon")
    assert dlg._pocket_surface_payload is not None
    dlg._reset_camera()
    assert dlg._pocket_surface_payload is not None
    state = dlg.collect_session_state()
    assert state["pocketSurface"]["active"] is True
    assert state["pocketSurface"]["color"] == "green"
    assert state["pocketSurface"]["opacity"] == 0.4
    surf.chk_show.setChecked(False)
    assert dlg._pocket_surface_payload is None
    surf.close()
    dlg.close()

    dlg2 = ProteinViewerDialog()
    dlg2.apply_session_state(state)
    assert dlg2._pocket_surface_payload is not None
    assert dlg2._pocket_surface_payload["color"] == "green"
    assert dlg2._pocket_surface_payload["wireframe"] is True
    dlg2.close()

    empty = tmp_path / "apo.pdb"
    empty.write_text(
        "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\nEND\n",
        encoding="utf-8",
    )
    dlg3 = ProteinViewerDialog()
    dlg3.load_structure_path(empty)
    dlg3.open_pocket_surface_dialog()
    assert dlg3._pocket_surface_dialog is not None
    assert dlg3._pocket_surface_dialog.isVisible()
    assert not dlg3._pocket_surface_dialog.is_showing()
    assert dlg3._pocket_surface_payload is None
    assert shown == []
    dlg3._pocket_surface_dialog.btn_ok.click()
    assert "Pocket Surface" in shown
    assert dlg3._pocket_surface_dialog.isVisible()
    assert not dlg3._pocket_surface_dialog.is_showing()
    assert dlg3._pocket_surface_payload is None
    dlg3._pocket_surface_dialog.close()
    dlg3.close()


def test_hbond_menu_filters_kinds(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    pdb = """\
ATOM      1  C   ALA A   1      -1.240   0.150   0.000  1.00  0.00           C
ATOM      2  O   ALA A   1       0.000   0.000   0.000  1.00  0.00           O
ATOM      3  N   ALA A   3       2.900   0.100   0.000  1.00  0.00           N
ATOM      4  CA  ALA A   3       4.000   0.400   0.000  1.00  0.00           C
ATOM      5  CB  SER A  10      10.000  10.000  10.000  1.00  0.00           C
ATOM      6  OG  SER A  10      11.430  10.000  10.000  1.00  0.00           O
HETATM  100  C1  LIG A  99      15.330  10.200  10.000  1.00  0.00           C
HETATM  101  O1  LIG A  99      14.230  10.100  10.000  1.00  0.00           O
HETATM  102  C2  LIG A  99      17.560  20.000  20.000  1.00  0.00           C
HETATM  103  O2  LIG A  99      18.780  20.000  20.000  1.00  0.00           O
HETATM  104  C3  LIG A  99      22.750  20.150  20.000  1.00  0.00           C
HETATM  105  O3  LIG A  99      21.530  20.150  20.000  1.00  0.00           O
END
"""
    path = tmp_path / "hbonds.pdb"
    path.write_text(pdb, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    empty = dlg._hbond_overlay_payload()
    assert empty["active"] is True
    assert dlg._act_hbond_complex.isChecked()
    dlg._act_hbond_complex.setChecked(False)
    dlg._act_hbond_ligand.setChecked(False)
    for act in dlg._protein_ligand_interaction_actions():
        if act is not None:
            act.setChecked(False)
    empty = dlg._hbond_overlay_payload()
    assert empty["active"] is False
    dlg._act_hbond_protein.setChecked(True)
    protein = dlg._hbond_overlay_payload()
    assert protein["active"] is True
    assert {b["kind"] for b in protein["bonds"]} == {"protein"}
    dlg._act_hbond_complex.setChecked(True)
    both = dlg._hbond_overlay_payload()
    kinds = {b["kind"] for b in both["bonds"]}
    assert "protein" in kinds
    assert "complex" in kinds
    dlg._act_hbond_ligand.setChecked(True)
    all_kinds = {b["kind"] for b in dlg._hbond_overlay_payload()["bonds"]}
    assert all_kinds == {"protein", "ligand", "complex"}
    lig = next(r for r in dlg._rows if r.spec.kind == "ligand")
    dlg._on_visibility_changed(lig.spec.component_id, False)
    hidden_kinds = {b["kind"] for b in dlg._hbond_overlay_payload()["bonds"]}
    assert hidden_kinds == {"protein"}
    dlg.close()


def test_dock_pose_hides_crystal_ligand_contacts(qapp, tmp_path):  # noqa: ARG001
    from rdkit import Chem
    from rdkit.Geometry import Point3D

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    pdb = """\
ATOM      1  N   ALA A   1      -1.240   0.150   0.000  1.00  0.00           N
ATOM      2  O   ALA A   1       0.000   0.000   0.000  1.00  0.00           O
ATOM      3  N   ALA A   3       2.900   0.100   0.000  1.00  0.00           N
ATOM      4  CA  ALA A   3       4.000   0.400   0.000  1.00  0.00           C
ATOM      5  CB  SER A  10      10.000  10.000  10.000  1.00  0.00           C
ATOM      6  OG  SER A  10      11.430  10.000  10.000  1.00  0.00           O
HETATM  100  C1  LIG A  99      15.330  10.200  10.000  1.00  0.00           C
HETATM  101  O1  LIG A  99      14.230  10.100  10.000  1.00  0.00           O
HETATM  102  C2  LIG A  99      17.560  20.000  20.000  1.00  0.00           C
HETATM  103  O2  LIG A  99      18.780  20.000  20.000  1.00  0.00           O
HETATM  104  C3  LIG A  99      22.750  20.150  20.000  1.00  0.00           C
HETATM  105  O3  LIG A  99      21.530  20.150  20.000  1.00  0.00           O
END
"""
    path = tmp_path / "holo.pdb"
    path.write_text(pdb, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    before = dlg._hbond_overlay_payload()
    crystal_pl = [
        b
        for b in before["bonds"]
        if b.get("kind") in {"ligand", "complex"} or (b.get("ligand") or {}).get("resi") == "99"
    ]
    assert crystal_pl
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    conf = Chem.Conformer(mol.GetNumAtoms())
    conf.SetAtomPosition(0, Point3D(40.0, 0.0, 0.0))
    conf.SetAtomPosition(1, Point3D(41.4, 0.0, 0.0))
    conf.SetAtomPosition(2, Point3D(42.0, 1.1, 0.0))
    mol.AddConformer(conf, assignId=True)
    assert dlg.set_dock_pose(mol, zoom=False, caption="Dock pose") is True
    assert dlg._dock_pose_mol is not None
    after = dlg._hbond_overlay_payload()
    for bond in after["bonds"]:
        lig = bond.get("ligand") or {}
        donor = bond.get("donor") or {}
        acc = bond.get("acceptor") or {}
        assert lig.get("resi") != "99"
        assert donor.get("resi") != "99" or donor.get("kind") != "ligand"
        assert acc.get("resi") != "99" or acc.get("kind") != "ligand"
    dlg.clear_dock_pose()
    restored = dlg._hbond_overlay_payload()
    assert any(
        b.get("kind") in {"ligand", "complex"} or (b.get("ligand") or {}).get("resi") == "99"
        for b in restored["bonds"]
    )
    dlg.close()


def test_interaction_menu_toggles_prolif_families(qapp, tmp_path):  # noqa: ARG001
    from molmanager.protein.protein_interactions import FAMILY_HYDROPHOBIC
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    pdb = """\
ATOM      1  C   ALA A   1      -1.240   0.150   0.000  1.00  0.00           C
ATOM      2  O   ALA A   1       0.000   0.000   0.000  1.00  0.00           O
HETATM  100  C1  LIG A  99      14.230  10.100  10.000  1.00  0.00           C
END
"""
    path = tmp_path / "interactions.pdb"
    path.write_text(pdb, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(path)
    assert dlg._act_interact_hydrophobic is not None
    assert dlg._act_interact_hydrophobic.isChecked()
    assert dlg._act_hbond_complex.isChecked()
    assert dlg._act_interact_ionic.isChecked()
    dlg._act_hbond_complex.setChecked(False)
    dlg._act_interact_ionic.setChecked(False)
    dlg._act_interact_pi_stacking.setChecked(False)
    dlg._act_interact_pi_cation.setChecked(False)
    dlg._act_interact_halogen.setChecked(False)
    assert dlg._prolif_families_enabled() == {FAMILY_HYDROPHOBIC}
    payload = dlg._hbond_overlay_payload()
    assert payload["active"] is True
    assert all(b.get("family") != "hbond" for b in payload["bonds"])
    state = dlg.collect_session_state()
    assert state["interactions"]["hydrophobic"] is True
    assert state["interactions"]["ionic"] is False
    dlg.close()


def test_complex_load_enables_protein_ligand_interactions(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    apo = tmp_path / "apo.pdb"
    apo.write_text(
        """\
ATOM      1  N   ALA A   1      0.000   0.000   0.000  1.00  0.00           N
ATOM      2  CA  ALA A   1      1.500   0.000   0.000  1.00  0.00           C
END
""",
        encoding="utf-8",
    )
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(apo)
    assert not dlg._act_hbond_complex.isChecked()
    assert not dlg._act_interact_hydrophobic.isChecked()
    dlg.close()

    lig_only = tmp_path / "lig.pdb"
    lig_only.write_text(
        """\
HETATM  100  C1  LIG A  99      0.000   0.000   0.000  1.00  0.00           C
HETATM  101  O1  LIG A  99      1.400   0.000   0.000  1.00  0.00           O
END
""",
        encoding="utf-8",
    )
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(lig_only)
    assert dlg._act_hbond_ligand.isChecked()
    assert not dlg._act_hbond_complex.isChecked()
    assert not dlg._act_interact_hydrophobic.isChecked()
    dlg.close()

    holo = tmp_path / "holo.pdb"
    holo.write_text(_POCKET_PDB, encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(holo)
    assert dlg._act_hbond_complex.isChecked()
    assert dlg._act_hbond_ligand.isChecked()
    assert dlg._act_interact_hydrophobic.isChecked()
    assert dlg._act_interact_ionic.isChecked()
    assert dlg._act_interact_pi_stacking.isChecked()
    assert dlg._act_interact_pi_cation.isChecked()
    assert dlg._act_interact_halogen.isChecked()
    assert not dlg._act_hbond_protein.isChecked()
    assert dlg._act_hbond_ligand.isChecked()
    dlg._act_interact_hydrophobic.setChecked(False)
    state = dlg.collect_session_state()
    dlg2 = ProteinViewerDialog()
    dlg2.apply_session_state(state)
    assert dlg2._act_hbond_complex.isChecked()
    assert dlg2._act_interact_hydrophobic.isChecked() is False
    dlg.close()
    dlg2.close()


def test_multi_file_session_and_prepare_overlay(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    a = tmp_path / "first.pdb"
    b = tmp_path / "second.pdb"
    a.write_text(_MINI_PDB, encoding="utf-8")
    b.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.add_structure_path(a, refit=True)
    dlg.add_structure_path(b, refit=False)
    names = [
        dlg.manager.tree.topLevelItem(i).text(0)
        for i in range(dlg.manager.tree.topLevelItemCount())
    ]
    assert names == ["first.pdb", "second.pdb"]
    assert len(dlg._slots) == 2
    models = {row.spec.selection.get("model") for row in dlg._rows}
    assert models == {0, 1}
    prepared = tmp_path / "first_prepared.pdb"
    prepared.write_text(_MINI_PDB, encoding="utf-8")
    dlg._on_structure_prepared(str(prepared))
    names = [
        dlg.manager.tree.topLevelItem(i).text(0)
        for i in range(dlg.manager.tree.topLevelItemCount())
    ]
    assert "first.pdb" in names
    assert "first_prepared.pdb" in names
    assert "second.pdb" in names
    assert len(dlg._slots) == 3
    dlg.close()


def test_second_structure_appends_without_replacing_canvas(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    a = tmp_path / "first.pdb"
    b = tmp_path / "second.pdb"
    a.write_text(_MINI_PDB, encoding="utf-8")
    b.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    sets: list[dict] = []
    adds: list[dict] = []
    monkeypatch.setattr(dlg.viewer, "set_payload", lambda payload: sets.append(payload))
    monkeypatch.setattr(dlg.viewer, "add_models", lambda payload: adds.append(payload))
    dlg.viewer._web_ready = True
    dlg.add_structure_path(a, refit=True)
    assert len(sets) == 1
    assert len(sets[0]["models"]) == 1
    assert adds == []
    first_id = dlg._slots[0].structure_id
    first_hbonds = dlg._hbond_cache.get(first_id)
    dlg.add_structure_path(b, refit=False)
    assert len(sets) == 1
    assert len(adds) == 1
    assert len(adds[0]["models"]) == 1
    assert dlg._hbond_cache.get(first_id) == first_hbonds
    dlg.close()


def test_delete_extra_structures_stops_overlay_work(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    files = []
    for name in ("one.pdb", "two.pdb", "three.pdb"):
        path = tmp_path / name
        path.write_text(_MINI_PDB, encoding="utf-8")
        files.append(path)
    dlg = ProteinViewerDialog()
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    for path in files:
        dlg.add_structure_path(path, refit=False)
    assert len(dlg._slots) == 3
    keep_id = dlg._slots[0].structure_id
    drop_ids = [slot.structure_id for slot in dlg._slots[1:]]
    dlg.manager.tree.clearSelection()
    for i in range(1, dlg.manager.tree.topLevelItemCount()):
        dlg.manager.tree.topLevelItem(i).setSelected(True)
    dlg.delete_selected_chains()
    assert [slot.structure_id for slot in dlg._slots] == [keep_id]
    skip = dlg._overlay_skip_sids()
    assert drop_ids[0] in skip
    assert drop_ids[1] in skip
    assert keep_id not in skip
    assert drop_ids[0] not in dlg._hbond_cache
    assert drop_ids[1] not in dlg._hbond_cache
    dlg.close()


def test_4agc_cif_axitinib_has_carbonyl_double():
    from pathlib import Path

    import pytest
    from rdkit import Chem

    from molmanager.workers.protein_prepare_ligand import mol_from_cif_component

    path = Path("samples/4AGC.cif")
    if not path.is_file():
        pytest.skip("samples/4AGC.cif is not present")
    text = path.read_text(encoding="utf-8")
    bonds = parse_cif_chem_comp_bonds(text).get("AXI") or ()
    assert any({b.atom_id_1, b.atom_id_2} == {"C80", "O81"} and b.order == 2 for b in bonds)
    tables = cif_viewer_bond_tables(text)
    assert any(row[2] == 2 for row in tables.get("AXI", []))
    mol = mol_from_cif_component(text, "AXI")
    assert mol is not None
    assert any(bond.GetBondType() == Chem.BondType.DOUBLE for bond in mol.GetBonds())


def test_save_structure_writes_active_slot(qapp, tmp_path, monkeypatch):  # noqa: ARG001
    from PyQt5.QtWidgets import QFileDialog, QMenuBar

    from molmanager.ui.protein_viewer import ProteinViewerDialog

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    dest = tmp_path / "out.pdb"
    dlg = ProteinViewerDialog()
    dlg.load_structure_path(src)
    mb = dlg.findChild(QMenuBar)
    file_menu = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "File")
    labels = [a.text().replace("&", "") for a in file_menu.actions()]
    assert "Save Structure…" in labels
    assert "Save to Session" in labels
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **k: (str(dest), "PDB (*.pdb)"))
    dlg.save_structure_dialog()
    saved = dest.read_bytes().decode("utf-8").replace("\r\n", "\n")
    assert saved.replace("\r\n", "\n") == _MINI_PDB.replace("\r\n", "\n")
    dlg.close()


def test_collect_session_state_keeps_manager_rows(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.protein_viewer import ProteinViewerDialog

    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    dlg = ProteinViewerDialog()
    dlg.add_structure_path(first, refit=True)
    dlg.add_structure_path(second, refit=False)
    lig = next(r for r in dlg._slots[0].rows if r.spec.kind == "ligand")
    dlg._on_visibility_changed(lig.spec.component_id, False)
    dlg._act_hbond_complex.setChecked(True)
    state = dlg.collect_session_state()
    assert state is not None
    assert [s["name"] for s in state["structures"]] == ["first.pdb", "second.pdb"]
    assert "allAtoms" in state
    assert "splitters" in state
    assert "residueHighlight" in state
    dlg._act_all_atoms.setChecked(True)
    state = dlg.collect_session_state()
    assert state["allAtoms"] is True
    dlg2 = ProteinViewerDialog()
    dlg2.apply_session_state(state)
    assert [slot.name for slot in dlg2._slots] == ["first.pdb", "second.pdb"]
    assert dlg2.manager.tree.topLevelItemCount() == 2
    restored = next(r for r in dlg2._slots[0].rows if r.spec.kind == "ligand")
    assert restored.visible is False
    assert dlg2._act_hbond_complex.isChecked()
    assert dlg2._act_all_atoms.isChecked()
    polymer = next(r for r in dlg2._slots[0].rows if r.spec.kind == "polymer")
    assert polymer.style == "ballstick"
    dlg.close()
    dlg2.close()


def test_save_to_session_is_required_for_cms(qapp, tmp_path):  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg.add_structure_path(src, refit=True)
    assert w._collect_protein_viewer() is None
    assert dlg.save_viewer_to_session() is True
    payload = w._collect_protein_viewer()
    assert isinstance(payload, dict)
    assert payload["structures"][0]["name"] == "mini.pdb"
    assert w._session_has_unsaved_changes()
    dlg.close()
    w.close()


def test_close_without_save_to_session_discards_live_viewer(qapp, tmp_path, monkeypatch):
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    first = tmp_path / "first.pdb"
    second = tmp_path / "second.pdb"
    first.write_text(_MINI_PDB, encoding="utf-8")
    second.write_text(_MINI_PDB.replace("MET", "SER").replace("M  ", "S  "), encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(first, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Discard)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted()
    assert w._collect_protein_viewer() is None

    dlg.show()
    dlg.add_structure_path(first, refit=True)
    assert dlg.save_viewer_to_session() is True
    dlg.close_structure()
    dlg.add_structure_path(second, refit=True)
    ev2 = QCloseEvent()
    dlg.closeEvent(ev2)
    assert ev2.isAccepted()
    kept = w._collect_protein_viewer()
    assert kept["structures"][0]["name"] == "first.pdb"
    w.close()


def test_close_save_to_session_commits_live_viewer(qapp, tmp_path, monkeypatch):
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "live.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(src, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Save)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert ev.isAccepted()
    payload = w._collect_protein_viewer()
    assert payload["structures"][0]["name"] == "live.pdb"
    w.close()


def test_close_cancel_keeps_protein_viewer_open(qapp, tmp_path, monkeypatch):
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMessageBox

    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    src = tmp_path / "mini.pdb"
    src.write_text(_MINI_PDB, encoding="utf-8")
    w = ChemistryWorkspaceWindow()
    dlg = w.open_protein_viewer()
    dlg._suppress_close_prompt = False
    dlg.add_structure_path(src, refit=True)
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Cancel)
    ev = QCloseEvent()
    dlg.closeEvent(ev)
    assert not ev.isAccepted()
    assert dlg.isVisible()
    assert w._collect_protein_viewer() is None
    dlg._suppress_close_prompt = True
    dlg.close()
    w.close()
