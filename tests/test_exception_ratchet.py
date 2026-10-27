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

"""Guard the silent-exception ruff allowlist against growth and stale paths."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RATCHET_PATH = ROOT / "ruff.exception-ratchet.toml"
ALLOWED_CODES = frozenset({"BLE001", "S110", "SIM105"})
# Frozen when the ratchet landed, then lowered to the current list. Never raise it.
EXCEPTION_RATCHET_MAX_FILES = 219

_MAX_RE = re.compile(r"^# ratchet-max-files = (\d+)\s*$", re.MULTILINE)
_ENTRY_RE = re.compile(r'^"([^"]+)" = \[([^\]]+)\]\s*$', re.MULTILINE)


def _load_allowlist() -> tuple[int, dict[str, tuple[str, ...]]]:
    text = RATCHET_PATH.read_text(encoding="utf-8")
    max_match = _MAX_RE.search(text)
    assert max_match is not None, f"missing ratchet-max-files in {RATCHET_PATH}"
    files: dict[str, tuple[str, ...]] = {}
    for path, raw_codes in _ENTRY_RE.findall(text):
        codes = tuple(code.strip().strip('"') for code in raw_codes.split(",") if code.strip())
        files[path] = codes
    return int(max_match.group(1)), files


def test_exception_ratchet_allowlist_is_frozen_or_shrinking():
    declared_max, files = _load_allowlist()
    assert declared_max == len(files)
    assert len(files) <= EXCEPTION_RATCHET_MAX_FILES
    for rel, codes in files.items():
        assert (ROOT / rel).is_file(), f"stale allowlist path: {rel}"
        assert codes, f"empty ignore list: {rel}"
        unexpected = set(codes) - ALLOWED_CODES
        assert not unexpected, f"{rel} ignores unsupported codes {sorted(unexpected)}"
