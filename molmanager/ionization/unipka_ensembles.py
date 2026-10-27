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

"""Uni-pKa ionization ensembles: enumerate, score G, FE2pKa, pH populations.

**Uni-pKa** — Luo, Y.; et al. *Toward Universal Cell Environment pKa Prediction.*
JACS Au 2024, 4, 1721. https://doi.org/10.1021/jacsau.4c00271
Code: https://github.com/dptech-corp/Uni-pKa — runtime: https://pypi.org/project/unipkainfer/

Free energies from ``unipkainfer`` are β-scaled (kT) but the pKa head is trained
on mean-centered Dwar targets (mean 6.50489, std 1). After scoring, G is shifted
by ``−charge · mean · ln(10)`` so FE2pKa and pH Boltzmann weights match the
official ``pKa = (G_base − G_acid) / ln(10) + mean`` denormalization.
"""

from __future__ import annotations

import gc
import logging
import math
import os
import tempfile
from collections import defaultdict
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace

from rdkit import Chem
from rdkit.Chem import rdmolops

from molmanager.ionization.unipka_enumerator import (
    enumerate_charge_ensemble,
    flatten_charge_ensemble,
)
from molmanager.chem.molecule_conversion import mol_to_canonical_smiles

logger = logging.getLogger(__name__)

LN10 = math.log(10.0)
# Uni-pKa ``mol_pka`` / ``unimol_mlm`` task: dwar_8228 full-set mean (std = 1).
UNIPKA_DWAR_PKA_MEAN = 6.504894871171601
INT_FNS_NEED_IONIZATION = frozenset({"LOGD74", "LOGS74", "CNS_MPO", "AB_MPS", "BBB_SCORE"})

UNIPKA_MISSING_MESSAGE = (
    "Could not load Uni-pKa (install the pka extra: pip install 'molmanager[pka]' "
    "or pip install unipkainfer)."
)


@dataclass(frozen=True)
class PicklableIonizationMicrostate:
    """Process-pool-safe microstate: 2D mol blob plus β-scaled free energy."""

    smiles: str
    charge: int
    free_energy: float
    mol_binary: bytes | None


@dataclass(frozen=True)
class PicklableIonizationEnsemble:
    """Picklable ionization ensemble stored in the session microstate cache."""

    microstates: tuple[PicklableIonizationMicrostate, ...]
    macro_pkas: tuple[float, ...]


@dataclass(frozen=True)
class PicklableMicrostate:
    """HA / A− pair snapshot (tests and HH fallback when G is unavailable)."""

    pka: float
    protonated_mol: bytes | None
    deprotonated_mol: bytes | None
    ph7_mol: bytes | None


def _mol_to_binary(mol: Chem.Mol | None) -> bytes | None:
    if mol is None:
        return None
    try:
        return mol.ToBinary()
    except Exception:
        return None


def _mol_from_binary(blob: bytes | None) -> Chem.Mol | None:
    if not blob:
        return None
    try:
        return Chem.Mol(blob)
    except Exception:
        return None


def _strip_mol_props_with_bad_encoding(mol: Chem.Mol) -> None:
    for key in list(mol.GetPropNames()):
        try:
            mol.GetProp(key)
        except UnicodeDecodeError:
            mol.ClearProp(key)


def _mol_props_dict_safe(mol: Chem.Mol) -> None:
    if hasattr(mol, "GetPropsAsDict"):
        mol.GetPropsAsDict()


def prepare_mol_for_ionization(mol: Chem.Mol | None) -> Chem.Mol | None:
    """Drop unreadable SDF tags, then fall back to an isomeric SMILES round-trip."""
    if mol is None or mol.GetNumAtoms() == 0:
        return None
    copy = Chem.Mol(mol)
    _strip_mol_props_with_bad_encoding(copy)
    try:
        _mol_props_dict_safe(copy)
        return copy
    except UnicodeDecodeError:
        pass
    try:
        smi = Chem.MolToSmiles(mol, canonical=True, isomericSmiles=True)
    except Exception:
        return None
    if not smi:
        return None
    return Chem.MolFromSmiles(smi)


def unipka_import_error() -> str | None:
    """Return an install hint if ``unipkainfer`` cannot be imported, else ``None``."""
    try:
        import unipkainfer  # noqa: F401
        from unipkainfer import predict_standard_free_energies  # noqa: F401
    except Exception as exc:
        return f"{UNIPKA_MISSING_MESSAGE} Details: {exc}"
    return None


