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

"""PubChem title and synonym formatting for the query dialog."""

from __future__ import annotations

from molmanager.sources.pubchem_names import (
    format_synonym_list,
    names_from_title_and_synonyms,
)


def test_format_synonym_list_dedupes_and_caps() -> None:
    text = format_synonym_list(
        ["aspirin", "Aspirin", "acetylsalicylic acid", "", "ASA"],
        limit=2,
    )
    assert text == "aspirin; acetylsalicylic acid"


def test_names_from_title_and_synonyms_keeps_title() -> None:
    names = names_from_title_and_synonyms(
        "aspirin",
        ["aspirin", "Acetylsalicylic acid", "ASA"],
    )
    assert names.common_name == "aspirin"
    assert names.synonyms.startswith("aspirin; Acetylsalicylic acid")


def test_names_use_first_synonym_when_title_missing() -> None:
    names = names_from_title_and_synonyms("", ["trivial name", "other"])
    assert names.common_name == "trivial name"
    assert names.synonyms == "trivial name; other"
