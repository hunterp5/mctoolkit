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

"""Write self-contained Plotly HTML for Qt WebEngine (no CDN)."""

from __future__ import annotations

import json
from pathlib import Path

from plotly import graph_objects as go
from plotly.io import to_json as plotly_to_json

from ..plotting.plotly_legend import (  # noqa: F401  re-exported for ui plot modules
    finalize_plot_legend,
    legend_name_is_utility,
    suppress_utility_legend_entries,
)

_DEFAULT_WEB_CONFIG = {
    "displaylogo": False,
    "responsive": True,
    # Wheel zoom / middle-mouse pan are handled in plotly_shell (keeps lasso on LMB).
    "scrollZoom": False,
}


def _scatter_point_count(tr: dict) -> int:
    x = tr.get("x")
    try:
        return len(x) if x is not None else 0
    except TypeError:
        return 0


def upgrade_scatter_payload_to_gl(payload: dict, *, min_points: int | None = None) -> None:
    """In serialized Plotly JSON, upgrade large marker scatters to ``scattergl``."""
    if min_points is None:
        from ..platform_support.config import load_config

        min_points = int(load_config().plot_scattergl_min_points)
    if min_points <= 0:
        return
    data = payload.get("data")
    if not isinstance(data, list):
        return
    for tr in data:
        if not isinstance(tr, dict):
            continue
        if tr.get("type") != "scatter":
            continue
        mode = str(tr.get("mode") or "markers")
        if "markers" not in mode:
            continue
        if _scatter_point_count(tr) < min_points:
            continue
        tr["type"] = "scattergl"


def prefer_scattergl_for_large_traces(fig: go.Figure, *, min_points: int | None = None) -> None:
    """Upgrade marker ``scatter`` traces to ``scattergl`` when point count is large.

    Mutates ``fig`` by rebuilding data (Plotly forbids assigning replacement traces
    of a different type onto ``fig.data`` directly).
    """
    if min_points is None:
        from ..platform_support.config import load_config

        min_points = int(load_config().plot_scattergl_min_points)
    if min_points <= 0:
        return
    payload = fig.to_plotly_json()
    upgrade_scatter_payload_to_gl(payload, min_points=min_points)
    if not any(
        isinstance(tr, dict) and tr.get("type") == "scattergl" for tr in (payload.get("data") or [])
    ):
        return
    # Rebuild in place so callers keep the same Figure object.
    rebuilt = go.Figure(payload)
    while len(fig.data):
        fig.data = fig.data[:-1]
    for tr in rebuilt.data:
        fig.add_trace(tr)


def figure_payload_json(fig: go.Figure, *, config: dict | None = None) -> str:
    """
    Serialize a figure for ``JSON.parse`` in Qt WebEngine.

    Standard ``json.dumps(fig.to_plotly_json())`` emits bare ``NaN`` tokens (invalid JSON)
    when marker colors include missing numeric values.
    """
    suppress_utility_legend_entries(fig)
    payload = json.loads(plotly_to_json(fig, validate=False))
    upgrade_scatter_payload_to_gl(payload)
    merged = dict(_DEFAULT_WEB_CONFIG)
    if config:
        merged.update(config)
    payload["config"] = merged
    return json.dumps(payload, separators=(",", ":"))


def write_self_contained_plotly_html(fig: go.Figure, path: Path) -> None:
    """
    Embed Plotly.js inline so QWebEngine does not depend on a CDN.

    Escapes ``:focus-visible`` CSS (Qt/Chromium can reject it) and ``</script>`` in JS.
    """
    from .plotly_shell import sanitized_plotly_js

    plotly_js = sanitized_plotly_js()
    payload = figure_payload_json(fig)
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <style>html, body, #plot {{ width: 100%; height: 100%; margin: 0; }}</style>
</head>
<body>
  <div id="plot"></div>
  <script>{plotly_js}</script>
  <script>
    (function() {{
      try {{
        var payload = {payload};
        var gd = document.getElementById('plot');
        Plotly.newPlot(gd, payload.data || [], payload.layout || {{}}, {{
          displaylogo: false,
          responsive: true
        }});
      }} catch (e) {{
        console.error('Plotly render failed:', e);
        document.body.innerHTML = '<p style="font-family:sans-serif;padding:1em">'
          + 'Plot failed to render: ' + e + '</p>';
      }}
    }})();
  </script>
</body>
</html>"""
    path.write_text(html, encoding="utf-8")
