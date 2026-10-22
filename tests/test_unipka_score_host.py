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

"""Uni-pKa scoring uses one weights-only model and RDKit conformers."""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest
from rdkit import Chem

from molmanager.ionization.unipka_ensembles import note_preprocess_record
from molmanager.ionization.unipka_preprocess import record_for_smiles, records_for_mols


def test_preprocess_progress_listener_fires_per_unique_smiles() -> None:
    from molmanager.ionization import unipka_ensembles as ensembles

    seen: list[int] = []
    ensembles._PREPROCESS_LISTENERS.append(lambda: seen.append(1))
    try:
        note_preprocess_record()
        note_preprocess_record()
    finally:
        ensembles._PREPROCESS_LISTENERS.clear()
    assert seen == [1, 1]


def test_score_does_not_probe_cuda_in_the_caller(monkeypatch) -> None:
    def _boom() -> bool:
        raise AssertionError("caller probed CUDA")

    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.unipka_use_gpu", _boom)
    monkeypatch.setattr(
        "molmanager.ionization.unipka_score_host.score_raw_free_energies",
        lambda mols, _records: [1.5] * len(mols),
    )
    from molmanager.ionization.unipka_ensembles import score_microstate_free_energies

    mol = Chem.MolFromSmiles("C")
    assert mol is not None
    energies = score_microstate_free_energies([mol])
    assert len(energies) == 1
    assert np.isfinite(energies[0])


@pytest.mark.skipif(importlib.util.find_spec("torch") is None, reason="torch is not installed")
def test_weights_checkpoint_drops_optimizer_state(tmp_path) -> None:
    import torch

    from molmanager.ionization.unipka_score_host import (
        ensure_weights_checkpoint,
        load_weights_state_dict,
    )

    source = tmp_path / "checkpoint_best.pt"
    torch.save(
        {
            "model": {"layer.weight": torch.ones(2, 2)},
            "optimizer": {"state": torch.zeros(64)},
        },
        source,
    )
    before = source.stat().st_size
    weights = ensure_weights_checkpoint(source)
    assert weights.name == "checkpoint_best.weights.pt"
    assert source.stat().st_size == before
    loaded = load_weights_state_dict(source)
    assert set(loaded) == {"layer.weight"}
    assert torch.equal(loaded["layer.weight"], torch.ones(2, 2))
    assert "optimizer" not in loaded


@pytest.mark.skipif(
    importlib.util.find_spec("unipkainfer") is None,
    reason="unipkainfer is not installed",
)
@pytest.mark.slow
def test_preprocess_record_matches_unipkainfer() -> None:
    pytest.importorskip("unipkainfer")
    from unipkainfer import UnipkaFreeEnergyConfig
    from unipkainfer.pka_predictor.free_energy import _smiles_to_free_energy_record

    smi = "CCO"
    ours = record_for_smiles(smi, nthreads=1)
    ref = _smiles_to_free_energy_record(smi, UnipkaFreeEnergyConfig(nthreads=1, gpu=False))
    assert ours["atoms"] == ref["atoms"]
    assert ours["charges"] == ref["charges"]
    assert ours["smi"] == ref["smi"] == smi
    assert ours["scaffold"] == ref["scaffold"]
    assert len(ours["coordinates"]) == len(ref["coordinates"]) == 11
    for left, right in zip(ours["coordinates"], ref["coordinates"]):
        np.testing.assert_allclose(left, right)
    mol = Chem.MolFromSmiles(smi)
    assert mol is not None
    built = records_for_mols([mol], nthreads=1, parallel_workers=1)
    assert set(built) == {smi}
