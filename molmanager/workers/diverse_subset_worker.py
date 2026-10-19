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

"""MaxMin diverse subset selection from molecular fingerprints."""

from __future__ import annotations

import logging
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from PyQt5.QtCore import QRunnable
from rdkit import Chem
from rdkit import DataStructs
from rdkit.SimDivFilters.rdSimDivPickers import LeaderPicker, MaxMinPicker

from ..platform_support.config import load_config
from ..chem.fingerprint_cache import get as cache_get
from ..chem.fingerprint_cache import store as cache_store
from ..chem.rdkit_fingerprints import (
    fingerprint_bitvect_for_row,
    fingerprint_bitvect_for_ui_choice,
    fingerprint_is_gil_heavy,
    spec_for_label,
)
from ..platform_support.tool_progress import report_tool_progress
from .process_pool_utils import (
    register_process_pool,
    should_terminate_process_pool,
    shutdown_process_pool_executor,
)
from .signals import DiverseSubsetSignals

logger = logging.getLogger(__name__)

_PROGRESS_LABEL = "Diverse subset"
_PROCESS_POOL_MIN_ROWS = 64
# LeaderPicker on BindingDB-scale pools can freeze the process for minutes (GIL-heavy).
_LEADER_PREFILTER_MAX_ROWS = 25_000

DiverseMode = Literal["exact", "fast", "auto"]
DIVERSE_SUBSET_MODE_LABELS: tuple[tuple[str, str], ...] = (
    ("auto", "Auto (exact when small, Fast when large)"),
    ("exact", "Exact MaxMin"),
    ("fast", "Fast (staged prefilter + MaxMin)"),
)


@dataclass(frozen=True)
class DiverseSubsetRequest:
    """Pool payloads and MaxMin options for :class:`DiverseSubsetWorker`."""

    fp_choice: str
    subset_size: int
    rows: list[tuple[int, Chem.Mol]] | None = None
    oids: list[int] | None = None
    structure_source: str = "Structure"
    mols_by_oid: dict[int, Chem.Mol] | None = None
    structure_texts: list[tuple[int, str]] | None = None
    onbits_by_oid: dict[int, str] | None = None
    use_onbits_column: bool = False
    mode: str = "auto"


class _Cancelled(Exception):
    pass


@dataclass
class DiverseSubsetPoolRow:
    oid: int
    mol: Chem.Mol | None
    fp: Any | None = None


def _tanimoto_distance(fp_i, fp_j) -> float:
    s = float(DataStructs.TanimotoSimilarity(fp_i, fp_j))
    d = 1.0 - s
    if d < 0.0:
        return 0.0
    if d > 1.0:
        return 1.0
    return d


def _parse_onbits_cell(text: str) -> bool:
    t = (text or "").strip()
    if not t or t.upper() == "N/A":
        return False
    try:
        int(float(t))
    except ValueError:
        return False
    return True


def build_diverse_subset_pool(
    rows: list[tuple[int, Chem.Mol]],
    fp_choice: str,
    *,
    onbits_by_oid: dict[int, str] | None = None,
    require_onbits_column: bool = False,
) -> tuple[list[DiverseSubsetPoolRow], str | None]:
    """
    Build the compound pool for MaxMin picking.

    When ``onbits_by_oid`` is set (matching descriptor on-bits column), only rows with
    valid on-bits values are included. Cached bit vectors are attached when available.
    """
    spec = spec_for_label(fp_choice)
    if spec is None:
        return [], "Unknown fingerprint type."
    internal_key = spec.internal_key
    pool: list[DiverseSubsetPoolRow] = []
    for oid, mol in rows:
        if require_onbits_column and onbits_by_oid is not None:
            if not _parse_onbits_cell(onbits_by_oid.get(int(oid), "")):
                continue
        fp = cache_get(int(oid), internal_key)
        pool.append(DiverseSubsetPoolRow(oid=int(oid), mol=mol, fp=fp))
    return pool, None


def _first_pick_index(n: int, seed: int) -> int:
    if n <= 0:
        return 0
    if seed >= 0:
        return int(seed % n)
    return 0


