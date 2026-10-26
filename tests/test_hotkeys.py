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

"""Hotkey registry and persistence."""

from __future__ import annotations

from molmanager.ui.hotkeys import (
    clear_hotkey_overrides,
    default_shortcuts,
    effective_shortcuts,
    find_duplicate_bindings,
    save_hotkey_overrides,
)


def test_default_and_override_roundtrip():
    clear_hotkey_overrides()
    assert "Ctrl+F" in default_shortcuts("tools.search")
    save_hotkey_overrides({"tools.search": ["Ctrl+Shift+F"]})
    assert effective_shortcuts("tools.search") == ["Ctrl+Shift+F"]
    assert effective_shortcuts("file.open") == default_shortcuts("file.open")
    clear_hotkey_overrides()
    assert effective_shortcuts("tools.search") == default_shortcuts("tools.search")


def test_ctrl_o_and_s_default_to_session():
    clear_hotkey_overrides()
    assert default_shortcuts("file.open_session") == ["Ctrl+O"]
    assert default_shortcuts("file.save_session") == ["Ctrl+S"]
    assert default_shortcuts("file.open") == []
    assert default_shortcuts("file.export_all") == []
    dups = find_duplicate_bindings(
        {
            "file.open": default_shortcuts("file.open"),
            "file.export_all": default_shortcuts("file.export_all"),
            "file.open_session": default_shortcuts("file.open_session"),
            "file.save_session": default_shortcuts("file.save_session"),
        }
    )
    assert dups == {}
    clear_hotkey_overrides()


def test_search_and_filter_hotkeys_are_data_category():
    from molmanager.ui.hotkeys import HOTKEY_SPECS

    by_id = {spec.action_id: spec for spec in HOTKEY_SPECS}
    assert by_id["tools.search"].category == "Data"
    assert by_id["tools.fingerprint_similarity"].category == "Data"
    assert by_id["tools.toggle_filter_panel"].category == "Data"
    assert by_id["file.browser"].category == "Data"
    assert by_id["data.add_to_list"].label == "Add to List"
    assert by_id["data.add_to_list"].category == "Data"
    assert by_id["data.add_to_list"].defaults == ("Ctrl+L",)
    assert by_id["edit.find_replace"].category == "Edit"
    assert by_id["edit.find_replace"].defaults == ("Ctrl+H",)


def test_find_duplicate_bindings():
    dups = find_duplicate_bindings(
        {
            "a": ["Ctrl+F"],
            "b": ["Ctrl+F"],
            "c": [],
        }
    )
    assert "Ctrl+F" in dups
    assert set(dups["Ctrl+F"]) == {"a", "b"}
