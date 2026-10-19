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

"""Tests for Plotly scatter color encoding."""

from molmanager.plotting.plot_marker_color import (
    color_values_are_numeric,
    parse_color_range_bounds,
    scatter_marker_from_column_values,
)


def test_colorbar_title_runs_along_the_bar():
    from molmanager.plotting.plot_marker_color import (
        COLORBAR_TITLE_MAX_CHARS,
        colorbar_for_label,
    )

    short = colorbar_for_label("Molecular Weight")
    assert short["title"] == {"text": "Molecular Weight", "side": "right"}
    assert short["thickness"] == 14

    long_name = "Very long calculated descriptor name for the color scale"
    titled = colorbar_for_label(long_name)
    text = titled["title"]["text"]
    assert titled["title"]["side"] == "right"
    assert len(text) == COLORBAR_TITLE_MAX_CHARS
    assert text.endswith("…")
    assert text[:-1] == long_name[: COLORBAR_TITLE_MAX_CHARS - 1].rstrip()

    marker = scatter_marker_from_column_values([1.0, 2.0, 3.0], color_label=long_name)
    assert marker["colorbar"]["title"]["text"] == text
    assert marker["colorbar"]["title"]["side"] == "right"


def test_numeric_strings_use_colorscale_not_hex():
    m = scatter_marker_from_column_values(
        ["457.6814032", "539.62482", "384.2372"],
        color_label="MW",
    )
    assert m["colorscale"] == "Viridis"
    assert all(isinstance(c, float) for c in m["color"])


def test_categorical_uses_hex_colors():
    m = scatter_marker_from_column_values(["A", "B", "A"], color_label="cluster")
    assert "colorscale" not in m
    assert m["color"][0].startswith("#")


def test_native_floats_use_colorscale():
    m = scatter_marker_from_column_values([1.0, 2.0, 3.0], color_label="score")
    assert m["colorscale"] == "Viridis"
    assert m["cmin"] == 1.0
    assert m["cmax"] == 3.0


def test_custom_colorscale():
    m = scatter_marker_from_column_values([1.0, 2.0], colorscale="Plasma")
    assert m["colorscale"] == "Plasma"


def test_custom_color_range_bounds():
    m = scatter_marker_from_column_values(
        [1.0, 5.0, 10.0],
        color_min=0.0,
        color_max=20.0,
    )
    assert m["cmin"] == 0.0
    assert m["cmax"] == 20.0


def test_parse_color_range_bounds():
    assert parse_color_range_bounds("", "") == (None, None)
    assert parse_color_range_bounds("1.5", "9") == (1.5, 9.0)


def test_color_values_are_numeric():
    assert color_values_are_numeric([1, "2.5", None])
    assert not color_values_are_numeric(["A", "B"])


def test_all_none_uses_default_marker():
    from molmanager.plotting.plot_marker_color import DEFAULT_MARKER_SIZE_PX

    m = scatter_marker_from_column_values([None, None, None], color_label="MW")
    assert m["color"] == "#2a74d6"
    assert m["size"] == DEFAULT_MARKER_SIZE_PX
    assert DEFAULT_MARKER_SIZE_PX > 6.0
    assert "colorscale" not in m


def test_mixed_none_and_float_uses_nan_for_missing():
    import math

    from plotly import graph_objects as go

    m = scatter_marker_from_column_values([None, None, 1.0], color_label="MW")
    assert m["colorscale"] == "Viridis"
    assert math.isnan(m["color"][0])
    assert math.isnan(m["color"][1])
    assert m["color"][2] == 1.0
    go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[1, 2, 3], marker=m)])


def test_size_by_numeric_maps_to_pixel_range():
    from molmanager.plotting.plot_marker_color import marker_sizes_from_column_values

    sizes = marker_sizes_from_column_values(
        [0.0, 5.0, 10.0],
        size_min_px=4.0,
        size_max_px=14.0,
    )
    assert isinstance(sizes, list)
    assert sizes[0] == 4.0
    assert sizes[1] == 9.0
    assert sizes[2] == 14.0


def test_scatter_marker_applies_size_values():
    m = scatter_marker_from_column_values(
        [1.0, 2.0, 3.0],
        color_label="score",
        size_values=[10.0, 20.0, 30.0],
        size_min_px=2.0,
        size_max_px=8.0,
    )
    assert m["size"][0] == 2.0
    assert m["size"][2] == 8.0


def test_attach_marker_size_legend_adds_right_scale():
    from plotly import graph_objects as go

    from molmanager.plotting.plot_marker_color import attach_marker_size_legend

    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[1, 2], mode="markers", showlegend=False)])
    attach_marker_size_legend(
        fig,
        size_label="MW",
        size_values=[100.0, 200.0, 300.0],
        size_min_px=4.0,
        size_max_px=14.0,
    )
    assert fig.layout.showlegend is True
    assert fig.layout.legend.title.text == "MW"
    size_traces = [tr for tr in fig.data if getattr(tr, "legendgroup", None) == "molmanager_size"]
    assert len(size_traces) == 5


def test_attach_marker_size_legend_with_colorbar():
    from plotly import graph_objects as go

    from molmanager.plotting.plot_marker_color import (
        attach_marker_size_legend,
        scatter_marker_from_column_values,
    )

    vals = [1.0, 2.0, 3.0, 4.0, 5.0]
    marker = scatter_marker_from_column_values(
        vals, color_label="Color", size_values=vals, size_min_px=4.0, size_max_px=16.0
    )
    fig = go.Figure(
        data=[go.Scatter(x=vals, y=vals, mode="markers", marker=marker, showlegend=False)]
    )
    attach_marker_size_legend(
        fig,
        size_label="Size",
        size_values=vals,
        size_min_px=4.0,
        size_max_px=16.0,
    )
    assert fig.layout.showlegend is True
    assert any(getattr(tr, "legendgroup", None) == "molmanager_size" for tr in fig.data)
    assert fig.data[0].marker.showscale is True
