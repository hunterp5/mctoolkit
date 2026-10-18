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

"""Every embedded web page sizes itself through the shared resize scheduler."""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from molmanager.ui.dock_complex_viewer import build_dock_complex_html
from molmanager.ui.mol_3d_html import (
    RESIZE_KEEP_VIEW_JS,
    RESIZE_KEEP_ZOOM_JS,
    RESIZE_REFIT_JS,
    _offline_embed_index_html,
    _offline_index_html,
    _offline_index_html_multiconf,
)
from molmanager.ui.protein_viewer_html import build_protein_viewer_html
from molmanager.ui.web_resize_scheduler import (
    resize_scheduler_binding_html,
    web_resize_scheduler_js,
)

_PAGES = {
    "ligand": (lambda: _offline_index_html(""), RESIZE_KEEP_ZOOM_JS),
    "sketcher embed": (lambda: _offline_embed_index_html(""), RESIZE_REFIT_JS),
    "multi-conformer": (lambda: _offline_index_html_multiconf("W10="), RESIZE_KEEP_ZOOM_JS),
    "protein": (build_protein_viewer_html, RESIZE_KEEP_VIEW_JS),
    "dock complex": (build_dock_complex_html, RESIZE_KEEP_VIEW_JS),
}


@pytest.mark.parametrize("name", sorted(_PAGES))
def test_3dmol_page_binds_resize_scheduler_once(name):
    build, callback = _PAGES[name]
    html = build()
    assert html.count("window.molmanagerCreateResizeScheduler = function") == 1
    assert callback in html
    assert "window.molmanagerHoldResize" in html
    assert not re.search(r"window\.addEventListener\(\s*[\"']resize[\"']\s*,\s*function", html)


def test_scheduler_js_is_inline_safe():
    assert "</script>" not in web_resize_scheduler_js()


def test_binding_targets_requested_element():
    html = resize_scheduler_binding_html("void 0;", target_id="plot")
    assert 'document.getElementById("plot")' in html


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_scheduler_js_parses(tmp_path):
    path = tmp_path / "scheduler.js"
    path.write_text(web_resize_scheduler_js(), encoding="utf-8")
    result = subprocess.run(
        ["node", "--check", str(path)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
