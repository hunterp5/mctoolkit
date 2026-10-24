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

"""Settings → Configure → BioTransformer: JAR path and install."""

from __future__ import annotations

import shutil
import subprocess
import urllib.error
import zipfile
from pathlib import Path

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

from ...platform_support.bundled_paths import (
    biotransformer_layout_errors,
    biotransformer_models_dir,
    configured_biotransformer_jar_text,
    resolve_biotransformer_jar,
    set_configured_biotransformer_jar,
)
from ...predictions.biotransformer_install import install_biotransformer
from ..qt_widget_utils import make_window_minimizable
from ..strings import TOOL_PREDICT_METABOLITES

_INSTALL_ERRORS = (
    OSError,
    shutil.Error,
    subprocess.SubprocessError,
    urllib.error.URLError,
    zipfile.BadZipFile,
    RuntimeError,
    ValueError,
)


def _initial_jar() -> str:
    saved = configured_biotransformer_jar_text()
    if saved:
        return saved
    found = resolve_biotransformer_jar()
    return str(found) if found is not None else ""


class BiotransformerSettingsDialog(QDialog):
    """Choose the BioTransformer JAR, or download the official package."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("BioTransformer")
        self.setMinimumWidth(640)

        root = QVBoxLayout(self)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.path_edit = QLineEdit(_initial_jar())
        self.path_edit.setPlaceholderText("BioTransformer3.0.jar")
        self.path_edit.setToolTip(
            "BioTransformer JAR. supportfiles/ and btkb/ (or database/) must sit next to it. "
            "Java is set under Settings → Configure → Java."
        )
        row.addWidget(self.path_edit, 1)
        browse = QPushButton("Browse JAR…")
        browse.clicked.connect(self._browse)
        row.addWidget(browse)
        install = QPushButton("Install…")
        install.setToolTip(
            "Download the official BioTransformer 3 package from Bitbucket (~120 MB)."
        )
        install.clicked.connect(self._install)
        row.addWidget(install)
        test_btn = QPushButton("Test")
        test_btn.setToolTip(
            "Check Java and that the JAR folder has its knowledge base and supportfiles/."
        )
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

    def _jar_for_check(self) -> Path | None:
        text = self.selected_path()
        if not text:
            return None
        return Path(text).expanduser()

    def _browse(self) -> None:
        start = self.selected_path() or str(biotransformer_models_dir())
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "BioTransformer JAR",
            start,
            "JAR files (*.jar);;All files (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _install(self) -> None:
        dest = biotransformer_models_dir()
        reply = QMessageBox.question(
            self,
            TOOL_PREDICT_METABOLITES,
            "Download BioTransformer 3 (~120 MB) from Bitbucket into:\n\n"
            f"{dest}\n\n"
            "The files are LGPL-3 and are not stored in git. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            jar = install_biotransformer(dest, progress=None)
        except _INSTALL_ERRORS as exc:
            jar = None
            install_error: BaseException | None = exc
        else:
            install_error = None
        finally:
            QApplication.restoreOverrideCursor()
        if install_error is not None:
            QMessageBox.warning(
                self,
                TOOL_PREDICT_METABOLITES,
                f"Could not install BioTransformer:\n{install_error}\n\n"
                "Run: python scripts/bootstrap_biotransformer.py",
            )
            return
        set_configured_biotransformer_jar(jar)
        self.path_edit.setText(str(jar))
        still = biotransformer_layout_errors(jar)
        if still:
            QMessageBox.warning(self, TOOL_PREDICT_METABOLITES, " ".join(still))
            self.status.setText(still[0])
            return
        QMessageBox.information(self, TOOL_PREDICT_METABOLITES, f"Installed:\n{jar}")
        self.status.setText(f"Installed: {jar}")

    def _test(self) -> None:
        jar = self._jar_for_check()
        errors = biotransformer_layout_errors(jar)
        if errors:
            message = " ".join(errors)
            QMessageBox.warning(self, self.windowTitle(), message)
            self.status.setText(errors[0])
            return
        shown = jar if jar is not None else resolve_biotransformer_jar()
        self.status.setText(f"OK: {shown}")

    def accept(self) -> None:
        set_configured_biotransformer_jar(self.selected_path())
        super().accept()
