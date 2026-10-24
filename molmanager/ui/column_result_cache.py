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

"""Drop calculation caches when their result column is deleted."""

from __future__ import annotations

import re

from ..conformers.conformer_column_codec import is_packed_ensemble_header
from ..ionization import microstate_cache
from ..storage.ensemble_store import EnsembleStore

_SUFFIX_RE = re.compile(r" \(\d+\)$")
# Columns whose values are a view of the session Uni-pKa ensemble cache.
_IONIZATION_BASES = frozenset({"pka", "pi", "protonated"})


def column_base_name(header: str) -> str:
    """Header without a `` (n)`` duplicate suffix."""
    return _SUFFIX_RE.sub("", (header or "").strip())


def column_uses_ionization_cache(header: str) -> bool:
    """True for pKa, pI, Protonated, and ``% Protomer`` columns, including copies."""
    base = column_base_name(header).lower()
    if base in _IONIZATION_BASES:
        return True
    return base.startswith("% protomer")


def _other_ionization_column_remains(headers: list[str], deleted: str) -> bool:
    for header in headers:
        if header == deleted:
            continue
        if column_uses_ionization_cache(header):
            return True
    return False


def release_deleted_column_cache(app, header: str) -> tuple[dict | None, dict[int, str]]:
    """Forget caches that would make the next run of *header* look already finished.

    Returns ``(ionization snapshot or None, conformer payloads by row id)`` so
    undo can put them back. The ionization cache is cleared only when this was
    the last pKa, pI, Protonated, or protomer-population column.
    """
    ionization: dict | None = None
    headers = list(getattr(app, "headers", []) or [])
    if column_uses_ionization_cache(header) and not _other_ionization_column_remains(
        headers, header
    ):
        ionization = microstate_cache.snapshot()
        microstate_cache.clear()
    ensembles = _pop_ensemble_column(app, header) if is_packed_ensemble_header(header) else {}
    return ionization, ensembles


def restore_deleted_column_cache(
    app,
    header: str,
    ionization: dict | None,
    ensembles: dict[int, str],
) -> None:
    """Put back caches saved by :func:`release_deleted_column_cache`."""
    if ionization is not None:
        microstate_cache.replace(ionization)
    if not ensembles or not is_packed_ensemble_header(header):
        return
    from ..storage import ensure_confs_sidecar

    store = ensure_confs_sidecar(app)
    for oid, blob in ensembles.items():
        store[(int(oid), header)] = blob


def _pop_ensemble_column(app, header: str) -> dict[int, str]:
    store = getattr(app, "_confs_blocks_sidecar", None)
    if isinstance(store, EnsembleStore):
        return store.pop_column(header)
    if isinstance(store, dict):
        out: dict[int, str] = {}
        for key in list(store.keys()):
            if isinstance(key, tuple) and len(key) == 2 and key[1] == header:
                out[int(key[0])] = store.pop(key)
        return out
    return {}