_WORKER_THREADS_PINNED = False
_UNIPKA_DEVICE_LOGGED = False


def pka_gpu_forced_off() -> bool:
    """True when ``MOLMANAGER_PKA_GPU`` forces CPU (does not initialize CUDA)."""
    raw = (os.environ.get("MOLMANAGER_PKA_GPU") or "").strip().lower()
    return raw in {"0", "false", "no", "off", "cpu"}


def torch_is_cuda_build() -> bool:
    """True when this PyTorch wheel was built with CUDA (does not initialize the runtime)."""
    try:
        import torch

        return bool(getattr(torch, "version", None) and torch.version.cuda)
    except Exception:
        return False


def unipka_cuda_available() -> bool:
    """True when the installed PyTorch can see a CUDA device.

    Initializes the CUDA runtime. Call only from Uni-pKa worker processes, never
    from the GUI process (Windows spawn hangs afterward; WebEngine GL breaks).
    """
    try:
        import torch

        return bool(torch.cuda.is_available())
    except Exception:
        return False


def unipka_use_gpu() -> bool:
    """Whether Uni-pKa inference should run on CUDA (env ``MOLMANAGER_PKA_GPU``)."""
    if pka_gpu_forced_off():
        return False
    raw = (os.environ.get("MOLMANAGER_PKA_GPU") or "").strip().lower()
    cuda = unipka_cuda_available()
    if raw in {"1", "true", "yes", "on", "cuda", "gpu"} and not cuda:
        logger.warning(
            "MOLMANAGER_PKA_GPU requested CUDA but this PyTorch build has no GPU; using CPU"
        )
        return False
    return cuda


