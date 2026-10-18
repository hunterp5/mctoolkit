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

"""plot_table_sync helpers."""

from __future__ import annotations

from molmanager.ui.plot_table_sync import (
    apply_table_selection_for_source_rows,
    clear_table_selection_from_plot,
    point_indices_for_oids,
    selected_oids_for_plot,
    selection_visual_push_key,
)
from molmanager.ui.selection_store import SelectionStore


def test_point_indices_for_oids() -> None:
    plotted = [10, 20, 30]
    assert point_indices_for_oids(plotted, {20, 99}) == {1}
    assert point_indices_for_oids(plotted, frozenset()) == set()
    assert point_indices_for_oids([], {10}) == set()


def test_selection_visual_push_key_stable_for_same_set() -> None:
    assert selection_visual_push_key(set()) == (0, 0)
    a = selection_visual_push_key({1, 2, 3})
    b = selection_visual_push_key({3, 2, 1})
    assert a == b
    assert a[0] == 3
    assert selection_visual_push_key({1, 2, 3, 4}) != a


def test_point_indices_for_oids_uses_index_and_partners() -> None:
    from molmanager.ui.plot_table_sync import build_oid_point_index

    plotted = [10, 20, 30]
    partners = [11, 21, 31]
    index = build_oid_point_index(plotted, partners)
    assert point_indices_for_oids(plotted, {21}, oid_index=index) == {1}
    assert point_indices_for_oids(plotted, {10, 31}, oid_index=index) == {0, 2}


def _app_with_store(selected: set[int], oids_by_row: dict[int, int]):
    """MagicMock window with a real ``SelectionStore`` and row → OID mapping."""
    from unittest.mock import MagicMock

    app = MagicMock()
    app.selection_store = SelectionStore()
    app.selection_store.set(selected)
    app._oids_for_source_rows.side_effect = lambda rows: frozenset(oids_by_row[r] for r in rows)
    return app


def test_selected_oids_for_plot_reads_store(qapp) -> None:  # noqa: ARG001
    app = _app_with_store({10, 30}, {})
    assert selected_oids_for_plot(app) == {10, 30}


def test_apply_table_selection_skips_identical_selection(qapp) -> None:  # noqa: ARG001
    """Re-applying the same plot selection must not scroll / re-select (snap-back loop)."""
    app = _app_with_store({10, 30}, {0: 10, 2: 30})

    apply_table_selection_for_source_rows(app, [0, 2], scroll=True)

    app.table.scrollTo.assert_not_called()
    app.select_table_rows.assert_not_called()


def test_apply_table_selection_selects_immediately_with_origin(qapp) -> None:  # noqa: ARG001
    """Plot→table is not debounced; the plot is the origin and the table is not revealed."""
    app = _app_with_store({10}, {0: 10, 1: 20})
    plot = object()

    apply_table_selection_for_source_rows(app, [1, 0], scroll=False, origin=plot)

    app.select_table_rows.assert_called_once_with([0, 1], origin=plot, reveal=False)


def test_clear_table_selection_from_plot_passes_origin() -> None:
    from unittest.mock import MagicMock

    app = MagicMock()
    plot = object()
    clear_table_selection_from_plot(app, origin=plot)
    app.clear_table_selection.assert_called_once_with(origin=plot)
