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

"""Fast Prepare worker: fused disconnect + neutralize equivalence, payloads, and cancellation."""

from __future__ import annotations

import threading

import pytest
from rdkit import Chem

from molmanager.chem.fragment_disconnect import largest_fragment_and_rest
from molmanager.chem.structure_neutralize import neutralize_mol
from molmanager.chem.molecule_conversion import mol_to_canonical_smiles
from molmanager.workers.fast_prepare import (
    FastPrepareParams,
    FastPrepareWorker,
    _mp_fast_prepare_batch,
    _prepare_one,
)

# Salts / charged species so both pipeline stages actually do work.
SAMPLE_SMILES = [
    "CC(=O)Oc1ccccc1C(=O)[O-].[Na+]",
    "C[NH+](C)C.[Cl-]",
    "OC(=O)c1ccccc1",
    "CCCCCCCCCCCC.Cc1ccc(S(=O)(=O)[O-])cc1.Cc1ccc(S(=O)(=O)[O-])cc1",
    "c1ccccc1",
    "[NH4+].[O-]C(=O)C",
]


def _old_pipeline(mol, source_text=None):
    """The previous two-job behavior: disconnect, then neutralize the parent."""
    parent, fragments = largest_fragment_and_rest(mol, source_text)
    if parent is None:
        return None
    neutral = neutralize_mol(parent) or parent
    return mol_to_canonical_smiles(neutral), fragments


@pytest.mark.parametrize("smiles", SAMPLE_SMILES)
def test_prepare_one_matches_old_two_stage_pipeline(smiles: str) -> None:
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    expected = _old_pipeline(mol, smiles)
    got = _prepare_one(mol.ToBinary(), smiles, is_text=False, need_smiles=True, neutralize=True)
    assert (expected is None) == (got is None)
    if expected is None:
        return
    exp_smiles, exp_fragments = expected
    blob, fragments, canonical = got
    assert fragments == exp_fragments
    assert canonical == exp_smiles
    assert mol_to_canonical_smiles(Chem.Mol(blob)) == exp_smiles


def test_prepare_one_from_cell_text_matches_mol_input() -> None:
    smiles = "CC(=O)Oc1ccccc1C(=O)[O-].[Na+]"
    from_text = _prepare_one(smiles, None, is_text=True, need_smiles=True, neutralize=True)
    mol = Chem.MolFromSmiles(smiles)
    from_mol = _prepare_one(
        mol.ToBinary(), smiles, is_text=False, need_smiles=True, neutralize=True
    )
    assert from_text is not None and from_mol is not None
    assert from_text[1:] == from_mol[1:]


def test_prepare_one_neutralizes_charge() -> None:
    res = _prepare_one("C[NH+](C)C.[Cl-]", None, is_text=True, need_smiles=True, neutralize=True)
    assert res is not None
    out = Chem.Mol(res[0])
    assert Chem.GetFormalCharge(out) == 0
    assert res[1] == mol_to_canonical_smiles(Chem.MolFromSmiles("[Cl-]"))


def test_prepare_one_skips_neutralize_when_disabled() -> None:
    res = _prepare_one("C[NH+](C)C.[Cl-]", None, is_text=True, need_smiles=True, neutralize=False)
    assert res is not None
    out = Chem.Mol(res[0])
    assert Chem.GetFormalCharge(out) == 1
    assert res[1] == mol_to_canonical_smiles(Chem.MolFromSmiles("[Cl-]"))


def test_prepare_one_skips_unparsable_row() -> None:
    assert _prepare_one("not a molecule", None, is_text=True, need_smiles=True) is None
    assert _prepare_one(b"", None, is_text=False, need_smiles=True) is None


def test_need_smiles_false_skips_canonical_smiles() -> None:
    res = _prepare_one("C[NH+](C)C.[Cl-]", None, is_text=True, need_smiles=False)
    assert res is not None
    assert res[2] == ""


def test_batch_helper_preserves_oids_and_drops_failures() -> None:
    items = [
        (7, "C[NH+](C)C.[Cl-]", None),
        (8, "still not a molecule", None),
        (9, "c1ccccc1", None),
    ]
    rows = _mp_fast_prepare_batch((items, True, True, True))
    assert [r[0] for r in rows] == [7, 9]


class _Recorder:
    """Minimal stand-in for ``WorkerSignals`` (no Qt event loop needed)."""

    def __init__(self) -> None:
        self.results: list | None = None
        self.progress: list[tuple[str, int, int]] = []
        self.partial: list[tuple[str, int, int]] = []
        outer = self

        class _Sig:
            def __init__(self, sink):
                self._sink = sink

            def emit(self, *args):
                self._sink(outer, *args)

        self.fast_prepared = _Sig(lambda o, res: setattr(o, "results", list(res)))
        self.tool_progress = _Sig(lambda o, m, d, t: o.progress.append((m, d, t)))
        self.partial_results = _Sig(lambda o, m, d, t: o.partial.append((m, d, t)))


