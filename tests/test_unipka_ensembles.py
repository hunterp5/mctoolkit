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

"""FE2pKa thermodynamics and Boltzmann populations (no Uni-pKa weights)."""

from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest
from rdkit import Chem

from molmanager.ionization.unipka_ensembles import (
    LN10,
    UNIPKA_DWAR_PKA_MEAN,
    PicklableIonizationEnsemble,
    _UnipkaTemporaryDirectory,
    _close_unipka_task_lmdb,
    build_ensemble_from_scored,
    calibrate_unipka_free_energy,
    format_isoelectric_point,
    format_pka_and_pi,
    format_pka_values,
    ionization_progress_from_preprocess,
    isoelectric_point_from_states,
    logd74_from_microstates,
    most_acidic_pka_from_states,
    most_basic_pka_from_states,
    pka_from_delta_g,
    populations_from_states,
    predict_ionization_ensemble,
    predict_ionization_ensembles,
    score_microstate_free_energies,
    unique_microstate_progress_thresholds,
    unipka_use_gpu,
)
from molmanager.ionization.unipka_enumerator import (
    enumerate_charge_ensemble,
    flatten_charge_ensemble,
)


def _acetic_ensemble(pka: float = 4.76) -> PicklableIonizationEnsemble:
    ha = Chem.MolFromSmiles("CC(=O)O")
    a = Chem.MolFromSmiles("CC(=O)[O-]")
    assert ha is not None and a is not None
    g_a = LN10 * pka
    return build_ensemble_from_scored(
        [
            (0, "CC(=O)O", ha, 0.0),
            (-1, "CC(=O)[O-]", a, g_a),
        ]
    )


def test_fe2pka_acetic_acid_two_decimals() -> None:
    assert abs(pka_from_delta_g(LN10 * 4.76, 0.0) - 4.76) < 1e-9
    ens = _acetic_ensemble()
    assert len(ens.macro_pkas) == 1
    assert abs(ens.macro_pkas[0] - 4.76) < 0.005
    assert most_acidic_pka_from_states(ens) == pytest.approx(4.76, abs=0.005)
    assert most_basic_pka_from_states(ens) == pytest.approx(4.76, abs=0.005)
    assert format_pka_values(list(ens.macro_pkas)) == "4.76"
    assert format_pka_and_pi(ens) == ("4.76", "N/A")
    assert isoelectric_point_from_states(ens) is None
    assert format_isoelectric_point(None) == "N/A"


def test_isoelectric_point_zwitterion_average_of_flanking_pkas() -> None:
    cat = Chem.MolFromSmiles("C[NH3+]")
    zw = Chem.MolFromSmiles("CN")
    an = Chem.MolFromSmiles("C[NH-]")
    assert cat is not None and zw is not None and an is not None
    pka1, pka2 = 2.34, 9.60
    ens = build_ensemble_from_scored(
        [
            (1, "C[NH3+]", cat, 0.0),
            (0, "CN", zw, LN10 * pka1),
            (-1, "C[NH-]", an, LN10 * (pka1 + pka2)),
        ]
    )
    pi = isoelectric_point_from_states(ens)
    assert pi == pytest.approx(0.5 * (pka1 + pka2), abs=0.02)
    assert format_isoelectric_point(pi) == "5.97"
    assert format_pka_and_pi(ens) == ("2.34; 9.60", "5.97")


def test_unipka_dwar_mean_shift_restores_aqueous_pka() -> None:
    """Raw FE2pKa is mean-centered; charge-linear G shift adds the dwar mean."""
    raw_pka = -1.82
    g_acid_raw = 0.0
    g_base_raw = raw_pka * LN10
    g_acid = calibrate_unipka_free_energy(g_acid_raw, 0)
    g_base = calibrate_unipka_free_energy(g_base_raw, -1)
    assert pka_from_delta_g(g_base, g_acid) == pytest.approx(
        raw_pka + UNIPKA_DWAR_PKA_MEAN, abs=1e-9
    )
    ha = Chem.MolFromSmiles("CC(=O)O")
    a = Chem.MolFromSmiles("CC(=O)[O-]")
    assert ha is not None and a is not None
    ens = build_ensemble_from_scored(
        [
            (0, "CC(=O)O", ha, g_acid),
            (-1, "CC(=O)[O-]", a, g_base),
        ]
    )
    assert ens.macro_pkas[0] == pytest.approx(raw_pka + UNIPKA_DWAR_PKA_MEAN, abs=1e-9)
    high = populations_from_states(ens, 7.4)
    assert Chem.GetFormalCharge(high[0][2]) == -1
    assert high[0][1] > 90.0


