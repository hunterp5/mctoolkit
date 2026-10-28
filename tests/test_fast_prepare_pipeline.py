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

"""Fast Prepare end-to-end: one fused job writes the neutralized parent and the fragments column."""

from __future__ import annotations

from rdkit import Chem

from molmanager.ui.main_window import ChemistryWorkspaceWindow
from molmanager.chem.molecule_conversion import mol_to_canonical_smiles
from molmanager.workers.fast_prepare import FastPrepareParams, FastPrepareWorker

SALTS = [
    "CC(=O)Oc1ccccc1C(=O)[O-].[Na+]",
    "C[NH+](C)C.[Cl-]",
    "c1ccccc1",
]


def _seeded_window() -> ChemistryWorkspaceWindow:
    win = ChemistryWorkspaceWindow()
    win.headers = ["ID_HIDDEN", "Structure", "SMILES"]
    win._table_model.set_headers(list(win.headers))
    win.table.setColumnHidden(0, True)
    for smiles in SALTS:
        mol = Chem.MolFromSmiles(smiles)
        assert mol is not None
        oid = win.next_oid
        win.next_oid += 1
        cells = win._ingest_store_mol(oid, mol)
        cells["SMILES"] = smiles
        win._table_model.append_row(oid, cells)
    return win


def _run_fast_prepare_inline(
    win: ChemistryWorkspaceWindow, src: str, *, neutralize: bool = False, want_scene: bool = False
) -> None:
    """Run the worker synchronously on the real collected items, then the real GUI handler."""
    items = win._collect_fast_prepare_items(src, None)
    captured: list = []

    class _Sig:
        def __init__(self, sink):
            self._sink = sink

        def emit(self, *args):
            self._sink(*args)

    class _Recorder:
        fast_prepared = _Sig(captured.append)
        fast_prepared_batch = _Sig(lambda rows, is_last: win.on_fast_prepare_batch(rows, is_last))
        tool_progress = _Sig(lambda *_a: None)
        partial_results = _Sig(lambda *_a: None)

    FastPrepareWorker(
        items,
        FastPrepareParams(
            is_smiles=src != "Structure",
            need_smiles=True,
            neutralize=neutralize,
            process_pool_min_rows=10**9,
            want_scene=want_scene,
        ),
        _Recorder(),
    ).run()
    if want_scene:
        return
    assert captured, "worker emitted no results"
    win.on_fast_prepare_finished(captured[0])


def test_prepare_items_carry_the_stored_orientation(qapp):  # noqa: ARG001
    from molmanager.chem.depiction_coords import pack_xy

    win = _seeded_window()
    try:
        oid = next(iter(win.mols))
        xy = pack_xy([(0.0, float(i)) for i in range(4)])
        win._depiction_coords.set("Structure", oid, xy)
        items = win._collect_fast_prepare_items("Structure", None)
        found = [item for item in items if int(item[0]) == int(oid)]
        assert found
        assert found[0][3] == xy
    finally:
        win.close()


