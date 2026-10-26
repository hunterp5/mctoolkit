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

"""Tool requests are plain choices. They do not import Qt."""

from __future__ import annotations

import sys

import pytest

from molmanager.workflows.tool_requests import (
    NumericFilterClause,
    TextFilterClause,
    clause_as_mapping,
    filter_request_from_params,
    row_scope_from_only_selected,
)


def test_tool_requests_do_not_import_qt():
    for name in list(sys.modules):
        if name.startswith("molmanager.workflows.tool_requests"):
            del sys.modules[name]
    qt_already_loaded = "PyQt5.QtWidgets" in sys.modules
    import molmanager.workflows.tool_requests  # noqa: F401

    if not qt_already_loaded:
        assert "PyQt5.QtWidgets" not in sys.modules


def test_selected_rows_map_to_the_selection_scope():
    assert row_scope_from_only_selected(False) == "table"
    assert row_scope_from_only_selected(True) == "selection"


def test_filter_request_resolves_column_refs():
    request = filter_request_from_params(
        {
            "replace": False,
            "clauses": [
                {
                    "kind": "numeric",
                    "column": "${desc1.MolWt}",
                    "min": 0,
                    "max": 500,
                    "inverted": False,
                },
                {
                    "kind": "text",
                    "column": "Name",
                    "text": "acid",
                    "partial_match": True,
                    "case_sensitive": False,
                },
            ],
        },
        resolve=lambda text: "Mol Weight" if text.startswith("${") else text,
    )
    assert request.replace is False
    assert request.clauses[0] == NumericFilterClause("Mol Weight", 0.0, 500.0, False)
    assert isinstance(request.clauses[1], TextFilterClause)
    assert clause_as_mapping(request.clauses[0])["kind"] == "numeric"
    assert clause_as_mapping(request.clauses[0])["column"] == "Mol Weight"


def test_unknown_filter_kind_is_rejected():
    with pytest.raises(ValueError, match="Unknown filter kind"):
        filter_request_from_params({"clauses": [{"kind": "nope"}]}, resolve=lambda text: text)
