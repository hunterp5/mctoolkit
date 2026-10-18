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

"""Local timing spans for workspace layout, dock/undock, and plot resize paths.

Enabled only when ``MOLMANAGER_LAYOUT_PERF=1``. Spans log at DEBUG level and keep an
in-process history (no file or network output) so ``scripts/bench_docking.py`` can
report percentiles.
"""

from __future__ import annotations

import logging
import os
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from typing import Iterator

logger = logging.getLogger(__name__)

LAYOUT_PERF_ENV = "MOLMANAGER_LAYOUT_PERF"
_HISTORY_LIMIT = 2000
_history: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_HISTORY_LIMIT))
_forced: bool | None = None


def layout_perf_enabled() -> bool:
    """True when layout timing spans should be recorded."""
    if _forced is not None:
        return _forced
    return (os.environ.get(LAYOUT_PERF_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def set_layout_perf_enabled(enabled: bool | None) -> None:
    """Force recording on/off (``None`` restores the environment-variable default)."""
    global _forced
    _forced = enabled


@contextmanager
def perf_span(name: str) -> Iterator[None]:
    """Time the enclosed block as ``name`` when layout perf recording is enabled."""
    if not layout_perf_enabled():
        yield
        return
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        record_span(name, elapsed_ms)


def record_span(name: str, elapsed_ms: float) -> None:
    """Store one measurement (also used for timings reported by web pages)."""
    if not layout_perf_enabled():
        return
    _history[name].append(float(elapsed_ms))
    logger.debug("layout perf %s: %.2f ms", name, elapsed_ms)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, round(fraction * (len(sorted_values) - 1))))
    return sorted_values[index]


def span_summary() -> dict[str, dict[str, float]]:
    """Return ``{name: {count, p50, p95, max}}`` in milliseconds for recorded spans."""
    summary: dict[str, dict[str, float]] = {}
    for name, values in _history.items():
        ordered = sorted(values)
        if not ordered:
            continue
        summary[name] = {
            "count": float(len(ordered)),
            "p50": _percentile(ordered, 0.50),
            "p95": _percentile(ordered, 0.95),
            "max": ordered[-1],
        }
    return summary


def reset_spans() -> None:
    """Drop all recorded measurements."""
    _history.clear()
