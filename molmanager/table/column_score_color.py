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

"""Traffic-light coloring for drug-likeness score columns (QED, AB-MPS, BBB, CNS MPO)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Match "QED Score (1)" / "CNS MPO score (2)" after uniquify.
_DUP_SUFFIX = re.compile(r"\s+\(\d+\)\s*$")

# Same family as Color Column defaults: green = favorable, red = unfavorable.
COLOR_FAVORABLE_RGB = (46, 164, 79)
COLOR_MID_RGB = (245, 209, 84)
COLOR_UNFAVORABLE_RGB = (236, 73, 73)
COLOR_ALPHA = 96


@dataclass(frozen=True)
class FavorableScoreColorSpec:
    """Absolute range for a score whose favorable end should be green."""

    min_value: float
    mid_value: float
    max_value: float
    higher_is_better: bool


# Keys are normalized header stems (hyphens → spaces, no uniquify suffix).
_SCORE_SPECS: dict[str, FavorableScoreColorSpec] = {
    "qed score": FavorableScoreColorSpec(0.0, 0.5, 1.0, True),
    "ab mps score": FavorableScoreColorSpec(0.0, 14.0, 28.0, False),
    "bbb score": FavorableScoreColorSpec(0.0, 4.0, 6.0, True),
    "cns mpo score": FavorableScoreColorSpec(0.0, 3.0, 6.0, True),
}


def normalize_score_color_header(header_name: str) -> str:
    """Lowercase stem used to look up auto-color specs (strips `` (n)`` suffixes)."""
    text = _DUP_SUFFIX.sub("", (header_name or "").strip()).casefold()
    text = text.replace("−", "-").replace("–", "-").replace("-", " ")
    return " ".join(text.split())


def favorable_score_color_spec(header_name: str) -> FavorableScoreColorSpec | None:
    """Return the auto-color spec for a calculated QED / AB-MPS / BBB / CNS MPO column, if any."""
    return _SCORE_SPECS.get(normalize_score_color_header(header_name))
