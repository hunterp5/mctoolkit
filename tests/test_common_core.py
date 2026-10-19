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

"""Common-core search and its dialog defaults."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.chem.common_core import (
    COMMON_CORE_HEADER,
    CORE_ATOM_MAP_HEADER,
    CORE_MATCH_HEADER,
    build_common_core_rows,
)
from molmanager.ui.dialogs.substructure import CommonCoreDialog


def _mol(smiles: str):
    mol = Chem.MolFromSmiles(smiles)
    assert mol is not None
    return mol


def test_common_core_ignores_one_outlier() -> None:
    rows = build_common_core_rows(
        [(1, _mol("c1ccccc1")), (2, _mol("Cc1ccccc1")), (3, _mol("CCO"))],
        outliers=1,
        complete_rings=True,
        timeout=30,
    )
    by_oid = dict(rows)
    assert by_oid[1][COMMON_CORE_HEADER] == by_oid[3][COMMON_CORE_HEADER]
    assert by_oid[1][CORE_MATCH_HEADER] == "yes"
    assert by_oid[2][CORE_MATCH_HEADER] == "yes"
    assert by_oid[3][CORE_MATCH_HEADER] == "no"
    assert by_oid[3][CORE_ATOM_MAP_HEADER] == ""
    assert len(by_oid[1][CORE_ATOM_MAP_HEADER].split(",")) == 6
    query = Chem.MolFromSmarts(by_oid[1][COMMON_CORE_HEADER])
    assert query is not None
    assert _mol("c1ccccc1").HasSubstructMatch(query)
    assert not _mol("CCO").HasSubstructMatch(query)


def test_common_core_requires_two_structures() -> None:
    with pytest.raises(ValueError, match="at least two"):
        build_common_core_rows([(1, _mol("CCO"))], outliers=0, complete_rings=True, timeout=5)


def test_missing_structure_is_not_a_search_row() -> None:
    rows = build_common_core_rows(
        [(1, _mol("c1ccccc1")), (2, _mol("Cc1ccccc1")), (3, None)],
        outliers=0,
        complete_rings=True,
        timeout=30,
    )
    by_oid = dict(rows)
    assert by_oid[3][COMMON_CORE_HEADER] == "N/A"
    assert by_oid[3][CORE_MATCH_HEADER] == "N/A"
    assert by_oid[1][CORE_MATCH_HEADER] == "yes"


def test_common_core_dialog_defaults(qapp) -> None:  # noqa: ARG001
    dlg = CommonCoreDialog(["Structure"], selected_row_count=2)
    params = dlg.params()
    assert params.structure_source == "Structure"
    assert params.outliers == 0
    assert params.complete_rings is True
    assert params.timeout == 30
    dlg.close()
