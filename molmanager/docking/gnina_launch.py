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

"""Launch Gnina (Linux binary; WSL on Windows) with path conversion and GPU probe."""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

from ..platform_support.bundled_paths import resolve_bundled_executable, resolve_user_executable
from ..platform_support.tool_paths import TOOL_GNINA, effective_tool_path

_WHICH_TIMEOUT_S = 20.0

_PATH_FLAGS = frozenset(
    {
        "--receptor",
        "--ligand",
        "--out",
        "--autobox_ligand",
        "--config",
        "--flex",
        "--flexdist_ligand",
        "--custom_scoring",
        "--custom_atoms",
        "--user_grid",
        "--cnn_model",
        "--log",
        "--atom_terms",
        "--out_flex",
    }
)


def gnina_uses_wsl() -> bool:
    """Official Gnina is a Linux binary; Windows always launches it through WSL."""
    return sys.platform.startswith("win")


def gnina_command_ok(path: str) -> bool:
    """True when *path* is a local file or a WSL/PATH command name (``gnina``)."""
    text = (path or "").strip()
    if not text:
        return False
    if resolve_user_executable(text):
        return True
    if gnina_uses_wsl():
        name = Path(text).name.lower()
        return name in {"gnina", "gnina.exe"} or text.startswith("/")
    return False


def gnina_missing_message(user_path: str = "") -> str:
    """User-facing text when the Gnina binary cannot be resolved."""
    shown = (user_path or "").strip() or "gnina"
    return (
        f"Gnina was not found ({shown}).\n\n"
        "Download the official Linux binary from "
        "https://github.com/gnina/gnina/releases "
        "(not a Windows .exe).\n\n"
        "On Windows, install it in WSL so a login shell can run `gnina` "
        "(Settings → Configure → WSL), or set the binary under "
        "Settings → Configure → Gnina (a Linux path such as /usr/local/bin/gnina). "
        "You can also copy the binary to molmanager/resources/bin/linux/gnina.\n\n"
        "macOS has no official Gnina build."
    )


def _process_succeeded(proc: object) -> bool:
    """True when *proc* exited 0. ``returncode or 1`` is wrong because 0 is falsy."""
    try:
        return int(getattr(proc, "returncode", 1)) == 0
    except (TypeError, ValueError):
        return False


def _wsl_which(name: str, *, timeout: float = _WHICH_TIMEOUT_S) -> str | None:
    """Return a Linux path when *name* is executable inside WSL, else ``None``."""
    from ..platform_support.wsl_launcher import run_linux_tool

    cmd = (name or "").strip()
    if not cmd:
        return None
    try:
        if cmd.startswith("/"):
            proc = run_linux_tool(["test", "-x", cmd], work_dir=Path("."), timeout=timeout)
            return cmd if _process_succeeded(proc) else None
        proc = run_linux_tool(["command", "-v", cmd], work_dir=Path("."), timeout=timeout)
    except Exception:
        return None
    if not _process_succeeded(proc):
        return None
    hit = (getattr(proc, "stdout", "") or "").strip().splitlines()
    text = hit[0].strip() if hit else ""
    return text or None


def resolve_gnina_command(user_path: str = "", *, timeout: float = _WHICH_TIMEOUT_S) -> str | None:
    """Return a Gnina command that exists on this host or in WSL, else ``None``."""
    text = effective_tool_path(TOOL_GNINA, user_path) or "gnina"
    local = resolve_user_executable(text)
    if local:
        return local
    bundled = resolve_bundled_executable("gnina")
    if bundled is not None:
        return str(bundled)
    if gnina_uses_wsl():
        linux = gnina_linux_executable(text)
        found = _wsl_which(linux, timeout=timeout)
        if found:
            return found
        if linux != "gnina":
            return _wsl_which("gnina", timeout=timeout)
        return None
    return None


def describe_gnina(user_path: str = "") -> tuple[bool, str]:
    """Whether *user_path* resolves, plus a status line or the missing-tool message."""
    found = resolve_gnina_command(user_path)
    if found:
        return True, f"OK: {found}"
    return False, gnina_missing_message(user_path)


def convert_gnina_argv_paths(argv: list[str]) -> list[str]:
    """Rewrite file-path flag values to Linux/WSL paths (identity on native Linux)."""
    from ..platform_support.wsl_launcher import linux_path

    out: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]
        out.append(tok)
        if tok in _PATH_FLAGS and i + 1 < n and not str(argv[i + 1]).startswith("--"):
            out.append(linux_path(argv[i + 1]))
            i += 2
            continue
        i += 1
    return out


def write_gnina_config(argv: list[str], dest: Path, *, linux_paths: bool = False) -> Path:
    """Write a Gnina ``--config`` file from an argv list (no executable).

    Repeated ``--ligand`` flags become repeated ``ligand =`` lines, which Gnina
    accepts in one process without a long Windows command line.
    """
    from ..platform_support.wsl_launcher import linux_path

    lines: list[str] = []
    i = 0
    n = len(argv)
    while i < n:
        tok = argv[i]
        if not tok.startswith("--"):
            i += 1
            continue
        key = tok[2:]
        if i + 1 < n and not argv[i + 1].startswith("--"):
            val = argv[i + 1]
            if linux_paths and tok in _PATH_FLAGS:
                val = linux_path(val)
            if any(ch.isspace() for ch in val):
                val = f'"{val}"'
            lines.append(f"{key} = {val}")
            i += 2
            continue
        lines.append(f"{key} = true")
        i += 1
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return dest


