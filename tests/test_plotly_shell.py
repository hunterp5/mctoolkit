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

"""Tests for shared interactive Plotly WebEngine shell."""

from molmanager.ui.plotly_shell import interactive_plot_shell_html, sanitized_plotly_js


def test_sanitized_plotly_js_escapes_script_close():
    js = sanitized_plotly_js()
    assert "</script>" not in js
    assert "<\\/script>" in js or "script" in js


def test_interactive_plot_shell_includes_bridge_handlers():
    html = interactive_plot_shell_html()
    assert "molmanagerApply" in html
    assert "molmanagerSetSelection" in html
    assert "applySelectionIndices" in html
    assert "primarySelectionTraceInfo" in html
    assert "molmanager_selection_overlay" in html
    assert "pendingSelectionJson" in html
    assert "heatmapCellClicked" in html
    assert "radarTraceClicked" in html
    assert "molmanager_selection_traces" in html
    assert "Plotly.Plots.resize" in html
    assert "addEventListener('resize'" in html
    assert "SELECTION_OVERLAY_MAX" in html
    assert "idxs.length > SELECTION_OVERLAY_MAX" in html
    assert 'typeof payloadJson === "string"' in html
    assert "viewNavBusy || middlePan" in html
    assert "captureAxisView" in html
    assert "afterSelectionDraw" in html
    assert "savedViewOnPointerDown" in html
    assert "xaxis.autorange" in html
    assert "scene.camera" in html
    assert "viewForSelectionRestore" in html
    assert "forgetSavedAxisView" in html


def test_interactive_plot_shell_bakes_overlay_max_from_config(monkeypatch):
    monkeypatch.setenv("MOLMANAGER_PLOT_SELECTION_OVERLAY_MAX", "250")
    html = interactive_plot_shell_html()
    assert "var SELECTION_OVERLAY_MAX = 250;" in html


def test_ensure_interactive_plot_shell_reuses_file(monkeypatch):
    from molmanager.ui import plotly_shell as shell

    monkeypatch.setattr(shell, "_SHELL_PATHS", {})
    first = shell.ensure_interactive_plot_shell()
    second = shell.ensure_interactive_plot_shell()
    assert first == second
    assert first.is_file()
    assert first.stat().st_size > 1000

