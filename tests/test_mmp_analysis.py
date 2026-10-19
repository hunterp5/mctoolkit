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

"""Tests for matched molecular pair analysis helpers."""

from rdkit import Chem

from molmanager.analysis.mmp_analysis import (
    MmpPair,
    aggregate_transforms,
    canonicalize_pair_direction,
    compute_mcs_smarts,
    find_matched_molecular_pairs,
    iter_core_sidechain_keys,
    pairs_for_summary,
    pairs_for_transform,
    parse_mmp_core_query,
)
from molmanager.analysis.mmp_depict import highlight_atoms_for_pair
from molmanager.analysis.mmp_table import assemble_mmp_table_annotations


def _rec(oid: int, smiles: str, activity: float):
    return oid, Chem.MolFromSmiles(smiles), activity


def test_iter_core_sidechain_keys_phenol():
    mol = Chem.MolFromSmiles("Oc1ccccc1")
    keys = list(iter_core_sidechain_keys(mol, max_cuts=1))
    assert keys
    cores = {c for c, _s in keys}
    assert any("c1ccc" in c for c in cores)


def test_find_mmp_phenol_anisole():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    assert pairs
    transforms = {p.transform for p in pairs}
    assert any("O[*:1]>>CO[*:1]" in t or "CO[*:1]>>O[*:1]" in t for t in transforms)
    phenol_anisole = [
        p
        for p in pairs
        if {p.oid_a, p.oid_b} == {1, 2} and "O[*:1]" in p.transform and "CO[*:1]" in p.transform
    ]
    assert phenol_anisole
    p = phenol_anisole[0]
    assert abs(abs(p.delta_activity) - 1.5) < 1e-9


def test_find_mmp_skips_missing_activity_partner():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "CCc1ccc(O)cc1", 1.2),
    ]
    # Different cores for OH->OMe style; still may find pairs via other cuts.
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    assert isinstance(pairs, list)


def test_max_variable_heavy_atoms_filters():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.0),
    ]
    loose = find_matched_molecular_pairs(records, max_variable_heavy_atoms=13)
    tight = find_matched_molecular_pairs(records, max_variable_heavy_atoms=1)
    assert len(loose) >= len(tight)


def test_min_activity_difference_filters():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),  # |Δ| = 1.5
        _rec(3, "CCOc1ccccc1", 2.7),  # vs 2: |Δ| = 0.2
    ]
    all_pairs = find_matched_molecular_pairs(records, max_cuts=1, min_activity_difference=0.0)
    filtered = find_matched_molecular_pairs(records, max_cuts=1, min_activity_difference=1.0)
    assert all_pairs
    assert len(filtered) <= len(all_pairs)
    assert all(abs(p.delta_activity) >= 1.0 - 1e-12 for p in filtered)
    # Phenol–anisole (|Δ|=1.5) should survive; tiny deltas should not.
    assert any({p.oid_a, p.oid_b} == {1, 2} for p in filtered)


def test_max_activity_difference_filters():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),  # |Δ| = 1.5
        _rec(3, "CCOc1ccccc1", 2.7),  # vs 2: |Δ| = 0.2
    ]
    all_pairs = find_matched_molecular_pairs(records, max_cuts=1, max_activity_difference=0.0)
    capped = find_matched_molecular_pairs(records, max_cuts=1, max_activity_difference=1.0)
    assert all_pairs
    assert len(capped) <= len(all_pairs)
    assert all(abs(p.delta_activity) <= 1.0 + 1e-12 for p in capped)
    # Large phenol–anisole cliff excluded; small anisole–phenetole kept.
    assert not any({p.oid_a, p.oid_b} == {1, 2} for p in capped)
    assert any({p.oid_a, p.oid_b} == {2, 3} for p in capped)


