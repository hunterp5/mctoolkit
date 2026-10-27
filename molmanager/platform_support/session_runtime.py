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

"""Process-lifetime temp directory, offline policy, and a local audit log.

One runtime exists per process. Table caches, plot shells, and scratch
sessions live under its directory and are removed when the process exits.
``MOLMANAGER_OFFLINE=1`` refuses network lookups. ``MOLMANAGER_SQL_WRITES=0``
refuses SQL that modifies a database. ``MOLMANAGER_TOOL_ALLOWLIST`` limits which
external programs may start, and ``MOLMANAGER_TOOL_DIGESTS`` pins their SHA-256.
A machine policy file can set the same names and wins over the process environment.
With no policy file and the variables unset, behavior matches a normal desktop launch.
"""

from __future__ import annotations

import atexit
import hashlib
import logging
import os
import re
import shutil
import sys
import tempfile
import threading
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from .app_logging import default_log_dir

logger = logging.getLogger(__name__)

_DIR_PREFIX = "molmanager-rt-"
_DIR_NAME = re.compile(rf"^{_DIR_PREFIX}(\d+)-")
_LEGACY_CACHE = "MOLMANAGER_table_cache.sqlite3"
_LEGACY_SESSIONS = "MolManagerSessions"
_LEGACY_PLOT_GLOB = "MOLMANAGER_plot_shell_*.html"

_current: SessionRuntime | None = None
_atexit_armed = False
_digest_cache: dict[tuple[str, int, int], str] = {}
_digest_lock = threading.Lock()


class ToolDenied(RuntimeError):
    """An external program was refused by the allowlist or a digest pin."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class NetworkDisabled(RuntimeError):
    """A lookup was refused because ``MOLMANAGER_OFFLINE`` is set."""

    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        super().__init__(
            f"{purpose} needs a network connection. "
            "MOLMANAGER_OFFLINE is set, so this request was not sent."
        )


class SessionRuntime:
    """Temp files and policy for the current process."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self._closed = False

    @classmethod
    def start(cls) -> SessionRuntime:
        root = Path(tempfile.mkdtemp(prefix=f"{_DIR_PREFIX}{os.getpid()}-"))
        runtime = cls(root)
        _sweep_stale_runtime_dirs(keep=root)
        _sweep_legacy_shared_temp()
        audit("runtime-start", f"pid={os.getpid()}")
        return runtime

    def close(self) -> None:
        """Delete this process's temp directory. Safe to call more than once."""
        if self._closed:
            return
        self._closed = True
        shutil.rmtree(self.root, ignore_errors=True)

    def contains(self, path: str | Path) -> bool:
        """True when *path* is inside this process's temp directory."""
        try:
            Path(path).resolve().relative_to(self.root.resolve())
        except (OSError, ValueError):
            return False
        return True

    def sessions_dir(self) -> Path:
        path = self.root / "sessions"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def session_copy_path(self) -> str:
        """A new ``.cms`` path for Send Selected to New Session. Does not write."""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return str(self.sessions_dir() / f"session_{stamp}_{os.getpid()}.cms")

    def allocate_sqlite(self, prefix: str = "table-cache-") -> Path:
        """An empty SQLite file under this process's temp directory."""
        self.root.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            prefix=prefix, suffix=".sqlite3", dir=self.root, delete=False
        )
        handle.close()
        return Path(handle.name)

    def temp_file(self, name: str) -> Path:
        """A path under the process temp directory. The file is not created."""
        self.root.mkdir(parents=True, exist_ok=True)
        return self.root / name

    def retain_foreign_session(self, path: str) -> str:
        """Copy a scratch session that belongs to another process into this one.

        User-chosen session files are returned unchanged. The copy lets the
        parent process delete its temp directory without taking the file the
        child was launched to open.
        """
        src = Path(path)
        if not src.is_file() or self.contains(src) or not _is_runtime_session_file(src):
            return path
        dest = Path(self.session_copy_path())
        shutil.copy2(src, dest)
        return str(dest)


def current_runtime() -> SessionRuntime:
    """The process runtime, created on first use."""
    global _current, _atexit_armed
    if _current is None or _current._closed:
        _current = SessionRuntime.start()
        if not _atexit_armed:
            atexit.register(_close_current)
            _atexit_armed = True
    return _current


