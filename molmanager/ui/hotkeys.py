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

"""Configurable application hotkeys (persisted with QSettings)."""

from __future__ import annotations

import json
from dataclasses import dataclass

from PyQt5.QtCore import QSettings
from PyQt5.QtGui import QKeySequence
from PyQt5.QtWidgets import QAction

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY_HOTKEYS = "gui/hotkeys"


@dataclass(frozen=True)
class HotkeySpec:
    """One bindable command."""

    action_id: str
    label: str
    category: str
    defaults: tuple[str, ...] = ()


# Stable ids — defaults mirror the built-in menubar shortcuts.
HOTKEY_SPECS: tuple[HotkeySpec, ...] = (
    HotkeySpec("file.open", "Open File…", "File", ()),
    HotkeySpec("file.export_all", "Save File…", "File", ()),
    HotkeySpec("file.open_session", "Open Session…", "File", ("Ctrl+O",)),
    HotkeySpec("file.save_session", "Save Session…", "File", ("Ctrl+S",)),
    HotkeySpec("file.close_session", "Close Session", "File", ("Ctrl+Shift+Backspace",)),
    HotkeySpec("file.browser", "Browser…", "Data", ()),
    HotkeySpec("edit.undo", "Undo", "Edit", ("Ctrl+Z",)),
    HotkeySpec("edit.redo", "Redo", "Edit", ("Ctrl+Y", "Ctrl+Shift+Z")),
    HotkeySpec("edit.copy", "Copy", "Edit", ("Ctrl+C",)),
    HotkeySpec("edit.paste", "Paste", "Edit", ("Ctrl+V",)),
    HotkeySpec("edit.find_replace", "Find and Replace…", "Edit", ("Ctrl+H",)),
    HotkeySpec("edit.delete_selection", "Delete Selection", "Edit", ("Del",)),
    HotkeySpec("edit.invert_selection", "Invert Selection", "Edit", ()),
    HotkeySpec("edit.clear_selection", "Clear Selection", "Edit", ("Ctrl+Shift+D",)),
    HotkeySpec("tools.search", "Search…", "Data", ("Ctrl+F",)),
    HotkeySpec("tools.toggle_filter_panel", "Toggle Filter Panel", "Data", ("Ctrl+Shift+L",)),
    HotkeySpec("tools.calculate_descriptors", "Calculate Descriptors…", "Chemistry", ()),
    HotkeySpec("tools.sketcher", "Sketcher…", "Tools", ()),
    HotkeySpec("tools.calculator", "Calculator…", "Tools", ()),
    HotkeySpec("tools.macros", "Macros…", "Tools", ()),
    HotkeySpec("tools.fingerprint_similarity", "Fingerprint Similarity…", "Data", ()),
    HotkeySpec("tools.render_2d", "Prepare…", "Chemistry", ()),
    HotkeySpec("data.plotter", "Plotter…", "Data", ()),
    HotkeySpec("data.cluster", "Cluster…", "Data", ()),
    HotkeySpec("data.add_row", "Add Row…", "Data", ()),
    HotkeySpec("data.add_column", "Add Column…", "Data", ()),
    HotkeySpec("data.add_to_list", "Add to List", "Data", ("Ctrl+L",)),
    HotkeySpec("data.analyze_table", "Statistics…", "Data", ()),
    HotkeySpec("data.split_column", "Split Column…", "Data", ()),
    HotkeySpec("data.join_columns", "Join Columns…", "Data", ()),
    HotkeySpec("data.binning", "Binning…", "Data", ()),
    HotkeySpec("help.user_guides", "User Guide", "Help", ("F1",)),
    HotkeySpec("help.citations", "Citations", "Help", ()),
)

_SPECS_BY_ID: dict[str, HotkeySpec] = {s.action_id: s for s in HOTKEY_SPECS}


def default_shortcuts(action_id: str) -> list[str]:
    spec = _SPECS_BY_ID.get(action_id)
    if spec is None:
        return []
    return list(spec.defaults)


def load_hotkey_overrides() -> dict[str, list[str]]:
    """User overrides: action_id → shortcut strings (empty list = explicitly unbound)."""
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY_HOTKEYS, "")
    if not raw:
        return {}
    try:
        data = json.loads(str(raw))
    except (json.JSONDecodeError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, list[str]] = {}
    for key, val in data.items():
        if not isinstance(key, str) or key not in _SPECS_BY_ID:
            continue
        if val is None or val == "":
            out[key] = []
        elif isinstance(val, str):
            out[key] = _normalize_shortcut_list([val])
        elif isinstance(val, list):
            out[key] = _normalize_shortcut_list([str(x) for x in val])
    return out


def save_hotkey_overrides(overrides: dict[str, list[str]]) -> None:
    payload: dict[str, list[str] | str] = {}
    for spec in HOTKEY_SPECS:
        if spec.action_id in overrides:
            payload[spec.action_id] = overrides[spec.action_id]
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(
        _SETTINGS_KEY_HOTKEYS,
        json.dumps(payload),
    )


def clear_hotkey_overrides() -> None:
    QSettings(_SETTINGS_ORG, _SETTINGS_APP).remove(_SETTINGS_KEY_HOTKEYS)


def _normalize_shortcut_list(raw: list[str]) -> list[str]:
    out: list[str] = []
    for item in raw:
        text = (item or "").strip()
        if not text:
            continue
        seq = QKeySequence(text)
        norm = seq.toString(QKeySequence.PortableText).strip()
        if norm and norm not in out:
            out.append(norm)
    return out


def effective_shortcuts(action_id: str, overrides: dict[str, list[str]] | None = None) -> list[str]:
    if overrides is None:
        overrides = load_hotkey_overrides()
    if action_id in overrides:
        return list(overrides[action_id])
    return default_shortcuts(action_id)


def apply_shortcuts_to_action(action: QAction, shortcuts: list[str]) -> None:
    from PyQt5.QtCore import Qt

    if shortcuts:
        action.setShortcuts([QKeySequence(s) for s in shortcuts])
        action.setShortcutContext(Qt.ApplicationShortcut)
    else:
        action.setShortcuts([])


def apply_hotkey_to_action(
    action_id: str,
    action: QAction,
    *,
    overrides: dict[str, list[str]] | None = None,
) -> None:
    apply_shortcuts_to_action(action, effective_shortcuts(action_id, overrides))


def find_duplicate_bindings(
    bindings: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Return shortcut → action_ids when the same key is assigned more than once."""
    key_to_ids: dict[str, list[str]] = {}
    for action_id, shortcuts in bindings.items():
        for s in shortcuts:
            key_to_ids.setdefault(s, []).append(action_id)
    return {k: ids for k, ids in key_to_ids.items() if len(ids) > 1}
