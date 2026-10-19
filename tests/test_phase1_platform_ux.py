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

"""Windows console and sleep helpers."""

from __future__ import annotations

import sys

from molmanager.platform_support.windows_console import ensure_stdio, hide_owned_windows_console
from molmanager.platform_support.windows_sleep import (
    clear_system_required,
    set_system_required_while_busy,
)
from molmanager.ui.search_panel import SearchCriterionRow


def test_ensure_stdio_fills_none_streams(monkeypatch) -> None:
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    ensure_stdio()
    assert sys.stdout is not None
    assert sys.stderr is not None


def test_hide_owned_windows_console_noops_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert hide_owned_windows_console() is False


def test_set_system_required_noops_off_windows(monkeypatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert set_system_required_while_busy(True) is False
    clear_system_required()


def test_search_criterion_row_parents_controls(qapp) -> None:  # noqa: ARG001
    row = SearchCriterionRow(show_glue=True, show_add=True)
    assert row.remove_btn.parent() is row
    assert row.glue_combo.parent() is row
    assert row.add_btn.parent() is row
    assert row.col_combo.parent() is row
    assert row.query_edit.parent() is row
    assert row.partial_cb.parent() is row
    assert row.case_cb.parent() is row
    assert not hasattr(row, "substructure_cb")
    not_idx = row.glue_combo.findData("not")
    assert not_idx >= 0
    row.glue_combo.setCurrentIndex(not_idx)
    assert row.glue() == "not"
    row.close()
