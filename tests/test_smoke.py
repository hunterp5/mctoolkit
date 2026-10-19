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

"""Import and construction smoke tests for CI."""

from __future__ import annotations

import molmanager
from molmanager.ui.main_window import ChemistryWorkspaceWindow


def test_package_version():
    assert hasattr(molmanager, "__version__")
    assert isinstance(molmanager.__version__, str)


def test_user_guides_html_contains_topics():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("ext_pubchem")
    assert "PubChem" in h
    assert "Topic unavailable" not in h


def test_user_guides_sections_cover_all_topics():
    from molmanager.ui.user_guides import GUIDE_MENU, GUIDE_SECTIONS, iter_guide_entries

    flat = list(iter_guide_entries())
    assert len(flat) == len(GUIDE_MENU)
    assert {e.guide_id for e in flat} == {gid for gid, _ in GUIDE_MENU}
    assert sum(len(s.entries) for s in GUIDE_SECTIONS) == len(flat)


def test_user_guides_data_viz_topic():
    from molmanager.ui.user_guides import guide_html

    h = guide_html("data_pca")
    assert "Principal" in h or "PCA" in h
    assert "Topic unavailable" not in h


def test_pubchem_similarity_results_sort_key():
    from molmanager.ui.external.pubchem import PubChemResult, _pubchem_similarity_sort_key
    from molmanager.ui.strings import COLUMN_TANIMOTO_SIMILARITY

    lo = PubChemResult(1, "C", {COLUMN_TANIMOTO_SIMILARITY: "0.41"})
    hi = PubChemResult(2, "CC", {COLUMN_TANIMOTO_SIMILARITY: "0.92"})
    assert sorted([lo, hi], key=_pubchem_similarity_sort_key, reverse=True)[0] is hi


def test_similarity_fp_type_labels_include_variants():
    from molmanager.chem.rdkit_fingerprints import SIMILARITY_FP_TYPE_LABELS

    joined = "\n".join(SIMILARITY_FP_TYPE_LABELS)
    assert "Atom pair" in joined and "Topological" in joined
    assert "Morgan (r=3" in joined
    assert "FCFP" in joined and "Pattern fingerprint" in joined


def test_fingerprint_bitvect_atom_pair_and_morgan_nbits():
    from rdkit import Chem

    from molmanager.workers.fingerprint_similarity import fingerprint_bitvect_for_ui_choice

    m = Chem.MolFromSmiles("c1ccccc1")
    ap = fingerprint_bitvect_for_ui_choice(m, "Atom pair (hashed, 2048 bits)")
    tt = fingerprint_bitvect_for_ui_choice(m, "Topological torsion (hashed, 2048 bits)")
    assert ap is not None and tt is not None
    assert ap.GetNumBits() == 2048 and tt.GetNumBits() == 2048
    morg = fingerprint_bitvect_for_ui_choice(m, "Morgan (r=2, n=2048)")
    assert morg is not None and morg.GetNumBits() == 2048


def test_parse_molecule_from_cell_text_accepts_smiles_and_inchi():
    from rdkit import Chem

    from molmanager.chem.molecule_conversion import parse_molecule_from_cell_text

    m1 = parse_molecule_from_cell_text("CCO")
    assert m1 is not None and m1.GetNumAtoms() == 3
    inchi = Chem.MolToInchi(m1)
    m2 = parse_molecule_from_cell_text(inchi)
    assert m2 is not None and m2.GetNumAtoms() == 3


def test_smina_dock_guide_html(qapp):  # noqa: ARG001
    from molmanager.ui.user_guides import guide_html

    h = guide_html("tools_gnina")
    assert "Gnina" in h and "PDBQT" in h
    assert "Selected rows" in h
    assert "Flexible side chains" in h
    assert "Protein Viewer" in h
    assert "Manager" in h
    assert "Topic unavailable" not in h


def test_systematic_conformations_guide_html(qapp):  # noqa: ARG001
    from molmanager.ui.user_guides import guide_html

    h = guide_html("tools_gen_conformations_systematic")
    assert "Confab" in h and "Systematic" in h
    assert "Topic unavailable" not in h


def test_conforge_conformations_guide_html(qapp):  # noqa: ARG001
    from molmanager.ui.user_guides import guide_html

    h = guide_html("tools_gen_conformations_conforge")
    assert "CONFORGE" in h and "CDPKit" in h
    assert "Topic unavailable" not in h


def test_smina_dock_dialog_constructible(qapp):  # noqa: ARG001
    from molmanager.ui.gnina_dock import GninaDockDialog

    d = GninaDockDialog(None)
    assert d.windowTitle() == "Dock — Gnina"
    d.close()


