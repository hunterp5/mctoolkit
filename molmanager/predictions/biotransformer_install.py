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

"""Download the official BioTransformer 3 runnable package (not stored in git)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import urllib.request
import zipfile
from collections.abc import Callable
from pathlib import Path

from ..platform_support.bundled_paths import (
    biotransformer_layout_errors,
    biotransformer_models_dir,
    find_biotransformer_jar_in,
)

BITBUCKET_GIT = "https://bitbucket.org/wishartlab/biotransformer3.0jar.git"
BITBUCKET_ZIP = "https://bitbucket.org/wishartlab/biotransformer3.0jar/get/master.zip"
_SKIP_NAMES = frozenset({".git", ".gitignore", ".project", "README.md"})
_USER_AGENT = "MolManager/0.1 (BioTransformer bootstrap)"

ProgressFn = Callable[[str], None]


def _emit(progress: ProgressFn | None, message: str) -> None:
    if progress is not None:
        progress(message)


def copy_biotransformer_tree(src: Path, dest: Path) -> Path:
    """Copy JAR + support folders from an extracted/cloned package into ``dest``."""
    dest.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        if item.name in _SKIP_NAMES:
            continue
        target = dest / item.name
        if item.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)
    jar = find_biotransformer_jar_in(dest)
    if jar is None:
        raise FileNotFoundError(f"No BioTransformer JAR found after copy into {dest}")
    return jar


def _package_root_from(extracted: Path) -> Path:
    jar = find_biotransformer_jar_in(extracted)
    if jar is not None:
        return extracted
    nested = [p for p in extracted.iterdir() if p.is_dir()]
    for folder in nested:
        if find_biotransformer_jar_in(folder) is not None:
            return folder
    raise FileNotFoundError(f"No BioTransformer JAR in {extracted}")


def _clone_git(dest: Path, progress: ProgressFn | None) -> None:
    _emit(progress, "Cloning BioTransformer from Bitbucket…")
    subprocess.run(
        ["git", "clone", "--depth", "1", BITBUCKET_GIT, str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )


def _download_zip(dest: Path, progress: ProgressFn | None) -> None:
    _emit(progress, "Downloading BioTransformer zip from Bitbucket…")
    archive = dest.parent / "biotransformer.zip"
    req = urllib.request.Request(BITBUCKET_ZIP, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp, archive.open("wb") as out:
        shutil.copyfileobj(resp, out)
    _emit(progress, "Extracting BioTransformer zip…")
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(dest)


def fetch_biotransformer_package(work: Path, progress: ProgressFn | None = None) -> Path:
    """Clone or unzip the official package into ``work`` and return the layout root."""
    git = shutil.which("git")
    clone_dir = work / "src"
    if git:
        try:
            _clone_git(clone_dir, progress)
            return _package_root_from(clone_dir)
        except (OSError, subprocess.CalledProcessError) as exc:
            _emit(progress, f"Git clone failed ({exc}); trying zip download.")
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)
    zip_dir = work / "zip"
    zip_dir.mkdir(parents=True, exist_ok=True)
    _download_zip(zip_dir, progress)
    return _package_root_from(zip_dir)


def install_biotransformer(
    dest: Path | None = None,
    *,
    progress: ProgressFn | None = None,
) -> Path:
    """
    Ensure a runnable BioTransformer layout under ``dest`` (models folder by default).

    Returns the JAR path. Existing complete installs are left in place.
    """
    dest_dir = dest if dest is not None else biotransformer_models_dir()
    dest_dir.mkdir(parents=True, exist_ok=True)
    existing = find_biotransformer_jar_in(dest_dir)
    if existing is not None:
        problems = [e for e in biotransformer_layout_errors(existing) if not e.startswith("Java ")]
        if not problems:
            _emit(progress, f"Already present: {existing}")
            return existing
    with tempfile.TemporaryDirectory(prefix="molmanager-biotransformer-") as tmp:
        src = fetch_biotransformer_package(Path(tmp), progress=progress)
        _emit(progress, f"Installing into {dest_dir}…")
        jar = copy_biotransformer_tree(src, dest_dir)
    _emit(progress, f"Installed {jar}")
    return jar
