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

"""Qt WebEngine / Chromium process flags (must run before WebEngine loads)."""

from __future__ import annotations

import logging
import os
import sys
import threading

logger = logging.getLogger(__name__)

_QTWEBENGINE_CHROMIUM_FLAGS_ENV = "QTWEBENGINE_CHROMIUM_FLAGS"
_QUIET_LOG_LEVEL_FLAG = "--log-level=3"
_DISABLE_LOGGING_FLAG = "--disable-logging"
_PREWARM_VIEW = None
_STDERR_FILTER_INSTALLED = False
_STDERR_FILTER_THREAD: threading.Thread | None = None

# Chromium needs a real windowing surface. These platform plugins provide none.
_PLATFORMS_WITHOUT_WEBENGINE = frozenset({"offscreen", "minimal", "vnc"})


def webengine_views_supported() -> bool:
    """Whether a ``QWebEngineView`` can be constructed on the current platform plugin.

    Under ``QT_QPA_PLATFORM=offscreen`` (headless tests, CI) constructing one **aborts the
    process** instead of raising, so every lazy WebEngine bootstrap must ask first and take
    its no-web fallback. Without this the behavior depends on whether some earlier import
    pulled in ``QtWebEngineWidgets`` before ``QApplication`` existed.
    """
    plugin = (os.environ.get("QT_QPA_PLATFORM") or "").strip().lower()
    return plugin.split(":")[0] not in _PLATFORMS_WITHOUT_WEBENGINE


def chromium_gpu_stderr_is_noise(line: str) -> bool:
    """True for the harmless WebGL SharedImage / GLES spam Chromium writes to stderr."""
    low = line.lower()
    return (
        "doendsharedimageaccesschromium" in low
        or "bound texture is not a shared image" in low
        or "gles2_cmd_decoder" in low
        or "sharedimagemanager" in low
        or "non-existent mailbox" in low
        or "invalid mailbox" in low
    )


def filter_chromium_stderr_bytes(pending: bytes, chunk: bytes) -> tuple[bytes, bytes]:
    """Drop GPU-noise lines from *chunk*. Return ``(kept, new_pending)``."""
    pending = pending + chunk
    kept: list[bytes] = []
    while b"\n" in pending:
        line, pending = pending.split(b"\n", 1)
        text = line.decode("utf-8", errors="replace")
        if chromium_gpu_stderr_is_noise(text):
            continue
        kept.append(line + b"\n")
    return b"".join(kept), pending


def configure_qtwebengine_quiet_logs() -> str:
    """
    Hide Chromium GPU ERROR spam on stderr (SharedImage / GLES while rotating WebGL).

    Must run before ``QtWebEngineWidgets`` is imported. Leaves an existing
    ``--log-level=`` value alone so a user can still raise Chromium verbosity.
    The renderer still prints some GLES shared-image errors past those flags, so a
    stderr filter drops that one family of lines.
    """
    current = (os.environ.get(_QTWEBENGINE_CHROMIUM_FLAGS_ENV) or "").strip()
    parts = current.split()
    user_set_level = any(part.startswith("--log-level=") for part in parts)
    if not user_set_level:
        parts.append(_QUIET_LOG_LEVEL_FLAG)
    if _wants_quiet_chromium_logs(parts) and _DISABLE_LOGGING_FLAG not in parts:
        parts.append(_DISABLE_LOGGING_FLAG)
    flags = " ".join(parts)
    os.environ[_QTWEBENGINE_CHROMIUM_FLAGS_ENV] = flags
    if _wants_quiet_chromium_logs(parts):
        install_chromium_stderr_filter()
    return flags


def _wants_quiet_chromium_logs(parts: list[str]) -> bool:
    """False when the user asked Chromium to keep logging."""
    level: int | None = None
    for part in parts:
        if part == "--enable-logging" or part.startswith("--enable-logging="):
            return False
        if not part.startswith("--log-level="):
            continue
        try:
            level = int(part.split("=", 1)[1])
        except ValueError:
            return False
    return level is None or level >= 3


