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

"""Background pKa prediction using Uni-pKa (Luo et al., JACS Au 2024).

**Uni-pKa** — Luo, Y.; Liu, Y.; Peng, J.; Tang, H.; Nie, H.; Zhong, W.; Chen, X.;
Zheng, S. Toward Universal Cell Environment pKa Prediction via Multi-task Learning.
JACS Au 2024, 4, 1721. https://doi.org/10.1021/jacsau.4c00271
Code: https://github.com/dptech-corp/Uni-pKa — runtime: unipkainfer.

Enumeration uses MolGpKa-derived SMARTS (Pan et al., J. Chem. Inf. Model. 2021).
Shorter copy-paste block: ``molmanager.reference.method_citations.UNIPKA``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import threading
from concurrent.futures import FIRST_COMPLETED, wait

from PyQt5 import sip
from PyQt5.QtCore import QObject, QRunnable, pyqtSignal
from rdkit import Chem

from molmanager.ionization.unipka_ensembles import (
    format_pka_and_pi,
    predict_ionization_ensemble,
    predict_ionization_ensembles,
    prepare_mol_for_ionization,
    unipka_import_error,
)
from .process_pool_utils import (
    application_is_shutting_down,
    should_terminate_process_pool,
)
from .structure_grouping import group_rows_by_structure

logger = logging.getLogger(__name__)

_unipka_lock = threading.Lock()
# Placeholder written for rows a cancelled run did not score. Later runs treat it as empty.
_CANCELLED_RESULT = "Cancelled."

_UNIPKA_SUPPRESSED_LOGGER_NAMES = (
    "rdkit.Chem.PandasPatcher",
    "rdkit.Chem.PandasTools",
    "unipkainfer",
    "unicoreinfer",
)


@contextlib.contextmanager
def _quieter_unipka_loggers():
    """Temporarily raise log levels so Uni-pKa / RDKit chatter does not flood the console."""
    saved: list[tuple[logging.Logger, int]] = []
    for name in _UNIPKA_SUPPRESSED_LOGGER_NAMES:
        lg = logging.getLogger(name)
        saved.append((lg, lg.level))
        lg.setLevel(logging.ERROR)
    try:
        yield
    finally:
        for lg, prev in saved:
            lg.setLevel(prev)


@contextlib.contextmanager
def _discard_stdio():
    """Hide Uni-pKa ``print`` output (it bypasses logging)."""
    with open(os.devnull, "w", encoding="utf-8") as dn:
        with contextlib.redirect_stdout(dn), contextlib.redirect_stderr(dn):
            yield


@contextlib.contextmanager
def _discard_stdout_only():
    """Hide chatty ``print`` on stdout while keeping stderr for tracebacks."""
    with open(os.devnull, "w", encoding="utf-8") as dn:
        with contextlib.redirect_stdout(dn):
            yield


def _safe_emit(obj, emitter_name: str, *args) -> None:
    """Emit on a QObject-owned signal if the C++ object still exists."""
    if obj is None:
        return
    try:
        if sip.isdeleted(obj):
            return
    except Exception:
        return
    try:
        getattr(obj, emitter_name).emit(*args)
    except RuntimeError:
        pass


def _acquire_lock_cooperative(
    lock: threading.Lock, cancel_event: threading.Event | None, timeout_s: float = 0.05
) -> bool:
    """Acquire lock in short slices so cancellation can abort long waits."""
    while True:
        if cancel_event is not None and cancel_event.is_set():
            return False
        if lock.acquire(timeout=timeout_s):
            return True


def _format_pka_and_pi(
    states, *, most_basic_only: bool = False, most_acidic_only: bool = False
) -> tuple[str, str]:
    return format_pka_and_pi(
        states, most_basic_only=most_basic_only, most_acidic_only=most_acidic_only
    )


def _mp_compute_pka_text(
    task: tuple[str, bytes, bool, bool],
) -> tuple[str, str, str, object | None, bool]:
    """Child-process entry: load Uni-pKa, predict one structure."""
    return _mp_compute_pka_chunk([task])[0]


def _na_pka_row(key: str, *, cacheable: bool = True) -> tuple[str, str, str, object | None, bool]:
    return (key, "N/A", "N/A", None, cacheable)


def _mp_compute_pka_chunk(
    tasks: list[tuple[str, bytes, bool, bool]],
    progress_flags=None,
    flag_indices: list[int] | None = None,
) -> list[tuple[str, str, str, object | None, bool]]:
    """Score a chunk of structures in one Uni-pKa free-energy call."""
    from .ionization_parallel import mark_structure_progress

    err = unipka_import_error()
    if err:
        logger.error("pKa subprocess: %s", err)
        return [(task[0], "Error (see log)", "N/A", None, False) for task in tasks]

    keys: list[str] = []
    flags: list[tuple[bool, bool]] = []
    mols: list[Chem.Mol | None] = []
    na_results: dict[int, tuple[str, str, str, object | None, bool]] = {}
    for i, (key, mol_blob, most_basic_only, most_acidic_only) in enumerate(tasks):
        keys.append(key)
        flags.append((most_basic_only, most_acidic_only))
        if not mol_blob:
            mols.append(None)
            na_results[i] = _na_pka_row(key)
            continue
        try:
            mol = Chem.Mol(mol_blob)
        except Exception:
            mols.append(None)
            na_results[i] = _na_pka_row(key)
            continue
        if mol is None or mol.GetNumAtoms() == 0:
            mols.append(None)
            na_results[i] = _na_pka_row(key)
            continue
        safe = prepare_mol_for_ionization(mol)
        if safe is None:
            mols.append(None)
            na_results[i] = _na_pka_row(key)
        else:
            mols.append(safe)

    if flag_indices is not None:
        for i in na_results:
            mark_structure_progress(progress_flags, [flag_indices[i]], 1)

    usable_idx = [i for i, mol in enumerate(mols) if mol is not None]
    ensembles: list[object | None] = [None] * len(keys)
    failed = False
    if usable_idx:
        usable_flags = [flag_indices[i] for i in usable_idx] if flag_indices is not None else None

        def _report(done: int, _total: int) -> None:
            mark_structure_progress(progress_flags, usable_flags, done)

        try:
            with _discard_stdout_only():
                scored = predict_ionization_ensembles(
                    [mols[i] for i in usable_idx],
                    on_progress=_report,
                )
            for i, ens in zip(usable_idx, scored):
                ensembles[i] = ens
            _report(len(usable_idx), len(usable_idx))
        except Exception:
            failed = True
            logger.exception(
                "pKa subprocess: batched prediction failed for %s structure(s)",
                len(usable_idx),
            )

    out: list[tuple[str, str, str, object | None, bool]] = []
    for i, key in enumerate(keys):
        if i in na_results:
            out.append(na_results[i])
            continue
        most_basic_only, most_acidic_only = flags[i]
        ensemble = ensembles[i]
        if failed and ensemble is None:
            out.append((key, "Error (see log)", "N/A", None, False))
            continue
        if ensemble is None:
            out.append(_na_pka_row(key))
            continue
        pka_txt, pi_txt = _format_pka_and_pi(
            ensemble,
            most_basic_only=most_basic_only,
            most_acidic_only=most_acidic_only,
        )
        out.append((key, pka_txt, pi_txt, ensemble, True))
    return out


class PKaPredictorSignals(QObject):
    """Emits from :class:`PKaPredictorWorker` back to the dialog (owned on the GUI thread)."""

    finished = pyqtSignal(list, bool)  # list[tuple[int | None, str, str]] oid, pKa, pI; include_pi
    failed = pyqtSignal(str)


class PKaPredictorWorker(QRunnable):
    """Predict macro pKa values per row; writes are applied on the GUI thread via ``finished``."""

    def __init__(
        self,
        rows: list[tuple[int | None, Chem.Mol | None]],
        worker_signals,
        pka_signals: PKaPredictorSignals,
        cancel_event: threading.Event | None = None,
        *,
        most_basic_only: bool = False,
        most_acidic_only: bool = False,
        include_pi: bool = False,
        progress_state=None,
    ):
        super().__init__()
        self.rows = rows
        self.worker_signals = worker_signals
        self.pka_signals = pka_signals
        self.cancel_event = cancel_event
        self.most_basic_only = most_basic_only
        self.most_acidic_only = most_acidic_only
        self.include_pi = bool(include_pi)
        self.progress_state = progress_state

    def run(self) -> None:
        with _quieter_unipka_loggers():
            err = unipka_import_error()
            if err:
                logger.exception("pKa predictor: Uni-pKa import failed")
                _safe_emit(self.pka_signals, "failed", err)
                return

            from molmanager.ionization.unipka_ensembles import warn_if_cuda_torch_missing

            warn_if_cuda_torch_missing()

            cancel_ev = self.cancel_event
            row_text: dict[int | None, tuple[str, str]] = {}
            for oid, mol in self.rows:
                if mol is None:
                    row_text[oid] = ("N/A", "N/A")

            order, rep, oids_map = group_rows_by_structure(self.rows)
            n_work = sum(len(oids_map[k]) for k in order) + sum(
                1 for oid, mol in self.rows if mol is None
            )
            tot = max(n_work, 1)

            from ..platform_support.config import load_config
            from molmanager.ionization.microstate_cache import lookup as cache_lookup
            from .ionization_parallel import (
                UNIPKA_PROGRESS_POLL_S,
                chunk_structure_keys,
                flagged_row_count,
                close_structure_progress_flags,
                mark_structure_progress,
                plan_ionization_process_workers,
                structure_progress_flags,
            )

            done_cum = sum(1 for oid, mol in self.rows if mol is None)
            cancelled = False

            from ..platform_support.tool_progress import report_tool_progress

            throttle = [0, 0.0]

            def _emit(done: int, *, force: bool = False) -> None:
                report_tool_progress(
                    message="pKa prediction",
                    done=min(done, tot),
                    total=tot,
                    progress_state=self.progress_state,
                    signals=self.worker_signals,
                    throttle=throttle,
                    force_signal=force,
                )

            _emit(done_cum, force=True)

            score_order: list[str] = []
            for key in order:
                hit, states = cache_lookup(key)
                if not hit:
                    score_order.append(key)
                    continue
                pka_txt, pi_txt = format_pka_and_pi(
                    states,
                    most_basic_only=self.most_basic_only,
                    most_acidic_only=self.most_acidic_only,
                )
                for oid in oids_map.get(key, ()):
                    row_text[oid] = (pka_txt, pi_txt)
                done_cum += len(oids_map.get(key, ()))
            order = score_order
            n_unique = len(order)
            _emit(done_cum, force=True)

            use_mp, proc_workers = plan_ionization_process_workers(
                n_unique, load_config().pka_process_workers
            )

            if not order:
                out = [(oid, *(row_text.get(oid, ("N/A", "N/A")))) for oid, _ in self.rows]
                _emit(tot, force=True)
                _safe_emit(self.pka_signals, "finished", out, self.include_pi)
                return

            if use_mp:
                from molmanager.ionization.microstate_cache import store as cache_store
                from .ionization_parallel import (
                    _restore_unipka_mmff_thread_env,
                    _set_unipka_mmff_thread_env,
                    ionization_process_pool,
                )

                key_chunks = chunk_structure_keys(order, proc_workers)
                task_chunks = [
                    [
                        (k, rep[k].ToBinary(), self.most_basic_only, self.most_acidic_only)
                        for k in chunk
                    ]
                    for chunk in key_chunks
                ]
                key_index = {k: i for i, k in enumerate(order)}
                flags = structure_progress_flags(n_unique)
                done_base = done_cum
                results_by_key: dict[str, tuple[str, str]] = {}
                wrote_mmff = (
                    os.environ.get("MOLMANAGER_UNIPKA_MMFF_THREADS") is None and proc_workers > 1
                )
                prev_mmff = _set_unipka_mmff_thread_env(proc_workers)
                pool_error_logged = False
                logger.info(
                    "pKa: scoring in %s worker process(es) (%s unique structure(s))",
                    proc_workers,
                    n_unique,
                )

                def _emit_live(*, force: bool = False) -> None:
                    nonlocal done_cum
                    done_cum = flagged_row_count(flags, order, oids_map, done_base)
                    _emit(done_cum, force=force)

                def _log_pool_failure() -> None:
                    nonlocal pool_error_logged
                    if should_terminate_process_pool(cancel_ev):
                        logger.debug("pKa process-pool task ended after cancel", exc_info=True)
                        return
                    if pool_error_logged:
                        logger.error("pKa process-pool task failed")
                        return
                    pool_error_logged = True
                    logger.exception("pKa process-pool task failed")

                def _take_result(fut) -> None:
                    if fut.cancelled():
                        return
                    try:
                        rows = fut.result()
                    except Exception:
                        _log_pool_failure()
                        return
                    for key, txt, pi_txt, ensemble, cacheable in rows:
                        results_by_key[key] = (txt, pi_txt)
                        if cacheable:
                            cache_store(key, ensemble)
                        idx = key_index.get(key)
                        if idx is not None:
                            mark_structure_progress(flags, [idx], 1)
                    _emit_live()

                try:
                    with ionization_process_pool(proc_workers, cancel_event=cancel_ev) as ex:
                        pending = {
                            ex.submit(
                                _mp_compute_pka_chunk,
                                chunk,
                                flags,
                                [key_index[k] for k in key_chunks[i]],
                            )
                            for i, chunk in enumerate(task_chunks)
                        }
                        while pending:
                            if (
                                should_terminate_process_pool(cancel_ev)
                                or application_is_shutting_down()
                            ):
                                cancelled = True
                                completed, pending = wait(pending, timeout=0)
                                for fut in completed:
                                    _take_result(fut)
                                for fut in pending:
                                    fut.cancel()
                                break
                            completed, pending = wait(
                                pending,
                                timeout=UNIPKA_PROGRESS_POLL_S,
                                return_when=FIRST_COMPLETED,
                            )
                            _emit_live()
                            for fut in completed:
                                _take_result(fut)
                finally:
                    _restore_unipka_mmff_thread_env(prev_mmff, wrote_mmff)
                    close_structure_progress_flags(flags)
                missing = (
                    (_CANCELLED_RESULT, _CANCELLED_RESULT)
                    if cancelled
                    else ("Error (see log)", "N/A")
                )
                for key in order:
                    txt, pi_txt = results_by_key.get(key, missing)
                    for oid in oids_map.get(key, ()):
                        row_text[oid] = (txt, pi_txt)
            else:
                from molmanager.ionization.microstate_cache import store as cache_store

                for key in order:
                    if should_terminate_process_pool(cancel_ev):
                        cancelled = True
                        break
                    mol = rep[key]
                    safe_mol = prepare_mol_for_ionization(mol)
                    if safe_mol is None:
                        pair = ("N/A", "N/A")
                        cache_store(key, None)
                    else:
                        try:
                            if not _acquire_lock_cooperative(_unipka_lock, cancel_ev):
                                cancelled = True
                                break
                            try:
                                with _discard_stdout_only():
                                    ensemble = predict_ionization_ensemble(safe_mol)
                            finally:
                                _unipka_lock.release()
                            pair = _format_pka_and_pi(
                                ensemble,
                                most_basic_only=self.most_basic_only,
                                most_acidic_only=self.most_acidic_only,
                            )
                            cache_store(key, ensemble)
                        except UnicodeDecodeError as e:
                            logger.warning(
                                "pKa prediction skipped %s row(s) (non-UTF8 structure metadata): %s",
                                len(oids_map[key]),
                                e,
                            )
                            pair = ("N/A (SDF metadata)", "N/A")
                            cache_store(key, None)
                        except Exception:
                            logger.exception(
                                "pKa prediction failed for %s row(s) (key prefix %.40s…)",
                                len(oids_map[key]),
                                key,
                            )
                            pair = ("Error (see log)", "N/A")
                    for oid in oids_map[key]:
                        row_text[oid] = pair
                    done_cum += len(oids_map[key])
                    _emit(done_cum)

            unfinished = (_CANCELLED_RESULT, _CANCELLED_RESULT) if cancelled else ("N/A", "N/A")
            out = [(oid, *row_text.get(oid, unfinished)) for oid, _mol in self.rows]
            saved = sum(1 for _oid, text, _pi in out if text != _CANCELLED_RESULT)
            _emit(tot if not cancelled else min(saved, tot), force=True)
            if cancelled and saved < tot:
                try:
                    self.worker_signals.partial_results.emit("pKa prediction", saved, tot)
                except Exception:
                    pass
            if use_mp:
                logger.debug(
                    "pKa: %s table row(s), %s unique structure(s), process pool=%s",
                    n_work,
                    n_unique,
                    proc_workers,
                )
            else:
                logger.debug(
                    "pKa: %s table row(s), %s unique structure(s), sequential (set "
                    "MOLMANAGER_PKA_PROCESS_WORKERS>=1 to allow worker processes; <=0 disables)",
                    n_work,
                    n_unique,
                )
            _safe_emit(self.pka_signals, "finished", out, self.include_pi)
