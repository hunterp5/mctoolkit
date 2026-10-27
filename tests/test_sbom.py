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

"""The release SBOM names MolManager and the installed libraries."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_sbom_names_the_application_and_a_library(tmp_path: Path) -> None:
    dest = tmp_path / "sbom.cdx.json"
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "write_sbom.py"), str(dest)])
    document = json.loads(dest.read_text(encoding="utf-8"))
    assert document["bomFormat"] == "CycloneDX"
    assert document["specVersion"] == "1.5"
    assert document["metadata"]["component"]["name"] == "MolManager"
    assert document["metadata"]["component"]["version"] == "0.1.0"
    names = {item["name"].lower() for item in document["components"]}
    assert "rdkit" in names