def test_chemistry_workspace_window_constructible(qapp):  # noqa: ARG001
    w = ChemistryWorkspaceWindow()
    assert w.windowTitle()
    assert w._table_model is not None
    assert w._sqlite_store is not None


def test_app_table_search_selects_matching_row(qapp):  # noqa: ARG001
    """Integration: table + search bar selects the entries whose column matches the query."""
    from rdkit import Chem

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w._table_model.append_row(1, {"SMILES": "C", "Note": "methane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.mols[1] = Chem.MolFromSmiles("C")
    w.next_oid = 2
    w.calculate_global_bounds()
    w._rebuild_sqlite_store_from_model()

    w._search_panel.setVisible(True)
    w._populate_table_search_columns_combo()
    note_col = w.headers.index("Note")
    for j in range(w._search_col_combo.count()):
        if w._search_col_combo.itemData(j) == note_col:
            w._search_col_combo.setCurrentIndex(j)
            break
    # Quoted literal matches "ethane" only (not "methane" via partial "eth").
    w._search_partial_cb.setChecked(False)
    w._search_query_edit.setText('"ethane"')
    w._search_substructure_cb.setChecked(False)
    w._run_table_search()
    qapp.processEvents()

    assert w._selected_oids_set() == {0}
    assert not w.table.selectionModel().hasSelection()


def test_app_table_search_works_when_sqlite_index_stale(qapp):  # noqa: ARG001
    """Large tables must not require a second Enter while the SQLite mirror rebuilds."""
    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "Note"]
    w._table_model.set_headers(list(w.headers))
    for i in range(6000):
        w._table_model.append_row(i, {"Note": "keep" if i == 42 else "other"})
    w.next_oid = 6000
    w.calculate_global_bounds()
    w._sqlite_store_dirty = True

    w._search_panel.setVisible(True)
    w._populate_table_search_columns_combo()
    note_col = w.headers.index("Note")
    for j in range(w._search_col_combo.count()):
        if w._search_col_combo.itemData(j) == note_col:
            w._search_col_combo.setCurrentIndex(j)
            break
    w._search_query_edit.setText('"keep"')
    w._run_table_search()
    qapp.processEvents()

    assert w._selected_logical_rows() == [42]


def test_search_minus_deletes_last_row_and_toggle_keeps_query(qapp):  # noqa: ARG001
    from rdkit import Chem

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    w.toggle_table_search_panel()
    first = w._search_criterion_rows[0]
    assert not first.remove_btn.isHidden()
    first.query_edit.setText('"ethane"')

    w.toggle_table_search_panel()
    assert w._search_panel.isHidden()
    assert first.query_edit.text() == '"ethane"'

    w.toggle_table_search_panel()
    assert not w._search_panel.isHidden()
    assert first.query_edit.text() == '"ethane"'

    w._add_search_criterion_row()
    assert len(w._search_criterion_rows) == 2
    w._remove_search_criterion_row(w._search_criterion_rows[0])
    assert len(w._search_criterion_rows) == 1
    assert not w._search_panel.isHidden()
    assert not w._search_criterion_rows[0].add_btn.isHidden()

    w._remove_search_criterion_row(w._search_criterion_rows[0])
    assert w._search_panel.isHidden()
    assert w._search_query_edit.text() == ""


def test_table_chemistry_context_menu_column_eligibility(qapp):  # noqa: ARG001
    """Chemistry context actions apply to Structure / SMILES-like columns and parseable cells."""
    from rdkit import Chem

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Note"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC", "Note": "ethane"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1

    assert w._column_eligible_for_table_chemistry_menu(0, 0) is False
    assert w._column_eligible_for_table_chemistry_menu(0, 1) is True
    assert w._column_eligible_for_table_chemistry_menu(0, 2) is True
    assert w._column_eligible_for_table_chemistry_menu(0, 3) is False

    w._table_model.set_cell_text(0, "Note", "CCO")
    assert w._column_eligible_for_table_chemistry_menu(0, 3) is True
    mol = w._mol_for_table_context_menu(0, 2)
    assert mol is not None and mol.GetNumAtoms() == 2
    mol_note = w._mol_for_table_context_menu(0, 3)
    assert mol_note is not None and mol_note.GetNumAtoms() == 3


def test_pixmap_structure_column_context_chemistry(qapp):  # noqa: ARG001
    """Protonated pixmap cells use backing SMILES, not the Structure mol cache."""
    from rdkit import Chem

    parent = Chem.MolFromSmiles("CC(=O)O")
    anion = Chem.MolFromSmiles("CC(=O)[O-]")
    parent_smi = Chem.MolToSmiles(parent, canonical=True)
    anion_smi = Chem.MolToSmiles(anion, canonical=True)

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES", "Protonated", "SOM Map"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": parent_smi, "Protonated": anion_smi, "SOM Map": ""})
    w.mols[0] = parent
    w.next_oid = 1
    w._table_model.register_pixmap_column("Protonated")
    w._table_model.register_pixmap_column("SOM Map")

    prot_col = w.headers.index("Protonated")
    som_col = w.headers.index("SOM Map")
    assert w._column_eligible_for_table_chemistry_menu(0, prot_col) is True
    assert w._column_eligible_for_table_chemistry_menu(0, som_col) is False
    assert w._column_accepts_cell_paste(0, prot_col) is True
    assert w._column_accepts_cell_paste(0, som_col) is False

    mol = w._mol_for_table_context_menu(0, prot_col)
    assert mol is not None
    assert Chem.MolToSmiles(mol, canonical=True) == anion_smi
    struct = w._mol_for_table_context_menu(0, 1)
    assert struct is not None
    assert Chem.MolToSmiles(struct, canonical=True) == parent_smi

    ok, txt = w._copy_text_for_table_cell(0, prot_col, 0)
    assert ok
    copied = Chem.MolFromSmiles(txt)
    assert copied is not None
    assert Chem.MolToSmiles(copied, canonical=True) == anion_smi

    scoped = w.collect_scoped_table_mols("Protonated")
    assert len(scoped) == 1
    assert Chem.MolToSmiles(scoped[0][1], canonical=True) == anion_smi
    assert Chem.MolToSmiles(w.mols[0], canonical=True) == parent_smi

    tool_mol = w._mol_for_structure_tool_oid(0, "Protonated")
    assert tool_mol is not None
    assert Chem.MolToSmiles(tool_mol, canonical=True) == anion_smi

    render_mol = w._mol_for_render2d_source(0, "Protonated")
    assert render_mol is not None
    assert Chem.MolToSmiles(render_mol, canonical=True) == anion_smi
    from molmanager.chem.render2d_mp import mol_from_render_payload

    renders, _ = w._build_render2d_tasks_in_table_order("Protonated", 64, 64)
    assert len(renders) == 1
    render_payload_mol = mol_from_render_payload(renders[0][1])
    assert Chem.MolToSmiles(render_payload_mol, canonical=True) == anion_smi
    assert Chem.MolToSmiles(w.mols[0], canonical=True) == parent_smi

    assert w._paste_clipboard_into_table_cell(0, prot_col, 0, clip_text="CCO", quiet=True)
    pasted = Chem.MolFromSmiles(w._table_model.backing_value_for_row_header(0, "Protonated"))
    assert pasted is not None
    assert pasted.GetNumAtoms() == 3
    assert Chem.MolToSmiles(w.mols[0], canonical=True) == parent_smi


