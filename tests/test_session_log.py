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

"""Session log buffer, status throttle, and logging handler."""

from __future__ import annotations

import logging

from molmanager.platform_support.session_log import (
    SessionLogHandler,
    ensure_session_log_handler,
    format_session_log_line,
    record_status_log,
    record_ui_log,
    session_log_buffer,
    should_record_status_text,
    short_logger_name,
)


def setup_function() -> None:
    session_log_buffer().clear()


def test_should_record_status_skips_ready_and_samples_progress():
    assert not should_record_status_text("Ready", None)
    assert not should_record_status_text("Ready.", None)
    assert not should_record_status_text("", None)
    start = "Protonate: collecting… — 0/10 (0%)"
    mid = "Protonate: collecting… — 5/10 (50%)"
    near = "Protonate: collecting… — 5/10 (52%)"
    done = "Protonate: collecting… — 10/10 (100%)"
    assert should_record_status_text(start, None)
    assert should_record_status_text(mid, start)
    assert not should_record_status_text(
        "Protonate: collecting… — 5/10 (51%)",
        mid,
    )
    assert should_record_status_text(near, mid, elapsed_s=2.0)
    assert should_record_status_text(done, mid)
    assert should_record_status_text(
        "Writing results… — 0/8 (0%)",
        done,
    )
    assert not should_record_status_text("Deleted 3 row(s).", "Deleted 3 row(s).")
    assert should_record_status_text("Deleted 3 row(s).", None)
    assert should_record_status_text("Writing results… (512/10,000)", None)
    assert not should_record_status_text(
        "Writing results… (600/10,000)",
        "Writing results… (512/10,000)",
    )
    assert should_record_status_text(
        "Writing results… (2,000/10,000)",
        "Writing results… (512/10,000)",
    )


def test_record_status_log_dedupes():
    last = record_status_log("Ready", None)
    assert last is None
    last = record_status_log("Cluster finished.", last)
    assert last == "Cluster finished."
    last = record_status_log("Cluster finished.", last)
    assert last == "Cluster finished."
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert [e.message for e in entries] == ["Cluster finished."]
    assert entries[0].source == "status"


def test_record_ui_log_and_python_logging():
    ensure_session_log_handler()
    record_ui_log("Starting PDBFixer", name="molmanager.ui.pdb_fixer")
    logging.getLogger("molmanager.workers.demo").warning("worker hiccup")
    entries, _seq, _gen = session_log_buffer().snapshot()
    messages = [e.message for e in entries]
    assert "Starting PDBFixer" in messages
    assert "worker hiccup" in messages
    ui = next(e for e in entries if e.message == "Starting PDBFixer")
    assert ui.source == "ui"
    log = next(e for e in entries if e.message == "worker hiccup")
    assert log.source == "logging"
    assert log.levelno == logging.WARNING


def test_session_log_handler_includes_exception_text():
    ensure_session_log_handler()
    session_log_buffer().clear()
    try:
        raise RuntimeError("chrome button gone")
    except RuntimeError:
        logging.getLogger("molmanager.ui.plot_dock_host").exception(
            "Failed to float released plot widget"
        )
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert entries
    assert "Failed to float released plot widget" in entries[-1].message
    assert "chrome button gone" in entries[-1].message
    assert "RuntimeError" in entries[-1].message


def test_record_ui_log_does_not_double_via_handler():
    ensure_session_log_handler()
    record_ui_log("once only")
    entries, _seq, _gen = session_log_buffer().snapshot()
    assert [e.message for e in entries].count("once only") == 1


def test_ensure_session_log_handler_is_idempotent():
    first = ensure_session_log_handler()
    second = ensure_session_log_handler()
    assert first is second
    root = logging.getLogger()
    assert sum(1 for h in root.handlers if isinstance(h, SessionLogHandler)) == 1


def test_short_name_and_format_line():
    assert short_logger_name("molmanager.ui.tools") == "ui.tools"
    assert short_logger_name("rdkit") == "rdkit"
    session_log_buffer().add(
        levelno=logging.INFO,
        logger_name="molmanager.ui.tools",
        message="hello",
        source="ui",
        created=1_700_000_000.0,
    )
    entries, _seq, _gen = session_log_buffer().snapshot()
    line = format_session_log_line(entries[-1])
    assert "INFO" in line
    assert "ui.tools" in line
    assert "hello" in line


def test_buffer_clear_bumps_generation():
    buf = session_log_buffer()
    buf.add(levelno=logging.INFO, logger_name="x", message="a", source="ui")
    _entries, _seq, gen1 = buf.snapshot()
    buf.clear()
    entries, _seq, gen2 = buf.snapshot()
    assert entries == []
    assert gen2 != gen1
