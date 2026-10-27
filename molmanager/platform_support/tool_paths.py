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

TOOL_AIZYNTH_CONFIG = "aizynthfinder_config"
TOOL_AIZYNTH_PYTHON = "aizynthfinder_python"
TOOL_AMBER = "ambertools"
TOOL_CONFGEN = "confgen"
TOOL_GNINA = "gnina"
TOOL_JAVA = "java"
TOOL_MAFFT = "mafft"
TOOL_OBABEL = "obabel"
TOOL_REINVENT = "reinvent"
TOOL_XTB = "xtb"

_SETTINGS_KEYS = {
    TOOL_AIZYNTH_CONFIG: "tools/aizynthfinder_config",
    TOOL_AIZYNTH_PYTHON: "tools/aizynthfinder_python",
    TOOL_AMBER: "tools/ambertools_executable",
    TOOL_CONFGEN: "tools/confgen_executable",
    TOOL_GNINA: "tools/gnina_executable",
    TOOL_JAVA: "tools/java_executable",
    TOOL_MAFFT: "tools/mafft_executable",
    TOOL_OBABEL: "tools/obabel_executable",
    TOOL_REINVENT: "tools/reinvent_executable",
    TOOL_XTB: "tools/xtb_executable",
}

# Machine policy keys. A present key wins over Settings → Configure.
_POLICY_KEYS = {
    TOOL_AIZYNTH_CONFIG: "MOLMANAGER_TOOL_AIZYNTH_CONFIG",
    TOOL_AIZYNTH_PYTHON: "MOLMANAGER_TOOL_AIZYNTH_PYTHON",
    TOOL_AMBER: "MOLMANAGER_TOOL_AMBER",
    TOOL_CONFGEN: "MOLMANAGER_TOOL_CONFGEN",
    TOOL_GNINA: "MOLMANAGER_TOOL_GNINA",
    TOOL_JAVA: "MOLMANAGER_TOOL_JAVA",
    TOOL_MAFFT: "MOLMANAGER_TOOL_MAFFT",
    TOOL_OBABEL: "MOLMANAGER_TOOL_OBABEL",
    TOOL_REINVENT: "MOLMANAGER_TOOL_REINVENT",
    TOOL_XTB: "MOLMANAGER_TOOL_XTB",
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


def policy_tool_path(tool: str) -> str | None:
    """Path forced by the machine policy, or ``None`` when *tool* is not pinned."""
    name = _POLICY_KEYS.get(tool)
    if name is None:
        return None
    from .session_runtime import policy_value

    return policy_value(name)


def configured_executable(tool: str) -> str:
    """Policy path, otherwise the saved Configure path. ``""`` when neither is set."""
    forced = policy_tool_path(tool)
    if forced is not None:
        return forced
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
    """Policy path when pinned, otherwise *user_path* or the saved Configure path."""
    forced = policy_tool_path(tool)
    if forced is not None:
        return forced
    text = (user_path or "").strip()
    if text:
        return text
    return configured_executable(tool)
