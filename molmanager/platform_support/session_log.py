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

"""In-memory session log shared by the Log window, Python logging, and UI tools."""

from __future__ import annotations

import logging
import re
import threading
import time
import traceback
from collections import deque
from dataclasses import dataclass

_MAX_ENTRIES = 10_000
_READY_STATUS = frozenset({"Ready", "Ready."})
_PROGRESS_BUCKET = 10
_STATUS_HEARTBEAT_S = 2.0
_EM_PROGRESS_RE = re.compile(r"—\s*(?P<done>[\d,]+)/(?P<total>[\d,]+)\s*\((?P<pct>\d+)%\)\s*$")
_BARE_PCT_RE = re.compile(r"\((?P<pct>\d+)%\)\s*$")
_COUNT_PROGRESS_RE = re.compile(r"\((?P<done>[\d,]+)/(?P<total>[\d,]+)\)\s*$")


@dataclass(frozen=True)
class SessionLogEntry:
    """One line in the session log (UI, status, or Python logging)."""

    seq: int
    created: float
    levelno: int
    levelname: str
    logger_name: str
    message: str
    source: str


class SessionLogBuffer:
    """Thread-safe ring buffer of session log entries."""

    def __init__(self, maxlen: int = _MAX_ENTRIES) -> None:
        self._lock = threading.Lock()
        self._entries: deque[SessionLogEntry] = deque(maxlen=max(1, int(maxlen)))
        self._seq = 0
        self._generation = 0

    def add(
        self,
        *,
        levelno: int,
        logger_name: str,
        message: str,
        source: str,
        created: float | None = None,
        levelname: str | None = None,
    ) -> SessionLogEntry:
        text = str(message or "").rstrip()
        name = str(logger_name or "molmanager")
        src = str(source or "logging")
        lvl = int(levelno)
        with self._lock:
            self._seq += 1
            entry = SessionLogEntry(
                seq=self._seq,
                created=float(created if created is not None else time.time()),
                levelno=lvl,
                levelname=str(levelname or logging.getLevelName(lvl)),
                logger_name=name,
                message=text,
                source=src,
            )
            self._entries.append(entry)
            return entry

    def snapshot(self, *, since_seq: int = 0) -> tuple[list[SessionLogEntry], int, int]:
        """Return ``(entries after since_seq, latest seq, generation)``."""
        with self._lock:
            items = [e for e in self._entries if e.seq > int(since_seq)]
            return items, self._seq, self._generation

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._generation += 1

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)


class SessionLogHandler(logging.Handler):
    """Root logging handler that mirrors records into the session buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        if getattr(record, "mm_session_skip", False):
            return
        try:
            msg = record.getMessage()
            if record.exc_info:
                # Handler has no formatException; mirror logging.Formatter behavior.
                msg = f"{msg}\n{''.join(traceback.format_exception(*record.exc_info)).rstrip()}"
            session_log_buffer().add(
                levelno=int(record.levelno),
                levelname=str(record.levelname),
                logger_name=str(record.name),
                message=msg,
                source="logging",
                created=float(record.created),
            )
        except Exception:  # noqa: BLE001 — logging.Handler.emit contract
            self.handleError(record)


_buffer: SessionLogBuffer | None = None
_handler: SessionLogHandler | None = None
_buffer_lock = threading.Lock()


def session_log_buffer() -> SessionLogBuffer:
    """Process-wide session log; created on first use."""
    global _buffer
    with _buffer_lock:
        if _buffer is None:
            _buffer = SessionLogBuffer()
        return _buffer


def ensure_session_log_handler() -> SessionLogHandler:
    """Attach a single ``SessionLogHandler`` to the root logger."""
    global _handler
    root = logging.getLogger()
    if _handler is not None and _handler in root.handlers:
        return _handler
    existing = next((h for h in root.handlers if isinstance(h, SessionLogHandler)), None)
    if existing is not None:
        _handler = existing
        return existing
    handler = SessionLogHandler()
    handler.setLevel(logging.DEBUG)
    root.addHandler(handler)
    _handler = handler
    return handler


def record_ui_log(
    message: str,
    *,
    level: int = logging.INFO,
    name: str = "molmanager.ui",
) -> None:
    """Record a user-visible tool line and mirror it to Python logging."""
    text = (message or "").rstrip()
    if not text:
        return
    session_log_buffer().add(
        levelno=int(level),
        logger_name=str(name or "molmanager.ui"),
        message=text,
        source="ui",
    )
    logging.getLogger(name).log(int(level), "%s", text, extra={"mm_session_skip": True})


def _parse_int(raw: str) -> int:
    return int((raw or "0").replace(",", ""))


def progress_head_and_pct(text: str) -> tuple[str, int | None]:
    """Stable status prefix and 0–100 percent when the line is a progress update."""
    t = (text or "").strip()
    match = _EM_PROGRESS_RE.search(t)
    if match is not None:
        return t[: match.start()].rstrip(" —"), int(match.group("pct"))
    match = _BARE_PCT_RE.search(t)
    if match is not None:
        return t[: match.start()].rstrip(), int(match.group("pct"))
    match = _COUNT_PROGRESS_RE.search(t)
    if match is not None:
        done = _parse_int(match.group("done"))
        total = _parse_int(match.group("total")) or 1
        pct = min(100, int(100 * done / total))
        return t[: match.start()].rstrip(), pct
    return t, None


def should_record_status_text(
    text: str,
    last_recorded: str | None,
    *,
    elapsed_s: float | None = None,
) -> bool:
    """
    True when a status-bar string is worth keeping in the session log.

    Skips idle Ready text and consecutive duplicates. Progress lines record on
    first sight, 0%, 100%, a change of tool/phase, every 10% bucket, and a
    heartbeat so a long job is not silent between buckets.
    """
    t = (text or "").strip()
    if not t or t in _READY_STATUS:
        return False
    if last_recorded is not None and t == last_recorded:
        return False
    head, pct = progress_head_and_pct(t)
    if pct is None:
        return True
    if last_recorded is None or pct in (0, 100):
        return True
    last_head, last_pct = progress_head_and_pct(last_recorded)
    if last_pct is None or head != last_head:
        return True
    if pct // _PROGRESS_BUCKET != last_pct // _PROGRESS_BUCKET:
        return True
    if elapsed_s is not None and elapsed_s >= _STATUS_HEARTBEAT_S:
        return True
    return False


def record_status_log(
    message: str,
    last_recorded: str | None,
    *,
    elapsed_s: float | None = None,
) -> str | None:
    """Append a status-bar line when ``should_record_status_text``; return the new last text."""
    t = (message or "").strip()
    if not should_record_status_text(t, last_recorded, elapsed_s=elapsed_s):
        return last_recorded
    session_log_buffer().add(
        levelno=logging.INFO,
        logger_name="molmanager.ui.status",
        message=t,
        source="status",
    )
    return t


def short_logger_name(name: str) -> str:
    """Drop the ``molmanager.`` prefix for compact Log-window labels."""
    raw = str(name or "")
    if raw.startswith("molmanager."):
        return raw[len("molmanager.") :]
    return raw or "app"


def format_session_log_line(entry: SessionLogEntry) -> str:
    """Single-line display form used by the Log window and Copy."""
    stamp = time.strftime("%H:%M:%S", time.localtime(entry.created))
    level = (entry.levelname or "INFO").ljust(7)
    source = short_logger_name(entry.logger_name)
    return f"{stamp}  {level}  {source}  {entry.message}"
