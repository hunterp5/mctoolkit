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

"""Kyte–Doolittle colors for the pocket hydrophobicity surface."""

from __future__ import annotations

from molmanager.protein.surface_color import (
    hydrophobicity_color,
    hydrophobicity_residue_colors,
    hydrophobicity_value,
)


def _channel(color: str, index: int) -> int:
    return int(color[1 + index * 2 : 3 + index * 2], 16)


def test_hydrophobicity_scale_and_colors() -> None:
    assert hydrophobicity_value("ILE") == 4.5
    assert hydrophobicity_value("arg") == -4.5
    assert hydrophobicity_value("HID") == hydrophobicity_value("HIS")
    assert hydrophobicity_value("ZZZ") is None
    ile = hydrophobicity_color("ILE")
    arg = hydrophobicity_color("ARG")
    assert _channel(ile, 0) > _channel(arg, 0)
    assert _channel(arg, 2) > _channel(ile, 2)
    assert hydrophobicity_color("not-a-residue") == "#f7f7f7"
    colors = hydrophobicity_residue_colors()
    assert colors["ALA"] == hydrophobicity_color("ALA")
    assert colors["MSE"] == hydrophobicity_color("MET")
