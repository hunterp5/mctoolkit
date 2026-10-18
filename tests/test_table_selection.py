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

"""Table selection helpers."""

from molmanager.ui.compound_table_model import CompoundTableModel
from molmanager.ui.table_selection import merge_sorted_row_indices


def test_filter_proxy_source_rows_for_row_spans():
    from molmanager.ui.filter_proxy_model import FilterProxyModel

    model = CompoundTableModel(["ID_HIDDEN", "Structure", "MW"])
    for oid in range(6):
        model.append_row(oid, {"MW": str(oid)})
    proxy = FilterProxyModel()
    proxy.setSourceModel(model)
    assert proxy.source_rows_for_row_spans([(1, 2), (4, 9)]) == [1, 2, 4, 5]
    proxy.set_visible_oids(frozenset({1, 3, 5}))
    assert proxy.source_rows_for_row_spans([(0, 0), (2, 5)]) == [1, 5]


def test_merge_sorted_row_indices_contiguous():
    assert merge_sorted_row_indices([0, 1, 2, 5, 6]) == [(0, 2), (5, 6)]


def test_merge_sorted_row_indices_single():
    assert merge_sorted_row_indices([42]) == [(42, 42)]


def test_invert_row_indices():
    n = 10
    selected = {1, 2, 3}
    inverted = [r for r in range(n) if r not in selected]
    assert inverted == [0, 4, 5, 6, 7, 8, 9]


def test_compound_model_highlighted_oids():
    model = CompoundTableModel(["ID_HIDDEN", "Structure", "MW"])
    model.append_row(1, {"MW": "1"})
    model.append_row(2, {"MW": "2"})
    assert not model.is_row_highlighted(0)
    model.set_highlighted_oids(frozenset({1}))
    assert model.is_row_highlighted(0)
    assert not model.is_row_highlighted(1)
    model.set_highlighted_oids(None)
    assert not model.is_row_highlighted(0)
