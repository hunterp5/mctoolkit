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

"""The depiction golden set stays parseable, uniquely named, and renderable."""

from __future__ import annotations

import csv
from pathlib import Path

from rdkit import Chem

from molmanager.chem.structure_2d_depiction import render_molecule_png

GOLDEN_PATH = Path(__file__).parent / "data" / "depiction_golden.tsv"


def _golden_rows() -> list[dict[str, str]]:
    with GOLDEN_PATH.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh, delimiter="\t"))


def test_golden_set_parses_with_unique_names() -> None:
    rows = _golden_rows()
    assert len(rows) >= 40
    names = [row["name"] for row in rows]
    assert len(names) == len(set(names))
    for row in rows:
        assert row["category"], row["name"]
        assert Chem.MolFromSmiles(row["smiles"]) is not None, row["name"]


def test_golden_set_renders_with_the_table_renderer() -> None:
    for row in _golden_rows():
        png = render_molecule_png(Chem.MolFromSmiles(row["smiles"]), 210, 170)
        assert png[:8] == b"\x89PNG\r\n\x1a\n", row["name"]