def test_unipka_dwar_mean_shift_restores_amine_conjugate_acid_pka() -> None:
    """Aliphatic amines use the BH+/B pair (charge +1 → 0); literature pKa is that of BH+."""
    raw_pka = 4.22
    g_acid_raw = 0.0
    g_base_raw = raw_pka * LN10
    g_acid = calibrate_unipka_free_energy(g_acid_raw, 1)
    g_base = calibrate_unipka_free_energy(g_base_raw, 0)
    assert pka_from_delta_g(g_base, g_acid) == pytest.approx(
        raw_pka + UNIPKA_DWAR_PKA_MEAN, abs=1e-9
    )
    bh = Chem.MolFromSmiles("C[NH2+]C")
    b = Chem.MolFromSmiles("CNC")
    assert bh is not None and b is not None
    ens = build_ensemble_from_scored(
        [
            (1, "C[NH2+]C", bh, g_acid),
            (0, "CNC", b, g_base),
        ]
    )
    assert ens.macro_pkas[0] == pytest.approx(raw_pka + UNIPKA_DWAR_PKA_MEAN, abs=1e-9)


def test_boltzmann_acetic_acid_ph_populations() -> None:
    ens = _acetic_ensemble()
    high = populations_from_states(ens, 7.4)
    low = populations_from_states(ens, 2.0)
    assert Chem.GetFormalCharge(high[0][2]) == -1
    assert high[0][1] > 90.0
    assert Chem.GetFormalCharge(low[0][2]) == 0
    assert low[0][1] > 90.0


def test_logd_uses_neutral_fraction() -> None:
    ens = _acetic_ensemble()
    logd = logd74_from_microstates(ens, clogp=0.0)
    assert logd < -2.0


def test_predict_ensemble_with_fake_scorer_enumerates_acetic() -> None:
    mol = Chem.MolFromSmiles("CC(=O)O")
    assert mol is not None
    ens = predict_ionization_ensemble(mol, score_fn=lambda mols: [0.0] * len(mols))
    assert ens is not None
    charges = {ms.charge for ms in ens.microstates}
    assert 0 in charges
    assert -1 in charges


def test_predict_ensembles_scores_all_microstates_in_one_call() -> None:
    calls: list[int] = []
    ticks: list[tuple[int, int]] = []

    def _score(mols):
        calls.append(len(mols))
        return [0.0] * len(mols)

    mols = [Chem.MolFromSmiles("CC(=O)O"), Chem.MolFromSmiles("Nc1ccccc1")]
    assert all(m is not None for m in mols)
    out = predict_ionization_ensembles(
        mols, score_fn=_score, on_progress=lambda done, total: ticks.append((done, total))
    )
    assert len(out) == 2
    assert all(ens is not None for ens in out)
    assert calls == [sum(len(ens.microstates) for ens in out)]
    assert ticks[-1] == (2, 2)


def test_ionization_progress_from_preprocess_reserves_last_tick() -> None:
    thresholds = [2, 5, 8]
    assert ionization_progress_from_preprocess(0, thresholds, 3) == 0
    assert ionization_progress_from_preprocess(2, thresholds, 3) == 1
    assert ionization_progress_from_preprocess(5, thresholds, 3) == 2
    assert ionization_progress_from_preprocess(8, thresholds, 3) == 2
    assert ionization_progress_from_preprocess(8, thresholds, 3, finished=True) == 3
    assert ionization_progress_from_preprocess(0, [3], 1) == 0
    assert ionization_progress_from_preprocess(3, [3], 1, finished=True) == 1


def test_unique_microstate_progress_thresholds_counts_new_smiles() -> None:
    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    flats = [
        [(0, "CCO", mol), (-1, "CC[O-]", mol)],
        [(0, "CCO", mol), (1, "CC[OH2+]", mol)],
    ]
    assert unique_microstate_progress_thresholds(flats) == [2, 3]


def test_aniline_and_glycine_enumeration_for_spike() -> None:
    for smi, needed in (
        ("Nc1ccccc1", {0, 1}),
        ("NCC(=O)O", {-1, 0, 1}),
    ):
        grouped = enumerate_charge_ensemble(smi)
        charges = {q for q, _s, _m in flatten_charge_ensemble(grouped)}
        assert needed.issubset(charges)


def test_close_unipka_task_lmdb_closes_env() -> None:
    class _Env:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class _Dataset:
        def __init__(self) -> None:
            self.env = _Env()

    class _Task:
        def __init__(self) -> None:
            self.datasets = {"valid": _Dataset()}

    task = _Task()
    env = task.datasets["valid"].env
    _close_unipka_task_lmdb(task)
    assert env.closed is True
    assert task.datasets == {}


def test_pka_gpu_forced_off_env(monkeypatch) -> None:
    from molmanager.ionization.unipka_ensembles import pka_gpu_forced_off

    monkeypatch.delenv("MOLMANAGER_PKA_GPU", raising=False)
    assert pka_gpu_forced_off() is False
    monkeypatch.setenv("MOLMANAGER_PKA_GPU", "0")
    assert pka_gpu_forced_off() is True


