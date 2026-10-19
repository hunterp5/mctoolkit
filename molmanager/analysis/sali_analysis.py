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
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with MolManager. If not, see <https://www.gnu.org/licenses/>.

"""Structure–Activity Landscape Index (SALI) pair metrics."""

from __future__ import annotations

import heapq
import math
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SaliPoint:
    """One molecule pair on the SALI landscape plot.

    ``signed_delta`` is activity B − A, or selectivity B − A when an off-target
    was supplied. ``delta_on`` and ``delta_off`` are set only for selectivity
    pairs (B − A on each column) and stay ``None`` for a single activity column.
    """

    pair_index: int
    oid_a: int
    oid_b: int
    similarity: float
    abs_delta: float
    signed_delta: float
    sali: float
    delta_on: float | None = None
    delta_off: float | None = None


def as_sali_activity(value: float, *, logarithmic: bool) -> float | None:
    """Activity on the scale SALI will difference.

    When *logarithmic* is set, return ``−log10(value)`` for a positive finite
    concentration. That matches pIC50 or pKi differences when every value in the
    column shares one unit. Non-positive values cannot be converted.
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if not logarithmic:
        return number
    if number <= 0.0:
        return None
    converted = -math.log10(number)
    if not math.isfinite(converted):
        return None
    return converted


def sali_index(
    abs_delta: float,
    similarity: float,
    *,
    eps: float = 1e-9,
) -> float:
    """
    Structure–Activity Landscape Index.

    ``SALI = |Δactivity| / (1 − similarity)``. When similarity is ≥ ``1 − eps``,
    returns a large finite sentinel so near-identical structures with any Δ remain
    visible rather than producing ``inf``.
    """
    d = abs(float(abs_delta))
    sim = float(similarity)
    denom = 1.0 - sim
    if denom <= float(eps):
        return d / float(eps)
    return d / denom


def _sali_rank_key(point: SaliPoint) -> tuple[float, float, float, int, int]:
    """Larger is better; matches descending SALI, |Δ|, similarity, then smaller OIDs."""
    return (
        float(point.sali),
        float(point.abs_delta),
        float(point.similarity),
        -int(point.oid_a),
        -int(point.oid_b),
    )


def accumulate_sali_candidate(
    heap: list,
    oid_a: int,
    oid_b: int,
    similarity: float,
    act_a: float,
    act_b: float,
    *,
    min_similarity: float,
    min_activity_difference: float,
    max_pairs: int,
    off_a: float | None = None,
    off_b: float | None = None,
) -> None:
    """Push one unordered pair into *heap*, keeping at most *max_pairs* best SALI values.

    ``max_pairs <= 0`` keeps every qualifying pair. *heap* stores ``(rank_key, SaliPoint)``.
    Canonical order is ``oid_a < oid_b``. With no off-target values,
    ``signed_delta = act_b - act_a``. When both off-target values are set,
    selectivity is on-target minus off-target and ``signed_delta`` is the
    selectivity difference. ``min_activity_difference`` applies to that
    absolute difference.
    """
    a, b = int(oid_a), int(oid_b)
    if a == b:
        return
    sim_f = float(similarity)
    if sim_f < float(min_similarity):
        return
    oa = None if off_a is None else float(off_a)
    ob = None if off_b is None else float(off_b)
    if (oa is None) != (ob is None):
        return
    va, vb = float(act_a), float(act_b)
    if a > b:
        a, b = b, a
        va, vb = vb, va
        oa, ob = ob, oa
    delta_on = None
    delta_off = None
    if oa is not None and ob is not None:
        delta_on = vb - va
        delta_off = ob - oa
        signed = delta_on - delta_off
    else:
        signed = vb - va
    abs_delta = abs(signed)
    if abs_delta < float(min_activity_difference):
        return
    point = SaliPoint(
        pair_index=0,
        oid_a=a,
        oid_b=b,
        similarity=sim_f,
        abs_delta=abs_delta,
        signed_delta=float(signed),
        sali=sali_index(abs_delta, sim_f),
        delta_on=None if delta_on is None else float(delta_on),
        delta_off=None if delta_off is None else float(delta_off),
    )
    key = _sali_rank_key(point)
    item = (key, point)
    limit = int(max_pairs)
    if limit <= 0:
        heap.append(item)
        return
    if len(heap) < limit:
        heapq.heappush(heap, item)
        return
    if key > heap[0][0]:
        heapq.heapreplace(heap, item)


def finalize_sali_points(heap: list) -> list[SaliPoint]:
    """Sort accumulated candidates by descending SALI and assign ``pair_index``."""
    items = sorted(heap, key=lambda it: it[0], reverse=True)
    return [
        SaliPoint(
            pair_index=i,
            oid_a=p.oid_a,
            oid_b=p.oid_b,
            similarity=p.similarity,
            abs_delta=p.abs_delta,
            signed_delta=p.signed_delta,
            sali=p.sali,
            delta_on=p.delta_on,
            delta_off=p.delta_off,
        )
        for i, (_key, p) in enumerate(items)
    ]


def build_sali_points(
    records: Sequence[tuple[int, float]],
    similarities: Sequence[tuple[int, int, float]],
    *,
    min_similarity: float = 0.0,
    min_activity_difference: float = 0.0,
    max_pairs: int = 0,
    off_by_oid: dict[int, float] | None = None,
    treat_logarithmically: bool = False,
) -> list[SaliPoint]:
    """
    Build SALI plot points from activities and pairwise similarities.

    *records* is ``(oid, activity)`` in any order. *similarities* is
    ``(oid_a, oid_b, similarity)`` for unordered pairs. ``max_pairs`` of 0 keeps
    all qualifying pairs; otherwise the highest-SALI pairs are retained.

    When *off_by_oid* is set, activity is the on-target column and selectivity
    is on-target minus off-target. Pairs missing either value are dropped.
    *treat_logarithmically* converts each positive value with ``−log10`` first.
    """
    act_by_oid: dict[int, float] = {}
    for oid, act in records:
        converted = as_sali_activity(act, logarithmic=treat_logarithmically)
        if converted is not None:
            act_by_oid[int(oid)] = converted
    offs = None
    if off_by_oid is not None:
        offs = {}
        for oid, off in off_by_oid.items():
            converted = as_sali_activity(off, logarithmic=treat_logarithmically)
            if converted is not None:
                offs[int(oid)] = converted
    min_sim = max(0.0, float(min_similarity))
    min_dact = max(0.0, float(min_activity_difference))
    heap: list = []
    for oid_a, oid_b, sim in similarities:
        a, b = int(oid_a), int(oid_b)
        if a not in act_by_oid or b not in act_by_oid:
            continue
        if offs is not None and (a not in offs or b not in offs):
            continue
        accumulate_sali_candidate(
            heap,
            a,
            b,
            sim,
            act_by_oid[a],
            act_by_oid[b],
            min_similarity=min_sim,
            min_activity_difference=min_dact,
            max_pairs=max_pairs,
            off_a=None if offs is None else offs[a],
            off_b=None if offs is None else offs[b],
        )
    return finalize_sali_points(heap)