def _worker_rows(items, **kwargs):
    sig = _Recorder()
    # Stay in-process: spawning child processes inside the test suite is slow and unnecessary
    # for verifying payload shape, since both paths share ``_mp_fast_prepare_batch``.
    kwargs.setdefault("process_pool_min_rows", 10**9)
    worker = FastPrepareWorker(items, FastPrepareParams(**kwargs), sig)
    worker.run()
    return sig, worker


def test_worker_emits_blobs_not_live_mols() -> None:
    mols = [Chem.MolFromSmiles(s) for s in SAMPLE_SMILES]
    items = [(i, m, s) for i, (m, s) in enumerate(zip(mols, SAMPLE_SMILES))]
    sig, _ = _worker_rows(items, need_smiles=True)
    assert sig.results
    for oid, blob, fragments, canonical in sig.results:
        assert isinstance(oid, int)
        assert isinstance(blob, bytes)
        assert isinstance(fragments, str)
        assert Chem.Mol(blob) is not None
        assert canonical == mol_to_canonical_smiles(Chem.Mol(blob))


def test_worker_text_mode_reads_cell_text() -> None:
    items = [(1, "C[NH+](C)C.[Cl-]"), (2, "c1ccccc1")]
    sig, _ = _worker_rows(items, is_smiles=True, need_smiles=True, neutralize=True)
    assert [r[0] for r in sig.results] == [1, 2]
    assert Chem.GetFormalCharge(Chem.Mol(sig.results[0][1])) == 0


def test_worker_reports_progress_and_empty_input() -> None:
    sig, _ = _worker_rows([])
    assert sig.results == []

    items = [(i, s) for i, s in enumerate(SAMPLE_SMILES)]
    sig, _ = _worker_rows(items, is_smiles=True, batch_size=2)
    assert sig.progress
    assert sig.progress[-1][2] == len(items)


def test_prepare_one_scene_matches_a_rebuild_from_the_stored_coordinates() -> None:
    from molmanager.chem.depiction_builder import build_scene
    from molmanager.chem.depiction_coords import apply_depiction_coords
    from molmanager.chem.depiction_layout import current_layout_options
    from molmanager.chem.depiction_scene import is_scene_blob, pack_scene

    options = current_layout_options()
    for smiles in ("c1ccccc1", "CC(=O)Oc1ccccc1C(=O)[O-].[Na+]"):
        res = _prepare_one(smiles, None, is_text=True, need_smiles=True, want_scene=True)
        assert res is not None
        blob, _fragments, _canonical, scene, xy = res
        assert xy and is_scene_blob(scene)
        laid = apply_depiction_coords(Chem.Mol(blob), xy)
        rebuilt, reason = build_scene(laid, options)
        assert reason is None
        assert pack_scene(rebuilt) == scene


def test_prepare_one_radical_keeps_the_blob_without_a_scene() -> None:
    mol = Chem.MolFromSmiles("[CH3]")
    assert mol is not None and mol.GetAtomWithIdx(0).GetNumRadicalElectrons() > 0
    res = _prepare_one(mol.ToBinary(), "[CH3]", is_text=False, need_smiles=True, want_scene=True)
    assert res is not None
    blob, _fragments, _canonical, scene, _xy = res
    assert blob and scene == b""
    assert Chem.Mol(blob) is not None


def test_worker_streams_scene_batches() -> None:
    sig = _Recorder()
    sig.batches = []
    sig.fast_prepared_batch = sig.fast_prepared.__class__(
        lambda o, rows, is_last: o.batches.append((list(rows), is_last))
    )
    items = [(i, smiles) for i, smiles in enumerate(("c1ccccc1", "CCO", "CCN", "CCC"))]
    FastPrepareWorker(
        items,
        FastPrepareParams(
            is_smiles=True, want_scene=True, batch_size=2, process_pool_min_rows=10**9
        ),
        sig,
    ).run()
    assert sig.results is None
    assert sig.batches[-1] == ([], True)
    rows = [row for batch, is_last in sig.batches if not is_last for row in batch]
    assert [row[0] for row in rows] == [0, 1, 2, 3]
    assert all(len(row) == 6 and row[4] for row in rows)


def test_worker_cancellation_emits_partial_results() -> None:
    ev = threading.Event()
    ev.set()
    sig = _Recorder()
    items = [(i, s) for i, s in enumerate(SAMPLE_SMILES)]
    FastPrepareWorker(
        items,
        FastPrepareParams(is_smiles=True, process_pool_min_rows=10**9, batch_size=2),
        sig,
        cancel_event=ev,
    ).run()
    assert sig.results == []
    assert sig.partial and sig.partial[0][0] == "Fast prepare"