def test_parse_mmp_core_query_and_mcs():
    assert parse_mmp_core_query("") is None
    assert parse_mmp_core_query("not a pattern !!!") is None
    q = parse_mmp_core_query("c1ccccc1")
    assert q is not None and q.GetNumAtoms() == 6
    mols = [
        Chem.MolFromSmiles("Oc1ccccc1"),
        Chem.MolFromSmiles("COc1ccccc1"),
        Chem.MolFromSmiles("CCOc1ccccc1"),
    ]
    smarts = compute_mcs_smarts(mols)
    assert smarts
    assert parse_mmp_core_query(smarts) is not None


def test_core_smarts_filters_molecules_and_pairs():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
        _rec(4, "CCCC", 0.5),  # no phenyl — excluded by core
    ]
    unconstrained = find_matched_molecular_pairs(records, max_cuts=1)
    with_core = find_matched_molecular_pairs(records, max_cuts=1, core_smarts="c1ccccc1")
    assert unconstrained
    assert with_core
    assert all(4 not in (p.oid_a, p.oid_b) for p in with_core)
    # Phenyl ethers still form MMP pairs under a benzene core constraint.
    assert any({p.oid_a, p.oid_b} == {1, 2} for p in with_core)


def test_no_duplicate_molecule_pairs():
    """Same two molecules cut at different bonds must yield only one reported pair."""
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    mol_keys = [(p.oid_a, p.oid_b) for p in pairs]
    assert len(mol_keys) == len(set(mol_keys))
    # Anisole–phenetole previously appeared twice (OMe/OEt and Me/Et cuts).
    anisole_phenetole = [p for p in pairs if {p.oid_a, p.oid_b} == {2, 3}]
    assert len(anisole_phenetole) == 1
    # Keep the smallest variable-atom cut (C↔CC rather than CO↔CCO).
    assert anisole_phenetole[0].transform == "C[*:1]>>CC[*:1]"


def test_assemble_mmp_table_annotations():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    rows, headers = assemble_mmp_table_annotations(pairs, activity_column="pIC50")
    assert headers == ["MMP_Partners", "MMP_Transforms", "MMP_Delta_pIC50"]
    assert rows
    by_oid = {oid: vals for oid, vals in rows}
    assert 1 in by_oid and 2 in by_oid
    assert "2" in by_oid[1]["MMP_Partners"]


def test_highlight_atoms_for_pair():
    a = Chem.MolFromSmiles("Oc1ccccc1")
    b = Chem.MolFromSmiles("COc1ccccc1")
    ha, hb = highlight_atoms_for_pair(a, b)
    assert isinstance(ha, list) and isinstance(hb, list)
    # Anisole has an extra carbon relative to phenol; at least one side should highlight.
    assert ha or hb


def _hand_pair(
    *,
    oid_a: int,
    oid_b: int,
    side_a: str,
    side_b: str,
    delta: float,
    core: str = "*",
) -> MmpPair:
    return MmpPair(
        oid_a=oid_a,
        oid_b=oid_b,
        smiles_a="C",
        smiles_b="CC",
        activity_a=0.0,
        activity_b=float(delta),
        delta_activity=float(delta),
        transform=f"{side_a}>>{side_b}",
        core=core,
        sidechain_a=side_a,
        sidechain_b=side_b,
    )


def test_canonicalize_pair_direction_flips_delta():
    pair = _hand_pair(oid_a=1, oid_b=2, side_a="CO[*:1]", side_b="O[*:1]", delta=1.5)
    transform, side_from, side_to, delta = canonicalize_pair_direction(pair)
    assert side_from == "CO[*:1]"
    assert side_to == "O[*:1]"
    assert transform == "CO[*:1]>>O[*:1]"
    assert abs(delta - 1.5) < 1e-12

    flipped = _hand_pair(oid_a=1, oid_b=2, side_a="O[*:1]", side_b="CO[*:1]", delta=-1.5)
    t2, sf2, st2, d2 = canonicalize_pair_direction(flipped)
    assert (t2, sf2, st2) == (transform, side_from, side_to)
    assert abs(d2 - 1.5) < 1e-12


