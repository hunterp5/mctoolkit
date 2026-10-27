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

"""The published core bundle installs a hashed lock, not floating ranges."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)")
PIN_RE = re.compile(r"^([A-Za-z0-9_.-]+)==")


def _pep503(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _direct_requirements(text: str) -> list[str]:
    names: list[str] = []
    for line in text.splitlines():
        raw = line.split("#", 1)[0].strip()
        if not raw or raw.startswith("-"):
            continue
        match = NAME_RE.match(raw)
        assert match is not None
        names.append(_pep503(match.group(1)))
    return names


def _lock_blocks(text: str) -> dict[str, str]:
    blocks: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in text.splitlines():
        match = PIN_RE.match(line)
        if match:
            if current is not None:
                blocks[_pep503(current)] = "\n".join(buf)
            current = match.group(1)
            buf = [line]
        elif current is not None:
            buf.append(line)
    if current is not None:
        blocks[_pep503(current)] = "\n".join(buf)
    return blocks


def test_core_lock_pins_every_direct_requirement_with_a_hash() -> None:
    direct = _direct_requirements((ROOT / "requirements-core.txt").read_text(encoding="utf-8"))
    blocks = _lock_blocks((ROOT / "requirements-core.lock").read_text(encoding="utf-8"))
    assert direct
    missing = [name for name in direct if name not in blocks]
    assert missing == []
    for name, block in blocks.items():
        assert block.startswith(f"{name}=="), name
        assert "--hash=sha256:" in block, name
    assert blocks["pyqt5-qt5"].startswith("pyqt5-qt5==5.15.2")
    assert blocks["pyqtwebengine-qt5"].startswith("pyqtwebengine-qt5==5.15.2")


def test_package_workflow_installs_the_core_lock() -> None:
    workflow = (ROOT / ".github" / "workflows" / "package.yml").read_text(encoding="utf-8")
    assert workflow.count("pip install -r requirements-core.lock") == 2
    assert "pip install -r requirements-core.txt" not in workflow
