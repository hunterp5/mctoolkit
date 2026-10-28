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

"""Settings → Configure → AiZynthFinder: interpreter and config.yml."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import Qt, QThread, pyqtSignal
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
    TOOL_AIZYNTH_CONFIG,
    TOOL_AIZYNTH_PYTHON,
    configured_executable,
    policy_tool_path,
    save_tool_path,
)
from ...platform_support.session_runtime import NetworkDisabled
from ...predictions.aizynthfinder_data import download_public_data
from ...predictions.aizynthfinder_run import probe_install
from ..qt_widget_utils import make_window_minimizable

_DOWNLOAD_ERRORS = (OSError, TimeoutError, NetworkDisabled)


class _DataDownload(QThread):
    """Fetch the public models without blocking the settings dialog."""

    status = pyqtSignal(str)
    finished_ok = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, folder: Path) -> None:
        super().__init__()
        self._folder = folder

    def run(self) -> None:  # noqa: N802
        try:
            config = download_public_data(self._folder, progress=self.status.emit)
        except _DOWNLOAD_ERRORS as exc:
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(str(config))


class AizynthFinderSettingsDialog(QDialog):
    """Choose the AiZynthFinder environment's Python and its local config.yml."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("AiZynthFinder")
        self.setMinimumWidth(720)
        root = QVBoxLayout(self)

        note = QLabel(
            "Use a separate conda environment (Python 3.10–3.12). "
            "The search reads the ONNX models and stock file named in config.yml."
        )
        note.setWordWrap(True)
        root.addWidget(note)

        self.python_edit = QLineEdit(configured_executable(TOOL_AIZYNTH_PYTHON))
        self.python_edit.setPlaceholderText(r"C:\envs\aizynth\python.exe")
        self.python_edit.setToolTip(
            "python.exe from the environment where aizynthfinder is installed. "
            "Do not use MolManager's own Python."
        )
        if policy_tool_path(TOOL_AIZYNTH_PYTHON) is not None:
            self.python_edit.setReadOnly(True)
        root.addLayout(self._path_row(self.python_edit, "Browse Python…", self._browse_python))

        self.config_edit = QLineEdit(configured_executable(TOOL_AIZYNTH_CONFIG))
        self.config_edit.setPlaceholderText("config.yml")
        self.config_edit.setToolTip(
            "config.yml next to the model files. Download… fetches them from Zenodo."
        )
        if policy_tool_path(TOOL_AIZYNTH_CONFIG) is not None:
            self.config_edit.setReadOnly(True)
        root.addLayout(self._path_row(self.config_edit, "Browse config…", self._browse_config))
        self.download_button = QPushButton("Download…")
        self.download_button.setToolTip(
            "Download the public models and ZINC stock from Zenodo (about 1.5 GB) "
            "and write config.yml next to them."
        )
        self.download_button.setEnabled(not self.config_edit.isReadOnly())
        self.download_button.clicked.connect(self._download)
        root.addWidget(self.download_button)

        buttons = QHBoxLayout()
        buttons.addStretch()
        test_btn = QPushButton("Test")
        test_btn.setToolTip(
            "Import aizynthfinder in that Python and check that the config is local."
        )
        test_btn.clicked.connect(self._test)
        buttons.addWidget(test_btn)
        ok = QPushButton("OK")
        ok.setDefault(True)
        ok.clicked.connect(self.accept)
        buttons.addWidget(ok)
        root.addLayout(buttons)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: palette(mid);")
        root.addWidget(self.status)
        if (
            policy_tool_path(TOOL_AIZYNTH_PYTHON) is not None
            or policy_tool_path(TOOL_AIZYNTH_CONFIG) is not None
        ):
            self.status.setText(
                "A path set by the machine policy is read-only and cannot be changed here."
            )
        make_window_minimizable(self)

    def selected_python(self) -> str:
        return (self.python_edit.text() or "").strip()

    def selected_config(self) -> str:
        return (self.config_edit.text() or "").strip()

    def selected_path(self) -> str:
        """Status-bar summary after OK. Prefers the config path."""
        return self.selected_config() or self.selected_python()

    def _path_row(self, edit: QLineEdit, browse_label: str, slot) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.addWidget(edit, 1)
        browse = QPushButton(browse_label)
        browse.setEnabled(not edit.isReadOnly())
        browse.clicked.connect(slot)
        row.addWidget(browse)
        return row

    def _browse_python(self) -> None:
        start = self.selected_python()
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "AiZynthFinder Python",
            start,
            "Python (python.exe python python3);;All files (*.*)",
        )
        if path:
            self.python_edit.setText(path)

    def _browse_config(self) -> None:
        start = self.selected_config() or self.selected_python()
        path, _filt = QFileDialog.getOpenFileName(
            self,
            "AiZynthFinder config",
            start,
            "YAML (*.yml *.yaml);;All files (*.*)",
        )
        if path:
            self.config_edit.setText(path)

    def _download(self) -> None:
        start = self.selected_config() or str(Path.home() / "aizynth-data")
        folder = QFileDialog.getExistingDirectory(self, "AiZynthFinder data folder", start)
        if not folder:
            return
        reply = QMessageBox.question(
            self,
            self.windowTitle(),
            "Download the public USPTO models and ZINC stock (about 1.5 GB) into:\n\n"
            f"{folder}\n\n"
            "config.yml is written in that folder. The files are not stored in git. Continue?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.Yes,
        )
        if reply != QMessageBox.Yes:
            return
        self.download_button.setEnabled(False)
        self.status.setText("Starting download…")
        thread = _DataDownload(Path(folder))
        thread.status.connect(self.status.setText)
        thread.finished_ok.connect(self._download_finished)
        thread.failed.connect(self._download_failed)
        thread.finished.connect(thread.deleteLater)
        self._download_thread = thread
        thread.start()

    def _download_finished(self, config: str) -> None:
        self.config_edit.setText(config)
        self.download_button.setEnabled(not self.config_edit.isReadOnly())
        self.status.setText(f"Downloaded: {config}")
        QMessageBox.information(self, self.windowTitle(), f"Downloaded:\n{config}")

    def _download_failed(self, message: str) -> None:
        self.download_button.setEnabled(not self.config_edit.isReadOnly())
        self.status.setText(message.splitlines()[0] if message else "Download failed.")
        QMessageBox.warning(
            self,
            self.windowTitle(),
            f"Could not download the public data:\n{message}",
        )

    def _test(self) -> None:
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok, message = probe_install(self.selected_python(), self.selected_config())
        finally:
            QApplication.restoreOverrideCursor()
        self.status.setText(message.splitlines()[0] if message else "")
        if ok:
            QMessageBox.information(self, self.windowTitle(), message)
            return
        QMessageBox.warning(self, self.windowTitle(), message)

    def accept(self) -> None:
        if policy_tool_path(TOOL_AIZYNTH_PYTHON) is None:
            save_tool_path(TOOL_AIZYNTH_PYTHON, self.selected_python())
        if policy_tool_path(TOOL_AIZYNTH_CONFIG) is None:
            save_tool_path(TOOL_AIZYNTH_CONFIG, self.selected_config())
        super().accept()
