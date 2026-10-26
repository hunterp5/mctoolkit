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

"""WSL executable settings and launcher."""

from __future__ import annotations

from pathlib import Path

import pytest

from molmanager.platform_support.wsl_launcher import (
    default_wsl_executable,
    linux_path,
    windows_path_to_wsl,
    wsl_argv,
)


def test_windows_path_to_wsl_drive_letter() -> None:
    assert windows_path_to_wsl(r"C:\Users\chem\lig.mol2") == "/mnt/c/Users/chem/lig.mol2"
    assert windows_path_to_wsl(Path(r"D:/tmp/openmm")) == "/mnt/d/tmp/openmm"


def test_linux_path_passthrough_on_linux(monkeypatch) -> None:
    monkeypatch.setattr("molmanager.platform_support.wsl_launcher.sys.platform", "linux")
    assert linux_path("/tmp/lig.mol2") == "/tmp/lig.mol2"


def test_wsl_argv_requires_executable(monkeypatch) -> None:
    monkeypatch.setattr(
        "molmanager.platform_support.wsl_launcher.resolve_wsl_executable", lambda _p="": None
    )
    with pytest.raises(FileNotFoundError, match="Configure → WSL"):
        wsl_argv(["uname", "-s"])


def test_wsl_argv_inserts_distro(monkeypatch, tmp_path) -> None:
    exe = tmp_path / "wsl.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "molmanager.platform_support.wsl_launcher.resolve_wsl_executable", lambda _p="": str(exe)
    )
    argv = wsl_argv(["antechamber", "-i", "lig.mol2"], distro="Ubuntu")
    assert argv[:4] == [str(exe), "-d", "Ubuntu", "--"]
    assert argv[4:] == ["antechamber", "-i", "lig.mol2"]


def test_default_wsl_executable_non_windows(monkeypatch) -> None:
    monkeypatch.setattr("molmanager.platform_support.wsl_launcher.sys.platform", "linux")
    assert default_wsl_executable() == ""


def test_wsl_settings_dialog_saves_path(qapp, monkeypatch, tmp_path):  # noqa: ARG001
    from PyQt5.QtWidgets import QPushButton

    from molmanager.ui.dialogs.wsl_settings import WslSettingsDialog

    saved: dict[str, str] = {}
    monkeypatch.setattr("molmanager.ui.dialogs.wsl_settings.load_wsl_executable", lambda: "")
    monkeypatch.setattr(
        "molmanager.ui.dialogs.wsl_settings.save_wsl_executable",
        lambda path: saved.setdefault("path", path) or path,
    )
    dlg = WslSettingsDialog()
    labels = [b.text().replace("&", "") for b in dlg.findChildren(QPushButton)]
    assert labels == ["Browse…", "Test", "OK"]
    dlg.path_edit.setText(str(tmp_path / "wsl.exe"))
    dlg.accept()
    assert saved["path"].endswith("wsl.exe")
    dlg.close()


def test_settings_menu_has_configure(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.main_window import ChemistryWorkspaceWindow

    w = ChemistryWorkspaceWindow()
    mb = w.menuBar()
    settings = next(a.menu() for a in mb.actions() if a.text().replace("&", "") == "Settings")
    labels = [a.text().replace("&", "") for a in settings.actions() if not a.isSeparator()]
    assert "WSL…" not in labels
    assert "Configure" in labels
    assert labels.index("Configure") == labels.index("Status Bar") + 1
    assert labels[-1] == "Help"
    assert "Status Bar" in labels
    assert labels.index("Status Bar") == labels.index("Hotkeys…") + 1
    assert "Structure…" not in labels
    assert "2D Render…" not in labels
    assert "Font…" not in labels
    configure = next(
        a.menu() for a in settings.actions() if a.text().replace("&", "") == "Configure"
    )
    configure_labels = [
        a.text().replace("&", "") for a in configure.actions() if not a.isSeparator()
    ]
    assert configure_labels == [
        "WSL…",
        "AmberTools…",
        "AiZynthFinder…",
        "BioTransformer…",
        "CONFORGE…",
        "Gnina…",
        "Java…",
        "MAFFT…",
        "Open Babel…",
        "REINVENT…",
        "xtb…",
    ]
    gui = next(a.menu() for a in settings.actions() if a.text().replace("&", "") == "GUI")
    gui_labels = [a.text().replace("&", "") for a in gui.actions() if not a.isSeparator()]
    assert gui_labels == ["Theme", "2D Render…", "Font…"]
    assert "Status Bar" not in gui_labels
    theme = next(a.menu() for a in gui.actions() if a.text().replace("&", "") == "Theme")
    theme_labels = [a.text().replace("&", "") for a in theme.actions() if not a.isSeparator()]
    assert theme_labels[:3] == ["Light Mode", "Dark Mode", "Groovy Mode"]
    assert theme_labels[-1] == "Custom Colors…"
    w.close()
