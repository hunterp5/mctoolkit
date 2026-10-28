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

"""Public AiZynthFinder data download."""

from __future__ import annotations

from pathlib import Path

import pytest
from PyQt5.QtCore import QThread
from PyQt5.QtWidgets import QFileDialog, QMessageBox

from molmanager.predictions import aizynthfinder_data
from molmanager.ui.dialogs.aizynthfinder_settings import AizynthFinderSettingsDialog, _DataDownload


class _Body:
    def __init__(self, payload: bytes, length: int | None = None) -> None:
        self._payload = payload
        self._pos = 0
        self.headers = {"Content-Length": "" if length is None else str(length)}

    def read(self, size: int) -> bytes:
        chunk = self._payload[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_args) -> bool:
        return False


def test_download_writes_files_and_config(tmp_path: Path, monkeypatch) -> None:
    seen: list[str] = []

    def _open(url: str) -> _Body:
        seen.append(url)
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        return _Body(name.encode("ascii"))

    monkeypatch.setattr(aizynthfinder_data, "require_network", lambda _purpose: None)
    config = aizynthfinder_data.download_public_data(tmp_path, opener=_open)
    assert config == tmp_path / "config.yml"
    assert (tmp_path / "zinc_stock.hdf5").read_bytes() == b"zinc_stock.hdf5"
    assert (tmp_path / "uspto_model.onnx").read_bytes() == b"uspto_model.onnx"
    text = config.read_text(encoding="utf-8")
    zinc = (tmp_path / "zinc_stock.hdf5").resolve().as_posix()
    assert f"zinc: {zinc}" in text
    assert "figshare" not in text
    assert all("zenodo.org/records/11430881" in url for url in seen)
    assert any(url.endswith("zinc_stock.hdf5?download=1") for url in seen)


def test_complete_file_is_not_downloaded_again(tmp_path: Path, monkeypatch) -> None:
    stock = tmp_path / "zinc_stock.hdf5"
    stock.write_bytes(b"already")
    calls: list[str] = []

    def _open(url: str) -> _Body:
        calls.append(url)
        name = url.rsplit("/", 1)[-1].split("?", 1)[0]
        if name == "zinc_stock.hdf5":
            return _Body(b"already")
        return _Body(b"x")

    monkeypatch.setattr(aizynthfinder_data, "require_network", lambda _purpose: None)
    aizynthfinder_data.download_public_data(tmp_path, opener=_open)
    assert stock.read_bytes() == b"already"
    assert sum(url.endswith("zinc_stock.hdf5?download=1") for url in calls) == 1


def test_short_download_is_retried_and_removed(tmp_path: Path, monkeypatch) -> None:
    def _open(_url: str) -> _Body:
        return _Body(b"short", length=20)

    monkeypatch.setattr(aizynthfinder_data, "require_network", lambda _purpose: None)
    with pytest.raises(OSError, match="stopped at"):
        aizynthfinder_data.download_public_data(tmp_path, opener=_open)
    assert not (tmp_path / "uspto_model.onnx").exists()
    assert not (tmp_path / "uspto_model.onnx.part").exists()
    assert not (tmp_path / "config.yml").exists()


def test_settings_download_fills_the_config_path(qapp, tmp_path: Path, monkeypatch) -> None:  # noqa: ARG001
    dialog = AizynthFinderSettingsDialog()
    written = tmp_path / "config.yml"

    def _fake(folder: Path, *, progress=None) -> Path:
        if progress is not None:
            progress("Downloading zinc_stock.hdf5")
        folder.mkdir(parents=True, exist_ok=True)
        config = folder / "config.yml"
        config.write_text("stock:\n  zinc: zinc_stock.hdf5\n", encoding="utf-8")
        return config

    monkeypatch.setattr(
        "molmanager.ui.dialogs.aizynthfinder_settings.download_public_data",
        _fake,
    )
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(tmp_path),
    )
    monkeypatch.setattr(QMessageBox, "question", lambda *_args, **_kwargs: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda *_args, **_kwargs: QMessageBox.Ok)
    monkeypatch.setattr(
        _DataDownload,
        "start",
        lambda self, priority=QThread.InheritPriority: self.run(),
    )
    dialog.download_button.click()
    assert dialog.config_edit.text() == str(written)
    assert dialog.status.text() == f"Downloaded: {written}"
    dialog.close()
