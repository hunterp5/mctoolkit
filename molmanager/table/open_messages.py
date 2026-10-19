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

"""User-facing messages for missing, unreadable, and damaged opens."""

from __future__ import annotations

import errno
import os

from .table_file_formats import logical_suffix

_FORMAT_LABELS = {
    ".sdf": "SDF",
    ".sd": "SDF",
    ".mol": "Molfile",
    ".mol2": "MOL2",
    ".ml2": "MOL2",
    ".smi": "SMILES",
    ".smiles": "SMILES",
    ".csv": "CSV",
    ".tsv": "TSV",
    ".txt": "text table",
    ".xlsx": "Excel workbook",
    ".tdt": "TDT",
    ".pdb": "PDB",
    ".pdbqt": "PDBQT",
    ".rxn": "reaction file",
    ".rdf": "reaction file",
}


def _quoted_name(path: str, *, fallback: str) -> str:
    text = str(path or "").strip()
    name = os.path.basename(text)
    return name or text or fallback


def _could_not_open(path: str, reason: str, *, fallback: str = "file") -> str:
    return f'Could not open "{_quoted_name(path, fallback=fallback)}". {reason}'


def no_path_message(*, kind: str) -> str:
    """Flag was present on the command line with no path after it."""
    label = "session" if kind == "session" else "file"
    return f"Could not open a {label}. No path was given."


def missing_path_message(path: str) -> str:
    return _could_not_open(path, "That file does not exist.")


def folder_path_message(path: str) -> str:
    return _could_not_open(path, "That path is a folder.")


def unreadable_path_message(path: str) -> str:
    return _could_not_open(path, "MolManager cannot read that file.")


def not_a_session_message(path: str) -> str:
    return _could_not_open(
        path,
        "It is not a MolManager session (expected .cms, version 1–2).",
        fallback="session",
    )


def damaged_session_message(path: str) -> str:
    return _could_not_open(path, "That session file is damaged.", fallback="session")


def damaged_file_message(path: str) -> str:
    """Format-specific line for a file that exists but could not be parsed."""
    label = _FORMAT_LABELS.get(logical_suffix(path))
    if label:
        return _could_not_open(path, f"That file is not a readable {label}, or it is damaged.")
    return _could_not_open(path, "That file is damaged or is not a supported format.")


def preflight_open_path(path: str | None) -> str | None:
    """Return a message when *path* cannot be opened, else ``None``.

    Call this on the GUI thread before clearing the workspace. A readable file
    can still fail later if its contents are damaged.
    """
    if path is None or not str(path).strip():
        return no_path_message(kind="file")
    text = str(path)
    if not os.path.exists(text):
        return missing_path_message(text)
    if os.path.isdir(text):
        return folder_path_message(text)
    if not os.access(text, os.R_OK):
        return unreadable_path_message(text)
    return None


def message_for_os_error(path: str, exc: BaseException) -> str | None:
    """Map a filesystem error to an open message. ``None`` when *exc* is not one."""
    if isinstance(exc, FileNotFoundError):
        return missing_path_message(path)
    if isinstance(exc, IsADirectoryError):
        return folder_path_message(path)
    if isinstance(exc, PermissionError):
        return unreadable_path_message(path)
    if isinstance(exc, OSError):
        err = getattr(exc, "errno", None)
        if err == errno.ENOENT:
            return missing_path_message(path)
        if err in (errno.EACCES, errno.EPERM):
            return unreadable_path_message(path)
        if err == errno.EISDIR:
            return folder_path_message(path)
    return None


def message_for_read_failure(path: str, exc: BaseException) -> str:
    """Message for a table-file read that raised *exc*."""
    os_msg = message_for_os_error(path, exc)
    if os_msg is not None:
        return os_msg
    return damaged_file_message(path)


def message_for_session_read_failure(path: str, exc: BaseException) -> str:
    """Message for a session file that could not be decoded."""
    os_msg = message_for_os_error(path, exc)
    if os_msg is not None:
        return os_msg
    text = str(exc).lower()
    if (
        "unsupported session" in text
        or "missing session.cms" in text
        or "session root must" in text
    ):
        return not_a_session_message(path)
    return damaged_session_message(path)
