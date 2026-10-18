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

"""SelectionStore semantics."""

from __future__ import annotations

import pytest

pytest.importorskip("PyQt5.QtCore")

from molmanager.ui.selection_store import ORIGIN_TABLE, SelectionStore


@pytest.fixture
def store(qapp):  # noqa: ARG001
    return SelectionStore()


def _record(store: SelectionStore) -> list[object]:
    origins: list[object] = []
    store.changed.connect(origins.append)
    return origins


def test_set_emits_once_per_change_with_origin(store) -> None:
    origins = _record(store)
    assert store.set({1, 2}, origin=ORIGIN_TABLE) is True
    assert store.set([2, 1], origin="plot") is False
    assert origins == [ORIGIN_TABLE]
    assert store.oids == frozenset({1, 2})
    assert store.version == 1


def test_add_remove_toggle_clear(store) -> None:
    store.set({1})
    store.add({2, 3})
    assert store.oids == frozenset({1, 2, 3})
    store.remove({1})
    assert store.oids == frozenset({2, 3})
    store.toggle(2)
    store.toggle(4)
    assert store.oids == frozenset({3, 4})
    assert store.contains(4) and not store.contains(2)
    assert store.count() == 2
    store.clear()
    assert store.is_empty()


def test_prune_keeps_present_oids(store) -> None:
    store.set({1, 2, 3})
    assert store.prune(lambda oids: oids & {2}) is True
    assert store.oids == frozenset({2})


def test_prune_skips_lookup_when_empty(store) -> None:
    def fail(_oids):
        raise AssertionError("prune should not query presence for an empty selection")

    assert store.prune(fail) is False


def test_empty_store_is_truthy(store) -> None:
    """``if app.selection_store:`` must not mean "has a selection"."""
    assert bool(store) is True
