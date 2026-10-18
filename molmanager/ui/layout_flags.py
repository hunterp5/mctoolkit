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

"""Rollback switches for workspace docking and resize behavior.

Each flag reads ``QSettings`` key ``layout/<name>``. An environment variable
``MOLMANAGER_LAYOUT_<NAME>`` (``0``/``1``) overrides the stored value so a regression can
be switched off without a release or a settings UI.
"""

from __future__ import annotations

import os

from PyQt5.QtCore import QSettings

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"

#: Show floating plot hosts once at final geometry (no off-screen pre-show).
FLAG_DIRECT_FLOAT_SHOW = "direct_float_show"
#: Show a captured image of a web view while it is reparented between windows.
FLAG_SNAPSHOT_TRANSITIONS = "snapshot_transitions"

_DEFAULTS: dict[str, bool] = {
    FLAG_DIRECT_FLOAT_SHOW: True,
    FLAG_SNAPSHOT_TRANSITIONS: False,
}

_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


def _parse_bool(raw: object) -> bool | None:
    if isinstance(raw, bool):
        return raw
    text = str(raw).strip().lower()
    if text in _TRUE_VALUES:
        return True
    if text in _FALSE_VALUES:
        return False
    return None


def layout_flag(name: str) -> bool:
    """Return the current value of layout flag ``name``."""
    default = _DEFAULTS.get(name, False)
    env_value = _parse_bool(os.environ.get(f"MOLMANAGER_LAYOUT_{name.upper()}", ""))
    if env_value is not None:
        return env_value
    try:
        raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(f"layout/{name}", None)
    except RuntimeError:
        return default
    if raw is None:
        return default
    parsed = _parse_bool(raw)
    return default if parsed is None else parsed


def set_layout_flag(name: str, enabled: bool | None) -> None:
    """Persist ``enabled`` for flag ``name`` (``None`` removes the override)."""
    settings = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    key = f"layout/{name}"
    if enabled is None:
        settings.remove(key)
    else:
        settings.setValue(key, bool(enabled))
