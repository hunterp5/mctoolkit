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

"""One Uni-pKa process. It loads model weights, not the training checkpoint.

RDKit conformers are built elsewhere and passed in. The original
``checkpoint_best.pt`` is left in place (its hash is checked by unipkainfer);
a sibling ``*.weights.pt`` holds only the state dict.
"""

from __future__ import annotations

import atexit
import gc
import logging
import multiprocessing
import os
import threading
from pathlib import Path

from rdkit.Chem.rdchem import Mol

from ..workers.process_pool_utils import (
    register_process_pool,
    shutdown_process_pool_executor,
)

logger = logging.getLogger(__name__)

_HOST_LOCK = threading.Lock()
_HOST = None
_WEIGHTS_PATCHED = False


def weights_checkpoint_path(source: Path) -> Path:
    """Sibling file that stores only the model state dict."""
    return Path(source).with_name(f"{Path(source).stem}.weights.pt")


def ensure_weights_checkpoint(source: Path) -> Path:
    """Write a weights-only copy of *source* when it is missing or older.

    The first call still reads the full training checkpoint (optimizer state and
    all). Later loads use the smaller file.
    """
    import torch

    src = Path(source)
    dest = weights_checkpoint_path(src)
    if dest.is_file() and dest.stat().st_mtime >= src.stat().st_mtime and dest.stat().st_size > 0:
        return dest
    state = torch.load(src, map_location="cpu", weights_only=False)
    model = state.get("model") if isinstance(state, dict) else None
    if not isinstance(model, dict):
        raise ValueError(f"Uni-pKa checkpoint {src} has no model state dict.")
    tmp = dest.with_suffix(".pt.tmp")
    torch.save(model, tmp)
    tmp.replace(dest)
    del state, model
    gc.collect()
    return dest


def load_weights_state_dict(source: Path) -> dict:
    """Load model weights, memory-mapping the stripped file when torch allows it."""
    import torch

    weights = ensure_weights_checkpoint(source)
    try:
        state = torch.load(weights, map_location="cpu", weights_only=True, mmap=True)
    except (TypeError, ValueError, RuntimeError):
        state = torch.load(weights, map_location="cpu", weights_only=True)
    if not isinstance(state, dict):
        raise ValueError(f"Uni-pKa weights file {weights} did not contain a state dict.")
    return state


def install_weights_only_loader() -> None:
    """Make unipkainfer's checkpoint read use the stripped weights file."""
    global _WEIGHTS_PATCHED
    if _WEIGHTS_PATCHED:
        return
    from unipkainfer.unicoreinfer import checkpoint_utils

    def _load(path, arg_overrides=None, load_on_all_ranks=True):
        del arg_overrides, load_on_all_ranks
        return {"model": load_weights_state_dict(Path(path))}

    checkpoint_utils.load_checkpoint_to_cpu = _load
    _WEIGHTS_PATCHED = True


def configure_score_threads() -> None:
    """Use the cores of this single process for inference."""
    n = max(1, (os.cpu_count() or 2) - 1)
    try:
        import torch

        torch.set_num_threads(n)
    except (ImportError, RuntimeError, OSError):
        logger.debug("could not set Uni-pKa torch threads", exc_info=True)


def _score_in_process(
    mols: list[Mol],
    records_by_smi: dict[str, dict],
) -> list[float]:
    """Raw (uncalibrated) standard free energy, one per molecule, in order."""
    install_weights_only_loader()
    configure_score_threads()
    from unipkainfer import UnipkaFreeEnergyConfig, predict_standard_free_energies
    from unipkainfer.pka_predictor import free_energy as fe_mod

    from .unipka_ensembles import (
        _log_unipka_compute_device,
        _unipka_windows_lmdb_guards,
        unipka_use_gpu,
    )

    use_gpu = unipka_use_gpu()
    _log_unipka_compute_device(use_gpu)
    orig = fe_mod._smiles_to_free_energy_record

    def _cached(smi, cfg):
        rec = records_by_smi.get(smi)
        if rec is None:
            return orig(smi, cfg)
        return rec

    fe_mod._smiles_to_free_energy_record = _cached
    try:
        cfg = UnipkaFreeEnergyConfig(nthreads=1, gpu=use_gpu)
        with _unipka_windows_lmdb_guards():
            frame = predict_standard_free_energies(list(mols), config=cfg)
    finally:
        fe_mod._smiles_to_free_energy_record = orig
    if len(frame) != len(mols):
        raise ValueError(f"Expected {len(mols)} free-energy rows, got {len(frame)}.")
    return [float(frame.loc[i, "standard_free_energy"]) for i in range(len(mols))]


def _host_entry(payload: tuple[list[Mol], dict[str, dict]]) -> list[float]:
    mols, records = payload
    return _score_in_process(mols, records)


def _host_pool():
    global _HOST
    with _HOST_LOCK:
        if _HOST is not None:
            return _HOST
        ctx = multiprocessing.get_context("spawn")
        from concurrent.futures import ProcessPoolExecutor

        _HOST = register_process_pool(ProcessPoolExecutor(max_workers=1, mp_context=ctx))
        return _HOST


def shutdown_unipka_score_host() -> None:
    """Stop the scoring process (app exit, cancel, or a broken worker)."""
    global _HOST
    with _HOST_LOCK:
        ex = _HOST
        _HOST = None
    shutdown_process_pool_executor(ex, kill_workers=True)


def score_raw_free_energies(mols: list[Mol], records_by_smi: dict[str, dict]) -> list[float]:
    """Score *mols* on the single torch process.

    A worker that already is that process scores in place so it does not start
    another copy of the model.
    """
    if multiprocessing.parent_process() is not None:
        return _score_in_process(mols, records_by_smi)
    pool = _host_pool()
    return pool.submit(_host_entry, (list(mols), records_by_smi)).result()


atexit.register(shutdown_unipka_score_host)