def install_runtime() -> SessionRuntime:
    """Create the process runtime during application startup."""
    return current_runtime()


def network_allowed() -> bool:
    """False when offline mode is set. The machine policy wins over the environment."""
    return not _truthy(_configured("MOLMANAGER_OFFLINE"))


def sql_writes_allowed() -> bool:
    """False when SQL writes are disabled. The machine policy wins over the environment."""
    return _flag(_configured("MOLMANAGER_SQL_WRITES"), True)


def require_tool(executable: str, purpose: str) -> None:
    """Allow *executable* to start, then record the launch.

    Unset ``MOLMANAGER_TOOL_ALLOWLIST`` allows every program. Set it to a
    comma-separated list of file names or full paths, or to a text file of one
    name per line. Unset ``MOLMANAGER_TOOL_DIGESTS`` skips hashing. Set it to a
    text file of ``sha256`` and a file name or path. A configured pin file that
    is missing, or a file whose digest differs, refuses the launch.
    """
    label = Path(executable).name or str(executable).strip() or purpose
    if not _allowlist_permits(executable):
        audit("tool-denied", f"{purpose} {label}")
        raise ToolDenied(
            f"{label} is not in MOLMANAGER_TOOL_ALLOWLIST, so {purpose} was not started."
        )
    problem = _digest_problem(executable)
    if problem:
        audit("tool-denied", f"{purpose} {label}")
        raise ToolDenied(problem)
    audit("tool-launch", f"{purpose} {label}")


def require_network(purpose: str) -> None:
    """Raise :class:`NetworkDisabled` when offline mode is set."""
    if network_allowed():
        return
    audit("network-denied", purpose)
    raise NetworkDisabled(purpose)


def audit(event: str, detail: str = "") -> None:
    """Append one line to the user audit log. *detail* must not contain structures."""
    stamp = datetime.now().isoformat(timespec="seconds")
    line = f"{stamp} {event}"
    if detail:
        line = f"{line} {detail}"
    try:
        folder = default_log_dir()
        folder.mkdir(parents=True, exist_ok=True)
        with (folder / "audit.log").open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError as exc:
        logger.warning("Could not append the audit log (%s)", exc)


def _close_current() -> None:
    if _current is not None:
        _current.close()


def machine_policy_path() -> Path:
    """File IT can deploy. A key in this file wins over the process environment."""
    if sys.platform == "win32":
        base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        return Path(base) / "MolManager" / "policy.txt"
    if sys.platform == "darwin":
        return Path("/Library/Application Support/MolManager/policy.txt")
    return Path("/etc/molmanager/policy.txt")


def _policy_values() -> dict[str, str]:
    path = machine_policy_path()
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    values: dict[str, str] = {}
    for line in lines:
        body = line.split("#", 1)[0].strip()
        if not body or "=" not in body:
            continue
        key, _, value = body.partition("=")
        key = key.strip()
        if key.startswith("MOLMANAGER_"):
            values[key] = value.strip()
    return values


def _configured(name: str) -> str:
    """Policy value when the key is present, otherwise the environment."""
    forced = policy_value(name)
    if forced is not None:
        return forced
    return (os.environ.get(name) or "").strip()


def policy_value(name: str) -> str | None:
    """Value from the machine policy file, or ``None`` when *name* is absent.

    An empty string means the key is present and explicitly blank. Callers that
    fall back to QSettings must treat ``None`` and ``""`` differently.
    """
    values = _policy_values()
    if name not in values:
        return None
    return values[name]


def _truthy(raw: str) -> bool:
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _flag(raw: str, default: bool) -> bool:
    text = raw.strip().lower()
    if not text:
        return default
    if text in ("0", "false", "no", "off"):
        return False
    if text in ("1", "true", "yes", "on"):
        return True
    return default


def _name_key(text: str) -> str:
    return os.path.normcase(text.strip())


def _allowlist_tokens() -> list[str] | None:
    """``None`` when no allowlist is configured. An empty list denies every tool."""
    raw = _configured("MOLMANAGER_TOOL_ALLOWLIST")
    if not raw:
        return None
    path = Path(raw)
    if path.is_file():
        tokens: list[str] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            item = line.split("#", 1)[0].strip()
            if item:
                tokens.append(item)
        return tokens
    return [part.strip() for part in raw.split(",") if part.strip()]


