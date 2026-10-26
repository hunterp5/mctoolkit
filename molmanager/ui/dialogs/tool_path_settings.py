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

"""Settings → Configure editors for optional external-tool paths."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...platform_support.tool_paths import (
    TOOL_AMBER,
    TOOL_CONFGEN,
    TOOL_GNINA,
    TOOL_JAVA,
    TOOL_MAFFT,
    TOOL_OBABEL,
    TOOL_XTB,
    configured_executable,
    save_tool_path,
)
from ..qt_widget_utils import make_window_minimizable


def _initial_amber() -> str:
    return configured_executable(TOOL_AMBER) or "antechamber"


def _initial_confgen() -> str:
    from ...platform_support.bundled_paths import default_external_executable

    return configured_executable(TOOL_CONFGEN) or default_external_executable("confgen")


def _initial_gnina() -> str:
    from ...platform_support.bundled_paths import default_external_executable

    return configured_executable(TOOL_GNINA) or default_external_executable("gnina")


def _initial_java() -> str:
    from ...platform_support.bundled_paths import java_on_path

    saved = configured_executable(TOOL_JAVA)
    if saved:
        return saved
    found = java_on_path()
    return str(found) if found is not None else ""


def _initial_mafft() -> str:
    from ...platform_support.bundled_paths import (
        default_external_executable,
        resolve_mafft_executable,
    )

    saved = configured_executable(TOOL_MAFFT)
    if saved:
        return saved
    return resolve_mafft_executable() or default_external_executable("mafft")


def _initial_obabel() -> str:
    from ...platform_support.bundled_paths import default_external_executable

    return configured_executable(TOOL_OBABEL) or default_external_executable("obabel")


def _probe_amber(path: str) -> tuple[bool, str]:
    from ...workers.protein_prepare_amber import describe_ambertools

    return describe_ambertools(path)


def _probe_confgen(path: str) -> tuple[bool, str]:
    from ...conformers.conforge_generation import (
        MISSING_CONFORGE_MSG,
        python_conforge_available,
        resolve_confgen_executable,
    )

    found = resolve_confgen_executable(path)
    if found:
        return True, f"OK: {found}"
    if python_conforge_available() and not (path or "").strip():
        return True, "OK: CDPKit Python bindings (no confgen path set)."
    return False, MISSING_CONFORGE_MSG


def _probe_gnina(path: str) -> tuple[bool, str]:
    from ...docking.gnina_launch import describe_gnina

    return describe_gnina(path)


def _probe_java(path: str) -> tuple[bool, str]:
    from ...platform_support.bundled_paths import java_on_path, resolve_user_executable

    text = (path or "").strip()
    if text:
        found = resolve_user_executable(text)
        if not found:
            return False, f"Java was not found ({text})."
        exe = found
    else:
        hit = java_on_path()
        if hit is None:
            return False, "Java is not on PATH."
        exe = str(hit)
    try:
        proc = subprocess.run(
            [exe, "-version"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not run Java: {exc}"
    detail = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    first = detail.splitlines()[0] if detail else f"exit code {proc.returncode}"
    if proc.returncode == 0 or "version" in detail.lower():
        return True, f"OK ({exe}): {first}"
    failed = detail or first
    return False, f"Java ran but the version check failed:\n{failed}"


def _probe_mafft(path: str) -> tuple[bool, str]:
    from ...platform_support.bundled_paths import ensure_mafft_ready, resolve_mafft_executable

    found = resolve_mafft_executable(path)
    if found:
        return True, f"OK: {found}"
    return False, ensure_mafft_ready(path) or "MAFFT was not found."


def _probe_obabel(path: str) -> tuple[bool, str]:
    from ...conformers.openbabel_confab import MISSING_OPENBABEL_MSG, resolve_obabel_executable

    found = resolve_obabel_executable(path)
    if found:
        return True, f"OK: {found}"
    return False, MISSING_OPENBABEL_MSG


def _initial_xtb() -> str:
    from ...platform_support.bundled_paths import default_external_executable

    return configured_executable(TOOL_XTB) or default_external_executable("xtb")


def _probe_xtb(path: str) -> tuple[bool, str]:
    from ...descriptors.orbitals import describe_xtb

    return describe_xtb(path)


@dataclass(frozen=True)
class ToolPathSpec:
    """One Settings → Configure page: a path, optional folder browse, and Test."""

    key: str
    title: str
    tooltip: str
    placeholder: str
    file_filter: str
    initial: Callable[[], str]
    probe: Callable[[str], tuple[bool, str]]
    browse_directory: bool = False
    browse_title: str = ""


_SPECS: dict[str, ToolPathSpec] = {
    TOOL_AMBER: ToolPathSpec(
        key=TOOL_AMBER,
        title="AmberTools",
        tooltip=(
            "antechamber command, its bin folder, or the executable. "
            "parmchk2 and tleap are taken from the same folder. "
            "On Windows this path is used inside WSL."
        ),
        placeholder="antechamber",
        file_filter="Executables (antechamber antechamber.exe);;All files (*.*)",
        initial=_initial_amber,
        probe=_probe_amber,
        browse_directory=True,
        browse_title="AmberTools executable",
    ),
    TOOL_CONFGEN: ToolPathSpec(
        key=TOOL_CONFGEN,
        title="CONFORGE",
        tooltip=(
            "confgen from a CDPKit install. On Windows this is usually "
            r"C:\Program Files\CDPKit\Bin\confgen.exe."
        ),
        placeholder="confgen",
        file_filter="Executables (confgen.exe confgen);;All files (*.*)",
        initial=_initial_confgen,
        probe=_probe_confgen,
        browse_title="CONFORGE executable",
    ),
    TOOL_GNINA: ToolPathSpec(
        key=TOOL_GNINA,
        title="Gnina",
        tooltip=(
            "Gnina command. On Windows this is the Linux binary (gnina on the WSL PATH, "
            "or a path such as /usr/local/bin/gnina). On Linux, a file path or PATH name."
        ),
        placeholder="gnina",
        file_filter="All files (*.*)",
        initial=_initial_gnina,
        probe=_probe_gnina,
        browse_title="Gnina executable",
    ),
    TOOL_JAVA: ToolPathSpec(
        key=TOOL_JAVA,
        title="Java",
        tooltip="Java runtime used by BioTransformer. Leave blank to use java on PATH.",
        placeholder="java",
        file_filter="Java (java.exe java);;All files (*.*)",
        initial=_initial_java,
        probe=_probe_java,
        browse_title="Java executable",
    ),
    TOOL_MAFFT: ToolPathSpec(
        key=TOOL_MAFFT,
        title="MAFFT",
        tooltip=(
            "MAFFT executable or install folder (Windows: mafft.bat, or the all-in-one directory)."
        ),
        placeholder="mafft",
        file_filter="MAFFT (mafft.bat mafft.exe mafft);;All files (*.*)",
        initial=_initial_mafft,
        probe=_probe_mafft,
        browse_directory=True,
        browse_title="MAFFT executable",
    ),
    TOOL_OBABEL: ToolPathSpec(
        key=TOOL_OBABEL,
        title="Open Babel",
        tooltip=(
            "Open Babel obabel executable. Defaults to the pip wheel "
            "(openbabel/bin/obabel) or a bundled copy under resources/bin."
        ),
        placeholder="obabel",
        file_filter="Executables (obabel.exe obabel);;All files (*.*)",
        initial=_initial_obabel,
        probe=_probe_obabel,
        browse_title="Open Babel executable",
    ),
    TOOL_XTB: ToolPathSpec(
        key=TOOL_XTB,
        title="xtb",
        tooltip=(
            "xtb executable for GFN2-xTB HOMO and LUMO descriptors. "
            "Leave blank to use xtb on PATH, or install the tblite package instead."
        ),
        placeholder="xtb",
        file_filter="Executables (xtb.exe xtb);;All files (*.*)",
        initial=_initial_xtb,
        probe=_probe_xtb,
        browse_title="xtb executable",
    ),
}


class ToolPathDialog(QDialog):
    """Pick and test the executable path for one external tool."""

    def __init__(self, tool: str, parent=None) -> None:
        super().__init__(parent)
        try:
            spec = _SPECS[tool]
        except KeyError as exc:
            raise KeyError(f"Unknown tool path setting: {tool}") from exc
        self._spec = spec
        self.setWindowTitle(spec.title)
        self.setMinimumWidth(560 if spec.browse_directory else 480)

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit(spec.initial())
        self.path_edit.setPlaceholderText(spec.placeholder)
        self.path_edit.setToolTip(spec.tooltip)
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_file)
        row.addWidget(browse)
        if spec.browse_directory:
            folder = QPushButton("Folder…")
            folder.clicked.connect(self._browse_dir)
            row.addWidget(folder)
        test_btn = QPushButton("Test")
        test_btn.setToolTip("Check that this path can be used.")
        test_btn.clicked.connect(self._test)
        row.addWidget(test_btn)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        root.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)
        make_window_minimizable(self)

    def selected_path(self) -> str:
        return (self.path_edit.text() or "").strip()

    def _browse_file(self) -> None:
        title = self._spec.browse_title or self._spec.title
        path, _filt = QFileDialog.getOpenFileName(
            self,
            title,
            self.selected_path(),
            self._spec.file_filter,
        )
        if path:
            self.path_edit.setText(path)

    def _browse_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(
            self,
            f"{self._spec.title} folder",
            self.selected_path(),
        )
        if path:
            self.path_edit.setText(path)

    def _test(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, message = self._spec.probe(self.selected_path())
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
            ok, message = False, str(exc)
        finally:
            QApplication.restoreOverrideCursor()
        if ok:
            self.status.setText(message)
            return
        QMessageBox.warning(self, self.windowTitle(), message or "That path could not be used.")
        first = (message or "Failed").strip().splitlines()[0]
        self.status.setText(first)

    def accept(self) -> None:
        save_tool_path(self._spec.key, self.selected_path())
        super().accept()
