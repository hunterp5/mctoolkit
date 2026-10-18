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

"""Single source of truth for which table entries (compound OIDs) are selected."""

from __future__ import annotations

from collections.abc import Callable, Iterable

from PyQt5.QtCore import QObject, pyqtSignal

#: Origin tag for changes made by the user in the compound table.
ORIGIN_TABLE = "table"


def _as_oid_set(oids: Iterable[int]) -> frozenset[int]:
    return frozenset(int(oid) for oid in oids)


class SelectionStore(QObject):
    """Entry selection keyed by compound OID, independent of table rows and filters.

    Every selection writer (table input, plots, search, tools) goes through this object and
    every reader asks it, so all views agree on one set. ``changed`` fires once per actual
    change with the writer's ``origin`` (any object, e.g. :data:`ORIGIN_TABLE` or the plot
    that made the change) so a view can skip repainting a change it made itself.

    Deliberately has no ``__len__``/``__bool__``: a ``QObject`` that is falsy when empty
    would break ``if store:`` presence checks. Use :meth:`count` / :meth:`is_empty`.
    """

    changed = pyqtSignal(object)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._oids: frozenset[int] = frozenset()
        self._version = 0

    @property
    def oids(self) -> frozenset[int]:
        return self._oids

    @property
    def version(self) -> int:
        """Increments on every change; lets consumers detect missed updates cheaply."""
        return self._version

    def count(self) -> int:
        return len(self._oids)

    def is_empty(self) -> bool:
        return not self._oids

    def contains(self, oid: int) -> bool:
        return int(oid) in self._oids

    def set(self, oids: Iterable[int], *, origin: object = None) -> bool:
        """Replace the selection. Returns ``True`` (and emits ``changed``) if it differs."""
        new = oids if isinstance(oids, frozenset) else _as_oid_set(oids)
        if new == self._oids:
            return False
        self._oids = new
        self._version += 1
        self.changed.emit(origin)
        return True

    def add(self, oids: Iterable[int], *, origin: object = None) -> bool:
        return self.set(self._oids | _as_oid_set(oids), origin=origin)

    def remove(self, oids: Iterable[int], *, origin: object = None) -> bool:
        return self.set(self._oids - _as_oid_set(oids), origin=origin)

    def toggle(self, oid: int, *, origin: object = None) -> bool:
        return self.set(self._oids ^ {int(oid)}, origin=origin)

    def clear(self, *, origin: object = None) -> bool:
        return self.set(frozenset(), origin=origin)

    def prune(self, present: Callable[[frozenset[int]], frozenset[int]], *, origin=None) -> bool:
        """Drop OIDs whose rows no longer exist; *present* returns the surviving subset."""
        if not self._oids:
            return False
        return self.set(present(self._oids), origin=origin)