def maxmin_diverse_pick_bulk(
    fps: list,
    pick_size: int,
    *,
    seed: int = -1,
    cancel_event: threading.Event | None = None,
    on_pick: Callable[[int], None] | None = None,
) -> list[int]:
    """
    Fast MaxMin using :func:`DataStructs.BulkTanimotoSimilarity` each iteration.

    Requires a complete fingerprint list (no lazy generation during picking).
    """
    n = len(fps)
    if pick_size <= 0:
        return []
    if pick_size >= n:
        return list(range(n))
    k = int(pick_size)
    first = _first_pick_index(n, seed)
    picked = [first]
    min_dist = np.full(n, np.inf, dtype=np.float32)
    min_dist[first] = 0.0
    picked_mask = np.zeros(n, dtype=bool)
    picked_mask[first] = True
    progress_step = max(1, k // 200)

    for step in range(1, k):
        if cancel_event is not None and cancel_event.is_set():
            raise _Cancelled()
        last = picked[-1]
        sims = DataStructs.BulkTanimotoSimilarity(fps[last], fps)
        dists = np.subtract(1.0, np.asarray(sims, dtype=np.float32))
        np.minimum(min_dist, dists, out=min_dist)
        min_dist[picked_mask] = -1.0
        nxt = int(np.argmax(min_dist))
        picked.append(nxt)
        picked_mask[nxt] = True
        if on_pick is not None and (step + 1) % progress_step == 0:
            on_pick(step + 1)
    if on_pick is not None:
        on_pick(k)
    return picked


def _leader_candidate_indices(
    fps: Sequence,
    target_count: int,
    *,
    cancel_event: threading.Event | None = None,
) -> list[int] | None:
    """
    Sphere-exclusion (Leader) centroids as a diverse prefilter.

    Tries a few Tanimoto-distance thresholds so the centroid count is near *target_count*.
    Returns ``None`` if Leader picking fails.
    """
    n = len(fps)
    if n <= 0 or target_count <= 0:
        return []
    if n <= target_count:
        return list(range(n))
    # Higher distance threshold → fewer centroids.
    thresholds = (0.15, 0.25, 0.35, 0.45, 0.55, 0.65)
    best: list[int] | None = None
    best_delta = None
    lp = LeaderPicker()
    for thr in thresholds:
        if cancel_event is not None and cancel_event.is_set():
            raise _Cancelled()
        try:
            cents = [int(i) for i in lp.LazyBitVectorPick(fps, n, float(thr))]
        except Exception:
            try:

                def dist(i: int, j: int, _thr=thr) -> float:
                    if cancel_event is not None and cancel_event.is_set():
                        raise _Cancelled()
                    if i == j:
                        return 0.0
                    return _tanimoto_distance(fps[i], fps[j])

                cents = [
                    int(i) for i in lp.LazyPick(distFunc=dist, poolSize=n, threshold=float(thr))
                ]
            except _Cancelled:
                raise
            except Exception:
                continue
        if not cents:
            continue
        delta = abs(len(cents) - int(target_count))
        if best is None or delta < best_delta:
            best = cents
            best_delta = delta
        if len(cents) <= target_count * 2 and len(cents) >= max(target_count // 2, 1):
            best = cents
            break
    return best


def _random_candidate_indices(n: int, cap: int, seed: int) -> list[int]:
    if n <= cap:
        return list(range(n))
    rng = np.random.default_rng(0 if seed < 0 else int(seed))
    return sorted(int(i) for i in rng.choice(n, size=int(cap), replace=False))


def prefilter_candidate_indices(
    fps: Sequence,
    candidate_cap: int,
    *,
    seed: int = -1,
    cancel_event: threading.Event | None = None,
    leader_max_rows: int | None = None,
) -> list[int]:
    """
    Reduce a large fingerprint pool to at most *candidate_cap* indices.

    Prefers Leader (sphere-exclusion) centroids on moderate pools; for BindingDB-scale
    ``n`` uses a seeded random subsample so the GUI stays responsive.
    """
    n = len(fps)
    cap = max(1, int(candidate_cap))
    if n <= cap:
        return list(range(n))
    leader_limit = (
        int(leader_max_rows) if leader_max_rows is not None else _LEADER_PREFILTER_MAX_ROWS
    )
    if n > max(cap, leader_limit):
        return _random_candidate_indices(n, cap, seed)
    leaders = _leader_candidate_indices(fps, cap, cancel_event=cancel_event)
    if leaders and len(leaders) >= max(2, min(cap // 4, 32)):
        if len(leaders) > cap:
            rng = np.random.default_rng(0 if seed < 0 else int(seed))
            chosen = rng.choice(len(leaders), size=cap, replace=False)
            return sorted(int(leaders[i]) for i in chosen)
        return sorted(int(i) for i in leaders)
    return _random_candidate_indices(n, cap, seed)


def staged_maxmin_diverse_pick(
    fps: list,
    pick_size: int,
    *,
    candidate_cap: int = 10_000,
    seed: int = -1,
    cancel_event: threading.Event | None = None,
    on_pick: Callable[[int], None] | None = None,
) -> list[int]:
    """
    Approximate diverse pick: prefilter to ``candidate_cap`` then exact MaxMin.

    Returns indices into the original ``fps`` list.
    """
    n = len(fps)
    if pick_size <= 0:
        return []
    if pick_size >= n:
        return list(range(n))
    k = int(pick_size)
    cap = max(k, int(candidate_cap))
    if n <= cap:
        return maxmin_diverse_pick_bulk(
            fps, k, seed=seed, cancel_event=cancel_event, on_pick=on_pick
        )
    cand = prefilter_candidate_indices(fps, cap, seed=seed, cancel_event=cancel_event)
    if len(cand) < k:
        cand = _random_candidate_indices(n, max(k, cap), seed)
    cand_fps = [fps[i] for i in cand]
    local = maxmin_diverse_pick_bulk(
        cand_fps, k, seed=seed, cancel_event=cancel_event, on_pick=on_pick
    )
    return [int(cand[i]) for i in local]


def resolve_diverse_mode(mode: str, n: int, exact_max_rows: int | None = None) -> str:
    """Return ``exact`` or ``fast`` after resolving ``auto``."""
    m = (mode or "auto").strip().lower()
    if m not in ("exact", "fast", "auto"):
        m = "auto"
    if m != "auto":
        return m
    cap = (
        int(exact_max_rows)
        if exact_max_rows is not None
        else int(load_config().diverse_subset_exact_max_rows)
    )
    return "exact" if int(n) <= max(1, cap) else "fast"


def maxmin_diverse_pick_lazy(
    pool: list[DiverseSubsetPoolRow],
    fp_choice: str,
    pick_size: int,
    *,
    internal_key: str | None = None,
    seed: int = -1,
    first_picks: tuple[int, ...] = (),
    cancel_event: threading.Event | None = None,
    on_fp_computed: Callable[[], None] | None = None,
) -> list[int]:
    """
    MaxMin via RDKit :meth:`MaxMinPicker.LazyPick` (small pools only).

    Returns indices into ``pool``.
    """
    n = len(pool)
    if pick_size <= 0:
        return []
    if pick_size >= n:
        return list(range(n))
    k = int(pick_size)
    spec_key = internal_key
    if spec_key is None:
        spec = spec_for_label(fp_choice)
        spec_key = spec.internal_key if spec is not None else ""

    fp_by_index: dict[int, Any] = {}
    for i, row in enumerate(pool):
        if row.fp is not None:
            fp_by_index[i] = row.fp

    def get_fp(i: int) -> Any:
        if i in fp_by_index:
            return fp_by_index[i]
        if cancel_event is not None and cancel_event.is_set():
            raise _Cancelled()
        row = pool[i]
        mol = row.mol
        if mol is None:
            raise ValueError(f"No structure for OID {row.oid}")
        fp = fingerprint_bitvect_for_row(row.oid, mol, fp_choice)
        if fp is None:
            raise ValueError(f"Could not compute fingerprint for OID {row.oid}")
        fp_by_index[i] = fp
        if on_fp_computed is not None:
            on_fp_computed()
        return fp

    def dist(i: int, j: int) -> float:
        if cancel_event is not None and cancel_event.is_set():
            raise _Cancelled()
        if i == j:
            return 0.0
        return _tanimoto_distance(get_fp(i), get_fp(j))

    picker = MaxMinPicker()
    picks = picker.LazyPick(
        distFunc=dist,
        poolSize=n,
        pickSize=k,
        firstPicks=tuple(int(x) for x in first_picks),
        seed=int(seed),
    )
    return [int(i) for i in picks]


def maxmin_diverse_pick_indices(
    fps: list,
    pick_size: int,
    *,
    seed: int = -1,
    first_picks: tuple[int, ...] = (),
) -> list[int]:
    """MaxMin on precomputed fingerprints (tests and small pools)."""
    if len(fps) >= 128 or pick_size >= 256:
        return maxmin_diverse_pick_bulk(fps, pick_size, seed=seed)
    n = len(fps)
    if pick_size <= 0:
        return []
    if pick_size >= n:
        return list(range(n))

    def dist(i: int, j: int) -> float:
        if i == j:
            return 0.0
        return _tanimoto_distance(fps[i], fps[j])

    picker = MaxMinPicker()
    picks = picker.LazyPick(
        distFunc=dist,
        poolSize=n,
        pickSize=int(pick_size),
        firstPicks=tuple(int(x) for x in first_picks),
        seed=int(seed),
    )
    return [int(i) for i in picks]


def _mp_fp_batch(args: tuple) -> list[tuple[int, Any | None]]:
    """Compute fingerprints for a batch of pool indices in a child process."""
    items, fp_choice = args
    out: list[tuple[int, Any | None]] = []
    for idx, mol_bytes in items:
        if not mol_bytes:
            out.append((int(idx), None))
            continue
        try:
            mol = Chem.Mol(mol_bytes)
            fp = fingerprint_bitvect_for_ui_choice(mol, str(fp_choice)) if mol else None
        except Exception:
            fp = None
        out.append((int(idx), fp))
    return out


def materialize_pool_fingerprints(
    pool: list[DiverseSubsetPoolRow],
    fp_choice: str,
    internal_key: str,
    *,
    cancel_event: threading.Event | None = None,
    on_fp_done: Callable[[int, int], None] | None = None,
    use_process_pool: bool = False,
) -> tuple[list[Any], int, int]:
    """
    Return a full ``fps`` list aligned with ``pool``.

    Newly computed fingerprints are stored in the parent-process fingerprint cache.
    ``on_fp_done(done, total)`` is called as fingerprints are resolved.
    """
    n = len(pool)
    fps: list[Any | None] = [row.fp for row in pool]
    n_cached = sum(1 for fp in fps if fp is not None)
    missing: list[tuple[int, DiverseSubsetPoolRow]] = [
        (i, row) for i, row in enumerate(pool) if fps[i] is None
    ]
    if not missing:
        if on_fp_done is not None:
            on_fp_done(n, n)
        return fps, n_cached, 0

    n_computed = 0
    mp_ok = use_process_pool and len(missing) >= 32

    if mp_ok:
        batch_size = max(1, int(load_config().descriptor_process_pool_batch_size))
        items = [(i, row.mol.ToBinary() if row.mol is not None else b"") for i, row in missing]
        batches = [items[s : s + batch_size] for s in range(0, len(items), batch_size)]
        from ..platform_support.worker_budget import rdkit_process_workers

        proc_workers = rdkit_process_workers()
        ex = register_process_pool(ProcessPoolExecutor(max_workers=proc_workers))
        try:
            pending = {ex.submit(_mp_fp_batch, (batch, fp_choice)): batch for batch in batches}
            while pending:
                if should_terminate_process_pool(cancel_event):
                    raise _Cancelled()
                completed, pending = wait(pending, timeout=0.25, return_when=FIRST_COMPLETED)
                for fut in completed:
                    if fut.cancelled():
                        continue
                    for idx, fp in fut.result():
                        if fp is None:
                            continue
                        fps[idx] = fp
                        cache_store(pool[idx].oid, internal_key, fp)
                        n_computed += 1
                        if on_fp_done is not None:
                            on_fp_done(n_cached + n_computed, n)
        finally:
            shutdown_process_pool_executor(
                ex, kill_workers=should_terminate_process_pool(cancel_event)
            )
    else:
        max_workers = min(8, max(1, (os.cpu_count() or 4)))

        def _one(item: tuple[int, DiverseSubsetPoolRow]) -> tuple[int, Any | None]:
            i, row = item
            if row.mol is None:
                return i, None
            try:
                return i, fingerprint_bitvect_for_row(row.oid, row.mol, fp_choice)
            except Exception:
                return i, None

        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            pending = {ex.submit(_one, item): item for item in missing}
            while pending:
                if cancel_event is not None and cancel_event.is_set():
                    raise _Cancelled()
                completed, pending = wait(pending, timeout=0.08, return_when=FIRST_COMPLETED)
                for fut in completed:
                    if fut.cancelled():
                        continue
                    idx, fp = fut.result()
                    if fp is not None:
                        fps[idx] = fp
                        cache_store(pool[idx].oid, internal_key, fp)
                    n_computed += 1
                    if on_fp_done is not None:
                        on_fp_done(n_cached + n_computed, n)

    bad = [pool[i].oid for i, fp in enumerate(fps) if fp is None]
    if bad:
        raise ValueError(f"Could not compute fingerprints for {len(bad)} row(s) in this scope.")
    if on_fp_done is not None:
        on_fp_done(n, n)
    return fps, n_cached, n_computed


def run_diverse_subset_pick(
    pool: list[DiverseSubsetPoolRow],
    fp_choice: str,
    pick_size: int,
    internal_key: str,
    *,
    seed: int = -1,
    cancel_event: threading.Event | None = None,
    on_fp_done: Callable[[int, int], None] | None = None,
    on_pick_done: Callable[[int, int], None] | None = None,
    use_process_pool: bool = False,
    mode: str = "exact",
    candidate_cap: int | None = None,
) -> tuple[list[int], int, int]:
    """Materialize fingerprints, then MaxMin (exact or staged). Returns (pick indices, n_cached, n_computed)."""
    n = len(pool)
    pick_k = min(int(pick_size), n)
    fps, n_cached, n_computed = materialize_pool_fingerprints(
        pool,
        fp_choice,
        internal_key,
        cancel_event=cancel_event,
        on_fp_done=on_fp_done,
        use_process_pool=use_process_pool,
    )
    fp_base = n
    resolved = resolve_diverse_mode(mode, n)
    cap = (
        int(candidate_cap)
        if candidate_cap is not None
        else int(load_config().diverse_subset_fast_candidate_cap)
    )

    def _on_pick(done: int) -> None:
        if on_pick_done is not None:
            on_pick_done(fp_base + done, fp_base + pick_k)

    if resolved == "fast":
        pick_idx = staged_maxmin_diverse_pick(
            fps,
            pick_k,
            candidate_cap=cap,
            seed=seed,
            cancel_event=cancel_event,
            on_pick=_on_pick,
        )
    else:
        pick_idx = maxmin_diverse_pick_bulk(
            fps,
            pick_k,
            seed=seed,
            cancel_event=cancel_event,
            on_pick=_on_pick,
        )
    return pick_idx, n_cached, n_computed


def _diverse_subset_fp_process_pool_min_rows() -> int:
    cfg = load_config()
    return int(cfg.descriptor_fp_process_pool_min_rows or _PROCESS_POOL_MIN_ROWS)


class DiverseSubsetWorker(QRunnable):
    """Pick a maximally diverse subset by fingerprint MaxMin (off the UI thread)."""

    def __init__(
        self,
        request: DiverseSubsetRequest,
        signals: DiverseSubsetSignals,
        *,
        app: Any | None = None,
        cancel_event: threading.Event | None = None,
        progress_state=None,
    ):
        super().__init__()
        self.rows = request.rows
        self.oids = [int(o) for o in (request.oids or [])]
        self.structure_source = request.structure_source or "Structure"
        # Prefer mols_by_oid / structure_texts snapshots — never touch Qt from this thread.
        self.app = app
        self.mols_by_oid = request.mols_by_oid
        self.structure_texts = request.structure_texts
        self.fp_choice = request.fp_choice
        self.subset_size = max(0, int(request.subset_size))
        self.signals = signals
        self.onbits_by_oid = request.onbits_by_oid
        self.use_onbits_column = bool(request.use_onbits_column)
        self.mode = (request.mode or "auto").strip().lower()
        self.cancel_event = cancel_event
        self.progress_state = progress_state

    def _report(self, done: int, total: int, *, force: bool = False) -> None:
        report_tool_progress(
            message=_PROGRESS_LABEL,
            done=done,
            total=total,
            progress_state=self.progress_state,
            force_signal=force,
        )

    def _resolve_rows(self) -> list[tuple[int, Chem.Mol]]:
        if self.rows is not None:
            return list(self.rows)
        out: list[tuple[int, Chem.Mol]] = []
        seen: set[int] = set()
        mols_map = self.mols_by_oid
        if mols_map:
            oid_iter = self.oids if self.oids else list(mols_map.keys())
            for oid in oid_iter:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise _Cancelled()
                mol = mols_map.get(int(oid))
                if mol is not None:
                    oi = int(oid)
                    out.append((oi, mol))
                    seen.add(oi)
        texts = self.structure_texts
        if texts:
            from ..chem.molecule_conversion import parse_molecule_from_cell_text

            for oid, raw in texts:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise _Cancelled()
                oi = int(oid)
                if oi in seen:
                    continue
                mol = parse_molecule_from_cell_text(raw or "")
                if mol is not None:
                    out.append((oi, mol))
                    seen.add(oi)
        if out or mols_map is not None or texts is not None:
            return out
        # Legacy fallback (tests / callers that still pass app + oids).
        app = self.app
        if app is None:
            return []
        mols_fallback = getattr(app, "mols", None) or {}
        for oid in self.oids:
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise _Cancelled()
            mol = mols_fallback.get(int(oid))
            if mol is not None:
                out.append((int(oid), mol))
        return out

    def run(self) -> None:
        try:
            cancel_ev = self.cancel_event
            spec = spec_for_label(self.fp_choice)
            if spec is None:
                self.signals.failed.emit("Unknown fingerprint type.")
                return

            try:
                row_pairs = self._resolve_rows()
            except _Cancelled:
                self.signals.failed.emit("Cancelled.")
                return

            pool, err = build_diverse_subset_pool(
                row_pairs,
                self.fp_choice,
                onbits_by_oid=self.onbits_by_oid,
                require_onbits_column=self.use_onbits_column,
            )
            if err:
                self.signals.failed.emit(err)
                return

            n = len(pool)
            if n == 0:
                if self.use_onbits_column:
                    self.signals.failed.emit(
                        "No rows with valid on-bits values in the matching fingerprint column."
                    )
                else:
                    self.signals.failed.emit("No rows in scope.")
                return

            k = self.subset_size
            if k < 1:
                self.signals.failed.emit("Subset size must be at least 1.")
                return

            pick_k = min(k, n)
            internal_key = spec.internal_key
            progress_total = n + pick_k
            resolved_mode = resolve_diverse_mode(self.mode, n)

            if cancel_ev is not None and cancel_ev.is_set():
                self.signals.failed.emit("Cancelled.")
                return

            self._report(0, progress_total, force=True)

            use_fp_mp = (
                fingerprint_is_gil_heavy(self.fp_choice)
                or n >= _diverse_subset_fp_process_pool_min_rows()
            )

            def _on_fp(done: int, _tot: int) -> None:
                self._report(min(done, n), progress_total)

            def _on_pick(done: int, _tot: int) -> None:
                self._report(min(n + done, progress_total), progress_total)

            try:
                pick_idx, n_cache, n_computed = run_diverse_subset_pick(
                    pool,
                    self.fp_choice,
                    pick_k,
                    internal_key,
                    cancel_event=cancel_ev,
                    on_fp_done=_on_fp,
                    on_pick_done=_on_pick,
                    use_process_pool=use_fp_mp,
                    mode=resolved_mode,
                )
            except _Cancelled:
                self.signals.failed.emit("Cancelled.")
                return

            column_rows = [(pool[i].oid, str(rank + 1)) for rank, i in enumerate(pick_idx)]
            picked_oids = [oid for oid, _ in column_rows]
            self._report(progress_total, progress_total, force=True)
            self.signals.finished.emit(picked_oids, column_rows, n_cache, n_computed)
        except Exception as e:
            logger.exception("DiverseSubsetWorker failed")
            self.signals.failed.emit(str(e))