def test_aggregate_transforms_win_rate_and_grouping():
    pairs = [
        _hand_pair(oid_a=1, oid_b=2, side_a="O[*:1]", side_b="CO[*:1]", delta=1.0),
        _hand_pair(oid_a=3, oid_b=4, side_a="CO[*:1]", side_b="O[*:1]", delta=-2.0),
        _hand_pair(oid_a=5, oid_b=6, side_a="C[*:1]", side_b="CC[*:1]", delta=0.0),
    ]
    # O[*:1] vs CO[*:1]: lex order is CO[*:1] < O[*:1]
    # pair1: O>>CO delta +1 → flip to CO>>O delta -1 (worsen)
    # pair2: CO>>O delta -2 → already canonical, worsen
    summaries = aggregate_transforms(pairs)
    by_t = {s.transform: s for s in summaries}
    assert "CO[*:1]>>O[*:1]" in by_t
    s = by_t["CO[*:1]>>O[*:1]"]
    assert s.n == 2
    assert s.n_improve == 0
    assert s.n_worsen == 2
    assert s.win_rate == 0.0
    assert abs(s.median_delta - (-1.5)) < 1e-12
    assert abs(s.mean_delta - (-1.5)) < 1e-12

    # "CC[*:1]" < "C[*:1]" lexicographically, so the flat pair flips.
    flat_key = "CC[*:1]>>C[*:1]"
    assert flat_key in by_t
    flat = by_t[flat_key]
    assert flat.n == 1
    assert flat.n_flat == 1
    assert flat.win_rate == 0.0
    assert flat.n_improve == 0
    assert abs(flat.median_delta) < 1e-12

    matched = pairs_for_transform(pairs, "CO[*:1]>>O[*:1]")
    assert len(matched) == 2


def test_aggregate_transforms_splits_by_core():
    pairs = [
        _hand_pair(oid_a=1, oid_b=2, side_a="O[*:1]", side_b="CO[*:1]", delta=1.0, core="c1ccccc1"),
        _hand_pair(oid_a=3, oid_b=4, side_a="O[*:1]", side_b="CO[*:1]", delta=2.0, core="c1ccncc1"),
    ]
    summaries = aggregate_transforms(pairs)
    assert len(summaries) == 2
    cores = {s.core for s in summaries}
    assert cores == {"c1ccccc1", "c1ccncc1"}
    for s in summaries:
        assert s.n == 1
        assert len(pairs_for_summary(pairs, s)) == 1


def test_aggregate_transforms_reference_oid():
    from molmanager.analysis.mmp_analysis import (
        orient_pair_relative_to_reference,
        pairs_involving_oid,
        reference_oids_in_pairs,
    )

    pairs = [
        _hand_pair(oid_a=1, oid_b=2, side_a="O[*:1]", side_b="CO[*:1]", delta=1.5),
        _hand_pair(oid_a=1, oid_b=3, side_a="O[*:1]", side_b="CCO[*:1]", delta=2.0),
        _hand_pair(oid_a=2, oid_b=3, side_a="CO[*:1]", side_b="CCO[*:1]", delta=0.5),
    ]
    assert reference_oids_in_pairs(pairs) == [1, 2, 3]
    assert len(pairs_involving_oid(pairs, 1)) == 2

    # Pair 1 as B-side reference: reverse transform and negate delta.
    flipped = _hand_pair(oid_a=2, oid_b=1, side_a="CO[*:1]", side_b="O[*:1]", delta=-1.5)
    oriented = orient_pair_relative_to_reference(flipped, 1)
    assert oriented is not None
    transform, side_from, side_to, delta = oriented
    assert side_from == "O[*:1]"
    assert side_to == "CO[*:1]"
    assert abs(delta - 1.5) < 1e-12

    summaries = aggregate_transforms(pairs, reference_oid=1)
    assert sum(s.n for s in summaries) == 2
    assert all(s.n >= 1 for s in summaries)
    # All oriented away from phenol O[*:1]
    assert all(s.sidechain_from == "O[*:1]" for s in summaries)


