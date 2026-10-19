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

"""Qt WebEngine Chromium flag helpers."""

from __future__ import annotations

import pytest

from molmanager.platform_support.qt_webengine_flags import (
    configure_qtwebengine_quiet_logs,
    filter_chromium_stderr_bytes,
    install_chromium_stderr_filter,
    webengine_views_supported,
)
from molmanager.ui.mol_viewer_3d import _js_console_is_benign


def test_configure_qtwebengine_quiet_logs_sets_log_level(monkeypatch):
    monkeypatch.delenv("QTWEBENGINE_CHROMIUM_FLAGS", raising=False)
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=3" in flags
    assert "--disable-logging" in flags
    assert flags == configure_qtwebengine_quiet_logs()


def test_configure_qtwebengine_quiet_logs_keeps_user_log_level(monkeypatch):
    monkeypatch.setenv("QTWEBENGINE_CHROMIUM_FLAGS", "--enable-gpu --log-level=0")
    flags = configure_qtwebengine_quiet_logs()
    assert "--log-level=0" in flags
    assert "--disable-logging" not in flags
    assert flags.count("--log-level=") == 1


def test_stderr_filter_drops_shared_image_gpu_noise():
    noise = (
        b"[35652:13152:1019/002531.244:ERROR:gles2_cmd_decoder.cc(18988)] "
        b"[.RendererMainThread-000001776ED40530]GL ERROR :GL_INVALID_OPERATION : "
        b"DoEndSharedImageAccessCHROMIUM: bound texture is not a shared image\n"
    )
    real = b"[1:2:0101/000000.000:ERROR:net.cc(10)] connection reset\n"
    kept, pending = filter_chromium_stderr_bytes(b"", noise[:40])
    assert kept == b""
    assert pending
    kept, pending = filter_chromium_stderr_bytes(pending, noise[40:] + real)
    assert kept == real
    assert pending == b""
    kept, pending = filter_chromium_stderr_bytes(b"", real)
    assert kept == real


def test_stderr_filter_is_not_installed_under_pytest():
    assert install_chromium_stderr_filter() is False


def test_installed_stderr_filter_drops_gpu_noise():
    """The live redirect drops the renderer line and keeps everything else."""
    import subprocess
    import sys
    from pathlib import Path

    import molmanager

    root = Path(molmanager.__file__).resolve().parents[1]
    script = r"""
import os
import sys

from molmanager.platform_support import qt_webengine_flags

assert qt_webengine_flags.install_chromium_stderr_filter()
noise = (
    b"[35652:13152:1019/002531.244:ERROR:gles2_cmd_decoder.cc(18988)] "
    b"GL ERROR :GL_INVALID_OPERATION : DoEndSharedImageAccessCHROMIUM: "
    b"bound texture is not a shared image\n"
)
os.write(2, noise)
os.write(2, b"kept-line\n")
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_char_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    handle = kernel32.GetStdHandle(wintypes.DWORD(0xFFFFFFF4))
    written = wintypes.DWORD()
    kernel32.WriteFile(handle, noise, len(noise), ctypes.byref(written), None)
    kernel32.WriteFile(handle, b"kept-win32\n", len(b"kept-win32\n"), ctypes.byref(written), None)
os.close(2)
thread = qt_webengine_flags._STDERR_FILTER_THREAD
assert thread is not None
thread.join(timeout=2)
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=root,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    err = proc.stderr
    assert b"kept-line" in err
    assert b"DoEndSharedImageAccessCHROMIUM" not in err
    assert b"gles2_cmd_decoder" not in err
    if sys.platform == "win32":
        assert b"kept-win32" in err


def test_schedule_qtwebengine_prewarm_skips_pytest():
    from molmanager.platform_support import qt_webengine_flags

    qt_webengine_flags.schedule_qtwebengine_prewarm()
    qt_webengine_flags.prewarm_qtwebengine()
    assert qt_webengine_flags._PREWARM_VIEW is None


@pytest.mark.parametrize(
    ("plugin", "supported"),
    [
        ("offscreen", False),
        ("minimal", False),
        ("vnc", False),
        ("offscreen:enable_fonts", False),
        ("windows", True),
        ("xcb", True),
        ("", True),
    ],
)
def test_webengine_views_supported_per_platform_plugin(monkeypatch, plugin, supported):
    """Constructing a WebEngine page aborts the process on surface-less plugins."""
    monkeypatch.setenv("QT_QPA_PLATFORM", plugin)
    assert webengine_views_supported() is supported


def test_viewer_skips_webengine_under_offscreen(qapp, monkeypatch):  # noqa: ARG001
    """The 3D viewer must fall back instead of building a page the platform cannot host."""
    from rdkit import Chem

    from molmanager.ui.mol_viewer_3d import Molecule3DViewerWidget, prepare_mol_2d

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    mol = prepare_mol_2d(Chem.MolFromSmiles("CCO"))
    viewer = Molecule3DViewerWidget(mol, None, window_title="View in 2D", flat=True)
    try:
        assert viewer._standalone_web is None
    finally:
        viewer.deleteLater()


def test_interactive_plot_skips_webengine_under_offscreen(qapp, monkeypatch):  # noqa: ARG001
    """The embedded plot must fall back instead of building a page the platform cannot host."""
    from molmanager.ui.plotly_interactive_view import PlotlyInteractiveView

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    view = PlotlyInteractiveView()
    try:
        assert view.web is None
        assert view._web_channel is None
        assert view._web_ready is False
    finally:
        view.deleteLater()


def test_no_module_scope_webengine_imports():
    """WebEngine must only be imported inside functions, behind ``webengine_views_supported``.

    A module-scope import settles WebEngine's initialization order for the whole process, which
    decides whether a later unguarded view construction raises ``ImportError`` or aborts. That is
    what let a plot widget kill the test suite from an unrelated test.
    """
    import ast
    from pathlib import Path

    import molmanager

    package_root = Path(molmanager.__file__).parent
    offenders: list[str] = []
    for path in sorted(package_root.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)) or node.col_offset != 0:
                continue
            names = [alias.name for alias in node.names]
            module = getattr(node, "module", None) or ""
            if "QtWebEngine" in module or any("QtWebEngine" in name for name in names):
                offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], f"import QtWebEngine inside a guarded function instead: {offenders}"


def test_js_console_filters_shared_image_gpu_noise():
    assert _js_console_is_benign(
        "GL ERROR :GL_INVALID_OPERATION : DoEndSharedImageAccessCHROMIUM: "
        "bound texture is not a shared image"
    )
    assert _js_console_is_benign(
        "SharedImageManager::ProduceGLTexture: Trying to produce a representation "
        "from a non-existent mailbox."
    )
    assert _js_console_is_benign(
        "[Violation] Added non-passive event listener to a scroll-blocking 'wheel' event"
    )
    assert not _js_console_is_benign("Uncaught TypeError: Cannot read property 'x' of undefined")
