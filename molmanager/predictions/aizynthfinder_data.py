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

"""Download the public AiZynthFinder models, ZINC stock, and a local config.yml."""

from __future__ import annotations

import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path

from ..platform_support.session_runtime import require_network

# Zenodo record 10.5281/zenodo.11430881. Figshare's ZINC link expires after
# 10 seconds, so ``download_public_data`` often stops on zinc_stock.hdf5 and
# never writes config.yml.
_RECORD = "https://zenodo.org/records/11430881/files"
_FILES: tuple[tuple[str, str], ...] = (
    ("uspto_model.onnx", f"{_RECORD}/uspto_model.onnx?download=1"),
    ("uspto_templates.csv.gz", f"{_RECORD}/uspto_templates.csv.gz?download=1"),
    ("uspto_ringbreaker_model.onnx", f"{_RECORD}/uspto_ringbreaker_model.onnx?download=1"),
    (
        "uspto_ringbreaker_templates.csv.gz",
        f"{_RECORD}/uspto_ringbreaker_templates.csv.gz?download=1",
    ),
    ("uspto_filter_model.onnx", f"{_RECORD}/uspto_filter_model.onnx?download=1"),
    ("zinc_stock.hdf5", f"{_RECORD}/zinc_stock.hdf5?download=1"),
)
_USER_AGENT = "MolManager (AiZynthFinder public data)"
_CHUNK = 256 * 1024
_ATTEMPTS = 3

ProgressFn = Callable[[str], None]
Opener = Callable[[str], "object"]


def public_config_text(folder: Path) -> str:
    """``config.yml`` body whose paths point at files inside *folder*."""
    root = Path(folder)
    model = _yaml_path(root / "uspto_model.onnx")
    templates = _yaml_path(root / "uspto_templates.csv.gz")
    ring_model = _yaml_path(root / "uspto_ringbreaker_model.onnx")
    ring_templates = _yaml_path(root / "uspto_ringbreaker_templates.csv.gz")
    filter_model = _yaml_path(root / "uspto_filter_model.onnx")
    stock = _yaml_path(root / "zinc_stock.hdf5")
    return (
        "expansion:\n"
        "  uspto:\n"
        f"    - {model}\n"
        f"    - {templates}\n"
        "  ringbreaker:\n"
        f"    - {ring_model}\n"
        f"    - {ring_templates}\n"
        "filter:\n"
        f"  uspto: {filter_model}\n"
        "stock:\n"
        f"  zinc: {stock}\n"
    )


def download_public_data(
    folder: Path,
    *,
    progress: ProgressFn | None = None,
    opener: Opener | None = None,
) -> Path:
    """Download the public files into *folder* and return the written ``config.yml``."""
    require_network("AiZynthFinder")
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    open_url = opener or _open_url
    for name, url in _FILES:
        _download_one(url, root / name, progress, open_url)
    config = root / "config.yml"
    _emit(progress, "Writing config.yml")
    config.write_text(public_config_text(root), encoding="utf-8")
    return config


def _yaml_path(path: Path) -> str:
    return path.resolve().as_posix()


def _emit(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)


def _open_url(url: str):
    request = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    return urllib.request.urlopen(request, timeout=120)


def _content_length(response) -> int:
    raw = response.headers.get("Content-Length") if response.headers is not None else None
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _download_one(url: str, dest: Path, progress: ProgressFn | None, open_url: Opener) -> None:
    last_error: OSError | None = None
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            _download_once(url, dest, progress, open_url)
            return
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            last_error = exc if isinstance(exc, OSError) else OSError(str(exc))
            _emit(progress, f"{dest.name} failed ({attempt} of {_ATTEMPTS})")
    if last_error is not None:
        raise last_error
    raise OSError(f"Could not download {dest.name}")


def _download_once(url: str, dest: Path, progress: ProgressFn | None, open_url: Opener) -> None:
    with open_url(url) as response:
        total = _content_length(response)
        if dest.is_file() and total > 0 and dest.stat().st_size == total:
            _emit(progress, f"{dest.name} already downloaded")
            return
        _emit(progress, f"Downloading {dest.name}")
        part = dest.with_name(dest.name + ".part")
        got = 0
        try:
            with part.open("wb") as handle:
                for chunk in _chunks(response):
                    handle.write(chunk)
                    got += len(chunk)
        except (OSError, urllib.error.URLError, TimeoutError):
            part.unlink(missing_ok=True)
            raise
        if total and got != total:
            part.unlink(missing_ok=True)
            raise OSError(f"{dest.name} stopped at {got} of {total} bytes")
        part.replace(dest)


def _chunks(response) -> Iterator[bytes]:
    while True:
        chunk = response.read(_CHUNK)
        if not chunk:
            return
        yield chunk
