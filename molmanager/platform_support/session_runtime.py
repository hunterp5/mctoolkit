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
refuses SQL that modifies a database. Both default to today's behavior.
"""

from __future__ import annotations

import atexit
import logging
import os
import re
import shutil
import tempfile
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
    """False when ``MOLMANAGER_OFFLINE`` is set. Read on each call."""
    return not _env_truthy("MOLMANAGER_OFFLINE")


def sql_writes_allowed() -> bool:
    """False when ``MOLMANAGER_SQL_WRITES`` is ``0``. Default is allowed."""
    return _env_bool("MOLMANAGER_SQL_WRITES", True)


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


def _env_truthy(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in ("1", "true", "yes", "on")


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    return default


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if pid == os.getpid():
        return True
    try:
        os.kill(pid, 0)
    except PermissionError:
        return True
    except OSError as exc:
        # Windows error 5: the process exists but this user cannot signal it.
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
