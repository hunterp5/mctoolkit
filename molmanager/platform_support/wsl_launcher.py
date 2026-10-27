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

"""Windows Subsystem for Linux (WSL) launcher for Linux-only tools.

Settings → Configure → WSL stores the ``wsl.exe`` path. Callers build a Windows argv with
:func:`wsl_argv` or run a command with :func:`run_wsl` (for example AmberTools
GAFF parameterization that is not available as a native Windows binary).
"""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from shutil import which

_SETTINGS_ORG = "MolManager"
_SETTINGS_APP = "MolManager"
_SETTINGS_KEY_WSL = "tools/wsl_executable"
_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _settings_value() -> str:
    try:
        from PyQt5.QtCore import QSettings
    except ImportError:
        return ""
    raw = QSettings(_SETTINGS_ORG, _SETTINGS_APP).value(_SETTINGS_KEY_WSL, "")
    return str(raw or "").strip()


def _set_settings_value(path: str) -> None:
    from PyQt5.QtCore import QSettings

    QSettings(_SETTINGS_ORG, _SETTINGS_APP).setValue(_SETTINGS_KEY_WSL, str(path or "").strip())


def default_wsl_executable() -> str:
    """Best-guess ``wsl.exe`` on Windows; empty on other platforms."""
    if not sys.platform.startswith("win"):
        return ""
    found = which("wsl") or which("wsl.exe")
    if found:
        return found
    system_root = Path(os.environ.get("SystemRoot") or r"C:\Windows")
    system32 = system_root / "System32" / "wsl.exe"
    if system32.is_file():
        return str(system32)
    return "wsl.exe"


def load_wsl_executable() -> str:
    """Saved WSL executable, or :func:`default_wsl_executable` when unset."""
    saved = _settings_value()
    if saved:
        return saved
    return default_wsl_executable()


def save_wsl_executable(path: str) -> str:
    """Persist *path* and return the stripped value."""
    text = (path or "").strip()
    _set_settings_value(text)
    return text


def resolve_wsl_executable(user_path: str = "") -> str | None:
    """Return an existing WSL executable path, else ``None``."""
    from .bundled_paths import resolve_user_executable

    text = (user_path or "").strip() or load_wsl_executable()
    return resolve_user_executable(text)


def wsl_available(user_path: str = "") -> bool:
    return resolve_wsl_executable(user_path) is not None


def windows_path_to_wsl(path: str | Path) -> str:
    """Convert a Windows path to the ``/mnt/<drive>/…`` form used inside WSL."""
    raw = str(path).strip().strip('"')
    if len(raw) >= 2 and raw[1] == ":":
        drive = raw[0].lower()
        rest = raw[2:].replace("\\", "/").replace("//", "/").lstrip("/")
        return f"/mnt/{drive}/{rest}" if rest else f"/mnt/{drive}"
    return raw.replace("\\", "/")


def wsl_argv(
    linux_args: Sequence[str],
    *,
    user_path: str = "",
    distro: str | None = None,
) -> list[str]:
    """Windows argv that runs *linux_args* inside WSL (``wsl.exe -- cmd …``)."""
    exe = resolve_wsl_executable(user_path)
    if not exe:
        raise FileNotFoundError(
            "WSL executable not found. Set it under Settings → Configure → WSL, or install "
            "Windows Subsystem for Linux."
        )
    argv = [exe]
    name = (distro or "").strip()
    if name:
        argv.extend(["-d", name])
    argv.append("--")
    argv.extend(str(a) for a in linux_args)
    return argv


def run_wsl(
    linux_args: Sequence[str],
    *,
    user_path: str = "",
    distro: str | None = None,
    cwd: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float | None = None,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
) -> subprocess.CompletedProcess:
    """Run *linux_args* in WSL and return the completed process."""
    argv = wsl_argv(linux_args, user_path=user_path, distro=distro)
    kwargs: dict = {
        "cwd": None if cwd is None else str(cwd),
        "timeout": timeout,
        "check": check,
        "capture_output": capture_output,
        "text": text,
    }
    if env is not None:
        kwargs["env"] = dict(env)
    if sys.platform.startswith("win") and _CREATE_NO_WINDOW:
        kwargs["creationflags"] = _CREATE_NO_WINDOW
    return subprocess.run(argv, **kwargs)


def linux_path(path: str | Path) -> str:
    """Path as seen by a Linux tool (WSL ``/mnt/…`` on Windows)."""
    if sys.platform.startswith("win"):
        return windows_path_to_wsl(path)
    return str(path)


def run_linux_tool(
    args: Sequence[str],
    *,
    work_dir: str | Path,
    timeout: float | None = None,
    check: bool = False,
) -> subprocess.CompletedProcess:
    """Run a Linux CLI with *work_dir* as cwd.

    On Windows this is ``wsl.exe -- bash -lic 'cd … && …'`` so conda/AmberTools
    on the WSL login PATH is found. *args* should use names relative to
    *work_dir* (or Linux-absolute paths).
    """
    work = Path(work_dir)
    with suppress(OSError):
        work = work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    if args:
        from .session_runtime import require_tool

        require_tool(str(args[0]), Path(str(args[0])).name)
    quoted = " ".join(shlex.quote(str(a)) for a in args)
    if sys.platform.startswith("win"):
        script = f"cd {shlex.quote(windows_path_to_wsl(work))} && {quoted}"
        return run_wsl(["bash", "-lic", script], timeout=timeout, check=check)
    argv = [str(a) for a in args]
    kwargs: dict = {
        "cwd": str(work),
        "timeout": timeout,
        "check": check,
        "capture_output": True,
        "text": True,
    }
    try:
        return subprocess.run(argv, **kwargs)
    except FileNotFoundError:
        script = f"cd {shlex.quote(str(work))} && {quoted}"
        return subprocess.run(["bash", "-lc", script], **kwargs)