def test_unipka_use_gpu_honors_env(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_PKA_GPU", "0")
    monkeypatch.setattr(
        "molmanager.ionization.unipka_ensembles.unipka_cuda_available", lambda: True
    )
    assert unipka_use_gpu() is False
    monkeypatch.setenv("MOLMANAGER_PKA_GPU", "auto")
    assert unipka_use_gpu() is True
    monkeypatch.delenv("MOLMANAGER_PKA_GPU", raising=False)
    monkeypatch.setattr(
        "molmanager.ionization.unipka_ensembles.unipka_cuda_available", lambda: False
    )
    assert unipka_use_gpu() is False


def test_cuda_missing_hint_emits_once(monkeypatch, caplog) -> None:
    monkeypatch.delenv("MOLMANAGER_UNIPKA_GPU_HINT_EMITTED", raising=False)
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.torch_is_cuda_build", lambda: False)
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.unipka_use_gpu", lambda: False)
    monkeypatch.setattr(
        "molmanager.ionization.unipka_ensembles.unipka_cuda_available", lambda: False
    )
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles._nvidia_gpu_present", lambda: True)
    import logging

    from molmanager.ionization.unipka_ensembles import warn_if_cuda_torch_missing

    with caplog.at_level(logging.WARNING, logger="molmanager.ionization.unipka_ensembles"):
        warn_if_cuda_torch_missing()
        warn_if_cuda_torch_missing()
    assert caplog.text.count("NVIDIA GPU detected") == 1
    assert "install_pytorch_pka" in caplog.text


def test_cpu_torch_with_nvidia_gpu(monkeypatch) -> None:
    from molmanager.ionization.unipka_ensembles import cpu_torch_with_nvidia_gpu

    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.torch_is_cuda_build", lambda: True)
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles._nvidia_gpu_present", lambda: True)
    assert cpu_torch_with_nvidia_gpu() is False
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles.torch_is_cuda_build", lambda: False)
    assert cpu_torch_with_nvidia_gpu() is True
    monkeypatch.setattr("molmanager.ionization.unipka_ensembles._nvidia_gpu_present", lambda: False)
    assert cpu_torch_with_nvidia_gpu() is False


def test_cuda_pka_install_hint_points_at_auto_script() -> None:
    from molmanager.ionization.unipka_ensembles import cuda_pka_install_hint

    text = cuda_pka_install_hint()
    assert "install_pytorch_pka.ps1" in text
    assert "install_pytorch_pka.sh" in text
    assert "-Cuda" not in text


def test_unipka_tempdir_cleanup_swallows_permission_error(monkeypatch) -> None:
    import tempfile

    tmp = object.__new__(_UnipkaTemporaryDirectory)

    def _boom(self) -> None:
        raise PermissionError(32, "in use")

    monkeypatch.setattr(tempfile.TemporaryDirectory, "cleanup", _boom)
    tmp.cleanup()


@pytest.mark.skipif(
    importlib.util.find_spec("unipkainfer") is None,
    reason="unipkainfer is not installed",
)
@pytest.mark.slow
def test_unipkainfer_spike_when_weights_present() -> None:
    """Optional live inference: skip unless fold 1 is already on disk (no download in CI)."""
    pytest.importorskip("unipkainfer")
    from unipkainfer.models import DEFAULT_FOLD
    from unipkainfer.paths import default_model_dir

    ckpt = Path(default_model_dir()) / f"fold_{DEFAULT_FOLD}" / "checkpoint_best.pt"
    if not ckpt.is_file():
        pytest.skip("Uni-pKa fold checkpoint is not downloaded")
    from molmanager.ionization.unipka_score_host import shutdown_unipka_score_host

    mol = Chem.MolFromSmiles("CCO")
    assert mol is not None
    try:
        energies = score_microstate_free_energies([mol])
    finally:
        shutdown_unipka_score_host()
    assert len(energies) == 1
    assert math.isfinite(energies[0])


@pytest.mark.skipif(
    importlib.util.find_spec("unipkainfer") is None,
    reason="unipkainfer is not installed",
)
@pytest.mark.slow
def test_live_acetic_and_aniline_pka_in_aqueous_range() -> None:
    """2D SMILES through Uni-pKa should land near experimental aqueous pKas."""
    pytest.importorskip("unipkainfer")
    from unipkainfer.models import DEFAULT_FOLD
    from unipkainfer.paths import default_model_dir

    ckpt = Path(default_model_dir()) / f"fold_{DEFAULT_FOLD}" / "checkpoint_best.pt"
    if not ckpt.is_file():
        pytest.skip("Uni-pKa fold checkpoint is not downloaded")
    from molmanager.ionization.unipka_score_host import shutdown_unipka_score_host

    cases = (
        ("CC(=O)O", 4.76, 2.0),
        ("Nc1ccccc1", 4.60, 2.0),
    )
    try:
        for smi, expected, tol in cases:
            mol = Chem.MolFromSmiles(smi)
            assert mol is not None
            ens = predict_ionization_ensemble(mol)
            assert ens is not None
            assert ens.macro_pkas, smi
            nearest = min(ens.macro_pkas, key=lambda p: abs(p - expected))
            assert abs(nearest - expected) < tol, (smi, ens.macro_pkas)
    finally:
        shutdown_unipka_score_host()
