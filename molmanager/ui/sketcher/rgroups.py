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

"""Numbered R-group atoms for the sketcher (R1, R2).

An R-group atom is a dummy with an atom-map number. R-group enumeration reads
that as ``[*:1]`` or ``[*:2]`` on the core.
"""

from __future__ import annotations

from typing import Any

RGROUP_LABELS: tuple[int, ...] = (1, 2)


def rgroup_element(label: int) -> str:
    """Toolbar and node symbol for one attachment number."""
    return f"R{int(label)}"


def rgroup_label_from_element(element: str | None) -> int | None:
    """Return 1 or 2 when *element* is ``R1`` or ``R2``."""
    text = (element or "").strip().upper()
    if len(text) == 2 and text[0] == "R" and text[1].isdigit():
        label = int(text[1])
        if label in RGROUP_LABELS:
            return label
    return None


def is_rgroup_element(element: str | None) -> bool:
    return rgroup_label_from_element(element) is not None


def is_rgroup_node(node: dict[str, Any]) -> bool:
    return is_rgroup_element(str(node.get("element") or ""))
