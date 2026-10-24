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

"""Settings → Configure → WSL: path to ``wsl.exe`` for Linux-only tools."""

from __future__ import annotations

from PyQt5.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from ...platform_support.wsl_launcher import (
    default_wsl_executable,
    load_wsl_executable,
    resolve_wsl_executable,
    run_wsl,
    save_wsl_executable,
)
from ..qt_widget_utils import make_window_minimizable


class WslSettingsDialog(QDialog):
    """Choose the Windows Subsystem for Linux executable used by Linux-only tools."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("WSL")
        self.setMinimumWidth(480)

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit(load_wsl_executable())
        self.path_edit.setPlaceholderText(default_wsl_executable() or "wsl.exe")
        self.path_edit.setToolTip("Path to wsl.exe. Leave as the default to use System32 or PATH.")
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        test_btn = QPushButton("Test")
        test_btn.setToolTip("Run `uname -s` inside WSL to confirm the executable works.")
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

    def _browse(self) -> None:
        start = self.selected_path() or default_wsl_executable()
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "WSL executable",
            start,
            "Executables (wsl.exe);;All files (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _test(self) -> None:
        path = self.selected_path() or default_wsl_executable()
        exe = resolve_wsl_executable(path)
        if not exe:
            QMessageBox.warning(
                self,
                "WSL",
                "That path is not an existing executable. Browse to wsl.exe.",
            )
            return
        try:
            proc = run_wsl(["uname", "-s"], user_path=exe, timeout=20.0, check=False)
        except FileNotFoundError as exc:
            QMessageBox.warning(self, "WSL", str(exc))
            return
        except Exception as exc:
            QMessageBox.warning(self, "WSL", f"Could not run WSL: {exc}")
            return
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode == 0 and out:
            self.status.setText(f"OK ({exe}): {out.splitlines()[0]}")
            return
        detail = out or f"exit code {proc.returncode}"
        QMessageBox.warning(
            self,
            "WSL",
            f"WSL ran but the test command failed:\n{detail}",
        )
        self.status.setText(f"Failed: {detail}")

    def accept(self) -> None:
        save_wsl_executable(self.selected_path())
        super().accept()