def gnina_linux_executable(user_path: str) -> str:
    """Gnina command as seen inside Linux/WSL (``/mnt/…`` for a Windows file)."""
    text = (user_path or "").strip() or "gnina"
    if len(text) >= 2 and text[1] == ":":
        from ..platform_support.wsl_launcher import windows_path_to_wsl

        return windows_path_to_wsl(text)
    return text.replace("\\", "/")


def cuda_available(*, timeout: float = 8.0) -> bool:
    """True when ``nvidia-smi -L`` succeeds in the same environment Gnina will use."""
    if sys.platform == "darwin":
        return False
    try:
        if gnina_uses_wsl():
            from ..platform_support.wsl_launcher import run_wsl

            proc = run_wsl(["nvidia-smi", "-L"], timeout=timeout)
        else:
            proc = subprocess.run(
                ["nvidia-smi", "-L"],
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        if not _process_succeeded(proc):
            return False
        return bool((getattr(proc, "stdout", "") or "").strip())
    except Exception:
        return False


def gnina_exit_127_message(exe: str = "", stderr: str = "") -> str:
    """Explain a 127 exit: missing binary vs missing CUDA/cuDNN libraries."""
    err = (stderr or "").strip()
    lib_line = ""
    for line in reversed(err.splitlines()):
        low = line.lower()
        if "shared librar" in low or "libcu" in low:
            lib_line = line.strip()
            break
    if lib_line or (exe or "").startswith("/"):
        extra = f"{lib_line} " if lib_line else ""
        return (
            f"{extra}Gnina could not load CUDA 12 / cuDNN 9 libraries "
            "(libcudnn.so.9, libcudart.so.12, libcublas, …). "
            "`nvidia-smi` only proves the Windows GPU driver; WSL still needs "
            "those Linux user-space libs. In WSL: "
            "`conda create -n gnina-cuda -c nvidia -c conda-forge libcudnn "
            "cuda-cudart libcublas libcufft libcusparse libcusolver`."
        )
    return (
        "Gnina was not found on the WSL/Linux PATH. Install the official Linux "
        "binary and put `gnina` on PATH, or set a full path in the Gnina field."
    )


_GNINA_LD_CACHE: str | None = None

# Globs only (no ``$HOME``): ``wsl.exe`` can strip Windows-empty ``$`` variables.
_GNINA_LD_LS = (
    "ls -d "
    "/home/*/miniconda3/envs/*/lib/libcudnn.so.9 "
    "/home/*/miniconda3/envs/*/lib/libcudart.so.12 "
    "/home/*/miniconda3/lib/libcudnn.so.9 "
    "/home/*/miniconda3/lib/libcudart.so.12 "
    "/home/*/anaconda3/envs/*/lib/libcudnn.so.9 "
    "/home/*/anaconda3/envs/*/lib/libcudart.so.12 "
    "/usr/local/cuda/lib64/libcudnn.so.9 "
    "/usr/local/cuda/lib64/libcudart.so.12 "
    "2>/dev/null"
)


def gnina_ld_library_path(*, timeout: float = 15.0) -> str:
    """Colon-separated WSL dirs that contain CUDA/cuDNN libs Gnina can ``dlopen``."""
    global _GNINA_LD_CACHE
    if _GNINA_LD_CACHE is not None:
        return _GNINA_LD_CACHE
    if not gnina_uses_wsl():
        _GNINA_LD_CACHE = ""
        return ""
    from ..platform_support.wsl_launcher import run_wsl

    try:
        proc = run_wsl(["bash", "-lc", _GNINA_LD_LS], timeout=timeout)
    except Exception:
        _GNINA_LD_CACHE = ""
        return ""
    dirs: list[str] = []
    for line in (getattr(proc, "stdout", "") or "").splitlines():
        parent = str(Path(line.strip()).parent).replace("\\", "/")
        if parent and parent not in dirs:
            dirs.append(parent)
    text = ":".join(dirs)
    _GNINA_LD_CACHE = text
    return text


def gnina_qprocess_spec(
    exe: str,
    argv: list[str],
    *,
    work_dir: str = "",
) -> tuple[str, list[str]]:
    """Return ``(program, arguments)`` for ``QProcess.start``.

    On Windows this is ``wsl.exe -- bash -lic 'cd … && gnina …'`` so a login-shell
    PATH (conda, ``/usr/local/bin``) is used and file paths are ``/mnt/…``.
    """
    if not gnina_uses_wsl():
        return exe, list(argv)
    from ..platform_support.wsl_launcher import windows_path_to_wsl, wsl_argv

    linux_exe = gnina_linux_executable(exe)
    linux_argv = convert_gnina_argv_paths(argv)
    work = (work_dir or "").strip() or str(Path.cwd())
    try:
        work = str(Path(work).resolve())
    except OSError:
        pass
    quoted = " ".join(shlex.quote(str(a)) for a in [linux_exe, *linux_argv])
    script = f"cd {shlex.quote(windows_path_to_wsl(work))} && {quoted}"
    # NTFS /mnt paths often lack +x; WSL then reports "command not found".
    if linux_exe.startswith("/mnt/"):
        script = f"chmod +x {shlex.quote(linux_exe)} 2>/dev/null; {script}"
    ld = gnina_ld_library_path()
    if ld:
        script = f"export LD_LIBRARY_PATH={shlex.quote(ld)}; {script}"
    full = wsl_argv(["bash", "-lic", script])
    return full[0], list(full[1:])
