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

"""IUPAC GR-3 ring geometry: bond-length polygons, large rings, spiro/fusion layout."""

from __future__ import annotations

import math
from itertools import combinations
from typing import Sequence

from .constants import SKETCH_MEDIAN_BOND_PX

# Preferred screen snap for ring→substituent bonds (GR-4.2.1 software warning).
SUBSTITUENT_SNAP_DEG = (0.0, 30.0, 60.0, 90.0, 120.0, 150.0, 180.0)
SUBSTITUENT_SNAP_TOL_DEG = 6.0

# GR-3.3.2: prefer 120°; else regular-pentagon/heptagon/octagon angles (±~10°).
PREFERRED_RING_BOND_ANGLES_DEG = (108.0, 120.0, 129.0, 135.0)

_HEX_TURN_CACHE: dict[int, tuple[float, ...]] = {}


def ring_circumradius_for_bond_length(n_atoms: int, bond_length: float) -> float:
    """
    Circumradius of a regular *n*-gon whose edge length equals *bond_length* (GR-1.1).

    ``R = bond / (2 sin(π/n))``.
    """
    n = max(3, int(n_atoms))
    bl = max(float(bond_length), 1.0)
    return bl / (2.0 * math.sin(math.pi / n))


def regular_ring_offsets_y_up(
    n_atoms: int,
    *,
    bond_length: float = SKETCH_MEDIAN_BOND_PX,
    ang0: float | None = None,
) -> list[tuple[float, float]]:
    """
    Vertex offsets (dx, dy) for a regular ring in Y-up chemistry space.

    Caller maps to screen with ``y_screen = cy - dy``.
    """
    from .iupac_style import iupac_ring_vertex_offset

    n = max(3, int(n_atoms))
    r = ring_circumradius_for_bond_length(n, bond_length)
    a0 = float(iupac_ring_vertex_offset(n) if ang0 is None else ang0)
    return [
        (r * math.cos(a0 + 2.0 * math.pi * i / n), r * math.sin(a0 + 2.0 * math.pi * i / n))
        for i in range(n)
    ]


def _equalize_polygon_edges(
    pts: list[tuple[float, float]],
    *,
    bond_length: float,
    iterations: int = 24,
) -> list[tuple[float, float]]:
    """Iteratively nudge vertices so each edge approaches *bond_length* (GR-1.1)."""
    if len(pts) < 3:
        return pts
    bl = max(float(bond_length), 1.0)
    cur = [list(p) for p in pts]
    n = len(cur)
    for _ in range(max(1, iterations)):
        for i in range(n):
            j = (i + 1) % n
            dx = cur[j][0] - cur[i][0]
            dy = cur[j][1] - cur[i][1]
            length = math.hypot(dx, dy) or 1e-6
            corr = 0.5 * (1.0 - bl / length)
            mx, my = dx * corr, dy * corr
            cur[i][0] += mx
            cur[i][1] += my
            cur[j][0] -= mx
            cur[j][1] -= my
        cx = sum(p[0] for p in cur) / n
        cy = sum(p[1] for p in cur) / n
        for p in cur:
            p[0] -= cx
            p[1] -= cy
    return [(p[0], p[1]) for p in cur]


def _polyline_from_exterior_turns(
    turns_deg: Sequence[float],
    *,
    bond_length: float,
) -> list[tuple[float, float]]:
    """Open walk of *len(turns)* unit bonds; apply exterior turn before each step."""
    bl = max(float(bond_length), 1.0)
    x = y = 0.0
    heading = 0.0
    pts: list[tuple[float, float]] = [(0.0, 0.0)]
    for turn in turns_deg:
        heading += math.radians(float(turn))
        x += bl * math.cos(heading)
        y += bl * math.sin(heading)
        pts.append((x, y))
    return pts


