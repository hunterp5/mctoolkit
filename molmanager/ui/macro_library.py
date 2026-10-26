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

"""User macro library in QSettings.

Recipes are not part of the table session. The same library is available in
every file the user opens on this machine.
"""

from __future__ import annotations

import json

from PyQt5.QtCore import QSettings

from ..workflows.macro_recipe import (
    MacroDocumentError,
    MacroRecipe,
    library_from_json,
    library_to_json,
)

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY = "macros/library"


def load_macro_library() -> list[MacroRecipe]:
    """Recipes the user has saved. Corrupt or empty settings yield an empty library."""
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY, "")
    if not raw:
        return []
    try:
        payload = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return []
    try:
        return library_from_json(payload)
    except MacroDocumentError:
        return []


def save_macro_library(recipes: list[MacroRecipe]) -> None:
    """Replace the saved library."""
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(
        _SETTINGS_KEY,
        json.dumps(library_to_json(recipes)),
    )
