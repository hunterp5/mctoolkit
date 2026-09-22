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

"""Shared Qt WebEngine shell for interactive Plotly (Plotter + PlotlyInteractiveView)."""

from __future__ import annotations

import tempfile
from pathlib import Path

from plotly.offline import get_plotlyjs

_SHELL_HTML_PATH = Path(__file__).with_name("plotly_shell.html")
_PLOTLY_JS: str | None = None
_SHELL_HTML: dict[int, str] = {}
_SHELL_PATHS: dict[int, Path] = {}


def sanitized_plotly_js() -> str:
    """Plotly.js safe for embedding in HTML (Qt/Chromium quirks)."""
    global _PLOTLY_JS
    if _PLOTLY_JS is None:
        _PLOTLY_JS = (
            get_plotlyjs()
            .replace(":focus-visible", ":focus")
            .replace("</script>", "<\\/script>")
        )
    return _PLOTLY_JS


def _overlay_max_points() -> int:
    from ..platform_support.config import load_config

    return int(load_config().plot_selection_overlay_max_points)


def _interactive_plot_shell_html_for(overlay_max: int) -> str:
    html = _SHELL_HTML.get(overlay_max)
    if html is not None:
        return html
    plotly_js = sanitized_plotly_js()
    template = _SHELL_HTML_PATH.read_text(encoding="utf-8")
    html = template.replace("__PLOTLY_JS__", plotly_js).replace(
        "__OVERLAY_MAX__", str(overlay_max)
    )
    _SHELL_HTML[overlay_max] = html
    return html


def interactive_plot_shell_html() -> str:
    """HTML document with Plotly, QWebChannel bridge, selection, and Plotter-specific click handlers."""
    return _interactive_plot_shell_html_for(_overlay_max_points())


def ensure_interactive_plot_shell() -> Path:
    """On-disk Plotly shell, written once per overlay-max in this process."""
    overlay_max = _overlay_max_points()
    path = _SHELL_PATHS.get(overlay_max)
    if path is not None and path.is_file():
        return path
    path = Path(tempfile.gettempdir()) / f"MOLMANAGER_plot_shell_{overlay_max}.html"
    path.write_text(_interactive_plot_shell_html_for(overlay_max), encoding="utf-8")
    _SHELL_PATHS[overlay_max] = path
    return path


def write_interactive_plot_shell(path: Path) -> None:
    path.write_text(interactive_plot_shell_html(), encoding="utf-8")
