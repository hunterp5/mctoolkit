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

"""Tests for embedded Plotly HTML export."""

import json
from pathlib import Path

from plotly import graph_objects as go

from molmanager.plotting.plot_marker_color import scatter_marker_from_column_values
from molmanager.ui.plotly_html import (
    figure_payload_json,
    legend_name_is_utility,
    prefer_scattergl_for_large_traces,
    suppress_utility_legend_entries,
    upgrade_scatter_payload_to_gl,
    write_self_contained_plotly_html,
)


def test_figure_payload_json_parses_with_nan_marker_colors():
    marker = scatter_marker_from_column_values([None, 1.0, 2.0], color_label="MW")
    fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[1, 2, 3], marker=marker)])
    raw = figure_payload_json(fig)
    assert "NaN" not in raw
    payload = json.loads(raw)
    assert payload["data"][0]["marker"]["color"]


def test_suppress_utility_legend_entries_hides_fit_and_trace_zero() -> None:
    fig = go.Figure(
        data=[
            go.Scatter(x=[1], y=[1], name="Fit"),
            go.Histogram(x=[1, 2, 2], name="Trace 0"),
            go.Scatter(x=[2], y=[2], name="OID 42"),
        ]
    )
    suppress_utility_legend_entries(fig)
    assert fig.data[0].showlegend is False
    assert fig.data[1].showlegend is False
    assert fig.data[2].showlegend is not False
    assert fig.layout.showlegend is not False


def test_legend_name_is_utility_compounds_and_fit_prefix() -> None:
    assert legend_name_is_utility("Compounds")
    assert legend_name_is_utility("Fit (normal)")
    assert legend_name_is_utility("") is True
    assert legend_name_is_utility("OID 3") is False


def test_suppress_utility_legend_entries_hides_compounds() -> None:
    fig = go.Figure(data=[go.Scatter(x=[1], y=[1], name="Compounds")])
    suppress_utility_legend_entries(fig)
    assert fig.data[0].showlegend is False
    assert fig.layout.showlegend is False


def test_figure_payload_json_hides_utility_legend() -> None:
    fig = go.Figure(data=[go.Scatter(x=[1], y=[1], name="Fit")])
    payload = json.loads(figure_payload_json(fig))
    assert payload["data"][0]["showlegend"] is False
    assert payload["layout"].get("showlegend") is False


def test_prefer_scattergl_for_large_marker_traces() -> None:
    n = 50
    fig = go.Figure(
        data=[
            go.Scatter(x=list(range(n)), y=list(range(n)), mode="markers", name="pts"),
            go.Scatter(x=[0, 1], y=[0, 1], mode="lines", name="edge"),
        ]
    )
    payload = fig.to_plotly_json()
    upgrade_scatter_payload_to_gl(payload, min_points=40)
    assert payload["data"][0]["type"] == "scattergl"
    assert payload["data"][1]["type"] == "scatter"
    prefer_scattergl_for_large_traces(fig, min_points=40)
    assert fig.data[0].type == "scattergl"
    assert fig.data[1].type == "scatter"


def test_prefer_scattergl_skips_small_traces() -> None:
    fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[1, 2, 3], mode="markers")])
    payload = fig.to_plotly_json()
    upgrade_scatter_payload_to_gl(payload, min_points=100)
    assert payload["data"][0]["type"] == "scatter"


def test_figure_payload_json_upgrades_large_scatter(monkeypatch) -> None:
    monkeypatch.setenv("MOLMANAGER_PLOT_SCATTERGL_MIN_POINTS", "50")
    n = 80
    fig = go.Figure(data=[go.Scatter(x=list(range(n)), y=list(range(n)), mode="markers")])
    payload = json.loads(figure_payload_json(fig))
    assert payload["data"][0]["type"] == "scattergl"


def test_write_self_contained_plotly_html_includes_plotly(tmp_path: Path):
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    path = tmp_path / "plot.html"
    write_self_contained_plotly_html(fig, path)
    text = path.read_text(encoding="utf-8")
    assert "Plotly.newPlot" in text
    assert 'replace("rotate(-90", "rotate(90")' in text
    assert 'src="https://cdn.plot.ly' not in text
