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

"""Saved paths for optional external tools (Settings → Configure)."""

from __future__ import annotations

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"

TOOL_AMBER = "ambertools"
TOOL_CONFGEN = "confgen"
TOOL_GNINA = "gnina"
TOOL_JAVA = "java"
TOOL_MAFFT = "mafft"
TOOL_OBABEL = "obabel"
TOOL_XTB = "xtb"

_SETTINGS_KEYS = {
    TOOL_AMBER: "tools/ambertools_executable",
    TOOL_CONFGEN: "tools/confgen_executable",
    TOOL_GNINA: "tools/gnina_executable",
    TOOL_JAVA: "tools/java_executable",
    TOOL_MAFFT: "tools/mafft_executable",
    TOOL_OBABEL: "tools/obabel_executable",
    TOOL_XTB: "tools/xtb_executable",
}


def _qsettings():
    """Process QSettings store. Tests replace this with an isolated ini file."""
    from PyQt5.QtCore import QSettings

    return QSettings(_SETTINGS_ORG, _SETTINGS_APP)


def _key(tool: str) -> str:
    try:
        return _SETTINGS_KEYS[tool]
    except KeyError as exc:
        raise KeyError(f"Unknown tool path setting: {tool}") from exc


def configured_executable(tool: str) -> str:
    """Saved path for *tool*, or ``""`` when unset or Qt settings are unavailable."""
    try:
        settings = _qsettings()
    except ImportError:
        return ""
    raw = settings.value(_key(tool), "")
    return str(raw or "").strip()


def save_tool_path(tool: str, path: str) -> str:
    """Persist *path* for *tool*. An empty path clears the setting."""
    text = (path or "").strip()
    settings = _qsettings()
    key = _key(tool)
    if text:
        settings.setValue(key, text)
    else:
        settings.remove(key)
    return text


def effective_tool_path(tool: str, user_path: str = "") -> str:
    """*user_path* when set, otherwise the saved Configure path (may be empty)."""
    text = (user_path or "").strip()
    if text:
        return text
    return configured_executable(tool)