def _nvidia_gpu_present() -> bool:
    """Best-effort check for an NVIDIA GPU even when PyTorch is CPU-only."""
    try:
        import shutil
        import subprocess

        exe = shutil.which("nvidia-smi")
        if not exe:
            return False
        from ..platform_support.session_runtime import require_tool

        require_tool(exe, "nvidia-smi")
        proc = subprocess.run(
            [exe, "-L"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        return proc.returncode == 0 and "GPU" in (proc.stdout or "")
    except Exception:
        return False


def cpu_torch_with_nvidia_gpu() -> bool:
    """True when nvidia-smi sees a GPU but this PyTorch wheel has no CUDA."""
    if torch_is_cuda_build():
        return False
    return _nvidia_gpu_present()


def cuda_pka_install_hint() -> str:
    """User-facing steps to swap the CPU PyTorch wheel for CUDA Uni-pKa."""
    return (
        "An NVIDIA GPU was found, but this Python has a CPU-only PyTorch, "
        "so Uni-pKa (Predict pKa, Protonate, LogD) runs on the CPU.\n\n"
        "Close MolManager and, in the same virtual environment, run:\n"
        "  Windows:      .\\scripts\\install_pytorch_pka.ps1\n"
        "  macOS/Linux:  bash scripts/install_pytorch_pka.sh\n\n"
        "Those scripts install the CUDA 12.4 wheel when nvidia-smi sees a GPU "
        "(pass -Cpu / --cpu to keep the CPU wheel). Restart MolManager afterward."
    )


def warn_if_cuda_torch_missing() -> None:
    """Log once if an NVIDIA GPU is present but this PyTorch build cannot use it."""
    if os.environ.get("MOLMANAGER_UNIPKA_GPU_HINT_EMITTED"):
        return
    if not cpu_torch_with_nvidia_gpu():
        return
    os.environ["MOLMANAGER_UNIPKA_GPU_HINT_EMITTED"] = "1"
    logger.warning(
        "NVIDIA GPU detected, but this PyTorch build is CPU-only. "
        "Close MolManager and run scripts\\install_pytorch_pka.ps1 "
        "(or bash scripts/install_pytorch_pka.sh); CUDA is selected automatically."
    )


def _log_unipka_compute_device(use_gpu: bool) -> None:
    """Log CUDA device once per process; CPU is debug to avoid pool-worker spam."""
    global _UNIPKA_DEVICE_LOGGED
    if _UNIPKA_DEVICE_LOGGED:
        return
    _UNIPKA_DEVICE_LOGGED = True
    if use_gpu:
        try:
            import torch

            name = torch.cuda.get_device_name(0)
        except Exception:
            name = "CUDA"
        logger.info("Uni-pKa scoring on GPU (%s)", name)
        return
    logger.debug("Uni-pKa scoring on CPU")
    warn_if_cuda_torch_missing()


def _mmff_threads_for_unipka() -> int:
    """RDKit EmbedMultipleConfs / MMFF threads for Uni-pKa preprocessing."""
    raw = os.environ.get("MOLMANAGER_UNIPKA_MMFF_THREADS")
    if raw:
        try:
            return max(1, min(16, int(raw)))
        except ValueError:
            pass
    cpu = os.cpu_count() or 1
    if cpu <= 2:
        return 1
    return min(4, cpu - 1)


def pin_unipka_torch_threads() -> None:
    """Let the single scoring process use the spare cores.

    Several Uni-pKa processes used to pin this to 1 so they would not oversubscribe.
    Scoring is one process now, so intra-op threads take ``cpu - 1``.
    """
    global _WORKER_THREADS_PINNED
    if _WORKER_THREADS_PINNED:
        return
    _WORKER_THREADS_PINNED = True
    n = max(1, (os.cpu_count() or 2) - 1)
    try:
        import torch

        torch.set_num_threads(n)
    except Exception:
        logger.debug("could not set Uni-pKa torch thread count", exc_info=True)


def pka_from_delta_g(g_base: float, g_acid: float) -> float:
    """FE2pKa: ``pKa = (G_base − G_acid) / ln(10)`` for β-scaled G."""
    return (float(g_base) - float(g_acid)) / LN10


def calibrate_unipka_free_energy(g: float, charge: int) -> float:
    """Undo Uni-pKa's mean-centered pKa training so ΔG/ln(10) is an aqueous pKa.

    The official infer path adds ``dwar_8228`` mean 6.50489 after
    ``(G_base − G_acid) / ln(10)``. Shifting each microstate by
    ``−charge · mean · ln(10)`` is the unique charge-linear correction that
    restores every adjacent-charge pKa and the pH Boltzmann weights.
    """
    return float(g) - float(charge) * UNIPKA_DWAR_PKA_MEAN * LN10


def g_effective(g: float, charge: int, ph: float) -> float:
    """pH-dependent microstate free energy ``G + m ln(10) pH`` (m = formal charge)."""
    return float(g) + float(charge) * LN10 * float(ph)


def ensemble_free_energy(gs: list[float]) -> float:
    """``G_q = −ln Σ exp(−G_i)`` via log-sum-exp."""
    if not gs:
        return float("inf")
    m = min(gs)
    acc = 0.0
    for g in gs:
        acc += math.exp(-(g - m))
    return m - math.log(acc)


def macro_pkas_from_groups(charge_to_gs: dict[int, list[float]]) -> tuple[float, ...]:
    """Macro pKa for each adjacent charge pair ``q ⇌ q−1`` (sorted)."""
    charges = sorted(charge_to_gs)
    pkas: list[float] = []
    g_ens = {q: ensemble_free_energy(gs) for q, gs in charge_to_gs.items() if gs}
    for q in charges:
        if (q - 1) not in g_ens or q not in g_ens:
            continue
        pkas.append(pka_from_delta_g(g_ens[q - 1], g_ens[q]))
    return tuple(sorted(pkas))


def _lse_weights(geffs: list[float]) -> list[float]:
    m = min(geffs)
    raw = [math.exp(-(g - m)) for g in geffs]
    z = sum(raw)
    if z <= 0:
        n = len(raw)
        return [1.0 / n] * n if n else []
    return [w / z for w in raw]


def populations_from_microstates(
    microstates: list[PicklableIonizationMicrostate] | tuple[PicklableIonizationMicrostate, ...],
    ph: float,
) -> list[tuple[str, float, Chem.Mol]]:
    """Boltzmann mole fractions (%) at ``ph`` from scored microstates."""
    usable: list[tuple[PicklableIonizationMicrostate, Chem.Mol]] = []
    for ms in microstates:
        mol = _mol_from_binary(ms.mol_binary)
        if mol is None:
            mol = Chem.MolFromSmiles(ms.smiles)
        if mol is None:
            continue
        usable.append((ms, mol))
    if not usable:
        return []
    geffs = [g_effective(ms.free_energy, ms.charge, ph) for ms, _mol in usable]
    weights = _lse_weights(geffs)
    acc: dict[str, float] = defaultdict(float)
    mols: dict[str, Chem.Mol] = {}
    for (ms, mol), w in zip(usable, weights):
        smi = ms.smiles or mol_to_canonical_smiles(mol)
        if not smi:
            continue
        acc[smi] += w
        mols.setdefault(smi, Chem.Mol(mol))
    out = [(smi, 100.0 * frac, mols[smi]) for smi, frac in acc.items() if smi in mols]
    out.sort(key=lambda t: -t[1])
    return out


def _hh_populations_from_pairs(states, pH: float) -> list[tuple[str, float, Chem.Mol]]:
    """Independent-site HH over HA/A− pairs (unit tests / fallback)."""
    if not states:
        return []
    key_to_mol: dict[str, Chem.Mol] = {}
    acc: defaultdict[str, float] = defaultdict(float)
    for s in states:
        pka = float(s.pka)
        pm = s.protonated_mol
        dm = s.deprotonated_mol
        if isinstance(pm, bytes):
            pm = _mol_from_binary(pm)
        if isinstance(dm, bytes):
            dm = _mol_from_binary(dm)
        if pm is None or dm is None:
            continue
        sp = mol_to_canonical_smiles(pm)
        sd = mol_to_canonical_smiles(dm)
        if not sp or not sd:
            continue
        key_to_mol.setdefault(sp, Chem.Mol(pm))
        key_to_mol.setdefault(sd, Chem.Mol(dm))
        frac_deprot = 1.0 / (1.0 + 10.0 ** (pka - pH))
        frac_prot = 1.0 - frac_deprot
        acc[sp] += frac_prot
        acc[sd] += frac_deprot
    total = sum(acc.values())
    if total <= 0:
        ref = getattr(states[0], "ph7_mol", None)
        if isinstance(ref, bytes):
            ref = _mol_from_binary(ref)
        if ref is None:
            return []
        smi = mol_to_canonical_smiles(ref)
        if not smi:
            return []
        return [(smi, 100.0, Chem.Mol(ref))]
    out = [(k, 100.0 * v / total, key_to_mol[k]) for k, v in acc.items() if k in key_to_mol]
    out.sort(key=lambda t: -t[1])
    return out


def is_ionization_ensemble(states) -> bool:
    return isinstance(states, PicklableIonizationEnsemble)


def pka_values_from_states(states) -> list[float]:
    """Macro pKas from an ensemble, or ``.pka`` from HA/A− pair objects."""
    if states is None:
        return []
    if isinstance(states, PicklableIonizationEnsemble):
        return [float(v) for v in states.macro_pkas]
    if hasattr(states, "macro_pkas"):
        return [float(v) for v in states.macro_pkas]
    out: list[float] = []
    try:
        iterable = list(states)
    except TypeError:
        return []
    for s in iterable:
        if hasattr(s, "pka"):
            try:
                out.append(float(s.pka))
            except (TypeError, ValueError):
                continue
    return out


def format_pka_values(
    values: list[float],
    *,
    most_basic_only: bool = False,
    most_acidic_only: bool = False,
) -> str:
    if not values:
        return "N/A"
    vals = [float(v) for v in values]
    if most_basic_only and most_acidic_only:
        most_acidic_only = False
    if most_basic_only:
        return f"{max(vals):.2f}"
    if most_acidic_only:
        return f"{min(vals):.2f}"
    vals.sort()
    parts = [f"{v:.2f}" for v in vals[:12]]
    tail = " …" if len(vals) > 12 else ""
    return "; ".join(parts) + tail


def _ensemble_microstates(states) -> tuple[PicklableIonizationMicrostate, ...] | None:
    if states is None:
        return None
    if isinstance(states, PicklableIonizationEnsemble):
        return states.microstates
    if states and isinstance(states[0], PicklableIonizationMicrostate):
        return tuple(states)
    return None


def mean_charge_from_states(states, ph: float) -> float | None:
    """Boltzmann-average formal charge at *ph* (Uni-pKa ensembles only)."""
    microstates = _ensemble_microstates(states)
    if not microstates:
        return None
    geffs = [g_effective(ms.free_energy, ms.charge, ph) for ms in microstates]
    weights = _lse_weights(geffs)
    return float(sum(ms.charge * w for ms, w in zip(microstates, weights)))


def isoelectric_point_from_states(
    states, *, ph_lo: float = 0.0, ph_hi: float = 14.0
) -> float | None:
    """pH where mean net charge crosses zero, or ``None`` if it never does.

    Simple acids/bases that stay non-positive or non-negative across 0–14 have
    no isoelectric point. Zwitterions (charge + → −) yield the interpolated pH.
    """
    q_lo = mean_charge_from_states(states, ph_lo)
    q_hi = mean_charge_from_states(states, ph_hi)
    if q_lo is None or q_hi is None:
        return None
    if q_lo * q_hi > 0:
        return None
    if abs(q_lo) < 1e-8 and abs(q_hi) < 1e-8:
        return 0.5 * (float(ph_lo) + float(ph_hi))
    lo, hi = float(ph_lo), float(ph_hi)
    for _ in range(48):
        mid = 0.5 * (lo + hi)
        q_mid = mean_charge_from_states(states, mid)
        if q_mid is None:
            return None
        if abs(q_mid) < 1e-8:
            return mid
        if q_lo * q_mid <= 0:
            hi, q_hi = mid, q_mid
        else:
            lo, q_lo = mid, q_mid
    return 0.5 * (lo + hi)


def format_isoelectric_point(value: float | None) -> str:
    """Two-decimal pI, or ``N/A`` when charge never crosses zero."""
    if value is None:
        return "N/A"
    return f"{float(value):.2f}"


def format_pka_and_pi(
    states,
    *,
    most_basic_only: bool = False,
    most_acidic_only: bool = False,
) -> tuple[str, str]:
    """Table text for the shared ``pKa`` column and optional ``pI`` from one Uni-pKa ensemble."""
    pka_txt = format_pka_values(
        pka_values_from_states(states),
        most_basic_only=most_basic_only,
        most_acidic_only=most_acidic_only,
    )
    try:
        pi_txt = format_isoelectric_point(isoelectric_point_from_states(states))
    except Exception:
        pi_txt = "N/A"
    return pka_txt, pi_txt


class _UnipkaTemporaryDirectory(tempfile.TemporaryDirectory):
    """Windows: unipkainfer keeps the LMDB env open, so default rmtree raises WinError 32."""

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ignore_cleanup_errors", True)
        super().__init__(*args, **kwargs)

    def cleanup(self) -> None:
        try:
            super().cleanup()
        except OSError:
            logger.debug(
                "Uni-pKa temp LMDB still locked: %s",
                getattr(self, "name", ""),
                exc_info=True,
            )


def _close_lmdb_env(obj, *, _seen: set[int] | None = None) -> None:
    """Close nested LMDB environments held by Uni-pKa dataset wrappers."""
    if obj is None:
        return
    seen = set() if _seen is None else _seen
    obj_id = id(obj)
    if obj_id in seen:
        return
    seen.add(obj_id)
    env = getattr(obj, "env", None)
    close = getattr(env, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            logger.debug("could not close Uni-pKa LMDB env", exc_info=True)
        try:
            delattr(obj, "env")
        except Exception:
            pass
    inner = getattr(obj, "dataset", None)
    if inner is not None and inner is not obj:
        _close_lmdb_env(inner, _seen=seen)
    nested = getattr(obj, "datasets", None)
    if isinstance(nested, dict):
        for child in nested.values():
            _close_lmdb_env(child, _seen=seen)
    elif isinstance(nested, (list, tuple)):
        for child in nested:
            _close_lmdb_env(child, _seen=seen)


def _close_unipka_task_lmdb(task) -> None:
    """Drop LMDB file handles so Windows can delete unipkainfer's temp dir."""
    datasets = getattr(task, "datasets", None)
    if isinstance(datasets, dict):
        for child in list(datasets.values()):
            _close_lmdb_env(child)
        datasets.clear()
    else:
        _close_lmdb_env(task)


@contextmanager
def _unipka_windows_lmdb_guards():
    """Close scored LMDBs and ignore Windows file-lock errors on temp-dir teardown."""
    from unipkainfer.pka_predictor import free_energy as fe_mod

    orig_td = fe_mod.tempfile.TemporaryDirectory
    orig_predict = fe_mod._FreeEnergyFoldRunner.predict

    def _predict(self, *args, **kwargs):
        try:
            return orig_predict(self, *args, **kwargs)
        finally:
            _close_unipka_task_lmdb(getattr(self, "task", None))

    fe_mod.tempfile.TemporaryDirectory = _UnipkaTemporaryDirectory
    fe_mod._FreeEnergyFoldRunner.predict = _predict
    try:
        yield
    finally:
        fe_mod._FreeEnergyFoldRunner.predict = orig_predict
        fe_mod.tempfile.TemporaryDirectory = orig_td
        gc.collect()


def _preprocess_worker_count(n_mols: int) -> int:
    """How many RDKit processes should build conformers for one scoring batch."""
    if n_mols < 2 or os.environ.get("MOLMANAGER_UNIPKA_PREPROCESS_CHILD") == "1":
        return 1
    from ..platform_support.config import load_config
    from ..platform_support.worker_budget import rdkit_process_workers

    configured = load_config().pka_process_workers
    if configured is not None and int(configured) <= 1:
        return 1
    workers = rdkit_process_workers(n_mols)
    if configured is not None:
        workers = min(workers, int(configured))
    return workers


def score_microstate_free_energies(mols: list[Chem.Mol]) -> list[float]:
    """Score β-scaled G for each mol.

    Conformers are built with RDKit. The network runs in one torch process,
    which loads a weights-only checkpoint rather than the training file.
    """
    from .unipka_preprocess import records_for_mols
    from .unipka_score_host import score_raw_free_energies

    if not mols:
        return []
    records = records_for_mols(
        mols,
        nthreads=_mmff_threads_for_unipka(),
        parallel_workers=_preprocess_worker_count(len(mols)),
        on_record=note_preprocess_record,
    )
    raw = score_raw_free_energies(list(mols), records)
    calibrated: list[float] = []
    for mol, energy in zip(mols, raw):
        charge = int(rdmolops.GetFormalCharge(mol))
        calibrated.append(calibrate_unipka_free_energy(float(energy), charge))
    return calibrated


def build_ensemble_from_scored(
    rows: list[tuple[int, str, Chem.Mol, float]],
) -> PicklableIonizationEnsemble:
    """Assemble a picklable ensemble from (charge, smiles, mol, G) rows."""
    microstates: list[PicklableIonizationMicrostate] = []
    charge_to_gs: dict[int, list[float]] = defaultdict(list)
    for charge, smi, mol, g in rows:
        microstates.append(
            PicklableIonizationMicrostate(
                smiles=smi,
                charge=int(charge),
                free_energy=float(g),
                mol_binary=_mol_to_binary(mol),
            )
        )
        charge_to_gs[int(charge)].append(float(g))
    return PicklableIonizationEnsemble(
        microstates=tuple(microstates),
        macro_pkas=macro_pkas_from_groups(charge_to_gs),
    )


def _microstate_rows_for_mol(mol: Chem.Mol) -> list[tuple[int, str, Chem.Mol]] | None:
    safe = prepare_mol_for_ionization(mol)
    if safe is None:
        return None
    smi = mol_to_canonical_smiles(safe)
    if not smi:
        return None
    grouped = enumerate_charge_ensemble(smi)
    flat = flatten_charge_ensemble(grouped)
    if not flat:
        flat = [(int(rdmolops.GetFormalCharge(safe)), smi, Chem.Mol(safe))]
    return flat


def unique_microstate_progress_thresholds(
    flats: Sequence[list[tuple[int, str, Chem.Mol]] | None],
) -> list[int]:
    """Cumulative unique microstate-SMILES counts after each parent molecule."""
    seen: set[str] = set()
    thresholds: list[int] = []
    n_unique = 0
    for flat in flats:
        if flat:
            for _charge, smi, _mol in flat:
                key = str(smi)
                if key not in seen:
                    seen.add(key)
                    n_unique += 1
        thresholds.append(n_unique)
    return thresholds


def ionization_progress_from_preprocess(
    n_calls: int,
    thresholds: Sequence[int],
    n_parents: int,
    *,
    finished: bool = False,
) -> int:
    """Map Uni-pKa MMFF/LMDB writes onto parent-molecule ``done`` counts.

    The last tick is reserved until ``finished`` so GPU inference is not shown
    as 100% while the batched free-energy call is still running.
    """
    n = max(0, int(n_parents))
    if n <= 0:
        return 0
    if finished:
        return n
    done = 0
    calls = max(0, int(n_calls))
    for threshold in thresholds:
        if calls >= int(threshold):
            done += 1
        else:
            break
    if n == 1:
        return 0
    return min(done, n - 1)


_PREPROCESS_LISTENERS: list = []


def note_preprocess_record() -> None:
    """Tell progress listeners that one unique microstate conformer set is ready."""
    for fn in list(_PREPROCESS_LISTENERS):
        try:
            fn()
        except Exception:
            logger.debug("Uni-pKa preprocess progress callback failed", exc_info=True)


def _notify_ionization_progress(on_progress, done: int, total: int) -> None:
    if on_progress is None:
        return
    try:
        on_progress(int(done), int(total))
    except Exception:
        logger.debug("ionization progress callback failed", exc_info=True)


@contextmanager
def _unipka_preprocess_progress(on_record: Callable[[], None] | None):
    """Call *on_record* after each unique microstate conformer set is built."""
    if on_record is None:
        yield
        return
    _PREPROCESS_LISTENERS.append(on_record)
    try:
        yield
    finally:
        try:
            _PREPROCESS_LISTENERS.remove(on_record)
        except ValueError:
            pass


def _ensembles_from_flats(
    flats: list[list[tuple[int, str, Chem.Mol]] | None],
    energies: list[float],
) -> list[PicklableIonizationEnsemble | None]:
    offset = 0
    out: list[PicklableIonizationEnsemble | None] = []
    for flat in flats:
        if not flat:
            out.append(None)
            continue
        n = len(flat)
        scored = [(c, s, m, float(energies[offset + i])) for i, (c, s, m) in enumerate(flat)]
        offset += n
        out.append(build_ensemble_from_scored(scored))
    return out


def predict_ionization_ensembles(
    mols: list[Chem.Mol],
    *,
    score_fn=None,
    on_progress=None,
) -> list[PicklableIonizationEnsemble | None]:
    """Enumerate and score many structures in one Uni-pKa free-energy call.

    ``on_progress(done, total)`` is optional status only: scoring stays one
    batched ``score_fn`` call. With the default scorer, ticks follow Uni-pKa
    MMFF/LMDB writes so a small job is not stuck at 0% until inference returns.
    """
    n = len(mols)
    flats = [_microstate_rows_for_mol(mol) for mol in mols]
    all_mols = [row[2] for flat in flats if flat for row in flat]
    if not all_mols:
        _notify_ionization_progress(on_progress, n, n)
        return [None] * n
    scorer = score_fn if score_fn is not None else score_microstate_free_energies
    thresholds = unique_microstate_progress_thresholds(flats)
    n_calls = 0

    def _tick(*, finished: bool = False) -> None:
        _notify_ionization_progress(
            on_progress,
            ionization_progress_from_preprocess(n_calls, thresholds, n, finished=finished),
            n,
        )

    def _on_record() -> None:
        nonlocal n_calls
        n_calls += 1
        _tick()

    def _score_all(target_mols: list[Chem.Mol]) -> list[float]:
        if on_progress is None or score_fn is not None:
            return scorer(target_mols)
        _tick()
        with _unipka_preprocess_progress(_on_record):
            return scorer(target_mols)

    try:
        energies = _score_all(all_mols)
        if len(energies) != len(all_mols):
            raise ValueError("score_fn must return one free energy per microstate")
        out = _ensembles_from_flats(flats, energies)
        _notify_ionization_progress(on_progress, n, n)
        return out
    except Exception:
        if len(mols) == 1:
            raise
        logger.debug("batched Uni-pKa scoring failed; retrying per molecule", exc_info=True)
        out: list[PicklableIonizationEnsemble | None] = []
        for i, (_mol, flat) in enumerate(zip(mols, flats), start=1):
            if not flat:
                out.append(None)
                _notify_ionization_progress(on_progress, min(i, n), n)
                continue
            try:
                chunk_e = scorer([row[2] for row in flat])
                if len(chunk_e) != len(flat):
                    raise ValueError("score_fn must return one free energy per microstate")
                out.extend(_ensembles_from_flats([flat], chunk_e))
            except Exception:
                logger.debug("Uni-pKa scoring failed for one structure", exc_info=True)
                out.append(None)
            _notify_ionization_progress(on_progress, min(i, n), n)
        return out


def predict_ionization_ensemble(
    mol: Chem.Mol,
    *,
    score_fn=None,
) -> PicklableIonizationEnsemble | None:
    """Enumerate microstates, score G, and return a picklable ensemble."""
    results = predict_ionization_ensembles([mol], score_fn=score_fn)
    return results[0] if results else None


def microstates_to_picklable(states: list) -> list | PicklableIonizationEnsemble:
    """Convert live objects to IPC-safe snapshots."""
    if isinstance(states, PicklableIonizationEnsemble):
        return states
    if states and isinstance(states[0], PicklableIonizationMicrostate):
        gs: dict[int, list[float]] = defaultdict(list)
        for s in states:
            gs[int(s.charge)].append(float(s.free_energy))
        return PicklableIonizationEnsemble(tuple(states), macro_pkas_from_groups(gs))
    out: list[PicklableMicrostate] = []
    for s in states:
        out.append(
            PicklableMicrostate(
                pka=float(s.pka),
                protonated_mol=_mol_to_binary(s.protonated_mol),
                deprotonated_mol=_mol_to_binary(s.deprotonated_mol),
                ph7_mol=_mol_to_binary(getattr(s, "ph7_mol", None)),
            )
        )
    return out


def hydrate_microstates(states: list):
    """Restore RDKit mols on HA/A− snapshots; ensembles are returned as-is."""
    if not states:
        return []
    if isinstance(states, PicklableIonizationEnsemble):
        return states
    if isinstance(states[0], PicklableIonizationEnsemble):
        return states[0]
    if isinstance(states[0], PicklableMicrostate):
        return [
            SimpleNamespace(
                pka=s.pka,
                protonated_mol=_mol_from_binary(s.protonated_mol),
                deprotonated_mol=_mol_from_binary(s.deprotonated_mol),
                ph7_mol=_mol_from_binary(s.ph7_mol),
            )
            for s in states
        ]
    return states


def int_fns_need_ionization(int_fns) -> bool:
    return any(isinstance(f, str) and f in INT_FNS_NEED_IONIZATION for f in int_fns)


def microstates_for_mol(mol: Chem.Mol) -> PicklableIonizationEnsemble | list | None:
    """Return a cached ionization ensemble, computing it if needed."""
    from molmanager.ionization.microstate_cache import lookup as cache_lookup
    from molmanager.ionization.microstate_cache import store as cache_store
    from molmanager.services.structure_grouping import structure_key

    key = structure_key(mol)
    hit, cached = cache_lookup(key)
    if hit:
        return cached
    if unipka_import_error() is not None:
        cache_store(key, None)
        return None
    try:
        ensemble = predict_ionization_ensemble(mol)
    except Exception:
        logger.debug("Uni-pKa ionization ensemble failed", exc_info=True)
        cache_store(key, None)
        return None
    cache_store(key, ensemble)
    return ensemble


def most_basic_pka_from_states(states) -> float | None:
    vals = pka_values_from_states(states)
    if not vals:
        return None
    return max(vals)


def most_acidic_pka_from_states(states) -> float | None:
    vals = pka_values_from_states(states)
    if not vals:
        return None
    return min(vals)


def populations_from_states(states, ph: float) -> list[tuple[str, float, Chem.Mol]]:
    """Protomer populations at ``ph`` (Boltzmann for Uni-pKa; HH for HA/A− pairs)."""
    if states is None:
        return []
    if isinstance(states, PicklableIonizationEnsemble):
        return populations_from_microstates(states.microstates, ph)
    if states and isinstance(states[0], PicklableIonizationMicrostate):
        return populations_from_microstates(states, ph)
    return _hh_populations_from_pairs(hydrate_microstates(states), ph)


def neutral_fraction_from_states(states, ph: float = 7.4) -> float:
    """Mole fraction of net-neutral protomer states at ``ph`` (0–1)."""
    pops = populations_from_states(states, ph)
    if not pops:
        return 1e-15
    neutral = 0.0
    for _smi, pct, m in pops:
        if m is not None and rdmolops.GetFormalCharge(m) == 0:
            neutral += pct
    return max(neutral / 100.0, 1e-15)


def logd74_from_microstates(states, clogp: float) -> float:
    """log D = log P + log10(f_neutral) with Uni-pKa (or HH) f_neutral at pH 7.4."""
    return clogp + math.log10(neutral_fraction_from_states(states, 7.4))


def logs74_from_microstates(states, log_s_intrinsic: float) -> float:
    """log S_aq ≈ log S_intrinsic − log10(f_neutral) at pH 7.4."""
    return log_s_intrinsic - math.log10(neutral_fraction_from_states(states, 7.4))
