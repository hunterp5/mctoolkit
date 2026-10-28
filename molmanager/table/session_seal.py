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

"""Encrypt a finished ``.cms`` SQLite file for the current OS user.

The working database is still written as SQLite. This wraps that file with
AES-GCM before it replaces the destination, and unwraps it into the process
temp directory on open. The 32-byte key lives in the user profile, protected
with Windows DPAPI on Windows and with mode ``0600`` elsewhere. A copy of the
``.cms`` without that key does not contain the chemistry.
"""

from __future__ import annotations

import contextlib
import os
import sys
import threading
from pathlib import Path
from typing import Any

SESSION_SEAL_MAGIC = b"MMC1"
_VERSION = 1
_NONCE_LEN = 12
_TAG_LEN = 16
_HEADER_LEN = 4 + 1 + _NONCE_LEN
_CHUNK = 1024 * 1024
_KEY_MAGIC = b"MMK1"
_SCHEME_RAW = 1
_SCHEME_DPAPI = 2
_KEY_LEN = 32

_key_lock = threading.Lock()


class SessionSealError(ValueError):
    """A ``.cms`` file could not be encrypted or decrypted."""


def is_sealed_session(path: str | os.PathLike[str]) -> bool:
    """True when *path* starts with the encrypted-session magic."""
    try:
        with open(path, "rb") as handle:
            return handle.read(4) == SESSION_SEAL_MAGIC
    except OSError:
        return False


def seal_sqlite_file(source: Path, dest: Path) -> None:
    """Encrypt the SQLite file at *source* onto *dest*. *source* is left in place."""
    key = load_or_create_session_key(create=True)
    _seal_with_key(source, dest, key)


def unseal_session_sqlite(source: Path) -> Path:
    """Decrypt *source* into this process's temp directory and return that path."""
    from ..platform_support.session_runtime import current_runtime

    key = load_or_create_session_key(create=False)
    dest = current_runtime().allocate_sqlite("session-plain-")
    try:
        _unseal_with_key(source, dest, key)
    except BaseException:
        _remove_sqlite(dest)
        raise
    return dest


def load_or_create_session_key(*, create: bool, scheme: int | None = None) -> bytes:
    """Return this user's session key, creating it on a save when it is missing."""
    path = _key_path()
    with _key_lock:
        if path.is_file():
            return _read_key(path)
        if not create:
            raise SessionSealError(
                "MolManager could not decrypt this session because this user account "
                "has no session key."
            )
        path.parent.mkdir(parents=True, exist_ok=True)
        key = os.urandom(_KEY_LEN)
        _write_key(path, key, scheme=scheme)
        return key


def _key_path() -> Path:
    from ..platform_support.session_runtime import session_key_directory

    return session_key_directory() / "session.key"


def _seal_with_key(source: Path, dest: Path, key: bytes) -> None:
    nonce = os.urandom(_NONCE_LEN)
    header = SESSION_SEAL_MAGIC + bytes([_VERSION]) + nonce
    encryptor = _cipher(key, nonce).encryptor()
    encryptor.authenticate_additional_data(header)
    partial = dest.with_name(dest.name + ".part")
    try:
        with source.open("rb") as incoming, partial.open("wb") as outgoing:
            outgoing.write(header)
            while True:
                chunk = incoming.read(_CHUNK)
                if not chunk:
                    break
                outgoing.write(encryptor.update(chunk))
            outgoing.write(encryptor.finalize())
            outgoing.write(encryptor.tag)
        os.replace(partial, dest)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def _unseal_with_key(source: Path, dest: Path, key: bytes) -> None:
    try:
        from cryptography.exceptions import InvalidTag
    except ImportError as exc:
        raise SessionSealError(
            "Encrypted sessions need the cryptography package. Install requirements-core.txt."
        ) from exc

    size = source.stat().st_size
    if size < _HEADER_LEN + _TAG_LEN:
        raise SessionSealError(
            "This session file is too small to be an encrypted MolManager session."
        )
    with source.open("rb") as incoming:
        header = incoming.read(_HEADER_LEN)
        if len(header) < _HEADER_LEN or header[:4] != SESSION_SEAL_MAGIC:
            raise SessionSealError("Not an encrypted MolManager session.")
        if header[4] != _VERSION:
            raise SessionSealError(f"Unsupported encrypted session version: {header[4]}.")
        nonce = header[5 : 5 + _NONCE_LEN]
        incoming.seek(size - _TAG_LEN)
        tag = incoming.read(_TAG_LEN)
        incoming.seek(_HEADER_LEN)
        decryptor = _cipher(key, nonce, tag).decryptor()
        decryptor.authenticate_additional_data(header)
        remaining = size - _HEADER_LEN - _TAG_LEN
        with dest.open("wb") as outgoing:
            while remaining:
                chunk = incoming.read(min(_CHUNK, remaining))
                if not chunk:
                    break
                remaining -= len(chunk)
                outgoing.write(decryptor.update(chunk))
            try:
                outgoing.write(decryptor.finalize())
            except InvalidTag:
                raise SessionSealError(
                    "MolManager could not decrypt this session. It was saved for a "
                    "different user account, or the session key has changed."
                ) from None