def install_chromium_stderr_filter() -> bool:
    """Retarget process stderr through a filter before Chromium inherits it.

    Chromium's renderer writes ``DoEndSharedImageAccessCHROMIUM`` with ``LOG(ERROR)``
    on its own stderr handle. ``--log-level`` does not reliably reach that process.
    Returns False when the filter is already installed, skipped under pytest, or stderr
    cannot be redirected.
    """
    global _STDERR_FILTER_INSTALLED, _STDERR_FILTER_THREAD
    if _STDERR_FILTER_INSTALLED or "pytest" in sys.modules:
        return False
    saved_fd: int | None = None
    read_fd: int | None = None
    write_fd: int | None = None
    redirected = False
    try:
        saved_fd = os.dup(2)
        read_fd, write_fd = os.pipe()
        os.set_inheritable(saved_fd, False)
        os.set_inheritable(read_fd, False)
        os.set_inheritable(write_fd, True)
        os.dup2(write_fd, 2)
        redirected = True
        os.close(write_fd)
        write_fd = None
        os.set_inheritable(2, True)
        _point_windows_stderr_at(2)
        thread = threading.Thread(
            target=_chromium_stderr_filter_loop,
            args=(read_fd, saved_fd),
            name="chromium-stderr-filter",
            daemon=True,
        )
        thread.start()
        _STDERR_FILTER_THREAD = thread
    except (OSError, RuntimeError):
        logger.debug("Chromium stderr filter was not installed", exc_info=True)
        if redirected and saved_fd is not None:
            try:
                os.dup2(saved_fd, 2)
                _point_windows_stderr_at(2)
            except OSError:
                logger.debug("Could not restore stderr after filter failure", exc_info=True)
        for fd in (read_fd, write_fd, saved_fd):
            if fd is None:
                continue
            try:
                os.close(fd)
            except OSError:
                pass
        return False
    _STDERR_FILTER_INSTALLED = True
    return True


def _point_windows_stderr_at(fd: int) -> None:
    """Point the Win32 standard-error handle at *fd* so Chromium children inherit the pipe."""
    if sys.platform != "win32":
        return
    import ctypes
    import msvcrt

    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.SetStdHandle.argtypes = [wintypes.DWORD, wintypes.HANDLE]
    kernel32.SetStdHandle.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
    # (DWORD)-12 is STD_ERROR_HANDLE.
    if not kernel32.SetStdHandle(wintypes.DWORD(0xFFFFFFF4), handle):
        raise OSError(ctypes.get_last_error(), "SetStdHandle(STD_ERROR_HANDLE) failed")
    inherit = wintypes.DWORD(0x00000001)
    kernel32.SetHandleInformation(handle, inherit, inherit)


def _chromium_stderr_filter_loop(read_fd: int, saved_fd: int) -> None:
    pending = b""
    try:
        while True:
            try:
                chunk = os.read(read_fd, 8192)
            except OSError:
                break
            if not chunk:
                break
            kept, pending = filter_chromium_stderr_bytes(pending, chunk)
            _write_all(saved_fd, kept)
        if pending and not chromium_gpu_stderr_is_noise(pending.decode("utf-8", errors="replace")):
            _write_all(saved_fd, pending)
    finally:
        for fd in (read_fd, saved_fd):
            try:
                os.close(fd)
            except OSError:
                pass


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        try:
            written = os.write(fd, view)
        except OSError:
            return
        if written <= 0:
            return
        view = view[written:]


def schedule_qtwebengine_prewarm(*, delay_ms: int = 0) -> None:
    """Start Chromium after the first GUI paint so later 3D views do not stall."""
    if "pytest" in sys.modules:
        return
    from PyQt5.QtCore import QTimer

    QTimer.singleShot(max(0, int(delay_ms)), prewarm_qtwebengine)


def prewarm_qtwebengine() -> None:
    """Create a hidden WebEngine view so the first protein canvas is not the Chromium cold start."""
    global _PREWARM_VIEW
    if _PREWARM_VIEW is not None or "pytest" in sys.modules:
        return
    try:
        from PyQt5.QtCore import Qt
        from PyQt5.QtWebEngineWidgets import QWebEngineView
        from PyQt5.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            return
        view = QWebEngineView()
        view.setAttribute(Qt.WA_DontShowOnScreen, True)
        view.resize(2, 2)
        view.setHtml("<!DOCTYPE html><html><body></body></html>")
        _PREWARM_VIEW = view
        app.aboutToQuit.connect(_release_qtwebengine_prewarm)
    except Exception:
        logger.debug("Qt WebEngine prewarm skipped", exc_info=True)


def _release_qtwebengine_prewarm() -> None:
    global _PREWARM_VIEW
    view = _PREWARM_VIEW
    _PREWARM_VIEW = None
    if view is None:
        return
    try:
        view.deleteLater()
    except RuntimeError:
        pass


def apply_viewer_webengine_settings(settings) -> None:
    """JavaScript on. Remote URLs follow ``MOLMANAGER_OFFLINE``."""
    from PyQt5.QtWebEngineWidgets import QWebEngineSettings

    from .session_runtime import network_allowed

    settings.setAttribute(QWebEngineSettings.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessFileUrls, True)
    settings.setAttribute(QWebEngineSettings.LocalContentCanAccessRemoteUrls, network_allowed())


def refuse_remote_viewer_script() -> None:
    """Raise when a missing local 3Dmol bundle would be loaded from the network."""
    from .session_runtime import network_allowed

    if network_allowed():
        return
    raise RuntimeError(
        "The bundled 3D viewer is missing and MOLMANAGER_OFFLINE is set, "
        "so the viewer will not load a script from the network."
    )