def _allowlist_permits(executable: str) -> bool:
    tokens = _allowlist_tokens()
    if tokens is None:
        return True
    name = _name_key(Path(executable).name)
    resolved = _existing_file(executable)
    for token in tokens:
        if _name_key(Path(token).name) == name or _name_key(token) == name:
            return True
        if resolved is not None and _same_file(token, resolved):
            return True
    return False


def _digest_problem(executable: str) -> str | None:
    raw = _configured("MOLMANAGER_TOOL_DIGESTS")
    if not raw:
        return None
    pin_path = Path(raw)
    if not pin_path.is_file():
        return "MOLMANAGER_TOOL_DIGESTS is set, but that file was not found."
    pins = _parse_digest_file(pin_path)
    path = _existing_file(executable)
    label = Path(executable).name or executable
    if path is None:
        return f"{label} is not an existing file, so its digest cannot be checked."
    digest = _file_sha256(path)
    allowed = pins.get(_name_key(path.name), set()) | pins.get(_name_key(str(path)), set())
    if digest in allowed:
        return None
    return f"{path.name} does not match MOLMANAGER_TOOL_DIGESTS, so it was not started."


def _parse_digest_file(path: Path) -> dict[str, set[str]]:
    pins: dict[str, set[str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.split("#", 1)[0].strip()
        if not text:
            continue
        digest, _, name = text.partition(" ")
        digest = digest.strip().lower()
        name = name.strip()
        if len(digest) != 64 or not name:
            continue
        pins.setdefault(_name_key(name), set()).add(digest)
        pins.setdefault(_name_key(Path(name).name), set()).add(digest)
    return pins


def _existing_file(executable: str) -> Path | None:
    candidate = Path(executable)
    if candidate.is_file():
        return candidate
    return None


def _same_file(token: str, resolved: Path) -> bool:
    other = Path(token)
    if not other.is_file():
        return _name_key(token) == _name_key(str(resolved))
    try:
        return other.resolve() == resolved.resolve()
    except OSError:
        return False


def _file_sha256(path: Path) -> str:
    try:
        stat = path.stat()
        key = (str(path.resolve()), int(stat.st_size), int(stat.st_mtime_ns))
    except OSError:
        key = None
    if key is not None:
        with _digest_lock:
            cached = _digest_cache.get(key)
        if cached is not None:
            return cached
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    text = digest.hexdigest()
    if key is not None:
        with _digest_lock:
            _digest_cache[key] = text
    return text


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except (OSError, SystemError) as exc:
        # Windows error 5: the process exists but this user cannot signal it.
        # A missing process can also surface as SystemError from os.kill.
        if getattr(exc, "winerror", None) == 5:
            return True
        return False
    return True


def _sweep_stale_runtime_dirs(*, keep: Path) -> None:
    """Remove temp directories left by processes that are no longer running."""
    root = Path(tempfile.gettempdir())
    keep_resolved = keep.resolve()
    for path in root.glob(f"{_DIR_PREFIX}*"):
        if not path.is_dir():
            continue
        try:
            if path.resolve() == keep_resolved:
                continue
        except OSError:
            continue
        match = _DIR_NAME.match(path.name)
        if match is None or _pid_alive(int(match.group(1))):
            continue
        shutil.rmtree(path, ignore_errors=True)


def _sweep_legacy_shared_temp() -> None:
    """Remove the old shared cache, plot shells, and scratch-session folder."""
    root = Path(tempfile.gettempdir())
    for suffix in ("", "-wal", "-shm"):
        with suppress(OSError):
            (root / f"{_LEGACY_CACHE}{suffix}").unlink(missing_ok=True)
    for path in root.glob(_LEGACY_PLOT_GLOB):
        with suppress(OSError):
            path.unlink(missing_ok=True)
    legacy_sessions = root / _LEGACY_SESSIONS
    if legacy_sessions.is_dir():
        shutil.rmtree(legacy_sessions, ignore_errors=True)


def _is_runtime_session_file(path: Path) -> bool:
    """True for a ``.cms`` written under a process runtime's ``sessions`` folder."""
    parts = path.resolve().parts
    if "sessions" not in parts:
        return False
    return any(part.startswith(_DIR_PREFIX) for part in parts)