def _force_close_polygon(
    open_pts: Sequence[tuple[float, float]],
) -> list[tuple[float, float]]:
    """
    Distribute closure error along an *n+1*-point walk so the last vertex meets the first.

    ``open_pts`` has n+1 samples (start duplicated at end ideally); returns n vertices.
    """
    if len(open_pts) < 4:
        return list(open_pts[:-1]) if open_pts else []
    n = len(open_pts) - 1
    dx = open_pts[0][0] - open_pts[n][0]
    dy = open_pts[0][1] - open_pts[n][1]
    out: list[tuple[float, float]] = []
    for i in range(n):
        f = i / float(n)
        out.append((open_pts[i][0] + dx * f, open_pts[i][1] + dy * f))
    return out


def _hex_lattice_turn_sequence(n: int) -> list[float] | None:
    """
    Exterior turns (±60°) for a closed equal-bond hex-lattice ring (GR-3.3.2, 120° angles).

    Requires even *n* ≥ 8. Rights (reentrants) are chosen for closure and even spacing.
    """
    n = int(n)
    if n < 8 or n % 2 != 0:
        return None
    cached = _HEX_TURN_CACHE.get(n)
    if cached is not None:
        return list(cached)
    n_r = (n - 6) // 2
    if n_r < 0:
        return None
    best: list[float] | None = None
    best_var = 1e18
    for rights in combinations(range(n), n_r):
        turns = [-60.0 if i in rights else 60.0 for i in range(n)]
        walk = _polyline_from_exterior_turns(turns, bond_length=1.0)
        err = math.hypot(walk[-1][0] - walk[0][0], walk[-1][1] - walk[0][1])
        if err > 1e-6:
            continue
        rs = sorted(rights)
        if n_r == 0:
            var = 0.0
        else:
            gaps = [(rs[(i + 1) % n_r] - rs[i]) % n for i in range(n_r)]
            mean = n / float(n_r)
            var = sum((g - mean) ** 2 for g in gaps)
        if var < best_var:
            best_var = var
            best = turns
            if var < 1e-9:
                break
    if best is None:
        return None
    _HEX_TURN_CACHE[n] = tuple(best)
    return list(best)


