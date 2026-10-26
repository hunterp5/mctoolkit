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

"""Named sets of table row ids (Lists menu)."""

from __future__ import annotations

from collections.abc import Iterable

MAX_LIST_NAME_LENGTH = 120


def normalize_list_name(name: object) -> str:
    """Collapse whitespace and cap length so a list name is safe as a menu label."""
    text = " ".join(str(name or "").split())
    return text[:MAX_LIST_NAME_LENGTH]


class RowListStore:
    """Creation-ordered named row lists. OIDs inside a list stay sorted and unique."""

    def __init__(self) -> None:
        self._order: list[str] = []
        self._oids: dict[str, list[int]] = {}

    def names(self) -> list[str]:
        return list(self._order)

    def oids(self, name: str) -> list[int]:
        return list(self._oids.get(name, ()))

    def __len__(self) -> int:
        return len(self._order)

    def add(self, name: str, oids: Iterable[int]) -> tuple[bool, int]:
        """Union *oids* into *name*. Return ``(created, n_new)``."""
        key = normalize_list_name(name)
        if not key:
            raise ValueError("List name is empty.")
        created = key not in self._oids
        have = set(self._oids.get(key, ()))
        added = 0
        for raw in oids:
            oid = int(raw)
            if oid in have:
                continue
            have.add(oid)
            added += 1
        if created:
            self._order.append(key)
        self._oids[key] = sorted(have)
        return created, added

    def remove(self, name: str, oids: Iterable[int]) -> int:
        """Drop *oids* from *name*. Return how many ids were removed.

        An unknown list is left unchanged and returns 0. The list remains when
        every id is removed.
        """
        key = normalize_list_name(name)
        current = self._oids.get(key)
        if not key or current is None:
            return 0
        drop: set[int] = set()
        for raw in oids:
            try:
                drop.add(int(raw))
            except (TypeError, ValueError):
                continue
        if not drop:
            return 0
        kept = [oid for oid in current if oid not in drop]
        removed = len(current) - len(kept)
        if removed:
            self._oids[key] = kept
        return removed

    def retain(self, names: Iterable[str]) -> list[str]:
        """Keep only *names* that already exist. Return the names that were removed."""
        keep = {name for name in names if name in self._oids}
        removed = [name for name in self._order if name not in keep]
        self._order = [name for name in self._order if name in keep]
        for name in removed:
            del self._oids[name]
        return removed

    def apply_edits(
        self, kept: Iterable[tuple[str, str]]
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Keep *kept* as ``(current_name, new_name)`` pairs, in that order.

        Lists left out are deleted. A list may take the name of one that is deleted
        in the same edit. The store changes only after every new name is valid.
        Return ``(deleted_names, renames)`` with renames as ``(old, new)`` pairs.
        """
        pairs = [(str(old), normalize_list_name(new)) for old, new in kept]
        for _old, new in pairs:
            if not new:
                raise ValueError("List name is empty.")
        seen: set[str] = set()
        for _old, new in pairs:
            if new in seen:
                raise ValueError(f'A list named "{new}" already exists.')
            seen.add(new)
        keep_orig = {old for old, _new in pairs}
        deleted = [name for name in self._order if name not in keep_orig]
        new_order: list[str] = []
        new_oids: dict[str, list[int]] = {}
        renames: list[tuple[str, str]] = []
        for old, new in pairs:
            oids = self._oids.get(old)
            if oids is None:
                continue
            new_oids[new] = oids
            new_order.append(new)
            if new != old:
                renames.append((old, new))
        self._order = new_order
        self._oids = new_oids
        return deleted, renames

    def clear(self) -> None:
        self._order.clear()
        self._oids.clear()

    def to_session(self, *, keep_oids: set[int] | None = None) -> list[dict]:
        """Session payload. Lists with no remaining ids are omitted when *keep_oids* is set."""
        out: list[dict] = []
        for name in self._order:
            oids = self._oids[name]
            if keep_oids is not None:
                oids = [oid for oid in oids if oid in keep_oids]
                if not oids:
                    continue
            out.append({"name": name, "oids": list(oids)})
        return out

    def load_session(self, payload: object) -> None:
        """Replace contents from a session payload. Invalid entries are skipped."""
        self.clear()
        if not isinstance(payload, list):
            return
        for item in payload:
            if not isinstance(item, dict):
                continue
            name = normalize_list_name(item.get("name"))
            if not name or name in self._oids:
                continue
            raw_oids = item.get("oids") or []
            if not isinstance(raw_oids, list):
                continue
            seen: set[int] = set()
            oids: list[int] = []
            for raw in raw_oids:
                try:
                    oid = int(raw)
                except (TypeError, ValueError):
                    continue
                if oid in seen:
                    continue
                seen.add(oid)
                oids.append(oid)
            self._order.append(name)
            self._oids[name] = sorted(oids)