def test_fast_prepare_structure_target_neutralizes_and_lists_fragments(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        win._fast_prepare_source = "Structure"
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = True
        win._fast_prepare_allowed_oids = None

        _run_fast_prepare_inline(win, "Structure", neutralize=True)

        assert "Fragments" in win.headers
        assert len(win.mols) == len(SALTS)
        for mol in win.mols.values():
            assert Chem.GetFormalCharge(mol) == 0
            assert len(Chem.GetMolFrags(mol)) == 1

        frag_col = win.headers.index("Fragments")
        frag_values = {
            win._table_cell_text(win.logical_row_for_oid(oid), frag_col) for oid in win.mols
        }
        assert mol_to_canonical_smiles(Chem.MolFromSmiles("[Cl-]")) in frag_values
        assert "" in frag_values  # benzene has no smaller fragments
    finally:
        win.close()


def test_fast_prepare_new_column_target_gets_canonical_smiles(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        target = "Largest fragment SMILES"
        win._fast_prepare_source = target
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = False
        win._fast_prepare_allowed_oids = None

        # A column the dialog named but that does not exist yet must still count as a text target,
        # otherwise the worker would skip canonical SMILES and the column would be written empty.
        assert win._fast_prepare_target_is_text(target) is True

        _run_fast_prepare_inline(win, "Structure", neutralize=True)

        assert target in win.headers
        col = win.headers.index(target)
        values = [
            win._table_cell_text(win.logical_row_for_oid(oid), col)
            for oid in win._all_oids_in_table_order()
        ]
        assert all(v for v in values), f"expected SMILES in every row, got {values}"
        for v in values:
            parsed = Chem.MolFromSmiles(v)
            assert parsed is not None
            assert Chem.GetFormalCharge(parsed) == 0
            assert len(Chem.GetMolFrags(parsed)) == 1
    finally:
        win.close()


def test_fast_prepare_does_not_hydrate_molecules_on_gui_thread(qapp, monkeypatch):  # noqa: ARG001
    from molmanager.storage.mol_store import MolStore

    win = _seeded_window()
    try:
        win._fast_prepare_source = "Structure"
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = True
        win._fast_prepare_allowed_oids = None
        win.mols._lru.clear()

        def _no_hydrate(self, key):
            raise AssertionError(f"GUI thread hydrated mol {key}")

        monkeypatch.setattr(MolStore, "__getitem__", _no_hydrate)
        monkeypatch.setattr(MolStore, "__setitem__", _no_hydrate)
        monkeypatch.setattr(win, "_start_render_2d_batch", lambda *_a, **_k: None)
        _run_fast_prepare_inline(win, "Structure", neutralize=True)
        renders, _ = win._build_render2d_tasks_in_table_order("Structure", 80, 80, None)
        assert len(renders) == len(SALTS)
    finally:
        monkeypatch.undo()
        win.close()


def test_fast_prepare_pixmap_column_target_keeps_structure(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        win.headers.append("Prepared")
        win._table_model.set_headers(list(win.headers))
        win._table_model.register_pixmap_column("Prepared")
        oids = win._all_oids_in_table_order()
        win._table_model.set_column_backing_text_by_oids(
            "Prepared", [(oid, smi) for oid, smi in zip(oids, SALTS)]
        )
        before = {oid: Chem.MolToSmiles(win.mols[oid]) for oid in oids}
        win._fast_prepare_source = "Prepared"
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = True
        win._fast_prepare_allowed_oids = None

        _run_fast_prepare_inline(win, "Prepared", neutralize=True)

        assert {oid: Chem.MolToSmiles(win.mols[oid]) for oid in oids} == before
        for oid in oids:
            text = win._table_model.backing_value_for_row_header(
                win.logical_row_for_oid(oid), "Prepared"
            )
            parsed = Chem.MolFromSmiles(text)
            assert parsed is not None
            assert len(Chem.GetMolFrags(parsed)) == 1
    finally:
        win.close()


def test_fast_prepare_structure_scenes_skip_the_second_render(qapp):  # noqa: ARG001
    from molmanager.chem.depiction_builder import build_scene
    from molmanager.chem.depiction_coords import apply_depiction_coords
    from molmanager.chem.depiction_layout import current_layout_options
    from molmanager.chem.depiction_scene import is_scene_blob, pack_scene

    win = _seeded_window()
    started: list = []
    try:
        win._fast_prepare_source = "Structure"
        win._fast_prepare_fragments_col = "Fragments"
        win._fast_prepare_update_target = True
        win._fast_prepare_allowed_oids = None
        win._start_render_2d_batch = lambda *args, **kwargs: started.append(args)

        _run_fast_prepare_inline(win, "Structure", neutralize=True, want_scene=True)

        assert started == []
        if win._render2d_batch_active:
            assert win._render2d_pixmap_target == "Fragments"
        store = win._table_model._structure_png_store
        assert store is not None and len(store) == len(SALTS)
        options = current_layout_options()
        for oid in win._all_oids_in_table_order():
            raw = store.png_bytes(oid)
            assert is_scene_blob(raw)
            xy = win._depiction_coords.get("Structure", oid)
            assert xy
            laid = apply_depiction_coords(win.mols[oid], xy)
            scene, reason = build_scene(laid, options)
            assert reason is None
            assert pack_scene(scene) == raw
    finally:
        win.close()


def test_fast_prepare_structure_target_is_not_text(qapp):  # noqa: ARG001
    win = _seeded_window()
    try:
        assert win._fast_prepare_target_is_text("Structure") is False
        assert win._fast_prepare_target_is_text("SMILES") is True
    finally:
        win.close()
