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

"""Format PubChem titles and synonym lists for the PubChem query dialog."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

MAX_SYNONYMS = 50


@dataclass(frozen=True)
class CompoundNames:
    """PubChem names for one structure (empty strings mean not found)."""

    common_name: str = ""
    synonyms: str = ""


def format_synonym_list(names: Sequence[object], *, limit: int = MAX_SYNONYMS) -> str:
    """Deduped, semicolon-separated synonyms with a stable cap."""
    out: list[str] = []
    seen: set[str] = set()
    cap = max(1, int(limit))
    for raw in names:
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(text)
        if len(out) >= cap:
            break
    return "; ".join(out)


def names_from_title_and_synonyms(title: str, synonyms: Sequence[object]) -> CompoundNames:
    """Build a name record from a PubChem Title and synonym list."""
    formatted = format_synonym_list(synonyms)
    common = (title or "").strip()
    if not common:
        for raw in synonyms:
            text = str(raw or "").strip()
            if text:
                common = text
                break
    return CompoundNames(common_name=common, synonyms=formatted)
