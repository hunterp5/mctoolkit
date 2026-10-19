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

"""Shared Uni-pKa ionization-ensemble deduplication and optional process-pool execution."""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, BrokenExecutor, ProcessPoolExecutor, wait
from collections.abc import Iterator
from contextlib import contextmanager

from rdkit import Chem

from ..platform_support.config import load_config
from .process_pool_utils import (
    add_process_pool_shutdown_callback,
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .structure_grouping import group_rows_by_structure, structure_key

logger = logging.getLogger(__name__)

# Uni-pKa writes an LMDB and scores 11 conformers per microstate. One molecule per
# call under-fills the GPU and repeats that I/O. A 1-worker (CUDA) pool can take a
# larger batch; several CPU workers keep smaller chunks so progress still moves.
UNIPKA_STRUCTURE_CHUNK = 8
UNIPKA_STRUCTURE_CHUNK_SERIAL = 16
# Wait-loop poll while a chunk is in flight. Scoring stays batched; this only
# refreshes the status bar from shared per-molecule flags.
UNIPKA_PROGRESS_POLL_S = 0.1

_POOL_LOCK = threading.Lock()
_PERSISTENT_POOL: ProcessPoolExecutor | None = None
_PERSISTENT_POOL_WORKERS = 0
_PERSISTENT_POOL_REFS = 0
_SHUTDOWN_HOOK_REGISTERED = False


def unipka_cuda_available() -> bool:
    """CUDA wheel present and GPU not forced off. Does not initialize the CUDA runtime."""
    from molmanager.ionization.unipka_ensembles import pka_gpu_forced_off, torch_is_cuda_build

    if pka_gpu_forced_off():
        return False
    return torch_is_cuda_build()


def structure_progress_flags(n: int):
    """Shared 0/1 completion flags for unique structures (process-pool progress)."""
    from multiprocessing import Array

    n_i = max(0, int(n))
    if n_i <= 0:
        return None
    return Array("B", n_i)


def mark_structure_progress(flags, flag_indices: list[int] | None, done_local: int) -> None:
    """Mark the first *done_local* chunk keys complete on *flags*."""
    if flags is None or not flag_indices:
        return
    n_mark = min(max(int(done_local), 0), len(flag_indices))
    for j in range(n_mark):
        flags[flag_indices[j]] = 1


def flagged_unique_count(flags, n: int) -> int:
    """How many of the first *n* flag slots are set."""
    if flags is None:
        return 0
    return sum(1 for i in range(max(0, int(n))) if flags[i])


def flagged_row_count(
    flags,
    keys: list[str],
    oids_map: dict[str, list],
    base: int = 0,
) -> int:
    """Row progress: *base* plus table rows whose unique key is flagged."""
    done = int(base)
    if flags is None:
        return done
    for i, key in enumerate(keys):
        if flags[i]:
            done += len(oids_map.get(key, ()))
    return done


def chunk_structure_keys(keys: list[str], n_workers: int) -> list[list[str]]:
    """Split unique keys into process-pool tasks.

    Each task is one Uni-pKa free-energy call. Batching several structures
    amortizes LMDB setup and GPU kernel launches; per-molecule status comes
    from shared flags, not from shrinking these batches.
    """
    if not keys:
        return []
    n_w = max(1, int(n_workers))
    cap = UNIPKA_STRUCTURE_CHUNK_SERIAL if n_w == 1 else UNIPKA_STRUCTURE_CHUNK
    chunk_size = min(cap, max(1, (len(keys) + n_w - 1) // n_w))
    return [keys[i : i + chunk_size] for i in range(0, len(keys), chunk_size)]


def _clear_persistent_pool_if_matches(ex: ProcessPoolExecutor) -> None:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS, _PERSISTENT_POOL_WORKERS
    with _POOL_LOCK:
        if _PERSISTENT_POOL is ex:
            _PERSISTENT_POOL = None
            _PERSISTENT_POOL_WORKERS = 0
            _PERSISTENT_POOL_REFS = 0


def _ensure_pool_shutdown_hook() -> None:
    global _SHUTDOWN_HOOK_REGISTERED
    if _SHUTDOWN_HOOK_REGISTERED:
        return
    add_process_pool_shutdown_callback(_clear_persistent_pool_if_matches)
    _SHUTDOWN_HOOK_REGISTERED = True


def _executor_is_usable(ex: ProcessPoolExecutor | None) -> bool:
    if ex is None:
        return False
    if getattr(ex, "_broken", False):
        return False
    shutdown_flag = getattr(ex, "_shutdown_thread", False)
    if shutdown_flag is True or isinstance(shutdown_flag, threading.Thread):
        return False
    if getattr(ex, "_shutdown", False) is True:
        return False
    return True


def discard_ionization_process_pool() -> None:
    """Kill the cached 1-worker Uni-pKa pool (timeout, tests, or a broken GPU worker)."""
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS, _PERSISTENT_POOL_WORKERS
    with _POOL_LOCK:
        ex = _PERSISTENT_POOL
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_WORKERS = 0
        _PERSISTENT_POOL_REFS = 0
    shutdown_process_pool_executor(ex, kill_workers=True)
    from molmanager.ionization.unipka_score_host import shutdown_unipka_score_host

    shutdown_unipka_score_host()


def _acquire_persistent_pool(n_workers: int) -> ProcessPoolExecutor:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS, _PERSISTENT_POOL_WORKERS
    _ensure_pool_shutdown_hook()
    n = max(1, int(n_workers))
    with _POOL_LOCK:
        ex = _PERSISTENT_POOL
        if _executor_is_usable(ex) and _PERSISTENT_POOL_WORKERS >= n:
            _PERSISTENT_POOL_REFS += 1
            return ex
        stale = ex
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_WORKERS = 0
        _PERSISTENT_POOL_REFS = 0
    if stale is not None:
        shutdown_process_pool_executor(stale, kill_workers=True)
    created = register_process_pool(ProcessPoolExecutor(max_workers=n))
    with _POOL_LOCK:
        _PERSISTENT_POOL = created
        _PERSISTENT_POOL_WORKERS = n
        _PERSISTENT_POOL_REFS = 1
    return created


def _release_persistent_pool(*, kill: bool) -> None:
    global _PERSISTENT_POOL, _PERSISTENT_POOL_REFS, _PERSISTENT_POOL_WORKERS
    with _POOL_LOCK:
        _PERSISTENT_POOL_REFS = max(0, _PERSISTENT_POOL_REFS - 1)
        ex = _PERSISTENT_POOL
        if not kill and _executor_is_usable(ex):
            return
        _PERSISTENT_POOL = None
        _PERSISTENT_POOL_WORKERS = 0
        _PERSISTENT_POOL_REFS = 0
    shutdown_process_pool_executor(ex, kill_workers=True)


@contextmanager
def ionization_process_pool(
    proc_workers: int,
    *,
    cancel_event: threading.Event | None = None,
) -> Iterator[ProcessPoolExecutor]:
    """Yield a Uni-pKa process pool.

    A 1-worker pool (CUDA, or CPU with one process) is kept alive after a
    successful job so the next Predict pKa / Protonate does not reload fold
    weights. Cancel, a broken executor, or ``discard_ionization_process_pool``
    still terminate the child. Multi-worker CPU pools are ephemeral.
    """
    n = max(1, int(proc_workers))
    persist = n == 1
    if persist:
        ex = _acquire_persistent_pool(n)
        kill = False
        try:
            yield ex
        except Exception:
            kill = True
            raise
        finally:
            if should_terminate_process_pool(cancel_event) or getattr(ex, "_broken", False):
                kill = True
            _release_persistent_pool(kill=kill)
        return
    ex = register_process_pool(ProcessPoolExecutor(max_workers=n))
    try:
        yield ex
    finally:
        shutdown_process_pool_executor(ex, kill_workers=should_terminate_process_pool(cancel_event))


def map_ionization_progress(
    done_unique: int,
    n_unique: int,
    *,
    progress_total: int | None = None,
    reserve_final_tick: bool = True,
) -> tuple[int, int]:
    """Map finished unique structures onto a status-bar ``(done, total)``.

    When ``progress_total`` is set (row count), ionization is scaled onto that
    range. ``reserve_final_tick`` leaves the last count for a later phase
    (descriptor rows). Protonate / Generate Protomers pass False so the bar
    moves during Uni-pKa instead of staying at 0% until the worker finishes.
    """
    n_u = max(0, int(n_unique))
    done_u = max(0, int(done_unique))
    if n_u:
        done_u = min(done_u, n_u)
    if progress_total is None:
        tot = max(n_u, 1)
        return min(done_u, tot), tot
    tot = max(1, int(progress_total))
    ceiling = tot if not reserve_final_tick else max(0, tot - 1)
    if n_u <= 0 or ceiling <= 0:
        return 0, tot
    if done_u >= n_u:
        return ceiling, tot
    mapped = int(round((float(done_u) / float(n_u)) * float(ceiling)))
    if done_u > 0:
        mapped = max(1, mapped)
    return min(mapped, ceiling), tot


def _set_unipka_mmff_thread_env(proc_workers: int) -> str | None:
    """Pin MMFF to 1 thread per child when several Uni-pKa processes share the CPU."""
    prev = os.environ.get("MOLMANAGER_UNIPKA_MMFF_THREADS")
    if prev:
        return prev
    if proc_workers > 1:
        os.environ["MOLMANAGER_UNIPKA_MMFF_THREADS"] = "1"
    return None


def _restore_unipka_mmff_thread_env(prev: str | None, wrote: bool) -> None:
    if not wrote:
        return
    if prev is None:
        os.environ.pop("MOLMANAGER_UNIPKA_MMFF_THREADS", None)
    else:
        os.environ["MOLMANAGER_UNIPKA_MMFF_THREADS"] = prev


def plan_ionization_process_workers(
    n_unique: int,
    configured: int | None,
) -> tuple[bool, int]:
    """
    Decide whether to use a process pool and how many workers.

    ``configured`` is the tool-specific env override (``None`` = auto). Scoring is
    always one torch process: each extra worker used to load its own ~1.9 GB
    checkpoint. ``configured`` above 1 still only starts that one process;
    conformer generation fans out separately. CUDA stays in that child so the
    GUI process must not call ``torch.cuda.is_available()``.
    """
    if configured is not None and int(configured) <= 0:
        return False, 1
    if unipka_cuda_available():
        return n_unique >= 1, 1
    cpu = os.cpu_count() or 4
    use_mp = cpu > 1 and n_unique >= 1
    return use_mp, 1


def _mp_compute_microstates(task: tuple[str, bytes]) -> tuple[str, object | None]:
    """Child-process entry: one structure → picklable ionization ensemble (or ``None``)."""
    return _mp_compute_microstates_chunk([task])[0]


def _mp_compute_microstates_chunk(
    tasks: list[tuple[str, bytes]],
    progress_flags=None,
    flag_indices: list[int] | None = None,
) -> list[tuple[str, object | None]]:
    """Score a chunk of structures in one Uni-pKa free-energy call."""
    from molmanager.ionization.unipka_ensembles import predict_ionization_ensembles

    keys: list[str] = []
    mols: list[Chem.Mol | None] = []
    for key, mol_blob in tasks:
        keys.append(key)
        if not mol_blob:
            mols.append(None)
            continue
        try:
            mol = Chem.Mol(mol_blob)
        except Exception:
            mols.append(None)
            continue
        if mol is None or mol.GetNumAtoms() == 0:
            mols.append(None)
        else:
            mols.append(mol)
    usable_idx = [i for i, mol in enumerate(mols) if mol is not None]
    if flag_indices is not None:
        for i, mol in enumerate(mols):
            if mol is None:
                mark_structure_progress(progress_flags, [flag_indices[i]], 1)
    ensembles: list[object | None] = [None] * len(keys)
    if usable_idx:
        usable_flags = [flag_indices[i] for i in usable_idx] if flag_indices is not None else None

        def _report(done: int, _total: int) -> None:
            mark_structure_progress(progress_flags, usable_flags, done)

        try:
            scored = predict_ionization_ensembles(
                [mols[i] for i in usable_idx],
                on_progress=_report,
            )
            for i, ens in zip(usable_idx, scored):
                ensembles[i] = ens
            _report(len(usable_idx), len(usable_idx))
        except Exception:
            logger.exception(
                "Uni-pKa subprocess: batched prediction failed for %s structure(s)",
                len(usable_idx),
            )
    return list(zip(keys, ensembles))


def predict_microstates_for_sketch(
    mol: Chem.Mol,
    *,
    cancel_event: threading.Event | None = None,
    timeout_s: float = 180.0,
):
    """
    Predict an ionization ensemble for one sketcher molecule without blocking Qt on the GIL.

    Uses the session microstate cache when possible. Otherwise runs Uni-pKa in a
    short-lived child process (no in-process fallback — failures return ``None``).
    """
    import time

    from molmanager.ionization.unipka_ensembles import microstates_for_mol
    from molmanager.ionization.microstate_cache import lookup as cache_lookup
    from molmanager.ionization.microstate_cache import store as cache_store

    key = structure_key(mol)
    hit, cached = cache_lookup(key)
    if hit:
        return cached

    try:
        blob = mol.ToBinary()
    except Exception:
        return None
    if not blob:
        return None

    cfg = load_config()
    configured = cfg.pka_process_workers
    if configured is not None and int(configured) <= 0:
        return microstates_for_mol(mol)

    states = None
    timed_out = False
    with ionization_process_pool(1, cancel_event=cancel_event) as ex:
        fut = ex.submit(_mp_compute_microstates, (key, blob))
        deadline = time.monotonic() + max(5.0, float(timeout_s))
        while True:
            if should_terminate_process_pool(cancel_event):
                fut.cancel()
                states = None
                break
            if time.monotonic() >= deadline:
                logger.warning("Uni-pKa sketch microstates timed out after %.0fs", timeout_s)
                fut.cancel()
                timed_out = True
                states = None
                break
            completed, _pending = wait({fut}, timeout=0.25, return_when=FIRST_COMPLETED)
            if not completed:
                continue
            if fut.cancelled():
                states = None
                break
            try:
                _k, states = fut.result()
            except BrokenExecutor:
                logger.warning("Uni-pKa sketch process pool broke during prediction")
                timed_out = True
                states = None
            except Exception:
                logger.debug("Uni-pKa sketch microstates failed", exc_info=True)
                states = None
            break
    if timed_out:
        discard_ionization_process_pool()

    cache_store(key, states)
    return states


def build_microstates_cache_by_key(
    mols: list[Chem.Mol],
    *,
    workers_cfg: int | None = None,
    cancel_event: threading.Event | None = None,
    progress_state=None,
    signals=None,
    progress_message: str = "Uni-pKa ionization…",
    progress_total: int | None = None,
    reserve_final_tick: bool = True,
) -> dict[str, object | None]:
    """
    Predict Uni-pKa ionization ensembles once per unique structure.

    Returns ``structure_key → ensemble`` (or ``None`` on failure).
    """
    rows = [(None, m) for m in mols if m is not None]
    if not rows:
        return {}
    order, rep, _oids_map = group_rows_by_structure(rows)
    if not order:
        return {}

    from molmanager.ionization.unipka_ensembles import (
        microstates_for_mol,
        warn_if_cuda_torch_missing,
    )
    from molmanager.ionization.microstate_cache import lookup as cache_lookup
    from molmanager.ionization.microstate_cache import store_many as cache_store_many
    from ..platform_support.tool_progress import report_tool_progress

    warn_if_cuda_torch_missing()

    cache: dict[str, object | None] = {}
    need: list[str] = []
    for key in order:
        hit, states = cache_lookup(key)
        if hit:
            cache[key] = states
        else:
            need.append(key)

    cfg = load_config()
    configured = workers_cfg if workers_cfg is not None else cfg.pka_process_workers
    use_mp, proc_workers = (
        plan_ionization_process_workers(len(need), configured) if need else (False, 1)
    )
    n_unique = len(order)
    n_need = len(need)

    def _report_ionization(done_unique: int, *, force: bool = False) -> None:
        done_mapped, total_mapped = map_ionization_progress(
            done_unique,
            n_unique,
            progress_total=progress_total,
            reserve_final_tick=reserve_final_tick,
        )
        report_tool_progress(
            message=progress_message,
            done=done_mapped,
            total=total_mapped,
            progress_state=progress_state,
            signals=signals,
            force_signal=force,
        )

    _report_ionization(len(cache), force=True)

    if not need:
        _report_ionization(len(cache), force=True)
        logger.debug("ionization cache: %s unique structure(s), all session-cache hits", n_unique)
        return cache

    from molmanager.ionization.unipka_ensembles import warn_if_cuda_torch_missing

    warn_if_cuda_torch_missing()

    if use_mp:
        key_chunks = chunk_structure_keys(need, proc_workers)
        task_chunks = [[(k, rep[k].ToBinary()) for k in chunk] for chunk in key_chunks]
        need_index = {k: i for i, k in enumerate(need)}
        flags = structure_progress_flags(n_need)
        n_cached = len(cache)
        pool_failed = False
        wrote_mmff = os.environ.get("MOLMANAGER_UNIPKA_MMFF_THREADS") is None and proc_workers > 1
        prev_mmff = _set_unipka_mmff_thread_env(proc_workers)

        def _report_live(*, force: bool = False) -> None:
            live = max(len(cache), n_cached + flagged_unique_count(flags, n_need))
            _report_ionization(live, force=force)

        try:
            with ionization_process_pool(proc_workers, cancel_event=cancel_event) as ex:
                pending = {
                    ex.submit(
                        _mp_compute_microstates_chunk,
                        chunk,
                        flags,
                        [need_index[k] for k in key_chunks[i]],
                    )
                    for i, chunk in enumerate(task_chunks)
                }
                while pending:
                    if should_terminate_process_pool(cancel_event):
                        completed, pending = wait(pending, timeout=0)
                        for f in completed:
                            if f.cancelled():
                                continue
                            try:
                                for key, states in f.result():
                                    cache[key] = states
                            except Exception:
                                logger.debug("Uni-pKa process-pool task failed", exc_info=True)
                        for f in pending:
                            f.cancel()
                        break
                    completed, pending = wait(
                        pending,
                        timeout=UNIPKA_PROGRESS_POLL_S,
                        return_when=FIRST_COMPLETED,
                    )
                    _report_live()
                    for f in completed:
                        if f.cancelled():
                            continue
                        try:
                            for key, states in f.result():
                                cache[key] = states
                                idx = need_index.get(key)
                                if idx is not None:
                                    mark_structure_progress(flags, [idx], 1)
                            _report_live(force=True)
                        except BrokenExecutor:
                            pool_failed = True
                            logger.warning(
                                "Uni-pKa process pool failed; finishing remaining structures sequentially"
                            )
                            break
                        except Exception:
                            logger.debug("Uni-pKa process-pool task failed", exc_info=True)
                    if pool_failed:
                        for f in pending:
                            f.cancel()
                        break
        finally:
            _restore_unipka_mmff_thread_env(prev_mmff, wrote_mmff)
        if pool_failed:
            discard_ionization_process_pool()
        if pool_failed or any(k not in cache for k in need):
            # Do not score leftover structures in this process when a CUDA wheel is
            # installed — that would initialize CUDA in the GUI and block shutdown.
            sequential_ok = not unipka_cuda_available()
            for key in need:
                if key in cache:
                    continue
                if should_terminate_process_pool(cancel_event):
                    break
                if sequential_ok:
                    cache[key] = microstates_for_mol(rep[key])
                else:
                    cache[key] = None
                _report_ionization(len(cache), force=True)
        _report_ionization(len(cache), force=True)
        cache_store_many({k: cache[k] for k in need if k in cache})
        logger.debug(
            "ionization cache: %s unique (%s missed session cache), process pool=%s",
            n_unique,
            n_need,
            proc_workers,
        )
        return cache

    for i, key in enumerate(need, start=1):
        if should_terminate_process_pool(cancel_event):
            break
        cache[key] = microstates_for_mol(rep[key])
        _report_ionization(len(cache), force=True)
    _report_ionization(len(cache), force=True)
    cache_store_many({k: cache[k] for k in need if k in cache})
    logger.debug(
        "ionization cache: %s unique (%s missed session cache), sequential",
        n_unique,
        n_need,
    )
    return cache


def build_microstates_cache_for_rows(
    rows: list[tuple[int, Chem.Mol | None]],
    *,
    workers_cfg: int | None = None,
    cancel_event: threading.Event | None = None,
    progress_state=None,
    signals=None,
    progress_message: str = "Uni-pKa ionization…",
    progress_total: int | None = None,
    reserve_final_tick: bool = True,
) -> dict[int, object | None]:
    """Map each row index to an ionization ensemble (deduplicated by structure)."""
    mols = [mol for _idx, mol in rows if mol is not None]
    by_key = build_microstates_cache_by_key(
        mols,
        workers_cfg=workers_cfg,
        cancel_event=cancel_event,
        progress_state=progress_state,
        signals=signals,
        progress_message=progress_message,
        progress_total=progress_total,
        reserve_final_tick=reserve_final_tick,
    )
    out: dict[int, object | None] = {}
    for idx, mol in rows:
        if mol is None:
            out[idx] = None
            continue
        out[idx] = by_key.get(structure_key(mol))
    return out
