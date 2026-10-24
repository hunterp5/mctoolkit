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

"""Deleting a result column drops the cache that would skip the next run."""

from __future__ import annotations

from types import SimpleNamespace

from molmanager.ionization import microstate_cache as mc
from molmanager.ui.column_result_cache import (
    release_deleted_column_cache,
    restore_deleted_column_cache,
)


def _app(headers: list[str], sidecar: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(headers=list(headers), _confs_blocks_sidecar=sidecar)


def test_deleting_last_pka_column_clears_ionization_cache() -> None:
    mc.clear()
    mc.store("CCO", None)
    app = _app(["ID_HIDDEN", "Structure"])
    snapshot, ensembles = release_deleted_column_cache(app, "pKa")
    assert ensembles == {}
    assert mc.lookup("CCO") == (False, None)
    restore_deleted_column_cache(app, "pKa", snapshot, ensembles)
    assert mc.lookup("CCO") == (True, None)
    mc.clear()


def test_deleting_pka_copy_keeps_cache_while_another_pka_column_remains() -> None:
    mc.clear()
    mc.store("CCO", None)
    app = _app(["ID_HIDDEN", "Structure", "pKa"])
    snapshot, _ensembles = release_deleted_column_cache(app, "pKa (1)")
    assert snapshot is None
    assert mc.lookup("CCO") == (True, None)
    mc.clear()


def test_deleting_confs_column_drops_only_that_sidecar() -> None:
    sidecar = {(1, "confs"): "old", (1, "superpose"): "keep", (2, "confs"): "also"}
    app = _app(["ID_HIDDEN", "Structure", "superpose"], sidecar)
    _snapshot, ensembles = release_deleted_column_cache(app, "confs")
    assert ensembles == {1: "old", 2: "also"}
    assert (1, "confs") not in sidecar
    assert sidecar[(1, "superpose")] == "keep"
    restore_deleted_column_cache(app, "confs", None, ensembles)
    store = app._confs_blocks_sidecar
    try:
        assert store[(1, "confs")] == "old"
        assert store[(2, "confs")] == "also"
        assert store[(1, "superpose")] == "keep"
    finally:
        close = getattr(store, "close", None)
        if callable(close):
            close()
