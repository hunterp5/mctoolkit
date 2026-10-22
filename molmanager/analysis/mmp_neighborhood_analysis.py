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

"""MMP pair neighborhood graph: nodes, edges, and spring layout."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from .mmp_analysis import MmpPair

# Above this node count, use a cheaper sparse layout (edge forces only).
_DENSE_LAYOUT_MAX_NODES = 600


@dataclass(frozen=True)
class MmpNetworkEdge:
    """One undirected MMP edge between two molecule OIDs."""

    oid_a: int
    oid_b: int
    abs_delta: float
    signed_delta: float
    transform: str
    pair_index: int


@dataclass(frozen=True)
class MmpNetworkGraph:
    """Laid-out neighborhood graph from MMP pairs."""

    node_oids: tuple[int, ...]
    positions: dict[int, tuple[float, float]]
    degrees: dict[int, int]
    activities: dict[int, float]
    edges: tuple[MmpNetworkEdge, ...]


def build_network_edges(pairs: Sequence[MmpPair]) -> list[MmpNetworkEdge]:
    """Convert MMP pairs into undirected network edges."""
    edges: list[MmpNetworkEdge] = []
    for idx, pair in enumerate(pairs):
        edges.append(
            MmpNetworkEdge(
                oid_a=int(pair.oid_a),
                oid_b=int(pair.oid_b),
                abs_delta=abs(float(pair.delta_activity)),
                signed_delta=float(pair.delta_activity),
                transform=pair.transform,
                pair_index=idx,
            )
        )
    return edges


def _connected_components(nodes: Sequence[int], adjacency: dict[int, set[int]]) -> list[list[int]]:
    remaining = set(int(n) for n in nodes)
    comps: list[list[int]] = []
    while remaining:
        start = next(iter(remaining))
        queue = deque([start])
        remaining.discard(start)
        comp = [start]
        while queue:
            cur = queue.popleft()
            for nbr in adjacency.get(cur, ()):
                if nbr in remaining:
                    remaining.discard(nbr)
                    queue.append(nbr)
                    comp.append(nbr)
        comps.append(sorted(comp))
    return comps


def _adaptive_iterations(n: int, requested: int) -> int:
    """Fewer FR iterations for larger components (UI responsiveness)."""
    req = max(1, int(requested))
    if n <= 80:
        return req
    if n <= 200:
        return min(req, 40)
    if n <= 600:
        return min(req, 25)
    return min(req, 15)


def _layout_component_dense(
    pos: np.ndarray,
    edge_pairs: list[tuple[int, int]],
    *,
    iterations: int,
    k: float,
    rng: np.random.RandomState,
) -> np.ndarray:
    """Vectorized Fruchterman–Reingold for modest component sizes."""
    n = pos.shape[0]
    temp = 1.0
    cool = temp / max(iterations, 1)
    for _ in range(iterations):
        # Pairwise repulsion (n×n), vectorized.
        delta = pos[:, None, :] - pos[None, :, :]
        dist2 = np.einsum("ijk,ijk->ij", delta, delta)
        np.fill_diagonal(dist2, 1.0)
        dist = np.sqrt(dist2, dtype=float)
        force = (k * k) / dist
        np.fill_diagonal(force, 0.0)
        unit = delta / dist[:, :, None]
        disp = np.sum(unit * force[:, :, None], axis=1)

        # Edge attraction (sparse).
        if edge_pairs:
            ii = np.fromiter((i for i, _ in edge_pairs), dtype=np.intp, count=len(edge_pairs))
            jj = np.fromiter((j for _, j in edge_pairs), dtype=np.intp, count=len(edge_pairs))
            dlt = pos[ii] - pos[jj]
            d = np.linalg.norm(dlt, axis=1)
            ok = d > 1e-6
            if np.any(ok):
                d = d[ok]
                dlt = dlt[ok]
                ii_ok = ii[ok]
                jj_ok = jj[ok]
                f = (d * d) / k
                u = dlt / d[:, None]
                pull = u * f[:, None]
                np.add.at(disp, ii_ok, -pull)
                np.add.at(disp, jj_ok, pull)

        lengths = np.linalg.norm(disp, axis=1)
        scale = np.ones(n, dtype=float)
        move = lengths > 1e-9
        scale[move] = np.minimum(lengths[move], temp) / lengths[move]
        pos = pos + disp * scale[:, None]
        # Nudge coincident nodes.
        if n > 1 and np.any(lengths < 1e-9):
            pos = pos + rng.randn(n, 2) * 1e-4
        temp = max(0.01, temp - cool)
    return pos


def _layout_component_sparse(
    pos: np.ndarray,
    edge_pairs: list[tuple[int, int]],
    *,
    iterations: int,
    k: float,
    rng: np.random.RandomState,
) -> np.ndarray:
    """
    Cheap layout for large components: random jitter + edge springs only.

    Avoids O(n²) all-pairs repulsion that freezes the UI on big MMP graphs.
    """
    n = pos.shape[0]
    temp = 1.0
    cool = temp / max(iterations, 1)
    # Mild per-node self-repulsion via random walk scale.
    for _ in range(iterations):
        disp = rng.randn(n, 2) * (0.05 * k)
        if edge_pairs:
            ii = np.fromiter((i for i, _ in edge_pairs), dtype=np.intp, count=len(edge_pairs))
            jj = np.fromiter((j for _, j in edge_pairs), dtype=np.intp, count=len(edge_pairs))
            dlt = pos[ii] - pos[jj]
            d = np.linalg.norm(dlt, axis=1)
            ok = d > 1e-6
            if np.any(ok):
                d = d[ok]
                dlt = dlt[ok]
                ii_ok = ii[ok]
                jj_ok = jj[ok]
                # Soft spring toward distance k.
                f = (d - k) * 0.35
                u = dlt / d[:, None]
                pull = u * f[:, None]
                np.add.at(disp, ii_ok, -pull)
                np.add.at(disp, jj_ok, pull)
        lengths = np.linalg.norm(disp, axis=1)
        scale = np.ones(n, dtype=float)
        move = lengths > 1e-9
        scale[move] = np.minimum(lengths[move], temp) / lengths[move]
        pos = pos + disp * scale[:, None]
        temp = max(0.01, temp - cool)
    return pos


def spring_layout_positions(
    nodes: Sequence[int],
    edges: Sequence[tuple[int, int]],
    *,
    iterations: int = 60,
    seed: int = 0,
) -> dict[int, tuple[float, float]]:
    """
    Fruchterman–Reingold-style layout (numpy only).

    Disconnected components are laid out separately and packed on a 2D grid
    (not a single horizontal strip, which collapses under equal-aspect plots).
    Large components use a sparse edge-spring layout to avoid UI freezes.
    """
    node_list = [int(n) for n in nodes]
    if not node_list:
        return {}
    if len(node_list) == 1:
        return {node_list[0]: (0.0, 0.0)}

    adjacency: dict[int, set[int]] = {n: set() for n in node_list}
    for a, b in edges:
        a_i, b_i = int(a), int(b)
        if a_i not in adjacency or b_i not in adjacency or a_i == b_i:
            continue
        adjacency[a_i].add(b_i)
        adjacency[b_i].add(a_i)

    comps = _connected_components(node_list, adjacency)
    rng = np.random.RandomState(int(seed))

    # Lay out each component in its own local frame (centered, unit span).
    local: list[tuple[list[int], np.ndarray]] = []
    for comp in comps:
        n = len(comp)
        if n == 1:
            local.append((comp, np.zeros((1, 2), dtype=float)))
            continue

        idx = {oid: i for i, oid in enumerate(comp)}
        # Circular seed keeps early iterations from collapsing to a line.
        angles = rng.uniform(0.0, 2.0 * np.pi, size=n)
        radii = 0.35 + 0.65 * rng.rand(n)
        pos = np.column_stack((radii * np.cos(angles), radii * np.sin(angles)))
        area = float(max(n, 1))
        # Classic FR ideal length; floor keeps tiny graphs from exploding.
        k = max(0.35, (area / max(n, 1)) ** 0.5)
        iters = _adaptive_iterations(n, iterations)

        edge_pairs = [(idx[a], idx[b]) for a in comp for b in adjacency[a] if a < b and b in idx]

        if n <= _DENSE_LAYOUT_MAX_NODES:
            pos = _layout_component_dense(pos, edge_pairs, iterations=iters, k=k, rng=rng)
        else:
            pos = _layout_component_sparse(pos, edge_pairs, iterations=iters, k=k, rng=rng)

        pos = pos - pos.mean(axis=0)
        # Normalize each axis independently so thin layouts still fill 2D cells.
        for dim in (0, 1):
            span = float(np.max(np.abs(pos[:, dim]))) or 1.0
            pos[:, dim] /= span
        local.append((comp, pos))

    n_comp = len(local)
    cols = max(1, int(np.ceil(np.sqrt(n_comp))))
    rows = max(1, int(np.ceil(n_comp / cols)))
    cell = 2.6
    out: dict[int, tuple[float, float]] = {}
    for ci, (comp, pos) in enumerate(local):
        row, col = divmod(ci, cols)
        # Center the grid around the origin.
        ox = (col - 0.5 * (cols - 1)) * cell
        oy = (0.5 * (rows - 1) - row) * cell
        for i, oid in enumerate(comp):
            out[oid] = (float(pos[i, 0] + ox), float(pos[i, 1] + oy))
    return out


def neighborhood_oids(
    edges: Sequence[MmpNetworkEdge],
    seed_oids: Sequence[int],
    *,
    max_hops: int,
) -> set[int]:
    """OIDs within *max_hops* of any seed (inclusive). ``max_hops<=0`` → all nodes."""
    all_nodes: set[int] = set()
    adjacency: dict[int, set[int]] = defaultdict(set)
    for e in edges:
        all_nodes.add(e.oid_a)
        all_nodes.add(e.oid_b)
        adjacency[e.oid_a].add(e.oid_b)
        adjacency[e.oid_b].add(e.oid_a)
    if max_hops <= 0 or not seed_oids:
        return all_nodes
    seeds = {int(o) for o in seed_oids if int(o) in all_nodes}
    if not seeds:
        return set()
    reached = set(seeds)
    frontier = set(seeds)
    for _ in range(int(max_hops)):
        nxt: set[int] = set()
        for node in frontier:
            nxt.update(adjacency.get(node, ()))
        nxt -= reached
        if not nxt:
            break
        reached |= nxt
        frontier = nxt
    return reached


def build_mmp_network_graph(
    pairs: Sequence[MmpPair],
    *,
    focus_oids: Sequence[int] | None = None,
    max_hops: int = 0,
    layout_iterations: int = 60,
    layout_seed: int = 0,
) -> MmpNetworkGraph:
    """
    Build a laid-out MMP neighborhood graph.

    When *focus_oids* is set and *max_hops* > 0, only the ego neighborhood is kept.
    """
    edges = build_network_edges(pairs)
    if focus_oids and max_hops > 0:
        keep = neighborhood_oids(edges, focus_oids, max_hops=max_hops)
        edges = [e for e in edges if e.oid_a in keep and e.oid_b in keep]
        pair_by_idx = {i: p for i, p in enumerate(pairs)}
    else:
        pair_by_idx = {i: p for i, p in enumerate(pairs)}

    degrees: dict[int, int] = defaultdict(int)
    activities: dict[int, float] = {}
    for e in edges:
        degrees[e.oid_a] += 1
        degrees[e.oid_b] += 1
        pair = pair_by_idx.get(e.pair_index)
        if pair is not None:
            activities[e.oid_a] = float(pair.activity_a)
            activities[e.oid_b] = float(pair.activity_b)

    node_oids = tuple(sorted(degrees.keys()))
    undirected = [(e.oid_a, e.oid_b) for e in edges]
    positions = spring_layout_positions(
        node_oids,
        undirected,
        iterations=layout_iterations,
        seed=layout_seed,
    )
    return MmpNetworkGraph(
        node_oids=node_oids,
        positions=positions,
        degrees=dict(degrees),
        activities=activities,
        edges=tuple(edges),
    )


def subset_mmp_network_graph(graph: MmpNetworkGraph, keep: frozenset[int]) -> MmpNetworkGraph:
    """Drop nodes that left the table, keeping the layout of the nodes that remain."""
    keep_nodes = {int(oid) for oid in graph.node_oids if int(oid) in keep}
    if len(keep_nodes) == len(graph.node_oids):
        return graph
    edges = tuple(
        edge
        for edge in graph.edges
        if int(edge.oid_a) in keep_nodes and int(edge.oid_b) in keep_nodes
    )
    degrees: dict[int, int] = {oid: 0 for oid in keep_nodes}
    for edge in edges:
        degrees[int(edge.oid_a)] = degrees.get(int(edge.oid_a), 0) + 1
        degrees[int(edge.oid_b)] = degrees.get(int(edge.oid_b), 0) + 1
    node_oids = tuple(sorted(keep_nodes))
    return MmpNetworkGraph(
        node_oids=node_oids,
        positions={oid: graph.positions[oid] for oid in node_oids if oid in graph.positions},
        degrees=degrees,
        activities={oid: graph.activities[oid] for oid in node_oids if oid in graph.activities},
        edges=edges,
    )