def test_canonical_structure_keys_for_dedup(qapp):  # noqa: ARG001
    from rdkit import Chem

    from molmanager.chem.molecule_conversion import morgan_tanimoto_to_query

    assert morgan_tanimoto_to_query("CC", "CC") == 1.0
    t = morgan_tanimoto_to_query("CCO", "CC")
    assert t is not None and 0.0 < t < 1.0

    w = ChemistryWorkspaceWindow()
    w.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    w._table_model.set_headers(list(w.headers))
    w._table_model.append_row(0, {"SMILES": "CC"})
    w.mols[0] = Chem.MolFromSmiles("CC")
    w.next_oid = 1
    k = w.canonical_structure_key_from_smiles("CC")
    assert k
    assert k in w.existing_canonical_structure_keys()
    assert w.canonical_structure_key_from_smiles("C(C)") == k


def test_data_analysis_outlier_masks() -> None:
    import numpy as np

    from molmanager.ui.data_analysis import (
        _outlier_mask_iqr,
        _outlier_mask_modified_z,
        _outlier_mask_zscore,
    )

    v = np.array([1.0, 2.0, 3.0, 4.0, 1000.0])
    assert _outlier_mask_iqr(v, k=1.5).sum() >= 1
    assert not _outlier_mask_iqr(np.array([1.0, 1.0, 1.0, 1.0]), k=1.5).any()
    vt = np.array([1.0, 2.0, 3.0, 4.0, 50.0])
    assert _outlier_mask_zscore(vt, z=1.5).any()
    assert _outlier_mask_modified_z(vt, threshold=2.0).any()
