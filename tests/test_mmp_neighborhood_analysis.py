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

"""Tests for MMP pair neighborhood graph helpers."""

from rdkit import Chem

from molmanager.analysis.mmp_analysis import find_matched_molecular_pairs
from molmanager.analysis.mmp_neighborhood_analysis import (
    MmpNetworkEdge,
    MmpNetworkGraph,
    build_mmp_network_graph,
    build_network_edges,
    neighborhood_oids,
    spring_layout_positions,
    subset_mmp_network_graph,
)
from molmanager.ui.mmp_neighborhood_plot import build_mmp_neighborhood_figure


def _rec(oid: int, smiles: str, activity: float):
    return oid, Chem.MolFromSmiles(smiles), activity


def test_subset_mmp_network_graph_keeps_remaining_layout():
    edges = (
        MmpNetworkEdge(1, 2, 1.0, 1.0, "a", 0),
        MmpNetworkEdge(2, 3, 0.5, -0.5, "b", 1),
    )
    graph = MmpNetworkGraph(
        node_oids=(1, 2, 3),
        positions={1: (0.0, 0.0), 2: (1.0, 0.0), 3: (2.0, 1.0)},
        degrees={1: 1, 2: 2, 3: 1},
        activities={1: 1.0, 2: 2.0, 3: 3.0},
        edges=edges,
    )
    assert subset_mmp_network_graph(graph, frozenset({1, 2, 3})) is graph
    kept = subset_mmp_network_graph(graph, frozenset({1, 2}))
    assert kept.node_oids == (1, 2)
    assert len(kept.edges) == 1
    assert kept.edges[0].oid_a == 1 and kept.edges[0].oid_b == 2
    assert kept.positions[2] == (1.0, 0.0)
    assert kept.degrees[2] == 1
    orphaned = subset_mmp_network_graph(graph, frozenset({1, 3}))
    assert orphaned.node_oids == (1, 3)
    assert orphaned.edges == ()
    assert orphaned.positions[3] == (2.0, 1.0)
    assert orphaned.degrees[1] == 0


def test_spring_layout_and_neighborhood():
    nodes = [1, 2, 3]
    edges = [(1, 2), (2, 3)]
    pos = spring_layout_positions(nodes, edges, iterations=20, seed=1)
    assert set(pos) == {1, 2, 3}
    assert all(len(xy) == 2 for xy in pos.values())

    from molmanager.analysis.mmp_neighborhood_analysis import MmpNetworkEdge

    net_edges = [
        MmpNetworkEdge(1, 2, 1.0, 1.0, "a>>b", 0),
        MmpNetworkEdge(2, 3, 0.5, -0.5, "b>>c", 1),
    ]
    assert neighborhood_oids(net_edges, [1], max_hops=0) == {1, 2, 3}
    assert neighborhood_oids(net_edges, [1], max_hops=1) == {1, 2}
    assert neighborhood_oids(net_edges, [1], max_hops=2) == {1, 2, 3}


def test_layout_many_components_fills_2d():
    """Disconnected MMP-like pairs must not pack into a horizontal line."""
    import numpy as np

    nodes: list[int] = []
    edges: list[tuple[int, int]] = []
    oid = 0
    for _ in range(40):
        nodes.extend([oid, oid + 1])
        edges.append((oid, oid + 1))
        oid += 2
    pos = spring_layout_positions(nodes, edges, iterations=20, seed=5)
    xs = np.array([pos[i][0] for i in nodes])
    ys = np.array([pos[i][1] for i in nodes])
    x_span = float(xs.max() - xs.min())
    y_span = float(ys.max() - ys.min())
    assert y_span > 1.0
    assert x_span / max(y_span, 1e-9) < 4.0


def test_spring_layout_scales_without_hanging():
    """Dense all-pairs layout must stay fast enough for UI use."""
    import time

    n = 250
    nodes = list(range(n))
    # Sparse path graph + a few random chords.
    edges = [(i, i + 1) for i in range(n - 1)]
    edges.extend((i, i + 7) for i in range(0, n - 7, 11))
    t0 = time.perf_counter()
    pos = spring_layout_positions(nodes, edges, iterations=60, seed=3)
    elapsed = time.perf_counter() - t0
    assert set(pos) == set(nodes)
    assert elapsed < 5.0, f"layout too slow: {elapsed:.2f}s"


def test_sparse_layout_for_large_component():
    n = 800
    nodes = list(range(n))
    edges = [(i, i + 1) for i in range(n - 1)]
    pos = spring_layout_positions(nodes, edges, iterations=20, seed=4)
    assert set(pos) == set(nodes)


def test_build_mmp_network_from_pairs():
    records = [
        _rec(1, "Oc1ccccc1", 1.0),
        _rec(2, "COc1ccccc1", 2.5),
        _rec(3, "CCOc1ccccc1", 3.0),
    ]
    pairs = find_matched_molecular_pairs(records, max_cuts=1)
    edges = build_network_edges(pairs)
    assert len(edges) == len(pairs)
    graph = build_mmp_network_graph(pairs, layout_iterations=25, layout_seed=2)
    assert graph.node_oids
    assert len(graph.edges) == len(pairs)
    assert set(graph.positions) == set(graph.node_oids)
    fig = build_mmp_neighborhood_figure(graph, activity_column="pIC50")
    assert fig.data
    meta = fig.layout.meta or {}
    assert "molmanager_selection_traces" in meta
    assert meta.get("molmanager_selection_overlay") is False
    assert all(getattr(tr, "type", None) == "scattergl" for tr in fig.data)
    assert fig.layout.xaxis.scaleanchor is None
    assert fig.layout.xaxis.range is not None
    assert fig.layout.yaxis.range is not None
    assert (
        abs(
            fig.layout.xaxis.range[1]
            - fig.layout.xaxis.range[0]
            - (fig.layout.yaxis.range[1] - fig.layout.yaxis.range[0])
        )
        < 1e-9
    )