def _odd_large_ring_turns(n: int) -> list[float]:
    """
    Exterior turns for odd large rings (GR-3.3.2).

    Mixes 120° (turn ±60°) with pentagon/octagon turns (72°/45°) so the sum is 360°,
    then the polyline is force-closed and edge-equalized.
    """
    n = max(9, int(n))
    # Prefer one 72° among mostly ±60°, with enough reentrants for a puckered look.
    n_r = max(1, (n - 5) // 2)
    turns: list[float] = []
    # Pattern inspired by fused 5/6 perimeters: mostly lefts, spaced rights, one 72°.
    special = n // 2
    for i in range(n):
        if i == special:
            turns.append(72.0)
        elif n_r > 0 and i % max(2, n // n_r) == 0 and turns.count(-60.0) < n_r:
            turns.append(-60.0)
        else:
            turns.append(60.0)
    # Fix count of rights if under/over.
    while turns.count(-60.0) < n_r:
        for i, t in enumerate(turns):
            if t == 60.0 and i != special:
                turns[i] = -60.0
                break
        else:
            break
    while turns.count(-60.0) > n_r:
        for i, t in enumerate(turns):
            if t == -60.0:
                turns[i] = 60.0
                break
        else:
            break
    residual = 360.0 - sum(turns)
    # Absorb residual into the special turn, then snap toward {45,51,60,72}.
    turns[special] += residual
    snap_set = (45.0, 51.0, 60.0, 72.0, -45.0, -51.0, -60.0, -72.0)
    turns[special] = min(snap_set, key=lambda s: abs(s - turns[special]))
    residual2 = 360.0 - sum(turns)
    pos = [i for i, t in enumerate(turns) if t > 0 and i != special]
    if pos and abs(residual2) > 1e-9:
        for i in pos:
            turns[i] += residual2 / len(pos)
    return turns


def _interior_bond_angles_deg(pts: Sequence[tuple[float, float]]) -> list[float]:
    """Unsigned smaller angle at each vertex (0–180°); reentrancy via cross signs elsewhere."""
    n = len(pts)
    out: list[float] = []
    for i in range(n):
        ax, ay = pts[(i - 1) % n]
        bx, by = pts[i]
        cx, cy = pts[(i + 1) % n]
        v1x, v1y = ax - bx, ay - by
        v2x, v2y = cx - bx, cy - by
        d = (math.hypot(v1x, v1y) * math.hypot(v2x, v2y)) or 1.0
        c = max(-1.0, min(1.0, (v1x * v2x + v1y * v2y) / d))
        out.append(math.degrees(math.acos(c)))
    return out


def _relax_ring_bond_angles(
    pts: list[tuple[float, float]],
    *,
    bond_length: float,
    iterations: int = 36,
) -> list[tuple[float, float]]:
    """Soft-snap vertex angles toward GR-3.3.2 preferred set while keeping edge lengths."""
    n = len(pts)
    if n < 3:
        return pts
    bl = max(float(bond_length), 1.0)
    cur = [list(p) for p in pts]
    for _ in range(max(1, iterations)):
        cur = [
            list(p)
            for p in _equalize_polygon_edges(
                [(p[0], p[1]) for p in cur], bond_length=bl, iterations=2
            )
        ]
        for i in range(n):
            ax, ay = cur[(i - 1) % n]
            bx, by = cur[i]
            cx, cy = cur[(i + 1) % n]
            v1x, v1y = ax - bx, ay - by
            v2x, v2y = cx - bx, cy - by
            l1 = math.hypot(v1x, v1y) or 1.0
            l2 = math.hypot(v2x, v2y) or 1.0
            u1x, u1y = v1x / l1, v1y / l1
            u2x, u2y = v2x / l2, v2y / l2
            cross = u1x * u2y - u1y * u2x
            dot = u1x * u2x + u1y * u2y
            ang = math.degrees(math.atan2(cross, dot))
            unsigned = abs(ang)
            # Concave (reentrant) vertices: prefer ~240° interior ≡ 120° smaller wedge.
            if cross < 0:
                target_small = 120.0
            else:
                target_small = min(PREFERRED_RING_BOND_ANGLES_DEG, key=lambda a: abs(a - unsigned))
            err = target_small - unsigned
            if abs(err) < 1.5:
                continue
            # Move vertex along the exterior bisector (away from interior).
            bx_hat = u1x + u2x
            by_hat = u1y + u2y
            bh = math.hypot(bx_hat, by_hat)
            if bh < 1e-6:
                bx_hat, by_hat = -u1y, u1x
                bh = 1.0
            bx_hat /= bh
            by_hat /= bh
            # If concave, bisector of unit vectors points into the small wedge (outside).
            step = 0.04 * bl * (1.0 if cross >= 0 else -1.0) * (1.0 if err > 0 else -1.0)
            cur[i][0] += bx_hat * step
            cur[i][1] += by_hat * step
        cx = sum(p[0] for p in cur) / n
        cy = sum(p[1] for p in cur) / n
        for p in cur:
            p[0] -= cx
            p[1] -= cy
    return [(p[0], p[1]) for p in cur]


def _orient_ring_longest_edge_horizontal(
    pts: list[tuple[float, float]],
) -> list[tuple[float, float]]:
    """Rotate so a longest edge is +x and the bulk of the ring sits above (Y-up)."""
    if len(pts) < 2:
        return pts
    best_i = 0
    best_len = -1.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        length = math.hypot(x2 - x1, y2 - y1)
        if length > best_len:
            best_len = length
            best_i = i
    x1, y1 = pts[best_i]
    x2, y2 = pts[(best_i + 1) % len(pts)]
    rot = -math.atan2(y2 - y1, x2 - x1)
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    rotated = [(x * cos_r - y * sin_r, x * sin_r + y * cos_r) for x, y in pts]
    if sum(y for _x, y in rotated) < 0:
        rotated = [(x, -y) for x, y in rotated]
    xs = [p[0] for p in rotated]
    ys = [p[1] for p in rotated]
    cx, cy = sum(xs) / len(xs), sum(ys) / len(ys)
    return [(x - cx, y - cy) for x, y in rotated]


def _odd_hex_lattice_offsets(
    n_atoms: int,
    *,
    bond_length: float,
) -> list[tuple[float, float]]:
    """
    Odd large rings (≥9) as hexagonal-lattice paths (GR-3.3.2), not circular polygons.

    Builds an (n+1) even hex-lattice ring, drops one convex vertex, then equalizes edges
    so bond lengths stay standard while angles stay near 120° / allowed GR-3.3.2 set.
    """
    n = max(9, int(n_atoms))
    bl = max(float(bond_length), 1.0)
    even_n = n + 1
    turns = _hex_lattice_turn_sequence(even_n)
    if turns is None:
        # Fallback: mostly ±60° with one pentagon turn, force-closed.
        turns = _odd_large_ring_turns(n)
        walk = _polyline_from_exterior_turns(turns, bond_length=bl)
        return _force_close_polygon(walk)
    walk = _polyline_from_exterior_turns(turns, bond_length=bl)
    pts = list(walk[:-1])
    if len(pts) != even_n:
        pts = _force_close_polygon(walk)
    # Drop a left-turn (+60°) vertex so the remainder stays hex-like.
    drop = 0
    for i, t in enumerate(turns):
        if t > 0:
            drop = i
            break
    kept = [pts[i] for i in range(len(pts)) if i != drop]
    if len(kept) != n:
        # Length mismatch: fall back to force-closed odd turns.
        turns = _odd_large_ring_turns(n)
        walk = _polyline_from_exterior_turns(turns, bond_length=bl)
        return _force_close_polygon(walk)
    return kept


def large_ring_offsets_y_up(
    n_atoms: int,
    *,
    bond_length: float = SKETCH_MEDIAN_BOND_PX,
) -> list[tuple[float, float]]:
    """
    Reentrant large-ring offsets (Y-up) in hexagonal form (GR-3.3.2).

    Never uses a circular regular polygon for n≥9. Even rings are exact hex-lattice
    closed paths (120°). Odd rings are hex-lattice with one vertex removed. Oriented
    with a longest edge horizontal and bulk above (IUPAC-friendly ring pose).
    """
    n = max(9, int(n_atoms))
    bl = max(float(bond_length), 1.0)
    turns = _hex_lattice_turn_sequence(n)
    exact_hex = False
    if turns is not None:
        walk = _polyline_from_exterior_turns(turns, bond_length=bl)
        err = math.hypot(walk[-1][0] - walk[0][0], walk[-1][1] - walk[0][1])
        pts = list(walk[:-1]) if err < 1e-6 and len(walk) == n + 1 else _force_close_polygon(walk)
        exact_hex = err < 1e-6 and len(pts) == n
    else:
        pts = _odd_hex_lattice_offsets(n, bond_length=bl)
    pts = _equalize_polygon_edges(pts, bond_length=bl, iterations=20 if exact_hex else 32)
    if not exact_hex:
        # Soft-snap odd / force-closed rings toward preferred angles without circularizing.
        pts = _relax_ring_bond_angles(pts, bond_length=bl, iterations=20)
        pts = _equalize_polygon_edges(pts, bond_length=bl, iterations=12)
    return _orient_ring_longest_edge_horizontal(pts)


def ring_vertex_offsets_y_up(
    n_atoms: int,
    *,
    bond_length: float = SKETCH_MEDIAN_BOND_PX,
) -> list[tuple[float, float]]:
    """Offsets for any ring size: regular ≤8, reentrant ≥9 (GR-3.3.1 / GR-3.3.2)."""
    n = max(3, int(n_atoms))
    if n >= 9:
        return large_ring_offsets_y_up(n, bond_length=bond_length)
    return regular_ring_offsets_y_up(n, bond_length=bond_length)


def rotate_offsets_to_inward_heteroatoms(
    offsets: Sequence[tuple[float, float]],
    elements: Sequence[str],
    *,
    hetero: frozenset[str] | None = None,
) -> list[tuple[float, float]]:
    """
    Rotate ring vertex indexing so unsubstituted heteroatoms sit at inward-facing sites (GR-3.3.2).

    Inward ≈ smallest radius from the ring centroid among vertices. Element *i* stays
    paired with returned offset *i*.
    """
    n = len(offsets)
    if n == 0 or len(elements) != n:
        return list(offsets)
    het = hetero or frozenset(
        {"N", "O", "S", "P", "Se", "Te", "As", "B", "Si", "F", "Cl", "Br", "I"}
    )
    het_idx = [i for i, el in enumerate(elements) if el in het]
    if not het_idx:
        return list(offsets)
    radii = [math.hypot(x, y) for x, y in offsets]
    inward_rank = sorted(range(n), key=lambda i: radii[i])
    best_rot = 0
    best_score = 1e18
    for rot in range(n):
        # new_offsets[i] = old_offsets[(i + rot) % n]  → element i gets old geometry (i+rot).
        score = 0.0
        for k, hi in enumerate(het_idx):
            target = inward_rank[min(k, n - 1)]
            got = (hi + rot) % n
            d = min((got - target) % n, (target - got) % n)
            score += float(d)
        if score < best_score:
            best_score = score
            best_rot = rot
    if best_rot == 0:
        return list(offsets)
    return [offsets[(i + best_rot) % n] for i in range(n)]


def snap_substituent_angle(angle: float) -> float:
    """Snap near-horizontal/vertical/30° multiples (GR-4.2.1 software warning)."""
    deg = math.degrees(angle) % 180.0
    best = SUBSTITUENT_SNAP_DEG[0]
    best_d = 180.0
    for s in SUBSTITUENT_SNAP_DEG:
        d = abs(((deg - s + 90.0) % 180.0) - 90.0)
        if d < best_d:
            best_d = d
            best = s
    if best_d > SUBSTITUENT_SNAP_TOL_DEG:
        return angle
    base = math.radians(best)
    cands = (base, base + math.pi)
    best_a = cands[0]
    best_ad = abs(((angle - best_a + math.pi) % (2.0 * math.pi)) - math.pi)
    for c in cands[1:]:
        d = abs(((angle - c + math.pi) % (2.0 * math.pi)) - math.pi)
        if d < best_ad:
            best_a, best_ad = c, d
    return best_a


def exterior_ring_substituent_direction(
    ring_neighbor_angles: Sequence[float],
) -> tuple[float, float] | None:
    """
    Unit vector for a single exocyclic substituent on a ring atom (GR-4.2.1).

    Bisects the *larger* exterior angle between the two ring bonds, then snaps
    to horizontal / vertical / 30° multiples when within tolerance.
    """
    if len(ring_neighbor_angles) != 2:
        return None
    a0, a1 = float(ring_neighbor_angles[0]), float(ring_neighbor_angles[1])
    d = (a1 - a0) % (2.0 * math.pi)
    if d <= 1e-9 or abs(d - math.pi) < 1e-9:
        mid = a0 + math.pi / 2.0
    elif d < math.pi:
        mid = a0 + d + (2.0 * math.pi - d) / 2.0
    else:
        mid = a0 + d / 2.0
    mid = mid % (2.0 * math.pi)
    mid = snap_substituent_angle(mid)
    return (math.cos(mid), math.sin(mid))


def _largest_gap_bisector(angles: Sequence[float]) -> float:
    """Mid-angle of the largest gap in a set of directions, in ``[0, 2π)``."""
    angs = sorted(float(a) for a in angles)
    if not angs:
        return 0.0
    if len(angs) == 1:
        return (angs[0] + math.pi) % (2.0 * math.pi)
    max_gap = -1.0
    best_mid = 0.0
    for i, a1 in enumerate(angs):
        a2 = angs[(i + 1) % len(angs)] if i + 1 < len(angs) else angs[0] + 2.0 * math.pi
        gap = a2 - a1 if a2 >= a1 else (a2 + 2.0 * math.pi - a1)
        if gap > max_gap:
            max_gap = gap
            best_mid = a1 + gap / 2.0
    return best_mid % (2.0 * math.pi)


def _angle_between(a: float, b: float) -> float:
    """Smallest absolute difference between two radians, in ``[0, π]``."""
    d = abs(float(a) - float(b)) % (2.0 * math.pi)
    return min(d, 2.0 * math.pi - d)


def _rotate_offsets(
    offsets: Sequence[tuple[float, float]], rot: float
) -> list[tuple[float, float]]:
    cos_r, sin_r = math.cos(rot), math.sin(rot)
    return [(x * cos_r - y * sin_r, x * sin_r + y * cos_r) for x, y in offsets]


def _spiro_pose_at_vertex(
    offsets: Sequence[tuple[float, float]],
    vertex: int,
    *,
    target: float,
    mirror: bool,
) -> list[tuple[float, float]] | None:
    """
    Ring offsets with *vertex* at the origin and the local bond bisector on *target*.

    The bisector is the smaller angle between the two bonds that leave that vertex,
    so one edge is not laid down the gap center (which would fuse it to a neighbor).
    """
    n = len(offsets)
    if n < 3:
        return None
    seq = [offsets[(vertex + i) % n] for i in range(n)]
    ox, oy = seq[0]
    seq = [(x - ox, y - oy) for x, y in seq]
    if mirror:
        seq = [(x, -y) for x, y in seq]
    if math.hypot(*seq[1]) < 1e-6 or math.hypot(*seq[-1]) < 1e-6:
        return None
    b1 = math.atan2(seq[1][1], seq[1][0])
    b2 = math.atan2(seq[-1][1], seq[-1][0])
    sweep = (b2 - b1) % (2.0 * math.pi)
    if sweep <= math.pi:
        bisector = b1 + sweep / 2.0
    else:
        bisector = b1 - (2.0 * math.pi - sweep) / 2.0
    return _rotate_offsets(seq, target - bisector)


def spiro_second_ring_offsets_y_up(
    n_atoms: int,
    *,
    bond_length: float,
    existing_ring_neighbor_dirs: Sequence[tuple[float, float]],
    obstacle_points: Sequence[tuple[float, float]] | None = None,
) -> list[tuple[float, float]]:
    """
    Offsets for a new ring sharing the origin (spiro atom) without overlapping nearby bonds.

    Vertex 0 is the shared atom. The ring is turned so the bisector of the two new
    bonds — not either bond — points into the largest gap between existing neighbor
    directions, and the ring body sits in that gap (GR-4.2.4 / GR-3.3). A single
    neighbor grows the ring directly opposite that bond. Among attachment vertices
    (needed for reentrant rings), the pose that stays farthest from *obstacle_points*
    wins. Neighbor endpoints are obstacles when that sequence is omitted.
    """
    n = max(3, int(n_atoms))
    offsets = ring_vertex_offsets_y_up(n, bond_length=bond_length)
    neighbors = [
        (float(dx), float(dy))
        for dx, dy in existing_ring_neighbor_dirs
        if math.hypot(dx, dy) > 1e-6
    ]
    target = _largest_gap_bisector([math.atan2(dy, dx) for dx, dy in neighbors])
    obstacles = [tuple(p) for p in (obstacle_points if obstacle_points is not None else neighbors)]
    if len(offsets) < 3:
        return list(offsets)

    def _score(pose: list[tuple[float, float]]) -> tuple[float, float, float]:
        bond_angs = (
            math.atan2(pose[1][1], pose[1][0]),
            math.atan2(pose[-1][1], pose[-1][0]),
        )
        if neighbors:
            clearance = min(
                _angle_between(bond, math.atan2(dy, dx))
                for bond in bond_angs
                for dx, dy in neighbors
            )
        else:
            clearance = math.pi
        nearest = min((math.hypot(x, y) for x, y in pose[1:]), default=0.0)
        for x, y in pose[1:]:
            for ox, oy in obstacles:
                nearest = min(nearest, math.hypot(x - ox, y - oy))
        cx = sum(x for x, _y in pose) / n
        cy = sum(y for _x, y in pose) / n
        align = 0.0
        if math.hypot(cx, cy) > 1e-6:
            align = math.cos(math.atan2(cy, cx) - target)
        # Angular clearance dominates so a bond is not drawn on top of a neighbor.
        return (clearance, nearest, align)

    best: list[tuple[float, float]] | None = None
    best_score: tuple[float, float, float] | None = None
    for vertex in range(len(offsets)):
        for mirror in (False, True):
            pose = _spiro_pose_at_vertex(offsets, vertex, target=target, mirror=mirror)
            if pose is None:
                continue
            score = _score(pose)
            if best_score is None or score > best_score:
                best_score = score
                best = pose
    if best is None:
        return list(offsets)
    return best


def fusion_ring_offsets_for_bond(
    n_atoms: int,
    *,
    bond_length: float,
    ax: float,
    ay: float,
    bx: float,
    by: float,
    prefer_side: float = 1.0,
) -> list[tuple[float, float]]:
    """
    Absolute Y-up positions for an ortho-fused ring sharing bond A–B (GR-3.3.3).

    Vertices 0 and 1 of the new ring map to A and B. Remaining vertices lie where
    the Y-up cross product ``(B-A) × (P-A)`` has the sign of *prefer_side*
    (+1 is left of A→B). Side is chosen by mirroring across the bond.
    """
    n = max(3, int(n_atoms))
    bl = max(float(bond_length), 1.0)
    dx, dy = bx - ax, by - ay
    length = math.hypot(dx, dy) or 1.0
    ux, uy = dx / length, dy / length
    px, py = -uy, ux
    # Large fused rings still prefer reentrant GR-3.3.2 geometry when n≥9.
    local = ring_vertex_offsets_y_up(n, bond_length=bl)
    lx0, ly0 = local[0]
    local = [(x - lx0, y - ly0) for x, y in local]
    lx1, ly1 = local[1]
    cur = math.atan2(ly1, lx1)
    cos_r, sin_r = math.cos(-cur), math.sin(-cur)
    local = [(x * cos_r - y * sin_r, x * sin_r + y * cos_r) for x, y in local]
    sx = length / max(local[1][0], 1e-6)
    if sum(y for _x, y in local) * prefer_side < 0:
        local = [(x, -y) for x, y in local]
    local = [(x * sx, y * sx) for x, y in local]
    out: list[tuple[float, float]] = []
    for lx, ly in local:
        out.append((ax + ux * lx + px * ly, ay + uy * lx + py * ly))
    return out


def hash_bar_count_for_style(*, bond_width_px: float, bond_length_px: float) -> int:
    """
    Number of hash bars so spacing is roughly 2–4× bond width (GR-1.3).

    Tip→wide length ≈ bond length; bars distributed along ~85% of that span.
    """
    bw = max(float(bond_width_px), 0.5)
    usable = max(float(bond_length_px) * 0.85, bw * 4.0)
    n = int(round(usable / (3.0 * bw)))
    return max(4, min(10, n))


def ring_bond_angles_near_preferred(
    pts: Sequence[tuple[float, float]],
    *,
    tol_deg: float = 12.0,
) -> bool:
    """True when every vertex angle is within *tol_deg* of a GR-3.3.2 preferred angle."""
    for ang in _interior_bond_angles_deg(pts):
        # Reentrant hex vertices report ~120° via acos; treat as preferred.
        if min(abs(ang - p) for p in PREFERRED_RING_BOND_ANGLES_DEG) <= tol_deg:
            continue
        return False
    return True
