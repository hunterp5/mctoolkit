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

"""30° drawing grid shared with the structure depiction layout."""

from __future__ import annotations

import math

# depiction_layout turns a drawing in this step so bonds stay on a hexagonal grid.
GRID_STEP_RADIANS = math.radians(30.0)


def snap_to_hex_grid(angle: float) -> float:
    """Nearest multiple of 30° to *angle* (radians)."""
    return round(float(angle) / GRID_STEP_RADIANS) * GRID_STEP_RADIANS


def chain_points(
    origin: tuple[float, float],
    target: tuple[float, float],
    bond_px: float,
) -> list[tuple[float, float]]:
    """Zigzag carbons from *origin* toward *target*, one median bond apart.

    The axis snaps to the 30° grid. Successive bonds sit 30° either side of that
    axis, so the angle at each carbon is 120°. The origin itself is not included.
    A drag shorter than one projected step returns an empty list.
    """
    if bond_px <= 0:
        return []
    dx = float(target[0]) - float(origin[0])
    dy = float(target[1]) - float(origin[1])
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        return []
    axis = snap_to_hex_grid(math.atan2(dy, dx))
    along = bond_px * math.cos(GRID_STEP_RADIANS)
    count = int(round(dist / along)) if along > 1e-6 else 0
    if count < 1:
        return []
    x, y = float(origin[0]), float(origin[1])
    points: list[tuple[float, float]] = []
    for index in range(count):
        sign = 1.0 if index % 2 == 0 else -1.0
        angle = axis + sign * GRID_STEP_RADIANS
        x += math.cos(angle) * bond_px
        y += math.sin(angle) * bond_px
        points.append((x, y))
    return points
