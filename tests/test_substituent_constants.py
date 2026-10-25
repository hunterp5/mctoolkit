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

"""Substituent-constant CSV loader. Values in these tests are synthetic."""

from __future__ import annotations

import pytest
from rdkit import Chem

from molmanager.analysis.substituent_constants import (
    SCHEMA_HEADER,
    attachment_key,
    load_substituent_constants,
)
from molmanager.platform_support.bundled_paths import resources_dir


def test_schema_file_is_header_only() -> None:
    path = resources_dir() / "substituent_constants.csv"
    assert path.read_text(encoding="utf-8").strip() == SCHEMA_HEADER
    with pytest.raises(ValueError, match="no substituent"):
        load_substituent_constants(path)


def test_loader_canonicalizes_attachment_smiles_and_keeps_blanks(tmp_path) -> None:
    path = tmp_path / "constants.csv"
    path.write_text(
        "smiles,pi,sigma_p,es\nH,0,0,\n*C,1.5,, -0.2\n",
        encoding="utf-8",
    )
    table = load_substituent_constants(path)
    hydrogen = table.get("H")
    methyl = table.get(attachment_key(Chem.MolFromSmiles("*C")))
    assert hydrogen is not None and hydrogen.pi == 0.0 and hydrogen.es is None
    assert methyl is not None and methyl.pi == 1.5 and methyl.sigma_p is None
    assert methyl.es == -0.2


def test_duplicate_attachment_smiles_are_rejected(tmp_path) -> None:
    path = tmp_path / "constants.csv"
    path.write_text("smiles,pi\n*C,1\nC*,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="matches the substituent"):
        load_substituent_constants(path)


def test_hydrogen_aliases_are_one_key(tmp_path) -> None:
    path = tmp_path / "constants.csv"
    path.write_text("smiles,pi\nH,0\n[H],1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="matches the substituent"):
        load_substituent_constants(path)


def test_invalid_smiles_names_the_line(tmp_path) -> None:
    path = tmp_path / "constants.csv"
    path.write_text("smiles,pi\nnot a molecule,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="Line 2"):
        load_substituent_constants(path)


def test_missing_smiles_column_is_rejected(tmp_path) -> None:
    path = tmp_path / "constants.csv"
    path.write_text("pi,sigma_p\n1,0\n", encoding="utf-8")
    with pytest.raises(ValueError, match="smiles"):
        load_substituent_constants(path)
