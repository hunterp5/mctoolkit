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

"""Pure splitter size math for workspace plot docking (unit-testable, no Qt widgets)."""

from __future__ import annotations


def grow_horizontal_plot_split(
    table_w: int,
    plot_w: int,
    *,
    preferred: int | None,
    min_plot_w: int,
    content_pref_w: int,
    collapsed_plot_w: int,
    table_min: int = 200,
) -> tuple[int, int] | None:
    """Return new ``(table_w, plot_w)`` when the plot side should grow, else ``None``.

    Grow-only once the plot region is already open; never shrinks an open plot side.
    """
    if preferred is None and plot_w >= collapsed_plot_w:
        return None
    if preferred is not None:
        want = max(min_plot_w, int(preferred))
    else:
        want = max(min_plot_w, content_pref_w)
    if plot_w >= collapsed_plot_w and plot_w >= want:
        return None
    total = max(table_w + plot_w, want + table_min)
    new_plot = min(want, max(min_plot_w, total - table_min))
    if plot_w >= new_plot:
        return None
    new_table = max(table_min, total - new_plot)
    return new_table, new_plot


def grow_vertical_pane_split(
    sizes: list[int],
    pane_index: int,
    height: int,
    *,
    min_pane: int = 80,
    min_sibling: int = 80,
) -> list[int] | None:
    """Return new vertical splitter sizes when ``pane_index`` should grow toward ``height``."""
    if height < 50 or pane_index < 0 or pane_index >= len(sizes) or len(sizes) < 2:
        return None
    current = sizes[pane_index]
    if current >= min_pane and current >= int(height):
        return None
    total = sum(sizes) if sum(sizes) > 0 else max(height + min_sibling, min_pane + min_sibling)
    want = max(min_pane, min(int(height), total - min_sibling))
    if current >= want:
        return None
    new_sizes = [0] * len(sizes)
    new_sizes[pane_index] = want
    remain = total - want
    others = [i for i in range(len(sizes)) if i != pane_index]
    if not others:
        return None
    base, rem = divmod(max(remain, 0), len(others))
    for n, i in enumerate(others):
        new_sizes[i] = max(min_sibling, base + (1 if n < rem else 0))
    drift = total - sum(new_sizes)
    new_sizes[others[-1]] = max(min_sibling, new_sizes[others[-1]] + drift)
    return new_sizes