def _remove_sqlite(path: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        with contextlib.suppress(OSError):
            Path(str(path) + suffix).unlink(missing_ok=True)


def _cipher(key: bytes, nonce: bytes, tag: bytes | None = None) -> Any:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except ImportError as exc:
        raise SessionSealError(
            "Encrypted sessions need the cryptography package. Install requirements-core.txt."
        ) from exc
    mode = modes.GCM(nonce, tag) if tag is not None else modes.GCM(nonce)
    return Cipher(algorithms.AES(key), mode)


def _write_key(path: Path, key: bytes, *, scheme: int | None) -> None:
    chosen = _default_scheme() if scheme is None else scheme
    payload = _protect(key, chosen)
    blob = _KEY_MAGIC + bytes([chosen]) + payload
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    mode = 0o600 if sys.platform != "win32" else 0o666
    fd = os.open(path, flags, mode)
    try:
        view = memoryview(blob)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                raise OSError("Could not write the MolManager session key.")
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)
    if sys.platform != "win32":
        os.chmod(path, 0o600)


def _read_key(path: Path) -> bytes:
    blob = path.read_bytes()
    if len(blob) < 5 or blob[:4] != _KEY_MAGIC:
        raise SessionSealError("The MolManager session key file is not a session key.")
    scheme = blob[4]
    try:
        key = _unprotect(blob[5:], scheme)
    except OSError as exc:
        raise SessionSealError(
            "MolManager could not read the session key for this user account."
        ) from exc
    if len(key) != _KEY_LEN:
        raise SessionSealError("The MolManager session key has the wrong length.")
    return key


def _default_scheme() -> int:
    return _SCHEME_DPAPI if sys.platform == "win32" else _SCHEME_RAW


def _protect(key: bytes, scheme: int) -> bytes:
    if scheme == _SCHEME_RAW:
        return key
    if scheme == _SCHEME_DPAPI:
        return _dpapi(key, protect=True)
    raise SessionSealError(f"Unsupported session key scheme: {scheme}.")


def _unprotect(payload: bytes, scheme: int) -> bytes:
    if scheme == _SCHEME_RAW:
        return payload
    if scheme == _SCHEME_DPAPI:
        return _dpapi(payload, protect=False)
    raise SessionSealError(f"Unsupported session key scheme: {scheme}.")


def _dpapi(data: bytes, *, protect: bool) -> bytes:
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_byte)),
        ]

    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    blob_in = _Blob()
    buffer = ctypes.create_string_buffer(data, len(data))
    blob_in.cbData = len(data)
    blob_in.pbData = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
    blob_out = _Blob()
    fn = crypt32.CryptProtectData if protect else crypt32.CryptUnprotectData
    fn.argtypes = [
        ctypes.POINTER(_Blob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_Blob),
    ]
    fn.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(blob_in), None, None, None, None, 0x1, ctypes.byref(blob_out)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        kernel32.LocalFree(ctypes.cast(blob_out.pbData, ctypes.c_void_p))