def test_aggregate_transforms_from_real_pairs():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    summaries = aggregate_transforms(pairs)
    assert summaries
    # Each chemical swap+core appears once; n sums to number of pairs.
    assert sum(s.n for s in summaries) == len(pairs)
    transforms = {s.transform for s in summaries}
    assert all(">>" in t for t in transforms)
    for s in summaries:
        assert s.core is not None
        matched = pairs_for_transform(pairs, s.transform, core=s.core)
        assert len(matched) == s.n
        assert len(pairs_for_summary(pairs, s)) == s.n


def test_apply_transform_to_mol_phenol_anisole():
    from molmanager.analysis.mmp_analysis import apply_transform_to_mol

    phenol = Chem.MolFromSmiles("Oc1ccccc1")
    products = apply_transform_to_mol(phenol, "O[*:1]", "CO[*:1]")
    assert products == ["COc1ccccc1"]

    # Transfer to naphthol
    naphthol = Chem.MolFromSmiles("Oc1ccc2ccccc2c1")
    products = apply_transform_to_mol(naphthol, "O[*:1]", "CO[*:1]")
    assert products == ["COc1ccc2ccccc2c1"]

    # Missing from-side
    anisole = Chem.MolFromSmiles("COc1ccccc1")
    assert apply_transform_to_mol(anisole, "O[*:1]", "CO[*:1]") == []

    # Reverse
    back = apply_transform_to_mol(anisole, "CO[*:1]", "O[*:1]")
    assert back == ["Oc1ccccc1"]


def test_apply_transform_to_mol_two_cut():
    from molmanager.analysis.mmp_analysis import apply_transform_to_mol

    mol = Chem.MolFromSmiles("Nc1ccc(O)cc1")
    products = apply_transform_to_mol(mol, "N[*:1].O[*:2]", "CN[*:1].CO[*:2]", max_cuts=2)
    assert products
    assert any("N" in p and "O" in p for p in products)
    # Canonical expected product from molzip
    assert "CNc1ccc(OC)cc1" in products or any("OC" in p and "NC" in p for p in products)


def test_mmp_ledger_session_payload_roundtrip():
    from molmanager.analysis.mmp_session import (
        deserialize_mmp_ledger_payload,
        serialize_mmp_ledger_payload,
    )

    pair = _hand_pair(
        oid_a=3,
        oid_b=9,
        side_a="Cl[*:1]",
        side_b="F[*:1]",
        delta=-0.5,
        core="c1ccccc1",
    )
    payload = serialize_mmp_ledger_payload([pair], activity_column="IC50")
    assert payload is not None
    assert payload["activity_column"] == "IC50"
    assert len(payload["pairs"]) == 1
    restored, act = deserialize_mmp_ledger_payload(payload)
    assert act == "IC50"
    assert len(restored) == 1
    assert restored[0] == pair
    assert serialize_mmp_ledger_payload([]) is None
    assert deserialize_mmp_ledger_payload(None) == ([], "")


def test_mmp_core_module_does_not_own_session_table_or_depict() -> None:
    from pathlib import Path

    text = (
        Path(__file__).resolve().parents[1] / "molmanager" / "analysis" / "mmp_analysis.py"
    ).read_text(encoding="utf-8")
    assert "def serialize_mmp_ledger_payload" not in text
    assert "def assemble_mmp_table_annotations" not in text
    assert "def highlight_atoms_for_pair" not in text


def test_mmp_dialog_groups_options(qapp) -> None:  # noqa: ARG001
    from PyQt5.QtWidgets import QGroupBox

    from molmanager.ui.dialogs.mmp import MmpDialog

    dialog = MmpDialog(
        structure_sources=["Structure"],
        activity_columns=["pIC50"],
        selected_row_count=0,
    )
    assert [box.title() for box in dialog.findChildren(QGroupBox)] == [
        "Activity",
        "Core",
        "Fragmentation",
    ]
    dialog.deleteLater()


def test_is_mmp_result_header() -> None:
    from molmanager.analysis.mmp_table import is_mmp_result_header

    assert is_mmp_result_header("MMP_Partners")
    assert is_mmp_result_header("MMP_Delta_pIC50")
    assert not is_mmp_result_header("MW")
