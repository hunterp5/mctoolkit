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

from molmanager.ui.layout_geometry import grow_horizontal_plot_split, grow_vertical_pane_split


def test_horizontal_grow_only_when_plot_collapsed_or_preferred():
    assert grow_horizontal_plot_split(
        800,
        400,
        preferred=None,
        min_plot_w=420,
        content_pref_w=640,
        collapsed_plot_w=80,
    ) is None
    grown = grow_horizontal_plot_split(
        800,
        40,
        preferred=None,
        min_plot_w=420,
        content_pref_w=640,
        collapsed_plot_w=80,
    )
    assert grown is not None
    assert grown[1] >= 420


def test_horizontal_preferred_wins_over_content_pref():
    pair = grow_horizontal_plot_split(
        500,
        100,
        preferred=900,
        min_plot_w=420,
        content_pref_w=640,
        collapsed_plot_w=80,
    )
    assert pair is not None
    assert pair[1] >= 900 - 200  # bounded by total - table_min


def test_vertical_grow_only_toward_height():
    assert grow_vertical_pane_split([400, 400], 1, 350) is None
    out = grow_vertical_pane_split([400, 200], 1, 350)
    assert out is not None
    assert out[1] >= 350
