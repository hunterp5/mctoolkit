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

"""Order Render 2D subprocess tasks so the rows on screen are drawn first."""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable

RenderTask = tuple[list[tuple[int, object]], int, int, bool]


class PriorityRenderPlan:
    """Hand out ``(rows, w, h, want_scenes)`` render tasks, viewport rows first.

    Rows are grouped by depict size because one task draws every molecule at one size;
    zoomed rows are drawn at 2x. The GUI thread calls :meth:`prioritize` with the rows
    on screen while the render runs. Those rows go out next in tasks of at most
    *priority_batch_size*, so several processes draw the viewport at once. Once no
    prioritized row is left, the rest go out in table order in full *batch_size* tasks.
    """

    def __init__(
        self,
        rows: Iterable[tuple[int, object, int, int]],
        *,
        batch_size: int,
        priority_batch_size: int,
        want_scenes: bool,
    ) -> None:
        self._batch_size = max(1, int(batch_size))
        self._priority_batch_size = max(1, min(int(priority_batch_size), self._batch_size))
        self._want_scenes = bool(want_scenes)
        self._lock = threading.Lock()
        self._payload: dict[int, object] = {}
        self._size: dict[int, tuple[int, int]] = {}
        self._seq: dict[int, int] = {}
        self._by_size: dict[tuple[int, int], deque[int]] = {}
        self._priority: deque[int] = deque()
        for seq, (oid, payload, w, h) in enumerate(rows):
            oid = int(oid)
            if oid in self._payload:
                continue
            size = (int(w), int(h))
            self._payload[oid] = payload
            self._size[oid] = size
            self._seq[oid] = seq
            self._by_size.setdefault(size, deque()).append(oid)

    def __len__(self) -> int:
        with self._lock:
            return len(self._payload)

    def prioritize(self, oids: Iterable[int]) -> None:
        """Draw *oids* next, replacing the previous request; finished rows are ignored."""
        with self._lock:
            self._priority = deque(int(oid) for oid in oids if int(oid) in self._payload)

    def next_task(self) -> RenderTask | None:
        """The next task to submit, or ``None`` once every row has been handed out."""
        with self._lock:
            taken = self._take_priority() or self._take_in_order()
        if taken is None:
            return None
        rows, (w, h) = taken
        return rows, w, h, self._want_scenes

    def _pop(self, oid: int) -> object:
        del self._size[oid]
        del self._seq[oid]
        return self._payload.pop(oid)

    def _take_priority(self) -> tuple[list, tuple[int, int]] | None:
        queue = self._priority
        while queue and queue[0] not in self._payload:
            queue.popleft()
        if not queue:
            return None
        size = self._size[queue[0]]
        rows: list[tuple[int, object]] = []
        other_sizes: list[int] = []
        while queue and len(rows) < self._priority_batch_size:
            oid = queue.popleft()
            if oid not in self._payload:
                continue
            if self._size[oid] != size:
                other_sizes.append(oid)
                continue
            rows.append((oid, self._pop(oid)))
        queue.extendleft(reversed(other_sizes))
        return rows, size

    def _take_in_order(self) -> tuple[list, tuple[int, int]] | None:
        best_size: tuple[int, int] | None = None
        best_seq = -1
        for size, queue in self._by_size.items():
            while queue and queue[0] not in self._payload:
                queue.popleft()
            if queue and (best_size is None or self._seq[queue[0]] < best_seq):
                best_size, best_seq = size, self._seq[queue[0]]
        if best_size is None:
            return None
        queue = self._by_size[best_size]
        rows: list[tuple[int, object]] = []
        while queue and len(rows) < self._batch_size:
            oid = queue.popleft()
            if oid in self._payload:
                rows.append((oid, self._pop(oid)))
        return rows, best_size
