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

"""Settings → Configure tool paths."""

from __future__ import annotations

from PyQt5.QtWidgets import QPushButton

from molmanager.platform_support.tool_paths import (
    TOOL_GNINA,
    TOOL_JAVA,
    configured_executable,
    save_tool_path,
)
from molmanager.workers.protein_prepare_amber import amber_program


def test_save_tool_path_roundtrip_and_clear() -> None:
    assert configured_executable(TOOL_GNINA) == ""
    assert save_tool_path(TOOL_GNINA, "  /usr/local/bin/gnina  ") == "/usr/local/bin/gnina"
    assert configured_executable(TOOL_GNINA) == "/usr/local/bin/gnina"
    assert save_tool_path(TOOL_GNINA, "  ") == ""
    assert configured_executable(TOOL_GNINA) == ""


def test_amber_program_directory_and_sibling() -> None:
    assert amber_program("antechamber", "antechamber") == "antechamber"
    assert amber_program("parmchk2", "antechamber") == "parmchk2"
    assert amber_program("parmchk2", "antechamber.exe") == "parmchk2.exe"
    assert amber_program("antechamber", "/opt/amber/bin") == "/opt/amber/bin/antechamber"
    assert amber_program("tleap", "/opt/amber/bin/antechamber") == "/opt/amber/bin/tleap"
    assert (
        amber_program("parmchk2", r"C:\amber\bin\antechamber.exe") == r"C:\amber\bin\parmchk2.exe"
    )
    assert amber_program("tleap", r"C:\amber\bin") == r"C:\amber\bin\tleap"


def test_ambertools_available_probes_configured_bin(monkeypatch) -> None:
    from molmanager.workers import protein_prepare_amber as amber

    captured: dict[str, list[str]] = {}

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    def _run(argv, **_kwargs):
        captured["argv"] = list(argv)
        return _Proc()

    monkeypatch.setattr("molmanager.platform_support.wsl_launcher.run_linux_tool", _run)
    assert amber.ambertools_available(user_path="/opt/amber/bin") is True
    assert captured["argv"][:2] == ["test", "-x"]
    assert captured["argv"][2].endswith("/opt/amber/bin/antechamber")


def test_gnina_dialog_uses_configured_executable(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.gnina_dock import GninaDockDialog

    save_tool_path(TOOL_GNINA, "/usr/local/bin/gnina")
    dlg = GninaDockDialog(None)
    assert dlg._gnina_executable() == "/usr/local/bin/gnina"
    dlg.close()


def test_tool_path_dialog_saves(qapp, tmp_path) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.tool_path_settings import ToolPathDialog

    dlg = ToolPathDialog("java", None)
    labels = [b.text().replace("&", "") for b in dlg.findChildren(QPushButton)]
    assert labels == ["Browse…", "Test", "OK"]
    exe = tmp_path / "java.exe"
    dlg.path_edit.setText(str(exe))
    dlg.accept()
    assert configured_executable(TOOL_JAVA) == str(exe)
    dlg.close()


def test_mafft_dialog_has_folder_browse(qapp) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.tool_path_settings import ToolPathDialog

    dlg = ToolPathDialog("mafft", None)
    labels = [b.text().replace("&", "") for b in dlg.findChildren(QPushButton)]
    assert labels == ["Browse…", "Folder…", "Test", "OK"]
    dlg.close()


def test_biotransformer_settings_saves_jar(qapp, monkeypatch, tmp_path) -> None:  # noqa: ARG001
    from molmanager.ui.dialogs.biotransformer_settings import BiotransformerSettingsDialog

    saved: dict[str, str] = {}
    monkeypatch.setattr(
        "molmanager.ui.dialogs.biotransformer_settings.configured_biotransformer_jar_text",
        lambda: "",
    )
    monkeypatch.setattr(
        "molmanager.ui.dialogs.biotransformer_settings.resolve_biotransformer_jar",
        lambda: None,
    )
    monkeypatch.setattr(
        "molmanager.ui.dialogs.biotransformer_settings.set_configured_biotransformer_jar",
        lambda path: saved.setdefault("path", str(path)),
    )
    dlg = BiotransformerSettingsDialog()
    labels = [b.text().replace("&", "") for b in dlg.findChildren(QPushButton)]
    assert "Browse JAR…" in labels
    assert "Install…" in labels
    jar = tmp_path / "BioTransformer3.0.jar"
    dlg.path_edit.setText(str(jar))
    dlg.accept()
    assert saved["path"] == str(jar)
    dlg.close()
