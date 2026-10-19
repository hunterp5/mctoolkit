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

import logging
import os
import sys

from .platform_support.windows_console import ensure_stdio, hide_owned_windows_console

ensure_stdio()

from .platform_support.qt_webengine_flags import configure_qtwebengine_quiet_logs

configure_qtwebengine_quiet_logs()

from PyQt5.QtCore import QTimer  # noqa: E402
from PyQt5.QtWidgets import QApplication  # noqa: E402

logger = logging.getLogger(__name__)

from .platform_support.app_logging import configure_app_logging, install_crash_excepthook  # noqa: E402
from .platform_support.rdkit_runtime_setup import configure_rdkit_for_desktop_app  # noqa: E402
from .table.open_messages import (  # noqa: E402
    message_for_read_failure,
    message_for_session_read_failure,
    no_path_message,
)
from .ui.main_window import ChemistryWorkspaceWindow  # noqa: E402
from .ui.theme import bootstrap_application_gui  # noqa: E402


def _configure_logging() -> None:
    """Console + rotating file logging; install crash dialog with log path."""
    log_path = configure_app_logging()
    install_crash_excepthook(log_path=log_path)


def _preload_qt_webengine() -> None:
    """Import QtWebEngine *before* ``QApplication`` — required for Chromium/QtWebEngineProcess on Windows."""
    configure_qtwebengine_quiet_logs()
    try:
        import PyQt5.QtWebEngineWidgets  # noqa: F401 — side effect: registers WebEngine with Qt
    except Exception as e:
        logger.warning(
            "QtWebEngine could not be loaded (%s: %s). The in-app 3D viewer will fall back to the system browser "
            "unless PyQtWebEngine is installed and matches your PyQt5 version.",
            type(e).__name__,
            e,
        )


def _argv_for_qt(argv: list[str]) -> tuple[list[str], str | None, str | None, list[str]]:
    """Remove MolManager-only flags so ``QApplication`` does not see unknown options.

    The last item lists ``"session"`` and/or ``"file"`` when that flag was given
    with no path.
    """
    out: list[str] = [argv[0]] if argv else []
    load_session: str | None = None
    open_file: str | None = None
    missing: list[str] = []
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == "--load-session":
            if i + 1 < len(argv):
                load_session = argv[i + 1]
                i += 2
                continue
            missing.append("session")
            i += 1
            continue
        if a in ("--open", "-o"):
            if i + 1 < len(argv):
                open_file = argv[i + 1]
                i += 2
                continue
            missing.append("file")
            i += 1
            continue
        out.append(a)
        i += 1
    return out, load_session, open_file, missing


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv

    hide_owned_windows_console()
    _configure_logging()
    try:
        configure_rdkit_for_desktop_app()
    except RuntimeError as exc:
        logger.error("%s", exc)
        print(exc, file=sys.stderr)
        return 1

    if "--demo-table-model" in argv:
        from .table_model_demo import main as demo_main

        return demo_main()

    _preload_qt_webengine()
    argv_qt, load_session, open_file, missing_open = _argv_for_qt(list(argv))
    app = QApplication(argv_qt)
    bootstrap_application_gui(app)

    w = ChemistryWorkspaceWindow()
    w.show()
    from .platform_support.qt_webengine_flags import schedule_qtwebengine_prewarm

    schedule_qtwebengine_prewarm()
    if "session" in missing_open:
        QTimer.singleShot(
            0,
            lambda: w._warn_could_not_open("Open Session", no_path_message(kind="session")),
        )
    if "file" in missing_open:
        QTimer.singleShot(
            0,
            lambda: w._warn_could_not_open("Open File", no_path_message(kind="file")),
        )
    if load_session:
        try:
            p = load_session.lower()
            if p.endswith(".cms") or p.endswith(".json"):
                w.apply_saved_session_from_file(load_session)
            else:
                w.load_session_csv(load_session)
        except Exception as e:
            logger.warning("Startup session load failed (%s): %s", load_session, e, exc_info=True)
            w._warn_could_not_open(
                "Open Session", message_for_session_read_failure(load_session, e)
            )
    if open_file:
        path = os.path.abspath(open_file)

        def _do_open() -> None:
            try:
                w.load_file(path)
            except Exception as e:
                logger.warning("Startup file load failed (%s): %s", path, e, exc_info=True)
                w._warn_could_not_open("Open File", message_for_read_failure(path, e))

        QTimer.singleShot(0, _do_open)
    code = app.exec_()
    try:
        from .workers.process_pool_utils import reap_after_gui_exit
        from .workers.render2d_pool import release_render2d_process_pool

        release_render2d_process_pool(kill_workers=True)
        reap_after_gui_exit(code)
    except Exception:
        logger.debug("post-GUI process reap failed", exc_info=True)
    return code
